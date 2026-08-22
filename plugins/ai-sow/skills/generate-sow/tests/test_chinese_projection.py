from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import openpyxl
from openpyxl.utils.cell import range_boundaries


SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
FIXTURE = SKILL_ROOT / "fixtures/project"
SCRIPT = SKILL_ROOT / "scripts/generate_sow.py"
HAN_CHARACTER = re.compile(r"[\u4e00-\u9fff]")


def generate_fixture_workbook(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    shutil.copytree(FIXTURE, project_root)
    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(PLUGIN_ROOT),
            "--locked",
            "python",
            str(SCRIPT),
            "--project-root",
            str(project_root),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "OK"
    assert len(payload["outputs"]) == 1
    workbook_path = Path(payload["outputs"][0]) / "sow.xlsx"
    assert workbook_path.is_file()
    return workbook_path


def table_column_values(
    workbook_path: Path, table_name: str, column_name: str
) -> list[object]:
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        for worksheet in workbook.worksheets:
            if table_name not in worksheet.tables:
                continue
            table = worksheet.tables[table_name]
            min_column, min_row, max_column, max_row = range_boundaries(table.ref)
            headers = [
                worksheet.cell(min_row, column).value
                for column in range(min_column, max_column + 1)
            ]
            column = min_column + headers.index(column_name)
            return [
                worksheet.cell(row, column).value for row in range(min_row + 1, max_row + 1)
            ]
    finally:
        workbook.close()
    raise AssertionError(f"missing table {table_name}")


def table_headers(workbook_path: Path, table_name: str) -> list[object]:
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        for worksheet in workbook.worksheets:
            if table_name not in worksheet.tables:
                continue
            table = worksheet.tables[table_name]
            min_column, min_row, max_column, _ = range_boundaries(table.ref)
            return [
                worksheet.cell(min_row, column).value
                for column in range(min_column, max_column + 1)
            ]
    finally:
        workbook.close()
    raise AssertionError(f"missing table {table_name}")


def assert_business_values_are_chinese(
    label: str, values: list[object]
) -> None:
    business_values = [value for value in values if isinstance(value, str) and value]
    assert business_values, f"{label} has no projected business values"
    missing_han = [value for value in business_values if not HAN_CHARACTER.search(value)]
    assert not missing_han, f"{label} lacks Chinese text: {missing_han}"


def test_smoke_workbook_projects_chinese_business_text_and_preserves_machine_tokens(
    tmp_path: Path,
) -> None:
    workbook_path = generate_fixture_workbook(tmp_path)
    business_columns = {
        "epics": table_column_values(workbook_path, "EpicTable", "需求描述"),
        "features": table_column_values(workbook_path, "FeatureTable", "场景/范围描述"),
        "stories": table_column_values(workbook_path, "SOWStoryTable", "Story名称"),
        "acceptance criteria": table_column_values(
            workbook_path, "AcceptanceCriterionTable", "验收结果"
        ),
        "tasks": table_column_values(workbook_path, "TaskTable", "任务说明"),
        "As-Is summaries": table_column_values(
            workbook_path, "AsIsTopicTable", "结论"
        ),
        "As-Is detail summaries": table_column_values(
            workbook_path, "AsIsDetailTable", "摘要/理由"
        ),
        "assumptions": table_column_values(
            workbook_path, "AssumptionRiskTable", "名称"
        ),
        "risks": table_column_values(
            workbook_path, "AssumptionRiskTable", "处理方式"
        ),
    }
    for label, values in business_columns.items():
        assert_business_values_are_chinese(label, values)

    assert {"假设", "风险"} <= set(
        table_column_values(workbook_path, "AssumptionRiskTable", "类型")
    )
    assert "BUSINESS" in table_column_values(
        workbook_path, "EpicTable", "需求类型"
    )
    assert "ASSESSED" in table_column_values(
        workbook_path, "AsIsTopicTable", "评估状态"
    )
    assert "EFFECTIVE_START" in table_column_values(
        workbook_path, "AsIsDetailTable", "记录类型"
    )
    assert "类型" not in table_headers(workbook_path, "SOWStoryTable")
    assert {
        "新建M档人天",
        "调整M档人天",
        "接入复用M档人天",
    } <= set(table_headers(workbook_path, "BaseUnitCatalogTable"))
    for column in ("新建M档人天", "调整M档人天", "接入复用M档人天"):
        values = table_column_values(workbook_path, "BaseUnitCatalogTable", column)
        assert all(
            value == "❌"
            or (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value > 0
            )
            for value in values
        )
    assert table_column_values(
        workbook_path, "ProjectParameterTable", "参数代码"
    )[:3] == ["K_COMPLEXITY_S", "K_COMPLEXITY_M", "K_COMPLEXITY_L"]
    assert len(table_column_values(workbook_path, "BaseUnitCatalogTable", "基础单元ID")) == 37
    assert set(table_column_values(workbook_path, "TaskTable", "Integration ID")) == {
        None,
        "integration-profile-api",
    }

    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        table_names = {
            name
            for worksheet in workbook.worksheets
            for name in worksheet.tables
        }
        assert "93-复杂度规则" not in workbook.sheetnames
        assert "BaseEffortTable" not in table_names
        assert "ComplexityRuleTable" not in table_names
    finally:
        workbook.close()
