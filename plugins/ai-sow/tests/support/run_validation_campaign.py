#!/usr/bin/env python3
"""Fail-fast, resumable validation campaigns for the AI SOW plugin.

The driver runs only deterministic local commands. Model work remains behind the
host-neutral action protocol and is never launched by this script.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence

import jsonschema


TEST_ROOT = Path(__file__).parents[1]
CONTRACT_ROOT = TEST_ROOT / "contracts"
REQUIRED_LOCK_CATEGORIES = frozenset(
    {
        "businessInputs",
        "caseManifests",
        "typedSubmissions",
        "goldens",
        "rubrics",
        "schemas",
        "templateAuthorities",
        "driversAndAssertions",
        "thresholds",
    }
)
CLASSIFICATIONS = frozenset(
    {
        "PLUGIN_DEFECT",
        "ENVIRONMENT_FAILURE",
        "FIXTURE_DEFECT",
        "TEST_HARNESS_DEFECT",
    }
)


class CampaignError(RuntimeError):
    """A safe, user-facing campaign protocol error."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"无法读取 JSON：{path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"JSON 顶层必须为对象：{path.name}")
    return value


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(_canonical_bytes(value))
    os.replace(temporary, path)


def _load_schema(name: str) -> dict[str, Any]:
    return _read_json(CONTRACT_ROOT / name)


def _validate(value: object, schema_name: str) -> None:
    try:
        jsonschema.Draft202012Validator(_load_schema(schema_name)).validate(value)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(item) for item in exc.absolute_path) or "<root>"
        raise CampaignError(f"{schema_name} 校验失败（{location}）：{exc.message}") from exc


def _resolve_relative(root: Path, locator: str, *, label: str) -> Path:
    relative = Path(locator)
    if relative.is_absolute() or ".." in relative.parts:
        raise CampaignError(f"{label} 必须是无上跳的相对路径。")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise CampaignError(f"{label} 逃逸其声明根目录。")
    return resolved


def _tree_sha256(root: Path, locators: Sequence[str]) -> str:
    entries: list[dict[str, str]] = []
    for locator in sorted(locators):
        path = _resolve_relative(root, locator, label="implementationPaths")
        if not path.exists():
            raise CampaignError(f"实现路径不存在：{locator}")
        files = (
            [path]
            if path.is_file()
            else sorted(
                item
                for item in path.rglob("*")
                if item.is_file()
                and not {"__pycache__", ".pytest_cache"}.intersection(
                    item.relative_to(path).parts
                )
                and item.suffix not in {".pyc", ".pyo"}
                and item.name not in {".DS_Store"}
            )
        )
        for file_path in files:
            display = Path(locator) if path.is_file() else Path(locator) / file_path.relative_to(path)
            entries.append({"path": display.as_posix(), "sha256": _sha256_file(file_path)})
    return _sha256_bytes(_canonical_bytes(entries))


def _environment_sha256() -> str:
    fingerprint = {
        "os": platform.system(),
        "osRelease": platform.release(),
        "machine": platform.machine(),
        "pythonImplementation": platform.python_implementation(),
        "pythonVersion": platform.python_version(),
    }
    return _sha256_bytes(_canonical_bytes(fingerprint))


def _snapshot(root: Path, locators: Sequence[str]) -> tuple[str, list[dict[str, str]]]:
    inventory: list[dict[str, str]] = []
    for locator in sorted(locators):
        path = _resolve_relative(root, locator, label="stateSnapshotPaths")
        if not path.exists():
            inventory.append({"path": locator, "sha256": "MISSING"})
            continue
        if path.is_file():
            inventory.append({"path": locator, "sha256": _sha256_file(path)})
            continue
        for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
            child = (Path(locator) / file_path.relative_to(path)).as_posix()
            inventory.append({"path": child, "sha256": _sha256_file(file_path)})
    return _sha256_bytes(_canonical_bytes(inventory)), inventory


def _validate_lock(lock_path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    if not lock_path.is_file():
        raise CampaignError("validation lock 不存在。")
    actual_sha256 = _sha256_file(lock_path)
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise CampaignError("validation lock 文件发生漂移。")
    lock = _read_json(lock_path)
    _validate(lock, "validation-lock.schema.json")
    categories = {str(entry["category"]) for entry in lock["entries"]}
    if categories != REQUIRED_LOCK_CATEGORIES:
        missing = sorted(REQUIRED_LOCK_CATEGORIES - categories)
        extra = sorted(categories - REQUIRED_LOCK_CATEGORIES)
        raise CampaignError(f"validation lock 分类不完整：missing={missing}, extra={extra}")
    root = _git_root(lock_path.parent) or lock_path.parent
    for entry in lock["entries"]:
        target = _resolve_relative(root, str(entry["path"]), label="validation lock entry")
        if not target.is_file() or _sha256_file(target) != entry["sha256"]:
            raise CampaignError(f"validation lock 条目漂移：{entry['category']}:{entry['path']}")
    return lock


def _check_oracle_implementation_separation(
    manifest: Mapping[str, Any], lock: Mapping[str, Any]
) -> None:
    implementation_paths = [Path(str(item)).parts for item in manifest["implementationPaths"]]
    oracle_paths = [Path(str(item["path"])).parts for item in lock["entries"]]
    for implementation in implementation_paths:
        for oracle in oracle_paths:
            common = min(len(implementation), len(oracle))
            if implementation[:common] == oracle[:common]:
                raise CampaignError(
                    "validation lock oracle 与可变 implementationPaths 不得重叠："
                    f"{'/'.join(implementation)} <-> {'/'.join(oracle)}"
                )


def _git_root(start: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _campaign_root(manifest_path: Path) -> Path:
    return _git_root(manifest_path.parent) or manifest_path.parent


def _check_worktree(manifest_root: Path, allowlist: Sequence[str]) -> None:
    if not allowlist:
        return
    root = _git_root(manifest_root)
    if root is None:
        raise CampaignError("声明 worktreeAllowlist 时必须从 Git worktree 启动。")
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise CampaignError("无法读取 worktree 状态。")
    unexpected: list[str] = []
    records = result.stdout.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:2]
        candidates = [record[3:]]
        if ("R" in status or "C" in status) and index < len(records) and records[index]:
            candidates.append(records[index])
            index += 1
        for candidate in candidates:
            if not any(fnmatch.fnmatch(candidate, pattern) for pattern in allowlist):
                unexpected.append(candidate)
    if unexpected:
        raise CampaignError(f"worktree 存在未计划文件：{', '.join(sorted(unexpected)[:8])}")


def _state_path(work_dir: Path) -> Path:
    return work_dir / "state.json"


def _load_state(work_dir: Path) -> dict[str, Any]:
    path = _state_path(work_dir)
    if not path.is_file():
        raise CampaignError("campaign state 不存在。")
    return _read_json(path)


def _write_state(work_dir: Path, state: dict[str, Any]) -> None:
    _atomic_json(_state_path(work_dir), state)


def _sentinel_path(work_dir: Path) -> Path:
    return work_dir / "failure-receipt.json"


def _guard_failure_sentinel(work_dir: Path) -> None:
    if _sentinel_path(work_dir).is_file():
        raise CampaignError("failure receipt 停止哨兵仍存在，必须先分类并满足恢复门禁。")


def _manifest_for_state(work_dir: Path, state: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    manifest_path = Path(str(state["manifestSource"])).resolve()
    if not manifest_path.is_file() or _sha256_file(manifest_path) != state["manifestSha256"]:
        raise CampaignError("campaign manifest 发生漂移。")
    manifest = _read_json(manifest_path)
    _validate(manifest, "validation-campaign.schema.json")
    return manifest_path, manifest


def _active_lock_path(manifest_path: Path, state: dict[str, Any]) -> Path:
    source = state.get("validationLockSource")
    if source:
        return Path(str(source)).resolve()
    return _resolve_relative(
        _campaign_root(manifest_path),
        str(state["validationLockLocator"]),
        label="validationLockPath",
    )


def _parse_outcome(stdout: bytes) -> str | None:
    for raw_line in reversed(stdout.decode("utf-8", errors="replace").splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("outcome"), str):
            return value["outcome"]
    return None


def _command_succeeded(command: dict[str, Any], result: subprocess.CompletedProcess[bytes]) -> bool:
    expected_codes = command.get("expectedExitCodes", [0])
    if result.returncode not in expected_codes:
        return False
    expected_outcomes = command.get("expectedOutcomes", [])
    return not expected_outcomes or _parse_outcome(result.stdout) in expected_outcomes


def _write_failure(
    work_dir: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    state: dict[str, Any],
    command: dict[str, Any],
    result: subprocess.CompletedProcess[bytes],
) -> None:
    index = int(state["nextCommandIndex"])
    output_root = work_dir / "commands" / f"{index:04d}-{command['commandId']}"
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "stdout.bin").write_bytes(result.stdout)
    (output_root / "stderr.bin").write_bytes(result.stderr)
    snapshot_sha256, snapshot_inventory = _snapshot(
        _campaign_root(manifest_path), command.get("stateSnapshotPaths", [])
    )
    receipt = {
        "contract": "ai-sow-validation-failure-receipt-v1",
        "campaignId": manifest["campaignId"],
        "commandId": command["commandId"],
        "scenarioId": command["scenarioId"],
        "sampleIndex": command["sampleIndex"],
        "cacheMode": command["cacheMode"],
        "runId": f"{manifest['campaignId']}:{command['scenarioId']}:{command['sampleIndex']}",
        "actionId": command["commandId"],
        "lastSuccessfulCheckpoint": state.get("lastSuccessfulCheckpoint"),
        "exitCode": result.returncode,
        "stdoutSha256": _sha256_bytes(result.stdout),
        "stderrSha256": _sha256_bytes(result.stderr),
        "stateSnapshotSha256": snapshot_sha256,
        "stateSnapshotInventory": snapshot_inventory,
        "implementationTreeSha256": state["implementationTreeSha256"],
        "environmentFingerprintSha256": _environment_sha256(),
        "validationLockSha256": state["validationLockSha256"],
        "workLocator": ".",
        "outputLocator": output_root.relative_to(work_dir).as_posix(),
        "checkpointLocator": command["checkpointId"],
    }
    _atomic_json(_sentinel_path(work_dir), receipt)


def _execute(work_dir: Path, manifest_path: Path, manifest: dict[str, Any], state: dict[str, Any]) -> int:
    commands = manifest["commands"]
    while int(state["nextCommandIndex"]) < len(commands):
        _guard_failure_sentinel(work_dir)
        index = int(state["nextCommandIndex"])
        command = commands[index]
        if command["kind"] == "USER_CHECKPOINT":
            return _pause_for_user(work_dir, manifest_path, state, command)
        if any(argument == "--update-golden" or argument.startswith("--update-golden=") for argument in command["argv"]):
            raise CampaignError("validation campaign 禁止 update-golden 模式。")
        result = subprocess.run(
            [str(argument) for argument in command["argv"]],
            cwd=_campaign_root(manifest_path),
            capture_output=True,
            check=False,
        )
        if not _command_succeeded(command, result):
            _write_failure(work_dir, manifest_path, manifest, state, command, result)
            if os.environ.get("AI_SOW_CAMPAIGN_CRASH_AFTER_RECEIPT") == "1":
                raise RuntimeError("injected crash after failure receipt")
            state["status"] = "FAILED_UNTRIAGED"
            state["unresolvedFailures"] = [_sha256_file(_sentinel_path(work_dir))]
            _write_state(work_dir, state)
            return 2
        output_root = work_dir / "commands" / f"{index:04d}-{command['commandId']}"
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / "stdout.bin").write_bytes(result.stdout)
        (output_root / "stderr.bin").write_bytes(result.stderr)
        state["results"].append(
            {
                "commandId": command["commandId"],
                "scenarioId": command["scenarioId"],
                "sampleIndex": command["sampleIndex"],
                "checkpointId": command["checkpointId"],
                "exitCode": result.returncode,
                "stdoutSha256": _sha256_bytes(result.stdout),
                "stderrSha256": _sha256_bytes(result.stderr),
                "valid": True,
            }
        )
        state["lastSuccessfulCheckpoint"] = command["checkpointId"]
        state["nextCommandIndex"] = index + 1
        _write_state(work_dir, state)
    state["status"] = "COMPLETE"
    state["unresolvedFailures"] = []
    _write_state(work_dir, state)
    return 0


def _pause_for_user(
    work_dir: Path,
    manifest_path: Path,
    state: dict[str, Any],
    command: dict[str, Any],
) -> int:
    artifact = _resolve_relative(
        _campaign_root(manifest_path), str(command["artifactPath"]), label="artifactPath"
    )
    if not artifact.is_file():
        raise CampaignError("用户检查点 artifact 不存在。")
    pause = {
        "contract": "ai-sow-validation-user-checkpoint-v1",
        "commandId": command["commandId"],
        "resumeCommandId": command["commandId"],
        "artifactLocator": command["artifactPath"],
        "artifactSha256": _sha256_file(artifact),
        "requiredReceiptContract": command["requiredReceiptContract"],
        "receiptLocator": command["receiptPath"],
    }
    _atomic_json(work_dir / "user-checkpoint.json", pause)
    state["status"] = "AWAITING_USER_CHECKPOINT"
    _write_state(work_dir, state)
    return 0


def start(manifest_path: Path, work_dir: Path) -> int:
    manifest_path = manifest_path.resolve()
    work_dir = work_dir.resolve()
    if work_dir.exists() and any(work_dir.iterdir()):
        raise CampaignError("work-dir 必须不存在或为空。")
    manifest = _read_json(manifest_path)
    _validate(manifest, "validation-campaign.schema.json")
    if len({command["commandId"] for command in manifest["commands"]}) != len(manifest["commands"]):
        raise CampaignError("commandId 必须唯一。")
    campaign_root = _campaign_root(manifest_path)
    _check_worktree(campaign_root, manifest["worktreeAllowlist"])
    lock_path = _resolve_relative(
        campaign_root, manifest["validationLockPath"], label="validationLockPath"
    )
    lock = _validate_lock(lock_path, manifest["validationLockSha256"])
    _check_oracle_implementation_separation(manifest, lock)
    implementation_sha256 = _tree_sha256(campaign_root, manifest["implementationPaths"])
    work_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "contract": "ai-sow-validation-campaign-state-v1",
        "campaignId": manifest["campaignId"],
        "status": "RUNNING",
        "manifestSource": str(manifest_path),
        "manifestSha256": _sha256_file(manifest_path),
        "validationLockLocator": manifest["validationLockPath"],
        "validationLockSource": str(lock_path),
        "validationLockSha256": manifest["validationLockSha256"],
        "implementationTreeSha256": implementation_sha256,
        "nextCommandIndex": 0,
        "lastSuccessfulCheckpoint": None,
        "results": [],
        "invalidatedResultIndexes": [],
        "failureHistory": [],
        "unresolvedFailures": [],
        "workDirIdentity": _sha256_bytes(str(work_dir).encode("utf-8")),
        "archiveSha256": None,
    }
    _write_state(work_dir, state)
    return _execute(work_dir, manifest_path, manifest, state)


def _read_classification(path: Path, failure: dict[str, Any]) -> dict[str, Any]:
    value = _read_json(path)
    required = {
        "contract",
        "classification",
        "rootCause",
        "ownerModule",
        "resumeCommandId",
        "remediationPlan",
        "remediationReceiptPath",
        "replacementValidationLockPath",
    }
    if set(value) != required or value.get("contract") != "ai-sow-validation-classification-v1":
        raise CampaignError("root-cause classification 合同无效。")
    if value.get("classification") not in CLASSIFICATIONS:
        raise CampaignError("failure 必须先归入四种可恢复根因分类。")
    for field in ("rootCause", "ownerModule", "resumeCommandId", "remediationPlan"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise CampaignError(f"classification 缺少 {field}。")
    if value["resumeCommandId"] != failure["commandId"]:
        raise CampaignError("resumeCommandId 必须精确指向失败命令。")
    return value


def classify(work_dir: Path, classification_path: Path) -> int:
    work_dir = work_dir.resolve()
    state = _load_state(work_dir)
    sentinel = _sentinel_path(work_dir)
    if not sentinel.is_file():
        raise CampaignError("没有可分类的 failure receipt。")
    if state["status"] not in {"FAILED_UNTRIAGED", "RUNNING"}:
        raise CampaignError("当前 campaign 状态不可分类。")
    failure = _read_json(sentinel)
    try:
        value = _read_classification(classification_path.resolve(), failure)
    except CampaignError:
        return 2
    _atomic_json(work_dir / "classification.json", value)
    state["status"] = "FAILED_CLASSIFIED"
    state["unresolvedFailures"] = [_sha256_file(sentinel)]
    _write_state(work_dir, state)
    return 0


def _require_remediation(
    work_dir: Path,
    manifest_path: Path,
    classification: dict[str, Any],
    failure: dict[str, Any],
    failure_sha256: str,
    current_implementation_sha256: str,
) -> None:
    locator = classification.get("remediationReceiptPath")
    if not isinstance(locator, str) or not locator:
        raise CampaignError("分类后恢复必须提供 remediation receipt。")
    receipt_path = _resolve_relative(work_dir, locator, label="remediationReceiptPath")
    receipt = _read_json(receipt_path)
    if receipt.get("failureReceiptSha256") != failure_sha256:
        raise CampaignError("remediation receipt 未绑定当前 failure receipt。")
    classification_name = classification["classification"]
    if classification_name == "ENVIRONMENT_FAILURE":
        if receipt.get("contract") != "ai-sow-environment-remediation-v1" or receipt.get("status") != "READY_TO_RESUME":
            raise CampaignError("environment remediation receipt 无效。")
        return
    if classification_name == "PLUGIN_DEFECT":
        _require_plugin_remediation(
            work_dir,
            manifest_path,
            receipt,
            failure,
            failure_sha256,
            current_implementation_sha256,
        )
        return
    if receipt.get("contract") != "ai-sow-oracle-remediation-v1" or receipt.get("status") != "READY_TO_RESUME":
        raise CampaignError("fixture/harness remediation receipt 无效。")


def _require_plugin_remediation(
    work_dir: Path,
    manifest_path: Path,
    receipt: dict[str, Any],
    failure: dict[str, Any],
    failure_sha256: str,
    current_implementation_sha256: str,
) -> None:
    if receipt.get("contract") != "ai-sow-plugin-remediation-v1" or receipt.get("status") != "READY_TO_RESUME":
        raise CampaignError("plugin remediation receipt 无效。")
    if receipt.get("preFixImplementationTreeSha256") != failure["implementationTreeSha256"]:
        raise CampaignError("plugin remediation 未绑定 failure 时的实现树。")
    if receipt.get("postFixImplementationTreeSha256") != current_implementation_sha256:
        raise CampaignError("plugin remediation 未绑定当前修复实现树。")
    paths = receipt.get("verificationReceiptPaths")
    required = {"reproductionFreeze", "red", "green", "ownerRegression", "batchGate"}
    if not isinstance(paths, dict) or set(paths) != required:
        raise CampaignError("plugin defect 恢复缺少 reproduction/red/green/Owner/Batch 收据。")
    if receipt.get("redTestId") != receipt.get("greenTestId"):
        raise CampaignError("plugin defect 必须由同一最小复现从 red 转为 green。")
    evidence = {
        name: _read_json(_resolve_relative(work_dir, str(locator), label=f"{name} receipt"))
        for name, locator in paths.items()
    }
    freeze = evidence["reproductionFreeze"]
    if (
        freeze.get("contract") != "ai-sow-reproduction-freeze-v1"
        or freeze.get("failureReceiptSha256") != failure_sha256
        or freeze.get("baseImplementationTreeSha256") != failure["implementationTreeSha256"]
        or freeze.get("appendOnly") is not True
    ):
        raise CampaignError("最小复现未在产品实现变更前以 append-only 方式冻结。")
    extension_locator = freeze.get("extensionPath")
    extension_sha256 = freeze.get("extensionSha256")
    reproduction_tree_sha256 = freeze.get("reproductionTreeSha256")
    if not isinstance(extension_locator, str) or not isinstance(extension_sha256, str):
        raise CampaignError("reproduction freeze 缺少扩展路径或哈希。")
    extension_path = _resolve_relative(
        _campaign_root(manifest_path), extension_locator, label="reproduction extension"
    )
    if not extension_path.is_file() or _sha256_file(extension_path) != extension_sha256:
        raise CampaignError("冻结后的最小复现扩展被修改或删除。")
    if reproduction_tree_sha256 == failure["implementationTreeSha256"]:
        raise CampaignError("append-only reproduction extension 未进入实现树快照。")
    if current_implementation_sha256 == reproduction_tree_sha256:
        raise CampaignError("只有复现测试发生变化；缺少产品实现修复。")

    def require_execution(name: str, *, role: str, outcome: str, tree_sha256: str) -> None:
        value = evidence[name]
        if (
            value.get("contract") != "ai-sow-validation-execution-receipt-v1"
            or value.get("role") != role
            or value.get("outcome") != outcome
            or value.get("implementationTreeSha256") != tree_sha256
            or value.get("reproductionSha256") != extension_sha256
        ):
            raise CampaignError(f"{name} execution receipt 无效。")

    require_execution(
        "red",
        role="MINIMAL_REPRODUCTION",
        outcome="FAILED",
        tree_sha256=str(reproduction_tree_sha256),
    )
    require_execution(
        "green",
        role="MINIMAL_REPRODUCTION",
        outcome="PASSED",
        tree_sha256=current_implementation_sha256,
    )
    require_execution(
        "ownerRegression",
        role="OWNER_REGRESSION",
        outcome="PASSED",
        tree_sha256=current_implementation_sha256,
    )
    require_execution(
        "batchGate",
        role="BATCH_GATE",
        outcome="PASSED",
        tree_sha256=current_implementation_sha256,
    )
    if evidence["red"].get("testId") != receipt["redTestId"]:
        raise CampaignError("red receipt 未绑定声明的最小复现。")
    if evidence["green"].get("testId") != receipt["greenTestId"]:
        raise CampaignError("green receipt 未绑定同一最小复现。")


def _resume_user_checkpoint(work_dir: Path, manifest_path: Path, manifest: dict[str, Any], state: dict[str, Any]) -> int:
    index = int(state["nextCommandIndex"])
    command = manifest["commands"][index]
    pause = _read_json(work_dir / "user-checkpoint.json")
    artifact = _resolve_relative(_campaign_root(manifest_path), command["artifactPath"], label="artifactPath")
    if _sha256_file(artifact) != pause.get("artifactSha256"):
        raise CampaignError("用户检查点 artifact 在等待期间发生漂移。")
    receipt_path = _resolve_relative(work_dir, command["receiptPath"], label="receiptPath")
    receipt = _read_json(receipt_path)
    if receipt.get("contract") != command["requiredReceiptContract"]:
        raise CampaignError("用户检查点收据合同不匹配。")
    if receipt.get("artifactSha256") != pause["artifactSha256"] or receipt.get("independent") is not True:
        raise CampaignError("用户检查点收据未绑定 artifact 或不是独立评审。")
    state["results"].append(
        {
            "commandId": command["commandId"],
            "scenarioId": command["scenarioId"],
            "sampleIndex": command["sampleIndex"],
            "checkpointId": command["checkpointId"],
            "receiptSha256": _sha256_file(receipt_path),
            "valid": True,
        }
    )
    state["lastSuccessfulCheckpoint"] = command["checkpointId"]
    state["nextCommandIndex"] = index + 1
    state["status"] = "RUNNING"
    (work_dir / "user-checkpoint.json").replace(
        work_dir / f"user-checkpoint-{index:04d}-closed.json"
    )
    _write_state(work_dir, state)
    return _execute(work_dir, manifest_path, manifest, state)


def resume(work_dir: Path) -> int:
    work_dir = work_dir.resolve()
    state = _load_state(work_dir)
    manifest_path, manifest = _manifest_for_state(work_dir, state)
    _check_worktree(_campaign_root(manifest_path), manifest["worktreeAllowlist"])
    if state["status"] == "AWAITING_USER_CHECKPOINT":
        _guard_failure_sentinel(work_dir)
        lock = _validate_lock(
            _active_lock_path(manifest_path, state), state["validationLockSha256"]
        )
        _check_oracle_implementation_separation(manifest, lock)
        return _resume_user_checkpoint(work_dir, manifest_path, manifest, state)
    sentinel = _sentinel_path(work_dir)
    if not sentinel.is_file():
        raise CampaignError("没有可恢复的 failure receipt。")
    if state["status"] != "FAILED_CLASSIFIED":
        raise CampaignError("failure 尚未完成根因分类。")
    failure = _read_json(sentinel)
    failure_sha256 = _sha256_file(sentinel)
    classification = _read_json(work_dir / "classification.json")
    if classification.get("resumeCommandId") != failure.get("commandId"):
        raise CampaignError("classification 的恢复目标与失败命令不一致。")
    classification_name = classification["classification"]
    original_lock = _active_lock_path(manifest_path, state)
    current_implementation = _tree_sha256(_campaign_root(manifest_path), manifest["implementationPaths"])
    if classification_name in {"FIXTURE_DEFECT", "TEST_HARNESS_DEFECT"}:
        if _sha256_file(original_lock) != state["validationLockSha256"]:
            raise CampaignError("原 validation lock 文件发生漂移；必须保留原 oracle 证据。")
        original_lock_value = _read_json(original_lock)
        _validate(original_lock_value, "validation-lock.schema.json")
        _check_oracle_implementation_separation(manifest, original_lock_value)
    else:
        original_lock_value = _validate_lock(
            original_lock, state["validationLockSha256"]
        )
        _check_oracle_implementation_separation(manifest, original_lock_value)
    _require_remediation(
        work_dir,
        manifest_path,
        classification,
        failure,
        failure_sha256,
        current_implementation,
    )
    if classification_name != "PLUGIN_DEFECT" and current_implementation != state["implementationTreeSha256"]:
        raise CampaignError("非插件缺陷恢复期间实现树不得漂移。")
    if classification_name in {"FIXTURE_DEFECT", "TEST_HARNESS_DEFECT"}:
        replacement = classification.get("replacementValidationLockPath")
        if not isinstance(replacement, str) or not replacement:
            raise CampaignError("fixture/harness 修复必须提供 replacement validation lock。")
        replacement_path = _resolve_relative(work_dir, replacement, label="replacementValidationLockPath")
        replacement_lock = _validate_lock(replacement_path)
        _check_oracle_implementation_separation(manifest, replacement_lock)
        for index, result in enumerate(state["results"]):
            result["valid"] = False
            state["invalidatedResultIndexes"].append(index)
        state["validationLockSource"] = str(replacement_path)
        state["validationLockSha256"] = _sha256_file(replacement_path)
    history_root = work_dir / "failure-history" / f"{len(state['failureHistory']):04d}-{failure['commandId']}"
    history_root.mkdir(parents=True, exist_ok=False)
    shutil.move(str(sentinel), history_root / "failure-receipt.json")
    shutil.move(str(work_dir / "classification.json"), history_root / "classification.json")
    remediation_path = _resolve_relative(work_dir, classification["remediationReceiptPath"], label="remediationReceiptPath")
    shutil.copyfile(remediation_path, history_root / "remediation-receipt.json")
    state["failureHistory"].append(
        {
            "commandId": failure["commandId"],
            "failureReceiptSha256": failure_sha256,
            "classification": classification_name,
            "historyLocator": history_root.relative_to(work_dir).as_posix(),
            "resumeCommandIndex": state["nextCommandIndex"],
        }
    )
    state["implementationTreeSha256"] = current_implementation
    state["unresolvedFailures"] = []
    state["status"] = "RUNNING"
    _write_state(work_dir, state)
    return _execute(work_dir, manifest_path, manifest, state)


def validate_campaign(work_dir: Path, *, require_complete: bool, require_closed: bool) -> int:
    work_dir = work_dir.resolve()
    state = _load_state(work_dir)
    if _sentinel_path(work_dir).is_file():
        raise CampaignError("campaign 仍有 failure receipt 停止哨兵。")
    manifest_path, manifest = _manifest_for_state(work_dir, state)
    lock = _validate_lock(
        _active_lock_path(manifest_path, state), state["validationLockSha256"]
    )
    _check_oracle_implementation_separation(manifest, lock)
    if require_complete and state["status"] != "COMPLETE":
        raise CampaignError("campaign 尚未 COMPLETE。")
    if require_closed and state["unresolvedFailures"]:
        raise CampaignError("campaign 仍有未闭合 failure。")
    if len(state["results"]) != len(manifest["commands"]):
        raise CampaignError("campaign 结果数量与命令数量不一致。")
    return 0


def archive(work_dir: Path, output: Path) -> int:
    work_dir = work_dir.resolve()
    output = output.resolve()
    state = _load_state(work_dir)
    if state["status"] != "COMPLETE" or state["unresolvedFailures"] or _sentinel_path(work_dir).exists():
        raise CampaignError("只能封存无未解决失败的 COMPLETE campaign。")
    if output == work_dir or work_dir in output.parents:
        raise CampaignError("archive 必须位于待清理 work-dir 之外。")
    history = []
    for item in state["failureHistory"]:
        history.append(
            {
                "commandId": item["commandId"],
                "classification": item["classification"],
                "failureReceiptSha256": item["failureReceiptSha256"],
                "historyLocator": item["historyLocator"],
            }
        )
    summary = {
        "contract": "ai-sow-validation-campaign-archive-v1",
        "campaignId": state["campaignId"],
        "status": state["status"],
        "workDirName": work_dir.name,
        "workDirIdentity": state["workDirIdentity"],
        "manifestSha256": state["manifestSha256"],
        "validationLockSha256": state["validationLockSha256"],
        "implementationTreeSha256": state["implementationTreeSha256"],
        "resultCount": len(state["results"]),
        "failureHistory": history,
        "unresolvedFailures": [],
    }
    _atomic_json(output, summary)
    state["archiveSha256"] = _sha256_file(output)
    _write_state(work_dir, state)
    return 0


def cleanup(work_dir: Path, archive_path: Path) -> int:
    work_dir = work_dir.resolve()
    archive_path = archive_path.resolve()
    state = _load_state(work_dir)
    archive_value = _read_json(archive_path)
    if state["status"] != "COMPLETE" or state["unresolvedFailures"]:
        raise CampaignError("cleanup 只接受无未解决失败的 COMPLETE campaign。")
    if state.get("archiveSha256") != _sha256_file(archive_path):
        raise CampaignError("archive hash 未复核。")
    if archive_value.get("workDirIdentity") != state["workDirIdentity"]:
        raise CampaignError("archive 不属于这个精确 work-dir。")
    forbidden = {Path.cwd().resolve(), Path.home().resolve(), Path(work_dir.anchor).resolve()}
    if work_dir in forbidden or len(work_dir.parts) < 3:
        raise CampaignError("拒绝清理过宽目录。")
    shutil.rmtree(work_dir)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--manifest", type=Path, required=True)
    start_parser.add_argument("--work-dir", type=Path, required=True)
    classify_parser = subparsers.add_parser("classify")
    classify_parser.add_argument("--work-dir", type=Path, required=True)
    classify_parser.add_argument("--classification-file", type=Path, required=True)
    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--work-dir", type=Path, required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--work-dir", type=Path, required=True)
    validate_parser.add_argument("--require-complete", action="store_true")
    validate_parser.add_argument("--require-no-unresolved-failures", action="store_true")
    archive_parser = subparsers.add_parser("archive")
    archive_parser.add_argument("--work-dir", type=Path, required=True)
    archive_parser.add_argument("--output", type=Path, required=True)
    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("--work-dir", type=Path, required=True)
    cleanup_parser.add_argument("--archive", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "start":
            return start(args.manifest, args.work_dir)
        if args.operation == "classify":
            return classify(args.work_dir, args.classification_file)
        if args.operation == "resume":
            return resume(args.work_dir)
        if args.operation == "validate":
            return validate_campaign(
                args.work_dir,
                require_complete=args.require_complete,
                require_closed=args.require_no_unresolved_failures,
            )
        if args.operation == "archive":
            return archive(args.work_dir, args.output)
        if args.operation == "cleanup":
            return cleanup(args.work_dir, args.archive)
    except CampaignError as exc:
        print(json.dumps({"outcome": "BLOCKED", "message": str(exc)}, ensure_ascii=False))
        return 2
    raise AssertionError(args.operation)


if __name__ == "__main__":
    raise SystemExit(main())
