from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import validate as requirement_validator


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


DEFAULT_CANDIDATE = ".ai-sow/work/analyze-requirement/requirements.candidate.json"
DEFAULT_SOURCE_DISPOSITION = ".ai-sow/work/analyze-requirement/context/source-disposition.json"
DEFAULT_OUTPUT = ".ai-sow/work/analyze-requirement/review.candidate.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a deterministic BUSINESS requirements review")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    parser.add_argument("--source-disposition", default=DEFAULT_SOURCE_DISPOSITION)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def joined(values: list[str]) -> str:
    return ", ".join(values) if values else "NONE"


def optional(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    return value if isinstance(value, str) and value else "NONE"


def render(
    data: dict[str, Any],
    source_disposition: dict[str, Any],
    questionnaire: str,
) -> bytes:
    sources = data.get("sourceDocuments")
    normalized = data.get("normalizedItems")
    epics = data.get("epics")
    features = data.get("features")
    if not all(isinstance(value, list) for value in (sources, normalized, epics, features)):
        raise ValueError("requirements candidate collections are unavailable")
    disposition_items = source_disposition.get("items")
    if not isinstance(disposition_items, list):
        raise ValueError("source disposition items are unavailable")
    ids = requirement_validator.stable_ids(data)
    lines = [
        "# 业务需求评审",
        "",
        "本文件由 requirements candidate 确定性投影。Reviewer 与用户批准声明是拟发布值；",
        "只有 reviewer/approval sidecar 同时绑定当前 review packet 后才具有授权效力。",
        "",
        "## 来源与归一化",
        "",
        "| Source ID | 项目路径 | 原文件名 | SHA-256 |",
        "|---|---|---|---|",
        *[
            f"| {cell(item['sourceDocumentId'])} | {cell(item['file'])} | "
            f"{cell(item['originalName'])} | {cell(item['sha256'])} |"
            for item in sources
        ],
        "",
        "| Normalized ID | Source ID | 主题 | 业务陈述 |",
        "|---|---|---|---|",
        *[
            f"| {cell(item['normalizedItemId'])} | {cell(item['sourceDocumentId'])} | "
            f"{cell(item['title'])} | {cell(item['statement'])} |"
            for item in normalized
        ],
        "",
        "## 来源处置",
        "",
        "| Disposition ID | Source ID | 来源定位 | 摘要 | 处置 | BUSINESS 目标 | 理由 |",
        "|---|---|---|---|---|---|---|",
        *[
            f"| {cell(item['dispositionId'])} | {cell(item['sourceDocumentId'])} | "
            f"{cell(item['sourceReference'])} | {cell(item['summary'])} | "
            f"{cell(item['disposition'])} | {cell(joined(item['targetIds']))} | "
            f"{cell(item['rationale'])} |"
            for item in disposition_items
        ],
        "",
        "每条会影响本阶段业务结论或后续方案边界的明确来源陈述都必须有且仅有一种处置；",
        "DESIGN_INPUT 仅保留给 generate-design，不得因此在本阶段创建 TECHNICAL Epic/Feature。",
        "",
        "## Epic 与 Feature",
        "",
        "| Epic | 名称 | 业务范围 | 目标结果 | 共同约束 / 排除 | 来源条目 |",
        "|---|---|---|---|---|---|",
        *[
            f"| {cell(item['epicId'])} | {cell(item['name'])} | {cell(item['description'])} | "
            f"{cell(optional(item, 'targetOutcome'))} | "
            f"{cell(optional(item, 'commonConstraintsOutOfScope'))} | "
            f"{cell(joined(item['source']['normalizedItemIds']))} |"
            for item in epics
        ],
        "",
        "| Feature | Epic | 名称 | 业务能力与可观察结果 | 业务约束 | 来源条目 |",
        "|---|---|---|---|---|---|",
        *[
            f"| {cell(item['featureId'])} | {cell(item['epicId'])} | {cell(item['name'])} | "
            f"{cell(item['description'])} | {cell(optional(item, 'constraintsNfr'))} | "
            f"{cell(joined(item['source']['normalizedItemIds']))} |"
            for item in features
        ],
        "",
        "## 范围边界",
        "",
        "候选仅承载上表 BUSINESS Epic 与 Feature；选填边界只在来源明确时投影，技术方案不在本阶段决定。",
        "",
        "## 问卷状态",
        "",
        f"Questionnaire: {questionnaire}",
        "",
        "阻塞问卷必须在进入 Reviewer 前为 CLOSED；APPROVED_DEFAULT 只保留为下游假设候选。",
        "",
        "## 稳定 ID 映射",
        "",
        f"Stable IDs: {joined(ids)}",
        "",
        "## 输入充分性",
        "",
        "当前候选逐项绑定已登记来源与问卷终态；Reviewer 仍须独立检查业务范围遗漏、冲突、未经批准猜测和验收意图。",
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
            raise ValueError("requirements candidate must be a JSON object")
        source_disposition = files.read_json(args.source_disposition)
        if not isinstance(source_disposition, dict):
            raise ValueError("source disposition must be a JSON object")
        questionnaire = requirement_validator.current_questionnaire_declaration(files)
        payload = render(candidate, source_disposition, questionnaire)
        files.write_atomic(args.output, payload)
        print(
            json.dumps(
                {
                    "outcome": "OK",
                    "summary": "BUSINESS requirements review projection is ready",
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
                    "summary": "BUSINESS requirements review projection could not be rendered",
                    "diagnostics": [
                        requirement_validator.diag(
                            getattr(error, "code", "REVIEW_RENDER_BLOCKED"),
                            str(error),
                            getattr(error, "relative_path", ""),
                        )
                    ],
                    "outputs": [],
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
