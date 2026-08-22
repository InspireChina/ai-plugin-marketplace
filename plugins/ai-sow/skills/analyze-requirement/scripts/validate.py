from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def diagnostic(code: str, message: str, path: str = "") -> dict[str, str]:
    value = {"code": code, "message": message}
    if path:
        value["path"] = path
    return value


def validation_output_diagnostic(
    project_root: Path,
    validation_path: Path,
) -> dict[str, str] | None:
    for path in (project_root / ".ai-sow", validation_path.parent, validation_path):
        if path.is_symlink():
            return diagnostic(
                "OUTPUT_PATH_UNSAFE",
                f"validation output path must not be a symlink: {path}",
                str(path),
            )
        try:
            path.resolve(strict=False).relative_to(project_root)
        except (OSError, RuntimeError, ValueError):
            return diagnostic(
                "OUTPUT_PATH_UNSAFE",
                f"validation output path is outside project root: {path}",
                str(path),
            )
    return None


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _is_windows_reparse_point(snapshot: os.stat_result) -> bool:
    attributes = getattr(snapshot, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _safe_directory_snapshot(path: Path) -> os.stat_result:
    snapshot = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(snapshot.st_mode) or _is_windows_reparse_point(snapshot):
        raise OSError(
            f"validation output directory is unsafe or a reparse point: {path}"
        )
    return snapshot


def _safe_regular_file_snapshot(path: Path) -> os.stat_result:
    snapshot = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(snapshot.st_mode) or _is_windows_reparse_point(snapshot):
        raise OSError(
            f"validation output report is unsafe or a reparse point: {path}"
        )
    return snapshot


def _write_validation_report_portable(
    project_root: Path,
    validation_path: Path,
    content: str,
) -> None:
    ai_sow = project_root / ".ai-sow"
    ai_sow_snapshot = _safe_directory_snapshot(ai_sow)
    validation_path.parent.mkdir(exist_ok=True)
    if not _same_file(ai_sow_snapshot, _safe_directory_snapshot(ai_sow)):
        raise OSError("validation output parent changed before write")
    validation_snapshot = _safe_directory_snapshot(validation_path.parent)
    try:
        previous_file_snapshot = _safe_regular_file_snapshot(validation_path)
    except FileNotFoundError:
        previous_file_snapshot = None
    flags = os.O_WRONLY | getattr(os, "O_BINARY", 0)
    if previous_file_snapshot is None:
        flags |= os.O_CREAT | os.O_EXCL
    file_descriptor = os.open(validation_path, flags, 0o666)
    try:
        file_snapshot = os.fstat(file_descriptor)
        current_path_snapshot = _safe_regular_file_snapshot(validation_path)
        if (
            not _same_file(file_snapshot, current_path_snapshot)
            or (
                previous_file_snapshot is not None
                and not _same_file(previous_file_snapshot, file_snapshot)
            )
            or not _same_file(ai_sow_snapshot, _safe_directory_snapshot(ai_sow))
            or not _same_file(
                validation_snapshot,
                _safe_directory_snapshot(validation_path.parent),
            )
        ):
            raise OSError("validation output path changed before write")
        os.ftruncate(file_descriptor, 0)
        payload = content.encode("utf-8")
        while payload:
            payload = payload[os.write(file_descriptor, payload) :]
        os.fsync(file_descriptor)
        if (
            not _same_file(ai_sow_snapshot, _safe_directory_snapshot(ai_sow))
            or not _same_file(
                validation_snapshot,
                _safe_directory_snapshot(validation_path.parent),
            )
            or not _same_file(
                file_snapshot,
                _safe_regular_file_snapshot(validation_path),
            )
        ):
            raise OSError("validation output path changed during write")
    finally:
        os.close(file_descriptor)


def write_validation_report(
    project_root: Path,
    validation_path: Path,
    content: str,
) -> None:
    if os.name != "posix":
        _write_validation_report_portable(project_root, validation_path, content)
        return

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    root_fd = os.open(project_root, directory_flags)
    try:
        ai_sow_fd = os.open(".ai-sow", directory_flags, dir_fd=root_fd)
        try:
            try:
                os.mkdir("validation", dir_fd=ai_sow_fd)
            except FileExistsError:
                pass
            validation_fd = os.open("validation", directory_flags, dir_fd=ai_sow_fd)
            try:
                report_flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_TRUNC
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                )
                report_fd = os.open(
                    validation_path.name,
                    report_flags,
                    0o666,
                    dir_fd=validation_fd,
                )
                try:
                    payload = content.encode("utf-8")
                    while payload:
                        payload = payload[os.write(report_fd, payload) :]
                    os.fsync(report_fd)
                finally:
                    os.close(report_fd)
            finally:
                os.close(validation_fd)
        finally:
            os.close(ai_sow_fd)
    finally:
        os.close(root_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate source requirements")
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    data_path = project_root / ".ai-sow/data/analyze-requirement/requirements.json"
    schema_path = Path(__file__).resolve().parents[1] / "contracts/source-requirements.schema.json"
    diagnostics: list[dict[str, str]] = []
    try:
        data: dict[str, Any] = json.loads(data_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        diagnostics.append(diagnostic("INPUT_UNREADABLE", str(error), str(data_path)))
        data = {}
        schema = {}

    if not diagnostics:
        for error in sorted(Draft202012Validator(schema).iter_errors(data), key=lambda item: list(item.path)):
            path = "/" + "/".join(str(part) for part in error.path)
            diagnostics.append(diagnostic("SCHEMA_INVALID", error.message, path))

    if not diagnostics:
        id_fields = (
            ("sourceDocuments", "sourceDocumentId"),
            ("normalizedItems", "normalizedItemId"),
            ("epics", "epicId"),
            ("features", "featureId"),
        )
        ids = [item[field] for collection, field in id_fields for item in data[collection]]
        for item_id, count in Counter(ids).items():
            if count > 1:
                diagnostics.append(diagnostic("ID_DUPLICATE", f"duplicate ID: {item_id}"))

        source_document_ids = {
            item["sourceDocumentId"] for item in data["sourceDocuments"]
        }
        for source_document in data["sourceDocuments"]:
            raw_path = source_document["file"]
            try:
                resolved = (project_root / raw_path).resolve(strict=True)
                resolved.relative_to(project_root)
                if not resolved.is_file():
                    raise ValueError("not a file")
            except (OSError, ValueError):
                diagnostics.append(
                    diagnostic(
                        "SOURCE_DOCUMENT_PATH_INVALID",
                        f"registered source document is missing or outside project root: {raw_path}",
                    )
                )
                continue
            actual_hash = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if actual_hash != source_document["sha256"]:
                diagnostics.append(
                    diagnostic(
                        "SOURCE_DOCUMENT_HASH_MISMATCH",
                        f"source document hash mismatch: {source_document['sourceDocumentId']}",
                    )
                )

        for normalized_item in data["normalizedItems"]:
            reference = normalized_item["sourceDocumentId"]
            if reference not in source_document_ids:
                diagnostics.append(
                    diagnostic(
                        "SOURCE_DOCUMENT_REF_UNKNOWN",
                        f"unknown sourceDocumentId: {reference}",
                    )
                )

        normalized_ids = {item["normalizedItemId"] for item in data["normalizedItems"]}
        epic_ids = {item["epicId"] for item in data["epics"]}
        referenced_epics: set[str] = set()
        for collection in (data["epics"], data["features"]):
            for item in collection:
                for normalized_id in item["source"]["normalizedItemIds"]:
                    if normalized_id not in normalized_ids:
                        diagnostics.append(
                            diagnostic(
                                "NORMALIZED_ITEM_REF_UNKNOWN",
                                f"unknown normalizedItemId: {normalized_id}",
                            )
                        )
        for feature in data["features"]:
            referenced_epics.add(feature["epicId"])
            if feature["epicId"] not in epic_ids:
                diagnostics.append(
                    diagnostic("EPIC_REF_UNKNOWN", f"unknown epicId: {feature['epicId']}")
                )
        for epic_id in sorted(epic_ids - referenced_epics):
            diagnostics.append(
                diagnostic("EPIC_WITHOUT_FEATURE", f"Epic has no Feature: {epic_id}")
            )

    validation_path = project_root / ".ai-sow/validation/analyze-requirement.json"
    output_diagnostic = validation_output_diagnostic(project_root, validation_path)
    if output_diagnostic:
        diagnostics.append(output_diagnostic)
    else:
        report = {
            "subject": "analyze-requirement",
            "passed": not diagnostics,
            "diagnostics": diagnostics,
        }
        try:
            write_validation_report(
                project_root,
                validation_path,
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            )
        except OSError as error:
            diagnostics.append(
                diagnostic("OUTPUT_UNWRITABLE", str(error), str(validation_path))
            )
    result = {
        "outcome": "OK" if not diagnostics else "BLOCKED",
        "summary": "source requirements are valid" if not diagnostics else "source requirements are invalid",
        "outputs": [str(data_path), str(validation_path)],
        "diagnostics": diagnostics,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not diagnostics else 2


if __name__ == "__main__":
    sys.exit(main())
