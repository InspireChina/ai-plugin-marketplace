from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.review_gates import validate_design_gates


def diag(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def validation_output_diagnostic(
    root: Path,
    validation_path: Path,
) -> dict[str, str] | None:
    for path in (root / ".ai-sow", validation_path.parent, validation_path):
        if path.is_symlink():
            return diag(
                "OUTPUT_PATH_UNSAFE",
                f"validation output path must not be a symlink: {path}",
            )
        try:
            path.resolve(strict=False).relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return diag(
                "OUTPUT_PATH_UNSAFE",
                f"validation output path is outside project root: {path}",
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


def _write_validation_report_portable(project_root: Path, validation_path: Path, content: str) -> None:
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
        if not _same_file(file_snapshot, current_path_snapshot) or (previous_file_snapshot is not None and not _same_file(previous_file_snapshot, file_snapshot)) or not _same_file(ai_sow_snapshot, _safe_directory_snapshot(ai_sow)) or not _same_file(validation_snapshot, _safe_directory_snapshot(validation_path.parent)):
            raise OSError("validation output path changed before write")
        os.ftruncate(file_descriptor, 0)
        payload = content.encode("utf-8")
        while payload:
            payload = payload[os.write(file_descriptor, payload) :]
        os.fsync(file_descriptor)
        if not _same_file(ai_sow_snapshot, _safe_directory_snapshot(ai_sow)) or not _same_file(validation_snapshot, _safe_directory_snapshot(validation_path.parent)) or not _same_file(file_snapshot, _safe_regular_file_snapshot(validation_path)):
            raise OSError("validation output path changed during write")
    finally:
        os.close(file_descriptor)


def write_validation_report(project_root: Path, validation_path: Path, content: str) -> None:
    if os.name != "posix":
        _write_validation_report_portable(project_root, validation_path, content)
        return
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
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
                report_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
                report_fd = os.open(validation_path.name, report_flags, 0o666, dir_fd=validation_fd)
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


def validate_as_is_input(
    asis: dict[str, Any],
    source: dict[str, Any],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    collection_ids = {
        "items": "asIsItemId",
        "commitments": "commitmentId",
        "effectiveStartItems": "effectiveStartItemId",
        "uncertainties": "uncertaintyId",
        "evidence": "evidenceId",
    }
    collections: dict[str, list[Any]] = {}
    for collection in (
        "topicAssessments",
        "items",
        "commitments",
        "effectiveStartItems",
        "coverage",
        "uncertainties",
        "evidence",
    ):
        entries = asis.get(collection)
        if not isinstance(entries, list):
            diagnostics.append(diag("SHAPE_INVALID", f"{collection} must be an array"))
            collections[collection] = []
        else:
            collections[collection] = entries
    if diagnostics:
        return diagnostics

    known_ids: dict[str, set[str]] = {}
    for collection, id_field in collection_ids.items():
        known: set[str] = set()
        for index, entry in enumerate(collections[collection]):
            if not isinstance(entry, dict) or not isinstance(entry.get(id_field), str):
                diagnostics.append(
                    diag(
                        "SHAPE_INVALID",
                        f"{collection}[{index}].{id_field} must be a string",
                    )
                )
                continue
            known.add(entry[id_field])
        known_ids[collection] = known

    source_feature_ids = {
        entry["featureId"]
        for entry in source.get("features", [])
        if isinstance(entry, dict) and isinstance(entry.get("featureId"), str)
    }
    coverage_counts: Counter[str] = Counter()
    reference_fields = (
        ("effectiveStartItemIds", known_ids["effectiveStartItems"], "EFFECTIVE_START_REF_UNKNOWN"),
        ("commitmentIds", known_ids["commitments"], "COMMITMENT_REF_UNKNOWN"),
        ("uncertaintyIds", known_ids["uncertainties"], "UNCERTAINTY_REF_UNKNOWN"),
    )
    for index, coverage in enumerate(collections["coverage"]):
        if not isinstance(coverage, dict) or not isinstance(
            coverage.get("featureId"), str
        ):
            diagnostics.append(
                diag("SHAPE_INVALID", f"coverage[{index}].featureId must be a string")
            )
            continue
        feature_id = coverage["featureId"]
        if feature_id in source_feature_ids:
            coverage_counts[feature_id] += 1
        for field, known, code in reference_fields:
            references = coverage.get(field)
            if not isinstance(references, list):
                diagnostics.append(
                    diag("SHAPE_INVALID", f"coverage[{index}].{field} must be an array")
                )
                continue
            for reference in references:
                if not isinstance(reference, str):
                    diagnostics.append(
                        diag("SHAPE_INVALID", f"coverage[{index}].{field} must contain strings")
                    )
                elif reference not in known:
                    diagnostics.append(diag(code, f"unknown {field} reference: {reference}"))

    for feature_id in sorted(source_feature_ids):
        count = coverage_counts[feature_id]
        if count == 0:
            diagnostics.append(
                diag("COVERAGE_MISSING", f"missing Coverage for: {feature_id}")
            )
        elif count > 1:
            diagnostics.append(
                diag("COVERAGE_DUPLICATE", f"duplicate Coverage for: {feature_id}")
            )
    return diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate delivery Stories")
    parser.add_argument("--project-root", required=True, type=Path)
    root = parser.parse_args().project_root.resolve()
    paths = {
        "source": root / ".ai-sow/data/analyze-requirement/requirements.json",
        "asis": root / ".ai-sow/data/analyze-as-is/asis.json",
        "derived": root / ".ai-sow/data/generate-design/requirements.json",
        "design": root / ".ai-sow/data/generate-design/design.json",
        "delivery": root / ".ai-sow/data/generate-story/delivery.json",
    }
    schema_path = Path(__file__).resolve().parents[1] / "contracts/delivery.schema.json"
    review_path = root / ".ai-sow/reviews/generate-design.md"
    diagnostics: list[dict[str, str]] = []
    try:
        values: dict[str, dict[str, Any]] = {
            name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()
        }
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        review_text = review_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as error:
        diagnostics.append(diag("INPUT_UNREADABLE", str(error)))
        values, schema, review_text = {}, {}, ""

    if not diagnostics:
        for error in sorted(Draft202012Validator(schema).iter_errors(values["delivery"]), key=lambda value: list(value.path)):
            diagnostics.append(diag("SCHEMA_INVALID", error.message))

    if not diagnostics:
        diagnostics.extend(validate_as_is_input(values["asis"], values["source"]))

    if not diagnostics:
        diagnostics.extend(
            validate_design_gates(
                values["source"],
                values["derived"],
                values["design"],
                values["asis"],
                review_text,
            )
        )

    if not diagnostics:
        delivery = values["delivery"]
        known_features = {
            entry["featureId"]
            for name in ("source", "derived")
            for entry in values[name].get("features", [])
        }
        in_scope = {
            entry["featureId"]
            for entry in values["design"].get("scopeDecisions", [])
            if entry["decision"] == "IN_SCOPE"
        }
        gap_ids = {entry["gapId"] for entry in delivery["gaps"]}
        story_ids = {entry["storyId"] for entry in delivery["stories"]}
        assumption_ids = {entry["assumptionId"] for entry in delivery["assumptions"]}

        own_ids = [
            *[entry["gapId"] for entry in delivery["gaps"]],
            *[entry["storyId"] for entry in delivery["stories"]],
            *[entry["acceptanceCriterionId"] for entry in delivery["acceptanceCriteria"]],
            *[entry["integrationId"] for entry in delivery["integrations"]],
            *[entry["assumptionId"] for entry in delivery["assumptions"]],
        ]
        for value, count in Counter(own_ids).items():
            if count > 1:
                diagnostics.append(diag("ID_DUPLICATE", f"duplicate ID: {value}"))

        gaps_by_feature = Counter(entry["featureId"] for entry in delivery["gaps"])
        for gap in delivery["gaps"]:
            reference = gap["featureId"]
            if reference not in known_features:
                diagnostics.append(diag("FEATURE_REF_UNKNOWN", f"unknown Feature: {reference}"))
            elif reference not in in_scope:
                diagnostics.append(diag("GAP_OUT_OF_SCOPE", f"Gap targets a non-IN_SCOPE Feature: {reference}"))
        for reference in sorted(in_scope - set(gaps_by_feature)):
            diagnostics.append(diag("GAP_COVERAGE_MISSING", f"missing Gap for: {reference}"))

        stories_by_gap = Counter(entry["gapId"] for entry in delivery["stories"])
        for story in delivery["stories"]:
            if story["gapId"] not in gap_ids:
                diagnostics.append(diag("GAP_REF_UNKNOWN", f"unknown gapId: {story['gapId']}"))
        for reference in sorted(gap_ids - set(stories_by_gap)):
            diagnostics.append(diag("STORY_COVERAGE_MISSING", f"Gap has no Story: {reference}"))

        for integration in delivery["integrations"]:
            story_id = integration["storyId"]
            if story_id not in story_ids:
                diagnostics.append(
                    diag(
                        "INTEGRATION_STORY_REF_UNKNOWN",
                        f"unknown storyId: {story_id}",
                    )
                )

        sequences: dict[str, list[int]] = defaultdict(list)
        for criterion in delivery["acceptanceCriteria"]:
            reference = criterion["storyId"]
            if reference not in story_ids:
                diagnostics.append(diag("STORY_REF_UNKNOWN", f"unknown storyId: {reference}"))
            sequences[reference].append(criterion["sequence"])
        for reference in sorted(story_ids - set(sequences)):
            diagnostics.append(diag("AC_COVERAGE_MISSING", f"Story has no acceptance criterion: {reference}"))
        for reference, actual in sequences.items():
            if sorted(actual) != list(range(1, len(actual) + 1)):
                diagnostics.append(diag("AC_SEQUENCE_INVALID", f"non-contiguous AC sequence for: {reference}"))

        assumption_relation_counts = Counter()
        for relation in delivery["assumptionStories"]:
            if relation["assumptionId"] not in assumption_ids:
                diagnostics.append(diag("ASSUMPTION_REF_UNKNOWN", f"unknown assumptionId: {relation['assumptionId']}"))
            else:
                assumption_relation_counts[relation["assumptionId"]] += 1
            if relation["storyId"] not in story_ids:
                diagnostics.append(diag("STORY_REF_UNKNOWN", f"unknown storyId: {relation['storyId']}"))
        for reference in sorted(assumption_ids - set(assumption_relation_counts)):
            diagnostics.append(
                diag(
                    "ASSUMPTION_COVERAGE_MISSING",
                    f"Assumption has no Story relation: {reference}",
                )
            )

    validation_path = root / ".ai-sow/validation/generate-story.json"
    output_diagnostic = validation_output_diagnostic(root, validation_path)
    if output_diagnostic:
        diagnostics.append(output_diagnostic)
    else:
        report = {
            "subject": "generate-story",
            "passed": not diagnostics,
            "diagnostics": diagnostics,
        }
        try:
            write_validation_report(
                root,
                validation_path,
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            )
        except OSError as error:
            diagnostics.append(diag("OUTPUT_UNWRITABLE", str(error)))
    print(json.dumps({
        "outcome": "OK" if not diagnostics else "BLOCKED",
        "summary": "delivery data is valid" if not diagnostics else "delivery data is invalid",
        "outputs": [str(paths["delivery"]), str(validation_path)],
        "diagnostics": diagnostics,
    }, ensure_ascii=False))
    return 0 if not diagnostics else 2


if __name__ == "__main__":
    sys.exit(main())
