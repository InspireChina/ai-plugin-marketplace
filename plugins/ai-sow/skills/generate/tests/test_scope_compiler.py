from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
FIXTURES = SKILL_ROOT / "fixtures"
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contracts import canonical_json_bytes  # noqa: E402
from models import ImpactPlan  # noqa: E402
from scope_compiler import compile_scope, impact_plan_sha256  # noqa: E402


COLLECTION_TYPES = {
    "epics": ("EPIC", "epicId"),
    "features": ("FEATURE", "featureId"),
    "commitments": ("COMMITMENT", "commitmentId"),
    "effectiveStartItems": ("EFFECTIVE_START_ITEM", "effectiveStartItemId"),
    "designItems": ("DESIGN_ITEM", "designItemId"),
    "designDecisions": ("DESIGN_DECISION", "designDecisionId"),
    "integrations": ("INTEGRATION", "integrationId"),
    "nfrs": ("NFR", "nfrId"),
    "assumptions": ("ASSUMPTION", "assumptionId"),
}


def read_fixture(mode: str, name: str) -> dict[str, object]:
    return json.loads((FIXTURES / mode / name).read_text(encoding="utf-8"))


def full_plan(feature_ids: list[str]) -> ImpactPlan:
    return ImpactPlan(
        action="FULL_COMPILE",
        baseline_generation_id=None,
        baseline_revision_id=None,
        changed_source_ids=(),
        changed_anchor_ids=(),
        affected_feature_ids=tuple(feature_ids),
        escalation="FULL",
        reason_codes=("NO_CURRENT_GENERATION",),
    )


def scope_slice(bundle: dict[str, object], plan: ImpactPlan) -> dict[str, object]:
    return {
        "contract": "ai-sow-scope-slice-v1",
        "inputRevisionId": bundle["inputRevisionId"],
        "impactPlanSha256": impact_plan_sha256(plan),
        "replacesFeatureIds": (
            [] if plan.baseline_generation_id is None else list(plan.affected_feature_ids)
        ),
        "newAnchorMappings": [],
        **{
            collection: copy.deepcopy(bundle[collection])
            for collection in COLLECTION_TYPES
        },
        "responsibilityBoundaries": copy.deepcopy(bundle["responsibilityBoundaries"]),
    }


def source_anchors(candidate: dict[str, object]) -> list[dict[str, str]]:
    seen: dict[tuple[str, str], dict[str, str]] = {}
    for collection in COLLECTION_TYPES:
        for item in candidate[collection]:
            for source_ref in item.get("sourceRefs", []):
                seen[(source_ref["sourceId"], source_ref["anchorId"])] = {
                    "sourceId": source_ref["sourceId"],
                    "anchorId": source_ref["anchorId"],
                    "sha256": source_ref["sha256"],
                }
    return list(seen.values())


def id_decisions(candidate: dict[str, object], previous=None) -> dict[str, object]:
    previous_ids = set()
    if previous is not None:
        for collection, (_object_type, id_field) in COLLECTION_TYPES.items():
            previous_ids.update(item[id_field] for item in previous[collection])
    decisions = []
    for collection, (object_type, id_field) in COLLECTION_TYPES.items():
        for item in candidate[collection]:
            object_id = item[id_field]
            preserved = object_id in previous_ids
            decision = {
                "objectType": object_type,
                "objectId": object_id,
                "disposition": "UNCHANGED" if preserved else "NEW",
                "meaningPreserved": preserved,
                "rationale": "语义未变化，保留原 ID。" if preserved else "新对象分配稳定 ID。",
            }
            if preserved:
                decision["previousId"] = object_id
            decisions.append(decision)
    return {"contract": "ai-sow-id-decisions-v1", "decisions": decisions}


def input_manifest(mode: str, revision_id: str) -> dict[str, object]:
    value = read_fixture(mode, "input-manifest.json")
    value["revisionId"] = revision_id
    return value


def compile_fixture_scope(mode: str):
    bundle = read_fixture(mode, "scope.json")
    plan = full_plan([item["featureId"] for item in bundle["features"]])
    candidate = scope_slice(bundle, plan)
    return compile_scope(
        input_manifest(mode, str(bundle["inputRevisionId"])),
        source_anchors(candidate),
        None,
        candidate,
        id_decisions(candidate),
        plan,
    )


def diagnostic_codes(result) -> set[str]:
    return {diagnostic.code for diagnostic in result.diagnostics}


def test_brownfield_scope_uses_prior_sow_as_contract_baseline() -> None:
    result = compile_fixture_scope("brownfield")
    assert not result.diagnostics
    assert result.bundle["commitments"][0]["treatment"] == "CARRY_FORWARD"
    assert result.bundle["effectiveStartItems"]
    assert all(item["sourceRefs"] for item in result.bundle["effectiveStartItems"])


def test_brownfield_task_instance_starts_have_distinct_prior_sow_evidence() -> None:
    scope = read_fixture("brownfield", "scope.json")
    instances = [
        item
        for item in scope["effectiveStartItems"]
        if item["matchLevel"] == "TASK_INSTANCE"
    ]
    evidence = {
        (
            item["sourceRefs"][0]["anchorId"],
            item["sourceRefs"][0]["locator"],
            item["sourceRefs"][0]["sha256"],
        )
        for item in instances
    }
    capability = next(
        item
        for item in scope["effectiveStartItems"]
        if item["matchLevel"] == "CAPABILITY"
    )
    capability_evidence = (
        capability["sourceRefs"][0]["anchorId"],
        capability["sourceRefs"][0]["locator"],
        capability["sourceRefs"][0]["sha256"],
    )

    assert len(instances) == 2
    assert len(evidence) == 2
    assert capability_evidence not in evidence


def test_scope_rejects_task_instance_effective_start_without_base_unit() -> None:
    bundle = read_fixture("brownfield", "scope.json")
    bundle["effectiveStartItems"][0]["matchLevel"] = "TASK_INSTANCE"
    bundle["effectiveStartItems"][0].pop("baseUnit", None)
    plan = full_plan([item["featureId"] for item in bundle["features"]])
    candidate = scope_slice(bundle, plan)

    result = compile_scope(
        input_manifest("brownfield", str(bundle["inputRevisionId"])),
        source_anchors(candidate),
        None,
        candidate,
        id_decisions(candidate),
        plan,
    )

    assert "CONTRACT_REQUIRED" in diagnostic_codes(result)


def test_initial_full_scope_rejects_nonempty_replacement_set() -> None:
    bundle = read_fixture("greenfield", "scope.json")
    plan = full_plan([item["featureId"] for item in bundle["features"]])
    candidate = scope_slice(bundle, plan)
    candidate["replacesFeatureIds"] = [bundle["features"][0]["featureId"]]

    result = compile_scope(
        input_manifest("greenfield", str(bundle["inputRevisionId"])),
        source_anchors(candidate),
        None,
        candidate,
        id_decisions(candidate),
        plan,
    )

    assert "SCOPE_REPLACEMENT_CLOSURE_MISMATCH" in diagnostic_codes(result)


def test_design_required_nfr_creates_fixed_boundary() -> None:
    result = compile_fixture_scope("brownfield")
    nfr = next(item for item in result.bundle["nfrs"] if item["nfrId"] == "nfr-recovery-objective")
    assert nfr["status"] == "DESIGN_REQUIRED"
    assert nfr["estimateBoundary"]
    assert nfr["changeTrigger"]


def test_scope_allows_pending_assumption_with_fixed_estimate_boundary() -> None:
    bundle = read_fixture("greenfield", "scope.json")
    bundle["assumptions"][0]["status"] = "待确认"
    plan = full_plan([item["featureId"] for item in bundle["features"]])
    candidate = scope_slice(bundle, plan)

    result = compile_scope(
        input_manifest("greenfield", str(bundle["inputRevisionId"])),
        source_anchors(candidate),
        None,
        candidate,
        id_decisions(candidate),
        plan,
    )

    assert "SCOPE_CONFLICT_UNRESOLVED" not in diagnostic_codes(result)
    assert result.bundle["assumptions"][0]["status"] == "待确认"
    assert result.bundle["assumptions"][0]["estimateBoundary"]
    assert result.bundle["assumptions"][0]["changeTrigger"]


def test_scope_rejects_in_scope_feature_without_vendor_responsibility() -> None:
    bundle = read_fixture("greenfield", "scope.json")
    customer_boundary = next(
        item
        for item in bundle["responsibilityBoundaries"]
        if item["party"] == "CUSTOMER"
    )
    bundle["features"][0]["responsibilityBoundaryIds"] = [
        customer_boundary["responsibilityBoundaryId"]
    ]
    plan = full_plan([item["featureId"] for item in bundle["features"]])
    candidate = scope_slice(bundle, plan)

    result = compile_scope(
        input_manifest("greenfield", str(bundle["inputRevisionId"])),
        source_anchors(candidate),
        None,
        candidate,
        id_decisions(candidate),
        plan,
    )

    assert "SCOPE_IN_SCOPE_VENDOR_RESPONSIBILITY_REQUIRED" in diagnostic_codes(result)


def independent_feature() -> dict[str, list[dict[str, object]]]:
    ref = {
        "sourceId": "prd-independent",
        "anchorId": "anchor-independent",
        "locator": "heading:Feature/Independent",
        "sha256": "9" * 64,
    }
    design_ref = {**ref, "sourceId": "hld-independent", "anchorId": "anchor-design-independent"}
    return {
        "epics": [
            {
                "epicId": "epic-independent",
                "kind": "BUSINESS",
                "name": "独立能力",
                "summary": "不受退款域变更影响。",
                "sourceRefs": [ref],
            }
        ],
        "features": [
            {
                "featureId": "feature-independent",
                "epicId": "epic-independent",
                "domainId": "domain-independent",
                "kind": "BUSINESS",
                "name": "独立功能",
                "summary": "保持完全不变的独立功能。",
                "sourceRefs": [ref],
                "responsibilityBoundaryIds": ["responsibility-vendor-delivery"],
                "scopeDecision": {
                    "decision": "IN_SCOPE",
                    "rationale": "独立范围。",
                    "designItemIds": ["design-item-independent"],
                    "effectiveStartItemIds": [],
                    "requiredIntegrationIds": [],
                    "requiredNfrIds": [],
                },
            }
        ],
        "designItems": [
            {
                "designItemId": "design-item-independent",
                "type": "COMPONENT",
                "name": "独立组件",
                "summary": "独立实现。",
                "featureIds": ["feature-independent"],
                "sourceRefs": [design_ref],
            }
        ],
    }


def test_slice_replacement_preserves_unaffected_object_bytes() -> None:
    previous = read_fixture("brownfield", "scope.json")
    independent = independent_feature()
    for collection, items in independent.items():
        previous[collection].extend(items)
    bundle = read_fixture("brownfield", "scope.json")
    bundle["inputRevisionId"] = "000002"
    plan = ImpactPlan(
        action="SLICE_COMPILE",
        baseline_generation_id="000001",
        baseline_revision_id="000001",
        changed_source_ids=("prd-refund-upgrade",),
        changed_anchor_ids=("anchor-refund-processing",),
        affected_feature_ids=("feature-refund-processing", "feature-refund-notification"),
        escalation="FEATURE",
        reason_codes=("INPUT_CHANGED",),
    )
    candidate = scope_slice(bundle, plan)
    before = canonical_json_bytes(independent["features"][0])
    result = compile_scope(
        input_manifest("brownfield", "000002"),
        source_anchors(candidate) + source_anchors(previous),
        previous,
        candidate,
        id_decisions(candidate, previous),
        plan,
    )
    preserved = next(
        item for item in result.bundle["features"] if item["featureId"] == "feature-independent"
    )
    assert not result.diagnostics
    assert canonical_json_bytes(preserved) == before


def test_replaces_feature_ids_contains_baseline_ids_not_new_ids() -> None:
    previous = read_fixture("greenfield", "scope.json")
    bundle = copy.deepcopy(previous)
    bundle["inputRevisionId"] = "000002"
    old_feature_id = "feature-refund-processing"
    new_feature_id = "feature-refund-processing-v2"
    bundle["features"][0]["featureId"] = new_feature_id
    bundle["features"][0]["name"] = "退款申请处理升级"
    decision = bundle["features"][0]["scopeDecision"]
    decision["decision"] = "OUT_OF_SCOPE"
    decision["rationale"] = "该回归只验证旧 ID 替换语义。"
    decision["designItemIds"] = []
    decision["effectiveStartItemIds"] = []
    decision["requiredIntegrationIds"] = []
    decision["requiredNfrIds"] = []
    for collection in tuple(COLLECTION_TYPES)[2:]:
        bundle[collection] = []
    plan = ImpactPlan(
        action="SLICE_COMPILE",
        baseline_generation_id="000001",
        baseline_revision_id="000001",
        changed_source_ids=("prd-refund",),
        changed_anchor_ids=("anchor-refund",),
        affected_feature_ids=(old_feature_id,),
        escalation="FEATURE",
        reason_codes=("INPUT_CHANGED",),
    )
    candidate = scope_slice(bundle, plan)
    candidate["replacesFeatureIds"] = [old_feature_id]
    previous_objects = {
        (object_type, item[id_field]): item
        for collection, (object_type, id_field) in COLLECTION_TYPES.items()
        for item in previous[collection]
    }
    decisions = []
    for collection, (object_type, id_field) in COLLECTION_TYPES.items():
        for item in candidate[collection]:
            object_id = item[id_field]
            previous_id = (
                old_feature_id
                if object_id == new_feature_id
                else object_id
            )
            previous_item = previous_objects.get((object_type, previous_id))
            unchanged = (
                previous_item is not None
                and canonical_json_bytes(previous_item)
                == canonical_json_bytes(item)
            )
            decisions.append(
                {
                    "objectType": object_type,
                    "objectId": object_id,
                    "disposition": "UNCHANGED" if unchanged else "CHANGED",
                    "previousId": previous_id,
                    "meaningPreserved": unchanged,
                    "rationale": (
                        "语义未变化，保留原 ID。"
                        if unchanged
                        else "交付含义变化，使用新语义。"
                    ),
                }
            )

    result = compile_scope(
        input_manifest("greenfield", "000002"),
        source_anchors(candidate) + source_anchors(previous),
        previous,
        candidate,
        {"contract": "ai-sow-id-decisions-v1", "decisions": decisions},
        plan,
    )

    assert candidate["replacesFeatureIds"] == [old_feature_id]
    assert new_feature_id not in candidate["replacesFeatureIds"]
    assert not result.diagnostics
    final_ids = {item["featureId"] for item in result.bundle["features"]}
    assert old_feature_id not in final_ids
    assert new_feature_id in final_ids


def test_unknown_source_ref_blocks_compilation() -> None:
    bundle = read_fixture("greenfield", "scope.json")
    plan = full_plan(["feature-refund-processing"])
    candidate = scope_slice(bundle, plan)
    anchors = source_anchors(candidate)
    anchors.pop()
    result = compile_scope(
        input_manifest("greenfield", "000001"),
        anchors,
        None,
        candidate,
        id_decisions(candidate),
        plan,
    )
    assert "SCOPE_SOURCE_REF_UNKNOWN" in diagnostic_codes(result)


def test_missing_id_decision_blocks_compilation() -> None:
    bundle = read_fixture("greenfield", "scope.json")
    plan = full_plan(["feature-refund-processing"])
    candidate = scope_slice(bundle, plan)
    decisions = id_decisions(candidate)
    decisions["decisions"].pop()
    result = compile_scope(
        input_manifest("greenfield", "000001"),
        source_anchors(candidate),
        None,
        candidate,
        decisions,
        plan,
    )
    assert "SCOPE_ID_DECISION_MISSING" in diagnostic_codes(result)
