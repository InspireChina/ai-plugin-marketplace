from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).parents[1]
FIXTURES = SKILL_ROOT / "fixtures"
SCRIPTS = SKILL_ROOT / "scripts"
TESTS = SKILL_ROOT / "tests"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from delivery_compiler import (  # noqa: E402
    accept_result as accept_story_result,
    apply_ready_group as apply_story_group,
    build_story_ac_checkpoint,
    derive_story_obligations,
    prepare_action as prepare_story_action,
    story_join_required,
    validate_story_ac_checkpoint,
)
from scope_compiler import build_scope_closure_checkpoint  # noqa: E402
from test_scope_compiler import (  # noqa: E402
    source_scan_record,
    stage_one_checkpoint_state,
)


def diagnostic_codes(result: object) -> set[str]:
    return {diagnostic.code for diagnostic in result.diagnostics}


def story_stage_state(*, token_budget: int = 30000) -> dict[str, object]:
    stage_one = stage_one_checkpoint_state()
    checkpoint_result = build_scope_closure_checkpoint(stage_one)
    assert checkpoint_result["outcome"] == "READY_FOR_STORY_AC"
    decisions = {
        item["policyInstanceId"]: "INCLUDED"
        for item in stage_one["candidate"]["policyInstances"]
    }
    return {
        **stage_one,
        "actionKind": "STORY_AC",
        "baseCandidate": copy.deepcopy(stage_one["candidate"]),
        "baseCandidateSha256": sha256_bytes(
            canonical_json_bytes(stage_one["candidate"])
        ),
        "scopeClosureCheckpoint": checkpoint_result["checkpoint"],
        "effectivePolicyDecisions": decisions,
        "maxInitialPacketTokens": token_budget,
        "maxOutputTokens": 8000,
        "modelProfileId": "author-story-ac-v1",
        "modelConfigSha256": "7" * 64,
        "acceptedRecords": [],
    }


def stage2_fixture() -> dict[str, object]:
    return json.loads(
        (FIXTURES / "pipeline/stage2/story-ac-results.json").read_text(
            encoding="utf-8"
        )
    )


def story_submission_for_spec(
    state: dict[str, object], spec: dict[str, object]
) -> dict[str, object]:
    fixture_value = stage2_fixture()
    assigned = set(spec["packet"]["assignedObligationIds"])
    upserts = []
    story_ids = set()
    for wrapper in fixture_value["replacementSet"]["upserts"]:
        node = wrapper["node"]
        obligation_ids = set(node.pop("fixtureObligationIds", []))
        if not obligation_ids.intersection(assigned):
            continue
        if wrapper["collection"] == "stories":
            story_ids.add(node["storyId"])
            upserts.append(wrapper)
        elif wrapper["collection"] == "acceptanceCriteria":
            story_ids.add(node["storyId"])
            upserts.append(wrapper)
        else:
            upserts.append(wrapper)
    upserts = [
        wrapper
        for wrapper in upserts
        if wrapper["collection"] != "acceptanceCriteria"
        or wrapper["node"]["storyId"] in story_ids
    ]
    return {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "PATCH",
        "reviewedEvidenceIds": list(spec["packet"]["assignedEvidenceIds"]),
        "replacementSet": {
            "expectedNodeHashes": {},
            "upserts": upserts,
            "deletes": [],
        },
        "selfCheck": {
            "completedCheckIds": list(spec["packet"]["requiredCheckIds"]),
            "unresolvedItems": [],
        },
    }


def execute_story_stage(state: dict[str, object] | None = None):
    current = state or story_stage_state()
    prepared = prepare_story_action(current, "STORY_AC")
    assert prepared["outcome"] == "ACTION_REQUIRED"
    records = [
        source_scan_record(current, spec, story_submission_for_spec(current, spec))
        for spec in prepared["specs"]
    ]
    return current, prepared, records, apply_story_group(current, records)


def test_story_packets_require_exact_scope_closure_checkpoint() -> None:
    state = story_stage_state()
    state["scopeClosureCheckpoint"] = copy.deepcopy(
        state["scopeClosureCheckpoint"]
    )
    state["scopeClosureCheckpoint"]["candidateSha256"] = "0" * 64

    prepared = prepare_story_action(state, "STORY_AC")

    assert prepared["outcome"] == "CONTRACT_UNSUPPORTED"
    assert prepared["specs"] == []
    assert "SCOPE_CHECKPOINT_BINDING_STALE" in {
        item["code"] for item in prepared["diagnostics"]
    }


def test_story_batch_contains_all_assigned_obligations_and_candidate_independent_evidence() -> None:
    state = story_stage_state()
    prepared = prepare_story_action(state, "STORY_AC")
    changed = copy.deepcopy(state)
    changed["baseCandidate"]["stories"] = [
        {
            "storyId": "story-untrusted-draft",
            "featureId": "feature-refund",
            "name": "不应成为证据的候选 Story",
            "coverageSet": ["feature-refund"],
            "requirementRefs": ["input-refund"],
            "designRefs": [],
            "policyRefs": [],
            "uatApplicable": True,
        }
    ]
    changed["candidate"] = changed["baseCandidate"]
    changed["baseCandidateSha256"] = sha256_bytes(
        canonical_json_bytes(changed["baseCandidate"])
    )
    changed_prepared = prepare_story_action(changed, "STORY_AC")

    assert prepared["outcome"] == "ACTION_REQUIRED"
    assigned = [
        obligation_id
        for spec in prepared["specs"]
        for obligation_id in spec["packet"]["assignedObligationIds"]
    ]
    assert sorted(assigned) == sorted(
        prepared["obligationProjection"]["obligationIds"]
    )
    assert len(assigned) == len(set(assigned))
    assert all(
        spec["packet"]["projectObligationRouting"]
        == prepared["obligationProjection"]["routing"]
        for spec in prepared["specs"]
    )
    assert [spec["evidenceCatalog"] for spec in prepared["specs"]] == [
        spec["evidenceCatalog"] for spec in changed_prepared["specs"]
    ]


def test_story_is_split_by_independent_closure_not_coverage_object_count() -> None:
    state = story_stage_state()
    candidate = state["baseCandidate"]
    source_item = next(
        item for item in candidate["inputItems"] if item["inputItemId"] == "input-refund"
    )
    split_item = copy.deepcopy(source_item)
    split_item["inputItemId"] = "input-refund-export"
    split_item["text"] = "退款结果由独立责任方生成导出物并独立发布。"
    split_item["applicableScopes"] = ["refund-export"]
    candidate["inputItems"].append(split_item)
    split_closure = copy.deepcopy(
        next(
            item
            for item in candidate["scopeClosure"]
            if item["inputItemId"] == "input-refund"
        )
    )
    split_closure.update(
        {
            "inputItemId": "input-refund-export",
            "preservedQualifiers": ["独立责任方", "独立发布"],
            "requiredQualifierRefs": ["boundary-refund-export"],
        }
    )
    candidate["scopeClosure"].append(split_closure)
    feature = next(
        item for item in candidate["features"] if item["featureId"] == "feature-refund"
    )
    feature["requirementRefs"].append("input-refund-export")
    projection = derive_story_obligations(
        candidate, state["effectivePolicyDecisions"]
    )
    ordinary = next(
        item for item in projection["obligations"] if item["subjectId"] == "input-refund"
    )
    independent = next(
        item
        for item in projection["obligations"]
        if item["subjectId"] == "input-refund-export"
    )

    assert ordinary["storyBoundaryKey"] != independent["storyBoundaryKey"]


def test_nine_homogeneous_services_share_one_story_and_coverage_set() -> None:
    _state, _prepared, _records, result = execute_story_stage()

    assert not result.diagnostics
    shared_stories = [
        item
        for item in result.model["stories"]
        if "input-shared-pipeline" in item["requirementRefs"]
    ]
    assert len(shared_stories) == 1
    assert shared_stories[0]["coverageSet"] == [
        f"service-{index:02d}" for index in range(1, 10)
    ]


def test_independent_customization_responsibility_acceptance_or_release_splits_story() -> None:
    projection = derive_story_obligations(
        story_stage_state()["baseCandidate"],
        story_stage_state()["effectivePolicyDecisions"],
    )
    requirement_keys = {
        item["storyBoundaryKey"]
        for item in projection["obligations"]
        if item["kind"] == "REQUIREMENT"
    }

    assert len(requirement_keys) > 1
    assert all(requirement_keys)


def test_story_ac_preserves_qualifiers_and_cannot_invent_design_or_tasks() -> None:
    state, prepared, records, result = execute_story_stage()
    assert not result.diagnostics
    all_ac_text = "\n".join(item["text"] for item in result.model["acceptanceCriteria"])
    expected_qualifiers = {
        qualifier
        for item in prepared["obligationProjection"]["obligations"]
        if item["kind"] == "REQUIREMENT"
        for qualifier in item["qualifiers"]
    }
    assert all(qualifier in all_ac_text for qualifier in expected_qualifiers)
    assert result.model["tasks"] == []
    assert result.model["designItems"] == state["baseCandidate"]["designItems"]

    bad_submission = story_submission_for_spec(state, prepared["specs"][0])
    bad_submission["replacementSet"]["upserts"].append(
        {
            "collection": "tasks",
            "node": {
                "taskId": "task-invented",
                "storyId": "story-refund",
            },
        }
    )
    bad_record = source_scan_record(state, prepared["specs"][0], bad_submission)
    progress = accept_story_result(state, bad_record)
    assert progress.outcome == "FAILED"
    assert "OWNER_WRITE_SCOPE_VIOLATION" in diagnostic_codes(progress)


def test_default_sit_uat_and_required_go_live_create_deliverable_story_ac() -> None:
    _state, _prepared, _records, result = execute_story_stage()
    assert not result.diagnostics
    for policy_id in (
        "policy-instance-sit",
        "policy-instance-uat",
        "policy-instance-go-live",
    ):
        policy_stories = [
            story for story in result.model["stories"] if policy_id in story["policyRefs"]
        ]
        assert policy_stories
        assert all(
            any(
                criterion["storyId"] == story["storyId"]
                and policy_id in criterion["policyRefs"]
                for criterion in result.model["acceptanceCriteria"]
            )
            for story in policy_stories
        )


def test_story_join_is_conditional_on_multiple_dynamic_shards() -> None:
    one = prepare_story_action(story_stage_state(), "STORY_AC")
    many = prepare_story_action(
        story_stage_state(token_budget=3000), "STORY_AC"
    )

    assert len(one["specs"]) == 1
    assert story_join_required(one) is False
    assert len(many["specs"]) > 1
    assert story_join_required(many) is True


def test_story_join_waits_for_every_sibling_before_single_apply() -> None:
    state = story_stage_state(token_budget=3000)
    prepared = prepare_story_action(state, "STORY_AC")
    first = prepared["specs"][0]
    record = source_scan_record(
        state, first, story_submission_for_spec(state, first)
    )

    progress = accept_story_result(state, record)
    result = apply_story_group(state, [record])

    assert progress.outcome == "ACTION_REQUIRED"
    assert progress.expected_action_ids
    assert "STORY_AC_GROUP_INCOMPLETE" in diagnostic_codes(result)
    assert result.model == state["baseCandidate"]


def story_checkpoint_state() -> tuple[dict[str, object], object]:
    state, _prepared, records, result = execute_story_stage()
    assert not result.diagnostics
    return {
        **state,
        "candidate": result.model,
        "storyActionRecords": records,
        "upstreamCheckpointSha256s": [
            sha256_bytes(canonical_json_bytes(state["scopeClosureCheckpoint"]))
        ],
    }, result


def test_story_ac_checkpoint_binds_scope_policy_projection_and_actions() -> None:
    state, result = story_checkpoint_state()

    built = build_story_ac_checkpoint(state)

    assert built["outcome"] == "READY_FOR_TASK"
    checkpoint = built["checkpoint"]
    assert checkpoint["kind"] == "STORY_AC"
    assert checkpoint["candidateSha256"] == result.model_sha256
    assert checkpoint["upstreamCheckpointSha256s"] == state[
        "upstreamCheckpointSha256s"
    ]
    assert checkpoint["obligationCounts"]["required"] == checkpoint[
        "obligationCounts"
    ]["closed"]
    assert checkpoint["outstandingIds"] == []
    assert len(checkpoint["actionRecordSha256s"]) == len(
        state["storyActionRecords"]
    )


def test_story_ac_checkpoint_recomputes_coverage_from_obligations() -> None:
    state, _result = story_checkpoint_state()
    story = next(
        item
        for item in state["candidate"]["stories"]
        if item["storyId"] == "story-shared-pipeline"
    )
    story["coverageSet"] = story["coverageSet"][:-1]

    built = build_story_ac_checkpoint(state)

    assert built["outcome"] == "OWNER_FIX_REQUIRED"
    assert "STORY_OBLIGATION_UNCLOSED" in {
        item.code for item in built["diagnostics"]
    }


def test_story_ac_checkpoint_survives_task_stage_additions() -> None:
    state, _result = story_checkpoint_state()
    checkpoint = build_story_ac_checkpoint(state)["checkpoint"]
    downstream = copy.deepcopy(state)
    downstream["candidate"]["tasks"] = [
        {
            "taskId": "task-refund",
            "storyId": "story-refund",
            "name": "开发退款提交",
            "workTypeId": "work-service-api",
            "rowSemanticSha256": "8" * 64,
            "workMode": "新建",
            "actualMeasurementScope": "退款提交接口",
            "complexity": "M",
            "acceptanceCriterionIds": ["ac-refund-submit"],
            "designItemIds": [],
            "integrationIds": [],
            "nfrIds": [],
            "policyInstanceIds": [],
        }
    ]

    assert validate_story_ac_checkpoint(checkpoint, downstream) == ()


def test_story_or_effective_policy_change_invalidates_story_ac_checkpoint() -> None:
    state, _result = story_checkpoint_state()
    checkpoint = build_story_ac_checkpoint(state)["checkpoint"]
    changed_story = copy.deepcopy(state)
    changed_story["candidate"]["stories"][0]["coverageSet"].append(
        "invented-object"
    )
    changed_policy = copy.deepcopy(state)
    changed_policy["effectivePolicyDecisions"]["policy-instance-sit"] = (
        "EXCLUDED"
    )

    assert "STORY_AC_CHECKPOINT_BINDING_STALE" in {
        item.code
        for item in validate_story_ac_checkpoint(checkpoint, changed_story)
    }
    assert "STORY_AC_CHECKPOINT_BINDING_STALE" in {
        item.code
        for item in validate_story_ac_checkpoint(checkpoint, changed_policy)
    }
