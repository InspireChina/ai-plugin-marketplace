from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal, Mapping, Sequence

from models import ContextRefDescriptor
from action_ledger import ActionLedger, validate_attempt_repair_context

from contracts import action_contract_binding, current_action_contract_id, canonical_json_bytes, estimate_action_input_tokens, load_schema_registry, sha256_bytes, usable_action_input_tokens, validate_contract

SKILL_ROOT = Path(__file__).parents[1]
StagePlan = Mapping[str, object]
ActionGroup = Mapping[str, object]


@dataclass(frozen=True)
class AtomicWorkItemDescriptor:
    work_item_id: str
    action_kind: str
    source_role: str
    source_sha256: str
    block_ordinal: int
    work_item_payload: Mapping[str, object]


@dataclass(frozen=True)
class PlannedWorkDescriptor:
    work_key: str
    action_kind: str
    ordered_work_item_ids: tuple[str, ...]
    context_ref_ids: tuple[str, ...]
    dependency_work_keys: tuple[str, ...]


@dataclass(frozen=True)
class DemoBudgetLimits:
    max_discovery_rounds: int
    max_scenario_steps: int
    max_screenshots: int


@dataclass(frozen=True)
class RunBudgetPolicy:
    contract_version: str
    model_profile_id: str
    model_context_limit_tokens: int
    estimator_version: str
    max_planned_tokens: int
    max_active_seconds: int
    output_reserve_tokens: int
    hydrate_reserve_tokens: int
    safety_margin_tokens: int
    reference_overhead_tokens: int
    max_concurrency: int
    demo_limits: DemoBudgetLimits

    def __post_init__(self):
        if not isinstance(self.demo_limits, DemoBudgetLimits):
            raise ValueError("demo_limits 必须是 DemoBudgetLimits。")
        diagnostics = validate_contract(
            run_budget_policy_value(self),
            "run-budget-policy.schema.json",
            load_schema_registry(SKILL_ROOT),
        )
        if diagnostics:
            raise ValueError("运行预算未通过合同校验。")


def run_budget_policy_value(policy: RunBudgetPolicy) -> dict[str, object]:
    return {
        "contractVersion": policy.contract_version,
        "modelProfileId": policy.model_profile_id,
        "modelContextLimitTokens": policy.model_context_limit_tokens,
        "estimatorVersion": policy.estimator_version,
        "maxPlannedTokens": policy.max_planned_tokens,
        "maxActiveSeconds": policy.max_active_seconds,
        "outputReserveTokens": policy.output_reserve_tokens,
        "hydrateReserveTokens": policy.hydrate_reserve_tokens,
        "safetyMarginTokens": policy.safety_margin_tokens,
        "referenceOverheadTokens": policy.reference_overhead_tokens,
        "maxConcurrency": policy.max_concurrency,
        "demoLimits": {
            "maxDiscoveryRounds": policy.demo_limits.max_discovery_rounds,
            "maxScenarioSteps": policy.demo_limits.max_scenario_steps,
            "maxScreenshots": policy.demo_limits.max_screenshots,
        },
    }


@dataclass(frozen=True)
class StagePlanningBlocked(Exception):
    reason_code: Literal["BUDGET_EXHAUSTED"]
    details: dict | None = None


@dataclass(frozen=True)
class DependencyResultRef:
    logical_work_id: str
    result_sha256: str
    normalized_result: bytes
    source_attempt_record_sha256: str | None = None

def _selected_action_contract_id(action_kind, action_contract_ids):
    contract_id = (action_contract_ids or {}).get(action_kind, current_action_contract_id(action_kind))
    if not isinstance(contract_id, str) or contract_id.rpartition("-v")[0] != action_kind:
        raise ValueError("已绑定 Action contract 与 work kind 不一致。")
    action_contract_binding(SKILL_ROOT, contract_id)
    return contract_id


def bound_action_contract_ids(plan):
    """Recover only verified contract selections; frozen inputs remain authoritative."""
    selected = {}
    for work in plan["works"]:
        packet = work["packetPlan"]
        kind, contract_id = packet["actionKind"], packet["actionContractId"]
        _selected_action_contract_id(kind, {kind: contract_id})
        _, digest = action_contract_binding(SKILL_ROOT, contract_id)
        if packet["actionContractSha256"] != digest or (kind in selected and selected[kind] != contract_id):
            raise ValueError("冻结计划的 Action contract hash 或同类版本不一致。")
        selected[kind] = contract_id
    return selected


def estimate_work_input_tokens(action_kind, work_items, context_refs, budget_policy, *, action_contract_ids=None):
    """Estimate known base bytes through the same public request authority."""
    descriptor = make_planned_work(action_kind, work_items, context_refs, [])
    items = {item.work_item_id: item for item in work_items}
    contexts = {ref.ref_id: ref for ref in context_refs}
    packet_plan = {
        "actionKind": action_kind,
        "orderedWorkItems": [{"workItemId": item_id, "payloadSha256": sha256_bytes(canonical_json_bytes(items[item_id].work_item_payload))}
                             for item_id in descriptor.ordered_work_item_ids],
        "contextRefs": [{"refId": ref_id, "contentSha256": sha256_bytes(contexts[ref_id].canonical_content)}
                        for ref_id in descriptor.context_ref_ids],
    }
    contract_id = _selected_action_contract_id(action_kind, action_contract_ids)
    contract, _ = action_contract_binding(SKILL_ROOT, contract_id)
    return estimate_action_input_tokens(SKILL_ROOT, contract_id,
        canonical_json_bytes(_base_packet(packet_plan, items, contexts)),
        budget_policy=run_budget_policy_value(budget_policy),
        max_output_tokens=min(budget_policy.output_reserve_tokens, contract["limits"]["maxOutputTokens"]))


def plan_stage(
    stage_kind: str,
    work_items: Sequence[AtomicWorkItemDescriptor],
    context_refs: Sequence[ContextRefDescriptor],
    planned_works: Sequence[PlannedWorkDescriptor],
    upstream_checkpoint_sha256s: Sequence[str],
    budget_policy: RunBudgetPolicy,
    *,
    action_contract_ids: Mapping[str, str] | None = None,
) -> StagePlan:
    items = {item.work_item_id: item for item in work_items}
    contexts = {ref.ref_id: ref for ref in context_refs}
    if len(items) != len(work_items) or len(contexts) != len(context_refs):
        raise ValueError("原子项和context ID必须唯一。")
    if len(set(upstream_checkpoint_sha256s)) != len(upstream_checkpoint_sha256s):
        raise ValueError("upstream checkpoint不得重复。")
    if len({work.work_key for work in planned_works}) != len(planned_works):
        raise ValueError("work key不得重复。")
    referenced_items = []
    referenced_contexts = set()
    for descriptor in planned_works:
        if not set(descriptor.ordered_work_item_ids) <= items.keys() or not set(descriptor.context_ref_ids) <= contexts.keys():
            raise ValueError("PlannedWork引用了缺失item/context。")
        expected = make_planned_work(
            descriptor.action_kind, [items[item_id] for item_id in descriptor.ordered_work_item_ids],
            [contexts[ref_id] for ref_id in descriptor.context_ref_ids], descriptor.dependency_work_keys,
        )
        if descriptor != expected:
            raise ValueError("PlannedWork key或稳定排序无效。")
        referenced_items.extend(descriptor.ordered_work_item_ids)
        referenced_contexts.update(descriptor.context_ref_ids)
    if len(referenced_items) != len(set(referenced_items)) or set(referenced_items) != items.keys():
        raise ValueError("每个原子项必须恰好归属一个PlannedWork。")
    if referenced_contexts != contexts.keys():
        raise ValueError("每个context必须被引用。")
    by_key = {work.work_key: work for work in planned_works}
    if any(not set(work.dependency_work_keys) <= by_key.keys() for work in planned_works):
        raise ValueError("dependency work key缺失。")
    layers = []
    resolved = set()
    while len(resolved) < len(by_key):
        ready = sorted(key for key, work in by_key.items() if key not in resolved and set(work.dependency_work_keys) <= resolved)
        if not ready:
            raise ValueError("dependency存在自指或循环。")
        layers.append(ready)
        resolved.update(ready)
    works = []
    logical_by_key = {}
    for key in [key for layer in layers for key in layer]:
        descriptor = by_key[key]
        contract_id = _selected_action_contract_id(descriptor.action_kind, action_contract_ids)
        contract, contract_hash = action_contract_binding(SKILL_ROOT, contract_id)
        packet_plan = {
            "actionKind": descriptor.action_kind,
            "actionContractId": contract_id,
            "actionContractSha256": contract_hash,
            "orderedWorkItems": [
                {"workItemId": item_id, "payloadSha256": sha256_bytes(canonical_json_bytes(items[item_id].work_item_payload))}
                for item_id in descriptor.ordered_work_item_ids
            ],
            "contextRefs": [
                {"refId": ref_id, "contentSha256": sha256_bytes(contexts[ref_id].canonical_content)}
                for ref_id in descriptor.context_ref_ids
            ],
            "dependencyLogicalWorkIds": sorted(logical_by_key[dependency] for dependency in descriptor.dependency_work_keys),
        }
        policy_value = run_budget_policy_value(budget_policy)
        estimate = estimate_action_input_tokens(
            SKILL_ROOT, contract_id, canonical_json_bytes(_base_packet(packet_plan, items, contexts)),
            budget_policy=policy_value, max_output_tokens=min(budget_policy.output_reserve_tokens, contract["limits"]["maxOutputTokens"]),
        )
        if estimate > usable_action_input_tokens(policy_value):
            raise StagePlanningBlocked("BUDGET_EXHAUSTED")
        logical_id = "logical-" + sha256_bytes(canonical_json_bytes({
            "stageKind": stage_kind, "packetPlanSha256": sha256_bytes(canonical_json_bytes(packet_plan)),
        }))
        works.append({"logicalWorkId": logical_id, "packetPlan": packet_plan})
        logical_by_key[key] = logical_id
    groups = []
    for layer in layers:
        for offset in range(0, len(layer), budget_policy.max_concurrency):
            required = [logical_by_key[key] for key in layer[offset:offset + budget_policy.max_concurrency]]
            groups.append({"groupId": "group-" + sha256_bytes(canonical_json_bytes({"stageKind": stage_kind, "requiredLogicalWorkIds": required})), "requiredLogicalWorkIds": required})
    return {
        "stageKind": stage_kind, "upstreamCheckpointSha256s": sorted(upstream_checkpoint_sha256s),
        "works": works,
        "groups": groups,
        "budgetPolicySha256": sha256_bytes(canonical_json_bytes(run_budget_policy_value(budget_policy))),
    }


def validate_stage_plan(
    plan: StagePlan,
    work_items: Sequence[AtomicWorkItemDescriptor],
    context_refs: Sequence[ContextRefDescriptor],
    planned_works: Sequence[PlannedWorkDescriptor],
    upstream_checkpoint_sha256s: Sequence[str],
    budget_policy: RunBudgetPolicy,
    *,
    action_contract_ids: Mapping[str, str] | None = None,
) -> None:
    frozen_ids = bound_action_contract_ids(plan)
    expected = plan_stage(str(plan["stageKind"]), work_items, context_refs, planned_works, upstream_checkpoint_sha256s, budget_policy,
                          action_contract_ids=frozen_ids if action_contract_ids is None else action_contract_ids)
    if canonical_json_bytes(plan) != canonical_json_bytes(expected):
        raise ValueError("StagePlan 与完整冻结输入不一致。")


def materialize_packet(
    plan: StagePlan,
    logical_work_id: str,
    revision: int,
    work_items: Sequence[AtomicWorkItemDescriptor],
    context_refs: Sequence[ContextRefDescriptor],
    dependency_refs: Sequence[DependencyResultRef],
    ledger: ActionLedger,
    attempt_repair_context: ContextRefDescriptor | None = None,
) -> bytes:
    if type(revision) is not int or not 1 <= revision <= 10 or (revision > 1 and attempt_repair_context is None) or (revision == 1 and attempt_repair_context is not None):
        raise ValueError("revision与唯一repair context不一致。")
    matches = [work for work in plan["works"] if work["logicalWorkId"] == logical_work_id]
    if len(matches) != 1:
        raise ValueError("LogicalWork必须在plan唯一存在。")
    work = matches[0]
    packet_plan = work["packetPlan"]
    contract, contract_hash = action_contract_binding(SKILL_ROOT, packet_plan["actionContractId"])
    if revision > 1 and contract["executionKind"] != "MODEL_PROVIDER":
        raise ValueError("只有MODEL_PROVIDER允许候选修复。")
    expected_id = "logical-" + sha256_bytes(canonical_json_bytes({"stageKind": plan["stageKind"], "packetPlanSha256": sha256_bytes(canonical_json_bytes(packet_plan))}))
    if contract_hash != packet_plan["actionContractSha256"] or expected_id != logical_work_id:
        raise ValueError("PacketPlan合同或LogicalWork hash漂移。")
    items = {item.work_item_id: item for item in work_items}
    contexts = {ref.ref_id: ref for ref in context_refs}
    expected_items = [item["workItemId"] for entry in plan["works"] for item in entry["packetPlan"]["orderedWorkItems"]]
    expected_contexts = {ref["refId"] for entry in plan["works"] for ref in entry["packetPlan"]["contextRefs"]}
    if len(items) != len(work_items) or len(contexts) != len(context_refs) or len(expected_items) != len(set(expected_items)) or items.keys() != set(expected_items) or contexts.keys() != expected_contexts:
        raise ValueError("实际item/context必须与完整plan集合一致且无重复。")
    for entry in plan["works"]:
        _base_packet(entry["packetPlan"], items, contexts)
    provided = [ref.logical_work_id for ref in dependency_refs]
    if len(provided) != len(set(provided)) or set(provided) != set(packet_plan["dependencyLogicalWorkIds"]):
        raise ValueError("DependencyResultRef必须恰好覆盖冻结依赖。")
    from action_ledger import CandidateResult, effective_result, effective_result_bytes, dependency_context
    for ref in dependency_refs:
        digest, result = effective_result(ledger, ref.logical_work_id)
        source = result.source_attempt_record_sha256 if isinstance(result, CandidateResult) else None
        if (digest != ref.result_sha256 or source != ref.source_attempt_record_sha256
                or sha256_bytes(ref.normalized_result) != result.normalized_result_sha256
                or effective_result_bytes(ledger,ref.logical_work_id) != ref.normalized_result):
            raise ValueError("dependency result或normalized bytes未由ledger证明。")
    packet = _base_packet(packet_plan, items, contexts)
    packet['contextRefs'].extend(dependency_context(ledger,ref.logical_work_id)
        for ref in sorted(dependency_refs,key=lambda ref:ref.logical_work_id))
    if attempt_repair_context is not None:
        previous = ledger.attempt_records.get(json.loads(attempt_repair_context.canonical_content)['attemptRecordSha256'])
        if previous is None or previous.revision != revision - 1:
            raise ValueError('repair 必须绑定紧邻前一候选。')
        validate_attempt_repair_context(attempt_repair_context, logical_work_id, ledger.attempt_records, envelopes_by_sha256=ledger.envelopes_by_sha256)
        packet["contextRefs"].append({"refId": attempt_repair_context.ref_id, "canonicalContent": _canonical_value(attempt_repair_context.canonical_content), "contentSha256": sha256_bytes(attempt_repair_context.canonical_content)})
    ref_ids = [ref["refId"] for ref in packet["contextRefs"]]
    if len(ref_ids) != len(set(ref_ids)):
        raise ValueError("base、dependency与repair context ID不得碰撞。")
    return canonical_json_bytes(packet)


def _effective_envelope(ledger: ActionLedger, logical_work_id: str):
    envelopes = [envelope for envelope in ledger.envelopes_by_sha256.values() if envelope.value["logicalWorkId"] == logical_work_id]
    if not envelopes:
        return None
    latest = max((envelope.value["revision"], envelope.value["attempt"]) for envelope in envelopes)
    effective = [envelope for envelope in envelopes if (envelope.value["revision"], envelope.value["attempt"]) == latest]
    if len(effective) != 1:
        raise ValueError("依赖effective Attempt必须唯一。")
    return effective[0]


def _effective_success(ledger: ActionLedger, logical_work_id: str):
    effective = _effective_envelope(ledger, logical_work_id)
    if effective is None:
        raise ValueError("依赖缺少已发行Envelope。")
    records = [(digest, record) for digest, record in ledger.attempt_records.items() if record.envelope_sha256 == effective.sha256 and record.outcome == "SUCCEEDED"]
    if len(records) != 1:
        raise ValueError("依赖必须有唯一effective SUCCEEDED Attempt。")
    return records[0]


def _canonical_value(payload: bytes) -> object:
    def invalid_constant(value):
        raise ValueError(f"非有限JSON数值：{value}")

    value = json.loads(payload.decode("utf-8"), parse_constant=invalid_constant)
    if canonical_json_bytes(value) != payload:
        raise ValueError("输入必须是严格canonical JSON bytes。")
    return value


def _base_packet(packet_plan, items, contexts) -> dict[str, object]:
    for item in packet_plan["orderedWorkItems"]:
        value = items[item["workItemId"]]
        if value.action_kind != packet_plan["actionKind"] or sha256_bytes(canonical_json_bytes(value.work_item_payload)) != item["payloadSha256"]:
            raise ValueError("work item actionKind或payload hash漂移。")
    for ref in packet_plan["contextRefs"]:
        if sha256_bytes(contexts[ref["refId"]].canonical_content) != ref["contentSha256"]:
            raise ValueError("base context hash漂移。")
        content = _canonical_value(contexts[ref["refId"]].canonical_content)
        if isinstance(content, Mapping) and content.get("kind") in {"ATTEMPT_REPAIR", "DEPENDENCY_RESULT"}:
            raise ValueError("base context不能伪装动态dependency/repair。")
    return {
        "workItems": [{"workItemId": item["workItemId"], "payload": _canonical_value(canonical_json_bytes(items[item["workItemId"]].work_item_payload))} for item in packet_plan["orderedWorkItems"]],
        "contextRefs": [{"refId": ref["refId"], "canonicalContent": _canonical_value(contexts[ref["refId"]].canonical_content), "contentSha256": sha256_bytes(contexts[ref["refId"]].canonical_content)} for ref in packet_plan["contextRefs"]],
    }


def validate_packet_against_plan(
    plan: StagePlan,
    logical_work_id: str,
    revision: int,
    work_items: Sequence[AtomicWorkItemDescriptor],
    context_refs: Sequence[ContextRefDescriptor],
    dependency_refs: Sequence[DependencyResultRef],
    ledger: ActionLedger,
    packet: bytes,
    attempt_repair_context: ContextRefDescriptor | None = None,
) -> None:
    if packet != materialize_packet(plan, logical_work_id, revision, work_items, context_refs, dependency_refs, ledger, attempt_repair_context):
        raise ValueError("实际packet与冻结plan不一致。")


def next_issuable_group(plan: StagePlan, ledger: ActionLedger) -> ActionGroup | None:
    from action_ledger import is_group_ready
    return next((group for group in plan['groups'] if not is_group_ready(ledger,group['requiredLogicalWorkIds'])),None)


def make_planned_work(
    action_kind: str,
    work_items: Sequence[AtomicWorkItemDescriptor],
    context_refs: Sequence[ContextRefDescriptor],
    dependency_work_keys: Sequence[str],
) -> PlannedWorkDescriptor:
    for values in (
        [item.work_item_id for item in work_items],
        [item.ref_id for item in context_refs],
        dependency_work_keys,
    ):
        if len(values) != len(set(values)):
            raise ValueError("work item、context 或 dependency 输入不得重复。")
    if any(item.action_kind != action_kind for item in work_items):
        raise ValueError("work item actionKind 与外部 actionKind 不一致。")
    ordered = sorted(work_items, key=lambda item: (
        item.action_kind, item.source_role, item.source_sha256,
        item.block_ordinal, item.work_item_id,
    ))
    item_ids = tuple(item.work_item_id for item in ordered)
    context_ids = tuple(sorted(item.ref_id for item in context_refs))
    dependencies = tuple(sorted(dependency_work_keys))
    identity = {
        "actionKind": action_kind,
        "orderedWorkItemIds": list(item_ids),
        "contextRefIds": list(context_ids),
        "dependencyWorkKeys": list(dependencies),
    }
    return PlannedWorkDescriptor(
        "work-" + sha256_bytes(canonical_json_bytes(identity)),
        action_kind, item_ids, context_ids, dependencies,
    )
