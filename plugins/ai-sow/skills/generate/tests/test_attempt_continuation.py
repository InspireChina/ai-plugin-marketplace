"""Finite repair proofs use deterministic synthetic candidates, no native model calls."""
from __future__ import annotations
import copy
import json
import pytest
import sys
from pathlib import Path
TESTS = Path(__file__).parent
for directory in (TESTS, TESTS.parent / "scripts", TESTS.parents[2]):
    if str(directory) not in sys.path: sys.path.insert(0, str(directory))

TEST_LAYER = 'integration'
from test_orchestrator import (orchestrator_module as api, write_run_store_request,
    write_budget_policy, submit_prototype, canonical_json_bytes)
from stage_driver import stage_result


def advance_to_task(project, mode='GREENFIELD'):
    request = write_run_store_request(project)
    if mode == 'BROWNFIELD':
        value = json.loads((project/request).read_bytes())
        value.update(mode=mode, declaredChangeContext={'status':'NO_KNOWN_CHANGES',
            'summary':'本期保留已声明范围。', 'supplementalSourceIds':[]})
        (project/request).write_bytes(canonical_json_bytes(value))
    result = api.run_mode(project, 'start', request=request,
        budget_policy=write_budget_policy(project))
    for _ in range(24):
        assert result['outcome'] == 'ACTIVE', result
        actions = result['nextAction'].get('actions', [result['nextAction']])
        if actions[0]['actionContractId'] in {'TASK-v1', 'TASK-v2'}:
            return actions[0], result['state']
        for action in actions:
            packet = json.loads((project / action['packetPath']).read_bytes())
            assert submit_prototype(project, action, stage_result(action['actionContractId'][:-3], packet))['record']['outcome'] == 'SUCCEEDED'
        result = api.run_mode(project, 'resume')
    pytest.fail('Task not reached')


@pytest.mark.parametrize('violate_scope', [False, True])
def test_task_failed_candidates_pause_and_continue_without_rebuilding_upstream(tmp_path, monkeypatch, violate_scope):
    monkeypatch.setattr(api, '_advance_artifact', lambda files, state: {'outcome':'ACTIVE','state':state,'nextAction':None})
    action, state = advance_to_task(tmp_path, 'BROWNFIELD' if violate_scope else 'GREENFIELD')
    run_root = tmp_path / '.ai-sow/work/runs' / state['runId']
    protected = {p:p.read_bytes() for stage in ('SCOPE','STORY_AC')
        for p in (run_root/'stages'/stage).rglob('*') if p.is_file()}
    checkpoints = copy.deepcopy(state['checkpointRefs'])
    packet = json.loads((tmp_path / action['packetPath']).read_bytes())
    good = stage_result('TASK', packet)
    assert len(good['tasks']) >= 2
    bad = copy.deepcopy(good)
    bad['tasks'][0]['evidenceIds'].append('unbound-first')
    first = submit_prototype(tmp_path, action, bad)['record']
    assert first['failureKind'] == 'INVALID_IR'
    assert first['diagnostic']['findings']
    retry = api.run_mode(tmp_path, 'resume')['nextAction']
    second_bad = copy.deepcopy(bad)
    if violate_scope:
        second_bad['tasks'][1]['workModeDecision'] = '调整'
    else:
        second_bad['tasks'][0]['evidenceIds'][-1] = 'unbound-second'
    second = submit_prototype(tmp_path, retry, second_bad)['record']
    assert second['failureKind'] == 'INVALID_IR'
    if violate_scope: assert second['diagnostic']['code'] == 'REPAIR_SCOPE_VIOLATION'
    paused = api.run_mode(tmp_path, 'resume')
    assert paused['outcome'] == 'WAITING_INPUT', paused
    assert paused['state']['checkpointRefs'] == checkpoints
    issued_before = set((run_root/'actions').iterdir())
    assert api.run_mode(tmp_path, 'resume')['outcome'] == 'WAITING_INPUT'
    assert set((run_root/'actions').iterdir()) == issued_before
    increased = write_budget_policy(tmp_path, maxActionRevisions=3)
    resumed = api.run_mode(tmp_path, 'resume', budget_policy=increased)
    assert resumed['outcome'] == 'ACTIVE', resumed
    third = resumed['nextAction']
    assert (third['logicalWorkId'], third['revision'], third['attempt']) == (action['logicalWorkId'], 3, 1)
    assert api.run_mode(tmp_path, 'resume')['nextAction']['actionId'] == third['actionId']
    assert submit_prototype(tmp_path, third, good)['record']['outcome'] == 'SUCCEEDED'
    fresh = api.run_mode(tmp_path, 'resume')['nextAction']
    assert fresh['actionContractId'] == 'TASK_ESTIMATION-v1'
    review = stage_result('TASK_ESTIMATION', json.loads((tmp_path/fresh['packetPath']).read_bytes()))
    assert submit_prototype(tmp_path, fresh, review)['record']['outcome'] == 'SUCCEEDED'
    completed = api.run_mode(tmp_path, 'resume')
    assert any(cp['kind'] == 'TASK' for cp in completed['state']['checkpointRefs'])
    assert all(p.read_bytes() == raw for p, raw in protected.items())
    records = [json.loads(p.read_bytes()) for p in (run_root/'actions').glob('*/record.json')]
    assert first in records and second in records


@pytest.mark.unit
def test_story_reports_all_located_failures():
    from test_delivery_compiler import story_inputs, story_packet, bound_story_ir
    from delivery_compiler import validate_bound_story_result
    from contracts import InvalidActionResult
    packet = story_packet(story_inputs())
    bad = bound_story_ir(packet)
    bad['stories'][0]['actorKey'] = 'unknown-actor'
    bad['stories'][0]['sourceFactIds'].append('unknown-fact')
    with pytest.raises(InvalidActionResult) as error:
        validate_bound_story_result(packet, canonical_json_bytes(bad))
    diagnostic = error.value.diagnostic
    assert diagnostic.subject_ids == (bad['stories'][0]['localKey'],)
    assert {'STORY_ACTOR_NOT_AUTHORIZED','STORY_FACT_NOT_AUTHORIZED'} <= {item.code for item in diagnostic.findings}


@pytest.mark.unit
def test_schema_invalid_repair_retains_previous_located_candidate():
    from test_action_ledger import prepared_envelope, changed_envelope, successful_completion
    from action_ledger import (ActionLedger, issue, finish, build_attempt_repair_context,
        validate_attempt_repair_context, attempt_record_value)
    from contracts import InvalidActionResult, sha256_bytes
    from models import AttemptCompletion, AttemptDiagnostic, ContextRefDescriptor
    first = prepared_envelope()
    ledger = issue(ActionLedger(), first)
    complete = successful_completion()
    def reject(_):
        raise InvalidActionResult('定位失败', diagnostic=AttemptDiagnostic('LOCATED_INVALID', '/roots/one', ('one',)))
    ledger, original = finish(ledger, first, complete, bound_result_validator=reject)
    second = changed_envelope(first, revision=2, actionId='action-bad-schema')
    ledger = issue(ledger, second)
    ledger, failed = finish(ledger, second, AttemptCompletion(b'{}', None, None, complete.usage, complete.timing))
    digest = sha256_bytes(canonical_json_bytes(attempt_record_value(failed)))
    ref = build_attempt_repair_context(failed.logical_work_id, digest, ledger.attempt_records,
        ledger.raw_outputs, envelopes_by_sha256=ledger.envelopes_by_sha256)
    value = json.loads(ref.canonical_content)
    assert value['rawOutputUtf8'] == '{}'
    assert value['preservationBase']['rawOutputUtf8'].encode() == complete.raw_output
    assert value['preservationBase']['attemptRecordSha256'] == sha256_bytes(canonical_json_bytes(attempt_record_value(original)))
    validate_attempt_repair_context(ref, failed.logical_work_id, ledger.attempt_records,
        envelopes_by_sha256=ledger.envelopes_by_sha256)
    del value['preservationBase']
    with pytest.raises(ValueError, match='基线'):
        validate_attempt_repair_context(ContextRefDescriptor(ref.ref_id, canonical_json_bytes(value)),
            failed.logical_work_id, ledger.attempt_records, envelopes_by_sha256=ledger.envelopes_by_sha256)


@pytest.mark.unit
def test_missing_ac_diagnostic_authorizes_only_its_story_repair():
    from test_task_compiler import exact_task_inputs, task_packet, bound_task_ir
    from task_compiler import validate_bound_task_result
    from action_ledger import diagnostic_value
    from contracts import InvalidActionResult
    packet = task_packet(exact_task_inputs())
    good = bound_task_ir(packet)
    assert len(good['tasks'][0]['acceptanceCriterionKeys']) > 1
    bad = copy.deepcopy(good)
    missing = bad['tasks'][0]['acceptanceCriterionKeys'].pop()
    with pytest.raises(InvalidActionResult) as error:
        validate_bound_task_result(packet, canonical_json_bytes(bad))
    finding = next(item for item in error.value.diagnostic.findings if item.code == 'TASK_STORY_AC_COVERAGE_INCOMPLETE')
    assert finding.path == '/obligations/' + missing
    assert finding.subject_ids == (good['tasks'][0]['storyLocalKey'],)
    packet['contextRefs'].append({'refId':'repair-from-attempt-test','canonicalContent':{
        'rawOutputUtf8':canonical_json_bytes(bad).decode(),'diagnostic':diagnostic_value(error.value.diagnostic)}})
    validate_bound_task_result(packet, canonical_json_bytes(good))


@pytest.mark.unit
def test_repair_key_prefix_does_not_authorize_an_unrelated_object():
    from candidate_repair import preserve_roots
    from contracts import InvalidActionResult
    before = {'tasks':[{'localKey':'broken','field':'old'},{'localKey':'protected','field':'valid'}]}
    after = copy.deepcopy(before)
    after['tasks'].append({'localKey':'broken:repair:unrelated','field':'unauthorized'})
    with pytest.raises(InvalidActionResult) as error:
        preserve_roots(before, after, 'tasks', {'broken'})
    assert error.value.diagnostic.code == 'REPAIR_SCOPE_VIOLATION'


@pytest.mark.parametrize('abandoned', [False, True])
def test_interrupted_execution_retains_attempts_and_never_revives_abandoned_run(tmp_path, abandoned):
    started = api.run_mode(tmp_path, 'start', request=write_run_store_request(tmp_path),
        budget_policy=write_budget_policy(tmp_path))
    first = started['nextAction'].get('actions', [started['nextAction']])[0]
    submit_prototype(tmp_path, first, None, 'EXECUTION')
    resumed = api.run_mode(tmp_path, 'resume')['nextAction']
    actions = resumed.get('actions', [resumed])
    second = next(action for action in actions if action['logicalWorkId'] == first['logicalWorkId'])
    assert second['attempt'] == 2
    submit_prototype(tmp_path, second, None, 'EXECUTION')
    assert api.run_mode(tmp_path, 'resume')['outcome'] == 'WAITING_INPUT'
    root = tmp_path / '.ai-sow/work/runs' / first['runId']
    old = {p:p.read_bytes() for p in (root/'actions').rglob('*') if p.is_file()}
    if abandoned:
        assert api.abandon(tmp_path)['outcome'] == 'ABANDONED'
        result = api.run_mode(tmp_path, 'resume', budget_policy=write_budget_policy(tmp_path, maxExecutionAttempts=3))
        assert result['outcome'] != 'ACTIVE'
    else:
        result = api.run_mode(tmp_path, 'resume', budget_policy=write_budget_policy(tmp_path, maxExecutionAttempts=3))
        next_action = result['nextAction']
        third = next(action for action in next_action.get('actions', [next_action])
            if action['logicalWorkId'] == first['logicalWorkId'])
        assert (third['revision'], third['attempt']) == (1, 3)
        assert third['packetSha256'] == first['packetSha256']
    assert all(p.read_bytes() == raw for p, raw in old.items())


@pytest.mark.parametrize('oversize', [False, True])
def test_repair_capacity_uses_actual_hydration_limit_and_keeps_prior_wait(tmp_path, monkeypatch, oversize):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path, modelContextLimitTokens=80000,
        outputReserveTokens=2048, hydrateReserveTokens=65536, safetyMarginTokens=1024)
    started = api.run_mode(tmp_path, 'start', request=request, budget_policy=budget)
    assert started['outcome'] == 'ACTIVE', started
    action = started['nextAction']
    hydrate_limit = action['executionLimits']['maxHydrateTokens']
    assert hydrate_limit < 65536
    raw = b'{' + b'x' * (180000 if oversize else 30000)
    (tmp_path / action['resultPath']).write_bytes(raw)
    from test_orchestrator import execution_facts, write_json
    write_json(tmp_path / 'execution.json', execution_facts())
    # Preserve a wait created by the older conservative gate, then resume it.
    original_capacity = api.usable_action_input_tokens
    with monkeypatch.context() as old_gate:
        old_gate.setattr(api, 'usable_action_input_tokens', lambda policy, **kwargs: original_capacity(policy))
        waiting = api.run_mode(tmp_path, 'submit', action_id=action['actionId'],
            result=action['resultPath'], execution='execution.json')
    assert waiting['outcome'] == 'WAITING_INPUT', waiting
    root = tmp_path / '.ai-sow/work/runs' / action['runId']
    protected = {p:p.read_bytes() for name in ('actions','budget-policies','stages')
        for p in (root/name).rglob('*') if p.is_file()}
    resumed = api.run_mode(tmp_path, 'resume')
    assert all(p.read_bytes() == raw for p,raw in protected.items())
    assert resumed['state']['runId'] == action['runId']
    if oversize:
        assert resumed['outcome'] == 'WAITING_INPUT', resumed
        details = resumed['diagnostics'][0]['details']
        assert details['usableInputTokens'] == 80000 - 2048 - hydrate_limit - 1024
        assert len(list((root/'actions').glob('*/envelope.json'))) == 1
    else:
        assert resumed['outcome'] == 'ACTIVE', resumed
        retry = resumed['nextAction']
        assert retry['budgetPolicySha256'] == action['budgetPolicySha256']
        assert (retry['logicalWorkId'], retry['revision'], retry['attempt']) == (action['logicalWorkId'],2,1)
        policy = json.loads((tmp_path/budget).read_bytes())
        assert retry['executionLimits']['estimatedInputTokens'] > original_capacity(policy)
        assert api.read_provider_request(tmp_path, retry['actionId'])
        assert api.run_mode(tmp_path, 'resume')['nextAction']['actionId'] == retry['actionId']
