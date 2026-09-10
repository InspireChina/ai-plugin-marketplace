"""Thin authoring consumer: real storage and existing public operations."""
import json
from uuid import uuid4

import pytest

from .support.clarify import delivered_baseline, clarify_case, edit_draft
from .support.fixtures import read_json


def test_client_starts_without_poisoning_first_ingest(tmp_path):
    from ai_sow_lite.authoring import Client

    project = tmp_path / 'new project'
    client = Client(project, str(uuid4()), 'generate')
    assert not project.exists()
    source = tmp_path / 'prd.md'
    source.write_text('本期交付资料查询。', encoding='utf-8')
    result = client.call('ingest', dict(kind='sources', entrypoint='generate', project_type='new',
        sources=[dict(source_path=str(source), input_id=None, material_types=['PRD'],
                      uses=['to-be'], use_regions=[])]))
    assert len(result['input_refs']) == 1
    ref = client.save('analysis-draft.json', {'draft': 'Agent authors the content'})
    assert read_json(project / ref['path']) == {'draft': 'Agent authors the content'}


def test_failed_operation_stops_caller_batch_with_real_diagnostics(clarify_case):
    from ai_sow_lite.authoring import Client, OperationError

    case = clarify_case
    client = Client(case['project'], case['request_id'], 'clarify')
    reached_next = False
    with pytest.raises(OperationError) as failed:
        client.call('check', dict(candidate_path='../../outside.json', scope='full', plan_path=None))
        reached_next = True
    assert not reached_next and not failed.value.response['ok']
    assert failed.value.response['diagnostics']
    assert read_json(case['project'] / '.ai-sow-lite/current.json') == case['current']


def test_saved_edit_consumed_by_existing_check_keeps_baseline(clarify_case):
    from ai_sow_lite.authoring import Client

    case = clarify_case
    client = Client(case['project'], case['request_id'], 'clarify')
    draft = edit_draft(case, [dict(op='replace', collection='stories', object_id=case['ids']['S-01'],
                                 field='notes', value='只调整这条备注')])
    saved = client.save('edit-draft.json', draft)
    checked = client.call('check', dict(edit_path=saved['path'], scope='full'))
    assert checked['valid_for_render']
    assert read_json(case['project'] / '.ai-sow-lite/current.json') == case['current']


@pytest.mark.parametrize('name', ['../checkpoint.json', '/tmp/outside.json', 'nested/file.json'])
def test_save_cannot_overwrite_runtime_files(clarify_case, name):
    from ai_sow_lite.authoring import Client
    from ai_sow_lite.project import StorageError

    case = clarify_case
    client = Client(case['project'], case['request_id'], 'clarify')
    checkpoint = case['project'] / client.area / 'checkpoint.json'
    before = checkpoint.read_bytes()
    with pytest.raises(StorageError):
        client.save(name, {})
    assert checkpoint.read_bytes() == before


def test_save_before_ingest_does_not_create_request(tmp_path):
    from ai_sow_lite.authoring import Client
    from ai_sow_lite.project import StorageError

    client = Client(tmp_path, str(uuid4()), 'generate')
    with pytest.raises(StorageError):
        client.save('draft.json', {})
    assert not (tmp_path / '.ai-sow-lite').exists()


def confirmation_inputs(case):
    from ai_sow_lite.authoring import Client, source_ref

    client = Client(case['project'], case['request_id'], 'clarify')
    draft = edit_draft(case, [dict(op='replace', collection='stories', object_id=case['ids']['S-01'],
                                 field='notes', value='保留原范围，只调整备注')])
    ref = client.save('edit-draft.json', draft)
    checked = client.call('check', dict(edit_path=ref['path'], scope='full'))
    assert (case['project'] / checked['review_ref']['path']).is_file()
    answer = case['project'] / 'execution-answer.md'
    answer.write_text('确认执行刚展示的备注调整。\n', encoding='utf-8')
    registered = client.call('ingest', dict(kind='sources', entrypoint='clarify', project_type='new',
        sources=[dict(source_path=str(answer), input_id=None, material_types=['answer'],
                      uses=['to-be-scope'], use_regions=[])]))
    region = client.call('inspect', dict(view='regions', selector=dict(
        input_version_id=registered['input_refs'][0]['input_version_id'],
        locator=dict(kind='text_lines', start_line=1, end_line=1))))
    return client, checked, source_ref(region)


def test_actual_confirmation_binding_is_immutable_and_passes_core_check(clarify_case):
    client, checked, answer = confirmation_inputs(clarify_case)
    shown = client.project / checked['plan_ref']['path']
    before = shown.read_bytes()
    confirmed = client.bind_confirmation(checked['check_ref'], answer)
    assert confirmed == client.bind_confirmation(checked['check_ref'], answer)
    assert shown.read_bytes() == before
    content = read_json(client.project / confirmed['path'])
    assert content['confirmation']['input_ref'] == answer
    assert content['confirmation']['shown_plan_ref'] == checked['plan_ref']
    result = client.call('check', dict(candidate_path=checked['candidate_ref']['path'],
                                     plan_path=confirmed['path'], scope='full'))
    assert result['valid_for_render']
    assert read_json(client.project / '.ai-sow-lite/current.json') == clarify_case['current']


@pytest.mark.parametrize('damage', ['check', 'plan', 'other_request'])
def test_confirmation_rejects_changed_or_foreign_shown_files(clarify_case, damage):
    from ai_sow_lite.authoring import Client
    from ai_sow_lite.project import StorageError

    client, checked, answer = confirmation_inputs(clarify_case)
    if damage == 'other_request':
        client = Client(client.project, str(uuid4()), 'clarify')
    else:
        target = client.project / checked[damage + '_ref']['path']
        target.write_bytes(target.read_bytes() + b' ')
    with pytest.raises(StorageError):
        client.bind_confirmation(checked['check_ref'], answer)
    assert not list((client.project / client.area).glob('**/confirmed-plan.json'))


def test_binding_never_substitutes_for_source_validation(clarify_case):
    from ai_sow_lite.authoring import OperationError

    client, checked, answer = confirmation_inputs(clarify_case)
    answer['excerpt_hash'] = '0' * 64
    confirmed = client.bind_confirmation(checked['check_ref'], answer)
    with pytest.raises(OperationError):
        client.call('check', dict(candidate_path=checked['candidate_ref']['path'],
                                 plan_path=confirmed['path'], scope='full'))
    assert read_json(client.project / '.ai-sow-lite/current.json') == clarify_case['current']


def test_client_marks_root_and_current_activity_without_business_state(tmp_path):
    from ai_sow_lite.authoring import Client
    from ai_sow_lite.telemetry import build_report

    context = dict(execution_id=str(uuid4()), activity_ids=[str(uuid4())], slice_ids=[str(uuid4())])
    client = Client(tmp_path, str(uuid4()), 'generate', observation_context=context)
    for name, phase in [('request', 'start'), ('input_analysis', 'start'),
                        ('input_analysis', 'end'), ('request', 'end')]:
        assert client.mark(name, phase)['recording'] == 'recorded'
    events = [json.loads(line) for path in (tmp_path / '.ai-sow-lite/telemetry').glob('*/events/*/*.jsonl')
              for line in path.read_text().splitlines()]
    roots = [e for e in events if e['data']['name'] == 'request']
    activities = [e for e in events if e['data']['name'] == 'input_analysis']
    assert len(events) == 4 and len(roots) == len(activities) == 2
    assert all(e['activity_ids'] == e['slice_ids'] == [] for e in roots)
    assert all(e['activity_ids'] == context['activity_ids'] and e['slice_ids'] == context['slice_ids']
               for e in activities)
    report = build_report(tmp_path, client.request_id)
    assert next(m['value'] for m in report['metrics'] if m['name'] == 'request_wall_ns') is not None
    assert not (tmp_path / '.ai-sow-lite/work').exists()
    assert not (tmp_path / '.ai-sow-lite/project.json').exists()


def test_failed_client_mark_keeps_business_query_usable(clarify_case):
    from ai_sow_lite.authoring import Client

    case = clarify_case
    client = Client(case['project'], case['request_id'], 'clarify')
    result = client.mark('request', 'start')  # No execution identity: do not invent one.
    assert result['recording'] == 'degraded'
    assert client.call('inspect', dict(view='current', selector={}))
    assert read_json(case['project'] / '.ai-sow-lite/current.json') == case['current']
