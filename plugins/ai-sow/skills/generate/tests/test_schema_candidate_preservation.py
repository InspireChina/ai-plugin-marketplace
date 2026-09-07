"""A malformed first candidate must not discard valid sibling objects."""
from __future__ import annotations
import copy
import json
import sys
from pathlib import Path
import pytest
TEST_LAYER = 'unit'
ROOT = Path(__file__).parents[1]
for directory in (ROOT/'scripts', ROOT/'tests', ROOT.parents[1]):
    if str(directory) not in sys.path: sys.path.insert(0,str(directory))
from contracts import InvalidActionResult, canonical_json_bytes, normalize_action_result, action_contract_binding
from action_ledger import diagnostic_value
from test_task_compiler import exact_task_inputs, task_packet, bound_task_ir
from contracts import sha256_bytes
import candidate_repair
from test_candidate_repair_protocol import field_case, proposal, verify_title


def test_first_schema_invalid_candidate_preserves_valid_task():
    packet = task_packet(exact_task_inputs()); good = bound_task_ir(packet)
    good['tasks'].append({**copy.deepcopy(good['tasks'][0]), 'localKey':'unrelated-task'})
    bad = copy.deepcopy(good); del bad['tasks'][0]['evidenceIds']
    envelope = {'actionContractId':'TASK-v1','actionContractSha256':action_contract_binding(ROOT,'TASK-v1')[1]}
    with pytest.raises(InvalidActionResult) as error:
        normalize_action_result(envelope,canonical_json_bytes(bad),skill_root=ROOT)
    packet['contextRefs'].append({'refId':'repair-from-attempt-schema', 'canonicalContent':{
        'rawOutputUtf8':canonical_json_bytes(bad).decode(), 'diagnostic':diagnostic_value(error.value.diagnostic)}})
    normalize_action_result(envelope,canonical_json_bytes(good),skill_root=ROOT,packet_payload=canonical_json_bytes(packet))
    changed = copy.deepcopy(good); changed['tasks'][1]['deliverableBoundary'] += ' 无关改写'
    with pytest.raises(InvalidActionResult) as protected:
        normalize_action_result(envelope,canonical_json_bytes(changed),skill_root=ROOT,packet_payload=canonical_json_bytes(packet))
    assert protected.value.diagnostic.code == 'REPAIR_SCOPE_VIOLATION'


def test_root_schema_error_does_not_authorize_unrelated_collection_addition():
    from contracts import preserve_schema_candidate
    good = {'scenarios':[{'scenarioId':'one','name':'original'}]}
    bad = {**copy.deepcopy(good),'unknownProperty':True}
    packet = {'contextRefs':[{'refId':'repair-from-attempt-schema','canonicalContent':{
        'rawOutputUtf8':canonical_json_bytes(bad).decode(), 'diagnostic':{
            'code':'INVALID_IR','path':'','subjectIds':[], 'findings':[
                {'code':'ACTION_RESULT_SCHEMA_INVALID','path':'','subjectIds':[]}]}}}]}
    preserve_schema_candidate(packet,'PROTOTYPE_SCENARIO-v1',good)
    changed=copy.deepcopy(good);changed['scenarios'].append({'scenarioId':'two','name':'unrelated'})
    with pytest.raises(InvalidActionResult): preserve_schema_candidate(packet,'PROTOTYPE_SCENARIO-v1',changed)


def test_root_schema_failure_is_kept_across_invalid_json():
    from dataclasses import replace
    from test_action_ledger import prepared_envelope, successful_completion, changed_envelope
    from action_ledger import ActionLedger, issue, finish, _preservation_base_record
    from models import AttemptDiagnostic, AttemptCompletion
    first=changed_envelope(prepared_envelope(), actionContractId='TASK-v1',
        actionContractSha256=action_contract_binding(ROOT,'TASK-v1')[1])
    ledger=issue(ActionLedger(),first); completion=successful_completion()
    bad=bound_task_ir(task_packet(exact_task_inputs()));bad['unknownProperty']=True
    ledger, record=finish(ledger,first,replace(completion,raw_output=canonical_json_bytes(bad)))
    assert record.diagnostic.code=='INVALID_IR'
    assert any(finding.path=='' for finding in record.diagnostic.findings)
    interrupted=replace(record,revision=2,failure_kind='INVALID_JSON',diagnostic=AttemptDiagnostic('INVALID_JSON','',()))
    base=_preservation_base_record(interrupted,ledger.attempt_records)
    assert base is not None and base[1]==record


def test_parseable_invalid_candidate_uses_slots_and_preserves_valid_fragments():
    base, report, groups, origin = field_case()
    plan = candidate_repair.build_repair_plan(base, report, groups, origin=origin)
    before = canonical_json_bytes(copy.deepcopy(json.loads(base)['tasks'][1]))
    merged, receipt = candidate_repair.apply_repair_patch(
        base, plan, proposal(plan), group_id='fix-t1', verify_group=verify_title)
    after = canonical_json_bytes(json.loads(merged)['tasks'][1])
    assert after == before
    assert json.loads(receipt)['objectIndex']


def test_invalid_json_cannot_replace_receipt_bound_protection_baseline():
    base, report, groups, origin = field_case()
    plan = candidate_repair.build_repair_plan(base, report, groups, origin=origin)
    merged, receipt = candidate_repair.apply_repair_patch(
        base, plan, proposal(plan), group_id='fix-t1', verify_group=verify_title)
    protected_sha256 = sha256_bytes(merged)
    protected_index = json.loads(receipt)['objectIndex']
    with pytest.raises(InvalidActionResult):
        candidate_repair.build_repair_plan(
            b'{"tasks":', {**report, 'candidateSha256': sha256_bytes(b'{"tasks":')},
            groups, origin={**origin, 'repairRound': 3,
                'previousReceiptSha256': sha256_bytes(receipt)})
    assert sha256_bytes(merged) == protected_sha256
    assert json.loads(receipt)['objectIndex'] == protected_index
