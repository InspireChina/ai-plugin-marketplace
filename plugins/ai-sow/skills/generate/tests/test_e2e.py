from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import openpyxl


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
from orchestrator import run_mode  # noqa: E402
from test_orchestrator import (  # noqa: E402
    NOW,
    prepare_delivery_files,
    prepare_scope_files,
    write_json,
    write_request,
)


EXPECTED_GENERATION_FILES = {
    "data/delivery.json",
    "data/scope.json",
    "manifest.json",
    "output/sow-notes.md",
    "output/sow.xlsx",
}


def test_installed_orchestrator_entrypoint_resolves_plugin_runtime(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "orchestrator.py"),
            "--project-root",
            str(tmp_path),
            "--mode",
            "status",
        ],
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2, result.stderr.decode("utf-8")
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["outcome"] == "BLOCKED"
    assert payload["diagnostics"][0]["code"] == "RUN_NOT_PREPARED"


def stage_reviewed_run(project: Path, decision: str = "PASS") -> str:
    request_path = write_request(project)
    prepared = run_mode(project, "prepare", request=request_path, now=NOW)
    assert prepared["outcome"] == "READY_FOR_SCOPE", prepared
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
    packet = run_mode(project, "prepare-review", now=NOW)
    assert packet["outcome"] == "REVIEW_REQUIRED", packet
    plan = json.loads(
        (project / ".ai-sow/work/run-plan.json").read_text(encoding="utf-8")
    )
    review = {
        "contract": "ai-sow-final-review-v1",
        "runId": plan["runId"],
        "inputRevisionId": plan["targetRevisionId"],
        "scopeSha256": sha256_bytes(
            (project / ".ai-sow/work/scope.candidate.json").read_bytes()
        ),
        "deliverySha256": sha256_bytes(
            (project / ".ai-sow/work/delivery.candidate.json").read_bytes()
        ),
        "packetSha256": packet["packetSha256"],
        "decision": decision,
        "notes": [],
        "questions": [],
    }
    if decision == "BLOCKED":
        review["questions"] = [
            {
                "blockingConditionId": "block-system-count",
                "subjectIds": ["feature-refund-processing"],
                "summary": "系统数量影响估算。",
                "question": "请确认涉及几个生产系统？",
            }
        ]
    write_json(project / "review.json", review)
    review_result = run_mode(
        project, "accept-review", review="review.json", now=NOW
    )
    expected = "BLOCKED" if decision == "BLOCKED" else "READY_TO_RENDER"
    assert review_result["outcome"] == expected, review_result
    return request_path


def generation_files(project: Path, generation_id: str) -> set[str]:
    root = project / f".ai-sow/generations/{generation_id}"
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_greenfield_first_run_publishes_one_revision_and_generation(
    tmp_path: Path,
) -> None:
    stage_reviewed_run(tmp_path)
    result = run_mode(tmp_path, "publish", now=NOW)
    assert result["outcome"] == "PUBLISHED", result
    assert result["decision"] == "PASS"
    assert result["featureCounts"] == {"added": 1, "updated": 0, "removed": 0}
    assert result["recomputedStoryCount"] == 1
    assert result["recomputedTaskCount"] == 1
    assert generation_files(tmp_path, "000001") == EXPECTED_GENERATION_FILES
    assert (tmp_path / ".ai-sow/inputs/revisions/000001/manifest.json").is_file()
    assert not (tmp_path / ".ai-sow/inputs/pending").exists()
    assert "不代表客户签署" in result["disclaimer"]


def test_exact_replay_reuses_current_without_new_generation(tmp_path: Path) -> None:
    request_path = stage_reviewed_run(tmp_path)
    assert run_mode(tmp_path, "publish", now=NOW)["outcome"] == "PUBLISHED"
    result = run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    assert result["outcome"] == "REUSED", result
    assert sorted(path.name for path in (tmp_path / ".ai-sow/generations").iterdir()) == [
        "000001"
    ]
    assert sorted(path.name for path in (tmp_path / ".ai-sow/inputs/revisions").iterdir()) == [
        "000001"
    ]


def test_blocked_review_never_renders_or_publishes(tmp_path: Path) -> None:
    stage_reviewed_run(tmp_path, decision="BLOCKED")
    result = run_mode(tmp_path, "publish", now=NOW)
    assert result["outcome"] == "BLOCKED"
    assert result["diagnostics"][0]["code"] == "FINAL_REVIEW_NOT_ACCEPTED"
    assert not (tmp_path / ".ai-sow/current.json").exists()
    assert not (tmp_path / ".ai-sow/work/generation").exists()
    assert (tmp_path / ".ai-sow/inputs/pending").is_dir()


def test_published_manifest_binds_review_impact_and_completion(tmp_path: Path) -> None:
    stage_reviewed_run(tmp_path)
    assert run_mode(tmp_path, "publish", now=NOW)["outcome"] == "PUBLISHED"
    manifest = json.loads(
        (tmp_path / ".ai-sow/generations/000001/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["decision"] == "PASS"
    assert manifest["reviewMode"] == "AUTOMATIC_FINAL_REVIEW"
    assert manifest["publicationComplete"] is True
    assert manifest["impact"]["action"] == "FULL_COMPILE"
    assert manifest["changeCounts"] == {
        "features": {"added": 1, "updated": 0, "removed": 0},
        "recomputedStories": 1,
        "recomputedTasks": 1,
    }
    assert ".ai-sow/work" not in json.dumps(manifest, ensure_ascii=False)


def change_template_without_breaking_contract(project: Path) -> None:
    template = project / ".ai-sow/templates/sow-template.xlsx"
    workbook = openpyxl.load_workbook(template)
    try:
        workbook.properties.lastModifiedBy = "template-contract-test"
        workbook.save(template)
    finally:
        workbook.close()


def test_template_only_change_publishes_generation_against_same_revision(
    tmp_path: Path,
) -> None:
    request_path = stage_reviewed_run(tmp_path)
    assert run_mode(tmp_path, "publish", now=NOW)["outcome"] == "PUBLISHED"
    change_template_without_breaking_contract(tmp_path)
    prepared = run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    assert prepared["outcome"] == "READY_TO_RENDER", prepared
    assert prepared["runPlan"]["action"] == "RENDER_ONLY"
    result = run_mode(tmp_path, "publish", now=NOW)
    assert result["outcome"] == "PUBLISHED", result
    current = json.loads(
        (tmp_path / ".ai-sow/current.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (tmp_path / ".ai-sow/generations/000002/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert current["revisionId"] == "000001"
    assert current["generationId"] == "000002"
    assert manifest["reviewMode"] == "REUSED_SCOPE_REVIEW"
    assert manifest["changeCounts"]["recomputedTasks"] == 0
    assert sorted(path.name for path in (tmp_path / ".ai-sow/inputs/revisions").iterdir()) == [
        "000001"
    ]


def test_render_failure_preserves_last_known_good_pointer(tmp_path: Path) -> None:
    request_path = stage_reviewed_run(tmp_path)
    assert run_mode(tmp_path, "publish", now=NOW)["outcome"] == "PUBLISHED"
    current_before = (tmp_path / ".ai-sow/current.json").read_bytes()
    change_template_without_breaking_contract(tmp_path)
    prepared = run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    assert prepared["runPlan"]["action"] == "RENDER_ONLY"
    (tmp_path / ".ai-sow/templates/sow-template.xlsx").write_bytes(b"not-an-xlsx")
    result = run_mode(tmp_path, "publish", now=NOW)
    assert result["outcome"] == "BLOCKED"
    assert result["diagnostics"][0]["code"] == "WORKBOOK_RENDER_FAILED"
    assert (tmp_path / ".ai-sow/current.json").read_bytes() == current_before
