"""Synthetic marker accounting through the public telemetry report consumer."""
import json
from uuid import uuid4

import pytest

from ai_sow_lite import cli, telemetry
from ai_sow_lite.contracts import schema_validator


REQUEST = '00000000-0000-4000-8000-000000000001'
EXECUTION = '00000000-0000-4000-8000-000000000002'
PRODUCER = '00000000-0000-4000-8000-000000000003'


def marker(name, phase, second, *, execution=EXECUTION, producer=PRODUCER):
    return dict(
        schema_version='1.0', event_id=str(uuid4()), event_type='lifecycle',
        request_id=REQUEST, execution_id=execution, producer_id=producer, sequence=second,
        observed_at=f'2026-09-09T00:00:{second:02d}.000000Z', activity_ids=[], slice_ids=[],
        data=dict(name=name, phase=phase, span_id=str(uuid4()), parent_span_id=None,
                  clock_domain=None, monotonic_ns=None, status=None, operation_id=None,
                  attempt_id=None, host_call_id=None, timing='utc_marker'))


def inspect(project):
    response = cli.execute(dict(
        protocol_version='1.0', request_id=REQUEST, project_path=str(project),
        operation='inspect', payload=dict(view='telemetry', selector={'request_id': REQUEST},
                                          limit=100, cursor=None)))
    assert response['ok'] and response['diagnostics'] == []
    result = response['result']
    assert result['next_cursor'] is None
    report = json.loads((project / result['report_ref']['path']).read_bytes())
    assert result['items'] == report['metrics']
    assert schema_validator('artifacts', 'telemetry_report').is_valid(report)
    return report


def metric(report, name):
    matches = [m for m in report['metrics']
               if m['name'] == name and m['scope'] == dict(kind='request', id=REQUEST)]
    assert len(matches) == 1, f'Expected one request metric {name}, got {matches}'
    return matches[0]


def test_inspect_reports_first_feedback_and_file_from_recorded_request_start(tmp_path):
    start = marker('request', 'start', 0)
    feedback = marker('useful_feedback', 'milestone', 10)
    file = marker('usable_file', 'milestone', 20)
    end = marker('request', 'end', 30)
    for event in (start, feedback, file, end):
        telemetry.append_event(tmp_path, event)

    report = inspect(tmp_path)

    assert report['event_count'] == 4
    assert metric(report, 'request_wall_ns')['value'] == 30_000_000_000
    for name, value, endpoint in (
        ('first_useful_feedback_ns', 10_000_000_000, feedback),
        ('first_usable_file_ns', 20_000_000_000, file),
    ):
        item = metric(report, name)
        assert item['value'] == value and item['unit'] == 'ns'
        assert item['coverage'] == 'partial'
        assert item['basis'] == dict(
            kind='utc_request_start_to_first_observed_milestone_including_wait',
            start=start['event_id'], end=endpoint['event_id'],
            event_ids=[start['event_id'], endpoint['event_id']])
        assert item['diagnostics'] == []
    assert metric(report, 'model_duration_ns')['value'] is None
    assert metric(report, 'total_tokens')['value'] is None


def test_same_clock_milestones_use_monotonic_time_without_utc_offset_adjustment(tmp_path):
    start = marker('request', 'start', 20)
    feedback = marker('useful_feedback', 'milestone', 10)
    file = marker('usable_file', 'milestone', 5)
    for event, ns in ((start, 500), (feedback, 520), (file, 570)):
        event['data'].update(timing='monotonic', clock_domain=PRODUCER, monotonic_ns=ns)
        telemetry.append_event(tmp_path, event)

    report = inspect(tmp_path)

    for name, expected in (('first_useful_feedback_ns', 20), ('first_usable_file_ns', 70)):
        item = metric(report, name)
        assert item['value'] == expected and item['coverage'] == 'partial'
        assert item['basis']['kind'] == 'same_process_request_start_to_first_observed_milestone_including_wait'
    assert metric(report, 'request_wall_ns')['value'] is None
    assert metric(report, 'model_duration_ns')['value'] is None


@pytest.mark.parametrize('boundary', [None, 'tool', 'processing'])
def test_missing_request_start_does_not_infer_one_from_other_observations(tmp_path, boundary):
    events = [marker('useful_feedback', 'milestone', 10), marker('usable_file', 'milestone', 20)]
    if boundary:
        events.append(marker(boundary, 'start', 0))
    for event in events:
        telemetry.append_event(tmp_path, event)

    report = inspect(tmp_path)

    for name in ('first_useful_feedback_ns', 'first_usable_file_ns'):
        item = metric(report, name)
        assert item['value'] is None and item['coverage'] == 'unknown'
        assert item['diagnostics'] == ['LIFECYCLE_INCOMPLETE']
        assert 'start' not in item['basis']


def test_empty_telemetry_returns_unknown_milestones_without_business_failure(tmp_path):
    report = inspect(tmp_path)

    assert report['event_count'] == 0 and report['coverage'] == 'unknown'
    for name in ('first_useful_feedback_ns', 'first_usable_file_ns'):
        assert metric(report, name)['value'] is None
        assert metric(report, name)['diagnostics'] == ['LIFECYCLE_INCOMPLETE']
    assert business_bytes(tmp_path) == {}


@pytest.mark.parametrize('present,missing', [('useful_feedback', 'usable_file'), ('usable_file', 'useful_feedback')])
def test_missing_milestone_keeps_its_own_gap_without_hiding_known_endpoint(tmp_path, present, missing):
    start = marker('request', 'start', 0)
    for event in (start, marker(present, 'milestone', 10), marker('request', 'end', 30)):
        telemetry.append_event(tmp_path, event)

    report = inspect(tmp_path)

    assert metric(report, 'first_' + present + '_ns')['value'] == 10_000_000_000
    item = metric(report, 'first_' + missing + '_ns')
    assert item['value'] is None and item['coverage'] == 'unknown'
    assert item['basis']['start'] == start['event_id']
    assert item['diagnostics'] == ['LIFECYCLE_INCOMPLETE']
    assert 'LIFECYCLE_INCOMPLETE' in report['diagnostics']


def test_utc_first_milestones_span_executions_and_include_user_wait_from_late_start(tmp_path):
    second_execution = str(uuid4())
    tool_start = marker('tool', 'start', 0)
    tool_end = marker('tool', 'end', 5)
    start = marker('request', 'start', 10)
    feedback = marker('useful_feedback', 'milestone', 20)
    wait_start = marker('user_wait', 'start', 21)
    wait_end = marker('user_wait', 'end', 35)
    file = marker('usable_file', 'milestone', 40, execution=second_execution, producer=str(uuid4()))
    later_feedback = marker('useful_feedback', 'milestone', 45, execution=second_execution)
    later_file = marker('usable_file', 'milestone', 50, execution=second_execution)
    for event in (later_file, later_feedback, file, wait_end, start, feedback, wait_start, tool_end, tool_start):
        telemetry.append_event(tmp_path, event)

    report = inspect(tmp_path)

    assert metric(report, 'user_wait_ns')['value'] == 14_000_000_000
    for name, value, endpoint in (
        ('first_useful_feedback_ns', 10_000_000_000, feedback),
        ('first_usable_file_ns', 30_000_000_000, file),
    ):
        item = metric(report, name)
        assert item['value'] == value and item['coverage'] == 'partial'
        assert item['basis']['kind'] == 'utc_request_start_to_first_observed_milestone_including_wait'
        assert item['basis']['start'] == start['event_id'] and item['basis']['end'] == endpoint['event_id']


def paired_request_segments():
    second_execution = str(uuid4())
    return [marker('request', 'start', 5), marker('request', 'end', 20),
            marker('request', 'start', 35, execution=second_execution, producer=str(uuid4())),
            marker('request', 'end', 55, execution=second_execution, producer=str(uuid4()))]


def test_paired_utc_resume_uses_first_observed_root_and_includes_between_execution_wait(tmp_path):
    first_start, first_end, second_start, second_end = paired_request_segments()
    feedback = marker('useful_feedback', 'milestone', 15)
    file = marker('usable_file', 'milestone', 45, execution=second_start['execution_id'])
    for event in (second_start, file, second_end, first_end, feedback, first_start):
        telemetry.append_event(tmp_path, event)

    report = inspect(tmp_path)

    for name, expected, endpoint in (
        ('first_useful_feedback_ns', 10_000_000_000, feedback),
        ('first_usable_file_ns', 40_000_000_000, file),
    ):
        item = metric(report, name)
        assert item['value'] == expected and item['coverage'] == 'partial'
        assert item['basis']['kind'] == 'utc_request_start_to_first_observed_milestone_including_wait'
        assert item['basis']['start'] == first_start['event_id']
        assert item['basis']['end'] == endpoint['event_id']
        assert item['diagnostics'] == []
    assert report['event_count'] == 6
    assert metric(report, 'model_duration_ns')['value'] is None
    for event in (first_start, first_end, second_start, second_end):
        telemetry.append_event(tmp_path, event)
    replay = inspect(tmp_path)
    assert replay['source_digest'] == report['source_digest']
    assert replay['metrics'] == report['metrics']


@pytest.mark.parametrize('change', [
    'same_execution', 'nested_start', 'nested_end', 'overlap', 'missing_first_end',
    'missing_second_end', 'mixed_clock', 'activity_mismatch', 'slice_mismatch',
    'reversed_segment', 'duplicate_end', 'orphan_end',
])
def test_ambiguous_or_incomplete_resumed_segments_keep_origin_unknown(tmp_path, change):
    roots = paired_request_segments()
    first_start, first_end, second_start, second_end = roots
    if change == 'same_execution':
        second_start['execution_id'] = second_end['execution_id'] = EXECUTION
    elif change == 'nested_start':
        second_start['data']['parent_span_id'] = str(uuid4())
    elif change == 'nested_end':
        second_end['data']['parent_span_id'] = str(uuid4())
    elif change == 'overlap':
        second_start['observed_at'] = '2026-09-09T00:00:15.000000Z'
    elif change == 'missing_first_end':
        roots.remove(first_end)
    elif change == 'missing_second_end':
        roots.remove(second_end)
    elif change == 'mixed_clock':
        second_start['data'].update(timing='monotonic', clock_domain=PRODUCER, monotonic_ns=500)
    elif change == 'activity_mismatch':
        second_end['activity_ids'] = [str(uuid4())]
    elif change == 'slice_mismatch':
        second_end['slice_ids'] = [str(uuid4())]
    elif change == 'reversed_segment':
        second_end['observed_at'] = '2026-09-09T00:00:30.000000Z'
    elif change == 'duplicate_end':
        roots.append(marker('request', 'end', 55, execution=second_start['execution_id']))
    else:
        roots.append(marker('request', 'end', 58, execution=str(uuid4())))
    feedback = marker('useful_feedback', 'milestone', 15)
    file = marker('usable_file', 'milestone', 45, execution=second_start['execution_id'])
    for event in (*roots, feedback, file):
        telemetry.append_event(tmp_path, event)

    report = inspect(tmp_path)

    for name in ('first_useful_feedback_ns', 'first_usable_file_ns'):
        item = metric(report, name)
        assert item['value'] is None and item['coverage'] == 'unknown'
        assert item['diagnostics'] == ['LIFECYCLE_INCOMPLETE']
        assert 'start' not in item['basis']


@pytest.mark.parametrize('change', ['domain', 'producer', 'execution', 'missing_clock', 'missing_ns', 'mixed_timing'])
def test_incompatible_milestone_clock_never_falls_back_to_observed_utc(tmp_path, change):
    start = marker('request', 'start', 0)
    feedback = marker('useful_feedback', 'milestone', 10)
    for event, ns in ((start, 500), (feedback, 520)):
        event['data'].update(timing='monotonic', clock_domain=PRODUCER, monotonic_ns=ns)
    if change == 'domain':
        feedback['data']['clock_domain'] = str(uuid4())
    elif change == 'producer':
        feedback['producer_id'] = str(uuid4())
    elif change == 'execution':
        feedback['execution_id'] = str(uuid4())
    elif change == 'missing_clock':
        feedback['data']['clock_domain'] = None
    elif change == 'missing_ns':
        feedback['data']['monotonic_ns'] = None
    else:
        feedback['data']['timing'] = 'utc_marker'
    for event in (start, feedback):
        telemetry.append_event(tmp_path, event)

    report = inspect(tmp_path)

    item = metric(report, 'first_useful_feedback_ns')
    assert item['value'] is None and item['coverage'] == 'unknown'
    assert item['diagnostics'] == ['CLOCK_UNALIGNED']
    assert 'CLOCK_UNALIGNED' in report['diagnostics']


@pytest.mark.parametrize('timing', ['utc_marker', 'monotonic'])
def test_negative_milestone_elapsed_is_unknown_and_never_clamped(tmp_path, timing):
    start = marker('request', 'start', 20)
    feedback = marker('useful_feedback', 'milestone', 10)
    if timing == 'monotonic':
        for event, ns in ((start, 520), (feedback, 500)):
            event['data'].update(timing=timing, clock_domain=PRODUCER, monotonic_ns=ns)
    for event in (start, feedback):
        telemetry.append_event(tmp_path, event)

    report = inspect(tmp_path)

    item = metric(report, 'first_useful_feedback_ns')
    assert item['value'] is None and item['coverage'] == 'unknown'
    assert item['diagnostics'] == ['CLOCK_REVERSED']
    assert 'CLOCK_REVERSED' in report['diagnostics']


@pytest.mark.parametrize('ambiguous', ['second_start', 'resumed_start', 'nested_start'])
def test_ambiguous_request_roots_do_not_select_an_earliest_or_restarted_origin(tmp_path, ambiguous):
    start = marker('request', 'start', 0)
    events = [start, marker('useful_feedback', 'milestone', 20), marker('usable_file', 'milestone', 30)]
    if ambiguous in ('second_start', 'resumed_start'):
        other = marker('request', 'start', 10)
        if ambiguous == 'resumed_start':
            other['execution_id'] = str(uuid4())
        events.append(other)
    else:
        start['data']['parent_span_id'] = str(uuid4())
    for event in events:
        telemetry.append_event(tmp_path, event)

    report = inspect(tmp_path)

    for name in ('first_useful_feedback_ns', 'first_usable_file_ns'):
        item = metric(report, name)
        assert item['value'] is None and item['coverage'] == 'unknown'
        assert item['diagnostics'] == ['LIFECYCLE_INCOMPLETE']


def test_request_activity_labels_do_not_replace_the_explicit_request_start(tmp_path):
    start = marker('request', 'start', 0)
    start['activity_ids'] = [str(uuid4())]
    start['slice_ids'] = [str(uuid4())]
    feedback = marker('useful_feedback', 'milestone', 10)
    for event in (start, feedback):
        telemetry.append_event(tmp_path, event)

    item = metric(inspect(tmp_path), 'first_useful_feedback_ns')

    assert item['value'] == 10_000_000_000
    assert item['basis']['start'] == start['event_id']


def test_unalignable_repeated_milestone_keeps_first_unknown_instead_of_ignoring_it(tmp_path):
    start = marker('request', 'start', 0)
    known = marker('useful_feedback', 'milestone', 10)
    unaligned = marker('useful_feedback', 'milestone', 20)
    unaligned['data'].update(timing='monotonic', clock_domain=PRODUCER, monotonic_ns=520)
    for event in (start, known, unaligned):
        telemetry.append_event(tmp_path, event)

    item = metric(inspect(tmp_path), 'first_useful_feedback_ns')

    assert item['value'] is None and item['diagnostics'] == ['CLOCK_UNALIGNED']


def business_bytes(project):
    return {p.relative_to(project): p.read_bytes() for p in project.rglob('*')
            if p.is_file() and 'telemetry' not in p.relative_to(project).parts}


def test_late_milestones_and_duplicate_replay_rebuild_only_telemetry(tmp_path):
    # Opaque sealed artifacts detect any attempted business backfill; no Office is involved.
    root = tmp_path / '.ai-sow-lite'
    version = root / 'versions' / str(uuid4())
    version.mkdir(parents=True)
    for name in ('model.json', 'sow.xlsx', 'manifest.json', 'summary.md'):
        (version / name).write_bytes(b'sealed-' + name.encode())
    (root / 'current.json').write_bytes(b'sealed-current')
    work = root / 'work/generate' / REQUEST
    work.mkdir(parents=True)
    (work / 'checkpoint.json').write_bytes(b'sealed-checkpoint')
    before = business_bytes(tmp_path)
    start = marker('request', 'start', 0)
    end = marker('request', 'end', 50)
    for event in (start, end, start, end):
        telemetry.append_event(tmp_path, event)
    empty = inspect(tmp_path)
    assert empty['event_count'] == 2
    assert metric(empty, 'first_usable_file_ns')['value'] is None

    feedback = marker('useful_feedback', 'milestone', 20)
    file = marker('usable_file', 'milestone', 40)
    for event in (feedback, file):
        telemetry.append_event(tmp_path, event)
    first = inspect(tmp_path)
    assert metric(first, 'first_useful_feedback_ns')['value'] == 20_000_000_000
    assert metric(first, 'first_usable_file_ns')['value'] == 40_000_000_000

    # Previously recorded earlier markers arrive late, rather than inventing past timestamps.
    earlier_feedback = marker('useful_feedback', 'milestone', 10)
    earlier_file = marker('usable_file', 'milestone', 30)
    for event in (earlier_file, earlier_feedback, feedback, file, start, end):
        telemetry.append_event(tmp_path, event)
    second = inspect(tmp_path)
    assert metric(second, 'first_useful_feedback_ns')['value'] == 10_000_000_000
    assert metric(second, 'first_usable_file_ns')['value'] == 30_000_000_000
    assert second['event_count'] == 6
    assert second['source_digest'] != first['source_digest']
    for event in (earlier_file, earlier_feedback, feedback, file, start, end):
        telemetry.append_event(tmp_path, event)
    replay = inspect(tmp_path)
    assert replay['source_digest'] == second['source_digest']
    assert replay['metrics'] == second['metrics'] and replay['event_count'] == 6
    assert business_bytes(tmp_path) == before
