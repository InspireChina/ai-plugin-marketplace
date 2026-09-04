#!/usr/bin/env python3
"""Host-neutral protocol for recording AI SOW pipeline benchmarks.

The runner never starts a model process.  It emits a self-contained action for an
external fresh worker and accepts a hash-bound execution receipt from the host.
That keeps the benchmark usable from Codex, Claude Code, CI, or another host on
Windows, macOS, and Linux without making any vendor CLI a runtime dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Sequence

import jsonschema


PLUGIN_ROOT = Path(__file__).parents[2]
TEST_ROOT = PLUGIN_ROOT / "tests"
CONTRACT_ROOT = TEST_ROOT / "contracts"
DEFAULT_POLICY_PATH = TEST_ROOT / "benchmarks/model-efficiency-policy-v1.json"
EXPECTED_SCENARIOS = (
    "small-greenfield",
    "medium-demo",
    "large-brownfield",
    "blocked-missing-design",
    "blocked-source-conflict",
)
SUCCESS_SCENARIOS = frozenset(EXPECTED_SCENARIOS[:3])
BLOCKED_CACHE_MODES = {
    "blocked-missing-design": "COLD",
    "blocked-source-conflict": "WARM",
}
SAME_EXECUTION_PROFILE_FIELDS = (
    "modelProfileId",
    "model",
    "reasoningEffort",
    "environmentSha256",
    "toolVersions",
    "office",
    "accountingMode",
    "cacheProtocol",
)
SUCCESS_ACTION_STAGES = frozenset({"STAGE_1", "STAGE_2", "STAGE_3", "R1", "R2", "R3"})
SUCCESS_RECEIPT_STAGES = SUCCESS_ACTION_STAGES | {"DRAFT_OFFICE"}
BLOCKED_ACTION_STAGES = frozenset({"CONTROL_PLANE"})
BLOCKED_RECEIPT_STAGES = frozenset({"CONTROL_PLANE"})
POST_REVIEW_STAGES = frozenset(
    {"R2", "R3", "REPAIR", "DELTA_REVIEW", "ADJUDICATION", "DRAFT_OFFICE"}
)
REVIEW_STAGES = frozenset(
    {"R1", "R2", "R3", "REPAIR", "DELTA_REVIEW", "ADJUDICATION"}
)
ADDITIVE_USAGE_FIELDS = (
    "inputTokens",
    "cachedInputTokens",
    "outputTokens",
    "controlPlaneTokens",
    "toolContextTokens",
)
ADDITIVE_TIMING_FIELDS = (
    "queueMilliseconds",
    "executionMilliseconds",
    "joinMilliseconds",
    "totalMilliseconds",
    "criticalPathMilliseconds",
)
ADDITIVE_WORK_FIELDS = (
    "hydrationRounds",
    "toolAttempts",
    "modelAttempts",
    "actionAttempts",
    "repairWaves",
    "adjudications",
    "recompiles",
    "rereviews",
    "failures",
    "retries",
)
CACHE_PROTOCOL = {
    "COLD": {
        "hostPrewarm": "NONE",
        "namespaceMode": "SAMPLE_UNIQUE",
        "providerCacheObservation": "RECORDED_NOT_ASSUMED_ZERO",
    },
    "WARM": {
        "hostPrewarm": "PRIOR_MEASURED_COLD_RUNS",
        "namespaceMode": "SCENARIO_STABLE",
        "providerCacheObservation": "RECORDED_NOT_REQUIRED",
    },
}


class ProtocolError(RuntimeError):
    """A machine-readable benchmark protocol error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_json_bytes(value: object) -> bytes:
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
        raise ProtocolError("INVALID_JSON", f"无法读取 JSON：{path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtocolError("INVALID_JSON", f"JSON 顶层必须为对象：{path.name}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical_json_bytes(value))
    temporary.replace(path)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _lower_kebab(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if "-" not in normalized:
        normalized = f"source-{normalized}"
    return normalized


def materialize_case_project(case_path: Path, project_root: Path) -> dict[str, Any]:
    """Create deterministic public-Skill inputs before model timing starts."""

    case = _read_json(case_path)
    if project_root.exists() and any(project_root.iterdir()):
        raise ProtocolError(
            "PROJECT_NOT_EMPTY",
            "benchmark sample 必须使用新的空项目目录。",
        )
    project_root.mkdir(parents=True, exist_ok=True)
    request_sources: list[dict[str, str]] = []
    prior_summary: str | None = None
    used_source_ids: set[str] = set()
    for index, source in enumerate(case["sources"], start=1):
        source_type = str(source["type"])
        source_id = _lower_kebab(str(source["sourceId"]))
        if source_id in used_source_ids:
            raise ProtocolError("DUPLICATE_SOURCE_ID", f"来源 ID 规范化后重复：{source_id}")
        used_source_ids.add(source_id)
        role = source_type
        source_status = str(source["status"])
        if source_type == "HLD" and source_status == "MISSING":
            source_status = "DRAFT"
        if source_type == "PRIOR_SOW" and source_status == "ACCEPTED_BASELINE":
            source_status = "APPLICABLE"
        if source_type == "PRIOR_SOW":
            relative_path = Path("inputs") / f"{source_id}.xlsx"
            authority = PLUGIN_ROOT / "docs/reference/SOW估算与生成示例_v1.3.xlsx"
            if not authority.is_file():
                raise ProtocolError(
                    "PRIOR_SOW_FIXTURE_MISSING",
                    "匿名 Brownfield 基准缺少可复读的 PRIOR_SOW 工作簿。",
                )
            target = project_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(authority, target)
            prior_summary = str(source["content"])
        else:
            relative_path = Path("inputs") / f"{source_id}.md"
            document = (
                f"# {case['title']}\n\n"
                f"## 来源身份\n\n{source['sourceId']} / {source_type} / {source['status']}\n\n"
                f"## 已批准范围\n\n{source['content']}\n"
            )
            _write_text(project_root / relative_path, document)
        request_sources.append(
            {
                "sourceId": source_id,
                "role": role,
                "path": relative_path.as_posix(),
                "status": source_status,
            }
        )
    mode = str(case["mode"])
    request = {
        "contract": "ai-sow-generate-request-v2",
        "project": {
            "projectId": f"benchmark-{case['scenarioId']}",
            "name": case["title"],
            "plannedEffectiveDate": "2026-10-01",
        },
        "mode": mode,
        "responsibilityBoundaries": [
            {
                "responsibilityBoundaryId": "responsibility-vendor-delivery",
                "party": "VENDOR",
                "name": "供应商交付责任",
                "responsibilities": ["完成范围内设计、实现、自测、发布支持和交付移交"],
            },
            {
                "responsibilityBoundaryId": "responsibility-customer-acceptance",
                "party": "CUSTOMER",
                "name": "客户输入与验收责任",
                "responsibilities": ["提供已批准来源、目标环境和验收人员并完成业务裁决"],
            },
        ],
        "sources": request_sources,
        "questions": [],
        "questionnaireAnswers": [],
        "currentStateDelta": (
            None
            if mode == "GREENFIELD"
            else {
                "status": "NO_KNOWN_CHANGES",
                "summary": prior_summary or "往期 SOW 生效后无其他已知变化。",
                "supplementalSourceIds": [],
            }
        ),
    }
    _write_json(project_root / "request.json", request)
    return {
        "requestPath": "request.json",
        "requestSha256": _sha256_file(project_root / "request.json"),
        "sourcePaths": [source["path"] for source in request_sources],
    }


def public_prepare_command(
    *, plugin_root: Path, project_root: Path, windows: bool
) -> list[str]:
    """Return the public bootstrap invocation for the current platform."""

    if windows:
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            (plugin_root / "skills/generate/scripts/bootstrap.ps1").as_posix(),
            "-ProjectRoot",
            project_root.as_posix(),
            "-Mode",
            "start",
            "-Request",
            "request.json",
        ]
    return [
        "sh",
        (plugin_root / "skills/generate/scripts/bootstrap.sh").as_posix(),
        "--project-root",
        project_root.as_posix(),
        "--mode",
        "start",
        "--request",
        "request.json",
    ]


def _emit(value: object) -> None:
    sys.stdout.buffer.write(_canonical_json_bytes(value))


def _schema(name: str) -> dict[str, Any]:
    return _read_json(CONTRACT_ROOT / name)


def _validate_schema(name: str, value: object) -> None:
    try:
        jsonschema.Draft202012Validator(_schema(name)).validate(value)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(item) for item in exc.absolute_path) or "<root>"
        raise ProtocolError(
            "SCHEMA_VALIDATION_FAILED",
            f"{name} 在 {location} 不符合合同：{exc.message}",
        ) from exc


def _relative_to_plugin(path: Path) -> str:
    try:
        return path.resolve().relative_to(PLUGIN_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ProtocolError(
            "PATH_OUTSIDE_PLUGIN",
            "可发布 benchmark 资产必须位于插件目录内。",
        ) from exc


def _parse_tool_versions(values: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        name, separator, version = value.partition("=")
        if not separator or not name or not version:
            raise ProtocolError(
                "INVALID_TOOL_VERSION",
                "--tool-version 必须使用 name=version 格式。",
            )
        if name in parsed:
            raise ProtocolError("DUPLICATE_TOOL_VERSION", f"工具版本重复：{name}")
        parsed[name] = version
    required = {"host-client", "python", "uv"}
    if not required.issubset(parsed):
        missing = ", ".join(sorted(required - parsed.keys()))
        raise ProtocolError("TOOL_VERSION_MISSING", f"缺少工具版本：{missing}")
    return parsed


def _load_cases(scenario_root: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for scenario_id in EXPECTED_SCENARIOS:
        path = scenario_root / scenario_id / "case.json"
        case = _read_json(path)
        expected_class = "SUCCESS" if scenario_id in SUCCESS_SCENARIOS else "BLOCKED"
        required = {
            "contract": "ai-sow-benchmark-case-v1",
            "scenarioId": scenario_id,
            "class": expected_class,
            "privacy": "ANONYMOUS_SYNTHETIC",
        }
        for key, expected in required.items():
            if case.get(key) != expected:
                raise ProtocolError(
                    "INVALID_BENCHMARK_CASE",
                    f"{scenario_id} 的 {key} 必须为 {expected!r}。",
                )
        sources = case.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ProtocolError("INVALID_BENCHMARK_CASE", f"{scenario_id} 缺少匿名来源。")
        if scenario_id == "large-brownfield":
            scale = case.get("scaleExpectations")
            if not isinstance(scale, dict) or scale.get("requiresModelSharding") is not True:
                raise ProtocolError(
                    "INVALID_BENCHMARK_CASE",
                    "large-brownfield 必须要求模型分片。",
                )
        cases.append(
            {
                "scenarioId": scenario_id,
                "class": expected_class,
                "casePath": _relative_to_plugin(path),
                "caseSha256": _sha256_file(path),
                "case": case,
            }
        )
    return cases


def _queue(cases: Sequence[dict[str, Any]], runs: int) -> list[dict[str, Any]]:
    queued: list[dict[str, Any]] = []
    by_id = {case["scenarioId"]: case for case in cases}
    for scenario_id in EXPECTED_SCENARIOS[:3]:
        case = by_id[scenario_id]
        for cache_mode in ("COLD", "WARM"):
            for repetition in range(1, runs + 1):
                queued.append(_sample(case, cache_mode, repetition))
    for scenario_id in EXPECTED_SCENARIOS[3:]:
        queued.append(_sample(by_id[scenario_id], BLOCKED_CACHE_MODES[scenario_id], 1))
    return queued


def _sample(case: dict[str, Any], cache_mode: str, repetition: int) -> dict[str, Any]:
    scenario_id = str(case["scenarioId"])
    sample_id = f"{scenario_id}-{cache_mode.lower()}-r{repetition:02d}"
    return {
        "sampleId": sample_id,
        "scenarioId": scenario_id,
        "scenarioClass": case["class"],
        "casePath": case["casePath"],
        "caseSha256": case["caseSha256"],
        "cacheMode": cache_mode,
        "repetition": repetition,
    }


def _state_path(state_dir: Path) -> Path:
    return state_dir / "session.json"


def _load_state(state_dir: Path) -> dict[str, Any]:
    state = _read_json(_state_path(state_dir))
    if state.get("contract") != "ai-sow-pipeline-benchmark-session-v1":
        raise ProtocolError("INVALID_SESSION", "benchmark session 合同不受支持。")
    return state


def _save_state(state_dir: Path, state: dict[str, Any]) -> None:
    _write_json(_state_path(state_dir), state)


def _prepared_artifact_hashes(project_root: Path) -> dict[str, str]:
    return {
        path.relative_to(project_root).as_posix(): _sha256_file(path)
        for path in sorted(project_root.rglob("*"))
        if path.is_file() and not path.name.startswith(".")
    }


def _run_public_prepare(
    *, project_root: Path, office_bin: str | None
) -> dict[str, Any]:
    command = public_prepare_command(
        plugin_root=PLUGIN_ROOT,
        project_root=project_root,
        windows=os.name == "nt",
    )
    environment = os.environ.copy()
    if office_bin:
        environment["AI_SOW_OFFICE_BIN"] = office_bin
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=project_root,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    outcome: dict[str, Any] | None = None
    for line in reversed(completed.stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and isinstance(candidate.get("outcome"), str):
            outcome = candidate
            break
    if outcome is None:
        raise ProtocolError(
            "PUBLIC_PREPARE_OUTPUT_INVALID",
            "公开 prepare 未返回唯一可解析的 UTF-8 JSON outcome。",
        )
    if completed.returncode not in {0, 2}:
        raise ProtocolError(
            "PUBLIC_PREPARE_EXECUTION_FAILED",
            f"公开 prepare 异常退出：{completed.returncode}",
        )
    return {
        "requestPath": "request.json",
        "prepareMilliseconds": elapsed,
        "prepareOutcome": outcome,
        "artifactHashes": _prepared_artifact_hashes(project_root),
    }


def _action_for(
    state: dict[str, Any],
    sample: dict[str, Any],
    *,
    project_root: Path | None = None,
    prepared_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = state["config"]
    case_path = PLUGIN_ROOT / sample["casePath"]
    case = _read_json(case_path)
    operation = (
        "CONTINUE_PUBLIC_GENERATE_FROM_ACCEPTED_INPUT"
        if prepared_input is not None
        else "RUN_PUBLIC_GENERATE_SKILL"
    )
    cache_mode = str(sample["cacheMode"])
    cache_protocol = {
        **config["cacheProtocol"][cache_mode],
        "namespace": (
            sample["sampleId"] if cache_mode == "COLD" else sample["scenarioId"]
        ),
    }
    packet: dict[str, Any] = {
        "case": case,
        "cacheProtocol": cache_protocol,
        "operation": operation,
        "startProbe": "INPUT_REVISION_ACCEPTED",
        "endProbe": "PUBLISHED_OFFICE_VERIFIED",
        "workerContract": "FRESH_NO_HISTORY_HASH_BOUND_RECEIPT",
    }
    if prepared_input is not None:
        packet["preparedInput"] = prepared_input
    packet_sha256 = _sha256_bytes(_canonical_json_bytes(packet))
    base_sha256 = _sha256_bytes(str(config["baselineCommit"]).encode("utf-8"))
    sample_id = str(sample["sampleId"])
    action_id = f"action-{sample_id}"
    run_id = f"run-{sample_id}"
    action = {
        "contract": "ai-sow-pipeline-benchmark-action-v1",
        "hostProtocol": "EXTERNAL_FRESH_WORKER",
        "runtimeDependency": "NONE",
        "actionId": action_id,
        "runId": run_id,
        "sampleId": sample_id,
        "scenarioId": sample["scenarioId"],
        "scenarioClass": sample["scenarioClass"],
        "cacheMode": sample["cacheMode"],
        "cacheProtocol": cache_protocol,
        "repetition": sample["repetition"],
        "modelProfileId": config["modelProfileId"],
        "model": config["model"],
        "reasoningEffort": config["reasoningEffort"],
        "operation": operation,
        "casePath": sample["casePath"],
        "packet": packet,
        "bindings": {
            "environmentSha256": config["environmentSha256"],
            "implementationSha256": config["implementationSha256"],
            "inputSha256": sample["caseSha256"],
            "packetSha256": packet_sha256,
            "baseSha256": base_sha256,
            "cacheProtocolSha256": _sha256_bytes(
                _canonical_json_bytes(cache_protocol)
            ),
        },
        "requiredProbes": {
            "start": "INPUT_REVISION_ACCEPTED",
            "successEnd": "PUBLISHED_OFFICE_VERIFIED",
            "blockedEnd": "INPUT_GAP_REPORTED",
        },
        "instructions": [
            "由宿主启动一个无历史 fresh worker；不要把既有对话传给 worker。",
            (
                "项目输入 revision 已由公开 prepare 接受；worker 从 preparedInput.prepareOutcome 指定的 outcome 继续，"
                "不得重新建档或重新运行 prepare。"
                if prepared_input is not None
                else "worker 仅按当前安装插件公开 generate Skill 推进 case，不调用本 benchmark runner 代替业务流程。"
            ),
            "宿主记录模型、控制面、工具与 Office 的实际耗时和 token；不可取得的 reasoning token 写 null。",
            "返回 ACTION、STAGE、RUN 粒度的签名 ModelExecutionReceipt，不保存来源正文、完整工具输出或本机绝对路径。",
        ],
    }
    if prepared_input is not None and project_root is not None:
        action["projectRoot"] = str(project_root.resolve())
        action["preparedInput"] = prepared_input
    return action


def _verify_receipt(receipt: dict[str, Any], state: dict[str, Any]) -> None:
    _validate_schema("model-execution-receipt.schema.json", receipt)
    signature = receipt["signature"]
    unsigned = dict(receipt)
    unsigned.pop("signature", None)
    actual = _sha256_bytes(_canonical_json_bytes(unsigned))
    if signature["payloadSha256"] != actual:
        raise ProtocolError("RECEIPT_SIGNATURE_INVALID", "receipt payload hash 不匹配。")
    active = state.get("activeAction")
    if not isinstance(active, dict):
        raise ProtocolError("NO_ACTIVE_ACTION", "当前没有可接收 receipt 的 action。")
    exact_fields = (
        "actionId",
        "runId",
        "sampleId",
        "scenarioId",
        "repetition",
        "cacheMode",
        "modelProfileId",
        "model",
        "reasoningEffort",
    )
    for field in exact_fields:
        if receipt.get(field) != active.get(field):
            raise ProtocolError(
                "RECEIPT_BINDING_MISMATCH",
                f"receipt 的 {field} 未绑定当前 action。",
            )
    if receipt.get("bindings") != active.get("bindings"):
        raise ProtocolError("RECEIPT_BINDING_MISMATCH", "receipt hash bindings 不匹配。")
    if receipt["usage"]["accountingMode"] != state["config"]["accountingMode"]:
        raise ProtocolError("ACCOUNTING_MODE_MISMATCH", "receipt accounting mode 已漂移。")


def _total_tokens(receipt: dict[str, Any]) -> int:
    usage = receipt["usage"]
    reasoning = usage["reasoningTokens"]
    return int(
        usage["inputTokens"]
        + usage["outputTokens"]
        + (reasoning if isinstance(reasoning, int) else 0)
        + usage["controlPlaneTokens"]
        + usage["toolContextTokens"]
    )


def assess_receipt(
    receipt: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    """Mechanically derive receipt usability without weakening semantic outcome."""

    assessed = deepcopy(receipt)
    granularity = str(assessed["granularity"])
    if granularity == "STAGE" and "stageBudgets" in policy:
        budget = policy["stageBudgets"].get(str(assessed["stage"]))
        if budget is None:
            raise ProtocolError(
                "RECEIPT_STAGE_BUDGET_MISSING",
                "STAGE receipt 未绑定 policy 中的已知 stage budget。",
            )
    elif granularity == "RUN" and "stageBudgets" in policy:
        budget = None
    else:
        budget = policy["actionBudget"]
    hard = policy["hardLimits"]
    wall_passed = budget is None or (
        assessed["timing"]["totalMilliseconds"] <= budget["maxWallMilliseconds"]
    )
    token_passed = budget is None or _total_tokens(assessed) <= budget["maxTotalTokens"]
    work = assessed["work"]
    no_waste_checks = [work["failures"] == 0, work["retries"] == 0]
    if granularity == "ACTION" or "stageBudgets" not in policy:
        no_waste_checks.extend(
            (
                work["hydrationRounds"] <= hard["maxHydrationRoundsPerAction"],
                work["modelAttempts"] <= hard["maxExecutionAttemptsPerShard"],
                work["repairWaves"]
                <= hard["maxSemanticRepairRoundsPerProposition"],
                work["adjudications"]
                <= hard["maxAdjudicationsPerProposition"],
                work["rereviews"] <= hard["maxReviewReshardDepth"],
                work["actionAttempts"]
                <= hard["maxPhysicalShardsPerLogicalTheme"],
            )
        )
    no_waste = all(no_waste_checks)
    outcome = assessed["outcome"]
    outcome["wallBudgetPassed"] = wall_passed
    outcome["tokenBudgetPassed"] = token_passed
    outcome["noWasteAmplification"] = no_waste
    outcome["usable"] = bool(
        outcome["semanticCorrectnessPassed"] and wall_passed and token_passed and no_waste
    )
    if outcome["usable"]:
        outcome["code"] = None
    elif outcome["semanticCorrectnessPassed"]:
        outcome["code"] = "MODEL_EFFICIENCY_FAILED"
    unsigned = dict(assessed)
    unsigned.pop("signature", None)
    assessed["signature"] = {
        "algorithm": "SHA256",
        "payloadSha256": _sha256_bytes(_canonical_json_bytes(unsigned)),
    }
    return assessed


def _require_mechanical_outcome(
    receipt: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    assessed = assess_receipt(receipt, policy)
    if receipt["outcome"] != assessed["outcome"]:
        raise ProtocolError(
            "RECEIPT_OUTCOME_ASSESSMENT_MISMATCH",
            "receipt 自报 outcome 与机械预算、失败和重试评估不一致。",
        )
    return assessed


def _derive_classified_receipt(
    failure: dict[str, Any],
    *,
    granularity: str,
    stage: str,
    action_id: str | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    derived = deepcopy(failure)
    derived["receiptId"] = (
        f"{failure['receiptId']}-classified-{granularity.lower()}"
    )
    derived["granularity"] = granularity
    derived["stage"] = stage
    derived["actionId"] = action_id
    return assess_receipt(derived, policy)


def _baseline_init(arguments: argparse.Namespace) -> int:
    state_dir = Path(arguments.state_dir)
    if _state_path(state_dir).exists():
        raise ProtocolError("SESSION_EXISTS", "目标 benchmark session 已存在。")
    cases = _load_cases(Path(arguments.scenario_root))
    tools = _parse_tool_versions(arguments.tool_version)
    policy = _read_json(Path(arguments.policy))
    _validate_schema("model-efficiency-policy.schema.json", policy)
    state = {
        "contract": "ai-sow-pipeline-benchmark-session-v1",
        "status": "READY",
        "config": {
            "baselineCommit": arguments.baseline_commit,
            "implementationSha256": arguments.implementation_sha256,
            "environmentSha256": arguments.environment_sha256,
            "modelProfileId": arguments.model_profile_id,
            "model": arguments.model,
            "reasoningEffort": arguments.reasoning_effort,
            "accountingMode": arguments.accounting_mode,
            "cacheProtocol": deepcopy(CACHE_PROTOCOL),
            "toolVersions": tools,
            "office": {
                "name": "LibreOffice",
                "version": arguments.office_version,
                "binarySha256": arguments.office_binary_sha256,
            },
            "maxConcurrency": arguments.max_concurrency,
            "repetitionsPerScenario": arguments.runs,
            "receiptAssessmentPolicy": {
                "actionBudget": deepcopy(policy["actionBudget"]),
                "stageBudgets": deepcopy(policy["stageBudgets"]),
                "hardLimits": deepcopy(policy["hardLimits"]),
            },
            "receiptAssessmentPolicySha256": _sha256_bytes(
                _canonical_json_bytes(
                    {
                        "actionBudget": policy["actionBudget"],
                        "stageBudgets": policy["stageBudgets"],
                        "hardLimits": policy["hardLimits"],
                    }
                )
            ),
        },
        "scenarios": [
            {key: case[key] for key in ("scenarioId", "class", "casePath", "caseSha256")}
            for case in cases
        ],
        "queue": _queue(cases, arguments.runs),
        "cursor": 0,
        "activeAction": None,
        "completedSamples": [],
        "receiptIndex": [],
        "seenReceiptSha256s": [],
    }
    _save_state(state_dir, state)
    _emit(
        {
            "status": "READY",
            "hostProtocol": "EXTERNAL_FRESH_WORKER",
            "runtimeDependency": "NONE",
            "sampleCount": len(state["queue"]),
        }
    )
    return 0


def _next_action(arguments: argparse.Namespace) -> int:
    state_dir = Path(arguments.state_dir)
    state = _load_state(state_dir)
    if state["status"] == "FAILED_UNTRIAGED":
        _emit(
            {
                "status": "FAILED_UNTRIAGED",
                "code": "BENCHMARK_FAILURE_UNCLASSIFIED",
                "message": "必须先完成根因分类；禁止发放下一 model action。",
            }
        )
        return 2
    if state["status"] == "COMPLETE":
        _emit({"status": "COMPLETE", "code": "NO_MORE_ACTIONS"})
        return 0
    active = state.get("activeAction")
    if isinstance(active, dict):
        response = dict(active)
        response.pop("partialReceipts", None)
        _emit(response)
        return 0
    cursor = int(state["cursor"])
    queue = state["queue"]
    if cursor >= len(queue):
        state["status"] = "COMPLETE"
        _save_state(state_dir, state)
        _emit({"status": "COMPLETE", "code": "NO_MORE_ACTIONS"})
        return 0
    project_root: Path | None = None
    prepared_input: dict[str, Any] | None = None
    if arguments.project_root:
        project_root = Path(arguments.project_root).resolve()
        case_path = PLUGIN_ROOT / queue[cursor]["casePath"]
        materialized = materialize_case_project(case_path, project_root)
        prepared_input = _run_public_prepare(
            project_root=project_root,
            office_bin=arguments.office_bin,
        )
        prepared_input["requestSha256"] = materialized["requestSha256"]
        expected_class = queue[cursor]["scenarioClass"]
        actual_outcome = prepared_input["prepareOutcome"]["outcome"]
        if expected_class == "SUCCESS" and actual_outcome != "ACTIVE":
            raise ProtocolError(
                "BASELINE_PREPARE_UNEXPECTED",
                f"成功场景 start 返回 {actual_outcome}，不能启动模型。",
            )
    active = _action_for(
        state,
        queue[cursor],
        project_root=project_root,
        prepared_input=prepared_input,
    )
    active["partialReceipts"] = []
    state["activeAction"] = active
    state["status"] = "ACTION_ISSUED"
    _save_state(state_dir, state)
    response = dict(active)
    response.pop("partialReceipts", None)
    _emit(response)
    return 0


def _record_usage(arguments: argparse.Namespace) -> int:
    state_dir = Path(arguments.state_dir)
    state = _load_state(state_dir)
    receipt_path = Path(arguments.receipt)
    receipt = _read_json(receipt_path)
    receipt_sha256 = _sha256_bytes(_canonical_json_bytes(receipt))
    if state["status"] == "FAILED_UNTRIAGED":
        code = (
            "BLIND_RETRY_FORBIDDEN"
            if receipt_sha256 in state["seenReceiptSha256s"]
            else "BENCHMARK_FAILURE_UNCLASSIFIED"
        )
        _emit(
            {
                "status": "FAILED_UNTRIAGED",
                "code": code,
                "message": "失败尚未分类，不能记录新结果或原样重试。",
            }
        )
        return 2
    _verify_receipt(receipt, state)
    receipt = _require_mechanical_outcome(
        receipt, state["config"]["receiptAssessmentPolicy"]
    )
    receipt_sha256 = _sha256_bytes(_canonical_json_bytes(receipt))
    if receipt_sha256 in state["seenReceiptSha256s"]:
        raise ProtocolError("DUPLICATE_RECEIPT", "同一 receipt 已记录。")
    state["seenReceiptSha256s"].append(receipt_sha256)
    outcome = receipt["outcome"]
    if (
        not outcome["semanticCorrectnessPassed"]
        or not outcome["usable"]
        or receipt["work"]["failures"] > 0
    ):
        _write_json(state_dir / "failure-receipt.json", receipt)
        state["status"] = "FAILED_UNTRIAGED"
        state["firstFailedReceiptSha256"] = receipt_sha256
        _save_state(state_dir, state)
        _emit(
            {
                "status": "FAILED_UNTRIAGED",
                "code": outcome.get("code") or "MODEL_EXECUTION_FAILED",
                "receiptSha256": receipt_sha256,
            }
        )
        return 2
    receipt_name = f"{receipt['receiptId']}.json"
    stored_path = state_dir / "receipts" / receipt_name
    active = state["activeAction"]
    if receipt["granularity"] == "RUN":
        prospective_receipts = {receipt_sha256: receipt}
        for item in active["partialReceipts"]:
            existing_path = state_dir / "receipts" / item["name"]
            existing = _read_json(existing_path)
            if _sha256_file(existing_path) != item["sha256"]:
                raise ProtocolError(
                    "RECEIPT_HASH_MISMATCH",
                    f"已记录 receipt 漂移：{item['name']}",
                )
            prospective_receipts[str(item["sha256"])] = existing
        sample = deepcopy(state["queue"][state["cursor"]])
        sample.update(
            {
                "status": "COMPLETED",
                "receiptSha256s": [
                    item["sha256"] for item in active["partialReceipts"]
                ]
                + [receipt_sha256],
            }
        )
        elapsed_field = (
            "readyForApprovalMilliseconds"
            if sample["scenarioClass"] == "SUCCESS"
            else "timeToInputGapMilliseconds"
        )
        sample[elapsed_field] = receipt["timing"]["totalMilliseconds"]
        _receipt_groups(sample, prospective_receipts)
    _write_json(stored_path, receipt)
    stored_sha256 = _sha256_file(stored_path)
    active["partialReceipts"].append(
        {
            "name": receipt_name,
            "sha256": stored_sha256,
            "granularity": receipt["granularity"],
        }
    )
    state["receiptIndex"].append(
        {"name": receipt_name, "sha256": stored_sha256}
    )
    if receipt["granularity"] != "RUN":
        state["status"] = "ACTION_ISSUED"
        _save_state(state_dir, state)
        _emit(
            {
                "status": "PARTIAL_RECEIPT_RECORDED",
                "granularity": receipt["granularity"],
                "receiptSha256": stored_sha256,
            }
        )
        return 0
    granularities = {item["granularity"] for item in active["partialReceipts"]}
    sample = state["queue"][state["cursor"]]
    elapsed = receipt["timing"]["totalMilliseconds"]
    completed = {
        "sampleId": sample["sampleId"],
        "scenarioId": sample["scenarioId"],
        "scenarioClass": sample["scenarioClass"],
        "cacheMode": sample["cacheMode"],
        "repetition": sample["repetition"],
        "status": "COMPLETED",
        "receiptSha256s": [item["sha256"] for item in active["partialReceipts"]],
        "failureCount": 0,
    }
    if sample["scenarioClass"] == "SUCCESS":
        completed["readyForApprovalMilliseconds"] = elapsed
    else:
        completed["timeToInputGapMilliseconds"] = elapsed
    completed["observedGranularities"] = sorted(granularities)
    state["completedSamples"].append(completed)
    state["cursor"] += 1
    state["activeAction"] = None
    state["status"] = (
        "COMPLETE" if state["cursor"] >= len(state["queue"]) else "READY"
    )
    _save_state(state_dir, state)
    _emit(
        {
            "status": state["status"],
            "sampleId": completed["sampleId"],
            "receiptSha256": stored_sha256,
        }
    )
    return 0


def _classify_failure(arguments: argparse.Namespace) -> int:
    state_dir = Path(arguments.state_dir)
    state = _load_state(state_dir)
    if state["status"] != "FAILED_UNTRIAGED":
        raise ProtocolError("NO_UNTRIAGED_FAILURE", "当前 session 没有待分类失败。")
    failure_path = state_dir / "failure-receipt.json"
    if not failure_path.is_file():
        raise ProtocolError("FAILURE_RECEIPT_MISSING", "失败哨兵缺少原始 receipt。")
    incident = _read_json(Path(arguments.incident))
    _validate_schema("model-efficiency-incident.schema.json", incident)
    failure_sha256 = _sha256_file(failure_path)
    if incident["firstFailedReceiptSha256"] != failure_sha256:
        raise ProtocolError(
            "INCIDENT_BINDING_MISMATCH",
            "incident 未绑定当前首次失败 receipt。",
        )
    classification = incident["classification"]
    if arguments.resume_same_sample and classification not in {
        "ENVIRONMENT_FAILURE",
        "TEST_HARNESS_DEFECT",
    }:
        raise ProtocolError(
            "RESUME_CLASSIFICATION_FORBIDDEN",
            "只有已证明的环境或 harness 故障可原位恢复同一 sample。",
        )
    if arguments.resume_same_sample and arguments.retain_product_failure:
        raise ProtocolError(
            "CLASSIFICATION_ACTION_CONFLICT",
            "同一次分类不能同时恢复并保留为产品失败。",
        )
    if not arguments.resume_same_sample and not arguments.retain_product_failure:
        raise ProtocolError(
            "CLASSIFIED_FAILURE_REQUIRES_DECISION",
            "产品或未分类失败不能自动推进；需显式处置决定。",
        )
    _write_json(state_dir / "failure-incident.json", incident)
    state["failureClassification"] = classification
    state["failureIncidentSha256"] = _sha256_file(state_dir / "failure-incident.json")
    active = state.get("activeAction")
    if not isinstance(active, dict):
        raise ProtocolError("NO_ACTIVE_ACTION", "失败状态未保留原 action。")
    if arguments.retain_product_failure:
        if classification != "PLUGIN_DEFECT":
            raise ProtocolError(
                "PRODUCT_FAILURE_CLASSIFICATION_REQUIRED",
                "只有 PLUGIN_DEFECT 可作为冻结基线的产品失败保留。",
            )
        if not arguments.decision:
            raise ProtocolError(
                "OPTIMIZATION_DECISION_REQUIRED",
                "保留产品失败前必须提供系统级优化 decision。",
            )
        decision = _read_json(Path(arguments.decision))
        _validate_schema("model-optimization-decision.schema.json", decision)
        incident_sha256 = _sha256_file(state_dir / "failure-incident.json")
        if decision["incidentSha256"] != incident_sha256:
            raise ProtocolError(
                "DECISION_BINDING_MISMATCH",
                "optimization decision 未绑定当前 incident。",
            )
        option_ids = {option["optionId"] for option in decision["options"]}
        if decision["selectedOptionId"] not in option_ids:
            raise ProtocolError(
                "DECISION_SELECTION_INVALID",
                "selectedOptionId 不在 decision options 中。",
            )
        _write_json(state_dir / "failure-decision.json", decision)
        failure = _read_json(failure_path)
        failure_stage = (
            failure["stage"] if failure["stage"] != "RUN" else "CONTROL_PLANE"
        )
        stored_sha256s: list[str] = []
        for granularity, stage in (
            ("ACTION", failure_stage),
            ("STAGE", failure_stage),
            ("RUN", "RUN"),
        ):
            derived = _derive_classified_receipt(
                failure,
                granularity=granularity,
                stage=stage,
                action_id=(
                    active["actionId"] if granularity == "ACTION" else None
                ),
                policy=state["config"]["receiptAssessmentPolicy"],
            )
            _validate_schema("model-execution-receipt.schema.json", derived)
            receipt_name = f"{derived['receiptId']}.json"
            stored_receipt = state_dir / "receipts" / receipt_name
            _write_json(stored_receipt, derived)
            stored_sha256 = _sha256_file(stored_receipt)
            stored_sha256s.append(stored_sha256)
            state["receiptIndex"].append(
                {"name": receipt_name, "sha256": stored_sha256}
            )
        sample = state["queue"][state["cursor"]]
        state["completedSamples"].append(
            {
                "sampleId": sample["sampleId"],
                "scenarioId": sample["scenarioId"],
                "scenarioClass": sample["scenarioClass"],
                "cacheMode": sample["cacheMode"],
                "repetition": sample["repetition"],
                "status": "FAILED_CLASSIFIED",
                "receiptSha256s": stored_sha256s,
                "failureCount": 1,
                "timeToFailureMilliseconds": failure["timing"]["totalMilliseconds"],
                "observedGranularities": ["ACTION", "RUN", "STAGE"],
            }
        )
        state["cursor"] += 1
        state["activeAction"] = None
        state["status"] = (
            "COMPLETE" if state["cursor"] >= len(state["queue"]) else "READY"
        )
        state["failureDecisionSha256"] = _sha256_file(
            state_dir / "failure-decision.json"
        )
        _save_state(state_dir, state)
        _emit(
            {
                "status": state["status"],
                "sampleId": sample["sampleId"],
                "classification": classification,
                "incidentSha256": incident_sha256,
                "decisionSha256": state["failureDecisionSha256"],
            }
        )
        return 0
    state["status"] = "READY_TO_RESUME"
    _save_state(state_dir, state)
    _emit(
        {
            "status": "READY_TO_RESUME",
            "sampleId": active["sampleId"],
            "actionId": active["actionId"],
            "bindings": active["bindings"],
            "incidentSha256": state["failureIncidentSha256"],
        }
    )
    return 0


def _percentile_nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(percentile * len(ordered) + 0.999999) - 1))
    return float(ordered[index])


def _summaries(samples: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = sorted({(sample["scenarioId"], sample["cacheMode"]) for sample in samples})
    summaries: list[dict[str, Any]] = []
    for scenario_id, cache_mode in keys:
        selected = [
            sample
            for sample in samples
            if sample["scenarioId"] == scenario_id and sample["cacheMode"] == cache_mode
        ]
        values = [
            float(
                sample.get(
                    "timeToFailureMilliseconds",
                    sample.get(
                        "readyForApprovalMilliseconds",
                        sample.get("timeToInputGapMilliseconds", 0),
                    ),
                )
            )
            for sample in selected
        ]
        failures = sum(sample["status"] == "FAILED_CLASSIFIED" for sample in selected)
        summaries.append(
            {
                "scenarioId": scenario_id,
                "cacheMode": cache_mode,
                "sampleCount": len(selected),
                "p50Milliseconds": float(statistics.median(values)),
                "rangeMilliseconds": [min(values), max(values)],
                "p95Milliseconds": (
                    _percentile_nearest_rank(values, 0.95) if len(values) >= 20 else None
                ),
                "failureRate": failures / len(selected),
            }
        )
    return summaries


def _finalize(arguments: argparse.Namespace) -> int:
    state_dir = Path(arguments.state_dir)
    state = _load_state(state_dir)
    if state["status"] != "COMPLETE":
        raise ProtocolError("SESSION_INCOMPLETE", "全部 sample 完成前不能 finalize。")
    samples: list[dict[str, Any]] = []
    for completed in state["completedSamples"]:
        sample = dict(completed)
        granularities = set(sample.pop("observedGranularities", []))
        if granularities != {
            "ACTION",
            "STAGE",
            "RUN",
        }:
            raise ProtocolError(
                "RECEIPT_GRANULARITY_INCOMPLETE",
                f"{sample['sampleId']} 缺少 ACTION/STAGE/RUN 粒度收据。",
            )
        samples.append(sample)
    manifest_path = Path(arguments.manifest)
    receipt_dir = manifest_path.parent / "receipts"
    receipt_index: list[dict[str, str]] = []
    for index in state["receiptIndex"]:
        source = state_dir / "receipts" / index["name"]
        target = receipt_dir / index["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        receipt_index.append(
            {"path": _relative_to_plugin(target), "sha256": _sha256_file(target)}
        )
    summaries = _summaries(samples)
    config = state["config"]
    manifest = {
        "contract": "ai-sow-pipeline-benchmark-v1",
        "baselineCommit": config["baselineCommit"],
        "implementationSha256": config["implementationSha256"],
        "execution": {
            "hostProtocol": "EXTERNAL_FRESH_WORKER",
            "runtimeDependency": "NONE",
            "modelProfileId": config["modelProfileId"],
            "model": config["model"],
            "reasoningEffort": config["reasoningEffort"],
            "environmentSha256": config["environmentSha256"],
            "toolVersions": config["toolVersions"],
            "maxConcurrency": config["maxConcurrency"],
            "office": config["office"],
            "cacheModes": ["COLD", "WARM"],
            "cacheProtocol": config["cacheProtocol"],
            "accountingMode": config["accountingMode"],
            "repetitionsPerScenario": config["repetitionsPerScenario"],
        },
        "comparisonInterval": {
            "startProbe": "INPUT_REVISION_ACCEPTED",
            "baselineEndProbe": "PUBLISHED_OFFICE_VERIFIED",
            "candidateEndProbe": "AWAITING_APPROVAL",
            "includedBaselinePublishSegments": [
                "RENDER",
                "OFFICE_RECALCULATION",
                "OFFICE_REREAD",
            ],
            "excludedAfterApprovalSegments": [
                "USER_WAIT",
                "ATOMIC_PROMOTE",
                "CURRENT_SWAP",
            ],
        },
        "scenarios": state["scenarios"],
        "samples": samples,
        "receiptIndex": receipt_index,
        "summaries": summaries,
        "summarySha256": _sha256_bytes(_canonical_json_bytes(summaries)),
    }
    _validate_schema("pipeline-benchmark.schema.json", manifest)
    _write_json(manifest_path, manifest)
    _emit(
        {
            "status": "FINALIZED",
            "manifest": _relative_to_plugin(manifest_path),
            "manifestSha256": _sha256_file(manifest_path),
        }
    )
    return 0


def _manifest_reference(manifest_path: Path, relative_path: str) -> Path:
    candidates = (PLUGIN_ROOT / relative_path, manifest_path.parent / relative_path)
    matches = [candidate for candidate in candidates if candidate.is_file()]
    if not matches:
        raise ProtocolError(
            "MANIFEST_REFERENCE_MISSING", f"manifest 引用不存在：{relative_path}"
        )
    return matches[0]


def _validated_manifest_bundle(
    manifest_path: Path,
    policy: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if policy is None:
        policy = _read_json(DEFAULT_POLICY_PATH)
        _validate_schema("model-efficiency-policy.schema.json", policy)
    manifest = _read_json(manifest_path)
    _validate_schema("pipeline-benchmark.schema.json", manifest)
    if manifest["summarySha256"] != _sha256_bytes(
        _canonical_json_bytes(manifest["summaries"])
    ):
        raise ProtocolError("SUMMARY_HASH_MISMATCH", "summaries hash 不匹配。")
    scenario_by_id: dict[str, dict[str, Any]] = {}
    for scenario in manifest["scenarios"]:
        scenario_id = str(scenario["scenarioId"])
        if scenario_id in scenario_by_id:
            raise ProtocolError(
                "SCENARIO_DUPLICATE", f"scenarioId 重复：{scenario_id}"
            )
        scenario_by_id[scenario_id] = scenario
        case_path = _manifest_reference(manifest_path, scenario["casePath"])
        if _sha256_file(case_path) != scenario["caseSha256"]:
            raise ProtocolError("CASE_HASH_MISMATCH", f"case 已漂移：{scenario['scenarioId']}")
    indexed_hashes: set[str] = set()
    receipts: dict[str, dict[str, Any]] = {}
    receipt_schema = _schema("model-execution-receipt.schema.json")
    for index in manifest["receiptIndex"]:
        receipt_path = _manifest_reference(manifest_path, index["path"])
        actual = _sha256_file(receipt_path)
        if actual != index["sha256"]:
            raise ProtocolError("RECEIPT_HASH_MISMATCH", f"receipt 已漂移：{receipt_path.name}")
        receipt = _read_json(receipt_path)
        try:
            jsonschema.Draft202012Validator(receipt_schema).validate(receipt)
        except jsonschema.ValidationError as exc:
            raise ProtocolError("RECEIPT_SCHEMA_INVALID", exc.message) from exc
        unsigned = dict(receipt)
        signature = unsigned.pop("signature")
        if signature["payloadSha256"] != _sha256_bytes(_canonical_json_bytes(unsigned)):
            raise ProtocolError("RECEIPT_SIGNATURE_INVALID", f"receipt 签名错误：{receipt_path.name}")
        if receipt["usage"]["accountingMode"] != manifest["execution"]["accountingMode"]:
            raise ProtocolError("ACCOUNTING_MODE_MISMATCH", f"receipt accounting 漂移：{receipt_path.name}")
        if receipt["bindings"]["implementationSha256"] != manifest["implementationSha256"]:
            raise ProtocolError("IMPLEMENTATION_HASH_MISMATCH", f"receipt implementation 漂移：{receipt_path.name}")
        if receipt["bindings"]["environmentSha256"] != manifest["execution"]["environmentSha256"]:
            raise ProtocolError(
                "RECEIPT_ENVIRONMENT_HASH_MISMATCH",
                f"receipt environment 漂移：{receipt_path.name}",
            )
        _require_mechanical_outcome(receipt, policy)
        if actual in receipts:
            raise ProtocolError("RECEIPT_INDEX_DUPLICATE", f"receipt 重复索引：{receipt_path.name}")
        receipts[actual] = receipt
        indexed_hashes.add(actual)
    referenced_hashes: set[str] = set()
    sample_ids: set[str] = set()
    for sample in manifest["samples"]:
        sample_id = str(sample["sampleId"])
        if sample_id in sample_ids:
            raise ProtocolError("SAMPLE_DUPLICATE", f"sampleId 重复：{sample_id}")
        sample_ids.add(sample_id)
        scenario = scenario_by_id.get(str(sample["scenarioId"]))
        if scenario is None or sample["scenarioClass"] != scenario["class"]:
            raise ProtocolError(
                "SAMPLE_SCENARIO_BINDING_MISMATCH",
                f"sample 未绑定声明场景：{sample_id}",
            )
        sample_hashes = set(sample["receiptSha256s"])
        if len(sample_hashes) != len(sample["receiptSha256s"]):
            raise ProtocolError(
                "RECEIPT_SAMPLE_DUPLICATE", f"sample 重复引用 receipt：{sample_id}"
            )
        if not sample_hashes.issubset(indexed_hashes):
            raise ProtocolError("RECEIPT_INDEX_INCOMPLETE", f"sample 收据未索引：{sample['sampleId']}")
        granularities: set[str] = set()
        cache_protocol = {
            **manifest["execution"]["cacheProtocol"][sample["cacheMode"]],
            "namespace": (
                sample_id if sample["cacheMode"] == "COLD" else sample["scenarioId"]
            ),
        }
        expected_cache_sha256 = _sha256_bytes(
            _canonical_json_bytes(cache_protocol)
        )
        expected_base_sha256 = _sha256_bytes(
            str(manifest["baselineCommit"]).encode("utf-8")
        )
        for receipt_hash in sample["receiptSha256s"]:
            receipt = receipts[receipt_hash]
            for field in ("sampleId", "scenarioId", "cacheMode", "repetition"):
                if receipt[field] != sample[field]:
                    raise ProtocolError(
                        "RECEIPT_SAMPLE_BINDING_MISMATCH",
                        f"receipt 未绑定 sample 字段 {field}：{sample_id}",
                    )
            if receipt["modelProfileId"] != manifest["execution"]["modelProfileId"]:
                raise ProtocolError("MODEL_PROFILE_MISMATCH", f"receipt model profile 漂移：{sample_id}")
            if receipt["model"] != manifest["execution"]["model"]:
                raise ProtocolError("MODEL_PROFILE_MISMATCH", f"receipt model 漂移：{sample_id}")
            if receipt["reasoningEffort"] != manifest["execution"]["reasoningEffort"]:
                raise ProtocolError("MODEL_PROFILE_MISMATCH", f"receipt reasoning 漂移：{sample_id}")
            if receipt["bindings"]["inputSha256"] != scenario["caseSha256"]:
                raise ProtocolError(
                    "RECEIPT_INPUT_HASH_MISMATCH",
                    f"receipt input 未绑定 case：{sample_id}",
                )
            if receipt["bindings"]["cacheProtocolSha256"] != expected_cache_sha256:
                raise ProtocolError(
                    "RECEIPT_CACHE_PROTOCOL_HASH_MISMATCH",
                    f"receipt cache protocol 未绑定 sample：{sample_id}",
                )
            if receipt["bindings"]["baseSha256"] != expected_base_sha256:
                raise ProtocolError(
                    "RECEIPT_BASE_HASH_MISMATCH",
                    f"receipt base 未绑定 baseline commit：{sample_id}",
                )
            granularities.add(str(receipt["granularity"]))
        if granularities != {"ACTION", "STAGE", "RUN"}:
            raise ProtocolError(
                "RECEIPT_GRANULARITY_INCOMPLETE",
                f"{sample_id} 缺少 ACTION/STAGE/RUN 粒度收据。",
            )
        referenced_hashes.update(sample_hashes)
    if referenced_hashes != indexed_hashes:
        raise ProtocolError("RECEIPT_INDEX_ORPHANED", "receiptIndex 含未被 sample 引用的收据。")
    if not scenario_by_id:
        raise ProtocolError("SCENARIOS_MISSING", "manifest 缺少场景。")
    return manifest, receipts


def _sample_matrix(
    manifest: dict[str, Any],
) -> tuple[dict[tuple[str, str, int], dict[str, Any]], str]:
    expected = {
        (scenario_id, cache_mode, repetition)
        for scenario_id in SUCCESS_SCENARIOS
        for cache_mode in ("COLD", "WARM")
        for repetition in range(1, 6)
    } | {
        (scenario_id, cache_mode, 1)
        for scenario_id, cache_mode in BLOCKED_CACHE_MODES.items()
    }
    by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    for sample in manifest["samples"]:
        key = (
            str(sample["scenarioId"]),
            str(sample["cacheMode"]),
            int(sample["repetition"]),
        )
        if key in by_key:
            raise ProtocolError("SAMPLE_MATRIX_DUPLICATE", f"sample matrix 重复：{key}")
        by_key[key] = sample
    if set(by_key) != expected:
        raise ProtocolError("SAMPLE_MATRIX_INVALID", "manifest 不满足精确 32 样本矩阵。")
    scenario_classes = {
        str(item["scenarioId"]): str(item["class"])
        for item in manifest["scenarios"]
    }
    if scenario_classes != {
        **{scenario_id: "SUCCESS" for scenario_id in SUCCESS_SCENARIOS},
        **{scenario_id: "BLOCKED" for scenario_id in BLOCKED_CACHE_MODES},
    }:
        raise ProtocolError("SCENARIO_MATRIX_INVALID", "scenario class 集合不精确。")
    matrix = {
        "samples": [list(key) for key in sorted(expected)],
        "scenarios": [
            {
                "scenarioId": item["scenarioId"],
                "class": item["class"],
                "caseSha256": item["caseSha256"],
            }
            for item in sorted(
                manifest["scenarios"], key=lambda value: value["scenarioId"]
            )
        ],
    }
    return by_key, _sha256_bytes(_canonical_json_bytes(matrix))


def _receipt_groups(
    sample: dict[str, Any], receipts: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    selected = [receipts[value] for value in sample["receiptSha256s"]]
    run_receipts = [item for item in selected if item["granularity"] == "RUN"]
    if len(run_receipts) != 1:
        raise ProtocolError(
            "RUN_RECEIPT_NOT_UNIQUE", f"{sample['sampleId']} 必须精确包含一份 RUN 收据。"
        )
    if run_receipts[0]["stage"] != "RUN":
        raise ProtocolError(
            "RECEIPT_GRANULARITY_STAGE_MISMATCH",
            f"{sample['sampleId']} 的 RUN receipt 必须绑定 RUN stage。",
        )
    action_receipts = [item for item in selected if item["granularity"] == "ACTION"]
    stage_receipts = [item for item in selected if item["granularity"] == "STAGE"]
    stage_names = [str(item["stage"]) for item in stage_receipts]
    if len(stage_names) != len(set(stage_names)):
        raise ProtocolError(
            "STAGE_RECEIPT_NOT_UNIQUE",
            f"{sample['sampleId']} 的每个 stage 必须精确包含一份 STAGE 收据。",
        )
    if sample["status"] == "COMPLETED":
        if sample["scenarioClass"] == "SUCCESS":
            required_action_stages = SUCCESS_ACTION_STAGES
            required_receipt_stages = SUCCESS_RECEIPT_STAGES
        else:
            required_action_stages = BLOCKED_ACTION_STAGES
            required_receipt_stages = BLOCKED_RECEIPT_STAGES
        action_stages = {str(item["stage"]) for item in action_receipts}
        receipt_stages = {str(item["stage"]) for item in stage_receipts}
        if not required_action_stages <= action_stages:
            raise ProtocolError(
                "RECEIPT_ACTION_COVERAGE_INCOMPLETE",
                f"{sample['sampleId']} 缺少必需 ACTION stage receipt。",
            )
        if not required_receipt_stages <= receipt_stages:
            raise ProtocolError(
                "RECEIPT_STAGE_COVERAGE_INCOMPLETE",
                f"{sample['sampleId']} 缺少必需 STAGE receipt。",
            )
    stage_by_name = {str(item["stage"]): item for item in stage_receipts}
    orphan_action_stages = {
        str(item["stage"]) for item in action_receipts
    } - set(stage_by_name)
    if orphan_action_stages:
        raise ProtocolError(
            "RECEIPT_ACTION_STAGE_ORPHANED",
            f"{sample['sampleId']} 的 ACTION 缺少对应 STAGE receipt："
            + ", ".join(sorted(orphan_action_stages)),
        )
    for stage_name, stage_receipt in stage_by_name.items():
        actions = [
            item for item in action_receipts if str(item["stage"]) == stage_name
        ]
        for field in ADDITIVE_USAGE_FIELDS:
            if sum(int(item["usage"][field]) for item in actions) > int(
                stage_receipt["usage"][field]
            ):
                raise ProtocolError(
                    "RECEIPT_AGGREGATION_MISMATCH",
                    f"{sample['sampleId']} 的 ACTION {field} 超过 STAGE 聚合值。",
                )
        for field in ADDITIVE_WORK_FIELDS:
            if sum(int(item["work"][field]) for item in actions) > int(
                stage_receipt["work"][field]
            ):
                raise ProtocolError(
                    "RECEIPT_AGGREGATION_MISMATCH",
                    f"{sample['sampleId']} 的 ACTION {field} 超过 STAGE 聚合值。",
                )
        if actions and max(
            float(item["timing"]["totalMilliseconds"]) for item in actions
        ) > float(stage_receipt["timing"]["totalMilliseconds"]):
            raise ProtocolError(
                "RECEIPT_AGGREGATION_MISMATCH",
                f"{sample['sampleId']} 的 ACTION wall time 超过所属 STAGE。",
            )
    for group, fields in (
        ("usage", ADDITIVE_USAGE_FIELDS),
        ("timing", ADDITIVE_TIMING_FIELDS),
        ("work", ADDITIVE_WORK_FIELDS),
    ):
        for field in fields:
            expected = sum(float(item[group][field]) for item in stage_receipts)
            actual = float(run_receipts[0][group][field])
            if actual != expected:
                raise ProtocolError(
                    "RECEIPT_AGGREGATION_MISMATCH",
                    f"{sample['sampleId']} 的 RUN {group}.{field} 未精确聚合 STAGE 收据。",
                )
    stage_reasoning = [item["usage"]["reasoningTokens"] for item in stage_receipts]
    expected_reasoning = (
        None
        if any(value is None for value in stage_reasoning)
        else sum(int(value) for value in stage_reasoning)
    )
    if run_receipts[0]["usage"]["reasoningTokens"] != expected_reasoning:
        raise ProtocolError(
            "RECEIPT_AGGREGATION_MISMATCH",
            f"{sample['sampleId']} 的 RUN reasoningTokens 未精确聚合 STAGE 收据。",
        )
    if sample["status"] == "COMPLETED":
        elapsed_field = (
            "readyForApprovalMilliseconds"
            if sample["scenarioClass"] == "SUCCESS"
            else "timeToInputGapMilliseconds"
        )
        if float(sample[elapsed_field]) != float(
            run_receipts[0]["timing"]["totalMilliseconds"]
        ):
            raise ProtocolError(
                "RECEIPT_AGGREGATION_MISMATCH",
                f"{sample['sampleId']} 的 sample elapsed 未绑定 RUN wall time。",
            )
    return run_receipts[0], stage_receipts, selected


def _safe_ratio(numerator: float, denominator: float, code: str) -> float:
    if denominator <= 0:
        raise ProtocolError(code, "paired benchmark 分母必须大于零。")
    return float(numerator / denominator)


def _policy_evaluation_sha256(policy: dict[str, Any]) -> str:
    normalized = deepcopy(policy)
    gate = normalized["pairedBenchmarkGate"]
    gate.update(
        {
            "status": "REQUIRED_NOT_SATISFIED",
            "claimStatus": "FORBIDDEN_UNTIL_VALIDATED_MANIFESTS",
            "baselineManifest": None,
            "candidateManifest": None,
            "comparisonReceipt": None,
        }
    )
    return _sha256_bytes(_canonical_json_bytes(normalized))


def _validate_comparison_receipt(receipt: dict[str, Any]) -> None:
    _validate_schema("paired-benchmark-comparison.schema.json", receipt)
    failure_codes = sorted(
        key for key, passed in receipt["checks"].items() if not passed
    )
    if receipt["failureCodes"] != failure_codes:
        raise ProtocolError(
            "COMPARISON_FAILURE_CODES_INVALID",
            "failureCodes 必须精确等于 checks 中的失败项。",
        )
    expected_verdict = "PASS" if not failure_codes else "FAIL"
    if receipt["verdict"] != expected_verdict:
        raise ProtocolError(
            "COMPARISON_VERDICT_INVALID", "comparison verdict 与 checks 不一致。"
        )


def _evaluate_comparison(
    policy: dict[str, Any],
    baseline_path: Path,
    candidate_path: Path,
) -> dict[str, Any]:
    baseline, baseline_receipts = _validated_manifest_bundle(baseline_path, policy)
    candidate, candidate_receipts = _validated_manifest_bundle(candidate_path, policy)
    baseline_samples, baseline_matrix_sha256 = _sample_matrix(baseline)
    candidate_samples, candidate_matrix_sha256 = _sample_matrix(candidate)
    if baseline_matrix_sha256 != candidate_matrix_sha256:
        raise ProtocolError("SAMPLE_MATRIX_MISMATCH", "baseline/candidate 样本矩阵不一致。")
    baseline_profile = {
        field: baseline["execution"][field] for field in SAME_EXECUTION_PROFILE_FIELDS
    }
    candidate_profile = {
        field: candidate["execution"][field] for field in SAME_EXECUTION_PROFILE_FIELDS
    }
    if baseline_profile != candidate_profile:
        raise ProtocolError(
            "EXECUTION_PROFILE_MISMATCH", "baseline/candidate 执行配置不可配对。"
        )

    baseline_run_tokens = 0
    candidate_run_tokens = 0
    baseline_review_tokens = 0
    candidate_review_tokens = 0
    wall_ratios: list[float] = []
    post_review_ratios: list[float] = []
    all_usable = True
    all_samples_completed = True
    for key in sorted(baseline_samples):
        baseline_sample = baseline_samples[key]
        candidate_sample = candidate_samples[key]
        baseline_run, baseline_stages, baseline_selected = _receipt_groups(
            baseline_sample, baseline_receipts
        )
        candidate_run, candidate_stages, candidate_selected = _receipt_groups(
            candidate_sample, candidate_receipts
        )
        all_usable = all_usable and all(
            bool(item["outcome"]["usable"]) for item in baseline_selected
        )
        all_usable = all_usable and all(
            bool(item["outcome"]["usable"]) for item in candidate_selected
        )
        if (
            baseline_sample["status"] != "COMPLETED"
            or candidate_sample["status"] != "COMPLETED"
        ):
            all_samples_completed = False
            continue
        if key[0] not in SUCCESS_SCENARIOS:
            continue
        baseline_run_tokens += _total_tokens(baseline_run)
        candidate_run_tokens += _total_tokens(candidate_run)
        wall_ratios.append(
            _safe_ratio(
                float(candidate_sample["readyForApprovalMilliseconds"]),
                float(baseline_sample["readyForApprovalMilliseconds"]),
                "BASELINE_WALL_ZERO",
            )
        )
        baseline_post_review = sum(
            float(item["timing"]["totalMilliseconds"])
            for item in baseline_stages
            if item["stage"] in POST_REVIEW_STAGES
        )
        candidate_post_review = sum(
            float(item["timing"]["totalMilliseconds"])
            for item in candidate_stages
            if item["stage"] in POST_REVIEW_STAGES
        )
        post_review_ratios.append(
            _safe_ratio(
                candidate_post_review,
                baseline_post_review,
                "BASELINE_POST_REVIEW_ZERO",
            )
        )
        baseline_review_tokens += sum(
            _total_tokens(item)
            for item in baseline_stages
            if item["stage"] in REVIEW_STAGES
        )
        candidate_review_tokens += sum(
            _total_tokens(item)
            for item in candidate_stages
            if item["stage"] in REVIEW_STAGES
        )

    if all_usable and all_samples_completed:
        metrics: dict[str, float | None] = {
            "fullCompileTokenRatio": _safe_ratio(
                candidate_run_tokens, baseline_run_tokens, "BASELINE_TOKENS_ZERO"
            ),
            "fullCompileP50WallRatio": float(statistics.median(wall_ratios)),
            "postReviewP50WallRatio": float(statistics.median(post_review_ratios)),
            "reviewTokenRatio": _safe_ratio(
                candidate_review_tokens,
                baseline_review_tokens,
                "BASELINE_REVIEW_TOKENS_ZERO",
            ),
        }
    else:
        metrics = {
            "fullCompileTokenRatio": None,
            "fullCompileP50WallRatio": None,
            "postReviewP50WallRatio": None,
            "reviewTokenRatio": None,
        }
    global_targets = policy["globalTargets"]
    targets = {
        "fullCompileTokenRatio": global_targets["fullCompileTokenRatio"],
        "fullCompileP50WallRatio": global_targets["fullCompileP50WallRatio"],
        "postReviewP50WallRatio": global_targets["postReviewP50WallRatio"],
        "reviewTokenRatio": global_targets["reviewTokenRatioMaximum"],
    }
    checks = {
        "sameExecutionProfile": True,
        "exactSampleMatrix": True,
        "completeReceiptGranularities": True,
        "allReceiptsUsable": all_usable and all_samples_completed,
        "fullCompileTokenTarget": metrics["fullCompileTokenRatio"] is not None
        and metrics["fullCompileTokenRatio"] <= targets["fullCompileTokenRatio"],
        "fullCompileP50WallTarget": metrics["fullCompileP50WallRatio"] is not None
        and metrics["fullCompileP50WallRatio"]
        <= targets["fullCompileP50WallRatio"],
        "postReviewP50WallTarget": metrics["postReviewP50WallRatio"] is not None
        and metrics["postReviewP50WallRatio"] <= targets["postReviewP50WallRatio"],
        "reviewTokenGuard": metrics["reviewTokenRatio"] is not None
        and metrics["reviewTokenRatio"] <= targets["reviewTokenRatio"],
    }
    failure_codes = sorted(key for key, passed in checks.items() if not passed)
    receipt = {
        "contract": "ai-sow-paired-benchmark-comparison-v1",
        "policySha256": _policy_evaluation_sha256(policy),
        "baselineManifestSha256": _sha256_file(baseline_path),
        "candidateManifestSha256": _sha256_file(candidate_path),
        "sampleMatrixSha256": baseline_matrix_sha256,
        "executionProfileSha256": _sha256_bytes(
            _canonical_json_bytes(baseline_profile)
        ),
        "metrics": metrics,
        "targets": targets,
        "checks": checks,
        "verdict": "PASS" if not failure_codes else "FAIL",
        "failureCodes": failure_codes,
    }
    _validate_comparison_receipt(receipt)
    return receipt


def _compare(arguments: argparse.Namespace) -> int:
    policy = _read_json(Path(arguments.policy))
    _validate_schema("model-efficiency-policy.schema.json", policy)
    receipt = _evaluate_comparison(
        policy,
        Path(arguments.baseline_manifest),
        Path(arguments.candidate_manifest),
    )
    output_path = Path(arguments.output)
    _write_json(output_path, receipt)
    _emit(
        {
            "status": "COMPARED",
            "verdict": receipt["verdict"],
            "comparisonReceiptSha256": _sha256_file(output_path),
        }
    )
    return 0 if receipt["verdict"] == "PASS" else 2


def _validate_manifest(arguments: argparse.Namespace) -> int:
    manifest_path = Path(arguments.manifest)
    manifest, receipts = _validated_manifest_bundle(manifest_path)
    _emit(
        {
            "status": "VALID",
            "manifestSha256": _sha256_file(manifest_path),
            "sampleCount": len(manifest["samples"]),
            "receiptCount": len(receipts),
        }
    )
    return 0


def _policy_reference(policy_path: Path, relative_path: str) -> Path:
    candidates = (PLUGIN_ROOT / relative_path, policy_path.parent / relative_path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ProtocolError(
        "POLICY_EVIDENCE_MISSING", f"policy 证据不存在：{relative_path}"
    )


def _validate_policy_evidence(arguments: argparse.Namespace) -> int:
    policy_path = Path(arguments.policy)
    policy = _read_json(policy_path)
    _validate_schema("model-efficiency-policy.schema.json", policy)
    gate = policy["pairedBenchmarkGate"]
    if gate["status"] != "SATISFIED":
        _emit(
            {
                "status": "VALID",
                "claimStatus": gate["claimStatus"],
                "verdict": None,
            }
        )
        return 0
    baseline_path = _policy_reference(policy_path, gate["baselineManifest"])
    candidate_path = _policy_reference(policy_path, gate["candidateManifest"])
    comparison_binding = gate["comparisonReceipt"]
    comparison_path = _policy_reference(policy_path, comparison_binding["path"])
    if _sha256_file(comparison_path) != comparison_binding["sha256"]:
        raise ProtocolError(
            "COMPARISON_RECEIPT_HASH_MISMATCH",
            "comparison receipt 与 policy hash 绑定不一致。",
        )
    stored = _read_json(comparison_path)
    _validate_comparison_receipt(stored)
    expected = _evaluate_comparison(policy, baseline_path, candidate_path)
    if _canonical_json_bytes(stored) != _canonical_json_bytes(expected):
        raise ProtocolError(
            "COMPARISON_RECEIPT_EVIDENCE_MISMATCH",
            "comparison receipt 不是当前 policy 与两份 manifest 的机械求值结果。",
        )
    if stored["verdict"] != "PASS":
        raise ProtocolError(
            "COMPARISON_NOT_PASSING", "SATISFIED policy 必须绑定 PASS receipt。"
        )
    _emit(
        {
            "status": "VALID",
            "claimStatus": gate["claimStatus"],
            "verdict": stored["verdict"],
        }
    )
    return 0


def _sha256_argument(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise argparse.ArgumentTypeError("必须是小写十六进制 SHA-256。")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("baseline-init")
    initialize.add_argument("--state-dir", required=True)
    initialize.add_argument("--scenario-root", required=True)
    initialize.add_argument("--baseline-commit", required=True)
    initialize.add_argument("--implementation-sha256", type=_sha256_argument, required=True)
    initialize.add_argument("--environment-sha256", type=_sha256_argument, required=True)
    initialize.add_argument("--model-profile-id", required=True)
    initialize.add_argument("--model", required=True)
    initialize.add_argument("--reasoning-effort", required=True)
    initialize.add_argument(
        "--accounting-mode",
        choices=("PROVIDER_REPORTED", "LOCALLY_ESTIMATED"),
        required=True,
    )
    initialize.add_argument("--office-version", required=True)
    initialize.add_argument("--office-binary-sha256", type=_sha256_argument, required=True)
    initialize.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    initialize.add_argument("--tool-version", action="append", default=[])
    initialize.add_argument("--max-concurrency", type=int, default=1)
    initialize.add_argument("--runs", type=int, default=5)
    initialize.set_defaults(handler=_baseline_init)

    next_action = commands.add_parser("next-action")
    next_action.add_argument("--state-dir", required=True)
    next_action.add_argument("--project-root")
    next_action.add_argument("--office-bin")
    next_action.set_defaults(handler=_next_action)

    record = commands.add_parser("record-usage")
    record.add_argument("--state-dir", required=True)
    record.add_argument("--receipt", required=True)
    record.set_defaults(handler=_record_usage)

    classify = commands.add_parser("classify-failure")
    classify.add_argument("--state-dir", required=True)
    classify.add_argument("--incident", required=True)
    classify.add_argument("--resume-same-sample", action="store_true")
    classify.add_argument("--decision")
    classify.add_argument("--retain-product-failure", action="store_true")
    classify.set_defaults(handler=_classify_failure)

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--state-dir", required=True)
    finalize.add_argument("--manifest", required=True)
    finalize.set_defaults(handler=_finalize)

    validate = commands.add_parser("validate")
    validate.add_argument("--manifest", required=True)
    validate.set_defaults(handler=_validate_manifest)

    compare = commands.add_parser("compare")
    compare.add_argument("--policy", required=True)
    compare.add_argument("--baseline-manifest", required=True)
    compare.add_argument("--candidate-manifest", required=True)
    compare.add_argument("--output", required=True)
    compare.set_defaults(handler=_compare)

    validate_policy = commands.add_parser("validate-policy")
    validate_policy.add_argument("--policy", required=True)
    validate_policy.set_defaults(handler=_validate_policy_evidence)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if getattr(arguments, "runs", 5) < 5:
            raise ProtocolError("INSUFFICIENT_REPETITIONS", "每个成功场景至少需要五次运行。")
        if getattr(arguments, "max_concurrency", 1) < 1:
            raise ProtocolError("INVALID_CONCURRENCY", "并发数必须大于零。")
        return int(arguments.handler(arguments))
    except ProtocolError as exc:
        _emit({"status": "ERROR", "code": exc.code, "message": exc.message})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
