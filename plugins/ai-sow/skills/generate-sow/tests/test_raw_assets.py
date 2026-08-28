from __future__ import annotations

import hashlib
from pathlib import Path

import openpyxl
from openpyxl.utils import range_boundaries
from openpyxl.worksheet.formula import ArrayFormula


GENERATE_SOW_TEMPLATE = Path(__file__).resolve().parents[1] / "fixtures/project/.ai-sow/templates/sow-template.xlsx"
SKILL_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_WORKBOOK = SKILL_ROOT.parent.parent / "docs/reference/SOW估算与生成示例_v1.3.xlsx"
EXPECTED_SHA256 = "6d3e97f08c98139a2f64502460c4bb88265b8aca572e991f9c662016edfa6049"
EXPECTED_SHEETS = [
    "00-使用说明",
    "01-需求",
    "02-子需求",
    "03-SOW主表",
    "04-验收条件",
    "05-任务明细",
    "06-集成点",
    "07-假设清单",
    "20-项目汇总",
    "90-系统现状",
    "91-项目参数",
    "92-基础人天",
]
EXPECTED_HEADERS = {
    "EpicTable": ["需求名称", "需求类型", "需求描述", "涉及系统/数据", "目标结果", "公共约束/范围外"],
    "FeatureTable": ["需求名称", "子需求名称", "场景/范围描述", "涉及系统/数据", "约束/NFR", "来源类型", "推断理由"],
    "SOWStoryTable": ["需求名称", "子需求名称", "故事名称", "UAT适用", "验收条件", "任务明细", "人天", "关联假设/风险名称", "假设/风险状态"],
    "AcceptanceCriterionTable": ["需求名称", "子需求名称", "故事名称", "验收条件名称"],
    "TaskTable": ["需求名称", "子需求名称", "故事名称", "任务名称", "基础单元名称", "任务族", "工作模式", "工作模式理由", "复杂度", "复杂度理由", "关联现状条目", "判断依据与备注", "基础人天", "复杂度倍率", "人天小计"],
    "IntegrationTable": ["需求名称", "子需求名称", "故事名称", "集成任务名称", "来源", "目标", "触发条件", "方向", "业务目的", "责任边界", "工作模式", "复杂度", "支持单价", "SIT人天"],
    "AssumptionRiskTable": ["假设/风险名称", "类型", "触发条件", "责任边界", "状态", "处理方式"],
    "AsIsDetailTable": ["主题名称", "现状条目名称", "现状描述", "起点可用性"],
}
FORMULA_COLUMNS = {
    "SOWStoryTable": {"需求名称", "验收条件", "任务明细", "人天", "假设/风险状态"},
    "AcceptanceCriterionTable": {"需求名称", "子需求名称"},
    "TaskTable": {"需求名称", "子需求名称", "任务族", "基础人天", "复杂度倍率", "人天小计"},
    "IntegrationTable": {"需求名称", "子需求名称", "工作模式", "复杂度", "支持单价", "SIT人天"},
}
RELATION_COLUMNS = {"IntegrationTable": {"故事名称", "集成任务名称"}}
PROTECTED_SHEETS = {"03-SOW主表", "04-验收条件", "05-任务明细", "06-集成点", "20-项目汇总"}


def workbook_signature(path: Path) -> tuple[list[str], dict[str, str], int]:
    workbook = openpyxl.load_workbook(path, data_only=False, read_only=False)
    try:
        tables = {
            name: worksheet.tables[name].ref
            for worksheet in workbook.worksheets
            for name in worksheet.tables
        }
        formulas = sum(
            cell.data_type == "f"
            for worksheet in workbook.worksheets
            for row in worksheet.iter_rows()
            for cell in row
        )
        return workbook.sheetnames, tables, formulas
    finally:
        workbook.close()


def table_headers(workbook: openpyxl.Workbook, table_name: str) -> list[str]:
    for worksheet in workbook.worksheets:
        if table_name in worksheet.tables:
            table = worksheet.tables[table_name]
            min_col, min_row, max_col, _ = range_boundaries(table.ref)
            return [
                str(worksheet.cell(min_row, column).value)
                for column in range(min_col, max_col + 1)
            ]
    raise AssertionError(f"missing table: {table_name}")


def table_body_cells(
    workbook: openpyxl.Workbook,
    table_name: str,
) -> tuple[openpyxl.worksheet.worksheet.Worksheet, dict[str, openpyxl.cell.cell.Cell]]:
    for worksheet in workbook.worksheets:
        if table_name in worksheet.tables:
            table = worksheet.tables[table_name]
            min_col, min_row, max_col, _ = range_boundaries(table.ref)
            return worksheet, {
                str(worksheet.cell(min_row, column).value): worksheet.cell(min_row + 1, column)
                for column in range(min_col, max_col + 1)
            }
    raise AssertionError(f"missing table: {table_name}")


def test_skill_local_template_copies_match_the_authoritative_fingerprint() -> None:
    assert hashlib.sha256(GENERATE_SOW_TEMPLATE.read_bytes()).hexdigest() == EXPECTED_SHA256
    sheets, tables, formulas = workbook_signature(GENERATE_SOW_TEMPLATE)
    assert len(sheets) == 12
    assert len(tables) == 11
    assert formulas == 142


def test_example_matches_generate_sow_template_contract() -> None:
    for path in (GENERATE_SOW_TEMPLATE, REFERENCE_WORKBOOK):
        workbook = openpyxl.load_workbook(path, data_only=False, read_only=False)
        try:
            assert workbook.sheetnames == EXPECTED_SHEETS
            for table_name, headers in EXPECTED_HEADERS.items():
                assert table_headers(workbook, table_name) == headers
        finally:
            workbook.close()


def test_dropdowns_are_name_based_and_chinese() -> None:
    expected = {
        ("01-需求", "B5:B104", '"业务,技术"'),
        ("02-子需求", "A5:A104", 'INDIRECT("\'01-需求\'!$A$5:$A$104")'),
        ("02-子需求", "F5:F104", '"来源输入,设计派生"'),
        ("03-SOW主表", "B5:B104", 'INDIRECT("\'02-子需求\'!$B$5:$B$104")'),
        ("03-SOW主表", "D5:D104", '"是,否"'),
        ("03-SOW主表", "H5:H104", 'INDIRECT("\'07-假设清单\'!$A$5:$A$104")'),
        ("04-验收条件", "C5:C104", 'INDIRECT("\'03-SOW主表\'!$C$5:$C$104")'),
        ("05-任务明细", "C5:C504", 'INDIRECT("\'03-SOW主表\'!$C$5:$C$104")'),
        ("05-任务明细", "E5:E504", 'INDIRECT("\'92-基础人天\'!$D$5:$D$41")'),
        ("05-任务明细", "G5:G504", '"新建,调整,接入复用"'),
        ("05-任务明细", "I5:I504", '"S,M,L"'),
        ("05-任务明细", "K5:K504", 'INDIRECT("AsIsDetailTable[现状条目名称]")'),
        ("06-集成点", "H5:H104", '"入站,出站"'),
        ("06-集成点", "J5:J104", '"内部,外部"'),
        ("07-假设清单", "B5:B104", '"假设,风险"'),
        ("07-假设清单", "E5:E104", '"已明确,待确认"'),
        ("90-系统现状", "A5:A1004", '"系统边界与参与方,能力与流程,应用与组件,集成与外部依赖,数据与存储,平台、环境与部署,安全与合规,运维与质量,交付与约束"'),
        ("90-系统现状", "D5:D1004", '"当前已存在,预计开工前具备"'),
    }
    for path in (GENERATE_SOW_TEMPLATE, REFERENCE_WORKBOOK):
        workbook = openpyxl.load_workbook(path, data_only=False, read_only=False)
        try:
            actual = {
                (worksheet.title, str(validation.sqref), str(validation.formula1))
                for worksheet in workbook.worksheets
                for validation in worksheet.data_validations.dataValidation
                if validation.type == "list"
            }
            assert actual == expected
        finally:
            workbook.close()


def test_formula_and_relation_columns_are_gray_locked_and_sheets_protected() -> None:
    for path in (GENERATE_SOW_TEMPLATE, REFERENCE_WORKBOOK):
        workbook = openpyxl.load_workbook(path, data_only=False, read_only=False)
        try:
            for sheet_name in PROTECTED_SHEETS:
                protection = workbook[sheet_name].protection
                assert protection.sheet is True
                assert protection.formatColumns is False
                assert protection.formatRows is False
                assert protection.formatCells is True
            assert workbook["07-假设清单"].protection.sheet is False
            assert workbook["90-系统现状"].protection.sheet is False
            for table_name in (
                "EpicTable",
                "FeatureTable",
                "SOWStoryTable",
                "AcceptanceCriterionTable",
                "TaskTable",
                "IntegrationTable",
                "AssumptionRiskTable",
            ):
                worksheet, cells = table_body_cells(workbook, table_name)
                locked = FORMULA_COLUMNS.get(table_name, set()) | RELATION_COLUMNS.get(table_name, set())
                for header, cell in cells.items():
                    assert cell.alignment.vertical == "center"
                    if header in locked:
                        assert cell.protection.locked is True
                        assert cell.fill.fgColor.rgb[-6:] == "F1F4F6"
                    else:
                        assert cell.protection.locked is False
                        assert cell.fill.fgColor.rgb[-6:] == "FFFFFF"
                if locked:
                    assert worksheet.protection.sheet is True
            asis_sheet = workbook["90-系统现状"]
            assert asis_sheet["A2"].protection.locked is False
            assert asis_sheet["A2"].fill.fgColor.rgb[-6:] == "FFFFFF"
            table = asis_sheet.tables["AsIsDetailTable"]
            min_col, min_row, max_col, max_row = range_boundaries(table.ref)
            headers = [
                asis_sheet.cell(min_row, column).value
                for column in range(min_col, max_col + 1)
            ]
            for row in range(min_row + 1, max_row + 1):
                for offset, header in enumerate(headers):
                    cell = asis_sheet.cell(row, min_col + offset)
                    assert cell.protection.locked is False
                    assert cell.fill.fill_type == "solid"
                    expected_fill = "FFF2CC" if header in {"主题名称", "起点可用性"} else "FFFFFF"
                    assert cell.fill.fgColor.rgb[-6:] == expected_fill
        finally:
            workbook.close()


def test_sow_story_aggregations_use_excel_2019_compatible_array_formulas() -> None:
    for path in (GENERATE_SOW_TEMPLATE, REFERENCE_WORKBOOK):
        workbook = openpyxl.load_workbook(path, data_only=False, read_only=False)
        try:
            worksheet, cells = table_body_cells(workbook, "SOWStoryTable")
            expected_sources = {
                "验收条件": "AcceptanceCriterionTable[验收条件名称]",
                "任务明细": "TaskTable[任务名称]",
            }
            for header, source in expected_sources.items():
                formula = cells[header].value
                assert isinstance(formula, ArrayFormula)
                assert formula.ref == cells[header].coordinate
                assert isinstance(formula.text, str)
                assert "_xlfn.TEXTJOIN" in formula.text
                assert "_xlfn._xlws." not in formula.text
                assert f'"• "&{source}' in formula.text

            table = worksheet.tables["SOWStoryTable"]
            columns = {column.name: column for column in table.tableColumns}
            for header in expected_sources:
                calculated = columns[header].calculatedColumnFormula
                assert calculated is not None
                assert calculated.array is True
                assert "_xlfn._xlws." not in calculated.text
        finally:
            workbook.close()


def test_all_visible_text_is_vertically_centered_and_summary_status_is_readable() -> None:
    for path in (GENERATE_SOW_TEMPLATE, REFERENCE_WORKBOOK):
        workbook = openpyxl.load_workbook(path, data_only=False, read_only=False)
        try:
            for worksheet in workbook.worksheets:
                expected_freeze = None if worksheet.title == "00-使用说明" else (
                    "A5" if worksheet.title == "90-系统现状" else "A4"
                )
                assert worksheet.freeze_panes == expected_freeze
                for row in worksheet.iter_rows():
                    for cell in row:
                        if cell.value is not None:
                            assert cell.alignment.vertical == "center", (
                                f"{path.name}:{worksheet.title}:{cell.coordinate}"
                            )
            rules = [
                rule
                for conditional_format, entries in workbook["20-项目汇总"].conditional_formatting._cf_rules.items()
                if str(conditional_format.sqref) == "F5:F12"
                for rule in entries
            ]
            by_formula = {tuple(rule.formula): rule for rule in rules}
            assert by_formula[('"正常"',)].dxf.font.color.rgb[-6:] == "315F61"
            assert by_formula[('"检查"',)].dxf.font.color.rgb[-6:] == "9C0006"
        finally:
            workbook.close()


def test_technical_keys_are_hidden_and_business_tables_do_not_expose_ids() -> None:
    workbook = openpyxl.load_workbook(REFERENCE_WORKBOOK, data_only=False, read_only=False)
    try:
        assert workbook["90-系统现状"].column_dimensions["H"].hidden is not True
        assert workbook["91-项目参数"].column_dimensions["A"].hidden is True
        assert workbook["92-基础人天"].column_dimensions["A"].hidden is True
        assert workbook["92-基础人天"].column_dimensions["C"].hidden is True
        for headers in EXPECTED_HEADERS.values():
            assert all(not header.endswith("ID") for header in headers)
        for worksheet in workbook.worksheets:
            for row in worksheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        formula = cell.value.text if isinstance(cell.value, ArrayFormula) else cell.value
                        assert isinstance(formula, str)
                        assert "#REF!" not in formula
                        assert "_xlfn._xlws." not in formula
    finally:
        workbook.close()


def test_generate_sow_runtime_does_not_read_another_skill_asset() -> None:
    skill_root = Path(__file__).resolve().parents[1]
    forbidden = ("skills/setup/", "skills/generate-task/")
    for path in skill_root.joinpath("scripts").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert all(fragment not in text for fragment in forbidden)
