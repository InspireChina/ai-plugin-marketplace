from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from read_template import read_contract


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


DEFAULT_CANDIDATE = ".ai-sow/work/generate-task/estimate.candidate.json"
DEFAULT_OUTPUT = ".ai-sow/work/generate-task/review.candidate.md"
TEMPLATE_PATH = ".ai-sow/templates/sow-template.xlsx"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a deterministic Task review projection")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def joined(values: list[str] | set[str]) -> str:
    ordered = sorted(values)
    return ", ".join(ordered) if ordered else "NONE"


def mapping(tasks: list[dict[str, Any]], source: str) -> str:
    grouped: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        values = task[source] if isinstance(task[source], list) else [task[source]]
        for value in values:
            grouped[value].append(task["taskId"])
    return "; ".join(
        f"{identifier}={','.join(task_ids)}"
        for identifier, task_ids in sorted(grouped.items())
    ) or "NONE"


def render(
    estimate: dict[str, Any],
    template_hash: str,
    template_contract: dict[str, Any],
) -> bytes:
    tasks = estimate.get("tasks")
    if not isinstance(tasks, list) or not tasks or any(not isinstance(task, dict) for task in tasks):
        raise ValueError("Estimate candidate must contain a non-empty tasks array")
    integration_tasks = [task for task in tasks if isinstance(task.get("integrationId"), str)]
    base_units = template_contract.get("baseUnits")
    if not isinstance(base_units, dict):
        raise ValueError("template contract must contain baseUnits")
    missing_base_units = sorted(
        {
            task.get("baseUnit")
            for task in tasks
            if not isinstance(task.get("baseUnit"), str) or task.get("baseUnit") not in base_units
        },
        key=str,
    )
    if missing_base_units:
        raise ValueError(f"candidate references unknown base units: {missing_base_units}")
    effective_start_ids = {
        identifier
        for task in tasks
        for identifier in task.get("matchedEffectiveStartItemIds", [])
        if isinstance(identifier, str)
    }
    lines = [
        "# Task 拆分评审",
        "",
        "本文件由 Estimate candidate 确定性投影。Reviewer 与用户批准声明是拟发布值；",
        "只有 reviewer/approval sidecar 同时绑定当前 review packet 后才具有授权效力。",
        "",
        "## Story → Task",
        "",
        f"Story Map: {mapping(tasks, 'storyId')}",
        f"AC Map: {mapping(tasks, 'acceptanceCriterionIds')}",
        f"Stable IDs: {joined([task['taskId'] for task in tasks])}",
        "",
        "| Task | Story | AC | 名称 | 拆分理由 |",
        "|---|---|---|---|---|",
        *[
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    task["taskId"],
                    task["storyId"],
                    joined(task["acceptanceCriterionIds"]),
                    task["name"],
                    task["rationale"],
                )
            )
            + " |"
            for task in tasks
        ],
        "",
        "## 基础单元",
        "",
        f"Base Units: {joined({task['baseUnit'] for task in tasks})}",
        "",
        "| Task | Base Unit | 计数口径 | 包含边界 | 排除边界 |",
        "|---|---|---|---|---|",
        *[
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    task["taskId"],
                    task["baseUnit"],
                    base_units[task["baseUnit"]]["countRule"],
                    base_units[task["baseUnit"]]["includes"],
                    base_units[task["baseUnit"]]["excludes"],
                )
            )
            + " |"
            for task in tasks
        ],
        "",
        "## 工作模式",
        "",
        f"Work Modes: {joined({task['workMode'] for task in tasks})}",
        "",
        "| Task | 模式 | 模式理由 | 项目侧承诺 |",
        "|---|---|---|---|",
        *[
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    task["taskId"],
                    task["workMode"],
                    task["workModeRationale"],
                    (
                        task.get("workModeEvidence", {}).get("projectSideWorkCommitment", "NONE")
                        if isinstance(task.get("workModeEvidence"), dict)
                        else "NONE"
                    ),
                )
            )
            + " |"
            for task in tasks
        ],
        "",
        "## 复杂度",
        "",
        f"Complexities: {joined({task['complexity'] for task in tasks})}",
        "",
        "| Task | 复杂度 | 偏离 M 理由 |",
        "|---|---|---|",
        *[
            f"| {cell(task['taskId'])} | {cell(task['complexity'])} | "
            f"{cell(task.get('complexityRationale', 'NONE'))} |"
            for task in tasks
        ],
        "",
        "## 现状依据",
        "",
        f"Effective Start IDs: {joined(effective_start_ids)}",
        "",
        "| Task | Effective Start | 依据 |",
        "|---|---|---|",
        *[
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    task["taskId"],
                    joined(task.get("matchedEffectiveStartItemIds", [])),
                    task.get("workModeEvidence", {}).get("effectiveStartItemName", "NONE")
                    if isinstance(task.get("workModeEvidence"), dict)
                    else "NONE",
                )
            )
            + " |"
            for task in tasks
        ],
        "",
        "## Integration 一对一",
        "",
        f"Integration Map: {mapping(integration_tasks, 'integrationId')}",
        "",
        "| Integration | Task |",
        "|---|---|",
        *(
            [
                f"| {cell(task['integrationId'])} | {cell(task['taskId'])} |"
                for task in integration_tasks
            ]
            or ["| NONE | NONE |"]
        ),
        "",
        "## 遗漏 / 重叠 / 排除理由",
        "",
        "Scope Review: PASSED",
        "",
        "| Task | 独立计价实例 | 非重复计价边界 |",
        "|---|---|---|",
        *[
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    task["taskId"],
                    task["rationale"],
                    base_units[task["baseUnit"]]["excludes"],
                )
            )
            + " |"
            for task in tasks
        ],
        "",
        "每条 Task 对应一个基础单元实例；Owner validator 复核 Story、AC、Integration 与 Effective",
        "Start 完整性。表中排除边界及候选未列出的工作均不进入 Estimate。",
        "",
        "## 估算前提",
        "",
        f"Template SHA-256: {template_hash}",
        "",
        "模板仍是基础人天、倍率、公式、SIT、UAT、风险与取整的唯一计算权威。",
        "",
        "## 审查与批准",
        "",
        "Reviewer: PASS",
        "User Approval: APPROVED",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def main() -> int:
    args = parse_args()
    try:
        files = (
            ProjectFiles.open_view(args.project_root, args.staging_root)
            if args.staging_root is not None
            else ProjectFiles.open(args.project_root)
        )
        candidate = files.read_json(args.candidate)
        if not isinstance(candidate, dict):
            raise ValueError("Estimate candidate must be a JSON object")
        template_path = files.resolve(TEMPLATE_PATH)
        template_hash = sha256_bytes(files.read_bytes(TEMPLATE_PATH))
        payload = render(candidate, template_hash, read_contract(template_path))
        files.write_atomic(args.output, payload)
        print(
            json.dumps(
                {
                    "outcome": "OK",
                    "summary": "Task review projection is ready",
                    "diagnostics": [],
                    "outputs": [args.output],
                    "sha256": sha256_bytes(payload),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (ProjectIOError, OSError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {
                    "outcome": "BLOCKED",
                    "summary": "Task review projection could not be rendered",
                    "diagnostics": [
                        {
                            "code": getattr(error, "code", "REVIEW_RENDER_BLOCKED"),
                            "message": str(error),
                        }
                    ],
                    "outputs": [],
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
