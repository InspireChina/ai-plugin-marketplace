"""Version-bound observation of one explicitly supplied Codex JSONL file."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import stat
import time
from datetime import datetime
from uuid import uuid4

from . import telemetry
from .contracts import canonical_json_bytes, strict_json_loads
from .project import atomic_bytes

ADAPTER_VERSION = 'codex-jsonl-v1'
PRODUCER_VERSION = '0.153.4'
MAX_BYTES = 8 * 1024 * 1024
MAX_LINES = 10000
MAX_RECORD_BYTES = 256 * 1024


class _NativeGap(Exception):
    """Only a stable diagnostic code crosses the observation boundary."""


class _Budget:
    def __init__(self, limits):
        ceiling = dict(max_bytes=MAX_BYTES, max_lines=MAX_LINES)
        limits = limits or {}
        if (not isinstance(limits, dict) or set(limits)-ceiling.keys()
            or any(type(v) is not int or not 0<v<=ceiling[k] for k,v in limits.items())):
            raise _NativeGap('NATIVE_LIMIT_INVALID')
        self.limits = ceiling | limits
        self.bytes = self.lines = 0

    def line(self, stream):
        remaining = self.limits['max_bytes']-self.bytes
        if remaining<=0 or self.lines>=self.limits['max_lines']:
            raise _NativeGap('NATIVE_READ_LIMIT')
        raw=stream.readline(min(MAX_RECORD_BYTES,remaining))
        self.bytes+=len(raw)
        self.lines+=bool(raw)
        if raw and not raw.endswith(b'\n'):
            code=('NATIVE_RECORD_LIMIT' if len(raw)==MAX_RECORD_BYTES else
                  'NATIVE_READ_LIMIT' if self.bytes==self.limits['max_bytes'] else 'NATIVE_TAIL_INCOMPLETE')
            raise _NativeGap(code)
        return raw


def _decode(raw):
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result: raise ValueError('duplicate')
            result[k]=v
        return result
    try:
        # Floats in unrelated native payloads are discarded, not normalized into events.
        value=json.loads(raw,object_pairs_hook=unique)
        if not isinstance(value,dict):raise ValueError('record')
        return value
    except (ValueError,UnicodeError,RecursionError):
        raise _NativeGap('NATIVE_MIDDLE_CORRUPT') from None


def _source(header, binding):
    payload = header.get('payload', {})
    if not isinstance(payload,dict):raise _NativeGap('SOURCE_UNVERIFIED')
    version = payload.get('cli_version')
    if not isinstance(version, str) or re.fullmatch(r'[A-Za-z0-9_:.=-]{1,128}', version) is None:
        version = None
    return dict(source_id=binding['source_id'], source_kind='codex_session_jsonl',
                host_thread_id=binding['host_thread_id'],host_turn_ids=binding['host_turn_ids'],
                producer_name='codex-desktop' if payload.get('originator') == 'Codex Desktop' else 'unknown',
                producer_version=version, verified_producer_version=PRODUCER_VERSION,
                source_schema_version=None, adapter_version=ADAPTER_VERSION,
                semantics='unverified', role='primary', capabilities={
                    k: 'unverified' for k in ('request_usage', 'call_identity', 'activity_attribution',
                                             'tool_lifecycle', 'interrupt_signal')})


def _gap(project, binding, code, source=None):
    data = dict(code=code, recoverable=True)
    if source is not None:
        data['source'] = source
    events, _ = telemetry._events(project, binding['request_id'])
    if not any(e['event_type'] == 'gap' and e['data'] == data for e in events):
        telemetry.append_event(project, telemetry._new_event(
            binding['request_id'], binding['execution_id'], str(uuid4()), 0, 'gap', data))


def _usage(record, source, start, end, raw):
    p=record['payload']
    native={k:p[k] for k in ('thread_id','turn_id','session_id','root_turn_id','response_id')}
    native.update(turn_counts={k:p['turn_token_usage'][k] for k in telemetry.TOKEN_FIELDS},
                  thread_counts={k:p['thread_token_usage'][k] for k in telemetry.TOKEN_FIELDS},
                  byte_start=start,byte_end=end,line_sha256=hashlib.sha256(raw).hexdigest())
    return dict(source=source,scope_kind='response',scope_id=p['response_id'],counter_epoch=None,
                native_event_id=None,source_sequence=record['ordinal'],revision=None,
                observation_kind='response_absolute',host_call_id=None,native=native,
                counts={k:p['usage'][k] for k in telemetry.TOKEN_FIELDS},
                coverage=dict(start=None,end=None,boundary='unknown',complete=False,exclusive=True))


def _turn(record,source,start,end,raw):
    p=record['payload'];kind=p['type']
    timestamp=record['timestamp']
    if not isinstance(timestamp,str) or re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3,6}Z',timestamp) is None:
        raise _NativeGap('SOURCE_UNVERIFIED')
    timestamp=datetime.fromisoformat(timestamp.replace('Z','+00:00')).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    return dict(source=source,source_sequence=record['ordinal'],name='processing',
        phase='start' if kind=='task_started' else 'end',parent_span_id=None,clock_domain=None,
        monotonic_ns=None,status=None if kind=='task_started' else 'interrupted' if kind=='turn_aborted' else 'succeeded',
        operation_id=None,attempt_id=None,host_call_id=None,timing='native_turn',
        native=dict(thread_id=source['host_thread_id'],turn_id=p['turn_id'],timestamp=timestamp,
                    duration_ms=p.get('duration_ms'),byte_start=start,byte_end=end,
                    line_sha256=hashlib.sha256(raw).hexdigest()))


def _append_native(project,binding,data,events,writer,kind='usage'):
    if kind=='lifecycle':
        related=next((e['data']['span_id'] for e in events if e['event_type']=='lifecycle'
            and e['data'].get('source',{}).get('source_id')==binding['source_id']
            and e['data'].get('native',{}).get('turn_id')==data['native']['turn_id']),None)
        data['span_id']=related or str(uuid4())
    for previous in events:
        old=previous['data']
        if (previous['event_type']==kind and old.get('source',{}).get('source_id')==binding['source_id']
            and old.get('native',{}).get('byte_start')==data['native']['byte_start']):
            if old!=data:
                raise _NativeGap('NATIVE_CURSOR_INVALID')
            telemetry.append_event(project,previous)
            return
    e=telemetry._new_event(binding['request_id'],binding['execution_id'],writer,
                           data['source_sequence'],kind,data)
    telemetry.append_event(project,e)
    events.append(e)


def _cursor(project,binding,stream,header_raw,budget):
    path=telemetry._path(project,binding['request_id'],f"cursors/{binding['source_id']}-native.json")
    info=os.fstat(stream.fileno())
    signature=dict(binding_sha256=hashlib.sha256(canonical_json_bytes(binding)).hexdigest(),
        header_sha256=hashlib.sha256(header_raw).hexdigest(),device=info.st_dev,inode=info.st_ino)
    if path.exists():
        try:
            state=strict_json_loads(telemetry._read(path,telemetry.MAX_EVENT_BYTES))
            telemetry._validate('telemetry_native_cursor',state)
        except (ValueError,TypeError):
            raise _NativeGap('NATIVE_CURSOR_INVALID') from None
        if (any(state[k]!=v for k,v in signature.items()) or state['offset']>info.st_size
            or state['source_id']!=binding['source_id'] or state['offset']<len(header_raw)
            or state['anchor_start']>=state['offset']):
            raise _NativeGap('NATIVE_CURSOR_INVALID')
        stream.seek(state['anchor_start'])
        anchor=budget.line(stream)
        if stream.tell()!=state['offset'] or hashlib.sha256(anchor).hexdigest()!=state['anchor_sha256']:
            raise _NativeGap('NATIVE_CURSOR_INVALID')
    else:
        state=dict(schema_version='1.0',source_id=binding['source_id'],producer_id=str(uuid4()),
            adapter_version=ADAPTER_VERSION,producer_version=PRODUCER_VERSION,**signature,
            offset=len(header_raw),ordinal=0,anchor_start=0,anchor_sha256=signature['header_sha256'])
        # Persist writer identity before any event; progress is committed only after event fsync.
        atomic_bytes(path,telemetry._validate('telemetry_native_cursor',state))
    stream.seek(state['offset'])
    return path,state


def _consume(project,binding,stream,source,state,budget,events):
    end=os.fstat(stream.fileno()).st_size
    while stream.tell()<end:
        start=stream.tell();raw=budget.line(stream)
        if not raw:raise _NativeGap('NATIVE_CURSOR_INVALID')
        record=_decode(raw)
        ordinal=record.get('ordinal')
        if type(ordinal) is not int or ordinal<=state['ordinal']:
            raise _NativeGap('NATIVE_SEQUENCE_INVALID')
        if record.get('type')=='token_usage_record':
            try:
                p=record['payload']
                if p.get('thread_id')!=binding['host_thread_id']:
                    raise _NativeGap('SOURCE_IDENTITY_MISMATCH')
                if p.get('turn_id') in binding['host_turn_ids']:
                    data=_usage(record,source,start,stream.tell(),raw)
                    telemetry._validate('telemetry_usage',data)
                    _append_native(project,binding,data,events,state['producer_id'])
            except (KeyError,TypeError,ValueError,AttributeError):
                raise _NativeGap('SOURCE_UNVERIFIED') from None
            except OSError:
                raise _NativeGap('TELEMETRY_RECORDING_FAILED') from None
        elif record.get('type')=='event_msg':
            p=record.get('payload')
            if (isinstance(p,dict) and p.get('type') in ('task_started','task_complete','turn_aborted')
                and p.get('turn_id') in binding['host_turn_ids']):
                try:
                    _append_native(project,binding,_turn(record,source,start,stream.tell(),raw),
                                   events,state['producer_id'],'lifecycle')
                except (ValueError,TypeError,KeyError):
                    raise _NativeGap('SOURCE_UNVERIFIED') from None
                except OSError:
                    raise _NativeGap('TELEMETRY_RECORDING_FAILED') from None
        state.update(offset=stream.tell(),ordinal=ordinal,anchor_start=start,
                     anchor_sha256=hashlib.sha256(raw).hexdigest())


def collect_native_usage(project: Path, request_id: str, *, source_path: Path, binding: dict,
                         limits: dict | None = None) -> dict:
    """Collect once, advancing only durable prefixes. There is no discovery or polling."""
    started=time.monotonic_ns()
    outcome=dict(recording='degraded',gaps=[],report_path=None,
                 read=dict(bytes_read=0,lines_read=0,start_offset=0,end_offset=0,eof=False))
    budget=source=state=cursor_path=None
    validated=False
    try:
        telemetry._validate('telemetry_native_binding', binding)
        if request_id != binding['request_id']:
            raise _NativeGap('OBSERVATION_CONTEXT_INVALID')
        validated=True
        budget=_Budget(limits)
        fd = os.open(source_path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise _NativeGap('SOURCE_UNAVAILABLE')
            header_raw=budget.line(stream);header=_decode(header_raw)
            source=_source(header,binding)
            if source['producer_version']!=PRODUCER_VERSION:
                raise _NativeGap('SOURCE_VERSION_CHANGED')
            if source['producer_name']!='codex-desktop' or header.get('type')!='session_meta':
                raise _NativeGap('SOURCE_UNVERIFIED')
            if header['payload'].get('id')!=binding['host_thread_id']:
                raise _NativeGap('SOURCE_IDENTITY_MISMATCH')
            source['semantics']='total_is_input_plus_output'
            source['capabilities']['request_usage']='partial'
            events,read_gaps=telemetry._events(project,request_id)
            if read_gaps:raise _NativeGap('NATIVE_CURSOR_INVALID')
            cursor_path,state=_cursor(project,binding,stream,header_raw,budget)
            outcome['read']['start_offset']=state['offset']
            try:
                _consume(project,binding,stream,source,state,budget,events)
                outcome['read']['eof']=state['offset']==os.fstat(stream.fileno()).st_size
            finally:
                outcome['read']['end_offset']=state['offset']
                try:
                    atomic_bytes(cursor_path,telemetry._validate('telemetry_native_cursor',state))
                except (OSError,ValueError):
                    outcome['gaps'].append('TELEMETRY_RECORDING_FAILED')
    except _NativeGap as error:
        outcome['gaps'].append(str(error))
    except (ValueError,TypeError,KeyError,RecursionError):
        outcome['gaps'].append('SOURCE_UNVERIFIED' if validated else 'OBSERVATION_CONTEXT_INVALID')
    except OSError:
        outcome['gaps'].append('SOURCE_UNAVAILABLE')
    except KeyboardInterrupt:
        if validated:
            try:_gap(project,binding,'INTERRUPTED',source)
            except Exception:pass
        raise
    finally:
        if budget:
            outcome['read'].update(bytes_read=budget.bytes,lines_read=budget.lines)
        outcome['collector_duration_ns']=time.monotonic_ns()-started
    if validated:
        try:
            for code in sorted(set(outcome['gaps'])):_gap(project,binding,code,source)
            report=telemetry.build_report(project,request_id)
            outcome['gaps']=sorted(set(outcome['gaps']+report['diagnostics']))
            outcome['report_path']=f'{telemetry.AREA}/{request_id}/report.json'
        except (OSError,ValueError,TypeError):
            outcome['gaps'].append('TELEMETRY_RECORDING_FAILED')
    outcome['gaps']=sorted(set(outcome['gaps']))
    outcome['recording']='degraded' if outcome['gaps'] else 'recorded'
    return outcome
