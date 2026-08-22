from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


EXPECTED_TOPICS = (
    "SYSTEM_CONTEXT",
    "CAPABILITY",
    "APPLICATION",
    "INTEGRATION",
    "DATA",
    "PLATFORM",
    "SECURITY_COMPLIANCE",
    "OPERATIONS_QUALITY",
    "DELIVERY_CONSTRAINTS",
)

ALLOWED_TREATMENTS = {
    "IMPLEMENTED": {"CURRENT_BASELINE"},
    "PARTIAL": {"EXPECTED_BEFORE_START", "CARRY_FORWARD", "NEEDS_DECISION"},
    "NOT_IMPLEMENTED": {"EXPECTED_BEFORE_START", "CARRY_FORWARD", "NEEDS_DECISION"},
    "UNVERIFIED": {"NEEDS_DECISION"},
    "SUPERSEDED": {"EXCLUDE"},
}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")


def item(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def validation_output_diagnostic(
    root: Path,
    validation_path: Path,
) -> dict[str, str] | None:
    for path in (root / ".ai-sow", validation_path.parent, validation_path):
        if path.is_symlink():
            return item(
                "OUTPUT_PATH_UNSAFE",
                f"validation output path must not be a symlink: {path}",
            )
        try:
            path.resolve(strict=False).relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return item(
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
            or (previous_file_snapshot is not None and not _same_file(previous_file_snapshot, file_snapshot))
            or not _same_file(ai_sow_snapshot, _safe_directory_snapshot(ai_sow))
            or not _same_file(validation_snapshot, _safe_directory_snapshot(validation_path.parent))
        ):
            raise OSError("validation output path changed before write")
        os.ftruncate(file_descriptor, 0)
        payload = content.encode("utf-8")
        while payload:
            payload = payload[os.write(file_descriptor, payload) :]
        os.fsync(file_descriptor)
        if (
            not _same_file(ai_sow_snapshot, _safe_directory_snapshot(ai_sow))
            or not _same_file(validation_snapshot, _safe_directory_snapshot(validation_path.parent))
            or not _same_file(file_snapshot, _safe_regular_file_snapshot(validation_path))
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


def add_unknown_references(
    diagnostics: list[dict[str, str]],
    references: list[str],
    known: set[str],
    code: str,
    label: str,
) -> None:
    for reference in references:
        if reference not in known:
            diagnostics.append(item(code, f"unknown {label}: {reference}"))


def validate_project_input(project: object) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    if not isinstance(project, dict):
        return [item("PROJECT_SCHEMA_INVALID", "project must be an object")]
    required = {"projectId", "name", "pluginVersion", "sowStandardVersion"}
    missing = sorted(required - set(project))
    for field in missing:
        diagnostics.append(item("PROJECT_SCHEMA_INVALID", f"project is missing {field}"))
    if missing:
        return diagnostics
    unexpected = sorted(set(project) - required)
    for field in unexpected:
        diagnostics.append(item("PROJECT_SCHEMA_INVALID", f"project has unexpected {field}"))
    if not isinstance(project["projectId"], str) or not ID_PATTERN.fullmatch(project["projectId"]):
        diagnostics.append(item("PROJECT_SCHEMA_INVALID", "projectId is invalid"))
    if not isinstance(project["name"], str) or not project["name"]:
        diagnostics.append(item("PROJECT_SCHEMA_INVALID", "project name is invalid"))
    if project["pluginVersion"] != "0.1.0-beta.1":
        diagnostics.append(item("PROJECT_SCHEMA_INVALID", "project pluginVersion must be 0.1.0-beta.1"))
    if project["sowStandardVersion"] != "1.3":
        diagnostics.append(item("PROJECT_SCHEMA_INVALID", "project sowStandardVersion must be 1.3"))
    return diagnostics


def attest_analysis_scope_inputs(
    root: Path,
    scope: dict[str, Any],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    repository_ids: set[str] = set()
    prior_sow_ids: set[str] = set()
    for repository in scope["repositorySnapshots"]:
        if repository["repoId"] in repository_ids:
            diagnostics.append(item("INTAKE_ID_DUPLICATE", f"duplicate repository ID: {repository['repoId']}"))
        repository_ids.add(repository["repoId"])
        raw_path = repository["path"]
        try:
            resolved = (root / raw_path).resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_dir():
                raise ValueError("not a directory")
        except (OSError, ValueError):
            diagnostics.append(
                item(
                    "REGISTERED_PATH_INVALID",
                    f"analysis scope repository is missing or outside project root: {raw_path}",
                )
            )
    for prior_sow in scope["priorSowSnapshots"]:
        if prior_sow["priorSowId"] in prior_sow_ids:
            diagnostics.append(item("INTAKE_ID_DUPLICATE", f"duplicate prior SOW ID: {prior_sow['priorSowId']}"))
        prior_sow_ids.add(prior_sow["priorSowId"])
        raw_path = prior_sow["file"]
        try:
            resolved = (root / raw_path).resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_file():
                raise ValueError("not a file")
        except (OSError, ValueError):
            diagnostics.append(
                item(
                    "REGISTERED_PATH_INVALID",
                    f"analysis scope prior SOW is missing or outside project root: {raw_path}",
                )
            )
            continue
        actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if actual != prior_sow["sha256"]:
            diagnostics.append(
                item(
                    "PRIOR_SOW_HASH_MISMATCH",
                    f"analysis scope prior SOW hash mismatch: {prior_sow['priorSowId']}",
                )
            )
    return diagnostics


def validate_semantics(
    data: dict[str, Any],
    project: dict[str, Any],
    source: dict[str, Any],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    source_ids = {entry["featureId"] for entry in source.get("features", [])}
    collections = (
        ("items", "asIsItemId", "Item"),
        ("commitments", "commitmentId", "Commitment"),
        ("effectiveStartItems", "effectiveStartItemId", "Effective Start"),
        ("uncertainties", "uncertaintyId", "Uncertainty"),
        ("evidence", "evidenceId", "Evidence"),
    )
    registry: dict[str, str] = {}
    for collection, field, kind in collections:
        for entry in data[collection]:
            value = entry[field]
            if value in registry:
                diagnostics.append(
                    item(
                        "ID_DUPLICATE",
                        f"duplicate global ID {value}: {registry[value]} and {kind}",
                    )
                )
            else:
                registry[value] = kind

    item_ids = {entry["asIsItemId"] for entry in data["items"]}
    commitments_by_id = {entry["commitmentId"]: entry for entry in data["commitments"]}
    commitment_ids = set(commitments_by_id)
    start_ids = {entry["effectiveStartItemId"] for entry in data["effectiveStartItems"]}
    uncertainty_ids = {entry["uncertaintyId"] for entry in data["uncertainties"]}
    uncertainties_by_id = {
        entry["uncertaintyId"]: entry for entry in data["uncertainties"]
    }

    actual_topics = tuple(entry["topic"] for entry in data["topicAssessments"])
    if actual_topics != EXPECTED_TOPICS:
        diagnostics.append(
            item(
                "TOPIC_ASSESSMENTS_INVALID",
                "topicAssessments must contain each required topic exactly once in canonical order",
            )
        )
    for assessment in data["topicAssessments"]:
        references = assessment["uncertaintyIds"]
        add_unknown_references(
            diagnostics,
            references,
            uncertainty_ids,
            "UNCERTAINTY_REF_UNKNOWN",
            "uncertaintyId",
        )
        if assessment["status"] == "INSUFFICIENT_EVIDENCE" and not references:
            diagnostics.append(
                item(
                    "TOPIC_UNCERTAINTY_REQUIRED",
                    f"{assessment['topic']} requires an Uncertainty when evidence is insufficient",
                )
            )

    scope = data["analysisScope"]
    snapshot_repo_ids = [entry["repoId"] for entry in scope["repositorySnapshots"]]
    prior_sow_snapshots = scope["priorSowSnapshots"]
    if scope["mode"] == "GREENFIELD":
        if snapshot_repo_ids or prior_sow_snapshots:
            diagnostics.append(
                item(
                    "REPOSITORY_SNAPSHOT_MISMATCH",
                    "Greenfield analysis must not contain technical intake snapshots",
                )
            )
    elif not snapshot_repo_ids and not prior_sow_snapshots:
        diagnostics.append(
            item(
                "BROWNFIELD_INPUT_REQUIRED",
                "Brownfield analysis requires a repository or prior SOW snapshot",
            )
        )

    project_repo_id_set = set(snapshot_repo_ids)
    for current_item in data["items"]:
        add_unknown_references(
            diagnostics,
            current_item["repositoryIds"],
            project_repo_id_set,
            "REPOSITORY_REF_UNKNOWN",
            "repoId",
        )

    prior_sow_ids = {entry["priorSowId"] for entry in prior_sow_snapshots}
    for commitment in data["commitments"]:
        if commitment["priorSowId"] not in prior_sow_ids:
            diagnostics.append(
                item(
                    "PRIOR_SOW_REF_UNKNOWN",
                    f"unknown priorSowId: {commitment['priorSowId']}",
                )
            )
        status = commitment["implementationStatus"]
        treatment = commitment["treatment"]
        if treatment not in ALLOWED_TREATMENTS[status]:
            diagnostics.append(
                item(
                    "COMMITMENT_TREATMENT_INVALID",
                    f"{status} commitment cannot use treatment {treatment}",
                )
            )
        if status == "IMPLEMENTED" and not commitment["affectedItemIds"]:
            diagnostics.append(
                item(
                    "IMPLEMENTED_COMMITMENT_ITEM_REQUIRED",
                    f"implemented commitment {commitment['commitmentId']} must affect a current Item",
                )
            )
        if treatment == "CARRY_FORWARD" and not commitment["relatedFeatureIds"]:
            diagnostics.append(
                item(
                    "CARRY_FORWARD_FEATURE_REQUIRED",
                    f"carry-forward commitment must name a source Feature: {commitment['commitmentId']}",
                )
            )
        add_unknown_references(
            diagnostics,
            commitment["affectedItemIds"],
            item_ids,
            "ASIS_REF_UNKNOWN",
            "asIsItemId",
        )
        add_unknown_references(
            diagnostics,
            commitment["relatedFeatureIds"],
            source_ids,
            "FEATURE_REF_UNKNOWN",
            "source Feature",
        )

    for start in data["effectiveStartItems"]:
        if not start["sourceItemIds"] and not start["commitmentIds"]:
            diagnostics.append(
                item(
                    "EFFECTIVE_START_SOURCE_REQUIRED",
                    f"effective start requires a source Item or eligible commitment: {start['effectiveStartItemId']}",
                )
            )
        add_unknown_references(
            diagnostics,
            start["sourceItemIds"],
            item_ids,
            "ASIS_REF_UNKNOWN",
            "asIsItemId",
        )
        for reference in start["commitmentIds"]:
            commitment = commitments_by_id.get(reference)
            if commitment is None:
                diagnostics.append(
                    item("COMMITMENT_REF_UNKNOWN", f"unknown commitmentId: {reference}")
                )
            elif commitment["treatment"] != "EXPECTED_BEFORE_START":
                diagnostics.append(
                    item(
                        "EFFECTIVE_START_COMMITMENT_INELIGIBLE",
                        f"effective start may not use {commitment['treatment']} commitment: {reference}",
                    )
                )

    for uncertainty in data["uncertainties"]:
        add_unknown_references(
            diagnostics,
            uncertainty["relatedFeatureIds"],
            source_ids,
            "FEATURE_REF_UNKNOWN",
            "source Feature",
        )

    covered_ids = [entry["featureId"] for entry in data["coverage"]]
    for reference, count in Counter(covered_ids).items():
        if count > 1:
            diagnostics.append(item("COVERAGE_DUPLICATE", f"duplicate coverage: {reference}"))
        if reference not in source_ids:
            diagnostics.append(
                item("FEATURE_REF_UNKNOWN", f"unknown source Feature: {reference}")
            )
    for reference in sorted(source_ids - set(covered_ids)):
        diagnostics.append(item("COVERAGE_MISSING", f"missing coverage for: {reference}"))
    for coverage in data["coverage"]:
        add_unknown_references(
            diagnostics,
            coverage["effectiveStartItemIds"],
            start_ids,
            "EFFECTIVE_START_REF_UNKNOWN",
            "effectiveStartItemId",
        )
        add_unknown_references(
            diagnostics,
            coverage["commitmentIds"],
            commitment_ids,
            "COMMITMENT_REF_UNKNOWN",
            "commitmentId",
        )
        add_unknown_references(
            diagnostics,
            coverage["uncertaintyIds"],
            uncertainty_ids,
            "UNCERTAINTY_REF_UNKNOWN",
            "uncertaintyId",
        )
        for reference in coverage["commitmentIds"]:
            commitment = commitments_by_id.get(reference)
            if (
                commitment is not None
                and coverage["featureId"] not in commitment["relatedFeatureIds"]
            ):
                diagnostics.append(
                    item(
                        "COMMITMENT_COVERAGE_FEATURE_MISMATCH",
                        f"Coverage {coverage['featureId']} references unrelated commitment: {reference}",
                    )
                )

    coverage_by_feature = {
        coverage["featureId"]: coverage for coverage in data["coverage"]
    }
    for commitment in data["commitments"]:
        commitment_id = commitment["commitmentId"]
        for feature_id in commitment["relatedFeatureIds"]:
            coverage = coverage_by_feature.get(feature_id)
            if coverage is None or commitment_id not in coverage["commitmentIds"]:
                diagnostics.append(
                    item(
                        "COMMITMENT_COVERAGE_MISSING",
                        f"commitment {commitment_id} is missing from Coverage for: {feature_id}",
                    )
                )
                if commitment["treatment"] == "CARRY_FORWARD":
                    diagnostics.append(
                        item(
                            "CARRY_FORWARD_COVERAGE_MISSING",
                            f"carry-forward commitment is not represented in Coverage: {commitment_id}",
                        )
                    )
        if (
            commitment["implementationStatus"] == "UNVERIFIED"
            or commitment["treatment"] == "NEEDS_DECISION"
        ) and not any(
            commitment_id in coverage["commitmentIds"]
            and coverage["featureId"] in commitment["relatedFeatureIds"]
            and any(
                coverage["featureId"]
                in uncertainties_by_id[uncertainty_id]["relatedFeatureIds"]
                for uncertainty_id in coverage["uncertaintyIds"]
                if uncertainty_id in uncertainties_by_id
            )
            for coverage in data["coverage"]
        ):
            diagnostics.append(
                item(
                    "COMMITMENT_DECISION_CHAIN_MISSING",
                    f"decision-dependent commitment lacks linked Coverage uncertainty: {commitment_id}",
                )
            )

    supported_targets = item_ids | commitment_ids | start_ids | source_ids | uncertainty_ids
    supported_item_ids: set[str] = set()
    item_evidence_kinds: dict[str, set[str]] = defaultdict(set)
    for evidence in data["evidence"]:
        supported_item_ids.update(item_ids.intersection(evidence["supportsIds"]))
        for reference in item_ids.intersection(evidence["supportsIds"]):
            item_evidence_kinds[reference].add(evidence["kind"])
        add_unknown_references(
            diagnostics,
            evidence["supportsIds"],
            supported_targets,
            "EVIDENCE_REF_UNKNOWN",
            "supported ID",
        )
    for reference in sorted(item_ids - supported_item_ids):
        if scope["mode"] == "BROWNFIELD":
            diagnostics.append(
                item(
                    "BROWNFIELD_ITEM_EVIDENCE_MISSING",
                    f"Brownfield Item lacks supporting Evidence: {reference}",
                )
            )
        else:
            diagnostics.append(
                item(
                    "GREENFIELD_ITEM_EVIDENCE_MISSING",
                    f"Greenfield Item lacks supporting Evidence: {reference}",
                )
            )
    if scope["mode"] == "GREENFIELD":
        allowed_greenfield_kinds = {"DOCUMENT", "QUESTIONNAIRE"}
        for reference, kinds in sorted(item_evidence_kinds.items()):
            if not kinds.issubset(allowed_greenfield_kinds):
                diagnostics.append(
                    item(
                        "GREENFIELD_ITEM_EVIDENCE_INVALID",
                        f"Greenfield Item may use only DOCUMENT or QUESTIONNAIRE Evidence: {reference}",
                    )
                )

    return diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate As-Is handoff data")
    parser.add_argument("--project-root", required=True, type=Path)
    root = parser.parse_args().project_root.resolve()
    project_path = root / ".ai-sow/project.json"
    data_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    source_path = root / ".ai-sow/data/analyze-requirement/requirements.json"
    schema_path = Path(__file__).resolve().parents[1] / "contracts/asis.schema.json"
    diagnostics: list[dict[str, str]] = []
    try:
        project: dict[str, Any] = json.loads(project_path.read_text(encoding="utf-8"))
        data: dict[str, Any] = json.loads(data_path.read_text(encoding="utf-8"))
        source: dict[str, Any] = json.loads(source_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        diagnostics.append(item("INPUT_UNREADABLE", str(error)))
        project, data, source, schema = {}, {}, {}, {}

    if not diagnostics:
        diagnostics.extend(validate_project_input(project))

    if not diagnostics:
        for error in sorted(
            Draft202012Validator(schema).iter_errors(data),
            key=lambda value: list(value.path),
        ):
            diagnostics.append(item("SCHEMA_INVALID", error.message))

    if not diagnostics:
        diagnostics.extend(attest_analysis_scope_inputs(root, data["analysisScope"]))

    if not diagnostics:
        diagnostics.extend(validate_semantics(data, project, source))

    validation_path = root / ".ai-sow/validation/analyze-as-is.json"
    output_diagnostic = validation_output_diagnostic(root, validation_path)
    if output_diagnostic:
        diagnostics.append(output_diagnostic)
    else:
        report = {
            "subject": "analyze-as-is",
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
            diagnostics.append(item("OUTPUT_UNWRITABLE", str(error)))
    print(
        json.dumps(
            {
                "outcome": "OK" if not diagnostics else "BLOCKED",
                "summary": "As-Is data is valid" if not diagnostics else "As-Is data is invalid",
                "outputs": [str(data_path), str(validation_path)],
                "diagnostics": diagnostics,
            },
            ensure_ascii=False,
        )
    )
    return 0 if not diagnostics else 2


if __name__ == "__main__":
    sys.exit(main())
