from __future__ import annotations

TEST_LAYER = 'integration'

import copy
import json
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(SKILL_ROOT / 'scripts'), str(SKILL_ROOT / 'tests')]

from contracts import action_contract_binding, action_provider_request, canonical_json_bytes, sha256_bytes
from test_stage_planner import policy
from test_task_compiler import exact_task_inputs, task_packet

SELECTED_RULE_IDS = ('ENG-RUNTIME', 'FE-BATCH', 'FE-COMMAND-API', 'FE-EDIT', 'FE-FILE-TRANSFER',
    'FE-QUERY-API', 'FE-VIEW', 'IN-INTEGRATION', 'REL-EXECUTION', 'TEST-API', 'TEST-UI-E2E')


@pytest.mark.unit
@pytest.mark.parametrize('kind,digest', [
    ('TASK-v1', 'b64c9c2ef343f137c48815404fdd17aa74ffea9cba8774a0230cc2e9e6932ba4'),
    ('TASK_REPAIR-v1', '9c10aeb95810ed873014254c3ba7ec0faf9927859a6b01f28a80778a240d5d4c')])
def test_task_v1_request_and_professional_bindings_remain_exact(kind, digest):
    from stage_planner import run_budget_policy_value
    request = action_provider_request(SKILL_ROOT, kind, canonical_json_bytes(task_packet(exact_task_inputs())),
        budget_policy=run_budget_policy_value(policy()), max_output_tokens=8192)
    assert sha256_bytes(request) == digest
    old, _ = action_contract_binding(SKILL_ROOT, kind)
    new, _ = action_contract_binding(SKILL_ROOT, kind[:-1]+'2')
    assert new == {**old, 'actionContractId': kind[:-1]+'2',
        'limits': {**old['limits'], 'maxHydrateTokens': 65536}}


def reach_task(project, monkeypatch, version, *, reserve=65536):
    import orchestrator
    import stage_planner
    from stage_driver import stage_result
    from test_orchestrator import write_run_store_request, write_budget_policy, submit_prototype
    selector = stage_planner.current_action_contract_id
    with monkeypatch.context() as frozen:
        frozen.setattr(stage_planner, 'current_action_contract_id', lambda kind:
            f'TASK-v{version}' if kind == 'TASK' else selector(kind))
        response = orchestrator.run_mode(project, 'start', request=write_run_store_request(project),
            budget_policy=write_budget_policy(project, hydrateReserveTokens=reserve, modelContextLimitTokens=800000))
        for _ in range(30):
            assert response['outcome'] == 'ACTIVE', response
            actions = response['nextAction'].get('actions', [response['nextAction']])
            if actions[0]['actionContractId'] == f'TASK-v{version}': return actions[0]
            for action in actions:
                submit_prototype(project, action, stage_result(action['actionContractId'][:-3],
                    json.loads((project/action['packetPath']).read_bytes())))
            response = orchestrator.run_mode(project, 'resume')
    pytest.fail('Task action was not issued')


@pytest.mark.parametrize('version,expected', [(1, 'BLOCKED'), (2, 'HYDRATED')])
def test_public_complete_rule_hydration(tmp_path, monkeypatch, version, expected):
    import orchestrator
    action = reach_task(tmp_path, monkeypatch, version)
    before = orchestrator.read_provider_request(tmp_path, action['actionId'])
    response = orchestrator.run_mode(tmp_path, 'hydrate', action_id=action['actionId'],
        evidence_ids=['task-rule:'+key for key in SELECTED_RULE_IDS])
    assert response['outcome'] == expected, response
    if expected == 'HYDRATED':
        assert 12000 < len(canonical_json_bytes(response)) <= 65536
        assert set(SELECTED_RULE_IDS) <= {row['workTypeId'] for e in response['evidence'] for row in e['canonicalContent']['rows']}
        request = json.loads(orchestrator.read_provider_request(tmp_path, action['actionId']))
        assert request['messages'][:2] == json.loads(before)['messages']
        assert json.loads(request['messages'][2]['content']) == response
    else:
        assert response['diagnostics'][0]['code'] == 'ACTION_HYDRATION_LIMIT_EXCEEDED'
        assert orchestrator.read_provider_request(tmp_path, action['actionId']) == before
    assert orchestrator.run_mode(tmp_path, 'status')['outcome'] == 'ACTIVE'


@pytest.mark.unit
def test_task_plan_replay_and_repair_version_are_bound_to_frozen_author():
    from final_review import repair_action_contract_id
    from stage_planner import plan_stage, bound_action_contract_ids
    from task_compiler import build_task_work_descriptors
    inputs = exact_task_inputs()
    for version in (1, 2):
        selected = {'TASK': f'TASK-v{version}'}
        works = build_task_work_descriptors(inputs.work_items, inputs.context_refs, policy(), action_contract_ids=selected)
        plan = plan_stage('TASK', inputs.work_items, inputs.context_refs, works, [inputs.checkpoint_sha256], policy(), action_contract_ids=selected)
        assert bound_action_contract_ids(plan) == selected
        assert repair_action_contract_id('TASK', plan) == f'TASK_REPAIR-v{version}'
        assert plan_stage('TASK', inputs.work_items, inputs.context_refs, works, [inputs.checkpoint_sha256], policy(),
            action_contract_ids=bound_action_contract_ids(plan)) == plan
        bad = copy.deepcopy(plan); bad['works'][0]['packetPlan']['actionContractSha256'] = '0'*64
        with pytest.raises(ValueError): repair_action_contract_id('TASK', bad)
    new = plan_stage('TASK', inputs.work_items, inputs.context_refs,
        build_task_work_descriptors(inputs.work_items, inputs.context_refs, policy()), [inputs.checkpoint_sha256], policy())
    assert bound_action_contract_ids(new) == {'TASK': 'TASK-v2'}


def test_hydrate_reserve_increase_preserves_inflight_task_and_retry(tmp_path, monkeypatch):
    import orchestrator
    from test_orchestrator import write_budget_policy, managed_snapshot, submit_prototype
    action = reach_task(tmp_path, monkeypatch, 2, reserve=12000)
    before = managed_snapshot(tmp_path)
    result = orchestrator.run_mode(tmp_path, 'resume', budget_policy=write_budget_policy(tmp_path,
        hydrateReserveTokens=65536, modelContextLimitTokens=800000))
    assert result['outcome'] == 'ACTIVE', result
    after = managed_snapshot(tmp_path)
    assert all(after[path] == raw for path, raw in before.items())
    assert result['nextAction'].get('actions', [result['nextAction']])[0] == action
    response = orchestrator.run_mode(tmp_path, 'hydrate', action_id=action['actionId'],
        evidence_ids=['task-rule:'+key for key in SELECTED_RULE_IDS])
    assert response['outcome'] == 'BLOCKED'
    submit_prototype(tmp_path, action, {'tasks': []})
    retry = orchestrator.run_mode(tmp_path, 'resume')
    assert retry['outcome'] == 'ACTIVE', retry
    next_action = retry['nextAction'].get('actions', [retry['nextAction']])[0]
    assert next_action['revision'] == 2
    assert next_action['executionLimits']['maxHydrateTokens'] == 12000


def test_public_identity_collision_fails_before_seal_and_revises_without_upstream_drift(tmp_path, monkeypatch):
    import orchestrator
    from stage_driver import stage_result
    from test_orchestrator import submit_prototype
    from task_compiler import verify_task_decision
    action = reach_task(tmp_path, monkeypatch, 2)
    packet = json.loads((tmp_path/action['packetPath']).read_bytes())
    original = stage_result('TASK', packet)
    collision = copy.deepcopy(original)
    task = next(copy.deepcopy(row) for row in collision['tasks'] if row['workTypeId']=='FE-VIEW')
    original_key = task['localKey']
    task.update(localKey='other', workTypeId='FE-EDIT', deliverableBoundary='另一个编辑场景')
    collision['tasks'].append(task)
    assert verify_task_decision(packet, collision) == ()
    run_root = tmp_path/'.ai-sow/work/runs'/action['runId']
    upstream = {path:path.read_bytes() for stage in ('SCOPE','STORY_AC') for path in (run_root/'stages'/stage).rglob('*.json')}
    rejected = submit_prototype(tmp_path, action, collision)
    record = rejected['record']
    assert record['outcome']=='FAILED' and record['failureKind']=='INVALID_IR'
    assert record['diagnostic']=={'code':'TASK_IDENTITY_COLLISION','path':'/tasks','subjectIds':sorted([original_key,'other'])}
    assert record['normalizedResultSha256'] is None
    retry = orchestrator.run_mode(tmp_path,'resume')['nextAction']
    retry = retry.get('actions', [retry])[0]
    assert retry['logicalWorkId']==action['logicalWorkId'] and retry['revision']==2
    assert submit_prototype(tmp_path,retry,original)['record']['outcome']=='SUCCEEDED'
    assert all(path.read_bytes()==raw for path,raw in upstream.items())
    response=orchestrator.run_mode(tmp_path,'resume')
    assert response['nextAction']['actionContractId']=='TASK_ESTIMATION-v1'


@pytest.mark.e2e
def test_public_repair_identity_validation_includes_untouched_roots(tmp_path, monkeypatch):
    import orchestrator
    from stage_driver import stage_result
    from test_orchestrator import submit_prototype
    from task_compiler import validate_bound_task_result
    action=reach_task(tmp_path,monkeypatch,2)
    packet=json.loads((tmp_path/action['packetPath']).read_bytes())
    original=stage_result('TASK',packet)
    first=next(row for row in original['tasks'] if row['workTypeId']=='FE-VIEW')
    other={**copy.deepcopy(first),'localKey':'other','workTypeId':'FE-EDIT','evidenceIds':first['evidenceIds'][:1]}
    original['tasks'].append(other)
    validate_bound_task_result(packet,canonical_json_bytes(original))
    assert submit_prototype(tmp_path,action,original)['record']['outcome']=='SUCCEEDED'
    review_action=orchestrator.run_mode(tmp_path,'resume')['nextAction']
    other={**other,'localKey':action['logicalWorkId']+':other'}
    first_key=action['logicalWorkId']+':'+first['localKey']
    finding={'decision':'REPAIRABLE_SEMANTIC','findings':[{'code':'BOUNDARY','path':'/tasks',
        'subjectIds':[other['localKey']],'evidenceIds':[],'message':'明确这一项原有交付边界。'}]}
    assert submit_prototype(tmp_path,review_action,finding)['record']['outcome']=='SUCCEEDED'
    repair=orchestrator.run_mode(tmp_path,'resume')['nextAction']
    assert repair['actionContractId']=='CANDIDATE_PATCH-v1'
    from candidate_repair import patch_context
    view=patch_context(json.loads((tmp_path/repair['packetPath']).read_bytes()))
    slot=view['group']['slots'][0]
    bad={**other,'evidenceIds':first['evidenceIds'],'deliverableBoundary':'与原有交付使用相同完整锚点'}
    bad_patch={'repairPlanSha256':view['repairPlanSha256'],'baseCandidateSha256':view['baseCandidateSha256'],
        'groupId':view['group']['groupId'],'operations':[{'slotId':slot['slotId'],'value':[bad]}]}
    record=submit_prototype(tmp_path,repair,bad_patch)['record']
    assert record['outcome']=='FAILED' and record['failureKind']=='INVALID_IR'
    retry=orchestrator.run_mode(tmp_path,'resume')['nextAction']
    retry_view=patch_context(json.loads((tmp_path/retry['packetPath']).read_bytes()))
    assert retry['actionContractId']=='CANDIDATE_PATCH-v1' and retry['logicalWorkId']!=repair['logicalWorkId']
    fixed={**other,'localKey':retry_view['group']['slots'][0]['outputNamespace']+'fixed',
        'deliverableBoundary':'明确原有编辑场景的验收边界'}
    fixed_patch={'repairPlanSha256':retry_view['repairPlanSha256'],'baseCandidateSha256':retry_view['baseCandidateSha256'],
        'groupId':retry_view['group']['groupId'],'operations':[{
            'slotId':retry_view['group']['slots'][0]['slotId'],'value':[fixed]}]}
    assert submit_prototype(tmp_path,retry,fixed_patch)['record']['outcome']=='SUCCEEDED'
    assert orchestrator.run_mode(tmp_path,'resume')['nextAction']['actionContractId']=='TASK_ESTIMATION-v1'
