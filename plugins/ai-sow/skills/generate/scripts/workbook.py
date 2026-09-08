from __future__ import annotations

import copy
import datetime as dt
import math
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.formula import ArrayFormula
from openpyxl.worksheet.table import TableFormula

from models import TaskStandardCatalog, WorkbookAudit
from sow_model import derive_sit_assignments
from task_standard_catalog import catalog as load_task_standard_catalog
if __package__:
    from .office_engine import normalize_xlsx, recalculate_workbook
    from .story_notes import model_story_note_projection
else:
    from office_engine import normalize_xlsx, recalculate_workbook
    from story_notes import model_story_note_projection


FORMAL_SHEETS = (
    "01-需求故事",
    "02-任务清单",
    "03-工作量汇总",
    "90-估算标准",
)
TABLES = ("SOWStoryTable", "TaskTable")
FORMAL_TABLES = {
    "SOWStoryTable",
    "TaskTable",
    "ProjectSummaryTable",
    "TaskStandardTable",
    "ProjectParameterTable",
}
FORMULA_HEADERS = {
    "SOWStoryTable": {"任务列表", "故事人天", "校验结果"},
    "TaskTable": {"工作类型名称", "M档标准人天", "复杂度系数", "任务人天", "SIT支持人天", "校验结果"},
}


def validate_formula_headers(table_name: str, headers: set[str]) -> None:
    """Allow either catalog selector while retaining every financial formula."""
    supported = [FORMULA_HEADERS[table_name]]
    if table_name == "TaskTable":
        supported.append(
            (FORMULA_HEADERS[table_name] - {"工作类型名称"}) | {"工作类型ID"}
        )
    if headers not in supported:
        raise ValueError(f"formula prototype mismatch in {table_name}")


TABLE_HEADERS = {
    "SOWStoryTable": [
        "需求",
        "子需求",
        "故事",
        "UAT适用",
        "验收条件",
        "备注",
        "任务列表",
        "故事人天",
        "校验结果",
    ],
    "TaskTable": [
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
    ],
}
COMPACT_TASK_HEADERS = [
    "集成类型" if header == "SIT支持分类" else header
    for header in TABLE_HEADERS["TaskTable"]
    if header != "SIT计费点ID"
]


def validate_table_headers(table_name: str, headers: list[str]) -> None:
    supported = [TABLE_HEADERS[table_name]]
    if table_name == "TaskTable":
        supported.append(COMPACT_TASK_HEADERS)
    if headers not in supported:
        raise ValueError(f"table header mismatch in {table_name}: {headers}")


def projected_input_value(table_name: str, header: str, payload: dict) -> object:
    value = payload.get(header, "")
    # Catalog selectors must match the authority verbatim. fill_table writes
    # strings with OOXML type 's', including names that begin with '='.
    if table_name == "TaskTable" and header == "工作类型名称":
        return value
    return safe_text(value)


SUMMARY_HEADERS = ["工作量项", "人天"]
CATALOG_HEADERS = [
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
PARAMETER_HEADERS = ["参数代码", "名称", "值", "单位", "适用范围", "验证状态/说明"]
PROTECTED_SHEETS = {"01-需求故事", "02-任务清单"}
RISKY_TEXT = re.compile(r"^[=+\-@]")
BARE_TEXTJOIN = re.compile(r"(?<![\w.])TEXTJOIN\(")
DETERMINISTIC_TIME = dt.datetime(2000, 1, 1, 0, 0, 0)
WRAPPED_LINE_HEIGHT = 15
WRAPPED_ROW_PADDING = 4
MAX_EXCEL_ROW_HEIGHT = 409.5
FORMULA_ERROR_PREFIXES = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!", "Err:")
SUMMARY_LABELS = (
    "直接开发人天",
    "SIT支持人天",
    "UAT支持人天",
    "总开发人天",
)


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


def comparable_formula(formula: object) -> str:
    """Normalize equivalent formula spelling used by Excel and LibreOffice."""
    value = formula_text(formula).replace("_xlfn.", "")
    return re.sub(r"\b(TRUE|FALSE)\(\)", r"\1", value)


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


def task_covered_story_ids(model, task):
    criteria = {row['acceptanceCriterionId']: row['storyId'] for row in model['acceptanceCriteria']}
    return {task['storyId'], *(criteria[key] for key in task.get('acceptanceCriterionIds', []) if key in criteria)}


def _task_display_names(model, catalog_rows):
    stories = {row['storyId']: row for row in model['stories']}
    policies = {row['policyId'] for row in model.get('policyInstances', [])}
    # Policy identifiers select a rule; the Story names its concrete deliverable.
    names = {task['taskId']: (stories[task['storyId']]['name']+'：'+catalog_rows[task['workTypeId']]['工作类型名称']
        if task['name'] in policies else task['name']) for task in model['tasks']}
    groups = {}
    for task in model['tasks']:
        key=unicodedata.normalize('NFC',str(safe_text(names[task['taskId']]))).casefold()
        groups.setdefault(key,[]).append(task)
    for tasks in groups.values():
        if len(tasks)>1:
            # Several independent work types may share one technical target description.
            # A repeated type remains ambiguous and must fail the uniqueness check.
            for task in tasks:
                names[task['taskId']]+='：'+catalog_rows[task['workTypeId']]['工作类型名称']
    require_unique_names([{'name':name} for name in names.values()], 'Task')
    return names


def shared_story_formula(header, formula, payload):
    """Project only display/coverage formulas; all monetary formulas stay in the template."""
    refs = payload.get('_sharedTaskReferences', [])
    if not refs or header not in {'任务列表','校验结果'}: return formula
    def literal(value): return '"'+str(safe_text(value)).replace('"','""')+'"'
    if header == '任务列表':
        predicate = re.search(r'TaskTable\[所属故事\]=\$C[0-9]+', formula)
        if predicate is None: raise ValueError('shared Story display prototype changed')
        shared = ['((TaskTable[所属故事]='+literal(ref['story'])+')*(TaskTable[任务名称]='+literal(ref['task'])+'))' for ref in refs]
        return formula.replace(predicate.group(), '('+'+'.join(['('+predicate.group()+')',*shared])+')>0')
    count = re.search(r'COUNTIF\(TaskTable\[所属故事\],\$C[0-9]+\)', formula)
    if count is None: raise ValueError('shared Story coverage prototype changed')
    shared = ['COUNTIFS(TaskTable[所属故事],'+literal(ref['story'])+',TaskTable[任务名称],'+literal(ref['task'])+')' for ref in refs]
    return formula.replace(count.group(), '('+'+'.join([count.group(),*shared])+')')


def build_rows(
    model: dict[str, Any],
    task_catalog: TaskStandardCatalog,
) -> dict[str, list[dict[str, object]]]:
    if not model["stories"]:
        raise ValueError("formal workbook requires at least one Story")
    if not model["tasks"]:
        raise ValueError("formal workbook requires at least one Task")

    epics = {entry["epicId"]: entry for entry in model["epics"]}
    features = {entry["featureId"]: entry for entry in model["features"]}
    stories = {entry["storyId"]: entry for entry in model["stories"]}
    catalog_rows = dict(task_catalog.by_work_type_id)

    for label, entries in (
        ("Epic", model["epics"]),
        ("Feature", model["features"]),
        ("Story", model["stories"]),
    ):
        require_unique_names(entries, label)

    display_names = _task_display_names(model, catalog_rows)
    acceptance_names_by_story: dict[str, list[str]] = {}
    for criterion in model["acceptanceCriteria"]:
        acceptance_names_by_story.setdefault(criterion["storyId"], []).append(
            criterion["text"]
        )

    task_display_names_by_story: dict[str, list[str]] = {}
    for task in model["tasks"]:
        work_type_id = task["workTypeId"]
        catalog_row = catalog_rows.get(work_type_id)
        if not isinstance(catalog_row, dict):
            raise ValueError(f"template work type is missing: {work_type_id}")
        if catalog_row.get("rowSemanticSha256") != task["rowSemanticSha256"]:
            raise ValueError(f"task standard row hash changed: {work_type_id}")
        for story_id in task_covered_story_ids(model,task):
            task_display_names_by_story.setdefault(story_id, []).append(
                f"• [{catalog_row['工作类型名称']}/{task['workMode']}/{task['complexity']}] "
                f"{display_names[task['taskId']]}"
            )

    story_notes, _story_note_inventory = model_story_note_projection(model)

    story_rows: list[dict[str, object]] = []
    for story in model["stories"]:
        feature = features[story["featureId"]]
        epic = epics[feature["epicId"]]
        story_name = str(safe_text(story["name"]))
        shared = [{'story':stories[task['storyId']]['name'],'task':display_names[task['taskId']]}
            for task in model['tasks'] if task['storyId']!=story['storyId'] and story['storyId'] in task_covered_story_ids(model,task)]
        notes = [story_notes.get(story['storyId'], '')]
        notes += ['共享交付：'+ref['task']+'；人天计入「'+ref['story']+'」，本故事不重复计量。' for ref in shared]
        story_rows.append(
            {
                "需求": safe_text(epic["name"]),
                "子需求": safe_text(feature["name"]),
                "故事": story_name,
                "UAT适用": "是" if story["uatApplicable"] else "否",
                "验收条件": "\n".join(
                    f"• {name}"
                    for name in acceptance_names_by_story.get(story["storyId"], [])
                ),
                "备注": "\n".join(note for note in notes if note),
                "_sharedTaskReferences": shared,
                "任务列表": "\n".join(
                    task_display_names_by_story.get(story["storyId"], [])
                ),
            }
        )

    task_rows: list[dict[str, object]] = []
    sit_by_task = {
        item["taskId"]: item for item in derive_sit_assignments(model, task_catalog)
    }
    for task in model["tasks"]:
        story = stories[task["storyId"]]
        story_name = str(safe_text(story["name"]))
        work_type_id = task["workTypeId"]
        catalog_row = catalog_rows.get(work_type_id)
        if not isinstance(catalog_row, dict):
            raise ValueError(f"template work type is missing: {work_type_id}")
        sit = sit_by_task[task["taskId"]]
        notes = [f"实际计量范围：{task['actualMeasurementScope']}"]
        task_rows.append(
            {
                "所属故事": story_name,
                "任务名称": display_names[task["taskId"]],
                "工作类型ID": work_type_id,
                "工作类型名称": catalog_row["工作类型名称"],
                "工作方式": task["workMode"],
                "复杂度": task["complexity"],
                "SIT支持分类": sit["sitSupportClass"],
                "集成类型": {"NONE": "", "INTERNAL": "内部集成", "EXTERNAL": "外部集成"}[sit["sitSupportClass"]],
                "SIT计费点ID": sit["sitSupportPointId"] or "",
                "备注": "\n".join(notes),
            }
        )

    return {"SOWStoryTable": story_rows, "TaskTable": task_rows}


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


def task_standard_name_map(workbook: Any) -> dict[str, str]:
    index = table_index(workbook)
    if "TaskStandardTable" not in index:
        raise ValueError("template Task Standard catalog is missing")
    worksheet, table = index["TaskStandardTable"]
    min_col, min_row, max_col, max_row = range_boundaries(table.ref)
    headers = [
        worksheet.cell(min_row, column).value
        for column in range(min_col, max_col + 1)
    ]
    if "工作类型ID" not in headers or "工作类型名称" not in headers:
        raise ValueError("template work type name projection columns are missing")
    id_column = min_col + headers.index("工作类型ID")
    name_column = min_col + headers.index("工作类型名称")
    result: dict[str, str] = {}
    used_names: set[str] = set()
    for row in range(min_row + 1, max_row + 1):
        unit_id = worksheet.cell(row, id_column).value
        name = worksheet.cell(row, name_column).value
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise ValueError("template work type ID is blank")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"template work type name is blank: {unit_id}")
        if unit_id in result:
            raise ValueError(f"template work type ID is duplicated: {unit_id}")
        if name in used_names:
            raise ValueError(f"template work type name is duplicated: {name}")
        result[unit_id] = name
        used_names.add(name)
    return result


def table_records(workbook: Any, table_name: str) -> list[dict[str, object]]:
    worksheet, table = table_index(workbook)[table_name]
    min_col, min_row, max_col, max_row = range_boundaries(table.ref)
    headers = [
        worksheet.cell(min_row, column).value
        for column in range(min_col, max_col + 1)
    ]
    if not all(isinstance(header, str) and header for header in headers):
        raise ValueError(f"invalid table header: {table_name}")
    return [
        {
            str(header): worksheet.cell(row, min_col + offset).value
            for offset, header in enumerate(headers)
        }
        for row in range(min_row + 1, max_row + 1)
    ]


def require_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"calculated workbook value is not numeric: {label}")
    if not math.isfinite(float(value)):
        raise ValueError(f"calculated workbook value is not finite: {label}")
    return float(value)


def formula_errors(workbook: Any) -> tuple[str, ...]:
    errors: list[str] = []
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows():
            for cell in row:
                value = cell.value
                if cell.data_type == "e" or (
                    isinstance(value, str)
                    and value.startswith(FORMULA_ERROR_PREFIXES)
                ):
                    errors.append(f"{worksheet.title}!{cell.coordinate}:{value}")
    return tuple(errors)



def scan_workbook_integrity(path: Path) -> dict[str, object]:
    """Read every ZIP member and both workbook views; never calculate formulas."""
    import zipfile
    from openpyxl.formula.tokenizer import Tokenizer
    from contracts import canonical_json_bytes, sha256_bytes
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None or len(archive.namelist()) != len(set(archive.namelist())):
                raise ValueError('corrupt or duplicate ZIP member')
            for name in archive.namelist():
                if name.endswith('.xml'): ET.fromstring(archive.read(name))
        formulas = []
        for cached in (False, True):
            book = openpyxl.load_workbook(path, data_only=cached)
            try:
                errors = formula_errors(book)
                if errors: raise ValueError('workbook formula errors: '+str(errors))
                if not cached:
                    for sheet in book:
                        for row in sheet:
                            for cell in row:
                                if cell.data_type != 'f': continue
                                expression = formula_text(cell.value)
                                for token in Tokenizer(expression).items:
                                    if token.type == 'OPERAND' and token.subtype == 'ERROR':
                                        raise ValueError('formula contains error reference')
                                    if token.type == 'OPERAND' and token.subtype == 'RANGE' and '!' in token.value:
                                        sheet_ref = token.value.rsplit('!', 1)[0].strip("'").replace("''", "'")
                                        if sheet_ref not in book.sheetnames:
                                            raise ValueError('unresolved cross-sheet reference')
                                formulas.append([sheet.title, cell.coordinate, comparable_formula(expression)])
            finally: book.close()
        return {'formulaSha256':sha256_bytes(canonical_json_bytes(formulas)), 'formulaCount':len(formulas)}
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as error:
        raise ValueError('workbook ZIP integrity failed') from error


def visible_identity_rows(model):
    """One explicit owner row per ID; reference rows do not assert ownership."""
    from contracts import canonical_json_bytes
    fields = {'inputItems':'inputItemId','epics':'epicId','features':'featureId',
        'designItems':'designItemId','integrations':'integrationId','nfrs':'nfrId',
        'policyInstances':'policyInstanceId','stories':'storyId','acceptanceCriteria':'acceptanceCriterionId',
        'tasks':'taskId','dependencies':'dependencyId','scopeAnnotations':'annotationId',
        'deliveryAnnotations':'annotationId','estimationAnnotations':'annotationId','decisions':'decisionId'}
    rows = []
    seen = set()
    for collection, field in fields.items():
        for item in model.get(collection, []):
            identity = item[field]
            if identity in seen: raise ValueError('ambiguous visible identity owner')
            seen.add(identity)
            rows.append([identity, collection, item.get('name', item.get('text', identity))])
            for ref in item.get('sourceRefs', []):
                rows.append([identity, 'SourceRef', canonical_json_bytes(ref).decode('utf-8').strip()])
    return rows


def write_visible_identity(workbook, model):
    from openpyxl.styles import Alignment, Font, PatternFill
    sheet = workbook['03-工作量汇总']
    # C is outside the template's two-column summary Table; retain A/B authority.
    sheet.column_dimensions['C'].width = 100
    start = sheet.max_row + 3
    for offset, values in enumerate([['实体 ID', '类型 / 来源', '名称 / 公开来源引用'], *visible_identity_rows(model)]):
        row = start + offset
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row, column, safe_text(value)); cell.data_type = 's'
            cell.alignment = Alignment(wrap_text=True, vertical='top')
            cell.font = Font(name='Arial', size=10, bold=offset == 0)
            cell.fill = PatternFill('solid', fgColor='E8EEF6' if offset == 0 else 'FFFFFF')
        sheet.row_dimensions[row].height = min(MAX_EXCEL_ROW_HEIGHT, max(32, max(
            wrapped_line_count(str(v), effective_cell_width(sheet, sheet.cell(row,c)))
            for c,v in enumerate(values,1))*WRAPPED_LINE_HEIGHT+WRAPPED_ROW_PADDING))
    sheet.print_area = f'A1:{get_column_letter(sheet.max_column)}{sheet.max_row}'


def verify_formula_cache_results(
    formula_workbook: Any,
    cached_workbook: Any,
    reference_formula_workbook: Any,
    reference_cached_workbook: Any,
) -> None:
    """Compare every formula cache with a fresh Office calculation.

    Python deliberately does not reimplement the workbook's estimation rules.
    Instead, the authoritative template is projected and independently
    recalculated by the same supported Office engine; every resulting formula
    cache must then match that reference calculation.
    """
    for sheet_name in FORMAL_SHEETS:
        formula_sheet = formula_workbook[sheet_name]
        cached_sheet = cached_workbook[sheet_name]
        reference_formula_sheet = reference_formula_workbook[sheet_name]
        reference_cached_sheet = reference_cached_workbook[sheet_name]
        coordinates = {
            cell.coordinate
            for row in formula_sheet.iter_rows()
            for cell in row
            if cell.data_type == "f" and isinstance(cell.value, (str, ArrayFormula))
        }
        reference_coordinates = {
            cell.coordinate
            for row in reference_formula_sheet.iter_rows()
            for cell in row
            if cell.data_type == "f" and isinstance(cell.value, (str, ArrayFormula))
        }
        if coordinates != reference_coordinates:
            raise ValueError(f"formula inventory mismatch: {sheet_name}")
        for coordinate in sorted(coordinates):
            actual_formula = formula_sheet[coordinate].value
            reference_formula = reference_formula_sheet[coordinate].value
            if comparable_formula(actual_formula) != comparable_formula(
                reference_formula
            ):
                raise ValueError(
                    f"formula mismatch against reference: {sheet_name}!{coordinate}"
                )
            actual = cached_sheet[coordinate].value
            expected = reference_cached_sheet[coordinate].value
            if (
                isinstance(actual, (int, float))
                and not isinstance(actual, bool)
                and isinstance(expected, (int, float))
                and not isinstance(expected, bool)
            ):
                matches = math.isclose(float(actual), float(expected), abs_tol=1e-9)
            else:
                matches = actual == expected
            if not matches:
                raise ValueError(
                    f"cached formula result mismatch: {sheet_name}!{coordinate}"
                )


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
    headers = [
        worksheet.cell(min_row, column).value
        for column in range(min_col, max_col + 1)
    ]
    if not all(isinstance(header, str) for header in headers):
        raise ValueError(f"invalid table header: {table_name}")
    validate_table_headers(table_name, headers)
    expected_headers = headers
    metadata_headers = [column.name for column in table.tableColumns]
    if metadata_headers != expected_headers:
        raise ValueError(
            f"template table metadata mismatch in {table_name}: "
            f"expected {expected_headers}, got {metadata_headers}"
        )

    prototypes = [
        worksheet.cell(prototype_row, column)
        for column in range(min_col, max_col + 1)
    ]
    formulas = {
        offset: (normalize_table_formula(cell.value), isinstance(cell.value, ArrayFormula))
        for offset, cell in enumerate(prototypes)
        if cell.data_type == "f" and isinstance(cell.value, (str, ArrayFormula))
    }
    actual_formula_headers = {headers[offset] for offset in formulas}
    validate_formula_headers(table_name, actual_formula_headers)
    for column_offset, column in enumerate(table.tableColumns):
        specification = formulas.get(column_offset)
        if specification is None:
            column.calculatedColumnFormula = None
            continue
        formula, is_array = specification
        column.calculatedColumnFormula = TableFormula(
            array=True if is_array else None,
            attr_text=formula.removeprefix("="),
        )

    physical_rows = rows if rows else [{}]
    clear_through = max(old_max_row, min_row + len(physical_rows), prototype_row)
    for row in range(prototype_row, clear_through + 1):
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
                if table_name == 'SOWStoryTable': translated = shared_story_formula(header,translated,payload)
                cell.value = (
                    ArrayFormula(ref=cell.coordinate, text=translated)
                    if is_array
                    else translated
                )
            else:
                value = None if not rows else projected_input_value(table_name, header, payload)
                cell.value = value
                if isinstance(value, str):
                    cell.data_type = "s"
        wrapped_lines = max(
            (
                wrapped_line_count(visible_value, effective_cell_width(worksheet, cell))
                for column_offset, cell in enumerate(
                    worksheet[row][min_col - 1 : max_col]
                )
                for visible_value in [
                    payload.get(headers[column_offset])
                    if column_offset in formulas
                    else cell.value
                ]
                if cell.alignment.wrap_text and isinstance(visible_value, str)
            ),
            default=1,
        )
        worksheet.row_dimensions[row].height = min(
            MAX_EXCEL_ROW_HEIGHT,
            max(
                prototype_height or 15,
                wrapped_lines * WRAPPED_LINE_HEIGHT + WRAPPED_ROW_PADDING,
            ),
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
    table.ref = (
        f"{get_column_letter(min_col)}{min_row}:"
        f"{get_column_letter(max_col)}{new_max_row}"
    )
    if table.autoFilter is not None:
        table.autoFilter.ref = table.ref


def projection_contract(workbook: Any) -> dict[str, dict[str, object]]:
    contract: dict[str, dict[str, object]] = {}
    for table_name, (worksheet, table) in table_index(workbook).items():
        if table_name not in TABLES:
            continue
        min_col, min_row, max_col, _ = range_boundaries(table.ref)
        headers = [
            worksheet.cell(min_row, column).value
            for column in range(min_col, max_col + 1)
        ]
        if not all(isinstance(header, str) for header in headers):
            raise ValueError(f"invalid table header: {table_name}")
        validate_table_headers(table_name, headers)
        formulas: dict[str, tuple[str, str, bool]] = {}
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
        validate_formula_headers(table_name, set(formulas))
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


def _visible_color(color: Any) -> tuple[object, ...] | None:
    if color is None:
        return None
    value = getattr(color, color.type, None)
    if color.type == "rgb" and isinstance(value, str):
        value = value[-6:].upper()
    return (
        color.type,
        value,
        round(float(color.tint or 0), 8),
    )


def _visible_side(side: Any) -> tuple[object, ...] | None:
    if side is None or (side.style is None and side.color is None):
        return None
    return (side.style, _visible_color(side.color))


def visible_style_signature(cell: Any) -> tuple[object, ...]:
    """Compare rendered appearance while tolerating Office font substitution."""
    font = cell.font
    fill = cell.fill
    border = cell.border
    alignment = cell.alignment
    return (
        (
            bool(font.bold),
            bool(font.italic),
            float(font.sz) if font.sz is not None else None,
            font.underline,
            bool(font.strike),
            _visible_color(font.color),
        ),
        (
            fill.patternType,
            _visible_color(fill.fgColor),
            (
                _visible_color(fill.bgColor)
                if fill.patternType not in {None, "solid"}
                else None
            ),
        ),
        tuple(
            _visible_side(getattr(border, name))
            for name in ("left", "right", "top", "bottom", "diagonal")
        ),
        (
            alignment.horizontal or "general",
            alignment.vertical or "bottom",
            int(alignment.textRotation or 0),
            bool(alignment.wrapText),
            bool(alignment.shrinkToFit),
            float(alignment.indent or 0),
        ),
        cell.number_format,
        (bool(cell.protection.locked), bool(cell.protection.hidden)),
    )


def verify_visible_layout(workbook: Any, expected_workbook: Any) -> None:
    for sheet_name in FORMAL_SHEETS:
        worksheet = workbook[sheet_name]
        expected_sheet = expected_workbook[sheet_name]
        max_row = max(worksheet.max_row, expected_sheet.max_row)
        max_column = max(worksheet.max_column, expected_sheet.max_column)
        for row in range(1, max_row + 1):
            actual_height = (
                worksheet.row_dimensions[row].height
                or worksheet.sheet_format.defaultRowHeight
            )
            expected_height = (
                expected_sheet.row_dimensions[row].height
                or expected_sheet.sheet_format.defaultRowHeight
            )
            if actual_height != expected_height:
                raise ValueError(f"row height mismatch: {sheet_name}!{row}")
            for column in range(1, max_column + 1):
                actual = worksheet.cell(row, column)
                expected = expected_sheet.cell(row, column)
                if visible_style_signature(actual) != visible_style_signature(expected):
                    raise ValueError(
                        f"visible style mismatch: {sheet_name}!{actual.coordinate}"
                    )


def verify_print_layout(workbook: Any) -> None:
    """Reject pagination that makes long sheets unreadable when printed."""
    for sheet_name in FORMAL_SHEETS:
        page_setup = workbook[sheet_name].page_setup
        if page_setup.fitToWidth != 1 or page_setup.fitToHeight != 0:
            raise ValueError(f"print layout mismatch: {sheet_name}")


def verify_compact_summary(workbook: Any, template_workbook: Any) -> None:
    def content(book):
        return {cell.coordinate: (cell.data_type, comparable_formula(cell.value) if cell.data_type == 'f' else cell.value)
                for row in book['03-工作量汇总'] for cell in row if cell.value is not None}
    if content(workbook) != content(template_workbook):
        raise ValueError('compact summary content differs from template')


def verify_workbook(
    path: Path,
    expected: dict[str, list[dict[str, object]]],
    contract: dict[str, dict[str, object]],
    *,
    require_recalculation: bool = True,
    verify_styles: bool = True,
) -> None:
    workbook = openpyxl.load_workbook(path, data_only=False, read_only=False)
    try:
        if tuple(workbook.sheetnames) != FORMAL_SHEETS:
            raise ValueError("formal workbook sheet contract changed")
        index = table_index(workbook)
        if require_recalculation and workbook.calculation.calcMode != "auto":
            raise ValueError("workbook recalculation is not enabled")
        for table_name, rows in expected.items():
            worksheet, table = index[table_name]
            min_col, min_row, max_col, max_row = range_boundaries(table.ref)
            if max_row - min_row != max(1, len(rows)):
                raise ValueError(f"table row count mismatch: {table_name}")
            headers = [
                worksheet.cell(min_row, column).value
                for column in range(min_col, max_col + 1)
            ]
            validate_table_headers(table_name, headers)
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
                    if verify_styles and style_signature(cell) != styles[header]:
                        raise ValueError(
                            f"prototype style changed in {table_name}.{header}"
                        )
                    if header in formulas:
                        origin, prototype, is_array = formulas[header]
                        expected_formula = Translator(
                            prototype,
                            origin=origin,
                        ).translate_formula(cell.coordinate)
                        if table_name == 'SOWStoryTable':
                            expected_formula = shared_story_formula(header,expected_formula,payload)
                        actual_formula = (
                            formula_text(cell.value)
                            if isinstance(cell.value, (str, ArrayFormula))
                            else None
                        )
                        formula_kind_matches = (
                            isinstance(cell.value, ArrayFormula)
                            and cell.value.ref
                            in {cell.coordinate, f"{cell.coordinate}:{cell.coordinate}"}
                            if is_array
                            else isinstance(cell.value, str)
                        )
                        if (
                            comparable_formula(actual_formula or "")
                            != comparable_formula(expected_formula)
                            or cell.data_type != "f"
                            or not formula_kind_matches
                        ):
                            raise ValueError(
                                f"formula mismatch in {table_name}.{header}"
                            )
                    else:
                        expected_value = (
                            None if not rows else projected_input_value(table_name, header, payload)
                        )
                        if expected_value == "":
                            expected_value = None
                        if cell.value != expected_value:
                            raise ValueError(
                                f"projected value mismatch in {table_name}.{header}"
                            )
                        if isinstance(expected_value, str) and cell.data_type != "s":
                            raise ValueError(
                                f"projected text type mismatch in {table_name}.{header}"
                            )
            calculated_headers = {
                column.name
                for column in table.tableColumns
                if column.calculatedColumnFormula is not None
                and column.calculatedColumnFormula.text
            }
            if calculated_headers != set(formulas):
                raise ValueError(f"calculated column mismatch in {table_name}")
            formula_columns = {
                column.name: column.calculatedColumnFormula
                for column in table.tableColumns
                if column.calculatedColumnFormula is not None
            }
            for header, (_, _, is_array) in formulas.items():
                metadata_formula = formula_columns[header]
                if (
                    comparable_formula("=" + str(metadata_formula.text))
                    != comparable_formula(formulas[header][1])
                ):
                    raise ValueError(
                        f"calculated column formula mismatch in {table_name}.{header}"
                    )
                if (metadata_formula.array is True) != is_array:
                    raise ValueError(
                        f"calculated column array mismatch in {table_name}.{header}"
                    )
            if table.autoFilter is not None and table.autoFilter.ref != table.ref:
                raise ValueError(f"autoFilter range mismatch: {table_name}")
        for sheet_name in PROTECTED_SHEETS:
            if not workbook[sheet_name].protection.sheet:
                raise ValueError(f"worksheet protection is missing: {sheet_name}")
    finally:
        workbook.close()


def verify_static_authority(workbook: Any, template_workbook: Any) -> None:
    """Verify immutable catalog, parameter and summary inputs/formulas."""
    workbook_index = table_index(workbook)
    template_index = table_index(template_workbook)
    for table_name in sorted(FORMAL_TABLES - set(TABLES)):
        worksheet, table = workbook_index[table_name]
        template_sheet, template_table = template_index[table_name]
        if table.ref != template_table.ref:
            raise ValueError(f"static table range mismatch: {table_name}")
        bounds = range_boundaries(table.ref)
        template_bounds = range_boundaries(template_table.ref)
        if bounds != template_bounds:
            raise ValueError(f"static table bounds mismatch: {table_name}")
        if [column.name for column in table.tableColumns] != [
            column.name for column in template_table.tableColumns
        ]:
            raise ValueError(f"static table metadata mismatch: {table_name}")
        min_col, min_row, max_col, max_row = bounds
        for row in range(min_row, max_row + 1):
            for column in range(min_col, max_col + 1):
                actual = worksheet.cell(row, column)
                expected = template_sheet.cell(row, column)
                if expected.data_type == "f" and isinstance(
                    expected.value, (str, ArrayFormula)
                ):
                    if actual.data_type != "f" or not isinstance(
                        actual.value, (str, ArrayFormula)
                    ):
                        raise ValueError(f"static formula is missing: {table_name}")
                    if comparable_formula(actual.value) != comparable_formula(
                        expected.value
                    ):
                        raise ValueError(f"static formula mismatch: {table_name}")
                elif isinstance(expected.value, bool) and (
                    actual.data_type == "f"
                    and isinstance(actual.value, str)
                    and actual.value.upper()
                    == ("=TRUE()" if expected.value else "=FALSE()")
                ):
                    continue
                elif actual.value != expected.value:
                    raise ValueError(f"static value mismatch: {table_name}")


def verify_worksheet_authority(workbook: Any, template_workbook: Any) -> None:
    """Verify worksheet controls that remain authoritative after Office roundtrip."""
    for sheet_name in FORMAL_SHEETS:
        worksheet = workbook[sheet_name]
        template_sheet = template_workbook[sheet_name]
        if ET.tostring(worksheet.data_validations.to_tree()) != ET.tostring(
            template_sheet.data_validations.to_tree()
        ):
            raise ValueError(f"data validation metadata mismatch: {sheet_name}")
        if ET.tostring(worksheet.protection.to_tree()) != ET.tostring(
            template_sheet.protection.to_tree()
        ):
            raise ValueError(f"worksheet protection metadata mismatch: {sheet_name}")


def audit_calculated_workbook(
    path: Path,
    template_path: Path,
    model: dict[str, Any],
    engine: Any,
    *, expected_layout_path: Path | None = None, reference_path: Path | None = None,
) -> WorkbookAudit:
    """Verify projected inputs and reread every calculation authority/result.

    The office engine, rather than Python, remains responsible for evaluating
    formulas. This function only proves that the verified output still contains
    the approved projection and that all authoritative cached results are usable.
    """
    stack = ExitStack()
    try:
        if (expected_layout_path is None) != (reference_path is None):
            raise ValueError('audit requires both externally prepared reference paths')
        if expected_layout_path is None:
            temporary_root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="ai-sow-audit-")))
            expected_layout_path = temporary_root / "expected-layout.xlsx"
            reference_path = temporary_root / "reference.xlsx"
            write_workbook(template_path, model, expected_layout_path)
            recalculate_workbook(expected_layout_path, reference_path, engine)
        scan_workbook_integrity(path)
        scan_workbook_integrity(reference_path)
        expected_layout_workbook = openpyxl.load_workbook(
            expected_layout_path, data_only=False, read_only=False
        )
        reference_formula_workbook = openpyxl.load_workbook(
            reference_path, data_only=False, read_only=False
        )
        reference_cached_workbook = openpyxl.load_workbook(
            reference_path, data_only=True, read_only=False
        )
        template_workbook = openpyxl.load_workbook(
            template_path, data_only=False, read_only=False
        )
        formula_workbook = openpyxl.load_workbook(
            path, data_only=False, read_only=False
        )
        cached_workbook = openpyxl.load_workbook(
            path, data_only=True, read_only=False
        )
        for workbook in (
            expected_layout_workbook,
            reference_formula_workbook,
            reference_cached_workbook,
            template_workbook,
            formula_workbook,
            cached_workbook,
        ):
            stack.callback(workbook.close)
        for workbook in (formula_workbook, cached_workbook):
            if tuple(workbook.sheetnames) != FORMAL_SHEETS:
                raise ValueError("formal workbook sheet contract changed")
            if set(table_index(workbook)) != FORMAL_TABLES:
                raise ValueError("formal workbook table contract changed")

        expected = build_rows(model, load_task_standard_catalog(template_path))
        template_contract = projection_contract(template_workbook)
        if template_contract['TaskTable']['headers'] == COMPACT_TASK_HEADERS:
            verify_compact_summary(formula_workbook, template_workbook)
        verify_workbook(
            path,
            expected,
            template_contract,
            require_recalculation=False,
            verify_styles=False,
        )
        verify_static_authority(formula_workbook, template_workbook)
        verify_worksheet_authority(formula_workbook, template_workbook)
        verify_visible_layout(formula_workbook, expected_layout_workbook)
        verify_print_layout(formula_workbook)
        formula_index = table_index(formula_workbook)
        cached_index = table_index(cached_workbook)
        cached_errors = formula_errors(cached_workbook)
        if cached_errors:
            raise ValueError(
                "calculated workbook contains formula errors: "
                + ", ".join(cached_errors)
            )
        reference_errors = formula_errors(reference_cached_workbook)
        if reference_errors:
            raise ValueError(
                "reference calculation contains formula errors: "
                + ", ".join(reference_errors)
            )
        verify_formula_cache_results(
            formula_workbook,
            cached_workbook,
            reference_formula_workbook,
            reference_cached_workbook,
        )

        for table_name in TABLES:
            formula_sheet, formula_table = formula_index[table_name]
            cached_sheet, cached_table = cached_index[table_name]
            formula_bounds = range_boundaries(formula_table.ref)
            cached_bounds = range_boundaries(cached_table.ref)
            if formula_bounds != cached_bounds:
                raise ValueError(f"calculated table range changed: {table_name}")
            min_col, min_row, max_col, max_row = formula_bounds
            headers = [
                formula_sheet.cell(min_row, column).value
                for column in range(min_col, max_col + 1)
            ]
            validate_table_headers(table_name, headers)
            if max_row - min_row != len(expected[table_name]):
                raise ValueError(f"calculated table row count mismatch: {table_name}")
            for row_offset, payload in enumerate(expected[table_name], start=1):
                for column_offset, header in enumerate(headers):
                    formula_cell = formula_sheet.cell(
                        min_row + row_offset, min_col + column_offset
                    )
                    cached_cell = cached_sheet.cell(
                        min_row + row_offset, min_col + column_offset
                    )
                    if header in template_contract[table_name]["formulas"]:
                        if formula_cell.data_type != "f" or not isinstance(
                            formula_cell.value, (str, ArrayFormula)
                        ):
                            raise ValueError(
                                f"calculated formula is missing: {table_name}.{header}"
                            )
                        if table_name == "TaskTable" and header in {"工作类型ID", "工作类型名称"}:
                            if cached_cell.value != payload[header]:
                                raise ValueError(f"calculated catalog selection changed: {header}")
                    else:
                        expected_value = projected_input_value(table_name, str(header), payload)
                        if expected_value == "":
                            expected_value = None
                        if formula_cell.value != expected_value:
                            raise ValueError(
                                f"calculated projection changed: {table_name}.{header}"
                            )
                        if cached_cell.value != expected_value:
                            raise ValueError(
                                f"cached projection changed: {table_name}.{header}"
                            )

        story_records = table_records(cached_workbook, "SOWStoryTable")
        task_records = table_records(cached_workbook, "TaskTable")
        task_names_by_story: dict[str, list[str]] = {}
        task_days: list[float] = []
        for record in task_records:
            story_path = record["所属故事"]
            task_name = record["任务名称"]
            if not isinstance(story_path, str) or not isinstance(task_name, str):
                raise ValueError("calculated task projection is incomplete")
            task_names_by_story.setdefault(story_path, []).append(task_name)
            for header in ("M档标准人天", "复杂度系数", "任务人天", "SIT支持人天"):
                value = require_number(record[header], f"TaskTable.{header}")
                if value < 0:
                    raise ValueError(f"calculated task value is negative: {header}")
                if header == "任务人天":
                    task_days.append(value)
            if record["校验结果"] != "通过":
                raise ValueError("calculated task validation did not pass")

        for record in story_records:
            story_name = record["故事"]
            if not isinstance(story_name, str) or not story_name:
                raise ValueError("calculated story name is missing")
            expected_story = next(row for row in expected['SOWStoryTable'] if row['故事']==story_name)
            expected_task_list = expected_story['任务列表']
            if not expected_task_list or record["任务列表"] != expected_task_list:
                raise ValueError("calculated story task list changed")
            require_number(record["故事人天"], "SOWStoryTable.故事人天")
            if record["校验结果"] != "通过":
                raise ValueError("calculated story validation did not pass")

        summary_formula_records = table_records(
            formula_workbook, "ProjectSummaryTable"
        )
        summary_records = table_records(cached_workbook, "ProjectSummaryTable")
        if [*summary_records[0].keys()] != SUMMARY_HEADERS:
            raise ValueError("summary table header contract changed")
        if [record["工作量项"] for record in summary_records] != list(SUMMARY_LABELS):
            raise ValueError("summary row contract changed")
        for record in summary_formula_records:
            if not isinstance(record["人天"], (str, ArrayFormula)):
                raise ValueError("summary formula is missing")
        summary_values = [
            require_number(record["人天"], f"ProjectSummaryTable.{record['工作量项']}")
            for record in summary_records
        ]
        direct_days, sit_days, uat_days, total_days = summary_values
        if not math.isclose(direct_days, sum(task_days), abs_tol=1e-9):
            raise ValueError("summary direct days do not match task results")
        if not math.isclose(total_days, direct_days + sit_days + uat_days, abs_tol=1e-9):
            raise ValueError("summary total days do not match component results")

        catalog_records = table_records(cached_workbook, "TaskStandardTable")
        if not catalog_records or [*catalog_records[0].keys()] != CATALOG_HEADERS:
            raise ValueError("task standard catalog contract changed")
        if len(catalog_records) != 88:
            raise ValueError("task standard catalog must contain 88 rows")
        catalog_ids: set[str] = set()
        applicable_modes = 0
        reusable_modes = 0
        for record in catalog_records:
            unit_id = record["工作类型ID"]
            if not isinstance(unit_id, str) or unit_id in catalog_ids:
                raise ValueError("task standard ID is invalid or duplicated")
            catalog_ids.add(unit_id)
            available_modes = 0
            for prefix in ("新建", "调整", "接入复用"):
                applicable = record[f"{prefix}适用"]
                value = record[f"{prefix}M档人天"]
                if not applicable:
                    if value not in (None, ""):
                        raise ValueError(
                            f"task standard unavailable mode has days: {unit_id}.{prefix}"
                        )
                    continue
                if require_number(value, f"TaskStandardTable.{unit_id}.{prefix}") <= 0:
                    raise ValueError("task standard person-days must be positive")
                available_modes += 1
                applicable_modes += 1
                if prefix == "接入复用":
                    reusable_modes += 1
            if available_modes == 0:
                raise ValueError(f"task standard row has no available work mode: {unit_id}")
        if applicable_modes != 191 or reusable_modes != 26:
            raise ValueError("task standard mode counts changed")

        parameter_records = table_records(cached_workbook, "ProjectParameterTable")
        if [*parameter_records[0].keys()] != PARAMETER_HEADERS:
            raise ValueError("project parameter header contract changed")
        parameter_codes: set[str] = set()
        parameter_statuses: list[tuple[str, str]] = []
        for record in parameter_records:
            code = record["参数代码"]
            status = record["验证状态/说明"]
            if not isinstance(code, str) or not code or code in parameter_codes:
                raise ValueError("project parameter code is invalid or duplicated")
            if not isinstance(status, str) or not status.strip():
                raise ValueError(f"project parameter status is missing: {code}")
            for header in PARAMETER_HEADERS[1:-1]:
                if record[header] in (None, ""):
                    raise ValueError(f"project parameter value is blank: {code}.{header}")
            require_number(record["值"], f"ProjectParameterTable.{code}.值")
            parameter_codes.add(code)
            parameter_statuses.append((code, status))

        return WorkbookAudit(
            trust_state="VERIFIED",
            story_count=len(story_records),
            task_count=len(task_records),
            direct_days=direct_days,
            sit_days=sit_days,
            uat_days=uat_days,
            total_days=total_days,
            parameter_statuses=tuple(parameter_statuses),
            formula_errors=(),
            engine_name=str(engine.name),
            engine_version=str(engine.version),
        )
    finally:
        stack.close()


def write_workbook(
    template_path: Path,
    model: dict[str, Any],
    output_path: Path,
) -> WorkbookAudit:
    workbook = openpyxl.load_workbook(
        template_path,
        data_only=False,
        read_only=False,
    )
    if workbook.calculation is None:
        workbook.calculation = CalcProperties()
    try:
        table_index(workbook)
        rows = build_rows(model, load_task_standard_catalog(template_path))
        contract = projection_contract(workbook)
        clear_orphan_table_formulas(workbook)
        for table_name in TABLES:
            fill_table(workbook, table_name, rows[table_name])
        # The compact SOW is a business document. Its model/source evidence is
        # retained in the package, without appending a technical ledger to Excel.
        if contract['TaskTable']['headers'] != COMPACT_TASK_HEADERS:
            write_visible_identity(workbook, model)
        # A blank fitToHeight is interpreted as one page by LibreOffice when
        # fit-to-page is enabled, which compresses long Task sheets until the
        # text is unreadable. Zero means unlimited vertical pages while the
        # template's one-page-wide layout remains authoritative.
        for worksheet in workbook.worksheets:
            worksheet.page_setup.fitToHeight = 0
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
    verify_workbook(output_path, rows, contract)
    return WorkbookAudit(
        trust_state="CANDIDATE",
        story_count=len(rows["SOWStoryTable"]),
        task_count=len(rows["TaskTable"]),
        direct_days=None,
        sit_days=None,
        uat_days=None,
        total_days=None,
        parameter_statuses=(),
        formula_errors=(),
        engine_name=None,
        engine_version=None,
    )


def dual_reopen(path, projected_path):
    import openpyxl
    report = scan_workbook_integrity(path)
    formula = openpyxl.load_workbook(path, data_only=False)
    cached = openpyxl.load_workbook(path, data_only=True)
    projected = openpyxl.load_workbook(projected_path, data_only=False)
    try:
        count = 0
        for source_sheet in projected:
            actual_sheet = formula[source_sheet.title]
            for row in source_sheet:
                for cell in row:
                    actual = actual_sheet[cell.coordinate]
                    if cell.data_type == 'f':
                        if actual.data_type != 'f' or comparable_formula(actual.value) != comparable_formula(cell.value):
                            raise ValueError('dual reopen formula missing or changed')
        for sheet in formula:
            for row in sheet:
                for cell in row:
                    if cell.data_type != 'f': continue
                    value = cached[sheet.title][cell.coordinate].value
                    if value is None or not isinstance(value, (str, int, float, bool)):
                        raise ValueError('dual reopen required cached value missing or invalid')
                    count += 1
        if count == 0: raise ValueError('dual reopen has no formula inventory')
        return {**report, 'cachedValueCount':count}
    finally:
        formula.close(); cached.close(); projected.close()
