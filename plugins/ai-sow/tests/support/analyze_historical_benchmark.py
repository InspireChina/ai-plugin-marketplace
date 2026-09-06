#!/usr/bin/env python3
"""已取代的历史 benchmark 收据分析；不启动当前 SOW run。"""
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("compare", _compare), ("validate", _validate_manifest), ("validate-policy", _validate_policy_evidence)):
        command = commands.add_parser(name)
        fields = {"compare": ("policy", "baseline-manifest", "candidate-manifest", "output"), "validate": ("manifest",), "validate-policy": ("policy",)}[name]
        for field in fields: command.add_argument("--" + field, required=True)
        command.set_defaults(handler=handler)
    try:
        args = parser.parse_args(argv)
        return int(args.handler(args))
    except ProtocolError as exc:
        _emit({"status": "ERROR", "code": exc.code, "message": exc.message})
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
