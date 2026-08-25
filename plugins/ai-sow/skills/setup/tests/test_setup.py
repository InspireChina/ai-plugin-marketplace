from __future__ import annotations

import json
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest


SKILL_ROOT = Path(__file__).parents[1]
SCRIPT = SKILL_ROOT / "scripts/setup.py"
TEMPLATE = SKILL_ROOT / "assets/sow-template.xlsx"


def test_skill_uses_current_stage_without_leaf_agents() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "当前 Stage Agent 是本 Skill 的唯一用户接口" in skill
    assert "直接运行" in skill
    for forbidden in ("Orchestrator Agent", "Worker Agent", "Validator Agent", "Reviewer Agent"):
        assert forbidden not in skill


def run_setup(
    project_root: Path,
    *extra: str,
    no_site: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if no_site:
        command.append("-S")
    command.extend(
        [
            str(SCRIPT),
            "--project-root",
            str(project_root),
            "--project-id",
            "bookstore-modernization",
            "--name",
            "在线书店 2.0",
            *extra,
        ]
    )
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        cwd=project_root,
        env=os.environ,
    )


def test_bundled_template_round_trips_and_contains_authoritative_catalog() -> None:
    payload = TEMPLATE.read_bytes()
    workbook = openpyxl.load_workbook(BytesIO(payload), data_only=False)
    try:
        tables = {
            name: worksheet.tables[name]
            for worksheet in workbook.worksheets
            for name in worksheet.tables
        }
        catalog = tables["BaseUnitCatalogTable"]
        min_col, min_row, _, max_row = openpyxl.utils.range_boundaries(catalog.ref)
        assert max_row - min_row == 37
        family_column = [column.name for column in catalog.tableColumns].index("任务族名称")
        worksheet = next(
            sheet for sheet in workbook.worksheets if "BaseUnitCatalogTable" in sheet.tables
        )
        families = {
            worksheet.cell(row, min_col + family_column).value
            for row in range(min_row + 1, max_row + 1)
        }
        assert len(families) == 13
        saved = BytesIO()
        workbook.save(saved)
    finally:
        workbook.close()
    reopened = openpyxl.load_workbook(BytesIO(saved.getvalue()), data_only=False)
    reopened.close()


def test_setup_creates_exact_minimal_project_shell(tmp_path: Path) -> None:
    result = run_setup(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "OK"
    assert json.loads((tmp_path / ".ai-sow/project.json").read_text()) == {
        "projectId": "bookstore-modernization",
        "name": "在线书店 2.0",
        "pluginVersion": "0.1.0-beta.2",
        "sowStandardVersion": "1.3",
    }
    assert (tmp_path / ".ai-sow/templates/sow-template.xlsx").read_bytes() == TEMPLATE.read_bytes()
    for relative in ("inputs", "work", "reviews", "data", "validation", "outputs"):
        assert (tmp_path / ".ai-sow" / relative).is_dir()


def test_complete_existing_project_is_read_only_idempotent(tmp_path: Path) -> None:
    assert run_setup(tmp_path).returncode == 0
    project = tmp_path / ".ai-sow/project.json"
    template = tmp_path / ".ai-sow/templates/sow-template.xlsx"
    before = (project.read_bytes(), template.read_bytes(), project.stat().st_mtime_ns)
    result = run_setup(tmp_path)
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["outcome"] == "OK"
    assert (project.read_bytes(), template.read_bytes(), project.stat().st_mtime_ns) == before


@pytest.mark.parametrize("missing", ["templates/sow-template.xlsx", "reviews"])
def test_incomplete_existing_project_blocks_without_repair(tmp_path: Path, missing: str) -> None:
    assert run_setup(tmp_path).returncode == 0
    target = tmp_path / ".ai-sow" / missing
    if target.is_dir():
        target.rmdir()
    else:
        target.unlink()
    project_before = (tmp_path / ".ai-sow/project.json").read_bytes()
    result = run_setup(tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)["outcome"] == "BLOCKED"
    assert not target.exists()
    assert (tmp_path / ".ai-sow/project.json").read_bytes() == project_before


def test_existing_identity_conflict_blocks(tmp_path: Path) -> None:
    assert run_setup(tmp_path).returncode == 0
    project = tmp_path / ".ai-sow/project.json"
    value = json.loads(project.read_text())
    value["name"] = "其他项目"
    project.write_text(json.dumps(value, ensure_ascii=False))
    result = run_setup(tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)["outcome"] == "BLOCKED"


def test_existing_valid_customized_project_template_is_read_only(tmp_path: Path) -> None:
    assert run_setup(tmp_path).returncode == 0
    template = tmp_path / ".ai-sow/templates/sow-template.xlsx"
    workbook = openpyxl.load_workbook(template, data_only=False)
    try:
        workbook.properties.title = "项目级定制模板"
        workbook.save(template)
    finally:
        workbook.close()
    before = template.read_bytes()

    result = run_setup(tmp_path)

    assert result.returncode == 0, result.stdout
    assert template.read_bytes() == before


def test_existing_corrupt_project_template_blocks_without_overwrite(tmp_path: Path) -> None:
    assert run_setup(tmp_path).returncode == 0
    template = tmp_path / ".ai-sow/templates/sow-template.xlsx"
    template.write_bytes(b"conflict")
    result = run_setup(tmp_path)
    assert result.returncode == 2
    assert template.read_bytes() == b"conflict"


def test_fresh_setup_rejects_symlink_in_managed_path(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / ".ai-sow").symlink_to(outside, target_is_directory=True)
    result = run_setup(tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)["outcome"] == "BLOCKED"
    assert list(outside.iterdir()) == []


def test_setup_reports_missing_python_dependencies(tmp_path: Path) -> None:
    result = run_setup(tmp_path, no_site=True)
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "NEEDS_INPUT"
    assert "uv sync --project" in payload["nextStep"]
    assert not (tmp_path / ".ai-sow").exists()


def test_setup_rejects_removed_repair_option(tmp_path: Path) -> None:
    result = run_setup(tmp_path, "--repair")
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_setup_rejects_invalid_project_id_without_partial_manifest(tmp_path: Path) -> None:
    result = run_setup(tmp_path, "--project-id", "Invalid")
    assert result.returncode == 2
    assert json.loads(result.stdout)["outcome"] == "BLOCKED"
    assert not (tmp_path / ".ai-sow/project.json").exists()
