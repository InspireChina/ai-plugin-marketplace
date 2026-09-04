from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
TESTS = SKILL_ROOT / "tests"
FIXTURES = SKILL_ROOT / "fixtures"
TEMPLATE = SKILL_ROOT / "assets/sow-template.xlsx"
for path in (SCRIPTS, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from task_compiler import (  # noqa: E402
    accept_result,
    apply_ready_group,
    build_task_checkpoint,
    hydrate_catalog,
    prepare_action,
    validate_task_checkpoint,
)
from task_standard_catalog import catalog  # noqa: E402
from test_delivery_compiler import story_checkpoint_state  # noqa: E402
from test_scope_compiler import source_scan_record  # noqa: E402


def task_stage_state(*, token_budget: int = 30000) -> dict[str, object]:
    story_state, _result = story_checkpoint_state()
    story_checkpoint = build_task_story_checkpoint(story_state)
    source = catalog(TEMPLATE)
    return {
        **story_state,
        "storyBaseCandidate": copy.deepcopy(story_state["baseCandidate"]),
        "baseCandidate": copy.deepcopy(story_state["candidate"]),
        "baseCandidateSha256": sha256_bytes(
            canonical_json_bytes(story_state["candidate"])
        ),
        "storyAcCheckpoint": story_checkpoint,
        "taskCatalog": source,
        "taskEstimationMethodSha256": "6" * 64,
        "priorSowInputSha256": "NOT_PROVIDED",
        "maxInitialPacketTokens": token_budget,
        "maxOutputTokens": 8000,
        "modelProfileId": "author-task-v1",
        "modelConfigSha256": "5" * 64,
        "acceptedRecords": [],
    }


def build_task_story_checkpoint(story_state: dict[str, object]) -> dict[str, object]:
    from delivery_compiler import build_story_ac_checkpoint  # noqa: PLC0415

    return build_story_ac_checkpoint(story_state)["checkpoint"]


def task_fixture() -> dict[str, object]:
    return json.loads(
        (FIXTURES / "pipeline/stage3/task-results.json").read_text(
            encoding="utf-8"
        )
    )


def task_submission_for_spec(
    state: dict[str, object], spec: dict[str, object]
) -> dict[str, object]:
    assigned = set(spec["packet"]["assignedStoryIds"])
    value = task_fixture()
    rows = state["taskCatalog"].by_work_type_id
    upserts = []
    for wrapper in value["replacementSet"]["upserts"]:
        node = copy.deepcopy(wrapper["node"])
        assigned_story_ids = set(node.pop("fixtureStoryIds", []))
        if not assigned_story_ids.intersection(assigned):
            continue
        if wrapper["collection"] == "tasks":
            node["rowSemanticSha256"] = rows[node["workTypeId"]][
                "rowSemanticSha256"
            ]
        upserts.append({"collection": wrapper["collection"], "node": node})
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


def execute_task_stage(state: dict[str, object] | None = None):
    current = state or task_stage_state()
    prepared = prepare_action(current, "TASK")
    assert prepared["outcome"] == "ACTION_REQUIRED", prepared
    records = [
        source_scan_record(current, spec, task_submission_for_spec(current, spec))
        for spec in prepared["specs"]
    ]
    return current, prepared, records, apply_ready_group(current, records)


def diagnostic_codes(value) -> set[str]:
    return {item.code for item in value.diagnostics}


def test_task_packets_require_exact_story_ac_checkpoint() -> None:
    state = task_stage_state()
    state["storyAcCheckpoint"] = copy.deepcopy(state["storyAcCheckpoint"])
    state["storyAcCheckpoint"]["ownerProjectionSha256"] = "0" * 64

    prepared = prepare_action(state, "TASK")

    assert prepared["outcome"] == "CONTRACT_UNSUPPORTED"
    assert prepared["specs"] == []
    assert "STORY_AC_CHECKPOINT_BINDING_STALE" in {
        item["code"] for item in prepared["diagnostics"]
    }


def test_task_packet_has_full_compact_index_but_hydrates_only_selected_rules() -> None:
    state = task_stage_state()
    prepared = prepare_action(state, "TASK")
    packet = prepared["specs"][0]["packet"]

    assert len(packet["taskStandardCompactIndex"]) == 88
    assert all("S标准" not in item for item in packet["taskStandardCompactIndex"])
    hydrated = hydrate_catalog(
        state,
        selected_work_type_ids=["FE-COMMAND-API"],
        query="退款提交接口",
    )
    assert hydrated.selected_work_type_ids == ("FE-COMMAND-API",)
    assert hydrated.rows[0]["工作类型ID"] == "FE-COMMAND-API"
    assert "S标准" in hydrated.rows[0]


def test_task_batches_use_story_affinity_and_candidate_independent_evidence() -> None:
    state = task_stage_state(token_budget=12000)
    prepared = prepare_action(state, "TASK")
    changed = copy.deepcopy(state)
    changed["baseCandidate"]["tasks"] = [
        {
            "taskId": "task-untrusted",
            "storyId": "story-refund",
            "name": "不应成为证据的候选任务",
            "workTypeId": "FE-COMMAND-API",
            "rowSemanticSha256": "0" * 64,
            "workMode": "新建",
            "actualMeasurementScope": "草稿",
            "complexity": "M",
            "acceptanceCriterionIds": ["ac-refund-submit"],
            "designItemIds": [],
            "integrationIds": [],
            "nfrIds": [],
            "policyInstanceIds": [],
        }
    ]
    changed["baseCandidateSha256"] = sha256_bytes(
        canonical_json_bytes(changed["baseCandidate"])
    )
    changed_prepared = prepare_action(changed, "TASK")

    assigned = [
        story_id
        for spec in prepared["specs"]
        for story_id in spec["packet"]["assignedStoryIds"]
    ]
    assert sorted(assigned) == sorted(
        item["storyId"] for item in state["baseCandidate"]["stories"]
    )
    assert [spec["evidenceCatalog"] for spec in prepared["specs"]] == [
        spec["evidenceCatalog"] for spec in changed_prepared["specs"]
    ]


def test_task_apply_preserves_story_ac_and_closes_each_story_ac() -> None:
    state, _prepared, _records, result = execute_task_stage()

    assert not result.diagnostics
    assert result.model["stories"] == state["baseCandidate"]["stories"]
    assert result.model["acceptanceCriteria"] == state["baseCandidate"][
        "acceptanceCriteria"
    ]
    by_story = {
        story["storyId"]: {
            criterion["acceptanceCriterionId"]
            for criterion in result.model["acceptanceCriteria"]
            if criterion["storyId"] == story["storyId"]
        }
        for story in result.model["stories"]
    }
    for story_id, criterion_ids in by_story.items():
        covered = {
            criterion_id
            for task in result.model["tasks"]
            if task["storyId"] == story_id
            for criterion_id in task["acceptanceCriterionIds"]
        }
        assert covered == criterion_ids


def test_nine_services_are_one_pipeline_measurement_not_nine_tasks() -> None:
    _state, _prepared, _records, result = execute_task_stage()

    tasks = [
        item
        for item in result.model["tasks"]
        if item["storyId"] == "story-shared-pipeline"
    ]
    assert len(tasks) == 1
    assert tasks[0]["workTypeId"] == "ENG-PIPELINE"
    assert "一套" in tasks[0]["actualMeasurementScope"]
    assert "九个服务" in tasks[0]["actualMeasurementScope"]


def test_catalog_row_hash_mode_and_effective_start_must_match() -> None:
    state = task_stage_state()
    prepared = prepare_action(state, "TASK")
    spec = prepared["specs"][0]
    submission = task_submission_for_spec(state, spec)
    task = next(
        item["node"]
        for item in submission["replacementSet"]["upserts"]
        if item["collection"] == "tasks"
    )
    task["rowSemanticSha256"] = "0" * 64
    task["workMode"] = "接入复用"
    record = source_scan_record(state, spec, submission)

    progress = accept_result(state, record)

    assert progress.outcome == "FAILED"
    assert diagnostic_codes(progress) >= {
        "TASK_STANDARD_HASH_MISMATCH",
        "TASK_EFFECTIVE_START_MODE_MISMATCH",
    }


def test_no_prior_sow_uses_explicit_no_match_new_decisions() -> None:
    _state, _prepared, _records, result = execute_task_stage()

    assert not result.diagnostics
    assert len(result.model["effectiveStartMatches"]) == len(result.model["tasks"])
    assert {
        item["decision"] for item in result.model["effectiveStartMatches"]
    } == {"NO_MATCH_NEW"}
    assert {item["workMode"] for item in result.model["tasks"]} == {"新建"}


def test_task_checkpoint_binds_catalog_method_prior_sow_and_used_rows() -> None:
    state, _prepared, records, result = execute_task_stage()
    checkpoint_state = {
        **state,
        "candidate": result.model,
        "taskActionRecords": records,
    }

    built = build_task_checkpoint(checkpoint_state)

    assert built["outcome"] == "READY_FOR_REVIEW"
    checkpoint = built["checkpoint"]
    assert checkpoint["taskCatalogSemanticSha256"] == state[
        "taskCatalog"
    ].task_catalog_semantic_sha256
    assert checkpoint["taskEstimationMethodSha256"] == "6" * 64
    assert checkpoint["priorSowInputSha256"] == "NOT_PROVIDED"
    assert {item["workTypeId"] for item in checkpoint["usedTaskStandards"]} == {
        item["workTypeId"] for item in result.model["tasks"]
    }
    assert validate_task_checkpoint(checkpoint, checkpoint_state) == ()
