"""Synthetic, in-memory protocol cases; no model, workbook or product flow."""
from __future__ import annotations
import copy
import json
import sys
from pathlib import Path
import pytest
TEST_LAYER = 'unit'
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from contracts import canonical_json_bytes as encode, sha256_bytes as digest, InvalidActionResult
import candidate_repair as repair


def field_case():
    base = encode({'tasks': [{'localKey': 't1', 'title': ''}, {'localKey': 't2', 'title': '保留'}]})
    origin = {'runId': 'run-test', 'inputRevisionSha256': '1'*64,
        'originLogicalWorkId': 'task-work-1', 'sourceKind': 'AUTHOR_FAILURE',
        'sourceActionContractId': 'TASK-v2', 'sourceAttemptRecordSha256': '2'*64,
        'stageKind': 'TASK', 'repairRound': 2, 'budgetPolicySha256': '3'*64}
    report = {'candidateSha256': digest(base), 'inputRevisionSha256': '1'*64,
        'sourceAttemptRecordSha256': '2'*64, 'owner': 'TASK', 'checkerFingerprint': 'a'*64,
        'checkedDomains': ['tasks/t1/title'], 'blockedChecks': [], 'issues': [
        {'issueId': 'i1', 'code': 'EMPTY_TITLE', 'subjects': [{'objectId': 'tasks/t1'}],
         'paths': ['/tasks/0/title'], 'observed': '', 'expectedConstraint': '非空标题',
         'evidenceRefs': [], 'dependencyRefs': [], 'repairOwner': 'TASK', 'repairClass': 'DATA', 'causedBy': []}]}
    groups = [{'groupId': 'fix-t1', 'issueIds': ['i1'], 'readSet': [{'objectId': 'tasks/t1', 'fields': ['title']}],
        'slots': [{'slotId': 't1-title', 'operation': 'SET_FIELD', 'collection': 'tasks',
                   'objectId': 'tasks/t1', 'field': 'title', 'oldValueSha256': digest(encode('')),
                   'valueSchema': {'type': 'string', 'minLength': 1}}],
        'verificationObligations': ['NONEMPTY_TITLE']}]
    return base, report, groups, origin


def proposal(plan, value='修复后的标题'):
    body = json.loads(plan)
    return encode({'repairPlanSha256': digest(plan), 'baseCandidateSha256': body['baseCandidateSha256'],
                   'groupId': 'fix-t1', 'operations': [{'slotId': 't1-title', 'value': value}]})


def verify_title(raw, group):
    if not json.loads(raw)['tasks'][0]['title']:
        raise InvalidActionResult('标题不能为空。')


def test_patch_changes_only_granted_field():
    base, report, groups, origin = field_case()
    plan = repair.build_repair_plan(base, report, groups, origin=origin)
    merged, receipt = repair.apply_repair_patch(base, plan, proposal(plan), group_id='fix-t1', verify_group=verify_title)
    assert json.loads(merged) == {'tasks': [{'localKey': 't1', 'title': '修复后的标题'}, {'localKey': 't2', 'title': '保留'}]}
    assert json.loads(base)['tasks'][0]['title'] == ''
    assert json.loads(receipt)['mergedCandidateSha256'] == digest(merged)


@pytest.mark.parametrize('attack', ['unknown', 'extra', 'duplicate', 'stale', 'type', 'empty', 'permission'])
def test_patch_rejects_ungranted_or_stale_changes(attack):
    base, report, groups, origin = field_case()
    plan = repair.build_repair_plan(base, report, groups, origin=origin)
    patch = json.loads(proposal(plan))
    if attack == 'unknown': patch['operations'][0]['slotId'] = 't2-title'
    if attack == 'extra': patch['tasks'] = []
    if attack == 'duplicate': patch['operations'] *= 2
    if attack == 'stale': patch['baseCandidateSha256'] = '9'*64
    if attack == 'type': patch['operations'][0]['value'] = 4
    if attack == 'empty': patch['operations'] = []
    if attack == 'permission': patch['operations'][0]['field'] = 'localKey'
    with pytest.raises(InvalidActionResult):
        repair.apply_repair_patch(base, plan, encode(patch), group_id='fix-t1', verify_group=verify_title)
    assert json.loads(base)['tasks'][1]['title'] == '保留'


def test_owner_failure_does_not_commit_atomic_group():
    base, report, groups, origin = field_case()
    plan = repair.build_repair_plan(base, report, groups, origin=origin)
    def reject(raw, group): raise InvalidActionResult('本组引用义务未关闭。')
    with pytest.raises(InvalidActionResult):
        repair.apply_repair_patch(base, plan, proposal(plan), group_id='fix-t1', verify_group=reject)
    assert json.loads(base)['tasks'][0]['title'] == ''


def test_duplicate_and_anonymous_occurrences_have_distinct_identity():
    raw = encode({'tasks': [{'localKey': 'same'}, {'localKey': 'same'}], 'notes': [{'reason': '保留'}, {'reason': '保留'}]})
    index = repair.index_candidate(raw)
    rows = [row for row in index if row['collection'] in {'tasks', 'notes'}]
    assert len(rows) == 4
    assert len({row['objectId'] for row in rows}) == 4
    assert {row['path'] for row in rows} == {'/tasks/0', '/tasks/1', '/notes/0', '/notes/1'}


def test_plan_rejects_drifted_old_value_and_duplicate_slot():
    base, report, groups, origin = field_case()
    groups[0]['slots'][0]['oldValueSha256'] = '9'*64
    with pytest.raises(InvalidActionResult): repair.build_repair_plan(base, report, groups, origin=origin)
    groups[0]['slots'][0]['oldValueSha256'] = digest(encode(''))
    groups[0]['slots'] *= 2
    with pytest.raises(InvalidActionResult): repair.build_repair_plan(base, report, groups, origin=origin)


def test_append_and_remove_preserve_anonymous_occurrences():
    base, report, groups, origin = field_case()
    base = encode({'notes': [{'reason': '保留'}, {'reason': '保留'}]})
    report['candidateSha256'] = digest(base)
    rows = [r for r in repair.index_candidate(base) if r['collection'] == 'notes']
    group = groups[0]; group['readSet'] = []
    group['slots'] = [{'slotId': 'remove-duplicate', 'operation': 'REMOVE_OBJECT', 'collection': 'notes',
        'objectId': rows[0]['objectId'], 'oldValueSha256': digest(encode({'reason':'保留'}))}]
    plan = repair.build_repair_plan(base, report, groups, origin=origin)
    patch = encode({'repairPlanSha256':digest(plan),'baseCandidateSha256':digest(base),'groupId':'fix-t1',
                    'operations':[{'slotId':'remove-duplicate'}]})
    merged, receipt = repair.apply_repair_patch(base, plan, patch, group_id='fix-t1', verify_group=lambda *_: None)
    assert json.loads(merged) == {'notes':[{'reason':'保留'}]}
    kept = [r for r in json.loads(receipt)['objectIndex'] if r['collection']=='notes']
    assert kept[0]['objectId'] == rows[1]['objectId']


def test_transform_is_atomic_and_requires_new_identity_and_reference_closure():
    base, report, groups, origin = field_case()
    group = groups[0]; group['slots'] = [{'slotId':'transform','operation':'TRANSFORM_ROOTS',
        'collection':'tasks','objectId':'tasks/t1','inputObjectIds':['tasks/t1'],
        'oldValueSha256':digest(encode([{'localKey':'t1','title':''}])),
        'outputNamespace':'t1:repair:', 'maxNewObjects':2, 'referenceClosure':[],
        'valueSchema':{'type':'array','items':{'type':'object','required':['localKey','title']}}}]
    plan = repair.build_repair_plan(base, report, groups, origin=origin)
    def patch(value): return encode({'repairPlanSha256':digest(plan),'baseCandidateSha256':digest(base),
        'groupId':'fix-t1','operations':[{'slotId':'transform','value':value}]})
    for value in [[{'localKey':'t1','title':'偷换身份'}], [{'localKey':'outside','title':'越权'}]]:
        with pytest.raises(InvalidActionResult):
            repair.apply_repair_patch(base,plan,patch(value),group_id='fix-t1',verify_group=lambda *_:None)
    good=[{'localKey':'t1:repair:a','title':'甲'},{'localKey':'t1:repair:b','title':'乙'}]
    merged,_ = repair.apply_repair_patch(base,plan,patch(good),group_id='fix-t1',verify_group=lambda *_:None)
    assert json.loads(merged)['tasks'] == [*good, {'localKey':'t2','title':'保留'}]
    with pytest.raises(InvalidActionResult):
        repair.apply_repair_patch(base,plan,patch(good),group_id='fix-t1',verify_group=lambda *_:(_ for _ in ()).throw(InvalidActionResult('引用仍缺失。')))
    assert json.loads(base)['tasks'][0]['localKey']=='t1'


def _chain_item(plan, patch, receipt, suffix):
    origin = json.loads(plan)['origin']
    packet = encode({'contextRefs': [{'refId': 'candidate-repair-plan-v1',
        'canonicalContent': {'repairPlanSha256': digest(plan)}}]})
    envelope = encode({'actionContractId': 'CANDIDATE_PATCH-v1',
        'packetSha256': digest(packet), 'runId': origin['runId'],
        'logicalWorkId': 'candidate-patch-' + suffix})
    record = encode({'outcome': 'SUCCEEDED', 'envelopeSha256': digest(envelope),
        'rawSha256': digest(patch), 'normalizedResultSha256': digest(receipt)})
    return {'plan': plan, 'patch': patch, 'receipt': receipt, 'record': record,
        'envelope': envelope, 'packet': packet}


def test_plan_rejects_ancestor_overlap_and_repeated_collection_mutation():
    base, report, groups, origin = field_case()
    base = encode({'tasks': [{'localKey': 't1', 'title': '', 'detail': {'text': ''}}]})
    report['candidateSha256'] = digest(base)
    groups[0]['slots'] = [
        {'slotId': 'detail', 'operation': 'SET_FIELD', 'collection': 'tasks',
         'objectId': 'tasks/t1', 'field': 'detail',
         'oldValueSha256': digest(encode({'text': ''})), 'valueSchema': {'type': 'object'}},
        {'slotId': 'detail-text', 'operation': 'SET_FIELD', 'collection': 'tasks/0/detail',
         'objectId': 'tasks/0/detail', 'field': 'text',
         'oldValueSha256': digest(encode('')), 'valueSchema': {'type': 'string'}},
    ]
    with pytest.raises(InvalidActionResult):
        repair.build_repair_plan(base, report, groups, origin=origin)
    groups[0]['readSet'] = []
    groups[0]['slots'] = [
        {'slotId': 'append-a', 'operation': 'APPEND_OBJECT', 'collection': 'tasks',
         'objectId': 'new-a', 'oldValueSha256': digest(encode(json.loads(base)['tasks'])),
         'valueSchema': {'type': 'object'}, 'maxNewObjects': 1},
        {'slotId': 'append-b', 'operation': 'APPEND_OBJECT', 'collection': 'tasks',
         'objectId': 'new-b', 'oldValueSha256': digest(encode(json.loads(base)['tasks'])),
         'valueSchema': {'type': 'object'}, 'maxNewObjects': 1},
    ]
    with pytest.raises(InvalidActionResult):
        repair.build_repair_plan(base, report, groups, origin=origin)


def test_patch_requires_all_regular_slots_and_one_alternative():
    base, report, groups, origin = field_case()
    groups[0]['slots'] = [
        groups[0]['slots'][0],
        {'slotId': 'alt-one', 'operation': 'SET_FIELD', 'collection': 'tasks',
         'objectId': 'tasks/t1', 'field': 'summary',
         'oldValueSha256': digest(encode({'$repairMissing': True})),
         'valueSchema': {'type': 'string'}, 'alternativeSet': 'choice'},
        {'slotId': 'alt-two', 'operation': 'SET_FIELD', 'collection': 'tasks',
         'objectId': 'tasks/t2', 'field': 'summary',
         'oldValueSha256': digest(encode({'$repairMissing': True})),
         'valueSchema': {'type': 'string'}, 'alternativeSet': 'choice'},
    ]
    plan = repair.build_repair_plan(base, report, groups, origin=origin)
    common = {'repairPlanSha256': digest(plan), 'baseCandidateSha256': digest(base), 'groupId': 'fix-t1'}
    missing = encode({**common, 'operations': [{'slotId': 't1-title', 'value': '完成'}]})
    multiple = encode({**common, 'operations': [
        {'slotId': 't1-title', 'value': '完成'}, {'slotId': 'alt-one', 'value': '甲'},
        {'slotId': 'alt-two', 'value': '乙'}]})
    for patch in (missing, multiple):
        with pytest.raises(InvalidActionResult):
            repair.apply_repair_patch(base, plan, patch, group_id='fix-t1', verify_group=lambda *_: None)


def test_append_remove_authorization_and_identity_reuse_are_rejected():
    base, report, groups, origin = field_case()
    original = json.loads(base)['tasks']
    groups[0]['readSet'] = []
    groups[0]['slots'] = [{'slotId': 'append', 'operation': 'APPEND_OBJECT',
        'collection': 'tasks', 'objectId': 'tasks/t1',
        'oldValueSha256': digest(encode(original)), 'valueSchema': {'type': 'object'},
        'maxNewObjects': 1}]
    with pytest.raises(InvalidActionResult):
        repair.build_repair_plan(base, report, groups, origin=origin)
    groups[0]['slots'][0]['objectId'] = 'new-task'
    plan = repair.build_repair_plan(base, report, groups, origin=origin)
    patch = encode({'repairPlanSha256': digest(plan), 'baseCandidateSha256': digest(base),
        'groupId': 'fix-t1', 'operations': [{'slotId': 'append',
            'value': {'localKey': 't2', 'title': '复用身份'}}]})
    with pytest.raises(InvalidActionResult):
        repair.apply_repair_patch(base, plan, patch, group_id='fix-t1', verify_group=lambda *_: None)
    groups[0]['slots'] = [{'slotId': 'remove-root', 'operation': 'REMOVE_OBJECT',
        'collection': '$', 'objectId': '$', 'oldValueSha256': digest(base)}]
    with pytest.raises(InvalidActionResult):
        repair.build_repair_plan(base, report, groups, origin=origin)


def test_stale_base_and_incomplete_transform_closure_are_rejected():
    base, report, groups, origin = field_case()
    plan = repair.build_repair_plan(base, report, groups, origin=origin)
    drifted = encode({'tasks': [{'localKey': 't1', 'title': '外部改写'},
                                {'localKey': 't2', 'title': '保留'}]})
    with pytest.raises(InvalidActionResult):
        repair.apply_repair_patch(drifted, plan, proposal(plan), group_id='fix-t1', verify_group=lambda *_: None)
    reference = copy.deepcopy(groups[0]['slots'][0])
    reference['slotId'] = 'reference'
    reference['objectId'] = 'tasks/t2'
    reference['oldValueSha256'] = digest(encode('保留'))
    groups[0]['slots'] = [{'slotId': 'transform', 'operation': 'TRANSFORM_ROOTS',
        'collection': 'tasks', 'objectId': 'tasks/t1', 'inputObjectIds': ['tasks/t1'],
        'oldValueSha256': digest(encode([{'localKey': 't1', 'title': ''}])),
        'outputNamespace': 't1:repair:', 'maxNewObjects': 1, 'referenceClosure': [],
        'valueSchema': {'type': 'array'}}, reference]
    with pytest.raises(InvalidActionResult):
        repair.build_repair_plan(base, report, groups, origin=origin)


def test_inherited_indexes_require_exact_previous_receipt_binding():
    base, report, groups, origin = field_case()
    first_plan = repair.build_repair_plan(base, report, groups, origin=origin)
    first_patch = proposal(first_plan)
    merged, first_receipt = repair.apply_repair_patch(
        base, first_plan, first_patch, group_id='fix-t1', verify_group=verify_title)
    second_report = copy.deepcopy(report)
    second_report['candidateSha256'] = digest(merged)
    second_report['objectIndex'] = json.loads(first_receipt)['objectIndex']
    second_origin = {**origin, 'repairRound': 3,
        'previousReceiptSha256': digest(first_receipt)}
    second_group = copy.deepcopy(groups)
    second_group[0]['slots'][0].update(
        {'objectId': 'tasks/t2', 'oldValueSha256': digest(encode('保留'))})
    second_plan = repair.build_repair_plan(merged, second_report, second_group, origin=second_origin)
    second_patch = encode({'repairPlanSha256': digest(second_plan),
        'baseCandidateSha256': digest(merged), 'groupId': 'fix-t1',
        'operations': [{'slotId': 't1-title', 'value': '第二次修复'}]})
    second_merged, second_receipt = repair.apply_repair_patch(
        merged, second_plan, second_patch, group_id='fix-t1', verify_group=lambda *_: None)
    assert json.loads(second_merged)['tasks'][1]['title'] == '第二次修复'
    first_item = _chain_item(first_plan, first_patch, first_receipt, 'one')
    second_item = _chain_item(second_plan, second_patch, second_receipt, 'two')
    repair.resolve_candidate(base, [first_item, second_item],
        verify_group=lambda *_: None, verify_candidate=lambda *_: None)
    forged_report = copy.deepcopy(second_report)
    forged_report['objectIndex'][2]['objectId'] = 'forged-object'
    forged_group = copy.deepcopy(second_group)
    forged_group[0]['slots'][0]['objectId'] = 'forged-object'
    forged_plan = repair.build_repair_plan(
        merged, forged_report, forged_group, origin=second_origin)
    forged_patch = encode({'repairPlanSha256': digest(forged_plan),
        'baseCandidateSha256': digest(merged), 'groupId': 'fix-t1',
        'operations': [{'slotId': 't1-title', 'value': '伪造'}]})
    forged_merged, forged_receipt = repair.apply_repair_patch(
        merged, forged_plan, forged_patch, group_id='fix-t1', verify_group=lambda *_: None)
    assert forged_merged
    with pytest.raises(InvalidActionResult):
        repair.resolve_candidate(base, [first_item,
            _chain_item(forged_plan, forged_patch, forged_receipt, 'forged')],
            verify_group=lambda *_: None, verify_candidate=lambda *_: None)
    wrong_origin = {**second_origin, 'previousReceiptSha256': '9' * 64}
    wrong_plan = repair.build_repair_plan(
        merged, second_report, second_group, origin=wrong_origin)
    wrong_patch = encode({'repairPlanSha256': digest(wrong_plan),
        'baseCandidateSha256': digest(merged), 'groupId': 'fix-t1',
        'operations': [{'slotId': 't1-title', 'value': '错误绑定'}]})
    wrong_merged, wrong_receipt = repair.apply_repair_patch(
        merged, wrong_plan, wrong_patch, group_id='fix-t1', verify_group=lambda *_: None)
    assert wrong_merged
    with pytest.raises(InvalidActionResult):
        repair.resolve_candidate(base, [first_item,
            _chain_item(wrong_plan, wrong_patch, wrong_receipt, 'wrong')],
            verify_group=lambda *_: None, verify_candidate=lambda *_: None)


def test_two_successful_writes_from_one_stale_base_are_rejected():
    base, report, groups, origin = field_case()
    plan = repair.build_repair_plan(base, report, groups, origin=origin)
    first_patch = proposal(plan, '第一次')
    second_patch = proposal(plan, '第二次')
    _, first_receipt = repair.apply_repair_patch(
        base, plan, first_patch, group_id='fix-t1', verify_group=verify_title)
    _, second_receipt = repair.apply_repair_patch(
        base, plan, second_patch, group_id='fix-t1', verify_group=verify_title)
    with pytest.raises(InvalidActionResult):
        repair.resolve_candidate(base, [
            _chain_item(plan, first_patch, first_receipt, 'one'),
            _chain_item(plan, second_patch, second_receipt, 'two')],
            verify_group=lambda *_: None, verify_candidate=lambda *_: None)


def test_additional_properties_become_narrow_field_removals():
    candidate = encode({
        'bundleSha256': '1' * 64,
        'round': 1,
        'kind': 'PROTOTYPE_SCENARIO-v1',
        'scenarios': [{
            'scenarioId': 'scenario-one',
            'critical': False,
            'interactionIds': ['interaction-one'],
            'title': '多余标题',
            'steps': [{
                'stepId': 'step-one',
                'page': 'demo/index.html',
                'interactionId': 'interaction-one',
                'operation': 'click',
                'action': 'click',
                'selector': '#action',
                'value': None,
                'assertions': [{
                    'selector': '#result',
                    'attribute': 'textContent',
                    'expected': '完成',
                }],
                'screenshot': True,
            }],
        }],
    })
    origin = {
        'runId': 'run-test',
        'inputRevisionSha256': '1' * 64,
        'originLogicalWorkId': 'prototype-work-1',
        'sourceKind': 'AUTHOR_FAILURE',
        'sourceActionContractId': 'PROTOTYPE_SCENARIO-v1',
        'sourceAttemptRecordSha256': '2' * 64,
        'stageKind': 'SCOPE',
        'repairRound': 2,
        'budgetPolicySha256': '3' * 64,
    }
    issues = repair.schema_issues(
        'PROTOTYPE_SCENARIO-v1', json.loads(candidate), 'PROTOTYPE')
    report = repair.diagnostic_report(
        candidate, issues, owner='PROTOTYPE', checker_file=__file__,
        packet={}, origin=origin)
    from prototype_analysis import plan_candidate_repair
    plan = plan_candidate_repair(
        'PROTOTYPE_SCENARIO', {}, candidate, report, origin=origin,
        action_contract_id='PROTOTYPE_SCENARIO-v1')
    groups = json.loads(plan)['groups']

    assert len(groups) == 1
    assert {
        (slot['operation'], slot['field'])
        for slot in groups[0]['slots']
    } == {
        ('REMOVE_FIELD', 'kind'),
        ('REMOVE_FIELD', 'title'),
        ('REMOVE_FIELD', 'action'),
    }

    plan = encode(json.loads(plan))
    patch = encode({
        'repairPlanSha256': digest(plan),
        'baseCandidateSha256': digest(candidate),
        'groupId': groups[0]['groupId'],
        'operations': [
            {'slotId': slot['slotId']} for slot in groups[0]['slots']
        ],
    })

    def verify(raw, _group):
        assert repair.schema_issues(
            'PROTOTYPE_SCENARIO-v1', json.loads(raw), 'PROTOTYPE') == []

    merged, _ = repair.apply_repair_patch(
        candidate, plan, patch, group_id=groups[0]['groupId'],
        verify_group=verify)
    assert json.loads(merged)['scenarios'][0]['steps'][0].get('action') is None


def test_missing_identity_gets_narrow_slot_but_existing_identity_stays_frozen():
    candidate = encode({
        'bundleSha256': '1' * 64,
        'round': 1,
        'scenarios': [{
            'critical': False,
            'interactionIds': ['interaction-one'],
            'steps': [{
                'stepId': 'step-one',
                'page': 'demo/index.html',
                'interactionId': 'interaction-one',
                'operation': 'click',
                'selector': '#action',
                'value': None,
                'assertions': [{
                    'selector': '#result',
                    'attribute': 'textContent',
                    'expected': '完成',
                }],
                'screenshot': True,
            }],
        }],
    })
    path = '/scenarios/0/scenarioId'
    slots = repair.located_slots(
        candidate, 'PROTOTYPE_SCENARIO-v1', [path])
    assert len(slots) == 1
    assert slots[0]['operation'] == 'SET_FIELD'
    assert slots[0]['field'] == 'scenarioId'

    existing = copy.deepcopy(json.loads(candidate))
    existing['scenarios'][0]['scenarioId'] = 'scenario-existing'
    assert repair.located_slots(
        encode(existing), 'PROTOTYPE_SCENARIO-v1', [path]) == []

    origin = {
        'runId': 'run-test',
        'inputRevisionSha256': '1' * 64,
        'originLogicalWorkId': 'prototype-work-1',
        'sourceKind': 'AUTHOR_FAILURE',
        'sourceActionContractId': 'PROTOTYPE_SCENARIO-v1',
        'sourceAttemptRecordSha256': '2' * 64,
        'stageKind': 'SCOPE',
        'repairRound': 2,
        'budgetPolicySha256': '3' * 64,
    }
    issues = repair.schema_issues(
        'PROTOTYPE_SCENARIO-v1', json.loads(candidate), 'PROTOTYPE')
    report = repair.diagnostic_report(
        candidate, issues, owner='PROTOTYPE', checker_file=__file__,
        packet={}, origin=origin)
    group = {
        'groupId': 'group-missing-identity',
        'issueIds': [issues[0]['issueId']],
        'readSet': [{'objectId': slots[0]['objectId'], 'fields': ['scenarioId']}],
        'slots': slots,
        'verificationObligations': [issues[0]['issueId']],
    }
    plan = repair.build_repair_plan(
        candidate, report, [group], origin=origin)
    patch = encode({
        'repairPlanSha256': digest(plan),
        'baseCandidateSha256': digest(candidate),
        'groupId': group['groupId'],
        'operations': [{
            'slotId': slots[0]['slotId'],
            'value': 'scenario-repaired',
        }],
    })
    merged, _ = repair.apply_repair_patch(
        candidate, plan, patch, group_id=group['groupId'],
        verify_group=lambda *_: None)
    assert json.loads(merged)['scenarios'][0]['scenarioId'] == 'scenario-repaired'
