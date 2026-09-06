from __future__ import annotations

TEST_LAYER = "integration"

import copy
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).parents[1]
FIXTURES = SKILL_ROOT / "fixtures"
SCRIPTS = SKILL_ROOT / "scripts"
TESTS = SKILL_ROOT / "tests"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402

import pytest
from delivery_compiler import derive_story_obligations
from ir_samples import story_ac_ir


@pytest.mark.unit
def test_story_ac_ir_contract_exact_fields_and_nonempty_observable_rules():
    from contracts import action_contract_binding, validate_action_result
    _, digest = action_contract_binding(SKILL_ROOT, "STORY_AC-v1")
    envelope = {"actionContractId": "STORY_AC-v1", "actionContractSha256": digest}
    valid = story_ac_ir()
    assert validate_action_result(envelope, valid, skill_root=SKILL_ROOT) == ()
    for field in ("featureRef", "featureId", "storyId", "node", "sourceRefs", "sha256", "replacementSet"):
        bad = copy.deepcopy(valid)
        bad["stories"][0][field] = "forbidden"
        assert validate_action_result(envelope, bad, skill_root=SKILL_ROOT), field
    for field in ("condition", "observableResult"):
        for invalid in (None, "", "  "):
            bad = copy.deepcopy(valid)
            if invalid is None:
                del bad["stories"][0]["acceptanceCriteria"][0][field]
            else:
                bad["stories"][0]["acceptanceCriteria"][0][field] = invalid
            assert validate_action_result(envelope, bad, skill_root=SKILL_ROOT)


# Narrow IR Owner tests use pure Scope data, never execute the legacy pipeline.
def story_inputs(model=None):
    import delivery_compiler as owner
    from ir_samples import story_scope_model
    from sow_model import owner_projection_sha256
    model = story_scope_model() if model is None else model
    candidate = canonical_json_bytes(model)
    from test_contracts import checkpoint_value
    checkpoint = {**checkpoint_value('SCOPE'), 'candidateSha256': sha256_bytes(candidate),
        'inputRevisionSha256': model['project']['inputRevisionSha256']}

    cp = canonical_json_bytes(checkpoint)
    return owner.prepare_story_inputs(candidate, cp, checkpoint_sha256=sha256_bytes(cp))


def story_packet(inputs):
    return {'workItems': [{'workItemId': item.work_item_id, 'payload': item.work_item_payload}
                          for item in inputs.work_items],
            'contextRefs': [{'refId': ref.ref_id, 'canonicalContent': json.loads(ref.canonical_content),
                             'contentSha256': sha256_bytes(ref.canonical_content)} for ref in inputs.context_refs]}


def bound_story_ir(packet):
    result = story_ac_ir()
    story = result['stories'][0]
    story['scopeDecisionKeys'] = [item['payload']['scopeDecisionKey'] for item in packet['workItems']]
    story['sourceFactIds'] = sorted({key for item in packet['workItems'] for key in item['payload']['obligation']['sourceFactIds']})
    story['actorKey'] = story['sourceFactIds'][0]
    for criterion, key in zip(story['acceptanceCriteria'], story['sourceFactIds']):
        criterion['sourceFactIds'] = [key]
    return result


@pytest.mark.unit
def test_story_ac_input_boundary_requires_hash_bound_sealed_scope_and_stable_plan():
    import delivery_compiler as owner
    from stage_planner import plan_stage, materialize_packet
    from test_stage_planner import policy
    from action_ledger import ActionLedger
    inputs = story_inputs()
    descriptors = owner.build_story_work_descriptors(inputs.work_items, inputs.context_refs, policy())
    upstream = [inputs.checkpoint_sha256]
    plan = plan_stage('STORY_AC', inputs.work_items, inputs.context_refs, descriptors, upstream, policy())
    permuted = owner.build_story_work_descriptors(inputs.work_items[::-1], inputs.context_refs[::-1], policy())
    assert plan == plan_stage('STORY_AC', inputs.work_items[::-1], inputs.context_refs[::-1], permuted, upstream, policy())
    assert [(item.source_role, item.source_sha256, item.block_ordinal) for item in inputs.work_items] == [
        ('SCOPE_CHECKPOINT', inputs.checkpoint_sha256, i) for i in range(2)]
    assert all(work['packetPlan']['dependencyLogicalWorkIds'] == [] for work in plan['works'])
    packet = json.loads(materialize_packet(plan, plan['works'][0]['logicalWorkId'], 1,
        inputs.work_items, inputs.context_refs, [], ActionLedger()))
    assert set(packet) == {'workItems', 'contextRefs'}
    encoded = json.dumps(packet)
    assert all(token not in encoded for token in ('workbook', 'canonicalCellValues', 'rawContent', '.xlsx', 'replacementSet'))
    locked = json.loads((FIXTURES/'planner/story-ac-plan-hash.json').read_bytes())
    assert sha256_bytes(canonical_json_bytes(plan)) == locked['stagePlanSha256']
    for mutation in ('unsealed', 'candidate', 'checkpoint'):
        candidate, cp = inputs.scope_candidate_bytes, json.loads(inputs.checkpoint_bytes)
        if mutation == 'unsealed': cp.pop('reviewDecisionSha256')
        if mutation == 'candidate': candidate = candidate.replace(b'orders', b'changed')
        cp_bytes = canonical_json_bytes(cp)
        with pytest.raises(ValueError):
            owner.prepare_story_inputs(candidate, cp_bytes,
                checkpoint_sha256='0'*64 if mutation == 'checkpoint' else sha256_bytes(cp_bytes))


@pytest.mark.unit
def test_story_ac_obligation_closure_rejects_missing_duplicate_conflicting_or_unbound_rules():
    import delivery_compiler as owner
    packet = story_packet(story_inputs())
    result = bound_story_ir(packet)
    assert owner.verify_story_ac_decision(packet, result) == ()
    for mutation, expected in [('missing', 'STORY_OBLIGATION_UNCLOSED'), ('duplicate', 'STORY_RULE_DUPLICATE'),
            ('conflict', 'STORY_RULE_CONTRADICTORY'), ('foreign', 'STORY_FACT_NOT_AUTHORIZED'),
            ('actor', 'STORY_ACTOR_NOT_AUTHORIZED'), ('local', 'STORY_LOCAL_KEY_DUPLICATE')]:
        bad = copy.deepcopy(result)
        story = bad['stories'][0]
        if mutation == 'missing': story['scopeDecisionKeys'].pop()
        if mutation in {'duplicate', 'conflict'}:
            rule = copy.deepcopy(story['acceptanceCriteria'][0]); rule['localKey'] = 'another'
            if mutation == 'conflict': rule['observableResult'] = '拒绝查询'
            story['acceptanceCriteria'].append(rule)
        if mutation == 'foreign': story['acceptanceCriteria'][0]['sourceFactIds'] = ['fact:unknown']
        if mutation == 'actor': story['actorKey'] = 'unknown'
        if mutation == 'local': story['acceptanceCriteria'][1]['localKey'] = story['acceptanceCriteria'][0]['localKey']
        assert expected in {d.code for d in owner.verify_story_ac_decision(packet, bad)}, mutation


@pytest.mark.unit
def test_story_ac_obligation_closure_preserves_qualifiers_and_explicit_scope_exclusions():
    import delivery_compiler as owner
    from ir_samples import story_scope_model
    model = story_scope_model()
    excluded = copy.deepcopy(model['inputItems'][0]); excluded['inputItemId'] = 'input-excluded'
    model['inputItems'].append(excluded)
    closure = copy.deepcopy(model['scopeClosure'][0]); closure.update(inputItemId='input-excluded', disposition='OUT_OF_SCOPE',
        targetNodeIds=[], assignedFeatureIds=[], deliveryDisposition='NO_DELIVERY')
    model['scopeClosure'].append(closure)
    model['scopeClosure'][0]['preservedQualifiers'] = ['仅管理员']
    packet = story_packet(story_inputs(model))
    assert len(packet['workItems']) == 2
    result = bound_story_ir(packet)
    assert 'STORY_QUALIFIER_MISSING' in {d.code for d in owner.verify_story_ac_decision(packet, result)}
    result['stories'][0]['acceptanceCriteria'][0]['condition'] += '且仅管理员'
    assert owner.verify_story_ac_decision(packet, result) == ()
    result['stories'][0]['sourceFactIds'].append('fact:input-excluded')
    assert 'STORY_FACT_NOT_AUTHORIZED' in {d.code for d in owner.verify_story_ac_decision(packet, result)}


def story_runtime(inputs=None, sizing=None):
    from test_stage_planner import policy
    from stage_planner import plan_stage
    from action_ledger import ActionLedger
    import delivery_compiler as owner
    inputs = inputs or story_inputs()
    sizing = sizing or policy()
    descriptors = owner.build_story_work_descriptors(inputs.work_items, inputs.context_refs, sizing)
    plan = plan_stage('STORY_AC', inputs.work_items, inputs.context_refs, descriptors, [inputs.checkpoint_sha256], sizing)
    return inputs, plan, ActionLedger(), sizing


def seal_story_work(runtime, result=None, *, revision=1, attempt=1, completion=None, work_index=0):
    import delivery_compiler as owner
    from test_stage_planner import envelope_for_plan
    from stage_planner import materialize_packet, run_budget_policy_value
    from action_ledger import issue, finish, build_attempt_repair_context
    from test_action_ledger import successful_completion
    from contracts import estimate_action_input_tokens
    from models import ActionEnvelope
    inputs, plan, ledger, sizing = runtime
    work = plan['works'][work_index]
    logical_id = work['logicalWorkId']
    repair = None
    if revision == 2:
        failed = next(digest for digest, record in ledger.attempt_records.items() if record.failure_kind == 'INVALID_IR')
        repair = build_attempt_repair_context(logical_id, failed, ledger.attempt_records, ledger.raw_outputs,
            envelopes_by_sha256=ledger.envelopes_by_sha256)
    payload = materialize_packet(plan, logical_id, revision, inputs.work_items, inputs.context_refs, [], ledger, repair)
    packet = json.loads(payload)
    value = {**envelope_for_plan(plan, logical_id).value, 'runId': 'run-story',
        'inputRevisionSha256': json.loads(inputs.scope_candidate_bytes)['project']['inputRevisionSha256'],
        'baseCandidateSha256': sha256_bytes(inputs.scope_candidate_bytes),
        'packetSha256': sha256_bytes(payload), 'revision': revision, 'attempt': attempt}
    value['actionId'] += '-r'+str(revision)+'-a'+str(attempt)
    value['executionLimits'] = {'estimatedInputTokens': estimate_action_input_tokens(SKILL_ROOT,'STORY_AC-v1',payload,
        budget_policy=run_budget_policy_value(sizing), max_output_tokens=sizing.output_reserve_tokens),
        'maxOutputTokens': sizing.output_reserve_tokens,'maxHydrateTokens': sizing.hydrate_reserve_tokens}
    envelope = ActionEnvelope(value, 'actions/'+value['actionId']+'/envelope.json',sha256_bytes(canonical_json_bytes(value)))
    owner.validate_bound_story_context(packet)
    ledger, record = finish(issue(ledger, envelope), envelope,
        completion or successful_completion(canonical_json_bytes(result if result is not None else bound_story_ir(packet))),
        bound_result_validator=lambda raw: owner.validate_bound_story_result(packet, raw))
    return (inputs, plan, ledger, sizing), record


def test_story_ac_materialize_once_per_revision_complete_ledger_stable_ids_and_immutable_files(tmp_path):
    import delivery_compiler as owner
    from runtime.project_io import ProjectFiles
    runtime = story_runtime()
    with pytest.raises(owner.StoryInputRequired):
        owner.materialize_story_candidate(*runtime)
    runtime, record = seal_story_work(runtime)
    assert record.outcome == 'SUCCEEDED'
    material = owner.materialize_story_candidate(*runtime)
    assert owner.validate_story_candidate(material) == ()
    model = json.loads(material.candidate_bytes)
    scope = json.loads(runtime[0].scope_candidate_bytes)
    for collection in scope:
        if collection not in {'stories','acceptanceCriteria','deliveryAnnotations'}:
            assert model[collection] == scope[collection]
    assert len(model['stories']) == 1 and len(model['acceptanceCriteria']) == 2
    story = model['stories'][0]
    assert story['featureId'] == 'feature-query' and story['sourceRefs']
    assert all(ac['storyId'] == story['storyId'] and ac['sourceRefs'] for ac in model['acceptanceCriteria'])
    assert owner.materialize_story_candidate(*runtime).candidate_bytes == material.candidate_bytes
    renamed = bound_story_ir(story_packet(runtime[0])); renamed['stories'][0]['localKey'] = 'polished'
    renamed['stories'][0]['deliverableOutcome'] += '并查看查询结果'
    renamed['stories'][0]['acceptanceCriteria'].reverse()
    repaired, _ = seal_story_work(story_runtime(runtime[0]), renamed)
    changed = owner.materialize_story_candidate(*repaired)
    revised = json.loads(changed.candidate_bytes)
    assert revised['stories'][0]['storyId'] == story['storyId']
    assert {ac['acceptanceCriterionId'] for ac in revised['acceptanceCriteria']} == {ac['acceptanceCriterionId'] for ac in model['acceptanceCriteria']}
    assert changed.candidate_bytes != material.candidate_bytes
    files = ProjectFiles.open(tmp_path)
    published = owner.publish_story_candidate(files, 'run-story', material)
    path = tmp_path / '.ai-sow/work/runs/run-story/stages/STORY_AC/candidates' / (published['candidateSha256']+'.json')
    before = path.stat().st_mtime_ns
    assert owner.publish_story_candidate(files,'run-story',material) == published
    assert path.stat().st_mtime_ns == before
    owner.publish_story_candidate(files,'run-story',changed)
    assert path.read_bytes() == material.candidate_bytes
    assert len(list(path.parent.glob('*.json'))) == 2


def test_story_ac_materialize_once_per_revision_recovers_invalid_ir_repair_and_rejects_tampering():
    import delivery_compiler as owner
    from dataclasses import replace
    runtime, failed = seal_story_work(story_runtime(), {'stories': []})
    assert failed.failure_kind == 'INVALID_IR'
    with pytest.raises(owner.StoryInputRequired): owner.materialize_story_candidate(*runtime)
    runtime, record = seal_story_work(runtime, revision=2)
    assert record.outcome == 'SUCCEEDED'
    material = owner.materialize_story_candidate(*runtime)
    assert owner.validate_story_candidate(material) == ()
    assert owner.materialize_story_candidate(*runtime).candidate_bytes == material.candidate_bytes
    inputs, plan, ledger, sizing = runtime
    poisoned = dict(ledger.normalized_results)
    poisoned[record.normalized_result_sha256] = b'{}\n'
    with pytest.raises(ValueError):
        owner.materialize_story_candidate(inputs, plan, replace(ledger,normalized_results=poisoned), sizing)
    altered = copy.deepcopy(plan); altered['upstreamCheckpointSha256s'] = ['0'*64]
    with pytest.raises(ValueError): owner.materialize_story_candidate(inputs,altered,ledger,sizing)


def test_story_ac_materialize_once_per_revision_reports_source_identity_collisions():
    import delivery_compiler as owner
    runtime = story_runtime()
    result = bound_story_ir(story_packet(runtime[0]))
    result['stories'][0]['acceptanceCriteria'].append({
        'localKey':'unsupported-second-identity', 'condition':'再次查询', 'observableResult':'显示另一结果',
        'sourceFactIds':['fact:input-a']})
    runtime, record = seal_story_work(runtime,result)
    assert record.outcome == 'SUCCEEDED'
    with pytest.raises(owner.StoryInputRequired,match='身份'):
        owner.materialize_story_candidate(*runtime)


def test_story_ac_obligation_closure_preseal_callback_reads_no_files(monkeypatch):
    import delivery_compiler as owner
    callback = owner.validate_bound_story_result
    def guarded(packet, normalized):
        def forbidden(*args, **kwargs): raise AssertionError('callback performed I/O')
        with monkeypatch.context() as guard:
            guard.setattr(Path, 'open', forbidden)
            callback(packet, normalized)
    monkeypatch.setattr(owner, 'validate_bound_story_result', guarded)
    good, succeeded = seal_story_work(story_runtime())
    assert succeeded.outcome == 'SUCCEEDED'
    assert succeeded.normalized_result_sha256 in good[2].normalized_results
    bad, failed = seal_story_work(story_runtime(), {'stories': []})
    assert failed.failure_kind == 'INVALID_IR'
    assert failed.normalized_result_sha256 is None and not bad[2].normalized_results


@pytest.mark.unit
def test_story_ac_materialize_once_per_revision_notes_do_not_depend_on_story_order():
    from story_notes import model_story_note_projection
    model = {'stories':[{'storyId':'story-z','featureId':'feature-a'},{'storyId':'story-a','featureId':'feature-a'}],
        'scopeAnnotations':[{'annotationId':'note-z','text':'范围说明','subjectIds':['feature-a']},
                            {'annotationId':'note-a','text':'另一说明','subjectIds':['feature-a']}]}
    first = model_story_note_projection(model)
    model['stories'].reverse(); model['scopeAnnotations'].reverse()
    assert model_story_note_projection(model) == first


@pytest.mark.unit
def test_story_ac_input_boundary_atomic_metadata_cannot_be_caller_selected():
    import delivery_compiler as owner
    from test_stage_planner import policy
    from dataclasses import replace
    inputs = story_inputs()
    for mutation in ({'source_sha256':'0'*64}, {'block_ordinal':99}):
        bad = (replace(inputs.work_items[0],**mutation), *inputs.work_items[1:])
        with pytest.raises(ValueError): owner.build_story_work_descriptors(bad,inputs.context_refs,policy())


@pytest.mark.unit
def test_story_ac_input_boundary_only_associated_facts_enter_each_packed_request():
    import delivery_compiler as owner
    from ir_samples import story_scope_model
    from test_stage_planner import policy
    from stage_planner import materialize_packet,plan_stage,StagePlanningBlocked
    from action_ledger import ActionLedger
    from dataclasses import replace
    model = story_scope_model()
    # Two independent Features, each individually small enough; all facts do not fit.
    model['features'].append({**copy.deepcopy(model['features'][0]),'featureId':'feature-other','name':'其他查询'})
    model['features'][0]['requirementRefs'] = ['input-a']
    model['features'][1]['requirementRefs'] = ['input-b']
    model['scopeClosure'][1].update(assignedFeatureIds=['feature-other'],targetNodeIds=['feature-other'])
    for fact in model['inputItems']: fact['text'] += '界'*4000
    inputs = story_inputs(model)
    sizing = replace(policy(),model_context_limit_tokens=36000)
    descriptors = owner.build_story_work_descriptors(inputs.work_items,inputs.context_refs,sizing)
    assert len(descriptors) == 2
    plan = plan_stage('STORY_AC',inputs.work_items,inputs.context_refs,descriptors,[inputs.checkpoint_sha256],sizing)
    for work in plan['works']:
        packet = json.loads(materialize_packet(plan,work['logicalWorkId'],1,inputs.work_items,inputs.context_refs,[],ActionLedger()))
        facts = [ref['canonicalContent']['factKey'] for ref in packet['contextRefs']
                 if ref['canonicalContent']['kind'] == 'STORY_SOURCE_FACT']
        assert len(facts) == 1
    with pytest.raises(StagePlanningBlocked):
        owner.build_story_work_descriptors(inputs.work_items,inputs.context_refs,replace(sizing,model_context_limit_tokens=14000))


@pytest.mark.unit
def test_story_ac_obligation_closure_covers_every_cross_feature_target_without_merging():
    import delivery_compiler as owner
    from ir_samples import story_scope_model
    model = story_scope_model()
    model['features'].append({**copy.deepcopy(model['features'][0]),'featureId':'feature-other','name':'其他查询'})
    for closure in model['scopeClosure']:
        closure['assignedFeatureIds'] = ['feature-query','feature-other']
        closure['targetNodeIds'] = ['feature-query','feature-other']
    packet = story_packet(story_inputs(model))
    result = bound_story_ir(packet)
    assert 'INDEPENDENT_STORY_BOUNDARIES_MERGED' in {d.code for d in owner.verify_story_ac_decision(packet,result)}
    result['stories'] = []
    for feature in ('feature-query','feature-other'):
        story = bound_story_ir(packet)['stories'][0]; story['localKey'] = feature
        story['scopeDecisionKeys'] = [item['payload']['scopeDecisionKey'] for item in packet['workItems']
                                     if item['payload']['obligation']['featureId'] == feature]
        result['stories'].append(story)
    assert owner.verify_story_ac_decision(packet,result) == ()
    result['stories'].pop()
    assert 'STORY_OBLIGATION_UNCLOSED' in {d.code for d in owner.verify_story_ac_decision(packet,result)}


@pytest.mark.unit
@pytest.mark.parametrize('independent', [False, True])
def test_shared_scope_constraint_uses_projected_feature_boundary_without_losing_independence(independent):
    import delivery_compiler as owner
    from ir_samples import story_scope_model
    model=story_scope_model()
    model['features'].append({**copy.deepcopy(model['features'][0]),'featureId':'feature-other',
        'name':'另一业务交易','requirementRefs':['input-b']})
    model['inputItems'][1]['kind']='CONSTRAINT'
    model['scopeClosure'][1].update(assignedFeatureIds=['feature-query','feature-other'],
        targetNodeIds=['feature-query','feature-other'],
        preservedQualifiers=['独立验收边界'] if independent else [])
    packet=story_packet(story_inputs(model))
    query=[item for item in packet['workItems'] if item['payload']['obligation']['featureId']=='feature-query']
    assert len({item['payload']['obligation']['storyBoundaryKey'] for item in query})==(2 if independent else 1)
    result={'stories':[]}
    for feature in ('feature-query','feature-other'):
        subset={**packet,'workItems':[item for item in packet['workItems']
            if item['payload']['obligation']['featureId']==feature]}
        story=bound_story_ir(subset)['stories'][0];story['localKey']=feature
        story['acceptanceCriteria']=story['acceptanceCriteria'][:len(story['sourceFactIds'])]
        if independent:
            for ac in story['acceptanceCriteria']:
                if 'fact:input-b' in ac['sourceFactIds']: ac['condition']+='；独立验收边界'
        result['stories'].append(story)
    codes={d.code for d in owner.verify_story_ac_decision(packet,result)}
    assert codes==({'INDEPENDENT_STORY_BOUNDARIES_MERGED'} if independent else set())
    merged=bound_story_ir(packet)
    assert 'INDEPENDENT_STORY_BOUNDARIES_MERGED' in {d.code for d in owner.verify_story_ac_decision(packet,merged)}


def test_story_ac_materialize_once_per_revision_validation_detects_unbound_candidate_and_context():
    import delivery_compiler as owner
    from dataclasses import replace
    runtime, _ = seal_story_work(story_runtime())
    material = owner.materialize_story_candidate(*runtime)
    model = json.loads(material.candidate_bytes)
    model['stories'][0]['name'] = '未由 IR 生成的结果'
    assert owner.validate_story_candidate(replace(material,candidate_bytes=canonical_json_bytes(model)))
    forged = replace(runtime[0],checkpoint_sha256='0'*64)
    with pytest.raises(ValueError): owner.materialize_story_candidate(forged,*runtime[1:])


@pytest.mark.unit
def test_story_ac_obligation_closure_epic_policy_targets_its_concrete_features():
    from ir_samples import story_scope_model
    import delivery_compiler as owner
    model = story_scope_model()
    model['policyInstances'] = [{'policyInstanceId':'policy-go-live', 'policyId':'policy-go-live',
        'targetNodeIds':['epic-orders'], 'inclusionPolicy':'REQUIRED',
        'sourceRefs':copy.deepcopy(model['inputItems'][0]['sourceRefs'])}]
    packet = story_packet(story_inputs(model))
    assert len(packet['workItems']) == 3
    result = bound_story_ir(packet)
    assert 'INDEPENDENT_STORY_BOUNDARIES_MERGED' in {
        diagnostic.code for diagnostic in owner.verify_story_ac_decision(packet, result)}
    policy = next(row['payload'] for row in packet['workItems']
                  if row['payload']['obligation']['kind'] == 'DELIVERY_POLICY')
    assert policy['obligation']['featureId'] == 'feature-query'
    result['stories'][0]['scopeDecisionKeys'].remove(policy['scopeDecisionKey'])
    fact_keys = policy['obligation']['sourceFactIds']
    result['stories'].append({
        'localKey': 'release', 'scopeDecisionKeys': [policy['scopeDecisionKey']],
        'actorKey': fact_keys[0], 'sourceFactIds': fact_keys,
        'deliverableOutcome': '完成上线工程化交付',
        'acceptanceCriteria': [{'localKey': 'release-ready', 'condition': '运行上线脚本时',
                                'observableResult': '部署与回退可验证', 'sourceFactIds': fact_keys}]})
    assert owner.verify_story_ac_decision(packet,result) == ()


def test_story_ac_materialize_once_per_revision_execution_retry_preserves_candidate():
    import delivery_compiler as owner
    from models import AttemptCompletion,AttemptDiagnostic
    from test_action_ledger import successful_completion
    base = successful_completion()
    failed = AttemptCompletion(None,'EXECUTION',AttemptDiagnostic('TIMEOUT','',()),base.usage,base.timing)
    runtime, record = seal_story_work(story_runtime(),completion=failed)
    assert record.failure_kind == 'EXECUTION'
    runtime, record = seal_story_work(runtime,attempt=2)
    assert record.outcome == 'SUCCEEDED'
    normal, _ = seal_story_work(story_runtime(runtime[0]))
    assert owner.materialize_story_candidate(*runtime).candidate_bytes == owner.materialize_story_candidate(*normal).candidate_bytes


def test_story_ac_materialize_once_per_revision_waits_for_siblings_and_preserves_order():
    import delivery_compiler as owner
    from ir_samples import story_scope_model
    from test_stage_planner import policy
    from dataclasses import replace
    model = story_scope_model()
    for key, original in zip(('c','d'),list(model['inputItems'])):
        fact = copy.deepcopy(original); fact['inputItemId'] = 'input-'+key
        fact['sourceRefs'][0].update(blockId='block-'+key,sha256=key*64,locator='paragraph:'+key)
        model['inputItems'].append(fact)
    for key, original in zip(('c','d'),list(model['scopeClosure'])):
        closure = copy.deepcopy(original); closure.update(inputItemId='input-'+key,
            assignedFeatureIds=['feature-other'], targetNodeIds=['feature-other'])
        closure['sourceRefs'] = copy.deepcopy(next(f for f in model['inputItems'] if f['inputItemId']=='input-'+key)['sourceRefs'])
        model['scopeClosure'].append(closure)
    model['features'].append({**copy.deepcopy(model['features'][0]),'featureId':'feature-other',
        'name':'其他查询','requirementRefs':['input-c','input-d']})
    for fact in model['inputItems']: fact['text'] += '界'*4000
    inputs = story_inputs(model); sizing = replace(policy(),model_context_limit_tokens=48000)
    runtime = story_runtime(inputs,sizing)
    assert len(runtime[1]['works']) == 2
    runtime,_ = seal_story_work(runtime,work_index=1)
    with pytest.raises(owner.StoryInputRequired): owner.materialize_story_candidate(*runtime)
    runtime,_ = seal_story_work(runtime,work_index=0)
    material = owner.materialize_story_candidate(*runtime)
    assert owner.validate_story_candidate(material) == ()
    normal,_ = seal_story_work(story_runtime(inputs,sizing),work_index=0)
    normal,_ = seal_story_work(normal,work_index=1)
    assert owner.materialize_story_candidate(*normal).candidate_bytes == material.candidate_bytes


@pytest.mark.parametrize('policy_id,expected', [('policy-sit-automation',False),('policy-go-live',False),
    ('policy-uat-automation',True),('policy-data-migration',True)])
def test_story_ac_materialize_once_per_revision_derives_policy_uat_applicability(policy_id,expected):
    import delivery_compiler as owner
    from ir_samples import story_scope_model
    model = story_scope_model()
    model['policyInstances'] = [{'policyInstanceId':'instance-policy','policyId':policy_id,
        'targetNodeIds':['feature-query'],'inclusionPolicy': ('SOURCE_GATED' if policy_id=='policy-data-migration'
            else 'REQUIRED' if policy_id=='policy-go-live' else 'DEFAULT_INCLUDED'),
        'sourceRefs':[ref for fact in model['inputItems'] for ref in copy.deepcopy(fact['sourceRefs'])]}]
    inputs = story_inputs(model); packet = story_packet(inputs)
    business, policy_story = [bound_story_ir(packet)['stories'][0] for _ in range(2)]
    business['scopeDecisionKeys'] = [item['payload']['scopeDecisionKey'] for item in packet['workItems']
        if item['payload']['obligation']['kind']=='REQUIREMENT']
    policy_story['scopeDecisionKeys'] = [item['payload']['scopeDecisionKey'] for item in packet['workItems']
        if item['payload']['obligation']['kind']=='DELIVERY_POLICY']
    policy_story.update(localKey='policy',deliverableOutcome='完成政策工程化交付')
    for criterion in policy_story['acceptanceCriteria']: criterion['condition'] += '并运行工程化脚本'
    runtime,record = seal_story_work(story_runtime(inputs),{'stories':[business,policy_story]})
    assert record.outcome == 'SUCCEEDED'
    material = owner.materialize_story_candidate(*runtime)
    assert owner.validate_story_candidate(material) == ()
    policy_node = next(story for story in json.loads(material.candidate_bytes)['stories'] if story['policyRefs'])
    assert policy_node['uatApplicable'] is expected


@pytest.mark.unit
def test_story_ac_input_boundary_filters_feature_designs_coverage_and_source_gated_facts():
    from ir_samples import story_scope_model
    model = story_scope_model()
    other = {**copy.deepcopy(model['features'][0]),'featureId':'feature-other','name':'其他查询','designRefs':['design-other']}
    model['features'][0]['designRefs'] = ['design-query']; model['features'].append(other)
    for name in ('query','other'):
        model['designItems'].append({'designItemId':'design-'+name,'name':'查询设计'+name,'featureIds':['feature-'+name],
            'sourceRefs':copy.deepcopy(model['inputItems'][0]['sourceRefs']),'status':'APPROVED'})
    for closure in model['scopeClosure']: closure['assignedFeatureIds'] = ['feature-query','feature-other']
    inputs = story_inputs(model)
    for item in inputs.work_items:
        obligation = item.work_item_payload['obligation']; feature = obligation['featureId']
        assert obligation['designRefs'] == ['design-'+feature.removeprefix('feature-')]
        assert obligation['coverageSet'] == [feature]
    model['policyInstances'] = [{'policyInstanceId':'migration','policyId':'policy-data-migration',
        'targetNodeIds':['feature-query'],'inclusionPolicy':'SOURCE_GATED',
        'sourceRefs':copy.deepcopy(model['inputItems'][1]['sourceRefs'])}]
    inputs = story_inputs(model)
    policy = next(item.work_item_payload['obligation'] for item in inputs.work_items if item.work_item_payload['obligation']['kind']=='DELIVERY_POLICY')
    assert policy['sourceFactIds'] == ['fact:input-b']


@pytest.mark.unit
@pytest.mark.parametrize('merge_kind', ['business-policy', 'distinct-policies'])
def test_story_policy_boundaries_reject_mixed_or_distinct_policy_stories(merge_kind):
    import delivery_compiler as owner
    from ir_samples import story_scope_model
    from stage_driver import stage_result
    model = story_scope_model()
    model['policyInstances'] = [
        {'policyInstanceId': 'instance-'+suffix, 'policyId': 'policy-'+suffix,
         'targetNodeIds': ['feature-query'], 'inclusionPolicy': 'DEFAULT_INCLUDED',
         'sourceRefs': [ref for fact in model['inputItems'] for ref in copy.deepcopy(fact['sourceRefs'])]}
        for suffix in ('sit-automation', 'uat-automation')]
    inputs = story_inputs(model)
    packet = story_packet(inputs)
    valid = stage_result('STORY_AC', packet)
    assert owner.verify_story_ac_decision(packet, valid) == ()
    obligations = {row['payload']['scopeDecisionKey']: row['payload']['obligation'] for row in packet['workItems']}
    policies = [story for story in valid['stories']
                if obligations[story['scopeDecisionKeys'][0]]['kind'] == 'DELIVERY_POLICY']
    business = next(story for story in valid['stories'] if story not in policies)
    selected = [business, policies[0]] if merge_kind == 'business-policy' else policies
    merged = copy.deepcopy(selected[0])
    for field in ('scopeDecisionKeys', 'sourceFactIds'):
        merged[field] = sorted({key for story in selected for key in story[field]})
    merged['acceptanceCriteria'] = [
        {**copy.deepcopy(ac), 'localKey': str(index)+':'+ac['localKey']}
        for index, story in enumerate(selected) for ac in story['acceptanceCriteria']]
    invalid = {'stories': [story for story in valid['stories'] if story not in selected]+[merged]}
    assert 'INDEPENDENT_STORY_BOUNDARIES_MERGED' in {
        diagnostic.code for diagnostic in owner.verify_story_ac_decision(packet, invalid)}
    runtime, failed = seal_story_work(story_runtime(inputs), invalid)
    assert failed.failure_kind == 'INVALID_IR'
    runtime, repaired = seal_story_work(runtime, valid, revision=2)
    assert repaired.outcome == 'SUCCEEDED'
    material = owner.materialize_story_candidate(*runtime)
    assert owner.validate_story_candidate(material) == ()
    assert material.scope_candidate_bytes == inputs.scope_candidate_bytes


def test_story_ac_materialize_once_per_revision_validation_binds_sealed_node_content_even_with_rehashed_candidate():
    import delivery_compiler as owner
    from dataclasses import replace
    runtime,_ = seal_story_work(story_runtime()); material = owner.materialize_story_candidate(*runtime)
    for mutation in ('name','sourceRefs','criterion','annotation'):
        model = json.loads(material.candidate_bytes)
        if mutation=='name': model['stories'][0]['name'] = '外部篡改'
        if mutation=='sourceRefs':
            del model['stories'][0]['sourceRefs']; del model['acceptanceCriteria'][0]['sourceRefs']
        if mutation=='criterion': model['acceptanceCriteria'][0]['text'] = '无条件通过'
        if mutation=='annotation': model['deliveryAnnotations'].append({'annotationId':'unbound','category':'ASSUMPTION',
            'subjectIds':[model['stories'][0]['storyId']],'text':'未授权假设'})
        candidate = canonical_json_bytes(model)
        assert owner.validate_story_candidate(replace(material,candidate_bytes=candidate,candidate_sha256=sha256_bytes(candidate))),mutation


def test_single_observable_criterion_closes_complete_story_without_padding():
    import delivery_compiler as owner
    runtime = story_runtime()
    result = bound_story_ir(story_packet(runtime[0]))
    story = result['stories'][0]
    story['acceptanceCriteria'] = [{
        'localKey':'query-result', 'condition':'管理员查询订单时',
        'observableResult':'展示满足查询条件的订单状态。',
        'sourceFactIds':story['sourceFactIds'],
    }]
    runtime, record = seal_story_work(runtime, result)
    assert record.outcome == 'SUCCEEDED'
    material = owner.materialize_story_candidate(*runtime)
    assert owner.validate_story_candidate(material) == ()
    model = json.loads(material.candidate_bytes)
    assert len(model['acceptanceCriteria']) == 1
    assert model['acceptanceCriteria'][0]['requirementRefs'] == model['stories'][0]['requirementRefs']


def shared_release_scope(policy_id='policy-go-live'):
    from ir_samples import story_scope_model
    model = story_scope_model()
    second = {**copy.deepcopy(model['features'][0]), 'featureId': 'feature-second',
              'name': '第二项功能', 'requirementRefs': ['input-b']}
    model['features'][0]['requirementRefs'] = ['input-a']
    model['features'].append(second)
    model['scopeClosure'][1].update(targetNodeIds=['feature-second'], assignedFeatureIds=['feature-second'])
    model['policyInstances'] = [{'policyInstanceId': 'shared-policy', 'policyId': policy_id,
        'targetNodeIds': ['epic-orders'], 'inclusionPolicy': 'REQUIRED' if policy_id=='policy-go-live' else 'DEFAULT_INCLUDED',
        'sourceRefs': [ref for fact in model['inputItems'] for ref in copy.deepcopy(fact['sourceRefs'])]}]
    return model


@pytest.mark.unit
@pytest.mark.parametrize('policy_id', ['policy-go-live', 'policy-sit-automation', 'policy-uat-automation'])
def test_shared_release_obligation_keeps_full_scope_without_per_feature_duplication(policy_id):
    import delivery_compiler as owner
    model = shared_release_scope(policy_id)
    inputs = story_inputs(model)
    policies = [item.work_item_payload['obligation'] for item in inputs.work_items
                if item.work_item_payload['obligation']['kind']=='DELIVERY_POLICY']
    assert len(policies) == (1 if policy_id=='policy-go-live' else 2)
    assert {feature for row in policies for feature in row['coverageSet']} == {'feature-query', 'feature-second'}
    if policy_id=='policy-go-live':
        shared = policies[0]
        assert shared['featureId'] == 'feature-query'
        assert shared['assignedFeatureIds'] == ['feature-query', 'feature-second']
        assert shared['sourceFactIds'] == ['fact:input-a', 'fact:input-b']
        item = next(item for item in inputs.work_items if item.work_item_payload['obligation']==shared)
        refs = owner._story_contexts_for_items([item], inputs.context_refs)
        assert {'feature:feature-query', 'feature:feature-second'} <= {ref.ref_id for ref in refs}
    else:
        assert all(row['assignedFeatureIds']==[row['featureId']] and row['coverageSet']==[row['featureId']] for row in policies)
    permuted = copy.deepcopy(model)
    for field in ('features', 'scopeClosure', 'inputItems', 'policyInstances'):
        permuted[field].reverse()
    assert [item.work_item_payload for item in story_inputs(permuted).work_items] == [item.work_item_payload for item in inputs.work_items]


@pytest.mark.unit
def test_distinct_release_policy_instances_remain_independent():
    model = shared_release_scope()
    first = model['policyInstances'][0]
    first['targetNodeIds'] = ['feature-query']
    model['policyInstances'].append({**copy.deepcopy(first), 'policyInstanceId': 'second-release',
                                     'targetNodeIds': ['feature-second']})
    policies = [item.work_item_payload['obligation'] for item in story_inputs(model).work_items
                if item.work_item_payload['obligation']['kind']=='DELIVERY_POLICY']
    assert len(policies)==2 and len({row['storyBoundaryKey'] for row in policies})==2
    assert {tuple(row['coverageSet']) for row in policies}=={('feature-query',), ('feature-second',)}
