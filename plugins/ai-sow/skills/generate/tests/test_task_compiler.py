from __future__ import annotations

TEST_LAYER = "integration"

import copy
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
TESTS = SKILL_ROOT / "tests"
FIXTURES = SKILL_ROOT / "fixtures"
TEMPLATE = SKILL_ROOT / "assets/sow-template.xlsx"
for path in (SCRIPTS, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from task_standard_catalog import catalog  # noqa: E402

import pytest
from ir_samples import task_decision_ir


@pytest.mark.unit
def test_task_decision_ir_contract_rejects_model_owned_nodes_and_estimation():
    from contracts import action_contract_binding, validate_action_result
    _, digest = action_contract_binding(SKILL_ROOT, 'TASK-v1')
    envelope = {'actionContractId': 'TASK-v1', 'actionContractSha256': digest}
    valid = task_decision_ir()
    assert validate_action_result(envelope, valid, skill_root=SKILL_ROOT) == ()
    for field in ('taskId', 'storyId', 'sourceRefs', 'baseDays', 'multiplier', 'formula', 'SIT', 'UAT', 'roundedDays', 'rowSemanticSha256', 'replacementSet'):
        bad = copy.deepcopy(valid); bad['tasks'][0][field] = 'forbidden'
        assert validate_action_result(envelope, bad, skill_root=SKILL_ROOT), field
    for field, value in [('deliverableBoundary', ' '), ('technicalTarget', ''), ('workModeDecision', '复用'),
                         ('complexityDecision', 'X'), ('evidenceIds', []), ('acceptanceCriterionKeys', [])]:
        bad = copy.deepcopy(valid); bad['tasks'][0][field] = value
        assert validate_action_result(envelope, bad, skill_root=SKILL_ROOT), field


@pytest.mark.unit
def test_task_decision_ir_contract_normalizes_only_sets_and_preserves_text():
    from contracts import action_contract_binding, normalize_action_result
    _, digest = action_contract_binding(SKILL_ROOT, 'TASK-v1')
    envelope = {'actionContractId': 'TASK-v1', 'actionContractSha256': digest}
    left = task_decision_ir()
    left['tasks'][0]['deliverableBoundary'] = '  Cafe\u0301\r\n一张页面  '
    second = copy.deepcopy(left['tasks'][0]); second['localKey'] = 'second'
    left['tasks'].append(second)
    right = copy.deepcopy(left); right['tasks'].reverse()
    for task in right['tasks']:
        task['evidenceIds'].reverse(); task['acceptanceCriterionKeys'].reverse()
    assert canonical_json_bytes(left) != canonical_json_bytes(right)
    normalized = normalize_action_result(envelope, canonical_json_bytes(left), skill_root=SKILL_ROOT)
    assert normalized == normalize_action_result(envelope, canonical_json_bytes(right), skill_root=SKILL_ROOT)
    assert json.loads(normalized)['tasks'][0]['deliverableBoundary'] == left['tasks'][0]['deliverableBoundary']


# Exact-IR tests use pure sealed values; no Scope/Story host execution.
def task_input_values(model=None, roles=None):
    from ir_samples import task_story_model
    from test_contracts import valid_input_revision
    from sow_model import owner_projection_sha256
    model = task_story_model() if model is None else copy.deepcopy(model)
    source = catalog(TEMPLATE)
    revision = valid_input_revision()
    revision['templateSha256'] = source.template_sha256
    revision['priorSowState'] = 'NOT_PROVIDED'; revision['priorSowSha256s'] = []
    refs = {canonical_json_bytes(ref):ref for collection in model.values() if isinstance(collection,list)
            for item in collection for ref in item.get('sourceRefs',[])}
    source_ids = sorted({ref['sourceId'] for ref in refs.values()})
    revision['sources'] = [{'sourceId':key,'role':(roles or {}).get(key,'PRD'),'status':'APPROVED',
        'path':'sources/'+key+'.md','rawSha256':'e'*64,'parserId':'markdown','parserVersion':'1',
        'blockIds':sorted({ref['blockId'] for ref in refs.values() if ref['sourceId']==key})} for key in source_ids]
    revision['blocks'] = [{'blockId':ref['blockId'],'sourceId':ref['sourceId'],'rawSha256':'e'*64,
        'contentSha256':ref['sha256'],'locator':ref['locator'],'primaryCoverageBlockId':ref['blockId'],
        'contextBlockIds':[],'structuralParentId':None,'extractionDisposition':'INCLUDED','droppedContentCategories':[]}
        for ref in refs.values()]
    revision_bytes=canonical_json_bytes(revision)
    model['project'].update(inputRevisionSha256=sha256_bytes(revision_bytes),templateSha256=source.template_sha256)
    candidate=canonical_json_bytes(model)
    from test_contracts import checkpoint_value
    checkpoint = {**checkpoint_value('STORY_AC'), 'candidateSha256': sha256_bytes(candidate),
        'inputRevisionSha256': model['project']['inputRevisionSha256']}

    return candidate, canonical_json_bytes(checkpoint), source, revision_bytes


def exact_task_inputs(model=None, roles=None):
    import task_compiler as owner
    candidate, cp, source, revision = task_input_values(model, roles)
    return owner.prepare_task_inputs(candidate,cp,checkpoint_sha256=sha256_bytes(cp),
        task_catalog=source,input_revision_bytes=revision)


def task_packet(inputs):
    return {'workItems':[{'workItemId':item.work_item_id,'payload':item.work_item_payload} for item in inputs.work_items],
        'contextRefs':[{'refId':ref.ref_id,'canonicalContent':json.loads(ref.canonical_content),
            'contentSha256':sha256_bytes(ref.canonical_content)} for ref in inputs.context_refs]}


@pytest.mark.unit
def test_task_review_rules_bind_selected_template_rows_without_calculation_or_duplicates():
    from task_compiler import task_review_rules
    from task_standard_catalog import decision_catalog
    source = catalog(TEMPLATE)
    rules = {row['workTypeId']: row for row in decision_catalog(source)}
    model = {'project': {'templateSha256': source.template_sha256}, 'tasks': [
        {'workTypeId': key, 'rowSemanticSha256': rules[key]['rowSemanticSha256']}
        for key in ('REL-EXECUTION', 'ENG-RUNTIME', 'ENG-RUNTIME')]}
    result = task_review_rules(model, source)
    assert result == {'kind': 'TASK_RULES', 'templateSha256': source.template_sha256,
        'catalogSemanticSha256': source.task_catalog_semantic_sha256,
        'rows': [rules[key] for key in ('ENG-RUNTIME', 'REL-EXECUTION')]}
    assert all({'includes', 'excludes', 'unit', 'deliverable', 'modeRules',
        'complexityRules', 'splitRule', 'neighborRule', 'noTaskRule'} <= row.keys()
        for row in result['rows'])
    assert not any(key in canonical_json_bytes(result).decode() for key in ('baseDays', 'formula', 'multiplier'))
    for field, value in (('workTypeId', 'UNKNOWN'), ('rowSemanticSha256', '0'*64)):
        bad = copy.deepcopy(model); bad['tasks'][0][field] = value
        with pytest.raises(ValueError): task_review_rules(bad, source)
    bad = copy.deepcopy(model); bad['project']['templateSha256'] = '0'*64
    with pytest.raises(ValueError): task_review_rules(bad, source)


@pytest.mark.unit
def test_task_repair_story_factoring_is_lossless_and_rejects_drift():
    from task_compiler import factor_task_repair_packet, expand_task_repair_packet
    original = task_packet(exact_task_inputs())
    before = canonical_json_bytes(original)
    factored = factor_task_repair_packet(original)
    assert factored['packetSha256'] == sha256_bytes(before)
    assert len(factored['stories']) == 1
    assert canonical_json_bytes(expand_task_repair_packet(factored)) == before
    assert canonical_json_bytes(original) == before
    assert expand_task_repair_packet(original) == original
    for mutation in ('story', 'missing', 'reference', 'packetHash', 'workItem'):
        changed = copy.deepcopy(factored)
        key = next(iter(changed['stories']))
        if mutation == 'story': changed['stories'][key]['name'] = '篡改'
        elif mutation == 'missing': changed['stories'].pop(key)
        elif mutation == 'reference': changed['packet']['workItems'][0]['payload']['story'] = {'storyRef': '0'*64}
        elif mutation == 'packetHash': changed['packetSha256'] = '0'*64
        else: changed['packet']['workItems'][0]['workItemId'] = 'changed'
        with pytest.raises(ValueError): expand_task_repair_packet(changed)


def bound_task_ir(packet, *, target_key=None, work_type='FE-VIEW'):
    targets=[ref['canonicalContent'] for ref in packet['contextRefs'] if ref['canonicalContent'].get('kind')=='TASK_TARGET']
    target=next(item for item in targets if item['targetKey']==target_key) if target_key else targets[0]
    story_key=target['storyKeys'][0]
    task=task_decision_ir()['tasks'][0]
    task.update(storyLocalKey=story_key,acceptanceCriterionKeys=sorted(item['payload']['acceptanceCriterionKey']
        for item in packet['workItems'] if item['payload']['storyLocalKey']==story_key),
        technicalTarget=target['targetKey'],workTypeId=work_type,evidenceIds=target['evidenceIds'])
    return {'tasks':[task]}


@pytest.mark.unit
def test_task_obligation_coverage_sealed_input_and_checkpoint_projection_plan():
    import task_compiler as owner
    from stage_planner import plan_stage
    from test_stage_planner import policy
    from dataclasses import replace
    inputs=exact_task_inputs()
    rules=owner.hydrate_task_rules(inputs,['FE-VIEW'],'订单查询页面')
    assert rules[0]['workTypeId']=='FE-VIEW' and set(rules[0]['complexityRules'])=={'S','M','L'}
    assert len(rules)>1 and 'baseDays' not in rules[0]
    works=owner.build_task_work_descriptors(inputs.work_items,inputs.context_refs,policy())
    plan=plan_stage('TASK',inputs.work_items,inputs.context_refs,works,[inputs.checkpoint_sha256],policy())
    assert [(i.source_role,i.source_sha256,i.block_ordinal) for i in inputs.work_items] == [
        ('STORY_AC_CHECKPOINT',inputs.checkpoint_sha256,0),('STORY_AC_CHECKPOINT',inputs.checkpoint_sha256,1)]
    assert [i.work_item_payload['acceptanceCriterionKey'] for i in inputs.work_items] == ['ac:ac-empty','ac:ac-success']
    reversed_works=owner.build_task_work_descriptors(inputs.work_items[::-1],inputs.context_refs[::-1],policy())
    assert plan==plan_stage('TASK',inputs.work_items[::-1],inputs.context_refs[::-1],reversed_works,[inputs.checkpoint_sha256],policy())
    assert all(not w['packetPlan']['dependencyLogicalWorkIds'] for w in plan['works'])
    for mutation in ('hash','review','projection','open','template','revision'):
        candidate, cp, source, revision=task_input_values(); checkpoint=json.loads(cp)
        if mutation=='review': checkpoint.pop('reviewDecisionSha256')
        if mutation=='projection': checkpoint['candidateSha256']='0'*64
        if mutation=='open': checkpoint['effectiveAttemptRecordSha256s']=[]
        if mutation=='template': source=replace(source,template_sha256='0'*64)
        if mutation=='revision': revision=revision.replace(b'APPROVED',b'SELECTED')
        cp=canonical_json_bytes(checkpoint)
        with pytest.raises(ValueError): owner.prepare_task_inputs(candidate,cp,checkpoint_sha256='0'*64 if mutation=='hash' else sha256_bytes(cp),task_catalog=source,input_revision_bytes=revision)
    with pytest.raises(ValueError): owner.build_task_work_descriptors((replace(inputs.work_items[0],block_ordinal=99),*inputs.work_items[1:]),inputs.context_refs,policy())
    locked=json.loads((FIXTURES/'planner/task-plan-hash.json').read_bytes())
    assert sha256_bytes(canonical_json_bytes(plan))==locked['stagePlanSha256']


@pytest.mark.unit
def test_task_obligation_coverage_rejects_missing_duplicate_orphan_catalog_and_mode():
    import task_compiler as owner
    packet=task_packet(exact_task_inputs()); valid=bound_task_ir(packet)
    assert owner.verify_task_decision(packet,valid)==()
    for mutation,code in [('missing','TASK_STORY_AC_COVERAGE_INCOMPLETE'),('duplicate','TASK_DUPLICATE_CHARGE'),
            ('story','TASK_STORY_NOT_ASSIGNED'),('ac','TASK_AC_STORY_MISMATCH'),('catalog','TASK_STANDARD_UNKNOWN'),
            ('mode','TASK_EFFECTIVE_START_EVIDENCE_MISSING'),('evidence','TASK_EVIDENCE_UNBOUND'),('target','TASK_TARGET_UNBOUND')]:
        bad=copy.deepcopy(valid); task=bad['tasks'][0]
        if mutation=='missing': task['acceptanceCriterionKeys'].pop()
        if mutation=='duplicate': other=copy.deepcopy(task);other['localKey']='duplicate';bad['tasks'].append(other)
        if mutation=='story': task['storyLocalKey']='story:unknown'
        if mutation=='ac': task['acceptanceCriterionKeys']=['ac:unknown']
        if mutation=='catalog': task['workTypeId']='BAD-ID'
        if mutation=='mode': task['workModeDecision']='调整'
        if mutation=='evidence': task['evidenceIds']=['unbound']
        if mutation=='target': task['technicalTarget']='target:unbound'
        assert code in {d.code for d in owner.verify_task_decision(packet,bad)},mutation


@pytest.mark.unit
@pytest.mark.parametrize('work_type',['FE-QUERY-API','DATA-MODEL-STORAGE','IN-INTEGRATION','IN-IDENTITY','ENG-RUNTIME'])
def test_demo_task_authority_rejects_technical_types_and_evidence_free_upgrade(work_type):
    import task_compiler as owner
    packet=task_packet(exact_task_inputs(roles={'prd':'DEMO'})); valid=bound_task_ir(packet)
    assert owner.verify_task_decision(packet,valid)==()
    task=valid['tasks'][0];task['workTypeId']=work_type
    assert 'TASK_DEMO_TECHNICAL_AUTHORITY' in {d.code for d in owner.verify_task_decision(packet,valid)}
    task['workTypeId']='FE-VIEW';task['complexityDecision']='L'
    assert 'TASK_COMPLEXITY_EVIDENCE_MISSING' in {d.code for d in owner.verify_task_decision(packet,valid)}


def technical_model(*, demo=False, integration=False):
    from ir_samples import task_story_model
    model=task_story_model()
    ref={'sourceId':'hld','blockId':'design-block','sha256':'d'*64,'locator':'section:api'}
    model['designItems']=[{'designItemId':'design-query','name':'订单查询接口','featureIds':['feature-query'],'sourceRefs':[ref],'status':'APPROVED'}]
    model['stories'][0]['designRefs']=['design-query']
    for ac in model['acceptanceCriteria']: ac['designRefs']=['design-query']
    if integration:
        model['integrations']=[{'integrationId':'integration-query','name':'查询订单服务','featureIds':['feature-query'],
            'sourceRefs':[ref],'direction':'outbound','trigger':'查询','purpose':'取得订单','dataCategories':['order'],
            'responsibilityBoundaryIds':['customer'],'counterpartyBoundary':'EXTERNAL'}]
    return model


@pytest.mark.unit
def test_task_obligation_coverage_integration_has_one_qualified_owner_and_approved_target():
    import task_compiler as owner
    packet=task_packet(exact_task_inputs(technical_model(integration=True),{'hld':'HLD'}))
    valid=bound_task_ir(packet,target_key='target:integration-query',work_type='IN-INTEGRATION')
    assert owner.verify_task_decision(packet,valid)==()
    wrong=copy.deepcopy(valid);wrong['tasks'][0]['workTypeId']='FE-QUERY-API'
    assert 'TASK_INTEGRATION_TYPE_INVALID' in {d.code for d in owner.verify_task_decision(packet,wrong)}
    missing=bound_task_ir(packet,target_key='target:design-query',work_type='FE-QUERY-API')
    assert 'TASK_INTEGRATION_OWNER_NON_UNIQUE' in {d.code for d in owner.verify_task_decision(packet,missing)}
    demo=task_packet(exact_task_inputs(technical_model(integration=True),{'hld':'DEMO'}))
    assert 'TASK_DEMO_TECHNICAL_AUTHORITY' in {d.code for d in owner.verify_task_decision(demo,bound_task_ir(demo,target_key='target:integration-query',work_type='IN-INTEGRATION'))}


@pytest.mark.unit
@pytest.mark.parametrize('technical_role', ['HLD', 'DEMO'])
@pytest.mark.parametrize('include_integration', [False, True])
def test_policy_target_retains_its_feature_approved_technical_baseline(technical_role, include_integration):
    import task_compiler as owner
    model=technical_model(integration=include_integration)
    model['policyInstances']=[{'policyInstanceId':'policy-uat','policyId':'policy-uat-automation',
        'targetNodeIds':['feature-query'],'inclusionPolicy':'DEFAULT_INCLUDED',
        'sourceRefs':model['inputItems'][0]['sourceRefs']}]
    model['stories'][0]['policyRefs']=['policy-uat']
    for ac in model['acceptanceCriteria']: ac['policyRefs']=['policy-uat']
    packet=task_packet(exact_task_inputs(model,{'hld':technical_role}))
    target=next(ref['canonicalContent'] for ref in packet['contextRefs'] if ref['canonicalContent'].get('targetKind')=='POLICY_INSTANCE')
    ir=bound_task_ir(packet,target_key=target['targetKey'],work_type='TEST-UI-E2E')
    if include_integration:
        integration=bound_task_ir(packet,target_key='target:integration-query',work_type='IN-INTEGRATION')['tasks'][0]
        integration['localKey']='interface-owner';ir['tasks'].append(integration)
    codes={d.code for d in owner.verify_task_decision(packet,ir)}
    if technical_role=='HLD':
        assert codes==set()
        assert model['designItems'][0]['sourceRefs'][0] in target['sourceRefs']
        assert target['storyKeys']==['story:story-query']
    else:
        assert 'TASK_DEMO_TECHNICAL_AUTHORITY' in codes
        assert model['designItems'][0]['sourceRefs'][0] not in target['sourceRefs']


@pytest.mark.unit
def test_integration_owner_prefers_explicit_source_obligation_over_story_id_order():
    import task_compiler as owner
    model=technical_model(integration=True)
    first,second=copy.deepcopy(model['stories'][0]),copy.deepcopy(model['stories'][0])
    first.update(storyId='story-z-interface',name='实现订单接口',coverageSet=['input-a'],requirementRefs=['input-a'])
    second.update(storyId='story-a-runtime',name='运行组件',coverageSet=['input-b'],requirementRefs=['input-b'])
    first['sourceRefs']=[*model['inputItems'][0]['sourceRefs'],*model['integrations'][0]['sourceRefs']]
    second['sourceRefs']=model['inputItems'][1]['sourceRefs']
    model['stories']=[first,second]
    model['acceptanceCriteria'][0].update(storyId=first['storyId'])
    model['acceptanceCriteria'][1].update(storyId=second['storyId'])
    model['scopeClosure'][0]['targetNodeIds']=['integration-query']
    packet=task_packet(exact_task_inputs(model,{'hld':'HLD'}))
    target=next(ref['canonicalContent'] for ref in packet['contextRefs'] if ref['canonicalContent'].get('targetKind')=='INTEGRATION')
    assert target['storyKeys']==['story:story-z-interface']


@pytest.mark.unit
def test_shared_policy_targets_do_not_borrow_other_feature_design_evidence():
    import task_compiler as owner
    model=technical_model()
    other_ref={'sourceId':'hld','blockId':'other-design','sha256':'c'*64,'locator':'section:other'}
    other_feature={**copy.deepcopy(model['features'][0]),'featureId':'feature-other','requirementRefs':['input-b']}
    model['features'][0]['requirementRefs']=['input-a'];model['features'].append(other_feature)
    model['scopeClosure'][1].update(targetNodeIds=['feature-other'],assignedFeatureIds=['feature-other'])
    model['designItems'].append({'designItemId':'design-other','name':'另一组件','featureIds':['feature-other'],'sourceRefs':[other_ref],'status':'APPROVED'})
    original=model['stories'][0]
    other={**copy.deepcopy(original),'storyId':'story-other','featureId':'feature-other',
        'coverageSet':['input-b'],'requirementRefs':['input-b'],'designRefs':['design-other']}
    original.update(coverageSet=['input-a'],requirementRefs=['input-a']);model['stories'].append(other)
    model['acceptanceCriteria'][1].update(storyId='story-other',designRefs=['design-other'])
    model['policyInstances']=[{'policyInstanceId':'policy-shared','policyId':'policy-uat-automation',
        'targetNodeIds':['epic-orders'],'inclusionPolicy':'DEFAULT_INCLUDED','sourceRefs':model['inputItems'][0]['sourceRefs']}]
    for row in model['stories']+model['acceptanceCriteria']: row['policyRefs']=['policy-shared']
    packet=task_packet(exact_task_inputs(model,{'hld':'HLD'}))
    targets=[ref['canonicalContent'] for ref in packet['contextRefs'] if ref['canonicalContent'].get('targetKind')=='POLICY_INSTANCE']
    assert len(targets)==2 and len({row['targetKey'] for row in targets})==2
    for target in targets:
        assert len(target['storyKeys'])==1 and target['policyInstanceIds']==['policy-shared']
        expected=other_ref if target['storyKeys']==['story:story-other'] else model['designItems'][0]['sourceRefs'][0]
        forbidden=model['designItems'][0]['sourceRefs'][0] if expected==other_ref else other_ref
        assert expected in target['sourceRefs'] and forbidden not in target['sourceRefs']


def task_runtime(inputs=None,sizing=None):
    import task_compiler as owner
    from test_stage_planner import policy
    from stage_planner import plan_stage
    from action_ledger import ActionLedger
    inputs=inputs or exact_task_inputs();sizing=sizing or policy()
    works=owner.build_task_work_descriptors(inputs.work_items,inputs.context_refs,sizing)
    plan=plan_stage('TASK',inputs.work_items,inputs.context_refs,works,[inputs.checkpoint_sha256],sizing)
    return inputs,plan,ActionLedger(),sizing


def seal_task_work(runtime,result=None,*,revision=1,attempt=1,completion=None,work_index=0):
    import task_compiler as owner
    from test_stage_planner import envelope_for_plan
    from stage_planner import materialize_packet,run_budget_policy_value
    from action_ledger import issue,finish,build_attempt_repair_context
    from test_action_ledger import successful_completion
    from contracts import estimate_action_input_tokens
    from models import ActionEnvelope
    inputs,plan,ledger,sizing=runtime;work=plan['works'][work_index];key=work['logicalWorkId']
    repair=None
    if revision==2:
        failed=next(digest for digest,record in ledger.attempt_records.items() if record.logical_work_id==key and record.failure_kind=='INVALID_IR')
        repair=build_attempt_repair_context(key,failed,ledger.attempt_records,ledger.raw_outputs,envelopes_by_sha256=ledger.envelopes_by_sha256)
    payload=materialize_packet(plan,key,revision,inputs.work_items,inputs.context_refs,[],ledger,repair)
    packet=json.loads(payload)
    value={**envelope_for_plan(plan,key).value,'runId':'run-task',
        'inputRevisionSha256':sha256_bytes(inputs.input_revision_bytes),'baseCandidateSha256':sha256_bytes(inputs.story_candidate_bytes),
        'packetSha256':sha256_bytes(payload),'revision':revision,'attempt':attempt}
    value['actionId']+='-r'+str(revision)+'-a'+str(attempt)
    value['executionLimits']={'estimatedInputTokens':estimate_action_input_tokens(SKILL_ROOT,'TASK-v1',payload,
        budget_policy=run_budget_policy_value(sizing),max_output_tokens=sizing.output_reserve_tokens),
        'maxOutputTokens':sizing.output_reserve_tokens,'maxHydrateTokens':sizing.hydrate_reserve_tokens}
    envelope=ActionEnvelope(value,'actions/'+value['actionId']+'/envelope.json',sha256_bytes(canonical_json_bytes(value)))
    owner.validate_bound_task_context(packet)
    ledger,record=finish(issue(ledger,envelope),envelope,
        completion or successful_completion(canonical_json_bytes(result if result is not None else bound_task_ir(packet))),
        bound_result_validator=lambda raw:owner.validate_bound_task_result(packet,raw))
    return (inputs,plan,ledger,sizing),record


def test_task_materialize_once_per_revision_complete_ledger_identity_immutable_publication(tmp_path):
    import task_compiler as owner
    from runtime.project_io import ProjectFiles
    runtime=task_runtime()
    with pytest.raises(owner.TaskInputRequired): owner.materialize_task_candidate(*runtime)
    runtime,record=seal_task_work(runtime)
    assert record.outcome=='SUCCEEDED'
    material=owner.materialize_task_candidate(*runtime)
    assert owner.validate_task_candidate(material)==()
    model=json.loads(material.candidate_bytes);upstream=json.loads(runtime[0].story_candidate_bytes)
    for collection in upstream:
        if collection not in owner.STAGE_3_COLLECTIONS: assert model[collection]==upstream[collection]
    assert len(model['tasks'])==len(model['effectiveStartMatches'])==1
    task=model['tasks'][0]
    assert task['storyId']=='story-query' and task['acceptanceCriterionIds']==['ac-empty','ac-success']
    assert task['workMode']=='新建' and task['complexity']=='M' and task['sourceRefs']
    assert model['effectiveStartMatches'][0]['decision']=='NO_MATCH_NEW'
    assert task['rowSemanticSha256']==runtime[0].task_catalog.by_work_type_id['FE-VIEW']['rowSemanticSha256']
    renamed=bound_task_ir(task_packet(runtime[0]));renamed['tasks'][0].update(localKey='renamed',deliverableBoundary='一张筛选并展示订单的页面',complexityDecision='S')
    changed,_=seal_task_work(task_runtime(runtime[0]),renamed)
    revised=owner.materialize_task_candidate(*changed)
    assert json.loads(revised.candidate_bytes)['tasks'][0]['taskId']==task['taskId']
    assert revised.candidate_sha256!=material.candidate_sha256
    assert owner.materialize_task_candidate(*runtime).candidate_bytes==material.candidate_bytes
    files=ProjectFiles.open(tmp_path)
    owner.publish_task_candidate(files,'run-task',material)
    path=tmp_path/'.ai-sow/work/runs/run-task/stages/TASK/candidates'/f'{material.candidate_sha256}.json'
    before=path.stat().st_mtime_ns
    owner.publish_task_candidate(files,'run-task',material);owner.publish_task_candidate(files,'run-task',revised)
    assert path.stat().st_mtime_ns==before and path.read_bytes()==material.candidate_bytes
    assert len(list(path.parent.glob('*.json')))==2


def test_task_materialize_once_per_revision_execution_retry_and_invalid_ir_repair():
    import task_compiler as owner
    from dataclasses import replace
    from test_action_ledger import successful_completion
    baseline,_=seal_task_work(task_runtime());expected=owner.materialize_task_candidate(*baseline)
    from models import AttemptDiagnostic
    failed,_=seal_task_work(task_runtime(),completion=replace(successful_completion(),raw_output=None,
        failure_kind='EXECUTION',diagnostic=AttemptDiagnostic('TIMEOUT','',())))
    retried,record=seal_task_work(failed,attempt=2)
    assert record.outcome=='SUCCEEDED' and owner.materialize_task_candidate(*retried).candidate_bytes==expected.candidate_bytes
    invalid,record=seal_task_work(task_runtime(),{'tasks':[]})
    assert record.failure_kind=='INVALID_IR'
    with pytest.raises(owner.TaskInputRequired): owner.materialize_task_candidate(*invalid)
    repaired,record=seal_task_work(invalid,revision=2)
    assert record.outcome=='SUCCEEDED' and owner.materialize_task_candidate(*repaired).candidate_bytes==expected.candidate_bytes
    inputs,plan,ledger,sizing=repaired
    poisoned=dict(ledger.normalized_results);poisoned[record.normalized_result_sha256]=b'{}\n'
    with pytest.raises(ValueError): owner.materialize_task_candidate(inputs,plan,replace(ledger,normalized_results=poisoned),sizing)


@pytest.mark.parametrize('field,value',[('name','伪造标题'),('complexity','L'),('rowSemanticSha256','0'*64),
    ('acceptanceCriterionIds',[]),('integrationIds',['forged']),('sourceRefs',[])])
def test_task_materialize_once_per_revision_independent_validation_binds_all_ir_fields(field,value):
    import task_compiler as owner
    from dataclasses import replace
    runtime,_=seal_task_work(task_runtime());material=owner.materialize_task_candidate(*runtime)
    model=json.loads(material.candidate_bytes);model['tasks'][0][field]=value
    raw=canonical_json_bytes(model)
    codes={d.code for d in owner.validate_task_candidate(replace(material,candidate_bytes=raw,candidate_sha256=sha256_bytes(raw)))}
    assert 'TASK_NODE_IR_BINDING_MISMATCH' in codes


def test_task_obligation_coverage_preseal_callback_is_pure_and_records_invalid_ir(monkeypatch):
    import task_compiler as owner
    packet=task_packet(exact_task_inputs())
    owner.validate_bound_task_context(packet)
    valid=canonical_json_bytes(bound_task_ir(packet))
    with monkeypatch.context() as guard:
        guard.setattr(Path,'read_bytes',lambda *args: (_ for _ in ()).throw(AssertionError('callback read')))
        owner.validate_bound_task_result(packet,valid)
        with pytest.raises(Exception,match='Task IR'): owner.validate_bound_task_result(packet,b'{"tasks":[]}\n')
    runtime,record=seal_task_work(task_runtime(),{'tasks':[]})
    assert record.failure_kind=='INVALID_IR' and record.normalized_result_sha256 is None


def prior_task_inputs(*, mode='ADJUST', role='PRIOR_SOW', future=False):
    import task_compiler as owner
    from sow_model import owner_projection_sha256
    base=technical_model()
    if mode=='REUSE_DEPENDENCY': base['designItems'][0]['name']='应用配置与功能开关'
    candidate,cp,source,raw=task_input_values(base,{'hld':'HLD'})
    model,revision,checkpoint=map(json.loads,(candidate,raw,cp))
    revision['priorSowState']='PROVIDED';revision['priorSowSha256s']=['9'*64]
    revision['sources'].append({'sourceId':'prior','role':role,'status':'APPLICABLE','path':'sources/prior.xlsx',
        'rawSha256':'9'*64,'parserId':'xlsx-inventory','parserVersion':'1','blockIds':[]})
    raw=canonical_json_bytes(revision);model['project']['inputRevisionSha256']=sha256_bytes(raw)
    model['project']['mode']='BROWNFIELD';candidate=canonical_json_bytes(model)
    checkpoint.update(candidateSha256=sha256_bytes(candidate),inputRevisionSha256=sha256_bytes(raw))
    cp=canonical_json_bytes(checkpoint)
    snapshot={'contractVersion':'prior-state-snapshot-v1','inputRevisionSha256':sha256_bytes(raw),
        'evidence':[{'priorEvidenceId':'7'*64,'sourceId':'prior','workbookSha256':'9'*64,'sheet':'Scope',
            'absoluteA1Range':'$A$1:$A$1','canonicalCellValuesSha256':'8'*64,
            'canonicalCellValues':[{'address':'$A$1','cellType':'s','value':'查询接口','formula':None,'cachedValue':None}]}],
        'entities':[{'entityId':'prior-query','sourceId':'prior','entityKind':'CONTRACT_ENTITY','semanticSummary':'现有查询接口',
            'deliveryStatus':'FUTURE' if future else 'CURRENT_BY_CONTRACT','evidenceIds':['7'*64]}],
        'sourceRelations':[],'entitySupersessions':[]}
    graph={'changeGroups':[{'kind':mode,'priorEntityIds':['prior-query'],'targetEntityIds':['design-query'],
        'evidenceIds':['7'*64,'design-block']}],'retiredPrior':[]}
    prior_bytes,graph_bytes=map(canonical_json_bytes,(snapshot,graph))
    return owner.prepare_task_inputs(candidate,cp,checkpoint_sha256=sha256_bytes(cp),task_catalog=source,input_revision_bytes=raw,
        prior_state_bytes=prior_bytes,prior_state_sha256=sha256_bytes(prior_bytes),change_graph_bytes=graph_bytes,change_graph_sha256=sha256_bytes(graph_bytes))


@pytest.mark.parametrize('kind,mode,decision',[('ADJUST','调整','MATCHED_ADJUSTMENT'),('REUSE_DEPENDENCY','接入复用','MATCHED_REUSE')])
def test_task_materialize_once_per_revision_uses_verified_prior_hash_projection(kind,mode,decision):
    import task_compiler as owner
    inputs=prior_task_inputs(mode=kind);packet=task_packet(inputs)
    serialized=json.dumps(packet)
    assert 'canonicalCellValues' not in serialized and 'absoluteA1Range' not in serialized
    result=bound_task_ir(packet,target_key='target:design-query',work_type='CO-CONFIG' if kind=='REUSE_DEPENDENCY' else 'FE-QUERY-API')
    result['tasks'][0].update(workModeDecision=mode,evidenceIds=[*result['tasks'][0]['evidenceIds'],'prior:prior-query'])
    assert owner.verify_task_decision(packet,result)==()
    runtime,record=seal_task_work(task_runtime(inputs),result)
    assert record.outcome=='SUCCEEDED'
    material=owner.materialize_task_candidate(*runtime)
    assert owner.validate_task_candidate(material)==()
    match=json.loads(material.candidate_bytes)['effectiveStartMatches'][0]
    assert match['decision']==decision and match['candidateIds']==['prior-query'] and match['checkedLocators']
    wrong=copy.deepcopy(result);wrong['tasks'][0]['technicalTarget']='target:story-query';wrong['tasks'][0]['workTypeId']='FE-VIEW'
    assert 'TASK_EFFECTIVE_START_EVIDENCE_MISSING' in {d.code for d in owner.verify_task_decision(packet,wrong)}
    for kwargs in ({'role':'DEMO'},{'future':True}):
        with pytest.raises(ValueError): prior_task_inputs(**kwargs)


@pytest.mark.unit
def test_task_obligation_coverage_demo_whole_file_anchor_and_shared_integration_are_bounded():
    import task_compiler as owner
    from ir_samples import task_story_model
    from sow_model import owner_projection_sha256
    model=task_story_model()
    for collection in ('inputItems','scopeClosure','stories','acceptanceCriteria'):
        for item in model[collection]:
            for ref in item['sourceRefs']:
                ref.update(blockId='demo-evidence',sha256='e'*64,locator='file:sources/prd.md')
    candidate,cp,source,revision=task_input_values(model,{'prd':'DEMO'})
    revision=json.loads(revision);revision['blocks']=[];revision['sources'][0]['blockIds']=[]
    raw=canonical_json_bytes(revision);model=json.loads(candidate);model['project']['inputRevisionSha256']=sha256_bytes(raw)
    candidate=canonical_json_bytes(model);cp=json.loads(cp);cp.update(candidateSha256=sha256_bytes(candidate),inputRevisionSha256=sha256_bytes(raw))
    cp=canonical_json_bytes(cp)
    inputs=owner.prepare_task_inputs(candidate,cp,checkpoint_sha256=sha256_bytes(cp),task_catalog=source,input_revision_bytes=raw)
    packet=task_packet(inputs)
    assert owner.verify_task_decision(packet,bound_task_ir(packet))==()
    shared=technical_model(integration=True)
    shared['stories'].append({**copy.deepcopy(shared['stories'][0]),'storyId':'story-z'})
    shared['acceptanceCriteria'] += [{**copy.deepcopy(ac),'storyId':'story-z','acceptanceCriterionId':ac['acceptanceCriterionId']+'-z'} for ac in list(shared['acceptanceCriteria'])]
    inputs=exact_task_inputs(shared,{'hld':'HLD'})
    targets=[json.loads(ref.canonical_content) for ref in inputs.context_refs if ref.ref_id=='target:integration-query']
    assert targets[0]['storyKeys']==['story:story-query']


def test_task_materialize_once_per_revision_waits_for_all_work_and_rejects_cross_work_double_charge():
    import task_compiler as owner
    from ir_samples import task_story_model
    from dataclasses import replace
    from test_stage_planner import policy
    model=task_story_model()
    model['stories'].append({**copy.deepcopy(model['stories'][0]),'storyId':'story-z','name':'查询其他订单'})
    model['acceptanceCriteria'] += [{**copy.deepcopy(ac),'storyId':'story-z','acceptanceCriterionId':ac['acceptanceCriterionId']+'-z'} for ac in list(model['acceptanceCriteria'])]
    inputs=exact_task_inputs(model)
    sizing=replace(policy(),model_context_limit_tokens=60000)
    runtime=task_runtime(inputs,sizing)
    assert len(runtime[1]['works'])==2
    runtime,_=seal_task_work(runtime,work_index=1)
    with pytest.raises(owner.TaskInputRequired): owner.materialize_task_candidate(*runtime)
    runtime,_=seal_task_work(runtime,work_index=0)
    material=owner.materialize_task_candidate(*runtime)
    assert owner.validate_task_candidate(material)==()
    normal,_=seal_task_work(task_runtime(inputs,sizing),work_index=0)
    normal,_=seal_task_work(normal,work_index=1)
    assert owner.materialize_task_candidate(*normal).candidate_bytes==material.candidate_bytes
    assert len(json.loads(material.candidate_bytes)['tasks'])==2
    poisoned=replace(inputs,context_refs=tuple(replace(ref,canonical_content=ref.canonical_content.replace(b'PRD',b'DEMO')) if ref.ref_id.startswith('evidence-') else ref for ref in inputs.context_refs))
    with pytest.raises(ValueError): owner.materialize_task_candidate(poisoned,*runtime[1:])


@pytest.mark.unit
def test_task_obligation_coverage_counts_one_shared_pipeline_and_rejects_repeated_service_tasks():
    import task_compiler as owner
    model=technical_model();model['designItems'][0]['name']='九个服务共用的一套流水线'
    packet=task_packet(exact_task_inputs(model,{'hld':'HLD'}))
    result=bound_task_ir(packet,target_key='target:design-query',work_type='ENG-PIPELINE')
    result['tasks'][0]['deliverableBoundary']='九个服务共用的一套流水线'
    assert owner.verify_task_decision(packet,result)==()
    result['tasks']=[{**copy.deepcopy(result['tasks'][0]),'localKey':'service-'+str(i)} for i in range(9)]
    codes={d.code for d in owner.verify_task_decision(packet,result)}
    assert {'TASK_DUPLICATE_CHARGE','TASK_STORY_TASK_LIMIT'}<=codes


@pytest.mark.unit
def test_task_obligation_coverage_rejects_unrelated_evidence_and_unimplemented_design():
    import task_compiler as owner
    model=technical_model()
    packet=task_packet(exact_task_inputs(model,{'hld':'HLD'}))
    ui=bound_task_ir(packet,target_key='target:story-query')
    assert 'TASK_STORY_DESIGN_COVERAGE_INCOMPLETE' in {d.code for d in owner.verify_task_decision(packet,ui)}
    design=bound_task_ir(packet,target_key='target:design-query',work_type='FE-QUERY-API')
    # A different approved target is not evidence for this task's selected object.
    extra=copy.deepcopy(model['designItems'][0]);extra.update(designItemId='design-other',name='无关的另一个接口',
        sourceRefs=[{'sourceId':'hld','blockId':'other-block','sha256':'f'*64,'locator':'section:other'}])
    model['designItems'].append(extra);model['stories'][0]['designRefs'].append('design-other')
    packet=task_packet(exact_task_inputs(model,{'hld':'HLD'}))
    unrelated=next(ref['canonicalContent']['evidenceIds'][0] for ref in packet['contextRefs'] if ref['refId']=='target:design-other')
    design['tasks'][0]['evidenceIds'].append(unrelated)
    assert 'TASK_EVIDENCE_UNBOUND' in {d.code for d in owner.verify_task_decision(packet,design)}


def test_task_materialize_once_per_revision_distinct_interfaces_share_design_without_duplicate_charge():
    import task_compiler as owner
    inputs=exact_task_inputs(technical_model(),{'hld':'HLD'});packet=task_packet(inputs)
    result=bound_task_ir(packet,target_key='target:design-query',work_type='FE-QUERY-API')
    template=result['tasks'][0]
    ac_evidence={item['payload']['acceptanceCriterionKey']:item['payload']['evidenceIds'] for item in packet['workItems']}
    result['tasks']=[{**copy.deepcopy(template),'localKey':str(i),'acceptanceCriterionKeys':[key],
        'evidenceIds':sorted(set(template['evidenceIds']+ac_evidence[key])),
        'deliverableBoundary':boundary} for i,(key,boundary) in enumerate([
            ('ac:ac-empty','一项无匹配订单查询接口'),('ac:ac-success','一项有效订单查询接口')])]
    assert owner.verify_task_decision(packet,result)==()
    runtime,record=seal_task_work(task_runtime(inputs),result)
    assert record.outcome=='SUCCEEDED'
    material=owner.materialize_task_candidate(*runtime)
    assert owner.validate_task_candidate(material)==()
    tasks=json.loads(material.candidate_bytes)['tasks']
    assert len({task['taskId'] for task in tasks})==2
    assert {tuple(task['acceptanceCriterionIds']) for task in tasks}=={('ac-empty',),('ac-success',)}
    duplicate=copy.deepcopy(result);duplicate['tasks'][1]['evidenceIds']=duplicate['tasks'][0]['evidenceIds']
    assert 'TASK_DUPLICATE_CHARGE' in {d.code for d in owner.verify_task_decision(packet,duplicate)}


@pytest.mark.unit
def test_task_obligation_coverage_shared_integration_keeps_responsible_story_design():
    import task_compiler as owner
    model=technical_model(integration=True)
    other=copy.deepcopy(model['designItems'][0]);other.update(designItemId='design-other',name='另一个技术对象',
        sourceRefs=[{'sourceId':'hld','blockId':'block-other','sha256':'f'*64,'locator':'section:other'}])
    model['designItems'].append(other)
    model['stories'].append({**copy.deepcopy(model['stories'][0]),'storyId':'story-z','designRefs':['design-other']})
    model['acceptanceCriteria'] += [{**copy.deepcopy(ac),'storyId':'story-z',
        'acceptanceCriterionId':ac['acceptanceCriterionId']+'-z','designRefs':['design-other']} for ac in list(model['acceptanceCriteria'])]
    inputs=exact_task_inputs(model,{'hld':'HLD'})
    target=next(json.loads(ref.canonical_content) for ref in inputs.context_refs if ref.ref_id=='target:integration-query')
    assert target['storyKeys']==['story:story-query'] and target['designItemIds']==['design-query']
    packet=task_packet(inputs)
    result=bound_task_ir(packet,target_key='target:integration-query',work_type='IN-INTEGRATION')
    result['tasks'] += bound_task_ir(packet,target_key='target:design-other',work_type='FE-QUERY-API')['tasks']
    result['tasks'][1]['localKey']='other'
    assert owner.verify_task_decision(packet,result)==()


def test_task_accepts_one_complete_sealed_acceptance_criterion():
    from ir_samples import task_story_model
    model = task_story_model()
    model['acceptanceCriteria'] = model['acceptanceCriteria'][:1]
    inputs = exact_task_inputs(model)
    assert len(inputs.work_items) == 1
    assert inputs.work_items[0].work_item_payload['acceptanceCriterionId'] == model['acceptanceCriteria'][0]['acceptanceCriterionId']


@pytest.mark.unit
def test_story_implementation_closes_shared_design_constraints_without_repeated_runtime_charge():
    import task_compiler as owner
    model=technical_model()
    runtime_ref={'sourceId':'hld','blockId':'runtime-block','sha256':'f'*64,'locator':'section:runtime'}
    model['designItems'].append({'designItemId':'design-runtime','name':'同一应用在单一环境部署',
        'featureIds':['feature-query'],'sourceRefs':[runtime_ref],'status':'APPROVED'})
    model['stories'][0]['designRefs'].append('design-runtime')
    for ac in model['acceptanceCriteria']: ac['designRefs'].append('design-runtime')
    second={**copy.deepcopy(model['stories'][0]),'storyId':'story-second','name':'第二项业务处理'}
    model['stories'].append(second)
    model['acceptanceCriteria'][1]['storyId']='story-second'
    inputs=exact_task_inputs(model,{'hld':'HLD'});packet=task_packet(inputs)
    targets=[ref['canonicalContent'] for ref in packet['contextRefs']
             if ref['canonicalContent'].get('targetKind')=='STORY_IMPLEMENTATION']
    assert len(targets)==2
    result={'tasks':[]}
    for target in targets:
        assert target['designItemIds']==['design-query','design-runtime']
        task=bound_task_ir(packet,target_key=target['targetKey'],work_type='FE-QUERY-API')['tasks'][0]
        task['localKey']=target['targetKey'];result['tasks'].append(task)
    deployment=bound_task_ir(packet,target_key='target:design-runtime',work_type='ENG-RUNTIME')['tasks'][0]
    deployment['localKey']='single-runtime';result['tasks'].append(deployment)
    assert owner.verify_task_decision(packet,result)==()
    nodes=[node for kind,node in owner._task_node_bindings(packet,result) if kind=='tasks']
    assert len({node['taskId'] for node in nodes})==3
    assert sum(node['workTypeId']=='ENG-RUNTIME' for node in nodes)==1
    assert owner._task_coverage_diagnostics({**model,'tasks':nodes,'effectiveStartMatches':[
        node for kind,node in owner._task_node_bindings(packet,result) if kind=='effectiveStartMatches']})==()


@pytest.mark.unit
@pytest.mark.parametrize('role',['PRD','DEMO'])
def test_story_implementation_requires_approved_technical_baseline(role):
    packet=task_packet(exact_task_inputs(technical_model(),{'hld':role}))
    assert not any(ref['canonicalContent'].get('targetKind')=='STORY_IMPLEMENTATION'
                   for ref in packet['contextRefs'])


@pytest.mark.unit
def test_story_implementation_does_not_inherit_unreferenced_design_or_ui_authority():
    import task_compiler as owner
    model=technical_model()
    unrelated={'sourceId':'hld','blockId':'unrelated-block','sha256':'f'*64,'locator':'section:unrelated'}
    model['designItems'].append({'designItemId':'unrelated-design','name':'未引用的另一对象',
        'featureIds':['feature-query'],'sourceRefs':[unrelated],'status':'APPROVED'})
    packet=task_packet(exact_task_inputs(model,{'hld':'HLD'}))
    target=next(ref['canonicalContent'] for ref in packet['contextRefs']
                if ref['canonicalContent'].get('targetKind')=='STORY_IMPLEMENTATION')
    assert target['storyKeys']==['story:story-query']
    assert target['designItemIds']==['design-query'] and unrelated not in target['sourceRefs']
    ui=bound_task_ir(packet,target_key='target:story-query')
    assert 'TASK_STORY_DESIGN_COVERAGE_INCOMPLETE' in {d.code for d in owner.verify_task_decision(packet,ui)}


@pytest.mark.unit
def test_task_diagnostics_locate_bad_root_and_deduplicate_story_coverage():
    import task_compiler as owner
    packet=task_packet(exact_task_inputs(technical_model(),{'hld':'HLD'}))
    result=bound_task_ir(packet,target_key='target:story-query')
    missing=[d for d in owner.verify_task_decision(packet,result)
             if d.code=='TASK_STORY_DESIGN_COVERAGE_INCOMPLETE']
    assert len(missing)==1
    assert missing[0].path=='/stories/story:story-query'
    assert missing[0].details=={'subjectIds':['story:story-query']}
    result['tasks'][0]['technicalTarget']='target:unknown'
    invalid=next(d for d in owner.verify_task_decision(packet,result) if d.code=='TASK_TARGET_UNBOUND')
    assert invalid.path=='/tasks/0'
    assert invalid.details=={'subjectIds':[result['tasks'][0]['localKey']]}


@pytest.mark.unit
def test_shared_release_task_uses_only_complete_declared_policy_scope():
    import task_compiler as owner
    model = technical_model()
    refs = {}
    for name in ('other', 'outside'):
        model['features'].append({**copy.deepcopy(model['features'][0]), 'featureId':'feature-'+name,
                                 'name':name, 'requirementRefs':[]})
        refs[name] = {'sourceId':'hld', 'blockId':'block-'+name,
                      'sha256':('c' if name=='other' else 'd')*64, 'locator':'section:'+name}
        model['designItems'].append({'designItemId':'design-'+name, 'name':name,
            'featureIds':['feature-'+name], 'sourceRefs':[refs[name]], 'status':'APPROVED'})
    model['policyInstances'] = [{'policyInstanceId':'shared-release', 'policyId':'policy-go-live',
        'targetNodeIds':['feature-query', 'feature-other'], 'inclusionPolicy':'REQUIRED',
        'sourceRefs':copy.deepcopy(model['inputItems'][0]['sourceRefs'])}]
    for row in model['stories']+model['acceptanceCriteria']:
        row.update(policyRefs=['shared-release'], coverageSet=['feature-query','feature-other'],
                   designRefs=['design-query','design-other'])
    inputs = exact_task_inputs(model, {'hld':'HLD'})
    packet = task_packet(inputs)
    target = next(ref['canonicalContent'] for ref in packet['contextRefs']
                  if ref['canonicalContent'].get('targetKind')=='POLICY_INSTANCE')
    assert refs['other'] in target['sourceRefs']
    assert refs['outside'] not in target['sourceRefs']
    assert target['designItemIds']==['design-other','design-query']
    result = bound_task_ir(packet, target_key=target['targetKey'], work_type='REL-EXECUTION')
    assert owner.verify_task_decision(packet, result)==()
    nodes = [node for kind,node in owner._task_node_bindings(packet,result) if kind=='tasks']
    assert len(nodes)==1 and nodes[0]['acceptanceCriterionIds']==sorted(
        criterion['acceptanceCriterionId'] for criterion in model['acceptanceCriteria'])
    runtime, record = seal_task_work(task_runtime(inputs), result)
    assert record.outcome=='SUCCEEDED'
    material = owner.materialize_task_candidate(*runtime)
    assert owner.validate_task_candidate(material)==()
    assert set(json.loads(material.candidate_bytes)['stories'][0]['coverageSet'])=={'feature-other','feature-query'}
    # Independently sourced application/environment releases remain countable.
    technical_refs = [model['designItems'][0]['sourceRefs'][0], refs['other']]
    split = {'tasks':[]}
    for index,source_ref in enumerate(technical_refs):
        evidence_id = next(ref['canonicalContent']['evidenceId'] for ref in packet['contextRefs']
            if ref['canonicalContent'].get('kind')=='TASK_EVIDENCE'
            and ref['canonicalContent']['sourceRef']==source_ref)
        split['tasks'].append({**copy.deepcopy(result['tasks'][0]), 'localKey':'release-'+str(index),
            'evidenceIds':[evidence_id], 'deliverableBoundary':'对应独立应用环境的发布'+str(index)})
    assert owner.verify_task_decision(packet,split)==()
    assert len({node['taskId'] for kind,node in owner._task_node_bindings(packet,split) if kind=='tasks'})==2
    duplicate = copy.deepcopy(split)
    duplicate['tasks'][1]['evidenceIds'] = duplicate['tasks'][0]['evidenceIds']
    assert 'TASK_DUPLICATE_CHARGE' in {d.code for d in owner.verify_task_decision(packet,duplicate)}


def shared_test_asset_model():
    model = technical_model()
    original = model['stories'][0]
    model['stories'] = []
    for i, phase in enumerate(('sit','uat')):
        policy = 'policy-' + phase
        model['policyInstances'].append({'policyInstanceId':policy,'policyId':'policy-'+phase+'-automation',
            'targetNodeIds':['feature-query'],'inclusionPolicy':'DEFAULT_INCLUDED',
            'sourceRefs':model['inputItems'][i]['sourceRefs']})
        story = copy.deepcopy(original)
        story.update(storyId='story-'+phase, policyRefs=[policy])
        model['stories'].append(story)
        model['acceptanceCriteria'][i].update(storyId=story['storyId'],policyRefs=[policy])
    return model


@pytest.mark.unit
def test_task_repair_shared_asset_keeps_all_acs_policies_and_rejects_unauthorized_coverage():
    import task_compiler as owner
    from final_review import replace_owner_decisions
    inputs = exact_task_inputs(shared_test_asset_model(), {'hld':'HLD'})
    packet = task_packet(inputs)
    original = {'tasks':[]}
    for phase in ('sit','uat'):
        task = bound_task_ir(packet,target_key='target:policy-'+phase+':story:story-'+phase,
            work_type='TEST-API')['tasks'][0]
        task['localKey'] = phase
        original['tasks'].append(task)
    assert owner.verify_task_decision(packet, original) == ()
    review = {'decision':'REPAIRABLE_SEMANTIC','findings':[{'subjectIds':['sit','uat']}]}
    repaired_packet = owner.prepare_task_repair_packet(packet,original,review,
        inputs.story_candidate_bytes,inputs.input_revision_bytes)
    merged = copy.deepcopy(original['tasks'][0])
    merged['acceptanceCriterionKeys'] = sorted({key for task in original['tasks'] for key in task['acceptanceCriterionKeys']})
    merged['evidenceIds'] = sorted({key for task in original['tasks'] for key in task['evidenceIds']})
    replacement = {'tasks':[merged]}
    result = replace_owner_decisions('TASK',original,review,replacement)
    assert owner.verify_task_decision(repaired_packet, result) == ()
    assert 'TASK_AC_STORY_MISMATCH' in {d.code for d in owner.verify_task_decision(packet,result)}
    nodes = list(owner._task_node_bindings(repaired_packet,result))
    task = next(node for collection,node in nodes if collection=='tasks')
    assert task['storyId'] == 'story-sit'
    assert task['acceptanceCriterionIds'] == ['ac-empty','ac-success']
    assert task['policyInstanceIds'] == ['policy-sit','policy-uat']
    bad = copy.deepcopy(result);bad['tasks'][0]['acceptanceCriterionKeys'].pop()
    assert 'TASK_STORY_AC_COVERAGE_INCOMPLETE' in {d.code for d in owner.verify_task_decision(repaired_packet,bad)}
    bad = copy.deepcopy(result);bad['tasks'][0]['localKey']='untouched'
    assert 'TASK_AC_STORY_MISMATCH' in {d.code for d in owner.verify_task_decision(repaired_packet,bad)}
    model = json.loads(inputs.story_candidate_bytes)
    for collection,node in nodes: model[collection].append(node)
    from sow_model import validate
    from contracts import load_schema_registry
    registry = load_schema_registry(SKILL_ROOT)
    assert validate(model,'STAGE_3',registry=registry) == ()
    assert owner._task_coverage_diagnostics(model) == ()
    model['stories'][1]['featureId'] = 'feature-unrelated'
    assert 'TASK_AC_STORY_MISMATCH' in {d.code for d in validate(model,'STAGE_3',registry=registry)}


def test_task_repair_shared_asset_materialization_and_replay_preserve_upstream():
    import task_compiler as owner
    inputs = exact_task_inputs(shared_test_asset_model(), {'hld':'HLD'})
    original = {'tasks':[]}
    for phase in ('sit','uat'):
        task = bound_task_ir(task_packet(inputs),target_key='target:policy-'+phase+':story:story-'+phase,work_type='TEST-API')['tasks'][0]
        task['localKey']=phase;original['tasks'].append(task)
    runtime,record = seal_task_work(task_runtime(inputs),original)
    assert record.outcome=='SUCCEEDED'
    first = owner.materialize_task_candidate(*runtime)
    before = json.loads(first.decision_bytes)
    review = {'decision':'REPAIRABLE_SEMANTIC','findings':[{'subjectIds':[row['localKey'] for row in before['tasks']]}]}
    merged = copy.deepcopy(before['tasks'][0])
    for field in ('acceptanceCriterionKeys','evidenceIds'):
        merged[field]=sorted({key for row in before['tasks'] for key in row[field]})
    repair = (review,{'tasks':[merged]})
    material = owner.materialize_task_candidate(*runtime,semantic_repair=repair)
    assert owner.validate_task_candidate(material) == ()
    assert len(json.loads(material.candidate_bytes)['tasks']) == 1
    for collection in ('stories','acceptanceCriteria','inputItems','scopeClosure'):
        assert json.loads(material.candidate_bytes)[collection] == json.loads(first.candidate_bytes)[collection]
    assert owner.materialize_task_candidate(*runtime,semantic_repair=repair) == material
    assert owner.materialize_task_candidate(*runtime) == first


@pytest.mark.unit
@pytest.mark.parametrize('mutation', [None,'no-commitment','unrelated-source','unrelated-target','demo-only'])
def test_task_repair_current_counterpart_candidate_requires_exact_commitment_and_technical_source(mutation):
    import task_compiler as owner
    model = technical_model(integration=True)
    fact = copy.deepcopy(model['inputItems'][0])
    fact.update(inputItemId='input-service',kind='ASSUMPTION',text='客户在项目开始时提供现有订单服务；服务端保持不变。',
        conditions=['项目开始时可用','服务端不修改'],sourceRefs=model['integrations'][0]['sourceRefs'])
    closure = copy.deepcopy(model['scopeClosure'][0])
    closure.update(inputItemId='input-service',sourceRefs=fact['sourceRefs'],disposition='PROJECT_GATE',
        targetNodeIds=['integration-query'],deliveryDisposition='PROJECT_GATE',assignedFeatureIds=[])
    if mutation!='no-commitment': model['inputItems'].append(fact);model['scopeClosure'].append(closure)
    if mutation=='unrelated-source': fact['sourceRefs']=model['inputItems'][1]['sourceRefs'];closure['sourceRefs']=fact['sourceRefs']
    if mutation=='unrelated-target': closure['targetNodeIds']=['feature-unrelated']
    # Projection helper is tested on sealed values; source binding is supplied explicitly.
    candidate,cp,source,revision = task_input_values(model,{'hld':'DEMO' if mutation=='demo-only' else 'HLD'})
    base_inputs = exact_task_inputs(technical_model(integration=True),{'hld':'DEMO' if mutation=='demo-only' else 'HLD'})
    packet = task_packet(base_inputs)
    original = bound_task_ir(packet,target_key='target:integration-query',work_type='IN-INTEGRATION')
    review = {'decision':'REPAIRABLE_SEMANTIC','findings':[{'subjectIds':[original['tasks'][0]['localKey']]}]}
    starts = owner._current_task_start_contexts(packet, json.loads(candidate), json.loads(revision),
        {'target:integration-query'})
    repaired = copy.deepcopy(packet)
    repaired['contextRefs'] += [{'refId':row['evidenceId'],'canonicalContent':row} for row in starts]
    if mutation is None:
        assert len(starts)==1
        assert starts[0]['modes']==['接入复用'] and starts[0]['commitment']==fact
        assert starts[0]['targetKeys']==['target:integration-query']
        assert 'priorStateSha256' not in starts[0]
        task=original['tasks'][0];task['workModeDecision']='接入复用';task['evidenceIds'].append(starts[0]['evidenceId'])
        assert owner._task_start_evidence(task,owner._task_packet_catalog(repaired)[2]) == starts
        task['workModeDecision']='调整'
        assert owner._task_start_evidence(task,owner._task_packet_catalog(repaired)[2]) == []
    else: assert starts == []


def test_task_clarification_extends_local_repair_without_losing_first_shared_asset():
    import task_compiler as owner
    inputs=exact_task_inputs(shared_test_asset_model(),{'hld':'HLD'});original={'tasks':[]}
    for phase in ('sit','uat'):
        task=bound_task_ir(task_packet(inputs),target_key='target:policy-'+phase+':story:story-'+phase,work_type='TEST-API')['tasks'][0]
        task['localKey']=phase;original['tasks'].append(task)
    runtime,_=seal_task_work(task_runtime(inputs),original);first=owner.materialize_task_candidate(*runtime)
    before=json.loads(first.decision_bytes)
    review={'decision':'REPAIRABLE_SEMANTIC','findings':[{'subjectIds':[row['localKey'] for row in before['tasks']]}]}
    merged=copy.deepcopy(before['tasks'][0])
    for field in ('acceptanceCriterionKeys','evidenceIds'): merged[field]=sorted({key for row in before['tasks'] for key in row[field]})
    repair=(review,{'tasks':[merged]})
    second=owner.materialize_task_candidate(*runtime,semantic_repair=repair)
    clarification_review={'decision':'INPUT_REQUIRED','findings':[{'subjectIds':[merged['localKey']]}]}
    resolution={'contract':'ai-sow-owner-clarification-v1','stageKind':'TASK','candidateSha256':second.candidate_sha256,
        'reviewDecisionSha256':sha256_bytes(canonical_json_bytes(clarification_review)),
        'scope':'IMPLEMENTATION_WITHIN_APPROVED_TARGETS','technicalTargetKeys':[merged['technicalTarget']],
        'decision':'同一套已批准查询测试资产在两个验收阶段运行，按一个资产计量。',
        'provenance':'SIMULATED_USER','authorization':'用户已授权模拟技术方案选择。'}
    adjusted=copy.deepcopy(merged);adjusted['deliverableBoundary']='一套查询自动化资产；分别提供两个阶段的运行结果。'
    repairs=[repair,(clarification_review,{'tasks':[adjusted]},resolution)]
    final=owner.materialize_task_candidate(*runtime,semantic_repairs=repairs)
    assert owner.validate_task_candidate(final)==()
    assert len(json.loads(final.candidate_bytes)['tasks'])==1
    assert json.loads(final.candidate_bytes)['stories']==json.loads(first.candidate_bytes)['stories']
    assert owner.materialize_task_candidate(*runtime,semantic_repairs=repairs)==final
    for field,value in [('reviewDecisionSha256','0'*64),('technicalTargetKeys',['target:foreign']),('scope','NEW_COMPONENT')]:
        wrong=copy.deepcopy(resolution);wrong[field]=value
        with pytest.raises(ValueError): owner.materialize_task_candidate(*runtime,semantic_repairs=[repair,(clarification_review,{'tasks':[adjusted]},wrong)])


@pytest.mark.parametrize('suffix',['',':repair:split'])
def test_later_task_repair_cannot_borrow_an_earlier_unrelated_root_ac(suffix):
    import task_compiler as owner
    from final_review import replace_owner_decisions, repair_root_keys
    model=shared_test_asset_model()
    model['policyInstances'].append({**copy.deepcopy(model['policyInstances'][-1]),'policyInstanceId':'policy-other'})
    model['stories'].append({**copy.deepcopy(model['stories'][-1]),'storyId':'story-other','policyRefs':['policy-other']})
    model['acceptanceCriteria'].append({**copy.deepcopy(model['acceptanceCriteria'][-1]),
        'acceptanceCriterionId':'ac-other','storyId':'story-other','policyRefs':['policy-other']})
    inputs=exact_task_inputs(model,{'hld':'HLD'});packet=task_packet(inputs);original={'tasks':[]}
    for phase in ('sit','uat','other'):
        row=bound_task_ir(packet,target_key=f'target:policy-{phase}:story:story-{phase}',work_type='TEST-API')['tasks'][0]
        row['localKey']=phase;original['tasks'].append(row)
    review={'decision':'REPAIRABLE_SEMANTIC','findings':[{'subjectIds':['sit','uat']}]}
    merged=copy.deepcopy(original['tasks'][0])
    for field in ('acceptanceCriterionKeys','evidenceIds'):
        merged[field]=sorted({key for row in original['tasks'][:2] for key in row[field]})
    first_repair=(review,{'tasks':[merged]})
    previous,current=owner.apply_task_repairs(packet,original,[first_repair],inputs)
    assert owner.verify_task_decision(previous,current)==()
    def candidate(source_packet,ir):
        value=json.loads(inputs.story_candidate_bytes)
        for collection,node in owner._task_node_bindings(source_packet,ir):value[collection].append(node)
        for collection in ('tasks','effectiveStartMatches'):value[collection].sort(key=lambda row:row['taskId'])
        return canonical_json_bytes(value)
    first=candidate(packet,original);second=candidate(previous,current)
    later={'decision':'INPUT_REQUIRED','findings':[{'subjectIds':['other']}]}
    resolution={'contract':'ai-sow-owner-clarification-v1','stageKind':'TASK','candidateSha256':sha256_bytes(second),
        'reviewDecisionSha256':sha256_bytes(canonical_json_bytes(later)),
        'scope':'IMPLEMENTATION_WITHIN_APPROVED_TARGETS','technicalTargetKeys':['target:policy-other:story:story-other'],
        'decision':'只澄清 other 的实施方式。','provenance':'SIMULATED_USER','authorization':'测试中的明确授权。'}
    bad=copy.deepcopy(original['tasks'][-1]);bad['localKey']+=suffix
    for field in ('acceptanceCriterionKeys','evidenceIds'):
        bad[field]=sorted(set(bad[field])|set(original['tasks'][1][field]))
    replacement={'tasks':[bad]}
    # The real materialization path must retain the earlier shared asset while
    # rejecting newly borrowed coverage outside this review's affected roots.
    with pytest.raises(ValueError,match='当前修复.*AC'):
        owner.apply_task_repairs(packet,original,[first_repair,(later,replacement,resolution)],inputs)
    # A forged, internally hashed suffix must fail the portable proof replay too.
    final_packet=owner.prepare_task_repair_packet(previous,current,later,
        inputs.story_candidate_bytes,inputs.input_revision_bytes,resolution)
    forged=replace_owner_decisions('TASK',current,later,replacement,resolution)
    final=candidate(final_packet,forged)
    entries=[(sha256_bytes(first),{'ownerIR':original,'ownerPacket':previous,'reviewDecision':review,
        'authorizedRootKeys':repair_root_keys('TASK',original,review)},first_repair[1]),
        (sha256_bytes(second),{'ownerIR':current,'ownerPacket':final_packet,'reviewDecision':later,
        'authorizedRootKeys':['other'],'ownerClarification':resolution},replacement)]
    with pytest.raises(ValueError,match='当前修复.*AC'):
        owner.verify_task_repair_chain(entries,{sha256_bytes(raw):raw for raw in (first,second,final)},
            inputs.input_revision_bytes,original,sha256_bytes(final))
