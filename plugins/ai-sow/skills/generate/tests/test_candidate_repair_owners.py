from __future__ import annotations
import copy
import json
import sys
from pathlib import Path
import pytest

TEST_LAYER = 'unit'
ROOT = Path(__file__).parents[1]
for path in (ROOT/'scripts', ROOT/'tests', ROOT.parents[1]):
    if str(path) not in sys.path: sys.path.insert(0, str(path))
from contracts import canonical_json_bytes, InvalidActionResult
from action_ledger import diagnostic_value


def repaired_packet(packet, bad, diagnostic):
    value = copy.deepcopy(packet)
    value['contextRefs'].append({'refId':'repair-from-attempt-synthetic', 'canonicalContent':{
        'kind':'ATTEMPT_REPAIR', 'rawOutputUtf8':canonical_json_bytes(bad).decode(),
        'diagnostic':diagnostic_value(diagnostic)}})
    return value


def test_scope_repair_preserves_unrelated_epic():
    from test_scope_compiler import synthesis_packet
    from ir_samples import complete_scope_ir
    from scope_compiler import validate_bound_scope_result
    packet, good = synthesis_packet(), complete_scope_ir()
    bad = copy.deepcopy(good)
    bad['decisions'][0]['boundaryEvidence']['evidenceIds'] = ['unknown']
    with pytest.raises(InvalidActionResult) as error:
        validate_bound_scope_result('SCOPE_SYNTHESIS', packet, canonical_json_bytes(bad))
    packet = repaired_packet(packet, bad, error.value.diagnostic)
    validate_bound_scope_result('SCOPE_SYNTHESIS', packet, canonical_json_bytes(good))
    changed = copy.deepcopy(good)
    changed['decisions'][1]['boundaryEvidence']['name'] = '无关改写'
    with pytest.raises(InvalidActionResult) as protected:
        validate_bound_scope_result('SCOPE_SYNTHESIS', packet, canonical_json_bytes(changed))
    assert protected.value.diagnostic.code == 'REPAIR_SCOPE_VIOLATION'


def test_scan_repair_preserves_other_source_block():
    from test_scope_compiler import scan_ir_packet
    from ir_samples import scan_ir
    from scope_compiler import validate_bound_scope_result
    packet = scan_ir_packet()
    other = copy.deepcopy(packet['workItems'][0]);other['workItemId']='work-b'
    other['payload'].update(coverageRootId='block-b', evidenceIds=['block-b'])
    packet['workItems'].append(other)
    good = scan_ir() + scan_ir('block-b','fact-b')
    bad = copy.deepcopy(good);bad[0]['facts'][0]['evidenceIds']=['block-b']
    with pytest.raises(InvalidActionResult) as error:
        validate_bound_scope_result('SOURCE_SCAN', packet, canonical_json_bytes(bad))
    assert error.value.diagnostic.subject_ids == ('block-a',)
    packet = repaired_packet(packet, bad, error.value.diagnostic)
    validate_bound_scope_result('SOURCE_SCAN', packet, canonical_json_bytes(good))
    changed=copy.deepcopy(good);changed[1]['facts'][0]['statement']='无关改写'
    with pytest.raises(InvalidActionResult) as protected:
        validate_bound_scope_result('SOURCE_SCAN', packet, canonical_json_bytes(changed))
    assert protected.value.diagnostic.code == 'REPAIR_SCOPE_VIOLATION'


def test_audit_repair_preserves_other_category():
    from test_scope_compiler import audit_ir_packet
    from ir_samples import audit_ir
    from scope_compiler import validate_bound_scope_result
    packet, good = audit_ir_packet(), audit_ir()
    bad=copy.deepcopy(good);bad['checks'][0]['relatedFactKeys']=['unknown']
    with pytest.raises(InvalidActionResult) as error:
        validate_bound_scope_result('SOURCE_AUDIT', packet, canonical_json_bytes(bad))
    assert error.value.diagnostic.subject_ids
    packet=repaired_packet(packet,bad,error.value.diagnostic)
    validate_bound_scope_result('SOURCE_AUDIT',packet,canonical_json_bytes(good))
    changed=copy.deepcopy(good);changed['checks'][-1]['relatedFactKeys']=[]
    with pytest.raises(InvalidActionResult) as protected:
        validate_bound_scope_result('SOURCE_AUDIT',packet,canonical_json_bytes(changed))
    assert protected.value.diagnostic.code == 'REPAIR_SCOPE_VIOLATION'


def test_prior_repair_preserves_other_entity(tmp_path):
    from test_prior_state import prior_pair, analyze_packet
    from prior_state import validate_bound_prior_result
    inventories, revision, good=prior_pair(tmp_path)
    _, packet=analyze_packet(inventories,revision)
    def check(packet,result):
        validate_bound_prior_result('PRIOR_ANALYZE',packet,canonical_json_bytes(result),
            inventories=inventories,input_revision_bytes=revision)
    bad=copy.deepcopy(good);bad['entities'][0]['evidenceIds']=['unknown']
    with pytest.raises(InvalidActionResult) as error: check(packet,bad)
    assert error.value.diagnostic.subject_ids == (bad['entities'][0]['localKey'],)
    packet=repaired_packet(packet,bad,error.value.diagnostic)
    check(packet,good)
    changed=copy.deepcopy(good);changed['entities'][1]['semanticSummary']='无关改写'
    with pytest.raises(InvalidActionResult) as protected: check(packet,changed)
    assert protected.value.diagnostic.code == 'REPAIR_SCOPE_VIOLATION'


def observation_packet():
    from test_scope_compiler import synthesis_packet
    packet = synthesis_packet()
    packet['contextRefs'].append({'refId': 'prototype-observations', 'canonicalContent': {
        'kind': 'PROTOTYPE_OBSERVATION_REF', 'observationKeys': ['observation-a'],
        'evidenceIds': ['prototype-evidence']}})
    return packet


def test_missing_scope_observation_only_allows_binding_supplements():
    from ir_samples import complete_scope_ir
    from scope_compiler import validate_bound_scope_result
    packet, bad = observation_packet(), complete_scope_ir()
    with pytest.raises(InvalidActionResult) as error:
        validate_bound_scope_result('SCOPE_SYNTHESIS', packet, canonical_json_bytes(bad))
    packet = repaired_packet(packet, bad, error.value.diagnostic)
    good = copy.deepcopy(bad)
    good['decisions'][0]['boundaryEvidence']['observationKeys'] = ['observation-a']
    good['decisions'][0]['boundaryEvidence']['evidenceIds'].append('prototype-evidence')
    validate_bound_scope_result('SCOPE_SYNTHESIS', packet, canonical_json_bytes(good))
    changed = copy.deepcopy(good)
    changed['decisions'][1]['boundaryEvidence']['name'] = '无关改名'
    with pytest.raises(InvalidActionResult) as protected:
        validate_bound_scope_result('SCOPE_SYNTHESIS', packet, canonical_json_bytes(changed))
    assert protected.value.diagnostic.code == 'REPAIR_SCOPE_VIOLATION'


def test_duplicate_scope_observation_identifies_holders_and_freezes_their_other_fields():
    from ir_samples import complete_scope_ir
    from scope_compiler import validate_bound_scope_result
    packet, bad = observation_packet(), complete_scope_ir()
    for row in bad['decisions']:
        row['boundaryEvidence']['observationKeys'] = ['observation-a']
    with pytest.raises(InvalidActionResult) as error:
        validate_bound_scope_result('SCOPE_SYNTHESIS', packet, canonical_json_bytes(bad))
    assert set(error.value.diagnostic.subject_ids) == {'feature-a', 'epic-a'}
    packet = repaired_packet(packet, bad, error.value.diagnostic)
    good = copy.deepcopy(bad)
    good['decisions'][1]['boundaryEvidence']['observationKeys'] = []
    validate_bound_scope_result('SCOPE_SYNTHESIS', packet, canonical_json_bytes(good))
    changed = copy.deepcopy(good)
    changed['decisions'][0]['boundaryEvidence']['name'] = '重复持有者也不能改名'
    with pytest.raises(InvalidActionResult) as protected:
        validate_bound_scope_result('SCOPE_SYNTHESIS', packet, canonical_json_bytes(changed))
    assert protected.value.diagnostic.code == 'REPAIR_SCOPE_VIOLATION'


def prior_coverage_case(tmp_path):
    from test_prior_v2 import prior_case
    from contracts import normalize_result_sets
    from prior_state import validate_bound_prior_result
    inventory, revision, packet, good = prior_case(tmp_path)
    source = good['unextractedEvidence'][0]
    good['unextractedEvidence'] = [{**source, 'evidenceIds': [key]}
                                 for key in source['evidenceIds']]
    good = normalize_result_sets('PRIOR_ANALYZE-v2', good)
    bad = copy.deepcopy(good)
    missing = bad['unextractedEvidence'].pop()
    def check(bound_packet, result):
        normalized = normalize_result_sets('PRIOR_ANALYZE-v2', copy.deepcopy(result))
        validate_bound_prior_result('PRIOR_ANALYZE', bound_packet, canonical_json_bytes(normalized),
            inventories=[inventory], input_revision_bytes=revision)
    with pytest.raises(InvalidActionResult) as error:
        check(packet, bad)
    assert error.value.diagnostic.code == 'PRIOR_EVIDENCE_COVERAGE_INVALID'
    return repaired_packet(packet, bad, error.value.diagnostic), bad, good, missing, check


def test_prior_missing_evidence_can_add_entity_but_cannot_reuse_correct_evidence(tmp_path):
    packet, bad, _, missing, check = prior_coverage_case(tmp_path)
    good = copy.deepcopy(bad)
    added = {**good['entities'][0], 'localKey': 'item-0:missing',
             'semanticSummary': '补齐遗漏合同对象', 'evidenceIds': missing['evidenceIds']}
    good['entities'].append(added)
    check(packet, good)
    changed = copy.deepcopy(good)
    changed['entities'][-1]['evidenceIds'] += changed['entities'][0]['evidenceIds']
    with pytest.raises(InvalidActionResult) as protected:
        check(packet, changed)
    assert protected.value.diagnostic.code == 'REPAIR_SCOPE_VIOLATION'


def test_prior_coverage_repair_preserves_unrelated_explanation_rows(tmp_path):
    packet, bad, good, missing, check = prior_coverage_case(tmp_path)
    check(packet, good)
    appended = copy.deepcopy(bad)
    appended['unextractedEvidence'][0]['evidenceIds'] += missing['evidenceIds']
    check(packet, appended)
    changed = copy.deepcopy(good)
    changed['unextractedEvidence'][0]['reason'] = '无关理由改写'
    with pytest.raises(InvalidActionResult) as protected:
        check(packet, changed)
    assert protected.value.diagnostic.code == 'REPAIR_SCOPE_VIOLATION'


@pytest.mark.parametrize('collection', [
    'sourceRelations', 'unextractedEvidence', 'unsupportedRegions', 'entitySupersessions'])
def test_prior_located_collection_row_does_not_unfreeze_unrelated_rows(collection):
    from contracts import normalize_result_sets
    from models import AttemptDiagnostic
    from prior_state import _preserve_prior_candidate
    good = {'entities': [], 'sourceRelations': [], 'unextractedEvidence': [],
            'unsupportedRegions': [], 'entitySupersessions': []}
    rows = {
        'sourceRelations': [{'sourceAId': 'source-a', 'sourceBId': 'source-b',
            'relation': 'COMPLEMENTARY', 'evidenceIds': ['evidence-a']},
            {'sourceAId': 'source-c', 'sourceBId': 'source-d',
             'relation': 'COMPLEMENTARY', 'evidenceIds': ['evidence-b']}],
        'unextractedEvidence': [{'sourceId': 'source-a', 'evidenceIds': ['evidence-a'], 'reason': '表头'},
            {'sourceId': 'source-b', 'evidenceIds': ['evidence-b'], 'reason': '上下文'}],
        'unsupportedRegions': [{'sourceId': 'source-a', 'regionId': 'region-a', 'reason': '无法解释'},
            {'sourceId': 'source-b', 'regionId': 'region-b', 'reason': '无法解释'}],
        'entitySupersessions': [{'predecessorLocalKeys': ['entity-a'], 'successorLocalKeys': ['entity-b'],
            'evidenceIds': ['evidence-a']}, {'predecessorLocalKeys': ['entity-c'],
            'successorLocalKeys': ['entity-d'], 'evidenceIds': ['evidence-b']}],
    }[collection]
    good[collection] = rows
    bad = copy.deepcopy(good)
    field = 'sourceId' if collection == 'unsupportedRegions' else 'evidenceIds'
    bad[collection][0][field] = 'unknown' if field == 'sourceId' else ['unknown']
    bad = normalize_result_sets('PRIOR_ANALYZE-v2', bad)
    index = next(i for i, row in enumerate(bad[collection]) if row[field] in ('unknown', ['unknown']))
    diagnostic = AttemptDiagnostic('PRIOR_BINDING_INVALID', f'/{collection}/{index}', ())
    packet = repaired_packet({'workItems': [], 'contextRefs': []}, bad, diagnostic)
    normalized = normalize_result_sets('PRIOR_ANALYZE-v2', copy.deepcopy(good))
    _preserve_prior_candidate('PRIOR_ANALYZE', packet, normalized)
    changed = copy.deepcopy(good)
    if collection in {'unextractedEvidence', 'unsupportedRegions'}:
        changed[collection][1]['reason'] = '无关改写'
    elif collection == 'sourceRelations':
        changed[collection][1]['relation'] = 'DUPLICATE'
    else:
        changed[collection][1]['evidenceIds'] = ['evidence-other']
    with pytest.raises(InvalidActionResult) as protected:
        _preserve_prior_candidate('PRIOR_ANALYZE', packet,
            normalize_result_sets('PRIOR_ANALYZE-v2', changed))
    assert protected.value.diagnostic.code == 'REPAIR_SCOPE_VIOLATION'


def protocol_origin(packet, contract_id, stage):
    from contracts import sha256_bytes
    return {'runId':'run-local','inputRevisionSha256':sha256_bytes(canonical_json_bytes(packet)),
        'sourceAttemptRecordSha256':'2'*64,'originLogicalWorkId':'work-local',
        'sourceKind':'AUTHOR_FAILURE','sourceActionContractId':contract_id,
        'stageKind':stage,'repairRound':2,'budgetPolicySha256':'3'*64}


def test_prior_report_exposes_complete_missing_set(tmp_path):
    from test_prior_v2 import prior_case
    from prior_state import diagnose_candidate, plan_candidate_repair
    from contracts import sha256_bytes
    inventory,revision,packet,good=prior_case(tmp_path)
    bad=copy.deepcopy(good);removed=bad['unextractedEvidence'].pop()
    origin=protocol_origin(packet,'PRIOR_ANALYZE-v3','SCOPE');origin['inputRevisionSha256']=sha256_bytes(revision)
    context={'inventories':[inventory],'input_revision_bytes':revision,'origin':origin}
    report=diagnose_candidate('PRIOR_ANALYZE',packet,bad,**context)
    actual={(s['sourceId'],s['evidenceId']) for issue in report['issues'] if issue['code']=='PRIOR_EVIDENCE_MISSING' for s in issue['subjects']}
    assert actual=={(removed['sourceId'],eid) for eid in removed['evidenceIds']}
    assert report['blockedChecks']==[]
    plan=json.loads(plan_candidate_repair('PRIOR_ANALYZE',packet,bad,report,**context))
    assert all(slot['operation']=='APPEND_OBJECT' for group in plan['groups'] for slot in group['slots'])
    assert {slot['collection'] for group in plan['groups'] for slot in group['slots']}=={'entities','unextractedEvidence'}


def test_prior_report_collects_duplicate_unassigned_used_and_missing(tmp_path):
    from test_prior_v2 import prior_case
    from prior_state import diagnose_candidate
    inventory,revision,packet,good=prior_case(tmp_path)
    bad=copy.deepcopy(good);row=bad['unextractedEvidence'].pop()
    bad['unextractedEvidence']=[{**row,'evidenceIds':[row['evidenceIds'][0],row['evidenceIds'][0],'unknown',good['entities'][0]['evidenceIds'][0]]}]
    report=diagnose_candidate('PRIOR_ANALYZE',packet,bad,inventories=[inventory],input_revision_bytes=revision)
    # Even malformed duplicate arrays have a Schema diagnostic. Independent
    # evidence coverage must remain visible rather than stopping at that error.
    assert any(issue['code'].startswith('SCHEMA_') for issue in report['issues'])
    assert 'PRIOR_BINDINGS' in report['blockedChecks']
    codes={i['code'] for i in report['issues']}
    assert {'PRIOR_EVIDENCE_DUPLICATE','PRIOR_EVIDENCE_UNASSIGNED','PRIOR_EVIDENCE_ALREADY_USED'} <= codes


@pytest.mark.parametrize('stage', ['TASK','STORY_AC'])
def test_owner_field_grants_preserve_other_fields_and_upstream(stage):
    import importlib
    from candidate_repair import apply_repair_patch,verify_group_progress
    from contracts import sha256_bytes
    if stage=='TASK':
        from test_task_compiler import exact_task_inputs,task_packet,bound_task_ir
        packet=task_packet(exact_task_inputs());good=bound_task_ir(packet);collection='tasks';field='evidenceIds';kind='TASK';module=importlib.import_module('task_compiler');contract='TASK-v2'
    else:
        from test_delivery_compiler import story_packet, story_inputs, bound_story_ir
        packet=story_packet(story_inputs());good=bound_story_ir(packet);collection='stories';field='actorKey';kind='STORY_AC';module=importlib.import_module('delivery_compiler');contract='STORY_AC-v1'
    frozen=canonical_json_bytes(packet);bad=copy.deepcopy(good)
    bad[collection][0][field]=['unknown'] if field=='evidenceIds' else 'unknown'
    origin=protocol_origin(packet,contract,stage)
    report=module.diagnose_candidate(kind,packet,bad,origin=origin)
    plan_raw=module.plan_candidate_repair(kind,packet,bad,report,origin=origin)
    plan=json.loads(plan_raw);group=plan['groups'][0]
    assert {s['field'] for s in group['slots']}=={field}
    patch=canonical_json_bytes({'repairPlanSha256':sha256_bytes(plan_raw),'baseCandidateSha256':sha256_bytes(canonical_json_bytes(bad)),
        'groupId':group['groupId'],'operations':[{'slotId':s['slotId'],'value':good[collection][0][field]} for s in group['slots']]})
    merged,_=apply_repair_patch(canonical_json_bytes(bad),plan_raw,patch,group_id=group['groupId'],
        verify_group=lambda raw,g:verify_group_progress(report,module.diagnose_candidate(kind,packet,raw,origin=origin),g))
    assert json.loads(merged)==good
    assert canonical_json_bytes(packet)==frozen


@pytest.mark.parametrize('kind',['SCOPE_SYNTHESIS','SCOPE_PROPOSAL','SCOPE_JOIN'])
def test_scope_diagnosis_grants_exact_nested_evidence(kind):
    from ir_samples import complete_scope_ir
    from scope_compiler import diagnose_candidate,plan_candidate_repair
    from test_scope_compiler import synthesis_packet
    packet=synthesis_packet();bad=complete_scope_ir();bad['decisions'][0]['boundaryEvidence']['evidenceIds']=['unknown']
    origin=protocol_origin(packet,kind+'-v1','SCOPE')
    report=diagnose_candidate(kind,packet,bad,origin=origin)
    plan=json.loads(plan_candidate_repair(kind,packet,bad,report,origin=origin))
    assert {s['field'] for g in plan['groups'] for s in g['slots']}=={'evidenceIds'}
    assert {s['objectId'] for g in plan['groups'] for s in g['slots']}=={'decisions/0/boundaryEvidence'}


def test_prior_patch_can_extract_missing_entity_without_rewriting_explanations(tmp_path):
    from test_prior_v2 import prior_case
    from prior_state import diagnose_candidate,plan_candidate_repair
    from candidate_repair import apply_repair_patch,verify_group_progress
    from contracts import sha256_bytes
    inventory,revision,packet,good=prior_case(tmp_path)
    bad=copy.deepcopy(good);removed=bad['unextractedEvidence'].pop()
    origin=protocol_origin(packet,'PRIOR_ANALYZE-v3','SCOPE');origin['inputRevisionSha256']=sha256_bytes(revision)
    context={'inventories':[inventory],'input_revision_bytes':revision,'origin':origin}
    report=diagnose_candidate('PRIOR_ANALYZE',packet,bad,**context)
    plan_raw=plan_candidate_repair('PRIOR_ANALYZE',packet,bad,report,**context);plan=json.loads(plan_raw);group=plan['groups'][0]
    slot=next(s for s in group['slots'] if s['collection']=='entities')
    eid=slot['valueSchema']['properties']['evidenceIds']['items']['const']
    entity={**bad['entities'][0],'localKey':packet['workItems'][0]['workItemId']+':missing',
            'evidenceIds':[eid],'semanticSummary':'根据对应冻结行提取的新增合同项。'}
    entity.pop('visiblePriorId',None);entity.pop('cellAnchors',None)
    raw=canonical_json_bytes(bad)
    patch=canonical_json_bytes({'repairPlanSha256':sha256_bytes(plan_raw),'baseCandidateSha256':sha256_bytes(raw),
        'groupId':group['groupId'],'operations':[{'slotId':slot['slotId'],'value':entity}]})
    merged,_=apply_repair_patch(raw,plan_raw,patch,group_id=group['groupId'],
        verify_group=lambda value,g:verify_group_progress(report,diagnose_candidate('PRIOR_ANALYZE',packet,value,**context),g))
    result=json.loads(merged)
    assert result['entities'][:-1]==bad['entities']
    assert result['unextractedEvidence']==bad['unextractedEvidence']


def test_story_qualifier_repair_uses_one_exact_ac_field_slot():
    from candidate_repair import apply_repair_patch,verify_group_progress
    from contracts import sha256_bytes
    from delivery_compiler import diagnose_candidate,plan_candidate_repair,candidate_repair_context
    from test_delivery_compiler import story_packet,story_inputs,bound_story_ir
    packet=story_packet(story_inputs())
    packet['workItems'][0]['payload']['obligation']['qualifiers']=['仅管理员']
    bad=bound_story_ir(packet);origin=protocol_origin(packet,'STORY_AC-v1','STORY_AC')
    report=diagnose_candidate('STORY_AC',packet,bad,origin=origin)
    qualifier=next(issue for issue in report['issues'] if issue['code']=='STORY_QUALIFIER_MISSING')
    plan_raw=plan_candidate_repair('STORY_AC',packet,bad,report,origin=origin);plan=json.loads(plan_raw)
    group=next(group for group in plan['groups'] if qualifier['issueId'] in group['issueIds'])
    assert {slot['field'] for slot in group['slots']}=={'condition','observableResult'}
    assert 'acceptanceCriteria' not in {slot.get('field') for slot in group['slots']}
    assert len({slot['alternativeSet'] for slot in group['slots']})==1
    context=candidate_repair_context('STORY_AC',packet,canonical_json_bytes(bad),plan,group)
    assert [item for item in context if item.get('kind')=='OWNER_OBLIGATION']
    chosen=next(slot for slot in group['slots'] if slot['field']=='condition')
    row=bad['stories'][0]['acceptanceCriteria'][0]
    patch=canonical_json_bytes({'repairPlanSha256':sha256_bytes(plan_raw),
        'baseCandidateSha256':sha256_bytes(canonical_json_bytes(bad)),'groupId':group['groupId'],
        'operations':[{'slotId':chosen['slotId'],'value':row['condition']+'，仅管理员'}]})
    unchanged=copy.deepcopy(bad['stories'][0]['acceptanceCriteria'][1])
    merged,_=apply_repair_patch(canonical_json_bytes(bad),plan_raw,patch,group_id=group['groupId'],
        verify_group=lambda raw,current:verify_group_progress(
            report,diagnose_candidate('STORY_AC',packet,raw,origin=origin),current))
    assert json.loads(merged)['stories'][0]['acceptanceCriteria'][1]==unchanged


def test_scan_append_context_contains_only_missing_root():
    from candidate_repair import apply_repair_patch,verify_group_progress
    from contracts import sha256_bytes
    from ir_samples import scan_ir
    from scope_compiler import diagnose_candidate,plan_candidate_repair,candidate_repair_context
    from test_scope_compiler import scan_ir_packet
    packet=scan_ir_packet();other=copy.deepcopy(packet['workItems'][0]);other['workItemId']='work-b'
    other['payload'].update(coverageRootId='block-b',evidenceIds=['block-b']);packet['workItems'].append(other)
    good=scan_ir()+scan_ir('block-b','fact-b');bad=good[:1]
    origin=protocol_origin(packet,'SOURCE_SCAN-v1','SCOPE')
    report=diagnose_candidate('SOURCE_SCAN',packet,bad,origin=origin)
    plan_raw=plan_candidate_repair('SOURCE_SCAN',packet,bad,report,origin=origin);plan=json.loads(plan_raw)
    group=next(group for group in plan['groups'] if group['slots'][0]['operation']=='APPEND_OBJECT')
    context=candidate_repair_context('SOURCE_SCAN',packet,canonical_json_bytes(bad),plan,group)
    assert {item['coverageRootId'] for item in context}=={'block-b'}
    patch=canonical_json_bytes({'repairPlanSha256':sha256_bytes(plan_raw),
        'baseCandidateSha256':sha256_bytes(canonical_json_bytes(bad)),'groupId':group['groupId'],
        'operations':[{'slotId':group['slots'][0]['slotId'],'value':good[1]}]})
    merged,_=apply_repair_patch(canonical_json_bytes(bad),plan_raw,patch,group_id=group['groupId'],
        verify_group=lambda raw,current:verify_group_progress(
            report,diagnose_candidate('SOURCE_SCAN',packet,raw,origin=origin),current))
    assert json.loads(merged)==good


def test_task_repair_context_restricts_catalog_to_selected_and_neighbors():
    from task_compiler import diagnose_candidate,plan_candidate_repair,candidate_repair_context
    from test_task_compiler import exact_task_inputs,task_packet,bound_task_ir
    packet=task_packet(exact_task_inputs());bad=bound_task_ir(packet);bad['tasks'][0]['evidenceIds']=['unknown']
    origin=protocol_origin(packet,'TASK-v2','TASK')
    report=diagnose_candidate('TASK',packet,bad,origin=origin)
    plan=json.loads(plan_candidate_repair('TASK',packet,bad,report,origin=origin));group=plan['groups'][0]
    context=candidate_repair_context('TASK',packet,canonical_json_bytes(bad),plan,group)
    original=next(ref['canonicalContent'] for ref in packet['contextRefs'] if ref['canonicalContent'].get('kind')=='TASK_CATALOG')
    narrowed=next(item for item in context if item.get('kind')=='TASK_CATALOG')
    selected=bad['tasks'][0]['workTypeId'];rows={row['workTypeId']:row for row in original['rows']}
    assert {row['workTypeId'] for row in narrowed['rows']}=={selected,*rows[selected]['neighbors']}
    assert len(narrowed['rows'])<len(original['rows'])


def test_prototype_repair_context_filters_unaffected_trace_runs():
    from prototype_analysis import diagnose_candidate,plan_candidate_repair,candidate_repair_context
    from test_prototype_analysis import prototype_candidate_case,observation_fixture
    inventory,_,payload=prototype_candidate_case()
    bad={'observations':[observation_fixture(inventory),observation_fixture(inventory,'untouched')]}
    bad['observations'][0]['evidenceIds']=['unknown-source']
    packet={'workItems':[{'workItemId':'prototype','payload':payload}],'contextRefs':[]}
    origin=protocol_origin(packet,'PROTOTYPE_ANALYZE-v1','SCOPE')
    report=diagnose_candidate('PROTOTYPE_ANALYZE',packet,bad,origin=origin)
    plan=json.loads(plan_candidate_repair('PROTOTYPE_ANALYZE',packet,bad,report,origin=origin));group=plan['groups'][0]
    context=candidate_repair_context('PROTOTYPE_ANALYZE',packet,canonical_json_bytes(bad),plan,group)
    trace=next(item['trace'] for item in context if item['kind']=='READ_ONLY_RUNTIME_FACTS')
    assert {run['scenarioId'] for run in trace['runs']}=={payload['scenario']['normalizedResult']['scenarios'][0]['scenarioId']}
    assert all(step['interactionId'] in set(bad['observations'][0]['interactionIds']) for run in trace['runs'] for step in run['steps'])


@pytest.mark.parametrize('family',['SCOPE','STORY_AC','TASK','PROTOTYPE'])
def test_schema_invalid_candidates_keep_independently_checkable_findings(family):
    if family=='SCOPE':
        from ir_samples import complete_scope_ir
        from scope_compiler import diagnose_candidate
        from test_scope_compiler import synthesis_packet
        packet=synthesis_packet();bad=complete_scope_ir();bad['unexpected']=True
        bad['decisions'][0]['boundaryEvidence']['evidenceIds']=['unknown']
        report=diagnose_candidate('SCOPE_SYNTHESIS',packet,bad)
        expected='SCOPE_BOUNDARY_REFERENCE_UNBOUND'
    elif family=='STORY_AC':
        from delivery_compiler import diagnose_candidate
        from test_delivery_compiler import story_packet,story_inputs,bound_story_ir
        packet=story_packet(story_inputs());bad=bound_story_ir(packet);bad['unexpected']=True
        bad['stories'][0]['actorKey']='unknown'
        report=diagnose_candidate('STORY_AC',packet,bad)
        expected='STORY_ACTOR_NOT_AUTHORIZED'
    elif family=='TASK':
        from task_compiler import diagnose_candidate
        from test_task_compiler import exact_task_inputs,task_packet,bound_task_ir
        packet=task_packet(exact_task_inputs());bad=bound_task_ir(packet);bad['unexpected']=True
        bad['tasks'][0]['evidenceIds']=['unknown']
        report=diagnose_candidate('TASK',packet,bad)
        expected='TASK_EVIDENCE_UNBOUND'
    else:
        from prototype_analysis import diagnose_candidate
        from test_prototype_analysis import prototype_candidate_case,observation_fixture
        inventory,_,payload=prototype_candidate_case()
        packet={'workItems':[{'workItemId':'prototype','payload':payload}],'contextRefs':[]}
        bad={'observations':[observation_fixture(inventory)],'unexpected':True}
        bad['observations'][0]['evidenceIds']=['unknown']
        report=diagnose_candidate('PROTOTYPE_ANALYZE',packet,bad)
        expected='PROTOTYPE_SOURCE_EVIDENCE_REQUIRED'
    codes={issue['code'] for issue in report['issues']}
    assert any(code.startswith('SCHEMA_') for code in codes)
    assert expected in codes
    assert report['blockedChecks']==[]
