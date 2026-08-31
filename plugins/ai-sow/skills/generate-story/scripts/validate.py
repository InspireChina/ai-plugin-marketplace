from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator


# Windows 控制台默认使用本地代码页（如 cp936），会把中文结构化输出写成非 UTF-8 字节。
# 调用方按 UTF-8 读取 stdout/stderr，这里显式固定编码，与 POSIX 行为保持一致。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.diagnostics import diagnostic as diag
from runtime.authorization import publish_review_packet
from runtime.controls import validate_manifest_controls
from runtime.context_pages import (
    context_budget,
    expected_context_fragment,
    expected_review_claims,
    read_protocol,
)
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
from runtime.review_checks import (
    artifact_metrics,
    record_reviewer_judgment,
    validate_review_artifacts,
)


SUBJECT = "generate-story"
SCHEMA_ID = "urn:ai-sow:generate-story:delivery:0.4"
PROJECT_PATH = ".ai-sow/project.json"
REQUIREMENTS_PATH = ".ai-sow/data/analyze-requirement/requirements.json"
REQUIREMENTS_VALIDATION_PATH = ".ai-sow/validation/analyze-requirement.json"
REQUIREMENTS_REVIEW_PATH = ".ai-sow/reviews/analyze-requirement.md"
REQUIREMENTS_QUESTIONNAIRE_PATH = ".ai-sow/reviews/analyze-requirement-questionnaire.md"
ASIS_PATH = ".ai-sow/data/analyze-as-is/asis.json"
ASIS_VALIDATION_PATH = ".ai-sow/validation/analyze-as-is.json"
ASIS_REVIEW_PATH = ".ai-sow/reviews/analyze-as-is.md"
ASIS_QUESTIONNAIRE_PATH = ".ai-sow/work/analyze-as-is/questionnaire.md"
DESIGN_PATH = ".ai-sow/data/generate-design/design.json"
TECHNICAL_PATH = ".ai-sow/data/generate-design/requirements.json"
DESIGN_VALIDATION_PATH = ".ai-sow/validation/generate-design.json"
DESIGN_REVIEW_PATH = ".ai-sow/reviews/generate-design.md"
REVIEW_PATH = ".ai-sow/reviews/generate-story.md"
STABLE_PATH = ".ai-sow/data/generate-story/delivery.json"
VALIDATION_PATH = ".ai-sow/validation/generate-story.json"
PACKET_PATH = ".ai-sow/work/generate-story/review-packet.json"
RISK_SUMMARY_PATH = ".ai-sow/work/generate-story/risk-summary.md"
REVIEWER_PATH = ".ai-sow/work/generate-story/reviewer.json"
APPROVAL_PATH = ".ai-sow/work/generate-story/approval.json"
CONTEXT_MANIFEST_PATH = ".ai-sow/work/generate-story/context/manifest.json"
CONTEXT_FRAGMENT_SPECS = (
    ("requirements", ".ai-sow/work/generate-story/context/requirements.json"),
    ("asIs", ".ai-sow/work/generate-story/context/as-is.json"),
    ("design", ".ai-sow/work/generate-story/context/design.json"),
    ("questionnaire", ".ai-sow/work/generate-story/context/questionnaire.json"),
)
CLAIMS_PATH = ".ai-sow/work/generate-story/claims.json"
REVIEW_PACKET_ALGORITHM = "ai-sow-owner-review-packet-v1"
REVIEWER_ALGORITHM = "ai-sow-owner-reviewer-v1"
APPROVAL_ALGORITHM = "ai-sow-owner-approval-v1"
REQUIRED_REVIEW_SECTIONS = (
    "Feature → Story",
    "Acceptance Criteria",
    "Integration",
    "Assumption / Risk",
    "Questionnaire consumption",
    "上线映射",
    "审查与批准",
)
GO_LIVE_CONCERNS = (
    "PRODUCTION_SCOPE",
    "ENVIRONMENT_CONFIGURATION",
    "DEPLOYMENT_CUTOVER_ROLLBACK",
    "DATA_MIGRATION",
    "PRODUCTION_VALIDATION",
    "OBSERVABILITY",
    "OPERATIONS_HANDOVER",
    "POST_GO_LIVE_SUPPORT",
    "USER_ENABLEMENT",
    "LEGACY_RETIREMENT",
)
GO_LIVE_COLUMNS = (
    "Concern",
    "Disposition",
    "Feature IDs",
    "Story IDs",
    "Assumption/Risk IDs",
    "责任边界",
    "依据",
)
ANCHOR_KINDS = {"CODE", "CONTRACT", "CONFIGURATION", "DEPLOYMENT"}
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
STABLE_ID_PATTERN = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")
QUESTION_ANCHOR_PATTERN = re.compile(r"analyze-requirement-questionnaire#([A-Za-z][A-Za-z0-9-]*)")
EMPTY = {"", "-", "—", "N/A", "NONE", "NOT_APPLICABLE"}
TASK_READINESS_THRESHOLD_PATTERN = re.compile(
    r"(?:\bP\d{2}\b|[<>]=?|≤|≥|\d+(?:\.\d+)?\s*(?:%|ms|毫秒|s|秒|分钟|小时|次|项|个))",
    re.IGNORECASE,
)
TASK_READINESS_OWNER_PATTERN = re.compile(
    r"(?:负责人|责任方|责任团队|由.{1,40}(?:团队|部门|角色|人员|运维).{0,12}(?:负责|承担)|"
    r"(?:团队|部门|角色|人员|运维).{0,12}(?:负责|承担)|\bowner\s*[:：])",
    re.IGNORECASE,
)

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
DESIGN_CONTRACT = OwnerContract(
    subject="generate-design",
    contract_ids=(
        "urn:ai-sow:generate-design:design:0.2",
        "urn:ai-sow:generate-design:technical-requirements:0.2",
    ),
    validation_path=DESIGN_VALIDATION_PATH,
    reviews=(("approvedReview", DESIGN_REVIEW_PATH),),
    outputs=(("design", DESIGN_PATH), ("technicalRequirements", TECHNICAL_PATH)),
)
CONTRACT = OwnerContract(
    subject=SUBJECT,
    contract_ids=(SCHEMA_ID,),
    validation_path=VALIDATION_PATH,
    reviews=(("approvedReview", REVIEW_PATH),),
    outputs=(("delivery", STABLE_PATH),),
    claims_path=CLAIMS_PATH,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and publish Delivery handoff data")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--staging-root")
    parser.add_argument(
        "--mode",
        required=True,
        choices=(
            "check",
            "review",
            "record-reviewer",
            "write-reviewer",
            "write-approval",
            "publish-approved",
            "publish",
            "rebind",
        ),
    )
    parser.add_argument("--review-path", default=REVIEW_PATH)
    parser.add_argument("--candidate", default=".ai-sow/work/generate-story/delivery.candidate.json")
    parser.add_argument("--packet-path", default=PACKET_PATH)
    parser.add_argument("--risk-summary-path", default=RISK_SUMMARY_PATH)
    parser.add_argument("--reviewer-path", default=REVIEWER_PATH)
    parser.add_argument("--approval-path", default=APPROVAL_PATH)
    parser.add_argument("--packet-sha256")
    parser.add_argument("--review-decision", choices=("PASS", "BLOCKED"))
    parser.add_argument("--finding-id", action="append", default=[])
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
    decision = "PASS" if args.mode == "write-reviewer" else args.review_decision
    if args.mode == "record-reviewer" and decision is None:
        diagnostics.append(
            diag(
                "REVIEW_DECISION_INVALID",
                "record-reviewer requires --review-decision PASS or BLOCKED",
            )
        )
    outputs: list[str] = []
    judgment_path: str | None = None
    if not diagnostics:
        try:
            files = ProjectFiles.open(args.project_root)
            local, outputs, judgment_path = record_reviewer_judgment(
                files,
                owner=SUBJECT,
                packet_sha256=args.packet_sha256,
                decision=decision,
                finding_ids=args.finding_id,
                journal_directory=".ai-sow/work/generate-story/review-judgments",
                reviewer_path=REVIEWER_PATH,
                reviewer_algorithm=REVIEWER_ALGORITHM,
            )
            diagnostics.extend(local)
        except (ProjectIOError, OSError) as error:
            diagnostics.append(diag(getattr(error, "code", "REVIEWER_WRITE_BLOCKED"), str(error)))
    result: dict[str, object] = {
        "outcome": "BLOCKED" if diagnostics else "OK",
        "summary": (
            f"{SUBJECT} reviewer judgment is invalid"
            if diagnostics
            else f"{SUBJECT} reviewer judgment is recorded"
        ),
        "diagnostics": diagnostics,
        "outputs": [] if diagnostics else outputs,
    }
    if not diagnostics:
        result["packetSha256"] = args.packet_sha256
        result["reviewDecision"] = decision
        result["judgmentPath"] = judgment_path
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


def split_ids(value: str) -> list[str]:
    if value.strip().upper() in EMPTY:
        return []
    return [part for part in re.split(r"[,，、;；\s]+", value.strip()) if part]


def read_review(files: ProjectFiles, path: str) -> str:
    try:
        return files.read_bytes(path).decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError):
        return ""


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


def current_file_hash(files: ProjectFiles, path: str, validation_path: str, name: str) -> str:
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


def current_requirement_inputs(files: ProjectFiles) -> tuple[tuple[Artifact, ...], MatchResult | None]:
    try:
        requirements = files.read_json(REQUIREMENTS_PATH)
    except ProjectIOError:
        return (), upstream_failure("analyze-requirement", REQUIREMENTS_PATH, "requirements output is unavailable")
    sources = requirements.get("sourceDocuments") if isinstance(requirements, dict) else None
    if not isinstance(sources, list):
        return (), upstream_failure("analyze-requirement", REQUIREMENTS_PATH, "requirements source contract is invalid")
    artifacts = [Artifact("project", "FILE", PROJECT_PATH, current_file_hash(files, PROJECT_PATH, REQUIREMENTS_VALIDATION_PATH, "project"))]
    names: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("sourceDocumentId"), str) or not isinstance(source.get("file"), str):
            return (), upstream_failure("analyze-requirement", REQUIREMENTS_PATH, "source document contract is invalid")
        name = f"source:{source['sourceDocumentId']}"
        if name in names:
            return (), upstream_failure("analyze-requirement", REQUIREMENTS_PATH, "source input names are not unique")
        names.add(name)
        artifacts.append(Artifact(name, "FILE", source["file"], current_file_hash(files, source["file"], REQUIREMENTS_VALIDATION_PATH, name)))
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
        artifacts.append(Artifact("questionnaire", "QUESTIONNAIRE_PRESENCE", f"questionnaire:{REQUIREMENTS_QUESTIONNAIRE_PATH}", current_file_hash(files, REQUIREMENTS_QUESTIONNAIRE_PATH, REQUIREMENTS_VALIDATION_PATH, "questionnaire")))
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
    artifacts = [
        Artifact(name, "FILE", path, current_file_hash(files, path, ASIS_VALIDATION_PATH, name))
        for name, path in (
            ("project", PROJECT_PATH),
            ("requirementsValidation", REQUIREMENTS_VALIDATION_PATH),
            ("requirements", REQUIREMENTS_PATH),
        )
    ]
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
            return (), upstream_failure("analyze-as-is", ASIS_PATH, "prior SOW contract is invalid")
        name = f"priorSow:{snapshot['priorSowId']}"
        artifacts.append(Artifact(name, "FILE", snapshot["file"], current_file_hash(files, snapshot["file"], ASIS_VALIDATION_PATH, name)))
    evidence_names: set[str] = set()
    for entry in evidence:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(field), str) for field in ("evidenceId", "kind", "reference")):
            return (), upstream_failure("analyze-as-is", ASIS_PATH, "Evidence input contract is invalid")
        name = f"evidence:{entry['evidenceId']}"
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
        artifacts.append(Artifact("questionnaire", "QUESTIONNAIRE_PRESENCE", f"questionnaire:{ASIS_QUESTIONNAIRE_PATH}", current_file_hash(files, ASIS_QUESTIONNAIRE_PATH, ASIS_VALIDATION_PATH, "questionnaire")))
    else:
        return (), upstream_failure("analyze-as-is", ASIS_REVIEW_PATH, "questionnaire declaration is invalid")
    return tuple(artifacts), None


def current_design_inputs(files: ProjectFiles) -> tuple[tuple[Artifact, ...], MatchResult | None]:
    return (
        tuple(
            Artifact(name, "FILE", path, current_file_hash(files, path, DESIGN_VALIDATION_PATH, name))
            for name, path in (
                ("project", PROJECT_PATH),
                ("requirementsValidation", REQUIREMENTS_VALIDATION_PATH),
                ("requirements", REQUIREMENTS_PATH),
                ("asIsValidation", ASIS_VALIDATION_PATH),
                ("asIs", ASIS_PATH),
            )
        ),
        None,
    )


def owner_handoff(
    files: ProjectFiles,
    contract: OwnerContract,
    builder: Callable[[ProjectFiles], tuple[tuple[Artifact, ...], MatchResult | None]],
) -> MatchResult:
    expected, failure = builder(files)
    result = match_owner(files, contract, expected)
    return result if not result.ok else failure or result


def load_upstreams(files: ProjectFiles) -> tuple[dict[str, dict[str, Any]] | None, list[dict[str, object]]]:
    paths = {
        "requirements": REQUIREMENTS_PATH,
        "asIs": ASIS_PATH,
        "design": DESIGN_PATH,
        "technical": TECHNICAL_PATH,
    }
    values: dict[str, object] = {}
    for name, path in paths.items():
        try:
            values[name] = files.read_json(path)
        except ProjectIOError:
            owner = (
                "analyze-requirement"
                if name == "requirements"
                else "analyze-as-is"
                if name == "asIs"
                else "generate-design"
            )
            return None, [
                {
                    "code": "UPSTREAM_HANDOFF_INVALID",
                    "message": "upstream stable output is unreadable",
                    "upstreamOwner": owner,
                    "path": path,
                }
            ]
    for name, value in values.items():
        if not isinstance(value, dict):
            owner = (
                "analyze-requirement"
                if name == "requirements"
                else "analyze-as-is"
                if name == "asIs"
                else "generate-design"
            )
            return None, [
                {
                    "code": "UPSTREAM_HANDOFF_INVALID",
                    "message": "upstream stable output must be an object",
                    "upstreamOwner": owner,
                    "path": paths[name],
                }
            ]
    required = {
        "requirements": (("features", "featureId"),),
        "asIs": (("commitments", "commitmentId"),),
        "design": (("scopeDecisions", "featureId"), ("decisions", "designDecisionId")),
        "technical": (("features", "featureId"),),
    }
    for name, collections in required.items():
        for collection, field in collections:
            entries = values[name].get(collection)
            if not isinstance(entries, list) or any(not isinstance(entry, dict) or not isinstance(entry.get(field), str) for entry in entries):
                owner = "analyze-requirement" if name == "requirements" else "analyze-as-is" if name == "asIs" else "generate-design"
                return None, [{"code": "UPSTREAM_HANDOFF_INVALID", "message": f"upstream output lacks contracted {field} values", "upstreamOwner": owner, "path": paths[name]}]
    return values, []  # type: ignore[return-value]


def load_candidate(files: ProjectFiles, relative_path: str, schema: dict[str, Any]) -> tuple[bytes | None, dict[str, Any] | None, list[dict[str, object]]]:
    try:
        payload = files.read_bytes(relative_path)
        value = json.loads(payload.decode("utf-8"))
    except (ProjectIOError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None, [diag("CANDIDATE_UNREADABLE", "Delivery candidate is unavailable", relative_path)]
    diagnostics = [
        diag("SCHEMA_INVALID", error.message, "/" + "/".join(str(part) for part in error.path))
        for error in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path))
    ]
    return payload, value if isinstance(value, dict) else None, diagnostics


def questionnaire_defaults(files: ProjectFiles) -> tuple[set[str], list[dict[str, object]]]:
    values = declaration(read_review(files, REQUIREMENTS_REVIEW_PATH), "Questionnaire")
    if values == ["NOT_REQUIRED"]:
        return set(), []
    if values != [REQUIREMENTS_QUESTIONNAIRE_PATH]:
        return set(), [diag("UPSTREAM_HANDOFF_INVALID", "Requirement questionnaire declaration is invalid", REQUIREMENTS_REVIEW_PATH)]
    text = read_review(files, REQUIREMENTS_QUESTIONNAIRE_PATH)
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|", line.strip())
        if match is None:
            continue
        field, value = match.groups()
        if field == "Question ID" and current:
            records.append(current)
            current = {}
        current[field] = value
    if current:
        records.append(current)
    return {
        record["Question ID"]
        for record in records
        if record.get("Status") == "APPROVED_DEFAULT"
        and record.get("Disposition") == "ASSUMPTION_CANDIDATE"
        and isinstance(record.get("Question ID"), str)
    }, []


def validate_semantics(
    delivery: dict[str, Any],
    upstream: dict[str, dict[str, Any]],
    approved_defaults: set[str],
) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    source_features = {entry["featureId"] for entry in upstream["requirements"]["features"]}
    technical_feature_by_id = {
        entry["featureId"]: entry for entry in upstream["technical"]["features"]
    }
    technical_features = set(technical_feature_by_id)
    known_features = source_features | technical_features
    scopes = {entry["featureId"]: entry for entry in upstream["design"]["scopeDecisions"]}
    in_scope = {feature_id for feature_id, scope in scopes.items() if scope.get("decision") == "IN_SCOPE"}
    decisions = {entry["designDecisionId"]: entry for entry in upstream["design"]["decisions"]}
    commitments = {entry["commitmentId"]: entry for entry in upstream["asIs"]["commitments"]}
    stories = {entry["storyId"]: entry for entry in delivery["stories"]}
    assumptions = {entry["assumptionId"]: entry for entry in delivery["assumptions"]}

    own_ids = [
        *(entry["storyId"] for entry in delivery["stories"]),
        *(entry["acceptanceCriterionId"] for entry in delivery["acceptanceCriteria"]),
        *(entry["integrationId"] for entry in delivery["integrations"]),
        *(entry["assumptionId"] for entry in delivery["assumptions"]),
    ]
    for value, count in Counter(own_ids).items():
        if count > 1:
            diagnostics.append(diag("ID_DUPLICATE", f"duplicate stable ID: {value}"))

    for collection in (
        "stories",
        "acceptanceCriteria",
        "integrations",
        "assumptions",
    ):
        for name, count in Counter(
            entry["name"] for entry in delivery[collection]
        ).items():
            if count > 1:
                diagnostics.append(
                    diag("NAME_DUPLICATE", f"duplicate {collection} name: {name}")
                )

    story_counts = Counter(entry["featureId"] for entry in delivery["stories"])
    stories_by_feature: dict[str, list[str]] = defaultdict(list)
    for story in delivery["stories"]:
        feature_id = story["featureId"]
        stories_by_feature[feature_id].append(story["storyId"])
        if feature_id not in known_features:
            diagnostics.append(diag("FEATURE_REF_UNKNOWN", f"unknown Feature: {feature_id}"))
        elif feature_id not in in_scope:
            diagnostics.append(diag("STORY_OUT_OF_SCOPE", f"Story targets a non-IN_SCOPE Feature: {feature_id}"))
    for feature_id in sorted(in_scope):
        if story_counts[feature_id] == 0:
            diagnostics.append(diag("FEATURE_COVERAGE_MISSING", f"missing Story for: {feature_id}"))

    feature_ids_by_ac_name: dict[str, set[str]] = defaultdict(set)
    for criterion in delivery["acceptanceCriteria"]:
        story = stories.get(criterion["storyId"])
        if story is not None:
            feature_ids_by_ac_name[criterion["name"]].add(story["featureId"])
    for ac_name, feature_ids in sorted(feature_ids_by_ac_name.items()):
        if len(feature_ids) > 1:
            ordered_feature_ids = sorted(feature_ids)
            diagnostics.append(
                diag(
                    "FEATURE_OVERLAP_SUSPECTED",
                    "different Features share an identical AC result; return to generate-design to merge or redraw the Feature boundary",
                    acceptanceCriterionName=ac_name,
                    featureIds=ordered_feature_ids,
                )
            )

    coverage = {
        entry["featureId"]: entry
        for entry in upstream["asIs"].get("coverage", [])
        if isinstance(entry, dict) and isinstance(entry.get("featureId"), str)
    }
    sequences: dict[str, list[int]] = defaultdict(list)
    carried_by_feature: dict[str, set[str]] = defaultdict(set)
    decision_refs_by_feature: dict[str, set[str]] = defaultdict(set)
    for criterion in delivery["acceptanceCriteria"]:
        story_id = criterion["storyId"]
        story = stories.get(story_id)
        if story is None:
            diagnostics.append(diag("STORY_REF_UNKNOWN", f"unknown Story: {story_id}"))
        sequences[story_id].append(criterion["sequence"])
        if story is not None:
            feature_id = story["featureId"]
            feature_coverage = coverage.get(feature_id, {})
            effective_ids = {
                value
                for value in feature_coverage.get("effectiveStartItemIds", [])
                if isinstance(value, str)
            }
            technical_feature = technical_feature_by_id.get(feature_id, {})
            technical_source = technical_feature.get("source", {}) if isinstance(technical_feature, dict) else {}
            effective_ids.update(
                value
                for value in technical_source.get("effectiveStartItemIds", [])
                if isinstance(value, str)
            )
            effective_ids.update(
                value
                for value in scopes.get(feature_id, {}).get("effectiveStartItemIds", [])
                if isinstance(value, str)
            )
            rationale = criterion["gapRationale"]
            has_start_anchor = any(value in rationale for value in effective_ids)
            declares_missing_start = (
                feature_coverage.get("status") == "MISSING"
                and bool(re.search(r"(?:无|没有).{0,12}(?:Effective Start|有效起点)", rationale))
            )
            if not has_start_anchor and not declares_missing_start:
                diagnostics.append(
                    diag(
                        "AC_GAP_RATIONALE_MISSING",
                        f"AC must cite its Effective Start or an evidenced missing start: {criterion['acceptanceCriterionId']}",
                    )
                )
            for commitment_id in criterion["carryForwardCommitmentIds"]:
                commitment = commitments.get(commitment_id)
                if commitment is None:
                    diagnostics.append(diag("COMMITMENT_REF_UNKNOWN", f"unknown Commitment: {commitment_id}"))
                elif commitment.get("treatment") != "CARRY_FORWARD":
                    diagnostics.append(diag("AC_COMMITMENT_NOT_CARRY_FORWARD", f"AC may only include CARRY_FORWARD Commitment: {commitment_id}"))
                elif feature_id not in commitment.get("relatedFeatureIds", []):
                    diagnostics.append(diag("COMMITMENT_FEATURE_MISMATCH", f"Commitment is unrelated to AC Story Feature: {commitment_id}"))
                else:
                    carried_by_feature[feature_id].add(commitment_id)
            mentioned_features = {
                value
                for value in STABLE_ID_PATTERN.findall(f"{criterion['name']} {rationale}")
                if value.startswith("feature-") and value != feature_id
            }
            for mentioned_feature in mentioned_features:
                if not any(
                    related_story in rationale or related_story in criterion["name"]
                    for related_story in stories_by_feature.get(mentioned_feature, [])
                ):
                    diagnostics.append(
                        diag(
                            "CROSS_FEATURE_CAPABILITY_UNDECLARED",
                            f"AC references another Feature without naming its producing Story: {criterion['acceptanceCriterionId']}",
                        )
                    )
        for decision_id in criterion["approvalDecisionIds"]:
            decision = decisions.get(decision_id)
            if decision is None:
                diagnostics.append(diag("DECISION_REF_UNKNOWN", f"unknown Design Decision: {decision_id}"))
            elif story is not None:
                decision_refs_by_feature[story["featureId"]].add(decision_id)
                if story["featureId"] not in decision.get("relatedFeatureIds", []):
                    diagnostics.append(
                        diag(
                            "DECISION_FEATURE_MISMATCH",
                            f"Design Decision is unrelated to AC Story Feature: {decision_id}",
                        )
                    )

    for decision_id, decision in decisions.items():
        if decision.get("decisionKind") != "OPERATIONAL_THRESHOLD":
            continue
        related_in_scope = [
            feature_id
            for feature_id in decision.get("relatedFeatureIds", [])
            if feature_id in in_scope
        ]
        if not related_in_scope:
            continue
        decision_text = f"{decision.get('decision', '')} {decision.get('rationale', '')}"
        if TASK_READINESS_OWNER_PATTERN.search(decision_text) is None:
            diagnostics.append(
                diag(
                    "TASK_READINESS_OWNERSHIP_MISSING",
                    "operational threshold must name the team, role, or party accountable for the outcome",
                    decisionId=decision_id,
                    featureIds=related_in_scope,
                )
            )
        if TASK_READINESS_THRESHOLD_PATTERN.search(decision_text) is None:
            diagnostics.append(
                diag(
                    "TASK_READINESS_THRESHOLD_MISSING",
                    "operational threshold must contain a measurable numeric or percentile threshold",
                    decisionId=decision_id,
                    featureIds=related_in_scope,
                )
            )
        unmapped = [
            feature_id
            for feature_id in related_in_scope
            if decision_id not in decision_refs_by_feature[feature_id]
        ]
        if unmapped:
            diagnostics.append(
                diag(
                    "TASK_READINESS_THRESHOLD_UNMAPPED",
                    "operational threshold must be referenced by Acceptance Criteria for every related IN_SCOPE Feature",
                    decisionId=decision_id,
                    featureIds=unmapped,
                )
            )
    for story_id in sorted(set(stories) - set(sequences)):
        diagnostics.append(diag("AC_COVERAGE_MISSING", f"Story has no AC: {story_id}"))
    for story_id, actual in sequences.items():
        if sorted(actual) != list(range(1, len(actual) + 1)):
            diagnostics.append(diag("AC_SEQUENCE_INVALID", f"non-contiguous AC sequence for: {story_id}"))
    for commitment_id, commitment in commitments.items():
        if commitment.get("treatment") != "CARRY_FORWARD":
            continue
        for feature_id in commitment.get("relatedFeatureIds", []):
            if feature_id in in_scope and commitment_id not in carried_by_feature[feature_id]:
                diagnostics.append(
                    diag(
                        "CARRY_FORWARD_AC_MISSING",
                        f"no AC carries forward Commitment for Feature {feature_id}: {commitment_id}",
                    )
                )

    integrations_by_story: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for integration in delivery["integrations"]:
        story_id = integration["storyId"]
        if story_id not in stories:
            diagnostics.append(diag("INTEGRATION_STORY_REF_UNKNOWN", f"unknown Story: {story_id}"))
        integrations_by_story[story_id].append(integration)
        for decision_id in integration["decisionIds"]:
            decision = decisions.get(decision_id)
            if decision is None:
                diagnostics.append(diag("DECISION_REF_UNKNOWN", f"unknown Design Decision: {decision_id}"))
            elif story_id in stories:
                if stories[story_id]["featureId"] not in decision.get("relatedFeatureIds", []):
                    diagnostics.append(
                        diag(
                            "DECISION_FEATURE_MISMATCH",
                            f"Design Decision is unrelated to Integration Story Feature: {decision_id}",
                        )
                    )

    integrations_by_feature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for story_id, related in integrations_by_story.items():
        story = stories.get(story_id)
        if story is None:
            continue
        integrations_by_feature[story["featureId"]].extend(related)
    for feature_id, feature in technical_feature_by_id.items():
        related_business_features = set(feature.get("relatedBusinessFeatureIds", []))
        if len(related_business_features) < 2:
            continue
        related_targets = [
            (business_feature_id, integration["target"].strip().casefold())
            for business_feature_id in related_business_features
            for integration in integrations_by_feature.get(business_feature_id, [])
            if integration["target"].strip()
        ]
        for integration in integrations_by_feature.get(feature_id, []):
            aggregate_target = integration["target"].strip().casefold()
            repeated_features = {
                business_feature_id
                for business_feature_id, target in related_targets
                if target in aggregate_target
            }
            if len(repeated_features) >= 2:
                diagnostics.append(
                    diag(
                        "INTEGRATION_SCOPE_OVERLAP",
                        "TECHNICAL Feature Integration aggregates targets already owned by "
                        "related BUSINESS Story Integrations; keep the shared technical Story "
                        "to a distinct adapter/control boundary: "
                        f"{integration['integrationId']} repeats "
                        f"{', '.join(sorted(repeated_features))}",
                    )
                )
    for story_id, story in stories.items():
        boundary = story["requiredIntegrationBoundary"]
        related = integrations_by_story.get(story_id, [])
        if boundary != "NONE" and not related:
            diagnostics.append(diag("INTEGRATION_COVERAGE_MISSING", f"Story requires Integration: {story_id}"))
        for integration in related:
            if boundary == "NONE" or integration["deliveryBoundary"] != boundary:
                diagnostics.append(diag("INTEGRATION_BOUNDARY_MISMATCH", f"Integration boundary disagrees with Story: {integration['integrationId']}"))

    stories_by_assumption: dict[str, list[str]] = defaultdict(list)
    for story_id, story in stories.items():
        assumption_id = story.get("assumptionId")
        if assumption_id is None:
            continue
        if assumption_id not in assumptions:
            diagnostics.append(
                diag("ASSUMPTION_REF_UNKNOWN", f"unknown Assumption/Risk: {assumption_id}")
            )
        else:
            stories_by_assumption[assumption_id].append(story_id)
    signatures: dict[tuple[str, ...], str] = {}
    for assumption in delivery["assumptions"]:
        signature = tuple(" ".join(str(assumption[field]).split()).casefold() for field in ("type", "name", "trigger", "responsibilityBoundary", "handling"))
        if signature in signatures:
            diagnostics.append(diag("ASSUMPTION_DUPLICATE", f"duplicate Assumption/Risk semantics: {assumption['assumptionId']}"))
        else:
            signatures[signature] = assumption["assumptionId"]

    actual_questions: dict[str, list[str]] = defaultdict(list)
    for assumption in delivery["assumptions"]:
        for question_id in QUESTION_ANCHOR_PATTERN.findall(assumption["handling"]):
            actual_questions[question_id].append(assumption["assumptionId"])
    if set(actual_questions) != approved_defaults:
        diagnostics.append(diag("QUESTIONNAIRE_CONSUMPTION_INVALID", "approved questionnaire defaults and Assumption anchors differ"))
    for question_id in approved_defaults:
        matches = actual_questions.get(question_id, [])
        if len(matches) != 1 or not stories_by_assumption.get(matches[0] if matches else ""):
            diagnostics.append(diag("QUESTIONNAIRE_CONSUMPTION_INVALID", f"{question_id} must map to one Assumption and at least one Story"))
    return diagnostics


def stable_ids(delivery: dict[str, Any]) -> list[str]:
    return [
        *(entry["storyId"] for entry in delivery["stories"]),
        *(entry["acceptanceCriterionId"] for entry in delivery["acceptanceCriteria"]),
        *(entry["integrationId"] for entry in delivery["integrations"]),
        *(entry["assumptionId"] for entry in delivery["assumptions"]),
    ]


def _section(text: str, title: str) -> list[str]:
    return [match.group("body") for match in re.finditer(rf"(?ms)^## {re.escape(title)}\s*\r?\n(?P<body>.*?)(?=^##\s+|\Z)", text)]


def parse_go_live_mapping(
    text: str,
    review_path: str,
) -> tuple[list[dict[str, object]], dict[str, tuple[list[str], list[str], list[str]]]]:
    diagnostics: list[dict[str, object]] = []
    sections = _section(text, "上线映射")
    if len(sections) != 1:
        return [diag("GO_LIVE_MAPPING_SECTION_INVALID", "review must contain one 上线映射 section", review_path)], {}
    if declaration(sections[0], "Go-live Mapping") != ["PASSED"]:
        diagnostics.append(diag("GO_LIVE_MAPPING_NOT_PASSED", "Go-live Mapping must be PASSED", review_path))
    header_seen = False
    rows: list[tuple[str, list[str], list[str], list[str]]] = []
    for raw in sections[0].splitlines():
        line = raw.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if cells == GO_LIVE_COLUMNS:
            header_seen = True
            continue
        if cells and all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        if not header_seen:
            continue
        if len(cells) != 7:
            diagnostics.append(diag("GO_LIVE_MAPPING_ROW_INVALID", f"go-live mapping row must have seven columns: {line}", review_path))
            continue
        concern, disposition, features, stories, assumptions, boundary, basis = cells
        if concern not in GO_LIVE_CONCERNS:
            diagnostics.append(diag("GO_LIVE_CONCERN_UNKNOWN", f"unknown Concern: {concern}", review_path))
            continue
        if disposition not in {"IN_SCOPE", "FULLY_COVERED", "OUT_OF_SCOPE", "NOT_APPLICABLE"}:
            diagnostics.append(diag("GO_LIVE_DISPOSITION_INVALID", f"invalid Concern disposition: {concern}", review_path))
        if boundary.strip().upper() in EMPTY or basis.strip().upper() in EMPTY:
            diagnostics.append(diag("GO_LIVE_MAPPING_EXPLANATION_MISSING", f"Concern needs responsibility and basis: {concern}", review_path))
        feature_ids = split_ids(features)
        story_ids = split_ids(stories)
        assumption_ids = split_ids(assumptions)
        if disposition == "IN_SCOPE" and (
            not feature_ids
            or (not story_ids and not assumption_ids)
        ):
            diagnostics.append(
                diag(
                    "GO_LIVE_IN_SCOPE_MAPPING_MISSING",
                    f"IN_SCOPE Concern needs Feature and Story or Assumption/Risk: {concern}",
                    review_path,
                )
            )
        if disposition == "FULLY_COVERED" and not feature_ids:
            diagnostics.append(
                diag(
                    "GO_LIVE_FULLY_COVERED_FEATURE_MISSING",
                    f"FULLY_COVERED Concern needs a Feature: {concern}",
                    review_path,
                )
            )
        rows.append((concern, feature_ids, story_ids, assumption_ids))
    if not header_seen:
        diagnostics.append(diag("GO_LIVE_MAPPING_HEADER_INVALID", "go-live mapping must use the fixed header", review_path))
    counts = Counter(row[0] for row in rows)
    for concern in GO_LIVE_CONCERNS:
        if counts[concern] == 0:
            diagnostics.append(diag("GO_LIVE_CONCERN_MISSING", f"missing Concern: {concern}", review_path))
        elif counts[concern] > 1:
            diagnostics.append(diag("GO_LIVE_CONCERN_DUPLICATE", f"duplicate Concern: {concern}", review_path))
    return diagnostics, {row[0]: row[1:] for row in rows if counts[row[0]] == 1}


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
    for part in split_ids(value):
        if "=" not in part:
            return None
        owner, digest = part.split("=", 1)
        if owner in result or owner not in {"analyze-requirement", "analyze-as-is", "generate-design"} or not HASH_PATTERN.fullmatch(digest):
            return None
        result[owner] = digest
    return result


def expected_questionnaire_map(delivery: dict[str, Any], approved_defaults: set[str]) -> dict[str, tuple[str, tuple[str, ...]]]:
    relations: dict[str, list[str]] = defaultdict(list)
    for story in delivery["stories"]:
        if assumption_id := story.get("assumptionId"):
            relations[assumption_id].append(story["storyId"])
    result: dict[str, tuple[str, tuple[str, ...]]] = {}
    for assumption in delivery["assumptions"]:
        for question_id in QUESTION_ANCHOR_PATTERN.findall(assumption["handling"]):
            if question_id in approved_defaults:
                result[question_id] = (assumption["assumptionId"], tuple(relations[assumption["assumptionId"]]))
    return result


def parse_questionnaire_map(value: str) -> dict[str, tuple[str, tuple[str, ...]]] | None:
    if value == "NONE":
        return {}
    result: dict[str, tuple[str, tuple[str, ...]]] = {}
    for item in [part.strip() for part in value.split(";") if part.strip()]:
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9-]*)=([a-z][a-z0-9-]+)->(.+)", item)
        if match is None or match.group(1) in result:
            return None
        result[match.group(1)] = (match.group(2), tuple(split_ids(match.group(3))))
    return result


def questionnaire_maps_match(
    actual: dict[str, tuple[str, tuple[str, ...]]] | None,
    expected: dict[str, tuple[str, tuple[str, ...]]],
) -> bool:
    if actual is None or set(actual) != set(expected):
        return False
    for question_id, (expected_assumption, expected_stories) in expected.items():
        actual_assumption, actual_stories = actual[question_id]
        if (
            actual_assumption != expected_assumption
            or len(actual_stories) != len(set(actual_stories))
            or set(actual_stories) != set(expected_stories)
        ):
            return False
    return True


def validate_review(
    files: ProjectFiles,
    delivery: dict[str, Any],
    upstream: dict[str, dict[str, Any]],
    approved_defaults: set[str],
    *,
    require_no_change: bool,
    review_path: str,
) -> list[dict[str, object]]:
    text = read_review(files, review_path)
    if not text:
        return [diag("REVIEW_MISSING", "approved Story review is unavailable", review_path)]
    diagnostics: list[dict[str, object]] = []
    for section in REQUIRED_REVIEW_SECTIONS:
        if len(re.findall(rf"(?m)^## {re.escape(section)}\s*$", text)) != 1:
            diagnostics.append(diag("REVIEW_SECTION_INVALID", f"review must contain exactly one section: {section}", review_path))
    ids = stable_ids(delivery)
    declared = declaration(text, "Stable IDs")
    declared_ids = split_ids(declared[0]) if len(declared) == 1 else []
    if (
        len(declared) != 1
        or len(declared_ids) != len(set(declared_ids))
        or set(declared_ids) != set(ids or ["NONE"])
    ):
        diagnostics.append(diag("REVIEW_ID_SET_MISMATCH", "review Stable IDs do not match Delivery candidate", review_path))
    maps = declaration(text, "Questionnaire Map")
    expected_map = expected_questionnaire_map(delivery, approved_defaults)
    if len(maps) != 1 or not questionnaire_maps_match(
        parse_questionnaire_map(maps[0]) if len(maps) == 1 else None,
        expected_map,
    ):
        diagnostics.append(diag("REVIEW_QUESTIONNAIRE_MAP_INVALID", "review Questionnaire Map does not match consumed defaults", review_path))
    if declaration(text, "Reviewer") != ["PASS"]:
        diagnostics.append(diag("REVIEW_NOT_PASSED", "Reviewer must be PASS", review_path))
    if declaration(text, "User Approval") != ["APPROVED"]:
        diagnostics.append(diag("USER_APPROVAL_MISSING", "User Approval must be APPROVED", review_path))
    mapping_diagnostics, rows = parse_go_live_mapping(text, review_path)
    diagnostics.extend(mapping_diagnostics)
    story_map = {entry["storyId"]: entry for entry in delivery["stories"]}
    assumption_ids = {entry["assumptionId"] for entry in delivery["assumptions"]}
    known_features = {
        *(entry["featureId"] for entry in upstream["requirements"]["features"]),
        *(entry["featureId"] for entry in upstream["technical"]["features"]),
    }
    relations = {
        (entry["assumptionId"], entry["storyId"])
        for entry in delivery["stories"]
        if entry.get("assumptionId")
    }
    for concern, (features, stories, assumptions) in rows.items():
        for feature_id in features:
            if feature_id not in known_features:
                diagnostics.append(
                    diag(
                        "GO_LIVE_FEATURE_REF_UNKNOWN",
                        f"unknown Feature mapping for {concern}: {feature_id}",
                        review_path,
                    )
                )
        for story_id in stories:
            if story_id not in story_map or story_map[story_id]["featureId"] not in features:
                diagnostics.append(diag("GO_LIVE_STORY_MAPPING_INVALID", f"invalid Story mapping for {concern}: {story_id}", review_path))
        for assumption_id in assumptions:
            mapped_through_story = any(
                (assumption_id, story_id) in relations
                and story_id in story_map
                and story_map[story_id]["featureId"] in features
                for story_id in story_map
            )
            if assumption_id not in assumption_ids or not mapped_through_story:
                diagnostics.append(diag("GO_LIVE_ASSUMPTION_MAPPING_INVALID", f"invalid Assumption/Risk mapping for {concern}: {assumption_id}", review_path))
    impacts = declaration(text, "Impact")
    if require_no_change and impacts != ["NO_CHANGE"]:
        diagnostics.append(diag("REVIEW_NO_CHANGE_MISSING", "NO_CHANGE 发布或 rebind 要求 review 声明 Impact: NO_CHANGE", review_path))
    elif not require_no_change and "NO_CHANGE" in impacts:
        diagnostics.append(diag("REVIEW_NO_CHANGE_MODE_INVALID", "Impact: NO_CHANGE 仅允许用于 NO_CHANGE 发布或 rebind", review_path))
    elif not require_no_change and impacts not in ([], ["CHANGED"]):
        diagnostics.append(diag("REVIEW_IMPACT_INVALID", "review Impact declaration is invalid", review_path))
    if require_no_change:
        previous = previous_owner_receipt(files)
        specs = (
            ("analyze-requirement", "requirementsValidation", REQUIREMENTS_VALIDATION_PATH),
            ("analyze-as-is", "asIsValidation", ASIS_VALIDATION_PATH),
            ("generate-design", "designValidation", DESIGN_VALIDATION_PATH),
        )
        previous_hashes = {owner: named_hash(previous, input_name) for owner, input_name, _ in specs}
        current_hashes = {owner: current_file_hash(files, path, VALIDATION_PATH, input_name) for owner, input_name, path in specs}
        changed = [owner for owner, _, _ in specs if previous_hashes[owner] != current_hashes[owner]]
        upstream = declaration(text, "Upstream")
        if len(upstream) != 1 or split_ids(upstream[0]) != changed:
            diagnostics.append(diag("REVIEW_UPSTREAM_INVALID", "NO_CHANGE review 的 Upstream 必须精确列出已变化的直接 Owner", review_path))
        previous_values = declaration(text, "Previous Receipt SHA-256")
        current_values = declaration(text, "Current Receipt SHA-256")
        if len(previous_values) != 1 or parse_hash_map(previous_values[0]) != {owner: previous_hashes[owner] for owner in changed}:
            diagnostics.append(diag("REVIEW_PREVIOUS_RECEIPT_MISMATCH", "review 中的旧 receipt hashes 无效", review_path))
        if len(current_values) != 1 or parse_hash_map(current_values[0]) != {owner: current_hashes[owner] for owner in changed}:
            diagnostics.append(diag("REVIEW_CURRENT_RECEIPT_MISMATCH", "review 中的当前 receipt hashes 无效", review_path))
        rationales = declaration(text, "Impact Rationale")
        rationale_ids = set(STABLE_ID_PATTERN.findall(rationales[0])) if len(rationales) == 1 else set()
        if len(rationales) != 1 or not set(ids).issubset(rationale_ids):
            diagnostics.append(diag("REVIEW_IMPACT_RATIONALE_INVALID", "Impact Rationale 必须点名每个稳定 ID", review_path))
    return diagnostics


def owner_inputs(files: ProjectFiles) -> tuple[list[dict[str, object]], tuple[Artifact, ...]]:
    diagnostics: list[dict[str, object]] = []
    artifacts: list[Artifact] = []
    for name, path in (
        ("project", PROJECT_PATH),
        ("requirementsValidation", REQUIREMENTS_VALIDATION_PATH),
        ("requirements", REQUIREMENTS_PATH),
        ("asIsValidation", ASIS_VALIDATION_PATH),
        ("asIs", ASIS_PATH),
        ("designValidation", DESIGN_VALIDATION_PATH),
        ("design", DESIGN_PATH),
        ("technicalRequirements", TECHNICAL_PATH),
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


def risk_summary_bytes(delivery: dict[str, Any], candidate_hash: str) -> bytes:
    assumptions = delivery["assumptions"]
    open_items = [item for item in assumptions if item.get("status") == "待确认"]
    uat_count = sum(1 for item in delivery["stories"] if item.get("uatRelevant") is True)
    lines = [
        "# Story 风险摘要",
        "",
        f"Candidate SHA-256: {candidate_hash}",
        f"Feature Count: {len({item['featureId'] for item in delivery['stories']})}",
        f"Story Count: {len(delivery['stories'])}",
        f"Acceptance Criterion Count: {len(delivery['acceptanceCriteria'])}",
        f"Integration Count: {len(delivery['integrations'])}",
        f"Assumption / Risk Count: {len(assumptions)}",
        f"Open Assumption / Risk Count: {len(open_items)}",
        f"UAT-relevant Story Count: {uat_count}",
    ]
    if open_items:
        lines.extend(
            [
                "",
                "## 待确认假设与风险",
                "",
                "| ID | Type | Name | Trigger | Responsibility | Handling |",
                "|---|---|---|---|---|---|",
                *[
                    "| "
                    + " | ".join(
                        str(item.get(key, "")).replace("|", "\\|").replace("\n", "<br>")
                        for key in (
                            "assumptionId",
                            "type",
                            "name",
                            "trigger",
                            "responsibilityBoundary",
                            "handling",
                        )
                    )
                    + " |"
                    for item in open_items
                ],
            ]
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


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
                **file_entry("delivery", candidate_path, candidate_payload),
                "targetPath": STABLE_PATH,
            }
        ],
        "context": context,
        "inputArtifacts": [input_entry(item) for item in inputs],
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
    if set(manifest) != {
        "algorithm",
        "claimMetrics",
        "contextBudget",
        "concernIds",
        "fragments",
        "inputArtifacts",
        "owner",
        "ownerControl",
        "readProtocol",
        "reviewClaims",
        "selectedEffectiveStartItemIds",
        "selectedFeatureIds",
        "selectedQuestionIds",
    }:
        diagnostics.append(
            diag(
                "CONTEXT_MANIFEST_INVALID",
                "context manifest fields do not match the current contract",
                CONTEXT_MANIFEST_PATH,
            )
        )
    if manifest.get("algorithm") != "ai-sow-generate-story-context-v1":
        diagnostics.append(
            diag("CONTEXT_MANIFEST_INVALID", "context manifest algorithm is invalid", CONTEXT_MANIFEST_PATH)
        )
    if manifest.get("owner") != SUBJECT:
        diagnostics.append(
            diag("CONTEXT_MANIFEST_INVALID", "context manifest owner is invalid", CONTEXT_MANIFEST_PATH)
        )
    if manifest.get("contextBudget") != context_budget() or manifest.get(
        "readProtocol"
    ) != read_protocol():
        diagnostics.append(
            diag(
                "CONTEXT_MANIFEST_INVALID",
                "context budget or read protocol is invalid",
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
    if manifest.get("concernIds") != list(GO_LIVE_CONCERNS):
        diagnostics.append(
            diag("CONTEXT_MANIFEST_INVALID", "context Concern order is invalid", CONTEXT_MANIFEST_PATH)
        )
    if manifest.get("inputArtifacts") != [input_entry(item) for item in inputs]:
        diagnostics.append(
            diag("CONTEXT_INPUT_STALE", "context inputs do not match current Owner inputs", CONTEXT_MANIFEST_PATH)
        )
    fragments = manifest.get("fragments")
    if not isinstance(fragments, list):
        diagnostics.append(
            diag("CONTEXT_MANIFEST_INVALID", "context fragments must be an ordered array", CONTEXT_MANIFEST_PATH)
        )
        return None, diagnostics
    expected_fragments: list[dict[str, object]] = []
    for name, path in CONTEXT_FRAGMENT_SPECS:
        try:
            expected_fragments.append(expected_context_fragment(files, name, path))
        except ProjectIOError as error:
            diagnostics.append(diag(error.code, str(error), error.relative_path))
            continue
    if fragments != expected_fragments:
        diagnostics.append(
            diag(
                "CONTEXT_FRAGMENT_STALE",
                "context fragment hashes do not match the current manifest",
                CONTEXT_MANIFEST_PATH,
            )
        )
    expected_claims: dict[str, object] | None = None
    try:
        expected_claims = expected_review_claims(files, CLAIMS_PATH)
    except ProjectIOError as error:
        diagnostics.append(diag(error.code, str(error), error.relative_path))
    if expected_claims is not None and manifest.get("reviewClaims") != expected_claims:
        diagnostics.append(
            diag(
                "CONTEXT_REVIEW_CLAIMS_STALE",
                "review claims do not match the current manifest",
                CONTEXT_MANIFEST_PATH,
            )
        )
    if diagnostics:
        return None, diagnostics
    return {
        "fragments": expected_fragments,
        "manifest": file_entry("manifest", CONTEXT_MANIFEST_PATH, manifest_payload),
        "reviewClaims": expected_claims,
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
    if value != {
        "algorithm": algorithm,
        "decision": decision,
        "owner": SUBJECT,
        "packetSha256": packet_hash,
    }:
        return [diag(invalid_code, f"binding does not match current review packet: {path}", path)]
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
        diagnostics.append(diag("REVIEW_PACKET_INVALID", "review packet fields are invalid", packet_path))
    comparisons = (
        ("candidateOutputs", "REVIEW_PACKET_CANDIDATE_STALE", candidate_path),
        ("context", "REVIEW_PACKET_CONTEXT_STALE", CONTEXT_MANIFEST_PATH),
        ("review", "REVIEW_PACKET_REVIEW_STALE", review_path),
        ("inputArtifacts", "REVIEW_PACKET_INPUT_STALE", packet_path),
        ("riskSummary", "REVIEW_PACKET_RISK_SUMMARY_STALE", risk_summary_path),
    )
    for key, code, path in comparisons:
        if packet.get(key) != expected_packet[key]:
            diagnostics.append(diag(code, f"review packet field is stale: {key}", path))
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
    files.write_atomic(VALIDATION_PATH, canonical_json_bytes({"owner": SUBJECT, "passed": False, "diagnostics": diagnostics}))


def main() -> int:
    args = parse_args()
    if args.mode in {"record-reviewer", "write-reviewer"}:
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
                    "summary": "Delivery data is invalid",
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
        for contract, builder in (
            (REQUIREMENT_CONTRACT, current_requirement_inputs),
            (ASIS_CONTRACT, current_asis_inputs),
            (DESIGN_CONTRACT, current_design_inputs),
        ):
            if diagnostics:
                break
            diagnostics.extend(owner_handoff(files, contract, builder).diagnostics)
        schema = json.loads((Path(__file__).resolve().parents[1] / "contracts/delivery.schema.json").read_text(encoding="utf-8"))
        relative = STABLE_PATH if args.mode == "rebind" else args.candidate
        payload: bytes | None = None
        delivery: dict[str, Any] | None = None
        if not diagnostics:
            payload, delivery, local = load_candidate(files, relative, schema)
            diagnostics.extend(local)
        inputs: tuple[Artifact, ...] = ()
        upstream: dict[str, dict[str, Any]] | None = None
        if not diagnostics and delivery is not None:
            upstream, local = load_upstreams(files)
            diagnostics.extend(local)
            defaults, local = questionnaire_defaults(files)
            diagnostics.extend(local)
            if upstream is not None and not diagnostics:
                diagnostics.extend(validate_semantics(delivery, upstream, defaults))
                diagnostics.extend(
                    validate_review(
                        files,
                        delivery,
                        upstream,
                        defaults,
                        require_no_change=no_change,
                        review_path=args.review_path,
                    )
                )
                local, inputs = owner_inputs(files)
                diagnostics.extend(local)
                if not diagnostics and no_change and payload is not None:
                    try:
                        validate_no_change_candidate(
                            files,
                            CONTRACT,
                            inputs,
                            {"delivery": payload},
                        )
                    except ProjectIOError as error:
                        diagnostics.append(diag(error.code, str(error), error.relative_path))
        review_payload: bytes | None = None
        summary_payload: bytes | None = None
        packet_payload: bytes | None = None
        expected_packet: dict[str, object] | None = None
        if (
            not diagnostics
            and args.mode == "review"
            and payload is not None
            and delivery is not None
        ):
            diagnostics.extend(
                validate_review_artifacts(
                    files,
                    args.project_root,
                    SUBJECT,
                    CLAIMS_PATH,
                    {"delivery": delivery},
                )
            )
        if (
            not diagnostics
            and args.mode in {"review", "publish-approved"}
            and payload is not None
            and delivery is not None
        ):
            context, local = context_packet_entry(files, inputs)
            diagnostics.extend(local)
            if not diagnostics:
                try:
                    review_payload = files.read_bytes(args.review_path)
                except ProjectIOError:
                    diagnostics.append(
                        diag("REVIEW_MISSING", "Story review candidate is unavailable", args.review_path)
                    )
            if review_payload is not None and context is not None:
                summary_payload = risk_summary_bytes(delivery, sha256_bytes(payload))
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
                        if args.staging_root is None:
                            publish_review_packet(
                                files,
                                packet_path=args.packet_path,
                                packet_payload=packet_payload,
                                reviewer_path=REVIEWER_PATH,
                                approval_path=APPROVAL_PATH,
                            )
                        else:
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
                                    "risk summary bytes do not match current candidate",
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
                    report = publish_owner(files, CONTRACT, inputs, {"delivery": payload})
                elif args.mode == "publish-approved":
                    assert payload is not None and review_payload is not None
                    files.write_atomic(REVIEW_PATH, review_payload)
                    publisher = publish_no_change_owner if no_change else publish_owner
                    report = publisher(files, CONTRACT, inputs, {"delivery": payload})
                elif args.mode == "rebind":
                    report = rebind_owner(files, CONTRACT, inputs)
            except ProjectIOError as error:
                diagnostics.append(diag(error.code, str(error), error.relative_path))
        if diagnostics and args.mode in {"publish", "rebind"}:
            write_failure(files, diagnostics)
        if diagnostics:
            outcome = "BLOCKED"
            summary = "Delivery data is invalid"
            outputs: list[str] = []
        elif args.mode == "review":
            outcome = "REVIEW_REQUIRED"
            summary = "Delivery review packet is ready"
            outputs = [args.risk_summary_path, args.packet_path]
        else:
            outcome = "OK"
            summary = "Delivery data is valid"
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
        if delivery is not None:
            result["artifactMetrics"] = artifact_metrics({"delivery": delivery})
        if packet_payload is not None:
            result["packetSha256"] = sha256_bytes(packet_payload)
        if report is not None:
            result["receipt"] = report["compilationReceipt"]
        print(json.dumps(result, ensure_ascii=False))
        return 0 if not diagnostics else 2
    except (ProjectIOError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"outcome": "BLOCKED", "summary": "Delivery validation could not run", "diagnostics": [diag(getattr(error, "code", "VALIDATOR_BLOCKED"), str(error))], "outputs": []}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
