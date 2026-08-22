from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.review_gates import validate_design_gates


DERIVED_RATIONALE_PATTERN = re.compile(
    r"^设计决策/Decision\s*[:：]\s*(?P<decision>[^；;\r\n]+)[；;]\s*"
    r"产生原因/Cause\s*[:：]\s*(?P<cause>[^；;\r\n]+)[；;]\s*"
    r"不交付影响/Non-delivery impact\s*[:：]\s*"
    r"(?P<category>流程/Process|接口/API|质量属性/Quality attribute|责任边界/Responsibility boundary)"
    r"\s*\|\s*(?P<target>[^|\r\n]+?)\s*->\s*(?P<impact>[^\r\n]+)$"
)
STABLE_ID_PATTERN = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")
GENERIC_IMPACT_TARGETS = {
    "业务",
    "功能",
    "模块",
    "系统",
    "business",
    "feature",
    "module",
    "system",
}
GENERIC_IMPACTS = {
    "会产生影响",
    "会受到影响",
    "功能不可用",
    "系统无法工作",
    "项目失败",
    "feature unavailable",
    "system will not work",
    "will cause impact",
}


def diag(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def normalized_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def significant_length(value: str) -> int:
    return len(re.sub(r"[^\w]+", "", value, flags=re.UNICODE))


def replace_entities(value: str, entities: list[str]) -> str:
    normalized = normalized_text(value)
    for entity in sorted(
        {normalized_text(entity) for entity in entities if entity},
        key=len,
        reverse=True,
    ):
        normalized = normalized.replace(entity, "<entity>")
    return normalized


def rationale_template_signature(
    feature: dict[str, Any],
    clauses: re.Match[str],
    decision_titles: dict[str, str],
) -> tuple[str, str, str, str]:
    provenance = feature["source"]
    entities = [
        feature["featureId"],
        feature["name"],
        *provenance["designDecisionIds"],
        *(decision_titles.get(reference, "") for reference in provenance["designDecisionIds"]),
    ]
    return (
        replace_entities(clauses.group("decision"), entities),
        replace_entities(clauses.group("cause"), entities),
        normalized_text(clauses.group("category")),
        replace_entities(clauses.group("impact"), entities),
    )


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate design and technical requirements")
    parser.add_argument("--project-root", required=True, type=Path)
    root = parser.parse_args().project_root.resolve()
    own = root / ".ai-sow/data/generate-design"
    paths = {
        "design": own / "design.json",
        "technical": own / "requirements.json",
        "source": root / ".ai-sow/data/analyze-requirement/requirements.json",
        "asis": root / ".ai-sow/data/analyze-as-is/asis.json",
        "review": root / ".ai-sow/reviews/generate-design.md",
    }
    skill_root = Path(__file__).resolve().parents[1]
    diagnostics: list[dict[str, str]] = []
    try:
        values: dict[str, dict[str, Any]] = {
            name: json.loads(paths[name].read_text(encoding="utf-8"))
            for name in ("design", "technical", "source", "asis")
        }
        review_text = paths["review"].read_text(encoding="utf-8")
        schemas = {
            "design": json.loads((skill_root / "contracts/design.schema.json").read_text()),
            "technical": json.loads((skill_root / "contracts/technical-requirements.schema.json").read_text()),
        }
    except (OSError, json.JSONDecodeError) as error:
        diagnostics.append(diag("INPUT_UNREADABLE", str(error)))
        values, schemas, review_text = {}, {}, ""

    if not diagnostics:
        for name in ("design", "technical"):
            for error in sorted(Draft202012Validator(schemas[name]).iter_errors(values[name]), key=lambda value: list(value.path)):
                diagnostics.append(diag("SCHEMA_INVALID", f"{name}: {error.message}"))

    if not diagnostics:
        design, technical, source, asis = (
            values[name] for name in ("design", "technical", "source", "asis")
        )
        design_item_ids = {entry["designItemId"] for entry in design["designItems"]}
        decision_ids = {entry["designDecisionId"] for entry in design["decisions"]}
        decision_titles = {
            entry["designDecisionId"]: entry["title"] for entry in design["decisions"]
        }
        start_ids = {entry["effectiveStartItemId"] for entry in asis.get("effectiveStartItems", [])}
        carry_forward_ids = {
            entry["commitmentId"]
            for entry in asis.get("commitments", [])
            if entry.get("treatment") == "CARRY_FORWARD"
        }
        carry_forward_feature_ids = {
            reference
            for entry in asis.get("commitments", [])
            if entry.get("commitmentId") in carry_forward_ids
            for reference in entry.get("relatedFeatureIds", [])
        } | {
            entry["featureId"]
            for entry in asis.get("coverage", [])
            if carry_forward_ids.intersection(entry.get("commitmentIds", []))
        }
        source_document_ids = {
            entry["sourceDocumentId"] for entry in source.get("sourceDocuments", [])
        }
        source_epic_ids = {entry["epicId"] for entry in source.get("epics", [])}
        source_feature_ids = {entry["featureId"] for entry in source.get("features", [])}
        technical_epic_ids = {entry["epicId"] for entry in technical["epics"]}
        technical_feature_ids = {entry["featureId"] for entry in technical["features"]}

        for epic in source.get("epics", []):
            if epic.get("type") != "BUSINESS":
                diagnostics.append(
                    diag(
                        "SOURCE_REQUIREMENT_TYPE_INVALID",
                        f"source Epic must be BUSINESS: {epic.get('epicId', '<unknown>')}",
                    )
                )

        all_ids = (
            [entry["epicId"] for entry in source.get("epics", [])]
            + [entry["featureId"] for entry in source.get("features", [])]
            + [entry["epicId"] for entry in technical["epics"]]
            + [entry["featureId"] for entry in technical["features"]]
            + [entry["designItemId"] for entry in design["designItems"]]
            + [entry["architectureDeltaId"] for entry in design["architectureDeltas"]]
            + [entry["designDecisionId"] for entry in design["decisions"]]
        )
        for value, count in Counter(all_ids).items():
            if count > 1:
                diagnostics.append(diag("ID_DUPLICATE", f"duplicate ID: {value}"))

        for delta in design["architectureDeltas"]:
            if delta["designItemId"] not in design_item_ids:
                diagnostics.append(diag("DESIGN_ITEM_REF_UNKNOWN", f"unknown designItemId: {delta['designItemId']}"))
            for reference in delta["effectiveStartItemIds"]:
                if reference not in start_ids:
                    diagnostics.append(diag("EFFECTIVE_START_REF_UNKNOWN", f"unknown effectiveStartItemId: {reference}"))
        for decision in design["decisions"]:
            for reference in decision["designItemIds"]:
                if reference not in design_item_ids:
                    diagnostics.append(diag("DESIGN_ITEM_REF_UNKNOWN", f"unknown designItemId: {reference}"))
            for reference in decision["effectiveStartItemIds"]:
                if reference not in start_ids:
                    diagnostics.append(diag("EFFECTIVE_START_REF_UNKNOWN", f"unknown effectiveStartItemId: {reference}"))
            for reference in decision["relatedFeatureIds"]:
                if reference not in source_feature_ids | technical_feature_ids:
                    diagnostics.append(diag("FEATURE_REF_UNKNOWN", f"unknown Feature: {reference}"))

        for requirement in [*technical["epics"], *technical["features"]]:
            provenance = requirement["source"]
            if provenance["type"] == "SOURCE_INPUT":
                for reference in provenance["sourceDocumentIds"]:
                    if reference not in source_document_ids:
                        diagnostics.append(
                            diag(
                                "SOURCE_DOCUMENT_REF_UNKNOWN",
                                f"unknown registered sourceDocumentId: {reference}",
                            )
                        )
            else:
                for reference in provenance["designDecisionIds"]:
                    if reference not in decision_ids:
                        diagnostics.append(diag("DESIGN_DECISION_REF_UNKNOWN", f"unknown designDecisionId: {reference}"))
                for reference in provenance["effectiveStartItemIds"]:
                    if reference not in start_ids:
                        diagnostics.append(diag("EFFECTIVE_START_REF_UNKNOWN", f"unknown effectiveStartItemId: {reference}"))
                for reference in provenance.get("relatedFeatureIds", []):
                    if reference not in source_feature_ids | technical_feature_ids:
                        diagnostics.append(diag("FEATURE_REF_UNKNOWN", f"unknown related Feature: {reference}"))

        referenced_epic_ids: set[str] = set()
        for feature in technical["features"]:
            referenced_epic_ids.add(feature["epicId"])
            if feature["epicId"] not in technical_epic_ids:
                diagnostics.append(
                    diag("EPIC_REF_UNKNOWN", f"unknown technical epicId: {feature['epicId']}")
                )
        for reference in sorted(technical_epic_ids - referenced_epic_ids):
            diagnostics.append(
                diag("EPIC_WITHOUT_FEATURE", f"technical Epic has no Feature: {reference}")
            )

        normalized_rationales: dict[str, str] = {}
        rationale_templates: dict[tuple[str, str, str, str], str] = {}
        for feature in technical["features"]:
            provenance = feature["source"]
            if provenance["type"] != "DESIGN_DERIVED":
                continue
            rationale = normalized_text(provenance["rationale"])
            previous = normalized_rationales.get(rationale)
            if previous is not None:
                diagnostics.append(
                    diag(
                        "DERIVED_RATIONALE_DUPLICATE",
                        f"Features {previous} and {feature['featureId']} use the same derived rationale",
                    )
                )
                continue
            normalized_rationales[rationale] = feature["featureId"]

            clauses = DERIVED_RATIONALE_PATTERN.fullmatch(provenance["rationale"])
            if clauses is None:
                continue
            decision_clause_ids = set(
                STABLE_ID_PATTERN.findall(normalized_text(clauses.group("decision")))
            )
            missing_decision_ids = [
                reference
                for reference in provenance["designDecisionIds"]
                if normalized_text(reference) not in decision_clause_ids
            ]
            if missing_decision_ids:
                diagnostics.append(
                    diag(
                        "DERIVED_RATIONALE_DECISION_REF_MISSING",
                        f"Feature {feature['featureId']} decision clause omits: "
                        + ", ".join(missing_decision_ids),
                    )
                )
            decision_detail = clauses.group("decision")
            for reference in provenance["designDecisionIds"]:
                decision_detail = decision_detail.replace(reference, "")
            if significant_length(decision_detail) < 8:
                diagnostics.append(
                    diag(
                        "DERIVED_RATIONALE_DECISION_GENERIC",
                        f"Feature {feature['featureId']} decision clause lacks a concrete decision",
                    )
                )
            if significant_length(clauses.group("cause")) < 12:
                diagnostics.append(
                    diag(
                        "DERIVED_RATIONALE_CAUSE_GENERIC",
                        f"Feature {feature['featureId']} cause clause lacks a concrete causal reason",
                    )
                )
            target = normalized_text(clauses.group("target"))
            impact = normalized_text(clauses.group("impact"))
            if (
                target in GENERIC_IMPACT_TARGETS
                or significant_length(target) < 3
                or impact in GENERIC_IMPACTS
                or significant_length(impact) < 8
            ):
                diagnostics.append(
                    diag(
                        "DERIVED_RATIONALE_IMPACT_GENERIC",
                        f"Feature {feature['featureId']} impact clause must name a concrete target and consequence",
                    )
                )

            signature = rationale_template_signature(
                feature,
                clauses,
                decision_titles,
            )
            template_owner = rationale_templates.get(signature)
            if template_owner is not None:
                diagnostics.append(
                    diag(
                        "DERIVED_RATIONALE_TEMPLATE_DUPLICATE",
                        f"Features {template_owner} and {feature['featureId']} use the same rationale template",
                    )
                )
            else:
                rationale_templates[signature] = feature["featureId"]

        required_scope = source_feature_ids | technical_feature_ids
        actual_scope = [entry["featureId"] for entry in design["scopeDecisions"]]
        for reference, count in Counter(actual_scope).items():
            if count > 1:
                diagnostics.append(diag("SCOPE_DUPLICATE", f"duplicate scope decision: {reference}"))
            if reference not in required_scope:
                diagnostics.append(diag("FEATURE_REF_UNKNOWN", f"unknown scoped Feature: {reference}"))
        for reference in sorted(required_scope - set(actual_scope)):
            diagnostics.append(diag("SCOPE_MISSING", f"missing scope decision: {reference}"))
        for scope in design["scopeDecisions"]:
            if (
                scope["decision"] == "FULLY_COVERED"
                and scope["featureId"] in carry_forward_feature_ids
            ):
                diagnostics.append(diag(
                    "CARRY_FORWARD_SCOPE_INVALID",
                    f"CARRY_FORWARD work cannot be FULLY_COVERED: {scope['featureId']}",
                ))
            for reference in scope["designItemIds"]:
                if reference not in design_item_ids:
                    diagnostics.append(diag("DESIGN_ITEM_REF_UNKNOWN", f"unknown designItemId: {reference}"))
            for reference in scope["effectiveStartItemIds"]:
                if reference not in start_ids:
                    diagnostics.append(diag("EFFECTIVE_START_REF_UNKNOWN", f"unknown effectiveStartItemId: {reference}"))

        diagnostics.extend(
            validate_design_gates(source, technical, design, asis, review_text)
        )

    validation_path = root / ".ai-sow/validation/generate-design.json"
    output_diagnostic = validation_output_diagnostic(root, validation_path)
    if output_diagnostic:
        diagnostics.append(output_diagnostic)
    else:
        report = {
            "subject": "generate-design",
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
        "summary": "design outputs are valid" if not diagnostics else "design outputs are invalid",
        "outputs": [str(paths["design"]), str(paths["technical"]), str(validation_path)],
        "diagnostics": diagnostics,
    }, ensure_ascii=False))
    return 0 if not diagnostics else 2


if __name__ == "__main__":
    sys.exit(main())
