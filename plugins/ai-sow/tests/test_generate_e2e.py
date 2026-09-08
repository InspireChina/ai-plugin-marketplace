from __future__ import annotations

TEST_LAYER = "integration"

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

PLUGIN_ROOT = Path(__file__).parents[1]
TEST_ROOT = PLUGIN_ROOT / "tests"
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from support import smoke_plugin  # noqa: E402
from support.smoke_plugin import run_smoke  # noqa: E402


CASE_MANIFEST = PLUGIN_ROOT / "tests/fixtures/explicit-architecture/case-manifest.json"
CASE_SCHEMA = PLUGIN_ROOT / "tests/contracts/case-manifest.schema.json"


def test_case_manifest_is_single_skill_and_schema_valid() -> None:
    manifest = json.loads(CASE_MANIFEST.read_text(encoding="utf-8"))
    schema = json.loads(CASE_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(manifest)
    assert {case["mode"] for case in manifest["cases"]} == {
        "GREENFIELD",
        "BROWNFIELD",
    }
    assert "owner" not in json.dumps(manifest).lower()
    for case in manifest["cases"]:
        for key, value in case.items():
            if key.endswith("Path"):
                assert (PLUGIN_ROOT / value).exists(), (key, value)


@pytest.fixture(scope="module")
def smoke_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    return run_smoke(
        PLUGIN_ROOT,
        tmp_path_factory.mktemp("generate-copy-smoke"),
        copy_plugin=True,
    )


@pytest.mark.e2e
def test_copy_smoke_runs_both_project_modes_and_fresh_full_compiles(
    smoke_report: dict[str, object],
) -> None:
    assert smoke_report["pluginName"] == "ai-sow"
    assert smoke_report["publicSkills"] == ["generate"]
    assert smoke_report["greenfieldOutcome"] == "PUBLISHED"
    assert smoke_report["brownfieldOutcome"] == "PUBLISHED"
    assert smoke_report["blockedResumeOutcome"] == "PUBLISHED"
    assert {run["change"] for run in smoke_report["freshRuns"]} == {"same-input", "template-bytes", "business-input"}
    assert all(run["route"] == "FULL_COMPILE" and run["outcome"] == "PUBLISHED" and run["actionCount"] > 0 for run in smoke_report["freshRuns"])
    assert smoke_report["hostInterface"] == "PYTHON_API_NEXT_ACTION"
    assert smoke_report["freshContextOnly"] is True


@pytest.mark.e2e
def test_copy_plugin_never_reads_marketplace_or_writes_outside_project_and_plugin(
    smoke_report: dict[str, object],
) -> None:
    assert smoke_report["marketplaceReadCount"] == 0
    assert smoke_report["hostInterface"] == "PYTHON_API_NEXT_ACTION"
    plugin_root = Path(smoke_report["pluginRoot"]).resolve()
    for project in smoke_report["projectRoots"]:
        assert Path(project).resolve().is_relative_to(
            Path(smoke_report["workDir"]).resolve()
        )
        assert not Path(project).resolve().is_relative_to(plugin_root)


def test_smoke_failure_writes_receipt_before_exit_and_preserves_work_dir(
    tmp_path: Path,
) -> None:
    work_dir = tmp_path / "failed-copy-smoke"
    with pytest.raises(FileNotFoundError):
        run_smoke(tmp_path / "missing-plugin", work_dir, copy_plugin=True)

    receipt = json.loads(
        (work_dir / "failure-receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["status"] == "FAILED"
    assert receipt["workDir"] == str(work_dir.resolve())
    assert work_dir.is_dir()


def test_copy_worker_temp_and_failure_outputs_are_project_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = tmp_path / "installed/ai-sow"
    project = tmp_path / "customer-project"
    audit_root = plugin / "tests/support/read_guard"
    audit_log = tmp_path / "forbidden.log"
    project.mkdir()
    environment = smoke_plugin._worker_environment(
        plugin, project, audit_root, audit_log
    )
    expected_temp = str(project / ".ai-sow/work/smoke-temp")
    assert environment["TMPDIR"] == expected_temp
    assert environment["TEMP"] == expected_temp
    assert environment["TMP"] == expected_temp

    office = tmp_path / "bin/soffice"
    monkeypatch.delenv("AI_SOW_OFFICE_BIN", raising=False)
    monkeypatch.setattr(
        smoke_plugin.shutil,
        "which",
        lambda command: str(office) if command == "soffice" else None,
    )
    environment = smoke_plugin._worker_environment(
        plugin, project, audit_root, audit_log
    )
    assert environment["AI_SOW_OFFICE_BIN"] == str(office.resolve())

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout=b"worker-out", stderr=b"worker-error"
        ),
    )
    with pytest.raises(RuntimeError):
        smoke_plugin._run_worker(
            plugin, project, "greenfield", audit_root, audit_log
        )
    output_root = project / ".ai-sow/work/smoke-host"
    assert (output_root / "greenfield.stdout.bin").read_bytes() == b"worker-out"
    assert (output_root / "greenfield.stderr.bin").read_bytes() == b"worker-error"


@pytest.mark.e2e
def test_copy_smoke_outputs_remain_in_customer_projects(
    smoke_report: dict[str, object],
) -> None:
    project_roots = [Path(value).resolve() for value in smoke_report["projectRoots"]]
    plugin_root = Path(smoke_report["pluginRoot"]).resolve()
    for value in smoke_report["workbookPaths"]:
        workbook = Path(value).resolve()
        assert workbook.is_file()
        assert any(workbook.is_relative_to(root) for root in project_roots)
        assert not workbook.is_relative_to(plugin_root)
