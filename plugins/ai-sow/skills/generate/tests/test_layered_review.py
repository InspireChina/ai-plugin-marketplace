from __future__ import annotations

import copy
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
TESTS = SKILL_ROOT / "tests"
PLUGIN_ROOT = SKILL_ROOT.parents[1]
for path in (SCRIPTS, TESTS, PLUGIN_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from final_review import (  # noqa: E402
    _layered_projection,
    _normalize_findings,
    advance_layered_review,
    build_repair_plan,
    prepare_adjudications,
    prepare_layered_review,
    prepare_theme_joins,
    validate_adjudication_result,
    validate_layered_review_result,
    validate_theme_join_result,
)
from task_compiler import build_task_checkpoint  # noqa: E402
from test_task_compiler import execute_task_stage  # noqa: E402


def review_state() -> dict[str, object]:
    task_state, _prepared, records, result = execute_task_stage()
    checkpoint_state = {
        **task_state,
        "candidate": result.model,
        "taskActionRecords": records,
    }
    task_checkpoint = build_task_checkpoint(checkpoint_state)["checkpoint"]
    return {
        **checkpoint_state,
        "taskCheckpoint": task_checkpoint,
        "reviewSetId": "review-layered-001",
        "maxInitialPacketTokens": 12000,
        "maxOutputTokens": 5000,
        "modelProfileId": "reviewer-layered-v1",
        "modelConfigSha256": "4" * 64,
    }


def pass_result(
    state: dict[str, object],
    prepared: dict[str, object],
    spec: dict[str, object],
) -> dict[str, object]:
    packet = spec["packet"]
    return {
        "contract": "ai-sow-review-result-v1",
        "reviewResultId": f"result-{spec['logicalShardId']}",
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "kind": packet["reviewKind"],
        "reviewPlanSha256": prepared["reviewPlanSha256"],
        "candidateProjectionSha256": prepared[
            "candidateProjectionSha256"
        ],
        "coverageSha256": packet["coverageSha256"],
        "completedCheckIds": list(packet["requiredCheckIds"]),
        "decision": "PASS",
        "findings": [],
    }


def _state_with_story_themes(theme_ids: list[str]) -> dict[str, object]:
    state = review_state()
    candidate = copy.deepcopy(state["candidate"])
    story_template = copy.deepcopy(candidate["stories"][0])
    feature_template = copy.deepcopy(candidate["features"][0])
    candidate["stories"] = []
    candidate["features"] = []
    candidate["acceptanceCriteria"] = []
    for index, theme_id in enumerate(theme_ids, 1):
        story = copy.deepcopy(story_template)
        story["storyId"] = f"story-capacity-{index:02d}"
        story["featureId"] = theme_id
        candidate["stories"].append(story)
        if not any(item["featureId"] == theme_id for item in candidate["features"]):
            feature = copy.deepcopy(feature_template)
            feature["featureId"] = theme_id
            candidate["features"].append(feature)
    state["candidate"] = candidate
    state["storyAcCheckpoint"] = copy.deepcopy(state["storyAcCheckpoint"])
    state["storyAcCheckpoint"]["ownerProjectionSha256"] = _layered_projection(
        candidate, "STORY_DESIGN"
    )[1]
    return state


def test_layered_review_allows_more_than_eight_total_shards_across_themes() -> None:
    state = _state_with_story_themes(
        [f"feature-capacity-{index:02d}" for index in range(1, 10)]
    )

    prepared = prepare_layered_review(state, "STORY_DESIGN")

    assert prepared["outcome"] == "ACTION_REQUIRED"
    assert len(prepared["specs"]) == 9
    assert max(
        shard["physicalShardIndex"] for shard in prepared["reviewPlan"]["shards"]
    ) == 0


def test_layered_review_rejects_ninth_physical_shard_in_one_theme() -> None:
    state = _state_with_story_themes(["feature-capacity-shared"] * 9)

    prepared = prepare_layered_review(state, "STORY_DESIGN")

    assert prepared["outcome"] == "CONTRACT_UNSUPPORTED"
    assert "LAYERED_REVIEW_CAPACITY_EXCEEDED" in {
        item.code for item in prepared["diagnostics"]
    }


def test_story_design_and_task_estimation_reviews_bind_exact_checkpoints() -> None:
    state = review_state()
    story = prepare_layered_review(state, "STORY_DESIGN")
    task = prepare_layered_review(state, "TASK_ESTIMATION")

    assert story["outcome"] == "ACTION_REQUIRED"
    assert task["outcome"] == "ACTION_REQUIRED"
    assert all(
        spec["packet"]["stageCheckpointSha256"]
        == sha256_bytes(canonical_json_bytes(state["storyAcCheckpoint"]))
        for spec in story["specs"]
    )
    assert all(
        spec["packet"]["stageCheckpointSha256"]
        == sha256_bytes(canonical_json_bytes(state["taskCheckpoint"]))
        for spec in task["specs"]
    )
    assert all(spec["role"] == "REVIEWER" for spec in [*story["specs"], *task["specs"]])


def test_leaf_review_finding_must_bind_reachable_subject_and_evidence() -> None:
    state = review_state()
    prepared = prepare_layered_review(state, "STORY_DESIGN")
    spec = prepared["specs"][0]
    result = pass_result(state, prepared, spec)
    result["decision"] = "OWNER_FIX_REQUIRED"
    result["findings"] = [
        {
            "findingId": "finding-unknown",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": ["story-unknown"],
            "evidenceIds": ["evidence-unknown"],
            "summary": "未知证据和对象不应被接受。",
        }
    ]

    diagnostics = validate_layered_review_result(
        state, prepared, spec["logicalShardId"], result
    )

    assert {item.code for item in diagnostics} >= {
        "REVIEW_FINDING_SUBJECT_UNKNOWN",
        "REVIEW_FINDING_EVIDENCE_UNREACHABLE",
    }


def test_multi_leaf_logical_theme_requires_join_but_single_leaf_does_not() -> None:
    state = review_state()
    prepared = prepare_layered_review(state, "STORY_DESIGN")
    results = [
        {
            "logicalShardId": spec["logicalShardId"],
            "result": pass_result(state, prepared, spec),
        }
        for spec in prepared["specs"]
    ]

    joins = prepare_theme_joins(state, prepared, results)
    shard_counts: dict[str, int] = {}
    for shard in prepared["reviewPlan"]["shards"]:
        shard_counts[shard["logicalThemeId"]] = shard_counts.get(
            shard["logicalThemeId"], 0
        ) + 1

    expected = {theme for theme, count in shard_counts.items() if count > 1}
    assert {spec["packet"]["logicalThemeId"] for spec in joins["specs"]} == expected
    assert "feature-refund" not in expected
    assert "feature-shared-pipeline" in expected


def test_theme_join_binds_every_leaf_hash_and_cannot_discard_finding() -> None:
    state = review_state()
    prepared = prepare_layered_review(state, "STORY_DESIGN")
    wrappers = [
        {
            "logicalShardId": spec["logicalShardId"],
            "result": pass_result(state, prepared, spec),
        }
        for spec in prepared["specs"]
    ]
    shared_spec = next(
        spec
        for spec in prepared["specs"]
        if spec["packet"]["logicalThemeId"] == "feature-shared-pipeline"
    )
    shared_result = next(
        item["result"]
        for item in wrappers
        if item["logicalShardId"] == shared_spec["logicalShardId"]
    )
    shared_result["decision"] = "OWNER_FIX_REQUIRED"
    shared_result["findings"] = [
        {
            "findingId": "finding-shared-design",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": [shared_spec["packet"]["subjectIds"][0]],
            "evidenceIds": [shared_spec["packet"]["evidenceIds"][0]],
            "summary": "共享交付边界需要返修。",
        }
    ]
    joins = prepare_theme_joins(state, prepared, wrappers)
    join_spec = next(
        item
        for item in joins["specs"]
        if item["packet"]["logicalThemeId"] == "feature-shared-pipeline"
    )
    result = {
        "contract": "ai-sow-review-result-v1",
        "reviewResultId": "result-theme-shared",
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "kind": "THEME_JOIN",
        "reviewPlanSha256": prepared["reviewPlanSha256"],
        "candidateProjectionSha256": prepared[
            "candidateProjectionSha256"
        ],
        "coverageSha256": join_spec["packet"]["coverageSha256"],
        "completedCheckIds": list(join_spec["packet"]["requiredCheckIds"]),
        "decision": "PASS",
        "findings": [],
        "leafReviewResultSha256s": list(
            join_spec["packet"]["leafReviewResultSha256s"]
        ),
    }

    diagnostics = validate_theme_join_result(
        state, prepared, join_spec, result
    )

    assert "THEME_JOIN_FINDING_DROPPED" in {item.code for item in diagnostics}


def test_theme_join_cannot_rewrite_or_inject_leaf_findings() -> None:
    state = review_state()
    prepared = prepare_layered_review(state, "STORY_DESIGN")
    wrappers = [
        {
            "logicalShardId": spec["logicalShardId"],
            "result": pass_result(state, prepared, spec),
        }
        for spec in prepared["specs"]
    ]
    shared_spec = next(
        spec
        for spec in prepared["specs"]
        if spec["packet"]["logicalThemeId"] == "feature-shared-pipeline"
    )
    shared_result = next(
        item["result"]
        for item in wrappers
        if item["logicalShardId"] == shared_spec["logicalShardId"]
    )
    canonical_finding = {
        "findingId": "finding-shared-design",
        "type": "OWNER_FIX_REQUIRED",
        "owner": "STAGE_2",
        "subjectIds": [shared_spec["packet"]["subjectIds"][0]],
        "evidenceIds": [shared_spec["packet"]["evidenceIds"][0]],
        "summary": "共享交付边界需要返修。",
    }
    shared_result["decision"] = "OWNER_FIX_REQUIRED"
    shared_result["findings"] = [canonical_finding]
    joins = prepare_theme_joins(state, prepared, wrappers)
    join_spec = next(
        item
        for item in joins["specs"]
        if item["packet"]["logicalThemeId"] == "feature-shared-pipeline"
    )
    rewritten = copy.deepcopy(canonical_finding)
    rewritten["owner"] = "STAGE_3"
    injected = copy.deepcopy(canonical_finding)
    injected["findingId"] = "finding-injected"
    result = {
        "contract": "ai-sow-review-result-v1",
        "reviewResultId": "result-theme-rewrite",
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "kind": "THEME_JOIN",
        "reviewPlanSha256": prepared["reviewPlanSha256"],
        "candidateProjectionSha256": prepared["candidateProjectionSha256"],
        "coverageSha256": join_spec["packet"]["coverageSha256"],
        "completedCheckIds": list(join_spec["packet"]["requiredCheckIds"]),
        "decision": "OWNER_FIX_REQUIRED",
        "findings": [rewritten, injected],
        "leafReviewResultSha256s": list(
            join_spec["packet"]["leafReviewResultSha256s"]
        ),
    }

    diagnostics = validate_theme_join_result(state, prepared, join_spec, result)

    assert {item.code for item in diagnostics} >= {
        "THEME_JOIN_FINDING_SET_MISMATCH",
        "THEME_JOIN_FINDING_CONTENT_MISMATCH",
    }


def test_conflicting_findings_require_fresh_adjudication() -> None:
    state = review_state()
    findings = [
        {
            "findingId": "finding-a",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": ["story-refund"],
            "evidenceIds": ["task-input-story-refund"],
            "summary": "应拆分 Story。",
        },
        {
            "findingId": "finding-b",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": ["story-refund"],
            "evidenceIds": ["task-input-story-refund"],
            "summary": "应保留一个 Story。",
        },
    ]

    result = prepare_adjudications(state, findings)

    assert result["outcome"] == "ACTION_REQUIRED"
    assert len(result["specs"]) == 1
    assert result["specs"][0]["role"] == "ADJUDICATOR"
    assert result["specs"][0]["packet"]["findingIds"] == [
        "finding-a",
        "finding-b",
    ]


def test_identical_duplicate_finding_ids_are_globally_deduplicated() -> None:
    finding = {
        "findingId": "finding-shared",
        "type": "OWNER_FIX_REQUIRED",
        "owner": "STAGE_2",
        "subjectIds": ["story-refund"],
        "evidenceIds": ["task-input-story-refund"],
        "summary": "两个独立评审发现同一个问题。",
    }

    normalized, diagnostics = _normalize_findings(
        [finding, copy.deepcopy(finding)]
    )
    adjudications = prepare_adjudications(
        review_state(), [finding, copy.deepcopy(finding)]
    )

    assert normalized == [finding]
    assert diagnostics == ()
    assert adjudications["outcome"] == "PASS"
    assert adjudications["diagnostics"] == ()


def test_conflicting_duplicate_finding_id_returns_structured_diagnostic() -> None:
    original = {
        "findingId": "finding-shared",
        "type": "OWNER_FIX_REQUIRED",
        "owner": "STAGE_2",
        "subjectIds": ["story-refund"],
        "evidenceIds": ["task-input-story-refund"],
        "summary": "应拆分 Story。",
    }
    conflicting = copy.deepcopy(original)
    conflicting["summary"] = "应保留一个 Story。"

    normalized, diagnostics = _normalize_findings([original, conflicting])
    adjudications = prepare_adjudications(
        review_state(), [original, conflicting]
    )

    assert normalized == [original]
    assert {item.code for item in diagnostics} == {
        "REVIEW_FINDING_ID_CONFLICT"
    }
    assert adjudications["outcome"] == "OWNER_FIX_REQUIRED"
    assert adjudications["specs"] == []
    assert {item.code for item in adjudications["diagnostics"]} == {
        "REVIEW_FINDING_ID_CONFLICT"
    }


def test_conflicts_are_indexed_by_every_finding_subject() -> None:
    state = review_state()
    findings = [
        {
            "findingId": "finding-a",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": ["story-refund", "story-i18n"],
            "evidenceIds": ["task-input-story-refund"],
            "summary": "应拆分 Story。",
        },
        {
            "findingId": "finding-b",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": ["story-i18n"],
            "evidenceIds": ["task-input-story-refund"],
            "summary": "应保留一个 Story。",
        },
    ]

    result = prepare_adjudications(state, findings)

    assert result["outcome"] == "ACTION_REQUIRED"
    assert [spec["packet"]["subjectIds"] for spec in result["specs"]] == [
        ["story-i18n"]
    ]


def test_multi_subject_conflicts_form_one_connected_adjudication_proposition() -> None:
    state = review_state()
    findings = [
        {
            "findingId": "finding-shared",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": ["story-refund", "story-i18n"],
            "evidenceIds": ["task-input-story-refund"],
            "summary": "两个 Story 应共同调整。",
        },
        {
            "findingId": "finding-refund",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": ["story-refund"],
            "evidenceIds": ["task-input-story-refund"],
            "summary": "退款 Story 应保持不变。",
        },
        {
            "findingId": "finding-i18n",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": ["story-i18n"],
            "evidenceIds": ["task-input-story-refund"],
            "summary": "国际化 Story 应保持不变。",
        },
    ]

    result = prepare_adjudications(state, findings)

    assert result["outcome"] == "ACTION_REQUIRED"
    assert len(result["specs"]) == 1
    packet = result["specs"][0]["packet"]
    assert packet["subjectIds"] == ["story-i18n", "story-refund"]
    assert packet["findingIds"] == [
        "finding-i18n",
        "finding-refund",
        "finding-shared",
    ]


def test_adjudication_cannot_rewrite_selected_finding() -> None:
    state = review_state()
    findings = [
        {
            "findingId": "finding-a",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": ["story-refund"],
            "evidenceIds": ["task-input-story-refund"],
            "summary": "应拆分 Story。",
        },
        {
            "findingId": "finding-b",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": ["story-refund"],
            "evidenceIds": ["task-input-story-refund"],
            "summary": "应保留一个 Story。",
        },
    ]
    spec = prepare_adjudications(state, findings)["specs"][0]
    packet = spec["packet"]
    rewritten = copy.deepcopy(findings[0])
    rewritten["summary"] = "被裁决器擅自改写。"
    result = {
        "contract": "ai-sow-review-result-v1",
        "reviewResultId": "result-adjudication-rewrite",
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "kind": "ADJUDICATION",
        "reviewPlanSha256": packet["reviewPlanSha256"],
        "candidateProjectionSha256": packet["candidateProjectionSha256"],
        "coverageSha256": packet["coverageSha256"],
        "completedCheckIds": list(packet["requiredCheckIds"]),
        "decision": "OWNER_FIX_REQUIRED",
        "findings": [rewritten],
        "propositionId": packet["propositionId"],
        "selectedFindingIds": ["finding-a"],
    }

    diagnostics = validate_adjudication_result(state, spec, result)

    assert "ADJUDICATION_FINDING_CONTENT_MISMATCH" in {
        item.code for item in diagnostics
    }


def test_repair_plan_starts_at_earliest_owner_and_locks_unaffected_nodes() -> None:
    state = review_state()
    findings = [
        {
            "findingId": "finding-story",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_2",
            "subjectIds": ["story-refund"],
            "evidenceIds": ["task-input-story-refund"],
            "summary": "Story 需返修。",
        },
        {
            "findingId": "finding-task",
            "type": "OWNER_FIX_REQUIRED",
            "owner": "STAGE_3",
            "subjectIds": ["task-refund-api"],
            "evidenceIds": ["task-input-story-refund"],
            "summary": "Task 需随上游重算。",
        },
    ]

    plan = build_repair_plan(state, findings)

    assert plan["earliestOwner"] == "STAGE_2"
    assert [wave["resumePhase"] for wave in plan["waves"]] == [
        "STORY_AC",
        "TASK",
    ]
    assert "story-refund" in plan["waves"][0]["editableNodeIds"]
    assert "story-i18n" in plan["waves"][0]["lockedNodeIds"]


def test_layered_review_state_machine_starts_with_story_design_leaves() -> None:
    result = advance_layered_review(review_state())

    assert result["outcome"] == "ACTION_REQUIRED"
    assert result["reviewKind"] == "STORY_DESIGN"
    assert result["stage"] == "STORY_DESIGN"
    assert result["specs"]


def test_layered_review_pass_proof_binds_every_leaf_and_theme_result() -> None:
    state = review_state()
    captured_hashes: list[str] = []
    for kind, leaf_field, join_field in (
        ("STORY_DESIGN", "storyDesignReviewResults", "storyDesignThemeJoinResults"),
        ("TASK_ESTIMATION", "taskEstimationReviewResults", "taskEstimationThemeJoinResults"),
    ):
        prepared = prepare_layered_review(state, kind)
        leaves = [
            {
                "logicalShardId": spec["logicalShardId"],
                "result": pass_result(state, prepared, spec),
            }
            for spec in prepared["specs"]
        ]
        state[leaf_field] = leaves
        captured_hashes.extend(
            sha256_bytes(canonical_json_bytes(item["result"])) for item in leaves
        )
        joins = prepare_theme_joins(state, prepared, leaves)
        join_results = []
        for spec in joins["specs"]:
            packet = spec["packet"]
            result = {
                "contract": "ai-sow-review-result-v1",
                "reviewResultId": f"result-{spec['logicalShardId']}",
                "reviewSetId": state["reviewSetId"],
                "runId": state["runId"],
                "kind": "THEME_JOIN",
                "reviewPlanSha256": prepared["reviewPlanSha256"],
                "candidateProjectionSha256": prepared[
                    "candidateProjectionSha256"
                ],
                "coverageSha256": packet["coverageSha256"],
                "completedCheckIds": list(packet["requiredCheckIds"]),
                "decision": "PASS",
                "findings": [],
                "leafReviewResultSha256s": list(
                    packet["leafReviewResultSha256s"]
                ),
            }
            join_results.append(
                {"logicalShardId": spec["logicalShardId"], "result": result}
            )
            captured_hashes.append(sha256_bytes(canonical_json_bytes(result)))
        state[join_field] = join_results

    result = advance_layered_review(state)

    assert result["outcome"] == "READY_FOR_APPROVAL"
    assert result["reviewDecision"]["decision"] == "PASS"
    assert set(result["reviewDecision"]["reviewResultSha256s"]) == set(
        captured_hashes
    )
    assert result["reviewDecisionSha256"] == sha256_bytes(
        canonical_json_bytes(result["reviewDecision"])
    )
