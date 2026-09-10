"""Finite edits through the real public CLI and immutable delivered projects."""
from copy import deepcopy
from uuid import uuid4

import pytest

from .support.clarify import (delivered_baseline, clarify_case, feedback, edit_draft, check_edits,
                             confirm_plan, complexity_draft, prepared_seed, prepared_case)
from .support.clarify import controlled_base_change
from .support.fixtures import read_json, write_json
from .support.cli import run_request


def load_candidate(case, reply):
    candidate = read_json(case['project'] / reply['result']['candidate_ref']['path'])
    return candidate, read_json(case['project'] / candidate['model_path'])


def recheck(case, result):
    return run_request(case['project'], case['request_id'], 'check', dict(
        candidate_path=result['candidate_ref']['path'], plan_path=result['plan_ref']['path'], scope='full'))


def test_public_check_edits_builds_only_requested_notes_change(clarify_case):
    case = clarify_case
    project, ids = case['project'], case['ids']
    old = project / '.ai-sow-lite/versions' / case['current']['version_id']
    old_bytes = {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()}
    pointer = (project / '.ai-sow-lite/current.json').read_bytes()
    source = feedback(case, '请仅把资料查询备注改为“保留现有查询验收规则”。\n')
    draft = edit_draft(case, [dict(op='replace', collection='stories', object_id=ids['S-01'],
        field='notes', value='保留现有查询验收规则')], [source])
    reply = check_edits(case, draft)
    assert reply['ok'], reply
    result = reply['result']
    assert result['valid_for_render'] is True
    assert not {'model', 'stories', 'tasks'} & result.keys()
    for name in ('candidate_ref', 'plan_ref', 'review_ref', 'check_ref'):
        assert (project / result[name]['path']).is_file()
    candidate = read_json(project / result['candidate_ref']['path'])
    model = read_json(project / candidate['model_path'])
    expected = deepcopy(read_json(old / 'model.json'))
    expected['stories'][0]['notes'] = '保留现有查询验收规则'
    assert model == expected
    for name, key in [('pending-items.json', 'pending_items_path'), ('decisions.json', 'decisions_path')]:
        assert (project / candidate[key]).read_bytes() == old_bytes[name]
    plan = read_json(project / result['plan_ref']['path'])
    assert plan['confirmation'] is None
    assert plan['changes'] == [
        dict(op='replace', collection='stories', object_id=ids['S-01'], field='notes',
             before='', after='保留现有查询验收规则'),
        dict(op='add', collection='input_refs', object_id=source, field=None, before=None, after=source),
    ]
    assert plan['write_set'] == [dict(collection='stories', object_id=ids['S-01'], field='notes'),
                                 dict(collection='input_refs', object_id=source, field=None)]
    assert '保留现有查询验收规则' in (project / result['review_ref']['path']).read_text()
    assert (project / '.ai-sow-lite/current.json').read_bytes() == pointer
    assert {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()} == old_bytes
    # Same draft reuses the exact constructed candidate and preview artifacts.
    repeated = check_edits(case, draft)
    assert repeated['ok'], repeated
    for key in ('candidate_ref', 'plan_ref', 'review_ref', 'check_ref'):
        assert repeated['result'][key] == result[key]


@pytest.mark.parametrize('with_conditions', [True, False])
def test_review_exposes_bound_conditions_questions_and_read_boundary(clarify_case, with_conditions):
    case = clarify_case
    old = case['project'] / '.ai-sow-lite/versions' / case['current']['version_id']
    draft = edit_draft(case, [dict(op='replace', collection='stories', object_id=case['ids']['S-01'],
                                  field='notes', value='保留已有验收范围')])
    condition = '本次仅在客户书面确认接口责任后采用；否则保留现版。'
    if with_conditions:
        manifest = read_json(old / 'manifest.json')
        draft['conditions'] = [condition]
        draft['unresolved_items'] = [case['ids']['P-01']]
        draft['read_boundary'].update(input_version_ids=manifest['input_version_ids'][:1],
                                      topic_version_ids=manifest['topic_version_ids'][:1], depth='source')
    reply = check_edits(case, draft)
    assert reply['ok'], reply
    review = (case['project'] / reply['result']['review_ref']['path']).read_text(encoding='utf-8')
    assert '保留已有验收范围' in review
    conditions = review.split('## 执行条件\n', 1)[1].split('\n## ', 1)[0]
    unresolved = review.split('## 仍未解决的事项\n', 1)[1].split('\n## ', 1)[0]
    boundary = review.split('## 回查边界\n', 1)[1]
    assert case['ids']['S-01'] in boundary and '资料查询' in boundary
    assert draft['read_boundary']['depth'] in boundary
    if with_conditions:
        assert condition in conditions
        question = read_json(old / 'pending-items.json')['items'][0]
        assert question['id'] in unresolved and question['question'] in unresolved
        assert draft['read_boundary']['input_version_ids'][0] in boundary
        assert draft['read_boundary']['topic_version_ids'][0] in boundary
    else:
        assert conditions.strip() == unresolved.strip() == '无。'
        assert '输入：无。' in boundary and '主题：无。' in boundary


def test_diff_uses_actual_value_not_a_field_allowlist():
    from ai_sow_lite.validation import diff_bundle
    identity = str(uuid4())
    assert diff_bundle({'tasks': [dict(id=identity, complexity='M')]},
                       {'tasks': [dict(id=identity, complexity='L')]}) == [
        dict(op='replace', collection='tasks', object_id=identity, field='complexity', before='M', after='L')]


def test_add_task_preserves_siblings_and_all_other_collections(clarify_case):
    case = clarify_case
    model = read_json(case['project'] / '.ai-sow-lite/versions' / case['current']['version_id'] / 'model.json')
    new = dict(deepcopy(model['tasks'][0]), id=str(uuid4()), name='明确新增的独立页面实例')
    draft = edit_draft(case, [dict(op='add', collection='tasks', object_id=new['id'], field=None, value=new)])
    reply = check_edits(case, draft)
    assert reply['ok'], reply
    _, actual = load_candidate(case, reply)
    expected = deepcopy(model)
    expected['tasks'].insert(2, new)  # S-01 already has T-01 and T-02.
    assert actual == expected


def test_duplicate_and_unknown_edits_return_one_diagnostic_batch(clarify_case):
    case = clarify_case
    base = dict(op='replace', collection='stories', object_id=case['ids']['S-01'], field='notes', value='说明')
    edits = [base, dict(base, value='矛盾说明'), dict(base, object_id=str(uuid4())), dict(base, object_id=str(uuid4()))]
    reply = check_edits(case, edit_draft(case, edits))
    assert not reply['ok']
    assert len(reply['diagnostics']) >= 3
    assert all(d['code'] == 'SCOPE_EXCEEDED' for d in reply['diagnostics'])


def test_ac_move_has_stable_ac_address_and_both_parent_arrays(clarify_case):
    case = clarify_case
    old = read_json(case['project'] / '.ai-sow-lite/versions' / case['current']['version_id'] / 'model.json')
    source, target = old['stories'][:2]
    moved = source['acs'][-1]
    edits = [dict(op='replace', collection='stories', object_id=source['id'], field='acs', value=source['acs'][:-1]),
             dict(op='replace', collection='stories', object_id=target['id'], field='acs', value=target['acs'] + [moved])]
    reply = check_edits(case, edit_draft(case, edits))
    assert reply['ok'], reply
    plan = read_json(case['project'] / reply['result']['plan_ref']['path'])
    assert any(c['collection'] == 'acs' and c['object_id'] == moved['id'] for c in plan['changes'])
    for story in (source, target):
        assert dict(collection='stories', object_id=story['id'], field='acs') in plan['write_set']
        assert any(r['selector']['view'] == 'objects' and story['id'] in
                   r['selector']['selector'].get('object_ids', []) for r in plan['read_set'])


def test_ac_reorder_is_not_an_allowed_finite_edit(clarify_case):
    case = clarify_case
    old = read_json(case['project'] / '.ai-sow-lite/versions' / case['current']['version_id'] / 'model.json')
    draft = edit_draft(case, [dict(op='replace', collection='stories', object_id=old['stories'][0]['id'],
                                 field='acs', value=old['stories'][0]['acs'][::-1])])
    reply = check_edits(case, draft)
    assert not reply['ok']
    assert 'SCOPE_EXCEEDED' in {d['code'] for d in reply['diagnostics']}


@pytest.mark.parametrize('tamper', ['task_order', 'out_of_plan_notes', 'candidate_bytes'])
def test_check_rejects_candidate_changes_after_plan_construction(clarify_case, tamper):
    case = clarify_case
    reply = check_edits(case, edit_draft(case, [dict(op='replace', collection='stories',
        object_id=case['ids']['S-01'], field='notes', value='明确说明')]))
    assert reply['ok'], reply
    candidate, model = load_candidate(case, reply)
    if tamper == 'task_order':
        model['tasks'].reverse()
        write_json(case['project'] / candidate['model_path'], model)
    elif tamper == 'out_of_plan_notes':
        model['tasks'][0]['notes'] += '未经确认的内容'
        write_json(case['project'] / candidate['model_path'], model)
    else:
        path = case['project'] / reply['result']['candidate_ref']['path']
        path.write_bytes(path.read_bytes() + b'\n')
    rejected = recheck(case, reply['result'])
    assert not rejected['ok'], rejected
    assert 'SCOPE_EXCEEDED' in {d['code'] for d in rejected['diagnostics']}


def test_question_meaning_change_requires_revision(clarify_case):
    case = clarify_case
    reply = check_edits(case, edit_draft(case, [dict(op='replace', collection='pending_items',
        object_id=case['ids']['P-01'], field='question', value='改为确认新的责任范围。')]))
    assert not reply['ok']
    assert any(d['target']['field'] == 'revision' for d in reply['diagnostics'])


def test_genuine_no_change_reports_existing_version_without_delivery(clarify_case):
    case = clarify_case
    reply = check_edits(case, edit_draft(case, [dict(op='replace', collection='stories',
        object_id=case['ids']['S-01'], field='notes', value='')]))
    assert reply['ok'], reply
    assert reply['result']['no_change'] is True
    assert reply['result']['current_version'] == case['current']['version_id']
    assert [p.name for p in (case['project'] / '.ai-sow-lite/versions').iterdir()] == [case['current']['version_id']]


def test_edit_preserves_unrelated_json_bytes_even_with_nonstandard_layout():
    from ai_sow_lite.changes import _encoded
    import json
    raw = b'{ "tasks" : [\n { "id" : "a", "notes":"old" },\n { "id":"b", "notes" : "keep" }\n] }\n'
    changed = json.loads(raw)
    changed['tasks'][0]['notes'] = 'new'
    assert _encoded(changed, raw) == raw.replace(b'"old"', b'"new"')


def notes_plan(case):
    source = feedback(case, '请仅将资料查询备注改为“保留已有验收范围”。\n')
    reply = check_edits(case, edit_draft(case, [dict(op='replace', collection='stories',
        object_id=case['ids']['S-01'], field='notes', value='保留已有验收范围')], [source]))
    assert reply['ok'], reply
    return reply['result']


def test_real_confirmation_registration_keeps_the_candidate_and_check_usable(clarify_case):
    case = clarify_case
    result = notes_plan(case)
    candidate = case['project'] / result['candidate_ref']['path']
    before = candidate.read_bytes()
    confirmed, _ = confirm_plan(case, result)
    reply = run_request(case['project'], case['request_id'], 'check', dict(candidate_path=result['candidate_ref']['path'],
        scope='full', plan_path=confirmed))
    assert reply['ok'], reply
    assert candidate.read_bytes() == before
    assert reply['result']['candidate_digest'] == result['candidate_digest']


@pytest.mark.parametrize('change', ['uses', 'path', 'remove', 'reorder', 'duplicate'])
def test_confirmation_append_does_not_allow_changes_to_prior_index_entries(clarify_case, change):
    case = clarify_case
    result = notes_plan(case)
    confirm_plan(case, result)
    path = case['project'] / '.ai-sow-lite/inputs/index.json'
    index = read_json(path)
    if change == 'uses':
        index['items'][0]['uses'] = ['as-is']
    elif change == 'path':
        index['items'][0]['relative_path'] += '.other'
    elif change == 'remove':
        index['items'].pop(0)
    elif change == 'reorder':
        index['items'][0], index['items'][1] = index['items'][1], index['items'][0]
    else:
        index['items'].append(deepcopy(index['items'][0]))
    write_json(path, index)
    reply = recheck(case, result)
    assert not reply['ok'], reply


@pytest.mark.office
def test_preview_then_confirmation_applies_same_prepared_without_second_office(clarify_case):
    case = clarify_case
    result = notes_plan(case)
    project, request = case['project'], case['request_id']
    rendered = run_request(project, request, 'render', dict(candidate_path=result['candidate_ref']['path'],
        check_path=result['check_ref']['path'], expected_current=case['current']))
    assert rendered['ok'], rendered
    prepared_ref = rendered['result']['prepared_ref']
    render_folders = set((project / '.ai-sow-lite/work/clarify' / request).glob('render-*'))
    attempt_path = (project / result['candidate_ref']['path']).with_name('render-attempt.json')
    attempt_bytes = attempt_path.read_bytes()
    prepared_bytes = (project / prepared_ref['path']).read_bytes()
    candidate, _ = load_candidate(case, dict(result=result))
    business_bytes = {key: (project / candidate[key]).read_bytes() for key in ('model_path', 'pending_items_path', 'decisions_path')}
    denied = run_request(project, request, 'apply', dict(entrypoint='clarify', prepared_path=prepared_ref['path'],
        plan_path=result['plan_ref']['path'], expected_current=case['current']))
    assert not denied['ok']
    assert read_json(project / '.ai-sow-lite/current.json') == case['current']
    confirmed, confirmation_id = confirm_plan(case, result)
    reused = run_request(project, request, 'render', dict(candidate_path=result['candidate_ref']['path'],
        check_path=result['check_ref']['path'], expected_current=case['current']))
    assert reused['ok'], reused
    assert reused['result']['prepared_ref'] == prepared_ref
    applied = run_request(project, request, 'apply', dict(entrypoint='clarify', prepared_path=prepared_ref['path'],
        plan_path=confirmed, expected_current=case['current']))
    assert applied['ok'], applied
    assert applied['result']['applied_version'] == rendered['result']['version_id']
    assert attempt_path.read_bytes() == attempt_bytes
    assert (project / prepared_ref['path']).read_bytes() == prepared_bytes
    assert set((project / '.ai-sow-lite/work/clarify' / request).glob('render-*')) == render_folders
    for key, raw in business_bytes.items():
        assert (project / candidate[key]).read_bytes() == raw
    manifest = read_json(project / applied['result']['manifest_ref']['path'])
    assert manifest['base_version_id'] == case['current']['version_id']
    assert confirmation_id not in manifest['input_version_ids']
    delivery = project / '.ai-sow-lite/versions' / applied['result']['applied_version']
    proof = read_json(delivery / 'confirmation.json')
    for key in ('plan_ref', 'shown_plan_ref'):
        assert (project / proof[key]['path']).is_file()
    assert proof['input_record']['input_version_id'] == confirmation_id


@pytest.mark.parametrize('choice', ['S', 'M'])
def test_registered_complexity_choice_changes_only_explicit_basis_issue_and_decision(clarify_case, choice):
    case = clarify_case
    old = case['project'] / '.ai-sow-lite/versions' / case['current']['version_id']
    model = read_json(old / 'model.json')
    draft = complexity_draft(case, choice)
    checked = check_edits(case, draft)
    assert checked['ok'], checked
    candidate, changed = load_candidate(case, checked)
    assert changed['tasks'][5]['complexity'] == choice
    assert changed['tasks'][5]['work_mode'] == model['tasks'][5]['work_mode']
    assert changed['tasks'][:5] + changed['tasks'][6:] == model['tasks'][:5] + model['tasks'][6:]
    assert {k: v for k, v in changed.items() if k != 'tasks'} == {k: v for k, v in model.items() if k != 'tasks'}
    assert read_json(case['project'] / candidate['pending_items_path'])['items'][0]['status'] == 'resolved'
    assert len(read_json(case['project'] / candidate['decisions_path'])['items']) == 2
    plan = read_json(case['project'] / checked['result']['plan_ref']['path'])
    complexity_changes = [c for c in plan['changes'] if c['collection'] == 'tasks' and c['field'] == 'complexity']
    assert bool(complexity_changes) == (choice == 'S')
    assert checked['result']['no_change'] is False
    for collection in ('input_refs', 'topic_refs', 'evidence_refs', 'pending_items', 'decisions'):
        assert any(c['collection'] == collection for c in plan['changes'])
    confirmed, _ = confirm_plan(case, checked['result'])
    again = run_request(case['project'], case['request_id'], 'check', dict(candidate_path=checked['result']['candidate_ref']['path'],
        scope='full', plan_path=confirmed))
    assert again['ok'], again


@pytest.mark.parametrize('change', ['value', 'selected_changes', 'digest', 'shown_plan', 'source_hash', 'source_bytes', 'boolean'])
def test_concrete_confirmation_tampering_is_rejected(clarify_case, change):
    case = clarify_case
    result = notes_plan(case)
    path, identity = confirm_plan(case, result)
    plan = read_json(case['project'] / path)
    if change == 'value':
        plan['changes'][0]['after'] = '另一个具体值'
    elif change == 'selected_changes':
        plan['confirmation']['selected_changes'] = []
    elif change == 'digest':
        plan['confirmation']['digest'] = 'json-v1:' + '0' * 64
    elif change == 'shown_plan':
        plan['confirmation']['shown_plan_ref'] = result['candidate_ref']
    elif change == 'source_hash':
        plan['confirmation']['input_ref']['excerpt_hash'] = '0' * 64
    elif change == 'boolean':
        plan['confirmation'] = {'confirmed': True}
    else:
        entry = next(e for e in read_json(case['project'] / '.ai-sow-lite/inputs/index.json')['items'] if e['input_version_id'] == identity)
        (case['project'] / entry['relative_path']).write_text('仅讨论，未执行。\n', encoding='utf-8')
    write_json(case['project'] / path, plan)
    reply = run_request(case['project'], case['request_id'], 'check', dict(candidate_path=result['candidate_ref']['path'], scope='full', plan_path=path))
    assert not reply['ok'], reply


def test_same_field_m_to_l_cannot_use_shown_m_to_s_plan(clarify_case):
    case = clarify_case
    reply = check_edits(case, complexity_draft(case, 'S'))
    assert reply['ok'], reply
    candidate, model = load_candidate(case, reply)
    model['tasks'][5]['complexity'] = 'L'
    write_json(case['project'] / candidate['model_path'], model)
    result = recheck(case, reply['result'])
    assert not result['ok']
    assert 'SCOPE_EXCEEDED' in {d['code'] for d in result['diagnostics']}


@pytest.mark.parametrize('field,value', [('acs', None), ('acs', [1]), ('notes', 7)])
def test_bad_finite_values_produce_diagnostics_not_internal_error(clarify_case, field, value):
    case = clarify_case
    reply = check_edits(case, edit_draft(case, [dict(op='replace', collection='stories',
        object_id=case['ids']['S-01'], field=field, value=value)]))
    assert not reply['ok']
    assert 'INTERNAL_ERROR' not in {d['code'] for d in reply['diagnostics']}


def check_confirmation(case):
    reply = run_request(case['project'], case['request_id'], 'check', dict(
        candidate_path=case['result']['candidate_ref']['path'], plan_path=case['confirmed_path'], scope='full'))
    assert reply['ok'], reply
    return reply['result']


def apply_confirmation(case):
    return run_request(case['project'], case['request_id'], 'apply', dict(entrypoint='clarify',
        prepared_path=case['prepared_ref']['path'], plan_path=case['confirmed_path'], expected_current=case['current']))


@pytest.mark.office
def test_checked_confirmation_bytes_cannot_change_before_apply(prepared_case):
    case = prepared_case
    check_confirmation(case)
    path = case['project'] / case['confirmed_path']
    path.write_bytes(path.read_bytes() + b'\n')
    reply = apply_confirmation(case)
    assert not reply['ok'], reply
    assert read_json(case['project'] / '.ai-sow-lite/current.json') == case['current']


@pytest.mark.office
def test_newly_checked_confirmation_reuses_the_old_prepared_result(prepared_case, monkeypatch):
    from ai_sow_lite import office, workbook
    case = prepared_case
    checked = check_confirmation(case)
    def unexpected_office(*args, **kwargs):
        pytest.fail('Unchanged candidate/plan must reuse its actual prepared workbook, not call Office again')
    monkeypatch.setattr(office, 'recalculate', unexpected_office)
    rendered = workbook.render_candidate(case['project'], case['request_id'], dict(
        candidate_path=checked['candidate_ref']['path'], check_path=checked['check_ref']['path'], expected_current=case['current']))
    assert rendered['prepared_ref'] == case['prepared_ref']


@pytest.mark.office
def test_apply_exact_checked_confirmation_and_repeat_are_idempotent(prepared_case):
    case = prepared_case
    check_confirmation(case)
    first = apply_confirmation(case)
    assert first['ok'], first
    pointer = (case['project'] / '.ai-sow-lite/current.json').read_bytes()
    second = apply_confirmation(case)
    assert second['ok'] and second['result']['idempotent'], second
    assert first['result']['applied_version'] == second['result']['applied_version']
    assert (case['project'] / '.ai-sow-lite/current.json').read_bytes() == pointer


def test_new_analysis_must_have_real_registration_provenance(clarify_case):
    case = clarify_case
    draft = complexity_draft(case, 'S')
    topic = draft['additional_refs']['topic_version_ids'][0]
    (case['project'] / f'.ai-sow-lite/analysis/topics/{topic}/registration-ref.json').unlink()
    reply = check_edits(case, draft)
    assert not reply['ok'], reply


def test_plan_revision_cannot_start_at_two_or_reset_with_a_new_identity(clarify_case):
    case = clarify_case
    draft = edit_draft(case, [dict(op='replace', collection='stories', object_id=case['ids']['S-01'], field='notes', value='首稿')])
    draft['revision'] = 2
    assert not check_edits(case, draft)['ok']
    draft['revision'] = 1
    assert check_edits(case, draft)['ok']
    draft['plan_id'] = str(uuid4())
    draft['edits'][0]['value'] = '另起身份绕过修订'
    assert not check_edits(case, draft)['ok']


def test_explicit_task_retirement_keeps_historical_topic_references_reachable(clarify_case):
    from ai_sow_lite.contracts import canonical_json_bytes
    case = clarify_case
    task = case['ids']['T-01']
    lineage = dict(from_version_id=case['current']['version_id'], from_ids=[task], to_ids=[],
                   reason='本次明确退出这个独立任务，保留原历史记录。', evidence_refs=[case['ids']['EV-P-B1']])
    key = canonical_json_bytes([lineage['from_version_id'], lineage['from_ids']]).decode('utf-8')
    draft = edit_draft(case, [dict(op='remove', collection='tasks', object_id=task, field=None),
        dict(op='add', collection='lineage', object_id=key, field=None, value=lineage)])
    reply = check_edits(case, draft)
    assert reply['ok'], reply
    candidate, model = load_candidate(case, reply)
    assert task not in [t['id'] for t in model['tasks']]
    assert model['lineage'] == [lineage]
    assert case['ids']['topic-version'] in candidate['topic_version_ids']


def test_cannot_delete_open_unestimated_work_while_its_target_remains(clarify_case):
    case = clarify_case
    path = case['project'] / '.ai-sow-lite/versions' / case['current']['version_id'] / 'pending-items.json'
    pending = read_json(path)
    gap = dict(deepcopy(pending['items'][0]), id=str(uuid4()), question='此范围仍有明确未拆明工作。',
        targets=[dict(object_id=case['ids']['S-01'], field=None)], unestimated_work=True)
    pending['items'].append(gap)
    controlled_base_change(case, 'pending-items.json', pending)
    reply = check_edits(case, edit_draft(case, [dict(op='remove', collection='pending_items', object_id=gap['id'], field=None)]))
    assert not reply['ok'], reply
    assert any(d['target']['field'] == 'unestimated_work' for d in reply['diagnostics'])


def test_whole_base_pointer_is_checked_even_when_version_id_is_unchanged(clarify_case):
    case = clarify_case
    result = notes_plan(case)
    old = case['project'] / '.ai-sow-lite/versions' / case['current']['version_id']
    manifest = read_json(old / 'manifest.json')
    manifest['intent_digest'] = 'json-v1:' + '1' * 64
    write_json(old / 'manifest.json', manifest)
    import hashlib
    altered = dict(case['current'], manifest_hash=hashlib.sha256((old / 'manifest.json').read_bytes()).hexdigest())
    write_json(case['project'] / '.ai-sow-lite/current.json', altered)
    reply = recheck(case, result)
    assert not reply['ok']
    assert 'BASE_STALE' in {d['code'] for d in reply['diagnostics']}


def test_hundreds_of_tasks_receive_only_one_explicit_classification_change(clarify_case):
    """Controlled scale fixture; no additional semantic generation or Office claim."""
    from ai_sow_lite.contracts import canonical_json_bytes
    case = clarify_case
    old = case['project'] / '.ai-sow-lite/versions' / case['current']['version_id']
    model = read_json(old / 'model.json')
    # Mechanical enlargement keeps the original migration task and issue unchanged.
    model['tasks'].extend(dict(deepcopy(model['tasks'][0]), id=str(uuid4()), name=f'受控独立任务 {i}') for i in range(300))
    controlled_base_change(case, 'model.json', model)
    original_bytes = (old / 'model.json').read_bytes()
    draft = complexity_draft(case, 'S')
    reply = check_edits(case, draft)
    assert reply['ok'], reply
    candidate, changed = load_candidate(case, reply)
    untouched = lambda tasks: [t for t in tasks if t['id'] != case['ids']['T-06']]
    assert untouched(changed['tasks']) == untouched(model['tasks'])
    assert len(changed['tasks']) == 307
    assert (old / 'model.json').read_bytes() == original_bytes
    plan = read_json(case['project'] / reply['result']['plan_ref']['path'])
    assert {c['object_id'] for c in plan['changes'] if c['collection'] == 'tasks'} == {case['ids']['T-06']}
    metrics = dict(task_count=307, unchanged_task_count=306, edit_count=len(draft['edits']),
        model_facing_edit_bytes=len(canonical_json_bytes(draft)), tool_response_bytes=len(canonical_json_bytes(reply)),
        copied_candidate_business_bytes=sum((case['project'] / candidate[k]).stat().st_size for k in
            ('model_path', 'pending_items_path', 'decisions_path')))
    assert metrics['model_facing_edit_bytes'] < metrics['copied_candidate_business_bytes'] // 10
    assert metrics['tool_response_bytes'] < 4096
    print('CLARIFY_MECHANICAL_SCALE', metrics)


@pytest.mark.parametrize('extra', [{'limit': 20}, {'cursor': None}])
def test_read_selectors_do_not_accept_paging_or_extra_fields(clarify_case, extra):
    case = clarify_case
    draft = edit_draft(case, [])
    draft['read_selectors'][0].update(extra)
    assert not check_edits(case, draft)['ok']


def test_unresolved_plan_items_must_resolve_to_open_questions(clarify_case):
    case = clarify_case
    draft = edit_draft(case, [])
    draft['unresolved_items'] = [str(uuid4())]
    reply = check_edits(case, draft)
    assert not reply['ok'], reply


def test_explicit_whole_input_query_cannot_ignore_new_confirmation_membership(clarify_case):
    case = clarify_case
    draft = edit_draft(case, [dict(op='replace', collection='stories', object_id=case['ids']['S-01'], field='notes', value='说明')])
    draft['read_selectors'] = [dict(view='inputs', selector={})]
    reply = check_edits(case, draft)
    assert reply['ok'], reply
    feedback(case, '确认登记也是整体输入集合的一项变化。\n')
    result = recheck(case, reply['result'])
    assert not result['ok']
    assert any(d['target']['field'] == 'read_set' for d in result['diagnostics'])


def test_optional_field_add_and_remove_are_exact_changes_across_one_revision(clarify_case):
    case = clarify_case
    old = case['project'] / '.ai-sow-lite/versions' / case['current']['version_id']
    decision = read_json(old / 'decisions.json')['items'][0]
    assert 'supersedes' not in decision
    draft = edit_draft(case, [dict(op='add', collection='decisions', object_id=decision['id'], field='supersedes', value=[])])
    first = check_edits(case, draft)
    assert first['ok'], first
    plan_path = case['project'] / first['result']['plan_ref']['path']
    first_bytes = plan_path.read_bytes()
    assert read_json(plan_path)['changes'] == [dict(op='add', collection='decisions', object_id=decision['id'],
        field='supersedes', before=None, after=[])]
    # Revision 2 is always constructed from the same complete base, not revision 1.
    draft['revision'] = 2
    draft['edits'] = []
    second = check_edits(case, draft)
    assert second['ok'] and second['result']['no_change'], second
    assert plan_path.read_bytes() == first_bytes
    draft['revision'] = 3
    assert not check_edits(case, draft)['ok']
    from ai_sow_lite.validation import diff_bundle
    assert diff_bundle({'decisions': [dict(decision, supersedes=[])]}, {'decisions': [decision]}) == [
        dict(op='remove', collection='decisions', object_id=decision['id'], field='supersedes', before=[], after=None)]


def test_complete_story_add_still_records_embedded_ac_container(clarify_case):
    case = clarify_case
    old = read_json(case['project'] / '.ai-sow-lite/versions' / case['current']['version_id'] / 'model.json')
    story = dict(deepcopy(old['stories'][0]), id=str(uuid4()), title='明确新增范围')
    story['acs'] = [dict(ac, id=str(uuid4())) for ac in story['acs']]
    task = dict(deepcopy(old['tasks'][0]), id=str(uuid4()), story_id=story['id'])
    edits = [dict(op='add', collection=c, object_id=v['id'], field=None, value=v) for c, v in [('stories', story), ('tasks', task)]]
    reply = check_edits(case, edit_draft(case, edits))
    assert reply['ok'], reply
    plan = read_json(case['project'] / reply['result']['plan_ref']['path'])
    assert dict(collection='stories', object_id=story['id'], field='acs') in plan['write_set']
    assert any(r['selector']['view'] == 'objects' and story['id'] in
        r['selector']['selector'].get('object_ids', []) for r in plan['read_set'])


def test_checked_plan_reference_is_returned_for_cli_and_relative_path_api(clarify_case):
    from pathlib import Path
    from ai_sow_lite.validation import verify_plan
    from ai_sow_lite.contracts import schema_validator
    case = clarify_case
    result = notes_plan(case)
    reply = recheck(case, result)
    assert reply['ok'], reply
    assert reply['result']['plan_ref'] == result['plan_ref']
    report = verify_plan(case['project'], Path(result['plan_ref']['path']), Path(result['candidate_ref']['path']))
    assert report['valid_for_render'], report
    assert report['plan_ref'] == result['plan_ref']
    assert not list(schema_validator('artifacts', 'check').iter_errors(report))


@pytest.mark.office
@pytest.mark.parametrize('change', ['candidate_bytes', 'model_bytes', 'adopted_source', 'confirmation_source', 'current'])
def test_apply_rechecks_exact_candidate_sources_and_whole_current(prepared_case, change):
    case = prepared_case
    check_confirmation(case)
    project = case['project']
    pointer = (project / '.ai-sow-lite/current.json').read_bytes()
    candidate = read_json(project / case['result']['candidate_ref']['path'])
    if change == 'current':
        write_json(project / '.ai-sow-lite/current.json', dict(case['current'], manifest_hash='0' * 64))
        pointer = (project / '.ai-sow-lite/current.json').read_bytes()
    else:
        if change == 'candidate_bytes':
            relative = case['result']['candidate_ref']['path']
        elif change == 'model_bytes':
            relative = candidate['model_path']
        else:
            plan = read_json(project / case['confirmed_path'])
            identity = (candidate['input_version_ids'][0] if change == 'adopted_source'
                        else plan['confirmation']['input_ref']['input_version_id'])
            relative = next(e['relative_path'] for e in read_json(project / '.ai-sow-lite/inputs/index.json')['items']
                            if e['input_version_id'] == identity)
        path = project / relative
        path.write_bytes(path.read_bytes() + b'\n')
    reply = apply_confirmation(case)
    assert not reply['ok'], reply
    assert 'INTERNAL_ERROR' not in {d['code'] for d in reply['diagnostics']}
    if change == 'model_bytes':
        assert 'SCOPE_EXCEEDED' in {d['code'] for d in reply['diagnostics']}
    assert (project / '.ai-sow-lite/current.json').read_bytes() == pointer
    assert len(list((project / '.ai-sow-lite/versions').iterdir())) == 1


@pytest.mark.office
def test_archived_confirmation_has_registered_contract_and_reachable_exact_files(prepared_case):
    from ai_sow_lite.contracts import schema_validator
    import hashlib
    case = prepared_case
    applied = apply_confirmation(case)
    assert applied['ok'], applied
    directory = case['project'] / '.ai-sow-lite/versions' / applied['result']['applied_version']
    proof = read_json(directory / 'confirmation.json')
    assert not list(schema_validator('artifacts', 'clarify_confirmation').iter_errors(proof))
    for field in ('plan_ref', 'shown_plan_ref'):
        path = case['project'] / proof[field]['path']
        assert path.parent == directory
        assert hashlib.sha256(path.read_bytes()).hexdigest() == proof[field]['sha256']
    assert (directory / 'plan.json').read_bytes() == (case['project'] / case['confirmed_path']).read_bytes()
    assert (directory / 'prepared.json').read_bytes() == (case['project'] / case['prepared_ref']['path']).read_bytes()


@pytest.mark.office
@pytest.mark.parametrize('choice', ['S', 'M'])
def test_real_complexity_delivery_from_reused_i1_baseline(clarify_case, choice):
    case = clarify_case
    project = case['project']
    old = project / '.ai-sow-lite/versions' / case['current']['version_id']
    old_bytes = {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()}
    result = check_edits(case, complexity_draft(case, choice))
    assert result['ok'], result
    result = result['result']
    confirmed, _ = confirm_plan(case, result)
    checked = run_request(project, case['request_id'], 'check', dict(candidate_path=result['candidate_ref']['path'],
        plan_path=confirmed, scope='full'))
    assert checked['ok'], checked
    rendered = run_request(project, case['request_id'], 'render', dict(candidate_path=result['candidate_ref']['path'],
        check_path=checked['result']['check_ref']['path'], expected_current=case['current']))
    assert rendered['ok'], rendered
    applied = run_request(project, case['request_id'], 'apply', dict(entrypoint='clarify',
        prepared_path=rendered['result']['prepared_ref']['path'], plan_path=confirmed, expected_current=case['current']))
    assert applied['ok'], applied
    current = read_json(project / '.ai-sow-lite/current.json')
    assert current['version_id'] == rendered['result']['version_id'] != case['current']['version_id']
    destination = project / '.ai-sow-lite/versions' / current['version_id']
    candidate = read_json(project / result['candidate_ref']['path'])
    for name, key in [('model.json', 'model_path'), ('pending-items.json', 'pending_items_path'), ('decisions.json', 'decisions_path')]:
        assert (destination / name).read_bytes() == (project / candidate[key]).read_bytes()
    model = read_json(destination / 'model.json')
    assert next(t for t in model['tasks'] if t['id'] == case['ids']['T-06'])['complexity'] == choice
    assert read_json(destination / 'pending-items.json')['items'][0]['status'] == 'resolved'
    assert len(read_json(destination / 'decisions.json')['items']) == 2
    assert {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()} == old_bytes
    print('CLARIFY_REAL_DELIVERY', dict(choice=choice, base_version=case['current']['version_id'],
        version=current['version_id'], prepared_ref=rendered['result']['prepared_ref'], manifest_ref=applied['result']['manifest_ref']))


@pytest.mark.parametrize('failure', ['lineage_version', 'retired_open_target', 'dangling_evidence', 'overlap'])
def test_explicit_reference_and_obligation_errors_remain_diagnostics(clarify_case, failure):
    from ai_sow_lite.contracts import canonical_json_bytes
    case = clarify_case
    task = case['ids']['T-06'] if failure == 'retired_open_target' else case['ids']['T-01']
    lineage = dict(from_version_id=case['current']['version_id'], from_ids=[task], to_ids=[],
        reason='受控明确退出范围。', evidence_refs=[case['ids']['EV-P-B1']])
    if failure == 'lineage_version':
        lineage['from_version_id'] = str(uuid4())
    key = canonical_json_bytes([lineage['from_version_id'], lineage['from_ids']]).decode('utf-8')
    edits = [dict(op='remove', collection='tasks', object_id=task, field=None),
             dict(op='add', collection='lineage', object_id=key, field=None, value=lineage)]
    if failure == 'dangling_evidence':
        edits = [dict(op='replace', collection='stories', object_id=case['ids']['S-01'], field='evidence_refs', value=[str(uuid4())])]
    elif failure == 'overlap':
        edits.append(dict(op='replace', collection='tasks', object_id=task, field='notes', value='交叠写入'))
    pointer = (case['project'] / '.ai-sow-lite/current.json').read_bytes()
    reply = check_edits(case, edit_draft(case, edits))
    assert not reply['ok'], reply
    assert reply['diagnostics'] and 'INTERNAL_ERROR' not in {d['code'] for d in reply['diagnostics']}
    assert (case['project'] / '.ai-sow-lite/current.json').read_bytes() == pointer


@pytest.mark.office
def test_superseded_layout_preview_reprojects_once_without_erasing_old_files(prepared_case,monkeypatch):
    from ai_sow_lite import office,workbook
    from ai_sow_lite.contracts import semantic_digest
    from ai_sow_lite.project import StorageError
    case=prepared_case;project=case['project'];result=case['result']
    candidate=project/result['candidate_ref']['path']
    attempt_path=candidate.with_name('render-attempt.json')
    attempt=read_json(attempt_path)
    payload=dict(candidate_path=result['candidate_ref']['path'],check_path=result['check_ref']['path'],expected_current=case['current'])
    attempt.update(implementation_version='lite-render-v5',signature=semantic_digest(dict(
        check=read_json(project/payload['check_path']),payload=payload,projector_version='lite-projection-v1',
        engine=office.selection_fingerprint(),implementation_version='lite-render-v5')))
    write_json(attempt_path,attempt)
    old_dir=(project/attempt['prepared_ref']['path']).parent
    old_files={p:p.read_bytes() for p in old_dir.iterdir() if p.is_file()}
    class OfficeBoundaryReached(Exception):pass
    def stop(source,destination):
        import openpyxl
        assert openpyxl.load_workbook(source).sheetnames==list(workbook.SHEETS)
        raise OfficeBoundaryReached
    monkeypatch.setattr(office,'recalculate',stop)
    with pytest.raises(OfficeBoundaryReached):workbook.render_candidate(project,case['request_id'],payload)
    assert all(p.read_bytes()==raw for p,raw in old_files.items())
    checkpoint=read_json(project/'.ai-sow-lite/work/clarify'/case['request_id']/'checkpoint.json')
    assert checkpoint['operation_retries']['render']==1
    with pytest.raises(StorageError,match='LOOP_LIMIT_REACHED'):workbook.render_candidate(project,case['request_id'],payload)
    assert read_json(project/'.ai-sow-lite/current.json')==case['current']
