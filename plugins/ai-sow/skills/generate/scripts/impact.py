from __future__ import annotations

from collections.abc import Mapping, Sequence

from models import ImpactPlan, InputChangeSet


SCOPE_LINK_COLLECTIONS = (
    "commitments",
    "effectiveStartItems",
    "designItems",
    "designDecisions",
    "integrations",
    "nfrs",
    "assumptions",
)
SCOPE_ID_FIELDS = (
    "commitmentId",
    "effectiveStartItemId",
    "designItemId",
    "designDecisionId",
    "integrationId",
    "nfrId",
    "assumptionId",
)
ESCALATION_RANK = {"NONE": 0, "FEATURE": 1, "DOMAIN": 2, "FULL": 3}


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _ids(value: object) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _features(scope: Mapping[str, object] | None) -> list[Mapping[str, object]]:
    return _mappings(scope.get("features")) if scope is not None else []


def _feature_order(
    previous_scope: Mapping[str, object] | None,
    candidate_scope: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    ordered: list[str] = []
    for scope in (previous_scope, candidate_scope):
        for feature in _features(scope):
            feature_id = feature.get("featureId")
            if isinstance(feature_id, str) and feature_id not in ordered:
                ordered.append(feature_id)
    return tuple(ordered)


def _source_refs(value: Mapping[str, object]) -> list[Mapping[str, object]]:
    return _mappings(value.get("sourceRefs"))


def _ref_matches(ref: Mapping[str, object], change) -> bool:
    if ref.get("sourceId") != change.source_id:
        return False
    return ref.get("anchorId") == change.anchor_id or (
        change.previous_sha256 is not None and ref.get("sha256") == change.previous_sha256
    )


def _scope_object_feature_sets(
    scope: Mapping[str, object] | None,
) -> tuple[list[tuple[Mapping[str, object], set[str]]], dict[str, set[str]]]:
    if scope is None:
        return [], {}
    features = _features(scope)
    epic_features: dict[str, set[str]] = {}
    object_features: dict[str, set[str]] = {}
    linked: list[tuple[Mapping[str, object], set[str]]] = []
    for feature in features:
        feature_id = feature.get("featureId")
        epic_id = feature.get("epicId")
        if not isinstance(feature_id, str):
            continue
        if isinstance(epic_id, str):
            epic_features.setdefault(epic_id, set()).add(feature_id)
        linked.append((feature, {feature_id}))
        object_features[feature_id] = {feature_id}
    for epic in _mappings(scope.get("epics")):
        epic_id = epic.get("epicId")
        feature_ids = set(epic_features.get(str(epic_id), set()))
        linked.append((epic, feature_ids))
        if isinstance(epic_id, str):
            object_features[epic_id] = feature_ids
    for collection, id_field in zip(SCOPE_LINK_COLLECTIONS, SCOPE_ID_FIELDS, strict=True):
        for item in _mappings(scope.get(collection)):
            feature_ids = set(_ids(item.get("featureIds")))
            linked.append((item, feature_ids))
            object_id = item.get(id_field)
            if isinstance(object_id, str):
                object_features[object_id] = feature_ids
    return linked, object_features


def _seed_features(
    changes: InputChangeSet,
    scope: Mapping[str, object] | None,
) -> tuple[set[str], bool]:
    linked, _ = _scope_object_feature_sets(scope)
    affected: set[str] = set()
    unmapped_structured = False
    for change in changes.source_changes:
        if change.change in {"ADDED", "MOVED_UNCHANGED"}:
            continue
        matched = False
        for item, feature_ids in linked:
            if any(_ref_matches(ref, change) for ref in _source_refs(item)):
                affected.update(feature_ids)
                matched = True
        if not matched:
            unmapped_structured = True

    features = _features(scope)
    for responsibility_id in changes.responsibility_ids:
        matched = False
        for feature in features:
            if responsibility_id in _ids(feature.get("responsibilityBoundaryIds")):
                feature_id = feature.get("featureId")
                if isinstance(feature_id, str):
                    affected.add(feature_id)
                    matched = True
        for item, feature_ids in linked:
            if item.get("responsibilityBoundaryId") == responsibility_id:
                affected.update(feature_ids)
                matched = True
        if not matched:
            unmapped_structured = True

    for answer_id in changes.answer_ids:
        matched = False
        for item, feature_ids in linked:
            for ref in _source_refs(item):
                locator = ref.get("locator")
                if ref.get("anchorId") == answer_id or (
                    isinstance(locator, str) and f"question:{answer_id}" in locator
                ):
                    affected.update(feature_ids)
                    matched = True
        if not matched:
            unmapped_structured = True
    return affected, unmapped_structured


def _closure(
    initial: set[str],
    scope: Mapping[str, object] | None,
    delivery: Mapping[str, object] | None,
) -> set[str]:
    affected = set(initial)
    _linked, object_features = _scope_object_feature_sets(scope)
    scope_feature_sets: list[set[str]] = []
    if scope is not None:
        for collection in SCOPE_LINK_COLLECTIONS:
            scope_feature_sets.extend(
                set(_ids(item.get("featureIds")))
                for item in _mappings(scope.get(collection))
            )
    story_features: dict[str, set[str]] = {}
    task_features: dict[str, set[str]] = {}
    dependencies: list[tuple[str, str]] = []
    if delivery is not None:
        for story in _mappings(delivery.get("stories")):
            story_id = story.get("storyId")
            if isinstance(story_id, str):
                story_features[story_id] = set(_ids(story.get("featureIds")))
        for task in _mappings(delivery.get("tasks")):
            task_id = task.get("taskId")
            story_id = task.get("storyId")
            if not isinstance(task_id, str):
                continue
            feature_ids = set(story_features.get(str(story_id), set()))
            for field in ("designItemIds", "integrationIds", "nfrIds"):
                for object_id in _ids(task.get(field)):
                    feature_ids.update(object_features.get(object_id, set()))
            task_features[task_id] = feature_ids
            for predecessor in _ids(task.get("dependsOnTaskIds")):
                dependencies.append((predecessor, task_id))
        for dependency in _mappings(delivery.get("dependencies")):
            predecessor = dependency.get("predecessorTaskId")
            successor = dependency.get("successorTaskId")
            if isinstance(predecessor, str) and isinstance(successor, str):
                dependencies.append((predecessor, successor))

    changed = True
    while changed:
        changed = False
        for feature_ids in scope_feature_sets:
            if affected & feature_ids and not feature_ids <= affected:
                affected.update(feature_ids)
                changed = True
        for feature_ids in story_features.values():
            if affected & feature_ids and not feature_ids <= affected:
                affected.update(feature_ids)
                changed = True
        for feature_ids in task_features.values():
            if affected & feature_ids and not feature_ids <= affected:
                affected.update(feature_ids)
                changed = True
        for predecessor, successor in dependencies:
            pair_features = task_features.get(predecessor, set()) | task_features.get(
                successor, set()
            )
            if affected & pair_features and not pair_features <= affected:
                affected.update(pair_features)
                changed = True
    return affected


def _ordered(selected: set[str], order: Sequence[str]) -> tuple[str, ...]:
    result = [feature_id for feature_id in order if feature_id in selected]
    result.extend(sorted(selected - set(result)))
    return tuple(result)


def compute_impact_plan(
    changes: InputChangeSet,
    *,
    previous_scope: Mapping[str, object] | None,
    previous_delivery: Mapping[str, object] | None,
    baseline_generation_id: str | None,
    baseline_revision_id: str | None,
    template_changed: bool = False,
    renderer_changed: bool = False,
    compiler_contract_changed: bool = False,
    pending_run: bool = False,
) -> ImpactPlan:
    order = _feature_order(previous_scope)
    all_features = set(order)
    changed_source_ids = tuple(
        sorted({change.source_id for change in changes.source_changes})
    )
    changed_anchor_ids = tuple(
        sorted({change.anchor_id for change in changes.source_changes})
    )

    if compiler_contract_changed:
        action = "FULL_COMPILE"
        affected = all_features
        escalation = "FULL"
        reasons = ("COMPILER_CONTRACT_CHANGED",)
    elif baseline_generation_id is None or previous_scope is None:
        action = "FULL_COMPILE"
        affected = all_features
        escalation = "FULL"
        reasons = ("NO_CURRENT_GENERATION",)
    elif pending_run:
        action = "RESUME_PENDING"
        affected, unmapped = _seed_features(changes, previous_scope)
        affected = _closure(affected, previous_scope, previous_delivery)
        escalation = "FULL" if unmapped else ("FEATURE" if affected else "NONE")
        if unmapped:
            affected = all_features
        reasons = ("PENDING_RUN_EXISTS",)
    elif changes.exact_match and not template_changed and not renderer_changed:
        action = "REUSE"
        affected = set()
        escalation = "NONE"
        reasons = ("INPUT_AND_RENDERER_UNCHANGED",)
    elif changes.exact_match:
        action = "RENDER_ONLY"
        affected = set()
        escalation = "NONE"
        reasons = tuple(
            reason
            for changed, reason in (
                (template_changed, "TEMPLATE_CHANGED"),
                (renderer_changed, "RENDERER_CHANGED"),
            )
            if changed
        )
    else:
        action = "SLICE_COMPILE"
        affected, unmapped = _seed_features(changes, previous_scope)
        if unmapped:
            affected = all_features
            escalation = "FULL"
            reasons = ("CHANGE_MAPPING_UNKNOWN",)
        else:
            affected = _closure(affected, previous_scope, previous_delivery)
            escalation = "FEATURE" if affected else "NONE"
            reasons = ("INPUT_CHANGED",)

    reasons = tuple(reasons) + tuple(
        f"ADDED_ANCHOR:{change.anchor_id}"
        for change in changes.source_changes
        if change.change == "ADDED"
    )
    return ImpactPlan(
        action=action,
        baseline_generation_id=baseline_generation_id,
        baseline_revision_id=baseline_revision_id,
        changed_source_ids=changed_source_ids,
        changed_anchor_ids=changed_anchor_ids,
        affected_feature_ids=_ordered(affected, order),
        escalation=escalation,  # type: ignore[arg-type]
        reason_codes=tuple(sorted(set(reasons))),
    )


def finalize_impact_plan(
    plan: ImpactPlan,
    candidate_slice: Mapping[str, object],
    previous_scope: Mapping[str, object] | None,
    previous_delivery: Mapping[str, object] | None,
) -> ImpactPlan:
    candidate_scope: Mapping[str, object] = {
        "features": candidate_slice.get("features", [])
    }
    order = _feature_order(previous_scope, candidate_scope)
    all_features = set(order)
    affected = set(plan.affected_feature_ids)
    escalation = plan.escalation
    reasons = set(plan.reason_codes)
    added_anchor_ids = {
        reason.removeprefix("ADDED_ANCHOR:")
        for reason in plan.reason_codes
        if reason.startswith("ADDED_ANCHOR:")
    }
    mappings = _mappings(candidate_slice.get("newAnchorMappings"))
    mapped_anchor_ids: set[str] = set()

    feature_domains: dict[str, str] = {}
    for scope in (previous_scope, candidate_scope):
        for feature in _features(scope):
            feature_id = feature.get("featureId")
            domain_id = feature.get("domainId")
            if isinstance(feature_id, str) and isinstance(domain_id, str):
                feature_domains[feature_id] = domain_id

    for mapping in mappings:
        source_ref = mapping.get("sourceRef")
        anchor_id = source_ref.get("anchorId") if isinstance(source_ref, Mapping) else None
        if not isinstance(anchor_id, str) or anchor_id not in added_anchor_ids:
            continue
        mapped_anchor_ids.add(anchor_id)
        confidence = mapping.get("confidence")
        feature_id = mapping.get("featureId")
        domain_id = mapping.get("domainId")
        if confidence == "UNIQUE" and isinstance(feature_id, str) and feature_id in all_features:
            affected.add(feature_id)
            if ESCALATION_RANK[escalation] < ESCALATION_RANK["FEATURE"]:
                escalation = "FEATURE"
            reasons.add("ADDED_ANCHOR_UNIQUE")
        elif confidence == "DOMAIN" and isinstance(domain_id, str):
            domain_features = {
                identifier
                for identifier, candidate_domain in feature_domains.items()
                if candidate_domain == domain_id
            }
            if not domain_features:
                escalation = "FULL"
                affected = all_features
                reasons.add("ADDED_ANCHOR_UNKNOWN")
            else:
                affected.update(domain_features)
                if ESCALATION_RANK[escalation] < ESCALATION_RANK["DOMAIN"]:
                    escalation = "DOMAIN"
                reasons.add("ADDED_ANCHOR_DOMAIN")
        else:
            escalation = "FULL"
            affected = all_features
            reasons.add("ADDED_ANCHOR_UNKNOWN")

    if added_anchor_ids - mapped_anchor_ids:
        escalation = "FULL"
        affected = all_features
        reasons.add("ADDED_ANCHOR_UNMAPPED")
    if escalation == "FULL":
        affected = all_features
    else:
        affected = _closure(affected, previous_scope, previous_delivery)

    return ImpactPlan(
        action=plan.action,
        baseline_generation_id=plan.baseline_generation_id,
        baseline_revision_id=plan.baseline_revision_id,
        changed_source_ids=plan.changed_source_ids,
        changed_anchor_ids=plan.changed_anchor_ids,
        affected_feature_ids=_ordered(affected, order),
        escalation=escalation,
        reason_codes=tuple(sorted(reasons)),
    )
