from __future__ import annotations

TEST_LAYER = "integration"

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).parent / "support/run_validation_campaign.py"


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(root: Path, locators: list[str]) -> str:
    entries: list[dict[str, str]] = []
    for locator in sorted(locators):
        path = root / locator
        files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
        for file_path in files:
            display = Path(locator) if path.is_file() else Path(locator) / file_path.relative_to(path)
            entries.append({"path": display.as_posix(), "sha256": sha256(file_path)})
    return hashlib.sha256(canonical(entries)).hexdigest()


def campaign_fixture(root: Path, commands: list[dict[str, object]]) -> tuple[Path, Path]:
    locked = root / "locked.json"
    implementation = root / "implementation.py"
    locked.write_text("locked\n", encoding="utf-8")
    implementation.write_text("implementation\n", encoding="utf-8")
    categories = (
        "businessInputs",
        "caseManifests",
        "typedSubmissions",
        "goldens",
        "rubrics",
        "schemas",
        "templateAuthorities",
        "driversAndAssertions",
        "thresholds",
    )
    lock = {
        "contract": "ai-sow-validation-lock-v1",
        "lockId": "lock-test",
        "entries": [
            {"category": category, "path": "locked.json", "sha256": sha256(locked)}
            for category in categories
        ],
    }
    lock_path = root / "validation-lock.json"
    write_json(lock_path, lock)
    manifest = {
        "contract": "ai-sow-validation-campaign-manifest-v1",
        "campaignId": "campaign-test",
        "validationLockPath": "validation-lock.json",
        "validationLockSha256": sha256(lock_path),
        "implementationPaths": ["implementation.py"],
        "worktreeAllowlist": [],
        "commands": commands,
    }
    manifest_path = root / "campaign.json"
    write_json(manifest_path, manifest)
    return manifest_path, root / "campaign-work"


def command(
    command_id: str,
    code: str,
    *,
    expected_exit_codes: list[int] | None = None,
    expected_outcomes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "kind": "COMMAND",
        "commandId": command_id,
        "scenarioId": "scenario-one",
        "sampleIndex": 0,
        "cacheMode": "NONE",
        "checkpointId": command_id,
        "argv": [sys.executable, "-c", code],
        "expectedExitCodes": expected_exit_codes or [0],
        "expectedOutcomes": expected_outcomes or [],
        "stateSnapshotPaths": [],
    }


def run_campaign(
    operation: str,
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), operation, *arguments],
        cwd=REPO_ROOT,
        env={**os.environ, **(env or {})},
        capture_output=True,
        check=False,
    )


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def environment_classification(work: Path, command_id: str = "failure") -> Path:
    path = work / "root-cause.json"
    write_json(
        path,
        {
            "contract": "ai-sow-validation-classification-v1",
            "classification": "ENVIRONMENT_FAILURE",
            "rootCause": "测试环境条件缺失。",
            "ownerModule": "environment",
            "resumeCommandId": command_id,
            "remediationPlan": "恢复环境条件。",
            "remediationReceiptPath": "environment-remediation.json",
            "replacementValidationLockPath": None,
        },
    )
    return path


def classify_environment(work: Path, command_id: str = "failure") -> None:
    classification_path = environment_classification(work, command_id)
    assert (
        run_campaign(
            "classify",
            "--work-dir",
            str(work),
            "--classification-file",
            str(classification_path),
        ).returncode
        == 0
    )
    write_json(
        work / "environment-remediation.json",
        {
            "contract": "ai-sow-environment-remediation-v1",
            "failureReceiptSha256": sha256(work / "failure-receipt.json"),
            "status": "READY_TO_RESUME",
        },
    )


def plugin_campaign_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    ready = root / "ready"
    manifest, work = campaign_fixture(
        root,
        [
            command(
                "failure",
                f"from pathlib import Path; raise SystemExit(0 if Path({str(ready)!r}).exists() else 1)",
            )
        ],
    )
    product = root / "product"
    product.mkdir()
    implementation = product / "implementation.py"
    implementation.write_text("value = 'before'\n", encoding="utf-8")
    campaign = read_json(manifest)
    campaign["implementationPaths"] = ["product"]
    write_json(manifest, campaign)
    return manifest, work, implementation, ready


def classify_plugin(work: Path) -> None:
    classification_path = work / "root-cause.json"
    write_json(
        classification_path,
        {
            "contract": "ai-sow-validation-classification-v1",
            "classification": "PLUGIN_DEFECT",
            "rootCause": "产品实现没有覆盖该边界条件。",
            "ownerModule": "generate/runtime",
            "resumeCommandId": "failure",
            "remediationPlan": "先冻结最小复现，再修复 Owner 实现并运行回归。",
            "remediationReceiptPath": "plugin-remediation.json",
            "replacementValidationLockPath": None,
        },
    )
    assert (
        run_campaign(
            "classify",
            "--work-dir",
            str(work),
            "--classification-file",
            str(classification_path),
        ).returncode
        == 0
    )


def write_execution_receipt(
    path: Path,
    *,
    role: str,
    outcome: str,
    implementation_sha256: str,
    test_id: str,
    reproduction_sha256: str,
) -> None:
    write_json(
        path,
        {
            "contract": "ai-sow-validation-execution-receipt-v1",
            "role": role,
            "outcome": outcome,
            "implementationTreeSha256": implementation_sha256,
            "testId": test_id,
            "reproductionSha256": reproduction_sha256,
        },
    )


def write_plugin_remediation(
    root: Path,
    work: Path,
    implementation: Path,
    *,
    change_product: bool,
) -> None:
    failure = read_json(work / "failure-receipt.json")
    failure_sha256 = sha256(work / "failure-receipt.json")
    reproduction = root / "product/test_reproduction.py"
    reproduction.write_text("def test_regression():\n    assert True\n", encoding="utf-8")
    reproduction_sha256 = sha256(reproduction)
    reproduction_tree_sha256 = tree_sha256(root, ["product"])
    write_json(
        work / "reproduction-freeze.json",
        {
            "contract": "ai-sow-reproduction-freeze-v1",
            "failureReceiptSha256": failure_sha256,
            "baseImplementationTreeSha256": failure["implementationTreeSha256"],
            "reproductionTreeSha256": reproduction_tree_sha256,
            "extensionPath": "product/test_reproduction.py",
            "extensionSha256": reproduction_sha256,
            "appendOnly": True,
        },
    )
    write_execution_receipt(
        work / "red.json",
        role="MINIMAL_REPRODUCTION",
        outcome="FAILED",
        implementation_sha256=reproduction_tree_sha256,
        test_id="test_regression",
        reproduction_sha256=reproduction_sha256,
    )
    if change_product:
        implementation.write_text("value = 'after'\n", encoding="utf-8")
    current_tree_sha256 = tree_sha256(root, ["product"])
    write_execution_receipt(
        work / "green.json",
        role="MINIMAL_REPRODUCTION",
        outcome="PASSED",
        implementation_sha256=current_tree_sha256,
        test_id="test_regression",
        reproduction_sha256=reproduction_sha256,
    )
    write_execution_receipt(
        work / "owner.json",
        role="OWNER_REGRESSION",
        outcome="PASSED",
        implementation_sha256=current_tree_sha256,
        test_id="owner-regression",
        reproduction_sha256=reproduction_sha256,
    )
    write_execution_receipt(
        work / "batch.json",
        role="BATCH_GATE",
        outcome="PASSED",
        implementation_sha256=current_tree_sha256,
        test_id="batch-gate",
        reproduction_sha256=reproduction_sha256,
    )
    write_json(
        work / "plugin-remediation.json",
        {
            "contract": "ai-sow-plugin-remediation-v1",
            "failureReceiptSha256": failure_sha256,
            "status": "READY_TO_RESUME",
            "preFixImplementationTreeSha256": failure["implementationTreeSha256"],
            "postFixImplementationTreeSha256": current_tree_sha256,
            "redTestId": "test_regression",
            "greenTestId": "test_regression",
            "verificationReceiptPaths": {
                "reproductionFreeze": "reproduction-freeze.json",
                "red": "red.json",
                "green": "green.json",
                "ownerRegression": "owner.json",
                "batchGate": "batch.json",
            },
        },
    )


def test_validation_campaign_stops_before_next_command_after_first_failure(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.txt"
    third = tmp_path / "third.txt"
    manifest, work = campaign_fixture(
        tmp_path,
        [
            command("first", f"from pathlib import Path; Path({str(first)!r}).write_text('ok')"),
            command("failure", "raise SystemExit(7)"),
            command("third", f"from pathlib import Path; Path({str(third)!r}).write_text('bad')"),
        ],
    )

    result = run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work))

    assert result.returncode == 2
    assert first.is_file()
    assert not third.exists()
    assert (work / "failure-receipt.json").is_file()
    assert read_json(work / "state.json")["status"] == "FAILED_UNTRIAGED"


def test_expected_negative_outcome_is_pass_not_campaign_failure(tmp_path: Path) -> None:
    manifest, work = campaign_fixture(
        tmp_path,
        [
            command(
                "expected-block",
                "import json; print(json.dumps({'outcome':'BLOCKED'})); raise SystemExit(2)",
                expected_exit_codes=[2],
                expected_outcomes=["BLOCKED"],
            )
        ],
    )

    result = run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work))

    assert result.returncode == 0
    assert read_json(work / "state.json")["status"] == "COMPLETE"
    assert not (work / "failure-receipt.json").exists()


def test_failure_receipt_is_redacted_and_written_before_status_update(
    tmp_path: Path,
) -> None:
    secret = "PRIVATE_SOURCE_TEXT_SHOULD_NOT_BE_IN_RECEIPT"
    manifest, work = campaign_fixture(
        tmp_path,
        [command("failure", f"import sys; print({secret!r}); sys.exit(9)")],
    )

    result = run_campaign(
        "start",
        "--manifest",
        str(manifest),
        "--work-dir",
        str(work),
        env={"AI_SOW_CAMPAIGN_CRASH_AFTER_RECEIPT": "1"},
    )

    assert result.returncode != 0
    receipt_path = work / "failure-receipt.json"
    assert receipt_path.is_file()
    assert secret not in receipt_path.read_text(encoding="utf-8")
    receipt = read_json(receipt_path)
    for field in (
        "commandId",
        "scenarioId",
        "sampleIndex",
        "cacheMode",
        "lastSuccessfulCheckpoint",
        "exitCode",
        "stdoutSha256",
        "stderrSha256",
        "stateSnapshotSha256",
        "implementationTreeSha256",
        "environmentFingerprintSha256",
        "validationLockSha256",
    ):
        assert field in receipt

    blocked = run_campaign("resume", "--work-dir", str(work))
    assert blocked.returncode == 2
    assert read_json(receipt_path)["commandId"] == "failure"


def test_unclassified_failure_cannot_resume(tmp_path: Path) -> None:
    manifest, work = campaign_fixture(
        tmp_path,
        [command("failure", "raise SystemExit(1)")],
    )
    run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work))
    classification = {
        "contract": "ai-sow-validation-classification-v1",
        "classification": "UNCLASSIFIED",
        "rootCause": "尚未确定。",
        "ownerModule": "unknown",
        "resumeCommandId": "failure",
        "remediationPlan": "先定位根因。",
        "remediationReceiptPath": None,
        "replacementValidationLockPath": None,
    }
    path = work / "root-cause.json"
    write_json(path, classification)

    classified = run_campaign(
        "classify",
        "--work-dir",
        str(work),
        "--classification-file",
        str(path),
    )

    assert classified.returncode == 2
    assert read_json(work / "state.json")["status"] == "FAILED_UNTRIAGED"


def test_validation_lock_drift_blocks_resume(tmp_path: Path) -> None:
    flag = tmp_path / "ready"
    manifest, work = campaign_fixture(
        tmp_path,
        [command("failure", f"from pathlib import Path; raise SystemExit(0 if Path({str(flag)!r}).exists() else 1)")],
    )
    run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work))
    classification = {
        "contract": "ai-sow-validation-classification-v1",
        "classification": "ENVIRONMENT_FAILURE",
        "rootCause": "测试环境条件缺失。",
        "ownerModule": "environment",
        "resumeCommandId": "failure",
        "remediationPlan": "恢复环境条件。",
        "remediationReceiptPath": "environment-remediation.json",
        "replacementValidationLockPath": None,
    }
    classification_path = work / "root-cause.json"
    write_json(classification_path, classification)
    assert run_campaign(
        "classify", "--work-dir", str(work), "--classification-file", str(classification_path)
    ).returncode == 0
    write_json(
        work / "environment-remediation.json",
        {
            "contract": "ai-sow-environment-remediation-v1",
            "failureReceiptSha256": sha256(work / "failure-receipt.json"),
            "status": "READY_TO_RESUME",
        },
    )
    flag.touch()
    (tmp_path / "locked.json").write_text("drift\n", encoding="utf-8")

    resumed = run_campaign("resume", "--work-dir", str(work))

    assert resumed.returncode == 2
    assert read_json(work / "state.json")["status"] == "FAILED_CLASSIFIED"


def test_e2e_driver_stops_before_next_scenario_after_unexpected_failure(
    tmp_path: Path,
) -> None:
    later_scenario = tmp_path / "later-scenario.txt"
    first = command("scenario-a", "raise SystemExit(4)")
    first["scenarioId"] = "scenario-a"
    second = command(
        "scenario-b",
        f"from pathlib import Path; Path({str(later_scenario)!r}).write_text('ran')",
    )
    second["scenarioId"] = "scenario-b"
    manifest, work = campaign_fixture(tmp_path, [first, second])

    assert run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work)).returncode == 2
    assert not later_scenario.exists()
    assert read_json(work / "failure-receipt.json")["scenarioId"] == "scenario-a"


def test_failure_receipt_is_written_before_driver_raises_and_preserves_work_dir(
    tmp_path: Path,
) -> None:
    manifest, work = campaign_fixture(tmp_path, [command("failure", "raise SystemExit(5)")])

    result = run_campaign(
        "start",
        "--manifest",
        str(manifest),
        "--work-dir",
        str(work),
        env={"AI_SOW_CAMPAIGN_CRASH_AFTER_RECEIPT": "1"},
    )

    assert result.returncode != 0
    assert work.is_dir()
    assert (work / "failure-receipt.json").is_file()
    assert (work / "commands/0000-failure/stderr.bin").is_file()


def test_failure_receipt_captures_scenario_checkpoint_environment_and_hashes(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "project-state.json"
    snapshot.write_text("state\n", encoding="utf-8")
    failing = command("failure", "raise SystemExit(6)")
    failing["scenarioId"] = "brownfield-one"
    failing["sampleIndex"] = 3
    failing["cacheMode"] = "COLD"
    failing["checkpointId"] = "stage-two"
    failing["stateSnapshotPaths"] = ["project-state.json"]
    manifest, work = campaign_fixture(tmp_path, [failing])

    run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work))

    receipt = read_json(work / "failure-receipt.json")
    assert receipt["scenarioId"] == "brownfield-one"
    assert receipt["sampleIndex"] == 3
    assert receipt["cacheMode"] == "COLD"
    assert receipt["checkpointLocator"] == "stage-two"
    for field in (
        "stdoutSha256",
        "stderrSha256",
        "stateSnapshotSha256",
        "implementationTreeSha256",
        "environmentFingerprintSha256",
        "validationLockSha256",
    ):
        assert len(str(receipt[field])) == 64
    assert receipt["stateSnapshotInventory"] == [
        {"path": "project-state.json", "sha256": sha256(snapshot)}
    ]


def test_failure_receipt_presence_blocks_progress_after_crash_before_status_update(
    tmp_path: Path,
) -> None:
    later = tmp_path / "later.txt"
    manifest, work = campaign_fixture(
        tmp_path,
        [
            command("failure", "raise SystemExit(1)"),
            command("later", f"from pathlib import Path; Path({str(later)!r}).write_text('ran')"),
        ],
    )
    run_campaign(
        "start",
        "--manifest",
        str(manifest),
        "--work-dir",
        str(work),
        env={"AI_SOW_CAMPAIGN_CRASH_AFTER_RECEIPT": "1"},
    )

    assert read_json(work / "state.json")["status"] == "RUNNING"
    assert run_campaign("resume", "--work-dir", str(work)).returncode == 2
    assert not later.exists()


def test_resume_starts_at_failed_checkpoint_or_scenario_not_scenario_zero(
    tmp_path: Path,
) -> None:
    count = tmp_path / "count.txt"
    ready = tmp_path / "ready.txt"
    complete = tmp_path / "complete.txt"
    increment = (
        "from pathlib import Path; "
        f"p=Path({str(count)!r}); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"
    )
    failure = (
        "from pathlib import Path; "
        f"raise SystemExit(0 if Path({str(ready)!r}).exists() else 1)"
    )
    manifest, work = campaign_fixture(
        tmp_path,
        [
            command("scenario-zero", increment),
            command("failure", failure),
            command("complete", f"from pathlib import Path; Path({str(complete)!r}).write_text('ok')"),
        ],
    )
    assert run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work)).returncode == 2
    classify_environment(work)
    ready.touch()

    assert run_campaign("resume", "--work-dir", str(work)).returncode == 0
    assert count.read_text(encoding="utf-8") == "1"
    assert complete.is_file()
    state = read_json(work / "state.json")
    assert state["status"] == "COMPLETE"
    assert state["failureHistory"][0]["resumeCommandIndex"] == 1


def test_validation_lock_covers_inputs_fixtures_goldens_rubric_thresholds_and_driver(
    tmp_path: Path,
) -> None:
    manifest, work = campaign_fixture(tmp_path, [command("pass", "pass")])
    lock_path = tmp_path / "validation-lock.json"
    lock = read_json(lock_path)
    lock["entries"] = lock["entries"][:-1]
    write_json(lock_path, lock)
    campaign = read_json(manifest)
    campaign["validationLockSha256"] = sha256(lock_path)
    write_json(manifest, campaign)

    result = run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work))

    assert result.returncode == 2
    assert not (work / "state.json").exists()


def test_resume_rejects_locked_input_or_oracle_drift(tmp_path: Path) -> None:
    test_validation_lock_drift_blocks_resume(tmp_path)


def test_plugin_defect_resume_requires_red_green_owner_and_batch_receipts(
    tmp_path: Path,
) -> None:
    manifest, work, implementation, ready = plugin_campaign_fixture(tmp_path)
    assert run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work)).returncode == 2
    classify_plugin(work)
    implementation.write_text("value = 'after'\n", encoding="utf-8")
    ready.touch()
    write_json(
        work / "plugin-remediation.json",
        {
            "contract": "ai-sow-plugin-remediation-v1",
            "failureReceiptSha256": sha256(work / "failure-receipt.json"),
            "status": "READY_TO_RESUME",
            "redTestId": "test_regression",
            "greenTestId": "test_regression",
            "verificationReceiptSha256s": {
                "reproductionFreeze": "0" * 64,
                "red": "1" * 64,
                "green": "2" * 64,
                "ownerRegression": "3" * 64,
                "batchGate": "4" * 64,
            },
        },
    )

    assert run_campaign("resume", "--work-dir", str(work)).returncode == 2
    assert (work / "failure-receipt.json").is_file()


def test_plugin_defect_allows_only_pre_fix_append_only_reproduction_extension_and_rejects_test_only_fix(
    tmp_path: Path,
) -> None:
    manifest, work, implementation, ready = plugin_campaign_fixture(tmp_path)
    assert run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work)).returncode == 2
    classify_plugin(work)
    write_plugin_remediation(tmp_path, work, implementation, change_product=False)
    ready.touch()

    assert run_campaign("resume", "--work-dir", str(work)).returncode == 2
    assert read_json(work / "state.json")["status"] == "FAILED_CLASSIFIED"


def test_plugin_defect_with_frozen_reproduction_and_product_fix_resumes(
    tmp_path: Path,
) -> None:
    manifest, work, implementation, ready = plugin_campaign_fixture(tmp_path)
    assert run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work)).returncode == 2
    classify_plugin(work)
    write_plugin_remediation(tmp_path, work, implementation, change_product=True)
    ready.touch()

    assert run_campaign("resume", "--work-dir", str(work)).returncode == 0
    assert read_json(work / "state.json")["status"] == "COMPLETE"


def test_fixture_or_harness_fix_invalidates_affected_results(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    manifest, work = campaign_fixture(
        tmp_path,
        [
            command("completed-before-failure", "pass"),
            command(
                "failure",
                f"from pathlib import Path; raise SystemExit(0 if Path({str(ready)!r}).exists() else 1)",
            ),
        ],
    )
    assert run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work)).returncode == 2
    classification_path = work / "root-cause.json"
    write_json(
        classification_path,
        {
            "contract": "ai-sow-validation-classification-v1",
            "classification": "FIXTURE_DEFECT",
            "rootCause": "fixture 中的预期值不符合已经批准的来源。",
            "ownerModule": "tests/fixtures",
            "resumeCommandId": "failure",
            "remediationPlan": "审批替代 lock 并失效旧结果。",
            "remediationReceiptPath": "oracle-remediation.json",
            "replacementValidationLockPath": "replacement-validation-lock.json",
        },
    )
    assert (
        run_campaign(
            "classify",
            "--work-dir",
            str(work),
            "--classification-file",
            str(classification_path),
        ).returncode
        == 0
    )
    write_json(
        work / "oracle-remediation.json",
        {
            "contract": "ai-sow-oracle-remediation-v1",
            "failureReceiptSha256": sha256(work / "failure-receipt.json"),
            "status": "READY_TO_RESUME",
        },
    )
    replacement_input = work / "replacement-locked.json"
    replacement_input.write_text("approved replacement\n", encoding="utf-8")
    categories = [
        "businessInputs",
        "caseManifests",
        "typedSubmissions",
        "goldens",
        "rubrics",
        "schemas",
        "templateAuthorities",
        "driversAndAssertions",
        "thresholds",
    ]
    replacement_lock = work / "replacement-validation-lock.json"
    write_json(
        replacement_lock,
        {
            "contract": "ai-sow-validation-lock-v1",
            "lockId": "approved-replacement",
            "entries": [
                {
                    "category": category,
                    "path": "replacement-locked.json",
                    "sha256": sha256(replacement_input),
                }
                for category in categories
            ],
        },
    )
    (tmp_path / "locked.json").write_text("corrected fixture\n", encoding="utf-8")
    ready.touch()

    assert run_campaign("resume", "--work-dir", str(work)).returncode == 0
    state = read_json(work / "state.json")
    assert state["invalidatedResultIndexes"] == [0]
    assert state["results"][0]["valid"] is False
    assert state["validationLockSha256"] == sha256(replacement_lock)


def test_e2e_and_enablement_tools_have_no_update_golden_mode(tmp_path: Path) -> None:
    manifest, work = campaign_fixture(tmp_path, [command("forbidden", "pass")])
    campaign = read_json(manifest)
    campaign["commands"][0]["argv"].append("--update-golden")
    write_json(manifest, campaign)

    result = run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work))
    benchmark_help = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "support/analyze_historical_benchmark.py"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    campaign_help = run_campaign("--help")

    assert result.returncode == 2
    assert b"--update-golden" not in campaign_help.stdout
    assert benchmark_help.returncode == 0
    assert "--update-golden" not in benchmark_help.stdout


def test_worktree_gate_fails_on_unplanned_or_temp_files(tmp_path: Path) -> None:
    manifest, work = campaign_fixture(tmp_path, [command("pass", "pass")])
    campaign = read_json(manifest)
    campaign["worktreeAllowlist"] = ["permitted.txt"]
    write_json(manifest, campaign)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=AI SOW Test",
            "-c",
            "user.email=ai-sow-test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "unplanned.tmp").write_text("temporary\n", encoding="utf-8")

    result = run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work))

    assert result.returncode == 2
    assert b"unplanned.tmp" in result.stdout
    assert not (work / "state.json").exists()


def test_worktree_gate_matches_non_ascii_paths_without_git_quoting(tmp_path: Path) -> None:
    manifest, work = campaign_fixture(tmp_path, [command("pass", "pass")])
    campaign = read_json(manifest)
    campaign["worktreeAllowlist"] = ["资料/**"]
    write_json(manifest, campaign)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=AI SOW Test",
            "-c",
            "user.email=ai-sow-test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    source = tmp_path / "资料" / "规范.md"
    source.parent.mkdir()
    source.write_text("输入\n", encoding="utf-8")

    result = run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work))

    assert result.returncode == 0, result.stdout.decode("utf-8")


def test_implementation_tree_ignores_runtime_cache_artifacts(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    cache = tmp_path / "product" / "__pycache__" / "generated.pyc"
    manifest, work = campaign_fixture(
        tmp_path,
        [
            command(
                "cache-producing-failure",
                (
                    "from pathlib import Path; "
                    f"cache=Path({str(cache)!r}); "
                    "cache.parent.mkdir(parents=True, exist_ok=True); "
                    "cache.write_bytes(b'generated'); "
                    f"raise SystemExit(0 if Path({str(ready)!r}).exists() else 1)"
                ),
            )
        ],
    )
    product = tmp_path / "product"
    product.mkdir()
    (product / "implementation.py").write_text("value = 'stable'\n", encoding="utf-8")
    campaign = read_json(manifest)
    campaign["implementationPaths"] = ["product"]
    write_json(manifest, campaign)

    assert run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work)).returncode == 2
    classify_environment(work, "cache-producing-failure")
    ready.touch()

    resumed = run_campaign("resume", "--work-dir", str(work))

    assert resumed.returncode == 0, resumed.stdout.decode("utf-8")


def test_validation_lock_cannot_overlap_mutable_implementation_paths(
    tmp_path: Path,
) -> None:
    manifest, work = campaign_fixture(tmp_path, [command("pass", "pass")])
    campaign = read_json(manifest)
    campaign["implementationPaths"] = ["locked.json"]
    write_json(manifest, campaign)

    result = run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work))

    assert result.returncode == 2
    assert "不得重叠" in result.stdout.decode("utf-8")
    assert not (work / "state.json").exists()


def test_user_checkpoint_pauses_without_failure_and_resumes_after_hash_bound_receipts(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "candidate.md"
    artifact.write_text("candidate\n", encoding="utf-8")
    completed = tmp_path / "completed"
    checkpoint = {
        "kind": "USER_CHECKPOINT",
        "commandId": "approve-candidate",
        "scenarioId": "scenario-one",
        "sampleIndex": 0,
        "cacheMode": "NONE",
        "checkpointId": "candidate-approval",
        "argv": [],
        "artifactPath": "candidate.md",
        "requiredReceiptContract": "ai-sow-test-approval-v1",
        "receiptPath": "approval.json",
    }
    manifest, work = campaign_fixture(
        tmp_path,
        [
            command("prepare", "pass"),
            checkpoint,
            command("after-approval", f"from pathlib import Path; Path({str(completed)!r}).touch()"),
        ],
    )

    assert run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work)).returncode == 0
    assert read_json(work / "state.json")["status"] == "AWAITING_USER_CHECKPOINT"
    assert not (work / "failure-receipt.json").exists()
    assert not completed.exists()
    write_json(
        work / "approval.json",
        {
            "contract": "ai-sow-test-approval-v1",
            "artifactSha256": sha256(artifact),
            "independent": True,
        },
    )

    assert run_campaign("resume", "--work-dir", str(work)).returncode == 0
    assert completed.is_file()
    state = read_json(work / "state.json")
    assert state["status"] == "COMPLETE"
    assert [result["commandId"] for result in state["results"]] == [
        "prepare",
        "approve-candidate",
        "after-approval",
    ]


def test_cleanup_requires_complete_archived_campaign_and_targets_exact_work_dir(
    tmp_path: Path,
) -> None:
    manifest, work = campaign_fixture(tmp_path, [command("pass", "pass")])
    assert run_campaign("start", "--manifest", str(manifest), "--work-dir", str(work)).returncode == 0
    archive = tmp_path / "archive.json"
    assert (
        run_campaign(
            "cleanup", "--work-dir", str(work), "--archive", str(archive)
        ).returncode
        == 2
    )
    assert work.is_dir()
    assert (
        run_campaign(
            "archive", "--work-dir", str(work), "--output", str(archive)
        ).returncode
        == 0
    )
    sibling = tmp_path / "sibling"
    sibling.mkdir()

    assert (
        run_campaign(
            "cleanup", "--work-dir", str(work), "--archive", str(archive)
        ).returncode
        == 0
    )
    assert not work.exists()
    assert sibling.is_dir()
