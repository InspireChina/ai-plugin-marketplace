from __future__ import annotations

import copy
import math
import re
import unicodedata
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
CATALOG_HEADERS = {
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
}
PARAMETER_HEADERS = {"参数代码", "名称", "值", "单位", "适用范围", "验证状态/说明"}
MODE_EFFORT_HEADERS = {
    "新建": "新建M档人天",
    "调整": "调整M档人天",
    "接入复用": "接入复用M档人天",
}
COMPLEXITIES = ("S", "M", "L")
CALIBRATED_PARAMETER_STATUSES = {"固定规则", "已校准", "已批准"}


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


def read_estimation_contract(template_path: Path) -> dict[str, Any]:
    """Read the workbook-owned task choices needed for defensive SOW validation."""
    workbook = openpyxl.load_workbook(template_path, data_only=False, read_only=False)
    try:
        index = table_index(workbook)

        def rows_for(table_name: str) -> list[dict[str, Any]]:
            if table_name not in index:
                raise ValueError(f"template table is missing: {table_name}")
            worksheet, table = index[table_name]
            min_col, min_row, max_col, max_row = range_boundaries(table.ref)
            headers = [
                worksheet.cell(min_row, column).value
                for column in range(min_col, max_col + 1)
            ]
            return [
                {
                    str(header): worksheet.cell(row, column).value
                    for header, column in zip(
                        headers,
                        range(min_col, max_col + 1),
                        strict=True,
                    )
                }
                for row in range(min_row + 1, max_row + 1)
            ]

        catalog_rows = rows_for("BaseUnitCatalogTable")
        parameter_rows = rows_for("ProjectParameterTable")
        if not catalog_rows or set(catalog_rows[0]) != CATALOG_HEADERS:
            raise ValueError("template BaseUnitCatalogTable headers are invalid")
        if not parameter_rows or set(parameter_rows[0]) != PARAMETER_HEADERS:
            raise ValueError("template ProjectParameterTable headers are invalid")

        base_units: dict[str, dict[str, Any]] = {}
        task_families: set[str] = set()
        options: set[tuple[str, str]] = set()
        text_headers = CATALOG_HEADERS - set(MODE_EFFORT_HEADERS.values())
        for index, row in enumerate(catalog_rows, start=1):
            required = [row.get(header) for header in text_headers]
            if any(not isinstance(value, str) or not value.strip() for value in required):
                raise ValueError("template base-unit catalog contains a blank definition")
            base_unit_id = str(row["基础单元ID"])
            if base_unit_id in base_units:
                raise ValueError(f"template base-unit ID is duplicated: {base_unit_id}")
            modes: list[str] = []
            for work_mode, effort_header in MODE_EFFORT_HEADERS.items():
                effort = row.get(effort_header)
                if effort == "❌":
                    continue
                if (
                    isinstance(effort, bool)
                    or not isinstance(effort, (int, float))
                    or effort <= 0
                ):
                    raise ValueError(
                        "template base effort must be a positive number or ❌: "
                        f"row {index}/{base_unit_id}/{effort_header}"
                    )
                modes.append(work_mode)
                options.add((base_unit_id, work_mode))
            if not modes:
                raise ValueError(
                    f"template must configure a work mode: {base_unit_id}"
                )
            base_units[base_unit_id] = {
                "name": str(row["基础单元名称"]),
                "taskFamily": str(row["任务族名称"]),
                "allowedWorkModes": modes,
                "complexityStandards": {
                    level: str(row[f"{level}标准"])
                    for level in COMPLEXITIES
                },
            }
            task_families.add(str(row["任务族ID"]))
        if len(base_units) != 37 or len(task_families) != 13:
            raise ValueError("template must define 37 base units in 13 task families")

        complexity_factors: dict[str, float] = {}
        parameter_codes: set[str] = set()
        for row in parameter_rows:
            code = row.get("参数代码")
            if not isinstance(code, str) or not code.strip():
                raise ValueError("template project parameter code is blank")
            if code in parameter_codes:
                raise ValueError(f"template project parameter is duplicated: {code}")
            parameter_codes.add(code)
            if not code.startswith("K_COMPLEXITY_"):
                continue
            level = code.removeprefix("K_COMPLEXITY_")
            if level not in COMPLEXITIES:
                raise ValueError(f"template complexity parameter is invalid: {code}")
            factor = row.get("值")
            if isinstance(factor, bool) or not isinstance(factor, (int, float)) or factor <= 0:
                raise ValueError(f"template complexity factor is invalid: {level}")
            status = row.get("验证状态/说明")
            if status not in CALIBRATED_PARAMETER_STATUSES:
                raise ValueError(f"complexity factor is not calibrated: {level}")
            complexity_factors[level] = float(factor)
        if set(complexity_factors) != set(COMPLEXITIES):
            raise ValueError(
                "template ProjectParameterTable must define "
                "K_COMPLEXITY_S, K_COMPLEXITY_M and K_COMPLEXITY_L"
            )
        return {
            "baseUnits": base_units,
            "taskOptions": options,
            "complexities": set(complexity_factors),
        }
    finally:
        workbook.close()


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


def verify_workbook(path: Path, expected: dict[str, list[dict[str, object]]]) -> None:
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
            for header in FORMULA_HEADERS.get(table_name, set()):
                column = min_col + headers.index(header)
                for row in range(min_row + 1, max_row + 1):
                    value = worksheet.cell(row, column).value
                    if not isinstance(value, str) or not value.startswith("="):
                        raise ValueError(f"formula missing in {table_name}.{header}")
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
    finally:
        workbook.close()


def write_workbook(template_path: Path, data: dict[str, dict[str, Any]], output_path: Path) -> None:
    workbook = openpyxl.load_workbook(template_path, data_only=False, read_only=False)
    if workbook.calculation is None:
        workbook.calculation = CalcProperties()
    rows = build_rows(data)
    if len(rows["AsIsTopicTable"]) != len(TOPIC_LABELS):
        raise ValueError("AsIsTopicTable must contain exactly nine topics")
    try:
        table_index(workbook)
        clear_orphan_table_formulas(workbook)
        for worksheet in workbook.worksheets:
            if worksheet.title != "00-使用说明":
                worksheet.freeze_panes = "A4"
        fill_asis_header(workbook, data["asis"])
        for table_name in TABLES:
            fill_table(workbook, table_name, rows[table_name])
        workbook.calculation.calcMode = "auto"
        workbook.calculation.calcOnSave = True
        workbook.calculation.forceFullCalc = True
        workbook.calculation.fullCalcOnLoad = True
        workbook.save(output_path)
    finally:
        workbook.close()
    verify_workbook(output_path, rows)
