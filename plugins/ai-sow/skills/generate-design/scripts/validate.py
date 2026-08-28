from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


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

from review_gates import validate_design_gates
from runtime.diagnostics import diagnostic as diag
from runtime.controls import validate_manifest_controls
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
from runtime.review_checks import validate_review_artifacts


SUBJECT = "generate-design"
DESIGN_SCHEMA_ID = "urn:ai-sow:generate-design:design:0.2"
TECHNICAL_SCHEMA_ID = "urn:ai-sow:generate-design:technical-requirements:0.2"
PROJECT_PATH = ".ai-sow/project.json"
REQUIREMENTS_PATH = ".ai-sow/data/analyze-requirement/requirements.json"
REQUIREMENTS_VALIDATION_PATH = ".ai-sow/validation/analyze-requirement.json"
REQUIREMENTS_REVIEW_PATH = ".ai-sow/reviews/analyze-requirement.md"
REQUIREMENTS_QUESTIONNAIRE_PATH = ".ai-sow/reviews/analyze-requirement-questionnaire.md"
ASIS_PATH = ".ai-sow/data/analyze-as-is/asis.json"
ASIS_VALIDATION_PATH = ".ai-sow/validation/analyze-as-is.json"
ASIS_REVIEW_PATH = ".ai-sow/reviews/analyze-as-is.md"
ASIS_QUESTIONNAIRE_PATH = ".ai-sow/work/analyze-as-is/questionnaire.md"
REVIEW_PATH = ".ai-sow/reviews/generate-design.md"
DESIGN_PATH = ".ai-sow/data/generate-design/design.json"
TECHNICAL_PATH = ".ai-sow/data/generate-design/requirements.json"
VALIDATION_PATH = ".ai-sow/validation/generate-design.json"
PACKET_PATH = ".ai-sow/work/generate-design/review-packet.json"
RISK_SUMMARY_PATH = ".ai-sow/work/generate-design/risk-summary.md"
REVIEWER_PATH = ".ai-sow/work/generate-design/reviewer.json"
APPROVAL_PATH = ".ai-sow/work/generate-design/approval.json"
CONTEXT_MANIFEST_PATH = ".ai-sow/work/generate-design/context/manifest.json"
CONTEXT_FRAGMENT_SPECS = (
    ("businessRequirements", ".ai-sow/work/generate-design/context/business-requirements.json"),
    ("asIsCoverage", ".ai-sow/work/generate-design/context/as-is-coverage.json"),
    ("uncertainties", ".ai-sow/work/generate-design/context/uncertainties.json"),
    ("effectiveStart", ".ai-sow/work/generate-design/context/effective-start.json"),
    ("sourceAnchors", ".ai-sow/work/generate-design/context/source-anchors.json"),
    ("claims", ".ai-sow/work/generate-design/claims.json"),
)
CLAIMS_PATH = ".ai-sow/work/generate-design/claims.json"
REVIEW_PACKET_ALGORITHM = "ai-sow-owner-review-packet-v1"
REVIEWER_ALGORITHM = "ai-sow-owner-reviewer-v1"
APPROVAL_ALGORITHM = "ai-sow-owner-approval-v1"
REQUIRED_REVIEW_SECTIONS = (
    "目标设计",
    "Architecture Delta",
    "Design Decision",
    "Scope",
    "TECHNICAL requirements",
    "高阶设计覆盖门禁",
    "上线范围门禁",
    "审查与批准",
)
ANCHOR_KINDS = {"CODE", "CONTRACT", "CONFIGURATION", "DEPLOYMENT"}
TYPED_DECISION_KINDS = {
    "INTEGRATION_BOUNDARY",
    "PROVIDER_TARGET",
    "OPERATIONAL_THRESHOLD",
    "ENVIRONMENT_AUTHORITY",
    "CUTOVER_ROLLBACK",
}
DERIVED_RATIONALE_PATTERN = re.compile(
    r"^设计决策/Decision\s*[:：]\s*(?P<decision>[^；;\r\n]+)[；;]\s*"
    r"产生原因/Cause\s*[:：]\s*(?P<cause>[^；;\r\n]+)[；;]\s*"
    r"不交付影响/Non-delivery impact\s*[:：]\s*"
    r"(?P<category>流程/Process|接口/API|质量属性/Quality attribute|责任边界/Responsibility boundary)"
    r"\s*\|\s*(?P<target>[^|\r\n]+?)\s*->\s*(?P<impact>[^\r\n]+)$"
)
STABLE_ID_PATTERN = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
GENERIC_IMPACT_TARGETS = {"业务", "功能", "模块", "系统", "business", "feature", "module", "system"}
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

REQUIREMENT_CONTRACT = OwnerContract(
    subject="analyze-requirement",
    contract_ids=("urn:ai-sow:analyze-requirement:source-requirements:0.1",),
    validation_path=REQUIREMENTS_VALIDATION_PATH,
    reviews=(("approvedReview", REQUIREMENTS_REVIEW_PATH),),
    outputs=(("requirements", REQUIREMENTS_PATH),),
)
ASIS_CONTRACT = OwnerContract(
    subject="analyze-as-is",
    contract_ids=("urn:ai-sow:analyze-as-is:asis:0.2",),
    validation_path=ASIS_VALIDATION_PATH,
    reviews=(("approvedReview", ASIS_REVIEW_PATH),),
    outputs=(("asIs", ASIS_PATH),),
)
CONTRACT = OwnerContract(
    subject=SUBJECT,
    contract_ids=(DESIGN_SCHEMA_ID, TECHNICAL_SCHEMA_ID),
    validation_path=VALIDATION_PATH,
    reviews=(("approvedReview", REVIEW_PATH),),
    outputs=(("design", DESIGN_PATH), ("technicalRequirements", TECHNICAL_PATH)),
    claims_path=CLAIMS_PATH,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and publish Design handoff data")
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
    parser.add_argument("--candidate", default=".ai-sow/work/generate-design/design.candidate.json")
    parser.add_argument(
        "--requirements-candidate",
        default=".ai-sow/work/generate-design/requirements.candidate.json",
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


def declaration(text: str, label: str) -> list[str]:
    return re.findall(rf"(?m)^{re.escape(label)}\s*:\s*(.+?)\s*$", text)


def declares_no_change(files: ProjectFiles, review_path: str) -> bool:
    try:
        text = files.read_bytes(review_path).decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError):
        return False
    return declaration(text, "Impact") == ["NO_CHANGE"]


def split_values(value: str) -> list[str]:
    return [part for part in re.split(r"[,，、;；\s]+", value) if part]


def receipt_input_hash(files: ProjectFiles, validation_path: str, name: str) -> str | None:
    try:
        report = files.read_json(validation_path)
    except ProjectIOError:
        return None
    receipt = report.get("compilationReceipt") if isinstance(report, dict) else None
    entries = receipt.get("inputs") if isinstance(receipt, dict) else None
    if not isinstance(entries, list):
        return None
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("name") == name]
    value = matches[0].get("sha256") if len(matches) == 1 else None
    return value if isinstance(value, str) and HASH_PATTERN.fullmatch(value) else None


def current_file_hash(
    files: ProjectFiles,
    path: str,
    validation_path: str,
    name: str,
) -> str:
    try:
        return sha256_bytes(files.read_bytes(path))
    except ProjectIOError:
        return receipt_input_hash(files, validation_path, name) or "0" * 64


def upstream_failure(owner: str, path: str, message: str) -> MatchResult:
    return MatchResult(
        False,
        ({"code": "UPSTREAM_HANDOFF_INVALID", "message": message, "upstreamOwner": owner, "path": path},),
        None,
    )


def read_review(files: ProjectFiles, path: str) -> str:
    try:
        return files.read_bytes(path).decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError):
        return ""


def current_requirement_inputs(files: ProjectFiles) -> tuple[tuple[Artifact, ...], MatchResult | None]:
    try:
        requirements = files.read_json(REQUIREMENTS_PATH)
    except ProjectIOError:
        return (), upstream_failure("analyze-requirement", REQUIREMENTS_PATH, "requirements output is unavailable")
    sources = requirements.get("sourceDocuments") if isinstance(requirements, dict) else None
    if not isinstance(sources, list):
        return (), upstream_failure("analyze-requirement", REQUIREMENTS_PATH, "requirements source input contract is invalid")
    artifacts: list[Artifact] = [
        Artifact(
            "project",
            "FILE",
            PROJECT_PATH,
            current_file_hash(files, PROJECT_PATH, REQUIREMENTS_VALIDATION_PATH, "project"),
        )
    ]
    names: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not all(isinstance(source.get(field), str) for field in ("sourceDocumentId", "file")):
            return (), upstream_failure("analyze-requirement", REQUIREMENTS_PATH, "source document contract is invalid")
        name = f"source:{source['sourceDocumentId']}"
        if name in names:
            return (), upstream_failure("analyze-requirement", REQUIREMENTS_PATH, "source input names are not unique")
        names.add(name)
        artifacts.append(
            Artifact(
                name,
                "FILE",
                source["file"],
                current_file_hash(files, source["file"], REQUIREMENTS_VALIDATION_PATH, name),
            )
        )
    questionnaire = declaration(read_review(files, REQUIREMENTS_REVIEW_PATH), "Questionnaire")
    if questionnaire == ["NOT_REQUIRED"]:
        try:
            current = files.read_bytes(REQUIREMENTS_QUESTIONNAIRE_PATH)
        except ProjectIOError:
            logical = canonical_json_bytes({"declaration": "NOT_REQUIRED"})
        else:
            logical = canonical_json_bytes({"declaration": "PRESENT", "sha256": sha256_bytes(current)})
        artifacts.append(Artifact("questionnaire", "QUESTIONNAIRE_PRESENCE", "questionnaire:NOT_REQUIRED", sha256_bytes(logical)))
    elif questionnaire == [REQUIREMENTS_QUESTIONNAIRE_PATH]:
        artifacts.append(
            Artifact(
                "questionnaire",
                "QUESTIONNAIRE_PRESENCE",
                f"questionnaire:{REQUIREMENTS_QUESTIONNAIRE_PATH}",
                current_file_hash(
                    files,
                    REQUIREMENTS_QUESTIONNAIRE_PATH,
                    REQUIREMENTS_VALIDATION_PATH,
                    "questionnaire",
                ),
            )
        )
    else:
        return (), upstream_failure("analyze-requirement", REQUIREMENTS_REVIEW_PATH, "questionnaire declaration is invalid")
    return tuple(artifacts), None


def repository_path(scope: dict[str, Any], repo_id: str, anchor: str) -> str | None:
    snapshots = scope.get("repositorySnapshots")
    if not isinstance(snapshots, list):
        return None
    snapshot = next((entry for entry in snapshots if isinstance(entry, dict) and entry.get("repoId") == repo_id), None)
    if snapshot is None or not isinstance(snapshot.get("path"), str):
        return None
    return anchor if snapshot["path"] == "." else f"{snapshot['path']}/{anchor}"


def current_asis_inputs(files: ProjectFiles) -> tuple[tuple[Artifact, ...], MatchResult | None]:
    try:
        asis = files.read_json(ASIS_PATH)
    except ProjectIOError:
        return (), upstream_failure("analyze-as-is", ASIS_PATH, "As-Is output is unavailable")
    scope = asis.get("analysisScope") if isinstance(asis, dict) else None
    evidence = asis.get("evidence") if isinstance(asis, dict) else None
    if not isinstance(scope, dict) or not isinstance(evidence, list):
        return (), upstream_failure("analyze-as-is", ASIS_PATH, "As-Is input contract is invalid")
    artifacts: list[Artifact] = []
    for name, path in (
        ("project", PROJECT_PATH),
        ("requirementsValidation", REQUIREMENTS_VALIDATION_PATH),
        ("requirements", REQUIREMENTS_PATH),
    ):
        artifacts.append(Artifact(name, "FILE", path, current_file_hash(files, path, ASIS_VALIDATION_PATH, name)))
    repositories = scope.get("repositorySnapshots")
    prior_sows = scope.get("priorSowSnapshots")
    if not isinstance(repositories, list) or not isinstance(prior_sows, list):
        return (), upstream_failure("analyze-as-is", ASIS_PATH, "As-Is registered input contract is invalid")
    for snapshot in repositories:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("repoId"), str):
            return (), upstream_failure("analyze-as-is", ASIS_PATH, "repository snapshot contract is invalid")
        repo_id = snapshot["repoId"]
        artifacts.append(Artifact(f"repository:{repo_id}", "CANONICAL_JSON", f"repository:{repo_id}", sha256_bytes(canonical_json_bytes(snapshot))))
    for snapshot in prior_sows:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("priorSowId"), str) or not isinstance(snapshot.get("file"), str):
            return (), upstream_failure("analyze-as-is", ASIS_PATH, "prior SOW snapshot contract is invalid")
        name = f"priorSow:{snapshot['priorSowId']}"
        artifacts.append(Artifact(name, "FILE", snapshot["file"], current_file_hash(files, snapshot["file"], ASIS_VALIDATION_PATH, name)))
    evidence_names: set[str] = set()
    for entry in evidence:
        if not isinstance(entry, dict) or not isinstance(entry.get("evidenceId"), str) or not isinstance(entry.get("kind"), str) or not isinstance(entry.get("reference"), str):
            return (), upstream_failure("analyze-as-is", ASIS_PATH, "Evidence input contract is invalid")
        evidence_id = entry["evidenceId"]
        name = f"evidence:{evidence_id}"
        path: str | None = None
        if entry["kind"] == "RUNTIME" or (
            entry["kind"] == "DOCUMENT"
            and not entry["reference"].startswith("requirements:")
        ):
            path = entry["reference"].split("#", 1)[0]
            if entry["kind"] == "DOCUMENT":
                match = re.fullmatch(
                    r"([a-z][a-z0-9-]*):([^#]+)(?:#.*)?",
                    entry["reference"],
                )
                if match:
                    path = repository_path(scope, match.group(1), match.group(2))
        elif entry["kind"] in ANCHOR_KINDS:
            match = re.fullmatch(r"([a-z][a-z0-9-]*):([^#]+)(?:#.*)?", entry["reference"])
            path = repository_path(scope, match.group(1), match.group(2)) if match else None
        if path is None:
            continue
        if name in evidence_names:
            return (), upstream_failure("analyze-as-is", ASIS_PATH, "Evidence input names are not unique")
        evidence_names.add(name)
        artifacts.append(Artifact(name, "FILE", path, current_file_hash(files, path, ASIS_VALIDATION_PATH, name)))
    questionnaire = declaration(read_review(files, ASIS_REVIEW_PATH), "Questionnaire")
    if questionnaire == ["NOT_REQUIRED"]:
        try:
            current = files.read_bytes(ASIS_QUESTIONNAIRE_PATH)
        except ProjectIOError:
            logical = canonical_json_bytes({"declaration": "NOT_REQUIRED"})
        else:
            logical = canonical_json_bytes({"declaration": "PRESENT", "sha256": sha256_bytes(current)})
        artifacts.append(Artifact("questionnaire", "QUESTIONNAIRE_PRESENCE", "questionnaire:NOT_REQUIRED", sha256_bytes(logical)))
    elif questionnaire == [ASIS_QUESTIONNAIRE_PATH]:
        artifacts.append(
            Artifact(
                "questionnaire",
                "QUESTIONNAIRE_PRESENCE",
                f"questionnaire:{ASIS_QUESTIONNAIRE_PATH}",
                current_file_hash(files, ASIS_QUESTIONNAIRE_PATH, ASIS_VALIDATION_PATH, "questionnaire"),
            )
        )
    else:
        return (), upstream_failure("analyze-as-is", ASIS_REVIEW_PATH, "questionnaire declaration is invalid")
    return tuple(artifacts), None


def owner_handoff(files: ProjectFiles, contract: OwnerContract, builder: Any) -> MatchResult:
    expected, failure = builder(files)
    result = match_owner(files, contract, expected)
    if not result.ok:
        return result
    return failure or result


def load_upstream(files: ProjectFiles) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, object]]]:
    try:
        source = files.read_json(REQUIREMENTS_PATH)
        asis = files.read_json(ASIS_PATH)
    except ProjectIOError:
        return None, None, [diag("UPSTREAM_HANDOFF_INVALID", "upstream stable output is unreadable")]
    if not isinstance(source, dict) or not isinstance(asis, dict):
        return None, None, [diag("UPSTREAM_HANDOFF_INVALID", "upstream stable output must be an object")]
    for owner, value, collections in (
        ("analyze-requirement", source, (("sourceDocuments", "sourceDocumentId"), ("epics", "epicId"), ("features", "featureId"))),
        ("analyze-as-is", asis, (("effectiveStartItems", "effectiveStartItemId"), ("commitments", "commitmentId"), ("uncertainties", "uncertaintyId"), ("evidence", "evidenceId"))),
    ):
        for collection, field in collections:
            entries = value.get(collection)
            if not isinstance(entries, list) or any(not isinstance(entry, dict) or not isinstance(entry.get(field), str) for entry in entries):
                return None, None, [{
                    "code": "UPSTREAM_HANDOFF_INVALID",
                    "message": f"upstream output lacks contracted {field} values",
                    "upstreamOwner": owner,
                    "path": REQUIREMENTS_PATH if owner == "analyze-requirement" else ASIS_PATH,
                }]
    return source, asis, []


def load_candidate(
    files: ProjectFiles,
    relative_path: str,
    schema: dict[str, Any],
    label: str,
) -> tuple[bytes | None, dict[str, Any] | None, list[dict[str, object]]]:
    try:
        payload = files.read_bytes(relative_path)
        value = json.loads(payload.decode("utf-8"))
    except (ProjectIOError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None, [diag("CANDIDATE_UNREADABLE", f"{label} candidate is unavailable", relative_path)]
    diagnostics = [
        diag("SCHEMA_INVALID", f"{label}: {error.message}", "/" + "/".join(str(part) for part in error.path))
        for error in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path))
    ]
    return payload, value if isinstance(value, dict) else None, diagnostics


def normalized_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def significant_length(value: str) -> int:
    return len(re.sub(r"[^\w]+", "", value, flags=re.UNICODE))


def replace_entities(value: str, entities: list[str]) -> str:
    normalized = normalized_text(value)
    for entity in sorted({normalized_text(entry) for entry in entities if entry}, key=len, reverse=True):
        normalized = normalized.replace(entity, "<entity>")
    return normalized


def rationale_template_signature(
    feature: dict[str, Any],
    clauses: re.Match[str],
    decision_titles: dict[str, str],
) -> tuple[str, str, str, str]:
    source = feature["source"]
    entities = [
        feature["featureId"],
        feature["name"],
        *source["designDecisionIds"],
        *(decision_titles.get(reference, "") for reference in source["designDecisionIds"]),
    ]
    return (
        replace_entities(clauses.group("decision"), entities),
        replace_entities(clauses.group("cause"), entities),
        normalized_text(clauses.group("category")),
        replace_entities(clauses.group("impact"), entities),
    )


def validate_semantics(
    design: dict[str, Any],
    technical: dict[str, Any],
    source: dict[str, Any],
    asis: dict[str, Any],
) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    source_document_ids = {entry["sourceDocumentId"] for entry in source["sourceDocuments"]}
    source_epic_ids = {entry["epicId"] for entry in source["epics"]}
    source_feature_ids = {entry["featureId"] for entry in source["features"]}
    start_ids = {entry["effectiveStartItemId"] for entry in asis["effectiveStartItems"]}
    evidence_ids = {entry["evidenceId"] for entry in asis["evidence"]}
    technical_epic_ids = {entry["epicId"] for entry in technical["epics"]}
    technical_feature_ids = {entry["featureId"] for entry in technical["features"]}
    design_item_ids = {entry["designItemId"] for entry in design["designItems"]}
    decision_ids = {entry["designDecisionId"] for entry in design["decisions"]}
    decision_titles = {entry["designDecisionId"]: entry["name"] for entry in design["decisions"]}
    all_ids = [
        *source_epic_ids,
        *source_feature_ids,
        *(entry["epicId"] for entry in technical["epics"]),
        *(entry["featureId"] for entry in technical["features"]),
        *(entry["designItemId"] for entry in design["designItems"]),
        *(entry["architectureDeltaId"] for entry in design["architectureDeltas"]),
        *(entry["designDecisionId"] for entry in design["decisions"]),
    ]
    for value, count in Counter(all_ids).items():
        if count > 1:
            diagnostics.append(diag("ID_DUPLICATE", f"duplicate stable ID: {value}"))

    for delta in design["architectureDeltas"]:
        if delta["designItemId"] not in design_item_ids:
            diagnostics.append(diag("DESIGN_ITEM_REF_UNKNOWN", f"unknown designItemId: {delta['designItemId']}"))
        for reference in delta["effectiveStartItemIds"]:
            if reference not in start_ids:
                diagnostics.append(diag("EFFECTIVE_START_REF_UNKNOWN", f"unknown effectiveStartItemId: {reference}"))

    decisions_by_feature: dict[str, list[dict[str, Any]]] = {}
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
            decisions_by_feature.setdefault(reference, []).append(decision)
        for reference in decision["evidenceIds"]:
            if reference not in evidence_ids:
                diagnostics.append(diag("EVIDENCE_REF_UNKNOWN", f"unknown Evidence: {reference}"))
        if decision["decisionKind"] in TYPED_DECISION_KINDS and not decision["evidenceIds"]:
            diagnostics.append(diag("DECISION_EVIDENCE_REQUIRED", f"typed Design Decision requires Evidence: {decision['designDecisionId']}"))

    for requirement in [*technical["epics"], *technical["features"]]:
        provenance = requirement["source"]
        if provenance["type"] == "SOURCE_INPUT":
            for reference in provenance["sourceDocumentIds"]:
                if reference not in source_document_ids:
                    diagnostics.append(diag("SOURCE_DOCUMENT_REF_UNKNOWN", f"unknown registered sourceDocumentId: {reference}"))
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

    referenced_epics: set[str] = set()
    for feature in technical["features"]:
        referenced_epics.add(feature["epicId"])
        if feature["epicId"] not in technical_epic_ids:
            diagnostics.append(diag("EPIC_REF_UNKNOWN", f"unknown technical epicId: {feature['epicId']}"))
        for reference in feature["relatedBusinessFeatureIds"]:
            if reference not in source_feature_ids:
                diagnostics.append(
                    diag(
                        "BUSINESS_FEATURE_REF_UNKNOWN",
                        f"unknown BUSINESS Feature: {reference}",
                    )
                )
    for epic_id in sorted(technical_epic_ids - referenced_epics):
        diagnostics.append(diag("EPIC_WITHOUT_FEATURE", f"technical Epic has no Feature: {epic_id}"))

    normalized_rationales: dict[str, str] = {}
    templates: dict[tuple[str, str, str, str], str] = {}
    for feature in technical["features"]:
        provenance = feature["source"]
        if provenance["type"] != "DESIGN_DERIVED":
            continue
        rationale = normalized_text(provenance["rationale"])
        if rationale in normalized_rationales:
            diagnostics.append(diag("DERIVED_RATIONALE_DUPLICATE", f"Features {normalized_rationales[rationale]} and {feature['featureId']} use the same rationale"))
        else:
            normalized_rationales[rationale] = feature["featureId"]
        clauses = DERIVED_RATIONALE_PATTERN.fullmatch(provenance["rationale"])
        if clauses is None:
            continue
        clause_ids = set(STABLE_ID_PATTERN.findall(normalized_text(clauses.group("decision"))))
        missing = [reference for reference in provenance["designDecisionIds"] if normalized_text(reference) not in clause_ids]
        if missing:
            diagnostics.append(diag("DERIVED_RATIONALE_DECISION_REF_MISSING", f"Feature {feature['featureId']} decision clause omits: {', '.join(missing)}"))
        detail = clauses.group("decision")
        for reference in provenance["designDecisionIds"]:
            detail = detail.replace(reference, "")
        if significant_length(detail) < 8:
            diagnostics.append(diag("DERIVED_RATIONALE_DECISION_GENERIC", f"Feature {feature['featureId']} decision clause lacks a concrete decision"))
        if significant_length(clauses.group("cause")) < 12:
            diagnostics.append(diag("DERIVED_RATIONALE_CAUSE_GENERIC", f"Feature {feature['featureId']} cause clause lacks a concrete reason"))
        target = normalized_text(clauses.group("target"))
        impact = normalized_text(clauses.group("impact"))
        if target in GENERIC_IMPACT_TARGETS or significant_length(target) < 3 or impact in GENERIC_IMPACTS or significant_length(impact) < 8:
            diagnostics.append(diag("DERIVED_RATIONALE_IMPACT_GENERIC", f"Feature {feature['featureId']} impact must name a concrete target and consequence"))
        signature = rationale_template_signature(feature, clauses, decision_titles)
        if signature in templates:
            diagnostics.append(diag("DERIVED_RATIONALE_TEMPLATE_DUPLICATE", f"Features {templates[signature]} and {feature['featureId']} use the same rationale template"))
        else:
            templates[signature] = feature["featureId"]

    for scope in design["scopeDecisions"]:
        if scope["decision"] != "IN_SCOPE":
            continue
        related = decisions_by_feature.get(scope["featureId"], [])
        required = set(scope["requiredDecisionKinds"])
        boundary = scope["requiredIntegrationBoundary"]
        if boundary != "NONE":
            required.add("INTEGRATION_BOUNDARY")
        present = {decision["decisionKind"] for decision in related}
        for kind in sorted(required - present):
            diagnostics.append(diag("SCOPE_OBLIGATION_MISSING", f"ScopeDecision {scope['featureId']} requires {kind}"))
        boundary_decisions = [decision for decision in related if decision["decisionKind"] == "INTEGRATION_BOUNDARY"]
        if boundary == "PORT_ONLY" and not any(decision.get("adapterCompletesDelivery") is True for decision in boundary_decisions):
            diagnostics.append(diag("SCOPE_OBLIGATION_MISSING", f"ScopeDecision {scope['featureId']} requires a port-complete integration decision"))
        if boundary == "END_TO_END" and any(decision.get("adapterCompletesDelivery") is True for decision in boundary_decisions):
            diagnostics.append(diag("SCOPE_INTEGRATION_BOUNDARY_INVALID", f"END_TO_END scope cannot stop at the adapter: {scope['featureId']}"))
    return diagnostics


def stable_ids(design: dict[str, Any], technical: dict[str, Any]) -> tuple[list[str], list[str]]:
    return (
        [
            *(entry["designItemId"] for entry in design["designItems"]),
            *(entry["architectureDeltaId"] for entry in design["architectureDeltas"]),
            *(entry["designDecisionId"] for entry in design["decisions"]),
        ],
        [
            *(entry["epicId"] for entry in technical["epics"]),
            *(entry["featureId"] for entry in technical["features"]),
        ],
    )


def previous_owner_receipt(files: ProjectFiles) -> dict[str, Any] | None:
    try:
        report = files.read_json(VALIDATION_PATH)
    except ProjectIOError:
        return None
    receipt = report.get("compilationReceipt") if isinstance(report, dict) and report.get("owner") == SUBJECT and report.get("passed") is True else None
    return receipt if isinstance(receipt, dict) else None


def named_hash(receipt: dict[str, Any] | None, name: str) -> str | None:
    entries = receipt.get("inputs") if isinstance(receipt, dict) else None
    if not isinstance(entries, list):
        return None
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("name") == name]
    value = matches[0].get("sha256") if len(matches) == 1 else None
    return value if isinstance(value, str) and HASH_PATTERN.fullmatch(value) else None


def parse_hash_map(value: str) -> dict[str, str] | None:
    result: dict[str, str] = {}
    for part in split_values(value):
        if "=" not in part:
            return None
        owner, digest = part.split("=", 1)
        if owner in result or owner not in {"analyze-requirement", "analyze-as-is"} or not HASH_PATTERN.fullmatch(digest):
            return None
        result[owner] = digest
    return result


def validate_review(
    files: ProjectFiles,
    design: dict[str, Any],
    technical: dict[str, Any],
    *,
    require_no_change: bool,
    review_path: str,
) -> tuple[list[dict[str, object]], str]:
    text = read_review(files, review_path)
    diagnostics: list[dict[str, object]] = []
    if not text:
        return [diag("REVIEW_MISSING", "approved Design review is unavailable", review_path)], text
    for section in REQUIRED_REVIEW_SECTIONS:
        if len(re.findall(rf"(?m)^## {re.escape(section)}\s*$", text)) != 1:
            diagnostics.append(diag("REVIEW_SECTION_INVALID", f"review must contain exactly one section: {section}", review_path))
    design_ids, technical_ids = stable_ids(design, technical)
    declared_design = declaration(text, "Design IDs")
    declared_technical = declaration(text, "Technical IDs")
    if len(declared_design) != 1 or split_values(declared_design[0]) != (design_ids or ["NONE"]):
        diagnostics.append(diag("REVIEW_ID_SET_MISMATCH", "review Design IDs do not match candidate", review_path))
    if len(declared_technical) != 1 or split_values(declared_technical[0]) != (technical_ids or ["NONE"]):
        diagnostics.append(diag("REVIEW_ID_SET_MISMATCH", "review Technical IDs do not match candidate", review_path))
    if declaration(text, "Reviewer") != ["PASS"]:
        diagnostics.append(diag("REVIEW_NOT_PASSED", "Reviewer must be PASS", review_path))
    if declaration(text, "User Approval") != ["APPROVED"]:
        diagnostics.append(diag("USER_APPROVAL_MISSING", "User Approval must be APPROVED", review_path))
    impacts = declaration(text, "Impact")
    if require_no_change and impacts != ["NO_CHANGE"]:
        diagnostics.append(diag("REVIEW_NO_CHANGE_MISSING", "NO_CHANGE 发布或 rebind 要求 review 声明 Impact: NO_CHANGE", review_path))
    elif not require_no_change and "NO_CHANGE" in impacts:
        diagnostics.append(diag("REVIEW_NO_CHANGE_MODE_INVALID", "Impact: NO_CHANGE 仅允许用于 NO_CHANGE 发布或 rebind", review_path))
    elif not require_no_change and impacts not in ([], ["CHANGED"]):
        diagnostics.append(diag("REVIEW_IMPACT_INVALID", "review Impact declaration is invalid", review_path))
    if require_no_change:
        previous = previous_owner_receipt(files)
        previous_hashes = {
            "analyze-requirement": named_hash(previous, "requirementsValidation"),
            "analyze-as-is": named_hash(previous, "asIsValidation"),
        }
        current_hashes = {
            "analyze-requirement": current_file_hash(files, REQUIREMENTS_VALIDATION_PATH, VALIDATION_PATH, "requirementsValidation"),
            "analyze-as-is": current_file_hash(files, ASIS_VALIDATION_PATH, VALIDATION_PATH, "asIsValidation"),
        }
        changed = [owner for owner in ("analyze-requirement", "analyze-as-is") if previous_hashes[owner] != current_hashes[owner]]
        upstream = declaration(text, "Upstream")
        if len(upstream) != 1 or split_values(upstream[0]) != changed:
            diagnostics.append(diag("REVIEW_UPSTREAM_INVALID", "NO_CHANGE review 的 Upstream 必须精确列出已变化的直接 Owner", review_path))
        previous_values = declaration(text, "Previous Receipt SHA-256")
        current_values = declaration(text, "Current Receipt SHA-256")
        expected_previous = {owner: previous_hashes[owner] for owner in changed}
        expected_current = {owner: current_hashes[owner] for owner in changed}
        if len(previous_values) != 1 or parse_hash_map(previous_values[0]) != expected_previous:
            diagnostics.append(diag("REVIEW_PREVIOUS_RECEIPT_MISMATCH", "review 中的旧上游 receipt hashes 无效", review_path))
        if len(current_values) != 1 or parse_hash_map(current_values[0]) != expected_current:
            diagnostics.append(diag("REVIEW_CURRENT_RECEIPT_MISMATCH", "review 中的当前上游 receipt hashes 无效", review_path))
        rationales = declaration(text, "Impact Rationale")
        rationale_ids = set(STABLE_ID_PATTERN.findall(rationales[0])) if len(rationales) == 1 else set()
        if len(rationales) != 1 or not set([*design_ids, *technical_ids]).issubset(rationale_ids):
            diagnostics.append(diag("REVIEW_IMPACT_RATIONALE_INVALID", "Impact Rationale 必须点名每个已确认的稳定 ID", review_path))
    return diagnostics, text


def owner_inputs(files: ProjectFiles) -> tuple[list[dict[str, object]], tuple[Artifact, ...]]:
    diagnostics: list[dict[str, object]] = []
    artifacts: list[Artifact] = []
    for name, path in (
        ("project", PROJECT_PATH),
        ("requirementsValidation", REQUIREMENTS_VALIDATION_PATH),
        ("requirements", REQUIREMENTS_PATH),
        ("asIsValidation", ASIS_VALIDATION_PATH),
        ("asIs", ASIS_PATH),
    ):
        try:
            payload = files.read_bytes(path)
        except ProjectIOError:
            diagnostics.append(diag("INPUT_MISSING", f"required input is unavailable: {path}", path))
        else:
            artifacts.append(Artifact(name, "FILE", path, sha256_bytes(payload)))
    return diagnostics, tuple(artifacts)


def input_entry(artifact: Artifact) -> dict[str, object]:
    return {"name": artifact.name, "kind": artifact.kind, "path": artifact.locator, "sha256": artifact.sha256}


def file_entry(name: str, path: str, payload: bytes) -> dict[str, object]:
    return {"name": name, "path": path, "sha256": sha256_bytes(payload)}


def risk_summary_bytes(
    design: dict[str, Any],
    technical: dict[str, Any],
    asis: dict[str, Any],
    design_hash: str,
    technical_hash: str,
) -> bytes:
    source_features = sum(
        1
        for entry in technical["features"]
        if entry.get("source", {}).get("type") == "SOURCE_INPUT"
    )
    derived_features = sum(
        1
        for entry in technical["features"]
        if entry.get("source", {}).get("type") == "DESIGN_DERIVED"
    )
    open_uncertainties = [
        entry
        for entry in asis.get("uncertainties", [])
        if isinstance(entry, dict) and entry.get("affectsEstimate") is True
    ]
    lines = [
        "# Design 风险摘要",
        "",
        f"Design Candidate SHA-256: {design_hash}",
        f"Technical Candidate SHA-256: {technical_hash}",
        f"Design Items: {len(design['designItems'])}",
        f"Architecture Deltas: {len(design['architectureDeltas'])}",
        f"Design Decisions: {len(design['decisions'])}",
        f"Scope Decisions: {len(design['scopeDecisions'])}",
        f"Technical Epics: {len(technical['epics'])}",
        f"Technical Features: {len(technical['features'])}",
        f"SOURCE_INPUT Features: {source_features}",
        f"DESIGN_DERIVED Features: {derived_features}",
        f"Estimate-affecting Uncertainties: {len(open_uncertainties)}",
        "HLD Authority: generate-design/scripts/review_gates.py",
        "",
    ]
    if open_uncertainties:
        lines.extend(
            [
                "## 阻塞估算的不确定项",
                "",
                "| ID | 问题 | 影响 |",
                "|---|---|---|",
                *[
                    "| "
                    + " | ".join(
                        str(entry.get(key, "")).replace("|", "\\|")
                        for key in ("uncertaintyId", "question", "impact")
                    )
                    + " |"
                    for entry in open_uncertainties
                ],
                "",
            ]
        )
    return "\n".join(lines).encode("utf-8")


def review_packet(
    *,
    design_path: str,
    design_payload: bytes,
    technical_path: str,
    technical_payload: bytes,
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
                **file_entry("design", design_path, design_payload),
                "targetPath": DESIGN_PATH,
            },
            {
                **file_entry(
                    "technicalRequirements", technical_path, technical_payload
                ),
                "targetPath": TECHNICAL_PATH,
            },
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
    expected_fields = {
        "algorithm",
        "claimMetrics",
        "fragments",
        "inputArtifacts",
        "owner",
        "ownerControl",
        "selectedEffectiveStartItemIds",
        "selectedFeatureIds",
    }
    if set(manifest) != expected_fields:
        diagnostics.append(
            diag(
                "CONTEXT_MANIFEST_INVALID",
                "context manifest fields do not match the current contract",
                CONTEXT_MANIFEST_PATH,
            )
        )
    if manifest.get("algorithm") != "ai-sow-generate-design-context-v1":
        diagnostics.append(
            diag(
                "CONTEXT_MANIFEST_INVALID",
                "context manifest algorithm is invalid",
                CONTEXT_MANIFEST_PATH,
            )
        )
    if manifest.get("owner") != SUBJECT:
        diagnostics.append(
            diag(
                "CONTEXT_MANIFEST_INVALID",
                "context manifest owner is invalid",
                CONTEXT_MANIFEST_PATH,
            )
        )
    diagnostics.extend(
        validate_manifest_controls(
            files,
            manifest,
            owner=SUBJECT,
            project_path=PROJECT_PATH,
            claims_path=CLAIMS_PATH,
            manifest_path=CONTEXT_MANIFEST_PATH,
        )
    )
    if manifest.get("inputArtifacts") != [input_entry(artifact) for artifact in inputs]:
        diagnostics.append(
            diag(
                "CONTEXT_INPUT_STALE",
                "context manifest inputs do not match current Owner inputs",
                CONTEXT_MANIFEST_PATH,
            )
        )
    expected_fragments: list[dict[str, object]] = []
    for name, path in CONTEXT_FRAGMENT_SPECS:
        try:
            payload = files.read_bytes(path)
        except ProjectIOError:
            diagnostics.append(
                diag("CONTEXT_FRAGMENT_MISSING", "context fragment is unavailable", path)
            )
            continue
        expected_fragments.append(
            {
                "bytes": len(payload),
                "name": name,
                "path": path,
                "sha256": sha256_bytes(payload),
            }
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
        files, path, missing_code=missing_code, invalid_code=invalid_code
    )
    if diagnostics:
        return diagnostics
    expected = {
        "algorithm": algorithm,
        "decision": decision,
        "owner": SUBJECT,
        "packetSha256": packet_hash,
    }
    return (
        []
        if value == expected
        else [
            diag(
                invalid_code,
                f"binding does not match the current review packet: {path}",
                path,
            )
        ]
    )


def approved_packet_diagnostics(
    files: ProjectFiles,
    *,
    packet_path: str,
    expected_packet: dict[str, object],
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
            diag(
                "REVIEW_PACKET_INVALID",
                "review packet fields do not match the current contract",
                packet_path,
            )
        )
    for key, code in (
        ("candidateOutputs", "REVIEW_PACKET_CANDIDATE_STALE"),
        ("context", "REVIEW_PACKET_CONTEXT_STALE"),
        ("inputArtifacts", "REVIEW_PACKET_INPUT_STALE"),
        ("review", "REVIEW_PACKET_REVIEW_STALE"),
        ("riskSummary", "REVIEW_PACKET_RISK_SUMMARY_STALE"),
    ):
        if packet.get(key) != expected_packet[key]:
            diagnostics.append(
                diag(code, f"review packet {key} does not match current bytes", packet_path)
            )
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


def write_failure(files: ProjectFiles, diagnostics: list[dict[str, object]]) -> None:
    files.write_atomic(VALIDATION_PATH, canonical_json_bytes({"owner": SUBJECT, "passed": False, "diagnostics": diagnostics}))


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
                    "summary": "Design outputs are invalid",
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
        no_change = (
            args.mode in {"review", "publish-approved", "rebind"}
            and declares_no_change(files, args.review_path)
        )
        diagnostics: list[dict[str, object]] = []
        requirement_handoff = owner_handoff(files, REQUIREMENT_CONTRACT, current_requirement_inputs)
        diagnostics.extend(requirement_handoff.diagnostics)
        if not diagnostics:
            asis_handoff = owner_handoff(files, ASIS_CONTRACT, current_asis_inputs)
            diagnostics.extend(asis_handoff.diagnostics)

        schemas = {
            "design": json.loads((SCRIPT_ROOT.parent / "contracts/design.schema.json").read_text(encoding="utf-8")),
            "technical": json.loads((SCRIPT_ROOT.parent / "contracts/technical-requirements.schema.json").read_text(encoding="utf-8")),
        }
        design_relative = DESIGN_PATH if args.mode == "rebind" else args.candidate
        technical_relative = TECHNICAL_PATH if args.mode == "rebind" else args.requirements_candidate
        design_payload: bytes | None = None
        technical_payload: bytes | None = None
        design: dict[str, Any] | None = None
        technical: dict[str, Any] | None = None
        source: dict[str, Any] | None = None
        asis: dict[str, Any] | None = None
        packet_payload: bytes | None = None
        review_payload: bytes | None = None
        summary_payload: bytes | None = None
        if not diagnostics:
            design_payload, design, local = load_candidate(files, design_relative, schemas["design"], "Design")
            diagnostics.extend(local)
            technical_payload, technical, local = load_candidate(files, technical_relative, schemas["technical"], "Technical requirements")
            diagnostics.extend(local)

        inputs: tuple[Artifact, ...] = ()
        if not diagnostics and design is not None and technical is not None:
            source, asis, upstream = load_upstream(files)
            diagnostics.extend(upstream)
            if source is not None and asis is not None and not diagnostics:
                diagnostics.extend(validate_semantics(design, technical, source, asis))
                review_diagnostics, review_text = validate_review(
                    files,
                    design,
                    technical,
                    require_no_change=no_change,
                    review_path=args.review_path,
                )
                diagnostics.extend(review_diagnostics)
                diagnostics.extend(
                    {**entry, "path": args.review_path}
                    for entry in validate_design_gates(source, technical, design, asis, review_text)
                )
                input_diagnostics, inputs = owner_inputs(files)
                diagnostics.extend(input_diagnostics)
                if (
                    not diagnostics
                    and no_change
                    and design_payload is not None
                    and technical_payload is not None
                ):
                    try:
                        validate_no_change_candidate(
                            files,
                            CONTRACT,
                            inputs,
                            {
                                "design": design_payload,
                                "technicalRequirements": technical_payload,
                            },
                        )
                    except ProjectIOError as error:
                        diagnostics.append(diag(error.code, str(error), error.relative_path))

        expected_packet: dict[str, object] | None = None
        if (
            not diagnostics
            and args.mode == "review"
            and design_payload is not None
            and technical_payload is not None
            and design is not None
            and technical is not None
            and asis is not None
        ):
            diagnostics.extend(
                validate_review_artifacts(
                    files,
                    args.project_root,
                    SUBJECT,
                    CLAIMS_PATH,
                    {"design": design, "technicalRequirements": technical},
                )
            )
        if (
            not diagnostics
            and args.mode in {"review", "publish-approved"}
            and design_payload is not None
            and technical_payload is not None
            and design is not None
            and technical is not None
            and asis is not None
        ):
            context, local = context_packet_entry(files, inputs)
            diagnostics.extend(local)
            if not diagnostics:
                try:
                    review_payload = files.read_bytes(args.review_path)
                except ProjectIOError:
                    diagnostics.append(
                        diag(
                            "REVIEW_MISSING",
                            "Design review candidate is unavailable",
                            args.review_path,
                        )
                    )
            if review_payload is not None and context is not None:
                summary_payload = risk_summary_bytes(
                    design,
                    technical,
                    asis,
                    sha256_bytes(design_payload),
                    sha256_bytes(technical_payload),
                )
                expected_packet = review_packet(
                    design_path=args.candidate,
                    design_payload=design_payload,
                    technical_path=args.requirements_candidate,
                    technical_payload=technical_payload,
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
                        diagnostics.append(
                            diag(error.code, str(error), error.relative_path)
                        )
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
                                    "risk summary bytes do not match current candidates",
                                    args.risk_summary_path,
                                )
                            )
                    diagnostics.extend(
                        approved_packet_diagnostics(
                            files,
                            packet_path=args.packet_path,
                            expected_packet=expected_packet,
                            reviewer_path=args.reviewer_path,
                            approval_path=args.approval_path,
                        )
                    )

        report: dict[str, object] | None = None
        if not diagnostics:
            try:
                if args.mode == "publish":
                    assert design_payload is not None and technical_payload is not None
                    report = publish_owner(
                        files,
                        CONTRACT,
                        inputs,
                        {"design": design_payload, "technicalRequirements": technical_payload},
                    )
                elif args.mode == "publish-approved":
                    assert (
                        design_payload is not None
                        and technical_payload is not None
                        and review_payload is not None
                    )
                    files.write_atomic(REVIEW_PATH, review_payload)
                    publisher = publish_no_change_owner if no_change else publish_owner
                    report = publisher(
                        files,
                        CONTRACT,
                        inputs,
                        {
                            "design": design_payload,
                            "technicalRequirements": technical_payload,
                        },
                    )
                elif args.mode == "rebind":
                    report = rebind_owner(files, CONTRACT, inputs)
            except ProjectIOError as error:
                diagnostics.append(diag(error.code, str(error), error.relative_path))
        if diagnostics and args.mode in {"publish", "rebind"}:
            write_failure(files, diagnostics)
        if diagnostics:
            outcome = "BLOCKED"
            outputs: list[str] = []
        elif args.mode == "review":
            outcome = "REVIEW_REQUIRED"
            outputs = [args.risk_summary_path, args.packet_path]
        else:
            outcome = "OK"
            outputs = (
                [DESIGN_PATH, TECHNICAL_PATH, VALIDATION_PATH]
                if args.mode in {"publish", "publish-approved", "rebind"}
                else []
            )
        result: dict[str, object] = {
            "outcome": outcome,
            "summary": "Design outputs are valid" if not diagnostics else "Design outputs are invalid",
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
                    "summary": "Design validation could not run",
                    "diagnostics": [diag(getattr(error, "code", "VALIDATOR_BLOCKED"), str(error))],
                    "outputs": [],
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
