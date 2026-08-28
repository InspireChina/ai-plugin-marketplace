from __future__ import annotations

import argparse
import json
import re
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


DEFAULT_DESIGN = ".ai-sow/work/generate-design/design.candidate.json"
DEFAULT_TECHNICAL = ".ai-sow/work/generate-design/requirements.candidate.json"
DEFAULT_SOURCE = ".ai-sow/work/generate-design/review-source.json"
DEFAULT_OUTPUT = ".ai-sow/work/generate-design/review.candidate.md"
MANUAL_COUNT_PATTERN = re.compile(
    r"(?:\d+|[零一二三四五六七八九十百]+)\s*(?:个|项|条|份)?\s*"
    r"(?:Design\s+Items?|Architecture\s+Deltas?|Design\s+Decisions?|"
    r"Scope\s+Decisions?|TECHNICAL\s+(?:Epics?|Features?)|"
    r"BUSINESS\s+Features?|设计项|架构变化|(?:设计)?决策|范围(?:决策|结论))",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a deterministic Design review projection"
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    parser.add_argument("--candidate", default=DEFAULT_DESIGN)
    parser.add_argument("--requirements-candidate", default=DEFAULT_TECHNICAL)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def object_at(files: ProjectFiles, path: str) -> dict[str, Any]:
    value = files.read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"JSON must be an object: {path}")
    return value


def objects(value: dict[str, Any], key: str) -> list[dict[str, Any]]:
    entries = value.get(key)
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError(f"{key} must be an object array")
    return entries


def ids(values: object) -> str:
    if not isinstance(values, list):
        raise ValueError("review source ID values must be arrays")
    return ", ".join(str(value) for value in values) if values else "—"


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def required_text(source: dict[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"review source requires non-empty {key}")
    if match := MANUAL_COUNT_PATTERN.search(value):
        raise ValueError(
            f"review source {key} must not manually state candidate object counts; "
            f"matched {match.group(0)!r}; renderer owns Structure Counts"
        )
    return value


def overlapping_technical_feature_pairs(
    design: dict[str, Any],
    technical: dict[str, Any],
) -> set[tuple[str, str]]:
    technical_ids = {
        entry["featureId"] for entry in objects(technical, "features")
    }
    scopes = [
        entry
        for entry in objects(design, "scopeDecisions")
        if entry.get("decision") == "IN_SCOPE"
        and entry.get("featureId") in technical_ids
        and entry.get("designItemIds")
    ]
    pairs: set[tuple[str, str]] = set()
    for index, left in enumerate(scopes):
        left_items = set(left["designItemIds"])
        for right in scopes[index + 1:]:
            right_items = set(right["designItemIds"])
            if left_items <= right_items or right_items <= left_items:
                pairs.add(tuple(sorted((left["featureId"], right["featureId"]))))
    return pairs


def feature_boundary_rows(
    design: dict[str, Any],
    technical: dict[str, Any],
    source: dict[str, Any],
) -> list[str]:
    expected = overlapping_technical_feature_pairs(design, technical)
    reviews = source.get("featureBoundaryReview", [])
    if not isinstance(reviews, list) or any(not isinstance(entry, dict) for entry in reviews):
        raise ValueError("review source featureBoundaryReview must be an object array")
    provided: dict[tuple[str, str], str] = {}
    for entry in reviews:
        feature_ids = entry.get("featureIds")
        rationale = entry.get("nonOverlapRationale")
        if (
            not isinstance(feature_ids, list)
            or len(feature_ids) != 2
            or any(not isinstance(feature_id, str) for feature_id in feature_ids)
            or len(set(feature_ids)) != 2
            or not isinstance(rationale, str)
            or not rationale.strip()
        ):
            raise ValueError(
                "each featureBoundaryReview entry requires two unique featureIds "
                "and a non-empty nonOverlapRationale"
            )
        pair = tuple(sorted(feature_ids))
        if pair not in expected:
            raise ValueError(
                "featureBoundaryReview names a pair without overlapping Design Item sets: "
                + ", ".join(pair)
            )
        if pair in provided:
            raise ValueError(
                "duplicate featureBoundaryReview pair: " + ", ".join(pair)
            )
        provided[pair] = rationale
    missing = sorted(expected - set(provided))
    if missing:
        raise ValueError(
            "featureBoundaryReview must explain independently verifiable, non-overlapping "
            "outcomes for: "
            + "; ".join(" <-> ".join(pair) for pair in missing)
        )
    return [
        "| " + " | ".join((cell(pair[0]), cell(pair[1]), cell(provided[pair]))) + " |"
        for pair in sorted(provided)
    ] or ["| NONE | NONE | NONE |"]


def render(
    design: dict[str, Any],
    technical: dict[str, Any],
    source: dict[str, Any],
    *,
    design_hash: str,
    technical_hash: str,
) -> bytes:
    design_ids = [
        *[entry["designItemId"] for entry in objects(design, "designItems")],
        *[
            entry["architectureDeltaId"]
            for entry in objects(design, "architectureDeltas")
        ],
        *[entry["designDecisionId"] for entry in objects(design, "decisions")],
    ]
    technical_ids = [
        *[entry["epicId"] for entry in objects(technical, "epics")],
        *[entry["featureId"] for entry in objects(technical, "features")],
    ]
    structure_counts = (
        f"designItems={len(objects(design, 'designItems'))}, "
        f"architectureDeltas={len(objects(design, 'architectureDeltas'))}, "
        f"decisions={len(objects(design, 'decisions'))}, "
        f"scopeDecisions={len(objects(design, 'scopeDecisions'))}, "
        f"technicalEpics={len(objects(technical, 'epics'))}, "
        f"technicalFeatures={len(objects(technical, 'features'))}"
    )
    concerns = objects(source, "concerns")
    boundary_rows = feature_boundary_rows(design, technical, source)
    rows = []
    for concern in concerns:
        rows.append(
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    concern.get("concern", ""),
                    concern.get("disposition", ""),
                    ids(concern.get("featureIds")),
                    ids(concern.get("effectiveStartIds")),
                    ids(concern.get("evidenceIds")),
                    concern.get("responsibilityBoundary", ""),
                    concern.get("basis", ""),
                )
            )
            + " |"
        )
    lines = [
        "# 目标设计评审",
        "",
        "本文件由两份 Design candidate 与 work-only review source 确定性投影。",
        "Reviewer 与用户批准声明是拟发布值；只有 sidecar 绑定当前 packet 后才具有授权效力。",
        "",
        "## 目标设计",
        "",
        required_text(source, "targetDesign"),
        "",
        f"Design IDs: {', '.join(design_ids) if design_ids else 'NONE'}",
        f"Technical IDs: {', '.join(technical_ids) if technical_ids else 'NONE'}",
        f"Structure Counts: {structure_counts}",
        f"Design Candidate SHA-256: {design_hash}",
        f"Technical Candidate SHA-256: {technical_hash}",
        "",
        "## Architecture Delta",
        "",
        required_text(source, "architectureDeltaReview"),
        "",
        "## Design Decision",
        "",
        required_text(source, "designDecisionReview"),
        "",
        "## Scope",
        "",
        required_text(source, "scopeReview"),
        "",
        "## Feature Boundary Review",
        "",
        "| Feature A | Feature B | 非重叠交付边界 |",
        "|---|---|---|",
        *boundary_rows,
        "",
        "## TECHNICAL requirements",
        "",
        required_text(source, "technicalRequirementsReview"),
        "",
        "## 高阶设计覆盖门禁",
        "",
        "HLD Coverage: PASSED",
        "",
        "## 上线范围门禁",
        "",
        "| Concern | Disposition | Feature IDs | Effective Start IDs | Evidence IDs | 责任边界 | 依据 |",
        "|---|---|---|---|---|---|---|",
        *rows,
        "",
        "Go-live Assessment: PASSED",
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
        design_payload = files.read_bytes(args.candidate)
        technical_payload = files.read_bytes(args.requirements_candidate)
        output = render(
            object_at(files, args.candidate),
            object_at(files, args.requirements_candidate),
            object_at(files, args.source),
            design_hash=sha256_bytes(design_payload),
            technical_hash=sha256_bytes(technical_payload),
        )
        files.write_atomic(args.output, output)
        print(
            json.dumps(
                {
                    "outcome": "OK",
                    "summary": "Design review projection is ready",
                    "diagnostics": [],
                    "outputs": [args.output],
                    "sha256": sha256_bytes(output),
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
                    "summary": "Design review projection could not be rendered",
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
