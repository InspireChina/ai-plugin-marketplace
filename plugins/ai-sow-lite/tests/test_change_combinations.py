"""Bounded change consumers; only explicitly marked tests invoke real Office."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from ai_sow_lite.project import file_ref
from .support.clarify import (delivered_baseline, clarify_case, check_edits, edit_draft,
                              adopt_feedback, feedback, controlled_base_change, refresh_controlled_projection)
from .support.cli import run_request
from .support.fixtures import read_json, write_json


def note(case, name='S-01', value='已展示的具体备注'):
    return dict(op='replace', collection='stories', object_id=case['ids'][name], field='notes', value=value)


def draft_ref(case, result):
    return file_ref(case['project'], (case['project'] / result['candidate_ref']['path']).with_name('edit-draft.json'))


def repair(case, draft, result, operation='topic-related-identity'):
    return dict(deepcopy(draft), repair=dict(draft_ref=draft_ref(case, result), operation=operation,
                                           reason='按实际诊断修正引用的对象身份；保留原专业方案。'))


def recheck(case, result, plan_path=None):
    return run_request(case['project'], case['request_id'], 'check', dict(scope='full',
        candidate_path=result['candidate_ref']['path'], plan_path=plan_path or result['plan_ref']['path']))


def test_failed_topic_candidate_repair_leaves_one_professional_revision(clarify_case):
    case = clarify_case
    refs = adopt_feedback(case, '仅更新两项备注，其他义务保留。', case['ids']['P-01'])
    draft = edit_draft(case, [note(case), note(case, 'S-02')], refs['input_version_ids'])
    draft['additional_refs'] = refs
    failed = check_edits(case, draft)
    assert not failed['ok']
    assert 'CANDIDATE_INVALID' in {d['code'] for d in failed['diagnostics']}
    saved = draft_ref(case, failed['result'])
    failed_bytes = (case['project'] / saved['path']).read_bytes()
    corrected = repair(case, draft, failed['result'])
    corrected['additional_refs'] = adopt_feedback(case, '仅更新两项备注，其他义务保留。', case['ids']['S-01'])
    valid = check_edits(case, corrected)
    assert valid['ok'], valid
    assert read_json(case['project'] / valid['result']['plan_ref']['path'])['revision'] == 1
    assert (case['project'] / saved['path']).read_bytes() == failed_bytes
    repeated = check_edits(case, corrected)
    assert repeated['ok'], repeated
    assert repeated['result']['candidate_ref'] == valid['result']['candidate_ref']
    revised = dict(deepcopy(corrected), revision=2)
    revised.pop('repair')
    revised['edits'][0]['value'] = '唯一一次专业修订的具体备注'
    second = check_edits(case, revised)
    assert second['ok'], second
    assert read_json(case['project'] / second['result']['plan_ref']['path'])['revision'] == 2
    selected = dict(deepcopy(revised), subset_of=second['result']['plan_ref'])
    selected['edits'] = selected['edits'][:1]
    subset = check_edits(case, selected)
    assert subset['ok'], subset
    assert read_json(case['project'] / subset['result']['plan_ref']['path'])['revision'] == 2
    exhausted = dict(deepcopy(revised), revision=3)
    assert not check_edits(case, exhausted)['ok']
    checkpoint = read_json(case['project'] / f".ai-sow-lite/work/clarify/{case['request_id']}/checkpoint.json")
    assert checkpoint['repair_batches'] == 1
    assert checkpoint['operation_retries']['topic-related-identity'] == 1


def test_r2_pure_subset_binds_original_shown_plan_and_selection_input(clarify_case):
    case = clarify_case
    draft = edit_draft(case, [note(case), note(case, 'S-02')])
    assert check_edits(case, draft)['ok']
    draft['revision'] = 2
    draft['edits'][0]['value'] = '修订后展示的具体备注'
    shown = check_edits(case, draft)
    assert shown['ok'], shown
    shown_plan = read_json(case['project'] / shown['result']['plan_ref']['path'])
    # This is the one actual execution input, supplied after viewing the complete plan.
    selection = feedback(case, '只执行刚展示的资料查询备注，资料新增备注暂缓。\n')
    subset = dict(deepcopy(draft), subset_of=shown['result']['plan_ref'])
    subset['edits'] = subset['edits'][:1]
    selected = check_edits(case, subset)
    assert selected['ok'], selected
    plan = read_json(case['project'] / selected['result']['plan_ref']['path'])
    assert plan['revision'] == 2
    assert plan['changes'] == shown_plan['changes'][:1]
    locator = dict(kind='text_lines', start_line=1, end_line=1)
    observed = run_request(case['project'], case['request_id'], 'inspect', dict(view='regions',
        selector=dict(input_version_id=selection, locator=locator)))
    report = read_json(case['project'] / selected['result']['check_ref']['path'])
    plan['confirmation'] = dict(digest=report['plan_digest'], shown_plan_ref=shown['result']['plan_ref'],
        selected_changes=deepcopy(plan['changes']), input_ref=dict(input_version_id=selection, locator=locator,
            excerpt_hash=observed['result']['coverage']['excerpt_hash']))
    path = Path(selected['result']['plan_ref']['path']).with_name('confirmed-plan.json')
    write_json(case['project'] / path, plan)
    assert recheck(case, selected['result'], path.as_posix())['ok']
    from ai_sow_lite.changes import confirmation_details, confirmation_files
    details = confirmation_details(case['project'], path.as_posix(), selected['result']['candidate_ref']['path'])
    assert details['shown_plan_ref'] == shown['result']['plan_ref']
    # Archive consumer exercised with existing bytes; this does not claim a prepared delivery.
    archive = confirmation_files(case['project'], details, selected['result']['candidate_ref']['path'],
                                 selected['result']['check_ref']['path'], str(uuid4()))
    assert archive['shown-plan.json'] == (case['project'] / shown['result']['plan_ref']['path']).read_bytes()
    assert read_json(case['project'] / '.ai-sow-lite/current.json') == case['current']
    # A freshly extracted child was not the original displayed proposal.
    plan['confirmation']['shown_plan_ref'] = selected['result']['plan_ref']
    write_json(case['project'] / path, plan)
    assert not recheck(case, selected['result'], path.as_posix())['ok']


def test_failed_structure_is_saved_and_repaired_without_resetting_request(clarify_case):
    case = clarify_case
    draft = edit_draft(case, [note(case, value=7)])
    assert not check_edits(case, draft)['ok']
    checkpoint_path = case['project'] / f".ai-sow-lite/work/clarify/{case['request_id']}/checkpoint.json"
    checkpoint = read_json(checkpoint_path)
    ref = checkpoint['clarify_draft_ref']
    raw = (case['project'] / ref['path']).read_bytes()
    fixed = deepcopy(draft)
    fixed['edits'][0]['value'] = '实际诊断后的合法文字'
    fixed['repair'] = dict(draft_ref=ref, operation='notes-type', reason='把错误整数按原稿恢复为文字。')
    assert check_edits(case, fixed)['ok']
    assert (case['project'] / ref['path']).read_bytes() == raw
    assert read_json(checkpoint_path)['repair_batches'] == 1


def test_candidate_once_operation_once_and_request_two_repairs_are_shared(clarify_case):
    case = clarify_case
    draft = edit_draft(case, [note(case), note(case, 'S-02')])
    first = check_edits(case, draft)
    fixed = repair(case, draft, first['result'], 'first-root-cause')
    fixed['change_summary'] = '修正可读方案遗漏。'
    repaired = check_edits(case, fixed)
    assert repaired['ok'], repaired
    twice = repair(case, fixed, repaired['result'], 'renamed-root-cause')
    twice['change_summary'] = '不能通过改名再次返修同一候选。'
    assert not check_edits(case, twice)['ok']
    second = dict(deepcopy(draft), revision=2, change_summary='唯一专业修订')
    result = check_edits(case, second)
    assert result['ok'], result
    same_operation = repair(case, second, result['result'], 'first-root-cause')
    assert not check_edits(case, same_operation)['ok']
    fixed_second = repair(case, second, result['result'], 'second-root-cause')
    result = check_edits(case, fixed_second)
    assert result['ok'], result
    subset = dict(deepcopy(second), subset_of=result['result']['plan_ref'])
    subset['edits'] = subset['edits'][:1]
    selected = check_edits(case, subset)
    assert selected['ok'], selected
    third = repair(case, subset, selected['result'], 'third-root-cause')
    denied = check_edits(case, third)
    assert not denied['ok']
    assert {d['code'] for d in denied['diagnostics']} == {'LOOP_LIMIT_REACHED'}
    checkpoint = read_json(case['project'] / f".ai-sow-lite/work/clarify/{case['request_id']}/checkpoint.json")
    assert checkpoint['repair_batches'] == 2


@pytest.mark.parametrize('change', ['new_value', 'new_condition', 'removed_condition', 'boundary', 'read_set',
                                  'whole_plan', 'shown_bytes'])
def test_pure_subset_rejects_unshown_values_or_premise_changes(clarify_case, change):
    case = clarify_case
    draft = edit_draft(case, [note(case), note(case, 'S-02')])
    draft['conditions'] = ['保留现有验收义务。']
    shown = check_edits(case, draft)
    assert shown['ok'], shown
    subset = dict(deepcopy(draft), subset_of=shown['result']['plan_ref'])
    subset['edits'] = subset['edits'][:1]
    if change == 'new_value':
        subset['edits'][0]['value'] = '未展示的新值'
    elif change == 'new_condition':
        subset['conditions'].append('额外执行条件。')
    elif change == 'removed_condition':
        subset['conditions'] = []
    elif change == 'boundary':
        subset['read_boundary']['object_ids'] = []
    elif change == 'read_set':
        subset['read_selectors'] = []
    elif change == 'whole_plan':
        subset['edits'] = draft['edits']
    else:
        path = case['project'] / shown['result']['plan_ref']['path']
        path.write_bytes(path.read_bytes() + b'\n')
    denied = check_edits(case, subset)
    assert not denied['ok'], denied
    assert 'INTERNAL_ERROR' not in {d['code'] for d in denied['diagnostics']}
    assert read_json(case['project'] / '.ai-sow-lite/current.json') == case['current']


def test_subset_cannot_nest_or_fork_another_selection_slot(clarify_case):
    case = clarify_case
    draft = edit_draft(case, [note(case), note(case, 'S-02'), note(case, 'S-03')])
    result = check_edits(case, draft)
    subset = dict(deepcopy(draft), subset_of=result['result']['plan_ref'])
    subset['edits'] = subset['edits'][:2]
    selected = check_edits(case, subset)
    assert selected['ok'], selected
    nested = dict(deepcopy(subset), subset_of=selected['result']['plan_ref'])
    nested['edits'] = nested['edits'][:1]
    assert not check_edits(case, nested)['ok']
    subset['edits'] = subset['edits'][1:]
    assert not check_edits(case, subset)['ok']


def base_documents(case):
    path = case['project'] / '.ai-sow-lite/versions' / case['current']['version_id']
    return read_json(path / 'model.json'), read_json(path / 'pending-items.json')


def lineage_edit(case, old_ids, new_ids):
    from ai_sow_lite.contracts import canonical_json_bytes
    value = dict(from_version_id=case['current']['version_id'], from_ids=old_ids, to_ids=new_ids,
                 reason='本次已明确的义务去向；机械组合夹具。', evidence_refs=[case['ids']['EV-P-B1']])
    identity = canonical_json_bytes([value['from_version_id'], old_ids]).decode('utf-8')
    return dict(op='add', collection='lineage', object_id=identity, field=None, value=value)


@pytest.mark.parametrize('operation', ['split', 'merge'])
def test_story_split_merge_lineage_preserves_existing_ac_and_task_identities(clarify_case, operation):
    case = clarify_case
    before, _ = base_documents(case)
    originals = before['stories'][:1 if operation == 'split' else 2]
    if operation == 'split':
        successors = [dict(deepcopy(originals[0]), id=str(uuid4()), acs=[deepcopy(ac)], title=f'明确拆分义务 {i}')
                      for i, ac in enumerate(originals[0]['acs'])]
        destinations = {case['ids']['T-01']: successors[0]['id'], case['ids']['T-02']: successors[1]['id']}
    else:
        successors = [dict(deepcopy(originals[0]), id=str(uuid4()), title='明确合并的查询交付',
                           acs=deepcopy(originals[0]['acs'] + originals[1]['acs']))]
        destinations = {t['id']: successors[0]['id'] for t in before['tasks']
                        if t['story_id'] in [s['id'] for s in originals]}
    edits = [dict(op='remove', collection='stories', object_id=s['id'], field=None) for s in originals]
    edits += [dict(op='add', collection='stories', object_id=s['id'], field=None, value=s) for s in successors]
    edits += [dict(op='replace', collection='tasks', object_id=task, field='story_id', value=parent)
              for task, parent in destinations.items()]
    for relation in before['dependencies']:
        if relation['from_story_id'] in [s['id'] for s in originals]:
            if operation == 'merge' and relation['id'] == case['ids']['R-02']:
                # Explicitly retire the duplicate relation after merging parents; retain all Tasks.
                edits.append(dict(op='remove', collection='dependencies', object_id=relation['id'], field=None))
            else:
                edits.append(dict(op='replace', collection='dependencies', object_id=relation['id'],
                                  field='from_story_id', value=successors[0]['id']))
    edits.append(lineage_edit(case, [s['id'] for s in originals], [s['id'] for s in successors]))
    if operation == 'merge':
        retired_feature = originals[1]['feature_id']
        edits += [dict(op='remove', collection='features', object_id=retired_feature, field=None),
                  lineage_edit(case, [retired_feature], [originals[0]['feature_id']])]
    draft = edit_draft(case, edits)
    draft['read_boundary']['object_ids'] = [s['id'] for s in originals] + [s['id'] for s in successors]
    result = check_edits(case, draft)
    assert result['ok'], result
    candidate = read_json(case['project'] / result['result']['candidate_ref']['path'])
    actual = read_json(case['project'] / candidate['model_path'])
    assert [t['id'] for t in actual['tasks']] == [t['id'] for t in before['tasks']]
    for old, new in zip(before['tasks'], actual['tasks']):
        assert new == dict(old, story_id=destinations.get(old['id'], old['story_id']))
    assert {a['id']: a for s in actual['stories'] for a in s['acs']} == {a['id']: a for s in before['stories'] for a in s['acs']}
    assert actual['lineage'][0]['from_version_id'] == case['current']['version_id']
    assert actual['lineage'][0]['to_ids'] == [s['id'] for s in successors]
    assert recheck(case, result['result'])['ok']


def test_partial_answer_keeps_remaining_targets_open_with_a_new_question_revision(clarify_case):
    case = clarify_case
    _, pending = base_documents(case)
    question = pending['items'][0]
    remaining = dict(object_id=case['ids']['T-07'], field='notes')
    question['targets'].append(remaining)
    question['question'] = '确认迁移复杂度，并补充发布说明。'
    controlled_base_change(case, 'pending-items.json', pending)
    refs = adopt_feedback(case, '迁移按默认 M；发布说明尚未答复。', case['ids']['T-06'])
    decision = dict(id=str(uuid4()), kind='scope_decision', text='迁移采用 M；发布说明保持待确认。',
        applies_to=[dict(object_id=case['ids']['T-06'], field='complexity')], evidence_refs=refs['evidence_ids'])
    changes = [('targets', [remaining]), ('question', '请补充发布说明。'), ('revision', 2),
               ('current_handling', '已采用迁移 M；发布说明仍待补充。')]
    edits = [dict(op='replace', collection='pending_items', object_id=question['id'], field=k, value=v) for k, v in changes]
    edits.append(dict(op='add', collection='decisions', object_id=decision['id'], field=None, value=decision))
    draft = edit_draft(case, edits)
    draft['additional_refs'] = refs
    draft['unresolved_items'] = [question['id']]
    checked = check_edits(case, draft)
    assert checked['ok'], checked
    candidate = read_json(case['project'] / checked['result']['candidate_ref']['path'])
    actual = read_json(case['project'] / candidate['pending_items_path'])['items'][0]
    assert (actual['id'], actual['revision'], actual['status'], actual['targets'], actual['resolution']) == (
        question['id'], 2, 'open', [remaining], None)
    assert '已采用迁移 M' in actual['current_handling']
    assert read_json(case['project'] / candidate['decisions_path'])['items'][-1] == decision


@pytest.mark.parametrize('outcome', ['fulfilled', 'exited'])
def test_unestimated_obligation_has_explicit_fulfillment_or_exit(clarify_case, outcome):
    case = clarify_case
    before, pending = base_documents(case)
    extra = dict(deepcopy(before['stories'][0]), id=str(uuid4()), title='明确待拆交付义务',
                 acs=[dict(deepcopy(before['stories'][0]['acs'][0]), id=str(uuid4()))])
    before['stories'].append(extra)
    gap = dict(deepcopy(pending['items'][0]), id=str(uuid4()), question='此义务还需拆明工作。',
               targets=[dict(object_id=extra['id'], field=None)], unestimated_work=True)
    pending['items'].append(gap)
    controlled_base_change(case, 'model.json', before)
    controlled_base_change(case, 'pending-items.json', pending)
    refresh_controlled_projection(case)
    if outcome == 'fulfilled':
        task = dict(deepcopy(before['tasks'][0]), id=str(uuid4()), story_id=extra['id'], name='明确补齐的交付工作')
        decision = dict(id=str(uuid4()), kind='scope_decision', text='已明确工作去向。',
                        applies_to=gap['targets'], evidence_refs=extra['evidence_refs'])
        edits = [dict(op='add', collection='tasks', object_id=task['id'], field=None, value=task),
                 dict(op='add', collection='decisions', object_id=decision['id'], field=None, value=decision)]
        changes = [('status', 'resolved'), ('revision', 2), ('unestimated_work', False),
                   ('current_handling', '已明确拆成所列工作。'), ('resolution', dict(decision_id=decision['id'],
                    request_id=case['request_id'], summary='已明确工作去向。'))]
    else:
        lineage = lineage_edit(case, [extra['id']], [])
        edits = [dict(op='remove', collection='stories', object_id=extra['id'], field=None), lineage]
        changes = [('status', 'superseded'), ('current_handling', '明确退出本期，未视为已回答。'),
                   ('resolution', dict(replacement_item_ids=[], lineage_refs=[dict(
                       from_version_id=case['current']['version_id'], from_ids=[extra['id']])],
                       request_id=case['request_id'], reason='用户明确退出本期。'))]
    edits += [dict(op='replace', collection='pending_items', object_id=gap['id'], field=k, value=v) for k, v in changes]
    checked = check_edits(case, edit_draft(case, edits))
    assert checked['ok'], checked
    candidate = read_json(case['project'] / checked['result']['candidate_ref']['path'])
    actual = read_json(case['project'] / candidate['pending_items_path'])['items'][-1]
    assert actual['status'] == ('resolved' if outcome == 'fulfilled' else 'superseded')
    model = read_json(case['project'] / candidate['model_path'])
    assert model['tasks'][:len(before['tasks'])] == before['tasks']
    assert read_json(case['project'] / candidate['pending_items_path'])['items'][0] == pending['items'][0]


def confirmed_subset(case, draft):
    """Controller selects after seeing the full plan; no second approval input."""
    shown = check_edits(case, draft)
    assert shown['ok'], shown
    selection = feedback(case, '只执行刚展示的资料查询备注；另一项暂缓。\n')
    assert recheck(case, shown['result'])['ok']
    subset = dict(deepcopy(draft), subset_of=shown['result']['plan_ref'])
    subset['edits'] = subset['edits'][:1]
    selected = check_edits(case, subset)
    assert selected['ok'], selected
    plan = read_json(case['project'] / selected['result']['plan_ref']['path'])
    report = read_json(case['project'] / selected['result']['check_ref']['path'])
    locator = dict(kind='text_lines', start_line=1, end_line=1)
    observed = run_request(case['project'], case['request_id'], 'inspect', dict(view='regions',
        selector=dict(input_version_id=selection, locator=locator)))
    assert observed['ok'], observed
    plan['confirmation'] = dict(digest=report['plan_digest'], shown_plan_ref=shown['result']['plan_ref'],
        selected_changes=deepcopy(plan['changes']), input_ref=dict(input_version_id=selection, locator=locator,
            excerpt_hash=observed['result']['coverage']['excerpt_hash']))
    path = Path(selected['result']['plan_ref']['path']).with_name('confirmed-plan.json').as_posix()
    write_json(case['project'] / path, plan)
    assert recheck(case, selected['result'], path)['ok']
    from ai_sow_lite.changes import confirmation_details
    details = confirmation_details(case['project'], path, selected['result']['candidate_ref']['path'])
    return shown['result'], selected['result'], path, details


def test_subset_confirmation_permanent_dependencies_survive_input_append(clarify_case):
    from ai_sow_lite.project import StorageError, _verify_refs
    case = clarify_case
    draft = edit_draft(case, [note(case), note(case, 'S-02')])
    shown, selected, path, details = confirmed_subset(case, draft)
    # project.apply_prepared appends this list to the permanent manifest unchanged.
    dependencies = details['dependencies']
    transient = [r['path'] for r in dependencies if r['path'].startswith('.ai-sow-lite/work/')
                 or r['path'] in ('.ai-sow-lite/inputs/index.json', '.ai-sow-lite/current.json')]
    assert transient == []
    paths = {r['path'] for r in dependencies}
    original_source = next(p for p in paths if p.startswith('.ai-sow-lite/inputs/originals/') and p.endswith('.md'))
    assert any(p.startswith('.ai-sow-lite/analysis/') for p in paths)
    assert f".ai-sow-lite/versions/{case['current']['version_id']}/manifest.json" in paths
    assert shown['plan_ref']['path'] not in paths  # separately verified and archived
    _verify_refs(case['project'], dependencies)
    feedback(case, '后续新增事实，尚未应用。\n')
    _verify_refs(case['project'], dependencies)
    assert recheck(case, selected, path)['ok']
    source = case['project'] / original_source
    source.write_bytes(source.read_bytes() + b'changed')
    with pytest.raises(StorageError) as error:
        _verify_refs(case['project'], dependencies)
    assert error.value.diagnostics[0]['code'] == 'EVIDENCE_MISSING'
    assert not recheck(case, selected, path)['ok']


@pytest.mark.office
def test_real_subset_delivery_recovers_after_later_input_append(clarify_case):
    case = clarify_case
    project = case['project']
    old = project / '.ai-sow-lite/versions' / case['current']['version_id']
    old_bytes = {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()}
    shown, selected, confirmed, _ = confirmed_subset(case, input_read_draft(case))
    checked = recheck(case, selected, confirmed)
    assert checked['ok'], checked
    rendered = run_request(project, case['request_id'], 'render', dict(
        candidate_path=selected['candidate_ref']['path'],
        check_path=checked['result']['check_ref']['path'], expected_current=case['current']))
    assert rendered['ok'], rendered
    applied = run_request(project, case['request_id'], 'apply', dict(entrypoint='clarify',
        prepared_path=rendered['result']['prepared_ref']['path'],
        plan_path=confirmed, expected_current=case['current']))
    assert applied['ok'], applied
    current = read_json(project / '.ai-sow-lite/current.json')
    directory = project / '.ai-sow-lite/versions' / current['version_id']
    before, after = read_json(old / 'model.json'), read_json(directory / 'model.json')
    expected = deepcopy(before)
    next(s for s in expected['stories'] if s['id'] == case['ids']['S-01'])['notes'] = '已展示的具体备注'
    assert after == expected
    assert (directory / 'pending-items.json').read_bytes() == old_bytes['pending-items.json']
    manifest = read_json(directory / 'manifest.json')
    from ai_sow_lite.project import _verify_refs
    _verify_refs(project, manifest['dependencies'])
    archived = list(directory.rglob('shown-plan.json'))
    assert len(archived) == 1
    assert archived[0].read_bytes() == (project / shown['plan_ref']['path']).read_bytes()
    feedback(case, '后续一项独立事实，尚未形成修改方案。\n')
    recovered = run_request(project, case['request_id'], 'recover', dict(target_request_id=case['request_id']))
    assert recovered['ok'], recovered
    assert read_json(project / '.ai-sow-lite/current.json') == current
    _verify_refs(project, manifest['dependencies'])
    assert {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()} == old_bytes


def test_subset_confirmation_still_rechecks_full_shown_candidate(clarify_case):
    case = clarify_case
    shown, selected, path, _ = confirmed_subset(case, edit_draft(case, [note(case), note(case, 'S-02')]))
    candidate = read_json(case['project'] / shown['candidate_ref']['path'])
    model_path = case['project'] / candidate['model_path']
    model = read_json(model_path)
    model['stories'][1]['notes'] = '篡改原展示但未被选择的内容。'
    write_json(model_path, model)
    rejected = recheck(case, selected, path)
    assert not rejected['ok'], rejected
    assert 'INTERNAL_ERROR' not in {d['code'] for d in rejected['diagnostics']}


def test_new_history_invalidates_adopted_zero_match_without_reclassifying_tasks(clarify_case):
    case = clarify_case
    selector = dict(historical_label='资料查询API', uses=['as-is'])
    first = run_request(case['project'], case['request_id'], 'inspect', dict(view='topics', selector=selector))
    assert first['ok'] and first['result']['matched_count'] == 0, first
    draft = edit_draft(case, [note(case)])
    draft['read_selectors'].append(dict(view='topics', selector=selector))
    shown = check_edits(case, draft)
    assert shown['ok'], shown
    history = case['project'].parent / 'new-history.md'
    history.write_text('历史范围含资料查询API；实例是否相同尚未确认。\n', encoding='utf-8')
    added = run_request(case['project'], case['request_id'], 'ingest', dict(kind='sources',
        entrypoint='clarify', project_type='new', sources=[dict(source_path=str(history), input_id=None,
        material_types=['prior-sow'], uses=['as-is'], use_regions=[])]))
    assert added['ok'], added
    rejected = recheck(case, shown['result'])
    assert not rejected['ok'], rejected
    assert 'INTERNAL_ERROR' not in {d['code'] for d in rejected['diagnostics']}
    assert read_json(case['project'] / '.ai-sow-lite/current.json') == case['current']
    candidate = read_json(case['project'] / shown['result']['candidate_ref']['path'])
    current_model = case['project'] / '.ai-sow-lite/versions' / case['current']['version_id'] / 'model.json'
    assert read_json(case['project'] / candidate['model_path'])['tasks'] == read_json(current_model)['tasks']


def input_read_draft(case):
    entry = read_json(case['project'] / '.ai-sow-lite/inputs/index.json')['items'][0]
    draft = edit_draft(case, [note(case), note(case, 'S-02')])
    draft['read_selectors'].append(dict(view='inputs', selector=dict(input_version_ids=[entry['input_version_id']])))
    draft['read_boundary']['input_version_ids'] = [entry['input_version_id']]
    return draft


def test_subset_inherits_precise_input_read_and_original_snapshot_after_selection(clarify_case):
    case = clarify_case
    shown, selected, path, _ = confirmed_subset(case, input_read_draft(case))
    original = read_json(case['project'] / shown['plan_ref']['path'])
    child = read_json(case['project'] / selected['plan_ref']['path'])
    original_check = read_json(case['project'] / shown['check_ref']['path'])
    child_check = read_json(case['project'] / selected['check_ref']['path'])
    assert child['read_set'] == original['read_set']
    assert child_check['input_index_snapshot_ref'] == original_check['input_index_snapshot_ref']
    snapshot = read_json(case['project'] / child_check['input_index_snapshot_ref']['path'])
    live = read_json(case['project'] / '.ai-sow-lite/inputs/index.json')
    assert live['items'][:len(snapshot['items'])] == snapshot['items']
    assert len(live['items']) == len(snapshot['items']) + 1
    observed = run_request(case['project'], case['request_id'], 'inspect', dict(view='inputs',
        selector=child['read_set'][-1]['selector']['selector']))
    assert observed['result']['selected_version'] != child['read_set'][-1]['observed_version']
    feedback(case, '另一项尚待以后决定。\n')
    assert recheck(case, selected, path)['ok']
    assert read_json(case['project'] / '.ai-sow-lite/current.json') == case['current']


@pytest.mark.parametrize('change', ['whole_index', 'selected_entry', 'removed_selector', 'changed_selector',
                                  'condition', 'snapshot'])
def test_subset_snapshot_inheritance_does_not_waive_changed_inputs_or_premises(clarify_case, change):
    case = clarify_case
    draft = input_read_draft(case)
    if change == 'whole_index':
        draft['read_selectors'][-1]['selector'] = {}
    shown = check_edits(case, draft)
    assert shown['ok'], shown
    feedback(case, '只执行刚展示的第一项；其余暂缓。\n')
    subset = dict(deepcopy(draft), subset_of=shown['result']['plan_ref'])
    subset['edits'] = subset['edits'][:1]
    if change == 'selected_entry':
        index_path = case['project'] / '.ai-sow-lite/inputs/index.json'
        index = read_json(index_path)
        index['items'][0]['uses'] = ['as-is']
        write_json(index_path, index)
    elif change == 'removed_selector':
        subset['read_selectors'].pop()
    elif change == 'changed_selector':
        index = read_json(case['project'] / '.ai-sow-lite/inputs/index.json')
        subset['read_selectors'][-1]['selector']['input_version_ids'] = [index['items'][1]['input_version_id']]
    elif change == 'condition':
        subset['conditions'] = ['新增执行前提。']
    elif change == 'snapshot':
        report = read_json(case['project'] / shown['result']['check_ref']['path'])
        snapshot = case['project'] / report['input_index_snapshot_ref']['path']
        snapshot.write_bytes(snapshot.read_bytes() + b'\n')
    rejected = check_edits(case, subset)
    assert not rejected['ok'], rejected
    assert 'INTERNAL_ERROR' not in {d['code'] for d in rejected['diagnostics']}
    assert read_json(case['project'] / '.ai-sow-lite/current.json') == case['current']
