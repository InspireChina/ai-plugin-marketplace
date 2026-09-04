from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path

from contracts import canonical_json_bytes, load_registry, sha256_bytes, validate_contract
from models import Diagnostic, ReplacementOutcome, TaskStandardCatalog


TOP_LEVEL_WRITE_OWNER: dict[str, str] = {
    "contract": "SCRIPT",
    "project": "SCRIPT",
    "inputItems": "STAGE_1",
    "scopeClosure": "STAGE_1",
    "epics": "STAGE_1",
    "features": "STAGE_1",
    "designItems": "STAGE_1",
    "integrations": "STAGE_1",
    "nfrs": "STAGE_1",
    "policyInstances": "STAGE_1",
    "scopeAnnotations": "STAGE_1",
    "stories": "STAGE_2",
    "acceptanceCriteria": "STAGE_2",
    "deliveryAnnotations": "STAGE_2",
    "tasks": "STAGE_3",
    "dependencies": "STAGE_3",
    "effectiveStartMatches": "STAGE_3",
    "estimationAnnotations": "STAGE_3",
    "decisions": "SCRIPT",
}

NODE_COLLECTIONS: dict[str, str] = {
    "inputItems": "inputItemId",
    "scopeClosure": "inputItemId",
    "epics": "epicId",
    "features": "featureId",
    "designItems": "designItemId",
    "integrations": "integrationId",
    "nfrs": "nfrId",
    "policyInstances": "policyInstanceId",
    "scopeAnnotations": "annotationId",
    "stories": "storyId",
    "acceptanceCriteria": "acceptanceCriterionId",
    "deliveryAnnotations": "annotationId",
    "tasks": "taskId",
    "dependencies": "dependencyId",
    "effectiveStartMatches": "taskId",
    "estimationAnnotations": "annotationId",
    "decisions": "decisionId",
}

_STAGE_RANK = {
    "SCRIPT": 0,
    "STAGE_1": 1,
    "STAGE_1_SOURCE_SCAN": 1,
    "STAGE_2": 2,
    "STAGE_3": 3,
}
_OWNER_STAGE = {"STAGE_1_SOURCE_SCAN": "STAGE_1"}
_CHECKPOINT_INVALIDATION = {
    "SCRIPT": ("SCOPE_CLOSURE", "STORY_AC", "TASK", "REVIEW", "DRAFT"),
    "STAGE_1": ("SCOPE_CLOSURE", "STORY_AC", "TASK", "REVIEW", "DRAFT"),
    "STAGE_1_SOURCE_SCAN": ("SCOPE_CLOSURE", "STORY_AC", "TASK", "REVIEW", "DRAFT"),
    "STAGE_2": ("STORY_AC", "TASK", "REVIEW", "DRAFT"),
    "STAGE_3": ("TASK", "REVIEW", "DRAFT"),
}
_NON_SEMANTIC_FIELDS: dict[str, frozenset[str]] = {
    "inputItems": frozenset(),
    "scopeClosure": frozenset(
        {
            "targetNodeIds",
            "assignedFeatureIds",
            "crossFeatureTargetIds",
        }
    ),
    "epics": frozenset({"name"}),
    "features": frozenset({"name"}),
    "designItems": frozenset({"name", "featureIds"}),
    "integrations": frozenset({"name", "featureIds", "responsibilityBoundaryIds"}),
    "nfrs": frozenset({"featureIds"}),
    "policyInstances": frozenset({"targetNodeIds"}),
    "scopeAnnotations": frozenset({"subjectIds"}),
    "stories": frozenset({"name"}),
    "acceptanceCriteria": frozenset(),
    "deliveryAnnotations": frozenset({"subjectIds"}),
    "tasks": frozenset({"name"}),
    "dependencies": frozenset(),
    "effectiveStartMatches": frozenset(),
    "estimationAnnotations": frozenset({"subjectIds"}),
    "decisions": frozenset(),
}
_NEXT_REGISTRY = load_registry(Path(__file__).resolve().parents[1] / "contracts")


class SitAssignmentError(ValueError):
    def __init__(self, category: str, code: str, subject_id: str) -> None:
        self.category = category
        self.code = code
        self.subject_id = subject_id
        super().__init__(f"{category}:{code}:{subject_id}")


def _diagnostic(code: str, path: str, message: str, **details: object) -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details=details)


def _sorted(diagnostics: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(diagnostics, key=lambda item: (item.path, item.code, item.message)))


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _node_id(collection: str, node: Mapping[str, object]) -> str | None:
    value = node.get(NODE_COLLECTIONS[collection])
    return value if isinstance(value, str) else None


def _node_key(collection: str, node_id: str) -> str:
    return f"{collection}:{node_id}"


def _node_index(
    model: Mapping[str, object],
) -> dict[str, tuple[str, int, Mapping[str, object]]]:
    index: dict[str, tuple[str, int, Mapping[str, object]]] = {}
    for collection, id_field in NODE_COLLECTIONS.items():
        for position, node in enumerate(_mappings(model.get(collection))):
            node_id = node.get(id_field)
            if isinstance(node_id, str):
                index[_node_key(collection, node_id)] = (collection, position, node)
    return index


def _ids(model: Mapping[str, object], collection: str) -> set[str]:
    return {
        str(node[NODE_COLLECTIONS[collection]])
        for node in _mappings(model.get(collection))
        if isinstance(node.get(NODE_COLLECTIONS[collection]), str)
    }


def _reference_diagnostics(model: Mapping[str, object], stage: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    collection_ids = {
        collection: _ids(model, collection) for collection in NODE_COLLECTIONS
    }
    for collection, id_field in NODE_COLLECTIONS.items():
        seen_in_collection: set[str] = set()
        for node in _mappings(model.get(collection)):
            node_id = node.get(id_field)
            if not isinstance(node_id, str):
                continue
            if node_id in seen_in_collection:
                diagnostics.append(
                    _diagnostic(
                        "MODEL_NODE_ID_DUPLICATE",
                        f"/{collection}/{node_id}",
                        "同一顶层区域内的节点 ID 必须唯一。",
                    )
                )
            seen_in_collection.add(node_id)
    primary_collections = tuple(
        collection
        for collection in NODE_COLLECTIONS
        if collection not in {"scopeClosure", "effectiveStartMatches"}
    )
    seen_primary: dict[str, str] = {}
    for collection in primary_collections:
        for node_id in collection_ids[collection]:
            previous = seen_primary.get(node_id)
            if previous is not None:
                diagnostics.append(
                    _diagnostic(
                        "MODEL_NODE_ID_DUPLICATE",
                        f"/{collection}/{node_id}",
                        "业务节点 ID 必须跨顶层区域唯一。",
                        previousCollection=previous,
                    )
                )
            else:
                seen_primary[node_id] = collection

    known_ids = set(seen_primary)
    input_ids = collection_ids["inputItems"]
    design_ids = collection_ids["designItems"]
    policy_ids = collection_ids["policyInstances"]
    feature_ids = collection_ids["features"]
    story_ids = collection_ids["stories"]
    ac_ids = collection_ids["acceptanceCriteria"]
    task_ids = collection_ids["tasks"]
    responsibility_ids = {
        str(item)
        for item in (
            model.get("project", {}).get("responsibilityBoundaries", [])
            if isinstance(model.get("project"), Mapping)
            else []
        )
    }

    def check(
        collection: str,
        node: Mapping[str, object],
        field: str,
        allowed: set[str],
    ) -> None:
        values = node.get(field)
        if not isinstance(values, list):
            return
        for value in values:
            if isinstance(value, str) and value not in allowed:
                diagnostics.append(
                    _diagnostic(
                        "MODEL_REFERENCE_MISSING",
                        f"/{collection}/{_node_id(collection, node)}/{field}/{value}",
                        "SOW Model 引用了不存在或不允许的节点。",
                    )
                )

    closure_by_input: defaultdict[str, int] = defaultdict(int)
    for node in _mappings(model.get("scopeClosure")):
        input_id = node.get("inputItemId")
        if isinstance(input_id, str):
            closure_by_input[input_id] += 1
            if input_id not in input_ids:
                diagnostics.append(
                    _diagnostic(
                        "MODEL_REFERENCE_MISSING",
                        f"/scopeClosure/{input_id}/inputItemId",
                        "Scope closure 没有对应 inputItem。",
                    )
                )
        check("scopeClosure", node, "targetNodeIds", known_ids)
        check("scopeClosure", node, "assignedFeatureIds", feature_ids)
        if node.get("deliveryDisposition") == "BLOCKED":
            diagnostics.append(
                _diagnostic(
                    "SCOPE_CLOSURE_BLOCKED",
                    f"/scopeClosure/{input_id}/deliveryDisposition",
                    "Scope closure 仍处于阻断状态。",
                )
            )
        if node.get("designCoverageStatus") in {"MISSING", "CONFLICT"}:
            diagnostics.append(
                _diagnostic(
                    "DESIGN_COVERAGE_INSUFFICIENT",
                    f"/scopeClosure/{input_id}/designCoverageStatus",
                    "批准设计覆盖不足或冲突。",
                )
            )
        mechanical = node.get("mechanicalCoverage")
        semantic = node.get("semanticSufficiency")
        status = node.get("designCoverageStatus")
        sufficient = mechanical == "COMPLETE" and semantic == "SUFFICIENT"
        not_required = (
            mechanical == "NOT_REQUIRED"
            and semantic == "NOT_REQUIRED"
        )
        if (status == "SUFFICIENT") != sufficient or (
            status == "NOT_REQUIRED" and not not_required
        ):
            diagnostics.append(
                _diagnostic(
                    "DESIGN_COVERAGE_PROOF_INCONSISTENT",
                    f"/scopeClosure/{input_id}/designCoverageStatus",
                    "只有机械覆盖与语义充分性同时通过，设计覆盖才可标记 SUFFICIENT。",
                )
            )
    for input_id in input_ids:
        if stage != "STAGE_1_SOURCE_SCAN" and closure_by_input[input_id] != 1:
            diagnostics.append(
                _diagnostic(
                    "SCOPE_CLOSURE_NON_UNIQUE",
                    f"/scopeClosure/{input_id}",
                    "每个 inputItem 必须且只能有一个 Scope closure 处置。",
                    actual=closure_by_input[input_id],
                )
            )

    for collection in ("epics", "features", "stories", "acceptanceCriteria"):
        for node in _mappings(model.get(collection)):
            check(collection, node, "requirementRefs", input_ids)
            check(collection, node, "designRefs", design_ids)
            check(collection, node, "policyRefs", policy_ids)
    epic_ids = collection_ids["epics"]
    for node in _mappings(model.get("features")):
        if node.get("epicId") not in epic_ids:
            diagnostics.append(
                _diagnostic(
                    "MODEL_REFERENCE_MISSING",
                    f"/features/{node.get('featureId')}/epicId",
                    "Feature 必须引用存在的 Epic。",
                )
            )
    for collection in ("designItems", "integrations", "nfrs"):
        for node in _mappings(model.get(collection)):
            check(collection, node, "featureIds", feature_ids)
    for node in _mappings(model.get("integrations")):
        check("integrations", node, "responsibilityBoundaryIds", responsibility_ids)
    for node in _mappings(model.get("policyInstances")):
        check("policyInstances", node, "targetNodeIds", known_ids)
    for collection in ("scopeAnnotations", "deliveryAnnotations", "estimationAnnotations"):
        for node in _mappings(model.get(collection)):
            check(collection, node, "subjectIds", known_ids)
    for node in _mappings(model.get("stories")):
        if node.get("featureId") not in feature_ids:
            diagnostics.append(
                _diagnostic(
                    "MODEL_REFERENCE_MISSING",
                    f"/stories/{node.get('storyId')}/featureId",
                    "Story 必须引用存在的 Feature。",
                )
            )
    story_by_ac: dict[str, str] = {}
    for node in _mappings(model.get("acceptanceCriteria")):
        story_id = node.get("storyId")
        ac_id = node.get("acceptanceCriterionId")
        if story_id not in story_ids:
            diagnostics.append(
                _diagnostic(
                    "MODEL_REFERENCE_MISSING",
                    f"/acceptanceCriteria/{ac_id}/storyId",
                    "AC 必须引用存在的 Story。",
                )
            )
        if isinstance(ac_id, str) and isinstance(story_id, str):
            story_by_ac[ac_id] = story_id
    for node in _mappings(model.get("tasks")):
        task_id = str(node.get("taskId"))
        story_id = node.get("storyId")
        if story_id not in story_ids:
            diagnostics.append(
                _diagnostic(
                    "MODEL_REFERENCE_MISSING",
                    f"/tasks/{task_id}/storyId",
                    "Task 必须引用存在的 Story。",
                )
            )
        check("tasks", node, "acceptanceCriterionIds", ac_ids)
        check("tasks", node, "designItemIds", design_ids)
        check("tasks", node, "integrationIds", collection_ids["integrations"])
        check("tasks", node, "nfrIds", collection_ids["nfrs"])
        check("tasks", node, "policyInstanceIds", policy_ids)
        for ac_id in node.get("acceptanceCriterionIds", []):
            if isinstance(ac_id, str) and story_by_ac.get(ac_id) != story_id:
                diagnostics.append(
                    _diagnostic(
                        "TASK_AC_STORY_MISMATCH",
                        f"/tasks/{task_id}/acceptanceCriterionIds/{ac_id}",
                        "Task 引用的 AC 必须属于同一 Story。",
                    )
                )
    for node in _mappings(model.get("dependencies")):
        dependency_id = str(node.get("dependencyId"))
        for field in ("fromNodeId", "toNodeId"):
            if node.get(field) not in known_ids:
                diagnostics.append(
                    _diagnostic(
                        "MODEL_REFERENCE_MISSING",
                        f"/dependencies/{dependency_id}/{field}",
                        "Dependency 端点必须引用存在的节点。",
                    )
                )
        if node.get("fromNodeId") == node.get("toNodeId"):
            diagnostics.append(
                _diagnostic(
                    "MODEL_DEPENDENCY_SELF_REFERENCE",
                    f"/dependencies/{dependency_id}",
                    "Dependency 不得自引用。",
                )
            )
    dependency_graph: defaultdict[str, set[str]] = defaultdict(set)
    for node in _mappings(model.get("dependencies")):
        source = node.get("fromNodeId")
        target = node.get("toNodeId")
        if isinstance(source, str) and isinstance(target, str):
            dependency_graph[source].add(target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit_dependency(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        cyclic = any(
            visit_dependency(target)
            for target in sorted(dependency_graph.get(node_id, ()))
        )
        visiting.remove(node_id)
        visited.add(node_id)
        return cyclic

    if any(visit_dependency(node_id) for node_id in sorted(dependency_graph)):
        diagnostics.append(
            _diagnostic(
                "MODEL_DEPENDENCY_CYCLE",
                "/dependencies",
                "Dependency 图不得形成循环。",
            )
        )
    for node in _mappings(model.get("effectiveStartMatches")):
        if node.get("taskId") not in task_ids:
            diagnostics.append(
                _diagnostic(
                    "MODEL_REFERENCE_MISSING",
                    f"/effectiveStartMatches/{node.get('taskId')}",
                    "Effective Start 判断必须引用存在的 Task。",
                )
            )
    if stage == "STAGE_3":
        match_task_ids = collection_ids["effectiveStartMatches"]
        for task_id in task_ids ^ match_task_ids:
            diagnostics.append(
                _diagnostic(
                    "EFFECTIVE_START_MATCH_INCOMPLETE",
                    f"/effectiveStartMatches/{task_id}",
                    "每个 Task 必须且只能有一个 Effective Start 判断。",
                )
            )
    for node in _mappings(model.get("decisions")):
        check("decisions", node, "subjectIds", known_ids)

    source_identities: dict[tuple[str, str], tuple[str, str]] = {}
    for collection in NODE_COLLECTIONS:
        for node in _mappings(model.get(collection)):
            refs = node.get("sourceRefs")
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if not isinstance(ref, Mapping):
                    continue
                key = (str(ref.get("sourceId")), str(ref.get("blockId")))
                identity = (str(ref.get("sha256")), str(ref.get("locator")))
                previous = source_identities.get(key)
                if previous is not None and previous != identity:
                    diagnostics.append(
                        _diagnostic(
                            "SOURCE_REF_IDENTITY_CONFLICT",
                            f"/{collection}/{_node_id(collection, node)}/sourceRefs",
                            "同一 source block 的 hash/locator 必须一致。",
                        )
                    )
                source_identities[key] = identity
    return diagnostics


def validate(
    model: Mapping[str, object],
    stage: str,
    *,
    registry,
) -> tuple[Diagnostic, ...]:
    if stage not in {"STAGE_1_SOURCE_SCAN", "STAGE_1", "STAGE_2", "STAGE_3"}:
        return (
            _diagnostic(
                "MODEL_STAGE_INVALID",
                "/stage",
                "SOW Model validator stage 不受支持。",
            ),
        )
    diagnostics = list(validate_contract(model, "sow-model.schema.json", registry))
    if diagnostics:
        return _sorted(diagnostics)
    diagnostics.extend(_reference_diagnostics(model, stage))
    return _sorted(diagnostics)


def model_skeleton(
    request: Mapping[str, object],
    input_revision: Mapping[str, object],
) -> dict[str, object]:
    """Build the script-owned envelope; semantic Owners only fill their regions."""
    project = request.get("project")
    if not isinstance(project, Mapping):
        raise ValueError("request project is missing")
    boundaries = request.get("responsibilityBoundaries")
    if not isinstance(boundaries, list):
        raise ValueError("request responsibility boundaries are missing")
    input_revision_sha256 = sha256_bytes(canonical_json_bytes(input_revision))
    source_manifest_sha256 = sha256_bytes(
        canonical_json_bytes(
            {
                "sources": input_revision.get("sources", []),
                "blocks": input_revision.get("blocks", []),
            }
        )
    )
    model: dict[str, object] = {
        "contract": "ai-sow-model-v1",
        "project": {
            "projectId": project.get("projectId"),
            "mode": request.get("mode"),
            "inputRevisionSha256": input_revision_sha256,
            "sourceManifestSha256": source_manifest_sha256,
            "templateSha256": input_revision.get("templateSha256"),
            "policyDefinitionSha256": input_revision.get("deliveryPolicySha256"),
            "responsibilityBoundaries": [
                item.get("responsibilityBoundaryId")
                for item in boundaries
                if isinstance(item, Mapping)
            ],
        },
    }
    for field in TOP_LEVEL_WRITE_OWNER:
        if field not in {"contract", "project"}:
            model[field] = []
    return model


def _add_edge(graph: defaultdict[str, set[str]], source: object, target: object) -> None:
    if isinstance(source, str) and isinstance(target, str) and source != target:
        graph[source].add(target)
        graph[target]


def derive_impact_graph(
    model: Mapping[str, object],
) -> Mapping[str, tuple[str, ...]]:
    graph: defaultdict[str, set[str]] = defaultdict(set)
    for collection, id_field in NODE_COLLECTIONS.items():
        if collection in {"scopeClosure", "effectiveStartMatches"}:
            continue
        for node in _mappings(model.get(collection)):
            node_id = node.get(id_field)
            if isinstance(node_id, str):
                graph[node_id]

    for node in _mappings(model.get("scopeClosure")):
        for field in ("targetNodeIds", "assignedFeatureIds", "crossFeatureTargetIds"):
            for target in node.get(field, []):
                _add_edge(graph, node.get("inputItemId"), target)
    for node in _mappings(model.get("features")):
        _add_edge(graph, node.get("epicId"), node.get("featureId"))
    for collection in ("designItems", "integrations", "nfrs"):
        id_field = NODE_COLLECTIONS[collection]
        for node in _mappings(model.get(collection)):
            for feature_id in node.get("featureIds", []):
                _add_edge(graph, feature_id, node.get(id_field))
    for collection in ("epics", "features"):
        id_field = NODE_COLLECTIONS[collection]
        for node in _mappings(model.get(collection)):
            node_id = node.get(id_field)
            # Stage 1 design objects already point at their Feature. Reversing the
            # same relationship through designRefs would create an artificial
            # Feature -> Design -> Epic -> sibling Feature cycle.
            for field in ("requirementRefs", "policyRefs"):
                for source_id in node.get(field, []):
                    _add_edge(graph, source_id, node_id)
    for collection in ("stories", "acceptanceCriteria"):
        id_field = NODE_COLLECTIONS[collection]
        for node in _mappings(model.get(collection)):
            node_id = node.get(id_field)
            for field in ("requirementRefs", "designRefs", "policyRefs"):
                for source_id in node.get(field, []):
                    _add_edge(graph, source_id, node_id)
    for node in _mappings(model.get("policyInstances")):
        for target_id in node.get("targetNodeIds", []):
            _add_edge(graph, node.get("policyInstanceId"), target_id)
    for node in _mappings(model.get("stories")):
        _add_edge(graph, node.get("featureId"), node.get("storyId"))
    for node in _mappings(model.get("acceptanceCriteria")):
        _add_edge(graph, node.get("storyId"), node.get("acceptanceCriterionId"))
    for node in _mappings(model.get("tasks")):
        task_id = node.get("taskId")
        _add_edge(graph, node.get("storyId"), task_id)
        for field in (
            "acceptanceCriterionIds",
            "designItemIds",
            "integrationIds",
            "nfrIds",
            "policyInstanceIds",
        ):
            for source_id in node.get(field, []):
                _add_edge(graph, source_id, task_id)
    for node in _mappings(model.get("dependencies")):
        dependency_id = node.get("dependencyId")
        _add_edge(graph, node.get("toNodeId"), node.get("fromNodeId"))
        _add_edge(graph, node.get("fromNodeId"), dependency_id)
        _add_edge(graph, node.get("toNodeId"), dependency_id)
    for collection in ("scopeAnnotations", "deliveryAnnotations", "estimationAnnotations"):
        for node in _mappings(model.get(collection)):
            for subject_id in node.get("subjectIds", []):
                _add_edge(graph, subject_id, node.get("annotationId"))
    for node in _mappings(model.get("decisions")):
        for subject_id in node.get("subjectIds", []):
            _add_edge(graph, node.get("decisionId"), subject_id)
    return {node_id: tuple(sorted(targets)) for node_id, targets in sorted(graph.items())}


def owner_projection_sha256(model: Mapping[str, object], owner_stage: str) -> str:
    if owner_stage not in _STAGE_RANK:
        raise ValueError(f"unsupported owner stage: {owner_stage}")
    rank = _STAGE_RANK[owner_stage]
    projection: dict[str, object] = {}
    for field, owner in TOP_LEVEL_WRITE_OWNER.items():
        if field == "contract":
            projection[field] = model.get(field)
            continue
        owner_rank = _STAGE_RANK[owner]
        include = owner_rank <= rank
        if owner_stage == "STAGE_1" and field == "decisions":
            include = False
        if include:
            projection[field] = deepcopy(model.get(field))
    return sha256_bytes(canonical_json_bytes(projection))


def _meaning(collection: str, node: Mapping[str, object]) -> bytes:
    ignored = _NON_SEMANTIC_FIELDS[collection]
    return canonical_json_bytes(
        {field: value for field, value in node.items() if field not in ignored}
    )


def _all_node_ids(model: Mapping[str, object]) -> dict[str, set[str]]:
    result: defaultdict[str, set[str]] = defaultdict(set)
    for collection in NODE_COLLECTIONS:
        if collection in {"scopeClosure", "effectiveStartMatches"}:
            continue
        for node_id in _ids(model, collection):
            result[node_id].add(collection)
    return dict(result)


def _descendants(
    graph: Mapping[str, Sequence[str]], seeds: set[str]
) -> set[str]:
    visited = set(seeds)
    queue = deque(sorted(seeds))
    while queue:
        current = queue.popleft()
        for target in graph.get(current, ()):
            if target not in visited:
                visited.add(target)
                queue.append(target)
    return visited - seeds


def _active_projection(
    candidate: Mapping[str, object], invalidated: set[str]
) -> dict[str, object]:
    active = deepcopy(dict(candidate))
    for collection, id_field in NODE_COLLECTIONS.items():
        values = _mappings(active.get(collection))
        if collection == "effectiveStartMatches":
            active[collection] = [
                node for node in values if node.get("taskId") not in invalidated
            ]
        elif collection == "dependencies":
            active[collection] = [
                node
                for node in values
                if node.get(id_field) not in invalidated
                and node.get("fromNodeId") not in invalidated
                and node.get("toNodeId") not in invalidated
            ]
        else:
            active[collection] = [
                node for node in values if node.get(id_field) not in invalidated
            ]
    return active


def _outcome(
    candidate: Mapping[str, object],
    active: Mapping[str, object],
    *,
    owner_stage: str,
    changed: Sequence[str],
    reused: Sequence[str],
    invalidated: Sequence[str],
    diagnostics: Sequence[Diagnostic],
    replacement: Mapping[str, object],
) -> ReplacementOutcome:
    candidate_sha256 = sha256_bytes(canonical_json_bytes(candidate))
    active_sha256 = sha256_bytes(canonical_json_bytes(active))
    checkpoint_ids = _CHECKPOINT_INVALIDATION.get(owner_stage, ()) if changed else ()
    proof_sha256 = sha256_bytes(
        canonical_json_bytes(
            {
                "ownerStage": owner_stage,
                "replacement": replacement,
                "candidateSha256": candidate_sha256,
                "activeProjectionSha256": active_sha256,
                "changedNodeIds": sorted(changed),
                "reusedNodeIds": sorted(reused),
                "invalidatedNodeIds": sorted(invalidated),
                "invalidatedCheckpointIds": list(checkpoint_ids),
                "diagnostics": [
                    {"code": item.code, "path": item.path} for item in _sorted(diagnostics)
                ],
            }
        )
    )
    return ReplacementOutcome(
        candidate=deepcopy(dict(candidate)),
        candidate_sha256=candidate_sha256,
        active_projection=deepcopy(dict(active)),
        active_projection_sha256=active_sha256,
        proof_sha256=proof_sha256,
        changed_node_ids=tuple(sorted(changed)),
        reused_node_ids=tuple(sorted(reused)),
        invalidated_node_ids=tuple(sorted(invalidated)),
        invalidated_checkpoint_ids=tuple(checkpoint_ids),
        diagnostics=_sorted(diagnostics),
    )


def apply_replacement(
    model: Mapping[str, object],
    replacement: Mapping[str, object],
    *,
    owner_stage: str,
) -> ReplacementOutcome:
    base = deepcopy(dict(model))
    base_index = _node_index(base)
    all_reused = tuple(sorted(base_index))
    diagnostics: list[Diagnostic] = []
    if owner_stage not in _STAGE_RANK:
        diagnostics.append(
            _diagnostic(
                "OWNER_STAGE_INVALID", "/ownerStage", "replacement Owner stage 不受支持。"
            )
        )
        return _outcome(
            base,
            base,
            owner_stage=owner_stage,
            changed=(),
            reused=all_reused,
            invalidated=(),
            diagnostics=diagnostics,
            replacement=replacement,
        )
    effective_owner_stage = _OWNER_STAGE.get(owner_stage, owner_stage)
    if set(replacement) != {"expectedNodeHashes", "upserts", "deletes"}:
        diagnostics.append(
            _diagnostic(
                "REPLACEMENT_CONTRACT_INVALID",
                "",
                "replacement 必须只包含 expectedNodeHashes/upserts/deletes。",
            )
        )
    expected = replacement.get("expectedNodeHashes")
    upserts = replacement.get("upserts")
    deletes = replacement.get("deletes")
    if not isinstance(expected, Mapping) or not isinstance(upserts, list) or not isinstance(deletes, list):
        diagnostics.append(
            _diagnostic(
                "REPLACEMENT_CONTRACT_INVALID", "", "replacement 字段类型无效。"
            )
        )
        return _outcome(
            base,
            base,
            owner_stage=owner_stage,
            changed=(),
            reused=all_reused,
            invalidated=(),
            diagnostics=diagnostics,
            replacement=replacement,
        )

    normalized_upserts: list[tuple[str, str, Mapping[str, object]]] = []
    target_keys: set[str] = set()
    existing_targets: set[str] = set()
    seen_upserts: set[str] = set()
    existing_ids = _all_node_ids(base)
    for position, wrapper in enumerate(upserts):
        if not isinstance(wrapper, Mapping) or set(wrapper) != {"collection", "node"}:
            diagnostics.append(
                _diagnostic(
                    "REPLACEMENT_UPSERT_INVALID",
                    f"/upserts/{position}",
                    "upsert 必须显式绑定 collection 与 node。",
                )
            )
            continue
        collection = wrapper.get("collection")
        node = wrapper.get("node")
        if collection not in NODE_COLLECTIONS or not isinstance(node, Mapping):
            diagnostics.append(
                _diagnostic(
                    "REPLACEMENT_UPSERT_INVALID",
                    f"/upserts/{position}",
                    "upsert collection 或 node 无效。",
                )
            )
            continue
        collection = str(collection)
        node_id = _node_id(collection, node)
        if node_id is None:
            diagnostics.append(
                _diagnostic(
                    "REPLACEMENT_NODE_ID_MISSING",
                    f"/upserts/{position}",
                    "upsert node 缺少所属集合的稳定 ID。",
                )
            )
            continue
        key = _node_key(collection, node_id)
        if key in seen_upserts:
            diagnostics.append(
                _diagnostic(
                    "REPLACEMENT_NODE_DUPLICATE", f"/upserts/{position}", "同一节点不能重复 upsert。"
                )
            )
        seen_upserts.add(key)
        target_keys.add(key)
        if key in base_index:
            existing_targets.add(key)
        elif (
            collection not in {"scopeClosure", "effectiveStartMatches"}
            and node_id in existing_ids
            and collection not in existing_ids[node_id]
        ):
            diagnostics.append(
                _diagnostic(
                    "MODEL_NODE_ID_DUPLICATE",
                    f"/upserts/{position}",
                    "新节点 ID 已由其他顶层区域使用。",
                )
            )
        authorized = TOP_LEVEL_WRITE_OWNER[collection] == effective_owner_stage
        if not authorized:
            diagnostics.append(
                _diagnostic(
                    "OWNER_WRITE_SCOPE_VIOLATION",
                    f"/upserts/{position}",
                    "Owner 不能修改上游、下游或脚本拥有的区域。",
                    collection=collection,
                    ownerStage=owner_stage,
                )
            )
        if key in base_index and authorized:
            previous = base_index[key][2]
            if canonical_json_bytes(previous) != canonical_json_bytes(node) and _meaning(
                collection, previous
            ) != _meaning(collection, node):
                diagnostics.append(
                    _diagnostic(
                        "STABLE_ID_SEMANTICS_CHANGED",
                        f"/upserts/{position}",
                        "节点语义变化时必须使用新的稳定 ID。",
                        nodeId=node_id,
                    )
                )
        normalized_upserts.append((collection, node_id, node))

    normalized_deletes: list[tuple[str, str]] = []
    for position, raw_key in enumerate(deletes):
        if not isinstance(raw_key, str) or raw_key not in base_index:
            diagnostics.append(
                _diagnostic(
                    "REPLACEMENT_DELETE_INVALID",
                    f"/deletes/{position}",
                    "delete 必须是存在节点的 collection:nodeId key。",
                )
            )
            continue
        collection, _, node = base_index[raw_key]
        node_id = _node_id(collection, node)
        assert node_id is not None
        if TOP_LEVEL_WRITE_OWNER[collection] != effective_owner_stage:
            diagnostics.append(
                _diagnostic(
                    "OWNER_WRITE_SCOPE_VIOLATION",
                    f"/deletes/{position}",
                    "Owner 不能删除上游、下游或脚本拥有的节点。",
                    collection=collection,
                    ownerStage=owner_stage,
                )
            )
        if raw_key in target_keys:
            diagnostics.append(
                _diagnostic(
                    "REPLACEMENT_NODE_CONFLICT",
                    f"/deletes/{position}",
                    "同一节点不能同时 upsert 与 delete。",
                )
            )
        target_keys.add(raw_key)
        existing_targets.add(raw_key)
        normalized_deletes.append((collection, node_id))

    if set(expected) != existing_targets:
        diagnostics.append(
            _diagnostic(
                "EXPECTED_NODE_HASH_SET_MISMATCH",
                "/expectedNodeHashes",
                "expectedNodeHashes 必须精确覆盖所有被修改的既有节点。",
                expected=sorted(existing_targets),
                actual=sorted(str(item) for item in expected),
            )
        )
    for key in sorted(set(expected) & set(base_index)):
        actual = sha256_bytes(canonical_json_bytes(base_index[key][2]))
        if expected.get(key) != actual:
            diagnostics.append(
                _diagnostic(
                    "EXPECTED_NODE_HASH_MISMATCH",
                    f"/expectedNodeHashes/{key}",
                    "节点已变化，replacement 绑定过期。",
                    expected=actual,
                    actual=expected.get(key),
                )
            )
    if diagnostics:
        return _outcome(
            base,
            base,
            owner_stage=owner_stage,
            changed=(),
            reused=all_reused,
            invalidated=(),
            diagnostics=diagnostics,
            replacement=replacement,
        )

    candidate = deepcopy(base)
    for collection, node_id in normalized_deletes:
        id_field = NODE_COLLECTIONS[collection]
        candidate[collection] = [
            node
            for node in _mappings(candidate.get(collection))
            if node.get(id_field) != node_id
        ]
    for collection, node_id, node in normalized_upserts:
        id_field = NODE_COLLECTIONS[collection]
        values = list(_mappings(candidate.get(collection)))
        for position, existing in enumerate(values):
            if existing.get(id_field) == node_id:
                values[position] = deepcopy(dict(node))
                break
        else:
            values.append(deepcopy(dict(node)))
        candidate[collection] = values

    candidate_index = _node_index(candidate)
    changed = {
        key
        for key in set(base_index) | set(candidate_index)
        if key not in base_index
        or key not in candidate_index
        or canonical_json_bytes(base_index[key][2])
        != canonical_json_bytes(candidate_index[key][2])
    }
    changed_ids: set[str] = set()
    for key in changed:
        collection, node_id = key.split(":", 1)
        before = base_index.get(key)
        after = candidate_index.get(key)
        if (
            before is None
            or after is None
            or _meaning(collection, before[2]) != _meaning(collection, after[2])
        ):
            changed_ids.add(node_id)
    before_graph = derive_impact_graph(base)
    after_graph = derive_impact_graph(candidate)
    descendants = _descendants(before_graph, changed_ids) | _descendants(
        after_graph, changed_ids
    )
    id_owners: defaultdict[str, set[str]] = defaultdict(set)
    for collection, id_field in NODE_COLLECTIONS.items():
        if collection in {"scopeClosure", "effectiveStartMatches"}:
            continue
        for node in _mappings(base.get(collection)) + _mappings(candidate.get(collection)):
            node_id = node.get(id_field)
            if isinstance(node_id, str):
                id_owners[node_id].add(TOP_LEVEL_WRITE_OWNER[collection])
    owner_rank = _STAGE_RANK[effective_owner_stage]
    invalidated = {
        node_id
        for node_id in descendants
        if any(_STAGE_RANK[owner] > owner_rank for owner in id_owners.get(node_id, ()))
    }
    active = _active_projection(candidate, invalidated)
    validation_stage = (
        owner_stage
        if owner_stage in {"STAGE_1_SOURCE_SCAN", "STAGE_1", "STAGE_2", "STAGE_3"}
        else "STAGE_3"
    )
    candidate_diagnostics = validate(
        active,
        validation_stage,
        registry=_NEXT_REGISTRY,
    )
    if candidate_diagnostics:
        return _outcome(
            base,
            base,
            owner_stage=owner_stage,
            changed=(),
            reused=all_reused,
            invalidated=(),
            diagnostics=candidate_diagnostics,
            replacement=replacement,
        )

    reused = {
        key
        for key in set(base_index) & set(candidate_index)
        if key not in changed
        and key.split(":", 1)[1] not in invalidated
        and canonical_json_bytes(base_index[key][2])
        == canonical_json_bytes(candidate_index[key][2])
    }
    return _outcome(
        candidate,
        active,
        owner_stage=owner_stage,
        changed=changed,
        reused=reused,
        invalidated=invalidated,
        diagnostics=(),
        replacement=replacement,
    )


def derive_sit_assignments(
    model: Mapping[str, object],
    catalog: TaskStandardCatalog,
) -> tuple[Mapping[str, object], ...]:
    rows = dict(catalog.by_work_type_id)
    if not rows:
        for row in catalog.rows:
            work_type_id = row.get("workTypeId", row.get("工作类型ID"))
            if isinstance(work_type_id, str):
                rows[work_type_id] = row
    tasks = _mappings(model.get("tasks"))
    owner_by_task: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    for integration in _mappings(model.get("integrations")):
        integration_id = integration.get("integrationId")
        if not isinstance(integration_id, str):
            continue
        support_class = integration.get("counterpartyBoundary")
        if support_class not in {"INTERNAL", "EXTERNAL"}:
            raise SitAssignmentError(
                "INPUT_REQUIRED",
                "SIT_SUPPORT_BOUNDARY_MISSING",
                integration_id,
            )
        candidates: list[str] = []
        for task in tasks:
            work_type_id = task.get("workTypeId")
            row = rows.get(str(work_type_id), {})
            eligibility = row.get(
                "sitSupportEligibility", row.get("SIT支持资格")
            ) if isinstance(row, Mapping) else None
            if (
                integration_id in task.get("integrationIds", [])
                and work_type_id in {"IN-INTEGRATION", "IN-IDENTITY"}
                and eligibility == "PER_INTEGRATION"
                and isinstance(task.get("taskId"), str)
            ):
                candidates.append(str(task["taskId"]))
        if len(candidates) != 1:
            raise SitAssignmentError(
                "OWNER_FIX_REQUIRED",
                "SIT_SUPPORT_ASSIGNMENT_NON_UNIQUE",
                integration_id,
            )
        owner_by_task[candidates[0]].append((integration_id, str(support_class)))

    assignments: list[Mapping[str, object]] = []
    for task in tasks:
        task_id = task.get("taskId")
        if not isinstance(task_id, str):
            continue
        owned = owner_by_task.get(task_id, [])
        if len(owned) > 1:
            raise SitAssignmentError(
                "OWNER_FIX_REQUIRED",
                "SIT_SUPPORT_TASK_HAS_MULTIPLE_POINTS",
                task_id,
            )
        if owned:
            support_point_id, support_class = owned[0]
        else:
            support_point_id, support_class = None, "NONE"
        assignments.append(
            {
                "taskId": task_id,
                "sitSupportClass": support_class,
                "sitSupportPointId": support_point_id,
            }
        )
    return tuple(assignments)
