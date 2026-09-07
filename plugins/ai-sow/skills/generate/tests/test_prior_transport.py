from __future__ import annotations

TEST_LAYER = "integration"

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "tests"))

from contracts import action_provider_request, canonical_json_bytes, sha256_bytes
from test_stage_planner import policy, scope_plan_inputs


def repeated_packet(*, repair=False):
    rows = [{"priorEvidenceId": f"evidence-{index}", "sheet": "合同明细", "absoluteA1Range": f"$A${index}:$C${index}",
             "canonicalCellValues": [{"address": f"A{index}", "value": "交付条件与排除边界", "formula": None,
                                      "cachedValue": None, "cellType": "s"}]} for index in range(160)]
    return canonical_json_bytes({"workItems": [{"workItemId": "item-0", "payload": {
        "priorInputLayout": "ai-sow-prior-row-partition-v1", "evidence": rows, "priorContext": rows}}],
        "contextRefs": [{"refId": "repair", "canonicalContent": {"kind": "ATTEMPT_REPAIR", "rawOutputUtf8": "{}"}}] if repair else []})


FROZEN_REQUEST_SHA256S = {'v1-initial': '20128459aabd2b2bff420b86b2760de7ac63ee261d4d73b83768e58211d7b5b6', 'v1-repair': '858b22d9beb6fb10cf99a3a5866e681e1d535a76e5d0c61c2c08a5f946cee130', 'v2-initial': '50cffa5ca5ed977f0829731c3994f8ad1c80b34fb59ca0dca3f3e077bca37971', 'v2-repair': 'd7a3858246a85cfb6ffacd34ff24889544e29c2f80274e1841816bf79df40b8d'}


@pytest.mark.parametrize("version,repair", [(version, repair) for version in (1, 2) for repair in (False, True)])
def test_legacy_initial_and_repair_requests_keep_exact_bytes(version, repair):
    from stage_planner import run_budget_policy_value
    request = action_provider_request(SKILL_ROOT, f"PRIOR_ANALYZE-v{version}", repeated_packet(repair=repair),
        budget_policy=run_budget_policy_value(policy()), max_output_tokens=8192)
    assert sha256_bytes(request) == FROZEN_REQUEST_SHA256S[f"v{version}-{'repair' if repair else 'initial'}"]


def test_v3_initial_request_is_lossless_and_estimator_counts_actual_request():
    from contracts import estimate_action_input_tokens, action_contract_binding
    from provider_adapter import unpack_lossless_tables
    from stage_planner import run_budget_policy_value
    raw = repeated_packet()
    budget = run_budget_policy_value(policy())
    request = action_provider_request(SKILL_ROOT, "PRIOR_ANALYZE-v3", raw, budget_policy=budget, max_output_tokens=8192)
    packet = json.loads(json.loads(request)["messages"][1]["content"])
    assert packet["transportEncoding"] == "ai-sow-lossless-tables-v1"
    assert unpack_lossless_tables(packet) == raw
    assert len(request) < len(action_provider_request(SKILL_ROOT, "PRIOR_ANALYZE-v2", raw, budget_policy=budget, max_output_tokens=8192))
    assert estimate_action_input_tokens(SKILL_ROOT, "PRIOR_ANALYZE-v3", raw, budget_policy=budget, max_output_tokens=8192) == len(request)
    old, _ = action_contract_binding(SKILL_ROOT, "PRIOR_ANALYZE-v2")
    new, _ = action_contract_binding(SKILL_ROOT, "PRIOR_ANALYZE-v3")
    assert all(new[key] == old[key] for key in ("instruction", "resultSchema", "limits"))


def test_v3_counts_decoding_instruction_before_choosing_compact_transport():
    from contracts import action_contract_binding
    from provider_adapter import canonical_provider_request
    from stage_planner import run_budget_policy_value
    raw = canonical_json_bytes({"workItems": [{"workItemId": "item-0", "payload": {"priorInputLayout": "ai-sow-prior-row-partition-v1",
        "evidence": [{"priorEvidenceId": "evidence-0", "sheet": "合同", "canonicalCellValues": [
            {"address": f"A{index}", "value": "交付", "cellType": "s", "formula": None, "cachedValue": None} for index in range(6)]}]}}], "contextRefs": []})
    contract, _ = action_contract_binding(SKILL_ROOT, "PRIOR_ANALYZE-v3")
    instruction = (SKILL_ROOT / contract["instruction"]["path"]).read_text()
    hydrated = [{"outcome": "HYDRATED", "evidence": [{"refId": "evidence-0", "value": "完整原文"}]}]
    plain = canonical_provider_request("host-canonical-messages-v1", instruction, raw, 8192, hydrated)
    compact = canonical_provider_request("host-canonical-messages-v1", instruction, raw, 8192, hydrated, lossless_tables=True)
    assert json.loads(json.loads(compact)["messages"][1]["content"])["transportEncoding"] == "ai-sow-lossless-tables-v1"
    assert len(compact) > len(plain)
    assert action_provider_request(SKILL_ROOT, "PRIOR_ANALYZE-v3", raw, budget_policy=run_budget_policy_value(policy()),
        max_output_tokens=8192, hydration_responses=iter(hydrated)) == plain


@pytest.mark.parametrize("legacy_version", [1, 2])
def test_frozen_versions_drive_scope_packing_and_independent_plan_validation(legacy_version):
    from contracts import usable_action_input_tokens
    from stage_planner import plan_stage, validate_stage_plan, bound_action_contract_ids, run_budget_policy_value
    from scope_compiler import build_scope_work_descriptors
    items, contexts = scope_plan_inputs(prior_count=2)
    payload = json.loads(repeated_packet())["workItems"][0]["payload"]
    items = [replace(item, work_item_payload={**item.work_item_payload, **payload}) if item.action_kind == "PRIOR_ANALYZE" else item for item in items]
    budget = replace(policy(), model_context_limit_tokens=150000)
    old_ids = {kind: f"{kind}-v{legacy_version}" for kind in ("PRIOR_ANALYZE", "PRIOR_CONSOLIDATE")}
    old_works = build_scope_work_descriptors(items, contexts, budget, action_contract_ids=old_ids)
    old_plan = plan_stage("SCOPE", items, contexts, old_works, [], budget, action_contract_ids=old_ids)
    frozen = bound_action_contract_ids(old_plan)
    assert frozen["PRIOR_ANALYZE"] == f"PRIOR_ANALYZE-v{legacy_version}"
    assert plan_stage("SCOPE", items, contexts, build_scope_work_descriptors(items, contexts, budget, action_contract_ids=frozen), [], budget, action_contract_ids=frozen) == old_plan
    validate_stage_plan(old_plan, items, contexts, old_works, [], budget)
    new_plan = plan_stage("SCOPE", items, contexts, build_scope_work_descriptors(items, contexts, budget), [], budget)
    assert bound_action_contract_ids(new_plan)["PRIOR_ANALYZE"] == "PRIOR_ANALYZE-v3"
    old_leaves = [w for w in old_plan["works"] if w["packetPlan"]["actionKind"] == "PRIOR_ANALYZE"]
    new_leaves = [w for w in new_plan["works"] if w["packetPlan"]["actionKind"] == "PRIOR_ANALYZE"]
    assert len(old_leaves) == 2 and len(new_leaves) == 1
    assert sorted(i["workItemId"] for w in new_plan["works"] for i in w["packetPlan"]["orderedWorkItems"]) == sorted(item.work_item_id for item in items)
    assert usable_action_input_tokens(run_budget_policy_value(budget)) > 0
    for defect in ("kind", "hash", "mixed"):
        changed = copy.deepcopy(old_plan)
        first = next(w["packetPlan"] for w in changed["works"] if w["packetPlan"]["actionKind"] == "PRIOR_ANALYZE")
        if defect == "kind": first["actionKind"] = "SOURCE_SCAN"
        elif defect == "hash": first["actionContractSha256"] = "f" * 64
        else:
            from contracts import action_contract_binding
            first["actionContractId"] = "PRIOR_ANALYZE-v3"
            first["actionContractSha256"] = action_contract_binding(SKILL_ROOT, "PRIOR_ANALYZE-v3")[1]
        with pytest.raises(ValueError): bound_action_contract_ids(changed)


@pytest.mark.parametrize("analyze_version", [2, 3])
def test_public_frozen_prior_analyze_consolidate_hydrate_and_scope_replay(tmp_path, monkeypatch, analyze_version):
    import openpyxl
    import orchestrator
    import stage_planner
    from test_intake import write_next_request
    from test_orchestrator import write_budget_policy, submit_prototype
    from test_scope_compiler import scope_owner_result

    request_path = write_next_request(tmp_path, mode="BROWNFIELD")
    request = json.loads(request_path.read_bytes())
    originals = {}
    for index in range(2):
        path = tmp_path / "inputs" / f"prior-{index}.xlsx"
        book = openpyxl.Workbook()
        book.active.title = "合同"
        book.active.append(["ID", "交付物"])
        book.active.append([f"delivery-{index}", "已有交付" + "x" * 18000])
        book.save(path)
        book.close()
        originals[path] = path.read_bytes()
        request["sources"].append({"sourceId": f"prior-{index}", "role": "PRIOR_SOW", "path": str(path.relative_to(tmp_path)),
                                    "expectedSha256": sha256_bytes(originals[path])})
    request_path.write_bytes(canonical_json_bytes(request))
    original_selector = stage_planner.current_action_contract_id
    with monkeypatch.context() as frozen:
        frozen.setattr(stage_planner, "current_action_contract_id", lambda kind:
                       f"PRIOR_ANALYZE-v{analyze_version}" if kind == "PRIOR_ANALYZE" else original_selector(kind))
        response = orchestrator.run_mode(tmp_path, "start", request=request_path.name,
            budget_policy=write_budget_policy(tmp_path, modelContextLimitTokens=40000, maxPlannedTokens=1000000,
                                             outputReserveTokens=4096, hydrateReserveTokens=1024, safetyMarginTokens=1024))
    assert response["outcome"] == "ACTIVE", response
    plans = tmp_path / ".ai-sow/work/runs" / response["state"]["runId"] / "stages/SCOPE/plans"
    plan_path = next(plans.glob("*.json"))
    frozen_bytes = plan_path.read_bytes()
    response = orchestrator.run_mode(tmp_path, "resume", budget_policy=write_budget_policy(tmp_path,
        modelContextLimitTokens=500000, maxPlannedTokens=1000000, outputReserveTokens=4096, hydrateReserveTokens=1024,
        safetyMarginTokens=1024))
    seen = []
    for _ in range(20):
        assert response["outcome"] == "ACTIVE", response
        for action in response["nextAction"].get("actions", [response["nextAction"]]):
            packet = json.loads((tmp_path / action["packetPath"]).read_bytes())
            kind = action["actionContractId"][:-3]
            seen.append(action["actionContractId"])
            if kind == "SOURCE_SCOPE":
                assert seen.count(f"PRIOR_ANALYZE-v{analyze_version}") == 2
                assert seen.count("PRIOR_CONSOLIDATE-v2") == 1
                assert len(packet["workItems"][0]["payload"]["priorState"]["entities"]) == 2
                assert orchestrator.status(tmp_path)["outcome"] == "ACTIVE"
                assert plan_path.read_bytes() == frozen_bytes
                assert all(path.read_bytes() == raw for path, raw in originals.items())
                return
            if kind == "PRIOR_ANALYZE":
                eid = packet["workItems"][0]["payload"]["evidence"][0]["priorEvidenceId"]
                hydrated = orchestrator.hydrate(tmp_path, action["actionId"], [eid])
                assert hydrated["outcome"] == "HYDRATED", hydrated
                wire = json.loads(orchestrator.read_provider_request(tmp_path, action["actionId"]))
                assert json.loads(wire["messages"][-1]["content"]) == hydrated
            assert submit_prototype(tmp_path, action, scope_owner_result(kind, packet))["record"]["outcome"] == "SUCCEEDED"
        response = orchestrator.run_mode(tmp_path, "resume")
    pytest.fail("未到达 Scope Review")


def test_public_v3_completion_rejects_unbound_business_evidence(tmp_path):
    import orchestrator
    from test_intake import write_next_request
    from test_orchestrator import write_budget_policy, submit_prototype
    from test_scope_compiler import scope_owner_result
    request = write_next_request(tmp_path, mode="BROWNFIELD", include_prior=True)
    response = orchestrator.run_mode(tmp_path, "start", request=request.name, budget_policy=write_budget_policy(tmp_path))
    assert response["outcome"] == "ACTIVE", response
    action = next(action for action in response["nextAction"].get("actions", [response["nextAction"]])
                  if action["actionContractId"] == "PRIOR_ANALYZE-v3")
    packet = json.loads((tmp_path / action["packetPath"]).read_bytes())
    result = scope_owner_result("PRIOR_ANALYZE", packet)
    result["entities"][0]["evidenceIds"] = ["f" * 64]
    completed = submit_prototype(tmp_path, action, result)
    assert completed["record"]["outcome"] == "FAILED"
    assert completed["record"]["failureKind"] == "INVALID_IR"
