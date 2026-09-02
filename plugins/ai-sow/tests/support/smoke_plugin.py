#!/usr/bin/env python3
"""Exercise the AI SOW plugin from a standalone plugin directory."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def run_command(command: list[str], cwd: Path) -> dict[str, object]:
    """Run a command from a user project and return its final JSON object."""
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        rendered = " ".join(command)
        raise RuntimeError(
            f"command failed ({completed.returncode}): {rendered}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if lines:
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return payload
    return {"outcome": "OK", "stdout": completed.stdout}


def plugin_uv_command(plugin_root: Path) -> str:
    """Resolve uv the way the runtime contract does: plugin-local copy first, then PATH."""
    local_uv = plugin_root / ".ai-sow-tools" / "bin" / (
        "uv.exe" if os.name == "nt" else "uv"
    )
    if local_uv.is_file():
        return str(local_uv)
    return shutil.which("uv") or "uv"


def plugin_python_command(
    plugin_root: Path,
    script: Path,
    *args: str,
) -> list[str]:
    """Build the cross-platform command published by the installed Skills."""
    python_bin = plugin_root / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    return [
        str(python_bin),
        str(script),
        *args,
    ]


def _require_ok(result: dict[str, object], label: str) -> None:
    if result.get("outcome") != "OK":
        raise RuntimeError(f"{label} did not report OK: {result}")


def run_smoke(
    plugin_root: Path,
    work_dir: Path,
    copy_plugin: bool,
) -> dict[str, object]:
    """Run setup, verify all Owner receipts, and generate outside the plugin."""
    source_plugin = plugin_root.resolve(strict=True)
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    if copy_plugin:
        active_plugin = (
            work_dir
            / "cache"
            / "ai-plugin-marketplace"
            / "ai-sow"
            / "local"
        )
        active_plugin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source_plugin,
            active_plugin,
            ignore=shutil.ignore_patterns(
                ".venv",
                ".pytest_cache",
                "__pycache__",
                "*.pyc",
            ),
        )
    else:
        active_plugin = source_plugin

    manifest = json.loads(
        (active_plugin / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
    )
    if manifest.get("name") != "ai-sow":
        raise RuntimeError(f"unexpected plugin manifest: {manifest}")

    projects_root = work_dir / "projects"
    greenfield = projects_root / "greenfield"
    reviewed_fixture = projects_root / "reviewed-fixture"
    greenfield.mkdir(parents=True, exist_ok=True)

    sync_result = run_command(
        [
            plugin_uv_command(source_plugin),
            "sync",
            "--project",
            str(active_plugin),
            "--locked",
        ],
        cwd=greenfield,
    )
    _require_ok(sync_result, "uv sync")

    setup_script = active_plugin / "skills/setup/scripts/setup.py"
    setup_result = run_command(
        plugin_python_command(
            active_plugin,
            setup_script,
            "--project-root",
            ".",
            "--project-id",
            "smoke-greenfield",
            "--name",
            "Smoke Greenfield",
        ),
        cwd=greenfield,
    )
    _require_ok(setup_result, "setup")

    fixture_source = active_plugin / "skills/generate-sow/fixtures/project"
    shutil.copytree(fixture_source, reviewed_fixture)
    validator_skills = (
        "analyze-requirement",
        "analyze-as-is",
        "generate-design",
        "generate-story",
        "generate-task",
    )
    owner_receipts: list[dict[str, object]] = []
    for skill_name in validator_skills:
        receipt_path = reviewed_fixture / f".ai-sow/validation/{skill_name}.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        compilation = receipt.get("compilationReceipt", {})
        if (
            receipt.get("owner") != skill_name
            or receipt.get("passed") is not True
            or compilation.get("validatorContractVersion") != "0.3"
        ):
            raise RuntimeError(f"invalid fixture Owner receipt: {receipt_path}")
        owner_receipts.append(receipt)

    generate_script = active_plugin / "skills/generate-sow/scripts/generate_sow.py"
    generate_result = run_command(
        plugin_python_command(
            active_plugin,
            generate_script,
            "--project-root",
            ".",
        ),
        cwd=reviewed_fixture,
    )
    _require_ok(generate_result, "generate-sow")

    supplier_project = projects_root / "supplier-completion"
    supplier_project.mkdir(parents=True, exist_ok=True)
    supplier_asset = (
        active_plugin
        / "skills/complete-supplier-estimate/assets/supplier-estimate-input.xlsx"
    )
    formal_asset = active_plugin / "assets/sow-template.xlsx"
    if not supplier_asset.is_file() or not formal_asset.is_file():
        raise RuntimeError("supplier or formal workbook asset is missing")
    supplier_input = supplier_project / "supplier.xlsx"
    completed_workbook = supplier_project / "formal.xlsx"
    shutil.copyfile(supplier_asset, supplier_input)
    import openpyxl

    supplier_book = openpyxl.load_workbook(supplier_input, data_only=False)
    try:
        story_sheet = supplier_book["01-需求故事"]
        for column, value in enumerate(
            (
                "Smoke 需求",
                "Smoke 子需求",
                "Smoke Story",
                "是",
                "可验收",
                "Smoke 备注",
            ),
            start=1,
        ):
            story_sheet.cell(5, column).value = value
            story_sheet.cell(5, column).data_type = "s"
        task_sheet = supplier_book["02-任务清单"]
        for column, value in enumerate(
            (
                "Smoke 需求 > Smoke 子需求 > Smoke Story",
                "Smoke Task",
                "界面与交互",
                "新建",
                "M",
                "Smoke 任务备注",
            ),
            start=1,
        ):
            task_sheet.cell(5, column).value = value
            task_sheet.cell(5, column).data_type = "s"
        supplier_book.save(supplier_input)
    finally:
        supplier_book.close()

    completion_script = (
        active_plugin
        / "skills/complete-supplier-estimate/scripts/complete_supplier_estimate.py"
    )
    completion_result = run_command(
        plugin_python_command(
            active_plugin,
            completion_script,
            "--input",
            str(supplier_input),
            "--output",
            str(completed_workbook),
        ),
        cwd=supplier_project,
    )
    _require_ok(completion_result, "complete-supplier-estimate")
    completed_book = openpyxl.load_workbook(completed_workbook, data_only=False)
    try:
        completed_sheets = len(completed_book.sheetnames)
        completed_formula_cells = sum(
            cell.data_type == "f"
            for worksheet in completed_book.worksheets
            for row in worksheet.iter_rows()
            for cell in row
        )
        if completed_book.sheetnames != [
            "01-需求故事",
            "02-任务清单",
            "03-工作量汇总",
            "90-估算标准",
        ] or completed_formula_cells == 0:
            raise RuntimeError("completed workbook contract is invalid")
    finally:
        completed_book.close()

    setup_project = json.loads(
        (greenfield / ".ai-sow/project.json").read_text(encoding="utf-8")
    )
    asis = json.loads(
        (
            reviewed_fixture
            / ".ai-sow/data/analyze-as-is/asis.json"
        ).read_text(encoding="utf-8")
    )
    analysis_scope = asis.get("analysisScope", {})
    asis_owns_technical_intake = (
        set(setup_project) == {
            "projectId",
            "name",
            "pluginVersion",
            "sowStandardVersion",
        }
        and analysis_scope.get("mode") == "BROWNFIELD"
        and bool(analysis_scope.get("repositorySnapshots"))
        and bool(analysis_scope.get("priorSowSnapshots"))
    )
    if not asis_owns_technical_intake:
        raise RuntimeError("As-Is does not own the reviewed technical intake")

    workbooks = sorted((reviewed_fixture / ".ai-sow/outputs").glob("*/sow.xlsx"))
    if len(workbooks) != 1:
        raise RuntimeError(f"expected one generated workbook, found {workbooks}")
    workbook_path = workbooks[0].resolve()
    output_manifest = workbook_path.with_name("manifest.json")
    if not output_manifest.is_file():
        raise RuntimeError(f"missing output manifest: {output_manifest}")

    return {
        "pluginName": manifest["name"],
        "pluginVersion": manifest.get("version"),
        "pluginRoot": str(active_plugin),
        "workDir": str(work_dir),
        "greenfieldProject": str(greenfield),
        "reviewedProject": str(reviewed_fixture),
        "setupOutcome": setup_result["outcome"],
        "ownerReceiptCount": len(owner_receipts),
        "generateOutcome": generate_result["outcome"],
        "completionOutcome": completion_result["outcome"],
        "supplierWorkbookPath": str(supplier_input.resolve()),
        "completedWorkbookPath": str(completed_workbook.resolve()),
        "completedWorkbookSheets": completed_sheets,
        "completedFormulaCells": completed_formula_cells,
        "workbookPath": str(workbook_path),
        "manifestPath": str(output_manifest.resolve()),
        "asisOwnsTechnicalIntake": asis_owns_technical_intake,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--copy-plugin", action="store_true")
    args = parser.parse_args()
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="ai-sow-smoke-"))
    report = run_smoke(args.plugin_root, work_dir, args.copy_plugin)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
