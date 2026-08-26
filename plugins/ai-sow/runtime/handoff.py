from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from runtime.project_io import ProjectFiles, ProjectIOError


ALGORITHM = "ai-sow-owner-v1"
VALIDATOR_CONTRACT_VERSION = "0.3"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ArtifactKind = Literal["FILE", "CANONICAL_JSON", "QUESTIONNAIRE_PRESENCE"]


@dataclass(frozen=True)
class Artifact:
    name: str
    kind: ArtifactKind
    locator: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.name or self.kind not in {
            "FILE",
            "CANONICAL_JSON",
            "QUESTIONNAIRE_PRESENCE",
        }:
            raise ValueError("artifact name and kind must be supported")
        if not self.locator or not SHA256.fullmatch(self.sha256):
            raise ValueError("artifact locator and SHA-256 must be valid")


@dataclass(frozen=True)
class OwnerContract:
    subject: str
    contract_ids: tuple[str, ...]
    validation_path: str
    reviews: tuple[tuple[str, str], ...]
    outputs: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.subject or not self.contract_ids or not self.validation_path:
            raise ValueError("owner contract identity must be complete")
        for entries in (self.reviews, self.outputs):
            names = [name for name, _ in entries]
            paths = [path for _, path in entries]
            if not entries or len(names) != len(set(names)) or len(paths) != len(set(paths)):
                raise ValueError("owner contract names and paths must be unique")


@dataclass(frozen=True)
class MatchResult:
    ok: bool
    diagnostics: tuple[dict[str, object], ...]
    receipt: dict[str, object] | None


def reconciliation_staging_failure(
    mode: str,
    staging_root: str | None,
) -> dict[str, object] | None:
    """Return the shared CLI failure when reconciliation writes lack staging."""

    if mode not in {"publish", "rebind"} or staging_root is not None:
        return None
    return {
        "outcome": "BLOCKED",
        "summary": "Reconciliation 写入缺少 staging",
        "diagnostics": [
            {
                "code": "RECONCILIATION_STAGING_REQUIRED",
                "message": (
                    f"`--mode {mode}` 仅供 reconciliation 使用，"
                    "必须提供 `--staging-root`"
                ),
            }
        ],
        "outputs": [],
    }


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _diagnostic(
    code: str,
    contract: OwnerContract,
    path: str,
    message: str,
) -> MatchResult:
    return MatchResult(
        False,
        (
            {
                "code": code,
                "message": message,
                "upstreamOwner": contract.subject,
                "path": path,
            },
        ),
        None,
    )


def _input_entry(artifact: Artifact) -> dict[str, object]:
    locator_key = "path" if artifact.kind == "FILE" else "identity"
    return {
        "name": artifact.name,
        "kind": artifact.kind,
        locator_key: artifact.locator,
        "sha256": artifact.sha256,
    }


def _file_entries(
    files: ProjectFiles,
    entries: tuple[tuple[str, str], ...],
) -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "path": path,
            "sha256": sha256_bytes(files.read_bytes(path)),
        }
        for name, path in entries
    ]


def _report(
    contract: OwnerContract,
    inputs: tuple[Artifact, ...],
    reviews: list[dict[str, object]],
    outputs: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "owner": contract.subject,
        "passed": True,
        "diagnostics": [],
        "compilationReceipt": {
            "algorithm": ALGORITHM,
            "subject": contract.subject,
            "validatorContractVersion": VALIDATOR_CONTRACT_VERSION,
            "contractIds": list(contract.contract_ids),
            "inputs": [_input_entry(artifact) for artifact in inputs],
            "reviews": reviews,
            "outputs": outputs,
        },
    }


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _valid_file_entry(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"name", "path", "sha256"}
        and isinstance(value["name"], str)
        and isinstance(value["path"], str)
        and _is_hash(value["sha256"])
    )


def _valid_input_entry(value: object) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        return False
    expected_locator = "path" if value["kind"] == "FILE" else "identity"
    if value["kind"] not in {"FILE", "CANONICAL_JSON", "QUESTIONNAIRE_PRESENCE"}:
        return False
    return (
        set(value) == {"name", "kind", expected_locator, "sha256"}
        and isinstance(value["name"], str)
        and isinstance(value[expected_locator], str)
        and _is_hash(value["sha256"])
    )


def _receipt_from_report(report: object) -> dict[str, object] | None:
    if (
        not isinstance(report, dict)
        or set(report) != {"owner", "passed", "diagnostics", "compilationReceipt"}
        or report.get("passed") is not True
        or report.get("diagnostics") != []
        or not isinstance(report.get("compilationReceipt"), dict)
    ):
        return None
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
        return None
    if not isinstance(receipt["contractIds"], list):
        return None
    if not isinstance(receipt["inputs"], list) or not all(
        _valid_input_entry(entry) for entry in receipt["inputs"]
    ):
        return None
    for key in ("reviews", "outputs"):
        if not isinstance(receipt[key], list) or not all(
            _valid_file_entry(entry) for entry in receipt[key]
        ):
            return None
    return receipt


def _expected_file_shape(entries: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    return list(entries)


def _actual_file_shape(entries: list[object]) -> list[tuple[object, object]]:
    return [(entry.get("name"), entry.get("path")) for entry in entries if isinstance(entry, dict)]


def _verify_input_files(files: ProjectFiles, inputs: tuple[Artifact, ...]) -> None:
    for artifact in inputs:
        if artifact.kind != "FILE":
            continue
        try:
            current = sha256_bytes(files.read_bytes(artifact.locator))
        except ProjectIOError as error:
            raise ProjectIOError(
                "OWNER_INPUT_MISSING",
                artifact.locator,
                f"owner input is unavailable: {artifact.locator}",
            ) from error
        if current != artifact.sha256:
            raise ProjectIOError(
                "OWNER_INPUT_STALE",
                artifact.locator,
                f"owner input hash changed: {artifact.locator}",
            )


def match_owner(
    files: ProjectFiles,
    contract: OwnerContract,
    expected_inputs: tuple[Artifact, ...],
) -> MatchResult:
    try:
        report = files.read_json(contract.validation_path)
    except ProjectIOError as error:
        code = (
            "UPSTREAM_HANDOFF_MISSING"
            if error.code == "PROJECT_PATH_MISSING"
            else "UPSTREAM_HANDOFF_INVALID"
        )
        return _diagnostic(code, contract, contract.validation_path, "upstream validation report is unavailable")

    receipt = _receipt_from_report(report)
    if receipt is None or not isinstance(report, dict) or report.get("owner") != contract.subject:
        return _diagnostic(
            "UPSTREAM_HANDOFF_INVALID",
            contract,
            contract.validation_path,
            "upstream validation report or receipt has an invalid shape",
        )

    if (
        receipt["algorithm"] != ALGORITHM
        or receipt["validatorContractVersion"] != VALIDATOR_CONTRACT_VERSION
        or receipt["contractIds"] != list(contract.contract_ids)
    ):
        return _diagnostic(
            "UPSTREAM_CONTRACT_UNSUPPORTED",
            contract,
            contract.validation_path,
            "upstream receipt contract is unsupported",
        )
    if receipt["subject"] != contract.subject:
        return _diagnostic(
            "UPSTREAM_HANDOFF_INVALID",
            contract,
            contract.validation_path,
            "upstream receipt subject is invalid",
        )

    actual_reviews = receipt["reviews"]
    actual_outputs = receipt["outputs"]
    assert isinstance(actual_reviews, list) and isinstance(actual_outputs, list)
    if _actual_file_shape(actual_reviews) != _expected_file_shape(contract.reviews):
        return _diagnostic(
            "UPSTREAM_HANDOFF_INVALID",
            contract,
            contract.validation_path,
            "upstream receipt review set is invalid",
        )
    if _actual_file_shape(actual_outputs) != _expected_file_shape(contract.outputs):
        return _diagnostic(
            "UPSTREAM_HANDOFF_INVALID",
            contract,
            contract.validation_path,
            "upstream receipt output set is invalid",
        )

    for entry in [*actual_reviews, *actual_outputs]:
        assert isinstance(entry, dict)
        path = str(entry["path"])
        try:
            current_hash = sha256_bytes(files.read_bytes(path))
        except ProjectIOError:
            return _diagnostic(
                "UPSTREAM_HANDOFF_MISSING",
                contract,
                path,
                "upstream receipt file is missing",
            )
        if current_hash != entry["sha256"]:
            return _diagnostic(
                "UPSTREAM_HANDOFF_STALE",
                contract,
                path,
                "upstream receipt file changed",
            )

    expected_input_entries = [_input_entry(artifact) for artifact in expected_inputs]
    actual_inputs = receipt["inputs"]
    assert isinstance(actual_inputs, list)
    expected_input_shape = [
        (entry["name"], entry["kind"], entry.get("path"), entry.get("identity"))
        for entry in expected_input_entries
    ]
    actual_input_shape = [
        (entry["name"], entry["kind"], entry.get("path"), entry.get("identity"))
        for entry in actual_inputs
    ]
    if actual_input_shape != expected_input_shape:
        return _diagnostic(
            "UPSTREAM_HANDOFF_INVALID",
            contract,
            contract.validation_path,
            "upstream receipt input set is invalid",
        )
    if actual_inputs != expected_input_entries:
        return _diagnostic(
            "UPSTREAM_HANDOFF_STALE",
            contract,
            contract.validation_path,
            "upstream receipt input hash is stale",
        )

    for artifact in expected_inputs:
        if artifact.kind != "FILE":
            continue
        try:
            current_hash = sha256_bytes(files.read_bytes(artifact.locator))
        except ProjectIOError:
            return _diagnostic(
                "UPSTREAM_HANDOFF_MISSING",
                contract,
                artifact.locator,
                "upstream receipt input file is missing",
            )
        if current_hash != artifact.sha256:
            return _diagnostic(
                "UPSTREAM_HANDOFF_STALE",
                contract,
                artifact.locator,
                "upstream receipt input file changed",
            )

    return MatchResult(True, (), receipt)


def publish_owner(
    files: ProjectFiles,
    contract: OwnerContract,
    inputs: tuple[Artifact, ...],
    candidate_outputs: dict[str, bytes],
) -> dict[str, object]:
    expected_names = [name for name, _ in contract.outputs]
    if set(candidate_outputs) != set(expected_names):
        raise ProjectIOError(
            "OWNER_OUTPUT_INVALID",
            contract.validation_path,
            "candidate output names do not match the owner contract",
        )
    _verify_input_files(files, inputs)
    reviews = _file_entries(files, contract.reviews)
    outputs = [
        {"name": name, "path": path, "sha256": sha256_bytes(candidate_outputs[name])}
        for name, path in contract.outputs
    ]
    report = _report(contract, inputs, reviews, outputs)
    for name, path in contract.outputs:
        files.write_atomic(path, candidate_outputs[name])
    files.write_atomic(contract.validation_path, canonical_json_bytes(report))
    return report


def _previous_owner_receipt(
    files: ProjectFiles,
    contract: OwnerContract,
) -> dict[str, object]:
    try:
        previous_report = files.read_json(contract.validation_path)
    except ProjectIOError as error:
        raise ProjectIOError(
            "OWNER_REBIND_RECEIPT_INVALID",
            contract.validation_path,
            "NO_CHANGE 需要上一份成功的 Owner receipt",
        ) from error
    receipt = _receipt_from_report(previous_report)
    if (
        receipt is None
        or not isinstance(previous_report, dict)
        or previous_report.get("owner") != contract.subject
        or receipt["algorithm"] != ALGORITHM
        or receipt["subject"] != contract.subject
        or receipt["validatorContractVersion"] != VALIDATOR_CONTRACT_VERSION
        or receipt["contractIds"] != list(contract.contract_ids)
    ):
        raise ProjectIOError(
            "OWNER_REBIND_RECEIPT_INVALID",
            contract.validation_path,
            "上一份成功的 Owner receipt 无效或不受支持",
        )
    previous_outputs = receipt["outputs"]
    assert isinstance(previous_outputs, list)
    if _actual_file_shape(previous_outputs) != _expected_file_shape(contract.outputs):
        raise ProjectIOError(
            "OWNER_REBIND_RECEIPT_INVALID",
            contract.validation_path,
            "上一份 Owner output 集合与当前合同不一致",
        )
    return receipt


def _verified_previous_outputs(
    files: ProjectFiles,
    contract: OwnerContract,
    receipt: dict[str, object],
) -> list[dict[str, object]]:
    previous_outputs = receipt["outputs"]
    assert isinstance(previous_outputs, list)
    for entry in previous_outputs:
        assert isinstance(entry, dict)
        path = str(entry["path"])
        try:
            current_hash = sha256_bytes(files.read_bytes(path))
        except ProjectIOError as error:
            raise ProjectIOError(
                "OWNER_REBIND_OUTPUT_CHANGED",
                path,
                "NO_CHANGE 期间缺少稳定 Owner output",
            ) from error
        if current_hash != entry["sha256"]:
            raise ProjectIOError(
                "OWNER_REBIND_OUTPUT_CHANGED",
                path,
                "NO_CHANGE 期间稳定 Owner output 字节已变化",
            )
    return [dict(entry) for entry in previous_outputs]


def validate_no_change_candidate(
    files: ProjectFiles,
    contract: OwnerContract,
    inputs: tuple[Artifact, ...],
    candidate_outputs: dict[str, bytes],
) -> list[dict[str, object]]:
    """Validate an approved NO_CHANGE candidate without writing project state."""

    expected_names = [name for name, _ in contract.outputs]
    if set(candidate_outputs) != set(expected_names):
        raise ProjectIOError(
            "OWNER_OUTPUT_INVALID",
            contract.validation_path,
            "NO_CHANGE candidate 输出名与 Owner 合同不一致",
        )
    receipt = _previous_owner_receipt(files, contract)
    outputs = _verified_previous_outputs(files, contract, receipt)
    by_name = {str(entry["name"]): entry for entry in outputs}
    for name, payload in candidate_outputs.items():
        if by_name[name]["sha256"] != sha256_bytes(payload):
            raise ProjectIOError(
                "OWNER_NO_CHANGE_CANDIDATE_CHANGED",
                str(by_name[name]["path"]),
                "NO_CHANGE candidate 必须与稳定输出原字节一致",
            )

    current_inputs = [_input_entry(artifact) for artifact in inputs]
    if receipt["inputs"] == current_inputs:
        raise ProjectIOError(
            "REBIND_INPUT_UNCHANGED",
            contract.validation_path,
            "NO_CHANGE 要求至少一项已绑定输入发生变化",
        )
    _verify_input_files(files, inputs)
    return outputs


def publish_no_change_owner(
    files: ProjectFiles,
    contract: OwnerContract,
    inputs: tuple[Artifact, ...],
    candidate_outputs: dict[str, bytes],
) -> dict[str, object]:
    outputs = validate_no_change_candidate(
        files,
        contract,
        inputs,
        candidate_outputs,
    )
    reviews = _file_entries(files, contract.reviews)
    report = _report(contract, inputs, reviews, outputs)
    files.write_atomic(contract.validation_path, canonical_json_bytes(report))
    return report


def rebind_owner(
    files: ProjectFiles,
    contract: OwnerContract,
    inputs: tuple[Artifact, ...],
) -> dict[str, object]:
    receipt = _previous_owner_receipt(files, contract)
    outputs = _verified_previous_outputs(files, contract, receipt)

    _verify_input_files(files, inputs)
    reviews = _file_entries(files, contract.reviews)
    report = _report(contract, inputs, reviews, outputs)
    files.write_atomic(contract.validation_path, canonical_json_bytes(report))
    return report
