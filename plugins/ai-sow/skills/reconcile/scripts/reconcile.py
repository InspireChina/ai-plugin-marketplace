from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.project_io import ProjectFiles, ProjectIOError, ProjectView


ALGORITHM = "ai-sow-reconciliation-redo-v1"
CONTRACT_VERSION = "0.1"
PREPARED_CONTRACT_VERSION = "0.2"
PACKET_ALGORITHM = "ai-sow-reconciliation-review-packet-v1"
REVIEWER_ALGORITHM = "ai-sow-reconciliation-reviewer-v1"
APPROVAL_ALGORITHM = "ai-sow-reconciliation-approval-v1"
PACKAGE_ALGORITHM = "ai-sow-package-v1"
GENERATOR_CONTRACT = "receipt-only-beta2-v1"
PROJECT_PATH = ".ai-sow/project.json"
TEMPLATE_PATH = ".ai-sow/templates/sow-template.xlsx"
ASIS_PATH = ".ai-sow/data/analyze-as-is/asis.json"
RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PACKAGE_ID_PATTERN = re.compile(r"^sow-sha256-[0-9a-f]{64}$")
Action = Literal["WRITE", "DELETE"]
Impact = Literal["CHANGED", "NO_CHANGE"]


@dataclass(frozen=True)
class OwnerSpec:
    name: str
    review: str
    output_names: tuple[str, ...]
    outputs: tuple[str, ...]
    candidates: tuple[str, ...]
    receipt: str
    optional_delete_paths: tuple[str, ...] = ()

    @property
    def ordered_paths(self) -> tuple[str, ...]:
        return (self.review, *self.outputs, self.receipt)


OWNER_SPECS = (
    OwnerSpec(
        "analyze-requirement",
        ".ai-sow/reviews/analyze-requirement.md",
        ("requirements",),
        (".ai-sow/data/analyze-requirement/requirements.json",),
        (".ai-sow/work/analyze-requirement/requirements.candidate.json",),
        ".ai-sow/validation/analyze-requirement.json",
        (".ai-sow/reviews/analyze-requirement-questionnaire.md",),
    ),
    OwnerSpec(
        "analyze-as-is",
        ".ai-sow/reviews/analyze-as-is.md",
        ("asIs",),
        (".ai-sow/data/analyze-as-is/asis.json",),
        (".ai-sow/work/analyze-as-is/asis.candidate.json",),
        ".ai-sow/validation/analyze-as-is.json",
    ),
    OwnerSpec(
        "generate-design",
        ".ai-sow/reviews/generate-design.md",
        ("design", "technicalRequirements"),
        (
            ".ai-sow/data/generate-design/design.json",
            ".ai-sow/data/generate-design/requirements.json",
        ),
        (
            ".ai-sow/work/generate-design/design.candidate.json",
            ".ai-sow/work/generate-design/requirements.candidate.json",
        ),
        ".ai-sow/validation/generate-design.json",
    ),
    OwnerSpec(
        "generate-story",
        ".ai-sow/reviews/generate-story.md",
        ("delivery",),
        (".ai-sow/data/generate-story/delivery.json",),
        (".ai-sow/work/generate-story/delivery.candidate.json",),
        ".ai-sow/validation/generate-story.json",
    ),
    OwnerSpec(
        "generate-task",
        ".ai-sow/reviews/generate-task.md",
        ("estimate",),
        (".ai-sow/data/generate-task/estimate.json",),
        (".ai-sow/work/generate-task/estimate.candidate.json",),
        ".ai-sow/validation/generate-task.json",
    ),
)
OWNER_BY_NAME = {spec.name: spec for spec in OWNER_SPECS}

PACKAGE_INPUT_BINDINGS = (
    (
        "sourceRequirements",
        ".ai-sow/data/analyze-requirement/requirements.json",
        "sources/data/analyze-requirement/requirements.json",
    ),
    (
        "asis",
        ".ai-sow/data/analyze-as-is/asis.json",
        "sources/data/analyze-as-is/asis.json",
    ),
    (
        "design",
        ".ai-sow/data/generate-design/design.json",
        "sources/data/generate-design/design.json",
    ),
    (
        "derivedRequirements",
        ".ai-sow/data/generate-design/requirements.json",
        "sources/data/generate-design/requirements.json",
    ),
    (
        "delivery",
        ".ai-sow/data/generate-story/delivery.json",
        "sources/data/generate-story/delivery.json",
    ),
    (
        "estimate",
        ".ai-sow/data/generate-task/estimate.json",
        "sources/data/generate-task/estimate.json",
    ),
)
PACKAGE_REVIEW_BINDINGS = (
    (
        "analyzeRequirement",
        ".ai-sow/reviews/analyze-requirement.md",
        "sources/reviews/analyze-requirement.md",
    ),
    (
        "analyzeAsIs",
        ".ai-sow/reviews/analyze-as-is.md",
        "sources/reviews/analyze-as-is.md",
    ),
    (
        "generateDesign",
        ".ai-sow/reviews/generate-design.md",
        "sources/reviews/generate-design.md",
    ),
    (
        "generateStory",
        ".ai-sow/reviews/generate-story.md",
        "sources/reviews/generate-story.md",
    ),
    (
        "generateTask",
        ".ai-sow/reviews/generate-task.md",
        "sources/reviews/generate-task.md",
    ),
)
PACKAGE_RECEIPT_BINDINGS = (
    (
        "analyzeRequirement",
        ".ai-sow/validation/analyze-requirement.json",
        "validation/analyze-requirement.json",
    ),
    (
        "analyzeAsIs",
        ".ai-sow/validation/analyze-as-is.json",
        "validation/analyze-as-is.json",
    ),
    (
        "generateDesign",
        ".ai-sow/validation/generate-design.json",
        "validation/generate-design.json",
    ),
    (
        "generateStory",
        ".ai-sow/validation/generate-story.json",
        "validation/generate-story.json",
    ),
    (
        "generateTask",
        ".ai-sow/validation/generate-task.json",
        "validation/generate-task.json",
    ),
)
PACKAGE_MANIFEST_KEYS = {
    "packageId",
    "fingerprintAlgorithm",
    "generationFingerprint",
    "generatedWorkbookSha256",
    "projectId",
    "pluginVersion",
    "sowStandardVersion",
    "projectMode",
    "repositories",
    "priorSows",
    "inputs",
    "reviews",
    "template",
    "validationReceipts",
}


class ReconcileError(ValueError):
    def __init__(
        self,
        code: str,
        path: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.details = details or {}

    def diagnostic(self) -> dict[str, object]:
        value: dict[str, object] = {
            "code": self.code,
            "message": str(self),
            "path": self.path,
        }
        value.update(self.details)
        return value


@dataclass(frozen=True)
class FileState:
    state: Literal["FILE", "MISSING"]
    sha256: str | None = None

    def as_json(self) -> dict[str, str]:
        if self.state == "MISSING":
            return {"state": "MISSING"}
        assert self.sha256 is not None
        return {"state": "FILE", "sha256": self.sha256}


@dataclass(frozen=True)
class OwnerChange:
    owner: str
    impact: Impact


@dataclass(frozen=True)
class Operation:
    owner: str
    action: Action
    path: str
    before: FileState
    after: FileState


@dataclass(frozen=True)
class PackagePlan:
    package_id: str
    staged_path: str
    final_path: str
    tree_sha256: str


@dataclass(frozen=True)
class RedoPlan:
    contract_version: str
    run_id: str
    start_owner: str
    owners: tuple[OwnerChange, ...]
    review_path: str
    review_sha256: str
    packet_path: str | None
    reviewer_path: str | None
    approval_path: str
    approval_sha256: str | None
    package: PackagePlan
    operations: tuple[Operation, ...]


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble, check, or publish an AI SOW reconciliation closure"
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--manifest")
    parser.add_argument("--run-id")
    parser.add_argument("--mode", required=True, choices=("assemble", "check", "publish"))
    return parser.parse_args()


def require_keys(
    value: object,
    keys: set[str],
    *,
    code: str,
    path: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ReconcileError(code, path, f"object must contain exactly: {sorted(keys)}")
    return value


def require_string(value: object, *, code: str, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReconcileError(code, path, "value must be a non-empty string")
    return value


def parse_state(value: object, path: str) -> FileState:
    if value == {"state": "MISSING"}:
        return FileState("MISSING")
    item = require_keys(
        value,
        {"state", "sha256"},
        code="MANIFEST_STATE_INVALID",
        path=path,
    )
    digest = item.get("sha256")
    if item.get("state") != "FILE" or not isinstance(digest, str) or not HASH_PATTERN.fullmatch(digest):
        raise ReconcileError(
            "MANIFEST_STATE_INVALID",
            path,
            "FILE state requires one lowercase SHA-256",
        )
    return FileState("FILE", digest)


def owner_suffix(start_owner: str) -> tuple[OwnerSpec, ...]:
    names = [spec.name for spec in OWNER_SPECS]
    if start_owner not in names:
        raise ReconcileError(
            "RECONCILIATION_OWNER_INVALID",
            ".ai-sow/work/reconcile",
            f"unsupported correction Owner: {start_owner}",
        )
    return OWNER_SPECS[names.index(start_owner) :]


def stage_path(run_id: str, logical_path: str) -> str:
    if not logical_path.startswith(".ai-sow/") or logical_path.startswith(".ai-sow/.stage-"):
        raise ReconcileError(
            "MANIFEST_PATH_INVALID",
            logical_path,
            "published paths must be non-staging .ai-sow project paths",
        )
    return f".ai-sow/.stage-{run_id}/{logical_path.removeprefix('.ai-sow/')}"


def load_plan(files: ProjectFiles, manifest_path: str) -> RedoPlan:
    try:
        payload = files.read_bytes(manifest_path)
        value = json.loads(payload.decode("utf-8"))
    except (ProjectIOError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconcileError(
            "REDO_MANIFEST_INVALID",
            manifest_path,
            "redo manifest is unavailable or invalid JSON",
        ) from error
    if payload != canonical_json_bytes(value):
        raise ReconcileError(
            "REDO_MANIFEST_NOT_CANONICAL",
            manifest_path,
            "redo manifest must use canonical UTF-8 JSON bytes",
        )
    if not isinstance(value, dict):
        raise ReconcileError(
            "REDO_MANIFEST_INVALID", manifest_path, "redo manifest must be an object"
        )
    contract_version = value.get("contractVersion")
    common_keys = {
            "algorithm",
            "contractVersion",
            "runId",
            "startOwner",
            "owners",
            "review",
            "approval",
            "writerMode",
            "package",
            "operations",
        }
    expected_keys = (
        common_keys
        if contract_version == CONTRACT_VERSION
        else common_keys | {"packet", "reviewer"}
    )
    manifest = require_keys(
        value,
        expected_keys,
        code="REDO_MANIFEST_INVALID",
        path=manifest_path,
    )
    if manifest["algorithm"] != ALGORITHM or contract_version not in {
        CONTRACT_VERSION,
        PREPARED_CONTRACT_VERSION,
    }:
        raise ReconcileError(
            "REDO_CONTRACT_UNSUPPORTED",
            manifest_path,
            "redo manifest algorithm or contract version is unsupported",
        )
    run_id = require_string(
        manifest["runId"], code="RUN_ID_INVALID", path=manifest_path
    )
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ReconcileError(
            "RUN_ID_INVALID", manifest_path, "runId must be exactly 12 lowercase hexadecimal characters"
        )
    expected_manifest_path = f".ai-sow/work/reconcile/{run_id}/redo.json"
    if manifest_path != expected_manifest_path:
        raise ReconcileError(
            "RUN_ID_PATH_MISMATCH",
            manifest_path,
            f"manifest path must be {expected_manifest_path}",
        )
    if manifest["writerMode"] != "SINGLE_WRITER":
        raise ReconcileError(
            "SINGLE_WRITER_REQUIRED",
            manifest_path,
            "reconciliation publication requires writerMode SINGLE_WRITER",
        )

    start_owner = require_string(
        manifest["startOwner"], code="RECONCILIATION_OWNER_INVALID", path=manifest_path
    )
    suffix = owner_suffix(start_owner)
    raw_owners = manifest["owners"]
    if not isinstance(raw_owners, list):
        raise ReconcileError(
            "OWNER_SUFFIX_INVALID", manifest_path, "owners must be the fixed Owner suffix"
        )
    owners: list[OwnerChange] = []
    for index, item in enumerate(raw_owners):
        owner = require_keys(
            item,
            {"owner", "impact"},
            code="OWNER_SUFFIX_INVALID",
            path=f"{manifest_path}#/owners/{index}",
        )
        if owner["impact"] not in {"CHANGED", "NO_CHANGE"}:
            raise ReconcileError(
                "OWNER_IMPACT_INVALID",
                f"{manifest_path}#/owners/{index}",
                "impact must be CHANGED or NO_CHANGE",
            )
        owners.append(OwnerChange(str(owner["owner"]), owner["impact"]))  # type: ignore[arg-type]
    if [owner.owner for owner in owners] != [spec.name for spec in suffix]:
        raise ReconcileError(
            "OWNER_SUFFIX_INVALID",
            manifest_path,
            "owners must be the complete fixed suffix from startOwner through generate-task",
        )

    review = require_keys(
        manifest["review"],
        {"path", "sha256"},
        code="REVIEW_BINDING_INVALID",
        path=manifest_path,
    )
    review_path = require_string(
        review["path"], code="REVIEW_BINDING_INVALID", path=manifest_path
    )
    review_sha256 = require_string(
        review["sha256"], code="REVIEW_BINDING_INVALID", path=manifest_path
    )
    if review_path != f".ai-sow/work/reconcile/{run_id}/review.md" or not HASH_PATTERN.fullmatch(
        review_sha256
    ):
        raise ReconcileError(
            "REVIEW_BINDING_INVALID",
            review_path,
            "holistic review path or SHA-256 is invalid",
        )

    approval_keys = {"path", "sha256"} if contract_version == CONTRACT_VERSION else {"path"}
    approval = require_keys(
        manifest["approval"], approval_keys, code="APPROVAL_BINDING_INVALID", path=manifest_path
    )
    approval_path = require_string(
        approval["path"], code="APPROVAL_BINDING_INVALID", path=manifest_path
    )
    approval_sha256 = (
        require_string(approval["sha256"], code="APPROVAL_BINDING_INVALID", path=manifest_path)
        if contract_version == CONTRACT_VERSION
        else None
    )
    if approval_path != f".ai-sow/work/reconcile/{run_id}/approval.json" or (
        approval_sha256 is not None and not HASH_PATTERN.fullmatch(approval_sha256)
    ):
        raise ReconcileError(
            "APPROVAL_BINDING_INVALID",
            approval_path,
            "approval path or SHA-256 is invalid",
        )

    packet_path: str | None = None
    reviewer_path: str | None = None
    if contract_version == PREPARED_CONTRACT_VERSION:
        packet = require_keys(
            manifest["packet"], {"path"}, code="PACKET_BINDING_INVALID", path=manifest_path
        )
        reviewer = require_keys(
            manifest["reviewer"], {"path"}, code="REVIEWER_BINDING_INVALID", path=manifest_path
        )
        packet_path = require_string(
            packet["path"], code="PACKET_BINDING_INVALID", path=manifest_path
        )
        reviewer_path = require_string(
            reviewer["path"], code="REVIEWER_BINDING_INVALID", path=manifest_path
        )
        if packet_path != f".ai-sow/work/reconcile/{run_id}/review-packet.json":
            raise ReconcileError(
                "PACKET_BINDING_INVALID", packet_path, "review packet path is invalid"
            )
        if reviewer_path != f".ai-sow/work/reconcile/{run_id}/reviewer.json":
            raise ReconcileError(
                "REVIEWER_BINDING_INVALID", reviewer_path, "Reviewer sidecar path is invalid"
            )

    package_value = require_keys(
        manifest["package"],
        {"packageId", "stagedPath", "finalPath", "treeSha256"},
        code="PACKAGE_PLAN_INVALID",
        path=manifest_path,
    )
    package_id = require_string(
        package_value["packageId"], code="PACKAGE_PLAN_INVALID", path=manifest_path
    )
    staged_package_path = require_string(
        package_value["stagedPath"], code="PACKAGE_PLAN_INVALID", path=manifest_path
    )
    final_package_path = require_string(
        package_value["finalPath"], code="PACKAGE_PLAN_INVALID", path=manifest_path
    )
    tree_digest = require_string(
        package_value["treeSha256"], code="PACKAGE_PLAN_INVALID", path=manifest_path
    )
    if (
        not PACKAGE_ID_PATTERN.fullmatch(package_id)
        or staged_package_path != f".ai-sow/.stage-{run_id}/outputs/{package_id}"
        or final_package_path != f".ai-sow/outputs/{package_id}"
        or not HASH_PATTERN.fullmatch(tree_digest)
    ):
        raise ReconcileError(
            "PACKAGE_PLAN_INVALID",
            staged_package_path,
            "package identity, paths, or tree SHA-256 is invalid",
        )
    package = PackagePlan(package_id, staged_package_path, final_package_path, tree_digest)

    raw_operations = manifest["operations"]
    if not isinstance(raw_operations, list):
        raise ReconcileError(
            "MANIFEST_OPERATION_SET_INVALID", manifest_path, "operations must be an ordered list"
        )
    operations: list[Operation] = []
    for index, raw in enumerate(raw_operations):
        item = require_keys(
            raw,
            {"owner", "action", "path", "before", "after"},
            code="MANIFEST_OPERATION_INVALID",
            path=f"{manifest_path}#/operations/{index}",
        )
        owner_name = require_string(
            item["owner"], code="MANIFEST_OPERATION_INVALID", path=manifest_path
        )
        action = item["action"]
        if action not in {"WRITE", "DELETE"}:
            raise ReconcileError(
                "MANIFEST_OPERATION_INVALID",
                manifest_path,
                "operation action must be WRITE or DELETE",
            )
        logical_path = require_string(
            item["path"], code="MANIFEST_OPERATION_INVALID", path=manifest_path
        )
        stage_path(run_id, logical_path)
        before = parse_state(item["before"], f"{manifest_path}#/operations/{index}/before")
        after = parse_state(item["after"], f"{manifest_path}#/operations/{index}/after")
        if action == "WRITE" and after.state != "FILE":
            raise ReconcileError(
                "MANIFEST_OPERATION_INVALID",
                logical_path,
                "WRITE requires a FILE after state",
            )
        if action == "DELETE" and after.state != "MISSING":
            raise ReconcileError(
                "MANIFEST_OPERATION_INVALID",
                logical_path,
                "DELETE requires a MISSING after state",
            )
        operations.append(Operation(owner_name, action, logical_path, before, after))  # type: ignore[arg-type]

    expected_operations: list[tuple[str, str]] = []
    actual_pairs = [(item.owner, item.path) for item in operations]
    for spec in suffix:
        present_optional = [
            path
            for path in spec.optional_delete_paths
            if (spec.name, path) in actual_pairs
        ]
        expected_operations.extend(
            (spec.name, path) for path in (*present_optional, *spec.ordered_paths)
        )
    if actual_pairs != expected_operations:
        raise ReconcileError(
            "MANIFEST_OPERATION_SET_INVALID",
            manifest_path,
            "operations must contain only the fixed scoped Owner paths in publication order",
        )
    if not operations or operations[-1].path != OWNER_BY_NAME["generate-task"].receipt:
        raise ReconcileError(
            "TASK_RECEIPT_NOT_LAST",
            manifest_path,
            "generate-task receipt must be the final Owner publication",
        )
    optional_delete_paths = {
        (spec.name, path)
        for spec in suffix
        for path in spec.optional_delete_paths
    }
    for operation in operations:
        if (operation.owner, operation.path) in optional_delete_paths:
            if (
                operation.action != "DELETE"
                or operation.before.state != "FILE"
                or operation.after.state != "MISSING"
            ):
                raise ReconcileError(
                    "OWNER_INPUT_PUBLICATION_INVALID",
                    operation.path,
                    "optional Owner input cleanup only supports deleting an existing baseline file",
                )
            continue
        if operation.before.state != "FILE" or operation.after.state != "FILE":
            raise ReconcileError(
                "FINAL_OWNER_PATH_MISSING",
                operation.path,
                "existing reconciliation Owner review/output/receipt paths must remain files",
            )

    plan = RedoPlan(
        str(contract_version),
        run_id,
        start_owner,
        tuple(owners),
        review_path,
        review_sha256,
        packet_path,
        reviewer_path,
        approval_path,
        approval_sha256,
        package,
        tuple(operations),
    )
    validate_owner_impacts(plan)
    return plan


def validate_owner_impacts(plan: RedoPlan) -> None:
    operations = {item.path: item for item in plan.operations}
    for change in plan.owners:
        spec = OWNER_BY_NAME[change.owner]
        output_changes = [
            operations[path].before.sha256 != operations[path].after.sha256
            for path in spec.outputs
        ]
        if change.impact == "NO_CHANGE" and any(output_changes):
            raise ReconcileError(
                "NO_CHANGE_OUTPUT_CHANGED",
                spec.outputs[output_changes.index(True)],
                f"{change.owner} NO_CHANGE must preserve every stable output byte",
            )
        if change.impact == "CHANGED" and not any(output_changes):
            raise ReconcileError(
                "CHANGED_OUTPUT_UNCHANGED",
                spec.outputs[0],
                f"{change.owner} CHANGED must change at least one owned stable output",
            )


def declaration(text: str, label: str) -> list[str]:
    return re.findall(rf"(?m)^{re.escape(label)}\s*:\s*(.+?)\s*$", text)


def split_owner_names(value: str) -> list[str]:
    return [part for part in re.split(r"[,，、;；\s]+", value) if part]


def review_impact_rows(text: str) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) == 6 and cells[0] in OWNER_BY_NAME:
            rows.append((cells[0], cells[1], cells[2], cells[3]))
    return rows


def output_hash_declaration(plan: RedoPlan, spec: OwnerSpec, *, after: bool) -> str:
    operations = operation_by_path(plan)
    entries: list[str] = []
    for name, output_path in zip(spec.output_names, spec.outputs, strict=True):
        state = operations[output_path].after if after else operations[output_path].before
        if state.state != "FILE" or state.sha256 is None:
            raise ReconcileError(
                "HOLISTIC_REVIEW_OUTPUT_HASH_MISMATCH",
                plan.review_path,
                "stable output review bindings require FILE SHA-256 states",
            )
        entries.append(f"{name}={state.sha256}")
    return "; ".join(entries)


def validate_review_and_approval(files: ProjectFiles, plan: RedoPlan) -> bytes:
    try:
        review_payload = files.read_bytes(plan.review_path)
        review_text = review_payload.decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError) as error:
        raise ReconcileError(
            "HOLISTIC_REVIEW_INVALID",
            plan.review_path,
            "holistic review is unavailable or not UTF-8",
        ) from error
    if sha256_bytes(review_payload) != plan.review_sha256:
        raise ReconcileError(
            "HOLISTIC_REVIEW_HASH_MISMATCH",
            plan.review_path,
            "holistic review bytes do not match the approved SHA-256",
        )
    expected_names = [owner.owner for owner in plan.owners]
    expected_impact_suffix = [*expected_names, "generate-sow"]
    if declaration(review_text, "Run ID") != [plan.run_id]:
        raise ReconcileError(
            "HOLISTIC_REVIEW_RUN_ID_MISMATCH",
            plan.review_path,
            "holistic review must declare the exact run ID once",
        )
    if declaration(review_text, "Correction Owner") != [plan.start_owner]:
        raise ReconcileError(
            "HOLISTIC_REVIEW_OWNER_MISMATCH",
            plan.review_path,
            "holistic review correction Owner does not match the manifest",
        )
    suffix_values = declaration(review_text, "Impact Suffix")
    if (
        len(suffix_values) != 1
        or split_owner_names(suffix_values[0]) != expected_impact_suffix
    ):
        raise ReconcileError(
            "HOLISTIC_REVIEW_SUFFIX_MISMATCH",
            plan.review_path,
            "holistic review must declare the complete fixed suffix through generate-sow",
        )
    impact_rows = review_impact_rows(review_text)
    expected_impacts = [(owner.owner, owner.impact) for owner in plan.owners]
    if [(owner, impact) for owner, impact, _, _ in impact_rows] != expected_impacts:
        raise ReconcileError(
            "HOLISTIC_REVIEW_IMPACT_MISMATCH",
            plan.review_path,
            "holistic review Owner impact rows must match the manifest exactly",
        )
    expected_hashes = [
        (
            owner.owner,
            output_hash_declaration(plan, OWNER_BY_NAME[owner.owner], after=False),
            output_hash_declaration(plan, OWNER_BY_NAME[owner.owner], after=True),
        )
        for owner in plan.owners
    ]
    actual_hashes = [
        (owner, before_hashes, after_hashes)
        for owner, _, before_hashes, after_hashes in impact_rows
    ]
    if actual_hashes != expected_hashes:
        raise ReconcileError(
            "HOLISTIC_REVIEW_OUTPUT_HASH_MISMATCH",
            plan.review_path,
            "holistic review output hashes must exactly match canonical named before/after output hashes",
        )
    reviewer_declarations = declaration(review_text, "Reviewer")
    if plan.contract_version == PREPARED_CONTRACT_VERSION:
        if reviewer_declarations:
            raise ReconcileError(
                "HOLISTIC_REVIEW_PREMATURE_REVIEWER",
                plan.review_path,
                "prepared holistic review must bind Reviewer PASS in reviewer.json, not review.md",
            )
        return review_payload
    if reviewer_declarations != ["PASS"]:
        raise ReconcileError(
            "HOLISTIC_REVIEW_NOT_PASSED",
            plan.review_path,
            "holistic review requires exactly one Reviewer: PASS",
        )
    try:
        approval_payload = files.read_bytes(plan.approval_path)
        approval_value = json.loads(approval_payload.decode("utf-8"))
    except (ProjectIOError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconcileError(
            "APPROVAL_INVALID",
            plan.approval_path,
            "approval is unavailable or invalid JSON",
        ) from error
    if approval_payload != canonical_json_bytes(approval_value):
        raise ReconcileError(
            "APPROVAL_NOT_CANONICAL",
            plan.approval_path,
            "approval must use canonical UTF-8 JSON bytes",
        )
    if plan.approval_sha256 is None or sha256_bytes(approval_payload) != plan.approval_sha256:
        raise ReconcileError(
            "APPROVAL_HASH_MISMATCH",
            plan.approval_path,
            "approval bytes do not match the manifest SHA-256",
        )
    expected_approval = {
        "algorithm": APPROVAL_ALGORITHM,
        "decision": "APPROVED",
        "reviewSha256": plan.review_sha256,
        "runId": plan.run_id,
    }
    if approval_value != expected_approval:
        raise ReconcileError(
            "APPROVAL_BINDING_MISMATCH",
            plan.approval_path,
            "approval must bind the exact run ID and holistic review SHA-256",
        )
    return review_payload


def actual_state(files: ProjectFiles, path: str) -> FileState:
    try:
        return FileState("FILE", sha256_bytes(files.read_bytes(path)))
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return FileState("MISSING")
        raise


def state_name(state: FileState) -> str:
    return state.sha256 if state.state == "FILE" else "MISSING"


def read_staged_operation(
    files: ProjectFiles,
    staging_view: ProjectView,
    plan: RedoPlan,
    operation: Operation,
) -> bytes:
    staged = stage_path(plan.run_id, operation.path)
    if operation.action == "DELETE":
        if not staging_view.is_tombstoned(operation.path):
            raise ReconcileError(
                "DELETE_TOMBSTONE_REQUIRED",
                operation.path,
                "DELETE requires a valid staging-view tombstone marker",
            )
        try:
            staging_view.resolve(operation.path)
        except ProjectIOError as error:
            if error.code == "PROJECT_PATH_MISSING":
                return b""
            raise
        raise ReconcileError(
            "DELETE_LOGICAL_VIEW_PRESENT",
            operation.path,
            "DELETE path must be MISSING in the staging logical view",
        )
    try:
        payload = files.read_bytes(staged)
    except ProjectIOError as error:
        raise ReconcileError(
            "STAGED_OUTPUT_MISSING",
            staged,
            "WRITE operation staged bytes are unavailable",
        ) from error
    if sha256_bytes(payload) != operation.after.sha256:
        raise ReconcileError(
            "STAGED_OUTPUT_HASH_MISMATCH",
            staged,
            "staged bytes do not match the operation after SHA-256",
        )
    return payload


def validate_staged_operations(files: ProjectFiles, plan: RedoPlan) -> dict[str, bytes]:
    staging_view = ProjectFiles.open_view(
        files.root,
        f".ai-sow/.stage-{plan.run_id}",
    )
    payloads: dict[str, bytes] = {}
    for operation in plan.operations:
        payloads[operation.path] = read_staged_operation(
            files,
            staging_view,
            plan,
            operation,
        )
    return payloads


def validate_owner_review_bindings(
    plan: RedoPlan,
    payloads: dict[str, bytes],
) -> None:
    for change in plan.owners:
        spec = OWNER_BY_NAME[change.owner]
        try:
            text = payloads[spec.review].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ReconcileError(
                "OWNER_REVIEW_INVALID",
                spec.review,
                "staged Owner review is not UTF-8",
            ) from error
        if declaration(text, "Reconciliation Run ID") != [plan.run_id]:
            raise ReconcileError(
                "OWNER_REVIEW_RUN_ID_MISMATCH",
                spec.review,
                "Owner review must bind the exact reconciliation run ID once",
            )
        if declaration(text, "Reconciliation Review SHA-256") != [plan.review_sha256]:
            raise ReconcileError(
                "OWNER_REVIEW_HASH_MISMATCH",
                spec.review,
                "Owner review must bind the approved holistic review SHA-256 once",
            )


def operation_by_path(plan: RedoPlan) -> dict[str, Operation]:
    return {operation.path: operation for operation in plan.operations}


def view_bytes(
    files: ProjectFiles,
    plan: RedoPlan,
    payloads: dict[str, bytes],
    path: str,
    *,
    receipt_input: bool,
) -> bytes:
    if path.startswith(".ai-sow/.stage-"):
        raise ReconcileError(
            "STAGED_ONLY_RECEIPT_INPUT",
            path,
            "final receipt cannot bind a staging path",
        )
    operation = operation_by_path(plan).get(path)
    if operation is not None:
        if operation.after.state == "MISSING":
            raise ReconcileError(
                "RECEIPT_FILE_MISSING",
                path,
                "final receipt binds a deleted file",
            )
        return payloads[path]
    try:
        return files.read_bytes(path)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING":
            raise
        staged: str | None = None
        if path.startswith(".ai-sow/"):
            staged = stage_path(plan.run_id, path)
            try:
                files.resolve(staged)
            except ProjectIOError:
                staged = None
        if receipt_input and staged is not None:
            raise ReconcileError(
                "STAGED_ONLY_RECEIPT_INPUT",
                path,
                "receipt FILE input exists only in staging and will not be published",
            ) from error
        raise ReconcileError(
            "RECEIPT_FILE_MISSING",
            path,
            "final receipt FILE closure is missing a project file",
        ) from error


def validate_file_entry(
    entry: object,
    *,
    path: str,
    allowed_keys: set[str],
) -> dict[str, object]:
    value = require_keys(entry, allowed_keys, code="FINAL_RECEIPT_INVALID", path=path)
    if not isinstance(value.get("name"), str) or not isinstance(value.get("path"), str):
        raise ReconcileError(
            "FINAL_RECEIPT_INVALID", path, "receipt file entry name and path must be strings"
        )
    digest = value.get("sha256")
    if not isinstance(digest, str) or not HASH_PATTERN.fullmatch(digest):
        raise ReconcileError(
            "FINAL_RECEIPT_INVALID", path, "receipt file entry SHA-256 is invalid"
        )
    return value


def validate_receipt(
    files: ProjectFiles,
    plan: RedoPlan,
    payloads: dict[str, bytes],
    spec: OwnerSpec,
    *,
    scoped: bool,
) -> None:
    report_payload = view_bytes(
        files, plan, payloads, spec.receipt, receipt_input=False
    )
    try:
        report = json.loads(report_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconcileError(
            "FINAL_RECEIPT_INVALID", spec.receipt, "final validation report is invalid JSON"
        ) from error
    if report_payload != canonical_json_bytes(report):
        raise ReconcileError(
            "FINAL_RECEIPT_INVALID",
            spec.receipt,
            "final validation report must use canonical UTF-8 JSON bytes",
        )
    if (
        not isinstance(report, dict)
        or set(report) != {"owner", "passed", "diagnostics", "compilationReceipt"}
        or report.get("owner") != spec.name
        or report.get("passed") is not True
        or report.get("diagnostics") != []
        or not isinstance(report.get("compilationReceipt"), dict)
    ):
        raise ReconcileError(
            "FINAL_RECEIPT_INVALID",
            spec.receipt,
            "final validation report is not a successful report for the expected Owner",
        )
    receipt = report["compilationReceipt"]
    if set(receipt) != {
        "algorithm",
        "subject",
        "validatorContractVersion",
        "contractIds",
        "inputs",
        "reviews",
        "outputs",
    }:
        raise ReconcileError(
            "FINAL_RECEIPT_INVALID", spec.receipt, "final compilation receipt shape is invalid"
        )
    if (
        receipt["algorithm"] != "ai-sow-owner-v1"
        or receipt["subject"] != spec.name
        or receipt["validatorContractVersion"] != "0.3"
        or not isinstance(receipt["contractIds"], list)
        or not receipt["contractIds"]
        or not all(isinstance(contract_id, str) and contract_id for contract_id in receipt["contractIds"])
    ):
        raise ReconcileError(
            "FINAL_RECEIPT_INVALID", spec.receipt, "final receipt identity is unsupported"
        )
    inputs = receipt["inputs"]
    reviews = receipt["reviews"]
    outputs = receipt["outputs"]
    if not isinstance(inputs, list) or not isinstance(reviews, list) or not isinstance(outputs, list):
        raise ReconcileError(
            "FINAL_RECEIPT_INVALID", spec.receipt, "receipt artifact collections must be lists"
        )
    for index, raw in enumerate(inputs):
        if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str):
            raise ReconcileError(
                "FINAL_RECEIPT_INVALID",
                spec.receipt,
                "receipt input entry is invalid",
            )
        kind = raw["kind"]
        if kind not in {"FILE", "CANONICAL_JSON", "QUESTIONNAIRE_PRESENCE"}:
            raise ReconcileError(
                "FINAL_RECEIPT_INVALID",
                spec.receipt,
                f"receipt input {index} kind is unsupported",
            )
        locator = "path" if kind == "FILE" else "identity"
        expected_keys = {"name", "kind", locator, "sha256"}
        if (
            set(raw) != expected_keys
            or not isinstance(raw.get("name"), str)
            or not isinstance(raw.get(locator), str)
        ):
            raise ReconcileError(
                "FINAL_RECEIPT_INVALID",
                spec.receipt,
                f"receipt input {index} shape is invalid",
            )
        digest = raw.get("sha256")
        if not isinstance(digest, str) or not HASH_PATTERN.fullmatch(digest):
            raise ReconcileError(
                "FINAL_RECEIPT_INVALID",
                spec.receipt,
                f"receipt input {index} SHA-256 is invalid",
            )
        if kind == "FILE":
            input_path = raw["path"]
            if not isinstance(input_path, str):
                raise ReconcileError(
                    "FINAL_RECEIPT_INVALID", spec.receipt, "FILE input path must be a string"
                )
            current = sha256_bytes(
                view_bytes(files, plan, payloads, input_path, receipt_input=True)
            )
            if current != digest:
                raise ReconcileError(
                    "FINAL_RECEIPT_HASH_MISMATCH",
                    input_path,
                    "receipt FILE input hash does not match the final view",
                )

    review_entries = [
        validate_file_entry(
            item,
            path=spec.receipt,
            allowed_keys={"name", "path", "sha256"},
        )
        for item in reviews
    ]
    output_entries = [
        validate_file_entry(
            item,
            path=spec.receipt,
            allowed_keys={"name", "path", "sha256"},
        )
        for item in outputs
    ]
    if [
        (entry["name"], entry["path"])
        for entry in review_entries
    ] != [("approvedReview", spec.review)]:
        raise ReconcileError(
            "FINAL_RECEIPT_INVALID", spec.receipt, "receipt review path is not Owner-local"
        )
    if [
        (entry["name"], entry["path"])
        for entry in output_entries
    ] != list(zip(spec.output_names, spec.outputs, strict=True)):
        raise ReconcileError(
            "FINAL_RECEIPT_INVALID", spec.receipt, "receipt output paths are not Owner-local"
        )
    for entry in [*review_entries, *output_entries]:
        entry_path = str(entry["path"])
        current = sha256_bytes(
            view_bytes(files, plan, payloads, entry_path, receipt_input=False)
        )
        if current != entry["sha256"]:
            raise ReconcileError(
                "FINAL_RECEIPT_HASH_MISMATCH",
                entry_path,
                "receipt review/output hash does not match the final view",
            )
    if scoped:
        expected_review_hash = operation_by_path(plan)[spec.review].after.sha256
        if review_entries[0]["sha256"] != expected_review_hash:
            raise ReconcileError(
                "OWNER_REVIEW_RECEIPT_MISMATCH",
                spec.receipt,
                "scoped receipt does not bind the staged Owner review",
            )


def validate_receipt_closure(
    files: ProjectFiles,
    plan: RedoPlan,
    payloads: dict[str, bytes],
) -> None:
    scoped = {owner.owner for owner in plan.owners}
    for spec in OWNER_SPECS:
        validate_receipt(files, plan, payloads, spec, scoped=spec.name in scoped)


def is_unsafe(snapshot: os.stat_result) -> bool:
    attributes = getattr(snapshot, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(snapshot.st_mode) or bool(attributes & reparse_flag)


def package_entries(root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        snapshot = path.lstat()
        if is_unsafe(snapshot):
            raise ReconcileError(
                "PACKAGE_PATH_UNSAFE",
                path.relative_to(root).as_posix(),
                "package tree contains a symlink or reparse point",
            )
        if stat.S_ISDIR(snapshot.st_mode):
            continue
        if not stat.S_ISREG(snapshot.st_mode):
            raise ReconcileError(
                "PACKAGE_PATH_UNSAFE",
                path.relative_to(root).as_posix(),
                "package tree contains a non-regular file",
            )
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_bytes(path.read_bytes()),
            }
        )
    return entries


def package_tree_sha256(root: Path) -> str:
    return sha256_bytes(canonical_json_bytes(package_entries(root)))


def resolve_package(files: ProjectFiles, relative_path: str) -> Path:
    try:
        return files.resolve(relative_path, expect="dir")
    except ProjectIOError as error:
        raise ReconcileError(
            "PACKAGE_INVALID", relative_path, "package directory is unavailable"
        ) from error


def package_file_bytes(root: Path, relative_path: str, manifest_path: str) -> bytes:
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or relative_path.startswith("/")
        or "\\" in relative_path
        or any(part in {"", ".", ".."} for part in relative_path.split("/"))
    ):
        raise ReconcileError(
            "PACKAGE_MANIFEST_INVALID",
            manifest_path,
            "package digest path must be a safe POSIX package-relative path",
        )
    target = root.joinpath(*relative_path.split("/"))
    try:
        snapshot = target.lstat()
    except OSError as error:
        raise ReconcileError(
            "PACKAGE_DIGEST_FILE_MISSING",
            relative_path,
            "package digest entry points to an unavailable file",
        ) from error
    if is_unsafe(snapshot) or not stat.S_ISREG(snapshot.st_mode):
        raise ReconcileError(
            "PACKAGE_DIGEST_FILE_INVALID",
            relative_path,
            "package digest entry must point to a regular package file",
        )
    return target.read_bytes()


def validate_manifest_digest_tree(
    root: Path,
    value: object,
    manifest_path: str,
    pointer: str = "#",
) -> None:
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            relative_path = value.get("path")
            digest = value.get("sha256")
            if (
                not isinstance(relative_path, str)
                or not isinstance(digest, str)
                or not HASH_PATTERN.fullmatch(digest)
            ):
                raise ReconcileError(
                    "PACKAGE_MANIFEST_INVALID",
                    f"{manifest_path}{pointer}",
                    "package digest entry must be exact {path, sha256}",
                )
            if sha256_bytes(package_file_bytes(root, relative_path, manifest_path)) != digest:
                raise ReconcileError(
                    "PACKAGE_DIGEST_MISMATCH",
                    relative_path,
                    "package file bytes do not match their manifest digest",
                )
            return
        for key, child in value.items():
            validate_manifest_digest_tree(
                root,
                child,
                manifest_path,
                f"{pointer}/{key}",
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_manifest_digest_tree(
                root,
                child,
                manifest_path,
                f"{pointer}/{index}",
            )


def validate_package_section(
    package_manifest: dict[str, object],
    section_name: str,
    bindings: tuple[tuple[str, str, str], ...],
    files: ProjectFiles,
    plan: RedoPlan,
    payloads: dict[str, bytes],
    manifest_path: str,
) -> None:
    section = package_manifest.get(section_name)
    expected_names = {name for name, _, _ in bindings}
    if not isinstance(section, dict) or set(section) != expected_names:
        raise ReconcileError(
            "PACKAGE_MANIFEST_INVALID",
            f"{manifest_path}#/{section_name}",
            f"package {section_name} must contain the exact fixed artifact set",
        )
    for name, logical_path, package_path in bindings:
        entry = require_keys(
            section[name],
            {"path", "sha256"},
            code="PACKAGE_MANIFEST_INVALID",
            path=f"{manifest_path}#/{section_name}/{name}",
        )
        digest = entry.get("sha256")
        if entry.get("path") != package_path or not isinstance(digest, str) or not HASH_PATTERN.fullmatch(
            digest
        ):
            raise ReconcileError(
                "PACKAGE_MANIFEST_INVALID",
                f"{manifest_path}#/{section_name}/{name}",
                "package artifact name, path, or SHA-256 is invalid",
            )
        final_digest = sha256_bytes(
            view_bytes(files, plan, payloads, logical_path, receipt_input=False)
        )
        if digest != final_digest:
            raise ReconcileError(
                "PACKAGE_FINAL_VIEW_HASH_MISMATCH",
                logical_path,
                f"package {section_name} digest does not match the final Owner artifact view",
            )


def fingerprint_entry(name: str, path: str, payload: bytes) -> dict[str, str]:
    return {"name": name, "path": path, "sha256": sha256_bytes(payload)}


def final_json_object(
    files: ProjectFiles,
    plan: RedoPlan,
    payloads: dict[str, bytes],
    logical_path: str,
    *,
    code: str,
) -> tuple[bytes, dict[str, object]]:
    try:
        payload = view_bytes(
            files,
            plan,
            payloads,
            logical_path,
            receipt_input=False,
        )
        value = json.loads(payload.decode("utf-8"))
    except (ReconcileError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconcileError(
            code,
            logical_path,
            "final-view JSON required by the package projection is unavailable or invalid",
        ) from error
    if not isinstance(value, dict):
        raise ReconcileError(
            code,
            logical_path,
            "final-view package projection source must be a JSON object",
        )
    return payload, value


def projection_list(
    value: object,
    fields: tuple[tuple[str, str], ...],
    *,
    path: str,
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ReconcileError(
            "PACKAGE_ASIS_PROJECTION_INVALID",
            path,
            "As-Is package projection source must be an array",
        )
    projected: list[dict[str, str]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ReconcileError(
                "PACKAGE_ASIS_PROJECTION_INVALID",
                f"{path}/{index}",
                "As-Is package projection entry must be an object",
            )
        entry: dict[str, str] = {}
        for source_name, target_name in fields:
            field = raw.get(source_name)
            if not isinstance(field, str) or not field:
                raise ReconcileError(
                    "PACKAGE_ASIS_PROJECTION_INVALID",
                    f"{path}/{index}/{source_name}",
                    "As-Is package projection field must be a non-empty string",
                )
            entry[target_name] = field
        projected.append(entry)
    return projected


def validate_package_projection(
    package_manifest: dict[str, object],
    files: ProjectFiles,
    plan: RedoPlan,
    payloads: dict[str, bytes],
    manifest_path: str,
) -> None:
    project_payload, project = final_json_object(
        files,
        plan,
        payloads,
        PROJECT_PATH,
        code="PACKAGE_PROJECT_INVALID",
    )
    identity_fields = ("projectId", "pluginVersion", "sowStandardVersion")
    project_identity: dict[str, str] = {}
    for field_name in identity_fields:
        value = project.get(field_name)
        if not isinstance(value, str) or not value:
            raise ReconcileError(
                "PACKAGE_PROJECT_INVALID",
                f"{PROJECT_PATH}#/{field_name}",
                "project package identity field must be a non-empty string",
            )
        project_identity[field_name] = value
        if package_manifest.get(field_name) != value:
            raise ReconcileError(
                "PACKAGE_METADATA_MISMATCH",
                manifest_path,
                "package metadata does not match the final project identity",
            )

    _, asis = final_json_object(
        files,
        plan,
        payloads,
        ASIS_PATH,
        code="PACKAGE_ASIS_PROJECTION_INVALID",
    )
    scope = asis.get("analysisScope")
    if not isinstance(scope, dict) or not isinstance(scope.get("mode"), str):
        raise ReconcileError(
            "PACKAGE_ASIS_PROJECTION_INVALID",
            f"{ASIS_PATH}#/analysisScope",
            "As-Is analysisScope package projection is invalid",
        )
    expected_repositories = projection_list(
        scope.get("repositorySnapshots"),
        (("repoId", "repoId"), ("revision", "setupRevision")),
        path=f"{ASIS_PATH}#/analysisScope/repositorySnapshots",
    )
    expected_prior_sows = projection_list(
        scope.get("priorSowSnapshots"),
        (("priorSowId", "priorSowId"), ("sha256", "sha256")),
        path=f"{ASIS_PATH}#/analysisScope/priorSowSnapshots",
    )
    if (
        package_manifest.get("projectMode") != scope["mode"]
        or package_manifest.get("repositories") != expected_repositories
        or package_manifest.get("priorSows") != expected_prior_sows
    ):
        raise ReconcileError(
            "PACKAGE_ASIS_PROJECTION_MISMATCH",
            manifest_path,
            "package mode and snapshot projections do not match final As-Is bytes",
        )

    try:
        template_payload = view_bytes(
            files,
            plan,
            payloads,
            TEMPLATE_PATH,
            receipt_input=False,
        )
    except ReconcileError as error:
        raise ReconcileError(
            "PACKAGE_TEMPLATE_MISSING",
            TEMPLATE_PATH,
            "formal project template required by the package fingerprint is unavailable",
        ) from error
    template = package_manifest["template"]
    assert isinstance(template, dict)
    if template.get("sha256") != sha256_bytes(template_payload):
        raise ReconcileError(
            "PACKAGE_TEMPLATE_HASH_MISMATCH",
            TEMPLATE_PATH,
            "package template digest does not match the formal project template bytes",
        )

    def entries(bindings: tuple[tuple[str, str, str], ...]) -> list[dict[str, str]]:
        return [
            fingerprint_entry(
                name,
                package_path,
                view_bytes(
                    files,
                    plan,
                    payloads,
                    logical_path,
                    receipt_input=False,
                ),
            )
            for name, logical_path, package_path in bindings
        ]

    fingerprint_payload = {
        "algorithm": PACKAGE_ALGORITHM,
        "generatorContract": GENERATOR_CONTRACT,
        "projectIdentity": project_identity,
        "project": fingerprint_entry("project", PROJECT_PATH, project_payload),
        "inputs": entries(PACKAGE_INPUT_BINDINGS),
        "reviews": entries(PACKAGE_REVIEW_BINDINGS),
        "validationReceipts": entries(PACKAGE_RECEIPT_BINDINGS),
        "template": fingerprint_entry(
            "template",
            "sources/templates/sow-template.xlsx",
            template_payload,
        ),
    }
    expected_fingerprint = sha256_bytes(canonical_json_bytes(fingerprint_payload))
    if package_manifest.get("generationFingerprint") != expected_fingerprint:
        raise ReconcileError(
            "PACKAGE_FINGERPRINT_MISMATCH",
            manifest_path,
            "package generation fingerprint does not match the final receipt-only input view",
        )


def validate_package(
    files: ProjectFiles,
    plan: RedoPlan,
    payloads: dict[str, bytes],
) -> Path:
    staged = resolve_package(files, plan.package.staged_path)
    entries = package_entries(staged)
    names = {entry["path"] for entry in entries}
    expected_names = {
        "manifest.json",
        "sow.xlsx",
        "sources/templates/sow-template.xlsx",
        *(package_path for _, _, package_path in PACKAGE_INPUT_BINDINGS),
        *(package_path for _, _, package_path in PACKAGE_REVIEW_BINDINGS),
        *(package_path for _, _, package_path in PACKAGE_RECEIPT_BINDINGS),
    }
    if names != expected_names:
        raise ReconcileError(
            "PACKAGE_INVALID",
            plan.package.staged_path,
            "validated package must contain the exact fixed package member set",
        )
    if package_tree_sha256(staged) != plan.package.tree_sha256:
        raise ReconcileError(
            "PACKAGE_TREE_HASH_MISMATCH",
            plan.package.staged_path,
            "staged package tree does not match the redo manifest",
        )
    manifest_path = f"{plan.package.staged_path}/manifest.json"
    try:
        manifest_payload = (staged / "manifest.json").read_bytes()
        package_manifest = json.loads(manifest_payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconcileError(
            "PACKAGE_INVALID",
            manifest_path,
            "package manifest is invalid",
        ) from error
    if not isinstance(package_manifest, dict) or set(package_manifest) != PACKAGE_MANIFEST_KEYS:
        raise ReconcileError(
            "PACKAGE_MANIFEST_INVALID",
            manifest_path,
            "package manifest must contain the exact supported top-level fields",
        )
    if manifest_payload != canonical_json_bytes(package_manifest):
        raise ReconcileError(
            "PACKAGE_MANIFEST_NOT_CANONICAL",
            manifest_path,
            "package manifest must use canonical UTF-8 JSON bytes",
        )
    fingerprint = package_manifest.get("generationFingerprint")
    expected_package_id = (
        f"sow-sha256-{fingerprint}"
        if isinstance(fingerprint, str) and HASH_PATTERN.fullmatch(fingerprint)
        else None
    )
    if (
        package_manifest.get("fingerprintAlgorithm") != PACKAGE_ALGORITHM
        or package_manifest.get("packageId") != expected_package_id
        or expected_package_id != plan.package.package_id
    ):
        raise ReconcileError(
            "PACKAGE_ID_MISMATCH",
            manifest_path,
            "package ID must be sow-sha256- plus the generation fingerprint and match the redo plan",
        )
    if not isinstance(package_manifest.get("repositories"), list) or not isinstance(
        package_manifest.get("priorSows"), list
    ):
        raise ReconcileError(
            "PACKAGE_MANIFEST_INVALID",
            manifest_path,
            "package repositories and priorSows must be arrays",
        )
    workbook_digest = package_manifest.get("generatedWorkbookSha256")
    if (
        not isinstance(workbook_digest, str)
        or not HASH_PATTERN.fullmatch(workbook_digest)
        or sha256_bytes(package_file_bytes(staged, "sow.xlsx", manifest_path)) != workbook_digest
    ):
        raise ReconcileError(
            "PACKAGE_WORKBOOK_HASH_MISMATCH",
            f"{plan.package.staged_path}/sow.xlsx",
            "generatedWorkbookSha256 does not match sow.xlsx bytes",
        )
    validate_manifest_digest_tree(staged, package_manifest, manifest_path)
    validate_package_section(
        package_manifest,
        "inputs",
        PACKAGE_INPUT_BINDINGS,
        files,
        plan,
        payloads,
        manifest_path,
    )
    validate_package_section(
        package_manifest,
        "reviews",
        PACKAGE_REVIEW_BINDINGS,
        files,
        plan,
        payloads,
        manifest_path,
    )
    validate_package_section(
        package_manifest,
        "validationReceipts",
        PACKAGE_RECEIPT_BINDINGS,
        files,
        plan,
        payloads,
        manifest_path,
    )
    template = require_keys(
        package_manifest["template"],
        {"path", "sha256"},
        code="PACKAGE_MANIFEST_INVALID",
        path=f"{manifest_path}#/template",
    )
    if template.get("path") != "sources/templates/sow-template.xlsx":
        raise ReconcileError(
            "PACKAGE_MANIFEST_INVALID",
            f"{manifest_path}#/template",
            "package template digest path is invalid",
        )
    validate_package_projection(
        package_manifest,
        files,
        plan,
        payloads,
        manifest_path,
    )
    return staged


def classify_publication(files: ProjectFiles, plan: RedoPlan) -> int:
    completed = 0
    seen_before = False
    for operation in plan.operations:
        current = actual_state(files, operation.path)
        if operation.before == operation.after:
            if current != operation.before:
                raise ReconcileError(
                    "THIRD_HASH_CONFLICT",
                    operation.path,
                    "byte-identical operation drifted from its required state",
                    details={
                        "before": state_name(operation.before),
                        "after": state_name(operation.after),
                        "current": state_name(current),
                    },
                )
            continue
        if current == operation.after:
            if seen_before:
                raise ReconcileError(
                    "PUBLISH_SEQUENCE_CONFLICT",
                    operation.path,
                    "after states must form one fixed-order prefix during forward recovery",
                )
            completed += 1
        elif current == operation.before:
            seen_before = True
        else:
            raise ReconcileError(
                "THIRD_HASH_CONFLICT",
                operation.path,
                "formal path is neither in its before nor after state",
                details={
                    "before": state_name(operation.before),
                    "after": state_name(operation.after),
                    "current": state_name(current),
                },
            )
    return completed


def publish_package(files: ProjectFiles, plan: RedoPlan, staged: Path) -> Literal["CREATED", "REUSED"]:
    try:
        final = files.resolve(plan.package.final_path, expect="dir")
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING":
            raise
    else:
        if package_tree_sha256(final) != plan.package.tree_sha256:
            raise ReconcileError(
                "PACKAGE_CONTENT_MISMATCH",
                plan.package.final_path,
                "existing content-addressed package has different bytes",
            )
        return "REUSED"

    outputs = files.ensure_dir(".ai-sow/outputs")
    temporary: Path | None = Path(
        tempfile.mkdtemp(prefix=f".reconcile-{plan.run_id}-", dir=outputs)
    )
    try:
        shutil.copytree(staged, temporary, dirs_exist_ok=True)
        if package_tree_sha256(temporary) != plan.package.tree_sha256:
            raise ReconcileError(
                "PACKAGE_COPY_MISMATCH",
                plan.package.final_path,
                "copied package bytes changed before publication",
            )
        final = outputs / plan.package.package_id
        try:
            os.replace(temporary, final)
        except FileExistsError:
            if package_tree_sha256(final) != plan.package.tree_sha256:
                raise ReconcileError(
                    "PACKAGE_CONTENT_MISMATCH",
                    plan.package.final_path,
                    "concurrently created package has different bytes",
                )
            return "REUSED"
        temporary = None
        return "CREATED"
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)


def apply_operation(
    files: ProjectFiles,
    plan: RedoPlan,
    operation: Operation,
    payloads: dict[str, bytes],
) -> bool:
    current = actual_state(files, operation.path)
    if current == operation.after:
        return False
    if current != operation.before:
        raise ReconcileError(
            "THIRD_HASH_CONFLICT",
            operation.path,
            "formal path changed after publication preflight",
            details={
                "before": state_name(operation.before),
                "after": state_name(operation.after),
                "current": state_name(current),
            },
        )
    if operation.action == "WRITE":
        files.write_atomic(operation.path, payloads[operation.path])
    else:
        files.resolve(operation.path).unlink()
    if actual_state(files, operation.path) != operation.after:
        raise ReconcileError(
            "PUBLISH_VERIFY_FAILED",
            operation.path,
            "formal path did not reach its declared after state",
        )
    return True


def operation_json(operation: Operation) -> dict[str, object]:
    return {
        "owner": operation.owner,
        "action": operation.action,
        "path": operation.path,
        "before": operation.before.as_json(),
        "after": operation.after.as_json(),
    }


def prepared_manifest_value(plan: RedoPlan) -> dict[str, object]:
    if plan.contract_version != PREPARED_CONTRACT_VERSION:
        raise ReconcileError(
            "REDO_CONTRACT_UNSUPPORTED", plan.review_path, "plan is not a prepared closure"
        )
    assert plan.packet_path is not None and plan.reviewer_path is not None
    return {
        "algorithm": ALGORITHM,
        "contractVersion": PREPARED_CONTRACT_VERSION,
        "runId": plan.run_id,
        "startOwner": plan.start_owner,
        "owners": [
            {"owner": owner.owner, "impact": owner.impact} for owner in plan.owners
        ],
        "review": {"path": plan.review_path, "sha256": plan.review_sha256},
        "packet": {"path": plan.packet_path},
        "reviewer": {"path": plan.reviewer_path},
        "approval": {"path": plan.approval_path},
        "writerMode": "SINGLE_WRITER",
        "package": {
            "packageId": plan.package.package_id,
            "stagedPath": plan.package.staged_path,
            "finalPath": plan.package.final_path,
            "treeSha256": plan.package.tree_sha256,
        },
        "operations": [operation_json(operation) for operation in plan.operations],
    }


def staged_artifact_bindings(
    plan: RedoPlan,
    payloads: dict[str, bytes],
) -> list[dict[str, str]]:
    return [
        {
            "owner": operation.owner,
            "path": operation.path,
            "stagedPath": stage_path(plan.run_id, operation.path),
            "sha256": sha256_bytes(payloads[operation.path]),
        }
        for operation in plan.operations
        if operation.action == "WRITE"
    ]


def candidate_bindings(
    files: ProjectFiles,
    plan: RedoPlan,
    payloads: dict[str, bytes],
) -> list[dict[str, str]]:
    bindings: list[dict[str, str]] = []
    for owner in plan.owners:
        if owner.impact != "CHANGED":
            continue
        spec = OWNER_BY_NAME[owner.owner]
        for candidate_path, output_path in zip(
            spec.candidates, spec.outputs, strict=True
        ):
            try:
                payload = files.read_bytes(candidate_path)
            except ProjectIOError as error:
                raise ReconcileError(
                    "RECONCILIATION_CANDIDATE_MISSING",
                    candidate_path,
                    "CHANGED Owner candidate is required before assemble",
                ) from error
            if payload != payloads[output_path]:
                raise ReconcileError(
                    "RECONCILIATION_CANDIDATE_STAGED_MISMATCH",
                    candidate_path,
                    "candidate bytes must exactly equal the staged stable output bytes",
                )
            bindings.append(
                {
                    "owner": owner.owner,
                    "path": candidate_path,
                    "sha256": sha256_bytes(payload),
                }
            )
    return bindings


def receipt_input_bindings(
    plan: RedoPlan,
    payloads: dict[str, bytes],
) -> list[dict[str, str]]:
    bindings: list[dict[str, str]] = []
    for owner in plan.owners:
        spec = OWNER_BY_NAME[owner.owner]
        report = json.loads(payloads[spec.receipt].decode("utf-8"))
        inputs = report["compilationReceipt"]["inputs"]
        for item in inputs:
            locator = "path" if item["kind"] == "FILE" else "identity"
            bindings.append(
                {
                    "owner": owner.owner,
                    "name": item["name"],
                    "kind": item["kind"],
                    locator: item[locator],
                    "sha256": item["sha256"],
                }
            )
    return bindings


def technical_diff_value(plan: RedoPlan) -> dict[str, object]:
    return {
        "algorithm": "ai-sow-reconciliation-diff-v1",
        "runId": plan.run_id,
        "operations": [operation_json(operation) for operation in plan.operations],
    }


def risk_summary_bytes(plan: RedoPlan) -> bytes:
    changed = sum(operation.before != operation.after for operation in plan.operations)
    deleted = sum(operation.action == "DELETE" for operation in plan.operations)
    lines = [
        "# Reconciliation 技术风险摘要",
        "",
        f"Run ID: {plan.run_id}",
        f"Start Owner: {plan.start_owner}",
        f"Owner Count: {len(plan.owners)}",
        f"Operation Count: {len(plan.operations)}",
        f"Changed Operation Count: {changed}",
        f"Delete Operation Count: {deleted}",
        f"Package ID: {plan.package.package_id}",
        f"Package Tree SHA-256: {plan.package.tree_sha256}",
        "Publication Mode: SINGLE_WRITER_FORWARD_ONLY",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _single_staged_package(files: ProjectFiles, run_id: str) -> PackagePlan:
    relative_root = f".ai-sow/.stage-{run_id}/outputs"
    root = files.root
    for part in Path(relative_root).parts:
        root = root / part
        try:
            snapshot = root.lstat()
        except FileNotFoundError as error:
            raise ReconcileError(
                "STAGED_PACKAGE_MISSING", relative_root, "staged package output is unavailable"
            ) from error
        if is_unsafe(snapshot) or not stat.S_ISDIR(snapshot.st_mode):
            raise ReconcileError(
                "STAGED_PACKAGE_INVALID", relative_root, "staged package path is unsafe or not a directory"
            )
    try:
        candidates = sorted(path for path in root.iterdir() if path.is_dir())
    except OSError as error:
        raise ReconcileError(
            "STAGED_PACKAGE_INVALID", relative_root, "staged package output cannot be read"
        ) from error
    if len(candidates) != 1 or not PACKAGE_ID_PATTERN.fullmatch(candidates[0].name):
        raise ReconcileError(
            "STAGED_PACKAGE_INVALID",
            relative_root,
            "staging must contain exactly one content-addressed package",
        )
    package_root = candidates[0]
    if is_unsafe(package_root.lstat()):
        raise ReconcileError(
            "STAGED_PACKAGE_INVALID", relative_root, "staged package cannot be a symlink or reparse point"
        )
    package_id = package_root.name
    return PackagePlan(
        package_id,
        f"{relative_root}/{package_id}",
        f".ai-sow/outputs/{package_id}",
        package_tree_sha256(package_root),
    )


def _prepared_plan(files: ProjectFiles, run_id: str) -> RedoPlan:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ReconcileError(
            "RUN_ID_INVALID", ".ai-sow/work/reconcile", "runId must be 12 lowercase hex"
        )
    work_root = f".ai-sow/work/reconcile/{run_id}"
    review_path = f"{work_root}/review.md"
    try:
        review_payload = files.read_bytes(review_path)
        review_text = review_payload.decode("utf-8")
    except (ProjectIOError, UnicodeDecodeError) as error:
        raise ReconcileError(
            "HOLISTIC_REVIEW_INVALID", review_path, "holistic review is unavailable or not UTF-8"
        ) from error
    owner_values = declaration(review_text, "Correction Owner")
    if len(owner_values) != 1:
        raise ReconcileError(
            "HOLISTIC_REVIEW_OWNER_MISMATCH", review_path, "review must declare one Correction Owner"
        )
    start_owner = owner_values[0]
    suffix = owner_suffix(start_owner)
    rows = review_impact_rows(review_text)
    if [row[0] for row in rows] != [spec.name for spec in suffix]:
        raise ReconcileError(
            "HOLISTIC_REVIEW_IMPACT_MISMATCH", review_path, "review rows must match the fixed Owner suffix"
        )
    owners: list[OwnerChange] = []
    for owner_name, impact, _, _ in rows:
        if impact not in {"CHANGED", "NO_CHANGE"}:
            raise ReconcileError(
                "OWNER_IMPACT_INVALID", review_path, "impact must be CHANGED or NO_CHANGE"
            )
        owners.append(OwnerChange(owner_name, impact))  # type: ignore[arg-type]

    staging_view = ProjectFiles.open_view(files.root, f".ai-sow/.stage-{run_id}")
    operations: list[Operation] = []
    for spec in suffix:
        for optional_path in spec.optional_delete_paths:
            before = actual_state(files, optional_path)
            if before.state == "FILE" and staging_view.is_tombstoned(optional_path):
                operations.append(
                    Operation(spec.name, "DELETE", optional_path, before, FileState("MISSING"))
                )
        for logical_path in spec.ordered_paths:
            before = actual_state(files, logical_path)
            if before.state != "FILE":
                raise ReconcileError(
                    "FINAL_OWNER_PATH_MISSING",
                    logical_path,
                    "reconciliation baseline must contain every scoped Owner path",
                )
            staged = stage_path(run_id, logical_path)
            try:
                after_payload = files.read_bytes(staged)
            except ProjectIOError as error:
                raise ReconcileError(
                    "STAGED_OUTPUT_MISSING", staged, "complete staged Owner closure is required"
                ) from error
            operations.append(
                Operation(
                    spec.name,
                    "WRITE",
                    logical_path,
                    before,
                    FileState("FILE", sha256_bytes(after_payload)),
                )
            )
    return RedoPlan(
        PREPARED_CONTRACT_VERSION,
        run_id,
        start_owner,
        tuple(owners),
        review_path,
        sha256_bytes(review_payload),
        f"{work_root}/review-packet.json",
        f"{work_root}/reviewer.json",
        f"{work_root}/approval.json",
        None,
        _single_staged_package(files, run_id),
        tuple(operations),
    )


def assemble(project_root: Path, run_id: str) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    plan = _prepared_plan(files, run_id)
    assert plan.packet_path is not None and plan.reviewer_path is not None
    for path in (plan.reviewer_path, plan.approval_path):
        if actual_state(files, path).state != "MISSING":
            raise ReconcileError(
                "ASSEMBLE_AUTHORIZATION_EXISTS", path, "cannot rebuild closure after authorization exists"
            )

    validate_owner_impacts(plan)
    validate_review_and_approval(files, plan)
    payloads = validate_staged_operations(files, plan)
    validate_owner_review_bindings(plan, payloads)
    validate_receipt_closure(files, plan, payloads)
    validate_package(files, plan, payloads)

    work_root = f".ai-sow/work/reconcile/{run_id}"
    diff_path = f"{work_root}/diff.json"
    risk_path = f"{work_root}/risk-summary.md"
    redo_path = f"{work_root}/redo.json"
    files.write_atomic(diff_path, canonical_json_bytes(technical_diff_value(plan)))
    files.write_atomic(risk_path, risk_summary_bytes(plan))
    files.write_atomic(redo_path, canonical_json_bytes(prepared_manifest_value(plan)))
    packet = {
        "algorithm": PACKET_ALGORITHM,
        "runId": run_id,
        "startOwner": plan.start_owner,
        "owners": [
            {"owner": owner.owner, "impact": owner.impact} for owner in plan.owners
        ],
        "review": {"path": plan.review_path, "sha256": plan.review_sha256},
        "redo": {"path": redo_path, "sha256": sha256_bytes(files.read_bytes(redo_path))},
        "diff": {"path": diff_path, "sha256": sha256_bytes(files.read_bytes(diff_path))},
        "riskSummary": {"path": risk_path, "sha256": sha256_bytes(files.read_bytes(risk_path))},
        "candidates": candidate_bindings(files, plan, payloads),
        "stagedArtifacts": staged_artifact_bindings(plan, payloads),
        "receiptInputs": receipt_input_bindings(plan, payloads),
        "package": {
            "packageId": plan.package.package_id,
            "stagedPath": plan.package.staged_path,
            "treeSha256": plan.package.tree_sha256,
        },
    }
    packet_payload = canonical_json_bytes(packet)
    files.write_atomic(plan.packet_path, packet_payload)
    return {
        "outcome": "OK",
        "publication": "NOT_STARTED",
        "runId": run_id,
        "manifestPath": redo_path,
        "packetPath": plan.packet_path,
        "packetSha256": sha256_bytes(packet_payload),
        "packagePath": plan.package.staged_path,
        "diagnostics": [],
    }


def _authorization_sidecar(
    files: ProjectFiles,
    *,
    path: str,
    expected: dict[str, str],
    missing_code: str,
    invalid_code: str,
) -> None:
    try:
        payload = files.read_bytes(path)
        value = json.loads(payload.decode("utf-8"))
    except ProjectIOError as error:
        raise ReconcileError(missing_code, path, "authorization sidecar is missing") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconcileError(invalid_code, path, "authorization sidecar is invalid JSON") from error
    if payload != canonical_json_bytes(value) or value != expected:
        raise ReconcileError(
            invalid_code, path, "authorization sidecar must canonically bind the exact packet"
        )


def validate_prepared_packet(
    files: ProjectFiles,
    plan: RedoPlan,
    payloads: dict[str, bytes],
) -> str:
    assert plan.packet_path is not None and plan.reviewer_path is not None
    try:
        packet_payload = files.read_bytes(plan.packet_path)
        packet = json.loads(packet_payload.decode("utf-8"))
    except (ProjectIOError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconcileError(
            "RECONCILIATION_PACKET_INVALID", plan.packet_path, "review packet is unavailable or invalid"
        ) from error
    if packet_payload != canonical_json_bytes(packet):
        raise ReconcileError(
            "RECONCILIATION_PACKET_INVALID", plan.packet_path, "review packet is not canonical"
        )
    work_root = f".ai-sow/work/reconcile/{plan.run_id}"
    redo_path = f"{work_root}/redo.json"
    diff_path = f"{work_root}/diff.json"
    risk_path = f"{work_root}/risk-summary.md"
    expected = {
        "algorithm": PACKET_ALGORITHM,
        "runId": plan.run_id,
        "startOwner": plan.start_owner,
        "owners": [
            {"owner": owner.owner, "impact": owner.impact} for owner in plan.owners
        ],
        "review": {"path": plan.review_path, "sha256": plan.review_sha256},
        "redo": {"path": redo_path, "sha256": sha256_bytes(files.read_bytes(redo_path))},
        "diff": {"path": diff_path, "sha256": sha256_bytes(files.read_bytes(diff_path))},
        "riskSummary": {"path": risk_path, "sha256": sha256_bytes(files.read_bytes(risk_path))},
        "candidates": candidate_bindings(files, plan, payloads),
        "stagedArtifacts": staged_artifact_bindings(plan, payloads),
        "receiptInputs": receipt_input_bindings(plan, payloads),
        "package": {
            "packageId": plan.package.package_id,
            "stagedPath": plan.package.staged_path,
            "treeSha256": plan.package.tree_sha256,
        },
    }
    if packet != expected:
        raise ReconcileError(
            "RECONCILIATION_PACKET_DRIFT", plan.packet_path, "review packet closure has drifted"
        )
    packet_sha256 = sha256_bytes(packet_payload)
    _authorization_sidecar(
        files,
        path=plan.reviewer_path,
        expected={
            "algorithm": REVIEWER_ALGORITHM,
            "decision": "PASS",
            "packetSha256": packet_sha256,
            "runId": plan.run_id,
        },
        missing_code="RECONCILIATION_REVIEWER_MISSING",
        invalid_code="RECONCILIATION_REVIEWER_INVALID",
    )
    _authorization_sidecar(
        files,
        path=plan.approval_path,
        expected={
            "algorithm": APPROVAL_ALGORITHM,
            "decision": "APPROVED",
            "packetSha256": packet_sha256,
            "runId": plan.run_id,
        },
        missing_code="RECONCILIATION_APPROVAL_MISSING",
        invalid_code="RECONCILIATION_APPROVAL_INVALID",
    )
    return packet_sha256


def validate_plan(
    files: ProjectFiles,
    plan: RedoPlan,
) -> tuple[dict[str, bytes], Path, int, str | None]:
    validate_review_and_approval(files, plan)
    payloads = validate_staged_operations(files, plan)
    validate_owner_review_bindings(plan, payloads)
    validate_receipt_closure(files, plan, payloads)
    staged_package = validate_package(files, plan, payloads)
    packet_sha256 = (
        validate_prepared_packet(files, plan, payloads)
        if plan.contract_version == PREPARED_CONTRACT_VERSION
        else None
    )
    completed = classify_publication(files, plan)
    return payloads, staged_package, completed, packet_sha256


def execute(project_root: Path, manifest_path: str, mode: str) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    plan = load_plan(files, manifest_path)
    payloads, staged_package, completed, packet_sha256 = validate_plan(files, plan)
    if mode == "check":
        result: dict[str, object] = {
            "outcome": "OK",
            "publication": "CHECKED",
            "runId": plan.run_id,
            "packagePath": plan.package.final_path,
            "completedOperations": completed,
            "totalOperations": len(plan.operations),
            "diagnostics": [],
        }
        if packet_sha256 is not None:
            result["packetSha256"] = packet_sha256
        return result
    if mode != "publish":
        raise ReconcileError("MODE_INVALID", manifest_path, "mode must be check or publish")

    package_publication = publish_package(files, plan, staged_package)
    initially_completed = completed
    changed_operation_count = sum(
        operation.before != operation.after for operation in plan.operations
    )
    writes = 0
    for operation in plan.operations:
        if apply_operation(files, plan, operation, payloads):
            writes += 1
    if classify_publication(files, plan) != changed_operation_count:
        raise ReconcileError(
            "PUBLISH_INCOMPLETE", manifest_path, "Owner publication did not reach every after state"
        )
    validate_receipt_closure(files, plan, payloads)
    if initially_completed == changed_operation_count:
        publication = "REUSED"
    elif initially_completed:
        publication = "RECOVERED"
    else:
        publication = "PUBLISHED"
    result = {
        "outcome": "OK",
        "publication": publication,
        "packagePublication": package_publication,
        "runId": plan.run_id,
        "packagePath": plan.package.final_path,
        "completedOperations": len(plan.operations),
        "writtenOperations": writes,
        "diagnostics": [],
    }
    if packet_sha256 is not None:
        result["packetSha256"] = packet_sha256
    return result


def main() -> int:
    args = parse_args()
    try:
        if args.mode == "assemble":
            if args.manifest is not None or args.run_id is None:
                raise ReconcileError(
                    "ASSEMBLE_ARGUMENT_INVALID",
                    ".ai-sow/work/reconcile",
                    "assemble requires --run-id and does not accept --manifest",
                )
            result = assemble(args.project_root, args.run_id)
        else:
            if args.manifest is None or args.run_id is not None:
                raise ReconcileError(
                    "PUBLISH_ARGUMENT_INVALID",
                    ".ai-sow/work/reconcile",
                    "check/publish require --manifest and do not accept --run-id",
                )
            result = execute(args.project_root, args.manifest, args.mode)
    except ReconcileError as error:
        result = {
            "outcome": "BLOCKED",
            "publication": "NOT_STARTED",
            "diagnostics": [error.diagnostic()],
        }
    except ProjectIOError as error:
        result = {
            "outcome": "BLOCKED",
            "publication": "NOT_STARTED",
            "diagnostics": [
                {
                    "code": error.code,
                    "message": str(error),
                    "path": error.relative_path,
                }
            ],
        }
    except (OSError, json.JSONDecodeError) as error:
        result = {
            "outcome": "BLOCKED",
            "publication": "NOT_STARTED",
            "diagnostics": [
                {
                    "code": "RECONCILIATION_PUBLISH_BLOCKED",
                    "message": str(error),
                }
            ],
        }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["outcome"] == "OK" else 2


if __name__ == "__main__":
    sys.exit(main())
