from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
FIXTURES = SKILL_ROOT / "fixtures"
ASSETS = SKILL_ROOT / "assets"
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from delivery_compiler import compile_delivery, read_template_catalog  # noqa: E402
from models import ImpactPlan  # noqa: E402
from scope_compiler import impact_plan_sha256  # noqa: E402


COLLECTION_TYPES = {
    "stories": ("STORY", "storyId"),
    "acceptanceCriteria": ("ACCEPTANCE_CRITERION", "acceptanceCriterionId"),
    "tasks": ("TASK", "taskId"),
    "dependencies": ("DEPENDENCY", "dependencyId"),
}


def fixture(mode: str, name: str) -> dict[str, object]:
    return json.loads((FIXTURES / mode / name).read_text(encoding="utf-8"))


def plan_for(scope: dict[str, object], action: str = "FULL_COMPILE") -> ImpactPlan:
    return ImpactPlan(
        action=action,
        baseline_generation_id=None if action == "FULL_COMPILE" else "000001",
        baseline_revision_id=None if action == "FULL_COMPILE" else "000001",
        changed_source_ids=(),
        changed_anchor_ids=(),
        affected_feature_ids=tuple(item["featureId"] for item in scope["features"]),
        escalation="FULL" if action == "FULL_COMPILE" else "FEATURE",
        reason_codes=("NO_CURRENT_GENERATION",) if action == "FULL_COMPILE" else ("INPUT_CHANGED",),
    )


def delivery_slice(
    bundle: dict[str, object], scope: dict[str, object], plan: ImpactPlan
) -> dict[str, object]:
    scope_sha = sha256_bytes(canonical_json_bytes(scope))
    return {
        "contract": "ai-sow-delivery-slice-v1",
        "inputRevisionId": scope["inputRevisionId"],
        "scopeSha256": scope_sha,
        "impactPlanSha256": impact_plan_sha256(plan),
        "replacesFeatureIds": list(plan.affected_feature_ids),
        **{
            collection: copy.deepcopy(bundle[collection])
            for collection in COLLECTION_TYPES
        },
    }


def id_decisions(candidate: dict[str, object], previous=None) -> dict[str, object]:
    previous_ids = set()
    if previous is not None:
        for collection, (_kind, id_field) in COLLECTION_TYPES.items():
            previous_ids.update(item[id_field] for item in previous[collection])
    decisions = []
    for collection, (kind, id_field) in COLLECTION_TYPES.items():
        for item in candidate[collection]:
            object_id = item[id_field]
            preserved = object_id in previous_ids
            decision = {
                "objectType": kind,
                "objectId": object_id,
                "disposition": "UNCHANGED" if preserved else "NEW",
                "meaningPreserved": preserved,
                "rationale": "语义不变，保留原 ID。" if preserved else "新交付对象分配稳定 ID。",
            }
            if preserved:
                decision["previousId"] = object_id
            decisions.append(decision)
    return {"contract": "ai-sow-id-decisions-v1", "decisions": decisions}


def compile_fixture(mode: str = "brownfield"):
    scope = fixture(mode, "scope.json")
    delivery = fixture(mode, "delivery.json")
    delivery["scopeSha256"] = sha256_bytes(canonical_json_bytes(scope))
    plan = plan_for(scope)
    candidate = delivery_slice(delivery, scope, plan)
    return compile_delivery(
        scope,
        None,
        candidate,
        id_decisions(candidate),
        plan,
        read_template_catalog(ASSETS / "sow-template.xlsx"),
    )


def diagnostic_codes(result) -> set[str]:
    return {diagnostic.code for diagnostic in result.diagnostics}


def test_design_required_item_becomes_design_task_under_implementation_story() -> None:
    result = compile_fixture()
    assert not result.diagnostics
    task = next(
        item
        for item in result.bundle["tasks"]
        if item["taskId"] == "task-refund-recovery-design"
    )
    assert task["taskKind"] == "DESIGN"
    assert task["storyId"] == "story-refund-processing"
    assert task["nfrIds"] == ["nfr-recovery-objective"]
    assert not any(story.get("storyType") == "DESIGN" for story in result.bundle["stories"])


def test_template_catalog_validates_but_does_not_copy_effort() -> None:
    catalog = read_template_catalog(ASSETS / "sow-template.xlsx")
    result = compile_fixture("greenfield")
    assert len(catalog.base_units) == 37
    assert all(
        not hasattr(rule, "person_days") and not hasattr(rule, "base_effort")
        for rule in catalog.base_units.values()
    )
    assert all(
        "personDays" not in task and "baseEffort" not in task
        for task in result.bundle["tasks"]
    )


def test_replaced_slice_drops_old_story_ac_task_and_preserves_unaffected() -> None:
    scope = fixture("brownfield", "scope.json")
    delivery = fixture("brownfield", "delivery.json")
    delivery["scopeSha256"] = sha256_bytes(canonical_json_bytes(scope))
    previous = copy.deepcopy(delivery)
    previous["stories"].append(
        {
            "storyId": "story-old-notification",
            "featureIds": ["feature-refund-notification"],
            "storyType": "IMPLEMENTATION",
            "name": "旧通知实现",
            "description": "应被完整替换。",
            "uatRelevant": True,
        }
    )
    previous["acceptanceCriteria"].append(
        {
            "acceptanceCriterionId": "ac-old-notification",
            "storyId": "story-old-notification",
            "sequence": 1,
            "name": "旧通知可用",
            "rationale": "旧结果。",
        }
    )
    previous["tasks"].append(
        {
            "taskId": "task-old-notification",
            "storyId": "story-old-notification",
            "taskKind": "IMPLEMENTATION",
            "name": "实现旧通知",
            "baseUnit": "BU-BUSINESS-SERVICE-API",
            "workMode": "新建",
            "workModeRationale": "旧任务。",
            "complexity": "M",
            "acceptanceCriterionIds": ["ac-old-notification"],
            "designItemIds": ["design-item-refund-orchestration"],
            "integrationIds": [],
            "nfrIds": [],
            "dependsOnTaskIds": [],
            "rationale": "旧任务应删除。",
        }
    )
    plan = plan_for(scope, "SLICE_COMPILE")
    candidate = delivery_slice(delivery, scope, plan)
    result = compile_delivery(
        scope,
        previous,
        candidate,
        id_decisions(candidate, previous),
        plan,
        read_template_catalog(ASSETS / "sow-template.xlsx"),
    )
    all_ids = {
        item[id_field]
        for collection, (_kind, id_field) in COLLECTION_TYPES.items()
        for item in result.bundle[collection]
    }
    assert not result.diagnostics
    assert {
        "story-old-notification",
        "ac-old-notification",
        "task-old-notification",
    }.isdisjoint(all_ids)


def test_unknown_template_base_unit_blocks_delivery() -> None:
    scope = fixture("greenfield", "scope.json")
    delivery = fixture("greenfield", "delivery.json")
    delivery["tasks"][0]["baseUnit"] = "BU-UNKNOWN"
    plan = plan_for(scope)
    candidate = delivery_slice(delivery, scope, plan)
    result = compile_delivery(
        scope,
        None,
        candidate,
        id_decisions(candidate),
        plan,
        read_template_catalog(ASSETS / "sow-template.xlsx"),
    )
    assert "DELIVERY_BASE_UNIT_UNKNOWN" in diagnostic_codes(result)


def test_dependency_cycle_blocks_delivery() -> None:
    scope = fixture("brownfield", "scope.json")
    delivery = fixture("brownfield", "delivery.json")
    delivery["tasks"][0]["dependsOnTaskIds"] = ["task-refund-orchestration"]
    delivery["dependencies"].append(
        {
            "dependencyId": "dependency-build-before-design",
            "predecessorTaskId": "task-refund-orchestration",
            "successorTaskId": "task-refund-recovery-design",
            "rationale": "合成循环。",
        }
    )
    plan = plan_for(scope)
    candidate = delivery_slice(delivery, scope, plan)
    result = compile_delivery(
        scope,
        None,
        candidate,
        id_decisions(candidate),
        plan,
        read_template_catalog(ASSETS / "sow-template.xlsx"),
    )
    assert "DELIVERY_DEPENDENCY_CYCLE" in diagnostic_codes(result)
