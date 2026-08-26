from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PLUGIN_ROOT / "skills/generate-sow/fixtures/project"
TASK_VALIDATOR = PLUGIN_ROOT / "skills/generate-task/scripts/validate.py"
TASK_CONTEXT = PLUGIN_ROOT / "skills/generate-task/scripts/prepare_context.py"
SOW_GENERATOR = PLUGIN_ROOT / "skills/generate-sow/scripts/generate_sow.py"
RECONCILE = PLUGIN_ROOT / "skills/reconcile/scripts/reconcile.py"
RUN_ID = "a1b2c3d4e5f6"
TASK_REVIEW = ".ai-sow/reviews/generate-task.md"
ESTIMATE = ".ai-sow/data/generate-task/estimate.json"
TASK_RECEIPT = ".ai-sow/validation/generate-task.json"
STORY_RECEIPT = ".ai-sow/validation/generate-story.json"
TEMPLATE = ".ai-sow/templates/sow-template.xlsx"


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def run_cli(script: Path, project: Path, *args: str) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    completed = subprocess.run(
        [sys.executable, str(script), "--project-root", str(project), *args],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed, json.loads(completed.stdout)


def mapped_ids(estimate: dict[str, object], key: str, value: str) -> str:
    groups: dict[str, list[str]] = {}
    for task in estimate["tasks"]:  # type: ignore[index]
        identifiers = task[key] if isinstance(task[key], list) else [task[key]]
        for identifier in identifiers:
            groups.setdefault(identifier, []).append(task[value])
    return "; ".join(
        f"{identifier}={','.join(task_ids)}"
        for identifier, task_ids in groups.items()
    )


def task_review(
    estimate: dict[str, object],
    *,
    template_hash: str,
    holistic_hash: str | None = None,
    previous_story_hash: str | None = None,
    current_story_hash: str | None = None,
) -> bytes:
    tasks = estimate["tasks"]  # type: ignore[index]
    task_ids = [task["taskId"] for task in tasks]
    integration_map = "; ".join(
        f"{task['integrationId']}={task['taskId']}"
        for task in tasks
        if "integrationId" in task
    )
    effective_starts = sorted(
        {
            identifier
            for task in tasks
            for identifier in task["matchedEffectiveStartItemIds"]
        }
    )
    impact = ""
    binding = ""
    if previous_story_hash is not None and current_story_hash is not None:
        impact = (
            "Impact: NO_CHANGE\n"
            "Upstream: generate-story\n"
            f"Previous Receipt SHA-256: generate-story={previous_story_hash}\n"
            f"Current Receipt SHA-256: generate-story={current_story_hash}\n"
            f"Impact Rationale: {'、'.join(task_ids)} 均确认不受影响。\n"
        )
    if holistic_hash is not None:
        binding = (
            f"Reconciliation Run ID: {RUN_ID}\n"
            f"Reconciliation Review SHA-256: {holistic_hash}\n"
        )
    return (
        "# Task 拆分评审\n\n"
        "## Story → Task\n\n"
        f"Story Map: {mapped_ids(estimate, 'storyId', 'taskId')}\n"
        f"AC Map: {mapped_ids(estimate, 'acceptanceCriterionIds', 'taskId')}\n"
        f"Stable IDs: {', '.join(task_ids)}\n\n"
        "## 基础单元\n\n"
        f"Base Units: {', '.join(sorted({task['baseUnit'] for task in tasks}))}\n\n"
        "## 工作模式\n\n"
        f"Work Modes: {', '.join(sorted({task['workMode'] for task in tasks}))}\n\n"
        "## 复杂度\n\n"
        f"Complexities: {', '.join(sorted({task['complexity'] for task in tasks}))}\n\n"
        "## 现状依据\n\n"
        f"Effective Start IDs: {', '.join(effective_starts) if effective_starts else 'NONE'}\n\n"
        "## Integration 一对一\n\n"
        f"Integration Map: {integration_map if integration_map else 'NONE'}\n\n"
        "## 遗漏 / 重叠 / 排除理由\n\n"
        "Scope Review: PASSED\n\n"
        "## 估算前提\n\n"
        f"Template SHA-256: {template_hash}\n\n"
        "## 审查与批准\n\n"
        "Reviewer: PASS\n"
        "User Approval: APPROVED\n"
        + impact
        + binding
    ).encode()


def test_no_change_owner_rebind_flows_through_flat_staging_sow_and_publisher(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE, project)
    estimate = json.loads((project / ESTIMATE).read_bytes())
    integration_task = next(
        task
        for task in estimate["tasks"]
        if task["taskId"] == "task-profile-integration"
    )
    integration_task["workModeEvidence"]["projectSideWorkTypes"] = [
        "MAP",
        "ADAPT",
        "AUTHENTICATE",
    ]
    integration_task["workModeEvidence"]["projectSideWorkCommitment"] = (
        "本项目负责并交付：映射、适配、认证"
    )
    integration_task["workModeRationale"] = (
        "可复用的客户档案框架保持不变；本项目负责并交付：映射、适配、认证。"
    )
    candidate_payload = (json.dumps(estimate, ensure_ascii=False, indent=2) + "\n").encode()
    candidate_path = project / ".ai-sow/work/generate-task/estimate.candidate.json"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_bytes(candidate_payload)
    (project / TASK_REVIEW).write_bytes(
        task_review(
            estimate,
            template_hash=sha256((project / TEMPLATE).read_bytes()),
        )
    )
    prepared, prepared_result = run_cli(TASK_CONTEXT, project)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    assert prepared_result["outcome"] == "OK"
    reviewed, reviewed_result = run_cli(
        TASK_VALIDATOR,
        project,
        "--mode",
        "review",
    )
    assert reviewed.returncode == 0, reviewed.stdout + reviewed.stderr
    packet_hash = str(reviewed_result["packetSha256"])
    for binding_mode in ("write-reviewer", "write-approval"):
        bound, bound_result = run_cli(
            TASK_VALIDATOR,
            project,
            "--mode",
            binding_mode,
            "--packet-sha256",
            packet_hash,
        )
        assert bound.returncode == 0, bound.stdout + bound.stderr
        assert bound_result["outcome"] == "OK"
    baseline, baseline_result = run_cli(
        TASK_VALIDATOR,
        project,
        "--mode",
        "publish-approved",
    )
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    assert baseline_result["outcome"] == "OK"
    stage_root = f".ai-sow/.stage-{RUN_ID}"

    before_review = (project / TASK_REVIEW).read_bytes()
    estimate_payload = (project / ESTIMATE).read_bytes()
    estimate = json.loads(estimate_payload)
    current_story_payload = (project / STORY_RECEIPT).read_bytes()
    current_story_hash = sha256(current_story_payload)

    previous_report = json.loads((project / TASK_RECEIPT).read_bytes())
    previous_story_hash = "0" * 64
    for item in previous_report["compilationReceipt"]["inputs"]:
        if item["name"] == "deliveryValidation":
            item["sha256"] = previous_story_hash
    before_receipt = canonical_json(previous_report)
    (project / TASK_RECEIPT).write_bytes(before_receipt)

    estimate_hash = sha256(estimate_payload)
    holistic_review = (
        "# AI SOW 影响集整体评审\n\n"
        f"Run ID: {RUN_ID}\n"
        "Correction Owner: generate-task\n"
        "Impact Suffix: generate-task, generate-sow\n\n"
        "| Owner | Impact | Before Output SHA-256 | After Output SHA-256 | Stable IDs | Rationale |\n"
        "|---|---|---|---|---|---|\n"
        f"| generate-task | NO_CHANGE | estimate={estimate_hash} | estimate={estimate_hash} | task-set | 原字节复用。 |\n\n"
        "Story/AC Outcome Change: NO_CHANGE\n"
        "Story/AC Exact Diff: NONE\n"
    ).encode()
    holistic_hash = sha256(holistic_review)
    review_path = f".ai-sow/work/reconcile/{RUN_ID}/review.md"
    (project / review_path).parent.mkdir(parents=True, exist_ok=True)
    (project / review_path).write_bytes(holistic_review)

    after_review = task_review(
        estimate,
        template_hash=sha256((project / TEMPLATE).read_bytes()),
        holistic_hash=holistic_hash,
        previous_story_hash=previous_story_hash,
        current_story_hash=current_story_hash,
    )
    physical_stage = project / stage_root
    (physical_stage / "reviews").mkdir(parents=True)
    (physical_stage / "reviews/generate-task.md").write_bytes(after_review)

    rebind, rebind_result = run_cli(
        TASK_VALIDATOR,
        project,
        "--staging-root",
        stage_root,
        "--mode",
        "rebind",
    )
    assert rebind.returncode == 0, rebind.stdout + rebind.stderr
    assert rebind_result["outcome"] == "OK"
    assert not (physical_stage / ".ai-sow").exists()
    (physical_stage / "data/generate-task").mkdir(parents=True)
    (physical_stage / "data/generate-task/estimate.json").write_bytes(estimate_payload)
    after_receipt = (physical_stage / "validation/generate-task.json").read_bytes()

    generated, generated_result = run_cli(
        SOW_GENERATOR,
        project,
        "--staging-root",
        stage_root,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    assert generated_result["outcome"] == "OK"
    package_id = str(generated_result["packageId"])
    staged_package = physical_stage / f"outputs/{package_id}"
    assert staged_package.is_dir()
    assert not (physical_stage / ".ai-sow").exists()
    manifest_path = f".ai-sow/work/reconcile/{RUN_ID}/redo.json"
    assembled, assembled_result = run_cli(
        RECONCILE,
        project,
        "--run-id",
        RUN_ID,
        "--mode",
        "assemble",
    )
    assert assembled.returncode == 0, assembled.stdout + assembled.stderr
    assert assembled_result["outcome"] == "OK"
    packet_path = f".ai-sow/work/reconcile/{RUN_ID}/review-packet.json"
    packet_payload = (project / packet_path).read_bytes()
    packet_hash = sha256(packet_payload)
    packet = json.loads(packet_payload)
    assert packet["package"]["packageId"] == package_id
    assert packet["redo"]["path"] == manifest_path
    assert packet["stagedArtifacts"]
    assert packet["receiptInputs"]
    assert (project / ESTIMATE).read_bytes() == estimate_payload
    assert (project / TASK_REVIEW).read_bytes() == before_review
    assert (project / TASK_RECEIPT).read_bytes() == before_receipt
    assert not (project / f".ai-sow/outputs/{package_id}").exists()

    work_root = project / f".ai-sow/work/reconcile/{RUN_ID}"
    (work_root / "reviewer.json").write_bytes(
        canonical_json(
            {
                "algorithm": "ai-sow-reconciliation-reviewer-v1",
                "decision": "PASS",
                "packetSha256": packet_hash,
                "runId": RUN_ID,
            }
        )
    )
    (work_root / "approval.json").write_bytes(
        canonical_json(
            {
                "algorithm": "ai-sow-reconciliation-approval-v1",
                "decision": "APPROVED",
                "packetSha256": packet_hash,
                "runId": RUN_ID,
            }
        )
    )

    checked, checked_result = run_cli(
        RECONCILE,
        project,
        "--manifest",
        manifest_path,
        "--mode",
        "check",
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert checked_result["publication"] == "CHECKED"
    assert checked_result["packetSha256"] == packet_hash

    published, published_result = run_cli(
        RECONCILE,
        project,
        "--manifest",
        manifest_path,
        "--mode",
        "publish",
    )
    assert published.returncode == 0, published.stdout + published.stderr
    assert published_result["publication"] == "PUBLISHED"
    assert (project / ESTIMATE).read_bytes() == estimate_payload
    assert (project / TASK_REVIEW).read_bytes() == after_review
    assert (project / TASK_RECEIPT).read_bytes() == after_receipt
    assert (project / f".ai-sow/outputs/{package_id}").is_dir()
