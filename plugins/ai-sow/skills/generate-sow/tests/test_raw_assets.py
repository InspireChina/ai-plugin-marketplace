from __future__ import annotations

import re
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils.cell import range_boundaries


SKILL_ROOT = Path(__file__).parents[1]
CANONICAL_TEMPLATE = SKILL_ROOT.parent / "setup/assets/sow-template.xlsx"
TASK_FIXTURE_TEMPLATE = SKILL_ROOT.parent / "generate-task/fixtures/sow-template.xlsx"
SOW_FIXTURE_TEMPLATE = SKILL_ROOT / "fixtures/project/.ai-sow/templates/sow-template.xlsx"
REFERENCE_WORKBOOK = (
    SKILL_ROOT.parent.parent / "docs/reference/SOW估算与生成示例_v1.3.xlsx"
)
REFERENCE_STANDARD = (
    SKILL_ROOT.parent.parent
    / "docs/reference/SOW任务分类与开发交付人天标准_v1.3.md"
)
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
EXPECTED_TASK_HEADERS = [
    "Task ID",
    "Story ID",
    "任务说明",
    "基础单元ID",
    "任务族",
    "工作模式",
    "工作模式理由",
    "复杂度",
    "复杂度理由",
    "Integration ID",
    "系统现状匹配",
    "判断依据与备注",
    "基础人天",
    "复杂度倍率",
    "人天小计",
]
EXPECTED_CATALOG_HEADERS = [
    "任务族ID",
    "任务族名称",
    "基础单元ID",
    "基础单元名称",
    "计数口径",
    "包含内容",
    "不包含内容",
    "新建M档人天",
    "调整M档人天",
    "接入复用M档人天",
    "S标准",
    "M标准",
    "L标准",
    "X/拆分条件",
]
ID_PATTERNS = {
    "Epic ID": re.compile(r"^epic-[a-z0-9]+(?:-[a-z0-9]+)*$"),
    "Feature ID": re.compile(r"^feature-[a-z0-9]+(?:-[a-z0-9]+)*$"),
    "Story ID": re.compile(r"^story-[a-z0-9]+(?:-[a-z0-9]+)*$"),
    "AC ID": re.compile(r"^ac-[a-z0-9]+(?:-[a-z0-9]+)*$"),
    "Task ID": re.compile(r"^task-[a-z0-9]+(?:-[a-z0-9]+)*$"),
    "Integration ID": re.compile(r"^integration-[a-z0-9]+(?:-[a-z0-9]+)*$"),
    "假设ID": re.compile(r"^assumption-[a-z0-9]+(?:-[a-z0-9]+)*$"),
}
EXPECTED_BODY_ALIGNMENT = {
    "EpicTable": {
        "Epic ID": ("left", "top"),
        "需求类型": ("center", "center"),
        "需求名称": ("left", "top"),
        "需求描述": ("left", "top"),
        "涉及系统/数据": ("left", "top"),
        "目标结果": ("left", "top"),
        "公共约束/范围外": ("left", "top"),
    },
    "FeatureTable": {
        "Feature ID": ("left", "top"),
        "Epic ID": ("left", "top"),
        "Epic 名称": ("left", "top"),
        "子需求名称": ("left", "top"),
        "场景/范围描述": ("left", "top"),
        "涉及系统/数据": ("left", "top"),
        "约束/NFR": ("left", "top"),
        "来源类型": ("center", "center"),
        "推断理由": ("left", "top"),
    },
    "SOWStoryTable": {
        "Story ID": ("left", "top"),
        "Story名称": ("left", "top"),
        "Feature ID": ("left", "top"),
        "UAT分母": ("center", "center"),
        "需求": ("left", "top"),
        "子需求": ("left", "top"),
        "验收条件": ("left", "top"),
        "任务明细": ("left", "top"),
        "人天": ("right", "center"),
        "关联假设ID": ("left", "top"),
        "假设状态": ("center", "center"),
    },
    "AcceptanceCriterionTable": {
        "AC ID": ("left", "top"),
        "Story ID": ("left", "top"),
        "顺序": ("right", "center"),
        "验收结果": ("left", "top"),
    },
    "TaskTable": {
        "Task ID": ("left", "top"),
        "Story ID": ("left", "top"),
        "任务说明": ("left", "top"),
        "基础单元ID": ("left", "top"),
        "任务族": ("center", "center"),
        "工作模式": ("center", "center"),
        "工作模式理由": ("left", "top"),
        "复杂度": ("center", "center"),
        "复杂度理由": ("left", "top"),
        "Integration ID": ("left", "top"),
        "系统现状匹配": ("left", "top"),
        "判断依据与备注": ("left", "top"),
        "基础人天": ("right", "center"),
        "复杂度倍率": ("right", "center"),
        "人天小计": ("right", "center"),
    },
    "IntegrationTable": {
        "Integration ID": ("left", "top"),
        "Story ID": ("left", "top"),
        "来源": ("left", "top"),
        "目标": ("left", "top"),
        "触发条件": ("left", "top"),
        "方向": ("center", "center"),
        "业务目的": ("left", "top"),
        "责任边界": ("center", "center"),
        "集成Task ID": ("left", "top"),
        "工作模式": ("center", "center"),
        "复杂度": ("center", "center"),
        "支持单价": ("right", "center"),
        "SIT人天": ("right", "center"),
    },
    "AssumptionRiskTable": {
        "假设ID": ("left", "top"),
        "类型": ("center", "center"),
        "名称": ("left", "top"),
        "触发条件": ("left", "top"),
        "关联 Story ID": ("left", "top"),
        "责任边界": ("left", "top"),
        "状态": ("center", "center"),
        "处理方式": ("left", "top"),
        "关联 Story 人天": ("right", "center"),
    },
    "ProjectSummaryTable": {
        "项目行": ("left", "top"),
        "计算/分母": ("left", "top"),
        "取整前": ("right", "center"),
        "开发交付估算人天": ("right", "center"),
        "口径": ("left", "top"),
        "校验": ("center", "center"),
    },
    "AsIsTopicTable": {
        "主题": ("left", "top"),
        "评估状态": ("left", "top"),
        "结论": ("left", "top"),
        "当前事实数": ("right", "center"),
        "承诺数": ("right", "center"),
        "有效起点数": ("right", "center"),
        "未决数": ("right", "center"),
    },
    "AsIsDetailTable": {
        "主题": ("left", "top"),
        "记录类型": ("left", "top"),
        "记录 ID": ("left", "top"),
        "分类/状态": ("left", "top"),
        "名称": ("left", "top"),
        "摘要/理由": ("left", "top"),
        "关系/流向": ("left", "top"),
        "关联 ID": ("left", "top"),
        "证据引用": ("left", "top"),
    },
    "ProjectParameterTable": {
        "参数代码": ("left", "top"),
        "名称": ("left", "top"),
        "值": ("right", "center"),
        "单位": ("left", "top"),
        "适用范围": ("left", "top"),
        "验证状态/说明": ("left", "top"),
    },
    "BaseUnitCatalogTable": {
        "任务族ID": ("left", "top"),
        "任务族名称": ("left", "top"),
        "基础单元ID": ("left", "top"),
        "基础单元名称": ("left", "top"),
        "计数口径": ("left", "top"),
        "包含内容": ("left", "top"),
        "不包含内容": ("left", "top"),
        "新建M档人天": ("right", "center"),
        "调整M档人天": ("right", "center"),
        "接入复用M档人天": ("right", "center"),
        "S标准": ("left", "top"),
        "M标准": ("left", "top"),
        "L标准": ("left", "top"),
        "X/拆分条件": ("left", "top"),
    },
}


def open_workbook(path: Path) -> openpyxl.Workbook:
    with path.open("rb") as source:
        return openpyxl.load_workbook(source, data_only=False, read_only=False)


def table_headers(workbook: openpyxl.Workbook, table_name: str) -> list[str]:
    for worksheet in workbook.worksheets:
        if table_name not in worksheet.tables:
            continue
        table = worksheet.tables[table_name]
        min_col, min_row, max_col, _ = range_boundaries(table.ref)
        return [
            str(worksheet.cell(min_row, column).value)
            for column in range(min_col, max_col + 1)
        ]
    raise AssertionError(f"missing workbook table: {table_name}")


def table_rows(
    workbook: openpyxl.Workbook,
    table_name: str,
) -> list[dict[str, Any]]:
    for worksheet in workbook.worksheets:
        if table_name not in worksheet.tables:
            continue
        table = worksheet.tables[table_name]
        min_col, min_row, max_col, max_row = range_boundaries(table.ref)
        headers = [
            str(worksheet.cell(min_row, column).value)
            for column in range(min_col, max_col + 1)
        ]
        return [
            {
                header: worksheet.cell(row, column).value
                for header, column in zip(
                    headers,
                    range(min_col, max_col + 1),
                    strict=True,
                )
            }
            for row in range(min_row + 1, max_row + 1)
        ]
    raise AssertionError(f"missing workbook table: {table_name}")


def populated_rows(
    workbook: openpyxl.Workbook,
    table_name: str,
    id_column: str,
) -> list[dict[str, Any]]:
    return [row for row in table_rows(workbook, table_name) if row[id_column]]


def table_body_cells(
    workbook: openpyxl.Workbook,
    table_name: str,
) -> dict[str, openpyxl.cell.cell.Cell]:
    for worksheet in workbook.worksheets:
        if table_name not in worksheet.tables:
            continue
        table = worksheet.tables[table_name]
        min_col, min_row, max_col, _ = range_boundaries(table.ref)
        return {
            str(worksheet.cell(min_row, column).value): worksheet.cell(
                min_row + 1,
                column,
            )
            for column in range(min_col, max_col + 1)
        }
    raise AssertionError(f"missing workbook table: {table_name}")


def list_validation_contract(
    workbook: openpyxl.Workbook,
) -> set[tuple[str, str, str]]:
    return {
        (
            worksheet.title,
            str(validation.sqref),
            str(validation.formula1),
        )
        for worksheet in workbook.worksheets
        for validation in worksheet.data_validations.dataValidation
        if validation.type == "list"
    }


def test_committed_canonical_template_copies_are_byte_identical() -> None:
    hashes = {
        sha256(path.read_bytes()).hexdigest()
        for path in (
            CANONICAL_TEMPLATE,
            TASK_FIXTURE_TEMPLATE,
            SOW_FIXTURE_TEMPLATE,
        )
    }
    assert len(hashes) == 1


def test_v13_template_and_reference_use_consolidated_sheet_contract() -> None:
    for path in (CANONICAL_TEMPLATE, REFERENCE_WORKBOOK):
        workbook = open_workbook(path)
        try:
            table_names = {
                name
                for worksheet in workbook.worksheets
                for name in worksheet.tables
            }
            assert workbook.sheetnames == EXPECTED_SHEETS
            assert table_headers(workbook, "TaskTable") == EXPECTED_TASK_HEADERS
            assert table_headers(workbook, "BaseUnitCatalogTable") == (
                EXPECTED_CATALOG_HEADERS
            )
            assert not {
                "BaseEffortTable",
                "WorkModeTable",
                "ComplexityRuleTable",
            } & table_names
        finally:
            workbook.close()


def test_v13_dropdowns_match_their_column_contracts() -> None:
    expected = {
        ("01-需求", "B5:B104", '"BUSINESS,TECHNICAL"'),
        (
            "02-子需求",
            "B5:B104",
            "INDIRECT(\"'01-需求'!$A$5:$A$104\")",
        ),
        ("02-子需求", "H5:H104", '"SOURCE_INPUT,DESIGN_DERIVED"'),
        (
            "03-SOW主表",
            "C5:C104",
            "INDIRECT(\"'02-子需求'!$A$5:$A$104\")",
        ),
        ("03-SOW主表", "D5:D104", '"是,否"'),
        (
            "04-验收条件",
            "B5:B104",
            "INDIRECT(\"'03-SOW主表'!$A$5:$A$104\")",
        ),
        (
            "05-任务明细",
            "B5:B504",
            "INDIRECT(\"'03-SOW主表'!$A$5:$A$104\")",
        ),
        (
            "05-任务明细",
            "D5:D504",
            "INDIRECT(\"'92-基础人天'!$C$5:$C$41\")",
        ),
        ("05-任务明细", "F5:F504", '"新建,调整,接入复用"'),
        ("05-任务明细", "H5:H504", '"S,M,L"'),
        (
            "05-任务明细",
            "J5:J504",
            "INDIRECT(\"'06-集成点'!$A$5:$A$104\")",
        ),
        (
            "06-集成点",
            "B5:B104",
            "INDIRECT(\"'03-SOW主表'!$A$5:$A$104\")",
        ),
        ("06-集成点", "F5:F104", '"INBOUND,OUTBOUND"'),
        ("06-集成点", "H5:H104", '"内部,外部"'),
        ("07-假设清单", "B5:B104", '"假设,风险"'),
        (
            "07-假设清单",
            "E5:E104",
            "INDIRECT(\"'03-SOW主表'!$A$5:$A$104\")",
        ),
        ("07-假设清单", "G5:G104", '"已明确,待确认"'),
    }
    for path in (CANONICAL_TEMPLATE, REFERENCE_WORKBOOK):
        workbook = open_workbook(path)
        try:
            assert list_validation_contract(workbook) == expected
        finally:
            workbook.close()


def test_v13_template_and_reference_use_semantic_body_alignment() -> None:
    for path in (CANONICAL_TEMPLATE, REFERENCE_WORKBOOK):
        workbook = open_workbook(path)
        try:
            for table_name, expected_columns in EXPECTED_BODY_ALIGNMENT.items():
                cells = table_body_cells(workbook, table_name)
                for header, expected in expected_columns.items():
                    cell = cells[header]
                    actual = (
                        cell.alignment.horizontal,
                        cell.alignment.vertical,
                    )
                    assert actual == expected, (
                        f"{path.name}:{table_name}:{header}:{cell.coordinate} "
                        f"expected {expected}, got {actual}"
                    )
        finally:
            workbook.close()


def test_v13_catalog_has_37_units_and_inline_work_mode_efforts() -> None:
    workbook = open_workbook(CANONICAL_TEMPLATE)
    try:
        catalog = table_rows(workbook, "BaseUnitCatalogTable")
        assert len(catalog) == 37
        assert len({row["基础单元ID"] for row in catalog}) == 37
        assert len({row["任务族ID"] for row in catalog}) == 13
        catalog_by_id = {row["基础单元ID"]: row for row in catalog}
        assert catalog_by_id["BU-DATA-MIGRATION"]["任务族名称"] == "数据迁移"
        assert catalog_by_id["BU-RELEASE-CUTOVER"]["任务族名称"] == "发布与切换"
        assert catalog_by_id["BU-SYSTEM-RETIREMENT"]["任务族名称"] == "发布与切换"
        assert catalog_by_id["BU-TECH-SUPPORT"]["基础单元名称"] == "问题诊断与恢复"
        assert catalog_by_id["BU-TECH-SUPPORT"]["任务族名称"] == "问题处理"
        assert catalog_by_id["BU-ROOT-CAUSE-REMEDIATION"]["任务族名称"] == "问题处理"
        assert catalog_by_id["BU-OPS-HANDOVER"]["任务族名称"] == "交付与移交"
        training = catalog_by_id["BU-USER-TRAINING"]
        assert training["任务族ID"] == "TF-DELIVERY-HANDOVER"
        assert training["任务族名称"] == "交付与移交"
        assert training["基础单元名称"] == "用户培训与使用材料"
        assert training["新建M档人天"] == 1.5
        assert training["调整M档人天"] == 1.0
        assert training["接入复用M档人天"] == "❌"

        configured = []
        for row in catalog:
            for mode, column in (
                ("新建", "新建M档人天"),
                ("调整", "调整M档人天"),
                ("接入复用", "接入复用M档人天"),
            ):
                effort = row[column]
                assert effort == "❌" or (
                    isinstance(effort, (int, float))
                    and not isinstance(effort, bool)
                    and effort > 0
                )
                if effort != "❌":
                    configured.append((row["基础单元ID"], mode))
        assert len(configured) == 86

        parameters = {
            row["参数代码"]: (row["值"], row["验证状态/说明"])
            for row in table_rows(workbook, "ProjectParameterTable")
        }
        assert parameters["K_COMPLEXITY_S"] == (0.6, "固定规则")
        assert parameters["K_COMPLEXITY_M"] == (1.0, "固定规则")
        assert parameters["K_COMPLEXITY_L"] == (1.5, "固定规则")
    finally:
        workbook.close()


def test_markdown_reference_effort_matrix_matches_the_canonical_template() -> None:
    text = REFERENCE_STANDARD.read_text(encoding="utf-8")
    section = text.split("### 12.3 推荐 M 档基础人天矩阵", 1)[1]
    section = section.split("### 12.4 Task 表", 1)[0]
    markdown_rows: list[list[str]] = []
    for line in section.splitlines():
        if (
            not line.startswith("| ")
            or line.startswith("| 任务族 ")
            or line.startswith("|---")
        ):
            continue
        markdown_rows.append([cell.strip() for cell in line.strip("|").split("|")])

    workbook = open_workbook(CANONICAL_TEMPLATE)
    try:
        catalog = table_rows(workbook, "BaseUnitCatalogTable")
    finally:
        workbook.close()

    assert len(markdown_rows) == len(catalog) == 37
    for markdown_row, catalog_row in zip(markdown_rows, catalog, strict=True):
        assert len(markdown_row) == 7
        family, unit, count_rule, contents, new, adjust, reuse = markdown_row
        assert family == catalog_row["任务族名称"]
        assert unit == catalog_row["基础单元名称"]
        assert count_rule == catalog_row["计数口径"]
        assert contents == (
            f'{catalog_row["包含内容"]}；不含{catalog_row["不包含内容"]}'
        )
        for displayed, configured in (
            (new, catalog_row["新建M档人天"]),
            (adjust, catalog_row["调整M档人天"]),
            (reuse, catalog_row["接入复用M档人天"]),
        ):
            if configured == "❌":
                assert displayed == "❌"
            else:
                assert float(displayed) == float(configured)


def test_reference_workbook_uses_stable_ids_and_valid_cross_sheet_refs() -> None:
    workbook = open_workbook(REFERENCE_WORKBOOK)
    try:
        epics = populated_rows(workbook, "EpicTable", "Epic ID")
        features = populated_rows(workbook, "FeatureTable", "Feature ID")
        assert any(
            row["Feature ID"] == "feature-production-scope" for row in features
        )
        stories = populated_rows(workbook, "SOWStoryTable", "Story ID")
        criteria = populated_rows(workbook, "AcceptanceCriterionTable", "AC ID")
        tasks = populated_rows(workbook, "TaskTable", "Task ID")
        integrations = populated_rows(
            workbook,
            "IntegrationTable",
            "Integration ID",
        )
        assumptions = populated_rows(workbook, "AssumptionRiskTable", "假设ID")

        collections = {
            "Epic ID": {str(row["Epic ID"]) for row in epics},
            "Feature ID": {str(row["Feature ID"]) for row in features},
            "Story ID": {str(row["Story ID"]) for row in stories},
            "AC ID": {str(row["AC ID"]) for row in criteria},
            "Task ID": {str(row["Task ID"]) for row in tasks},
            "Integration ID": {
                str(row["Integration ID"]) for row in integrations
            },
            "假设ID": {str(row["假设ID"]) for row in assumptions},
        }
        for column, values in collections.items():
            assert values
            assert all(ID_PATTERNS[column].fullmatch(value) for value in values)

        assert {str(row["Epic ID"]) for row in features} <= collections["Epic ID"]
        assert {str(row["Feature ID"]) for row in stories} <= collections["Feature ID"]
        assert {str(row["Story ID"]) for row in criteria} <= collections["Story ID"]
        assert {str(row["Story ID"]) for row in tasks} <= collections["Story ID"]
        assert {str(row["Story ID"]) for row in integrations} <= collections["Story ID"]
    finally:
        workbook.close()


def test_reference_tasks_are_atomic_and_integrations_have_one_task() -> None:
    workbook = open_workbook(REFERENCE_WORKBOOK)
    try:
        tasks = populated_rows(workbook, "TaskTable", "Task ID")
        integrations = populated_rows(
            workbook,
            "IntegrationTable",
            "Integration ID",
        )
        assert len({row["Task ID"] for row in tasks}) == len(tasks)
        assert all(row["基础单元ID"] for row in tasks)
        assert all(
            row["工作模式"] in {"新建", "调整", "接入复用"}
            for row in tasks
        )
        assert all(row["复杂度"] in {"S", "M", "L"} for row in tasks)

        task_counts = Counter(
            row["Integration ID"] for row in tasks if row["Integration ID"]
        )
        integration_ids = {row["Integration ID"] for row in integrations}
        assert task_counts == Counter(
            {integration_id: 1 for integration_id in integration_ids}
        )

        formulas = [
            value
            for row in tasks
            for value in row.values()
            if isinstance(value, str) and value.startswith("=")
        ]
        assert any("BaseUnitCatalogTable" in formula for formula in formulas)
        assert any("ProjectParameterTable" in formula for formula in formulas)
        assert all("BaseEffortTable" not in formula for formula in formulas)
        assert all("ComplexityRuleTable" not in formula for formula in formulas)
    finally:
        workbook.close()
