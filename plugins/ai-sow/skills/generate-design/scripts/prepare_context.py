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

SCRIPT_ROOT = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_ROOT.parents[2]
for import_root in (SCRIPT_ROOT, PLUGIN_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import validate as design_validator
from runtime.claims import claim_metrics
from runtime.controls import owner_control
from runtime.context_pages import (
    PENDING_CLAIM_METRICS,
    context_budget,
    read_protocol,
    write_context_fragments,
    write_review_claims,
)
from runtime.handoff import canonical_json_bytes
from runtime.project_io import ProjectFiles, ProjectIOError
from runtime.review_checks import prepare_claims


CONTEXT_ROOT = ".ai-sow/work/generate-design/context"
MANIFEST_PATH = f"{CONTEXT_ROOT}/manifest.json"
FRAGMENT_SPECS = (
    ("businessRequirements", f"{CONTEXT_ROOT}/business-requirements.json"),
    ("asIsCoverage", f"{CONTEXT_ROOT}/as-is-coverage.json"),
    ("uncertainties", f"{CONTEXT_ROOT}/uncertainties.json"),
    ("effectiveStart", f"{CONTEXT_ROOT}/effective-start.json"),
    ("sourceAnchors", f"{CONTEXT_ROOT}/source-anchors.json"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare the Owner-local generate-design context closure"
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    parser.add_argument("--candidate", default=".ai-sow/work/generate-design/design.candidate.json")
    parser.add_argument("--requirements-candidate", default=".ai-sow/work/generate-design/requirements.candidate.json")
    return parser.parse_args()


def object_at(files: ProjectFiles, path: str) -> dict[str, Any]:
    value = files.read_json(path)
    if not isinstance(value, dict):
        raise ProjectIOError(
            "PROJECT_JSON_INVALID", path, f"project JSON must be an object: {path}"
        )
    return value


def list_at(value: dict[str, Any], key: str) -> list[dict[str, Any]]:
    entries = value.get(key, [])
    if not isinstance(entries, list):
        raise ValueError(f"{key} must be an array")
    return [entry for entry in entries if isinstance(entry, dict)]


def source_evidence(
    entries: list[dict[str, Any]],
    *,
    evidence_paths: dict[str, str],
    prior_sow_paths: dict[str, str],
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for entry in entries:
        value = {
            key: entry.get(key)
            for key in ("evidenceId", "kind", "reference", "summary", "supportsIds")
            if key in entry
        }
        evidence_id = entry.get("evidenceId")
        resolved = evidence_paths.get(evidence_id) if isinstance(evidence_id, str) else None
        reference = entry.get("reference")
        if resolved is None and entry.get("kind") == "PRIOR_SOW" and isinstance(reference, str):
            locator = reference.split("#", 1)[0]
            if locator.startswith("prior-sow:"):
                resolved = prior_sow_paths.get(locator.removeprefix("prior-sow:"))
        if resolved is not None:
            value["resolvedPath"] = resolved
        projected.append(value)
    return projected


def main() -> int:
    args = parse_args()
    try:
        files = (
            ProjectFiles.open_view(args.project_root, args.staging_root)
            if args.staging_root is not None
            else ProjectFiles.open(args.project_root)
        )
        diagnostics: list[dict[str, object]] = []
        for contract, builder in (
            (
                design_validator.REQUIREMENT_CONTRACT,
                design_validator.current_requirement_inputs,
            ),
            (design_validator.ASIS_CONTRACT, design_validator.current_asis_inputs),
        ):
            if diagnostics:
                break
            diagnostics.extend(
                design_validator.owner_handoff(files, contract, builder).diagnostics
            )
        if diagnostics:
            print(
                json.dumps(
                    {
                        "outcome": "BLOCKED",
                        "summary": "generate-design context inputs are invalid",
                        "diagnostics": diagnostics,
                        "outputs": [],
                    },
                    ensure_ascii=False,
                )
            )
            return 2

        requirements = object_at(files, design_validator.REQUIREMENTS_PATH)
        asis = object_at(files, design_validator.ASIS_PATH)
        scope = asis.get("analysisScope")
        if not isinstance(scope, dict):
            raise ValueError("analysisScope must be an object")
        asis_inputs, asis_input_failure = design_validator.current_asis_inputs(files)
        if asis_input_failure is not None:
            raise ProjectIOError(
                "CONTEXT_INPUT_INVALID", MANIFEST_PATH, str(asis_input_failure.diagnostics)
            )
        evidence_paths = {
            artifact.name.removeprefix("evidence:"): artifact.locator
            for artifact in asis_inputs
            if artifact.kind == "FILE" and artifact.name.startswith("evidence:")
        }
        repository_snapshots = list_at(scope, "repositorySnapshots")
        prior_sow_snapshots = list_at(scope, "priorSowSnapshots")
        prior_sow_paths = {
            entry["priorSowId"]: entry["file"]
            for entry in prior_sow_snapshots
            if isinstance(entry.get("priorSowId"), str)
            and isinstance(entry.get("file"), str)
        }
        business = {
            key: requirements.get(key, [])
            for key in ("epics", "features")
        }
        coverage = {
            key: asis.get(key, [])
            for key in ("topicAssessments", "coverage", "commitments")
        }
        uncertainties = {"uncertainties": asis.get("uncertainties", [])}
        effective_start = {
            key: asis.get(key, [])
            for key in ("effectiveStartItems", "items", "commitments")
        }
        source_anchors = {
            "sourceDocuments": list_at(requirements, "sourceDocuments"),
            "normalizedItems": list_at(requirements, "normalizedItems"),
            "repositorySnapshots": repository_snapshots,
            "priorSowSnapshots": prior_sow_snapshots,
            "evidence": source_evidence(
                list_at(asis, "evidence"),
                evidence_paths=evidence_paths,
                prior_sow_paths=prior_sow_paths,
            ),
        }
        claims = prepare_claims(
            files,
            args.project_root,
            design_validator.SUBJECT,
            (("design", args.candidate), ("technicalRequirements", args.requirements_candidate)),
            ".ai-sow/work/generate-design/claims.json",
            validation_path=design_validator.VALIDATION_PATH,
            anchor_documents=(source_anchors,),
        )
        fragments = {
            "businessRequirements": business,
            "asIsCoverage": coverage,
            "uncertainties": uncertainties,
            "effectiveStart": effective_start,
            "sourceAnchors": source_anchors,
        }
        fragment_entries = write_context_fragments(files, FRAGMENT_SPECS, fragments)
        input_errors, inputs = design_validator.owner_inputs(files)
        if input_errors:
            raise ProjectIOError(
                "CONTEXT_INPUT_INVALID", MANIFEST_PATH, str(input_errors)
            )
        manifest = {
            "algorithm": "ai-sow-generate-design-context-v1",
            "contextBudget": context_budget(),
            "fragments": fragment_entries,
            "inputArtifacts": [
                design_validator.input_entry(artifact) for artifact in inputs
            ],
            "owner": design_validator.SUBJECT,
            "ownerControl": owner_control(
                files.read_json(design_validator.PROJECT_PATH), design_validator.SUBJECT
            ),
            "claimMetrics": (
                PENDING_CLAIM_METRICS
                if claims.get("status") == "PENDING_CANDIDATE"
                else claim_metrics(claims)
            ),
            "readProtocol": read_protocol(),
            "reviewClaims": write_review_claims(
                files,
                design_validator.CLAIMS_PATH,
                claims,
            ),
            "selectedEffectiveStartItemIds": sorted(
                entry["effectiveStartItemId"]
                for entry in list_at(asis, "effectiveStartItems")
                if isinstance(entry.get("effectiveStartItemId"), str)
            ),
            "selectedFeatureIds": sorted(
                entry["featureId"]
                for entry in list_at(requirements, "features")
                if isinstance(entry.get("featureId"), str)
            ),
        }
        files.write_atomic(MANIFEST_PATH, canonical_json_bytes(manifest))
        print(
            json.dumps(
                {
                    "outcome": "OK",
                    "summary": "generate-design context closure is ready",
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
                    "summary": "generate-design context preparation could not run",
                    "diagnostics": [
                        design_validator.diag(
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
    raise SystemExit(main())
