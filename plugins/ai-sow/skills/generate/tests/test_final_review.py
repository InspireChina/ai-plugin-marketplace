from __future__ import annotations

TEST_LAYER = "integration"

import copy
import json
import pytest
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(SKILL_ROOT / 'tests') not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT / 'tests'))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
import orchestrator as orchestrator_module  # noqa: E402
from sow_model import apply_replacement, model_skeleton  # noqa: E402


@pytest.mark.unit
def test_fresh_control_review_exact_ir_identity_and_set_normalization():
    import final_review
    from contracts import normalize_action_result, action_contract_binding, load_schema_registry, validate_contract
    decision = {'decision':'REPAIRABLE_SEMANTIC','findings':[
        {'code':'BOUNDARY','path':'/features','subjectIds':['b','a'],'evidenceIds':['e2','e1'],'message':'需明确验收边界'},
        {'code':'QUALIFIER','path':'/inputItems','subjectIds':['a'],'evidenceIds':['e1'],'message':'保留时间条件'}]}
    raw = canonical_json_bytes(decision)
    import copy
    shuffled=copy.deepcopy(decision)
    shuffled['findings'].reverse()
    shuffled['findings'][1]['subjectIds'].reverse()
    shuffled['findings'][1]['evidenceIds'].reverse()
    _, contract_hash=action_contract_binding(SKILL_ROOT,'SOURCE_SCOPE-v1')
    envelope={'actionContractId':'SOURCE_SCOPE-v1','actionContractSha256':contract_hash}
    normalized=normalize_action_result(envelope,raw,skill_root=SKILL_ROOT)
    assert normalized == normalize_action_result(envelope,canonical_json_bytes(shuffled),skill_root=SKILL_ROOT)
    assert raw != canonical_json_bytes(shuffled)
    _, contract_hash=action_contract_binding(SKILL_ROOT,'SOURCE_SCOPE-v1')
    expected={'stageKind':'SCOPE','actionKind':'REVIEW','candidateSha256':'a'*64,'actionContractSha256':contract_hash}
    logical,group=final_review.control_identity('SCOPE','REVIEW','a'*64,contract_hash)
    assert logical=='logical-'+sha256_bytes(canonical_json_bytes(expected))
    assert group=='control-group-'+sha256_bytes(canonical_json_bytes({'logicalWorkId':logical}))
    for invalid in [{'decision':'PASS','findings':decision['findings']}, {'decision':'OWNER_BUG','findings':[]},
                    {'decision':'SYSTEM','findings':decision['findings']}]:
        assert validate_contract(invalid,'review-repair.schema.json',load_schema_registry(SKILL_ROOT))


@pytest.mark.unit
def test_bounded_semantic_repair_exact_roots_and_lineage_closure():
    import final_review
    original={'tasks':[{'localKey':'a','name':'原始A'},{'localKey':'b','name':'原始B'}]}
    review={'decision':'REPAIRABLE_SEMANTIC','findings':[{'code':'BOUNDARY','path':'/tasks','subjectIds':['a'],
        'evidenceIds':['e'],'message':'明确对象'}]}
    replacement={'tasks':[{'localKey':'a','name':'修正A'}]}
    repaired=final_review.replace_owner_decisions('TASK',original,review,replacement)
    assert repaired=={'tasks':[{'localKey':'a','name':'修正A'},{'localKey':'b','name':'原始B'}]}
    assert original['tasks'][0]['name']=='原始A'
    for invalid in ({'tasks':[]},original,{'tasks':[{'localKey':'unknown'}]}):
        with pytest.raises(ValueError): final_review.replace_owner_decisions('TASK',original,review,invalid)
    assert final_review.review_route({'decision':'PASS','findings':[]},previous_review=review)=='SEAL'
    assert final_review.review_route(review,previous_review=review)=='MANUAL_REVIEW_REQUIRED'
    assert final_review.review_route({'decision':'INPUT_REQUIRED','findings':review['findings']},previous_review=review)=='WAITING_INPUT'


@pytest.mark.unit
def test_checkpoint_deep_binding_exact_required_proof_fields():
    from contracts import load_schema_registry, validate_contract
    value={'stageKind':'SCOPE','inputRevisionSha256':'a'*64,'upstreamCheckpointSha256s':[],
        'stagePlanSha256':'b'*64,'effectiveAttemptRecordSha256s':['c'*64], 'candidateSha256':'d'*64,
        'validatorResultSha256':'e'*64,'reviewPacketSha256':'f'*64,'reviewDecisionSha256':'0'*64}
    registry=load_schema_registry(SKILL_ROOT)
    assert validate_contract(value,'stage-checkpoint.schema.json',registry)==()
    for key in value:
        invalid=dict(value); del invalid[key]
        assert validate_contract(invalid,'stage-checkpoint.schema.json',registry), key
    for extra in ('ownerProjectionSha256','decision','priorStateSha256'):
        invalid={**value,extra:None}
        assert validate_contract(invalid,'stage-checkpoint.schema.json',registry)


@pytest.fixture(scope='module')
def sealed_prior_repair_project(tmp_path_factory):
    from test_intake import write_next_request
    from test_orchestrator import (
        semantic_scope_patch,
        submit_prototype,
        prototype_payload,
        write_budget_policy,
    )
    from test_scope_compiler import scope_owner_result
    from stage_driver import stage_result
    project = tmp_path_factory.mktemp('sealed-prior-repair')
    request = write_next_request(project, mode='BROWNFIELD', include_prior=True)
    response = orchestrator_module.run_mode(project, 'start', request=request.name,
        budget_policy=write_budget_policy(project))
    repaired = False
    for _ in range(40):
        assert response['outcome'] == 'ACTIVE', response
        if response['state']['phase'] == 'DRAFT': return project
        for action in response['nextAction'].get('actions', [response['nextAction']]):
            packet = json.loads((project/action['packetPath']).read_bytes())
            kind = action['actionContractId'][:-3]
            if kind == 'SOURCE_SCOPE' and not repaired:
                body = prototype_payload(project, action)
                key = next(key for key, row in body['ownerIndex'].items() if row['path'].startswith('/features/'))
                result = {'decision': 'REPAIRABLE_SEMANTIC', 'findings': [{'code': 'BOUNDARY', 'path': '/features',
                    'subjectIds': [key], 'evidenceIds': [], 'message': '名称应明确交付结果。'}]}
                repaired = True
            elif kind == 'CANDIDATE_PATCH':
                result = semantic_scope_patch(
                    project, action, key, '已明确的订单交付能力'
                )
            else:
                result = scope_owner_result(kind, packet) if kind.startswith('PRIOR_') else stage_result(kind, packet)
            recorded = submit_prototype(project, action, result)
            assert recorded['record']['outcome'] == 'SUCCEEDED', recorded
        response = orchestrator_module.run_mode(project, 'resume')
    pytest.fail('three-stage Prior/Repair fixture did not seal')


@pytest.mark.parametrize('target', ['plan', 'upstream', 'owner-attempt', 'review-attempt', 'repair-attempt',
    'candidate-one', 'candidate-two', 'validator', 'review-packet', 'review-decision', 'prior-state', 'phantom-repair'])
def test_checkpoint_deep_binding_complete_real_chain(sealed_prior_repair_project, target):
    from final_review import verify_checkpoint_proof
    from runtime.project_io import ProjectFiles
    from test_orchestrator import managed_snapshot
    project = sealed_prior_repair_project
    files = ProjectFiles.open(project)
    state = orchestrator_module.status(project)['state']
    run_root = project/'.ai-sow/work/runs'/state['runId']
    stage = 'STORY_AC' if target == 'upstream' else 'SCOPE'
    root = run_root/'stages'/stage
    def content_map(directory, pattern):
        return {path.stem: path.read_bytes() for path in (root/directory).glob(pattern)}
    checkpoint = json.loads(next((root/'checkpoints').glob('*.json')).read_bytes())
    ledger = orchestrator_module._load_action_ledger(files, state['runId'])
    arguments = dict(revision_bytes=(project/json.loads((project/'.ai-sow/work/active-run.json').read_bytes())['inputRevisionPath']).read_bytes(),
        plan_bytes=next((root/'plans').glob('*.json')).read_bytes(),
        upstream_bytes=[] if stage == 'SCOPE' else [next((run_root/'stages/SCOPE/checkpoints').glob('*.json')).read_bytes()],
        ledger=ledger, candidates=content_map('candidates', '*.json'), validators=content_map('validators', '*/*.json'),
        review_inputs=content_map('review-inputs', '*/*.json'), prior_states=content_map('prior-states', '*.json'),
        packets={item.value['packetSha256']: files.read_bytes(item.value['packetPath']) for item in ledger.envelopes_by_sha256.values()})
    verify_checkpoint_proof(checkpoint, **arguments)
    if target == 'plan': checkpoint['stagePlanSha256'] = '0'*64
    elif target == 'upstream': checkpoint['upstreamCheckpointSha256s'] = ['0'*64]
    elif target.endswith('-attempt'):
        contract = {'owner-attempt': 'SOURCE_SCAN-v1', 'review-attempt': 'SOURCE_SCOPE-v1', 'repair-attempt': 'CANDIDATE_PATCH-v1'}[target]
        digest = next(digest for digest, record in ledger.attempt_records.items()
            if ledger.envelopes_by_sha256[record.envelope_sha256].value['actionContractId'] == contract)
        checkpoint['effectiveAttemptRecordSha256s'].remove(digest)
    elif target.startswith('candidate-'):
        candidates = arguments['candidates']
        digest = checkpoint['candidateSha256'] if target == 'candidate-two' else next(key for key in candidates if key != checkpoint['candidateSha256'])
        candidates[digest] = canonical_json_bytes({'unrelated': True})
    elif target == 'validator': checkpoint['validatorResultSha256'] = '0'*64
    elif target == 'review-packet': checkpoint['reviewPacketSha256'] = '0'*64
    elif target == 'review-decision': checkpoint['reviewDecisionSha256'] = '0'*64
    elif target == 'prior-state': checkpoint['priorStateSha256'] = '0'*64
    else: checkpoint['effectiveAttemptRecordSha256s'].append('0'*64)
    before = managed_snapshot(project)
    with pytest.raises(ValueError): verify_checkpoint_proof(checkpoint, **arguments)
    assert managed_snapshot(project) == before

@pytest.mark.unit
@pytest.mark.parametrize('stage,collection', [('SCOPE','decisions'),('STORY_AC','stories'),('TASK','tasks')])
def test_localized_repair_merges_splits_and_preserves_unaffected_roots(stage, collection):
    from final_review import replace_owner_decisions
    original = {collection: [{'localKey': key, 'name': key} for key in ('a','b','c')]}
    review = {'decision':'REPAIRABLE_SEMANTIC','findings':[{'subjectIds':['a','b']}]}
    assert replace_owner_decisions(stage, original, review, {collection:[{'localKey':'a','name':'合并'}]}) == {
        collection:[{'localKey':'a','name':'合并'},original[collection][2]]}
    children = [{'localKey':'a:repair:left'}, {'localKey':'a:repair:right'}, original[collection][1]]
    result = replace_owner_decisions(stage,original,review,{collection:children})
    assert result[collection][-1] == original[collection][2]
    assert original[collection][0]['name'] == 'a'
    for rows in ([], [{'localKey':'c'}], [{'localKey':'x:repair:left'}],
                 [{'localKey':'a:repair:'}], [{'localKey':'a'},{'localKey':'a'}]):
        with pytest.raises(ValueError): replace_owner_decisions(stage,original,review,{collection:rows})


@pytest.mark.unit
def test_scope_repair_reference_impact_closure_is_explicit_and_transitive():
    from final_review import repair_root_keys, replace_owner_decisions
    original = {'decisions':[
        {'localKey':'epic','relations':[]},
        {'localKey':'feature','relations':[{'targetLocalKeys':['epic']}]},
        {'localKey':'design','relations':[{'targetLocalKeys':['feature']}]},
        {'localKey':'unrelated','relations':[]}]}
    review = {'decision':'REPAIRABLE_SEMANTIC','findings':[{'subjectIds':['epic']}]}
    assert repair_root_keys('SCOPE',original,review) == ['design','epic','feature']
    replacement = {'decisions': original['decisions'][:3]}
    assert replace_owner_decisions('SCOPE',original,review,replacement)['decisions'][-1] == original['decisions'][-1]
    with pytest.raises(ValueError): replace_owner_decisions('SCOPE',original,review,original)


@pytest.mark.unit
@pytest.mark.parametrize('stage,collection', [('SCOPE','decisions'),('STORY_AC','stories'),('TASK','tasks')])
def test_explicit_manual_repair_is_review_bound_and_field_limited(stage, collection):
    from final_review import replace_owner_decisions, review_route
    original={collection:[{'localKey':'a','name':'原名','boundary':'保留'}, {'localKey':'b','name':'正确'}]}
    review={'decision':'REPAIRABLE_SEMANTIC','findings':[{'subjectIds':['a']}]}
    answer={'contract':'ai-sow-owner-repair-authorization-v1','runId':'run-123456abcdef',
        'stageKind':stage,'candidateSha256':'a'*64,'terminalStateSha256':'b'*64,
        'reviewDecisionSha256':sha256_bytes(canonical_json_bytes(review)),
        'rootKeys':['a'],'allowedFields':['name'],'additionalRevisions':1,
        'decision':'仅修正名称，其他字段保留。','provenance':'SIMULATED_USER','authorization':'已授权技术裁定。'}
    replacement={collection:[{**original[collection][0],'name':'修正名称'}]}
    assert review_route(review,previous_review=review,resolution=answer)=='REPAIR'
    result=replace_owner_decisions(stage,original,review,replacement,answer)
    assert result[collection][1]==original[collection][1]
    for invalid in ({**answer,'reviewDecisionSha256':'c'*64},{**answer,'rootKeys':['b']},
                    {**answer,'allowedFields':['localKey']},{**answer,'additionalRevisions':2}):
        with pytest.raises(ValueError): replace_owner_decisions(stage,original,review,replacement,invalid)
    for rows in ([{**replacement[collection][0],'boundary':'越权修改'}],
                 [{**replacement[collection][0],'localKey':'a:repair:split'}], []):
        with pytest.raises(ValueError): replace_owner_decisions(stage,original,review,{collection:rows},answer)
