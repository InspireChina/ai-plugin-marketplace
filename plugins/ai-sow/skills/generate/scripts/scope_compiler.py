from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from contracts import (
    canonical_json_bytes,
    load_schema_registry,
    sha256_bytes,
    validate_contract,
    validate_id_decisions,
)
from models import Diagnostic, ImpactPlan, ScopeCompilation


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_REGISTRY = load_schema_registry(SKILL_ROOT)
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
FEATURE_LINKED_COLLECTIONS = {
    "commitments",
    "effectiveStartItems",
    "designItems",
    "designDecisions",
    "integrations",
    "nfrs",
    "assumptions",
}
CLARIFICATION_FIELDS = frozenset(
    {"name", "summary", "description", "rationale", "sourceRefs"}
)


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _sort_diagnostics(values: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(values, key=lambda item: (item.path, item.code, item.message)))


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _ids(value: object) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _impact_value(plan: ImpactPlan) -> dict[str, object]:
    raw = asdict(plan)
    return {
        "action": raw["action"],
        "baselineGenerationId": raw["baseline_generation_id"],
        "baselineRevisionId": raw["baseline_revision_id"],
        "changedSourceIds": list(raw["changed_source_ids"]),
        "changedAnchorIds": list(raw["changed_anchor_ids"]),
        "affectedFeatureIds": list(raw["affected_feature_ids"]),
        "escalation": raw["escalation"],
        "reasonCodes": list(raw["reason_codes"]),
    }


def impact_plan_sha256(plan: ImpactPlan) -> str:
    return sha256_bytes(canonical_json_bytes(_impact_value(plan)))


def _all_objects(bundle: Mapping[str, object] | None) -> dict[tuple[str, str], Mapping[str, object]]:
    result: dict[tuple[str, str], Mapping[str, object]] = {}
    if bundle is None:
        return result
    for collection, (object_type, id_field) in COLLECTION_TYPES.items():
        for item in _mappings(bundle.get(collection)):
            object_id = item.get(id_field)
            if isinstance(object_id, str):
                result[(object_type, object_id)] = item
    return result


def _without_clarifications(value: Mapping[str, object]) -> dict[str, object]:
    return {key: item for key, item in value.items() if key not in CLARIFICATION_FIELDS}


def _validate_id_ledger(
    candidate: Mapping[str, object],
    previous: Mapping[str, object] | None,
    id_decisions: object,
) -> list[Diagnostic]:
    diagnostics = list(validate_id_decisions(id_decisions, SCHEMA_REGISTRY))
    if not isinstance(id_decisions, Mapping):
        return diagnostics
    decisions = _mappings(id_decisions.get("decisions"))
    by_identity = {
        (str(item.get("objectType")), str(item.get("objectId"))): item
        for item in decisions
    }
    previous_objects = _all_objects(previous)
    candidate_objects = _all_objects(candidate)
    for identity, item in candidate_objects.items():
        decision = by_identity.get(identity)
        if decision is None:
            diagnostics.append(
                _diagnostic(
                    "SCOPE_ID_DECISION_MISSING",
                    "Scope 切片中的每个对象必须有 ID 决定。",
                    f"/{identity[0]}/{identity[1]}",
                )
            )
            continue
        disposition = decision.get("disposition")
        previous_id = decision.get("previousId")
        previous_item = (
            previous_objects.get((identity[0], str(previous_id)))
            if isinstance(previous_id, str)
            else None
        )
        if disposition == "NEW" and identity in previous_objects:
            diagnostics.append(
                _diagnostic(
                    "SCOPE_ID_NEW_ALREADY_EXISTS",
                    "NEW 对象不得复用既有 ID。",
                    f"/{identity[0]}/{identity[1]}",
                )
            )
        elif disposition == "UNCHANGED":
            if previous_item is None or canonical_json_bytes(previous_item) != canonical_json_bytes(item):
                diagnostics.append(
                    _diagnostic(
                        "SCOPE_ID_UNCHANGED_SEMANTICS_DIFFER",
                        "UNCHANGED 对象的规范语义必须完全相同。",
                        f"/{identity[0]}/{identity[1]}",
                    )
                )
        elif disposition == "CLARIFIED":
            if previous_item is None or canonical_json_bytes(
                _without_clarifications(previous_item)
            ) != canonical_json_bytes(_without_clarifications(item)):
                diagnostics.append(
                    _diagnostic(
                        "SCOPE_ID_CLARIFICATION_CHANGED_MEANING",
                        "CLARIFIED 只能修改说明性字段，不得改变交付含义。",
                        f"/{identity[0]}/{identity[1]}",
                    )
                )
        elif disposition == "CHANGED" and previous_item is None:
            diagnostics.append(
                _diagnostic(
                    "SCOPE_ID_CHANGED_PREVIOUS_MISSING",
                    "CHANGED 必须引用存在的旧对象。",
                    f"/{identity[0]}/{identity[1]}",
                )
            )
    for identity in by_identity:
        if identity not in candidate_objects:
            diagnostics.append(
                _diagnostic(
                    "SCOPE_ID_DECISION_ORPHAN",
                    "ID 决定引用了切片中不存在的对象。",
                    f"/{identity[0]}/{identity[1]}",
                )
            )
    return diagnostics


def _anchor_index(anchors: Sequence[object]) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for anchor in anchors:
        if isinstance(anchor, Mapping):
            source_id = anchor.get("sourceId", anchor.get("source_id"))
            anchor_id = anchor.get("anchorId", anchor.get("anchor_id"))
            digest = anchor.get("sha256")
        else:
            source_id = getattr(anchor, "source_id", None)
            anchor_id = getattr(anchor, "anchor_id", None)
            digest = getattr(anchor, "sha256", None)
        if all(isinstance(value, str) for value in (source_id, anchor_id, digest)):
            result.add((str(source_id), str(anchor_id), str(digest)))
    return result


def _validate_scope(
    bundle: Mapping[str, object],
    anchors: Sequence[object],
) -> list[Diagnostic]:
    diagnostics = list(validate_contract(bundle, "scope-bundle.schema.json", SCHEMA_REGISTRY))
    anchor_keys = _anchor_index(anchors)
    feature_ids = {
        str(item.get("featureId")) for item in _mappings(bundle.get("features"))
    }
    epic_ids = {str(item.get("epicId")) for item in _mappings(bundle.get("epics"))}
    design_ids = {
        str(item.get("designItemId")) for item in _mappings(bundle.get("designItems"))
    }
    effective_ids = {
        str(item.get("effectiveStartItemId"))
        for item in _mappings(bundle.get("effectiveStartItems"))
    }
    integration_ids = {
        str(item.get("integrationId")) for item in _mappings(bundle.get("integrations"))
    }
    nfr_ids = {str(item.get("nfrId")) for item in _mappings(bundle.get("nfrs"))}
    responsibility_ids = {
        str(item.get("responsibilityBoundaryId"))
        for item in _mappings(bundle.get("responsibilityBoundaries"))
    }
    vendor_responsibility_ids = {
        str(item.get("responsibilityBoundaryId"))
        for item in _mappings(bundle.get("responsibilityBoundaries"))
        if item.get("party") == "VENDOR"
    }

    seen_ids: set[tuple[str, str]] = set()
    for collection, (_object_type, id_field) in COLLECTION_TYPES.items():
        for index, item in enumerate(_mappings(bundle.get(collection))):
            object_id = item.get(id_field)
            identity = (collection, str(object_id))
            if identity in seen_ids:
                diagnostics.append(
                    _diagnostic(
                        "SCOPE_ID_DUPLICATE",
                        "同一 Scope 集合内对象 ID 不得重复。",
                        f"/{collection}/{index}/{id_field}",
                    )
                )
            seen_ids.add(identity)
            for ref_index, source_ref in enumerate(_mappings(item.get("sourceRefs"))):
                key = (
                    str(source_ref.get("sourceId")),
                    str(source_ref.get("anchorId")),
                    str(source_ref.get("sha256")),
                )
                if key not in anchor_keys:
                    diagnostics.append(
                        _diagnostic(
                            "SCOPE_SOURCE_REF_UNKNOWN",
                            "Scope 来源引用未绑定当前输入锚点。",
                            f"/{collection}/{index}/sourceRefs/{ref_index}",
                        )
                    )

    for index, feature in enumerate(_mappings(bundle.get("features"))):
        if feature.get("epicId") not in epic_ids:
            diagnostics.append(
                _diagnostic("SCOPE_EPIC_UNKNOWN", "Feature 引用了未知 Epic。", f"/features/{index}/epicId")
            )
        for responsibility_id in _ids(feature.get("responsibilityBoundaryIds")):
            if responsibility_id not in responsibility_ids:
                diagnostics.append(
                    _diagnostic(
                        "SCOPE_RESPONSIBILITY_UNKNOWN",
                        "Feature 引用了未知责任边界。",
                        f"/features/{index}/responsibilityBoundaryIds",
                    )
                )
        decision = feature.get("scopeDecision")
        if not isinstance(decision, Mapping):
            continue
        if decision.get("decision") == "IN_SCOPE" and not (
            set(_ids(feature.get("responsibilityBoundaryIds")))
            & vendor_responsibility_ids
        ):
            diagnostics.append(
                _diagnostic(
                    "SCOPE_IN_SCOPE_VENDOR_RESPONSIBILITY_REQUIRED",
                    "进入供应商 SOW 的 IN_SCOPE Feature 必须绑定至少一项供应商责任边界。",
                    f"/features/{index}/responsibilityBoundaryIds",
                )
            )
        for field, known, code in (
            ("designItemIds", design_ids, "SCOPE_DESIGN_UNKNOWN"),
            ("effectiveStartItemIds", effective_ids, "SCOPE_EFFECTIVE_START_UNKNOWN"),
            ("requiredIntegrationIds", integration_ids, "SCOPE_INTEGRATION_UNKNOWN"),
            ("requiredNfrIds", nfr_ids, "SCOPE_NFR_UNKNOWN"),
        ):
            if any(identifier not in known for identifier in _ids(decision.get(field))):
                diagnostics.append(
                    _diagnostic(code, "Feature 范围决定引用了未知对象。", f"/features/{index}/scopeDecision/{field}")
                )

    for collection in FEATURE_LINKED_COLLECTIONS:
        for index, item in enumerate(_mappings(bundle.get(collection))):
            unknown = set(_ids(item.get("featureIds"))) - feature_ids
            if unknown:
                diagnostics.append(
                    _diagnostic(
                        "SCOPE_FEATURE_LINK_UNKNOWN",
                        "Scope 对象引用了未知 Feature。",
                        f"/{collection}/{index}/featureIds",
                    )
                )
            responsibility_id = item.get("responsibilityBoundaryId")
            if isinstance(responsibility_id, str) and responsibility_id not in responsibility_ids:
                diagnostics.append(
                    _diagnostic(
                        "SCOPE_RESPONSIBILITY_UNKNOWN",
                        "Scope 对象引用了未知责任边界。",
                        f"/{collection}/{index}/responsibilityBoundaryId",
                    )
                )
    for index, commitment in enumerate(_mappings(bundle.get("commitments"))):
        if commitment.get("treatment") == "NEEDS_DECISION":
            diagnostics.append(
                _diagnostic(
                    "SCOPE_CONFLICT_UNRESOLVED",
                    "会改变范围的往期承诺冲突必须先建立固定边界。",
                    f"/commitments/{index}/treatment",
                )
            )
    return diagnostics


def _merge_collection(
    collection: str,
    previous: Mapping[str, object],
    candidate: Mapping[str, object],
    replaced: set[str],
    diagnostics: list[Diagnostic],
) -> list[object]:
    _object_type, id_field = COLLECTION_TYPES[collection]
    old_items = list(_mappings(previous.get(collection)))
    new_items = list(_mappings(candidate.get(collection)))
    candidate_ids = {
        str(item.get(id_field)) for item in new_items if isinstance(item.get(id_field), str)
    }
    old_features = {
        str(item.get("featureId")): item for item in _mappings(previous.get("features"))
    }
    remove_indexes: list[int] = []
    for index, item in enumerate(old_items):
        should_remove = str(item.get(id_field)) in candidate_ids
        if collection == "features":
            should_remove = should_remove or item.get("featureId") in replaced
        elif collection == "epics":
            linked = {
                feature_id
                for feature_id, feature in old_features.items()
                if feature.get("epicId") == item.get("epicId")
            }
            should_remove = should_remove or bool(linked) and linked <= replaced
        elif collection in FEATURE_LINKED_COLLECTIONS:
            linked = set(_ids(item.get("featureIds")))
            if linked & replaced and not linked <= replaced:
                diagnostics.append(
                    _diagnostic(
                        "SCOPE_SHARED_OBJECT_REQUIRES_WIDENING",
                        "共享 Scope 对象跨越受影响闭包，必须扩大 ImpactPlan。",
                        f"/{collection}/{index}",
                    )
                )
            should_remove = should_remove or bool(linked & replaced and linked <= replaced)
        if should_remove:
            remove_indexes.append(index)
    insertion = min(remove_indexes, default=len(old_items))
    retained = [item for index, item in enumerate(old_items) if index not in remove_indexes]
    return retained[:insertion] + new_items + retained[insertion:]


def _merge_scope(
    previous: Mapping[str, object] | None,
    candidate: Mapping[str, object],
    impact: ImpactPlan,
    diagnostics: list[Diagnostic],
) -> dict[str, object]:
    replaced = set(_ids(candidate.get("replacesFeatureIds")))
    expected = set() if previous is None else set(impact.affected_feature_ids)
    if replaced != expected:
        diagnostics.append(
            _diagnostic(
                "SCOPE_REPLACEMENT_CLOSURE_MISMATCH",
                "Scope 切片替换的 Feature 必须与最终 ImpactPlan 完全一致；初次编译必须为空。",
                "/replacesFeatureIds",
            )
        )
    if previous is None or impact.action == "FULL_COMPILE":
        collections = {
            collection: list(_mappings(candidate.get(collection)))
            for collection in COLLECTION_TYPES
        }
    else:
        collections = {
            collection: _merge_collection(
                collection,
                previous,
                candidate,
                replaced,
                diagnostics,
            )
            for collection in COLLECTION_TYPES
        }
    return {
        "contract": "ai-sow-scope-bundle-v1",
        "inputRevisionId": candidate.get("inputRevisionId"),
        **collections,
        "responsibilityBoundaries": list(
            _mappings(candidate.get("responsibilityBoundaries"))
        ),
    }


def _metrics(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object],
) -> dict[str, object]:
    before = _all_objects(previous)
    after = _all_objects(current)
    before_ids = set(before)
    after_ids = set(after)
    created = sorted(identifier for identifier in after_ids - before_ids)
    removed = sorted(identifier for identifier in before_ids - after_ids)
    preserved = sorted(
        identifier
        for identifier in before_ids & after_ids
        if canonical_json_bytes(before[identifier]) == canonical_json_bytes(after[identifier])
    )
    changed = sorted((before_ids & after_ids) - set(preserved))

    def labels(values: Sequence[tuple[str, str]]) -> tuple[str, ...]:
        return tuple(f"{object_type}:{object_id}" for object_type, object_id in values)

    return {
        "createdIds": labels(created),
        "preservedIds": labels(preserved),
        "removedIds": labels(removed),
        "changedIds": labels(changed),
        "createdCount": len(created),
        "preservedCount": len(preserved),
        "removedCount": len(removed),
        "changedCount": len(changed),
    }


def compile_scope(
    input_manifest: Mapping[str, object],
    input_anchors: Sequence[object],
    previous_scope: Mapping[str, object] | None,
    scope_slice: Mapping[str, object],
    id_decisions: object,
    impact: ImpactPlan,
) -> ScopeCompilation:
    diagnostics = list(
        validate_contract(scope_slice, "scope-slice.schema.json", SCHEMA_REGISTRY)
    )
    diagnostics.extend(
        validate_contract(input_manifest, "input-manifest.schema.json", SCHEMA_REGISTRY)
    )
    if scope_slice.get("inputRevisionId") != input_manifest.get("revisionId"):
        diagnostics.append(
            _diagnostic(
                "SCOPE_INPUT_REVISION_MISMATCH",
                "Scope 切片未绑定当前 pending input revision。",
                "/inputRevisionId",
            )
        )
    if scope_slice.get("impactPlanSha256") != impact_plan_sha256(impact):
        diagnostics.append(
            _diagnostic(
                "SCOPE_IMPACT_HASH_MISMATCH",
                "Scope 切片未绑定最终 ImpactPlan。",
                "/impactPlanSha256",
            )
        )
    diagnostics.extend(_validate_id_ledger(scope_slice, previous_scope, id_decisions))
    bundle = _merge_scope(previous_scope, scope_slice, impact, diagnostics)
    diagnostics.extend(_validate_scope(bundle, input_anchors))
    metrics = _metrics(previous_scope, bundle)
    return ScopeCompilation(
        bundle=bundle,
        bundle_sha256=sha256_bytes(canonical_json_bytes(bundle)),
        impact=impact,
        metrics=metrics,
        diagnostics=_sort_diagnostics(diagnostics),
    )
