from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


SOURCE_VERSION = "0.1.0-beta.1"
TARGET_VERSION = "0.1.0-beta.2"
PROJECT_PATH = ".ai-sow/project.json"
REPORT_PATH = ".ai-sow/migrations/beta1-to-beta2.json"
MIGRATION_ID = "ai-sow-beta1-to-beta2"
PROJECT_SCHEMA_PATH = PLUGIN_ROOT / "skills/setup/contracts/project.schema.json"


class MigrationError(ValueError):
    def __init__(self, code: str, message: str, path: str = PROJECT_PATH) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate AI SOW beta.1 project metadata to beta.2")
    parser.add_argument("--project-root", required=True, type=Path)
    return parser.parse_args()


def project_schema(version: str) -> dict[str, Any]:
    schema = json.loads(PROJECT_SCHEMA_PATH.read_text(encoding="utf-8"))
    if version == SOURCE_VERSION:
        schema = copy.deepcopy(schema)
        schema["properties"]["pluginVersion"]["const"] = SOURCE_VERSION
    elif version != TARGET_VERSION:
        raise ValueError(f"unsupported project schema version: {version}")
    return schema


def validate_project(value: object, version: str) -> dict[str, Any]:
    errors = sorted(
        Draft202012Validator(project_schema(version)).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors or not isinstance(value, dict):
        raise MigrationError(
            "PROJECT_SCHEMA_INVALID",
            f"project metadata is not a valid {version} project: {errors[0].message if errors else 'object required'}",
        )
    return value


def migration_values(current: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    version = current.get("pluginVersion")
    if version == SOURCE_VERSION:
        source = validate_project(current, SOURCE_VERSION)
        target = {**source, "pluginVersion": TARGET_VERSION}
    elif version == TARGET_VERSION:
        target = validate_project(current, TARGET_VERSION)
        source = {**target, "pluginVersion": SOURCE_VERSION}
        validate_project(source, SOURCE_VERSION)
    else:
        raise MigrationError(
            "MIGRATION_SOURCE_UNSUPPORTED",
            f"migration accepts only {SOURCE_VERSION} or its migrated {TARGET_VERSION} project",
        )
    validate_project(target, TARGET_VERSION)
    return source, target


def report_for(source: dict[str, Any], target: dict[str, Any]) -> dict[str, object]:
    return {
        "migrationId": MIGRATION_ID,
        "sourcePluginVersion": SOURCE_VERSION,
        "targetPluginVersion": TARGET_VERSION,
        "projectPath": PROJECT_PATH,
        "sourceCanonicalSha256": sha256_bytes(canonical_json_bytes(source)),
        "targetCanonicalSha256": sha256_bytes(canonical_json_bytes(target)),
        "businessDataChanged": False,
        "stableDataAction": "REVIEW_AND_REPUBLISH_0_3",
    }


def migrate(project_root: Path) -> tuple[str, dict[str, object]]:
    files = ProjectFiles.open(project_root)
    current = files.read_json(PROJECT_PATH)
    source, target = migration_values(current if isinstance(current, dict) else {})
    report = report_for(source, target)
    target_payload = canonical_json_bytes(target)
    report_payload = canonical_json_bytes(report)

    try:
        existing_report = files.read_bytes(REPORT_PATH)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING":
            raise
    else:
        if existing_report != report_payload:
            raise ProjectIOError(
                "PROJECT_CONTENT_CONFLICT",
                REPORT_PATH,
                f"existing project file has different content: {REPORT_PATH}",
            )

    files.write_atomic(PROJECT_PATH, target_payload)
    reread = files.read_json(PROJECT_PATH)
    validate_project(reread, TARGET_VERSION)
    publication = files.publish_new(REPORT_PATH, report_payload)
    return publication, report


def main() -> int:
    args = parse_args()
    try:
        publication, report = migrate(args.project_root)
        print(
            json.dumps(
                {
                    "outcome": "OK",
                    "summary": "project metadata migrated to beta.2",
                    "publication": publication,
                    "reportPath": REPORT_PATH,
                    "report": report,
                    "diagnostics": [],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except MigrationError as error:
        code, path = error.code, error.path
        message = str(error)
    except ProjectIOError as error:
        code, path, message = error.code, error.relative_path, str(error)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        code, path, message = "MIGRATION_BLOCKED", PROJECT_PATH, str(error)
    print(
        json.dumps(
            {
                "outcome": "BLOCKED",
                "summary": "project metadata was not migrated",
                "diagnostics": [{"code": code, "message": message, "path": path}],
            },
            ensure_ascii=False,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
