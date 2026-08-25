from __future__ import annotations

import copy
import datetime as dt
import math
import os
import re
import tempfile
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.filters import AutoFilter
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
ASIS_TABLES = {"AsIsTopicTable", "AsIsDetailTable"}
TABLES = (
    "EpicTable",
    "FeatureTable",
    "SOWStoryTable",
    "AcceptanceCriterionTable",
    "TaskTable",
    "IntegrationTable",
    "AssumptionRiskTable",
    "AsIsTopicTable",
    "AsIsDetailTable",
)
FORMULA_HEADERS = {
    "SOWStoryTable": {"需求", "子需求", "验收条件", "任务明细", "人天", "关联假设ID", "假设状态"},
    "TaskTable": {"任务族", "基础人天", "复杂度倍率", "人天小计"},
    "IntegrationTable": {"集成Task ID", "工作模式", "复杂度", "支持单价", "SIT人天"},
    "AssumptionRiskTable": {"关联 Story 人天"},
}
RISKY_TEXT = re.compile(r"^[=+\-@]")
BARE_TEXTJOIN = re.compile(r"(?<![\w.])TEXTJOIN\(")
DETERMINISTIC_TIME = dt.datetime(2000, 1, 1, 0, 0, 0)
DETERMINISTIC_ZIP_TIME = (2000, 1, 1, 0, 0, 0)


def safe_text(value: object) -> object:
    if isinstance(value, str) and RISKY_TEXT.match(value):
        return "'" + value
    return value


def normalize_table_formula(formula: str) -> str:
    """Serialize table references and future functions in OOXML form."""
    parts = formula.split('"')
    for index in range(0, len(parts), 2):
        parts[index] = parts[index].replace("@", "[#This Row],")
        parts[index] = BARE_TEXTJOIN.sub("_xlfn.TEXTJOIN(", parts[index])
    return '"'.join(parts)


def display_text(value: object) -> object:
    return safe_text(value if value is not None else "")


def joined(values: list[object]) -> object:
    return display_text("、".join(str(value) for value in values))


def topic_label(topic: object) -> object:
    return display_text(TOPIC_LABELS.get(str(topic), str(topic) if topic is not None else ""))


def build_asis_topic_rows(asis: dict[str, Any]) -> list[dict[str, object]]:
    assessments = {
        entry["topic"]: entry
        for entry in asis["topicAssessments"]
    }
    counts = {
        "items": Counter(entry["topic"] for entry in asis["items"]),
        "commitments": Counter(entry["topic"] for entry in asis["commitments"]),
        "effectiveStartItems": Counter(
            entry["topic"] for entry in asis["effectiveStartItems"]
        ),
        "uncertainties": Counter(entry["topic"] for entry in asis["uncertainties"]),
    }
    rows: list[dict[str, object]] = []
    for topic, label in TOPIC_LABELS.items():
        assessment = assessments.get(topic, {})
        rows.append(
            {
                "主题": label,
                "评估状态": display_text(assessment.get("status", "")),
                "结论": display_text(assessment.get("summary", "")),
                "当前事实数": counts["items"][topic],
                "承诺数": counts["commitments"][topic],
                "有效起点数": counts["effectiveStartItems"][topic],
                "未决数": counts["uncertainties"][topic],
            }
        )
    return rows


def build_asis_detail_rows(asis: dict[str, Any]) -> list[dict[str, object]]:
    evidence_references: dict[str, list[object]] = defaultdict(list)
    for evidence in asis["evidence"]:
        for supported_id in evidence["supportsIds"]:
            evidence_references[supported_id].append(evidence["reference"])

    entity_topics = {
        entry[id_field]: entry["topic"]
        for collection, id_field in (
            (asis["items"], "asIsItemId"),
            (asis["commitments"], "commitmentId"),
            (asis["effectiveStartItems"], "effectiveStartItemId"),
            (asis["uncertainties"], "uncertaintyId"),
        )
        for entry in collection
    }

    def evidence_for(record_id: object) -> object:
        return joined(evidence_references.get(str(record_id), []))

    rows: list[dict[str, object]] = []
    for entry in asis["items"]:
        relation = ""
        if entry["itemType"] == "INTEGRATION":
            relation = " | ".join(
                (
                    f"{entry.get('source', '')} → {entry.get('target', '')}",
                    f"触发：{entry.get('trigger', '')}",
                    f"方向：{entry.get('direction', '')}",
                    f"目的：{entry.get('purpose', '')}",
                    f"责任：{entry.get('owner', '')}",
                )
            )
        rows.append(
            {
                "主题": topic_label(entry["topic"]),
                "记录类型": "CURRENT_FACT",
                "记录 ID": display_text(entry["asIsItemId"]),
                "分类/状态": display_text(entry["itemType"]),
                "名称": display_text(entry["name"]),
                "摘要/理由": display_text(entry["summary"]),
                "关系/流向": display_text(relation),
                "关联 ID": joined(entry["repositoryIds"]),
                "证据引用": evidence_for(entry["asIsItemId"]),
            }
        )
    for entry in asis["commitments"]:
        rows.append(
            {
                "主题": topic_label(entry["topic"]),
                "记录类型": "COMMITMENT",
                "记录 ID": display_text(entry["commitmentId"]),
                "分类/状态": display_text(
                    f"{entry['implementationStatus']} / {entry['treatment']}"
                ),
                "名称": display_text(entry["name"]),
                "摘要/理由": display_text(entry["summary"]),
                "关系/流向": display_text(entry["changeType"]),
                "关联 ID": joined(
                    [
                        entry["priorSowId"],
                        *entry["affectedItemIds"],
                        *entry["relatedFeatureIds"],
                    ]
                ),
                "证据引用": joined(
                    [
                        entry["sourceReference"],
                        *evidence_references.get(entry["commitmentId"], []),
                    ]
                ),
            }
        )
    for entry in asis["effectiveStartItems"]:
        rows.append(
            {
                "主题": topic_label(entry["topic"]),
                "记录类型": "EFFECTIVE_START",
                "记录 ID": display_text(entry["effectiveStartItemId"]),
                "分类/状态": display_text(entry["itemType"]),
                "名称": display_text(entry["name"]),
                "摘要/理由": display_text(entry["summary"]),
                "关系/流向": "",
                "关联 ID": joined(
                    [*entry["sourceItemIds"], *entry["commitmentIds"]]
                ),
                "证据引用": evidence_for(entry["effectiveStartItemId"]),
            }
        )
    for entry in asis["coverage"]:
        rows.append(
            {
                "主题": "Feature覆盖",
                "记录类型": "COVERAGE",
                "记录 ID": display_text(entry["featureId"]),
                "分类/状态": display_text(entry["status"]),
                "名称": "",
                "摘要/理由": display_text(entry["rationale"]),
                "关系/流向": "",
                "关联 ID": joined(
                    [
                        *entry["effectiveStartItemIds"],
                        *entry["commitmentIds"],
                        *entry["uncertaintyIds"],
                    ]
                ),
                "证据引用": evidence_for(entry["featureId"]),
            }
        )
    for entry in asis["uncertainties"]:
        rows.append(
            {
                "主题": topic_label(entry["topic"]),
                "记录类型": "UNCERTAINTY",
                "记录 ID": display_text(entry["uncertaintyId"]),
                "分类/状态": display_text(entry["recommendedHandling"]),
                "名称": display_text(entry["question"]),
                "摘要/理由": display_text(entry["impact"]),
                "关系/流向": display_text(entry["owner"]),
                "关联 ID": joined(entry["relatedFeatureIds"]),
                "证据引用": evidence_for(entry["uncertaintyId"]),
            }
        )
    for entry in asis["evidence"]:
        topic = next(
            (
                entity_topics[supported_id]
                for supported_id in entry["supportsIds"]
                if supported_id in entity_topics
            ),
            "",
        )
        rows.append(
            {
                "主题": topic_label(topic),
                "记录类型": "EVIDENCE",
                "记录 ID": display_text(entry["evidenceId"]),
                "分类/状态": display_text(
                    f"{entry['kind']} / {entry['runtimeOutcome']}"
                    if entry["kind"] == "RUNTIME"
                    else entry["kind"]
                ),
                "名称": display_text(entry["reference"]),
                "摘要/理由": display_text(entry["summary"]),
                "关系/流向": "",
                "关联 ID": joined(entry["supportsIds"]),
                "证据引用": display_text(entry["reference"]),
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
            f"{repository['repoId']}@{str(repository['revision'])[:12]}"
            for repository in repositories
        ]
    ) if repositories else "无"
    excluded_text = joined(scope["excludedAreas"]) if scope["excludedAreas"] else "无"
    header = safe_text(
        f"模式：{scope['mode']} | As-of：{scope['asOfDate']} | "
        f"Repo：{repo_text} | 排除范围：{excluded_text}"
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


def build_rows(data: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, object]]]:
    requirements = data["requirements"]
    delivery = data["delivery"]
    estimate = data["estimate"]
    epics = {entry["epicId"]: entry for entry in requirements["epics"]}
    gaps = {entry["gapId"]: entry for entry in delivery["gaps"]}
    assumption_story_ids: dict[str, list[str]] = defaultdict(list)
    for relation in delivery["assumptionStories"]:
        story_ids = assumption_story_ids[relation["assumptionId"]]
        if relation["storyId"] not in story_ids:
            story_ids.append(relation["storyId"])

    asis = data["asis"]
    return {
        "EpicTable": [
            {
                "Epic ID": entry["epicId"],
                "需求类型": entry["type"],
                "需求名称": entry["name"],
                "需求描述": entry["description"],
                "涉及系统/数据": entry.get("involvedSystemsData", ""),
                "目标结果": entry.get("targetOutcome", ""),
                "公共约束/范围外": entry.get("commonConstraintsOutOfScope", ""),
            }
            for entry in requirements["epics"]
        ],
        "FeatureTable": [
            {
                "Feature ID": entry["featureId"],
                "Epic ID": entry["epicId"],
                "Epic 名称": epics[entry["epicId"]]["name"],
                "子需求名称": entry["name"],
                "场景/范围描述": entry["description"],
                "涉及系统/数据": entry.get("involvedSystemsData", ""),
                "约束/NFR": entry.get("constraintsNfr", ""),
                "来源类型": entry["source"]["type"],
                "推断理由": entry["source"].get("rationale", ""),
            }
            for entry in requirements["features"]
        ],
        "SOWStoryTable": [
            {
                "Story ID": entry["storyId"],
                "Story名称": entry["name"],
                "Feature ID": gaps[entry["gapId"]]["featureId"],
                "UAT分母": "是" if entry["uatRelevant"] else "否",
            }
            for entry in delivery["stories"]
        ],
        "AcceptanceCriterionTable": [
            {
                "AC ID": entry["acceptanceCriterionId"],
                "Story ID": entry["storyId"],
                "顺序": entry["sequence"],
                "验收结果": entry["result"],
            }
            for entry in delivery["acceptanceCriteria"]
        ],
        "TaskTable": [
            {
                "Task ID": entry["taskId"],
                "Story ID": entry["storyId"],
                "任务说明": entry["name"],
                "基础单元ID": entry["baseUnit"],
                "工作模式": entry["workMode"],
                "工作模式理由": entry["workModeRationale"],
                "复杂度": entry["complexity"],
                "复杂度理由": entry.get("complexityRationale", ""),
                "Integration ID": entry.get("integrationId", ""),
                "系统现状匹配": "、".join(entry["matchedEffectiveStartItemIds"]),
                "判断依据与备注": entry["rationale"],
            }
            for entry in estimate["tasks"]
        ],
        "IntegrationTable": [
            {
                "Integration ID": entry["integrationId"],
                "Story ID": entry["storyId"],
                "来源": entry["source"],
                "目标": entry["target"],
                "触发条件": entry["trigger"],
                "方向": entry["direction"],
                "业务目的": entry["purpose"],
                "责任边界": "内部" if entry["owner"] == "INTERNAL" else "外部",
            }
            for entry in delivery["integrations"]
        ],
        "AssumptionRiskTable": [
            {
                "假设ID": entry["assumptionId"],
                "类型": entry["type"],
                "名称": entry["name"],
                "触发条件": entry["trigger"],
                "关联 Story ID": "、".join(assumption_story_ids[entry["assumptionId"]]),
                "责任边界": entry["responsibilityBoundary"],
                "状态": entry["status"],
                "处理方式": entry["handling"],
            }
            for entry in delivery["assumptions"]
        ],
        "AsIsTopicTable": build_asis_topic_rows(asis),
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
    prototypes = [worksheet.cell(prototype_row, column) for column in range(min_col, max_col + 1)]
    formulas = {
        offset: normalize_table_formula(cell.value)
        for offset, cell in enumerate(prototypes)
        if cell.data_type == "f" and isinstance(cell.value, str)
    }
    expected_formula_headers = FORMULA_HEADERS.get(table_name, set())
    actual_formula_headers = {headers[offset] for offset in formulas}
    if actual_formula_headers != expected_formula_headers:
        raise ValueError(f"formula prototype mismatch in {table_name}")
    for column_offset, column in enumerate(table.tableColumns):
        formula = formulas.get(column_offset)
        column.calculatedColumnFormula = (
            TableFormula(attr_text=formula.removeprefix("="))
            if formula is not None
            else None
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
                cell.value = Translator(
                    formulas[column_offset],
                    origin=prototypes[column_offset].coordinate,
                ).translate_formula(cell.coordinate)
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
            if cell.data_type == "f" and isinstance(cell.value, str):
                formulas[str(header)] = (cell.coordinate, normalize_table_formula(cell.value))
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
            if not rows and worksheet.cell(min_row + 1, min_col).value not in (None, ""):
                raise ValueError(f"empty table placeholder is not blank: {table_name}")
            headers = [worksheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
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
                        origin, prototype = formulas[header]
                        expected_formula = Translator(
                            prototype,
                            origin=origin,
                        ).translate_formula(cell.coordinate)
                        if cell.value != expected_formula or cell.data_type != "f":
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
            if table_name in ASIS_TABLES and table.autoFilter is None:
                raise ValueError(f"autoFilter is missing: {table_name}")
            if table.autoFilter is not None and table.autoFilter.ref != table.ref:
                raise ValueError(f"autoFilter range mismatch: {table_name}")
        topic_sheet, topic_table = index["AsIsTopicTable"]
        detail_sheet, detail_table = index["AsIsDetailTable"]
        if topic_sheet is detail_sheet:
            topic_min_col, topic_min_row, topic_max_col, topic_max_row = range_boundaries(topic_table.ref)
            detail_min_col, detail_min_row, detail_max_col, detail_max_row = range_boundaries(detail_table.ref)
            if not (
                topic_max_col < detail_min_col
                or detail_max_col < topic_min_col
                or topic_max_row < detail_min_row
                or detail_max_row < topic_min_row
            ):
                raise ValueError("As-Is tables overlap")
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
                entry.create_system = original.create_system
                entry.external_attr = original.external_attr
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
    rows = build_rows(data)
    if len(rows["AsIsTopicTable"]) != len(TOPIC_LABELS):
        raise ValueError("AsIsTopicTable must contain exactly nine topics")
    try:
        table_index(workbook)
        contract = projection_contract(workbook)
        clear_orphan_table_formulas(workbook)
        for worksheet in workbook.worksheets:
            if worksheet.title != "00-使用说明":
                worksheet.freeze_panes = "A4"
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
