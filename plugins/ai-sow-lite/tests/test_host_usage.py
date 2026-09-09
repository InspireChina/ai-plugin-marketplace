"""Synthetic native shapes test accounting, never physical model-call support."""
import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from ai_sow_lite import telemetry
from ai_sow_lite.contracts import canonical_json_bytes


THREAD = 'synthetic-thread'
TURN = 'synthetic-turn'


def counts(input_tokens=10, output_tokens=2):
    return dict(input_tokens=input_tokens, output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens, cached_input_tokens=4,
                cache_write_input_tokens=0, reasoning_output_tokens=1)


def native_records():
    return [
        dict(type='session_meta', ordinal=0, payload=dict(
            id=THREAD, cli_version='0.153.4', originator='Codex Desktop',
            base_instructions='PRIVATE PROMPT', cwd='/private/customer')),
        dict(type='event_msg', ordinal=1, timestamp='2026-09-10T00:00:00.000Z',
             payload=dict(type='task_started', turn_id=TURN, started_at=1788998400)),
        dict(type='token_usage_record', ordinal=2, timestamp='2026-09-10T00:00:01.000Z',
             payload=dict(thread_id=THREAD, turn_id=TURN, session_id='synthetic-parent-session',
                          root_turn_id='synthetic-root-turn', response_id='response-1',
                          usage=counts(), turn_token_usage=counts(), thread_token_usage=counts())),
        dict(type='event_msg', ordinal=3, timestamp='2026-09-10T00:00:02.000Z',
             payload=dict(type='task_complete', turn_id=TURN, started_at=1788998400,
                          completed_at=1788998402, duration_ms=1999)),
    ]


def write_native(path, records):
    path.write_bytes(b''.join(canonical_json_bytes(r) + b'\n' for r in records))


def binding(request_id):
    return dict(schema_version='1.0', request_id=request_id, execution_id=str(uuid4()),
                source_id=str(uuid4()), host_thread_id=THREAD, host_turn_ids=[TURN])


def collect_cli(project, source, selection, capsys):
    descriptor = source.parent / 'selection.json'
    descriptor.write_bytes(canonical_json_bytes(selection))
    code = telemetry.main(['--project', str(project), '--collect-file', str(descriptor),
                           '--native-source', str(source)])
    return code, json.loads(capsys.readouterr().out)


def metric(report, name):
    return next(m for m in report['metrics'] if m['name'] == name and m['scope']['kind'] == 'request')


def business_bytes(project):
    return {p.relative_to(project).as_posix(): p.read_bytes()
            for p in (project / '.ai-sow-lite').rglob('*')
            if p.is_file() and 'telemetry' not in p.relative_to(project).parts}


@pytest.mark.parametrize('field,value,gap', [
    ('originator', 'Unknown Host', 'SOURCE_UNVERIFIED'),
    ('cli_version', '0.999.0', 'SOURCE_VERSION_CHANGED'),
])
def test_unknown_host_format_keeps_business_result(tmp_path, capsys, field, value, gap):
    from ai_sow_lite import cli, project as storage
    from .support.fixtures import storage_package

    project = tmp_path / 'project'
    package = storage_package(project)
    storage._commit_version(**package)
    request_id = package['request_id']
    response = cli.execute(dict(protocol_version='1.0', request_id=request_id,
                                project_path=str(project), operation='inspect',
                                payload=dict(view='current', selector={})))
    assert response['ok']
    before = business_bytes(project)
    records = native_records()
    records[0]['payload'][field] = value
    source = tmp_path / 'controlled-native.jsonl'
    write_native(source, records)
    selection = binding(request_id)

    for _ in range(2):
        code, outcome = collect_cli(project, source, selection, capsys)
        assert code == 0
        assert gap in outcome['gaps']
        report = telemetry.build_report(project, request_id)
        assert gap in report['diagnostics']
        assert report['sources'][0]['producer_version'] == records[0]['payload']['cli_version']
        assert metric(report, 'total_tokens')['value'] is None
        assert metric(report, 'model_call_count')['value'] is None
        assert metric(report, 'tool_duration_ns')['value'] is not None
        assert all(m['coverage'] in {'complete', 'partial', 'unknown'} for m in report['metrics'])
        assert business_bytes(project) == before
        assert storage.recover_request(project, request_id)['state'] == 'applied'
    text = b''.join(p.read_bytes() for p in (project / '.ai-sow-lite/telemetry').rglob('*') if p.is_file())
    assert b'PRIVATE PROMPT' not in text and b'/private/customer' not in text


def two_responses():
    records = native_records()
    second = copy.deepcopy(records[2])
    second['ordinal'] = 3
    second['payload'].update(response_id='response-2', usage=counts(20, 3),
        turn_token_usage=dict(counts(30, 5), cached_input_tokens=8, reasoning_output_tokens=2),
        thread_token_usage=dict(counts(30, 5), cached_input_tokens=8, reasoning_output_tokens=2))
    records.insert(3, second)
    records[-1]['ordinal'] = 4
    return records


def test_response_absolute_counts_once_without_physical_call_or_activity_claim(tmp_path, capsys):
    project = tmp_path / 'project'
    source = tmp_path / 'controlled-native.jsonl'
    records = two_responses()
    duplicate = copy.deepcopy(records[2])
    duplicate['ordinal'] = 4
    records.insert(4, duplicate)
    records[-1]['ordinal'] = 5
    write_native(source, records)
    selection = binding(str(uuid4()))
    _, outcome = collect_cli(project, source, selection, capsys)
    assert outcome['recording'] == 'recorded', outcome
    report = telemetry.build_report(project, selection['request_id'])
    assert metric(report, 'total_tokens')['value'] == 35
    assert metric(report, 'total_tokens')['coverage'] == 'partial'
    assert metric(report, 'input_tokens')['value'] == 30
    assert metric(report, 'cached_input_tokens')['value'] == 8
    assert metric(report, 'model_call_count')['value'] is None
    assert report['host_capabilities']['request_usage'] == 'partial'
    assert report['host_capabilities']['call_identity'] == 'unverified'
    assert report['host_capabilities']['activity_attribution'] == 'unverified'
    groups = [m for m in report['metrics'] if m['name'] == 'total_tokens' and m['scope']['kind'] != 'request']
    assert sorted((m['value'], m['attribution']) for m in groups) == [(12, 'unassigned'), (23, 'unassigned')]
    assert all(m['basis']['kind'] == 'response_absolute' for m in groups)
    _, again = collect_cli(project, source, selection, capsys)
    rebuilt = telemetry.build_report(project, selection['request_id'])
    assert again['recording'] == 'recorded'
    assert rebuilt['event_count'] == report['event_count']
    assert rebuilt['source_digest'] == report['source_digest']


@pytest.mark.parametrize('mutation,gap', [
    ('response_conflict', 'NATIVE_RESPONSE_CONFLICT'),
    ('turn_counter', 'NATIVE_COUNTER_MISMATCH'),
    ('thread_counter', 'NATIVE_COUNTER_MISMATCH'),
])
def test_native_conflict_never_selects_latest_or_sums_overlapping_counters(tmp_path, capsys, mutation, gap):
    records = two_responses()
    if mutation == 'response_conflict':
        records[3]['payload']['response_id'] = 'response-1'
    elif mutation == 'turn_counter':
        records[3]['payload']['turn_token_usage'] = counts(100, 20)
    else:
        records[3]['payload']['thread_token_usage'] = counts(100, 20)
    source = tmp_path / 'controlled-native.jsonl'
    write_native(source, records)
    selection = binding(str(uuid4()))
    collect_cli(tmp_path / 'project', source, selection, capsys)
    report = telemetry.build_report(tmp_path / 'project', selection['request_id'])
    assert gap in report['diagnostics']
    assert metric(report, 'total_tokens')['value'] is None
    assert metric(report, 'model_call_count')['value'] is None
    if mutation != 'response_conflict':
        assert metric(report,'known_tokens')['value']==12


def collect(project, source, selection, **kwargs):
    from ai_sow_lite.host_usage import collect_native_usage
    return collect_native_usage(project, selection['request_id'], source_path=source,
                                binding=selection, **kwargs)


def test_native_cursor_resumes_after_durable_prefix_without_rereading_large_background(tmp_path):
    source = tmp_path / 'native.jsonl'
    records = two_responses()
    background = [dict(type='response_item', ordinal=10+i, payload={'content':'PRIVATE '*2000}) for i in range(80)]
    records = records[:2] + background + records[2:]
    for i, record in enumerate(records): record['ordinal'] = i
    write_native(source, records)
    assert source.stat().st_size > 1024 * 1024
    project = tmp_path / 'project'; selection = binding(str(uuid4()))
    first = collect(project, source, selection, limits={'max_bytes': 1024 * 1024})
    assert 'NATIVE_READ_LIMIT' in first['gaps']
    assert first['read']['bytes_read'] <= 1024 * 1024
    assert not first['read']['eof']
    second = collect(project, source, selection)
    assert second['read']['start_offset'] == first['read']['end_offset']
    assert second['read']['eof']
    assert second['read']['bytes_read'] < 512 * 1024
    assert metric(telemetry.build_report(project, selection['request_id']), 'total_tokens')['value'] == 35
    third = collect(project, source, selection)
    assert third['read']['start_offset'] == third['read']['end_offset'] == source.stat().st_size
    assert third['read']['bytes_read'] < 4096


def test_native_cursor_failure_replays_original_event_envelope(tmp_path, monkeypatch):
    from ai_sow_lite import host_usage
    source = tmp_path / 'native.jsonl'; write_native(source, two_responses())
    project = tmp_path / 'project'; selection = binding(str(uuid4()))
    original = host_usage.atomic_bytes
    writes = 0
    def fail_progress(path, raw):
        nonlocal writes
        writes += 1
        if writes > 1: raise OSError('PRIVATE DISK ERROR')
        return original(path, raw)
    monkeypatch.setattr(host_usage, 'atomic_bytes', fail_progress)
    failed = collect(project, source, selection)
    assert 'TELEMETRY_RECORDING_FAILED' in failed['gaps']
    events, _ = telemetry._events(project, selection['request_id'])
    before = {e['event_id']: e for e in events if e['event_type'] == 'usage'}
    assert len(before) == 2
    monkeypatch.setattr(host_usage, 'atomic_bytes', original)
    collect(project, source, selection)
    events, _ = telemetry._events(project, selection['request_id'])
    assert {e['event_id']: e for e in events if e['event_type'] == 'usage'} == before
    assert metric(telemetry.build_report(project, selection['request_id']), 'total_tokens')['value'] == 35


@pytest.mark.parametrize('problem,gap', [
    ('tail', 'NATIVE_TAIL_INCOMPLETE'),
    ('middle', 'NATIVE_MIDDLE_CORRUPT'),
    ('record_limit', 'NATIVE_RECORD_LIMIT'),
    ('line_limit', 'NATIVE_READ_LIMIT'),
    ('identity', 'SOURCE_IDENTITY_MISMATCH'),
])
def test_native_reader_stops_at_uncertain_boundary_and_preserves_diagnostic(tmp_path, problem, gap):
    records = native_records(); source = tmp_path / 'native.jsonl'
    write_native(source, records[:3])
    prefix = source.stat().st_size
    suffix = b'{"unfinished":'
    limits = {}
    if problem == 'middle': suffix = b'not json\n' + canonical_json_bytes(records[-1]) + b'\n'
    elif problem == 'record_limit': suffix = b'X' * (256 * 1024 + 1) + b'\n'
    elif problem == 'line_limit':
        suffix = canonical_json_bytes(records[-1]) + b'\n'; limits = {'max_lines':3}
    elif problem == 'identity':
        bad = copy.deepcopy(records[2]); bad['ordinal']=3; bad['payload']['thread_id']='another-thread'
        suffix=canonical_json_bytes(bad)+b'\n'
    with source.open('ab') as stream: stream.write(suffix)
    project=tmp_path/'project';selection=binding(str(uuid4()))
    outcome=collect(project,source,selection,limits=limits)
    assert gap in outcome['gaps']
    assert outcome['read']['end_offset'] == prefix
    assert not outcome['read']['eof']
    report=telemetry.build_report(project,selection['request_id'])
    assert gap in report['diagnostics']
    assert metric(report,'known_tokens')['value']==12
    assert metric(report,'total_tokens')['coverage']!='complete'


@pytest.mark.parametrize('change', ['replace', 'truncate', 'anchor', 'binding'])
def test_native_cursor_rejects_replacement_truncation_and_changed_binding(tmp_path,change):
    source=tmp_path/'native.jsonl';write_native(source,two_responses())
    project=tmp_path/'project';selection=binding(str(uuid4()))
    collect(project,source,selection)
    if change=='replace':
        replacement=tmp_path/'replacement.jsonl';replacement.write_bytes(source.read_bytes());replacement.replace(source)
    elif change=='truncate': source.write_bytes(source.read_bytes()[:300])
    elif change=='anchor':
        raw=source.read_bytes();source.write_bytes(raw.replace(b'"duration_ms":1999',b'"duration_ms":2999'))
    else: selection['host_turn_ids']=['different-turn']
    result=collect(project,source,selection)
    assert 'NATIVE_CURSOR_INVALID' in result['gaps']
    assert result['recording']=='degraded'


def test_native_late_end_rebuilds_only_telemetry_and_never_claims_full_request(tmp_path):
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    project=tmp_path/'project';package=storage_package(project);storage._commit_version(**package)
    source=tmp_path/'native.jsonl';records=native_records();write_native(source,records[:3])
    selection=binding(package['request_id']);before=business_bytes(project)
    collect(project,source,selection)
    first=telemetry.build_report(project,selection['request_id'])
    assert 'NATIVE_TURN_END_UNKNOWN' in first['diagnostics']
    with source.open('ab') as stream:stream.write(canonical_json_bytes(records[-1])+b'\n')
    collect(project,source,selection)
    second=telemetry.build_report(project,selection['request_id'])
    assert 'NATIVE_TURN_END_UNKNOWN' not in second['diagnostics']
    native_time=next(m for m in second['metrics'] if m['name']=='native_turn_duration_ns')
    assert native_time['value']==1999000000 and native_time['scope']['kind']=='host_turn'
    assert native_time['basis']['kind']=='native_reported_turn_duration'
    assert metric(second,'total_tokens')['value']==12 and metric(second,'total_tokens')['coverage']=='partial'
    assert metric(second,'model_duration_ns')['value'] is None
    assert metric(second,'request_wall_ns')['value'] is None
    assert business_bytes(project)==before


def test_native_activity_annotation_remains_one_shared_group(tmp_path):
    source=tmp_path/'native.jsonl';write_native(source,native_records())
    selection=binding(str(uuid4()));project=tmp_path/'project';collect(project,source,selection)
    events,_=telemetry._events(project,selection['request_id'])
    native=next(e for e in events if e['event_type']=='usage')
    assert native['activity_ids']==[]  # Native completion timestamps supplied no attribution.
    native['activity_ids']=[str(uuid4()),str(uuid4())]
    annotated=tmp_path/'explicit-annotation'
    telemetry.append_event(annotated,native)
    report=telemetry.build_report(annotated,selection['request_id'])
    groups=[m for m in report['metrics'] if m['name']=='total_tokens' and m['scope']['kind']=='activity_group']
    assert len(groups)==1 and groups[0]['value']==12 and groups[0]['attribution']=='shared'
    assert len(groups[0]['scope']['activity_ids'])==2


def test_native_event_write_failure_does_not_acknowledge_unrecorded_usage(tmp_path,monkeypatch):
    source=tmp_path/'native.jsonl';write_native(source,native_records())
    selection=binding(str(uuid4()));project=tmp_path/'project'
    original=telemetry.append_event
    def fail_usage(root,event):
        if event['event_type']=='usage':raise OSError('PRIVATE DISK ERROR')
        return original(root,event)
    monkeypatch.setattr(telemetry,'append_event',fail_usage)
    result=collect(project,source,selection)
    assert 'TELEMETRY_RECORDING_FAILED' in result['gaps']
    before=result['read']['end_offset']
    monkeypatch.setattr(telemetry,'append_event',original)
    result=collect(project,source,selection)
    assert result['read']['start_offset']==before
    assert metric(telemetry.build_report(project,selection['request_id']),'total_tokens')['value']==12


def test_real_sigint_after_durable_native_usage_propagates_without_business_mutation(tmp_path):
    import os
    import select
    import signal
    import subprocess
    import sys
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    if os.name!='posix':pytest.skip('Real SIGINT handshake requires POSIX')
    project=tmp_path/'project';package=storage_package(project);storage._commit_version(**package)
    source=tmp_path/'native.jsonl';write_native(source,two_responses())
    selection=binding(package['request_id']);descriptor=tmp_path/'binding.json'
    descriptor.write_bytes(canonical_json_bytes(selection));before=business_bytes(project)
    script='''
import json,signal,sys
from pathlib import Path
from ai_sow_lite.host_usage import collect_native_usage
project,source,descriptor=map(Path,sys.argv[1:])
binding=json.loads(descriptor.read_text())
armed=True
def trace(frame,event,arg):
    global armed
    if (armed and event=='line' and frame.f_code.co_name=='_consume'
        and frame.f_globals.get('__name__')=='ai_sow_lite.host_usage'
        and frame.f_locals.get('state',{}).get('ordinal')==2):
        armed=False
        print('DURABLE_USAGE',flush=True)
        signal.pause()
    return trace
sys.settrace(trace)
try:
    collect_native_usage(project,binding['request_id'],source_path=source,binding=binding)
except KeyboardInterrupt:
    print('INTERRUPT_PROPAGATED',flush=True)
    raise SystemExit(130)
raise SystemExit(99)
'''
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'runtime'))
    process=subprocess.Popen([sys.executable,'-c',script,str(project),str(source),str(descriptor)],
                             env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        ready,_,_=select.select([process.stdout],[],[],5)
        assert ready,'Collector did not reach the bounded cancellation point'
        assert process.stdout.readline().strip()=='DURABLE_USAGE'
        process.send_signal(signal.SIGINT)
        stdout,stderr=process.communicate(timeout=5)
        assert process.returncode==130 and stdout.strip()=='INTERRUPT_PROPAGATED'
        assert stderr==''
    finally:
        if process.poll() is None:process.kill();process.communicate(timeout=5)
    report=telemetry.build_report(project,selection['request_id'])
    assert 'INTERRUPTED' in report['diagnostics']
    assert metric(report,'known_tokens')['value']==12
    assert report['host_capabilities']['interrupt_signal']=='unverified'
    cursor=json.loads(next((project/'.ai-sow-lite/telemetry').glob('*/cursors/*-native.json')).read_text())
    assert cursor['ordinal']==2
    assert business_bytes(project)==before


def test_default_eight_mib_cap_is_physical_and_no_private_payload_is_copied(tmp_path):
    records=native_records()
    background=[dict(type='response_item',ordinal=i+2,payload={'content':'PRIVATE'*20000}) for i in range(70)]
    records=records[:2]+background+records[2:]
    for i,record in enumerate(records):record['ordinal']=i
    source=tmp_path/'native.jsonl';write_native(source,records)
    assert source.stat().st_size>8*1024*1024
    project=tmp_path/'project';selection=binding(str(uuid4()))
    outcome=collect(project,source,selection)
    assert outcome['read']['bytes_read']<=8*1024*1024
    assert not outcome['read']['eof'] and 'NATIVE_READ_LIMIT' in outcome['gaps']
    outcome=collect(project,source,selection)
    assert outcome['read']['eof']
    persisted=b''.join(p.read_bytes() for p in (project/'.ai-sow-lite/telemetry').rglob('*') if p.is_file())
    assert b'PRIVATE' not in persisted and str(source).encode() not in persisted
