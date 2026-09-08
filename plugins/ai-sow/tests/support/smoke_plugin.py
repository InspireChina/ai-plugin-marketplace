#!/usr/bin/env python3
"""Exercise the host-neutral NextAction pipeline from a standalone plugin copy."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import jsonschema
import openpyxl


CASE_MANIFEST_PATH = "tests/fixtures/explicit-architecture/case-manifest.json"
CASE_SCHEMA_PATH = "tests/contracts/case-manifest.schema.json"
E2E_DRIVER_PATH = "skills/generate/tests/test_e2e.py"
EXPECTED_SHEETS = ["01-需求故事", "02-任务清单", "03-工作量汇总", "90-估算标准"]
EXPECTED_TABLES = {
    "SOWStoryTable",
    "TaskTable",
    "ProjectSummaryTable",
    "ProjectParameterTable",
    "TaskStandardTable",
}



def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(_canonical_json_bytes(value))
    os.replace(temporary, path)


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def plugin_uv_command(plugin_root: Path) -> str:
    local_uv = plugin_root / ".ai-sow-tools" / "bin" / (
        "uv.exe" if os.name == "nt" else "uv"
    )
    if local_uv.is_file():
        return str(local_uv)
    return shutil.which("uv") or "uv"


def plugin_python_command(plugin_root: Path) -> str:
    return str(
        plugin_root
        / ".venv"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )


def _run_checked(command: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            "subprocess failed: "
            + command[0]
            + f" (exit={completed.returncode})"
        )
    return completed


def _case_manifest(plugin_root: Path) -> dict[str, dict[str, object]]:
    manifest = _load_json(plugin_root / CASE_MANIFEST_PATH)
    schema = _load_json(plugin_root / CASE_SCHEMA_PATH)
    jsonschema.Draft202012Validator(schema).validate(manifest)
    return {
        str(case["caseId"]): dict(case)
        for case in manifest["cases"]
        if isinstance(case, Mapping)
    }


def _tree_digests(root: Path) -> dict[str, str]:
    ignored_parts = {".venv", ".ai-sow-tools", ".pytest_cache", "__pycache__"}
    return {
        path.relative_to(root).as_posix(): _sha256(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not ignored_parts.intersection(path.relative_to(root).parts)
        and path.suffix not in {".pyc", ".pyo"}
    }


def _load_e2e_driver(plugin_root: Path):
    path = plugin_root / E2E_DRIVER_PATH
    spec = importlib.util.spec_from_file_location(
        f"ai_sow_copy_e2e_{os.getpid()}", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load copied NextAction E2E driver")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _generation_files(project: Path, manifest: Mapping[str, object]) -> set[str]:
    root = project / ".ai-sow/generations" / str(manifest["generationId"])
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def _generation_file_digests(generations_root: Path) -> dict[str, str]:
    return {
        path.relative_to(generations_root).as_posix(): _sha256(path.read_bytes())
        for path in sorted(generations_root.rglob("*"))
        if path.is_file()
    }


def _verify_generation_template_path(
    manifest: Mapping[str, object], generation_root: Path
) -> Path:
    generation_id = str(manifest["generationId"])
    if generation_root.name != generation_id:
        raise RuntimeError("generation root does not match manifest generationId")
    template = generation_root / "input/sow-template.xlsx"
    if not template.is_file() or _sha256(template.read_bytes()) != manifest.get(
        "templateSha256"
    ):
        raise RuntimeError("generation template does not match manifest hash")
    return template


def _verify_workbook(path: Path) -> None:
    workbook = openpyxl.load_workbook(path, data_only=False)
    try:
        if workbook.sheetnames != EXPECTED_SHEETS:
            raise RuntimeError("generated workbook sheet contract changed")
        tables = {name for sheet in workbook.worksheets for name in sheet.tables}
        if tables != EXPECTED_TABLES:
            raise RuntimeError("generated workbook table contract changed")
        if not any(
            cell.data_type == "f"
            for sheet in workbook.worksheets
            for row in sheet.iter_rows()
            for cell in row
        ):
            raise RuntimeError("generated workbook contains no formulas")
    finally:
        workbook.close()
    calculated = openpyxl.load_workbook(path, data_only=True)
    try:
        values = [calculated["03-工作量汇总"][f"B{row}"].value for row in range(5, 9)]
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in values
        ):
            raise RuntimeError("generated workbook lacks calculated summary values")
    finally:
        calculated.close()


def _verify_generation(project: Path) -> dict[str, object]:
    current = _load_json(project / ".ai-sow/current.json")
    manifest_path = project / str(current["generationManifestPath"])
    manifest_payload = manifest_path.read_bytes()
    if _sha256(manifest_payload) != current["generationManifestSha256"]:
        raise RuntimeError("current pointer does not bind generation manifest")
    manifest = _load_json(manifest_path)
    from generation_store import load_current
    from runtime.project_io import ProjectFiles
    loaded = load_current(ProjectFiles.open(project))
    if loaded is None or loaded.generation_id != manifest['generationId']:
        raise RuntimeError("published generation proof closure is invalid")
    _verify_generation_template_path(manifest, manifest_path.parent)
    for path_field, hash_field in (
        ("sowModelPath", "sowModelSha256"),
        ("workbookPath", "workbookSha256"),
        ("notesPath", "notesSha256"),
    ):
        target = project / str(manifest[path_field])
        if _sha256(target.read_bytes()) != manifest[hash_field]:
            raise RuntimeError(f"generation hash mismatch: {hash_field}")
    generation_root = manifest_path.parent
    artifact = _load_json(generation_root / "proof/artifact-manifest.json")
    verification = artifact.get("workbookVerification")
    if not isinstance(verification, Mapping) or verification.get("trustState") != "VERIFIED":
        raise RuntimeError("candidate workbook lacks trusted Office verification")
    workbook = project / str(manifest["workbookPath"])
    _verify_workbook(workbook)
    return {
        "generationId": manifest["generationId"],
        "workbookPath": str(workbook.resolve()),
        "notesPath": str((project / str(manifest["notesPath"])).resolve()),
        "officeEngine": {
            "name": verification["engineName"],
            "version": verification["engineVersion"],
        },
    }


def _change_template_bytes(driver, project: Path) -> None:
    target = project / ".ai-sow/templates/sow-template.xlsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(driver.SKILL_ROOT / "assets/sow-template.xlsx", target)
    with zipfile.ZipFile(target, "a") as archive:
        archive.comment = b"copy-smoke-template-change-v1"


def _approve(driver, project: Path, result: Mapping[str, object]) -> None:
    approved = driver.orchestrator_module.run_mode(
        project,
        "approve",
        artifact_manifest_sha256=str(result["artifactManifestSha256"]),
    )
    if approved.get("outcome") != "PUBLISHED":
        raise RuntimeError("approval did not publish the verified artifact")


def _worker_scenario(plugin_root: Path, project: Path, scenario: str) -> dict[str, object]:
    driver = _load_e2e_driver(plugin_root)
    invocations = []
    def fresh_submission(action, packet):
        request_bytes = driver.orchestrator_module.read_provider_request(project, action['actionId'])
        request = json.loads(request_bytes)
        completed = subprocess.run(
            [sys.executable, str(plugin_root / 'tests/support/fresh_fixture_worker.py')],
            input=_canonical_json_bytes({'request': request, 'kind': action['actionContractId'][:-3]}),
            cwd=project, capture_output=True, check=False,
        )
        if completed.returncode:
            raise RuntimeError('fresh fixture worker failed: ' + completed.stderr.decode('utf-8'))
        response = json.loads(completed.stdout)
        facts = response['invocation']
        if (facts['pid'] == os.getpid() or facts['contextMode'] != 'FRESH_NO_HISTORY'
                or facts['requestSha256'] != _sha256(request_bytes)
                or facts['maxOutputTokens'] != action['executionLimits']['maxOutputTokens']
                or facts['actualProviderVerified'] is not False):
            raise RuntimeError('fresh fixture invocation binding mismatch')
        invocations.append(facts)
        return response['result']
    project.mkdir(parents=True, exist_ok=True)
    if scenario in {"greenfield", "brownfield"}:
        result, trace = driver.drive_fixture_host(project, scenario, fresh_submission)
    elif scenario == "input-recovery":
        request_path = driver._prepare_project(project, "greenfield")
        started = driver.orchestrator_module.run_mode(
            project, "start", request=request_path, budget_policy="budget.json"
        )
        old_run_id = started["state"]["runId"]
        driver.orchestrator_module.run_mode(project, "abandon")
        request = driver._load(project / request_path)
        request["project"]["name"] = "匿名恢复路径项目"
        driver._write_json(project / request_path, request)
        resumed = driver.orchestrator_module.run_mode(
            project, "start", request=request_path, budget_policy="budget.json"
        )
        if resumed.get("state", {}).get("runId") == old_run_id:
            raise RuntimeError("input recovery did not create a new immutable run")
        result, trace = driver.drive_result_host(project, resumed, fresh_submission)
        old_states = [
            driver._load(path)
            for path in (
                project / f".ai-sow/work/runs/{old_run_id}/states"
            ).glob("state-*.json")
        ]
        if not any(
            state.get("phase") == "DONE"
            and state.get("result") == "ABANDONED"
            for state in old_states
        ):
            raise RuntimeError("input recovery did not retain the old terminal state")
    else:
        raise RuntimeError(f"unknown worker scenario: {scenario}")
    if result.get("outcome") != "REQUEST_APPROVAL":
        raise RuntimeError("NextAction host loop did not reach REQUEST_APPROVAL")
    _approve(driver, project, result)
    generations = [_verify_generation(project)]
    report: dict[str, object] = {
        "scenario": scenario,
        "outcome": "PUBLISHED",
        "actionCount": len(trace),
        "actionContracts": sorted({action["actionContractId"] for action in trace}),
        "freshContextOnly": len(invocations) == len(trace) and bool(invocations),
        "fixtureProcessIsolation": "ONE_PROCESS_PER_ACTION",
        "actualProviderVerified": False,
    }
    if scenario == "greenfield":
        fresh_runs = []
        previous_run_ids = {str(result["state"]["runId"])}
        for change in ("same-input", "template-bytes", "business-input"):
            if change == "template-bytes":
                _change_template_bytes(driver, project)
            elif change == "business-input":
                request = driver._load(project / "request.json")
                request["project"]["name"] = "匿名复制安装完整重编译"
                driver._write_json(project / "request.json", request)
            current_before = (project / ".ai-sow/current.json").read_bytes()
            started = driver.orchestrator_module.run_mode(
                project, "start", request="request.json", budget_policy="budget.json"
            )
            state = started.get("state", {})
            if state.get("route") != "FULL_COMPILE" or state.get("runId") in previous_run_ids:
                raise RuntimeError("new explicit request must start a fresh FULL_COMPILE run")
            if (project / ".ai-sow/current.json").read_bytes() != current_before:
                raise RuntimeError("new compilation changed last-known-good before approval")
            previous_run_ids.add(state["runId"])
            prepared, fresh_trace = driver.drive_result_host(project, started, fresh_submission)
            required = {"SOURCE_SCOPE-v1", "STORY_DESIGN-v1", "TASK_ESTIMATION-v1"}
            if not required <= {action["actionContractId"] for action in fresh_trace}:
                raise RuntimeError("fresh run did not independently review all three stages")
            if len(invocations) != len(trace) + sum(item['actionCount'] for item in fresh_runs) + len(fresh_trace):
                raise RuntimeError('every action must have its own fresh fixture process')
            _approve(driver, project, prepared)
            generations.append(_verify_generation(project))
            fresh_runs.append({"change": change, "route": state["route"],
                               "outcome": "PUBLISHED", "actionCount": len(fresh_trace)})
        report["freshRuns"] = fresh_runs
    report["generations"] = generations
    return report


def _worker_environment(
    active_plugin: Path, project: Path, audit_root: Path, audit_log: Path
) -> dict[str, str]:
    temporary_root = project / ".ai-sow/work/smoke-temp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "PYTHONPATH": str(audit_root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "AI_SOW_ALLOWED_READ_ROOTS": os.pathsep.join(
            (str(active_plugin), str(project))
        ),
        "AI_SOW_FORBIDDEN_READ_LOG": str(audit_log),
        "TMPDIR": str(temporary_root),
        "TEMP": str(temporary_root),
        "TMP": str(temporary_root),
    }
    office = (
        os.environ.get("AI_SOW_OFFICE_BIN")
        or shutil.which("soffice")
        or shutil.which("libreoffice")
    )
    if office:
        environment["AI_SOW_OFFICE_BIN"] = str(Path(office).expanduser().resolve())
    return environment


def _run_worker(
    active_plugin: Path,
    project: Path,
    scenario: str,
    audit_root: Path,
    audit_log: Path,
) -> dict[str, object]:
    command = [
        plugin_python_command(active_plugin),
        str(active_plugin / "tests/support/smoke_plugin.py"),
        "--worker-scenario",
        scenario,
        "--plugin-root",
        str(active_plugin),
        "--project-root",
        str(project),
    ]
    completed = subprocess.run(
        command,
        cwd=project.parent,
        capture_output=True,
        check=False,
        env=_worker_environment(active_plugin, project, audit_root, audit_log),
    )
    output_root = project / ".ai-sow/work/smoke-host"
    _write_bytes(output_root / f"{scenario}.stdout.bin", completed.stdout)
    _write_bytes(output_root / f"{scenario}.stderr.bin", completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(
            f"copy worker failed: {scenario} (exit={completed.returncode})"
        )
    try:
        lines = [
            line
            for line in completed.stdout.decode("utf-8").splitlines()
            if line.strip()
        ]
    except UnicodeDecodeError as error:
        raise RuntimeError("copy worker output was not UTF-8") from error
    if len(lines) != 1:
        raise RuntimeError("copy worker did not emit exactly one JSON result")
    value = json.loads(lines[0])
    if not isinstance(value, dict):
        raise RuntimeError("copy worker result was not a JSON object")
    return value


def _run_smoke(
    plugin_root: Path,
    work_dir: Path,
    copy_plugin: bool,
) -> dict[str, object]:
    source_plugin = plugin_root.resolve(strict=True)
    if copy_plugin:
        active_plugin = work_dir / "installed/ai-sow"
        active_plugin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source_plugin,
            active_plugin,
            ignore=shutil.ignore_patterns(
                ".venv", ".ai-sow-tools", ".pytest_cache", "__pycache__", "*.pyc"
            ),
        )
    else:
        active_plugin = source_plugin
    manifest = _load_json(active_plugin / ".codex-plugin/plugin.json")
    if manifest.get("name") != "ai-sow":
        raise RuntimeError("copied plugin manifest name mismatch")
    _run_checked(
        [
            plugin_uv_command(source_plugin),
            "sync",
            "--project",
            str(active_plugin),
            "--locked",
        ],
        work_dir,
    )
    cases = _case_manifest(active_plugin)
    plugin_before = _tree_digests(active_plugin)
    projects_root = work_dir / "customer-projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    audit_root = active_plugin / "tests/support/read_guard"
    audit_log = work_dir / "forbidden-reads.log"
    reports = {
        scenario: _run_worker(
            active_plugin,
            projects_root / scenario,
            scenario,
            audit_root,
            audit_log,
        )
        for scenario in ("greenfield", "brownfield", "input-recovery")
    }
    for case_id, case in cases.items():
        report = reports[case_id]
        if not set(case["requiredActionContracts"]) <= set(report["actionContracts"]):
            raise RuntimeError(f"copy smoke mandatory Action coverage missing: {case_id}")
    if not all(report["freshContextOnly"] for report in reports.values()):
        raise RuntimeError("copy smoke observed inherited conversational context")
    if _tree_digests(active_plugin) != plugin_before:
        raise RuntimeError("runtime modified the installed plugin copy")
    forbidden_reads = (
        audit_log.read_text(encoding="utf-8").splitlines()
        if audit_log.is_file()
        else []
    )
    if forbidden_reads:
        raise RuntimeError("runtime read outside copied plugin and customer project")
    generations = [
        generation
        for report in reports.values()
        for generation in report["generations"]
    ]
    return {
        "contract": "ai-sow-copy-smoke-report-v2",
        "pluginName": manifest["name"],
        "pluginVersion": manifest.get("version"),
        "pluginRoot": str(active_plugin.resolve()),
        "workDir": str(work_dir.resolve()),
        "publicSkills": ["generate"],
        "hostInterface": "PYTHON_API_NEXT_ACTION",
        "greenfieldOutcome": reports["greenfield"]["outcome"],
        "brownfieldOutcome": reports["brownfield"]["outcome"],
        "blockedResumeOutcome": reports["input-recovery"]["outcome"],
        "freshRuns": reports["greenfield"]["freshRuns"],
        "freshContextOnly": all(report['freshContextOnly'] for report in reports.values()),
        "fixtureProcessIsolation": "ONE_PROCESS_PER_ACTION",
        "actualProviderVerified": False,
        "marketplaceReadCount": 0,
        "projectRoots": [
            str((projects_root / scenario).resolve()) for scenario in reports
        ],
        "workbookPaths": [item["workbookPath"] for item in generations],
        "officeEngines": [item["officeEngine"] for item in generations],
    }


def run_smoke(
    plugin_root: Path,
    work_dir: Path,
    copy_plugin: bool,
) -> dict[str, object]:
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        report = _run_smoke(plugin_root, work_dir, copy_plugin)
    except Exception as error:
        receipt = {
            "contract": "ai-sow-copy-smoke-failure-v1",
            "status": "FAILED",
            "errorType": type(error).__name__,
            "summary": str(error),
            "workDir": str(work_dir),
        }
        _write_json(work_dir / "failure-receipt.json", receipt)
        raise
    _write_json(work_dir / "smoke-report.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plugin-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--copy-plugin", action="store_true")
    parser.add_argument("--worker-scenario")
    parser.add_argument("--project-root", type=Path)
    args = parser.parse_args(argv)
    if args.worker_scenario:
        if args.project_root is None:
            parser.error("--worker-scenario requires --project-root")
        report = _worker_scenario(
            args.plugin_root.resolve(),
            args.project_root.resolve(),
            args.worker_scenario,
        )
        print(json.dumps(report, ensure_ascii=False))
        return 0
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="ai-sow-smoke-"))
    try:
        report = run_smoke(args.plugin_root, work_dir, args.copy_plugin)
    except Exception:
        receipt_path = work_dir.resolve() / "failure-receipt.json"
        if receipt_path.is_file():
            print(receipt_path.read_text(encoding="utf-8").strip(), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
