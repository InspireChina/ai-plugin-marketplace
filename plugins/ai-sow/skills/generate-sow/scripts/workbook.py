from __future__ import annotations

import copy
import datetime as dt
import math
import os
import re
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.formula.translate import Translator
from openpyxl.styles import PatternFill, Protection
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.filters import AutoFilter
from openpyxl.worksheet.formula import ArrayFormula
from openpyxl.worksheet.table import TableFormula


TOPIC_LABELS = {
    "SYSTEM_CONTEXT": "系统边界与参与方",
    "CAPABILITY": "能力与流程",
    "APPLICATION": "应用与组件",
    "INTEGRATION": "集成与外部依赖",
    "DATA": "数据与存储",
    "PLATFORM": "平台、环境与部署",
    "SECURITY_COMPLIANCE": "安全与合规",
    "OPERATIONS_QUALITY": "运维与质量",
    "DELIVERY_CONSTRAINTS": "交付与约束",
}
EPIC_TYPE_LABELS = {"BUSINESS": "业务", "TECHNICAL": "技术"}
FEATURE_SOURCE_LABELS = {
    "SOURCE_INPUT": "来源输入",
    "DESIGN_DERIVED": "设计派生",
}
DIRECTION_LABELS = {"INBOUND": "入站", "OUTBOUND": "出站"}
ASIS_START_AVAILABILITY_LABELS = {
    "CURRENT": "当前已存在",
    "EXPECTED_BEFORE_START": "预计开工前具备",
}
ASIS_TABLES = {"AsIsDetailTable"}
ASIS_DROPDOWN_HEADERS = {"主题名称", "起点可用性"}
ASIS_INPUT_LIMIT = 1000
TABLES = (
    "EpicTable",
    "FeatureTable",
    "SOWStoryTable",
    "AcceptanceCriterionTable",
    "TaskTable",
    "IntegrationTable",
    "AssumptionRiskTable",
    "AsIsDetailTable",
)
FORMULA_HEADERS = {
    "SOWStoryTable": {"需求名称", "验收条件", "任务明细", "人天", "假设/风险状态"},
    "AcceptanceCriterionTable": {"需求名称", "子需求名称"},
    "TaskTable": {"需求名称", "子需求名称", "任务族", "基础人天", "复杂度倍率", "人天小计"},
    "IntegrationTable": {"需求名称", "子需求名称", "工作模式", "复杂度", "支持单价", "SIT人天"},
}
TABLE_HEADERS = {
    "EpicTable": ["需求名称", "需求类型", "需求描述", "涉及系统/数据", "目标结果", "公共约束/范围外"],
    "FeatureTable": ["需求名称", "子需求名称", "场景/范围描述", "涉及系统/数据", "约束/NFR", "来源类型", "推断理由"],
    "SOWStoryTable": ["需求名称", "子需求名称", "故事名称", "UAT适用", "验收条件", "任务明细", "人天", "关联假设/风险名称", "假设/风险状态"],
    "AcceptanceCriterionTable": ["需求名称", "子需求名称", "故事名称", "验收条件名称"],
    "TaskTable": ["需求名称", "子需求名称", "故事名称", "任务名称", "基础单元名称", "任务族", "工作模式", "工作模式理由", "复杂度", "复杂度理由", "关联现状条目", "判断依据与备注", "基础人天", "复杂度倍率", "人天小计"],
    "IntegrationTable": ["需求名称", "子需求名称", "故事名称", "集成任务名称", "来源", "目标", "触发条件", "方向", "业务目的", "责任边界", "工作模式", "复杂度", "支持单价", "SIT人天"],
    "AssumptionRiskTable": ["假设/风险名称", "类型", "触发条件", "责任边界", "状态", "处理方式"],
    "AsIsDetailTable": ["主题名称", "现状条目名称", "现状描述", "起点可用性"],
}
PROTECTED_SHEETS = {
    "03-SOW主表",
    "04-验收条件",
    "05-任务明细",
    "06-集成点",
    "20-项目汇总",
}
RISKY_TEXT = re.compile(r"^[=+\-@]")
BARE_TEXTJOIN = re.compile(r"(?<![\w.])TEXTJOIN\(")
DETERMINISTIC_TIME = dt.datetime(2000, 1, 1, 0, 0, 0)
DETERMINISTIC_ZIP_TIME = (2000, 1, 1, 0, 0, 0)
# zipfile 按运行平台写入宿主标记（Unix 3 / Windows 0），openpyxl 从临时文件流出的条目还会
# 带上该文件的权限位。两者都与输入无关，必须钉死，否则同一份已批准数据在不同平台生成的
# 工作簿字节不同，package 复用和 manifest 绑定会失效。
DETERMINISTIC_CREATE_SYSTEM = 3
DETERMINISTIC_UNIX_MODE = 0o600


def safe_text(value: object) -> object:
    if isinstance(value, str) and RISKY_TEXT.match(value):
        return "'" + value
    return value


def formula_text(value: object) -> str:
    """Return a formula's text without discarding legacy array metadata."""
    if isinstance(value, ArrayFormula):
        value = value.text
    if not isinstance(value, str):
        raise TypeError("formula value is not text")
    return value


def normalize_table_formula(formula: object) -> str:
    """Serialize table references and future functions in OOXML form."""
    formula = formula_text(formula)
    parts = formula.split('"')
    for index in range(0, len(parts), 2):
        parts[index] = parts[index].replace("@", "[#This Row],")
        parts[index] = BARE_TEXTJOIN.sub("_xlfn.TEXTJOIN(", parts[index])
    return '"'.join(parts)


def display_text(value: object) -> object:
    return safe_text(value if value is not None else "")


def joined(values: list[object]) -> object:
    return display_text("、".join(str(value) for value in values))


def localized(value: object, labels: dict[str, str]) -> object:
    text = str(value) if value is not None else ""
    return display_text(labels.get(text, text))


def require_unique_names(entries: list[dict[str, Any]], label: str) -> None:
    projected_names: dict[str, str] = {}
    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{label} display name is blank")
        projected = str(safe_text(name))
        key = unicodedata.normalize("NFC", projected).casefold()
        if key in projected_names:
            raise ValueError(
                f"{label} display name is duplicated after Excel projection: "
                f"{projected_names[key]} / {name}"
            )
        projected_names[key] = name


def feature_rationale(
    feature: dict[str, Any],
    decision_names: dict[str, str],
) -> object:
    rationale = str(feature["source"].get("rationale", ""))
    identifiers = list(feature["source"].get("designDecisionIds", []))
    missing = next(
        (identifier for identifier in identifiers if identifier not in decision_names),
        None,
    )
    if missing is not None:
        raise ValueError(f"display name is missing for design decision: {missing}")
    if identifiers:
        alternatives = (
            re.escape(identifier)
            for identifier in sorted(identifiers, key=len, reverse=True)
        )
        pattern = re.compile(
            rf"(?<![A-Za-z0-9-])(?:{'|'.join(alternatives)})(?![A-Za-z0-9-])"
        )
        rationale = pattern.sub(lambda match: decision_names[match.group(0)], rationale)
    return display_text(rationale)


def topic_label(topic: object) -> object:
    return display_text(TOPIC_LABELS.get(str(topic), str(topic) if topic is not None else ""))


def build_asis_detail_rows(
    asis: dict[str, Any],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for entry in asis["effectiveStartItems"]:
        rows.append(
            {
                "主题名称": topic_label(entry["topic"]),
                "现状条目名称": display_text(entry["name"]),
                "现状描述": display_text(entry["summary"]),
                "起点可用性": ASIS_START_AVAILABILITY_LABELS[
                    "EXPECTED_BEFORE_START" if entry["commitmentIds"] else "CURRENT"
                ],
            }
        )
    return rows


def fill_asis_header(workbook: Any, asis: dict[str, Any]) -> None:
    scope = asis["analysisScope"]
    repositories = (
        []
        if scope["mode"] == "GREENFIELD"
        else scope["repositorySnapshots"]
    )
    repo_text = joined(
        [
            f"{repository['name']}@{str(repository['revision'])[:12]}"
            for repository in repositories
        ]
    ) if repositories else "无"
    excluded_text = joined(scope["excludedAreas"]) if scope["excludedAreas"] else "无"
    mode = {"GREENFIELD": "全新建设", "BROWNFIELD": "存量改造"}.get(
        scope["mode"], scope["mode"]
    )
    header = safe_text(
        f"模式：{mode} | 截止日期：{scope['asOfDate']} | "
        f"代码仓库：{repo_text} | 排除范围：{excluded_text}"
    )
    cell = workbook["90-系统现状"]["A2"]
    cell.value = header
    cell.data_type = "s"
    worksheet = cell.parent
    prototype_height = worksheet.row_dimensions[cell.row].height or 15
    worksheet.row_dimensions[cell.row].height = max(
        prototype_height,
        wrapped_line_count(header, effective_cell_width(worksheet, cell)) * 15,
    )


def build_rows(
    data: dict[str, dict[str, Any]],
    base_unit_names: dict[str, str],
) -> dict[str, list[dict[str, object]]]:
    requirements = data["requirements"]
    delivery = data["delivery"]
    estimate = data["estimate"]
    epics = {entry["epicId"]: entry for entry in requirements["epics"]}
    features = {entry["featureId"]: entry for entry in requirements["features"]}
    stories = {entry["storyId"]: entry for entry in delivery["stories"]}
    assumptions = {entry["assumptionId"]: entry for entry in delivery["assumptions"]}
    decision_names = {
        entry["designDecisionId"]: entry["name"]
        for entry in data["design"]["decisions"]
    }
    integration_tasks = {
        entry["integrationId"]: entry
        for entry in estimate["tasks"]
        if entry.get("integrationId")
    }
    effective_start_names = {
        entry["effectiveStartItemId"]: entry["name"]
        for entry in data["asis"]["effectiveStartItems"]
    }
    asis = data["asis"]
    for label, entries in (
        ("Epic", requirements["epics"]),
        ("Feature", requirements["features"]),
        ("Story", delivery["stories"]),
        ("Acceptance Criterion", delivery["acceptanceCriteria"]),
        ("Task", estimate["tasks"]),
        ("Assumption/Risk", delivery["assumptions"]),
        ("Effective Start", asis["effectiveStartItems"]),
    ):
        require_unique_names(entries, label)
    return {
        "EpicTable": [
            {
                "需求名称": entry["name"],
                "需求类型": EPIC_TYPE_LABELS[entry["type"]],
                "需求描述": entry["description"],
                "涉及系统/数据": entry.get("involvedSystemsData", ""),
                "目标结果": entry.get("targetOutcome", ""),
                "公共约束/范围外": entry.get("commonConstraintsOutOfScope", ""),
            }
            for entry in requirements["epics"]
        ],
        "FeatureTable": [
            {
                "需求名称": epics[entry["epicId"]]["name"],
                "子需求名称": entry["name"],
                "场景/范围描述": entry["description"],
                "涉及系统/数据": entry.get("involvedSystemsData", ""),
                "约束/NFR": entry.get("constraintsNfr", ""),
                "来源类型": FEATURE_SOURCE_LABELS[entry["source"]["type"]],
                "推断理由": feature_rationale(entry, decision_names),
            }
            for entry in requirements["features"]
        ],
        "SOWStoryTable": [
            {
                "子需求名称": features[entry["featureId"]]["name"],
                "故事名称": entry["name"],
                "UAT适用": "是" if entry["uatRelevant"] else "否",
                "关联假设/风险名称": assumptions[entry["assumptionId"]]["name"]
                if entry.get("assumptionId")
                else "",
            }
            for entry in delivery["stories"]
        ],
        "AcceptanceCriterionTable": [
            {
                "故事名称": stories[entry["storyId"]]["name"],
                "验收条件名称": entry["name"],
            }
            for entry in delivery["acceptanceCriteria"]
        ],
        "TaskTable": [
            {
                "故事名称": stories[entry["storyId"]]["name"],
                "任务名称": entry["name"],
                "基础单元名称": base_unit_names[entry["baseUnit"]],
                "工作模式": entry["workMode"],
                "工作模式理由": entry["workModeRationale"],
                "复杂度": entry["complexity"],
                "复杂度理由": entry.get("complexityRationale", ""),
                "关联现状条目": effective_start_names[entry["matchedEffectiveStartItemId"]]
                if entry.get("matchedEffectiveStartItemId")
                else "",
                "判断依据与备注": entry["rationale"],
            }
            for entry in estimate["tasks"]
        ],
        "IntegrationTable": [
            {
                "故事名称": stories[integration_tasks[entry["integrationId"]]["storyId"]]["name"],
                "集成任务名称": integration_tasks[entry["integrationId"]]["name"],
                "来源": entry["source"],
                "目标": entry["target"],
                "触发条件": entry["trigger"],
                "方向": DIRECTION_LABELS[entry["direction"]],
                "业务目的": entry["purpose"],
                "责任边界": "内部" if entry["owner"] == "INTERNAL" else "外部",
            }
            for entry in delivery["integrations"]
        ],
        "AssumptionRiskTable": [
            {
                "假设/风险名称": entry["name"],
                "类型": entry["type"],
                "触发条件": entry["trigger"],
                "责任边界": entry["responsibilityBoundary"],
                "状态": entry["status"],
                "处理方式": entry["handling"],
            }
            for entry in delivery["assumptions"]
        ],
        "AsIsDetailTable": build_asis_detail_rows(asis),
    }


def table_index(workbook: Any) -> dict[str, tuple[Any, Any]]:
    found: dict[str, tuple[Any, Any]] = {}
    for worksheet in workbook.worksheets:
        for table_name in worksheet.tables:
            if table_name in found:
                raise ValueError(f"duplicate template table: {table_name}")
            found[table_name] = (worksheet, worksheet.tables[table_name])
    missing = sorted(set(TABLES) - set(found))
    if missing:
        raise ValueError(f"template tables are missing: {missing}")
    return found


def enable_asis_manual_editing(workbook: Any) -> None:
    worksheet = workbook["90-系统现状"]
    worksheet.protection.sheet = False
    editable_fill = PatternFill(fill_type="solid", fgColor="FFFFFF")
    worksheet["A2"].protection = Protection(locked=False)
    worksheet["A2"].fill = copy.copy(editable_fill)
    for table_name in ASIS_TABLES:
        table_worksheet, table = table_index(workbook)[table_name]
        if table_worksheet is not worksheet:
            raise ValueError(f"As-Is table is on the wrong worksheet: {table_name}")
        min_col, min_row, max_col, max_row = range_boundaries(table.ref)
        for row in range(min_row + 1, max_row + 1):
            for column in range(min_col, max_col + 1):
                cell = worksheet.cell(row, column)
                cell.protection = Protection(locked=False)


def base_unit_name_map(workbook: Any) -> dict[str, str]:
    worksheet, table = table_index(workbook)["BaseUnitCatalogTable"]
    min_col, min_row, max_col, max_row = range_boundaries(table.ref)
    headers = [worksheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
    if "基础单元ID" not in headers or "基础单元名称" not in headers:
        raise ValueError("template base-unit name projection columns are missing")
    id_column = min_col + headers.index("基础单元ID")
    name_column = min_col + headers.index("基础单元名称")
    result: dict[str, str] = {}
    used_names: set[str] = set()
    for row in range(min_row + 1, max_row + 1):
        unit_id = worksheet.cell(row, id_column).value
        name = worksheet.cell(row, name_column).value
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise ValueError("template base-unit ID is blank")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"template base-unit name is blank: {unit_id}")
        if unit_id in result:
            raise ValueError(f"template base-unit ID is duplicated: {unit_id}")
        if name in used_names:
            raise ValueError(f"template base-unit name is duplicated: {name}")
        result[unit_id] = name
        used_names.add(name)
    return result


def clear_orphan_table_formulas(workbook: Any) -> None:
    for worksheet in workbook.worksheets:
        table_ranges = [
            range_boundaries(worksheet.tables[name].ref)
            for name in worksheet.tables
        ]
        for row in worksheet.iter_rows():
            for cell in row:
                if cell.data_type != "f" or not isinstance(cell.value, str):
                    continue
                if "@" not in cell.value and "[#This Row]," not in cell.value:
                    continue
                inside_table = any(
                    min_col <= cell.column <= max_col
                    and min_row < cell.row <= max_row
                    for min_col, min_row, max_col, max_row in table_ranges
                )
                if not inside_table:
                    cell.value = None


def copy_style(source: Any, target: Any) -> None:
    target.font = copy.copy(source.font)
    target.fill = copy.copy(source.fill)
    target.border = copy.copy(source.border)
    target.alignment = copy.copy(source.alignment)
    target.number_format = source.number_format
    target.protection = copy.copy(source.protection)


def wrapped_line_count(value: str, column_width: float) -> int:
    lines = value.splitlines() or [""]
    return sum(
        max(
            1,
            math.ceil(
                sum(
                    2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
                    for character in line
                )
                / column_width
            ),
        )
        for line in lines
    )


def effective_cell_width(worksheet: Any, cell: Any) -> float:
    for merged in worksheet.merged_cells.ranges:
        if cell.coordinate in merged:
            return sum(
                worksheet.column_dimensions[get_column_letter(column)].width or 8.43
                for column in range(merged.min_col, merged.max_col + 1)
            )
    return worksheet.column_dimensions[get_column_letter(cell.column)].width or 8.43


def fill_table(workbook: Any, table_name: str, rows: list[dict[str, object]]) -> None:
    worksheet, table = table_index(workbook)[table_name]
    min_col, min_row, max_col, old_max_row = range_boundaries(table.ref)
    prototype_row = min_row + 1
    headers = [worksheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
    if not all(isinstance(header, str) for header in headers):
        raise ValueError(f"invalid table header: {table_name}")
    expected_headers = TABLE_HEADERS[table_name]
    if headers != expected_headers:
        raise ValueError(
            f"template header mismatch in {table_name}: expected {expected_headers}, got {headers}"
        )
    metadata_headers = [column.name for column in table.tableColumns]
    if metadata_headers != expected_headers:
        raise ValueError(
            f"template table metadata mismatch in {table_name}: "
            f"expected {expected_headers}, got {metadata_headers}"
        )
    prototypes = [worksheet.cell(prototype_row, column) for column in range(min_col, max_col + 1)]
    formulas = {
        offset: (
            normalize_table_formula(cell.value),
            isinstance(cell.value, ArrayFormula),
        )
        for offset, cell in enumerate(prototypes)
        if cell.data_type == "f" and isinstance(cell.value, (str, ArrayFormula))
    }
    expected_formula_headers = FORMULA_HEADERS.get(table_name, set())
    actual_formula_headers = {headers[offset] for offset in formulas}
    if actual_formula_headers != expected_formula_headers:
        raise ValueError(f"formula prototype mismatch in {table_name}")
    for column_offset, column in enumerate(table.tableColumns):
        specification = formulas.get(column_offset)
        if specification is None:
            column.calculatedColumnFormula = None
            continue
        formula, is_array = specification
        column.calculatedColumnFormula = (
            TableFormula(
                array=True if is_array else None,
                attr_text=formula.removeprefix("="),
            )
        )

    physical_rows = rows if rows else [{}]
    for row in range(prototype_row, max(old_max_row, min_row + len(physical_rows), prototype_row) + 1):
        for column in range(min_col, max_col + 1):
            worksheet.cell(row, column).value = None

    prototype_height = worksheet.row_dimensions[prototype_row].height
    for offset, payload in enumerate(physical_rows, start=1):
        row = min_row + offset
        if prototype_height is not None:
            worksheet.row_dimensions[row].height = prototype_height
        for column_offset, header in enumerate(headers):
            cell = worksheet.cell(row, min_col + column_offset)
            copy_style(prototypes[column_offset], cell)
            if column_offset in formulas:
                formula, is_array = formulas[column_offset]
                translated = Translator(
                    formula,
                    origin=prototypes[column_offset].coordinate,
                ).translate_formula(cell.coordinate)
                cell.value = (
                    ArrayFormula(ref=cell.coordinate, text=translated)
                    if is_array
                    else translated
                )
            else:
                value = None if not rows else safe_text(payload.get(header, ""))
                cell.value = value
                if isinstance(value, str):
                    cell.data_type = "s"
        if table_name in ASIS_TABLES:
            wrapped_lines = max(
                (
                    wrapped_line_count(
                        cell.value,
                        effective_cell_width(worksheet, cell),
                    )
                    for cell in worksheet[row][min_col - 1 : max_col]
                    if cell.alignment.wrap_text and isinstance(cell.value, str)
                ),
                default=1,
            )
            worksheet.row_dimensions[row].height = max(
                prototype_height or 15,
                wrapped_lines * 15,
            )

    new_max_row = min_row + len(physical_rows)
    for row in range(new_max_row + 1, worksheet.max_row + 1):
        trailing_cells = [
            worksheet.cell(row, column)
            for column in range(min_col, max_col + 1)
        ]
        if any(cell.value not in (None, "") for cell in trailing_cells):
            break
        for cell in trailing_cells:
            cell._style = None
        if worksheet.row_dimensions[row].height == prototype_height:
            worksheet.row_dimensions[row].height = None
    table.ref = f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{new_max_row}"
    if table_name in ASIS_TABLES and table.autoFilter is None:
        table.autoFilter = AutoFilter(ref=table.ref)
    if table.autoFilter is not None:
        table.autoFilter.ref = table.ref


def projection_contract(workbook: Any) -> dict[str, dict[str, object]]:
    contract: dict[str, dict[str, object]] = {}
    for table_name, (worksheet, table) in table_index(workbook).items():
        if table_name not in TABLES:
            continue
        min_col, min_row, max_col, _ = range_boundaries(table.ref)
        headers = [worksheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
        if not all(isinstance(header, str) for header in headers):
            raise ValueError(f"invalid table header: {table_name}")
        formulas: dict[str, tuple[str, str]] = {}
        styles: dict[str, tuple[object, ...]] = {}
        for offset, header in enumerate(headers):
            cell = worksheet.cell(min_row + 1, min_col + offset)
            styles[str(header)] = style_signature(cell)
            if cell.data_type == "f" and isinstance(cell.value, (str, ArrayFormula)):
                formula = normalize_table_formula(cell.value)
                if "_xlfn._xlws." in formula:
                    raise ValueError(
                        f"unsupported dynamic worksheet formula in {table_name}.{header}"
                    )
                formulas[str(header)] = (
                    cell.coordinate,
                    formula,
                    isinstance(cell.value, ArrayFormula),
                )
        contract[table_name] = {
            "headers": headers,
            "formulas": formulas,
            "styles": styles,
        }
    return contract


def style_signature(cell: Any) -> tuple[object, ...]:
    return (
        copy.copy(cell.font),
        copy.copy(cell.fill),
        copy.copy(cell.border),
        copy.copy(cell.alignment),
        cell.number_format,
        copy.copy(cell.protection),
    )


def fill_input_hashes(workbook: Any, input_hashes: dict[str, str]) -> None:
    expected = {
        "sourceRequirements",
        "asis",
        "design",
        "derivedRequirements",
        "delivery",
        "estimate",
    }
    if set(input_hashes) != expected:
        raise ValueError("workbook input hash set is invalid")
    worksheet = workbook["00-使用说明"]
    slots = {
        str(worksheet.cell(row, 1).value): worksheet.cell(row, 2)
        for row in range(1, worksheet.max_row + 1)
        if worksheet.cell(row, 1).value in expected
    }
    if set(slots) != expected:
        raise ValueError("workbook input hash slots are missing")
    for name, digest in input_hashes.items():
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError(f"workbook input hash is invalid: {name}")
        slots[name].value = digest
        slots[name].data_type = "s"


def verify_workbook(
    path: Path,
    expected: dict[str, list[dict[str, object]]],
    contract: dict[str, dict[str, object]],
    input_hashes: dict[str, str],
) -> None:
    workbook = openpyxl.load_workbook(path, data_only=False, read_only=False)
    try:
        index = table_index(workbook)
        if workbook.calculation.calcMode != "auto":
            raise ValueError("workbook recalculation is not enabled")
        for table_name, rows in expected.items():
            worksheet, table = index[table_name]
            min_col, min_row, max_col, max_row = range_boundaries(table.ref)
            actual_count = max_row - min_row
            expected_count = max(1, len(rows))
            if actual_count != expected_count:
                raise ValueError(f"table row count mismatch: {table_name}")
            headers = [worksheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
            if headers != TABLE_HEADERS[table_name]:
                raise ValueError(f"table header mismatch: {table_name}")
            specification = contract[table_name]
            if headers != specification["headers"]:
                raise ValueError(f"table headers changed: {table_name}")
            formulas = specification["formulas"]
            styles = specification["styles"]
            assert isinstance(formulas, dict) and isinstance(styles, dict)
            physical_rows = rows if rows else [{}]
            for row_offset, payload in enumerate(physical_rows, start=1):
                for column_offset, header in enumerate(headers):
                    cell = worksheet.cell(min_row + row_offset, min_col + column_offset)
                    if style_signature(cell) != styles[header]:
                        raise ValueError(f"prototype style changed in {table_name}.{header}")
                    if header in formulas:
                        origin, prototype, is_array = formulas[header]
                        expected_formula = Translator(
                            prototype,
                            origin=origin,
                        ).translate_formula(cell.coordinate)
                        actual_formula = (
                            formula_text(cell.value)
                            if isinstance(cell.value, (str, ArrayFormula))
                            else None
                        )
                        formula_kind_matches = (
                            isinstance(cell.value, ArrayFormula)
                            and cell.value.ref == cell.coordinate
                            if is_array
                            else isinstance(cell.value, str)
                        )
                        if (
                            actual_formula != expected_formula
                            or cell.data_type != "f"
                            or not formula_kind_matches
                        ):
                            raise ValueError(f"formula mismatch in {table_name}.{header}")
                    else:
                        expected_value = None if not rows else safe_text(payload.get(header, ""))
                        if expected_value == "":
                            expected_value = None
                        if cell.value != expected_value:
                            raise ValueError(f"projected value mismatch in {table_name}.{header}")
                        if isinstance(expected_value, str) and cell.data_type != "s":
                            raise ValueError(f"projected text type mismatch in {table_name}.{header}")
            calculated_headers = {
                column.name
                for column in table.tableColumns
                if column.calculatedColumnFormula is not None
                and column.calculatedColumnFormula.text
            }
            if calculated_headers != FORMULA_HEADERS.get(table_name, set()):
                raise ValueError(f"calculated column mismatch in {table_name}")
            formula_columns = {
                column.name: column.calculatedColumnFormula
                for column in table.tableColumns
                if column.calculatedColumnFormula is not None
            }
            for header, (_, _, is_array) in formulas.items():
                if (formula_columns[header].array is True) != is_array:
                    raise ValueError(f"calculated column array mismatch in {table_name}.{header}")
            if table_name in ASIS_TABLES and table.autoFilter is None:
                raise ValueError(f"autoFilter is missing: {table_name}")
            if table.autoFilter is not None and table.autoFilter.ref != table.ref:
                raise ValueError(f"autoFilter range mismatch: {table_name}")
        asis_sheet = workbook["90-系统现状"]
        if asis_sheet.protection.sheet:
            raise ValueError("As-Is worksheet must allow manual editing")
        if asis_sheet["A2"].protection.locked:
            raise ValueError("As-Is scope summary must allow manual editing")
        if (
            asis_sheet["A2"].fill.fill_type != "solid"
            or asis_sheet["A2"].fill.fgColor.rgb[-6:] != "FFFFFF"
        ):
            raise ValueError("As-Is scope summary must use the editable fill")
        table_sheet, table = index["AsIsDetailTable"]
        min_col, min_row, max_col, max_row = range_boundaries(table.ref)
        headers = [
            str(table_sheet.cell(min_row, column).value)
            for column in range(min_col, max_col + 1)
        ]
        for row in range(min_row + 1, max_row + 1):
            for offset, header in enumerate(headers):
                cell = table_sheet.cell(row, min_col + offset)
                if cell.protection.locked:
                    raise ValueError(f"As-Is cell is not editable: {cell.coordinate}")
                expected_fill = "FFF2CC" if header in ASIS_DROPDOWN_HEADERS else "FFFFFF"
                if (
                    cell.fill.fill_type != "solid"
                    or cell.fill.fgColor.rgb[-6:] != expected_fill
                ):
                    raise ValueError(f"As-Is editable cell has the wrong fill: {cell.coordinate}")
        for sheet_name in PROTECTED_SHEETS:
            protection = workbook[sheet_name].protection
            if not protection.sheet:
                raise ValueError(f"worksheet protection is missing: {sheet_name}")
            if protection.formatColumns or protection.formatRows:
                raise ValueError(f"worksheet dimensions are locked: {sheet_name}")
            if protection.autoFilter or protection.sort:
                raise ValueError(f"worksheet filtering or sorting is locked: {sheet_name}")
            if not protection.formatCells:
                raise ValueError(f"worksheet cell formatting is unlocked: {sheet_name}")
        worksheet = workbook["00-使用说明"]
        actual_hashes = {
            str(worksheet.cell(row, 1).value): worksheet.cell(row, 2).value
            for row in range(1, worksheet.max_row + 1)
            if worksheet.cell(row, 1).value in input_hashes
        }
        if actual_hashes != input_hashes:
            raise ValueError("workbook input hash projection mismatch")
    finally:
        workbook.close()


def deterministic_external_attr(external_attr: int) -> int:
    """Keep an entry's file-type and DOS bits, but pin its Unix mode to a fixed value."""
    return (external_attr & 0xFFFF0000) & ~(0o777 << 16) | (DETERMINISTIC_UNIX_MODE << 16)


def normalize_xlsx(path: Path) -> None:
    """Normalize ZIP metadata so identical inputs produce identical XLSX bytes."""
    with zipfile.ZipFile(path, "r") as source:
        members = []
        for entry in source.infolist():
            payload = source.read(entry.filename)
            if entry.filename == "docProps/core.xml":
                payload = re.sub(
                    rb"<dcterms:modified[^>]*>.*?</dcterms:modified>",
                    b'<dcterms:modified xsi:type="dcterms:W3CDTF">2000-01-01T00:00:00Z</dcterms:modified>',
                    payload,
                )
            members.append((entry.filename, payload, entry))
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            for name, payload, original in sorted(members, key=lambda item: item[0]):
                entry = zipfile.ZipInfo(name, DETERMINISTIC_ZIP_TIME)
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.create_system = DETERMINISTIC_CREATE_SYSTEM
                entry.external_attr = deterministic_external_attr(original.external_attr)
                entry.flag_bits = original.flag_bits
                target.writestr(entry, payload)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_workbook(
    template_path: Path,
    data: dict[str, dict[str, Any]],
    output_path: Path,
    input_hashes: dict[str, str],
) -> None:
    workbook = openpyxl.load_workbook(template_path, data_only=False, read_only=False)
    if workbook.calculation is None:
        workbook.calculation = CalcProperties()
    try:
        table_index(workbook)
        enable_asis_manual_editing(workbook)
        rows = build_rows(data, base_unit_name_map(workbook))
        if len(rows["AsIsDetailTable"]) > ASIS_INPUT_LIMIT:
            raise ValueError("As-Is detail table exceeds template capacity")
        contract = projection_contract(workbook)
        clear_orphan_table_formulas(workbook)
        fill_asis_header(workbook, data["asis"])
        fill_input_hashes(workbook, input_hashes)
        for table_name in TABLES:
            fill_table(workbook, table_name, rows[table_name])
        workbook.calculation.calcMode = "auto"
        workbook.calculation.calcOnSave = True
        workbook.calculation.forceFullCalc = True
        workbook.calculation.fullCalcOnLoad = True
        workbook.properties.created = DETERMINISTIC_TIME
        workbook.properties.modified = DETERMINISTIC_TIME
        workbook.save(output_path)
    finally:
        workbook.close()
    normalize_xlsx(output_path)
    verify_workbook(output_path, rows, contract, input_hashes)
