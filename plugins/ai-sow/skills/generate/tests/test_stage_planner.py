from __future__ import annotations

TEST_LAYER = "integration"

import sys
import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(SKILL_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT / "tests"))

from stage_planner import AtomicWorkItemDescriptor, DemoBudgetLimits, RunBudgetPolicy, StagePlanningBlocked, DependencyResultRef, make_planned_work, plan_stage, validate_stage_plan, materialize_packet, validate_packet_against_plan, next_issuable_group
from action_ledger import ActionLedger, issue, finish, attempt_record_value, build_attempt_repair_context
from contracts import canonical_json_bytes, sha256_bytes
from models import ActionEnvelope, ContextRefDescriptor


def policy() -> RunBudgetPolicy:
    return RunBudgetPolicy(
        "ai-sow-run-budget-policy-v1", "host-canonical-messages-v1", 128000,
        "utf8-bytes-v1", 1000000, 3600,
        8192, 4096, 1024, 256, 8, DemoBudgetLimits(2, 30, 12),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"max_planned_tokens": 0},
        {"max_active_seconds": 0},
        {"reference_overhead_tokens": 0},
        {"max_concurrency": 9},
        {"model_context_limit_tokens": 13312},
        {"demo_limits": DemoBudgetLimits(0, 1, 1)},
        {"demo_limits": DemoBudgetLimits(1, 0, 1)},
        {"demo_limits": DemoBudgetLimits(1, 1, 0)},
    ],
)
def test_run_budget_policy_typed_value_cannot_bypass_contract(changes):
    with pytest.raises(ValueError):
        replace(policy(), **changes)


def test_stable_stage_plan_packet_work_key_canonicalizes_descriptor_inputs():
    items = [
        AtomicWorkItemDescriptor("item-b", "SOURCE_SCAN", "PRD", "a" * 64, 1, {"text": "乙"}),
        AtomicWorkItemDescriptor("item-a", "SOURCE_SCAN", "PRD", "a" * 64, 0, {"text": "甲"}),
    ]
    contexts = [ContextRefDescriptor("ctx-b", b"{}\n"), ContextRefDescriptor("ctx-a", b"{}\n")]
    work = make_planned_work("SOURCE_SCAN", items, contexts, ["work-b", "work-a"])
    assert work.ordered_work_item_ids == ("item-a", "item-b")
    assert work.context_ref_ids == ("ctx-a", "ctx-b")
    assert work.dependency_work_keys == ("work-a", "work-b")
    assert work.work_key == "work-7107557260402e2c5115eaee7acd9d4e841257b6c2df206ba170f32d687a4507"
    assert work == make_planned_work("SOURCE_SCAN", items[::-1], contexts[::-1], ["work-a", "work-b"])


@pytest.mark.parametrize("mutation", ["item", "context", "dependency", "action_kind"])
def test_stage_plan_closure_topology_work_descriptor_rejects_ambiguous_inputs(mutation):
    items = [AtomicWorkItemDescriptor("item-a", "SOURCE_SCAN", "PRD", "a" * 64, 0, {})]
    contexts = [ContextRefDescriptor("ctx-a", b"{}\n")]
    dependencies = ["work-a"]
    if mutation == "item":
        items.append(replace(items[0], work_item_payload={"different": True}))
    elif mutation == "context":
        contexts.append(ContextRefDescriptor("ctx-a", b'{"different":true}\n'))
    elif mutation == "dependency":
        dependencies.append("work-a")
    else:
        items[0] = replace(items[0], action_kind="STORY_AC")
    with pytest.raises(ValueError):
        make_planned_work("SOURCE_SCAN", items, contexts, dependencies)


def test_stage_plan_closure_topology_freezes_complete_single_work():
    items = [AtomicWorkItemDescriptor("item-a", "SOURCE_SCAN", "PRD", "a" * 64, 0, {"text": "甲"})]
    contexts = [ContextRefDescriptor("ctx-a", b'{"evidence":"one"}\n')]
    work = make_planned_work("SOURCE_SCAN", items, contexts, [])
    plan = plan_stage("SCOPE", items, contexts, [work], ["a" * 64], policy())
    assert set(plan) == {"stageKind", "upstreamCheckpointSha256s", "works", "groups", "budgetPolicySha256"}
    assert plan["stageKind"] == "SCOPE"
    assert plan["upstreamCheckpointSha256s"] == ["a" * 64]
    assert len(plan["works"]) == len(plan["groups"]) == 1
    frozen = plan["works"][0]
    assert set(frozen) == {"logicalWorkId", "packetPlan"}
    assert frozen["packetPlan"]["actionContractId"] == "SOURCE_SCAN-v1"
    assert frozen["packetPlan"]["orderedWorkItems"][0]["workItemId"] == "item-a"
    assert frozen["packetPlan"]["contextRefs"][0]["refId"] == "ctx-a"
    assert frozen["packetPlan"]["dependencyLogicalWorkIds"] == []
    assert plan["groups"][0]["requiredLogicalWorkIds"] == [frozen["logicalWorkId"]]
    validate_stage_plan(plan, items, contexts, [work], ["a" * 64], policy())


@pytest.mark.parametrize("mutation", [
    "duplicate_item", "unreferenced_item", "missing_item", "duplicate_item_ref", "shared_item",
    "duplicate_context", "conflicting_context", "unreferenced_context", "missing_context", "duplicate_context_ref",
    "wrong_work_key", "duplicate_work", "outer_kind", "duplicate_upstream",
])
def test_stage_plan_closure_topology_rejects_incomplete_or_ambiguous_universe(mutation):
    items = [AtomicWorkItemDescriptor("item-a", "SOURCE_SCAN", "PRD", "a" * 64, 0, {})]
    contexts = [ContextRefDescriptor("ctx-a", b"{}\n")]
    works = [make_planned_work("SOURCE_SCAN", items, contexts, [])]
    upstream = ["a" * 64]
    if mutation == "duplicate_item":
        items.append(items[0])
    elif mutation == "unreferenced_item":
        items.append(replace(items[0], work_item_id="item-b"))
    elif mutation == "missing_item":
        items.clear()
    elif mutation == "duplicate_item_ref":
        works[0] = replace(works[0], ordered_work_item_ids=("item-a", "item-a"))
    elif mutation == "shared_item":
        works.append(make_planned_work("SOURCE_SCAN", items, [], []))
    elif mutation == "duplicate_context":
        contexts.append(contexts[0])
    elif mutation == "conflicting_context":
        contexts.append(ContextRefDescriptor("ctx-a", b'{"other":true}\n'))
    elif mutation == "unreferenced_context":
        contexts.append(ContextRefDescriptor("ctx-b", b"{}\n"))
    elif mutation == "missing_context":
        contexts.clear()
    elif mutation == "duplicate_context_ref":
        works[0] = replace(works[0], context_ref_ids=("ctx-a", "ctx-a"))
    elif mutation == "wrong_work_key":
        works[0] = replace(works[0], work_key="work-wrong")
    elif mutation == "duplicate_work":
        works.append(works[0])
    elif mutation == "outer_kind":
        works[0] = replace(works[0], action_kind="STORY_AC")
    else:
        upstream.append(upstream[0])
    with pytest.raises(ValueError):
        plan_stage("SCOPE", items, contexts, works, upstream, policy())


def test_stage_plan_closure_topology_resolves_explicit_dependencies_before_groups():
    items = [AtomicWorkItemDescriptor(f"item-{index}", "SOURCE_SCAN", "PRD", "a" * 64, index, {"index": index}) for index in range(3)]
    left = make_planned_work("SOURCE_SCAN", items[:1], [], [])
    right = make_planned_work("SOURCE_SCAN", items[1:2], [], [])
    child = make_planned_work("SOURCE_SCAN", items[2:], [], [left.work_key, right.work_key])
    descriptors = [child, right, left]
    plan = plan_stage("SCOPE", items, [], descriptors, [], policy())
    assert len(plan["groups"]) == 2
    assert [len(group["requiredLogicalWorkIds"]) for group in plan["groups"]] == [2, 1]
    by_item = {work["packetPlan"]["orderedWorkItems"][0]["workItemId"]: work for work in plan["works"]}
    assert by_item["item-2"]["packetPlan"]["dependencyLogicalWorkIds"] == sorted([by_item["item-0"]["logicalWorkId"], by_item["item-1"]["logicalWorkId"]])
    assert plan["groups"][1]["requiredLogicalWorkIds"] == [by_item["item-2"]["logicalWorkId"]]
    validate_stage_plan(plan, items, [], descriptors, [], policy())


@pytest.mark.parametrize("mutation", ["missing", "self", "cycle"])
def test_stage_plan_closure_topology_rejects_unresolvable_dependencies(mutation):
    item = AtomicWorkItemDescriptor("item-a", "SOURCE_SCAN", "PRD", "a" * 64, 0, {})
    first = make_planned_work("SOURCE_SCAN", [item], [], ["work-missing"])
    works = [first]
    if mutation == "self":
        works = [replace(first, dependency_work_keys=(first.work_key,))]
    elif mutation == "cycle":
        second = make_planned_work("SOURCE_SCAN", [], [], [first.work_key])
        works = [replace(first, dependency_work_keys=(second.work_key,)), second]
    with pytest.raises(ValueError):
        plan_stage("SCOPE", [item], [], works, [], policy())


@pytest.mark.parametrize("mutation", ["missing_group", "duplicate_group", "missing_work", "duplicate_work", "non_early_dependency", "upstream", "policy", "extra_field"])
def test_stage_plan_closure_topology_validator_rejects_plan_drift(mutation):
    items = [AtomicWorkItemDescriptor(f"item-{index}", "SOURCE_SCAN", "PRD", "a" * 64, index, {}) for index in range(2)]
    first = make_planned_work("SOURCE_SCAN", items[:1], [], [])
    second = make_planned_work("SOURCE_SCAN", items[1:], [], [first.work_key])
    works = [first, second]
    plan = copy.deepcopy(plan_stage("SCOPE", items, [], works, ["a" * 64], policy()))
    if mutation == "missing_group":
        plan["groups"].pop()
    elif mutation == "duplicate_group":
        plan["groups"].append(plan["groups"][0])
    elif mutation == "missing_work":
        plan["works"].pop()
    elif mutation == "duplicate_work":
        plan["works"].append(plan["works"][0])
    elif mutation == "non_early_dependency":
        plan["groups"].reverse()
    elif mutation == "upstream":
        plan["upstreamCheckpointSha256s"] = ["b" * 64]
    elif mutation == "policy":
        plan["budgetPolicySha256"] = "b" * 64
    else:
        plan["universeSha256"] = "b" * 64
    with pytest.raises(ValueError):
        validate_stage_plan(plan, items, [], works, ["a" * 64], policy())


def test_stable_stage_plan_packet_materializes_exact_two_collection_encoding():
    items = [AtomicWorkItemDescriptor("item-a", "SOURCE_SCAN", "PRD", "a" * 64, 0, {"text": "甲"})]
    contexts = [ContextRefDescriptor("ctx-a", b"{}\n")]
    work = make_planned_work("SOURCE_SCAN", items, contexts, [])
    plan = plan_stage("SCOPE", items, contexts, [work], [], policy())
    logical_id = plan["works"][0]["logicalWorkId"]
    packet = materialize_packet(plan, logical_id, 1, items, contexts, [], ActionLedger())
    assert json.loads(packet) == {
        "workItems": [{"workItemId": "item-a", "payload": {"text": "甲"}}],
        "contextRefs": [{"refId": "ctx-a", "canonicalContent": {}, "contentSha256": "ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356"}],
    }
    validate_packet_against_plan(plan, logical_id, 1, items, contexts, [], ActionLedger(), packet)
    assert work.work_key == "work-ad8d8e5c9a967c81f9b250e10932c83c0e3b494f475d2f7c727feb783bc40e07"
    assert sha256_bytes(canonical_json_bytes(plan["works"][0]["packetPlan"])) == "0ba9a06f551f24b524c71edaf4859cc25e15a9e22521acec6ae3b4e89a15483d"
    assert logical_id == "logical-23853aebfac8e509aa5fc742168589be68a3207b7cef68871204577cb842dfe8"
    assert plan["groups"][0]["groupId"] == "group-29c353c8488803d351859dc83db03e2fc2270fa80cfb9bb6fc393f2e7693d508"
    assert sha256_bytes(canonical_json_bytes(plan)) == "422ab8af3d8ce9fbe9d73eadf64b0899745743703cf34475018ff1aae3ad1c5d"


def test_stable_stage_plan_packet_compile_rejects_known_base_request_over_capacity():
    items = [AtomicWorkItemDescriptor("item-a", "SOURCE_SCAN", "PRD", "a" * 64, 0, {"text": "甲"})]
    work = make_planned_work("SOURCE_SCAN", items, [], [])
    tiny = replace(policy(), model_context_limit_tokens=13313)
    with pytest.raises(StagePlanningBlocked) as blocked:
        plan_stage("SCOPE", items, [], [work], [], tiny)
    assert blocked.value.reason_code == "BUDGET_EXHAUSTED"


@pytest.mark.parametrize("mutation", ["payload", "context", "extra_item", "extra_context", "duplicate_item", "duplicate_context", "action_kind", "contract_hash", "revision", "repair_missing"])
def test_stable_stage_plan_packet_rejects_base_drift(mutation):
    items = [AtomicWorkItemDescriptor("item-a", "SOURCE_SCAN", "PRD", "a" * 64, 0, {"text": "甲"})]
    contexts = [ContextRefDescriptor("ctx-a", b"{}\n")]
    work = make_planned_work("SOURCE_SCAN", items, contexts, [])
    plan = copy.deepcopy(plan_stage("SCOPE", items, contexts, [work], [], policy()))
    logical_id = plan["works"][0]["logicalWorkId"]
    revision = 1
    if mutation == "payload":
        items[0] = replace(items[0], work_item_payload={"text": "乙"})
    elif mutation == "context":
        contexts[0] = ContextRefDescriptor("ctx-a", b'{"changed":true}\n')
    elif mutation == "extra_item":
        items.append(replace(items[0], work_item_id="item-b"))
    elif mutation == "extra_context":
        contexts.append(ContextRefDescriptor("ctx-b", b"{}\n"))
    elif mutation == "duplicate_item":
        items.append(items[0])
    elif mutation == "duplicate_context":
        contexts.append(contexts[0])
    elif mutation == "action_kind":
        items[0] = replace(items[0], action_kind="STORY_AC")
    elif mutation == "contract_hash":
        plan["works"][0]["packetPlan"]["actionContractSha256"] = "b" * 64
    elif mutation == "revision":
        revision = 0
    else:
        revision = 2
    with pytest.raises(ValueError):
        materialize_packet(plan, logical_id, revision, items, contexts, [], ActionLedger())


@pytest.mark.parametrize("mutation", ["duplicate_json_key", "noncanonical", "context_nan", "payload_nan"])
def test_stable_stage_plan_packet_rejects_noncanonical_or_nonfinite_json(mutation):
    payload = {"value": float("nan")} if mutation == "payload_nan" else {}
    item = AtomicWorkItemDescriptor("item-a", "SOURCE_SCAN", "PRD", "a" * 64, 0, payload)
    content = {"duplicate_json_key": b'{"a":1,"a":2}\n', "noncanonical": b'{ }\n', "context_nan": b'{"value":NaN}\n', "payload_nan": b"{}\n"}[mutation]
    context = ContextRefDescriptor("ctx-a", content)
    work = make_planned_work("SOURCE_SCAN", [item], [context], [])
    with pytest.raises(ValueError):
        plan_stage("SCOPE", [item], [context], [work], [], policy())


def envelope_for_plan(plan, logical_id):
    from test_action_ledger import prepared_envelope

    work = next(work for work in plan["works"] if work["logicalWorkId"] == logical_id)
    packet_plan = work["packetPlan"]
    group = next(group for group in plan["groups"] if logical_id in group["requiredLogicalWorkIds"])
    value = {**prepared_envelope().value, "actionId": "action-" + logical_id[-12:], "logicalWorkId": logical_id, "stageKind": plan["stageKind"], "groupId": group["groupId"], "actionContractId": packet_plan["actionContractId"], "actionContractSha256": packet_plan["actionContractSha256"], "budgetPolicySha256": plan["budgetPolicySha256"]}
    return ActionEnvelope(value, "actions/" + value["actionId"] + "/envelope.json", sha256_bytes(canonical_json_bytes(value)))


def dependency_case():
    from test_action_ledger import successful_completion

    items = [AtomicWorkItemDescriptor(f"item-{index}", "SOURCE_SCAN", "PRD", "a" * 64, index, {"index": index}) for index in range(2)]
    contexts = [ContextRefDescriptor("ctx-base", b"{}\n")]
    parent = make_planned_work("SOURCE_SCAN", items[:1], [], [])
    child = make_planned_work("SOURCE_SCAN", items[1:], contexts, [parent.work_key])
    plan = plan_stage("SCOPE", items, contexts, [child, parent], [], policy())
    parent_id = plan["groups"][0]["requiredLogicalWorkIds"][0]
    child_id = plan["groups"][1]["requiredLogicalWorkIds"][0]
    envelope = envelope_for_plan(plan, parent_id)
    ledger, record = finish(issue(ActionLedger(), envelope), envelope, successful_completion())
    ref = DependencyResultRef(parent_id, sha256_bytes(canonical_json_bytes(attempt_record_value(record))), ledger.normalized_results[record.normalized_result_sha256])
    return plan, child_id, items, contexts, ledger, ref


def test_stable_stage_plan_packet_materializes_verified_dependency_wrapper():
    plan, logical_id, items, contexts, ledger, ref = dependency_case()
    frozen = canonical_json_bytes(plan)
    packet = materialize_packet(plan, logical_id, 1, items, contexts, [ref], ledger)
    value = json.loads(packet)
    assert [context["refId"] for context in value["contextRefs"]] == ["ctx-base", "dependency-result-" + ref.logical_work_id]
    assert value["contextRefs"][1] == {"refId": "dependency-result-" + ref.logical_work_id, "canonicalContent": {"kind": "DEPENDENCY_RESULT", "logicalWorkId": ref.logical_work_id, "attemptRecordSha256": ref.result_sha256, "normalizedResult": json.loads(ref.normalized_result)}}
    assert canonical_json_bytes(plan) == frozen
    validate_packet_against_plan(plan, logical_id, 1, items, contexts, [ref], ledger, packet)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "unknown_record", "bytes", "cross_logical", "superseded", "pending", "latest_pending", "ambiguous_latest"])
def test_stable_stage_plan_packet_dependency_requires_unique_effective_success(mutation):
    plan, logical_id, items, contexts, ledger, ref = dependency_case()
    refs = [ref]
    record = ledger.attempt_records[ref.result_sha256]
    if mutation == "missing":
        refs = []
    elif mutation == "extra":
        refs.append(replace(ref, logical_work_id="logical-extra"))
    elif mutation == "duplicate":
        refs.append(ref)
    elif mutation == "unknown_record":
        refs = [replace(ref, attempt_record_sha256="f" * 64)]
    elif mutation == "bytes":
        refs = [replace(ref, normalized_result=b"{}\n")]
    elif mutation == "cross_logical":
        refs = [replace(ref, logical_work_id=logical_id)]
    elif mutation == "superseded":
        record = replace(record, outcome="SUPERSEDED")
        digest = sha256_bytes(canonical_json_bytes(attempt_record_value(record)))
        ledger = replace(ledger, attempt_records={digest: record})
        refs = [replace(ref, attempt_record_sha256=digest)]
    elif mutation == "pending":
        ledger = replace(ledger, attempt_records={})
    else:
        original = ledger.envelopes_by_sha256[record.envelope_sha256]
        value = {**original.value, "actionId": "action-extra", "attempt": 2 if mutation == "latest_pending" else 1}
        extra = ActionEnvelope(value, "actions/action-extra/envelope.json", sha256_bytes(canonical_json_bytes(value)))
        ledger = replace(ledger, envelopes_by_sha256={**ledger.envelopes_by_sha256, extra.sha256: extra})
        if mutation == "ambiguous_latest":
            another = replace(record, envelope_sha256=extra.sha256)
            ledger = replace(ledger, attempt_records={**ledger.attempt_records, sha256_bytes(canonical_json_bytes(attempt_record_value(another))): another})
    with pytest.raises(ValueError):
        materialize_packet(plan, logical_id, 1, items, contexts, refs, ledger)


def repair_case():
    from test_action_ledger import successful_completion

    plan, logical_id, items, contexts, ledger, dependency = dependency_case()
    envelope = envelope_for_plan(plan, logical_id)
    ledger, record = finish(issue(ledger, envelope), envelope, successful_completion(b"{"))
    digest = sha256_bytes(canonical_json_bytes(attempt_record_value(record)))
    repair = build_attempt_repair_context(logical_id, digest, ledger.attempt_records, ledger.raw_outputs, envelopes_by_sha256=ledger.envelopes_by_sha256)
    return plan, logical_id, items, contexts, ledger, dependency, repair


def test_stable_stage_plan_packet_revision_two_appends_one_verified_repair_without_replanning():
    plan, logical_id, items, contexts, ledger, dependency, repair = repair_case()
    frozen = canonical_json_bytes(plan)
    original = materialize_packet(plan, logical_id, 1, items, contexts, [dependency], ledger)
    repaired = materialize_packet(plan, logical_id, 2, items, contexts, [dependency], ledger, repair)
    assert json.loads(repaired)["workItems"] == json.loads(original)["workItems"]
    assert json.loads(repaired)["contextRefs"] == [*json.loads(original)["contextRefs"], {"refId": repair.ref_id, "canonicalContent": json.loads(repair.canonical_content), "contentSha256": sha256_bytes(repair.canonical_content)}]
    assert repaired != original
    assert canonical_json_bytes(plan) == frozen
    validate_packet_against_plan(plan, logical_id, 2, items, contexts, [dependency], ledger, repaired, repair)


def test_stable_stage_plan_packet_order_and_content_dependency_hash_laws():
    items = [AtomicWorkItemDescriptor(f"item-{index}", "SOURCE_SCAN", "PRD", "a" * 64, index, {"index": index}) for index in range(2)]
    contexts = [ContextRefDescriptor("ctx-b", b'{"b":2}\n'), ContextRefDescriptor("ctx-a", b'{"a":1}\n')]
    left = make_planned_work("SOURCE_SCAN", items[:1], [], [])
    right = make_planned_work("SOURCE_SCAN", items[1:], [], [])
    join = make_planned_work("SCOPE_JOIN", [], contexts, [left.work_key, right.work_key])
    descriptors = [join, right, left]
    upstream = ["b" * 64, "a" * 64]
    plan = plan_stage("SCOPE", items, contexts, descriptors, upstream, policy())
    frozen = canonical_json_bytes(plan)
    assert frozen == canonical_json_bytes(plan_stage("SCOPE", items[::-1], contexts[::-1], descriptors[::-1], upstream[::-1], policy()))
    changed_items = [replace(items[0], work_item_payload={"changed": True}), items[1]]
    changed_payload = plan_stage("SCOPE", changed_items, contexts, descriptors, upstream, policy())
    assert sha256_bytes(canonical_json_bytes(changed_payload)) != sha256_bytes(frozen)
    assert changed_payload["works"][0]["logicalWorkId"] != plan["works"][0]["logicalWorkId"] or changed_payload["works"][1]["logicalWorkId"] != plan["works"][1]["logicalWorkId"]
    changed_join = make_planned_work("SCOPE_JOIN", [], contexts, [left.work_key])
    changed_dependency = plan_stage("SCOPE", items, contexts, [left, right, changed_join], upstream, policy())
    assert changed_dependency["works"][-1]["logicalWorkId"] != plan["works"][-1]["logicalWorkId"]
    assert sha256_bytes(canonical_json_bytes(changed_dependency)) != sha256_bytes(frozen)
    assert plan["works"][-1]["packetPlan"]["orderedWorkItems"] == []
    with pytest.raises(ValueError):
        validate_stage_plan(plan, items, contexts, descriptors, upstream, replace(policy(), max_planned_tokens=2000000))
    validate_stage_plan(plan, items, contexts, descriptors, upstream, policy())
    assert canonical_json_bytes(plan) == frozen


@pytest.mark.parametrize("mutation", ["dependency_collision", "embedded_repair"])
def test_stable_stage_plan_packet_rejects_reserved_context_collision(mutation):
    plan, logical_id, items, contexts, ledger, dependency = dependency_case()
    context = ContextRefDescriptor("dependency-result-" + dependency.logical_work_id, b"{}\n") if mutation == "dependency_collision" else ContextRefDescriptor("ctx-hidden-repair", b'{"kind":"ATTEMPT_REPAIR"}\n')
    first = make_planned_work("SOURCE_SCAN", items[:1], [], [])
    second = make_planned_work("SOURCE_SCAN", items[1:], [context], [first.work_key])
    with pytest.raises(ValueError):
        changed = plan_stage("SCOPE", items, [context], [first, second], [], policy())
        changed_id = changed["groups"][1]["requiredLogicalWorkIds"][0]
        materialize_packet(changed, changed_id, 1, items, [context], [dependency], ledger)


@pytest.mark.parametrize("mutation", ["revision_one", "unknown_record", "cross_logical", "raw_tamper", "extra_overlay", "extra_context", "packet_payload"])
def test_stable_stage_plan_packet_repair_proof_and_exact_packet_reject_changes(mutation):
    plan, logical_id, items, contexts, ledger, dependency, repair = repair_case()
    revision = 2
    if mutation == "revision_one":
        revision = 1
    elif mutation in {"unknown_record", "cross_logical", "raw_tamper"}:
        content = json.loads(repair.canonical_content)
        if mutation == "raw_tamper":
            content["rawOutputUtf8"] = "different"
        else:
            content["attemptRecordSha256"] = "f" * 64 if mutation == "unknown_record" else dependency.result_sha256
        repair = ContextRefDescriptor("repair-from-attempt-" + content["attemptRecordSha256"], canonical_json_bytes(content))
    if mutation in {"revision_one", "unknown_record", "cross_logical", "raw_tamper"}:
        with pytest.raises(ValueError):
            materialize_packet(plan, logical_id, revision, items, contexts, [dependency], ledger, repair)
    else:
        packet = json.loads(materialize_packet(plan, logical_id, revision, items, contexts, [dependency], ledger, repair))
        if mutation == "extra_overlay":
            packet["contextRefs"].append(packet["contextRefs"][-1])
        elif mutation == "extra_context":
            packet["contextRefs"].append({"refId": "extra", "canonicalContent": {}})
        else:
            packet["workItems"][0]["payload"] = {"changed": True}
        with pytest.raises(ValueError):
            validate_packet_against_plan(plan, logical_id, revision, items, contexts, [dependency], ledger, canonical_json_bytes(packet), repair)


def test_stable_stage_plan_packet_host_browser_rejects_revision_two(tmp_path, monkeypatch):
    import shutil
    import stage_planner

    *_, repair = repair_case()
    skill = tmp_path / "skill"
    shutil.copytree(SKILL_ROOT, skill)
    path = skill / "contracts/action-contracts-v1.json"
    registry = json.loads(path.read_bytes())
    registry["contracts"][0]["executionKind"] = "HOST_BROWSER"
    path.write_bytes(canonical_json_bytes(registry))
    monkeypatch.setattr(stage_planner, "SKILL_ROOT", skill)
    item = AtomicWorkItemDescriptor("item-browser", "SOURCE_SCAN", "PRD", "a" * 64, 0, {})
    work = make_planned_work("SOURCE_SCAN", [item], [], [])
    plan = plan_stage("SCOPE", [item], [], [work], [], policy())
    with pytest.raises(ValueError, match="MODEL_PROVIDER"):
        materialize_packet(plan, plan["works"][0]["logicalWorkId"], 2, [item], [], [], ActionLedger(), repair)


def test_stable_stage_plan_packet_repair_rejects_execution_failure_route():
    from models import AttemptCompletion, AttemptDiagnostic

    plan, logical_id, items, contexts, ledger, dependency, repair = repair_case()
    old_hash = json.loads(repair.canonical_content)["attemptRecordSha256"]
    old = ledger.attempt_records[old_hash]
    envelope = ledger.envelopes_by_sha256[old.envelope_sha256]
    pending = replace(ledger, attempt_records={key: record for key, record in ledger.attempt_records.items() if key != old_hash})
    failed, record = finish(pending, envelope, AttemptCompletion(None, "EXECUTION", AttemptDiagnostic("HOST_FAILED", "", ()), old.usage, old.timing))
    digest = sha256_bytes(canonical_json_bytes(attempt_record_value(record)))
    invalid = ContextRefDescriptor("repair-from-attempt-" + digest, canonical_json_bytes({"kind": "ATTEMPT_REPAIR", "attemptRecordSha256": digest, "rawOutputUtf8": "{", "diagnostic": attempt_record_value(record)["diagnostic"]}))
    with pytest.raises(ValueError, match="JSON/IR failure"):
        materialize_packet(plan, logical_id, 2, items, contexts, [dependency], failed, invalid)


def test_stable_stage_plan_packet_registry_versions_never_reselect_frozen_contract(tmp_path, monkeypatch):
    import shutil
    import stage_planner

    skill = tmp_path / "skill"
    shutil.copytree(SKILL_ROOT, skill)
    monkeypatch.setattr(stage_planner, "SKILL_ROOT", skill)
    item = AtomicWorkItemDescriptor("item-a", "SOURCE_SCAN", "PRD", "a" * 64, 0, {})
    work = make_planned_work("SOURCE_SCAN", [item], [], [])
    plan = plan_stage("SCOPE", [item], [], [work], [], policy())
    logical_id = plan["works"][0]["logicalWorkId"]
    packet = materialize_packet(plan, logical_id, 1, [item], [], [], ActionLedger())
    path = skill / "contracts/action-contracts-v1.json"
    registry = json.loads(path.read_bytes())
    second = {**registry["contracts"][0], "actionContractId": "SOURCE_SCAN-v2", "goal": "另一个版本"}
    registry["contracts"].insert(0, second)
    path.write_bytes(canonical_json_bytes(registry))
    assert plan_stage("SCOPE", [item], [], [work], [], policy()) == plan
    assert materialize_packet(plan, logical_id, 1, [item], [], [], ActionLedger()) == packet
    registry["contracts"] = [contract for contract in registry["contracts"] if contract["actionContractId"] != "SOURCE_SCAN-v1"]
    path.write_bytes(canonical_json_bytes(registry))
    with pytest.raises(LookupError):
        plan_stage("SCOPE", [item], [], [work], [], policy())
    with pytest.raises(LookupError):
        materialize_packet(plan, logical_id, 1, [item], [], [], ActionLedger())


def test_unlimited_groups_selects_first_unfinished_without_reissuing_or_mutating():
    from models import AttemptCompletion, AttemptDiagnostic
    from test_action_ledger import successful_completion

    plan, child_id, items, contexts, parent_complete, dependency = dependency_case()
    empty = ActionLedger()
    assert next_issuable_group(plan, empty) == plan["groups"][0]
    assert next_issuable_group(plan, empty) == plan["groups"][0]
    assert empty == ActionLedger()
    parent = envelope_for_plan(plan, dependency.logical_work_id)
    pending = issue(empty, parent)
    assert next_issuable_group(plan, pending) == plan["groups"][0]
    complete = successful_completion()
    failed, _ = finish(pending, parent, AttemptCompletion(None, "EXECUTION", AttemptDiagnostic("HOST_FAILED", "", ()), complete.usage, complete.timing))
    assert next_issuable_group(plan, failed) == plan["groups"][0]
    retry_value = {**parent.value, "actionId": "action-retry", "attempt": 2}
    retry = ActionEnvelope(retry_value, "actions/action-retry/envelope.json", sha256_bytes(canonical_json_bytes(retry_value)))
    done, _ = finish(issue(failed, retry), retry, complete)
    assert next_issuable_group(plan, done) == plan["groups"][1]
    assert next_issuable_group(plan, parent_complete) == plan["groups"][1]
    child = envelope_for_plan(plan, child_id)
    finished, _ = finish(issue(done, child), child, complete)
    assert next_issuable_group(plan, finished) is None


def independent_plan(count, budget=None):
    items = [AtomicWorkItemDescriptor(f"item-{index:03d}", "SOURCE_SCAN", "PRD", "a" * 64, index, {"index": index}) for index in range(count)]
    descriptors = [make_planned_work("SOURCE_SCAN", [item], [], []) for item in items]
    return plan_stage("SCOPE", items, [], descriptors, [], budget or policy()), items, descriptors


@pytest.mark.parametrize("count,group_sizes", [(8, [8]), (9, [8, 1]), (57, [8, 8, 8, 8, 8, 8, 8, 1])])
def test_unlimited_groups_eight_nine_fifty_seven_are_all_reachable(count, group_sizes):
    from test_action_ledger import successful_completion

    plan, items, descriptors = independent_plan(count)
    assert [len(group["requiredLogicalWorkIds"]) for group in plan["groups"]] == group_sizes
    assert len(plan["works"]) == count
    assert len({work["logicalWorkId"] for work in plan["works"]}) == count
    ledger = ActionLedger()
    selected = []
    for expected in plan["groups"]:
        group = next_issuable_group(plan, ledger)
        assert group == expected
        selected.append(group["groupId"])
        for index, logical_id in enumerate(group["requiredLogicalWorkIds"]):
            envelope = envelope_for_plan(plan, logical_id)
            ledger = issue(ledger, envelope)
            assert next_issuable_group(plan, ledger) == expected
            ledger, _ = finish(ledger, envelope, successful_completion())
            if index + 1 < len(group["requiredLogicalWorkIds"]):
                assert next_issuable_group(plan, ledger) == expected
    assert selected == [group["groupId"] for group in plan["groups"]]
    assert next_issuable_group(plan, ledger) is None
    validate_stage_plan(plan, items, [], descriptors, [], policy())
    if count == 57:
        fixture = json.loads((SKILL_ROOT / "fixtures/planner/57-work-plan-hash.json").read_bytes())
        assert fixture["workCount"] == count
        assert fixture["groupSizes"] == group_sizes
        assert sha256_bytes(canonical_json_bytes(plan)) == fixture["stagePlanSha256"]


@pytest.mark.parametrize("count,concurrency", [(73, 3), (97, 8)])
def test_unlimited_groups_generated_property_above_fifty_seven(count, concurrency):
    import random
    from test_action_ledger import successful_completion

    budget = replace(policy(), max_concurrency=concurrency)
    plan, items, descriptors = independent_plan(count, budget)
    random.Random(count).shuffle(items)
    random.Random(concurrency).shuffle(descriptors)
    assert canonical_json_bytes(plan_stage("SCOPE", items, [], descriptors, [], budget)) == canonical_json_bytes(plan)
    required = [logical_id for group in plan["groups"] for logical_id in group["requiredLogicalWorkIds"]]
    assert len(required) == len(set(required)) == count
    assert set(required) == {work["logicalWorkId"] for work in plan["works"]}
    assert all(1 <= len(group["requiredLogicalWorkIds"]) <= concurrency <= 8 for group in plan["groups"])
    ledger = ActionLedger()
    for group in plan["groups"]:
        assert next_issuable_group(plan, ledger) == group
        for logical_id in group["requiredLogicalWorkIds"]:
            envelope = envelope_for_plan(plan, logical_id)
            ledger, _ = finish(issue(ledger, envelope), envelope, successful_completion())
    assert next_issuable_group(plan, ledger) is None


def test_unlimited_groups_refuses_ambiguous_effective_envelope():
    plan, _, _, _, ledger, dependency = dependency_case()
    original = next(iter(ledger.envelopes_by_sha256.values()))
    value = {**original.value, "actionId": "action-conflicting"}
    extra = ActionEnvelope(value, "actions/action-conflicting/envelope.json", sha256_bytes(canonical_json_bytes(value)))
    ambiguous = replace(ledger, envelopes_by_sha256={**ledger.envelopes_by_sha256, extra.sha256: extra})
    with pytest.raises(ValueError, match="唯一"):
        next_issuable_group(plan, ambiguous)


@pytest.mark.parametrize("failure_kind", ["INPUT_REQUIRED", "CONTRACT_GAP", "OWNER_BUG", "SYSTEM"])
def test_unlimited_groups_selection_does_not_authorize_non_retry_failure(failure_kind):
    from models import AttemptCompletion, AttemptDiagnostic
    from test_action_ledger import successful_completion

    plan, *_ = independent_plan(1)
    envelope = envelope_for_plan(plan, plan["works"][0]["logicalWorkId"])
    complete = successful_completion()
    ledger, _ = finish(issue(ActionLedger(), envelope), envelope, AttemptCompletion(None, failure_kind, AttemptDiagnostic("STOP", "", ()), complete.usage, complete.timing))
    assert next_issuable_group(plan, ledger) == plan["groups"][0]
    assert len(ledger.envelopes_by_sha256) == len(ledger.attempt_records) == 1


def scope_plan_inputs(count=1, text_size=20, prior_count=0):
    items, contexts = [], []
    for i in range(count):
        payload = {"coverageRootId": f"block-{i:03}", "sourceRole": "PRD", "evidenceIds": [f"block-{i:03}"],
                   "sourceBlock": {"blockId": f"block-{i:03}", "content": "x" * text_size}}
        item_id = "item-" + sha256_bytes(canonical_json_bytes(payload))
        items.append(AtomicWorkItemDescriptor(item_id, "SOURCE_SCAN", "PRD", "a" * 64, i, payload))
        contexts.append(ContextRefDescriptor("source-" + item_id, canonical_json_bytes({"kind": "SOURCE_BLOCK", **payload})))
    for i in range(prior_count):
        payload = {"sourceId": f"prior-{i}", "evidenceIds": [str(i) * 64], "region": "x" * text_size}
        items.append(AtomicWorkItemDescriptor("item-" + sha256_bytes(canonical_json_bytes(payload)), "PRIOR_ANALYZE", "PRIOR_SOW", str(i) * 64, i, payload))
    contexts.append(ContextRefDescriptor("scope-context", canonical_json_bytes({"kind": "SCOPE_CONTEXT", "responsibilityBoundaries": [{"responsibilityBoundaryId": "boundary-api", "name": "应用接口"}]})))
    if prior_count:
        from prior_state import build_project_effective_start_context
        from test_contracts import valid_input_revision
        contexts.append(build_project_effective_start_context(canonical_json_bytes(valid_input_revision())))
    return items, contexts


def test_scope_owner_plan_topology_direct_synthesis_has_no_empty_prior_work():
    from scope_compiler import build_scope_work_descriptors
    items, contexts = scope_plan_inputs()
    descriptors = build_scope_work_descriptors(items, contexts, policy())
    plan = plan_stage("SCOPE", items, contexts, descriptors, [], policy())
    kinds = {work["packetPlan"]["actionKind"]: work for work in plan["works"]}
    assert set(kinds) == {"SOURCE_SCAN", "SOURCE_AUDIT", "SCOPE_SYNTHESIS"}
    scan_id, audit_id = (kinds[kind]["logicalWorkId"] for kind in ["SOURCE_SCAN", "SOURCE_AUDIT"])
    assert kinds["SOURCE_SCAN"]["packetPlan"]["dependencyLogicalWorkIds"] == []
    assert kinds["SOURCE_AUDIT"]["packetPlan"]["dependencyLogicalWorkIds"] == [scan_id]
    assert set(kinds["SCOPE_SYNTHESIS"]["packetPlan"]["dependencyLogicalWorkIds"]) == {scan_id, audit_id}
    reordered = build_scope_work_descriptors(items[::-1], contexts[::-1], policy())
    assert plan == plan_stage("SCOPE", items[::-1], contexts[::-1], reordered, [], policy())


@pytest.mark.parametrize("prior_count", [0, 7])
def test_scope_owner_plan_topology_57_items_bounded_joins_and_unique_prior_root(prior_count):
    from scope_compiler import build_scope_work_descriptors
    sizing = replace(policy(), model_context_limit_tokens=27000, output_reserve_tokens=4096,
                     hydrate_reserve_tokens=1024, safety_margin_tokens=1024, reference_overhead_tokens=256)
    items, contexts = scope_plan_inputs(57, 12000, prior_count)
    descriptors = build_scope_work_descriptors(items, contexts, sizing)
    plan = plan_stage("SCOPE", items, contexts, descriptors, [], sizing)
    works = {work["logicalWorkId"]: work["packetPlan"] for work in plan["works"]}
    scans = {key for key, packet in works.items() if packet["actionKind"] == "SOURCE_SCAN"}
    audits = {key for key, packet in works.items() if packet["actionKind"] == "SOURCE_AUDIT"}
    assert len(scans) == len(audits) == 57
    assert all(not works[key]["dependencyLogicalWorkIds"] for key in scans)
    for audit in audits:
        assert len(works[audit]["dependencyLogicalWorkIds"]) == 1
        assert set(works[audit]["dependencyLogicalWorkIds"]) <= scans
        assert works[audit]["orderedWorkItems"] == []
    prior = {key for key, packet in works.items() if packet["actionKind"].startswith("PRIOR_")}
    consumed_prior = {dependency for key in prior for dependency in works[key]["dependencyLogicalWorkIds"]}
    roots = prior - consumed_prior
    assert len(roots) == bool(prior_count)
    if prior_count:
        assert sum(works[key]["actionKind"] == "PRIOR_CONSOLIDATE" for key in prior) >= 3
        assert all("PROJECT_EFFECTIVE_START" in {ref["refId"] for ref in works[key]["contextRefs"]} for key in prior)
    for key, packet in works.items():
        if packet["actionKind"] == "SCOPE_PROPOSAL":
            dependencies = set(packet["dependencyLogicalWorkIds"])
            assert roots <= dependencies
            assert dependencies - roots <= scans | audits
            for audit in dependencies & audits:
                assert set(works[audit]["dependencyLogicalWorkIds"]) <= dependencies
    joins = {key for key, packet in works.items() if packet["actionKind"] == "SCOPE_JOIN"}
    assert any(set(works[key]["dependencyLogicalWorkIds"]) & joins for key in joins)
    consumed = {dependency for packet in works.values() for dependency in packet["dependencyLogicalWorkIds"]}
    final = set(works) - consumed
    assert len(final) == 1
    closure = set(final)
    while True:
        expanded = closure | {dep for key in closure for dep in works[key]["dependencyLogicalWorkIds"]}
        if expanded == closure: break
        closure = expanded
    assert closure == set(works)
    assert plan == plan_stage("SCOPE", items[::-1], contexts[::-1],
        build_scope_work_descriptors(items[::-1], contexts[::-1], sizing), [], sizing)


def test_scope_owner_plan_topology_refuses_unaffordable_leaf_and_narrow_fan_in():
    from scope_compiler import build_scope_work_descriptors
    items, contexts = scope_plan_inputs(2, 100)
    narrow = replace(policy(), model_context_limit_tokens=19000)
    with pytest.raises(StagePlanningBlocked) as error:
        build_scope_work_descriptors(items, contexts, narrow)
    assert error.value.reason_code == "BUDGET_EXHAUSTED"
    items, contexts = scope_plan_inputs(1, 1000000)
    with pytest.raises(StagePlanningBlocked):
        build_scope_work_descriptors(items, contexts, policy())
