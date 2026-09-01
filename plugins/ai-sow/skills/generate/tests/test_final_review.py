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
from orchestrator import run_mode  # noqa: E402
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
    assert packet["changeSummary"]["affectedFeatureIds"] == [
        "feature-refund-processing"
    ]
    assert packet["bundles"]["scope"]["features"]
    assert packet["sourceRefInventory"]


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
        {
            "blockingConditionId": "block-system-count",
            "subjectIds": ["feature-refund-processing"],
            "summary": "系统数量无法确定。",
            "question": "需要确认涉及几个生产系统？",
        },
        {
            "blockingConditionId": "block-system-count-duplicate",
            "subjectIds": ["feature-refund-processing"],
            "summary": "仍缺少系统数量。",
            "question": " 需要确认涉及几个生产系统？ ",
        },
    ]
    (tmp_path / "review.json").write_bytes(canonical_json_bytes(review))
    result = record_review(ProjectFiles.open(tmp_path), "review.json")
    stored = json.loads(
        (tmp_path / ".ai-sow/work/final-review.json").read_text(encoding="utf-8")
    )
    assert result.decision == "BLOCKED"
    assert result.questions == ("需要确认涉及几个生产系统？",)
    assert len(stored["questions"]) == 1
    assert (tmp_path / ".ai-sow/inputs/pending").is_dir()
    assert not (tmp_path / ".ai-sow/current.json").exists()


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
        {
            "blockingConditionId": "block-late",
            "subjectIds": ["feature-refund-processing"],
            "summary": "后续改写。",
            "question": "是否允许覆盖既有终审？",
        }
    ]
    (tmp_path / "review-2.json").write_bytes(canonical_json_bytes(changed))
    second = record_review(ProjectFiles.open(tmp_path), "review-2.json")
    assert second.decision == "BLOCKED"
    assert "FINAL_REVIEW_CONFLICT" in diagnostic_codes(second)
