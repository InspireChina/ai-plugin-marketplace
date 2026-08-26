from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import (
    Artifact,
    OwnerContract,
    VALIDATOR_CONTRACT_VERSION,
    canonical_json_bytes,
    publish_no_change_owner,
    publish_owner,
    reconciliation_staging_failure,
    rebind_owner,
    sha256_bytes,
    validate_no_change_candidate,
)
from runtime.project_io import ProjectFiles, ProjectIOError


SUBJECT = "analyze-requirement"
PROJECT_PATH = ".ai-sow/project.json"
REVIEW_PATH = ".ai-sow/reviews/analyze-requirement.md"
STABLE_PATH = ".ai-sow/data/analyze-requirement/requirements.json"
VALIDATION_PATH = ".ai-sow/validation/analyze-requirement.json"
QUESTIONNAIRE_PATH = ".ai-sow/reviews/analyze-requirement-questionnaire.md"
PACKET_PATH = ".ai-sow/work/analyze-requirement/review-packet.json"
RISK_SUMMARY_PATH = ".ai-sow/work/analyze-requirement/risk-summary.md"
REVIEWER_PATH = ".ai-sow/work/analyze-requirement/reviewer.json"
APPROVAL_PATH = ".ai-sow/work/analyze-requirement/approval.json"
SOURCE_DISPOSITION_PATH = ".ai-sow/work/analyze-requirement/source-disposition.json"
CONTEXT_MANIFEST_PATH = ".ai-sow/work/analyze-requirement/context/manifest.json"
CONTEXT_FRAGMENT_SPECS = (
    ("sourceIndex", ".ai-sow/work/analyze-requirement/context/source-index.json"),
    ("sourceDisposition", ".ai-sow/work/analyze-requirement/context/source-disposition.json"),
    ("questionnaire", ".ai-sow/work/analyze-requirement/context/questionnaire.json"),
)
CONTEXT_ALGORITHM = "ai-sow-analyze-requirement-context-v2"
REVIEW_PACKET_ALGORITHM = "ai-sow-owner-review-packet-v1"
REVIEWER_ALGORITHM = "ai-sow-owner-reviewer-v1"
APPROVAL_ALGORITHM = "ai-sow-owner-approval-v1"
SCHEMA_ID = "urn:ai-sow:analyze-requirement:source-requirements:0.1"
REQUIRED_REVIEW_SECTIONS = (
    "来源与归一化",
    "来源处置",
    "Epic 与 Feature",
    "范围边界",
    "问卷状态",
    "稳定 ID 映射",
    "输入充分性",
    "审查与批准",
)
QUESTIONNAIRE_FIELDS = (
    "Question ID",
    "Type",
    "Source",
    "Gap or conflict",
    "Business impact",
    "Options",
    "Recommendation",
    "Rationale",
    "Answer",
    "Status",
    "Blocking",
    "Decision date",
    "Decision evidence",
    "Disposition",
)
QUESTIONNAIRE_TYPES = {"GAP", "CONFLICT", "AMBIGUITY"}
GENERIC_DECISION_EVIDENCE = {"已批准", "已确认", "同意", "用户已批准", "用户已确认"}
CONTRACT = OwnerContract(
    subject=SUBJECT,
    contract_ids=(SCHEMA_ID,),
    validation_path=VALIDATION_PATH,
    reviews=(("approvedReview", REVIEW_PATH),),
    outputs=(("requirements", STABLE_PATH),),
)


def diag(code: str, message: str, path: str = "") -> dict[str, object]:
    value: dict[str, object] = {"code": code, "message": message}
    if path:
        value["path"] = path
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and publish BUSINESS requirements")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    parser.add_argument(
        "--mode",
        required=True,
        choices=(
            "check",
            "review",
            "write-reviewer",
            "write-approval",
            "publish-approved",
            "publish",
            "rebind",
        ),
    )
    parser.add_argument("--review-path", default=REVIEW_PATH)
    parser.add_argument(
        "--candidate",
        default=".ai-sow/work/analyze-requirement/requirements.candidate.json",
    )
    parser.add_argument("--packet-path", default=PACKET_PATH)
    parser.add_argument("--risk-summary-path", default=RISK_SUMMARY_PATH)
    parser.add_argument("--reviewer-path", default=REVIEWER_PATH)
    parser.add_argument("--approval-path", default=APPROVAL_PATH)
    parser.add_argument("--packet-sha256")
    return parser.parse_args()


def write_reviewer(args: argparse.Namespace) -> int:
    diagnostics: list[dict[str, object]] = []
    if args.staging_root is not None:
        diagnostics.append(
            diag("REVIEWER_STAGING_UNSUPPORTED", "write-reviewer does not accept --staging-root")
        )
    if args.reviewer_path != REVIEWER_PATH:
        diagnostics.append(
            diag("REVIEWER_PATH_INVALID", f"write-reviewer must use {REVIEWER_PATH}")
        )
    if not isinstance(args.packet_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", args.packet_sha256) is None:
        diagnostics.append(
            diag(
                "PACKET_SHA256_INVALID",
                "--packet-sha256 must be exactly 64 lowercase hexadecimal characters",
            )
        )
    if not diagnostics:
        try:
            files = ProjectFiles.open(args.project_root)
            files.write_atomic(
                REVIEWER_PATH,
                canonical_json_bytes(
                    {
                        "algorithm": REVIEWER_ALGORITHM,
                        "decision": "PASS",
                        "owner": SUBJECT,
                        "packetSha256": args.packet_sha256,
                    }
                ),
            )
        except (ProjectIOError, OSError) as error:
            diagnostics.append(diag(getattr(error, "code", "REVIEWER_WRITE_BLOCKED"), str(error)))
    result: dict[str, object] = {
        "outcome": "BLOCKED" if diagnostics else "OK",
        "summary": (
            f"{SUBJECT} reviewer sidecar is invalid"
            if diagnostics
            else f"{SUBJECT} reviewer sidecar is ready"
        ),
        "diagnostics": diagnostics,
        "outputs": [] if diagnostics else [REVIEWER_PATH],
    }
    if not diagnostics:
        result["packetSha256"] = args.packet_sha256
    print(json.dumps(result, ensure_ascii=False))
    return 2 if diagnostics else 0


def write_approval(args: argparse.Namespace) -> int:
    diagnostics: list[dict[str, object]] = []
    if args.staging_root is not None:
        diagnostics.append(
            diag("APPROVAL_STAGING_UNSUPPORTED", "write-approval does not accept --staging-root")
        )
    if args.approval_path != APPROVAL_PATH:
        diagnostics.append(
            diag("APPROVAL_PATH_INVALID", f"write-approval must use {APPROVAL_PATH}")
        )
    if not isinstance(args.packet_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", args.packet_sha256) is None:
        diagnostics.append(
            diag(
                "PACKET_SHA256_INVALID",
                "--packet-sha256 must be exactly 64 lowercase hexadecimal characters",
            )
        )
    if not diagnostics:
        try:
            files = ProjectFiles.open(args.project_root)
            files.write_atomic(
                APPROVAL_PATH,
                canonical_json_bytes(
                    {
                        "algorithm": APPROVAL_ALGORITHM,
                        "decision": "APPROVED",
                        "owner": SUBJECT,
                        "packetSha256": args.packet_sha256,
                    }
                ),
            )
        except (ProjectIOError, OSError) as error:
            diagnostics.append(diag(getattr(error, "code", "APPROVAL_WRITE_BLOCKED"), str(error)))
    result: dict[str, object] = {
        "outcome": "BLOCKED" if diagnostics else "OK",
        "summary": (
            f"{SUBJECT} approval sidecar is invalid"
            if diagnostics
            else f"{SUBJECT} approval sidecar is ready"
        ),
        "diagnostics": diagnostics,
        "outputs": [] if diagnostics else [APPROVAL_PATH],
    }
    if not diagnostics:
        result["packetSha256"] = args.packet_sha256
    print(json.dumps(result, ensure_ascii=False))
    return 2 if diagnostics else 0


def validate_review_path(mode: str, review_path: str) -> list[dict[str, object]]:
    if review_path == REVIEW_PATH:
        return []
    if mode not in {"check", "review", "publish-approved"}:
        return [
            diag(
                "REVIEW_PATH_MODE_INVALID",
                "--review-path override is allowed only in check, review, or publish-approved mode",
                review_path,
            )
        ]
    parts = tuple(review_path.split("/"))
    if (
        not review_path
        or "\\" in review_path
        or review_path.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or (parts and parts[0].endswith(":"))
    ):
        return [
            diag(
                "REVIEW_PATH_INVALID",
                "--review-path must be a POSIX project-relative path without traversal",
                review_path,
            )
        ]
    return []


def stable_ids(data: dict[str, Any]) -> list[str]:
    return [
        *(item["sourceDocumentId"] for item in data["sourceDocuments"]),
        *(item["normalizedItemId"] for item in data["normalizedItems"]),
        *(item["epicId"] for item in data["epics"]),
        *(item["featureId"] for item in data["features"]),
    ]


def declaration(text: str, label: str) -> list[str]:
    return re.findall(rf"(?m)^{re.escape(label)}\s*:\s*(.+?)\s*$", text)


def declares_no_change(files: ProjectFiles, review_path: str) -> bool:
    try:
        text = files.read_bytes(review_path).decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError):
        return False
    return declaration(text, "Impact") == ["NO_CHANGE"]


def parse_questionnaire(text: str) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    records: list[dict[str, str]] = []
    duplicates: list[tuple[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 2 or cells[0] not in QUESTIONNAIRE_FIELDS:
            continue
        field, value = cells
        if field == "Question ID" and current:
            records.append(current)
            current = {}
        if field in current:
            duplicates.append((current.get("Question ID", value if field == "Question ID" else "unknown"), field))
        current[field] = value
    if current:
        records.append(current)
    return records, duplicates


def current_questionnaire_declaration(files: ProjectFiles) -> str:
    try:
        files.resolve(QUESTIONNAIRE_PATH)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return "NOT_REQUIRED"
        raise
    return QUESTIONNAIRE_PATH


def validate_questionnaire(
    files: ProjectFiles,
    questionnaire: str,
    known_business_ids: set[str],
    *,
    review_path: str,
) -> tuple[list[dict[str, object]], Artifact | None]:
    diagnostics: list[dict[str, object]] = []
    if questionnaire == "NOT_REQUIRED":
        try:
            files.resolve(QUESTIONNAIRE_PATH)
        except ProjectIOError as error:
            if error.code != "PROJECT_PATH_MISSING":
                diagnostics.append(
                    diag(
                        "QUESTIONNAIRE_PRESENCE_CONFLICT",
                        "Questionnaire: NOT_REQUIRED conflicts with an unsafe or invalid questionnaire path",
                        QUESTIONNAIRE_PATH,
                    )
                )
        else:
            diagnostics.append(
                diag(
                    "QUESTIONNAIRE_PRESENCE_CONFLICT",
                    "Questionnaire: NOT_REQUIRED conflicts with an existing questionnaire file",
                    QUESTIONNAIRE_PATH,
                )
            )
        payload = canonical_json_bytes({"declaration": "NOT_REQUIRED"})
        return diagnostics, Artifact(
            "questionnaire",
            "QUESTIONNAIRE_PRESENCE",
            "questionnaire:NOT_REQUIRED",
            sha256_bytes(payload),
        )
    if questionnaire != QUESTIONNAIRE_PATH:
        return [
            diag(
                "QUESTIONNAIRE_DECLARATION_INVALID",
                "Questionnaire must be NOT_REQUIRED or the fixed project-relative path",
                review_path,
            )
        ], None
    try:
        payload = files.read_bytes(QUESTIONNAIRE_PATH)
        text = payload.decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError):
        return [
            diag(
                "QUESTIONNAIRE_MISSING",
                "declared requirement questionnaire is unavailable",
                QUESTIONNAIRE_PATH,
            )
        ], None

    records, duplicate_fields = parse_questionnaire(text)
    if not records:
        diagnostics.append(
            diag("QUESTIONNAIRE_INVALID", "questionnaire contains no question records", QUESTIONNAIRE_PATH)
        )
    for question_id, field in duplicate_fields:
        diagnostics.append(
            diag(
                "QUESTIONNAIRE_FIELD_DUPLICATE",
                f"{question_id} repeats field: {field}",
                QUESTIONNAIRE_PATH,
            )
        )
    question_ids = [record.get("Question ID", "") for record in records]
    for question_id, count in Counter(question_ids).items():
        if not question_id or count > 1:
            diagnostics.append(
                diag("QUESTIONNAIRE_ID_INVALID", "question IDs must be non-empty and unique", QUESTIONNAIRE_PATH)
            )
            break
    for record in records:
        question_id = record.get("Question ID", "unknown")
        missing = [field for field in QUESTIONNAIRE_FIELDS if not record.get(field, "").strip()]
        if missing:
            diagnostics.append(
                diag(
                    "QUESTIONNAIRE_FIELD_MISSING",
                    f"{question_id} missing fields: {', '.join(missing)}",
                    QUESTIONNAIRE_PATH,
                )
            )
            continue
        status = record["Status"]
        question_type = record["Type"]
        blocking_match = re.fullmatch(r"(YES|NO)\s*[:：]\s*(\S.*)", record["Blocking"])
        blocking = blocking_match.group(1) if blocking_match else ""
        disposition = record["Disposition"]
        if question_type not in QUESTIONNAIRE_TYPES:
            diagnostics.append(
                diag("QUESTIONNAIRE_TYPE_INVALID", f"{question_id} has invalid Type", QUESTIONNAIRE_PATH)
            )
        if record["Decision evidence"].strip() in GENERIC_DECISION_EVIDENCE:
            diagnostics.append(
                diag(
                    "QUESTIONNAIRE_DECISION_EVIDENCE_GENERIC",
                    f"{question_id} has generic Decision evidence",
                    QUESTIONNAIRE_PATH,
                )
            )
        if status in {"OPEN", "ANSWERED"} or status not in {"CLOSED", "APPROVED_DEFAULT"}:
            diagnostics.append(
                diag("QUESTIONNAIRE_NOT_FINAL", f"{question_id} is not in a handoff terminal state", QUESTIONNAIRE_PATH)
            )
            continue
        if blocking_match is None:
            diagnostics.append(
                diag(
                    "QUESTIONNAIRE_BLOCKING_INVALID",
                    f"{question_id} Blocking must be YES or NO followed by a non-empty rationale",
                    QUESTIONNAIRE_PATH,
                )
            )
        if status == "APPROVED_DEFAULT":
            if blocking == "YES":
                diagnostics.append(
                    diag(
                        "QUESTIONNAIRE_BLOCKING_DEFAULT",
                        f"{question_id} is blocking and cannot use APPROVED_DEFAULT",
                        QUESTIONNAIRE_PATH,
                    )
                )
            if disposition != "ASSUMPTION_CANDIDATE":
                diagnostics.append(
                    diag(
                        "QUESTIONNAIRE_DEFAULT_DISPOSITION_INVALID",
                        f"{question_id} approved default must become ASSUMPTION_CANDIDATE",
                        QUESTIONNAIRE_PATH,
                    )
                )
        else:
            if disposition.startswith("INCORPORATED_BUSINESS:"):
                target = disposition.split(":", 1)[1]
                if target not in known_business_ids:
                    diagnostics.append(
                        diag(
                            "QUESTIONNAIRE_BUSINESS_REF_UNKNOWN",
                            f"{question_id} references unknown approved BUSINESS ID: {target}",
                            QUESTIONNAIRE_PATH,
                        )
                    )
            elif disposition != "NO_CHANGE":
                diagnostics.append(
                    diag(
                        "QUESTIONNAIRE_CLOSED_DISPOSITION_INVALID",
                        f"{question_id} CLOSED disposition is invalid",
                        QUESTIONNAIRE_PATH,
                    )
                )
    artifact = Artifact(
        "questionnaire",
        "QUESTIONNAIRE_PRESENCE",
        f"questionnaire:{QUESTIONNAIRE_PATH}",
        sha256_bytes(payload),
    )
    return diagnostics, artifact


def validate_review(
    files: ProjectFiles,
    data: dict[str, Any],
    *,
    require_no_change: bool,
    review_path: str,
) -> tuple[list[dict[str, object]], Artifact | None]:
    try:
        text = files.read_bytes(review_path).decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError):
        return [diag("REVIEW_MISSING", "approved requirement review is unavailable", review_path)], None
    diagnostics: list[dict[str, object]] = []
    for section in REQUIRED_REVIEW_SECTIONS:
        if len(re.findall(rf"(?m)^## {re.escape(section)}\s*$", text)) != 1:
            diagnostics.append(
                diag("REVIEW_SECTION_INVALID", f"review must contain exactly one section: {section}", review_path)
            )

    questionnaires = declaration(text, "Questionnaire")
    if len(questionnaires) != 1:
        diagnostics.append(
            diag("QUESTIONNAIRE_DECLARATION_INVALID", "review must declare Questionnaire exactly once", review_path)
        )
        questionnaire_artifact = None
    else:
        questionnaire_diagnostics, questionnaire_artifact = validate_questionnaire(
            files,
            questionnaires[0],
            {item["epicId"] for item in data["epics"]}
            | {item["featureId"] for item in data["features"]},
            review_path=review_path,
        )
        diagnostics.extend(questionnaire_diagnostics)

    id_declarations = declaration(text, "Stable IDs")
    if len(id_declarations) != 1:
        diagnostics.append(diag("REVIEW_ID_SET_MISMATCH", "review must declare Stable IDs exactly once", review_path))
    else:
        declared_ids = [item for item in re.split(r"[,，、;；\s]+", id_declarations[0]) if item]
        if declared_ids != stable_ids(data):
            diagnostics.append(
                diag("REVIEW_ID_SET_MISMATCH", "review Stable IDs do not match candidate output", review_path)
            )
    if declaration(text, "Reviewer") != ["PASS"]:
        diagnostics.append(diag("REVIEW_NOT_PASSED", "Reviewer must be PASS", review_path))
    if declaration(text, "User Approval") != ["APPROVED"]:
        diagnostics.append(diag("USER_APPROVAL_MISSING", "User Approval must be APPROVED", review_path))
    impacts = declaration(text, "Impact")
    if require_no_change and impacts != ["NO_CHANGE"]:
        diagnostics.append(diag("REVIEW_NO_CHANGE_MISSING", "NO_CHANGE 发布或 rebind 要求 review 声明 Impact: NO_CHANGE", review_path))
    elif not require_no_change and "NO_CHANGE" in impacts:
        diagnostics.append(
            diag(
                "REVIEW_NO_CHANGE_MODE_INVALID",
                "Impact: NO_CHANGE 仅允许用于 NO_CHANGE 发布或 rebind",
                review_path,
            )
        )
    elif not require_no_change and impacts not in ([], ["CHANGED"]):
        diagnostics.append(diag("REVIEW_IMPACT_INVALID", "review Impact declaration is invalid", review_path))
    return diagnostics, questionnaire_artifact


def validate_business(
    files: ProjectFiles,
    data: dict[str, Any],
) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    all_ids = stable_ids(data)
    for item_id, count in Counter(all_ids).items():
        if count > 1:
            diagnostics.append(diag("ID_DUPLICATE", f"duplicate stable ID: {item_id}"))

    source_ids = {item["sourceDocumentId"] for item in data["sourceDocuments"]}
    for source in data["sourceDocuments"]:
        relative = source["file"]
        try:
            actual = sha256_bytes(files.read_bytes(relative))
        except ProjectIOError:
            diagnostics.append(
                diag("SOURCE_DOCUMENT_MISSING", f"registered source is missing: {source['sourceDocumentId']}", relative)
            )
            continue
        if actual != source["sha256"]:
            diagnostics.append(
                diag(
                    "SOURCE_DOCUMENT_HASH_MISMATCH",
                    f"registered source hash changed: {source['sourceDocumentId']}",
                    relative,
                )
            )

    normalized_ids = {item["normalizedItemId"] for item in data["normalizedItems"]}
    for item in data["normalizedItems"]:
        if item["sourceDocumentId"] not in source_ids:
            diagnostics.append(
                diag("SOURCE_DOCUMENT_REF_UNKNOWN", f"unknown sourceDocumentId: {item['sourceDocumentId']}")
            )
    epic_ids = {item["epicId"] for item in data["epics"]}
    referenced_epics: set[str] = set()
    referenced_normalized: set[str] = set()
    for item in [*data["epics"], *data["features"]]:
        for normalized_id in item["source"]["normalizedItemIds"]:
            referenced_normalized.add(normalized_id)
            if normalized_id not in normalized_ids:
                diagnostics.append(
                    diag("NORMALIZED_ITEM_REF_UNKNOWN", f"unknown normalizedItemId: {normalized_id}")
                )
    for feature in data["features"]:
        referenced_epics.add(feature["epicId"])
        if feature["epicId"] not in epic_ids:
            diagnostics.append(diag("EPIC_REF_UNKNOWN", f"unknown epicId: {feature['epicId']}"))
    for epic_id in sorted(epic_ids - referenced_epics):
        diagnostics.append(diag("EPIC_WITHOUT_FEATURE", f"Epic has no Feature: {epic_id}"))
    for normalized_id in sorted(normalized_ids - referenced_normalized):
        diagnostics.append(diag("NORMALIZED_ITEM_UNUSED", f"normalized item is not used: {normalized_id}"))
    return diagnostics


def load_source_disposition(
    files: ProjectFiles,
    data: dict[str, Any],
    *,
    path: str = SOURCE_DISPOSITION_PATH,
) -> tuple[dict[str, Any] | None, list[dict[str, object]]]:
    try:
        value = files.read_json(path)
    except ProjectIOError:
        return None, [
            diag(
                "SOURCE_DISPOSITION_MISSING",
                "work-only source disposition inventory is unavailable",
                path,
            )
        ]
    if not isinstance(value, dict):
        return None, [
            diag(
                "SOURCE_DISPOSITION_INVALID",
                "source disposition inventory must be a JSON object",
                path,
            )
        ]

    schema_path = Path(__file__).resolve().parents[1] / "contracts/source-disposition.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    diagnostics = [
        diag(
            "SOURCE_DISPOSITION_INVALID",
            error.message,
            path + "/" + "/".join(str(part) for part in error.path),
        )
        for error in sorted(
            Draft202012Validator(schema).iter_errors(value),
            key=lambda item: list(item.path),
        )
    ]
    if diagnostics:
        return None, diagnostics

    items = value["items"]
    source_ids = {item["sourceDocumentId"] for item in data["sourceDocuments"]}
    normalized_ids = {item["normalizedItemId"] for item in data["normalizedItems"]}
    epic_ids = {item["epicId"] for item in data["epics"]}
    feature_ids = {item["featureId"] for item in data["features"]}
    business_ids = normalized_ids | epic_ids | feature_ids
    disposition_ids = [item["dispositionId"] for item in items]
    for disposition_id, count in Counter(disposition_ids).items():
        if count > 1:
            diagnostics.append(
                diag(
                    "SOURCE_DISPOSITION_ID_DUPLICATE",
                    f"duplicate source disposition ID: {disposition_id}",
                    path,
                )
            )

    covered_sources: set[str] = set()
    covered_normalized: set[str] = set()
    for item in items:
        source_id = item["sourceDocumentId"]
        if source_id not in source_ids:
            diagnostics.append(
                diag(
                    "SOURCE_DISPOSITION_SOURCE_UNKNOWN",
                    f"unknown sourceDocumentId: {source_id}",
                    path,
                )
            )
        else:
            covered_sources.add(source_id)
        target_ids = set(item["targetIds"])
        for target_id in sorted(target_ids - business_ids):
            diagnostics.append(
                diag(
                    "SOURCE_DISPOSITION_TARGET_UNKNOWN",
                    f"unknown BUSINESS target ID: {target_id}",
                    path,
                )
            )
        if item["disposition"] == "BUSINESS":
            normalized_targets = target_ids & normalized_ids
            if not normalized_targets:
                diagnostics.append(
                    diag(
                        "SOURCE_DISPOSITION_BUSINESS_TARGET_INVALID",
                        "BUSINESS disposition must target at least one normalized item",
                        path,
                    )
                )
            covered_normalized.update(normalized_targets)
        elif item["disposition"] == "SCOPE_BOUNDARY":
            invalid_targets = target_ids - (epic_ids | feature_ids)
            if invalid_targets:
                diagnostics.append(
                    diag(
                        "SOURCE_DISPOSITION_BOUNDARY_TARGET_INVALID",
                        "SCOPE_BOUNDARY may target only BUSINESS Epic or Feature IDs",
                        path,
                    )
                )

    for source_id in sorted(source_ids - covered_sources):
        diagnostics.append(
            diag(
                "SOURCE_DISPOSITION_DOCUMENT_UNCOVERED",
                f"registered source has no disposition items: {source_id}",
                path,
            )
        )
    for normalized_id in sorted(normalized_ids - covered_normalized):
        diagnostics.append(
            diag(
                "SOURCE_DISPOSITION_BUSINESS_UNCOVERED",
                f"normalized BUSINESS item has no BUSINESS disposition: {normalized_id}",
                path,
            )
        )
    return (value if not diagnostics else None), diagnostics


def owner_inputs(
    files: ProjectFiles,
    data: dict[str, Any],
    questionnaire: Artifact | None,
) -> tuple[list[dict[str, object]], tuple[Artifact, ...]]:
    diagnostics: list[dict[str, object]] = []
    inputs: list[Artifact] = []
    try:
        project_payload = files.read_bytes(PROJECT_PATH)
        inputs.append(Artifact("project", "FILE", PROJECT_PATH, sha256_bytes(project_payload)))
    except ProjectIOError:
        diagnostics.append(diag("PROJECT_INPUT_MISSING", "project metadata is unavailable", PROJECT_PATH))
    for source in data["sourceDocuments"]:
        try:
            source_payload = files.read_bytes(source["file"])
        except ProjectIOError:
            continue
        inputs.append(
            Artifact(
                f"source:{source['sourceDocumentId']}",
                "FILE",
                source["file"],
                sha256_bytes(source_payload),
            )
        )
    if questionnaire is not None:
        inputs.append(questionnaire)
    return diagnostics, tuple(inputs)


def input_entry(artifact: Artifact) -> dict[str, object]:
    return {
        "name": artifact.name,
        "kind": artifact.kind,
        "path": artifact.locator,
        "sha256": artifact.sha256,
    }


def load_and_validate(
    files: ProjectFiles,
    relative_path: str,
    schema: dict[str, Any],
    *,
    require_no_change: bool,
    review_path: str,
) -> tuple[bytes | None, dict[str, Any] | None, tuple[Artifact, ...], list[dict[str, object]]]:
    diagnostics: list[dict[str, object]] = []
    try:
        payload = files.read_bytes(relative_path)
        data = json.loads(payload.decode("utf-8"))
    except (ProjectIOError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None, (), [diag("CANDIDATE_UNREADABLE", "requirements JSON is unavailable or invalid", relative_path)]
    schema_errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda item: list(item.path))
    for error in schema_errors:
        diagnostics.append(
            diag("SCHEMA_INVALID", error.message, "/" + "/".join(str(part) for part in error.path))
        )
    if diagnostics or not isinstance(data, dict):
        return payload, None, (), diagnostics

    diagnostics.extend(validate_business(files, data))
    review_diagnostics, questionnaire = validate_review(
        files,
        data,
        require_no_change=require_no_change,
        review_path=review_path,
    )
    diagnostics.extend(review_diagnostics)
    input_diagnostics, inputs = owner_inputs(files, data, questionnaire)
    diagnostics.extend(input_diagnostics)
    return payload, data, inputs, diagnostics


def file_entry(name: str, path: str, payload: bytes) -> dict[str, object]:
    return {"name": name, "path": path, "sha256": sha256_bytes(payload)}


def canonical_object(
    files: ProjectFiles,
    path: str,
    *,
    missing_code: str,
    invalid_code: str,
) -> tuple[dict[str, object] | None, bytes | None, list[dict[str, object]]]:
    try:
        payload = files.read_bytes(path)
    except ProjectIOError:
        return None, None, [diag(missing_code, f"required canonical JSON is unavailable: {path}", path)]
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, [diag(invalid_code, f"canonical JSON is invalid: {path}", path)]
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        return None, None, [diag(invalid_code, f"canonical JSON bytes are invalid: {path}", path)]
    return value, payload, []


def context_packet_entry(
    files: ProjectFiles,
    inputs: tuple[Artifact, ...],
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    manifest, manifest_payload, diagnostics = canonical_object(
        files,
        CONTEXT_MANIFEST_PATH,
        missing_code="CONTEXT_MANIFEST_MISSING",
        invalid_code="CONTEXT_MANIFEST_INVALID",
    )
    if diagnostics:
        return None, diagnostics
    assert manifest is not None and manifest_payload is not None
    if set(manifest) != {"algorithm", "fragments", "inputArtifacts", "owner"}:
        diagnostics.append(
            diag(
                "CONTEXT_MANIFEST_INVALID",
                "context manifest fields do not match the current contract",
                CONTEXT_MANIFEST_PATH,
            )
        )
    if manifest.get("algorithm") != CONTEXT_ALGORITHM:
        diagnostics.append(
            diag("CONTEXT_MANIFEST_INVALID", "context manifest algorithm is invalid", CONTEXT_MANIFEST_PATH)
        )
    if manifest.get("owner") != SUBJECT:
        diagnostics.append(
            diag("CONTEXT_MANIFEST_INVALID", "context manifest owner is invalid", CONTEXT_MANIFEST_PATH)
        )
    if manifest.get("inputArtifacts") != [input_entry(artifact) for artifact in inputs]:
        diagnostics.append(
            diag("CONTEXT_INPUT_STALE", "context inputs do not match current Owner inputs", CONTEXT_MANIFEST_PATH)
        )
    expected_fragments: list[dict[str, object]] = []
    for name, path in CONTEXT_FRAGMENT_SPECS:
        try:
            payload = files.read_bytes(path)
        except ProjectIOError:
            diagnostics.append(diag("CONTEXT_FRAGMENT_MISSING", "context fragment is unavailable", path))
            continue
        expected_fragments.append(
            {"bytes": len(payload), "name": name, "path": path, "sha256": sha256_bytes(payload)}
        )
    if manifest.get("fragments") != expected_fragments:
        diagnostics.append(
            diag(
                "CONTEXT_FRAGMENT_STALE",
                "context fragment hashes do not match the current manifest",
                CONTEXT_MANIFEST_PATH,
            )
        )
    if diagnostics:
        return None, diagnostics
    return {
        "fragments": expected_fragments,
        "manifest": file_entry("manifest", CONTEXT_MANIFEST_PATH, manifest_payload),
    }, []


def risk_summary_bytes(
    files: ProjectFiles,
    data: dict[str, Any],
    candidate_hash: str,
) -> bytes:
    declaration_value = current_questionnaire_declaration(files)
    records: list[dict[str, str]] = []
    if declaration_value == QUESTIONNAIRE_PATH:
        records, _ = parse_questionnaire(files.read_bytes(QUESTIONNAIRE_PATH).decode("utf-8"))
    open_critical = sum(
        record.get("Status") not in {"CLOSED", "APPROVED_DEFAULT"}
        and record.get("Blocking", "").startswith("YES")
        for record in records
    )
    approved_defaults = sum(record.get("Status") == "APPROVED_DEFAULT" for record in records)
    return (
        "# BUSINESS requirements 风险摘要\n\n"
        f"Candidate SHA-256: {candidate_hash}\n"
        f"Source Document Count: {len(data['sourceDocuments'])}\n"
        f"Normalized Item Count: {len(data['normalizedItems'])}\n"
        f"Epic Count: {len(data['epics'])}\n"
        f"Feature Count: {len(data['features'])}\n"
        f"Questionnaire: {declaration_value}\n"
        f"Open Critical Questionnaire Items: {open_critical}\n"
        f"Approved Default Items: {approved_defaults}\n"
    ).encode("utf-8")


def review_packet(
    *,
    candidate_path: str,
    candidate_payload: bytes,
    context: dict[str, object],
    inputs: tuple[Artifact, ...],
    review_path: str,
    review_payload: bytes,
    risk_summary_path: str,
    risk_summary_payload: bytes,
) -> dict[str, object]:
    return {
        "algorithm": REVIEW_PACKET_ALGORITHM,
        "candidateOutputs": [
            {
                **file_entry("requirements", candidate_path, candidate_payload),
                "targetPath": STABLE_PATH,
            }
        ],
        "context": context,
        "inputArtifacts": [input_entry(artifact) for artifact in inputs],
        "owner": SUBJECT,
        "review": {"path": review_path, "sha256": sha256_bytes(review_payload)},
        "riskSummary": {
            "path": risk_summary_path,
            "sha256": sha256_bytes(risk_summary_payload),
        },
        "status": "READY_FOR_REVIEW",
        "validatorContractVersion": VALIDATOR_CONTRACT_VERSION,
    }


def binding_diagnostics(
    files: ProjectFiles,
    *,
    path: str,
    algorithm: str,
    decision: str,
    packet_hash: str,
    missing_code: str,
    invalid_code: str,
) -> list[dict[str, object]]:
    value, _, diagnostics = canonical_object(
        files,
        path,
        missing_code=missing_code,
        invalid_code=invalid_code,
    )
    if diagnostics:
        return diagnostics
    expected = {
        "algorithm": algorithm,
        "decision": decision,
        "owner": SUBJECT,
        "packetSha256": packet_hash,
    }
    return [] if value == expected else [
        diag(invalid_code, f"binding does not match the current review packet: {path}", path)
    ]


def approved_packet_diagnostics(
    files: ProjectFiles,
    *,
    packet_path: str,
    expected_packet: dict[str, object],
    candidate_path: str,
    review_path: str,
    risk_summary_path: str,
    reviewer_path: str,
    approval_path: str,
) -> list[dict[str, object]]:
    packet, packet_payload, diagnostics = canonical_object(
        files,
        packet_path,
        missing_code="REVIEW_PACKET_MISSING",
        invalid_code="REVIEW_PACKET_INVALID",
    )
    if diagnostics:
        return diagnostics
    assert packet is not None and packet_payload is not None
    if set(packet) != set(expected_packet):
        diagnostics.append(diag("REVIEW_PACKET_INVALID", "review packet fields are invalid", packet_path))
    comparisons = (
        ("candidateOutputs", "REVIEW_PACKET_CANDIDATE_STALE", candidate_path),
        ("context", "REVIEW_PACKET_CONTEXT_STALE", CONTEXT_MANIFEST_PATH),
        ("inputArtifacts", "REVIEW_PACKET_INPUT_STALE", packet_path),
        ("review", "REVIEW_PACKET_REVIEW_STALE", review_path),
        ("riskSummary", "REVIEW_PACKET_RISK_SUMMARY_STALE", risk_summary_path),
    )
    for key, code, path in comparisons:
        if packet.get(key) != expected_packet[key]:
            diagnostics.append(diag(code, f"review packet {key} does not match current bytes", path))
    for key in ("algorithm", "owner", "status", "validatorContractVersion"):
        if packet.get(key) != expected_packet[key]:
            diagnostics.append(diag("REVIEW_PACKET_INVALID", f"review packet field is invalid: {key}", packet_path))
    if diagnostics:
        return diagnostics
    packet_hash = sha256_bytes(packet_payload)
    diagnostics.extend(
        binding_diagnostics(
            files,
            path=reviewer_path,
            algorithm=REVIEWER_ALGORITHM,
            decision="PASS",
            packet_hash=packet_hash,
            missing_code="REVIEWER_BINDING_MISSING",
            invalid_code="REVIEWER_BINDING_INVALID",
        )
    )
    diagnostics.extend(
        binding_diagnostics(
            files,
            path=approval_path,
            algorithm=APPROVAL_ALGORITHM,
            decision="APPROVED",
            packet_hash=packet_hash,
            missing_code="APPROVAL_BINDING_MISSING",
            invalid_code="APPROVAL_BINDING_INVALID",
        )
    )
    return diagnostics


def write_failure(files: ProjectFiles, diagnostics: list[dict[str, object]]) -> None:
    files.write_atomic(
        VALIDATION_PATH,
        canonical_json_bytes({"owner": SUBJECT, "passed": False, "diagnostics": diagnostics}),
    )


def main() -> int:
    args = parse_args()
    if args.mode == "write-reviewer":
        return write_reviewer(args)
    if args.mode == "write-approval":
        return write_approval(args)
    staging_failure = reconciliation_staging_failure(args.mode, args.staging_root)
    if staging_failure is not None:
        print(json.dumps(staging_failure, ensure_ascii=False))
        return 2
    review_path_diagnostics = validate_review_path(args.mode, args.review_path)
    if review_path_diagnostics:
        print(
            json.dumps(
                {
                    "outcome": "BLOCKED",
                    "summary": "BUSINESS requirements are invalid",
                    "diagnostics": review_path_diagnostics,
                    "outputs": [],
                },
                ensure_ascii=False,
            )
        )
        return 2
    try:
        files = (
            ProjectFiles.open_view(args.project_root, args.staging_root)
            if args.staging_root is not None
            else ProjectFiles.open(args.project_root)
        )
        schema_path = Path(__file__).resolve().parents[1] / "contracts/source-requirements.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        no_change = (
            args.mode in {"review", "publish-approved", "rebind"}
            and declares_no_change(files, args.review_path)
        )
        relative = STABLE_PATH if args.mode == "rebind" else args.candidate
        payload, data, inputs, diagnostics = load_and_validate(
            files,
            relative,
            schema,
            require_no_change=no_change,
            review_path=args.review_path,
        )
        if not diagnostics and no_change and payload is not None:
            try:
                validate_no_change_candidate(
                    files,
                    CONTRACT,
                    inputs,
                    {"requirements": payload},
                )
            except ProjectIOError as error:
                diagnostics.append(diag(error.code, str(error), error.relative_path))
        packet_payload: bytes | None = None
        review_payload: bytes | None = None
        summary_payload: bytes | None = None
        expected_packet: dict[str, object] | None = None
        if (
            not diagnostics
            and args.mode in {"review", "publish-approved"}
            and payload is not None
            and data is not None
        ):
            context, local = context_packet_entry(files, inputs)
            diagnostics.extend(local)
            if not diagnostics:
                try:
                    review_payload = files.read_bytes(args.review_path)
                except ProjectIOError:
                    diagnostics.append(
                        diag("REVIEW_MISSING", "requirement review candidate is unavailable", args.review_path)
                    )
            if context is not None and review_payload is not None:
                summary_payload = risk_summary_bytes(files, data, sha256_bytes(payload))
                expected_packet = review_packet(
                    candidate_path=args.candidate,
                    candidate_payload=payload,
                    context=context,
                    inputs=inputs,
                    review_path=args.review_path,
                    review_payload=review_payload,
                    risk_summary_path=args.risk_summary_path,
                    risk_summary_payload=summary_payload,
                )
                if args.mode == "review":
                    try:
                        files.write_atomic(args.risk_summary_path, summary_payload)
                        packet_payload = canonical_json_bytes(expected_packet)
                        files.write_atomic(args.packet_path, packet_payload)
                    except ProjectIOError as error:
                        diagnostics.append(diag(error.code, str(error), error.relative_path))
                else:
                    try:
                        current_summary = files.read_bytes(args.risk_summary_path)
                    except ProjectIOError:
                        diagnostics.append(
                            diag(
                                "REVIEW_PACKET_RISK_SUMMARY_MISSING",
                                "review packet risk summary is unavailable",
                                args.risk_summary_path,
                            )
                        )
                    else:
                        if current_summary != summary_payload:
                            diagnostics.append(
                                diag(
                                    "REVIEW_PACKET_RISK_SUMMARY_STALE",
                                    "risk summary bytes do not match the current candidate",
                                    args.risk_summary_path,
                                )
                            )
                    diagnostics.extend(
                        approved_packet_diagnostics(
                            files,
                            packet_path=args.packet_path,
                            expected_packet=expected_packet,
                            candidate_path=args.candidate,
                            review_path=args.review_path,
                            risk_summary_path=args.risk_summary_path,
                            reviewer_path=args.reviewer_path,
                            approval_path=args.approval_path,
                        )
                    )
        report: dict[str, object] | None = None
        if not diagnostics:
            try:
                if args.mode == "publish":
                    assert payload is not None
                    report = publish_owner(files, CONTRACT, inputs, {"requirements": payload})
                elif args.mode == "publish-approved":
                    assert payload is not None and review_payload is not None
                    files.write_atomic(REVIEW_PATH, review_payload)
                    publisher = publish_no_change_owner if no_change else publish_owner
                    report = publisher(files, CONTRACT, inputs, {"requirements": payload})
                elif args.mode == "rebind":
                    report = rebind_owner(files, CONTRACT, inputs)
            except ProjectIOError as error:
                diagnostics.append(diag(error.code, str(error), error.relative_path))
        if diagnostics and args.mode in {"publish", "rebind"}:
            write_failure(files, diagnostics)
        if diagnostics:
            outcome = "BLOCKED"
            summary = "BUSINESS requirements are invalid"
            outputs: list[str] = []
        elif args.mode == "review":
            outcome = "REVIEW_REQUIRED"
            summary = "BUSINESS requirements review packet is ready"
            outputs = [args.risk_summary_path, args.packet_path]
        else:
            outcome = "OK"
            summary = "BUSINESS requirements are valid"
            outputs = (
                [STABLE_PATH, VALIDATION_PATH]
                if args.mode in {"publish", "publish-approved", "rebind"}
                else []
            )
        result = {
            "outcome": outcome,
            "summary": summary,
            "diagnostics": diagnostics,
            "outputs": outputs,
        }
        if packet_payload is not None:
            result["packetSha256"] = sha256_bytes(packet_payload)
        if report is not None:
            result["receipt"] = report["compilationReceipt"]
        print(json.dumps(result, ensure_ascii=False))
        return 0 if not diagnostics else 2
    except (ProjectIOError, OSError, json.JSONDecodeError) as error:
        result = {
            "outcome": "BLOCKED",
            "summary": "BUSINESS requirements validation could not run",
            "diagnostics": [diag(getattr(error, "code", "VALIDATOR_BLOCKED"), str(error))],
            "outputs": [],
        }
        print(json.dumps(result, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
