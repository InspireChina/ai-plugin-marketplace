from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from read_template import read_contract
import validate as task_validator


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


CONTEXT_ROOT = ".ai-sow/work/generate-task/context"
MANIFEST_PATH = f"{CONTEXT_ROOT}/manifest.json"
FRAGMENT_SPECS = (
    ("delivery", f"{CONTEXT_ROOT}/delivery.json"),
    ("design", f"{CONTEXT_ROOT}/design.json"),
    ("asIs", f"{CONTEXT_ROOT}/as-is.json"),
    ("technicalRequirements", f"{CONTEXT_ROOT}/technical-requirements.json"),
    ("templateCatalog", f"{CONTEXT_ROOT}/template-catalog.json"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the Owner-local generate-task context closure")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    return parser.parse_args()


def values(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def string_ids(items: list[dict[str, Any]], key: str) -> set[str]:
    return {
        value
        for item in items
        for value in (
            item.get(key, []) if isinstance(item.get(key), list) else [item.get(key)]
        )
        if isinstance(value, str)
    }


def load_object(files: Any, path: str) -> dict[str, Any]:
    value = files.read_json(path)
    if not isinstance(value, dict):
        raise ProjectIOError("PROJECT_JSON_INVALID", path, f"project JSON must be an object: {path}")
    return value


def delivery_context(delivery: dict[str, Any]) -> dict[str, Any]:
    return {
        key: delivery.get(key, [])
        for key in (
            "gaps",
            "stories",
            "acceptanceCriteria",
            "integrations",
            "assumptions",
        )
        if key in delivery
    }


def design_context(
    delivery: dict[str, Any],
    design: dict[str, Any],
    technical: dict[str, Any],
) -> tuple[dict[str, Any], set[str], set[str], set[str]]:
    gaps = values(delivery, "gaps")
    feature_ids = string_ids(gaps, "featureId")
    scope_decisions = [
        item
        for item in values(design, "scopeDecisions")
        if item.get("featureId") in feature_ids
    ]
    design_item_ids = string_ids(scope_decisions, "designItemIds")
    design_items = [
        item
        for item in values(design, "designItems")
        if item.get("designItemId") in design_item_ids
    ]
    deltas = [
        item
        for item in values(design, "architectureDeltas")
        if item.get("designItemId") in design_item_ids
    ]
    effective_start_ids = string_ids(scope_decisions, "effectiveStartItemIds") | string_ids(
        deltas, "effectiveStartItemIds"
    )
    selected_technical_features = [
        item
        for item in values(technical, "features")
        if item.get("featureId") in feature_ids
        or string_ids([item], "relatedBusinessFeatureIds") & feature_ids
    ]
    decision_ids = string_ids(values(delivery, "integrations"), "decisionIds")
    for feature in selected_technical_features:
        source = feature.get("source")
        if isinstance(source, dict):
            decision_ids.update(string_ids([source], "designDecisionIds"))
            effective_start_ids.update(string_ids([source], "effectiveStartItemIds"))
    decisions = [
        item
        for item in values(design, "decisions")
        if item.get("designDecisionId") in decision_ids
        or bool(string_ids([item], "designItemIds") & design_item_ids)
        or bool(string_ids([item], "relatedFeatureIds") & feature_ids)
    ]
    effective_start_ids.update(string_ids(decisions, "effectiveStartItemIds"))
    evidence_ids = string_ids(decisions, "evidenceIds")
    return (
        {
            "scopeDecisions": scope_decisions,
            "designItems": design_items,
            "architectureDeltas": deltas,
            "decisions": decisions,
        },
        feature_ids,
        effective_start_ids,
        evidence_ids,
    )


def asis_context(
    delivery: dict[str, Any],
    asis: dict[str, Any],
    selected_effective_start_ids: set[str],
    feature_ids: set[str],
    evidence_ids: set[str],
) -> dict[str, Any]:
    effective_starts = values(asis, "effectiveStartItems")
    selected_effective_starts = [
        item
        for item in effective_starts
        if not selected_effective_start_ids
        or item.get("effectiveStartItemId") in selected_effective_start_ids
    ]
    if selected_effective_start_ids and len(selected_effective_starts) != len(
        selected_effective_start_ids
    ):
        selected_effective_starts = effective_starts
    source_item_ids = string_ids(selected_effective_starts, "sourceItemIds")
    commitment_ids = string_ids(selected_effective_starts, "commitmentIds") | string_ids(
        values(delivery, "gaps"), "commitmentIds"
    )
    selected_items = [
        item for item in values(asis, "items") if item.get("asIsItemId") in source_item_ids
    ]
    selected_commitments = [
        item
        for item in values(asis, "commitments")
        if item.get("commitmentId") in commitment_ids
    ]
    selected_uncertainties = [
        item for item in values(asis, "uncertainties") if item.get("affectsEstimate") is True
    ]
    support_ids = (
        {item.get("effectiveStartItemId") for item in selected_effective_starts}
        | source_item_ids
        | commitment_ids
        | feature_ids
    )
    selected_evidence = [
        item
        for item in values(asis, "evidence")
        if item.get("evidenceId") in evidence_ids
        or string_ids([item], "supportsIds") & support_ids
    ]
    return {
        "effectiveStartItems": selected_effective_starts,
        "items": selected_items,
        "commitments": selected_commitments,
        "uncertainties": selected_uncertainties,
        "evidence": selected_evidence,
    }


def technical_context(
    technical: dict[str, Any],
    feature_ids: set[str],
) -> dict[str, Any]:
    features = [
        item
        for item in values(technical, "features")
        if item.get("featureId") in feature_ids
        or set(
            value
            for value in item.get("relatedBusinessFeatureIds", [])
            if isinstance(value, str)
        )
        & feature_ids
    ]
    epic_ids = {item.get("epicId") for item in features if isinstance(item.get("epicId"), str)}
    epics = [item for item in values(technical, "epics") if item.get("epicId") in epic_ids]
    return {"epics": epics, "features": features}


def upstream_diagnostics(files: Any) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    for contract, builder in (
        (task_validator.ASIS_CONTRACT, task_validator.current_asis_inputs),
        (task_validator.DESIGN_CONTRACT, task_validator.current_design_inputs),
        (task_validator.STORY_CONTRACT, task_validator.current_story_inputs),
    ):
        if diagnostics:
            break
        diagnostics.extend(task_validator.owner_handoff(files, contract, builder).diagnostics)
    return diagnostics


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
                        "summary": "generate-task context inputs are invalid",
                        "diagnostics": diagnostics,
                        "outputs": [],
                    },
                    ensure_ascii=False,
                )
            )
            return 2

        delivery = load_object(files, task_validator.DELIVERY_PATH)
        design = load_object(files, task_validator.DESIGN_PATH)
        asis = load_object(files, task_validator.ASIS_PATH)
        technical = load_object(files, task_validator.TECHNICAL_PATH)
        template_catalog = read_contract(files.resolve(task_validator.TEMPLATE_PATH))
        selected_design, feature_ids, effective_start_ids, evidence_ids = design_context(
            delivery, design, technical
        )
        # Delivery does not own a complete Story -> Effective Start relation. Until that
        # relation exists in an upstream contract, excluding an As-Is starting point would
        # turn a context optimization into an unsupported business-scope decision.
        effective_start_ids.update(
            item["effectiveStartItemId"]
            for item in values(asis, "effectiveStartItems")
            if isinstance(item.get("effectiveStartItemId"), str)
        )
        fragments = {
            "delivery": delivery_context(delivery),
            "design": selected_design,
            "asIs": asis_context(
                delivery,
                asis,
                effective_start_ids,
                feature_ids,
                evidence_ids,
            ),
            "technicalRequirements": technical_context(technical, feature_ids),
            "templateCatalog": template_catalog,
        }

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
        input_errors, inputs = task_validator.owner_inputs(files)
        if input_errors:
            raise ProjectIOError(
                "CONTEXT_INPUT_INVALID",
                MANIFEST_PATH,
                str(input_errors),
            )
        manifest = {
            "algorithm": "ai-sow-generate-task-context-v1",
            "fragments": fragment_entries,
            "inputArtifacts": [task_validator.input_entry(artifact) for artifact in inputs],
            "owner": task_validator.SUBJECT,
            "selectedFeatureIds": sorted(feature_ids),
            "selectedEffectiveStartItemIds": sorted(effective_start_ids),
        }
        files.write_atomic(MANIFEST_PATH, canonical_json_bytes(manifest))
        print(
            json.dumps(
                {
                    "outcome": "OK",
                    "summary": "generate-task context closure is ready",
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
                    "summary": "generate-task context preparation could not run",
                    "diagnostics": [
                        task_validator.diag(
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
