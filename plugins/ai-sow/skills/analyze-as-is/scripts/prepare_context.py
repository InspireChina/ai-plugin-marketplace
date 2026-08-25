from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import validate as asis_validator


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import Artifact, canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


CONTEXT_ROOT = ".ai-sow/work/analyze-as-is/context"
MANIFEST_PATH = f"{CONTEXT_ROOT}/manifest.json"
FRAGMENT_SPECS = (
    ("requirements", f"{CONTEXT_ROOT}/requirements.json"),
    ("investigationScope", f"{CONTEXT_ROOT}/investigation-scope.json"),
    ("evidenceInventory", f"{CONTEXT_ROOT}/evidence-inventory.json"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the Owner-local As-Is review context")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    parser.add_argument(
        "--candidate",
        default=".ai-sow/work/analyze-as-is/asis.candidate.json",
    )
    return parser.parse_args()


def input_entry(artifact: Artifact) -> dict[str, object]:
    locator_key = "path" if artifact.kind == "FILE" else "identity"
    return {
        "name": artifact.name,
        "kind": artifact.kind,
        locator_key: artifact.locator,
        "sha256": artifact.sha256,
    }


def questionnaire_artifact(files: ProjectFiles) -> Artifact:
    try:
        payload = files.read_bytes(asis_validator.QUESTIONNAIRE_PATH)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING":
            raise
        logical = canonical_json_bytes({"declaration": "NOT_REQUIRED"})
        return Artifact(
            "questionnaire",
            "QUESTIONNAIRE_PRESENCE",
            "questionnaire:NOT_REQUIRED",
            sha256_bytes(logical),
        )
    return Artifact(
        "questionnaire",
        "QUESTIONNAIRE_PRESENCE",
        f"questionnaire:{asis_validator.QUESTIONNAIRE_PATH}",
        sha256_bytes(payload),
    )


def main() -> int:
    args = parse_args()
    try:
        files = (
            ProjectFiles.open_view(args.project_root, args.staging_root)
            if args.staging_root is not None
            else ProjectFiles.open(args.project_root)
        )
        handoff = asis_validator.requirement_handoff(files)
        diagnostics: list[dict[str, object]] = list(handoff.diagnostics)
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "contracts/asis.schema.json").read_text(
                encoding="utf-8"
            )
        )
        _, candidate, local = asis_validator.load_candidate(files, args.candidate, schema)
        if not diagnostics:
            diagnostics.extend(local)
        if not diagnostics and candidate is not None:
            feature_ids, requirement_ids, local = asis_validator.requirement_ids_from_upstream(files)
            diagnostics.extend(local)
            if not diagnostics:
                diagnostics.extend(
                    asis_validator.validate_semantics(candidate, feature_ids, requirement_ids)
                )
        inputs: tuple[Artifact, ...] = ()
        if not diagnostics and candidate is not None:
            local, inputs = asis_validator.attest_inputs(
                files,
                candidate,
                questionnaire_artifact(files),
            )
            diagnostics.extend(local)
        if diagnostics or candidate is None:
            print(
                json.dumps(
                    {
                        "outcome": "BLOCKED",
                        "summary": "analyze-as-is context inputs are invalid",
                        "diagnostics": diagnostics,
                        "outputs": [],
                    },
                    ensure_ascii=False,
                )
            )
            return 2

        requirements = files.read_json(asis_validator.REQUIREMENTS_PATH)
        if not isinstance(requirements, dict):
            raise ValueError("Requirements must be a JSON object")
        scope = candidate["analysisScope"]
        fragments: dict[str, object] = {
            "requirements": {
                key: requirements.get(key, [])
                for key in ("sourceDocuments", "normalizedItems", "epics", "features")
            },
            "investigationScope": {
                "analysisScope": scope,
                "topicAssessments": candidate["topicAssessments"],
                "uncertainties": candidate["uncertainties"],
            },
            "evidenceInventory": {
                "evidence": candidate["evidence"],
                "registeredRepositories": scope["repositorySnapshots"],
                "registeredPriorSows": scope["priorSowSnapshots"],
            },
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
        manifest = {
            "algorithm": "ai-sow-analyze-as-is-context-v1",
            "fragments": fragment_entries,
            "inputArtifacts": [input_entry(artifact) for artifact in inputs],
            "owner": asis_validator.SUBJECT,
            "selectedEvidenceIds": [
                entry["evidenceId"] for entry in candidate["evidence"]
            ],
            "selectedTopicIds": [
                entry["topic"] for entry in candidate["topicAssessments"]
            ],
            "selectionRule": (
                "九个 Topic 全量披露；登记 repository/prior SOW 与 Evidence 只保存 inventory、"
                "项目相对 anchor 和 hash，正文与工具输出按需读取。"
            ),
        }
        files.write_atomic(MANIFEST_PATH, canonical_json_bytes(manifest))
        print(
            json.dumps(
                {
                    "outcome": "OK",
                    "summary": "analyze-as-is context closure is ready",
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
                    "summary": "analyze-as-is context preparation could not run",
                    "diagnostics": [
                        asis_validator.diag(
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
