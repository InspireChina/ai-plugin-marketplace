from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

import validate as requirement_validator


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


CANDIDATE_PATH = ".ai-sow/work/analyze-requirement/requirements.candidate.json"
MANIFEST_PATH = requirement_validator.CONTEXT_MANIFEST_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the Owner-local BUSINESS requirements context")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    parser.add_argument("--candidate", default=CANDIDATE_PATH)
    return parser.parse_args()


def schema_diagnostics(data: object) -> list[dict[str, object]]:
    schema_path = Path(__file__).resolve().parents[1] / "contracts/source-requirements.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    diagnostics: list[dict[str, object]] = []
    for error in sorted(Draft202012Validator(schema).iter_errors(data), key=lambda item: list(item.path)):
        diagnostics.append(
            requirement_validator.diag(
                "SCHEMA_INVALID",
                error.message,
                "/" + "/".join(str(part) for part in error.path),
            )
        )
    return diagnostics


def main() -> int:
    args = parse_args()
    try:
        files = (
            ProjectFiles.open_view(args.project_root, args.staging_root)
            if args.staging_root is not None
            else ProjectFiles.open(args.project_root)
        )
        candidate = files.read_json(args.candidate)
        diagnostics = schema_diagnostics(candidate)
        if not isinstance(candidate, dict):
            diagnostics.append(
                requirement_validator.diag(
                    "CANDIDATE_UNREADABLE",
                    "requirements candidate must be a JSON object",
                    args.candidate,
                )
            )
        questionnaire_artifact = None
        questionnaire_declaration = "NOT_REQUIRED"
        records: list[dict[str, str]] = []
        if not diagnostics and isinstance(candidate, dict):
            diagnostics.extend(requirement_validator.validate_business(files, candidate))
            questionnaire_declaration = requirement_validator.current_questionnaire_declaration(files)
            questionnaire_diagnostics, questionnaire_artifact = (
                requirement_validator.validate_questionnaire(
                    files,
                    questionnaire_declaration,
                    {item["epicId"] for item in candidate["epics"]}
                    | {item["featureId"] for item in candidate["features"]},
                    review_path=args.candidate,
                )
            )
            diagnostics.extend(questionnaire_diagnostics)
            if questionnaire_declaration == requirement_validator.QUESTIONNAIRE_PATH:
                records, _ = requirement_validator.parse_questionnaire(
                    files.read_bytes(requirement_validator.QUESTIONNAIRE_PATH).decode("utf-8")
                )
        inputs = ()
        if not diagnostics and isinstance(candidate, dict):
            local, inputs = requirement_validator.owner_inputs(
                files,
                candidate,
                questionnaire_artifact,
            )
            diagnostics.extend(local)
        if diagnostics:
            print(
                json.dumps(
                    {
                        "outcome": "BLOCKED",
                        "summary": "analyze-requirement context inputs are invalid",
                        "diagnostics": diagnostics,
                        "outputs": [],
                    },
                    ensure_ascii=False,
                )
            )
            return 2

        assert isinstance(candidate, dict)
        fragments: dict[str, object] = {
            "sourceIndex": {
                "normalizedItems": candidate["normalizedItems"],
                "sourceDocuments": candidate["sourceDocuments"],
            },
            "questionnaire": {
                "declaration": questionnaire_declaration,
                "records": records,
            },
        }
        fragment_entries: list[dict[str, object]] = []
        for name, path in requirement_validator.CONTEXT_FRAGMENT_SPECS:
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
            "algorithm": "ai-sow-analyze-requirement-context-v1",
            "fragments": fragment_entries,
            "inputArtifacts": [requirement_validator.input_entry(artifact) for artifact in inputs],
            "owner": requirement_validator.SUBJECT,
        }
        files.write_atomic(MANIFEST_PATH, canonical_json_bytes(manifest))
        print(
            json.dumps(
                {
                    "outcome": "OK",
                    "summary": "analyze-requirement context closure is ready",
                    "diagnostics": [],
                    "outputs": [MANIFEST_PATH, *[path for _, path in requirement_validator.CONTEXT_FRAGMENT_SPECS]],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (ProjectIOError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {
                    "outcome": "BLOCKED",
                    "summary": "analyze-requirement context preparation could not run",
                    "diagnostics": [
                        requirement_validator.diag(
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
