from __future__ import annotations

TEST_LAYER = "unit"

import copy
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contracts import canonical_json_bytes, load_registry, sha256_bytes  # noqa: E402
from models import TaskStandardCatalog  # noqa: E402
from sow_model import (  # noqa: E402
    SitAssignmentError,
    TOP_LEVEL_WRITE_OWNER,
    apply_replacement,
    derive_impact_graph,
    derive_sit_assignments,
    model_skeleton,
    owner_projection_sha256,
    validate,
)


REGISTRY = load_registry(SKILL_ROOT / "contracts")
HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64


def sit_catalog() -> TaskStandardCatalog:
    return TaskStandardCatalog(
        template_sha256=HEX_A,
        semantic_sha256=HEX_B,
        rows=(
            {
                "workTypeId": "IN-INTEGRATION",
                "sitSupportEligibility": "PER_INTEGRATION",
            },
            {"workTypeId": "FE-PAGE", "sitSupportEligibility": "NONE"},
        ),
        by_work_type_id={},
    )


def source_ref() -> dict[str, object]:
    return {
        "sourceId": "prd-main",
        "blockId": "block-prd-refund",
        "sha256": HEX_A,
        "locator": "heading:退款范围",
    }


def valid_model() -> dict[str, object]:
    ref = source_ref()
    return {
        "contract": "ai-sow-model-v1",
        "project": {
            "projectId": "project-refund",
            "mode": "GREENFIELD",
            "inputRevisionSha256": HEX_A,
            "sourceManifestSha256": HEX_B,
            "templateSha256": HEX_C,
            "policyDefinitionSha256": HEX_D,
            "responsibilityBoundaries": ["boundary-customer"],
        },
        "inputItems": [
            {
                "inputItemId": "input-refund",
                "kind": "REQUIREMENT",
                "text": "用户提交退款并看到结果。",
                "conditions": [],
                "thresholds": [],
                "prohibitions": [],
                "applicableScopes": ["退款申请"],
                "sourceRefs": [ref],
            },
            {
                "inputItemId": "input-history",
                "kind": "REQUIREMENT",
                "text": "用户查看退款历史。",
                "conditions": [],
                "thresholds": [],
                "prohibitions": [],
                "applicableScopes": ["退款历史"],
                "sourceRefs": [ref],
            },
        ],
        "scopeClosure": [
            {
                "inputItemId": "input-refund",
                "sourceRefs": [ref],
                "disposition": "SCOPE_NODE",
                "targetNodeIds": ["feature-refund"],
                "preservedQualifiers": ["结果可见"],
                "crossFeatureRuleIds": [],
                "mechanicalCoverage": "COMPLETE",
                "semanticSufficiency": "SUFFICIENT",
                "designCoverageStatus": "SUFFICIENT",
                "deliveryDisposition": "STORY_AC_REQUIRED",
                "assignedFeatureIds": ["feature-refund"],
                "requiredQualifierRefs": [],
                "crossFeatureTargetIds": [],
            },
            {
                "inputItemId": "input-history",
                "sourceRefs": [ref],
                "disposition": "SCOPE_NODE",
                "targetNodeIds": ["feature-history"],
                "preservedQualifiers": [],
                "crossFeatureRuleIds": [],
                "mechanicalCoverage": "NOT_REQUIRED",
                "semanticSufficiency": "NOT_REQUIRED",
                "designCoverageStatus": "NOT_REQUIRED",
                "deliveryDisposition": "STORY_AC_REQUIRED",
                "assignedFeatureIds": ["feature-history"],
                "requiredQualifierRefs": [],
                "crossFeatureTargetIds": [],
            },
        ],
        "epics": [
            {
                "epicId": "epic-commerce",
                "name": "交易服务",
                "scopeClass": "BUSINESS",
                "requirementRefs": ["input-refund", "input-history"],
                "designRefs": ["design-refund"],
                "policyRefs": ["policy-sit"],
                "effortPhase": "BUILD",
                "activationPhase": "BUILD",
                "inclusionPolicy": "REQUIRED",
            },
            {
                "epicId": "epic-operations",
                "name": "运营服务",
                "scopeClass": "BUSINESS",
                "requirementRefs": ["input-refund"],
                "designRefs": ["design-refund"],
                "policyRefs": [],
                "effortPhase": "BUILD",
                "activationPhase": "BUILD",
                "inclusionPolicy": "REQUIRED",
            },
        ],
        "features": [
            {
                "featureId": "feature-refund",
                "epicId": "epic-commerce",
                "name": "退款申请",
                "scopeDecision": "IN_SCOPE",
                "scopeClass": "BUSINESS",
                "requirementRefs": ["input-refund"],
                "designRefs": ["design-refund"],
                "policyRefs": ["policy-sit"],
                "effortPhase": "BUILD",
                "activationPhase": "BUILD",
                "inclusionPolicy": "REQUIRED",
            },
            {
                "featureId": "feature-history",
                "epicId": "epic-commerce",
                "name": "退款历史",
                "scopeDecision": "IN_SCOPE",
                "scopeClass": "BUSINESS",
                "requirementRefs": ["input-history"],
                "designRefs": [],
                "policyRefs": [],
                "effortPhase": "BUILD",
                "activationPhase": "BUILD",
                "inclusionPolicy": "REQUIRED",
            },
        ],
        "designItems": [
            {
                "designItemId": "design-refund",
                "name": "退款服务",
                "featureIds": ["feature-refund"],
                "sourceRefs": [ref],
                "status": "APPROVED",
            }
        ],
        "integrations": [
            {
                "integrationId": "integration-refund",
                "name": "门户到退款服务",
                "featureIds": ["feature-refund"],
                "sourceRefs": [ref],
                "direction": "门户到退款服务",
                "trigger": "提交退款",
                "purpose": "创建退款申请",
                "dataCategories": ["退款申请"],
                "responsibilityBoundaryIds": ["boundary-customer"],
                "counterpartyBoundary": "EXTERNAL",
            }
        ],
        "nfrs": [
            {
                "nfrId": "nfr-audit",
                "category": "AUDIT",
                "featureIds": ["feature-refund"],
                "sourceRefs": [ref],
                "status": "DEFINED",
                "target": "记录退款状态变化",
            }
        ],
        "policyInstances": [
            {
                "policyInstanceId": "policy-sit",
                "policyId": "policy-sit-automation",
                "targetNodeIds": ["feature-refund"],
                "inclusionPolicy": "DEFAULT_INCLUDED",
                "sourceRefs": [],
            }
        ],
        "scopeAnnotations": [
            {
                "annotationId": "annotation-scope",
                "category": "RESPONSIBILITY",
                "subjectIds": ["feature-refund"],
                "text": "客户负责外部网络放通。",
            }
        ],
        "stories": [
            {
                "storyId": "story-refund",
                "featureId": "feature-refund",
                "name": "提交退款申请",
                "coverageSet": ["portal"],
                "requirementRefs": ["input-refund"],
                "designRefs": ["design-refund"],
                "policyRefs": ["policy-sit"],
                "uatApplicable": True,
            },
            {
                "storyId": "story-history",
                "featureId": "feature-history",
                "name": "查看退款历史",
                "coverageSet": ["portal"],
                "requirementRefs": ["input-history"],
                "designRefs": [],
                "policyRefs": [],
                "uatApplicable": True,
            },
        ],
        "acceptanceCriteria": [
            {
                "acceptanceCriterionId": "ac-refund",
                "storyId": "story-refund",
                "text": "提交后显示退款编号。",
                "coverageSet": ["portal"],
                "requirementRefs": ["input-refund"],
                "designRefs": ["design-refund"],
                "policyRefs": ["policy-sit"],
            },
            {
                "acceptanceCriterionId": "ac-history",
                "storyId": "story-history",
                "text": "列表显示退款状态。",
                "coverageSet": ["portal"],
                "requirementRefs": ["input-history"],
                "designRefs": [],
                "policyRefs": [],
            },
        ],
        "deliveryAnnotations": [
            {
                "annotationId": "annotation-delivery",
                "category": "DESIGN",
                "subjectIds": ["story-refund"],
                "text": "复用批准的退款服务。",
            }
        ],
        "tasks": [
            {
                "taskId": "task-refund-integration",
                "storyId": "story-refund",
                "name": "接入退款服务",
                "workTypeId": "IN-INTEGRATION",
                "rowSemanticSha256": HEX_D,
                "workMode": "新建",
                "actualMeasurementScope": "门户到退款服务单向集成",
                "complexity": "M",
                "acceptanceCriterionIds": ["ac-refund"],
                "designItemIds": ["design-refund"],
                "integrationIds": ["integration-refund"],
                "nfrIds": ["nfr-audit"],
                "policyInstanceIds": ["policy-sit"],
            },
            {
                "taskId": "task-history",
                "storyId": "story-history",
                "name": "实现退款历史查询",
                "workTypeId": "FE-PAGE",
                "rowSemanticSha256": HEX_C,
                "workMode": "新建",
                "actualMeasurementScope": "退款历史页",
                "complexity": "M",
                "acceptanceCriterionIds": ["ac-history"],
                "designItemIds": [],
                "integrationIds": [],
                "nfrIds": [],
                "policyInstanceIds": [],
            },
        ],
        "dependencies": [],
        "effectiveStartMatches": [
            {
                "taskId": "task-refund-integration",
                "queryKey": "门户到退款服务",
                "candidateIds": [],
                "checkedLocators": [],
                "decision": "NO_MATCH_NEW",
            },
            {
                "taskId": "task-history",
                "queryKey": "退款历史页",
                "candidateIds": [],
                "checkedLocators": [],
                "decision": "NO_MATCH_NEW",
            },
        ],
        "estimationAnnotations": [
            {
                "annotationId": "annotation-estimate",
                "category": "ESTIMATE_BOUNDARY",
                "subjectIds": ["task-refund-integration"],
                "text": "按一个单向 Integration 计数。",
            }
        ],
        "decisions": [],
    }


def node_hash(model: dict[str, object], collection: str, node_id: str) -> str:
    id_field = {
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
    }[collection]
    node = next(item for item in model[collection] if item[id_field] == node_id)
    return sha256_bytes(canonical_json_bytes(node))


def test_sow_model_top_level_regions_have_one_write_owner() -> None:
    model = valid_model()
    assert set(TOP_LEVEL_WRITE_OWNER) == set(model)
    assert TOP_LEVEL_WRITE_OWNER["project"] == "SCRIPT"
    assert TOP_LEVEL_WRITE_OWNER["inputItems"] == "STAGE_1"
    assert TOP_LEVEL_WRITE_OWNER["stories"] == "STAGE_2"
    assert TOP_LEVEL_WRITE_OWNER["tasks"] == "STAGE_3"
    assert TOP_LEVEL_WRITE_OWNER["decisions"] == "SCRIPT"
    assert validate(model, "STAGE_3", registry=REGISTRY) == ()


def test_model_skeleton_binds_script_fields_and_leaves_owner_regions_empty() -> None:
    request = {
        "project": {"projectId": "project-refund"},
        "mode": "GREENFIELD",
        "responsibilityBoundaries": [
            {"responsibilityBoundaryId": "boundary-customer"}
        ],
    }
    revision = {
        "templateSha256": HEX_C,
        "deliveryPolicySha256": HEX_D,
        "sources": [],
        "blocks": [],
    }

    model = model_skeleton(request, revision)

    assert model["project"]["inputRevisionSha256"] == sha256_bytes(
        canonical_json_bytes(revision)
    )
    assert model["project"]["policyDefinitionSha256"] == HEX_D
    assert all(
        model[field] == []
        for field in TOP_LEVEL_WRITE_OWNER
        if field not in {"contract", "project"}
    )


def test_replacement_rejects_stale_or_incomplete_expected_node_hashes() -> None:
    model = valid_model()
    changed = copy.deepcopy(model["features"][0])
    changed["name"] = "退款申请澄清"

    stale = apply_replacement(
        model,
        {
            "expectedNodeHashes": {"features:feature-refund": "0" * 64},
            "upserts": [{"collection": "features", "node": changed}],
            "deletes": [],
        },
        owner_stage="STAGE_1",
    )
    missing = apply_replacement(
        model,
        {
            "expectedNodeHashes": {},
            "upserts": [{"collection": "features", "node": changed}],
            "deletes": [],
        },
        owner_stage="STAGE_1",
    )

    assert {item.code for item in stale.diagnostics} == {
        "EXPECTED_NODE_HASH_MISMATCH"
    }
    assert {item.code for item in missing.diagnostics} == {
        "EXPECTED_NODE_HASH_SET_MISMATCH"
    }


def test_validator_rejects_duplicate_ids_and_dependency_cycles() -> None:
    model = valid_model()
    model["stories"].append(copy.deepcopy(model["stories"][0]))
    model["dependencies"] = [
        {
            "dependencyId": "dependency-a",
            "fromNodeId": "task-history",
            "toNodeId": "task-refund-integration",
            "kind": "REQUIRES",
        },
        {
            "dependencyId": "dependency-b",
            "fromNodeId": "task-refund-integration",
            "toNodeId": "task-history",
            "kind": "REQUIRES",
        },
    ]

    diagnostics = validate(model, "STAGE_3", registry=REGISTRY)

    assert {item.code for item in diagnostics} >= {
        "MODEL_NODE_ID_DUPLICATE",
        "MODEL_DEPENDENCY_CYCLE",
    }


def test_owner_replacement_rejects_locked_or_upstream_changes() -> None:
    model = valid_model()
    changed = copy.deepcopy(model["features"][0])
    changed["epicId"] = "epic-operations"
    result = apply_replacement(
        model,
        {
            "expectedNodeHashes": {
                "features:feature-refund": node_hash(model, "features", "feature-refund")
            },
            "upserts": [{"collection": "features", "node": changed}],
            "deletes": [],
        },
        owner_stage="STAGE_2",
    )
    assert {item.code for item in result.diagnostics} == {
        "OWNER_WRITE_SCOPE_VIOLATION"
    }
    assert result.candidate == model


def test_replacement_preserves_unaffected_story_task_and_review_bytes() -> None:
    model = valid_model()
    story_bytes = canonical_json_bytes(model["stories"])
    task_bytes = canonical_json_bytes(model["tasks"])
    new_feature = copy.deepcopy(model["features"][1])
    new_feature.update({"featureId": "feature-export", "name": "退款记录导出"})

    result = apply_replacement(
        model,
        {
            "expectedNodeHashes": {},
            "upserts": [{"collection": "features", "node": new_feature}],
            "deletes": [],
        },
        owner_stage="STAGE_1",
    )

    assert result.diagnostics == ()
    assert canonical_json_bytes(result.candidate["stories"]) == story_bytes
    assert canonical_json_bytes(result.candidate["tasks"]) == task_bytes
    assert result.invalidated_node_ids == ()


def test_owner_projection_ignores_downstream_additions_but_detects_direct_change() -> None:
    model = valid_model()
    baseline = owner_projection_sha256(model, "STAGE_1")
    downstream = copy.deepcopy(model)
    extra_story = copy.deepcopy(model["stories"][1])
    extra_story.update({"storyId": "story-history-export", "name": "导出退款历史"})
    downstream["stories"].append(extra_story)
    assert owner_projection_sha256(downstream, "STAGE_1") == baseline

    direct = copy.deepcopy(model)
    direct["features"][0]["name"] = "退款申请处理"
    assert owner_projection_sha256(direct, "STAGE_1") != baseline


def test_scope_fact_kinds_and_program_source_refs_remain_in_owner_projection():
    model = valid_model()
    for collection in ("epics", "features"):
        model[collection][0]["sourceRefs"] = [source_ref()]
    for kind in ("RULE", "ASSUMPTION", "RISK"):
        model["inputItems"][0]["kind"] = kind
        assert validate(model, "STAGE_3", registry=REGISTRY) == ()
    before = owner_projection_sha256(model, "STAGE_1")
    model["features"][0]["sourceRefs"][0]["sha256"] = HEX_D
    assert owner_projection_sha256(model, "STAGE_1") != before


def test_derived_obligations_sit_assignments_and_graph_are_not_persisted() -> None:
    model = valid_model()
    before = canonical_json_bytes(model)

    assignments = derive_sit_assignments(model, sit_catalog())
    graph = derive_impact_graph(model)

    assert canonical_json_bytes(model) == before
    assert {item["taskId"]: item["sitSupportClass"] for item in assignments} == {
        "task-refund-integration": "EXTERNAL",
        "task-history": "NONE",
    }
    assert "story-refund" in graph["feature-refund"]
    for forbidden in ("storyObligations", "sitSupportAssignments", "traceEdges"):
        assert forbidden not in model


def test_sit_assignment_is_unique_and_derived_from_responsibility_boundary() -> None:
    assignments = derive_sit_assignments(valid_model(), sit_catalog())
    owner = next(item for item in assignments if item["taskId"] == "task-refund-integration")
    assert owner == {
        "taskId": "task-refund-integration",
        "sitSupportClass": "EXTERNAL",
        "sitSupportPointId": "integration-refund",
    }


def test_non_owner_tasks_project_none_and_empty_support_point() -> None:
    assignments = derive_sit_assignments(valid_model(), sit_catalog())
    non_owner = next(item for item in assignments if item["taskId"] == "task-history")
    assert non_owner == {
        "taskId": "task-history",
        "sitSupportClass": "NONE",
        "sitSupportPointId": None,
    }


def test_sit_assignment_distinguishes_input_gap_from_owner_fix() -> None:
    missing_boundary = valid_model()
    del missing_boundary["integrations"][0]["counterpartyBoundary"]
    with pytest.raises(SitAssignmentError) as missing:
        derive_sit_assignments(missing_boundary, sit_catalog())
    assert (missing.value.category, missing.value.code) == (
        "INPUT_REQUIRED",
        "SIT_SUPPORT_BOUNDARY_MISSING",
    )

    duplicate_owner = valid_model()
    second = copy.deepcopy(duplicate_owner["tasks"][0])
    second["taskId"] = "task-refund-integration-duplicate"
    duplicate_owner["tasks"].append(second)
    with pytest.raises(SitAssignmentError) as duplicate:
        derive_sit_assignments(duplicate_owner, sit_catalog())
    assert (duplicate.value.category, duplicate.value.code) == (
        "OWNER_FIX_REQUIRED",
        "SIT_SUPPORT_ASSIGNMENT_NON_UNIQUE",
    )


def test_same_id_requires_same_semantics_or_explicit_new_id() -> None:
    model = valid_model()
    changed = copy.deepcopy(model["features"][0])
    changed["scopeClass"] = "DELIVERY"
    rejected = apply_replacement(
        model,
        {
            "expectedNodeHashes": {
                "features:feature-refund": node_hash(model, "features", "feature-refund")
            },
            "upserts": [{"collection": "features", "node": changed}],
            "deletes": [],
        },
        owner_stage="STAGE_1",
    )
    assert {item.code for item in rejected.diagnostics} == {
        "STABLE_ID_SEMANTICS_CHANGED"
    }

    explicit = copy.deepcopy(model["features"][0])
    explicit.update(
        {
            "featureId": "feature-refund-v2",
            "name": "完全不同的能力",
            "scopeClass": "DELIVERY",
        }
    )
    accepted = apply_replacement(
        model,
        {
            "expectedNodeHashes": {},
            "upserts": [{"collection": "features", "node": explicit}],
            "deletes": [],
        },
        owner_stage="STAGE_1",
    )
    assert accepted.diagnostics == ()
    assert "features:feature-refund-v2" in accepted.changed_node_ids


def move_refund_feature(model: dict[str, object]) -> dict[str, object]:
    moved_feature = copy.deepcopy(model["features"][0])
    moved_feature.update(
        {"featureId": "feature-refund-v2", "epicId": "epic-operations"}
    )
    changed_nodes: list[tuple[str, dict[str, object]]] = []
    for collection, node, fields in (
        (
            "scopeClosure",
            model["scopeClosure"][0],
            {
                "targetNodeIds": ["feature-refund-v2"],
                "assignedFeatureIds": ["feature-refund-v2"],
            },
        ),
        (
            "designItems",
            model["designItems"][0],
            {"featureIds": ["feature-refund-v2"]},
        ),
        (
            "integrations",
            model["integrations"][0],
            {"featureIds": ["feature-refund-v2"]},
        ),
        (
            "nfrs",
            model["nfrs"][0],
            {"featureIds": ["feature-refund-v2"]},
        ),
        (
            "policyInstances",
            model["policyInstances"][0],
            {"targetNodeIds": ["feature-refund-v2"]},
        ),
        (
            "scopeAnnotations",
            model["scopeAnnotations"][0],
            {"subjectIds": ["feature-refund-v2"]},
        ),
    ):
        changed = copy.deepcopy(node)
        changed.update(fields)
        changed_nodes.append((collection, changed))
    expected = {
        f"{collection}:{node[next(
            key for key in node if key.endswith('Id')
        )]}": node_hash(
            model,
            collection,
            str(node[next(key for key in node if key.endswith("Id"))]),
        )
        for collection, node in (
            ("scopeClosure", model["scopeClosure"][0]),
            ("designItems", model["designItems"][0]),
            ("integrations", model["integrations"][0]),
            ("nfrs", model["nfrs"][0]),
            ("policyInstances", model["policyInstances"][0]),
            ("scopeAnnotations", model["scopeAnnotations"][0]),
        )
    }
    expected["features:feature-refund"] = node_hash(
        model, "features", "feature-refund"
    )
    return {
        "expectedNodeHashes": expected,
        "upserts": [
            {"collection": "features", "node": moved_feature},
            *[
                {"collection": collection, "node": node}
                for collection, node in changed_nodes
            ],
        ],
        "deletes": ["features:feature-refund"],
    }


def test_replacement_outcome_separates_stored_snapshot_from_active_projection() -> None:
    model = valid_model()
    result = apply_replacement(
        model,
        move_refund_feature(model),
        owner_stage="STAGE_1",
    )

    assert result.diagnostics == ()
    assert any(item["storyId"] == "story-refund" for item in result.candidate["stories"])
    assert all(
        item["storyId"] != "story-refund"
        for item in result.active_projection["stories"]
    )
    assert {
        "story-refund",
        "ac-refund",
        "task-refund-integration",
    } <= set(result.invalidated_node_ids)
    assert result.candidate_sha256 != result.active_projection_sha256
    assert result.proof_sha256


def test_parent_id_change_crash_resume_rebuilds_only_invalidated_descendants() -> None:
    model = valid_model()
    replacement = move_refund_feature(model)

    first = apply_replacement(model, replacement, owner_stage="STAGE_1")
    resumed = apply_replacement(model, replacement, owner_stage="STAGE_1")

    assert resumed == first
    assert "story-history" not in first.invalidated_node_ids
    assert "task-history" not in first.invalidated_node_ids
    assert any(
        item["storyId"] == "story-history"
        for item in first.active_projection["stories"]
    )
    assert any(
        item["taskId"] == "task-history"
        for item in first.active_projection["tasks"]
    )
