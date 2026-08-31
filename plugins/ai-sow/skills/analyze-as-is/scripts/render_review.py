from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# Windows 控制台默认使用本地代码页（如 cp936），会把中文结构化输出写成非 UTF-8 字节。
# 调用方按 UTF-8 读取 stdout/stderr，这里显式固定编码，与 POSIX 行为保持一致。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


DEFAULT_CANDIDATE = ".ai-sow/work/analyze-as-is/asis.candidate.json"
DEFAULT_OUTPUT = ".ai-sow/work/analyze-as-is/review.candidate.md"
QUESTIONNAIRE_PATH = ".ai-sow/work/analyze-as-is/questionnaire.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a deterministic As-Is review projection")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def cell(value: object) -> str:
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value) or "NONE"
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def stable_ids(data: dict[str, Any]) -> list[str]:
    return [
        *(entry["asIsItemId"] for entry in data["items"]),
        *(entry["commitmentId"] for entry in data["commitments"]),
        *(entry["effectiveStartItemId"] for entry in data["effectiveStartItems"]),
        *(entry["uncertaintyId"] for entry in data["uncertainties"]),
        *(entry["evidenceId"] for entry in data["evidence"]),
    ]


def table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
        *(
            ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
            or ["| " + " | ".join("NONE" for _ in headers) + " |"]
        ),
    ]


def render(data: dict[str, Any], questionnaire: str | None) -> bytes:
    scope = data["analysisScope"]
    questionnaire_lines = (
        [
            f"Questionnaire: {QUESTIONNAIRE_PATH}",
            "Questionnaire IDs: "
            + ", ".join(
                line.split(":", 1)[1].strip()
                for line in questionnaire.splitlines()
                if line.startswith("Question ID:")
            ),
            "",
            questionnaire.strip(),
        ]
        if questionnaire is not None
        else ["Questionnaire: NOT_REQUIRED", "Questionnaire IDs: NONE"]
    )
    lines = [
        "# 现状评审",
        "",
        "本文件由 As-Is candidate 确定性投影。Reviewer 与用户批准声明是拟发布值；",
        "只有 reviewer/approval sidecar 同时绑定当前 review packet 后才具有授权效力。",
        "",
        "## 调查范围",
        "",
        f"Mode: {scope['mode']}",
        f"As Of Date: {scope['asOfDate']}",
        f"Repositories: {cell([entry['repoId'] for entry in scope['repositorySnapshots']])}",
        f"Prior SOWs: {cell([entry['priorSowId'] for entry in scope['priorSowSnapshots']])}",
        f"Included Systems: {cell(scope['includedSystems'])}",
        f"Included Areas: {cell(scope['includedAreas'])}",
        f"Excluded Areas: {cell(scope['excludedAreas'])}",
        "",
        "## 九个 Topic",
        "",
        *table(
            ("Topic", "状态", "结论", "Uncertainty"),
            [
                (
                    entry["topic"],
                    entry["status"],
                    entry["summary"],
                    entry["uncertaintyIds"],
                )
                for entry in data["topicAssessments"]
            ],
        ),
        "",
        "## Item",
        "",
        *table(
            ("Item", "Topic", "类型", "名称", "仓库", "结论"),
            [
                (
                    entry["asIsItemId"],
                    entry["topic"],
                    entry["itemType"],
                    entry["name"],
                    entry["repositoryIds"],
                    entry["summary"],
                )
                for entry in data["items"]
            ],
        ),
        "",
        "## Commitment",
        "",
        *table(
            ("Commitment", "名称", "变化", "实现状态", "处置", "Feature", "Item"),
            [
                (
                    entry["commitmentId"],
                    entry["name"],
                    entry["changeType"],
                    entry["implementationStatus"],
                    entry["treatment"],
                    entry["relatedFeatureIds"],
                    entry["affectedItemIds"],
                )
                for entry in data["commitments"]
            ],
        ),
        "",
        "## Effective Start",
        "",
        *table(
            ("Effective Start", "名称", "当前 Item", "预计完成 Commitment"),
            [
                (
                    entry["effectiveStartItemId"],
                    entry["name"],
                    entry["sourceItemIds"],
                    entry["commitmentIds"],
                )
                for entry in data["effectiveStartItems"]
            ],
        ),
        "",
        "## Coverage",
        "",
        *table(
            ("Feature", "状态", "Effective Start", "Commitment", "Uncertainty", "理由"),
            [
                (
                    entry["featureId"],
                    entry["status"],
                    entry["effectiveStartItemIds"],
                    entry["commitmentIds"],
                    entry["uncertaintyIds"],
                    entry["rationale"],
                )
                for entry in data["coverage"]
            ],
        ),
        "",
        "## Uncertainty",
        "",
        *table(
            ("Uncertainty", "名称", "Topic", "问题", "影响", "影响估算", "负责人", "建议"),
            [
                (
                    entry["uncertaintyId"],
                    entry["name"],
                    entry["topic"],
                    entry["question"],
                    entry["impact"],
                    entry["affectsEstimate"],
                    entry["owner"],
                    entry["recommendedHandling"],
                )
                for entry in data["uncertainties"]
            ],
        ),
        "",
        "## Evidence",
        "",
        *table(
            ("Evidence", "名称", "类型", "项目相对 anchor", "摘要", "支持 ID"),
            [
                (
                    entry["evidenceId"],
                    entry["name"],
                    entry["kind"],
                    entry["reference"],
                    entry["summary"],
                    entry["supportsIds"],
                )
                for entry in data["evidence"]
            ],
        ),
        "",
        "Evidence 只投影项目相对 anchor 与简要摘要；不包含源码、完整工具输出、凭据或本机绝对路径。",
        "",
        "## 问卷记录",
        "",
        *questionnaire_lines,
        "",
        "## 审查与批准",
        "",
        f"Stable IDs: {', '.join(stable_ids(data)) or 'NONE'}",
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
            raise ValueError("As-Is candidate must be a JSON object")
        try:
            questionnaire = files.read_bytes(QUESTIONNAIRE_PATH).decode("utf-8")
        except ProjectIOError as error:
            if error.code != "PROJECT_PATH_MISSING":
                raise
            questionnaire = None
        payload = render(candidate, questionnaire)
        files.write_atomic(args.output, payload)
        print(
            json.dumps(
                {
                    "outcome": "OK",
                    "summary": "As-Is review projection is ready",
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
                    "summary": "As-Is review projection could not be rendered",
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
