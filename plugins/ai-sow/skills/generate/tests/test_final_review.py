from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
TESTS = SKILL_ROOT / "tests"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from final_review import build_review_packet, record_review  # noqa: E402
from orchestrator import prepare_review, run_mode  # noqa: E402
from questions import question_sha256  # noqa: E402
from runtime.project_io import ProjectFiles  # noqa: E402
from test_orchestrator import (  # noqa: E402
    NOW,
    prepare_delivery_files,
    prepare_scope_files,
    write_request,
)


def stage_delivery(project: Path) -> dict[str, object]:
    request_path = write_request(project)
    prepared = run_mode(project, "prepare", request=request_path, now=NOW)
    prepare_scope_files(project, prepared)
    scope_result = run_mode(
        project,
        "accept-scope",
        candidate="scope.json",
        ids="scope-ids.json",
        now=NOW,
    )
    assert scope_result["outcome"] == "READY_FOR_DELIVERY", scope_result
    prepare_delivery_files(project, prepared)
    delivery_result = run_mode(
        project,
        "accept-delivery",
        candidate="delivery.json",
        ids="delivery-ids.json",
        now=NOW,
    )
    assert delivery_result["outcome"] == "REVIEW_REQUIRED", delivery_result
    return prepared


def diagnostic_codes(result) -> set[str]:
    return {item.code for item in result.diagnostics}


def build_packet_with_delivery_story(tmp_path: Path, story_name: str) -> dict[str, object]:
    stage_delivery(tmp_path)
    for relative_path in (
        ".ai-sow/work/delivery-slice.candidate.json",
        ".ai-sow/work/delivery.candidate.json",
    ):
        path = tmp_path / relative_path
        delivery = json.loads(path.read_text(encoding="utf-8"))
        delivery["stories"][0]["name"] = story_name
        path.write_bytes(canonical_json_bytes(delivery))
    result = build_review_packet(ProjectFiles.open(tmp_path))
    assert result.outcome == "REVIEW_REQUIRED", result.diagnostics
    return json.loads((tmp_path / str(result.packet_path)).read_text(encoding="utf-8"))


def build_packet_with_delivery_task(tmp_path: Path, task_name: str) -> dict[str, object]:
    stage_delivery(tmp_path)
    for relative_path in (
        ".ai-sow/work/delivery-slice.candidate.json",
        ".ai-sow/work/delivery.candidate.json",
    ):
        path = tmp_path / relative_path
        delivery = json.loads(path.read_text(encoding="utf-8"))
        delivery["tasks"][0]["name"] = task_name
        path.write_bytes(canonical_json_bytes(delivery))
    result = build_review_packet(ProjectFiles.open(tmp_path))
    assert result.outcome == "REVIEW_REQUIRED", result.diagnostics
    return json.loads((tmp_path / str(result.packet_path)).read_text(encoding="utf-8"))


def test_review_packet_binds_run_template_snapshot(tmp_path: Path) -> None:
    stage_delivery(tmp_path)

    result = build_review_packet(ProjectFiles.open(tmp_path))

    packet = json.loads((tmp_path / str(result.packet_path)).read_text(encoding="utf-8"))
    plan = json.loads(
        (tmp_path / ".ai-sow/work/run-plan.json").read_text(encoding="utf-8")
    )
    assert packet["artifacts"]["template"]["path"] == plan["templateSnapshotPath"]
    assert packet["artifacts"]["template"]["sha256"] == plan["templateSha256"]


def test_question_answer_source_ref_is_accepted_by_scope_delivery_and_review(
    tmp_path: Path,
) -> None:
    request_path = write_request(tmp_path)
    request_file = tmp_path / request_path
    request = json.loads(request_file.read_text(encoding="utf-8"))
    question = question_fixture()
    answer = {
        "questionId": question["questionId"],
        "questionSha256": question_sha256(question),
        "answer": "已有，并允许本项目直接调整。",
    }
    request["questions"] = [question]
    request["questionnaireAnswers"] = [answer]
    request_file.write_bytes(canonical_json_bytes(request))
    prepared = run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    anchors = json.loads(
        (tmp_path / ".ai-sow/inputs/pending/anchors.json").read_text(encoding="utf-8")
    )
    answer_anchor = next(
        anchor for anchor in anchors if anchor["kind"] == "QUESTION_ANSWER"
    )
    source_ref = {
        "sourceId": answer_anchor["sourceId"],
        "anchorId": answer_anchor["anchorId"],
        "locator": answer_anchor["locator"],
        "sha256": answer_anchor["sha256"],
    }

    prepare_scope_files(tmp_path, prepared)
    scope_candidate = json.loads((tmp_path / "scope.json").read_text(encoding="utf-8"))
    scope_candidate["features"][0]["sourceRefs"] = [source_ref]
    (tmp_path / "scope.json").write_bytes(canonical_json_bytes(scope_candidate))
    scope_result = run_mode(
        tmp_path,
        "accept-scope",
        candidate="scope.json",
        ids="scope-ids.json",
        now=NOW,
    )
    assert scope_result["outcome"] == "READY_FOR_DELIVERY", scope_result

    prepare_delivery_files(tmp_path, prepared)
    delivery_candidate = json.loads(
        (tmp_path / "delivery.json").read_text(encoding="utf-8")
    )
    delivery_candidate["acceptanceCriteria"][0]["sourceRefs"] = [source_ref]
    (tmp_path / "delivery.json").write_bytes(canonical_json_bytes(delivery_candidate))
    delivery_result = run_mode(
        tmp_path,
        "accept-delivery",
        candidate="delivery.json",
        ids="delivery-ids.json",
        now=NOW,
    )
    assert delivery_result["outcome"] == "REVIEW_REQUIRED", delivery_result

    packet_result = build_review_packet(ProjectFiles.open(tmp_path))
    packet = json.loads(
        (tmp_path / str(packet_result.packet_path)).read_text(encoding="utf-8")
    )
    inventory_entry = next(
        item
        for item in packet["sourceRefInventory"]
        if item["anchorId"] == answer_anchor["anchorId"]
    )
    criterion_entry = next(
        item
        for item in packet["acceptanceCriterionSources"]
        if item["acceptanceCriterionId"] == "ac-refund-submit"
    )

    assert packet_result.outcome == "REVIEW_REQUIRED", packet_result.diagnostics
    assert {
        key: inventory_entry[key]
        for key in ("sourceId", "anchorId", "locator", "sha256")
    } == source_ref
    assert packet["bundles"]["inputManifest"]["questions"] == [question]
    assert packet["bundles"]["inputManifest"]["questionnaireAnswers"] == [answer]
    assert criterion_entry == {
        "acceptanceCriterionId": "ac-refund-submit",
        "storyId": "story-refund-processing",
        "sourceRefs": [source_ref],
        "resolvable": True,
    }


def test_reviewer_instruction_is_self_contained_for_the_review_contract() -> None:
    instruction = (
        SKILL_ROOT / "references/final-review.md"
    ).read_text(encoding="utf-8")

    for required in (
        '"scopeSha256"',
        '"deliverySha256"',
        '"packetSha256"',
        '"decision"',
        '"noteId"',
        '"subjectIds"',
        '"sowNotesText"',
        '"questionId"',
        '"reason"',
        '"decisionImpact"',
        '"unansweredEffect"',
        "packet.artifacts.scope.sha256",
        "packet.artifacts.delivery.sha256",
        "review-packet.json 原始字节",
    ):
        assert required in instruction


def test_story_effort_is_only_a_non_blocking_authoring_reference() -> None:
    reviewer = (SKILL_ROOT / "references/final-review.md").read_text(encoding="utf-8")

    assert "Story 的 1–5 个工作日只作经验参考" in reviewer
    assert "不得根据工作簿中的 Story 人天" in reviewer


def test_single_story_feature_is_a_review_claim_not_a_compile_failure(
    tmp_path: Path,
) -> None:
    stage_delivery(tmp_path)
    result = build_review_packet(ProjectFiles.open(tmp_path))
    assert result.outcome == "REVIEW_REQUIRED", result.diagnostics
    packet = json.loads((tmp_path / str(result.packet_path)).read_text(encoding="utf-8"))

    claim = packet["claims"]["featureGrain"][0]
    assert claim["featureId"] == "feature-refund-processing"
    assert claim["requiresReview"] is True


def test_review_packet_does_not_infer_claims_from_business_language(
    tmp_path: Path,
) -> None:
    packet = build_packet_with_delivery_task(
        tmp_path, "持续支持上线并保障稳定运行，客户负责生产发布审批"
    )

    assert "deliveryWork" not in packet["claims"]


def test_optional_automation_is_not_added_without_source(tmp_path: Path) -> None:
    stage_delivery(tmp_path)
    result = build_review_packet(ProjectFiles.open(tmp_path))
    packet = json.loads((tmp_path / str(result.packet_path)).read_text(encoding="utf-8"))

    assert not any(
        "自动化回归" in item["name"]
        for collection in ("stories", "tasks")
        for item in packet["bundles"]["delivery"][collection]
    )


def test_reviewer_contract_returns_known_correctable_defects_before_review_json() -> None:
    reviewer = (SKILL_ROOT / "references/final-review.md").read_text(encoding="utf-8")

    for required in (
        "不得提交 `accept-review` JSON",
        "已有 packet",
        "return to Owner",
        "重新编译候选",
        "重建 review packet",
        "fresh-context review",
        "BLOCKED JSON",
        "用户可以明确回答",
    ):
        assert required in reviewer


def review_value(project: Path, packet_sha: str, decision: str = "PASS"):
    plan = json.loads(
        (project / ".ai-sow/work/run-plan.json").read_text(encoding="utf-8")
    )
    return {
        "contract": "ai-sow-final-review-v1",
        "runId": plan["runId"],
        "inputRevisionId": plan["targetRevisionId"],
        "scopeSha256": sha256_bytes(
            (project / ".ai-sow/work/scope.candidate.json").read_bytes()
        ),
        "deliverySha256": sha256_bytes(
            (project / ".ai-sow/work/delivery.candidate.json").read_bytes()
        ),
        "packetSha256": packet_sha,
        "decision": decision,
        "notes": [],
        "questions": [],
    }


def blocking_question(question_id: str, subject_ids: list[str], question: str) -> dict[str, object]:
    return {
        "questionId": question_id,
        "subjectIds": subject_ids,
        "question": question,
        "reason": "该信息会影响范围和估算边界。",
        "decisionImpact": "答案将决定交付拆分和 Task 人天。",
        "unansweredEffect": "未回答时无法形成可信估算。",
    }


def question_fixture() -> dict[str, object]:
    return {
        "questionId": "question-return-api",
        "subjectIds": ["feature-refund-processing"],
        "question": "当前是否已有退货申请提交接口？",
        "reason": "往期材料只说明退货模块，不能证明该接口存在。",
        "decisionImpact": "答案决定该 Task 使用新建、调整或接入现有接口。",
        "unansweredEffect": "无法确认且必须修改现有接口时，本项保持阻断。",
    }


def test_prepare_review_returns_readable_material_not_hash_prompt(tmp_path: Path) -> None:
    stage_delivery(tmp_path)

    result = prepare_review(tmp_path)
    assert result["reviewMaterialPath"] == ".ai-sow/work/review-material.md"
    text = (tmp_path / str(result["reviewMaterialPath"])).read_text(encoding="utf-8")

    for heading in (
        "## 结论摘要",
        "## 包含范围",
        "## 不包含范围",
        "## 重要假设",
        "## 风险",
        "## 下一步",
    ):
        assert heading in text
    assert "是否确认哈希" not in text
    assert "feature-refund-processing" not in text


def test_review_material_orders_counts_before_natural_conclusion(tmp_path: Path) -> None:
    stage_delivery(tmp_path)
    result = prepare_review(tmp_path)
    text = (tmp_path / str(result["reviewMaterialPath"])).read_text(encoding="utf-8")

    assert text.index("# 示例退款服务新建项目 终审材料") < text.index("- 本次材料包含")
    assert text.index("- 本次材料包含") < text.index("## 结论摘要")
    assert text.index("## 结论摘要") < text.index("- 范围、交付拆分和估算边界已整理，等待独立终审。")
    assert text.index("- 范围、交付拆分和估算边界已整理，等待独立终审。") < text.index("## 包含范围")


def test_blocked_review_result_keeps_question_objects(tmp_path: Path) -> None:
    stage_delivery(tmp_path)
    packet = build_review_packet(ProjectFiles.open(tmp_path))
    question = blocking_question(
        "block-return-api",
        ["feature-refund-processing"],
        "当前是否已有退货申请提交接口？",
    )
    review = review_value(tmp_path, str(packet.packet_sha256), "BLOCKED")
    review["questions"] = [question]
    (tmp_path / "review.json").write_bytes(canonical_json_bytes(review))

    result = run_mode(tmp_path, "accept-review", review="review.json", now=NOW)

    assert result["outcome"] == "BLOCKED"
    assert result["questions"] == [question]


def test_invalid_review_result_keeps_complete_question_objects(tmp_path: Path) -> None:
    stage_delivery(tmp_path)
    packet = build_review_packet(ProjectFiles.open(tmp_path))
    question = blocking_question(
        "block-return-api",
        ["feature-refund-processing"],
        "当前是否已有退货申请提交接口？",
    )
    review = review_value(tmp_path, "0" * 64, "BLOCKED")
    review["questions"] = [question]
    (tmp_path / "review.json").write_bytes(canonical_json_bytes(review))

    result = run_mode(tmp_path, "accept-review", review="review.json", now=NOW)

    assert packet.packet_sha256 != review["packetSha256"]
    assert result["outcome"] == "BLOCKED"
    assert result["questions"] == [question]
    assert {item["code"] for item in result["diagnostics"]} >= {
        "FINAL_REVIEW_PACKET_HASH_MISMATCH"
    }


def test_review_packet_binds_complete_bundles_and_change_summary(tmp_path: Path) -> None:
    stage_delivery(tmp_path)
    result = build_review_packet(ProjectFiles.open(tmp_path))
    packet_path = tmp_path / result.packet_path
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert result.outcome == "REVIEW_REQUIRED"
    assert packet["artifacts"]["scope"]["sha256"] == sha256_bytes(
        (tmp_path / ".ai-sow/work/scope.candidate.json").read_bytes()
    )
    assert packet["artifacts"]["delivery"]["sha256"] == sha256_bytes(
        (tmp_path / ".ai-sow/work/delivery.candidate.json").read_bytes()
    )
    assert packet["changeSummary"]["affectedFeatureIds"] == []
    assert packet["bundles"]["scope"]["features"]
    assert packet["sourceRefInventory"]
    assert packet.get("storyNoteProjection") == {
        "projected": [
            {
                "assumptionIds": ["assumption-test-environment"],
                "featureId": "feature-refund-processing",
                "storyId": "story-refund-processing",
            }
        ],
        "suppressedProjectLevelAssumptionIds": [],
    }


def test_review_packet_projects_complete_ac_story_source_traceability(
    tmp_path: Path,
) -> None:
    stage_delivery(tmp_path)
    result = build_review_packet(ProjectFiles.open(tmp_path))
    packet = json.loads(
        (tmp_path / str(result.packet_path)).read_text(encoding="utf-8")
    )

    assert packet["acceptanceCriterionSources"] == [
        {
            "acceptanceCriterionId": "ac-refund-invalid",
            "storyId": "story-refund-processing",
            "sourceRefs": [
                {
                    "anchorId": "anchor-a1076b3d69271346",
                    "locator": "heading:PRD",
                    "sha256": "9d4bacb4376916256e3e9f7f63f189bf9dd20499747f653562b6f5585841d1e8",
                    "sourceId": "prd-refund",
                }
            ],
            "resolvable": True,
        },
        {
            "acceptanceCriterionId": "ac-refund-submit",
            "storyId": "story-refund-processing",
            "sourceRefs": [
                {
                    "anchorId": "anchor-a1076b3d69271346",
                    "locator": "heading:PRD",
                    "sha256": "9d4bacb4376916256e3e9f7f63f189bf9dd20499747f653562b6f5585841d1e8",
                    "sourceId": "prd-refund",
                }
            ],
            "resolvable": True,
        },
    ]


def test_review_packet_exposes_exact_allowed_subjects(tmp_path: Path) -> None:
    stage_delivery(tmp_path)
    result = build_review_packet(ProjectFiles.open(tmp_path))
    packet = json.loads(
        (tmp_path / str(result.packet_path)).read_text(encoding="utf-8")
    )

    assert packet["allowedSubjects"] == {
        "ASSUMPTION": ["assumption-test-environment"],
        "CHANGE_TRIGGER": ["assumption-test-environment"],
        "DESIGN_TASK": [],
        "ESTIMATE_BOUNDARY": ["assumption-test-environment"],
        "EXCLUSION": [],
        "RESPONSIBILITY": [
            "responsibility-customer-environment",
            "responsibility-vendor-delivery",
        ],
    }


def test_review_rejects_subject_inventory_that_no_longer_matches_bundles(
    tmp_path: Path,
) -> None:
    stage_delivery(tmp_path)
    build_review_packet(ProjectFiles.open(tmp_path))
    packet_path = tmp_path / ".ai-sow/work/review-packet.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["allowedSubjects"]["RESPONSIBILITY"] = ["invented-subject"]
    packet_path.write_bytes(canonical_json_bytes(packet))
    review = review_value(tmp_path, sha256_bytes(packet_path.read_bytes()))
    (tmp_path / "review.json").write_bytes(canonical_json_bytes(review))

    result = record_review(ProjectFiles.open(tmp_path), "review.json")

    assert result.decision == "BLOCKED"
    assert "FINAL_REVIEW_SUBJECT_INVENTORY_MISMATCH" in diagnostic_codes(result)


def test_pass_with_notes_requires_bound_fixed_boundary(tmp_path: Path) -> None:
    stage_delivery(tmp_path)
    packet = build_review_packet(ProjectFiles.open(tmp_path))
    review = review_value(tmp_path, packet.packet_sha256, "PASS_WITH_NOTES")
    review["notes"] = [
        {
            "noteId": "note-unbound",
            "category": "ASSUMPTION",
            "subjectIds": ["unknown-object"],
            "summary": "未知边界。",
            "sowNotesText": "未知边界不能进入 SOW 说明。",
        }
    ]
    (tmp_path / "review.json").write_bytes(canonical_json_bytes(review))
    result = record_review(ProjectFiles.open(tmp_path), "review.json")
    assert result.decision == "BLOCKED"
    assert "FINAL_REVIEW_NOTE_UNBOUND" in diagnostic_codes(result)
    assert not (tmp_path / ".ai-sow/work/final-review.json").exists()


def test_blocked_review_preserves_minimal_deduplicated_questions(
    tmp_path: Path,
) -> None:
    stage_delivery(tmp_path)
    packet = build_review_packet(ProjectFiles.open(tmp_path))
    review = review_value(tmp_path, packet.packet_sha256, "BLOCKED")
    review["questions"] = [
        blocking_question(
            "block-system-count",
            ["feature-refund-processing"],
            "需要确认涉及几个生产系统？",
        ),
        blocking_question(
            "block-system-count-duplicate",
            ["feature-refund-processing"],
            " 需要确认涉及几个生产系统？ ",
        ),
    ]
    (tmp_path / "review.json").write_bytes(canonical_json_bytes(review))
    result = record_review(ProjectFiles.open(tmp_path), "review.json")
    stored = json.loads(
        (tmp_path / ".ai-sow/work/final-review.json").read_text(encoding="utf-8")
    )
    assert result.decision == "BLOCKED"
    assert result.questions == (stored["questions"][0],)
    assert len(stored["questions"]) == 1
    assert (tmp_path / ".ai-sow/inputs/pending").is_dir()
    assert not (tmp_path / ".ai-sow/current.json").exists()


def test_blocked_review_questions_use_shared_question_contract() -> None:
    schema = json.loads(
        (SKILL_ROOT / "contracts/final-review.schema.json").read_text(encoding="utf-8")
    )
    assert schema["properties"]["questions"]["items"] == {
        "$ref": "urn:ai-sow:generate:question:1"
    }


def test_blocked_review_rejects_question_bound_to_unknown_object(
    tmp_path: Path,
) -> None:
    stage_delivery(tmp_path)
    packet = build_review_packet(ProjectFiles.open(tmp_path))
    review = review_value(tmp_path, packet.packet_sha256, "BLOCKED")
    review["questions"] = [
        blocking_question(
            "block-invented-subject",
            ["feature-invented"],
            "这个未知对象的边界是什么？",
        )
    ]
    (tmp_path / "review.json").write_bytes(canonical_json_bytes(review))

    result = record_review(ProjectFiles.open(tmp_path), "review.json")

    assert result.decision == "BLOCKED"
    assert "FINAL_REVIEW_QUESTION_UNBOUND" in diagnostic_codes(result)
    assert not (tmp_path / ".ai-sow/work/final-review.json").exists()


def test_second_review_with_different_bytes_is_rejected(tmp_path: Path) -> None:
    stage_delivery(tmp_path)
    packet = build_review_packet(ProjectFiles.open(tmp_path))
    review = review_value(tmp_path, packet.packet_sha256)
    (tmp_path / "review.json").write_bytes(canonical_json_bytes(review))
    first = record_review(ProjectFiles.open(tmp_path), "review.json")
    assert first.decision == "PASS"
    changed = copy.deepcopy(review)
    changed["decision"] = "BLOCKED"
    changed["questions"] = [
        blocking_question(
            "block-late",
            ["feature-refund-processing"],
            "是否允许覆盖既有终审？",
        )
    ]
    (tmp_path / "review-2.json").write_bytes(canonical_json_bytes(changed))
    second = record_review(ProjectFiles.open(tmp_path), "review-2.json")
    assert second.decision == "BLOCKED"
    assert "FINAL_REVIEW_CONFLICT" in diagnostic_codes(second)
