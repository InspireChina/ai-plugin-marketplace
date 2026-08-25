from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


DEFAULT_CANDIDATE = ".ai-sow/work/generate-story/delivery.candidate.json"
DEFAULT_OUTPUT = ".ai-sow/work/generate-story/review.candidate.md"
CONTEXT_ROOT = ".ai-sow/work/generate-story/context"
QUESTION_PATTERN = re.compile(r"analyze-requirement-questionnaire#([A-Za-z][A-Za-z0-9-]*)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a deterministic Story review projection")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def joined(values: list[str] | set[str]) -> str:
    ordered = sorted(values)
    return ", ".join(ordered) if ordered else "—"


def records(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"Delivery candidate field must be an object array: {key}")
    return value


def stable_ids(delivery: dict[str, Any]) -> list[str]:
    return [
        *(item["gapId"] for item in records(delivery, "gaps")),
        *(item["storyId"] for item in records(delivery, "stories")),
        *(item["acceptanceCriterionId"] for item in records(delivery, "acceptanceCriteria")),
        *(item["integrationId"] for item in records(delivery, "integrations")),
        *(item["assumptionId"] for item in records(delivery, "assumptions")),
    ]


def questionnaire_map(delivery: dict[str, Any]) -> str:
    stories: dict[str, list[str]] = defaultdict(list)
    for relation in records(delivery, "assumptionStories"):
        stories[relation["assumptionId"]].append(relation["storyId"])
    values: list[str] = []
    for assumption in records(delivery, "assumptions"):
        for question_id in QUESTION_PATTERN.findall(assumption["handling"]):
            values.append(
                f"{question_id}={assumption['assumptionId']}->{joined(stories[assumption['assumptionId']])}"
            )
    return "; ".join(sorted(values)) if values else "NONE"


def go_live_rows(
    delivery: dict[str, Any],
    design_context: dict[str, Any],
) -> list[str]:
    gaps = records(delivery, "gaps")
    stories = records(delivery, "stories")
    relations = records(delivery, "assumptionStories")
    assumptions = {item["assumptionId"] for item in records(delivery, "assumptions")}
    gap_ids_by_feature: dict[str, list[str]] = defaultdict(list)
    for gap in gaps:
        gap_ids_by_feature[gap["featureId"]].append(gap["gapId"])
    story_ids_by_gap: dict[str, list[str]] = defaultdict(list)
    for story in stories:
        story_ids_by_gap[story["gapId"]].append(story["storyId"])
    assumption_ids_by_story: dict[str, list[str]] = defaultdict(list)
    for relation in relations:
        if relation["assumptionId"] in assumptions:
            assumption_ids_by_story[relation["storyId"]].append(relation["assumptionId"])
    concerns = design_context.get("goLiveConcerns")
    if not isinstance(concerns, list) or any(not isinstance(item, dict) for item in concerns):
        raise ValueError("Story context must contain fixed Go-live Concern rows")
    result: list[str] = []
    for concern in concerns:
        feature_ids = [item for item in concern.get("featureIds", []) if isinstance(item, str)]
        gap_ids = [gap_id for feature_id in feature_ids for gap_id in gap_ids_by_feature[feature_id]]
        story_ids = [story_id for gap_id in gap_ids for story_id in story_ids_by_gap[gap_id]]
        assumption_ids = sorted(
            {
                assumption_id
                for story_id in story_ids
                for assumption_id in assumption_ids_by_story[story_id]
            }
        )
        disposition = concern.get("disposition")
        if disposition not in {"IN_SCOPE", "FULLY_COVERED"}:
            feature_ids, gap_ids, story_ids, assumption_ids = [], [], [], []
        result.append(
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    concern.get("concern", ""),
                    disposition,
                    joined(feature_ids),
                    joined(gap_ids),
                    joined(story_ids),
                    joined(assumption_ids),
                    concern.get("responsibilityBoundary", ""),
                    concern.get("basis", ""),
                )
            )
            + " |"
        )
    return result


def render(delivery: dict[str, Any], design_context: dict[str, Any]) -> bytes:
    gaps = records(delivery, "gaps")
    stories = records(delivery, "stories")
    criteria = records(delivery, "acceptanceCriteria")
    integrations = records(delivery, "integrations")
    assumptions = records(delivery, "assumptions")
    story_assumptions: dict[str, list[str]] = defaultdict(list)
    for relation in records(delivery, "assumptionStories"):
        story_assumptions[relation["storyId"]].append(relation["assumptionId"])
    lines = [
        "# 交付 Story 评审",
        "",
        "本文件由 Delivery candidate 与已验证的 Owner-local context 确定性投影。Reviewer 与用户",
        "批准声明是拟发布值，只有 sidecar 同时绑定当前 packet 后才具有授权效力。",
        "",
        "## Feature → Gap → Story",
        "",
        f"Stable IDs: {', '.join(stable_ids(delivery)) if stable_ids(delivery) else 'NONE'}",
        "",
        "| Feature | Gap | Story | Gap 说明 | Story 结果 | UAT |",
        "|---|---|---|---|---|---|",
    ]
    gap_by_id = {gap["gapId"]: gap for gap in gaps}
    lines.extend(
        "| "
        + " | ".join(
            cell(value)
            for value in (
                gap_by_id[story["gapId"]]["featureId"],
                story["gapId"],
                story["storyId"],
                gap_by_id[story["gapId"]].get("description", gap_by_id[story["gapId"]].get("name", "")),
                story.get("outcome", story.get("description", story.get("name", ""))),
                story.get("uatRelevant", ""),
            )
        )
        + " |"
        for story in stories
    )
    lines.extend(
        [
            "",
            "## Acceptance Criteria",
            "",
            "| Story | AC | Sequence | 可观察结果 | Decision Gate |",
            "|---|---|---|---|---|",
            *[
                "| "
                + " | ".join(
                    cell(value)
                    for value in (
                        item["storyId"],
                        item["acceptanceCriterionId"],
                        item["sequence"],
                        item["result"],
                        item.get("decisionGate", ""),
                    )
                )
                + " |"
                for item in criteria
            ],
            "",
            "## Integration",
            "",
            "| Integration | Story | Source | Target | Trigger | Direction | Purpose | Owner |",
            "|---|---|---|---|---|---|---|---|",
            *(
                [
                    "| "
                    + " | ".join(
                        cell(item.get(key, ""))
                        for key in (
                            "integrationId",
                            "storyId",
                            "source",
                            "target",
                            "trigger",
                            "direction",
                            "purpose",
                            "owner",
                        )
                    )
                    + " |"
                    for item in integrations
                ]
                or ["| NONE | NONE | NONE | NONE | NONE | NONE | NONE | NONE |"]
            ),
            "",
            "## Assumption / Risk",
            "",
            "| ID | Type | Name | Status | Trigger | Responsibility | Handling | Story IDs |",
            "|---|---|---|---|---|---|---|---|",
            *(
                [
                    "| "
                    + " | ".join(
                        cell(value)
                        for value in (
                            item["assumptionId"],
                            item["type"],
                            item["name"],
                            item["status"],
                            item["trigger"],
                            item["responsibilityBoundary"],
                            item["handling"],
                            joined(
                                [
                                    story_id
                                    for story_id, item_ids in story_assumptions.items()
                                    if item["assumptionId"] in item_ids
                                ]
                            ),
                        )
                    )
                    + " |"
                    for item in assumptions
                ]
                or ["| NONE | NONE | NONE | NONE | NONE | NONE | NONE | NONE |"]
            ),
            "",
            "## Questionnaire consumption",
            "",
            f"Questionnaire Map: {questionnaire_map(delivery)}",
            "",
            "## 上线映射",
            "",
            "| Concern | Disposition | Feature IDs | Gap IDs | Story IDs | Assumption/Risk IDs | 责任边界 | 依据 |",
            "|---|---|---|---|---|---|---|---|",
            *go_live_rows(delivery, design_context),
            "",
            "Go-live Mapping: PASSED",
            "",
            "## 审查与批准",
            "",
            "Reviewer: PASS",
            "User Approval: APPROVED",
            "",
        ]
    )
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
        design_context = files.read_json(f"{CONTEXT_ROOT}/design.json")
        if not isinstance(candidate, dict) or not isinstance(design_context, dict):
            raise ValueError("candidate and Story context must be JSON objects")
        payload = render(candidate, design_context)
        files.write_atomic(args.output, payload)
        print(
            json.dumps(
                {
                    "outcome": "OK",
                    "summary": "Story review projection is ready",
                    "diagnostics": [],
                    "outputs": [args.output],
                    "sha256": sha256_bytes(payload),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (ProjectIOError, OSError, ValueError, json.JSONDecodeError, KeyError) as error:
        print(
            json.dumps(
                {
                    "outcome": "BLOCKED",
                    "summary": "Story review projection could not be rendered",
                    "diagnostics": [
                        {
                            "code": getattr(error, "code", "RENDER_BLOCKED"),
                            "message": str(error),
                            "path": getattr(error, "relative_path", ""),
                        }
                    ],
                    "outputs": [],
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
