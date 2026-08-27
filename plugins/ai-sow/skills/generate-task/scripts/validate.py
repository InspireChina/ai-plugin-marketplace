from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from read_template import read_contract


# Windows 控制台默认使用本地代码页（如 cp936），会把中文结构化输出写成非 UTF-8 字节。
# 调用方按 UTF-8 读取 stdout/stderr，这里显式固定编码，与 POSIX 行为保持一致。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

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


SUBJECT = "generate-task"
SCHEMA_ID = "urn:ai-sow:generate-task:estimate:0.2"
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
DELIVERY_PATH = ".ai-sow/data/generate-story/delivery.json"
DELIVERY_VALIDATION_PATH = ".ai-sow/validation/generate-story.json"
DELIVERY_REVIEW_PATH = ".ai-sow/reviews/generate-story.md"
TEMPLATE_PATH = ".ai-sow/templates/sow-template.xlsx"
REVIEW_PATH = ".ai-sow/reviews/generate-task.md"
STABLE_PATH = ".ai-sow/data/generate-task/estimate.json"
VALIDATION_PATH = ".ai-sow/validation/generate-task.json"
PACKET_PATH = ".ai-sow/work/generate-task/review-packet.json"
RISK_SUMMARY_PATH = ".ai-sow/work/generate-task/risk-summary.md"
REVIEWER_PATH = ".ai-sow/work/generate-task/reviewer.json"
APPROVAL_PATH = ".ai-sow/work/generate-task/approval.json"
CONTEXT_MANIFEST_PATH = ".ai-sow/work/generate-task/context/manifest.json"
CONTEXT_FRAGMENT_SPECS = (
    ("delivery", ".ai-sow/work/generate-task/context/delivery.json"),
    ("design", ".ai-sow/work/generate-task/context/design.json"),
    ("asIs", ".ai-sow/work/generate-task/context/as-is.json"),
    ("technicalRequirements", ".ai-sow/work/generate-task/context/technical-requirements.json"),
    ("templateCatalog", ".ai-sow/work/generate-task/context/template-catalog.json"),
)
REVIEW_PACKET_ALGORITHM = "ai-sow-owner-review-packet-v1"
REVIEWER_ALGORITHM = "ai-sow-owner-reviewer-v1"
APPROVAL_ALGORITHM = "ai-sow-owner-approval-v1"
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
STABLE_ID_PATTERN = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")
EMPTY = {"", "-", "—", "N/A", "NONE", "NOT_APPLICABLE"}
ANCHOR_KINDS = {"CODE", "CONTRACT", "CONFIGURATION", "DEPLOYMENT"}
REQUIRED_REVIEW_SECTIONS = (
    "Story → Task",
    "基础单元",
    "工作模式",
    "复杂度",
    "现状依据",
    "Integration 一对一",
    "遗漏 / 重叠 / 排除理由",
    "估算前提",
    "审查与批准",
)
GENERIC_RATIONALES = {
    "新建任务",
    "按需求新建",
    "按需求调整",
    "接入复用",
    "按需求",
    "工作量较大",
    "复杂度高",
    "复杂度低",
    "简单",
    "复杂",
}
REUSE_ACTIVITY_LABELS = {
    "REGISTER": "注册",
    "CONFIGURE": "配置",
    "WRAP": "封装",
    "MAP": "映射",
    "ADAPT": "适配",
    "AUTHENTICATE": "认证",
    "TENANT_SETUP": "租户设置",
    "PERMISSION_SETUP": "权限设置",
    "SPECIALIZED_VERIFY": "专项验证",
}
EXISTING_OBJECT_NEW_WORK = {"数据迁移", "系统功能下线", "同一根因问题整改"}
EXISTING_CUTOVER_MARKERS = ("现有", "已有", "当前运行", "生产", "切流", "替换")
TEST_ASSET_MARKERS = (
    "测试资产",
    "回归资产",
    "测试方案",
    "测试范围",
    "测试用例",
    "测试脚本",
    "测试配置",
    "测试框架",
    "自动化框架",
    "恢复演练",
)
ADJUSTMENT_ASSET_MARKERS = {
    "数据迁移": ("迁移资产", "迁移脚本", "迁移方案", "映射规则"),
    "发布切换": ("切换资产", "切换方案", "切换清单", "发布方案"),
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
    contract_ids=("urn:ai-sow:analyze-as-is:asis:0.1",),
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
STORY_CONTRACT = OwnerContract(
    subject="generate-story",
    contract_ids=("urn:ai-sow:generate-story:delivery:0.2",),
    validation_path=DELIVERY_VALIDATION_PATH,
    reviews=(("approvedReview", DELIVERY_REVIEW_PATH),),
    outputs=(("delivery", DELIVERY_PATH),),
)
CONTRACT = OwnerContract(
    subject=SUBJECT,
    contract_ids=(SCHEMA_ID,),
    validation_path=VALIDATION_PATH,
    reviews=(("approvedReview", REVIEW_PATH),),
    outputs=(("estimate", STABLE_PATH),),
)


def diag(code: str, message: str, path: str = "") -> dict[str, object]:
    value: dict[str, object] = {"code": code, "message": message}
    if path:
        value["path"] = path
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and publish Estimate handoff data")
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
    parser.add_argument("--candidate", default=".ai-sow/work/generate-task/estimate.candidate.json")
    parser.add_argument("--review-path", default=REVIEW_PATH)
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


def review_path_diagnostics(mode: str, review_path: str) -> list[dict[str, object]]:
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
    parts = review_path.split("/")
    if (
        not review_path
        or review_path.startswith("/")
        or "\\" in review_path
        or any(part in {"", ".", ".."} for part in parts)
        or parts[0].endswith(":")
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
    artifacts = [
        Artifact(
            "project",
            "FILE",
            PROJECT_PATH,
            current_file_hash(files, PROJECT_PATH, REQUIREMENTS_VALIDATION_PATH, "project"),
        )
    ]
    names: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("sourceDocumentId"), str) or not isinstance(source.get("file"), str):
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
        artifacts.append(
            Artifact(
                "questionnaire",
                "QUESTIONNAIRE_PRESENCE",
                "questionnaire:NOT_REQUIRED",
                sha256_bytes(logical),
            )
        )
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
    snapshot = next(
        (entry for entry in snapshots if isinstance(entry, dict) and entry.get("repoId") == repo_id),
        None,
    )
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
        artifacts.append(
            Artifact(
                f"repository:{repo_id}",
                "CANONICAL_JSON",
                f"repository:{repo_id}",
                sha256_bytes(canonical_json_bytes(snapshot)),
            )
        )
    for snapshot in prior_sows:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("priorSowId"), str) or not isinstance(snapshot.get("file"), str):
            return (), upstream_failure("analyze-as-is", ASIS_PATH, "prior SOW contract is invalid")
        name = f"priorSow:{snapshot['priorSowId']}"
        artifacts.append(
            Artifact(
                name,
                "FILE",
                snapshot["file"],
                current_file_hash(files, snapshot["file"], ASIS_VALIDATION_PATH, name),
            )
        )
    names: set[str] = set()
    for entry in evidence:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(field), str) for field in ("evidenceId", "kind", "reference")):
            return (), upstream_failure("analyze-as-is", ASIS_PATH, "Evidence input contract is invalid")
        name = f"evidence:{entry['evidenceId']}"
        path: str | None = None
        if entry["kind"] == "RUNTIME" or (
            entry["kind"] == "DOCUMENT" and not entry["reference"].startswith("requirements:")
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
        if name in names:
            return (), upstream_failure("analyze-as-is", ASIS_PATH, "Evidence input names are not unique")
        names.add(name)
        artifacts.append(
            Artifact(name, "FILE", path, current_file_hash(files, path, ASIS_VALIDATION_PATH, name))
        )
    questionnaire = declaration(read_review(files, ASIS_REVIEW_PATH), "Questionnaire")
    if questionnaire == ["NOT_REQUIRED"]:
        try:
            current = files.read_bytes(ASIS_QUESTIONNAIRE_PATH)
        except ProjectIOError:
            logical = canonical_json_bytes({"declaration": "NOT_REQUIRED"})
        else:
            logical = canonical_json_bytes({"declaration": "PRESENT", "sha256": sha256_bytes(current)})
        artifacts.append(
            Artifact(
                "questionnaire",
                "QUESTIONNAIRE_PRESENCE",
                "questionnaire:NOT_REQUIRED",
                sha256_bytes(logical),
            )
        )
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


def current_story_inputs(files: ProjectFiles) -> tuple[tuple[Artifact, ...], MatchResult | None]:
    return (
        tuple(
            Artifact(name, "FILE", path, current_file_hash(files, path, DELIVERY_VALIDATION_PATH, name))
            for name, path in (
                ("project", PROJECT_PATH),
                ("requirementsValidation", REQUIREMENTS_VALIDATION_PATH),
                ("requirements", REQUIREMENTS_PATH),
                ("asIsValidation", ASIS_VALIDATION_PATH),
                ("asIs", ASIS_PATH),
                ("designValidation", DESIGN_VALIDATION_PATH),
                ("design", DESIGN_PATH),
                ("technicalRequirements", TECHNICAL_PATH),
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
    if failure is not None:
        return failure
    result = match_owner(files, contract, expected)
    return result


def load_upstreams(
    files: ProjectFiles,
) -> tuple[dict[str, dict[str, Any]] | None, list[dict[str, object]]]:
    values: dict[str, dict[str, Any]] = {}
    for name, owner, path in (
        ("asIs", "analyze-as-is", ASIS_PATH),
        ("delivery", "generate-story", DELIVERY_PATH),
    ):
        try:
            value = files.read_json(path)
        except ProjectIOError:
            return None, [
                {
                    "code": "UPSTREAM_HANDOFF_INVALID",
                    "message": "upstream stable output is unreadable",
                    "upstreamOwner": owner,
                    "path": path,
                }
            ]
        if not isinstance(value, dict):
            return None, [
                {
                    "code": "UPSTREAM_HANDOFF_INVALID",
                    "message": "upstream stable output must be an object",
                    "upstreamOwner": owner,
                    "path": path,
                }
            ]
        values[name] = value
    required = {
        "asIs": (("effectiveStartItems", "effectiveStartItemId"),),
        "delivery": (
            ("stories", "storyId"),
            ("acceptanceCriteria", "acceptanceCriterionId"),
            ("integrations", "integrationId"),
        ),
    }
    owners = {"asIs": "analyze-as-is", "delivery": "generate-story"}
    paths = {"asIs": ASIS_PATH, "delivery": DELIVERY_PATH}
    for name, collections in required.items():
        for collection, identifier in collections:
            entries = values[name].get(collection)
            if not isinstance(entries, list) or any(
                not isinstance(entry, dict) or not isinstance(entry.get(identifier), str)
                for entry in entries
            ):
                return None, [
                    {
                        "code": "UPSTREAM_HANDOFF_INVALID",
                        "message": f"upstream output lacks contracted {identifier} values",
                        "upstreamOwner": owners[name],
                        "path": paths[name],
                    }
                ]
    return values, []


def load_candidate(
    files: ProjectFiles,
    relative_path: str,
    schema: dict[str, Any],
) -> tuple[bytes | None, dict[str, Any] | None, list[dict[str, object]]]:
    try:
        payload = files.read_bytes(relative_path)
        value = json.loads(payload.decode("utf-8"))
    except (ProjectIOError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None, [diag("CANDIDATE_UNREADABLE", "Estimate candidate is unavailable", relative_path)]
    diagnostics = [
        diag("SCHEMA_INVALID", error.message, "/" + "/".join(str(part) for part in error.path))
        for error in sorted(
            Draft202012Validator(schema).iter_errors(value),
            key=lambda error: list(error.path),
        )
    ]
    return payload, value if isinstance(value, dict) else None, diagnostics


def normalized(value: str) -> str:
    return re.sub(r"[\s，。；、:：/]+", "", value.casefold())


def generic(value: str) -> bool:
    return normalized(value) in {normalized(candidate) for candidate in GENERIC_RATIONALES}


def validate_semantics(
    estimate: dict[str, Any],
    upstream: dict[str, dict[str, Any]],
    template: dict[str, Any],
) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    delivery = upstream["delivery"]
    stories = {entry["storyId"]: entry for entry in delivery["stories"]}
    criteria = {entry["acceptanceCriterionId"]: entry for entry in delivery["acceptanceCriteria"]}
    integrations = {entry["integrationId"]: entry for entry in delivery["integrations"]}
    effective_starts = {
        entry["effectiveStartItemId"]: entry
        for entry in upstream["asIs"]["effectiveStartItems"]
    }
    configured = {tuple(option) for option in template["taskOptions"]}
    base_units = template["baseUnits"]
    integration_unit_ids = {
        base_unit_id
        for base_unit_id, value in base_units.items()
        if value["name"] in {"内部系统对接", "外部系统对接"}
    }
    if len(integration_unit_ids) != 2:
        diagnostics.append(
            diag(
                "TEMPLATE_INTEGRATION_UNIT_MISSING",
                "template must define internal and external integration base units",
            )
        )

    task_ids = [task["taskId"] for task in estimate["tasks"]]
    for task_id, count in Counter(task_ids).items():
        if count > 1:
            diagnostics.append(diag("ID_DUPLICATE", f"duplicate taskId: {task_id}"))
    for name, count in Counter(task["name"] for task in estimate["tasks"]).items():
        if count > 1:
            diagnostics.append(
                diag(
                    "TASK_NAME_DUPLICATE",
                    f"duplicate Task name, which cannot be used as an Excel reference: {name}",
                )
            )
    descriptions = Counter(
        (task["storyId"], " ".join(task["name"].casefold().split()))
        for task in estimate["tasks"]
    )
    for (story_id, description), count in descriptions.items():
        if count > 1:
            diagnostics.append(
                diag(
                    "TASK_DESCRIPTION_DUPLICATE",
                    f"duplicate normalized Task description for {story_id}: {description}",
                )
            )

    tasks_by_story: Counter[str] = Counter()
    ac_coverage: Counter[str] = Counter()
    tasks_by_integration: Counter[str] = Counter()
    release_cutovers: Counter[str] = Counter()
    problem_units: dict[str, set[str]] = defaultdict(set)
    for task in estimate["tasks"]:
        task_id = task["taskId"]
        story_id = task["storyId"]
        if story_id not in stories:
            diagnostics.append(diag("STORY_REF_UNKNOWN", f"unknown Story: {story_id}"))
        else:
            tasks_by_story[story_id] += 1
        if (task["baseUnit"], task["workMode"]) not in configured:
            diagnostics.append(
                diag(
                    "TASK_OPTION_NOT_CONFIGURED",
                    f"task option is not configured: {task['baseUnit']}/{task['workMode']}",
                )
            )
        base_unit = base_units.get(task["baseUnit"])
        base_name = base_unit["name"] if base_unit else ""
        if generic(task["workModeRationale"]):
            diagnostics.append(
                diag(
                    "WORK_MODE_RATIONALE_GENERIC",
                    f"work-mode rationale lacks instance facts: {task_id}",
                )
            )
        if task["complexity"] in {"S", "L"} and base_unit is not None:
            rationale = task["complexityRationale"]
            standard = base_unit["complexityStandards"][task["complexity"]]
            if generic(rationale) or normalized(rationale) == normalized(standard):
                diagnostics.append(
                    diag(
                        "COMPLEXITY_RATIONALE_GENERIC",
                        f"complexity rationale must state facts beyond the catalog standard: {task_id}",
                    )
                )

        for criterion_id in task["acceptanceCriterionIds"]:
            criterion = criteria.get(criterion_id)
            if criterion is None:
                diagnostics.append(diag("AC_REF_UNKNOWN", f"unknown Acceptance Criterion: {criterion_id}"))
                continue
            ac_coverage[criterion_id] += 1
            if criterion.get("storyId") != story_id:
                diagnostics.append(
                    diag(
                        "AC_STORY_MISMATCH",
                        f"Task and Acceptance Criterion must share a Story: {task_id}/{criterion_id}",
                    )
                )

        matched = task.get("matchedEffectiveStartItemId")
        if matched is not None and matched not in effective_starts:
            diagnostics.append(
                diag("EFFECTIVE_START_REF_UNKNOWN", f"unknown Effective Start: {matched}")
            )
        needs_existing = base_name in EXISTING_OBJECT_NEW_WORK or (
            base_name == "发布切换"
            and any(marker in task["workModeRationale"] for marker in EXISTING_CUTOVER_MARKERS)
        )
        if (
            task["workMode"] in {"调整", "接入复用"}
            or (task["workMode"] == "新建" and needs_existing)
        ) and not matched:
            diagnostics.append(
                diag("EFFECTIVE_START_REQUIRED", f"Task requires an Effective Start: {task_id}")
            )
        evidence = task.get("workModeEvidence")
        referenced: dict[str, Any] | None = None
        if task["workMode"] in {"调整", "接入复用"} and isinstance(evidence, dict):
            evidence_id = evidence.get("effectiveStartItemId")
            evidence_name = evidence.get("effectiveStartItemName")
            if evidence_id != matched:
                diagnostics.append(
                    diag(
                        "WORK_MODE_EVIDENCE_REF_MISMATCH",
                        f"work-mode evidence must reference a matched Effective Start: {task_id}",
                    )
                )
            referenced = effective_starts.get(evidence_id)
            if referenced is not None:
                if evidence_name != referenced.get("name"):
                    diagnostics.append(
                        diag(
                            "WORK_MODE_EVIDENCE_NAME_MISMATCH",
                            f"work-mode evidence name differs from Effective Start: {task_id}",
                        )
                    )
                elif evidence_name not in " ".join(
                    value
                    for value in (task.get("name"), task.get("workModeRationale"), task.get("rationale"))
                    if isinstance(value, str)
                ):
                    diagnostics.append(
                        diag(
                            "EFFECTIVE_START_IRRELEVANT",
                            f"Task does not name the Effective Start object: {task_id}",
                        )
                    )
        markers = (
            TEST_ASSET_MARKERS
            if base_unit is not None and base_unit["taskFamily"] == "质量验证"
            else ADJUSTMENT_ASSET_MARKERS.get(base_name, ())
        )
        if task["workMode"] == "调整" and markers and referenced is not None:
            start_text = f"{referenced.get('name', '')} {referenced.get('summary', '')}"
            if not any(marker in start_text for marker in markers):
                diagnostics.append(
                    diag(
                        "WORK_MODE_ADJUSTMENT_ASSET_UNSPECIFIED",
                        f"adjustment requires an existing {base_name} asset; otherwise use 新建: {task_id}",
                    )
                )
        if task["workMode"] == "接入复用" and isinstance(evidence, dict):
            activities = evidence.get("projectSideWorkTypes", [])
            activity_order = {
                activity: index for index, activity in enumerate(REUSE_ACTIVITY_LABELS)
            }
            labels = [
                REUSE_ACTIVITY_LABELS[activity]
                for activity in activities
                if activity in REUSE_ACTIVITY_LABELS
            ]
            commitment = "本项目负责并交付：" + "、".join(labels)
            rationale = f"{evidence.get('effectiveStartItemName', '')}保持不变；{commitment}。"
            if (
                not activities
                or len(labels) != len(activities)
                or activities
                != sorted(activities, key=lambda activity: activity_order.get(activity, -1))
                or evidence.get("projectSideWorkCommitment") != commitment
                or task["workModeRationale"] != rationale
            ):
                diagnostics.append(
                    diag(
                        "WORK_MODE_REUSE_NOT_ESTIMABLE",
                        f"reuse evidence must produce this canonical rationale: {rationale} [{task_id}]",
                    )
                )

        if task["baseUnit"] == "BU-RELEASE-CUTOVER":
            release_cutovers[story_id] += 1
        if task["baseUnit"] in {"BU-TECH-SUPPORT", "BU-ROOT-CAUSE-REMEDIATION"}:
            problem_units[story_id].add(task["baseUnit"])

        integration_id = task.get("integrationId")
        if task["baseUnit"] in integration_unit_ids:
            if integration_id is None:
                diagnostics.append(diag("INTEGRATION_ID_REQUIRED", f"integration Task lacks Integration: {task_id}"))
            else:
                tasks_by_integration[integration_id] += 1
                integration = integrations.get(integration_id)
                if integration is None:
                    diagnostics.append(diag("INTEGRATION_REF_UNKNOWN", f"unknown Integration: {integration_id}"))
                else:
                    if integration.get("storyId") != story_id:
                        diagnostics.append(
                            diag(
                                "INTEGRATION_STORY_MISMATCH",
                                f"Task and Integration must share a Story: {task_id}/{integration_id}",
                            )
                        )
                    expected_name = (
                        "内部系统对接"
                        if integration.get("owner") == "INTERNAL"
                        else "外部系统对接"
                    )
                    if base_name != expected_name:
                        diagnostics.append(
                            diag(
                                "INTEGRATION_OWNER_MISMATCH",
                                f"Integration ownership requires {expected_name}: {task_id}",
                            )
                        )
        elif integration_id is not None:
            diagnostics.append(
                diag(
                    "INTEGRATION_ID_FORBIDDEN",
                    f"non-integration Task references an Integration: {task_id}",
                )
            )

    for story_id in sorted(set(stories) - set(tasks_by_story)):
        diagnostics.append(diag("TASK_COVERAGE_MISSING", f"Story has no Task: {story_id}"))
    for criterion_id in criteria:
        if ac_coverage[criterion_id] == 0:
            diagnostics.append(diag("AC_COVERAGE_MISSING", f"Acceptance Criterion has no Task: {criterion_id}"))
    for integration_id in integrations:
        if tasks_by_integration[integration_id] == 0:
            diagnostics.append(diag("INTEGRATION_COVERAGE_MISSING", f"Integration has no Task: {integration_id}"))
        elif tasks_by_integration[integration_id] > 1:
            diagnostics.append(diag("INTEGRATION_COVERAGE_DUPLICATE", f"Integration has multiple Tasks: {integration_id}"))
    for story_id, count in release_cutovers.items():
        if count > 1:
            diagnostics.append(diag("RELEASE_CUTOVER_DUPLICATE", f"Story has multiple release-cutover Tasks: {story_id}"))
    problem_pair = {"BU-TECH-SUPPORT", "BU-ROOT-CAUSE-REMEDIATION"}
    for story_id, units in problem_units.items():
        if problem_pair <= units:
            diagnostics.append(diag("PROBLEM_TASK_OVERLAP", f"Story double counts diagnosis and remediation: {story_id}"))
    return diagnostics


def parse_mapping(value: str) -> dict[str, tuple[str, ...]] | None:
    if value == "NONE":
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for part in [item.strip() for item in value.split(";") if item.strip()]:
        if "=" not in part:
            return None
        left, right = part.split("=", 1)
        ids = tuple(split_ids(right))
        if not left or left in result or not ids or len(ids) != len(set(ids)):
            return None
        result[left] = ids
    return result


def mappings_match(
    actual: dict[str, tuple[str, ...]] | None,
    expected: dict[str, tuple[str, ...]],
) -> bool:
    return (
        actual is not None
        and set(actual) == set(expected)
        and all(set(actual[key]) == set(value) for key, value in expected.items())
    )


def stable_ids(estimate: dict[str, Any]) -> list[str]:
    return [task["taskId"] for task in estimate["tasks"]]


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
        if owner in result or owner not in {"analyze-as-is", "generate-design", "generate-story"} or not HASH_PATTERN.fullmatch(digest):
            return None
        result[owner] = digest
    return result


def expected_maps(
    estimate: dict[str, Any],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    stories: dict[str, list[str]] = defaultdict(list)
    criteria: dict[str, list[str]] = defaultdict(list)
    integrations: dict[str, list[str]] = defaultdict(list)
    for task in estimate["tasks"]:
        stories[task["storyId"]].append(task["taskId"])
        for criterion_id in task["acceptanceCriterionIds"]:
            criteria[criterion_id].append(task["taskId"])
        if "integrationId" in task:
            integrations[task["integrationId"]].append(task["taskId"])
    return (
        {key: tuple(value) for key, value in stories.items()},
        {key: tuple(value) for key, value in criteria.items()},
        {key: tuple(value) for key, value in integrations.items()},
    )


def validate_review(
    files: ProjectFiles,
    estimate: dict[str, Any],
    template_hash: str,
    *,
    require_no_change: bool,
    review_path: str = REVIEW_PATH,
) -> list[dict[str, object]]:
    text = read_review(files, review_path)
    if not text:
        return [diag("REVIEW_MISSING", "approved Task review is unavailable", review_path)]
    diagnostics: list[dict[str, object]] = []
    for section in REQUIRED_REVIEW_SECTIONS:
        if len(re.findall(rf"(?m)^## {re.escape(section)}\s*$", text)) != 1:
            diagnostics.append(diag("REVIEW_SECTION_INVALID", f"review must contain exactly one section: {section}", review_path))
    ids = stable_ids(estimate)
    declared = declaration(text, "Stable IDs")
    declared_ids = split_ids(declared[0]) if len(declared) == 1 else []
    if len(declared) != 1 or len(declared_ids) != len(set(declared_ids)) or set(declared_ids) != set(ids):
        diagnostics.append(diag("REVIEW_ID_SET_MISMATCH", "review Stable IDs do not match Estimate", review_path))
    story_map, ac_map, integration_map = expected_maps(estimate)
    for label, expected, code in (
        ("Story Map", story_map, "REVIEW_STORY_MAP_INVALID"),
        ("AC Map", ac_map, "REVIEW_AC_MAP_INVALID"),
        ("Integration Map", integration_map, "REVIEW_INTEGRATION_MAP_INVALID"),
    ):
        values = declaration(text, label)
        actual = parse_mapping(values[0]) if len(values) == 1 else None
        if not mappings_match(actual, expected):
            diagnostics.append(diag(code, f"review {label} does not match Estimate", review_path))
    tasks = estimate["tasks"]
    expected_sets = (
        ("Base Units", {task["baseUnit"] for task in tasks}, "REVIEW_BASE_UNITS_INVALID"),
        ("Work Modes", {task["workMode"] for task in tasks}, "REVIEW_WORK_MODES_INVALID"),
        ("Complexities", {task["complexity"] for task in tasks}, "REVIEW_COMPLEXITIES_INVALID"),
        (
            "Effective Start IDs",
            {
                identifier
                for task in tasks
                if (identifier := task.get("matchedEffectiveStartItemId")) is not None
            },
            "REVIEW_EFFECTIVE_START_IDS_INVALID",
        ),
    )
    for label, expected, code in expected_sets:
        values = declaration(text, label)
        actual = split_ids(values[0]) if len(values) == 1 else []
        if len(values) != 1 or len(actual) != len(set(actual)) or set(actual) != expected:
            diagnostics.append(diag(code, f"review {label} does not match Estimate", review_path))
    if declaration(text, "Scope Review") != ["PASSED"]:
        diagnostics.append(diag("REVIEW_SCOPE_NOT_PASSED", "Scope Review must be PASSED", review_path))
    if declaration(text, "Template SHA-256") != [template_hash]:
        diagnostics.append(diag("REVIEW_TEMPLATE_HASH_MISMATCH", "review template hash is stale", review_path))
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
        specs = (
            ("analyze-as-is", "asIsValidation", ASIS_VALIDATION_PATH),
            ("generate-design", "designValidation", DESIGN_VALIDATION_PATH),
            ("generate-story", "deliveryValidation", DELIVERY_VALIDATION_PATH),
        )
        previous_hashes = {owner: named_hash(previous, name) for owner, name, _ in specs}
        current_hashes = {
            owner: current_file_hash(files, path, VALIDATION_PATH, name)
            for owner, name, path in specs
        }
        changed = [owner for owner, _, _ in specs if previous_hashes[owner] != current_hashes[owner]]
        upstream = declaration(text, "Upstream")
        if len(upstream) != 1 or split_ids(upstream[0]) != changed:
            diagnostics.append(diag("REVIEW_UPSTREAM_INVALID", "NO_CHANGE review 的 Upstream 必须列出已变化的直接 Owner", review_path))
        previous_values = declaration(text, "Previous Receipt SHA-256")
        current_values = declaration(text, "Current Receipt SHA-256")
        if len(previous_values) != 1 or parse_hash_map(previous_values[0]) != {owner: previous_hashes[owner] for owner in changed}:
            diagnostics.append(diag("REVIEW_PREVIOUS_RECEIPT_MISMATCH", "review 中的旧 receipt hashes 无效", review_path))
        if len(current_values) != 1 or parse_hash_map(current_values[0]) != {owner: current_hashes[owner] for owner in changed}:
            diagnostics.append(diag("REVIEW_CURRENT_RECEIPT_MISMATCH", "review 中的当前 receipt hashes 无效", review_path))
        rationales = declaration(text, "Impact Rationale")
        rationale_ids = set(STABLE_ID_PATTERN.findall(rationales[0])) if len(rationales) == 1 else set()
        if len(rationales) != 1 or not set(ids).issubset(rationale_ids):
            diagnostics.append(diag("REVIEW_IMPACT_RATIONALE_INVALID", "Impact Rationale 必须点名每个 Task ID", review_path))
    return diagnostics


def owner_inputs(files: ProjectFiles) -> tuple[list[dict[str, object]], tuple[Artifact, ...]]:
    diagnostics: list[dict[str, object]] = []
    artifacts: list[Artifact] = []
    for name, path in (
        ("project", PROJECT_PATH),
        ("asIsValidation", ASIS_VALIDATION_PATH),
        ("asIs", ASIS_PATH),
        ("designValidation", DESIGN_VALIDATION_PATH),
        ("design", DESIGN_PATH),
        ("technicalRequirements", TECHNICAL_PATH),
        ("deliveryValidation", DELIVERY_VALIDATION_PATH),
        ("delivery", DELIVERY_PATH),
        ("template", TEMPLATE_PATH),
    ):
        try:
            payload = files.read_bytes(path)
        except ProjectIOError:
            diagnostics.append(diag("INPUT_MISSING", f"required input is unavailable: {path}", path))
        else:
            artifacts.append(Artifact(name, "FILE", path, sha256_bytes(payload)))
    return diagnostics, tuple(artifacts)


def input_entry(artifact: Artifact) -> dict[str, object]:
    return {
        "name": artifact.name,
        "kind": artifact.kind,
        "path": artifact.locator,
        "sha256": artifact.sha256,
    }


def risk_summary_bytes(
    estimate: dict[str, Any],
    delivery: dict[str, Any],
    candidate_hash: str,
) -> bytes:
    tasks = estimate["tasks"]
    story_ids = {task["storyId"] for task in tasks}
    criterion_ids = {
        criterion_id
        for task in tasks
        for criterion_id in task["acceptanceCriterionIds"]
    }
    integration_ids = {
        task["integrationId"] for task in tasks if "integrationId" in task
    }
    complexities = Counter(task["complexity"] for task in tasks)
    work_modes = Counter(task["workMode"] for task in tasks)
    open_delivery_risks = [
        assumption
        for assumption in delivery.get("assumptions", [])
        if isinstance(assumption, dict)
        and assumption.get("type") == "风险"
        and assumption.get("status") == "待确认"
    ]

    def counts(values: Counter[str], order: tuple[str, ...]) -> str:
        return ", ".join(f"{name}={values.get(name, 0)}" for name in order)

    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", "<br>")

    summary = (
        "# Task 风险摘要\n\n"
        f"Candidate SHA-256: {candidate_hash}\n"
        f"Task Count: {len(tasks)}\n"
        f"Story Count: {len(story_ids)}\n"
        f"Acceptance Criterion Count: {len(criterion_ids)}\n"
        f"Integration Task Count: {len(integration_ids)}\n"
        f"Complexities: {counts(complexities, ('S', 'M', 'L'))}\n"
        f"Work Modes: {counts(work_modes, ('新建', '调整', '接入复用'))}\n"
        f"High-risk L Tasks: {complexities.get('L', 0)}\n"
        f"Open Delivery Risks: {len(open_delivery_risks)}\n"
        "Calculation Authority: .ai-sow/templates/sow-template.xlsx\n"
    )
    if open_delivery_risks:
        summary += (
            "\n## 待确认交付风险\n\n"
            "| ID | 名称 | 触发条件 | 责任边界 | 处理方式 |\n"
            "|---|---|---|---|---|\n"
        )
        summary += "".join(
            "| "
            + " | ".join(
                cell(risk.get(key, ""))
                for key in (
                    "assumptionId",
                    "name",
                    "trigger",
                    "responsibilityBoundary",
                    "handling",
                )
            )
            + " |\n"
            for risk in open_delivery_risks
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
                **file_entry("estimate", candidate_path, candidate_payload),
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
        "fragments",
        "inputArtifacts",
        "owner",
        "selectedEffectiveStartItemIds",
        "selectedFeatureIds",
    }:
        diagnostics.append(
            diag(
                "CONTEXT_MANIFEST_INVALID",
                "context manifest fields do not match the current contract",
                CONTEXT_MANIFEST_PATH,
            )
        )
    if manifest.get("algorithm") != "ai-sow-generate-task-context-v1":
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
            diag(
                "CONTEXT_MANIFEST_INVALID",
                "context manifest fragments must be an ordered array",
                CONTEXT_MANIFEST_PATH,
            )
        )
        return None, diagnostics
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
            diag(
                "REVIEW_PACKET_INVALID",
                "review packet fields do not match the current contract",
                packet_path,
            )
        )
    if packet.get("candidateOutputs") != expected_packet["candidateOutputs"]:
        diagnostics.append(
            diag(
                "REVIEW_PACKET_CANDIDATE_STALE",
                "review packet candidate hash does not match current candidate bytes",
                candidate_path,
            )
        )
    if packet.get("context") != expected_packet["context"]:
        diagnostics.append(
            diag(
                "REVIEW_PACKET_CONTEXT_STALE",
                "review packet context hashes do not match current context fragments",
                CONTEXT_MANIFEST_PATH,
            )
        )
    if packet.get("review") != expected_packet["review"]:
        diagnostics.append(
            diag(
                "REVIEW_PACKET_REVIEW_STALE",
                "review packet review hash does not match current review bytes",
                review_path,
            )
        )
    if packet.get("inputArtifacts") != expected_packet["inputArtifacts"]:
        diagnostics.append(
            diag(
                "REVIEW_PACKET_INPUT_STALE",
                "review packet inputs do not match current Owner inputs",
                packet_path,
            )
        )
    if packet.get("riskSummary") != expected_packet["riskSummary"]:
        diagnostics.append(
            diag(
                "REVIEW_PACKET_RISK_SUMMARY_STALE",
                "review packet risk summary does not match current deterministic summary",
                risk_summary_path,
            )
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
    path_diagnostics = review_path_diagnostics(args.mode, args.review_path)
    if path_diagnostics:
        print(
            json.dumps(
                {
                    "outcome": "BLOCKED",
                    "summary": "Estimate data is invalid",
                    "diagnostics": path_diagnostics,
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
            (ASIS_CONTRACT, current_asis_inputs),
            (DESIGN_CONTRACT, current_design_inputs),
            (STORY_CONTRACT, current_story_inputs),
        ):
            if diagnostics:
                break
            diagnostics.extend(owner_handoff(files, contract, builder).diagnostics)
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "contracts/estimate.schema.json").read_text(
                encoding="utf-8"
            )
        )
        relative = STABLE_PATH if args.mode == "rebind" else args.candidate
        payload: bytes | None = None
        estimate: dict[str, Any] | None = None
        packet_payload: bytes | None = None
        review_payload: bytes | None = None
        summary_payload: bytes | None = None
        if not diagnostics:
            payload, estimate, local = load_candidate(files, relative, schema)
            diagnostics.extend(local)
        inputs: tuple[Artifact, ...] = ()
        if not diagnostics and estimate is not None:
            upstream, local = load_upstreams(files)
            diagnostics.extend(local)
            try:
                template = read_contract(files.resolve(TEMPLATE_PATH))
                template_hash = sha256_bytes(files.read_bytes(TEMPLATE_PATH))
            except (OSError, ValueError, ProjectIOError) as error:
                diagnostics.append(diag("TEMPLATE_INVALID", str(error), TEMPLATE_PATH))
                template = {}
                template_hash = ""
            if upstream is not None and not diagnostics:
                diagnostics.extend(validate_semantics(estimate, upstream, template))
                diagnostics.extend(
                    validate_review(
                        files,
                        estimate,
                        template_hash,
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
                            {"estimate": payload},
                        )
                    except ProjectIOError as error:
                        diagnostics.append(diag(error.code, str(error), error.relative_path))
        expected_packet: dict[str, object] | None = None
        if (
            not diagnostics
            and args.mode in {"review", "publish-approved"}
            and payload is not None
            and estimate is not None
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
                            "Task review candidate is unavailable",
                            args.review_path,
                        )
                    )
            if review_payload is not None and context is not None:
                assert upstream is not None
                summary_payload = risk_summary_bytes(
                    estimate,
                    upstream["delivery"],
                    sha256_bytes(payload),
                )
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
                    report = publish_owner(files, CONTRACT, inputs, {"estimate": payload})
                elif args.mode == "publish-approved":
                    assert payload is not None and review_payload is not None
                    files.write_atomic(REVIEW_PATH, review_payload)
                    publisher = publish_no_change_owner if no_change else publish_owner
                    report = publisher(files, CONTRACT, inputs, {"estimate": payload})
                elif args.mode == "rebind":
                    report = rebind_owner(files, CONTRACT, inputs)
            except ProjectIOError as error:
                diagnostics.append(diag(error.code, str(error), error.relative_path))
        if diagnostics and args.mode in {"publish", "rebind"}:
            write_failure(files, diagnostics)
        if diagnostics:
            outcome = "BLOCKED"
            summary = "Estimate data is invalid"
            outputs: list[str] = []
        elif args.mode == "review":
            outcome = "REVIEW_REQUIRED"
            summary = "Estimate review packet is ready"
            outputs = [args.risk_summary_path, args.packet_path]
        else:
            outcome = "OK"
            summary = "Estimate data is valid"
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
                    "summary": "Estimate validation could not run",
                    "diagnostics": [
                        diag(getattr(error, "code", "VALIDATOR_BLOCKED"), str(error))
                    ],
                    "outputs": [],
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
