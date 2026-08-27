from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import validate as story_validator


# Windows 控制台默认使用本地代码页（如 cp936），会把中文结构化输出写成非 UTF-8 字节。
# 调用方按 UTF-8 读取 stdout/stderr，这里显式固定编码，与 POSIX 行为保持一致。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


CONTEXT_ROOT = ".ai-sow/work/generate-story/context"
MANIFEST_PATH = f"{CONTEXT_ROOT}/manifest.json"
FRAGMENT_SPECS = (
    ("requirements", f"{CONTEXT_ROOT}/requirements.json"),
    ("asIs", f"{CONTEXT_ROOT}/as-is.json"),
    ("design", f"{CONTEXT_ROOT}/design.json"),
    ("questionnaire", f"{CONTEXT_ROOT}/questionnaire.json"),
)
DESIGN_GO_LIVE_COLUMNS = (
    "Concern",
    "Disposition",
    "Feature IDs",
    "Effective Start IDs",
    "Evidence IDs",
    "责任边界",
    "依据",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare the Owner-local generate-story context closure"
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    return parser.parse_args()


def values(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def ids(items: list[dict[str, Any]], key: str) -> set[str]:
    result: set[str] = set()
    for item in items:
        value = item.get(key)
        candidates = value if isinstance(value, list) else [value]
        result.update(candidate for candidate in candidates if isinstance(candidate, str))
    return result


def upstream_diagnostics(files: ProjectFiles) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    for contract, builder in (
        (story_validator.REQUIREMENT_CONTRACT, story_validator.current_requirement_inputs),
        (story_validator.ASIS_CONTRACT, story_validator.current_asis_inputs),
        (story_validator.DESIGN_CONTRACT, story_validator.current_design_inputs),
    ):
        if diagnostics:
            break
        diagnostics.extend(story_validator.owner_handoff(files, contract, builder).diagnostics)
    return diagnostics


def questionnaire_records(files: ProjectFiles) -> list[dict[str, str]]:
    declaration = story_validator.declaration(
        story_validator.read_review(files, story_validator.REQUIREMENTS_REVIEW_PATH),
        "Questionnaire",
    )
    if declaration == ["NOT_REQUIRED"]:
        return []
    if declaration != [story_validator.REQUIREMENTS_QUESTIONNAIRE_PATH]:
        raise ProjectIOError(
            "UPSTREAM_HANDOFF_INVALID",
            story_validator.REQUIREMENTS_REVIEW_PATH,
            "Requirement questionnaire declaration is invalid",
        )
    text = story_validator.read_review(files, story_validator.REQUIREMENTS_QUESTIONNAIRE_PATH)
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|", line.strip())
        if match is None:
            continue
        field, value = match.groups()
        if field == "Question ID" and current:
            records.append(current)
            current = {}
        current[field] = value
    if current:
        records.append(current)
    return [
        record
        for record in records
        if record.get("Status") == "APPROVED_DEFAULT"
        and record.get("Disposition") == "ASSUMPTION_CANDIDATE"
    ]


def go_live_rows(files: ProjectFiles) -> list[dict[str, object]]:
    text = story_validator.read_review(files, story_validator.DESIGN_REVIEW_PATH)
    header_seen = False
    rows: list[dict[str, object]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if cells == DESIGN_GO_LIVE_COLUMNS:
            header_seen = True
            continue
        if cells and all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        if not header_seen:
            continue
        if len(cells) != 7 or cells[0] not in story_validator.GO_LIVE_CONCERNS:
            continue
        concern, disposition, features, effective_starts, evidence, boundary, basis = cells
        rows.append(
            {
                "basis": basis,
                "concern": concern,
                "disposition": disposition,
                "effectiveStartItemIds": story_validator.split_ids(effective_starts),
                "evidenceIds": story_validator.split_ids(evidence),
                "featureIds": story_validator.split_ids(features),
                "responsibilityBoundary": boundary,
            }
        )
    counts = {concern: 0 for concern in story_validator.GO_LIVE_CONCERNS}
    for row in rows:
        counts[str(row["concern"])] += 1
    if any(count != 1 for count in counts.values()):
        raise ProjectIOError(
            "UPSTREAM_HANDOFF_INVALID",
            story_validator.DESIGN_REVIEW_PATH,
            "Design review must expose each fixed Go-live Concern exactly once",
        )
    return rows


def context_fragments(
    upstream: dict[str, dict[str, Any]],
    concerns: list[dict[str, object]],
    questionnaire: list[dict[str, str]],
) -> tuple[dict[str, object], set[str], set[str]]:
    design = upstream["design"]
    asis = upstream["asIs"]
    requirements = upstream["requirements"]
    technical = upstream["technical"]
    scopes = values(design, "scopeDecisions")
    selected_features = {
        item["featureId"]
        for item in scopes
        if item.get("decision") in {"IN_SCOPE", "FULLY_COVERED"}
        and isinstance(item.get("featureId"), str)
    }
    selected_features.update(
        feature_id
        for concern in concerns
        for feature_id in concern["featureIds"]  # type: ignore[union-attr]
        if isinstance(feature_id, str)
    )
    selected_decisions = [
        item
        for item in values(design, "decisions")
        if bool(ids([item], "relatedFeatureIds") & selected_features)
    ]
    effective_start_ids = ids(scopes, "effectiveStartItemIds")
    effective_start_ids.update(
        value
        for concern in concerns
        for value in concern["effectiveStartItemIds"]  # type: ignore[union-attr]
        if isinstance(value, str)
    )
    selected_coverage = [
        item for item in values(asis, "coverage") if item.get("featureId") in selected_features
    ]
    effective_start_ids.update(ids(selected_coverage, "effectiveStartItemIds"))
    selected_effective_starts = [
        item
        for item in values(asis, "effectiveStartItems")
        if item.get("effectiveStartItemId") in effective_start_ids
    ]
    commitment_ids = ids(selected_effective_starts, "commitmentIds")
    selected_commitments = [
        item
        for item in values(asis, "commitments")
        if item.get("commitmentId") in commitment_ids
        or bool(ids([item], "relatedFeatureIds") & selected_features)
    ]
    evidence_ids = ids(scopes, "evidenceIds")
    evidence_ids.update(
        value
        for concern in concerns
        for value in concern["evidenceIds"]  # type: ignore[union-attr]
        if isinstance(value, str)
    )
    selected_evidence = [
        item
        for item in values(asis, "evidence")
        if item.get("evidenceId") in evidence_ids
        or bool(ids([item], "supportsIds") & (selected_features | effective_start_ids))
    ]
    return (
        {
            "requirements": {
                "business": {
                    "epics": values(requirements, "epics"),
                    "features": [
                        item
                        for item in values(requirements, "features")
                        if item.get("featureId") in selected_features
                    ],
                },
                "technical": {
                    "epics": values(technical, "epics"),
                    "features": [
                        item
                        for item in values(technical, "features")
                        if item.get("featureId") in selected_features
                    ],
                },
            },
            "asIs": {
                "commitments": selected_commitments,
                "coverage": selected_coverage,
                "effectiveStartItems": selected_effective_starts,
                "evidence": selected_evidence,
                "uncertainties": [
                    item
                    for item in values(asis, "uncertainties")
                    if item.get("affectsEstimate") is True
                    or bool(ids([item], "relatedFeatureIds") & selected_features)
                ],
            },
            "design": {
                "decisions": selected_decisions,
                "goLiveConcerns": concerns,
                "scopeDecisions": scopes,
            },
            "questionnaire": {"approvedDefaults": questionnaire},
        },
        selected_features,
        effective_start_ids,
    )


def main() -> int:
    args = parse_args()
    try:
        files = (
            ProjectFiles.open_view(args.project_root, args.staging_root)
            if args.staging_root is not None
            else ProjectFiles.open(args.project_root)
        )
        diagnostics = upstream_diagnostics(files)
        if diagnostics:
            print(
                json.dumps(
                    {
                        "outcome": "BLOCKED",
                        "summary": "generate-story context inputs are invalid",
                        "diagnostics": diagnostics,
                        "outputs": [],
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        upstream, diagnostics = story_validator.load_upstreams(files)
        if diagnostics or upstream is None:
            raise ProjectIOError("CONTEXT_INPUT_INVALID", MANIFEST_PATH, str(diagnostics))
        fragments, feature_ids, effective_start_ids = context_fragments(
            upstream,
            go_live_rows(files),
            questionnaire_records(files),
        )
        fragment_entries: list[dict[str, object]] = []
        for name, path in FRAGMENT_SPECS:
            payload = canonical_json_bytes(fragments[name])
            files.write_atomic(path, payload)
            fragment_entries.append(
                {
                    "bytes": len(payload),
                    "name": name,
                    "path": path,
                    "sha256": sha256_bytes(payload),
                }
            )
        input_errors, inputs = story_validator.owner_inputs(files)
        if input_errors:
            raise ProjectIOError("CONTEXT_INPUT_INVALID", MANIFEST_PATH, str(input_errors))
        manifest = {
            "algorithm": "ai-sow-generate-story-context-v1",
            "concernIds": list(story_validator.GO_LIVE_CONCERNS),
            "fragments": fragment_entries,
            "inputArtifacts": [story_validator.input_entry(item) for item in inputs],
            "owner": story_validator.SUBJECT,
            "selectedEffectiveStartItemIds": sorted(effective_start_ids),
            "selectedFeatureIds": sorted(feature_ids),
            "selectedQuestionIds": sorted(
                record["Question ID"]
                for record in fragments["questionnaire"]["approvedDefaults"]  # type: ignore[index]
                if isinstance(record.get("Question ID"), str)
            ),
        }
        files.write_atomic(MANIFEST_PATH, canonical_json_bytes(manifest))
        print(
            json.dumps(
                {
                    "outcome": "OK",
                    "summary": "generate-story context closure is ready",
                    "diagnostics": [],
                    "outputs": [MANIFEST_PATH, *[path for _, path in FRAGMENT_SPECS]],
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
                    "summary": "generate-story context preparation could not run",
                    "diagnostics": [
                        story_validator.diag(
                            getattr(error, "code", "CONTEXT_PREPARATION_BLOCKED"),
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
    sys.exit(main())
