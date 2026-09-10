"""Synthetic accounting fixtures never establish actual desktop host capabilities."""
import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from ai_sow_lite.contracts import canonical_json_bytes, schema_validator

REQUEST = '00000000-0000-4000-8000-000000000001'
EXECUTION = '00000000-0000-4000-8000-000000000002'
PRODUCER = '00000000-0000-4000-8000-000000000003'
ACTIVITY = '00000000-0000-4000-8000-000000000004'


def event(kind='work', sequence=1, **data):
    return dict(schema_version='1.0', event_id=str(uuid4()), event_type=kind,
                request_id=REQUEST, execution_id=EXECUTION, producer_id=PRODUCER,
                sequence=sequence, observed_at='2026-09-09T00:00:00.000000Z',
                activity_ids=[], slice_ids=[], data=data)


def metric(report, name, kind='request'):
    return next(m for m in report['metrics'] if m['name'] == name and m['scope']['kind'] == kind)


def append(project, *events):
    from ai_sow_lite.telemetry import append_event
    for item in events:
        append_event(project, item)


def report(project):
    from ai_sow_lite.telemetry import build_report
    return build_report(project, REQUEST)


def test_empty_usage_is_unknown(tmp_path):
    tokens = metric(report(tmp_path), 'total_tokens')
    assert tokens['value'] is None and tokens['coverage'] == 'unknown'
    assert {'value', 'unit', 'scope', 'basis', 'coverage', 'attribution', 'diagnostics'} <= tokens.keys()
    assert not list(schema_validator('artifacts', 'telemetry_report').iter_errors(report(tmp_path)))


def test_direct_mark_accepts_existing_envelope_and_rejects_extra_content(tmp_path):
    from ai_sow_lite.telemetry import record_mark

    assert record_mark(tmp_path, mark())['recording'] == 'recorded'
    before = report(tmp_path)
    rejected = record_mark(tmp_path, dict(mark('end'), observed_at='2020-01-01T00:00:00Z'))
    assert rejected['recording'] == 'degraded'
    assert report(tmp_path)['event_count'] == before['event_count'] == 1
    assert record_mark(tmp_path, mark('end'))['recording'] == 'recorded'
    rebuilt = report(tmp_path)
    assert rebuilt['event_count'] == 2
    assert metric(rebuilt, 'request_wall_ns')['value'] is not None
    assert metric(rebuilt, 'total_tokens')['value'] is None


def test_direct_mark_storage_failure_is_observation_only(tmp_path):
    from ai_sow_lite.telemetry import record_mark

    (tmp_path / '.ai-sow-lite').write_bytes(b'preserve')
    assert record_mark(tmp_path, mark())['recording'] == 'degraded'
    assert (tmp_path / '.ai-sow-lite').read_bytes() == b'preserve'


def test_event_is_durable_replay_deduplicated_and_report_rebuildable(tmp_path):
    item = event(input_bytes=17, output_bytes=29)
    append(tmp_path, item, item)
    paths = list((tmp_path / '.ai-sow-lite/telemetry').glob('*/events/*/*.jsonl'))
    assert len(paths) == 1 and paths[0].read_bytes() == canonical_json_bytes(item) + b'\n'
    first = report(tmp_path)
    assert first['event_count'] == 1
    assert metric(first, 'input_bytes')['value'] == 17
    assert metric(first, 'output_bytes')['value'] == 29
    assert metric(first, 'total_tokens')['value'] is None
    saved = tmp_path / '.ai-sow-lite/telemetry' / REQUEST / 'report.json'
    assert json.loads(saved.read_bytes()) == first
    saved.unlink()
    assert report(tmp_path)['source_digest'] == first['source_digest']


@pytest.mark.parametrize('change', [dict(prompt='PRIVATE'), dict(arguments={'path':'/private'}),
                                      dict(sequence=-1), dict(schema_version='9.0')])
def test_unapproved_event_fields_never_persist(tmp_path, change):
    item = event(input_bytes=17)
    item.update(change)
    with pytest.raises(ValueError):
        append(tmp_path, item)
    assert not (tmp_path / '.ai-sow-lite').exists()


def request(project, **extra):
    return dict(protocol_version='1.0', request_id=REQUEST, project_path=str(project), operation='inspect',
                payload=dict(view='current', selector={}), **extra)


def existing_request(project, entrypoint='generate'):
    from ai_sow_lite.project import ensure_request, initialize
    template = Path(__file__).resolve().parents[1] / 'assets/sow-template.xlsx'
    initialize(project, 'new', template)
    ensure_request(project, REQUEST, entrypoint)
    return request(project)


def tool_events(project):
    return [json.loads(line) for path in (project / '.ai-sow-lite/telemetry').glob('*/events/*/*.jsonl')
            for line in path.read_bytes().splitlines()]


@pytest.mark.parametrize('context', [dict(execution_id=EXECUTION, activity_ids=[ACTIVITY], slice_ids=[PRODUCER]),
                                   dict(execution_id='/PRIVATE/execution'), None])
def test_invalid_payload_validates_observation_context_independently(tmp_path, context):
    from ai_sow_lite.cli import execute, exit_code
    req = existing_request(tmp_path)
    req['payload']['unapproved'] = 'PRIVATE payload'
    expected = execute(req)
    previous_events = {e['event_id'] for e in tool_events(tmp_path)}
    req['observation_context'] = context

    response = execute(req)

    assert response['diagnostics'] == expected['diagnostics']
    assert not response['ok'] and exit_code(response) == 2
    valid_context = context is not None and context.get('execution_id') == EXECUTION
    observation = response['result']['observation']
    assert observation['gaps'] == ([] if valid_context else ['OBSERVATION_CONTEXT_INVALID'])
    assert observation['recording'] == ('recorded' if valid_context else 'degraded')
    starts = [e for e in tool_events(tmp_path)
              if e['event_id'] not in previous_events and e['data'].get('phase') == 'start']
    assert len(starts) == 1
    labelled = starts[0]
    if valid_context:
        assert labelled['execution_id'] == EXECUTION
        assert labelled['activity_ids'] == [ACTIVITY] and labelled['slice_ids'] == [PRODUCER]
    else:
        assert labelled['activity_ids'] == labelled['slice_ids'] == []
    assert 'PRIVATE' not in json.dumps(tool_events(tmp_path)) + json.dumps(response)


@pytest.mark.parametrize('payload_fields', [{}, {'payload': None}, {'payload': []},
    {'payload': ['PRIVATE']}, {'payload': 'PRIVATE'}, {'payload': 7}, {'payload': True}],
    ids=['missing', 'null', 'empty-array', 'array', 'string', 'integer', 'boolean'])
def test_missing_or_non_object_payload_is_observed_without_changing_rejection(tmp_path, payload_fields):
    from ai_sow_lite.cli import execute, exit_code
    req = existing_request(tmp_path)
    del req['payload']
    req.update(payload_fields)

    response = execute(req)

    assert not response['ok'] and exit_code(response) == 2
    assert response['diagnostics'][0]['code'] == 'PROTOCOL_INVALID'
    assert response['result']['observation']['recording'] == 'recorded'
    ends = [e for e in tool_events(tmp_path) if e['data'].get('phase') == 'end']
    assert len(ends) == 1 and ends[0]['data']['status'] == 'failed'
    assert 'PRIVATE' not in json.dumps(tool_events(tmp_path)) + json.dumps(response)


@pytest.mark.parametrize('operation,payload', [
    ('ingest', {}), ('inspect', {}), ('render', {}), ('apply', {}), ('recover', {}),
    ('ingest', dict(kind='sources', project_type='new', sources=[dict(
        source_path='/PRIVATE/source.md', input_id=None, material_types=['prd'],
        uses=['to-be-scope'], use_regions=[])])),
], ids=['empty-ingest', 'empty-inspect', 'empty-render', 'empty-apply', 'empty-recover',
        'ingest-without-entrypoint'])
@pytest.mark.parametrize('identity_state', ['known', 'unknown-project', 'unknown-request'])
def test_unsupported_payload_observation_requires_existing_identity(
        tmp_path, monkeypatch, operation, payload, identity_state):
    from ai_sow_lite.cli import execute, exit_code
    project = tmp_path / 'project'
    req = request(project) if identity_state == 'unknown-project' else existing_request(project)
    if identity_state == 'unknown-request':
        req['request_id'] = EXECUTION
    req.update(operation=operation, payload=payload,
               observation_context=dict(execution_id=EXECUTION, activity_ids=[ACTIVITY]))
    assert schema_validator('protocol').is_valid(req)  # These are schema-compatible legacy forms.
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    paths_before = set(tmp_path.rglob('*'))
    ticks = iter([100, 160])
    monkeypatch.setattr('time.monotonic_ns', lambda: next(ticks))

    response = execute(req)

    assert not response['ok'] and exit_code(response) == 2
    assert response['diagnostics'] == [dict(code='OPERATION_UNSUPPORTED',
        target=dict(path=None, object_id=None, field='operation'),
        message='尚未实现此操作，或没有提供受支持的 payload 形式。', preserved_paths=[])]
    if identity_state == 'known':
        assert response['result']['observation']['recording'] == 'recorded'
        events = tool_events(project)
        assert len(events) == 3
        ends = [e for e in events if e['data'].get('phase') == 'end']
        assert len(ends) == 1 and ends[0]['data']['status'] == 'failed'
        assert ends[0]['execution_id'] == EXECUTION and ends[0]['activity_ids'] == [ACTIVITY]
        assert metric(report(project), 'tool_duration_ns')['value'] == 60
    else:
        assert set(tmp_path.rglob('*')) == paths_before
        assert response['result'] == {}
    assert {p: p.read_bytes() for p in tmp_path.rglob('*')
            if p.is_file() and 'telemetry' not in p.relative_to(tmp_path).parts} == before


def test_invalid_telemetry_query_records_rejection_without_recursive_reporting(tmp_path):
    from ai_sow_lite.cli import execute
    req = existing_request(tmp_path)
    req['payload'] = dict(view='telemetry', selector={'request_id': REQUEST}, unapproved=True)

    response = execute(req)

    assert response['diagnostics'][0]['code'] == 'PROTOCOL_INVALID'
    assert response['result'].get('observation', {}).get('recording') == 'recorded'
    assert len(tool_events(tmp_path)) == 3
    del req['payload']['unapproved']
    inspected = execute(req)
    assert inspected['ok']
    assert len(tool_events(tmp_path)) == 3


def test_invalid_source_fields_for_existing_request_record_one_redacted_failed_span(tmp_path, monkeypatch):
    from ai_sow_lite.cli import execute, exit_code
    req = existing_request(tmp_path)
    req.update(operation='ingest', payload=dict(kind='sources', entrypoint='generate', project_type='new',
        sources=[dict(source_path='/PRIVATE/source.md', input_version_id=EXECUTION,
                      material_types=['prd'], uses=['to-be-scope'], use_regions=[])]))
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    ticks = iter([100, 160])
    monkeypatch.setattr('time.monotonic_ns', lambda: next(ticks))

    response = execute(req)

    assert not response['ok'] and exit_code(response) == 2
    assert response['diagnostics'] == [dict(code='PROTOCOL_INVALID',
        target=dict(path=None, object_id=None, field=None),
        message='请求信封或操作字段不符合合同。', preserved_paths=[])]
    assert response['result'].get('observation') == dict(recording='recorded', gaps=[],
        report_path=f'.ai-sow-lite/telemetry/{REQUEST}/report.json')
    events = tool_events(tmp_path)
    assert len(events) == 3
    start, end = sorted((e for e in events if e['event_type'] == 'lifecycle'), key=lambda e: e['sequence'])
    assert start['data']['phase'] == 'start' and end['data']['phase'] == 'end'
    assert end['data']['status'] == 'failed'
    assert start['producer_id'] == end['producer_id'] == start['data']['clock_domain'] == end['data']['clock_domain']
    assert start['data']['span_id'] == end['data']['span_id']
    measured = report(tmp_path)
    assert metric(measured, 'tool_duration_ns')['value'] == 60
    assert metric(measured, 'tool_duration_ns')['basis']['kind'] == 'same_process_monotonic'
    assert metric(measured, 'total_tokens')['value'] is None
    # Replaying durable events or rebuilding a report is not a second invocation.
    append(tmp_path, *events)
    assert report(tmp_path)['event_count'] == 3
    assert metric(report(tmp_path), 'tool_duration_ns')['value'] == 60
    assert {p: p.read_bytes() for p in tmp_path.rglob('*')
            if p.is_file() and 'telemetry' not in p.relative_to(tmp_path).parts} == before
    assert all(b'PRIVATE' not in p.read_bytes() and b'input_version_id' not in p.read_bytes()
               for p in (tmp_path / '.ai-sow-lite/telemetry').rglob('*') if p.is_file())


@pytest.mark.parametrize('field,value', [
    ('protocol_version', '9.0'), ('protocol_version', None),
    ('operation', 'PRIVATE'), ('operation', None),
    ('request_id', '../outside'), ('request_id', REQUEST + '\n'),
    ('request_id', 'ABCDEFAB-0000-4000-8000-000000000001'),
    ('request_id', '00000000-0000-1000-8000-000000000001'),
    ('request_id', REQUEST.replace('-', '')), ('request_id', None),
    ('project_path', ''), ('project_path', '  '), ('project_path', None),
    ('project_path', '/PRIVATE/invalid\x00path'),
])
def test_invalid_envelope_identity_never_starts_observation(tmp_path, field, value):
    from ai_sow_lite.cli import execute, exit_code
    req = existing_request(tmp_path)
    req.update(payload=None, observation_context=dict(execution_id=EXECUTION))
    req[field] = value
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}

    response = execute(req)

    expected_code = 'VERSION_INCOMPATIBLE' if field == 'protocol_version' and value == '9.0' else 'PROTOCOL_INVALID'
    assert not response['ok'] and exit_code(response) == 2
    assert response['diagnostics'][0]['code'] == expected_code
    assert response['result'] == {}
    assert not (tmp_path / '.ai-sow-lite/telemetry').exists()
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('damage', [
    'unknown-request', 'missing-project-path', 'project-path-file', 'other-project',
    'missing-project-record', 'invalid-project-record', 'missing-request-record',
    'invalid-request-record', 'mismatched-request-id', 'mismatched-entrypoint',
    'ambiguous-entrypoint', 'request-record-directory',
    'project-root-link', 'project-record-link', 'request-record-link',
])
def test_invalid_payload_requires_existing_safe_matching_project_and_request(tmp_path, damage):
    from ai_sow_lite.cli import execute
    project = tmp_path / 'project'
    req = existing_request(project)
    req['payload'] = ['PRIVATE']
    root = project / '.ai-sow-lite'
    marker = root / 'work/generate' / REQUEST / 'request.json'
    project_record = root / 'project.json'
    if damage == 'unknown-request':
        req['request_id'] = EXECUTION
    elif damage == 'missing-project-path':
        req['project_path'] = str(tmp_path / 'missing')
    elif damage == 'project-path-file':
        req['project_path'] = str(project_record)
    elif damage == 'other-project':
        other = tmp_path / 'other'
        other.mkdir()
        req['project_path'] = str(other)
    elif damage == 'missing-project-record':
        project_record.unlink()
    elif damage == 'invalid-project-record':
        project_record.write_bytes(b'{"schema_version":"9.0"}')
    elif damage == 'missing-request-record':
        marker.unlink()
    elif damage == 'invalid-request-record':
        marker.write_bytes(b'{"PRIVATE":')
    elif damage in ('mismatched-request-id', 'mismatched-entrypoint', 'ambiguous-entrypoint'):
        record = json.loads(marker.read_bytes())
        if damage == 'mismatched-request-id':
            record['request_id'] = EXECUTION
        else:
            record['entrypoint'] = 'clarify'
        if damage == 'ambiguous-entrypoint':
            marker = root / 'work/clarify' / REQUEST / 'request.json'
            marker.parent.mkdir(parents=True)
        marker.write_bytes(canonical_json_bytes(record))
    elif damage == 'request-record-directory':
        marker.unlink()
        marker.mkdir()
    else:
        target = {'project-root-link': root, 'project-record-link': project_record,
                  'request-record-link': marker}[damage]
        outside = tmp_path / 'outside'
        target.rename(outside)
        target.symlink_to(outside, target_is_directory=outside.is_dir())
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    paths_before = set(tmp_path.rglob('*'))

    response = execute(req)

    assert response['diagnostics'][0]['code'] == 'PROTOCOL_INVALID'
    assert response['result'] == {}
    assert set(tmp_path.rglob('*')) == paths_before
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('entrypoint', ['generate', 'clarify'])
def test_initial_valid_ingest_and_later_rejection_both_keep_observation(tmp_path, entrypoint):
    from ai_sow_lite.cli import execute
    project = tmp_path / 'new-project'
    req = request(project)
    source = Path(__file__).parent / 'fixtures/generate/prd.md'
    req.update(operation='ingest', payload=dict(kind='sources', entrypoint=entrypoint, project_type='new',
        sources=[dict(source_path=str(source), input_id=None, material_types=['prd'],
                      uses=['to-be-scope'], use_regions=[])]))
    assert not project.exists()

    registered = execute(req)

    assert registered['ok'] and registered['result']['observation']['recording'] == 'recorded'
    assert len(tool_events(project)) == 3
    req['payload'] = None
    rejected = execute(req)
    assert rejected['diagnostics'][0]['code'] == 'PROTOCOL_INVALID'
    assert rejected['result']['observation']['recording'] == 'recorded'
    ends = [e for e in tool_events(project) if e['data'].get('phase') == 'end']
    assert sorted(e['data']['status'] for e in ends) == ['failed', 'succeeded']
    assert len(tool_events(project)) == 6


@pytest.mark.parametrize('mode', ['file', 'symlink', 'disk_full'])
def test_invalid_payload_observation_failure_keeps_original_business_diagnostic(tmp_path, monkeypatch, mode):
    from ai_sow_lite import cli, telemetry
    req = existing_request(tmp_path)
    req['payload'] = 'PRIVATE'
    area = tmp_path / '.ai-sow-lite/telemetry'
    outside = tmp_path / 'outside'
    outside.mkdir()
    if mode == 'file':
        area.write_bytes(b'obstruction')
    elif mode == 'symlink':
        area.symlink_to(outside, target_is_directory=True)
    else:
        def fail(*args, **kwargs):
            raise OSError('PRIVATE disk full')
        monkeypatch.setattr(telemetry, 'append_event', fail)

    response = cli.execute(req)

    assert not response['ok'] and cli.exit_code(response) == 2
    assert response['diagnostics'][0]['code'] == 'PROTOCOL_INVALID'
    assert response['result']['observation'] == dict(recording='degraded',
        gaps=['TELEMETRY_RECORDING_FAILED'], report_path=None)
    assert not list(outside.iterdir())
    assert 'PRIVATE' not in json.dumps(response)


def test_invalid_payload_after_cancellation_does_not_reclassify_or_change_state(tmp_path):
    from ai_sow_lite.cli import execute
    from ai_sow_lite.project import cancel_request, recover_request
    req = existing_request(tmp_path)
    cancel_request(tmp_path, REQUEST, 'generate')
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    req['payload'] = None

    response = execute(req)

    assert response['diagnostics'][0]['code'] == 'PROTOCOL_INVALID'
    ends = [e for e in tool_events(tmp_path) if e['data'].get('phase') == 'end']
    assert len(ends) == 1 and ends[0]['data']['status'] == 'failed'
    assert recover_request(tmp_path, REQUEST)['state'] == 'cancelled'
    assert {p: p.read_bytes() for p in tmp_path.rglob('*')
            if p.is_file() and 'telemetry' not in p.relative_to(tmp_path).parts} == before


def lifecycle(name, phase, ns, *, span=None, parent=None, domain=PRODUCER, sequence=1, status=None):
    item = event('lifecycle', sequence, name=name, phase=phase, span_id=span or ACTIVITY,
                 parent_span_id=parent, clock_domain=domain, monotonic_ns=ns,
                 status=status, operation_id=None, attempt_id=None, host_call_id=None)
    return item


def test_execute_records_real_attempts_bytes_and_redacted_business_failure(tmp_path):
    from ai_sow_lite.cli import execute, exit_code
    # A valid query of an uninitialised project genuinely fails. It still has a cost.
    first = execute(request(tmp_path))
    second = execute(request(tmp_path))
    assert not first['ok'] and exit_code(first) == 3
    assert set(first) == {'ok','request_id','operation','result','diagnostics'}
    assert first['result']['observation'] == dict(recording='recorded', gaps=[],
        report_path=f'.ai-sow-lite/telemetry/{REQUEST}/report.json')
    paths = list((tmp_path / '.ai-sow-lite/telemetry').glob('*/events/*/*.jsonl'))
    assert len(paths) == 2  # distinct actual writers, even for the same business query
    events = [json.loads(line) for p in paths for line in p.read_bytes().splitlines()]
    starts = [e for e in events if e['event_type']=='lifecycle' and e['data']['phase']=='start']
    ends = [e for e in events if e['event_type']=='lifecycle' and e['data']['phase']=='end']
    assert len(starts) == len(ends) == 2
    assert len({e['data']['attempt_id'] for e in starts}) == 2
    assert len({e['execution_id'] for e in starts}) == 2
    assert all(e['data']['host_call_id'] is None for e in starts)
    assert all(e['data']['status']=='failed' for e in ends)
    assert metric(report(tmp_path), 'tool_duration_ns')['value'] > 0
    assert metric(report(tmp_path), 'input_bytes')['value'] > 0
    assert metric(report(tmp_path), 'model_duration_ns')['value'] is None


def run_mark(tmp_path, mark):
    import os
    import subprocess
    import sys
    path = tmp_path / 'mark.json'
    path.write_bytes(canonical_json_bytes(mark))
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'runtime'))
    return subprocess.run([sys.executable, '-m', 'ai_sow_lite.telemetry', '--project',str(tmp_path),
                           '--mark-file',str(path)],env=env,cwd=tmp_path,capture_output=True,timeout=10)


def mark(phase='start', **extra):
    return dict(schema_version='1.0',request_id=REQUEST,execution_id=EXECUTION,activity_ids=[],
                slice_ids=[],phase=phase,name='request',**extra)


def test_request_marks_two_processes_are_wall_observations_and_rebuild(tmp_path):
    assert run_mark(tmp_path,mark()).returncode == 0
    assert run_mark(tmp_path,mark('end')).returncode == 0
    r = json.loads((tmp_path / '.ai-sow-lite/telemetry' / REQUEST / 'report.json').read_bytes())
    assert metric(r, 'request_wall_ns')['value'] > 0
    assert metric(r, 'request_wall_ns')['basis']['kind'] == 'utc_observed_interval'
    assert metric(r, 'model_duration_ns')['value'] is None
    assert metric(r, 'tool_duration_ns')['value'] is None
    assert r['event_count'] == 2  # no recorder self-observation
    assert not (tmp_path / '.ai-sow-lite/current.json').exists()


@pytest.mark.parametrize('extra', [dict(total_tokens=123),dict(name='/private/customer'),dict(activity_ids=['PRIVATE'])])
def test_mark_rejects_extra_content_and_never_writes_business(tmp_path, extra):
    m=mark(); m.update(extra)
    response=run_mark(tmp_path,m)
    assert response.returncode == 0  # observation command degrades; no business exit/retry
    assert json.loads(response.stdout)['recording'] == 'degraded'
    assert not (tmp_path / '.ai-sow-lite').exists()
    assert b'PRIVATE' not in response.stdout and b'/private/customer' not in response.stdout


def test_unmatched_marks_and_cross_clock_tools_are_incomplete(tmp_path):
    append(tmp_path,lifecycle('tool','start',10),lifecycle('tool','end',20,domain=str(uuid4())))
    r=report(tmp_path)
    assert metric(r,'tool_duration_ns')['value'] is None
    assert 'CLOCK_UNALIGNED' in r['diagnostics']
    assert run_mark(tmp_path,mark('end')).returncode == 0
    assert 'LIFECYCLE_INCOMPLETE' in report(tmp_path)['diagnostics']


def test_invalid_observation_degrades_only_after_business_envelope_validation(tmp_path):
    from ai_sow_lite.cli import execute
    r=execute(request(tmp_path,observation_context={'execution_id':'/private/customer'}))
    assert r['diagnostics'][0]['code']=='IO_FAILED'
    assert r['result']['observation']['gaps']==['OBSERVATION_CONTEXT_INVALID']
    invalid=request(tmp_path / 'invalid',observation_context={'execution_id':'bad'})
    invalid['payload']['unapproved']=True
    r=execute(invalid)
    assert r['diagnostics'][0]['code']=='PROTOCOL_INVALID'
    assert not (tmp_path / 'invalid').exists()


def test_cancellation_cost_and_keyboard_interrupt_are_recorded_once(tmp_path, monkeypatch):
    from ai_sow_lite import cli
    def cancelled(_):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli,'_execute',cancelled)
    with pytest.raises(KeyboardInterrupt):
        cli.execute(request(tmp_path))
    ends=[json.loads(line) for p in (tmp_path/'.ai-sow-lite/telemetry').glob('*/events/*/*.jsonl')
          for line in p.read_bytes().splitlines() if json.loads(line)['data'].get('phase')=='end']
    assert len(ends)==1 and ends[0]['data']['status']=='interrupted'
    assert metric(report(tmp_path),'tool_duration_ns')['value'] > 0


def snapshots():
    fixture=json.loads((Path(__file__).parent/'fixtures/telemetry/ex06-synthetic.json').read_bytes())
    result=[]
    for i,s in enumerate(fixture['snapshots']):
        e=event('usage',i,source=fixture['source'],scope_kind='thread',scope_id='synthetic-thread',
                counter_epoch='E1',native_event_id=s['id'],source_sequence=i,revision=0,
                observation_kind='cumulative',host_call_id=None,counts=s['counts'],
                coverage=dict(start=None if i==0 else f'B{i-1}',end=s['id'],boundary=s['boundary'],
                              complete=True,exclusive=True))
        e['activity_ids']=s['activities']; result.append(e)
    return result


def test_ex06_duplicate_out_of_order_cumulative_and_shared_accounting(tmp_path):
    b=snapshots(); append(tmp_path,b[0],b[2],b[2],b[1],b[3])
    r=report(tmp_path)
    for field,want in [('total_tokens',6000),('input_tokens',4800),('output_tokens',1200),
                       ('cached_input_tokens',2200),('reasoning_output_tokens',350)]:
        m=metric(r,field); assert m['value']==want and m['coverage']=='complete'
    groups=[m for m in r['metrics'] if m['name']=='total_tokens' and m['scope']['kind']=='activity_group']
    assert sorted((m['value'],m['attribution']) for m in groups)==[(800,'shared'),(1500,'exclusive'),(3700,'shared')]
    assert metric(r,'model_call_count')['value'] is None
    assert all(v=='unverified' for v in r['host_capabilities'].values())
    assert r['sources'][0]['source_kind']=='synthetic'


@pytest.mark.parametrize('variant,want,known,gap',[
    ('missing_start',None,4500,'USAGE_START_UNKNOWN'),
    ('missing_end',5200,5200,'USAGE_END_UNKNOWN'),
    ('mixed',2300,2300,'USAGE_MIXED_SCOPE'),
    ('reset',None,2300,'USAGE_START_UNKNOWN'),
    ('decrease',None,1500,'COUNTER_DECREASED'),
    ('unknown_semantics',None,None,'SOURCE_UNVERIFIED'),
    ('version_change',None,None,'SOURCE_VERSION_CHANGED'),
])
def test_usage_boundaries_epochs_and_unknown_sources(tmp_path,variant,want,known,gap):
    b=snapshots()
    if variant=='missing_start': b=b[1:]
    elif variant=='missing_end': b=b[:-1]
    elif variant=='mixed': b[2]['data']['coverage']['exclusive']=False
    elif variant=='reset':
        for e in b[2:]: e['data']['counter_epoch']='E2'
    elif variant=='decrease':
        for field in b[2]['data']['counts']: b[2]['data']['counts'][field]=1
        b[2]['data']['counts']['total_tokens']=2
        # B2→B3 is also uncertain after an unexplained decrease, never enormous inferred cost.
    elif variant=='unknown_semantics':
        for e in b: e['data']['source']['semantics']='unverified'
    elif variant=='version_change':
        b=copy.deepcopy(b)
        b[2]['data']['source']=dict(b[2]['data']['source'],producer_version='future')
    append(tmp_path,*b)
    r=report(tmp_path)
    assert metric(r,'total_tokens')['value']==want
    if variant=='decrease':
        assert metric(r,'known_tokens')['value']==1500
    else:
        assert metric(r,'known_tokens')['value']==known
    assert metric(r,'total_tokens')['coverage']!='complete'
    assert gap in r['diagnostics']


def calls():
    base=snapshots()[0]
    base['data']['source']['capabilities']['call_identity']='verified'
    result=[]
    for seq,call,revision,count in [(1,'C1',1,600),(2,'C1',2,700),(3,'C2',1,500)]:
        e=copy.deepcopy(base); e['event_id']=str(uuid4()); e['sequence']=seq
        e['data'].update(scope_kind='call',scope_id=call,host_call_id=call,observation_kind='call_absolute',
                         native_event_id=f'{call}-{revision}',source_sequence=seq,revision=revision,
                         counts={'total_tokens':count},coverage=dict(start=call,end=call,boundary='interval',complete=revision==2 or call=='C2',exclusive=True))
        e['data']['source']['semantics']='native_total'
        result.append(e)
    return result


def test_call_revisions_real_retry_and_secondary_parent_are_not_added_twice(tmp_path):
    c=calls(); parent=copy.deepcopy(c[-1]); parent['event_id']=str(uuid4());parent['sequence']=4
    parent['data']['source']=copy.deepcopy(parent['data']['source']);parent['data']['source'].update(source_id=str(uuid4()),role='cross_check')
    parent['data'].update(scope_kind='request',scope_id=REQUEST,host_call_id=None,native_event_id='parent',counts={'total_tokens':1200})
    append(tmp_path,c[1],c[1],c[0],c[2],parent)
    r=report(tmp_path)
    assert metric(r,'total_tokens')['value']==1200
    assert metric(r,'model_call_count')['value']==2
    assert metric(r,'total_tokens')['coverage']=='partial' # all observed calls isn't a full request denominator


@pytest.mark.parametrize('change', ['no_revision','conflicting_revision','overlapping_sources','inconsistent_fields'])
def test_ambiguous_usage_never_guesses_latest_or_double_counts(tmp_path,change):
    c=calls()
    if change=='no_revision': c[1]['data']['revision']=None
    elif change=='conflicting_revision': c[1]['data']['revision']=1
    elif change=='overlapping_sources':
        d=copy.deepcopy(c[-1]);d['event_id']=str(uuid4());d['sequence']=4;d['data']['source']['source_id']=str(uuid4());c.append(d)
    else:
        c[1]['data']['source']['semantics']='total_is_input_plus_output'
        c[1]['data']['counts'].update(input_tokens=700,output_tokens=100)
    append(tmp_path,*c)
    r=report(tmp_path)
    assert metric(r,'total_tokens')['value'] is None
    assert r['diagnostics']


def test_total_derived_only_with_verified_disjoint_input_output(tmp_path):
    c=calls()[-1]; c['data']['counts']={'input_tokens':400,'output_tokens':100,'cached_input_tokens':200}
    c['data']['source']['semantics']='total_is_input_plus_output'
    append(tmp_path,c)
    r=report(tmp_path)
    assert metric(r,'total_tokens')['value']==500
    assert 'derived' in metric(r,'total_tokens')['basis']['kind']


def test_ex06_union_wait_and_parent_exclusion(tmp_path):
    spans=[('activity',0,30,ACTIVITY,None),('tool',2,12,str(uuid4()),ACTIVITY),
           ('tool',8,18,str(uuid4()),ACTIVITY),('user_wait',30,90,str(uuid4()),None),
           ('processing',0,30,str(uuid4()),None),('processing',90,110,str(uuid4()),None)]
    events=[]
    for name,left,right,identity,parent in spans:
        events.extend([lifecycle(name,'start',left*10**9,span=identity,parent=parent),
                       lifecycle(name,'end',right*10**9,span=identity,parent=parent)])
    append(tmp_path,*events)
    r=report(tmp_path)
    assert metric(r,'tool_duration_ns')['value']==20*10**9
    assert metric(r,'tool_union_ns')['value']==16*10**9
    assert metric(r,'processing_ns')['value']==50*10**9
    assert metric(r,'user_wait_ns')['value']==60*10**9
    assert metric(r,'exclusive_duration_ns','span')['value']==14*10**9
    # Missing end invalidates union/exclusive, but retains the complete tool A.
    other=tmp_path/'incomplete'; append(other,*[e for e in events if e is not events[5]])
    r=report(other)
    assert metric(r,'tool_union_ns')['value'] is None
    assert metric(r,'exclusive_duration_ns','span')['value'] is None
    assert metric(r,'tool_duration_ns')['value']==10*10**9


def test_cursor_advances_only_after_durable_event_and_replay_deduplicates(tmp_path,monkeypatch):
    from ai_sow_lite import telemetry
    b=snapshots(); real=telemetry.atomic_bytes
    def fail_cursor(path,raw,**kwargs):
        if path.parent.name=='cursors': raise OSError('PRIVATE ENOSPC')
        return real(path,raw,**kwargs)
    monkeypatch.setattr(telemetry,'atomic_bytes',fail_cursor)
    with pytest.raises(OSError): append(tmp_path,b[0])
    files=list((tmp_path/'.ai-sow-lite/telemetry').glob('*/events/*/*.jsonl'))
    assert len(files)==1 and b'B0' in files[0].read_bytes()
    monkeypatch.setattr(telemetry,'atomic_bytes',real)
    append(tmp_path,b[0],b[1],b[0])
    cursor=json.loads(next((tmp_path/'.ai-sow-lite/telemetry').glob('*/cursors/*.json')).read_bytes())
    assert cursor['source_sequence']==1 and cursor['native_event_id']=='B1'
    assert report(tmp_path)['event_count']==2


@pytest.mark.parametrize('middle,gap', [(False,'EVENT_TAIL_INCOMPLETE'),(True,'EVENT_MIDDLE_CORRUPT')])
def test_corrupt_jsonl_keeps_complete_prefix_visible_and_does_not_append_over_tail(tmp_path,middle,gap):
    item=event(input_bytes=17);append(tmp_path,item)
    path=next((tmp_path/'.ai-sow-lite/telemetry').glob('*/events/*/*.jsonl'))
    with path.open('ab') as f:
        f.write(b'{"private":"secret"' + (b'\n'+canonical_json_bytes(event(output_bytes=29))+b'\n' if middle else b''))
    r=report(tmp_path)
    assert gap in r['diagnostics'] and r['coverage']=='partial'
    assert metric(r,'input_bytes')['value']==17
    with pytest.raises(ValueError):append(tmp_path,event(input_bytes=1))
    assert 'secret' not in (tmp_path/'.ai-sow-lite/telemetry'/REQUEST/'report.md').read_text()


def test_report_limits_are_finite_and_never_claim_complete_usage(tmp_path,monkeypatch):
    from ai_sow_lite import telemetry
    append(tmp_path,*snapshots())
    monkeypatch.setattr(telemetry,'MAX_EVENTS',2)
    r=report(tmp_path)
    assert r['event_count']==2 and 'READ_LIMIT' in r['diagnostics']
    assert metric(r,'total_tokens')['coverage']!='complete'
    monkeypatch.setattr(telemetry,'MAX_EVENTS',10000)
    monkeypatch.setattr(telemetry,'MAX_BYTES',10)
    r=report(tmp_path)
    assert r['event_count']==0 and 'READ_LIMIT' in r['diagnostics']


@pytest.mark.parametrize('mode',['file','symlink','disk_full'])
def test_observation_failure_preserves_actual_business_result_once(tmp_path,monkeypatch,mode):
    from ai_sow_lite import cli,telemetry
    # Real valid recover of a missing request is an inexpensive successful business call.
    req=request(tmp_path);req.update(operation='recover',payload={'target_request_id':REQUEST})
    root=tmp_path/'.ai-sow-lite';root.mkdir()
    outside=tmp_path/'outside';outside.mkdir()
    if mode=='file': (root/'telemetry').write_text('obstruction')
    elif mode=='symlink': (root/'telemetry').symlink_to(outside,target_is_directory=True)
    else:
        def fail(*args,**kwargs): raise OSError('PRIVATE disk full /private/path')
        monkeypatch.setattr(telemetry,'append_event',fail)
    r=cli.execute(req)
    assert r['ok'] and cli.exit_code(r)==0
    assert r['result']['state']=='draft'
    assert r['result']['observation']['gaps']==['TELEMETRY_RECORDING_FAILED']
    assert r['diagnostics']==[] and not list(outside.iterdir())
    assert 'PRIVATE' not in json.dumps(r)


def test_late_usage_and_telemetry_inspect_touch_no_business_bytes(tmp_path):
    from ai_sow_lite.cli import execute
    business=tmp_path/'.ai-sow-lite/versions'/EXECUTION;business.mkdir(parents=True)
    for name in ['model.json','sow.xlsx','manifest.json','summary.md']:(business/name).write_bytes(b'sealed-'+name.encode())
    current=tmp_path/'.ai-sow-lite/current.json';current.write_bytes(b'sealed-current')
    before={p:p.read_bytes() for p in (tmp_path/'.ai-sow-lite').rglob('*') if p.is_file()}
    b=snapshots();append(tmp_path,*b[:-1]); assert metric(report(tmp_path),'total_tokens')['value']==5200
    append(tmp_path,b[-1])
    req=request(tmp_path);req['payload']=dict(view='telemetry',selector={'request_id':REQUEST},limit=2,cursor=None)
    r=execute(req)
    assert r['ok'] and r['result']['report_ref']['path']==f'.ai-sow-lite/telemetry/{REQUEST}/report.json'
    assert r['result']['returned_count']==2 and r['result']['next_cursor']
    assert metric(report(tmp_path),'total_tokens')['value']==6000
    assert all(p.read_bytes()==raw for p,raw in before.items())
    assert {p for p in (tmp_path/'.ai-sow-lite').rglob('*') if p.is_file() and 'telemetry' not in p.parts}==set(before)


def test_telemetry_inspect_cursor_is_bound_to_source_events(tmp_path):
    from ai_sow_lite.cli import execute
    append(tmp_path,*snapshots())
    req=request(tmp_path);req['payload']=dict(view='telemetry',selector={'request_id':REQUEST},limit=2,cursor=None)
    first=execute(req)
    req['payload']['cursor']=first['result']['next_cursor']
    second=execute(req)
    assert second['ok'] and second['result']['coverage']['start_offset']==2
    append(tmp_path,event(input_bytes=3))
    stale=execute(req)
    assert not stale['ok'] and stale['diagnostics'][0]['code']=='VERSION_INCOMPATIBLE'


@pytest.mark.parametrize('mutation', ['negative','bool','unknown_version','native_missing','scope_missing'])
def test_usage_illegal_counts_rejected_unknown_identity_diagnosed(tmp_path,mutation):
    b=snapshots()[0]
    if mutation=='negative':b['data']['counts']['total_tokens']=-1
    elif mutation=='bool':b['data']['counts']['total_tokens']=True
    elif mutation=='unknown_version':b['data']['source']['source_schema_version']='future'
    elif mutation=='native_missing':b['data']['native_event_id']=None
    else:b['data']['scope_id']=None
    if mutation in ['negative','bool']:
        with pytest.raises(ValueError):append(tmp_path,b)
        assert not (tmp_path/'.ai-sow-lite').exists()
    else:
        append(tmp_path,b);r=report(tmp_path)
        assert metric(r,'total_tokens')['value'] is None and r['diagnostics']


def test_same_native_replay_different_writer_is_deduped_without_new_call(tmp_path):
    c=calls();append(tmp_path,*c)
    replay=copy.deepcopy(c[-1]);replay.update(event_id=str(uuid4()),producer_id=str(uuid4()))
    append(tmp_path,replay)
    assert metric(report(tmp_path),'total_tokens')['value']==1200
    assert metric(report(tmp_path),'model_call_count')['value']==2


def test_missing_intermediate_boundary_does_not_claim_exclusive_scope(tmp_path):
    b=snapshots();append(tmp_path,b[0],b[2],b[3])
    r=report(tmp_path)
    assert metric(r,'total_tokens')['coverage']!='complete'
    assert metric(r,'known_tokens')['value']==800
    assert 'USAGE_BOUNDARY_UNKNOWN' in r['diagnostics']


def test_cross_domain_or_incomplete_wait_has_no_fabricated_union(tmp_path):
    a=str(uuid4());b=str(uuid4())
    append(tmp_path,lifecycle('user_wait','start',0,span=a),lifecycle('user_wait','end',10,span=a),
           lifecycle('user_wait','start',2,span=b,domain=EXECUTION),lifecycle('user_wait','end',12,span=b,domain=EXECUTION))
    r=report(tmp_path)
    assert metric(r,'user_wait_ns')['value'] is None


def test_gap_event_persists_recording_loss_in_report(tmp_path):
    append(tmp_path,event('gap',code='SOURCE_UNAVAILABLE',recoverable=True))
    r=report(tmp_path)
    assert 'SOURCE_UNAVAILABLE' in r['diagnostics']
    assert metric(r,'total_tokens')['value'] is None


def test_cumulative_requires_every_interval_complete_and_preserves_basis(tmp_path):
    b=snapshots();b[1]['data']['coverage']['complete']=False
    append(tmp_path,*b);r=report(tmp_path)
    assert metric(r,'total_tokens')['coverage']=='partial'
    assert 'USAGE_INTERVAL_INCOMPLETE' in r['diagnostics']
    assert metric(r,'total_tokens')['basis']['source_id']==b[0]['data']['source']['source_id']
    assert metric(r,'total_tokens')['basis']['start']=='B0'
    assert metric(r,'total_tokens')['basis']['end']=='B3'


def test_delta_overlap_rejected_even_when_boundary_ids_differ(tmp_path):
    b=snapshots()[1:3]
    for e in b:e['data']['observation_kind']='delta'
    b[0]['data']['coverage'].update(start='B0',end='B2')
    b[1]['data']['coverage'].update(start='B1',end='B3')
    append(tmp_path,*b)
    assert metric(report(tmp_path),'total_tokens')['value'] is None
    assert 'USAGE_DELTA_OVERLAP' in report(tmp_path)['diagnostics']


def test_explicit_chained_deltas_and_missing_total_are_never_char_estimates(tmp_path):
    b=snapshots()[1:3]
    for e,count in zip(b,[1500,3700]):
        e['data'].update(observation_kind='delta',counts={'total_tokens':count})
        e['data']['source']['semantics']='native_total'
    append(tmp_path,*b)
    assert metric(report(tmp_path),'total_tokens')['value']==5200
    assert metric(report(tmp_path),'total_tokens')['coverage']=='partial'


def test_same_claimed_clock_but_different_writers_and_mismatched_attempt_are_unknown(tmp_path):
    start=lifecycle('tool','start',10);end=lifecycle('tool','end',20)
    end['producer_id']=str(uuid4())
    append(tmp_path,start,end)
    assert metric(report(tmp_path),'tool_duration_ns')['value'] is None
    other=tmp_path/'other';end['producer_id']=PRODUCER;end['data']['attempt_id']=str(uuid4())
    append(other,start,end)
    assert metric(report(other),'tool_duration_ns')['value'] is None


def test_utc_wait_marks_are_observed_wait_not_monotonic_time(tmp_path):
    a=mark();a['name']='user_wait';b=dict(a,phase='end')
    run_mark(tmp_path,a);run_mark(tmp_path,b)
    m=metric(report(tmp_path),'user_wait_ns')
    assert m['value'] > 0 and m['basis']['kind']=='utc_observed_union'


def test_report_metric_cap_is_visible_and_inspect_can_page(tmp_path,monkeypatch):
    from ai_sow_lite import telemetry
    append(tmp_path,*snapshots())
    monkeypatch.setattr(telemetry,'MAX_METRICS',12,raising=False)
    r=report(tmp_path)
    assert len(r['metrics'])==12 and 'REPORT_LIMIT' in r['diagnostics']
    assert r['limits']['max_metrics']==12


def test_recording_gap_survives_next_report_rebuild(tmp_path,monkeypatch):
    from ai_sow_lite import cli,telemetry
    real=telemetry.append_event
    def fail_start(project,e):
        if e['data'].get('phase')=='start':raise OSError('disk full')
        return real(project,e)
    monkeypatch.setattr(telemetry,'append_event',fail_start)
    r=cli.execute(request(tmp_path))
    assert r['result']['observation']['recording']=='degraded'
    assert 'TELEMETRY_RECORDING_FAILED' in report(tmp_path)['diagnostics']


def test_lifecycle_negative_end_and_missing_end_preserve_unknown_span(tmp_path):
    append(tmp_path,lifecycle('tool','start',20),lifecycle('tool','end',10))
    assert metric(report(tmp_path),'tool_duration_ns')['value'] is None
    assert 'CLOCK_REVERSED' in report(tmp_path)['diagnostics']
    other=tmp_path/'unfinished';append(other,lifecycle('tool','start',20))
    m=metric(report(other),'duration_ns','span')
    assert m['value'] is None and 'LIFECYCLE_INCOMPLETE' in m['diagnostics']


def test_interrupt_after_pointer_commit_retains_applied_fact_and_no_cancellation_claim(tmp_path,monkeypatch):
    from ai_sow_lite import cli,project as storage,telemetry
    from .support.fixtures import storage_package
    package=storage_package(tmp_path)
    real=storage.replace_current
    def interrupt_after_commit(root,pointer):
        real(root,pointer)
        raise KeyboardInterrupt
    monkeypatch.setattr(storage,'replace_current',interrupt_after_commit)
    def commit(_):
        storage._commit_version(**package)
    monkeypatch.setattr(cli,'_execute',commit)
    req=request(tmp_path);req['request_id']=package['request_id']
    with pytest.raises(KeyboardInterrupt):cli.execute(req)
    assert storage.recover_request(tmp_path,package['request_id'])['state']=='applied'
    before={p:p.read_bytes() for p in (tmp_path/'.ai-sow-lite').rglob('*') if p.is_file() and 'telemetry' not in p.parts}
    telemetry.build_report(tmp_path,package['request_id'])
    ends=[json.loads(line) for p in (tmp_path/'.ai-sow-lite/telemetry').glob('*/events/*/*.jsonl') for line in p.read_bytes().splitlines() if json.loads(line)['data'].get('phase')=='end']
    assert ends[0]['data']['status']=='interrupted'
    assert not list((tmp_path/'.ai-sow-lite').rglob('cancelled.json'))
    assert all(p.read_bytes()==raw for p,raw in before.items())


def test_inspect_telemetry_invalid_optional_metadata_reports_gap_without_recursion(tmp_path):
    from ai_sow_lite.cli import execute
    req=request(tmp_path,observation_context={'execution_id':'bad'})
    req['payload']=dict(view='telemetry',selector={'request_id':REQUEST})
    r=execute(req)
    assert r['ok'] and r['result']['observation']['gaps']==['OBSERVATION_CONTEXT_INVALID']
    assert report(tmp_path)['event_count']==0


@pytest.mark.parametrize('field',['request_id','observed_at','producer_version','native_event_id'])
def test_telemetry_machine_tokens_reject_trailing_lf_in_schema_and_append(tmp_path,field):
    e=snapshots()[0]
    owner=e if field in ('request_id','observed_at') else e['data']['source'] if field=='producer_version' else e['data']
    owner[field]+='\n'
    assert not schema_validator('artifacts','telemetry_event').is_valid(e)
    with pytest.raises(ValueError):append(tmp_path,e)
    assert not (tmp_path/'.ai-sow-lite').exists()


@pytest.mark.parametrize('changed_identity', ['producer_id', 'execution_id', 'both'])
def test_review_distinct_clock_owners_keep_duration_but_not_union(tmp_path, changed_identity):
    events = []
    for index, (left, right) in enumerate([(2, 12), (8, 18)]):
        span = str(uuid4())
        pair = [lifecycle('tool', 'start', left, span=span),
                lifecycle('tool', 'end', right, span=span)]
        if index:
            for field in ('producer_id', 'execution_id'):
                if changed_identity in (field, 'both'):
                    identity = str(uuid4())
                    for item in pair:
                        item[field] = identity
        events.extend(pair)
    append(tmp_path, *events)
    result = report(tmp_path)
    assert metric(result, 'tool_duration_ns')['value'] == 20
    union = metric(result, 'tool_union_ns')
    assert union['value'] is None
    assert 'CLOCK_UNALIGNED' in union['diagnostics']
    assert 'CLOCK_UNALIGNED' in result['diagnostics']


@pytest.mark.parametrize('changed_identity', ['producer_id', 'execution_id'])
def test_review_parent_cannot_subtract_a_different_clock_owner(tmp_path, changed_identity):
    parent = [lifecycle('activity', 'start', 0), lifecycle('activity', 'end', 30)]
    child_id, owner = str(uuid4()), str(uuid4())
    children = [lifecycle('tool', 'start', 2, span=child_id, parent=ACTIVITY),
                lifecycle('tool', 'end', 12, span=child_id, parent=ACTIVITY)]
    for item in children:
        item[changed_identity] = owner
    append(tmp_path, *parent, *children)
    result = report(tmp_path)
    assert metric(result, 'tool_duration_ns')['value'] == 10
    exclusive = metric(result, 'exclusive_duration_ns', 'span')
    assert exclusive['value'] is None
    assert 'CLOCK_UNALIGNED' in exclusive['diagnostics']
    assert 'CLOCK_UNALIGNED' in result['diagnostics']


@pytest.mark.parametrize('boundaries', [('B0', 'B1', 'B0'), ('B0', 'B0')])
def test_review_explicit_deltas_cannot_revisit_a_native_boundary(tmp_path, boundaries):
    items = snapshots()[1:len(boundaries)]
    for item, start, end, count in zip(items, boundaries, boundaries[1:], [100, 200]):
        item['data'].update(observation_kind='delta', counts={'total_tokens': count})
        item['data']['source']['semantics'] = 'native_total'
        item['data']['coverage'].update(start=start, end=end)
    append(tmp_path, *items)
    result = report(tmp_path)
    assert metric(result, 'total_tokens')['value'] is None
    assert metric(result, 'known_tokens')['value'] is None
    assert 'USAGE_DELTA_OVERLAP' in result['diagnostics']


def test_review_markdown_report_exposes_metric_scope_and_measurement_basis(tmp_path):
    append(tmp_path, *snapshots())
    result = report(tmp_path)
    body = (tmp_path / '.ai-sow-lite/telemetry' / REQUEST / 'report.md').read_text()
    assert result['as_of'] in body
    assert result['source_digest'] in body
    for item in result['metrics']:
        # Scope IDs distinguish totals, exclusive activities and shared groups.
        # Basis retains the actual source and cumulative boundary identities.
        line = next(line for line in body.splitlines()
                    if item['name'] in line and json.dumps(item['scope'], ensure_ascii=False, sort_keys=True) in line)
        assert item['attribution'] in line
        assert json.dumps(item['basis'], ensure_ascii=False, sort_keys=True) in line
