from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from openpyxl.worksheet.formula import ArrayFormula


SKILL_ROOT = Path(__file__).parents[1]
ASSETS = SKILL_ROOT / "assets"
PRD_TEMPLATE = ASSETS / "prd-template.md"
HLD_TEMPLATE = ASSETS / "hld-template.md"
QUESTIONNAIRE = ASSETS / "greenfield-questionnaire.md"
SOW_TEMPLATE = ASSETS / "sow-template.xlsx"
NEXT_SOW_TEMPLATE = SOW_TEMPLATE
PLUGIN_ROOT = SKILL_ROOT.parents[1]
V6_REFERENCE_ROOT = PLUGIN_ROOT / "docs" / "reference"
V6_DISCUSSION = V6_REFERENCE_ROOT / "研发全生命周期标准人天基准表_v6.0_讨论稿.md"
MIGRATION_LEDGER = (
    SKILL_ROOT
    / "fixtures"
    / "task-standard"
    / "task-standard-migration-ledger-v1.json"
)
MIGRATION_APPROVAL = (
    SKILL_ROOT
    / "fixtures"
    / "task-standard"
    / "task-standard-migration-approval-v1.json"
)
RENDERER_BASELINE = SKILL_ROOT / "contracts/renderer-fingerprint-baseline.json"
TASK_STANDARD_HEADERS = [
    "序号",
    "分类",
    "工作类型ID",
    "工作类型名称",
    "计量单位",
    "标准交付物",
    "包含内容",
    "不包含内容",
    "说明",
    "新建适用",
    "新建M档人天",
    "新建完成标准",
    "调整适用",
    "调整M档人天",
    "调整完成标准",
    "接入复用适用",
    "接入复用M档人天",
    "接入复用完成标准",
    "主要计量维度",
    "S标准",
    "M标准",
    "L标准",
    "X/拆分条件",
    "模式适用说明",
    "相邻工作类型IDs",
    "相邻类型选择规则",
    "不建Task条件",
    "SIT支持资格",
    "标准版本",
    "参数状态",
    "来源版本",
]
V6_SOURCE_PINS = {
    "docs/reference/研发全生命周期标准人天基准表_v6.0_讨论稿.md": {
        "gitBlobSha1": "d93f0d02bcbde4c2415bd8d6795677eaef3606d8",
        "contentSha256": "37d26828303569fef1639683c33d4a801a32f71e81a30fd64e3b86fd23e3db42",
    },
    "docs/reference/研发全生命周期标准人天基准表_v6.0_复杂度标准设计.md": {
        "gitBlobSha1": "161988351e81154ec1d748ed7729bfa3a1315ede",
        "contentSha256": "76f47a14f2848d8f5be6712d4ccab7fac2953f161e8efb3d5d71edb35fa62c7a",
    },
    "docs/reference/研发全生命周期标准人天基准表_v6.0_复杂度案例复核.md": {
        "gitBlobSha1": "d1e7e10414582c368c9acdf881fc296654d7c5f5",
        "contentSha256": "abed7186f00ebdd7f718bee382392046a56b2bb72b80c0bbca1d2eed0c414605",
    },
    "docs/reference/研发全生命周期标准人天基准表_v6.0_权威依据.md": {
        "gitBlobSha1": "bebe253b6635939e916572087ba2292e4101df3c",
        "contentSha256": "9fe31cb80ec511b96b18d16ec12f9f2f2fb2b7af23b8a825296503e2d5a56e45",
    },
}
USER_CONTINUATION_INSTRUCTION = (
    "要你停下来不是等我的，停下来的意思是解决掉问题继续，你就按合理的方式继续\n"
    "我要afk了，按照执行计划顺序推进就行，有问题自己解决，除非解决不了，那就不要一直试了"
)
REQUIRED_PRD_SECTIONS = {
    "项目背景与问题",
    "目标与成功指标",
    "In Scope",
    "Out of Scope",
    "用户与角色",
    "核心业务场景",
    "Feature、业务结果、业务规则与验收意图",
    "优先级与阶段",
    "业务约束、依赖与假设",
    "业务数据、合规与外部参与方",
}
REQUIRED_HLD_SECTIONS = {
    "系统上下文与责任",
    "目标架构",
    "关键业务流",
    "跨系统 Integration",
    "数据、迁移、保留与安全分类",
    "NFR",
    "环境、部署与切换",
    "关键技术决策",
    "范围外与约束",
    "实施单元与复用边界",
    "待设计事项",
}


def markdown_headings(path: Path) -> set[str]:
    return {
        match.group(1).strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := re.match(r"^#{2,6}\s+(.+)$", line))
    }


def test_prd_and_hld_assets_express_every_required_semantic_section() -> None:
    assert REQUIRED_PRD_SECTIONS <= markdown_headings(PRD_TEMPLATE)
    assert REQUIRED_HLD_SECTIONS <= markdown_headings(HLD_TEMPLATE)


def test_templates_do_not_request_internal_compilation_artifacts() -> None:
    prd = PRD_TEMPLATE.read_text(encoding="utf-8")
    hld = HLD_TEMPLATE.read_text(encoding="utf-8")
    for forbidden in ("Coverage Matrix", "Story 分解", "Task 分解"):
        assert forbidden not in prd
    for forbidden in ("Coverage Matrix", "字段级接口", "类设计"):
        assert forbidden not in hld


def test_hld_template_requires_an_approved_implementation_ready_baseline() -> None:
    hld = HLD_TEMPLATE.read_text(encoding="utf-8")
    assert "APPROVED" in hld
    assert {
        "目标系统",
        "组件",
        "Integration",
        "数据流",
        "部署",
        "NFR",
        "责任",
        "ADR",
        "范围外",
        "实施单元",
    } <= {term for term in (
        "目标系统",
        "组件",
        "Integration",
        "数据流",
        "部署",
        "NFR",
        "责任",
        "ADR",
        "范围外",
        "实施单元",
    ) if term in hld}


def test_greenfield_questionnaire_is_minimal() -> None:
    text = QUESTIONNAIRE.read_text(encoding="utf-8")
    assert {"责任边界", "环境准备", "第三方依赖", "数据迁移责任"} <= set(
        re.findall(r"^##\s+(.+)$", text, re.MULTILINE)
    )
    assert text.count("？") == 4


def table_names(workbook) -> set[str]:
    return {
        table_name
        for worksheet in workbook.worksheets
        for table_name in worksheet.tables
    }


def table_headers(workbook, table_name: str) -> list[str]:
    for worksheet in workbook.worksheets:
        if table_name in worksheet.tables:
            return [column.name for column in worksheet.tables[table_name].tableColumns]
    raise AssertionError(f"missing table: {table_name}")


def formula_headers(workbook, table_name: str) -> set[str]:
    for worksheet in workbook.worksheets:
        if table_name not in worksheet.tables:
            continue
        table = worksheet.tables[table_name]
        header_row = worksheet[table.ref.split(":", 1)[0]].row
        result: set[str] = set()
        for column in table.tableColumns:
            cell = worksheet.cell(header_row + 1, column.id)
            if cell.data_type == "f" and isinstance(cell.value, (str, ArrayFormula)):
                result.add(column.name)
        return result
    raise AssertionError(f"missing table: {table_name}")


def formula_text(value: object) -> str:
    if isinstance(value, ArrayFormula):
        return value.text
    return str(value)


def table_values(workbook, table_name: str) -> list[list[Any]]:
    for worksheet in workbook.worksheets:
        if table_name not in worksheet.tables:
            continue
        min_col, min_row, max_col, max_row = range_boundaries(
            worksheet.tables[table_name].ref
        )
        return [
            [worksheet.cell(row, column).value for column in range(min_col, max_col + 1)]
            for row in range(min_row + 1, max_row + 1)
        ]
    raise AssertionError(f"missing table: {table_name}")


def _canonical_decimal(value: int | float | Decimal) -> str:
    decimal = Decimal(str(value))
    if not decimal.is_finite():
        raise AssertionError(f"non-finite number: {value}")
    result = format(decimal, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return "0" if result in {"-0", ""} else result


def _canonical_json(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        return _canonical_decimal(value)
    if isinstance(value, str):
        normalized = unicodedata.normalize(
            "NFC", value.replace("\r\n", "\n").replace("\r", "\n").strip()
        )
        return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    raise AssertionError(f"unsupported canonical value: {type(value).__name__}")


def _canonical_target_row(values: list[Any], *, semantic: bool) -> list[Any]:
    selected = values[1:28] if semantic else values
    result = list(selected)
    neighbor_index = 24 - (1 if semantic else 0)
    neighbors = result[neighbor_index]
    if neighbors is None or not str(neighbors).strip():
        result[neighbor_index] = []
    else:
        result[neighbor_index] = sorted(
            set(part.strip() for part in str(neighbors).split(",") if part.strip())
        )
    return result


def _row_sha256(values: list[Any], *, semantic: bool = False) -> str:
    payload = _canonical_json(_canonical_target_row(values, semantic=semantic))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _markdown_tables(path: Path) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in [*path.read_text(encoding="utf-8").splitlines(), ""]:
        if line.startswith("|"):
            current.append(
                [
                    cell.strip().replace("<br>", "\n")
                    for cell in line.strip().strip("|").split("|")
                ]
            )
        elif current:
            if len(current) >= 3:
                tables.append(current)
            current = []
    return tables


def _source_row_sha256(values: list[str]) -> str:
    return hashlib.sha256(_canonical_json(values).encode("utf-8")).hexdigest()


def _canonical_mapping_sha256(value: object) -> str:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _completion_standards(value: str) -> dict[str, str]:
    parts = re.split(r"(新建|调整|接入复用)：", value)
    return {parts[index]: parts[index + 1].strip() for index in range(1, len(parts), 2)}


def _explicit_boundary_sentences(value: str) -> tuple[str, ...]:
    markers = (
        "不单列",
        "不计",
        "包含在",
        "不重复",
        "另行",
        "不属于",
        "不得",
        "不能",
        "不用于",
        "优先使用",
        "使用对应",
        "使用被修改",
    )
    return tuple(
        sentence
        for sentence in (
            part.strip()
            for part in re.split(r"(?<=[。；])", value)
            if part.strip()
        )
        if any(marker in sentence for marker in markers)
    )


def test_bundled_sow_template_is_pinned_four_sheet_calculation_authority() -> None:
    assert hashlib.sha256(SOW_TEMPLATE.read_bytes()).hexdigest() == (
        "43058a761a3d5ea2e71e779b1600aa159258f732b1cb5c60d491051540454041"
    )
    workbook = load_workbook(SOW_TEMPLATE, data_only=False, read_only=False)
    try:
        assert workbook.sheetnames == [
            "01-需求故事",
            "02-任务清单",
            "03-工作量汇总",
            "90-估算标准",
        ]
        assert table_names(workbook) == {
            "SOWStoryTable",
            "TaskTable",
            "ProjectSummaryTable",
            "ProjectParameterTable",
            "TaskStandardTable",
        }
        assert table_headers(workbook, "SOWStoryTable") == [
            "需求",
            "子需求",
            "故事",
            "UAT适用",
            "验收条件",
            "备注",
            "任务列表",
            "故事人天",
            "校验结果",
        ]
        assert table_headers(workbook, "TaskTable") == [
            "所属故事",
            "任务名称",
            "工作类型ID",
            "工作类型名称",
            "工作方式",
            "复杂度",
            "SIT支持分类",
            "SIT计费点ID",
            "备注",
            "M档标准人天",
            "复杂度系数",
            "任务人天",
            "SIT支持人天",
            "校验结果",
        ]
        assert formula_headers(workbook, "SOWStoryTable") == {
            "任务列表",
            "故事人天",
            "校验结果",
        }
        assert formula_headers(workbook, "TaskTable") == {
            "工作类型名称",
            "M档标准人天",
            "复杂度系数",
            "任务人天",
            "SIT支持人天",
            "校验结果",
        }
        summary = workbook["03-工作量汇总"]
        assert summary["B5"].value == "=SUM(TaskTable[任务人天])"
        assert "CEILING" in summary["B6"].value
    finally:
        workbook.close()


def test_task_standard_table_has_exact_name_range_and_31_headers() -> None:
    workbook = load_workbook(NEXT_SOW_TEMPLATE, data_only=False, read_only=False)
    try:
        sheet = workbook["90-估算标准"]
        assert sheet.tables["TaskStandardTable"].ref == "A4:AE92"
        assert table_headers(workbook, "TaskStandardTable") == TASK_STANDARD_HEADERS
        assert sheet.tables["ProjectParameterTable"].ref == "AG4:AL12"
        assert all(sheet.cell(row, 32).value is None for row in range(1, 93))
    finally:
        workbook.close()


def test_v6_catalog_has_88_unique_contiguous_rows_191_modes_and_26_reuse_types() -> None:
    workbook = load_workbook(NEXT_SOW_TEMPLATE, data_only=False, read_only=False)
    try:
        rows = table_values(workbook, "TaskStandardTable")
        ids = [row[2] for row in rows]
        assert len(rows) == len(ids) == len(set(ids)) == 88
        assert [row[0] for row in rows] == list(range(1, 89))
        mode_columns = (9, 12, 15)
        assert sum(row[column] is True for row in rows for column in mode_columns) == 191
        assert sum(row[15] is True for row in rows) == 26
    finally:
        workbook.close()


def test_mode_applicability_pairs_boolean_effort_and_completion_standard() -> None:
    workbook = load_workbook(NEXT_SOW_TEMPLATE, data_only=False, read_only=False)
    try:
        for row in table_values(workbook, "TaskStandardTable"):
            for applicable_index, effort_index, completion_index in (
                (9, 10, 11),
                (12, 13, 14),
                (15, 16, 17),
            ):
                applicable = row[applicable_index]
                effort = row[effort_index]
                completion = row[completion_index]
                assert type(applicable) is bool
                if applicable:
                    assert isinstance(effort, (int, float)) and effort >= 1.0
                    assert isinstance(completion, str) and completion.strip()
                else:
                    assert effort is None
                    assert completion is None
    finally:
        workbook.close()


def test_migration_ledger_covers_every_source_and_target_row_once() -> None:
    ledger = json.loads(MIGRATION_LEDGER.read_text(encoding="utf-8"))
    assert ledger["schemaVersion"] == "task-standard-migration-ledger-v1"
    assert ledger["sourceCommit"] == "0d0982fb7787fdcdc9bcfbcbbe46928ca8f9c7fd"
    assert len(ledger["sources"]) == 4
    assert {source["path"] for source in ledger["sources"]} == set(V6_SOURCE_PINS)
    for source in ledger["sources"]:
        path = PLUGIN_ROOT / source["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["contentSha256"]
        assert {
            "gitBlobSha1": source["gitBlobSha1"],
            "contentSha256": source["contentSha256"],
        } == V6_SOURCE_PINS[source["path"]]

    source_tables = _markdown_tables(V6_DISCUSSION)
    base_rows = source_tables[1][2:]
    complexity_rows = source_tables[5][2:]
    assert len(base_rows) == len(complexity_rows) == 88

    workbook = load_workbook(NEXT_SOW_TEMPLATE, data_only=False, read_only=False)
    try:
        target_rows = table_values(workbook, "TaskStandardTable")
    finally:
        workbook.close()

    entries = ledger["rows"]
    assert len(entries) == 88
    assert [entry["sequence"] for entry in entries] == list(range(1, 89))
    assert len({entry["sourceBaseRowRef"] for entry in entries}) == 88
    assert len({entry["sourceComplexityRowRef"] for entry in entries}) == 88
    assert len({entry["targetWorkTypeId"] for entry in entries}) == 88
    for entry, base, complexity, target in zip(
        entries, base_rows, complexity_rows, target_rows, strict=True
    ):
        assert base[1] == complexity[0] == target[2] == entry["targetWorkTypeId"]
        assert entry["sourceBaseRowSha256"] == _source_row_sha256(base)
        assert entry["sourceComplexityRowSha256"] == _source_row_sha256(complexity)
        assert entry["targetRowSha256"] == _row_sha256(target)
        assert entry["rowSemanticSha256"] == _row_sha256(target, semantic=True)
        assert set(entry["fieldMappings"]) == {
            "modeCompletionStandards",
            "sourceNotes",
            "complexityRules",
            "normalizedBoundaries",
        }
        boundaries = entry["fieldMappings"]["normalizedBoundaries"]
        assert set(boundaries) == {
            "包含内容",
            "不包含内容",
            "相邻工作类型IDs",
            "相邻类型选择规则",
            "不建Task条件",
            "SIT支持资格",
        }
        assert all(boundaries[field]["auditReason"].strip() for field in boundaries)


def test_migration_candidate_replays_source_rows_and_materializes_explicit_boundaries() -> None:
    source_tables = _markdown_tables(V6_DISCUSSION)
    base_rows = source_tables[1][2:]
    complexity_rows = source_tables[5][2:]
    known_ids = {row[1] for row in base_rows}
    id_pattern = re.compile(
        r"\b(?:AN|FE|IN|CO|DATA|GOV|TEST|ENG|REL|OPS|HAND|AI)-[A-Z0-9-]+\b"
    )
    workbook = load_workbook(NEXT_SOW_TEMPLATE, data_only=False, read_only=False)
    try:
        target_rows = table_values(workbook, "TaskStandardTable")
    finally:
        workbook.close()

    for base, complexity, target in zip(
        base_rows, complexity_rows, target_rows, strict=True
    ):
        assert target[:6] == [
            int(base[0]),
            base[2],
            base[1],
            base[3],
            base[4],
            base[8],
        ]
        assert target[8] == base[10]
        completions = _completion_standards(base[9])
        for mode, effort_source, indexes in zip(
            ("新建", "调整", "接入复用"),
            base[5:8],
            ((9, 10, 11), (12, 13, 14), (15, 16, 17)),
            strict=True,
        ):
            applicable, effort, completion = (target[index] for index in indexes)
            assert applicable is (effort_source != "-")
            assert effort == (None if effort_source == "-" else float(effort_source))
            assert completion == completions.get(mode)
        assert target[18:24] == complexity[2:8]

        assert base[8] in target[6] and base[4] in target[6]
        assert target[7].startswith(f"超出“{base[4]}”边界")
        assert "来源“说明”中要求" not in target[7]
        for sentence in _explicit_boundary_sentences(base[10]):
            assert sentence in target[7]
        assert target[26].strip() == target[26]
        assert "未形成可独立交付和验收" in target[26]

        expected_neighbors = sorted(
            (
                set(id_pattern.findall("\n".join([*base, *complexity])))
                & known_ids
            )
            - {base[1]}
        )
        actual_neighbors = sorted(target[24].split(",")) if target[24] else []
        assert actual_neighbors == expected_neighbors
        assert target[27] == (
            "PER_INTEGRATION"
            if base[1] in {"IN-INTEGRATION", "IN-IDENTITY"}
            else "NONE"
        )
        assert target[28:] == ["v6.0", "待校准", "0d0982fb/v6.0"]


def test_no_quantity_column_or_legacy_catalog_table_remains() -> None:
    workbook = load_workbook(NEXT_SOW_TEMPLATE, data_only=False, read_only=False)
    try:
        names = table_names(workbook)
        assert "BaseUnitCatalogTable" not in names
        assert names == {
            "SOWStoryTable",
            "TaskTable",
            "ProjectSummaryTable",
            "ProjectParameterTable",
            "TaskStandardTable",
        }
        assert "quantity" not in {header.casefold() for header in TASK_STANDARD_HEADERS}
        assert "数量" not in TASK_STANDARD_HEADERS
    finally:
        workbook.close()


def test_task_standard_sheet_is_filterable_wrapped_frozen_and_human_readable() -> None:
    workbook = load_workbook(NEXT_SOW_TEMPLATE, data_only=False, read_only=False)
    try:
        sheet = workbook["90-估算标准"]
        table = sheet.tables["TaskStandardTable"]
        assert table.autoFilter is not None
        assert table.autoFilter.ref == table.ref
        assert sheet.freeze_panes == "D5"
        assert sheet.sheet_view.showGridLines is False
        assert sheet.page_setup.orientation == "landscape"
        assert sheet.sheet_properties.pageSetUpPr.fitToPage is True
        assert sheet.page_setup.fitToWidth == 1
        assert sheet.page_setup.fitToHeight == 0
        assert all(sheet.cell(4, column).alignment.wrap_text for column in range(1, 32))
        assert all(sheet.cell(row, 7).alignment.wrap_text for row in range(5, 93))
        assert all((sheet.row_dimensions[row].height or 0) >= 48 for row in range(5, 93))
        assert all((sheet.column_dimensions[column].width or 0) >= 10 for column in ("A", "B", "C", "D", "E"))
        assert all((sheet.column_dimensions[column].width or 0) >= 28 for column in ("G", "H", "I", "L", "O", "R", "T", "U", "V", "W", "X", "Z", "AA"))
    finally:
        workbook.close()


def test_task_table_has_exact_14_columns_and_structured_formulas() -> None:
    workbook = load_workbook(NEXT_SOW_TEMPLATE, data_only=False, read_only=False)
    try:
        assert table_headers(workbook, "TaskTable") == [
            "所属故事",
            "任务名称",
            "工作类型ID",
            "工作类型名称",
            "工作方式",
            "复杂度",
            "SIT支持分类",
            "SIT计费点ID",
            "备注",
            "M档标准人天",
            "复杂度系数",
            "任务人天",
            "SIT支持人天",
            "校验结果",
        ]
        assert formula_headers(workbook, "TaskTable") == {
            "工作类型名称",
            "M档标准人天",
            "复杂度系数",
            "任务人天",
            "SIT支持人天",
            "校验结果",
        }
        sheet = workbook["02-任务清单"]
        for coordinate in ("D5", "J5", "K5", "L5", "M5", "N5"):
            assert formula_text(sheet[coordinate].value).startswith("=")
        structured_formula_text = "\n".join(
            formula_text(sheet[coordinate].value)
            for coordinate in ("D5", "J5", "K5", "M5", "N5")
        )
        assert "TaskStandardTable[" in structured_formula_text
        assert "ProjectParameterTable[" in structured_formula_text
    finally:
        workbook.close()


def test_work_type_name_and_effort_resolve_by_id_and_mode_from_same_row() -> None:
    workbook = load_workbook(NEXT_SOW_TEMPLATE, data_only=False, read_only=False)
    try:
        task_sheet = workbook["02-任务清单"]
        name_formula = formula_text(task_sheet["D5"].value)
        effort_formula = formula_text(task_sheet["J5"].value)
        assert "TaskStandardTable[工作类型名称]" in name_formula
        assert "TaskStandardTable[工作类型ID]" in name_formula
        for field in (
            "新建适用",
            "新建M档人天",
            "调整适用",
            "调整M档人天",
            "接入复用适用",
            "接入复用M档人天",
        ):
            assert f"TaskStandardTable[{field}]" in effort_formula
        assert effort_formula.count("TaskStandardTable[工作类型ID]") >= 6
        story_list_formula = formula_text(workbook["01-需求故事"]["G5"].value)
        assert "TaskTable[工作类型名称]" in story_list_formula
        assert "TaskTable[工作类型ID]" not in story_list_formula

        all_formula_and_validation_text = "\n".join(
            [
                formula_text(cell.value)
                for sheet in workbook.worksheets
                for row in sheet.iter_rows()
                for cell in row
                if cell.data_type == "f" or isinstance(cell.value, ArrayFormula)
            ]
            + [
                str(validation.formula1)
                for sheet in workbook.worksheets
                for validation in sheet.data_validations.dataValidation
            ]
        )
        for forbidden in ("$D$5:$D$41", "$H$5:$J$41", "$P$5:$R$12", "BaseUnitCatalogTable"):
            assert forbidden not in all_formula_and_validation_text
    finally:
        workbook.close()


def test_internal_external_support_round_separately_before_sum() -> None:
    workbook = load_workbook(NEXT_SOW_TEMPLATE, data_only=False, read_only=False)
    try:
        formula = formula_text(workbook["03-工作量汇总"]["B6"].value)
        assert formula.count("CEILING(") == 2
        assert formula.count("TaskTable[SIT支持人天]") == 2
        assert formula.count("TaskTable[SIT支持分类]") == 2
        assert '"INTERNAL"' in formula
        assert '"EXTERNAL"' in formula
        assert "ProjectParameterTable[值]" in formula
        assert "ProjectParameterTable[参数代码]" in formula
    finally:
        workbook.close()


def test_migration_approval_binds_final_template_all_88_rows_source_hashes_and_rendered_audit() -> None:
    approval = json.loads(MIGRATION_APPROVAL.read_text(encoding="utf-8"))
    ledger = json.loads(MIGRATION_LEDGER.read_text(encoding="utf-8"))
    assert approval["schemaVersion"] == "task-standard-migration-approval-v1"
    assert approval["decision"] == "APPROVED_FOR_IMPLEMENTATION"
    assert approval["humanRowReviewClaimed"] is False
    assert approval["reviewMethod"] == "DETERMINISTIC_EXHAUSTIVE_ROW_AUDIT"
    assert approval["userAuthorization"] == {
        "mode": "STANDING_CONTINUE_DIRECTION",
        "instructionSha256": hashlib.sha256(
            USER_CONTINUATION_INSTRUCTION.encode("utf-8")
        ).hexdigest(),
        "reviewClaimed": False,
        "approvedPacketSha256": approval["packetSha256"],
    }

    bindings = approval["bindings"]
    assert bindings["sourceCommit"] == ledger["sourceCommit"]
    assert bindings["sources"] == [
        {
            "path": source["path"],
            "gitBlobSha1": source["gitBlobSha1"],
            "contentSha256": source["contentSha256"],
        }
        for source in ledger["sources"]
    ]
    assert bindings["ledgerSha256"] == hashlib.sha256(
        MIGRATION_LEDGER.read_bytes()
    ).hexdigest()
    assert bindings["templateSha256"] == hashlib.sha256(
        NEXT_SOW_TEMPLATE.read_bytes()
    ).hexdigest()
    office = bindings["officeRoundtrip"]
    assert office["engineName"] == "LibreOffice"
    assert office["engineVersion"]
    assert office["formulaErrorCount"] == 0
    assert office["calculatedValues"] == {
        "directDays": 3.6,
        "internalSitDays": 0.3,
        "externalSitDays": 0.6,
        "separatelyRoundedSitDays": 1.5,
        "uatDays": 0,
        "totalDays": 5.1,
    }
    rendered = bindings["renderedAudit"]
    assert rendered["sheet"] == "90-估算标准"
    assert rendered["range"] == "A1:AL92"
    assert rendered["width"] >= 7000 and rendered["height"] >= 8000
    assert re.fullmatch(r"[0-9a-f]{64}", rendered["sha256"])

    rows = approval["rowApprovals"]
    assert len(rows) == 88
    assert [row["workTypeId"] for row in rows] == [
        row["targetWorkTypeId"] for row in ledger["rows"]
    ]
    expected_checks = [
        "BASE_FIELDS_EXACT",
        "MODE_AND_COMPLETION_EXACT",
        "COMPLEXITY_FIELDS_EXACT",
        "NORMALIZED_BOUNDARIES_AUDITED",
        "TARGET_HASHES_RECOMPUTED",
    ]
    for reviewed, migrated in zip(rows, ledger["rows"], strict=True):
        assert reviewed == {
            "sequence": migrated["sequence"],
            "workTypeId": migrated["targetWorkTypeId"],
            "sourceBaseRowSha256": migrated["sourceBaseRowSha256"],
            "sourceComplexityRowSha256": migrated["sourceComplexityRowSha256"],
            "targetRowSha256": migrated["targetRowSha256"],
            "rowSemanticSha256": migrated["rowSemanticSha256"],
            "checks": expected_checks,
            "decision": "PASS",
        }

    packet = {
        "reviewMethod": approval["reviewMethod"],
        "humanRowReviewClaimed": approval["humanRowReviewClaimed"],
        "bindings": approval["bindings"],
        "rowApprovals": rows,
    }
    assert approval["reviewerSha256"] == _canonical_mapping_sha256(rows)
    assert approval["packetSha256"] == _canonical_mapping_sha256(packet)


def test_renderer_fingerprint_binds_projection_and_office_implementation() -> None:
    baseline = json.loads(RENDERER_BASELINE.read_text(encoding="utf-8"))
    assert baseline["rendererContract"] == "generation-renderer-v8"
    assert baseline["files"] == {
        name: hashlib.sha256((SKILL_ROOT / name).read_bytes()).hexdigest()
        for name in (
            "scripts/package_renderer.py",
            "scripts/workbook.py",
            "scripts/office_engine.py",
            "scripts/story_notes.py",
        )
    }
