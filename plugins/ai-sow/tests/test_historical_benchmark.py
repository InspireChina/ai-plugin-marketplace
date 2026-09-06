"""已取代的历史比较分析回归，不运行当前生产协议。"""
from __future__ import annotations

TEST_LAYER = "unit"

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import jsonschema
import pytest


PLUGIN_ROOT = Path(__file__).parents[1]
TEST_ROOT = PLUGIN_ROOT / "tests"
CONTRACT_ROOT = TEST_ROOT / "contracts"
BENCHMARK_ROOT = TEST_ROOT / "benchmarks"
BASELINE_ROOT = BENCHMARK_ROOT / "baseline-75970b2"
BASELINE_OBSERVATION = BASELINE_ROOT / "observation.json"
DEFECT_HARVEST = BASELINE_ROOT / "defect-harvest.md"
POLICY_PATH = BENCHMARK_ROOT / "model-efficiency-policy-v1.json"
SCENARIO_ROOT = BENCHMARK_ROOT / "scenarios"
RUNNER_PATH = TEST_ROOT / "support/analyze_historical_benchmark.py"
BASELINE_COMMIT = "75970b2cadd6c298443b1d6016f99b34c8e3b25a"
SHA256 = "a" * 64


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema(name: str) -> dict[str, object]:
    return _read_json(CONTRACT_ROOT / name)


def _validate(name: str, value: object) -> None:
    jsonschema.Draft202012Validator(_schema(name)).validate(value)


def _observation() -> dict[str, object]:
    value = _read_json(BASELINE_OBSERVATION)
    _validate("pipeline-baseline-observation.schema.json", value)
    return value


def _load_runner() -> ModuleType:
    assert RUNNER_PATH.is_file(), RUNNER_PATH
    spec = importlib.util.spec_from_file_location("analyze_historical_benchmark", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _valid_receipt(
    *,
    sample_id: str = "small-greenfield-cold-r01",
    scenario_id: str = "small-greenfield",
    cache_mode: str = "COLD",
    repetition: int = 1,
    bindings: dict[str, str] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "contract": "ai-sow-model-execution-receipt-v1",
        "receiptId": f"receipt-{sample_id}",
        "sampleId": sample_id,
        "scenarioId": scenario_id,
        "repetition": repetition,
        "cacheMode": cache_mode,
        "granularity": "RUN",
        "runId": f"run-{sample_id}",
        "actionId": None,
        "stage": "RUN",
        "modelProfileId": "benchmark-profile-v1",
        "model": "benchmark-model",
        "reasoningEffort": "high",
        "bindings": bindings
        or {
            "environmentSha256": SHA256,
            "implementationSha256": "b" * 64,
            "inputSha256": "c" * 64,
            "packetSha256": "d" * 64,
            "baseSha256": "e" * 64,
            "cacheProtocolSha256": "f" * 64,
        },
        "timing": {
            "queueMilliseconds": 10,
            "executionMilliseconds": 80,
            "joinMilliseconds": 0,
            "totalMilliseconds": 90,
            "criticalPathMilliseconds": 80,
        },
        "usage": {
            "accountingMode": "LOCALLY_ESTIMATED",
            "inputTokens": 40,
            "cachedInputTokens": 0,
            "outputTokens": 20,
            "reasoningTokens": None,
            "controlPlaneTokens": 10,
            "toolContextTokens": 5,
            "tokenizer": {"id": "fixture-tokenizer", "version": "1"},
        },
        "work": {
            "hydrationRounds": 0,
            "toolAttempts": 1,
            "modelAttempts": 1,
            "actionAttempts": 1,
            "repairWaves": 0,
            "adjudications": 0,
            "recompiles": 0,
            "rereviews": 0,
            "failures": 0,
            "retries": 0,
        },
        "outcome": {
            "semanticCorrectnessPassed": True,
            "wallBudgetPassed": True,
            "tokenBudgetPassed": True,
            "noWasteAmplification": True,
            "usable": True,
            "code": None,
        },
    }
    payload_sha256 = hashlib.sha256(_canonical_json_bytes(value)).hexdigest()
    value["signature"] = {"algorithm": "SHA256", "payloadSha256": payload_sha256}
    return value


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER_PATH), *arguments],
        cwd=PLUGIN_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def _resign_receipt(receipt: dict[str, object]) -> None:
    unsigned = dict(receipt)
    unsigned.pop("signature", None)
    receipt["signature"] = {
        "algorithm": "SHA256",
        "payloadSha256": hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest(),
    }


def _write_comparable_manifest(
    module: ModuleType,
    root: Path,
    *,
    implementation_sha256: str,
    wall_ratio: float,
    token_ratio: float,
) -> Path:
    root.mkdir(parents=True)
    receipt_root = root / "receipts"
    receipt_root.mkdir()
    samples: list[dict[str, object]] = []
    receipt_index: list[dict[str, str]] = []
    case_sha256_by_scenario = {
        path.parent.name: _sha256(path)
        for path in SCENARIO_ROOT.glob("*/case.json")
    }
    matrix = [
        (scenario_id, cache_mode, repetition, "SUCCESS")
        for scenario_id in (
            "small-greenfield",
            "medium-demo",
            "large-brownfield",
        )
        for cache_mode in ("COLD", "WARM")
        for repetition in range(1, 6)
    ] + [
        ("blocked-missing-design", "COLD", 1, "BLOCKED"),
        ("blocked-source-conflict", "WARM", 1, "BLOCKED"),
    ]
    for scenario_id, cache_mode, repetition, scenario_class in matrix:
        sample_id = f"{scenario_id}-{cache_mode.lower()}-r{repetition:02d}"
        hashes: list[str] = []
        if scenario_class == "SUCCESS":
            receipt_specs = [
                *( ("ACTION", stage) for stage in (
                    "STAGE_1", "STAGE_2", "STAGE_3", "R1", "R2", "R3"
                ) ),
                *( ("STAGE", stage) for stage in (
                    "STAGE_1", "STAGE_2", "STAGE_3", "R1", "R2", "R3",
                    "DRAFT_OFFICE",
                ) ),
                ("RUN", "RUN"),
            ]
        else:
            receipt_specs = [
                ("ACTION", "CONTROL_PLANE"),
                ("STAGE", "CONTROL_PLANE"),
                ("RUN", "RUN"),
            ]
        stage_count = sum(
            1 for granularity, _stage in receipt_specs if granularity == "STAGE"
        )
        cache_protocol = {
            **module.CACHE_PROTOCOL[cache_mode],
            "namespace": sample_id if cache_mode == "COLD" else scenario_id,
        }
        for granularity, stage in receipt_specs:
            aggregate_multiplier = stage_count if granularity == "RUN" else 1
            receipt = _valid_receipt(
                sample_id=sample_id,
                scenario_id=scenario_id,
                cache_mode=cache_mode,
                repetition=repetition,
            )
            receipt["receiptId"] = (
                f"receipt-{sample_id}-{granularity.lower()}-{stage.lower()}"
            )
            receipt["granularity"] = granularity
            receipt["stage"] = stage
            receipt["actionId"] = (
                f"action-{sample_id}-{stage.lower()}"
                if granularity == "ACTION"
                else None
            )
            receipt["bindings"] = {
                **receipt["bindings"],
                "environmentSha256": SHA256,
                "implementationSha256": implementation_sha256,
                "inputSha256": case_sha256_by_scenario[scenario_id],
                "baseSha256": hashlib.sha256(
                    BASELINE_COMMIT.encode("utf-8")
                ).hexdigest(),
                "cacheProtocolSha256": hashlib.sha256(
                    _canonical_json_bytes(cache_protocol)
                ).hexdigest(),
            }
            receipt["timing"] = {
                **receipt["timing"],
                "queueMilliseconds": 10 * aggregate_multiplier,
                "executionMilliseconds": 1000
                * wall_ratio
                * aggregate_multiplier,
                "joinMilliseconds": 0,
                "totalMilliseconds": 1000 * wall_ratio * aggregate_multiplier,
                "criticalPathMilliseconds": 1000
                * wall_ratio
                * aggregate_multiplier,
            }
            receipt["usage"] = {
                **receipt["usage"],
                "inputTokens": int(65 * token_ratio) * aggregate_multiplier,
                "outputTokens": int(20 * token_ratio) * aggregate_multiplier,
                "controlPlaneTokens": int(10 * token_ratio)
                * aggregate_multiplier,
                "toolContextTokens": int(5 * token_ratio)
                * aggregate_multiplier,
            }
            receipt["work"] = {
                key: value * aggregate_multiplier
                for key, value in receipt["work"].items()
            }
            _resign_receipt(receipt)
            receipt_path = receipt_root / f"{receipt['receiptId']}.json"
            receipt_path.write_bytes(_canonical_json_bytes(receipt))
            receipt_sha256 = _sha256(receipt_path)
            hashes.append(receipt_sha256)
            receipt_index.append(
                {
                    "path": f"receipts/{receipt_path.name}",
                    "sha256": receipt_sha256,
                }
            )
        sample: dict[str, object] = {
            "sampleId": sample_id,
            "scenarioId": scenario_id,
            "scenarioClass": scenario_class,
            "cacheMode": cache_mode,
            "repetition": repetition,
            "status": "COMPLETED",
            "receiptSha256s": hashes,
            "failureCount": 0,
        }
        if scenario_class == "SUCCESS":
            sample["readyForApprovalMilliseconds"] = (
                1000 * wall_ratio * stage_count
            )
        else:
            sample["timeToInputGapMilliseconds"] = (
                1000 * wall_ratio * stage_count
            )
        samples.append(sample)
    scenarios = []
    for case_path in sorted(SCENARIO_ROOT.glob("*/case.json")):
        case = _read_json(case_path)
        scenarios.append(
            {
                "scenarioId": case["scenarioId"],
                "class": case["class"],
                "casePath": case_path.relative_to(PLUGIN_ROOT).as_posix(),
                "caseSha256": _sha256(case_path),
            }
        )
    summaries = module._summaries(samples)
    interval = _read_json(POLICY_PATH)["pairedBenchmarkGate"]["comparisonInterval"]
    manifest = {
        "contract": "ai-sow-pipeline-benchmark-v1",
        "baselineCommit": BASELINE_COMMIT,
        "implementationSha256": implementation_sha256,
        "execution": {
            "hostProtocol": "EXTERNAL_FRESH_WORKER",
            "runtimeDependency": "NONE",
            "modelProfileId": "benchmark-profile-v1",
            "model": "benchmark-model",
            "reasoningEffort": "high",
            "environmentSha256": SHA256,
            "toolVersions": {
                "host-client": "fixture",
                "python": "3.12",
                "uv": "0.11.7",
            },
            "maxConcurrency": 4,
            "office": {
                "name": "LibreOffice",
                "version": "24.2",
                "binarySha256": "f" * 64,
            },
            "cacheModes": ["COLD", "WARM"],
            "cacheProtocol": deepcopy(module.CACHE_PROTOCOL),
            "accountingMode": "LOCALLY_ESTIMATED",
            "repetitionsPerScenario": 5,
        },
        "comparisonInterval": interval,
        "scenarios": scenarios,
        "samples": samples,
        "receiptIndex": receipt_index,
        "summaries": summaries,
        "summarySha256": hashlib.sha256(
            _canonical_json_bytes(summaries)
        ).hexdigest(),
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_bytes(_canonical_json_bytes(manifest))
    return manifest_path


def _mutate_indexed_receipts(
    manifest_path: Path,
    predicate,
    mutation,
) -> None:
    manifest = _read_json(manifest_path)
    replacements: dict[str, str] = {}
    for index in manifest["receiptIndex"]:
        receipt_path = manifest_path.parent / str(index["path"])
        receipt = _read_json(receipt_path)
        if not predicate(receipt):
            continue
        old_sha256 = str(index["sha256"])
        mutation(receipt)
        _resign_receipt(receipt)
        receipt_path.write_bytes(_canonical_json_bytes(receipt))
        new_sha256 = _sha256(receipt_path)
        index["sha256"] = new_sha256
        replacements[old_sha256] = new_sha256
    for sample in manifest["samples"]:
        sample["receiptSha256s"] = [
            replacements.get(str(value), str(value))
            for value in sample["receiptSha256s"]
        ]
    manifest_path.write_bytes(_canonical_json_bytes(manifest))






def _receipt_for_action(action: dict[str, object], *, failed: bool) -> dict[str, object]:
    bindings = action["bindings"]
    assert isinstance(bindings, dict)
    receipt = _valid_receipt(
        sample_id=str(action["sampleId"]),
        scenario_id=str(action["scenarioId"]),
        cache_mode=str(action["cacheMode"]),
        repetition=int(action["repetition"]),
        bindings={str(key): str(value) for key, value in bindings.items()},
    )
    receipt["actionId"] = action["actionId"]
    receipt["runId"] = action["runId"]
    if failed:
        receipt["work"] = {**receipt["work"], "failures": 1}
        receipt["outcome"] = {
            "semanticCorrectnessPassed": False,
            "wallBudgetPassed": True,
            "tokenBudgetPassed": True,
            "noWasteAmplification": False,
            "usable": False,
            "code": "MODEL_EXECUTION_FAILED",
        }
    unsigned = dict(receipt)
    unsigned.pop("signature", None)
    receipt["signature"] = {
        "algorithm": "SHA256",
        "payloadSha256": hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest(),
    }
    return receipt


def test_partial_baseline_observation_is_hash_bound_and_cannot_support_numeric_claims() -> None:
    observation = _observation()
    assert observation["baselineCommit"] == BASELINE_COMMIT
    assert observation["evidenceStatus"] == "PARTIAL_BASELINE_CHECKPOINT"
    assert observation["evidenceSource"] == {
        "path": "tests/benchmarks/baseline-75970b2/defect-harvest.md",
        "sha256": _sha256(DEFECT_HARVEST),
    }
    assert observation["sampleAccounting"] == {
        "completedSamples": 12,
        "excludedSamples": 1,
        "usableComparisonSamples": 0,
    }
    assert observation["aggregateObservation"] == {
        "wallMilliseconds": 19_606_627,
        "inputTokens": 90_864_877,
        "cachedInputTokens": 88_910_720,
        "outputTokens": 720_700,
        "reasoningTokens": 144_264,
        "toolAttempts": 1_042,
        "failures": 59,
        "repairWaves": 23,
        "rereviews": 21,
    }
    outcome_counts = {
        item["code"]: item["count"] for item in observation["outcomeCounts"]
    }
    assert outcome_counts == {
        "FINAL_REVIEW_CONFLICT": 5,
        "STORY_AC_RECEIPT_MISSING": 2,
        "MODEL_EFFICIENCY_FAILED": 5,
    }
    assert sum(outcome_counts.values()) == observation["sampleAccounting"]["completedSamples"]
    assert observation["comparisonEligibility"]["pairedNumericConclusionAllowed"] is False
    assert observation["comparisonEligibility"]["relativeImprovementClaimAllowed"] is False
    with pytest.raises(jsonschema.ValidationError):
        _validate("pipeline-benchmark.schema.json", observation)


def test_benchmark_cases_cover_small_medium_large_and_two_blockers() -> None:
    cases = {
        path.parent.name: _read_json(path)
        for path in sorted(SCENARIO_ROOT.glob("*/case.json"))
    }
    assert set(cases) == {
        "small-greenfield",
        "medium-demo",
        "large-brownfield",
        "blocked-missing-design",
        "blocked-source-conflict",
    }
    assert {
        cases[key]["class"]
        for key in ("small-greenfield", "medium-demo", "large-brownfield")
    } == {"SUCCESS"}
    assert cases["blocked-missing-design"]["class"] == "BLOCKED"
    assert cases["blocked-source-conflict"]["class"] == "BLOCKED"
    for case in cases.values():
        assert case["contract"] == "ai-sow-benchmark-case-v1"
        assert case["privacy"] == "ANONYMOUS_SYNTHETIC"
    large = _read_json(SCENARIO_ROOT / "large-brownfield/case.json")
    assert large["scaleExpectations"]["requiresModelSharding"] is True






def test_ready_for_approval_interval_includes_render_and_office_verification() -> None:
    interval = _read_json(POLICY_PATH)["pairedBenchmarkGate"]["comparisonInterval"]
    assert interval["startProbe"] == "INPUT_REVISION_ACCEPTED"
    assert interval["candidateEndProbe"] == "AWAITING_APPROVAL"
    assert set(interval["includedBaselinePublishSegments"]) == {
        "RENDER",
        "OFFICE_RECALCULATION",
        "OFFICE_REREAD",
    }


def test_baseline_cutoff_maps_old_publish_probe_to_candidate_approval_ready_interval() -> None:
    interval = _read_json(POLICY_PATH)["pairedBenchmarkGate"]["comparisonInterval"]
    assert interval == {
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
    }


def test_model_execution_receipt_covers_action_stage_run_time_token_and_rework() -> None:
    receipt = _valid_receipt()
    _validate("model-execution-receipt.schema.json", receipt)
    for required_group in ("bindings", "timing", "usage", "work", "outcome"):
        invalid = deepcopy(receipt)
        invalid.pop(required_group)
        with pytest.raises(jsonschema.ValidationError):
            _validate("model-execution-receipt.schema.json", invalid)
    assert receipt["usage"]["reasoningTokens"] is None



def test_model_efficiency_policy_allocates_global_seventy_percent_target_without_hiding_cost() -> None:
    policy = _read_json(POLICY_PATH)
    _validate("model-efficiency-policy.schema.json", policy)
    assert policy["contract"] == "ai-sow-model-efficiency-policy-v1"
    assert policy["baselineObservationSha256"] == _sha256(BASELINE_OBSERVATION)
    assert policy["contextAllocation"] == {
        "initialPacketRatio": 0.60,
        "hydrationRatio": 0.15,
        "outputRatio": 0.20,
        "safetyMarginRatio": 0.05,
    }
    assert policy["globalTargets"]["fullCompileTokenRatio"] == 0.70
    assert policy["globalTargets"]["fullCompileP50WallRatio"] == 0.70
    assert policy["globalTargets"]["postReviewP50WallRatio"] == 0.70
    assert policy["globalTargets"]["reviewTokenRatioMaximum"] == 1.40
    assert set(policy["stageBudgets"]) == {
        "STAGE_1",
        "STAGE_2",
        "STAGE_3",
        "R1",
        "R2",
        "R3",
        "REPAIR",
        "DELTA_REVIEW",
        "ADJUDICATION",
        "DRAFT_OFFICE",
        "CONTROL_PLANE",
    }
    assert set(policy["costShiftGuards"]) == {
        "stage1",
        "downstreamReview",
        "office",
        "promote",
        "controlPlane",
        "retryRework",
    }
    assert all(policy["costShiftGuards"].values())
    assert policy["allocationProof"]["targetCriticalPathRatio"] == 0.70
    assert policy["allocationProof"]["targetTokenRatio"] == 0.70
    assert policy["allocationProof"]["status"] == "REQUIRES_PAIRED_BENCHMARK"


def test_numeric_efficiency_claim_requires_two_complete_validated_manifests() -> None:
    gate = _read_json(POLICY_PATH)["pairedBenchmarkGate"]
    assert gate["status"] == "REQUIRED_NOT_SATISFIED"
    assert gate["claimStatus"] == "FORBIDDEN_UNTIL_VALIDATED_MANIFESTS"
    assert gate["baselineManifest"] is None
    assert gate["candidateManifest"] is None
    assert gate["minimumSamplesPerManifest"] == 32
    assert gate["minimumRepetitionsPerSuccessScenario"] == 5
    assert gate["cacheModes"] == ["COLD", "WARM"]
    assert gate["requiredReceiptGranularities"] == ["ACTION", "STAGE", "RUN"]
    assert gate["sameExecutionProfileRequired"] == [
        "modelProfileId",
        "model",
        "reasoningEffort",
        "environmentSha256",
        "toolVersions",
        "office",
        "accountingMode",
        "cacheProtocol",
    ]
    invalid = deepcopy(_read_json(POLICY_PATH))
    invalid["pairedBenchmarkGate"]["status"] = "SATISFIED"
    with pytest.raises(jsonschema.ValidationError):
        _validate("model-efficiency-policy.schema.json", invalid)
    paths_only = deepcopy(_read_json(POLICY_PATH))
    paths_only["pairedBenchmarkGate"].update(
        {
            "status": "SATISFIED",
            "claimStatus": "ALLOWED_AFTER_TARGET_EVALUATION",
            "baselineManifest": "tests/benchmarks/baseline/manifest.json",
            "candidateManifest": "tests/benchmarks/candidate/manifest.json",
        }
    )
    with pytest.raises(jsonschema.ValidationError):
        _validate("model-efficiency-policy.schema.json", paths_only)


def test_compare_mechanically_pairs_32_samples_and_evaluates_full_cost(
    tmp_path: Path,
) -> None:
    module = _load_runner()
    baseline = _write_comparable_manifest(
        module,
        tmp_path / "baseline",
        implementation_sha256="b" * 64,
        wall_ratio=1.0,
        token_ratio=1.0,
    )
    candidate = _write_comparable_manifest(
        module,
        tmp_path / "candidate",
        implementation_sha256="c" * 64,
        wall_ratio=0.6,
        token_ratio=0.6,
    )
    output = tmp_path / "comparison.json"

    compared = _run_cli(
        "compare",
        "--policy",
        str(POLICY_PATH),
        "--baseline-manifest",
        str(baseline),
        "--candidate-manifest",
        str(candidate),
        "--output",
        str(output),
    )

    assert compared.returncode == 0, compared.stderr or compared.stdout
    receipt = _read_json(output)
    _validate("paired-benchmark-comparison.schema.json", receipt)
    assert receipt["verdict"] == "PASS"
    assert receipt["metrics"] == {
        "fullCompileTokenRatio": 0.6,
        "fullCompileP50WallRatio": 0.6,
        "postReviewP50WallRatio": 0.6,
        "reviewTokenRatio": 0.6,
    }
    candidate_value = _read_json(candidate)
    candidate_value["execution"]["toolVersions"]["uv"] = "profile-drift"
    candidate.write_bytes(_canonical_json_bytes(candidate_value))
    rejected = _run_cli(
        "compare",
        "--policy",
        str(POLICY_PATH),
        "--baseline-manifest",
        str(baseline),
        "--candidate-manifest",
        str(candidate),
        "--output",
        str(output),
    )
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["code"] == "EXECUTION_PROFILE_MISMATCH"


def test_comparison_receipt_verdict_is_consistent_with_checks_and_failures() -> None:
    checks = {
        "sameExecutionProfile": True,
        "exactSampleMatrix": True,
        "completeReceiptGranularities": True,
        "allReceiptsUsable": True,
        "fullCompileTokenTarget": True,
        "fullCompileP50WallTarget": True,
        "postReviewP50WallTarget": True,
        "reviewTokenGuard": True,
    }
    receipt = {
        "contract": "ai-sow-paired-benchmark-comparison-v1",
        "policySha256": SHA256,
        "baselineManifestSha256": SHA256,
        "candidateManifestSha256": SHA256,
        "sampleMatrixSha256": SHA256,
        "executionProfileSha256": SHA256,
        "metrics": {
            "fullCompileTokenRatio": 0.6,
            "fullCompileP50WallRatio": 0.6,
            "postReviewP50WallRatio": 0.6,
            "reviewTokenRatio": 0.6,
        },
        "targets": {
            "fullCompileTokenRatio": 0.7,
            "fullCompileP50WallRatio": 0.7,
            "postReviewP50WallRatio": 0.7,
            "reviewTokenRatio": 1.0,
        },
        "checks": checks,
        "verdict": "PASS",
        "failureCodes": [],
    }
    _validate("paired-benchmark-comparison.schema.json", receipt)

    pass_with_failed_check = deepcopy(receipt)
    pass_with_failed_check["checks"]["allReceiptsUsable"] = False
    with pytest.raises(jsonschema.ValidationError):
        _validate("paired-benchmark-comparison.schema.json", pass_with_failed_check)

    pass_with_failure = deepcopy(receipt)
    pass_with_failure["failureCodes"] = ["allReceiptsUsable"]
    with pytest.raises(jsonschema.ValidationError):
        _validate("paired-benchmark-comparison.schema.json", pass_with_failure)

    fail_without_failure = deepcopy(receipt)
    fail_without_failure["verdict"] = "FAIL"
    with pytest.raises(jsonschema.ValidationError):
        _validate("paired-benchmark-comparison.schema.json", fail_without_failure)

    fabricated_failure = deepcopy(receipt)
    fabricated_failure["verdict"] = "FAIL"
    fabricated_failure["failureCodes"] = ["fabricated"]
    with pytest.raises(jsonschema.ValidationError):
        _validate("paired-benchmark-comparison.schema.json", fabricated_failure)

    module = _load_runner()
    wrong_failure = deepcopy(receipt)
    wrong_failure["checks"]["allReceiptsUsable"] = False
    wrong_failure["verdict"] = "FAIL"
    wrong_failure["failureCodes"] = ["fabricated"]
    with pytest.raises(module.ProtocolError) as captured:
        module._validate_comparison_receipt(wrong_failure)
    assert captured.value.code == "COMPARISON_FAILURE_CODES_INVALID"


def test_compare_marks_nonusable_action_receipt_as_auditable_failure(
    tmp_path: Path,
) -> None:
    module = _load_runner()
    baseline = _write_comparable_manifest(
        module,
        tmp_path / "baseline",
        implementation_sha256="b" * 64,
        wall_ratio=1.0,
        token_ratio=1.0,
    )
    candidate = _write_comparable_manifest(
        module,
        tmp_path / "candidate",
        implementation_sha256="c" * 64,
        wall_ratio=0.6,
        token_ratio=0.6,
    )
    changed = {"done": False}

    def first_action(receipt: dict[str, object]) -> bool:
        if changed["done"] or receipt["granularity"] != "ACTION":
            return False
        changed["done"] = True
        return True

    def make_unusable(receipt: dict[str, object]) -> None:
        outcome = receipt["outcome"]
        assert isinstance(outcome, dict)
        outcome.update(
            {
                "semanticCorrectnessPassed": False,
                "usable": False,
                "code": "MODEL_EXECUTION_FAILED",
            }
        )

    _mutate_indexed_receipts(candidate, first_action, make_unusable)
    output = tmp_path / "comparison.json"
    compared = _run_cli(
        "compare",
        "--policy",
        str(POLICY_PATH),
        "--baseline-manifest",
        str(baseline),
        "--candidate-manifest",
        str(candidate),
        "--output",
        str(output),
    )

    assert compared.returncode == 2, compared.stderr or compared.stdout
    receipt = _read_json(output)
    assert receipt["verdict"] == "FAIL"
    assert receipt["checks"]["allReceiptsUsable"] is False
    assert "allReceiptsUsable" in receipt["failureCodes"]


@pytest.mark.parametrize(
    ("binding", "expected_code"),
    (
        ("environmentSha256", "RECEIPT_ENVIRONMENT_HASH_MISMATCH"),
        ("inputSha256", "RECEIPT_INPUT_HASH_MISMATCH"),
        ("cacheProtocolSha256", "RECEIPT_CACHE_PROTOCOL_HASH_MISMATCH"),
    ),
)
def test_compare_rejects_receipt_environment_input_and_cache_drift(
    tmp_path: Path,
    binding: str,
    expected_code: str,
) -> None:
    module = _load_runner()
    baseline = _write_comparable_manifest(
        module,
        tmp_path / "baseline",
        implementation_sha256="b" * 64,
        wall_ratio=1.0,
        token_ratio=1.0,
    )
    candidate = _write_comparable_manifest(
        module,
        tmp_path / "candidate",
        implementation_sha256="c" * 64,
        wall_ratio=0.6,
        token_ratio=0.6,
    )

    def drift(receipt: dict[str, object]) -> None:
        bindings = receipt["bindings"]
        assert isinstance(bindings, dict)
        bindings[binding] = "9" * 64

    _mutate_indexed_receipts(candidate, lambda _receipt: True, drift)
    compared = _run_cli(
        "compare",
        "--policy",
        str(POLICY_PATH),
        "--baseline-manifest",
        str(baseline),
        "--candidate-manifest",
        str(candidate),
        "--output",
        str(tmp_path / "comparison.json"),
    )

    assert compared.returncode == 2
    assert json.loads(compared.stdout)["code"] == expected_code


def test_compare_rejects_self_reported_usable_action_over_budget(
    tmp_path: Path,
) -> None:
    module = _load_runner()
    baseline = _write_comparable_manifest(
        module,
        tmp_path / "baseline",
        implementation_sha256="b" * 64,
        wall_ratio=1.0,
        token_ratio=1.0,
    )
    candidate = _write_comparable_manifest(
        module,
        tmp_path / "candidate",
        implementation_sha256="c" * 64,
        wall_ratio=0.6,
        token_ratio=0.6,
    )

    def forge_usable(receipt: dict[str, object]) -> None:
        receipt["timing"]["totalMilliseconds"] = 999_999_999
        receipt["usage"]["inputTokens"] = 999_999_999
        receipt["work"]["retries"] = 99

    mutated = False

    def first_action(receipt: dict[str, object]) -> bool:
        nonlocal mutated
        if mutated or receipt["granularity"] != "ACTION":
            return False
        mutated = True
        return True

    _mutate_indexed_receipts(candidate, first_action, forge_usable)
    compared = _run_cli(
        "compare",
        "--policy",
        str(POLICY_PATH),
        "--baseline-manifest",
        str(baseline),
        "--candidate-manifest",
        str(candidate),
        "--output",
        str(tmp_path / "comparison.json"),
    )

    assert compared.returncode == 2
    assert json.loads(compared.stdout)["code"] == (
        "RECEIPT_OUTCOME_ASSESSMENT_MISMATCH"
    )


def test_compare_rejects_run_stage_accounting_mismatch(tmp_path: Path) -> None:
    module = _load_runner()
    baseline = _write_comparable_manifest(
        module,
        tmp_path / "baseline",
        implementation_sha256="b" * 64,
        wall_ratio=1.0,
        token_ratio=1.0,
    )
    candidate = _write_comparable_manifest(
        module,
        tmp_path / "candidate",
        implementation_sha256="c" * 64,
        wall_ratio=0.6,
        token_ratio=0.6,
    )
    mutated = False

    def first_run(receipt: dict[str, object]) -> bool:
        nonlocal mutated
        if mutated or receipt["granularity"] != "RUN":
            return False
        mutated = True
        return True

    def break_aggregation(receipt: dict[str, object]) -> None:
        receipt["usage"]["inputTokens"] -= 1

    _mutate_indexed_receipts(candidate, first_run, break_aggregation)
    compared = _run_cli(
        "compare",
        "--policy",
        str(POLICY_PATH),
        "--baseline-manifest",
        str(baseline),
        "--candidate-manifest",
        str(candidate),
        "--output",
        str(tmp_path / "comparison.json"),
    )

    assert compared.returncode == 2
    assert json.loads(compared.stdout)["code"] == "RECEIPT_AGGREGATION_MISMATCH"


def test_compare_rejects_action_without_corresponding_stage_receipt(
    tmp_path: Path,
) -> None:
    module = _load_runner()
    baseline = _write_comparable_manifest(
        module,
        tmp_path / "baseline",
        implementation_sha256="b" * 64,
        wall_ratio=1.0,
        token_ratio=1.0,
    )
    candidate = _write_comparable_manifest(
        module,
        tmp_path / "candidate",
        implementation_sha256="c" * 64,
        wall_ratio=0.6,
        token_ratio=0.6,
    )
    manifest = _read_json(candidate)
    sample = next(
        item
        for item in manifest["samples"]
        if item["scenarioId"] == "small-greenfield"
    )
    source_hash = next(
        value
        for value in sample["receiptSha256s"]
        if _read_json(
            candidate.parent
            / next(
                item["path"]
                for item in manifest["receiptIndex"]
                if item["sha256"] == value
            )
        )["granularity"]
        == "ACTION"
    )
    source_index = next(
        item for item in manifest["receiptIndex"] if item["sha256"] == source_hash
    )
    orphan = _read_json(candidate.parent / source_index["path"])
    orphan.update(
        {
            "receiptId": f"{orphan['receiptId']}-orphan-repair",
            "actionId": f"{orphan['actionId']}-orphan-repair",
            "stage": "REPAIR",
        }
    )
    _resign_receipt(orphan)
    orphan_path = candidate.parent / "receipts/orphan-repair-action.json"
    orphan_path.write_bytes(_canonical_json_bytes(orphan))
    orphan_sha256 = _sha256(orphan_path)
    manifest["receiptIndex"].append(
        {"path": "receipts/orphan-repair-action.json", "sha256": orphan_sha256}
    )
    sample["receiptSha256s"].append(orphan_sha256)
    candidate.write_bytes(_canonical_json_bytes(manifest))

    compared = _run_cli(
        "compare",
        "--policy",
        str(POLICY_PATH),
        "--baseline-manifest",
        str(baseline),
        "--candidate-manifest",
        str(candidate),
        "--output",
        str(tmp_path / "comparison.json"),
    )

    assert compared.returncode == 2
    assert json.loads(compared.stdout)["code"] == "RECEIPT_ACTION_STAGE_ORPHANED"


def test_compare_requires_declared_success_action_and_stage_coverage(
    tmp_path: Path,
) -> None:
    module = _load_runner()
    baseline = _write_comparable_manifest(
        module,
        tmp_path / "baseline",
        implementation_sha256="b" * 64,
        wall_ratio=1.0,
        token_ratio=1.0,
    )
    candidate = _write_comparable_manifest(
        module,
        tmp_path / "candidate",
        implementation_sha256="c" * 64,
        wall_ratio=0.6,
        token_ratio=0.6,
    )
    manifest = _read_json(candidate)
    target_sample = next(
        item
        for item in manifest["samples"]
        if item["scenarioId"] == "small-greenfield"
    )
    indexed = {
        str(item["sha256"]): item for item in manifest["receiptIndex"]
    }
    removed = next(
        value
        for value in target_sample["receiptSha256s"]
        if _read_json(candidate.parent / indexed[str(value)]["path"])["granularity"]
        == "ACTION"
        and _read_json(candidate.parent / indexed[str(value)]["path"])["stage"]
        == "R3"
    )
    target_sample["receiptSha256s"].remove(removed)
    manifest["receiptIndex"].remove(indexed[str(removed)])
    candidate.write_bytes(_canonical_json_bytes(manifest))

    compared = _run_cli(
        "compare",
        "--policy",
        str(POLICY_PATH),
        "--baseline-manifest",
        str(baseline),
        "--candidate-manifest",
        str(candidate),
        "--output",
        str(tmp_path / "comparison.json"),
    )

    assert compared.returncode == 2
    assert json.loads(compared.stdout)["code"] == "RECEIPT_ACTION_COVERAGE_INCOMPLETE"


def test_classified_sample_produces_serializable_fail_comparison_receipt(
    tmp_path: Path,
) -> None:
    module = _load_runner()
    baseline = _write_comparable_manifest(
        module,
        tmp_path / "baseline",
        implementation_sha256="b" * 64,
        wall_ratio=1.0,
        token_ratio=1.0,
    )
    candidate = _write_comparable_manifest(
        module,
        tmp_path / "candidate",
        implementation_sha256="c" * 64,
        wall_ratio=0.6,
        token_ratio=0.6,
    )
    manifest = _read_json(candidate)
    failed_sample = next(
        item
        for item in manifest["samples"]
        if item["scenarioId"] == "small-greenfield"
    )
    failed_sample["status"] = "FAILED_CLASSIFIED"
    failed_sample["failureCount"] = 1
    failed_sample["timeToFailureMilliseconds"] = 400
    failed_sample.pop("readyForApprovalMilliseconds")
    candidate.write_bytes(_canonical_json_bytes(manifest))
    failed_sample_id = str(failed_sample["sampleId"])

    def make_unusable(receipt: dict[str, object]) -> None:
        outcome = receipt["outcome"]
        assert isinstance(outcome, dict)
        outcome.update(
            {
                "semanticCorrectnessPassed": False,
                "usable": False,
                "code": "MODEL_EXECUTION_FAILED",
            }
        )

    _mutate_indexed_receipts(
        candidate,
        lambda receipt: receipt["sampleId"] == failed_sample_id,
        make_unusable,
    )
    output = tmp_path / "comparison.json"
    compared = _run_cli(
        "compare",
        "--policy",
        str(POLICY_PATH),
        "--baseline-manifest",
        str(baseline),
        "--candidate-manifest",
        str(candidate),
        "--output",
        str(output),
    )

    assert compared.returncode == 2, compared.stderr or compared.stdout
    receipt = _read_json(output)
    assert receipt["verdict"] == "FAIL"
    assert receipt["metrics"] == {
        "fullCompileTokenRatio": None,
        "fullCompileP50WallRatio": None,
        "postReviewP50WallRatio": None,
        "reviewTokenRatio": None,
    }
    assert receipt["checks"]["allReceiptsUsable"] is False


def test_satisfied_policy_is_derived_from_exact_pass_receipt_evidence(
    tmp_path: Path,
) -> None:
    module = _load_runner()
    baseline = _write_comparable_manifest(
        module,
        tmp_path / "baseline",
        implementation_sha256="b" * 64,
        wall_ratio=1.0,
        token_ratio=1.0,
    )
    candidate = _write_comparable_manifest(
        module,
        tmp_path / "candidate",
        implementation_sha256="c" * 64,
        wall_ratio=0.6,
        token_ratio=0.6,
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(_canonical_json_bytes(_read_json(POLICY_PATH)))
    comparison_path = tmp_path / "comparison.json"
    compared = _run_cli(
        "compare",
        "--policy",
        str(policy_path),
        "--baseline-manifest",
        str(baseline),
        "--candidate-manifest",
        str(candidate),
        "--output",
        str(comparison_path),
    )
    assert compared.returncode == 0, compared.stderr or compared.stdout

    policy = _read_json(policy_path)
    policy["pairedBenchmarkGate"].update(
        {
            "status": "SATISFIED",
            "claimStatus": "ALLOWED_AFTER_TARGET_EVALUATION",
            "baselineManifest": "baseline/manifest.json",
            "candidateManifest": "candidate/manifest.json",
            "comparisonReceipt": {
                "path": "comparison.json",
                "sha256": _sha256(comparison_path),
            },
        }
    )
    policy_path.write_bytes(_canonical_json_bytes(policy))
    validated = _run_cli(
        "validate-policy", "--policy", str(policy_path)
    )

    assert validated.returncode == 0, validated.stderr or validated.stdout
    assert json.loads(validated.stdout) == {
        "claimStatus": "ALLOWED_AFTER_TARGET_EVALUATION",
        "status": "VALID",
        "verdict": "PASS",
    }

    policy["pairedBenchmarkGate"]["comparisonReceipt"]["sha256"] = "0" * 64
    policy_path.write_bytes(_canonical_json_bytes(policy))
    rejected = _run_cli(
        "validate-policy", "--policy", str(policy_path)
    )
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["code"] == "COMPARISON_RECEIPT_HASH_MISMATCH"


def test_semantically_correct_but_slow_token_heavy_or_retry_amplified_sample_is_not_usable() -> None:
    module = _load_runner()
    policy = {
        "actionBudget": {"maxWallMilliseconds": 100, "maxTotalTokens": 100},
        "hardLimits": {
            "maxHydrationRoundsPerAction": 2,
            "maxExecutionAttemptsPerShard": 2,
            "maxSemanticRepairRoundsPerProposition": 2,
            "maxAdjudicationsPerProposition": 1,
            "maxReviewReshardDepth": 2,
            "maxPhysicalShardsPerLogicalTheme": 8,
        },
    }
    for mutation in ("wall", "tokens", "retries"):
        receipt = _valid_receipt()
        if mutation == "wall":
            receipt["timing"]["totalMilliseconds"] = 101
        elif mutation == "tokens":
            receipt["usage"]["inputTokens"] = 101
        else:
            receipt["work"]["modelAttempts"] = 3
            receipt["work"]["retries"] = 2
        assessed = module.assess_receipt(receipt, policy)
        assert assessed["outcome"]["semanticCorrectnessPassed"] is True
        assert assessed["outcome"]["usable"] is False
        assert assessed["outcome"]["code"] == "MODEL_EFFICIENCY_FAILED"


def test_classified_failure_receipts_are_reassessed_for_derived_granularity() -> None:
    module = _load_runner()
    policy = _read_json(POLICY_PATH)
    failure = _valid_receipt()
    failure["timing"]["totalMilliseconds"] = 500_000
    failure["work"]["failures"] = 1
    failure["outcome"].update(
        {
            "semanticCorrectnessPassed": False,
            "noWasteAmplification": False,
            "usable": False,
            "code": "MODEL_EXECUTION_FAILED",
        }
    )
    _resign_receipt(failure)

    action = module._derive_classified_receipt(
        failure,
        granularity="ACTION",
        stage="CONTROL_PLANE",
        action_id="action-classified",
        policy=policy,
    )
    run = module._derive_classified_receipt(
        failure,
        granularity="RUN",
        stage="RUN",
        action_id=None,
        policy=policy,
    )

    assert action["outcome"]["wallBudgetPassed"] is False
    assert action["outcome"]["usable"] is False
    assert run["outcome"]["wallBudgetPassed"] is True


def test_model_incident_and_optimization_decision_require_global_root_cause_and_options() -> None:
    incident = {
        "contract": "ai-sow-model-efficiency-incident-v1",
        "incidentId": "incident-001",
        "firstFailedReceiptSha256": SHA256,
        "classification": "PLUGIN_DEFECT",
        "firstCostDivergence": "STAGE_1 packet 重复包含同一来源块。",
        "criticalPath": [{"stage": "STAGE_1", "wallMilliseconds": 120, "critical": True}],
        "tokenFlow": [{"stage": "STAGE_1", "inputTokens": 100, "outputTokens": 20, "controlPlaneTokens": 10, "toolContextTokens": 5}],
        "reworkGraph": [{"from": "STAGE_1", "to": "STAGE_2", "reason": "上游遗漏导致重编译"}],
        "sharedRootCause": "来源证据未按内容 hash 去重，导致跨阶段重复输入。",
        "affectedStages": ["STAGE_1", "STAGE_2", "R1"],
        "stoppedBeforeNextWork": True,
    }
    decision = {
        "contract": "ai-sow-model-optimization-decision-v1",
        "decisionId": "decision-001",
        "incidentSha256": SHA256,
        "options": [
            {"optionId": "no-change", "kind": "NO_CHANGE", "systemChange": "保持现状", "expectedWallDeltaRatio": 0, "expectedTokenDeltaRatio": 0, "risks": ["继续超预算"]},
            {"optionId": "dedupe", "kind": "SYSTEM_OPTIMIZATION", "systemChange": "按内容 hash 去重 packet", "expectedWallDeltaRatio": -0.2, "expectedTokenDeltaRatio": -0.3, "risks": ["需验证 coverage"]},
            {"optionId": "reshard", "kind": "SYSTEM_OPTIMIZATION", "systemChange": "重分 source shards", "expectedWallDeltaRatio": -0.15, "expectedTokenDeltaRatio": -0.1, "risks": ["增加 join"]},
        ],
        "selectedOptionId": "dedupe",
        "expectedNetBenefit": "减少跨阶段重复证据且不改变 coverage roots。",
        "costShiftChecks": {"stage1": True, "downstreamReview": True, "office": True, "promote": True, "controlPlane": True, "retryRework": True},
        "ownerClosure": ["scope_compiler", "final_review"],
        "semanticGuards": ["coverageSha256 不变"],
        "privacyGuards": ["receipt 不保存来源正文"],
        "recoveryGuards": ["从原失败 action 恢复"],
        "validationPlan": ["原 action", "Owner 回归", "Batch gate"],
        "rollbackConditions": ["任何 coverage root 丢失"],
    }
    _validate("model-efficiency-incident.schema.json", incident)
    _validate("model-optimization-decision.schema.json", decision)
    invalid_incident = deepcopy(incident)
    invalid_incident.pop("sharedRootCause")
    with pytest.raises(jsonschema.ValidationError):
        _validate("model-efficiency-incident.schema.json", invalid_incident)
    invalid_decision = deepcopy(decision)
    invalid_decision["options"] = invalid_decision["options"][:2]
    with pytest.raises(jsonschema.ValidationError):
        _validate("model-optimization-decision.schema.json", invalid_decision)
