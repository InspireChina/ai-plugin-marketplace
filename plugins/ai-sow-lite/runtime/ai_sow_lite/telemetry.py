"""Bounded, local observation only. No host discovery or business-state writes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat

from .contracts import canonical_json_bytes, schema_validator, strict_json_loads
from .project import atomic_bytes, fsync_directory, safe_path

MAX_FILES = 256
MAX_EVENTS = 10000
MAX_METRICS = 2000
MAX_BYTES = 8 * 1024 * 1024
MAX_EVENT_BYTES = 64 * 1024
AREA = '.ai-sow-lite/telemetry'


def _validate(definition, value):
    raw = canonical_json_bytes(value)
    if next(schema_validator('artifacts', definition).iter_errors(value), None):
        raise ValueError('TELEMETRY_INVALID')
    return raw


def _path(project, request_id, suffix=''):
    # Validate identity before it becomes a filesystem component.
    from uuid import UUID
    if not isinstance(request_id, str) or str(UUID(request_id)) != request_id or UUID(request_id).version != 4:
        raise ValueError('TELEMETRY_INVALID')
    return safe_path(project, f'{AREA}/{request_id}' + ('/' + suffix if suffix else ''), AREA)


def _read(path, limit):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('TELEMETRY_PATH_UNSAFE')
        return stream.read(limit + 1)


def append_event(project: Path, event: dict) -> None:
    raw = _validate('telemetry_event', event)
    datetime.strptime(event['observed_at'], '%Y-%m-%dT%H:%M:%S.%fZ')
    if len(raw) > MAX_EVENT_BYTES:
        raise ValueError('TELEMETRY_LIMIT')
    path = _path(project, event['request_id'], f"events/{event['execution_id']}/{event['producer_id']}.jsonl")
    old = _read(path, MAX_BYTES) if path.exists() else b''
    if len(old) + len(raw) + 1 > MAX_BYTES:
        raise ValueError('TELEMETRY_LIMIT')
    if old and not old.endswith(b'\n'):
        raise ValueError('EVENT_TAIL_INCOMPLETE')
    if len(old.splitlines()) >= MAX_EVENTS:
        raise ValueError('TELEMETRY_LIMIT')
    for line in old.splitlines():
        previous = strict_json_loads(line)
        if previous['event_id'] == event['event_id']:
            if previous != event:
                raise ValueError('TELEMETRY_IDENTITY_CONFLICT')
            _advance_cursor(project,event)
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    path = _path(project, event['request_id'], f"events/{event['execution_id']}/{event['producer_id']}.jsonl")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'ab') as stream:
        stream.write(raw + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(path.parent)
    _advance_cursor(project,event)


def _advance_cursor(project, event):
    if event['event_type']!='usage' or event['data']['source_sequence'] is None:
        return
    d=event['data'];source=d['source']
    path=_path(project,event['request_id'],f"cursors/{source['source_id']}.json")
    current=None
    if path.exists():
        current=strict_json_loads(_read(path,MAX_EVENT_BYTES))
        _validate('telemetry_cursor',current)
    if current and current['source_sequence']>d['source_sequence']:
        return
    cursor=dict(schema_version='1.0',source_id=source['source_id'],event_id=event['event_id'],
                native_event_id=d['native_event_id'],source_sequence=d['source_sequence'],producer_version=source['producer_version'])
    atomic_bytes(path,_validate('telemetry_cursor',cursor))


def _event_paths(project,request_id,gaps):
    root=_path(project,request_id,'events')
    if not root.exists():return
    visited=0;files=0
    with os.scandir(root) as directories:
        for entry in directories:
            visited+=1
            if visited>MAX_FILES*3:gaps.append('READ_LIMIT');return
            directory=_path(project,request_id,'events/'+entry.name)
            if not entry.is_dir(follow_symlinks=False):
                gaps.append('EVENT_PATH_UNSAFE');continue
            with os.scandir(directory) as children:
                for child in children:
                    visited+=1
                    if visited>MAX_FILES*3 or files>=MAX_FILES:gaps.append('READ_LIMIT');return
                    if not child.name.endswith('.jsonl'):continue
                    files+=1
                    yield _path(project,request_id,'events/'+entry.name+'/'+child.name)


def _events(project, request_id):
    events,gaps,size,lines={ },[],0,0
    conflicts=set()
    try:
        for path in _event_paths(project,request_id,gaps):
            if size>=MAX_BYTES or lines>=MAX_EVENTS:
                gaps.append('READ_LIMIT');break
            raw=_read(path,MAX_BYTES-size)
            truncated=len(raw)>MAX_BYTES-size
            if truncated:
                raw=raw[:MAX_BYTES-size];gaps.append('READ_LIMIT')
            size+=len(raw)
            pieces=raw.splitlines(keepends=True)
            for index,line in enumerate(pieces):
                if lines>=MAX_EVENTS:gaps.append('READ_LIMIT');break
                lines+=1
                if not line.endswith(b'\n'):
                    gaps.append('READ_LIMIT' if truncated else 'EVENT_TAIL_INCOMPLETE');continue
                try:
                    if len(line)>MAX_EVENT_BYTES+1:raise ValueError('line limit')
                    item=strict_json_loads(line);_validate('telemetry_event',item)
                    _utc_ns(item['observed_at'])
                    if (item['request_id']!=request_id or item['execution_id']!=path.parent.name
                        or item['producer_id']!=path.stem):raise ValueError('identity')
                    key=item['event_id']
                    if key in events and events[key]!=item:
                        conflicts.add(key);gaps.append('EVENT_IDENTITY_CONFLICT')
                    events[key]=item
                except (ValueError,TypeError,UnicodeError):
                    gaps.append('EVENT_MIDDLE_CORRUPT')
    except (OSError,ValueError,RuntimeError):
        gaps.append('EVENT_READ_FAILED')
    for key in conflicts:events.pop(key,None)
    return sorted(events.values(),key=lambda e:e['event_id']),gaps


def _metric(name, value, request_id, *, unit='tokens', coverage='partial', basis='observed', scope=None,
            attribution='unassigned', diagnostics=()):
    return dict(name=name, value=value, unit=unit, scope=scope or dict(kind='request', id=request_id),
                basis=dict(kind=basis), coverage='unknown' if value is None else coverage,
                attribution=attribution, diagnostics=list(diagnostics))


def build_report(project: Path, request_id: str) -> dict:
    events, gaps = _events(project, request_id)
    gaps.extend(e['data']['code'] for e in events if e['event_type']=='gap')
    read_gaps = list(gaps)
    metrics, sources = _usage_metrics(events, request_id, gaps)
    if read_gaps:
        for m in metrics:
            if m['coverage']=='complete':m['coverage']='partial'
            m['diagnostics'].extend(read_gaps)
    for field in ('input_bytes', 'output_bytes'):
        values = [e['data'][field] for e in events if e['event_type'] == 'work' and field in e['data']]
        metrics.append(_metric(field, sum(values) if values else None, request_id, unit='bytes'))
    metrics.extend(_time_metrics(events, request_id, gaps))
    if len(metrics)>MAX_METRICS:
        gaps.append('REPORT_LIMIT')
        metrics=metrics[:MAX_METRICS]
    result = dict(schema_version='1.0', request_id=request_id,
                  as_of=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                  source_digest=hashlib.sha256(canonical_json_bytes(events)).hexdigest(), event_count=len(events),
                  metrics=metrics, sources=sources, diagnostics=sorted(set(gaps)), coverage='partial' if events else 'unknown',
                  limits=dict(max_files=MAX_FILES, max_events=MAX_EVENTS, max_bytes=MAX_BYTES, max_metrics=MAX_METRICS),
                  host_capabilities={k:'unverified' for k in ('request_usage','call_identity','activity_attribution','tool_lifecycle','interrupt_signal')})
    context=dict(schema_version='1.0',request_id=request_id,execution_ids=sorted({e['execution_id'] for e in events}),host_capabilities=result['host_capabilities'],sources=sources)
    atomic_bytes(_path(project,request_id,'context.json'),_validate('telemetry_context',context))
    raw = _validate('telemetry_report', result)
    atomic_bytes(_path(project, request_id, 'report.json'), raw)
    body = '观测报告\n\n计量始于实际记录边界；宿主 usage 接入尚未验证。\n\n'
    body += f"截止：{result['as_of']}\n\n来源事件摘要：{result['source_digest']}\n\n"
    body += '请求合计与活动/共享分组是同一用量的不同视图，请勿再次相加。\n\n'
    for m in metrics:
        scope = json.dumps(m['scope'], ensure_ascii=False, sort_keys=True)
        basis = json.dumps(m['basis'], ensure_ascii=False, sort_keys=True)
        body += (f"- {m['name']}: {m['value'] if m['value'] is not None else '未知'} {m['unit']}"
                 f"；覆盖：{m['coverage']}；范围：{scope}；归属：{m['attribution']}；依据：{basis}\n")
    body+='\n\n缺口：'+('、'.join(result['diagnostics']) or '无已检测到的读取缺口')+'\n'
    atomic_bytes(_path(project, request_id, 'report.md'), body.encode('utf-8'))
    return result


TOKEN_FIELDS = ('total_tokens','input_tokens','output_tokens','cached_input_tokens','reasoning_output_tokens','cache_write_input_tokens')


def _counts(data, gaps):
    counts=dict(data['counts'])
    semantics=data['source']['semantics']
    inp,out=counts.get('input_tokens'),counts.get('output_tokens')
    total=counts.get('total_tokens')
    derived=False
    if semantics=='total_is_input_plus_output' and inp is not None and out is not None:
        if total is None:
            counts['total_tokens']=inp+out; derived=True
        elif total!=inp+out:
            gaps.append('USAGE_FIELDS_INCONSISTENT'); return None,False
        if ((counts.get('cached_input_tokens') is not None and counts['cached_input_tokens']>inp)
            or (counts.get('reasoning_output_tokens') is not None and counts['reasoning_output_tokens']>out)):
            gaps.append('USAGE_FIELDS_INCONSISTENT'); return None,False
    return counts,derived


def _usage_metrics(events, request_id, gaps):
    usages=[e for e in events if e['event_type']=='usage']
    sources={canonical_json_bytes(e['data']['source']):e['data']['source'] for e in usages}
    by_source={}
    for e in usages:
        by_source.setdefault(e['data']['source']['source_id'],[]).append(e)
    segments=[]; invalid=False; missing_start=False; complete=False; derived=False; call_ids=set()
    primaries=[key for key,items in by_source.items() if any(e['data']['source']['role']=='primary' for e in items)]
    if len(primaries)>1:
        gaps.append('USAGE_SOURCE_OVERLAP'); invalid=True
    for source_id,items in by_source.items():
        declarations={canonical_json_bytes(e['data']['source']) for e in items}
        source=items[0]['data']['source']
        if len(declarations)!=1 or any(e['data']['source']['producer_version']!=e['data']['source']['verified_producer_version'] for e in items):
            gaps.append('SOURCE_VERSION_CHANGED'); invalid=True; continue
        if (source['producer_version'] is None or source['source_schema_version']!='1.0'
            or source['adapter_version']!='normalized-v1' or source['semantics']=='unverified'
            or source['capabilities']['request_usage']!='verified'):
            gaps.append('SOURCE_UNVERIFIED'); invalid=True; continue
        if source['role']=='cross_check':
            continue  # Separate source evidence is retained; never summed with primary.
        if len(primaries)>1:
            continue
        unique={}; source_bad=False
        for e in items:
            d=e['data']; identity=(d['native_event_id'],d['revision'])
            if d['native_event_id'] is None or d['source_sequence'] is None or d['scope_id'] is None or d['counter_epoch'] is None:
                gaps.append('USAGE_IDENTITY_UNKNOWN');source_bad=True;continue
            if identity in unique:
                previous=unique[identity]
                if (previous['data']!=d or previous['activity_ids']!=e['activity_ids'] or previous['slice_ids']!=e['slice_ids']):
                    gaps.append('USAGE_REVISION_CONFLICT');source_bad=True
            else:
                unique[identity]=e
        if source_bad:
            invalid=True;continue
        items=list(unique.values())
        kinds={e['data']['observation_kind'] for e in items}
        if len(kinds)!=1:
            gaps.append('USAGE_SCOPE_OVERLAP');invalid=True;continue
        kind=next(iter(kinds))
        scopes={}
        for e in items:
            d=e['data'];scopes.setdefault((d['scope_kind'],d['scope_id'],d['counter_epoch']),[]).append(e)
        # Multiple native scopes may overlap (turn plus thread); epochs of one scope do not.
        if len({k[:2] for k in scopes})>1 and kind!='call_absolute':
            gaps.append('USAGE_SCOPE_OVERLAP');invalid=True;continue
        if kind=='cumulative':
            source_complete=True
            for scope,ordered in scopes.items():
                ordered.sort(key=lambda e:e['data']['source_sequence'])
                sequences=[e['data']['source_sequence'] for e in ordered]
                if len(sequences)!=len(set(sequences)):
                    gaps.append('USAGE_SEQUENCE_CONFLICT');invalid=True;continue
                if ordered[0]['data']['coverage']['boundary']!='request_start':
                    gaps.append('USAGE_START_UNKNOWN');missing_start=True;source_complete=False
                if ordered[-1]['data']['coverage']['boundary']!='request_end' or not ordered[-1]['data']['coverage']['complete']:
                    gaps.append('USAGE_END_UNKNOWN');source_complete=False
                previous=None;broken=False
                for e in ordered:
                    d=e['data'];counts,is_derived=_counts(d,gaps);derived|=is_derived
                    if counts is None:
                        invalid=True;broken=True;continue
                    if not d['coverage']['complete']:
                        gaps.append('USAGE_INTERVAL_INCOMPLETE');source_complete=False
                    if previous is not None and not broken:
                        prev_e,prev_counts=previous
                        delta={k:counts[k]-prev_counts[k] for k in counts if counts[k] is not None and prev_counts.get(k) is not None}
                        if any(v<0 for v in delta.values()):
                            gaps.append('COUNTER_DECREASED');invalid=True;broken=True;continue
                        if d['coverage']['start']!=prev_e['data']['native_event_id'] or d['coverage']['end']!=d['native_event_id']:
                            # Missing intermediate samples still allow a bounded difference, with unknown activity attribution.
                            activities=[]
                        else:
                            activities=e['activity_ids']
                        aligned=d['coverage']['start']==prev_e['data']['native_event_id'] and d['coverage']['end']==d['native_event_id']
                        exclusive=d['coverage']['exclusive'] and aligned
                        if not aligned:
                            gaps.append('USAGE_BOUNDARY_UNKNOWN');source_complete=False
                        if not exclusive:
                            gaps.append('USAGE_MIXED_SCOPE');source_complete=False
                        segments.append(dict(counts=delta,event=e,activities=activities,exclusive=exclusive,
                            basis=dict(kind='cumulative_difference',source_id=source_id,counter_epoch=scope[2],start=prev_e['data']['native_event_id'],end=d['native_event_id'])))
                    previous=e,counts
            complete=source_complete and not invalid and not missing_start
        else:
            selected=[]
            if kind=='call_absolute':
                calls={}
                for e in items:
                    d=e['data']
                    if d['host_call_id'] is None or source['capabilities']['call_identity']!='verified' or d['scope_kind']!='call' or d['scope_id']!=d['host_call_id'] or d['revision'] is None:
                        gaps.append('CALL_IDENTITY_UNVERIFIED');invalid=True;continue
                    calls.setdefault((d['counter_epoch'],d['host_call_id']),[]).append(e)
                for identity,observations in calls.items():
                    revisions=[e['data']['revision'] for e in observations]
                    if len(revisions)!=len(set(revisions)):
                        gaps.append('USAGE_REVISION_CONFLICT');invalid=True;continue
                    selected.append(max(observations,key=lambda e:e['data']['revision']))
                    call_ids.add(identity)
            else:
                selected=sorted(items,key=lambda e:e['data']['source_sequence'])
                # Explicit increments require disjoint native boundary links, never timestamp inference.
                starts=[e['data']['coverage']['start'] for e in selected]
                ends=[e['data']['coverage']['end'] for e in selected]
                boundary_path=starts[:1]+ends
                if (None in starts or None in ends or len(set(starts))!=len(starts) or len(set(ends))!=len(ends)
                    or len(set(boundary_path))!=len(boundary_path)
                    or any(left!=right for left,right in zip(ends,starts[1:]))):
                    gaps.append('USAGE_DELTA_OVERLAP');invalid=True;selected=[]
            for e in selected:
                d=e['data'];counts,is_derived=_counts(d,gaps);derived|=is_derived
                if counts is None:
                    invalid=True;continue
                exclusive=d['coverage']['exclusive']
                if not exclusive:gaps.append('USAGE_MIXED_SCOPE')
                segments.append(dict(counts=counts,event=e,activities=e['activity_ids'],exclusive=exclusive,
                    basis=dict(kind='call_absolute' if kind=='call_absolute' else 'explicit_delta',source_id=source_id,counter_epoch=d['counter_epoch'])))
    metrics=[];known=[s for s in segments if s['exclusive']]
    for field in TOKEN_FIELDS:
        values=[s['counts'][field] for s in known if s['counts'].get(field) is not None]
        value=sum(values) if values else None
        total=None if invalid or missing_start else value
        m=_metric(field,total,request_id,coverage='complete' if complete and len(values)==len(known) else 'partial',
            basis='derived_verified_input_output' if derived and field=='total_tokens' else 'normalized_usage',attribution='exclusive')
        if known and not derived and len({canonical_json_bytes(x['basis'].get('source_id')) for x in known})==1:
            m['basis'].update(source_id=known[0]['basis']['source_id'])
            if all(x['basis']['kind']=='cumulative_difference' for x in known) and len({x['basis']['counter_epoch'] for x in known})==1:
                ordered=sorted(known,key=lambda x:x['event']['data']['source_sequence'])
                m['basis'].update(kind='cumulative_difference',counter_epoch=ordered[0]['basis']['counter_epoch'],
                                  start=ordered[0]['basis']['start'],end=ordered[-1]['basis']['end'])
        metrics.append(m)
    values=[s['counts']['total_tokens'] for s in known if s['counts'].get('total_tokens') is not None]
    metrics.append(_metric('known_tokens',sum(values) if values else None,request_id,attribution='exclusive'))
    metrics.append(_metric('model_call_count',len(call_ids) if call_ids and not invalid else None,request_id,unit='count'))
    for s in segments:
        e=s['event'];activities=s['activities']
        scope=dict(kind='activity_group' if s['exclusive'] else 'host',id=e['event_id'],activity_ids=activities)
        for field,value in s['counts'].items():
            m=_metric(field,value,request_id,scope=scope,coverage='complete' if e['data']['coverage']['complete'] else 'partial',
                attribution='unassigned' if not activities or not s['exclusive'] else 'shared' if len(activities)>1 else 'exclusive')
            m['basis']=s['basis'];metrics.append(m)
    if not usages:
        gaps.append('USAGE_UNAVAILABLE')
    return metrics,list(sources.values())


def _union(intervals):
    end=None;total=0
    for left,right in sorted(intervals):
        total+=right-left if end is None or left>end else max(0,right-end)
        end=right if end is None else max(end,right)
    return total


def _utc_ns(value):
    dt = datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
    delta = dt - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def _time_metrics(events, request_id, gaps):
    groups, intervals, metrics = {}, [], []
    for e in events:
        if e['event_type'] != 'lifecycle' or e['data']['phase']=='milestone':
            continue
        d=e['data']
        key = ((e['execution_id'],d['name'],tuple(e['activity_ids']),tuple(e['slice_ids']))
               if d.get('timing')=='utc_marker' else (e['execution_id'],d['span_id']))
        groups.setdefault(key,[]).append(e)
    incomplete=set()
    for group in groups.values():
        starts=[e for e in group if e['data']['phase']=='start']
        ends=[e for e in group if e['data']['phase']=='end']
        name=group[0]['data']['name']
        if len(starts)!=1 or len(ends)!=1:
            gaps.append('LIFECYCLE_INCOMPLETE'); incomplete.add(name)
            metrics.append(_metric('duration_ns',None,request_id,unit='ns',scope=dict(kind='span',id=group[0]['data']['span_id']),diagnostics=['LIFECYCLE_INCOMPLETE']))
            continue
        start,end=starts[0],ends[0]; a,b=start['data'],end['data']
        wall=a.get('timing')==b.get('timing')=='utc_marker'
        if wall:
            left,right=_utc_ns(start['observed_at']),_utc_ns(end['observed_at'])
        elif (a['clock_domain'] is not None and a['clock_domain']==b['clock_domain']
              and start['producer_id']==end['producer_id']
              and all(a[k]==b[k] for k in ('name','parent_span_id','operation_id','attempt_id','host_call_id'))
              and a['monotonic_ns'] is not None and b['monotonic_ns'] is not None):
            left,right=a['monotonic_ns'],b['monotonic_ns']
        else:
            gaps.append('CLOCK_UNALIGNED'); incomplete.add(name)
            continue
        if right < left:
            gaps.append('CLOCK_REVERSED'); incomplete.add(name)
            continue
        clock_owner = (start['execution_id'], start['producer_id'], a['clock_domain'])
        intervals.append(dict(name=name,start=left,end=right,wall=wall,clock_owner=clock_owner,data=a))
        metrics.append(_metric('observed_wall_ns' if wall else 'duration_ns',right-left,request_id,unit='ns',
            coverage='complete',basis='utc_observed_interval' if wall else 'same_process_monotonic',
            scope=dict(kind='span',id=a['span_id']),attribution='exclusive'))
    for name,field in [('tool','tool_duration_ns'),('request','request_wall_ns'),('model','model_duration_ns'),('user_wait','user_wait_ns')]:
        selected=[i for i in intervals if i['name']==name]
        # Model lifecycle integration has not been verified by I1.4.
        value=sum(i['end']-i['start'] for i in selected) if selected and name!='model' else None
        metrics.append(_metric(field,value,request_id,unit='ns',basis='utc_observed_interval' if name=='request' else 'same_process_monotonic',
            diagnostics=['LIFECYCLE_INCOMPLETE'] if name in incomplete else []))
    for name, field in [('tool','tool_union_ns'),('user_wait','user_wait_union_ns'),('processing','processing_ns')]:
        selected=[i for i in intervals if i['name']==name]
        wall=bool(selected) and all(i['wall'] for i in selected) and name=='user_wait'
        aligned=wall or (len({i['clock_owner'] for i in selected})==1 and not any(i['wall'] for i in selected))
        value=_union([(i['start'],i['end']) for i in selected]) if selected and aligned and name not in incomplete else None
        diagnostics=['CLOCK_UNALIGNED'] if selected and not aligned else []
        gaps.extend(diagnostics)
        metrics.append(_metric(field,value,request_id,unit='ns',basis='same_process_union',diagnostics=diagnostics))
        if name=='user_wait':
            m=next(m for m in metrics if m['name']=='user_wait_ns')
            m.update(value=value,coverage='unknown' if value is None else 'partial',basis=dict(kind='utc_observed_union' if wall else 'same_process_union'))
    for parent in [i for i in intervals if i['name']=='activity']:
        child_events=[e for e in events if e['event_type']=='lifecycle' and e['data']['parent_span_id']==parent['data']['span_id']]
        child_ids={e['data']['span_id'] for e in child_events}
        children=[i for i in intervals if i['data']['span_id'] in child_ids]
        aligned=not parent['wall'] and all(not i['wall'] and i['clock_owner']==parent['clock_owner'] for i in children)
        valid=(len(children)==len(child_ids) and aligned and all(parent['start']<=i['start']<=i['end']<=parent['end'] for i in children))
        value=parent['end']-parent['start']-_union([(i['start'],i['end']) for i in children]) if valid else None
        diagnostics=[] if aligned else ['CLOCK_UNALIGNED']
        gaps.extend(diagnostics)
        metrics.append(_metric('exclusive_duration_ns',value,request_id,unit='ns',basis='parent_minus_child_union',scope=dict(kind='span',id=parent['data']['span_id']),diagnostics=diagnostics))
    return metrics


def _new_event(request_id, execution_id, producer_id, sequence, kind, data, activity_ids=(), slice_ids=()):
    from uuid import uuid4
    return dict(schema_version='1.0',event_id=str(uuid4()),event_type=kind,request_id=request_id,
                execution_id=execution_id,producer_id=producer_id,sequence=sequence,
                observed_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                activity_ids=list(activity_ids),slice_ids=list(slice_ids),data=data)


def begin_tool(request, start_ns, gaps):
    """One writer/clock per actual invocation; caller's execution is only a grouping label."""
    from uuid import uuid4
    observation=request.get('observation_context',{})
    execution=observation.get('execution_id',str(uuid4()))
    writer=str(uuid4())
    data=dict(name='tool',phase='start',span_id=str(uuid4()),parent_span_id=None,clock_domain=writer,
              monotonic_ns=start_ns,status=None,operation_id=str(uuid4()),attempt_id=str(uuid4()),
              host_call_id=None,operation=request['operation'],timing='monotonic')
    start=_new_event(request['request_id'],execution,writer,0,'lifecycle',data,
                     observation.get('activity_ids',[]),observation.get('slice_ids',[]))
    try:
        append_event(Path(request['project_path']).resolve(),start)
    except Exception:
        gaps.append('TELEMETRY_RECORDING_FAILED')
    return start


def finish_tool(request, start, response, end_ns, gaps, *, interrupted=False):
    project=Path(request['project_path']).resolve()
    if interrupted:
        gaps.append('INTERRUPTED')
    try:
        data=dict(start['data'],phase='end',monotonic_ns=end_ns,
                  status='interrupted' if interrupted else 'cancelled' if any(d['code']=='REQUEST_CANCELLED' for d in response['diagnostics'])
                  else 'succeeded' if response['ok'] else 'failed')
        end=_new_event(request['request_id'],start['execution_id'],start['producer_id'],1,'lifecycle',data,
                       start['activity_ids'],start['slice_ids'])
        append_event(project,end)
        # Values count canonical business envelope/response bytes, never token estimates.
        work=_new_event(request['request_id'],start['execution_id'],start['producer_id'],2,'work',
                        dict(input_bytes=len(canonical_json_bytes(request)),output_bytes=len(canonical_json_bytes(response))))
        append_event(project,work)
        for index,code in enumerate(sorted(set(gaps)),3):
            append_event(project,_new_event(request['request_id'],start['execution_id'],start['producer_id'],index,'gap',dict(code=code,recoverable=True)))
        build_report(project,request['request_id'])
    except Exception:
        gaps.append('TELEMETRY_RECORDING_FAILED')
    return dict(recording='degraded' if gaps else 'recorded',gaps=sorted(set(gaps)),
                report_path=None if 'TELEMETRY_RECORDING_FAILED' in gaps else f"{AREA}/{request['request_id']}/report.json")


def main(argv=None):
    import sys
    from uuid import uuid4
    from .cli import _Parser
    parser=_Parser(add_help=False)
    parser.add_argument('--project',required=True)
    parser.add_argument('--mark-file',required=True)
    outcome=dict(recording='degraded',gaps=['TELEMETRY_MARK_INVALID'],report_path=None)
    try:
        args=parser.parse_args(argv)
        raw=_read(Path(args.mark_file),MAX_EVENT_BYTES)
        if len(raw)>MAX_EVENT_BYTES:
            raise ValueError('TELEMETRY_LIMIT')
        mark=strict_json_loads(raw)
        _validate('telemetry_mark',mark)
        data=dict(name=mark['name'],phase=mark['phase'],span_id=str(uuid4()),parent_span_id=None,
                  clock_domain=None,monotonic_ns=None,status=None,operation_id=None,attempt_id=None,
                  host_call_id=None,timing='utc_marker')
        e=_new_event(mark['request_id'],mark['execution_id'],str(uuid4()),0,'lifecycle',data,
                     mark['activity_ids'],mark['slice_ids'])
        append_event(Path(args.project).resolve(),e)
        result_path=None
        if mark['name']=='request' and mark['phase']=='end':
            build_report(Path(args.project).resolve(),mark['request_id'])
            result_path=f"{AREA}/{mark['request_id']}/report.json"
        outcome=dict(recording='recorded',gaps=[],report_path=result_path)
    except Exception:
        pass  # Observation-only entry never emits source text or a business failure/retry.
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8',errors='strict')
    print(canonical_json_bytes(outcome).decode('utf-8'))
    return 0


def inspect_report(project, payload):
    """Explicit query; stable pagination depends on source digest, not rebuild UTC."""
    import base64
    from .contracts import semantic_digest
    from .project import StorageError, file_ref
    request_id=payload['selector']['request_id']
    try:
        report=build_report(project,request_id)
    except Exception:
        return dict(selected_version=None,items=[],matched_count=0,returned_count=0,remaining_count=0,
            next_cursor=None,coverage=dict(complete=False),report_ref=None,
            observation=dict(recording='degraded',gaps=['TELEMETRY_RECORDING_FAILED'],report_path=None))
    items=report['metrics'];binding=semantic_digest(dict(selector=payload['selector'],source_digest=report['source_digest']))
    offset=0
    if payload.get('cursor') is not None:
        try:
            cursor=strict_json_loads(base64.urlsafe_b64decode(payload['cursor']))
            if set(cursor)!={'binding','offset'} or cursor['binding']!=binding or type(cursor['offset']) is not int or not 0<cursor['offset']<len(items):
                raise ValueError('cursor')
            offset=cursor['offset']
        except (ValueError,KeyError,TypeError):
            raise StorageError('VERSION_INCOMPATIBLE','观测游标与来源事件集合不同；请用 cursor=null 重读。') from None
    selected=[];size=0
    for item in items[offset:offset+payload.get('limit',20)]:
        size+=len(canonical_json_bytes(item))
        if size>64*1024:break
        selected.append(item)
    end=offset+len(selected)
    cursor=None if end==len(items) else base64.urlsafe_b64encode(canonical_json_bytes(dict(binding=binding,offset=end))).decode('ascii')
    return dict(selected_version=report['source_digest'],items=selected,matched_count=len(items),returned_count=len(selected),
                remaining_count=len(items)-end,next_cursor=cursor,coverage=dict(view='telemetry',selector=payload['selector'],
                start_offset=offset,end_offset=end,complete=cursor is None,observation_coverage=report['coverage']),
                report_ref=file_ref(project,_path(project,request_id,'report.json')))


if __name__ == '__main__':
    raise SystemExit(main())
