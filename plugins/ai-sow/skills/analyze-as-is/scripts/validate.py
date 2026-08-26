from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import (
    Artifact,
    MatchResult,
    OwnerContract,
    VALIDATOR_CONTRACT_VERSION,
    canonical_json_bytes,
    match_owner,
    publish_no_change_owner,
    publish_owner,
    reconciliation_staging_failure,
    rebind_owner,
    sha256_bytes,
    validate_no_change_candidate,
)
from runtime.project_io import ProjectFiles, ProjectIOError


SUBJECT = "analyze-as-is"
SCHEMA_ID = "urn:ai-sow:analyze-as-is:asis:0.1"
PROJECT_PATH = ".ai-sow/project.json"
REQUIREMENTS_PATH = ".ai-sow/data/analyze-requirement/requirements.json"
REQUIREMENTS_VALIDATION_PATH = ".ai-sow/validation/analyze-requirement.json"
REQUIREMENTS_QUESTIONNAIRE_PATH = ".ai-sow/reviews/analyze-requirement-questionnaire.md"
REVIEW_PATH = ".ai-sow/reviews/analyze-as-is.md"
QUESTIONNAIRE_PATH = ".ai-sow/work/analyze-as-is/questionnaire.md"
STABLE_PATH = ".ai-sow/data/analyze-as-is/asis.json"
VALIDATION_PATH = ".ai-sow/validation/analyze-as-is.json"
PACKET_PATH = ".ai-sow/work/analyze-as-is/review-packet.json"
RISK_SUMMARY_PATH = ".ai-sow/work/analyze-as-is/risk-summary.md"
REVIEWER_PATH = ".ai-sow/work/analyze-as-is/reviewer.json"
APPROVAL_PATH = ".ai-sow/work/analyze-as-is/approval.json"
CONTEXT_MANIFEST_PATH = ".ai-sow/work/analyze-as-is/context/manifest.json"
CONTEXT_FRAGMENT_SPECS = (
    ("requirements", ".ai-sow/work/analyze-as-is/context/requirements.json"),
    ("investigationScope", ".ai-sow/work/analyze-as-is/context/investigation-scope.json"),
    ("evidenceInventory", ".ai-sow/work/analyze-as-is/context/evidence-inventory.json"),
)
REVIEW_PACKET_ALGORITHM = "ai-sow-owner-review-packet-v1"
REVIEWER_ALGORITHM = "ai-sow-owner-reviewer-v1"
APPROVAL_ALGORITHM = "ai-sow-owner-approval-v1"
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
REQUIRED_REVIEW_SECTIONS = (
    "调查范围",
    "九个 Topic",
    "Item",
    "Commitment",
    "Effective Start",
    "Coverage",
    "Uncertainty",
    "Evidence",
    "问卷记录",
    "审查与批准",
)
ALLOWED_TREATMENTS = {
    "IMPLEMENTED": {"CURRENT_BASELINE"},
    "PARTIAL": {"EXPECTED_BEFORE_START", "CARRY_FORWARD", "NEEDS_DECISION"},
    "NOT_IMPLEMENTED": {"EXPECTED_BEFORE_START", "CARRY_FORWARD", "NEEDS_DECISION"},
    "UNVERIFIED": {"NEEDS_DECISION"},
    "SUPERSEDED": {"EXCLUDE"},
}
QUESTIONNAIRE_FIELDS = (
    "Question ID",
    "Answer",
    "Owner",
    "Evidence reference",
    "Effective date",
)
QUESTION_TOPIC = {
    "sys": "SYSTEM_CONTEXT",
    "cap": "CAPABILITY",
    "app": "APPLICATION",
    "int": "INTEGRATION",
    "data": "DATA",
    "plat": "PLATFORM",
    "sec": "SECURITY_COMPLIANCE",
    "ops": "OPERATIONS_QUALITY",
    "del": "DELIVERY_CONSTRAINTS",
}
QUESTION_IDS = {
    *(f"sys-{index:02d}" for index in range(1, 6)),
    *(f"cap-{index:02d}" for index in range(1, 6)),
    *(f"app-{index:02d}" for index in range(1, 6)),
    *(f"int-{index:02d}" for index in range(1, 7)),
    *(f"data-{index:02d}" for index in range(1, 7)),
    *(f"plat-{index:02d}" for index in range(1, 7)),
    *(f"sec-{index:02d}" for index in range(1, 7)),
    *(f"ops-{index:02d}" for index in range(1, 7)),
    *(f"del-{index:02d}" for index in range(1, 7)),
}
ANCHOR_KINDS = {"CODE", "CONTRACT", "CONFIGURATION", "DEPLOYMENT"}

REQUIREMENT_CONTRACT = OwnerContract(
    subject="analyze-requirement",
    contract_ids=("urn:ai-sow:analyze-requirement:source-requirements:0.1",),
    validation_path=REQUIREMENTS_VALIDATION_PATH,
    reviews=(("approvedReview", ".ai-sow/reviews/analyze-requirement.md"),),
    outputs=(("requirements", REQUIREMENTS_PATH),),
)
CONTRACT = OwnerContract(
    subject=SUBJECT,
    contract_ids=(SCHEMA_ID,),
    validation_path=VALIDATION_PATH,
    reviews=(("approvedReview", REVIEW_PATH),),
    outputs=(("asIs", STABLE_PATH),),
)


def diag(code: str, message: str, path: str = "") -> dict[str, object]:
    value: dict[str, object] = {"code": code, "message": message}
    if path:
        value["path"] = path
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and publish As-Is handoff data")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    parser.add_argument(
        "--mode",
        required=True,
        choices=(
            "upstream-check",
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
    parser.add_argument("--candidate", default=".ai-sow/work/analyze-as-is/asis.candidate.json")
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


def declaration(text: str, label: str) -> list[str]:
    return re.findall(rf"(?m)^{re.escape(label)}\s*:\s*(.+?)\s*$", text)


def declares_no_change(files: ProjectFiles, review_path: str) -> bool:
    try:
        text = files.read_bytes(review_path).decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError):
        return False
    return declaration(text, "Impact") == ["NO_CHANGE"]


def stable_ids(data: dict[str, Any]) -> list[str]:
    return [
        *(entry["asIsItemId"] for entry in data["items"]),
        *(entry["commitmentId"] for entry in data["commitments"]),
        *(entry["effectiveStartItemId"] for entry in data["effectiveStartItems"]),
        *(entry["uncertaintyId"] for entry in data["uncertainties"]),
        *(entry["evidenceId"] for entry in data["evidence"]),
    ]


def receipt_input_hash(files: ProjectFiles, name: str) -> str | None:
    try:
        report = files.read_json(REQUIREMENTS_VALIDATION_PATH)
    except ProjectIOError:
        return None
    if not isinstance(report, dict) or not isinstance(report.get("compilationReceipt"), dict):
        return None
    entries = report["compilationReceipt"].get("inputs")
    if not isinstance(entries, list):
        return None
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("name") == name]
    value = matches[0].get("sha256") if len(matches) == 1 else None
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


def current_file_hash(files: ProjectFiles, path: str, fallback: str | None) -> str:
    try:
        return sha256_bytes(files.read_bytes(path))
    except ProjectIOError:
        return fallback or "0" * 64


def current_requirement_inputs(files: ProjectFiles) -> tuple[tuple[Artifact, ...], MatchResult | None]:
    try:
        requirements = files.read_json(REQUIREMENTS_PATH)
    except ProjectIOError as error:
        code = "UPSTREAM_HANDOFF_MISSING" if error.code == "PROJECT_PATH_MISSING" else "UPSTREAM_HANDOFF_INVALID"
        return (), MatchResult(
            False,
            ({"code": code, "message": "upstream requirements output is unavailable", "upstreamOwner": "analyze-requirement", "path": REQUIREMENTS_PATH},),
            None,
        )
    if not isinstance(requirements, dict) or not isinstance(requirements.get("sourceDocuments"), list):
        return (), MatchResult(
            False,
            ({"code": "UPSTREAM_HANDOFF_INVALID", "message": "upstream requirements source input contract is invalid", "upstreamOwner": "analyze-requirement", "path": REQUIREMENTS_PATH},),
            None,
        )
    artifacts: list[Artifact] = [
        Artifact(
            "project",
            "FILE",
            PROJECT_PATH,
            current_file_hash(files, PROJECT_PATH, receipt_input_hash(files, "project")),
        )
    ]
    source_names: set[str] = set()
    for source in requirements["sourceDocuments"]:
        if not isinstance(source, dict) or not all(
            isinstance(source.get(field), str)
            for field in ("sourceDocumentId", "file", "sha256")
        ):
            return (), MatchResult(
                False,
                ({"code": "UPSTREAM_HANDOFF_INVALID", "message": "upstream source document contract is invalid", "upstreamOwner": "analyze-requirement", "path": REQUIREMENTS_PATH},),
                None,
            )
        name = f"source:{source['sourceDocumentId']}"
        if name in source_names:
            return (), MatchResult(
                False,
                ({"code": "UPSTREAM_HANDOFF_INVALID", "message": "upstream source input names are not unique", "upstreamOwner": "analyze-requirement", "path": REQUIREMENTS_PATH},),
                None,
            )
        source_names.add(name)
        artifacts.append(
            Artifact(
                name,
                "FILE",
                source["file"],
                current_file_hash(files, source["file"], source["sha256"]),
            )
        )
    try:
        review = files.read_bytes(".ai-sow/reviews/analyze-requirement.md").decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError):
        review = ""
    questionnaires = declaration(review, "Questionnaire")
    if questionnaires == ["NOT_REQUIRED"]:
        try:
            current = files.read_bytes(REQUIREMENTS_QUESTIONNAIRE_PATH)
        except ProjectIOError:
            logical = canonical_json_bytes({"declaration": "NOT_REQUIRED"})
        else:
            logical = canonical_json_bytes({"declaration": "PRESENT", "sha256": sha256_bytes(current)})
        artifacts.append(
            Artifact("questionnaire", "QUESTIONNAIRE_PRESENCE", "questionnaire:NOT_REQUIRED", sha256_bytes(logical))
        )
    elif questionnaires == [REQUIREMENTS_QUESTIONNAIRE_PATH]:
        artifacts.append(
            Artifact(
                "questionnaire",
                "QUESTIONNAIRE_PRESENCE",
                f"questionnaire:{REQUIREMENTS_QUESTIONNAIRE_PATH}",
                current_file_hash(
                    files,
                    REQUIREMENTS_QUESTIONNAIRE_PATH,
                    receipt_input_hash(files, "questionnaire"),
                ),
            )
        )
    else:
        return (), MatchResult(
            False,
            ({"code": "UPSTREAM_HANDOFF_INVALID", "message": "upstream questionnaire declaration is invalid", "upstreamOwner": "analyze-requirement", "path": ".ai-sow/reviews/analyze-requirement.md"},),
            None,
        )
    return tuple(artifacts), None


def requirement_handoff(files: ProjectFiles) -> MatchResult:
    expected_inputs, failure = current_requirement_inputs(files)
    result = match_owner(files, REQUIREMENT_CONTRACT, expected_inputs)
    if not result.ok:
        return result
    if failure is not None:
        return failure
    if result.receipt is None:
        return result
    for entry in result.receipt["inputs"]:  # type: ignore[index]
        if not isinstance(entry, dict) or entry.get("kind") != "QUESTIONNAIRE_PRESENCE":
            continue
        identity = entry.get("identity")
        if identity == f"questionnaire:{REQUIREMENTS_QUESTIONNAIRE_PATH}":
            try:
                files.resolve(REQUIREMENTS_QUESTIONNAIRE_PATH)
            except ProjectIOError:
                return MatchResult(
                    False,
                    (
                        {
                            "code": "UPSTREAM_HANDOFF_MISSING",
                            "message": "upstream questionnaire declared by its receipt is missing",
                            "upstreamOwner": "analyze-requirement",
                            "path": REQUIREMENTS_QUESTIONNAIRE_PATH,
                        },
                    ),
                    None,
                )
    return result


def parse_questionnaire(text: str) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    records: list[dict[str, str]] = []
    duplicates: list[tuple[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"(Question ID|Answer|Owner|Evidence reference|Effective date):\s*(.*)", line.strip())
        if match is None:
            continue
        field, value = match.groups()
        if field == "Question ID" and current:
            records.append(current)
            current = {}
        if field in current:
            duplicates.append((current.get("Question ID", "unknown"), field))
        current[field] = value
    if current:
        records.append(current)
    return records, duplicates


def previous_owner_receipt(files: ProjectFiles) -> dict[str, Any] | None:
    try:
        report = files.read_json(VALIDATION_PATH)
    except ProjectIOError:
        return None
    if not isinstance(report, dict) or report.get("owner") != SUBJECT or report.get("passed") is not True:
        return None
    receipt = report.get("compilationReceipt")
    return receipt if isinstance(receipt, dict) else None


def named_receipt_input_hash(receipt: dict[str, Any], name: str) -> str | None:
    entries = receipt.get("inputs")
    if not isinstance(entries, list):
        return None
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("name") == name]
    value = matches[0].get("sha256") if len(matches) == 1 else None
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


def validate_questionnaire(
    files: ProjectFiles,
    declaration_value: str,
    declared_ids: str,
    data: dict[str, Any],
    *,
    review_path: str,
) -> tuple[list[dict[str, object]], Artifact, list[dict[str, str]]]:
    diagnostics: list[dict[str, object]] = []
    if declaration_value == "NOT_REQUIRED":
        if any(entry["kind"] == "QUESTIONNAIRE" for entry in data["evidence"]):
            diagnostics.append(
                diag(
                    "QUESTIONNAIRE_EVIDENCE_UNDECLARED",
                    "QUESTIONNAIRE Evidence requires a declared selected questionnaire",
                    STABLE_PATH,
                )
            )
        try:
            files.resolve(QUESTIONNAIRE_PATH)
        except ProjectIOError as error:
            if error.code != "PROJECT_PATH_MISSING":
                diagnostics.append(
                    diag("QUESTIONNAIRE_PRESENCE_CONFLICT", "questionnaire path is unsafe", QUESTIONNAIRE_PATH)
                )
        else:
            diagnostics.append(
                diag(
                    "QUESTIONNAIRE_PRESENCE_CONFLICT",
                    "Questionnaire: NOT_REQUIRED conflicts with an existing questionnaire",
                    QUESTIONNAIRE_PATH,
                )
            )
        if declared_ids != "NONE":
            diagnostics.append(
                diag("QUESTIONNAIRE_ID_SET_MISMATCH", "NOT_REQUIRED requires Questionnaire IDs: NONE", review_path)
            )
        payload = canonical_json_bytes({"declaration": "NOT_REQUIRED"})
        return diagnostics, Artifact(
            "questionnaire",
            "QUESTIONNAIRE_PRESENCE",
            "questionnaire:NOT_REQUIRED",
            sha256_bytes(payload),
        ), []
    if declaration_value != QUESTIONNAIRE_PATH:
        diagnostics.append(
            diag("QUESTIONNAIRE_DECLARATION_INVALID", "review must use the fixed questionnaire path", review_path)
        )
        payload = canonical_json_bytes({"declaration": "INVALID"})
        return diagnostics, Artifact(
            "questionnaire", "QUESTIONNAIRE_PRESENCE", "questionnaire:INVALID", sha256_bytes(payload)
        ), []
    try:
        payload = files.read_bytes(QUESTIONNAIRE_PATH)
        text = payload.decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError):
        diagnostics.append(diag("QUESTIONNAIRE_MISSING", "declared questionnaire is unavailable", QUESTIONNAIRE_PATH))
        payload = b""
        text = ""
    records, duplicates = parse_questionnaire(text)
    for question_id, field in duplicates:
        diagnostics.append(
            diag("QUESTIONNAIRE_FIELD_DUPLICATE", f"{question_id} repeats field: {field}", QUESTIONNAIRE_PATH)
        )
    actual_ids = [record.get("Question ID", "") for record in records]
    expected_ids = [value for value in re.split(r"[,，、;；\s]+", declared_ids) if value]
    if not records or actual_ids != expected_ids or len(set(actual_ids)) != len(actual_ids):
        diagnostics.append(
            diag("QUESTIONNAIRE_ID_SET_MISMATCH", "review IDs must match unique questionnaire records", review_path)
        )
    uncertainty_topics = {entry["topic"] for entry in data["uncertainties"]}
    questionnaire_evidence = {
        entry["reference"]
        for entry in data["evidence"]
        if entry["kind"] == "QUESTIONNAIRE"
    }
    expected_evidence_references = {f"questionnaire:{question_id}" for question_id in actual_ids}
    for reference in sorted(questionnaire_evidence - expected_evidence_references):
        diagnostics.append(
            diag(
                "QUESTIONNAIRE_EVIDENCE_UNKNOWN",
                f"QUESTIONNAIRE Evidence references an unselected question: {reference}",
                STABLE_PATH,
            )
        )
    for record in records:
        question_id = record.get("Question ID", "unknown")
        if question_id not in QUESTION_IDS:
            diagnostics.append(
                diag(
                    "QUESTIONNAIRE_ID_UNKNOWN",
                    f"{question_id} is not in the current-state questionnaire catalog",
                    QUESTIONNAIRE_PATH,
                )
            )
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
        answer = record["Answer"]
        topic = QUESTION_TOPIC.get(question_id.split("-", 1)[0])
        reference = f"questionnaire:{question_id}"
        if answer == "UNKNOWN":
            if topic is None or topic not in uncertainty_topics:
                diagnostics.append(
                    diag(
                        "QUESTIONNAIRE_UNCERTAINTY_MISSING",
                        f"{question_id} UNKNOWN answer requires an owned Uncertainty",
                        QUESTIONNAIRE_PATH,
                    )
                )
            if reference in questionnaire_evidence:
                diagnostics.append(
                    diag(
                        "QUESTIONNAIRE_EVIDENCE_INVALID",
                        f"{question_id} UNKNOWN answer cannot create Evidence",
                        QUESTIONNAIRE_PATH,
                    )
                )
        else:
            if record["Owner"] == "UNKNOWN" or record["Effective date"] == "UNKNOWN":
                diagnostics.append(
                    diag(
                        "QUESTIONNAIRE_DECISION_INCOMPLETE",
                        f"{question_id} confirmed answer requires owner and effective date",
                        QUESTIONNAIRE_PATH,
                    )
                )
            if reference not in questionnaire_evidence:
                diagnostics.append(
                    diag(
                        "QUESTIONNAIRE_EVIDENCE_MISSING",
                        f"{question_id} confirmed answer requires QUESTIONNAIRE Evidence",
                        QUESTIONNAIRE_PATH,
                    )
                )
    return diagnostics, Artifact(
        "questionnaire",
        "QUESTIONNAIRE_PRESENCE",
        f"questionnaire:{QUESTIONNAIRE_PATH}",
        sha256_bytes(payload),
    ), records


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
        return [diag("REVIEW_MISSING", "approved As-Is review is unavailable", review_path)], None
    diagnostics: list[dict[str, object]] = []
    for section in REQUIRED_REVIEW_SECTIONS:
        if len(re.findall(rf"(?m)^## {re.escape(section)}\s*$", text)) != 1:
            diagnostics.append(
                diag("REVIEW_SECTION_INVALID", f"review must contain exactly one section: {section}", review_path)
            )
    id_values = declaration(text, "Stable IDs")
    declared_ids = (
        []
        if id_values == ["NONE"]
        else [value for value in re.split(r"[,，、;；\s]+", id_values[0]) if value]
        if len(id_values) == 1
        else []
    )
    if len(id_values) != 1 or declared_ids != stable_ids(data):
        diagnostics.append(diag("REVIEW_ID_SET_MISMATCH", "review Stable IDs do not match As-Is candidate", review_path))
    if declaration(text, "Reviewer") != ["PASS"]:
        diagnostics.append(diag("REVIEW_NOT_PASSED", "Reviewer must be PASS", review_path))
    if declaration(text, "User Approval") != ["APPROVED"]:
        diagnostics.append(diag("USER_APPROVAL_MISSING", "User Approval must be APPROVED", review_path))
    impacts = declaration(text, "Impact")
    if require_no_change and impacts != ["NO_CHANGE"]:
        diagnostics.append(diag("REVIEW_NO_CHANGE_MISSING", "NO_CHANGE 发布或 rebind 要求 review 声明 Impact: NO_CHANGE", review_path))
    elif not require_no_change and "NO_CHANGE" in impacts:
        diagnostics.append(
            diag("REVIEW_NO_CHANGE_MODE_INVALID", "Impact: NO_CHANGE 仅允许用于 NO_CHANGE 发布或 rebind", review_path)
        )
    elif not require_no_change and impacts not in ([], ["CHANGED"]):
        diagnostics.append(diag("REVIEW_IMPACT_INVALID", "review Impact declaration is invalid", review_path))
    if require_no_change:
        previous = previous_owner_receipt(files)
        previous_hash = named_receipt_input_hash(previous, "requirementsValidation") if previous else None
        current_hash = current_file_hash(files, REQUIREMENTS_VALIDATION_PATH, None)
        if declaration(text, "Upstream") != ["analyze-requirement"]:
            diagnostics.append(diag("REVIEW_UPSTREAM_INVALID", "NO_CHANGE review 的 Upstream 必须是 analyze-requirement", review_path))
        if declaration(text, "Previous Receipt SHA-256") != ([previous_hash] if previous_hash else []):
            diagnostics.append(
                diag("REVIEW_PREVIOUS_RECEIPT_MISMATCH", "review 中的旧上游 receipt hash 无效", review_path)
            )
        if declaration(text, "Current Receipt SHA-256") != [current_hash]:
            diagnostics.append(
                diag("REVIEW_CURRENT_RECEIPT_MISMATCH", "review 中的当前上游 receipt hash 无效", review_path)
            )
        rationales = declaration(text, "Impact Rationale")
        expected_ids = stable_ids(data) or ["NONE"]
        rationale_ids = (
            set(
                re.findall(
                    r"(?:asis|commitment|effective-start|uncertainty|evidence)-[a-z0-9]+(?:-[a-z0-9]+)*|NONE",
                    rationales[0],
                )
            )
            if len(rationales) == 1
            else set()
        )
        if len(rationales) != 1 or not set(expected_ids).issubset(rationale_ids):
            diagnostics.append(
                diag(
                    "REVIEW_IMPACT_RATIONALE_INVALID",
                    "NO_CHANGE Impact Rationale 必须点名每个受影响或确认不受影响的稳定 ID",
                    review_path,
                )
            )
    questionnaires = declaration(text, "Questionnaire")
    question_ids = declaration(text, "Questionnaire IDs")
    if len(questionnaires) != 1 or len(question_ids) != 1:
        diagnostics.append(
            diag("QUESTIONNAIRE_DECLARATION_INVALID", "review must declare Questionnaire and Questionnaire IDs once", review_path)
        )
        return diagnostics, None
    questionnaire_diagnostics, artifact, questionnaire_records = validate_questionnaire(
        files,
        questionnaires[0],
        question_ids[0],
        data,
        review_path=review_path,
    )
    diagnostics.extend(questionnaire_diagnostics)
    review_records, review_duplicates = parse_questionnaire(text)
    if review_duplicates or review_records != questionnaire_records:
        diagnostics.append(
            diag(
                "REVIEW_QUESTIONNAIRE_RECORD_MISMATCH",
                "review must reproduce every selected questionnaire record exactly",
                review_path,
            )
        )
    return diagnostics, artifact


def input_entry(artifact: Artifact) -> dict[str, object]:
    locator_key = "path" if artifact.kind == "FILE" else "identity"
    return {
        "name": artifact.name,
        "kind": artifact.kind,
        locator_key: artifact.locator,
        "sha256": artifact.sha256,
    }


def add_unknown_references(
    diagnostics: list[dict[str, object]],
    references: list[str],
    known: set[str],
    code: str,
    label: str,
) -> None:
    for reference in references:
        if reference not in known:
            diagnostics.append(diag(code, f"unknown {label}: {reference}"))


def validate_semantics(
    data: dict[str, Any],
    feature_ids: set[str],
    requirement_ids: set[str],
) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    registry: dict[str, str] = {}
    for collection, field, kind in (
        ("items", "asIsItemId", "Item"),
        ("commitments", "commitmentId", "Commitment"),
        ("effectiveStartItems", "effectiveStartItemId", "Effective Start"),
        ("uncertainties", "uncertaintyId", "Uncertainty"),
        ("evidence", "evidenceId", "Evidence"),
    ):
        for entry in data[collection]:
            value = entry[field]
            if value in registry:
                diagnostics.append(diag("ID_DUPLICATE", f"duplicate global ID: {value}"))
            registry[value] = kind
    display_names = [
        *[entry["name"] for entry in data["items"]],
        *[entry["name"] for entry in data["commitments"]],
        *[entry["name"] for entry in data["effectiveStartItems"]],
        *[entry["name"] for entry in data["uncertainties"]],
        *[entry["name"] for entry in data["evidence"]],
    ]
    for name, count in Counter(display_names).items():
        if count > 1:
            diagnostics.append(
                diag("NAME_DUPLICATE", f"duplicate system-current display name: {name}")
            )
    item_ids = {entry["asIsItemId"] for entry in data["items"]}
    commitments = {entry["commitmentId"]: entry for entry in data["commitments"]}
    commitment_ids = set(commitments)
    start_ids = {entry["effectiveStartItemId"] for entry in data["effectiveStartItems"]}
    uncertainties = {entry["uncertaintyId"]: entry for entry in data["uncertainties"]}
    uncertainty_ids = set(uncertainties)
    topics = tuple(entry["topic"] for entry in data["topicAssessments"])
    if topics != EXPECTED_TOPICS:
        diagnostics.append(
            diag("TOPIC_ASSESSMENTS_INVALID", "topicAssessments must contain nine Topics in canonical order")
        )
    for assessment in data["topicAssessments"]:
        add_unknown_references(
            diagnostics, assessment["uncertaintyIds"], uncertainty_ids,
            "UNCERTAINTY_REF_UNKNOWN", "uncertaintyId",
        )
        if assessment["status"] == "INSUFFICIENT_EVIDENCE" and not assessment["uncertaintyIds"]:
            diagnostics.append(
                diag("TOPIC_UNCERTAINTY_REQUIRED", f"{assessment['topic']} requires an Uncertainty")
            )
    scope = data["analysisScope"]
    for collection in ("repositorySnapshots", "priorSowSnapshots"):
        for name, count in Counter(entry["name"] for entry in scope[collection]).items():
            if count > 1:
                diagnostics.append(
                    diag("NAME_DUPLICATE", f"duplicate {collection} name: {name}")
                )
    repo_ids = {entry["repoId"] for entry in scope["repositorySnapshots"]}
    prior_ids = {entry["priorSowId"] for entry in scope["priorSowSnapshots"]}
    if scope["mode"] == "GREENFIELD" and (repo_ids or prior_ids):
        diagnostics.append(diag("GREENFIELD_INPUT_INVALID", "Greenfield must not contain technical snapshots"))
    if scope["mode"] == "BROWNFIELD" and not repo_ids and not prior_ids:
        diagnostics.append(diag("BROWNFIELD_INPUT_REQUIRED", "Brownfield requires a repository or prior SOW"))
    for entry in data["items"]:
        add_unknown_references(
            diagnostics, entry["repositoryIds"], repo_ids,
            "REPOSITORY_REF_UNKNOWN", "repoId",
        )
    for commitment in data["commitments"]:
        if commitment["priorSowId"] not in prior_ids:
            diagnostics.append(diag("PRIOR_SOW_REF_UNKNOWN", f"unknown priorSowId: {commitment['priorSowId']}"))
        source_match = re.fullmatch(
            r"prior-sow:([a-z][a-z0-9-]*)(?:#.+)?",
            commitment["sourceReference"],
        )
        if source_match is None or source_match.group(1) != commitment["priorSowId"]:
            diagnostics.append(
                diag(
                    "PRIOR_SOW_COMMITMENT_REF_INVALID",
                    "Commitment sourceReference must use "
                    f"prior-sow:{commitment['priorSowId']}#<anchor>: {commitment['commitmentId']}",
                )
            )
        status = commitment["implementationStatus"]
        treatment = commitment["treatment"]
        if treatment not in ALLOWED_TREATMENTS[status]:
            diagnostics.append(diag("COMMITMENT_TREATMENT_INVALID", f"{status} cannot use {treatment}"))
        if status == "IMPLEMENTED" and not commitment["affectedItemIds"]:
            diagnostics.append(diag("IMPLEMENTED_COMMITMENT_ITEM_REQUIRED", "implemented Commitment needs an Item"))
        if treatment == "CARRY_FORWARD" and not commitment["relatedFeatureIds"]:
            diagnostics.append(diag("CARRY_FORWARD_FEATURE_REQUIRED", "carry-forward needs a Feature"))
        add_unknown_references(
            diagnostics, commitment["affectedItemIds"], item_ids,
            "ASIS_REF_UNKNOWN", "asIsItemId",
        )
        add_unknown_references(
            diagnostics, commitment["relatedFeatureIds"], feature_ids,
            "FEATURE_REF_UNKNOWN", "source Feature",
        )
    for start in data["effectiveStartItems"]:
        add_unknown_references(
            diagnostics, start["sourceItemIds"], item_ids,
            "ASIS_REF_UNKNOWN", "asIsItemId",
        )
        for reference in start["commitmentIds"]:
            commitment = commitments.get(reference)
            if commitment is None:
                diagnostics.append(diag("COMMITMENT_REF_UNKNOWN", f"unknown commitmentId: {reference}"))
            elif commitment["treatment"] != "EXPECTED_BEFORE_START":
                diagnostics.append(
                    diag("EFFECTIVE_START_COMMITMENT_INELIGIBLE", f"ineligible Commitment: {reference}")
                )
    for uncertainty in data["uncertainties"]:
        add_unknown_references(
            diagnostics, uncertainty["relatedFeatureIds"], feature_ids,
            "FEATURE_REF_UNKNOWN", "source Feature",
        )
    covered = [entry["featureId"] for entry in data["coverage"]]
    for feature_id, count in Counter(covered).items():
        if count > 1:
            diagnostics.append(diag("COVERAGE_DUPLICATE", f"duplicate Coverage: {feature_id}"))
        if feature_id not in feature_ids:
            diagnostics.append(diag("FEATURE_REF_UNKNOWN", f"unknown source Feature: {feature_id}"))
    for feature_id in sorted(feature_ids - set(covered)):
        diagnostics.append(diag("COVERAGE_MISSING", f"missing Coverage: {feature_id}"))
    coverage_by_feature = {entry["featureId"]: entry for entry in data["coverage"]}
    for coverage in data["coverage"]:
        add_unknown_references(
            diagnostics, coverage["effectiveStartItemIds"], start_ids,
            "EFFECTIVE_START_REF_UNKNOWN", "effectiveStartItemId",
        )
        add_unknown_references(
            diagnostics, coverage["commitmentIds"], commitment_ids,
            "COMMITMENT_REF_UNKNOWN", "commitmentId",
        )
        add_unknown_references(
            diagnostics, coverage["uncertaintyIds"], uncertainty_ids,
            "UNCERTAINTY_REF_UNKNOWN", "uncertaintyId",
        )
        for reference in coverage["commitmentIds"]:
            commitment = commitments.get(reference)
            if commitment and coverage["featureId"] not in commitment["relatedFeatureIds"]:
                diagnostics.append(
                    diag("COMMITMENT_COVERAGE_FEATURE_MISMATCH", f"unrelated Commitment: {reference}")
                )
    for commitment_id, commitment in commitments.items():
        for feature_id in commitment["relatedFeatureIds"]:
            coverage = coverage_by_feature.get(feature_id)
            if coverage is None or commitment_id not in coverage["commitmentIds"]:
                diagnostics.append(
                    diag("COMMITMENT_COVERAGE_MISSING", f"Commitment missing from Coverage: {commitment_id}")
                )
                if commitment["treatment"] == "CARRY_FORWARD":
                    diagnostics.append(
                        diag("CARRY_FORWARD_COVERAGE_MISSING", f"carry-forward missing: {commitment_id}")
                    )
        if commitment["implementationStatus"] == "UNVERIFIED" or commitment["treatment"] == "NEEDS_DECISION":
            linked = any(
                commitment_id in coverage["commitmentIds"]
                and any(
                    coverage["featureId"] in uncertainties[uncertainty_id]["relatedFeatureIds"]
                    for uncertainty_id in coverage["uncertaintyIds"]
                    if uncertainty_id in uncertainties
                )
                for coverage in data["coverage"]
            )
            if not linked:
                diagnostics.append(
                    diag("COMMITMENT_DECISION_CHAIN_MISSING", f"decision chain missing: {commitment_id}")
                )
    supported = item_ids | commitment_ids | start_ids | uncertainty_ids | feature_ids
    item_evidence: dict[str, set[str]] = defaultdict(set)
    for evidence in data["evidence"]:
        add_unknown_references(
            diagnostics, evidence["supportsIds"], supported,
            "EVIDENCE_REF_UNKNOWN", "supported ID",
        )
        for reference in item_ids.intersection(evidence["supportsIds"]):
            item_evidence[reference].add(evidence["kind"])
        if evidence["kind"] == "PRIOR_SOW":
            match = re.fullmatch(r"prior-sow:([a-z][a-z0-9-]*)(?:#.+)?", evidence["reference"])
            if match is None or match.group(1) not in prior_ids:
                registered = ", ".join(sorted(prior_ids)) or "NONE"
                diagnostics.append(
                    diag(
                        "PRIOR_SOW_EVIDENCE_REF_UNKNOWN",
                        "PRIOR_SOW Evidence must use "
                        "prior-sow:<registered-priorSowId>#<anchor>: "
                        f"{evidence['evidenceId']}; registered priorSowIds: {registered}",
                    )
                )
        if evidence["kind"] == "DOCUMENT" and evidence["reference"].startswith("requirements:"):
            requirement_id = evidence["reference"].split(":", 1)[1].split("#", 1)[0]
            if requirement_id not in requirement_ids:
                diagnostics.append(
                    diag(
                        "REQUIREMENT_EVIDENCE_REF_UNKNOWN",
                        f"DOCUMENT Evidence has an unknown Requirement ID: {evidence['evidenceId']}",
                    )
                )
    for item_id in sorted(item_ids - set(item_evidence)):
        diagnostics.append(
            diag(
                "BROWNFIELD_ITEM_EVIDENCE_MISSING" if scope["mode"] == "BROWNFIELD" else "GREENFIELD_ITEM_EVIDENCE_MISSING",
                f"Item lacks Evidence: {item_id}",
            )
        )
    if scope["mode"] == "GREENFIELD":
        for item_id, kinds in item_evidence.items():
            if not kinds.issubset({"DOCUMENT", "QUESTIONNAIRE"}):
                diagnostics.append(
                    diag("GREENFIELD_ITEM_EVIDENCE_INVALID", f"invalid Greenfield Evidence: {item_id}")
                )
    return diagnostics


def repository_path(scope: dict[str, Any], repo_id: str, anchor: str) -> str | None:
    snapshot = next((entry for entry in scope["repositorySnapshots"] if entry["repoId"] == repo_id), None)
    if snapshot is None:
        return None
    base = snapshot["path"]
    return anchor if base == "." else f"{base}/{anchor}"


def attest_inputs(
    files: ProjectFiles,
    data: dict[str, Any],
    questionnaire: Artifact,
) -> tuple[list[dict[str, object]], tuple[Artifact, ...]]:
    diagnostics: list[dict[str, object]] = []
    inputs: list[Artifact] = []
    for name, path in (
        ("project", PROJECT_PATH),
        ("requirementsValidation", REQUIREMENTS_VALIDATION_PATH),
        ("requirements", REQUIREMENTS_PATH),
    ):
        try:
            payload = files.read_bytes(path)
        except ProjectIOError:
            diagnostics.append(diag("INPUT_MISSING", f"required input is unavailable: {path}", path))
        else:
            inputs.append(Artifact(name, "FILE", path, sha256_bytes(payload)))
    scope = data["analysisScope"]
    seen_repositories: set[str] = set()
    for snapshot in scope["repositorySnapshots"]:
        repo_id = snapshot["repoId"]
        if repo_id in seen_repositories:
            diagnostics.append(diag("INTAKE_ID_DUPLICATE", f"duplicate repository ID: {repo_id}"))
        seen_repositories.add(repo_id)
        try:
            files.resolve(snapshot["path"], expect="dir")
        except ProjectIOError:
            diagnostics.append(diag("REGISTERED_PATH_INVALID", f"repository is unavailable: {repo_id}", snapshot["path"]))
        inputs.append(
            Artifact(
                f"repository:{repo_id}",
                "CANONICAL_JSON",
                f"repository:{repo_id}",
                sha256_bytes(canonical_json_bytes(snapshot)),
            )
        )
    seen_prior: set[str] = set()
    for snapshot in scope["priorSowSnapshots"]:
        prior_id = snapshot["priorSowId"]
        if prior_id in seen_prior:
            diagnostics.append(diag("INTAKE_ID_DUPLICATE", f"duplicate prior SOW ID: {prior_id}"))
        seen_prior.add(prior_id)
        try:
            payload = files.read_bytes(snapshot["file"])
        except ProjectIOError:
            diagnostics.append(diag("REGISTERED_PATH_INVALID", f"prior SOW is unavailable: {prior_id}", snapshot["file"]))
            continue
        actual = sha256_bytes(payload)
        if actual != snapshot["sha256"]:
            diagnostics.append(diag("PRIOR_SOW_HASH_MISMATCH", f"prior SOW hash changed: {prior_id}", snapshot["file"]))
        inputs.append(Artifact(f"priorSow:{prior_id}", "FILE", snapshot["file"], actual))
    for evidence in data["evidence"]:
        if evidence["kind"] == "RUNTIME" or (
            evidence["kind"] == "DOCUMENT" and not evidence["reference"].startswith("requirements:")
        ):
            reference_path = evidence["reference"].split("#", 1)[0]
            path: str | None = reference_path
            if evidence["kind"] == "DOCUMENT":
                match = re.fullmatch(r"([a-z][a-z0-9-]*):([^#]+)(?:#.*)?", evidence["reference"])
                if match:
                    path = repository_path(scope, match.group(1), match.group(2))
            if evidence["kind"] == "RUNTIME" and re.fullmatch(
                r"\.ai-sow/work/analyze-as-is/runtime-[a-z0-9]+(?:-[a-z0-9]+)*\.md",
                reference_path,
            ) is None:
                diagnostics.append(
                    diag(
                        "RUNTIME_EVIDENCE_PATH_INVALID",
                        f"RUNTIME Evidence must use an owned runtime record: {evidence['evidenceId']}",
                        reference_path,
                    )
                )
                continue
            try:
                payload = files.read_bytes(path) if path else None
            except ProjectIOError:
                payload = None
            if payload is None:
                diagnostics.append(
                    diag(
                        "ANCHOR_FILE_MISSING",
                        f"Evidence anchor file is unavailable: {evidence['evidenceId']}",
                        path or evidence["reference"],
                    )
                )
                continue
            inputs.append(
                Artifact(f"evidence:{evidence['evidenceId']}", "FILE", path, sha256_bytes(payload))
            )
            continue
        if evidence["kind"] not in ANCHOR_KINDS:
            continue
        match = re.fullmatch(r"([a-z][a-z0-9-]*):([^#]+)(?:#.*)?", evidence["reference"])
        path = repository_path(scope, match.group(1), match.group(2)) if match else None
        try:
            payload = files.read_bytes(path) if path else None
        except ProjectIOError:
            payload = None
        if payload is None:
            diagnostics.append(
                diag("ANCHOR_FILE_MISSING", f"Evidence anchor file is unavailable: {evidence['evidenceId']}", path or evidence["reference"])
            )
            continue
        inputs.append(Artifact(f"evidence:{evidence['evidenceId']}", "FILE", path, sha256_bytes(payload)))
    inputs.append(questionnaire)
    return diagnostics, tuple(inputs)


def requirement_ids_from_upstream(
    files: ProjectFiles,
) -> tuple[set[str], set[str], list[dict[str, object]]]:
    try:
        value = files.read_json(REQUIREMENTS_PATH)
        features = value["features"] if isinstance(value, dict) else None
        if not isinstance(features, list):
            raise (KeyError("features"))
        ids = {entry["featureId"] for entry in features if isinstance(entry, dict) and isinstance(entry.get("featureId"), str)}
        if len(ids) != len(features):
            raise KeyError("featureId")
        requirement_ids = set(ids)
        for collection, field in (
            ("sourceDocuments", "sourceDocumentId"),
            ("normalizedItems", "normalizedItemId"),
            ("epics", "epicId"),
        ):
            entries = value.get(collection)
            if not isinstance(entries, list):
                raise KeyError(collection)
            values = {
                entry[field]
                for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get(field), str)
            }
            if len(values) != len(entries):
                raise KeyError(field)
            requirement_ids.update(values)
        return ids, requirement_ids, []
    except (ProjectIOError, KeyError, TypeError):
        return set(), set(), [
            {
                "code": "UPSTREAM_HANDOFF_INVALID",
                "message": "upstream requirements output lacks its contracted Feature identifiers",
                "upstreamOwner": "analyze-requirement",
                "path": REQUIREMENTS_PATH,
            }
        ]


def load_candidate(
    files: ProjectFiles,
    relative_path: str,
    schema: dict[str, Any],
) -> tuple[bytes | None, dict[str, Any] | None, list[dict[str, object]]]:
    try:
        payload = files.read_bytes(relative_path)
        value = json.loads(payload.decode("utf-8"))
    except (ProjectIOError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None, [diag("CANDIDATE_UNREADABLE", "As-Is candidate is unavailable", relative_path)]
    diagnostics = [
        diag("SCHEMA_INVALID", error.message, "/" + "/".join(str(part) for part in error.path))
        for error in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path))
    ]
    return payload, value if isinstance(value, dict) else None, diagnostics


def write_failure(files: ProjectFiles, diagnostics: list[dict[str, object]]) -> None:
    files.write_atomic(
        VALIDATION_PATH,
        canonical_json_bytes({"owner": SUBJECT, "passed": False, "diagnostics": diagnostics}),
    )


def risk_summary_bytes(data: dict[str, Any], candidate_hash: str) -> bytes:
    status_counts = Counter(entry["status"] for entry in data["topicAssessments"])
    estimate_uncertainties = [
        entry for entry in data["uncertainties"] if entry["affectsEstimate"] is True
    ]

    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", "<br>")

    summary = (
        "# As-Is 风险摘要\n\n"
        f"Candidate SHA-256: {candidate_hash}\n"
        f"Topic Count: {len(data['topicAssessments'])}\n"
        f"ASSESSED Topics: {status_counts.get('ASSESSED', 0)}\n"
        f"NOT_APPLICABLE Topics: {status_counts.get('NOT_APPLICABLE', 0)}\n"
        f"INSUFFICIENT_EVIDENCE Topics: {status_counts.get('INSUFFICIENT_EVIDENCE', 0)}\n"
        f"Evidence Count: {len(data['evidence'])}\n"
        f"Estimate-affecting Uncertainties: {len(estimate_uncertainties)}\n"
    )
    if estimate_uncertainties:
        summary += (
            "\n## 影响估算的不确定性\n\n"
            "| ID | Topic | 问题 | 影响 | 负责人 | 建议处理 |\n"
            "|---|---|---|---|---|---|\n"
        )
        summary += "".join(
            "| "
            + " | ".join(
                cell(entry[key])
                for key in (
                    "uncertaintyId",
                    "topic",
                    "question",
                    "impact",
                    "owner",
                    "recommendedHandling",
                )
            )
            + " |\n"
            for entry in estimate_uncertainties
        )
    return summary.encode("utf-8")


def file_entry(name: str, path: str, payload: bytes) -> dict[str, object]:
    return {"name": name, "path": path, "sha256": sha256_bytes(payload)}


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
                **file_entry("asIs", candidate_path, candidate_payload),
                "targetPath": STABLE_PATH,
            }
        ],
        "context": context,
        "inputArtifacts": [input_entry(artifact) for artifact in inputs],
        "owner": SUBJECT,
        "review": {
            "path": review_path,
            "sha256": sha256_bytes(review_payload),
        },
        "riskSummary": {
            "path": risk_summary_path,
            "sha256": sha256_bytes(risk_summary_payload),
        },
        "status": "READY_FOR_REVIEW",
        "validatorContractVersion": VALIDATOR_CONTRACT_VERSION,
    }


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
        return None, None, [
            diag(missing_code, f"required canonical JSON is unavailable: {path}", path)
        ]
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, [diag(invalid_code, f"canonical JSON is invalid: {path}", path)]
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        return None, None, [
            diag(invalid_code, f"canonical JSON bytes are invalid: {path}", path)
        ]
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
    if set(manifest) != {
        "algorithm",
        "fragments",
        "inputArtifacts",
        "owner",
        "selectedEvidenceIds",
        "selectedTopicIds",
        "selectionRule",
    }:
        diagnostics.append(
            diag(
                "CONTEXT_MANIFEST_INVALID",
                "context manifest fields do not match the current contract",
                CONTEXT_MANIFEST_PATH,
            )
        )
    if manifest.get("algorithm") != "ai-sow-analyze-as-is-context-v1":
        diagnostics.append(
            diag("CONTEXT_MANIFEST_INVALID", "context manifest algorithm is invalid", CONTEXT_MANIFEST_PATH)
        )
    if manifest.get("owner") != SUBJECT:
        diagnostics.append(
            diag("CONTEXT_MANIFEST_INVALID", "context manifest owner is invalid", CONTEXT_MANIFEST_PATH)
        )
    if manifest.get("inputArtifacts") != [input_entry(artifact) for artifact in inputs]:
        diagnostics.append(
            diag(
                "CONTEXT_INPUT_STALE",
                "context manifest inputs do not match current Owner inputs",
                CONTEXT_MANIFEST_PATH,
            )
        )
    fragments = manifest.get("fragments")
    if not isinstance(fragments, list):
        diagnostics.append(
            diag("CONTEXT_MANIFEST_INVALID", "context manifest fragments must be an ordered array", CONTEXT_MANIFEST_PATH)
        )
        return None, diagnostics
    expected_fragments: list[dict[str, object]] = []
    for name, path in CONTEXT_FRAGMENT_SPECS:
        try:
            payload = files.read_bytes(path)
        except ProjectIOError:
            diagnostics.append(diag("CONTEXT_FRAGMENT_MISSING", "context fragment is unavailable", path))
            continue
        expected_fragments.append(
            {
                "bytes": len(payload),
                "name": name,
                "path": path,
                "sha256": sha256_bytes(payload),
            }
        )
    if fragments != expected_fragments:
        diagnostics.append(
            diag(
                "CONTEXT_FRAGMENT_STALE",
                "context fragment hashes do not match the current manifest",
                CONTEXT_MANIFEST_PATH,
            )
        )
    if diagnostics:
        return None, diagnostics
    return (
        {
            "fragments": expected_fragments,
            "manifest": file_entry("manifest", CONTEXT_MANIFEST_PATH, manifest_payload),
        },
        [],
    )


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
    if value != expected:
        return [diag(invalid_code, f"binding does not match the current review packet: {path}", path)]
    return []


def approved_packet_diagnostics(
    files: ProjectFiles,
    *,
    packet_path: str,
    expected_packet: dict[str, object],
    review_path: str,
    risk_summary_path: str,
    candidate_path: str,
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
        diagnostics.append(
            diag("REVIEW_PACKET_INVALID", "review packet fields do not match the current contract", packet_path)
        )
    for key, code, message, path in (
        (
            "candidateOutputs",
            "REVIEW_PACKET_CANDIDATE_STALE",
            "review packet candidate hash does not match current candidate bytes",
            candidate_path,
        ),
        (
            "context",
            "REVIEW_PACKET_CONTEXT_STALE",
            "review packet context hashes do not match current context fragments",
            CONTEXT_MANIFEST_PATH,
        ),
        (
            "review",
            "REVIEW_PACKET_REVIEW_STALE",
            "review packet review hash does not match current review bytes",
            review_path,
        ),
        (
            "inputArtifacts",
            "REVIEW_PACKET_INPUT_STALE",
            "review packet inputs do not match current Owner inputs",
            packet_path,
        ),
        (
            "riskSummary",
            "REVIEW_PACKET_RISK_SUMMARY_STALE",
            "review packet risk summary does not match current deterministic summary",
            risk_summary_path,
        ),
    ):
        if packet.get(key) != expected_packet[key]:
            diagnostics.append(diag(code, message, path))
    for key in ("algorithm", "owner", "status", "validatorContractVersion"):
        if packet.get(key) != expected_packet[key]:
            diagnostics.append(
                diag("REVIEW_PACKET_INVALID", f"review packet field is invalid: {key}", packet_path)
            )
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
                    "summary": "As-Is data is invalid",
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
        handoff = requirement_handoff(files)
        if args.mode == "upstream-check":
            diagnostics = list(handoff.diagnostics)
            print(
                json.dumps(
                    {
                        "outcome": "BLOCKED" if diagnostics else "OK",
                        "summary": (
                            "analyze-requirement handoff is invalid"
                            if diagnostics
                            else "analyze-requirement handoff is valid"
                        ),
                        "diagnostics": diagnostics,
                        "outputs": [],
                    },
                    ensure_ascii=False,
                )
            )
            return 2 if diagnostics else 0
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "contracts/asis.schema.json").read_text(encoding="utf-8")
        )
        no_change = (
            args.mode in {"review", "publish-approved", "rebind"}
            and declares_no_change(files, args.review_path)
        )
        diagnostics: list[dict[str, object]] = list(handoff.diagnostics)
        relative = STABLE_PATH if args.mode == "rebind" else args.candidate
        payload, data, local_diagnostics = load_candidate(files, relative, schema)
        if not diagnostics:
            diagnostics.extend(local_diagnostics)
        inputs: tuple[Artifact, ...] = ()
        if not diagnostics and data is not None:
            feature_ids, requirement_ids, upstream_diagnostics = requirement_ids_from_upstream(files)
            diagnostics.extend(upstream_diagnostics)
            if not diagnostics:
                diagnostics.extend(validate_semantics(data, feature_ids, requirement_ids))
                review_diagnostics, questionnaire = validate_review(
                    files,
                    data,
                    require_no_change=no_change,
                    review_path=args.review_path,
                )
                diagnostics.extend(review_diagnostics)
                if questionnaire is not None:
                    input_diagnostics, inputs = attest_inputs(files, data, questionnaire)
                    diagnostics.extend(input_diagnostics)
                    if not diagnostics and no_change and payload is not None:
                        try:
                            validate_no_change_candidate(
                                files,
                                CONTRACT,
                                inputs,
                                {"asIs": payload},
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
            context, context_diagnostics = context_packet_entry(files, inputs)
            diagnostics.extend(context_diagnostics)
            if not diagnostics:
                try:
                    review_payload = files.read_bytes(args.review_path)
                except ProjectIOError:
                    diagnostics.append(
                        diag("REVIEW_MISSING", "As-Is review candidate is unavailable", args.review_path)
                    )
            if review_payload is not None and context is not None:
                summary_payload = risk_summary_bytes(data, sha256_bytes(payload))
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
                            review_path=args.review_path,
                            risk_summary_path=args.risk_summary_path,
                            candidate_path=args.candidate,
                            reviewer_path=args.reviewer_path,
                            approval_path=args.approval_path,
                        )
                    )
        report: dict[str, object] | None = None
        if not diagnostics:
            try:
                if args.mode == "publish":
                    assert payload is not None
                    report = publish_owner(files, CONTRACT, inputs, {"asIs": payload})
                elif args.mode == "publish-approved":
                    assert payload is not None and review_payload is not None
                    files.write_atomic(REVIEW_PATH, review_payload)
                    publisher = publish_no_change_owner if no_change else publish_owner
                    report = publisher(files, CONTRACT, inputs, {"asIs": payload})
                elif args.mode == "rebind":
                    report = rebind_owner(files, CONTRACT, inputs)
            except ProjectIOError as error:
                diagnostics.append(diag(error.code, str(error), error.relative_path))
        if diagnostics and args.mode in {"publish", "rebind"}:
            write_failure(files, diagnostics)
        if diagnostics:
            outcome = "BLOCKED"
            summary = "As-Is data is invalid"
            outputs: list[str] = []
        elif args.mode == "review":
            outcome = "REVIEW_REQUIRED"
            summary = "As-Is review packet is ready"
            outputs = [args.risk_summary_path, args.packet_path]
        else:
            outcome = "OK"
            summary = "As-Is data is valid"
            outputs = (
                [STABLE_PATH, VALIDATION_PATH]
                if args.mode in {"publish", "publish-approved", "rebind"}
                else []
            )
        result: dict[str, object] = {
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
        print(
            json.dumps(
                {
                    "outcome": "BLOCKED",
                    "summary": "As-Is validation could not run",
                    "diagnostics": [diag(getattr(error, "code", "VALIDATOR_BLOCKED"), str(error))],
                    "outputs": [],
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
