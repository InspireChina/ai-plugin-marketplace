from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Literal

from contracts import canonical_json_bytes, sha256_bytes
from models import Diagnostic, ImpactPlan, RunPlan


SCOPE_COLLECTION_TYPES = {
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
SCOPE_COLLECTIONS = tuple(SCOPE_COLLECTION_TYPES)
DELIVERY_COLLECTION_TYPES = {
    "stories": ("STORY", "storyId"),
    "acceptanceCriteria": ("ACCEPTANCE_CRITERION", "acceptanceCriterionId"),
    "tasks": ("TASK", "taskId"),
    "dependencies": ("DEPENDENCY", "dependencyId"),
}
SCOPE_CLARIFICATION_FIELDS = frozenset(
    {"name", "summary", "description", "rationale", "sourceRefs"}
)
DELIVERY_CLARIFICATION_FIELDS = frozenset({"name", "description", "rationale"})


def _impact_value(impact: ImpactPlan) -> dict[str, object]:
    return {
        "action": impact.action,
        "baselineGenerationId": impact.baseline_generation_id,
        "baselineRevisionId": impact.baseline_revision_id,
        "changedSourceIds": list(impact.changed_source_ids),
        "changedAnchorIds": list(impact.changed_anchor_ids),
        "affectedFeatureIds": list(impact.affected_feature_ids),
        "escalation": impact.escalation,
        "reasonCodes": list(impact.reason_codes),
    }


def impact_plan_sha256(impact: ImpactPlan) -> str:
    return sha256_bytes(canonical_json_bytes(_impact_value(impact)))


def _mappings(value: object) -> list[Mapping[str, object]]:
    return (
        [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, list)
        else []
    )


def _objects(
    bundle: Mapping[str, object] | None,
    collection_types: Mapping[str, tuple[str, str]],
) -> dict[tuple[str, str], Mapping[str, object]]:
    if bundle is None:
        return {}
    result: dict[tuple[str, str], Mapping[str, object]] = {}
    for collection, (object_type, id_field) in collection_types.items():
        for item in _mappings(bundle.get(collection)):
            object_id = item.get(id_field)
            if isinstance(object_id, str):
                result[(object_type, object_id)] = item
    return result


def _without_fields(
    value: Mapping[str, object], fields: frozenset[str]
) -> dict[str, object]:
    return {key: item for key, item in value.items() if key not in fields}


def build_id_decisions(
    candidate: Mapping[str, object],
    previous: Mapping[str, object] | None,
    *,
    stage: Literal["scope", "delivery"],
) -> tuple[dict[str, object], tuple[Diagnostic, ...]]:
    collection_types = (
        SCOPE_COLLECTION_TYPES if stage == "scope" else DELIVERY_COLLECTION_TYPES
    )
    clarification_fields = (
        SCOPE_CLARIFICATION_FIELDS
        if stage == "scope"
        else DELIVERY_CLARIFICATION_FIELDS
    )
    previous_objects = _objects(previous, collection_types)
    decisions: list[dict[str, object]] = []
    diagnostics: list[Diagnostic] = []

    for collection, (object_type, id_field) in collection_types.items():
        for item in _mappings(candidate.get(collection)):
            object_id = item.get(id_field)
            if not isinstance(object_id, str):
                continue
            previous_item = previous_objects.get((object_type, object_id))
            if previous_item is None:
                decisions.append(
                    {
                        "objectType": object_type,
                        "objectId": object_id,
                        "disposition": "NEW",
                        "meaningPreserved": False,
                        "rationale": "该对象使用新的稳定 ID。",
                    }
                )
                continue
            if canonical_json_bytes(previous_item) == canonical_json_bytes(item):
                disposition = "UNCHANGED"
                rationale = "对象语义未变化，保留稳定 ID。"
            elif canonical_json_bytes(
                _without_fields(previous_item, clarification_fields)
            ) == canonical_json_bytes(_without_fields(item, clarification_fields)):
                disposition = "CLARIFIED"
                rationale = "仅说明性字段变化，保留稳定 ID。"
            else:
                diagnostics.append(
                    Diagnostic(
                        code="CANDIDATE_STABLE_ID_SEMANTICS_CHANGED",
                        message="对象语义发生变化时必须分配新的稳定 ID。",
                        path=f"/{collection}/{object_id}",
                        details={"stage": stage, "objectType": object_type},
                    )
                )
                continue
            decisions.append(
                {
                    "objectType": object_type,
                    "objectId": object_id,
                    "disposition": disposition,
                    "previousId": object_id,
                    "meaningPreserved": True,
                    "rationale": rationale,
                }
            )

    return (
        {"contract": "ai-sow-id-decisions-v1", "decisions": decisions},
        tuple(diagnostics),
    )


def scope_candidate_skeleton(
    plan: RunPlan,
    input_manifest: Mapping[str, object],
) -> dict[str, object]:
    return {
        "contract": "ai-sow-scope-slice-v1",
        "inputRevisionId": plan.target_revision_id,
        "impactPlanSha256": impact_plan_sha256(plan.impact),
        "replacesFeatureIds": (
            []
            if plan.impact.baseline_generation_id is None
            else list(plan.impact.affected_feature_ids)
        ),
        "newAnchorMappings": [],
        **{collection: [] for collection in SCOPE_COLLECTIONS},
        "responsibilityBoundaries": deepcopy(
            input_manifest.get("responsibilityBoundaries", [])
        ),
    }


def refresh_scope_candidate(
    plan: RunPlan,
    input_manifest: Mapping[str, object],
    authored: Mapping[str, object],
) -> dict[str, object]:
    candidate = scope_candidate_skeleton(plan, input_manifest)
    for field in ("newAnchorMappings", *SCOPE_COLLECTIONS):
        if field in authored:
            candidate[field] = deepcopy(authored[field])
    return candidate


def delivery_candidate_skeleton(
    plan: RunPlan,
    scope: Mapping[str, object],
) -> dict[str, object]:
    return {
        "contract": "ai-sow-delivery-slice-v3",
        "inputRevisionId": plan.target_revision_id,
        "scopeSha256": sha256_bytes(canonical_json_bytes(scope)),
        "impactPlanSha256": impact_plan_sha256(plan.impact),
        "replacesFeatureIds": (
            []
            if plan.impact.baseline_generation_id is None
            else list(plan.impact.affected_feature_ids)
        ),
        **{collection: [] for collection in DELIVERY_COLLECTION_TYPES},
    }


def refresh_delivery_candidate(
    plan: RunPlan,
    scope: Mapping[str, object],
    authored: Mapping[str, object],
) -> dict[str, object]:
    candidate = delivery_candidate_skeleton(plan, scope)
    for field in DELIVERY_COLLECTION_TYPES:
        if field in authored:
            candidate[field] = deepcopy(authored[field])
    return candidate
