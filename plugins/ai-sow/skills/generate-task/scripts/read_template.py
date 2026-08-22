from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils.cell import range_boundaries


def table_rows(workbook: Any, table_name: str) -> list[dict[str, Any]]:
    for worksheet in workbook.worksheets:
        if table_name not in worksheet.tables:
            continue
        table = worksheet.tables[table_name]
        min_col, min_row, max_col, max_row = range_boundaries(table.ref)
        headers = [worksheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
        return [
            {
                str(header): worksheet.cell(row, column).value
                for header, column in zip(headers, range(min_col, max_col + 1), strict=True)
            }
            for row in range(min_row + 1, max_row + 1)
        ]
    raise ValueError(f"template table is missing: {table_name}")


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


def require_text(row: dict[str, Any], header: str, subject: str) -> str:
    value = row.get(header)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{subject} must define non-empty {header}")
    return value


def require_headers(rows: list[dict[str, Any]], expected: set[str], table_name: str) -> None:
    if not rows:
        raise ValueError(f"template table has no rows: {table_name}")
    actual = set(rows[0])
    if actual != expected:
        raise ValueError(
            f"template table headers are invalid for {table_name}: "
            f"expected {sorted(expected)}, got {sorted(actual)}"
        )


def read_contract(template_path: Path) -> dict[str, Any]:
    workbook = openpyxl.load_workbook(template_path, data_only=False, read_only=False)
    try:
        catalog_rows = table_rows(workbook, "BaseUnitCatalogTable")
        parameter_rows = table_rows(workbook, "ProjectParameterTable")
        require_headers(catalog_rows, CATALOG_HEADERS, "BaseUnitCatalogTable")
        require_headers(parameter_rows, PARAMETER_HEADERS, "ProjectParameterTable")

        base_units: dict[str, dict[str, Any]] = {}
        family_names_by_id: dict[str, str] = {}
        family_ids_by_name: dict[str, str] = {}
        options: list[list[str]] = []
        for index, row in enumerate(catalog_rows, start=1):
            subject = f"base-unit catalog row {index}"
            family_id = require_text(row, "任务族ID", subject)
            family_name = require_text(row, "任务族名称", subject)
            base_unit_id = require_text(row, "基础单元ID", subject)
            base_unit_name = require_text(row, "基础单元名称", subject)
            if base_unit_id in base_units:
                raise ValueError(f"base-unit catalog ID is duplicated: {base_unit_id}")
            if (
                family_id in family_names_by_id
                and family_names_by_id[family_id] != family_name
            ):
                raise ValueError(f"task-family ID maps to multiple names: {family_id}")
            if (
                family_name in family_ids_by_name
                and family_ids_by_name[family_name] != family_id
            ):
                raise ValueError(f"task-family name maps to multiple IDs: {family_name}")
            family_names_by_id[family_id] = family_name
            family_ids_by_name[family_name] = family_id

            allowed_modes: list[str] = []
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
                        f"{subject} {effort_header} must be a positive number or ❌"
                    )
                allowed_modes.append(work_mode)
                options.append([base_unit_id, work_mode])
            if not allowed_modes:
                raise ValueError(
                    f"base-unit catalog must configure at least one work mode: {base_unit_id}"
                )
            standards = {
                level: require_text(row, f"{level}标准", subject)
                for level in COMPLEXITIES
            }
            base_units[base_unit_id] = {
                "taskFamilyId": family_id,
                "taskFamily": family_name,
                "name": base_unit_name,
                "countRule": require_text(row, "计数口径", subject),
                "includes": require_text(row, "包含内容", subject),
                "excludes": require_text(row, "不包含内容", subject),
                "allowedWorkModes": allowed_modes,
                "complexityStandards": standards,
                "splitRule": require_text(row, "X/拆分条件", subject),
            }

        if len(base_units) != 37:
            raise ValueError(
                f"template must define exactly 37 base units, got {len(base_units)}"
            )
        if len(family_names_by_id) != 13:
            raise ValueError(
                f"template must define exactly 13 task families, got {len(family_names_by_id)}"
            )

        complexity_factors: dict[str, float] = {}
        parameter_codes: set[str] = set()
        for row in parameter_rows:
            code = row.get("参数代码")
            if not isinstance(code, str) or not code.strip():
                raise ValueError("project parameter must define a non-empty 参数代码")
            if code in parameter_codes:
                raise ValueError(f"project parameter is duplicated: {code}")
            parameter_codes.add(code)
            if not code.startswith("K_COMPLEXITY_"):
                continue
            level = code.removeprefix("K_COMPLEXITY_")
            factor = row.get("值")
            if level not in COMPLEXITIES:
                raise ValueError(f"complexity parameter is invalid: {code}")
            if level in complexity_factors:
                raise ValueError(f"complexity parameter is duplicated: {level}")
            if (
                isinstance(factor, bool)
                or not isinstance(factor, (int, float))
                or factor <= 0
            ):
                raise ValueError(f"complexity factor must be positive: {level}")
            status = row.get("验证状态/说明")
            if status not in CALIBRATED_PARAMETER_STATUSES:
                raise ValueError(f"complexity factor is not calibrated: {level}")
            complexity_factors[level] = float(factor)
        if set(complexity_factors) != set(COMPLEXITIES):
            raise ValueError(
                "ProjectParameterTable must define K_COMPLEXITY_S, "
                "K_COMPLEXITY_M and K_COMPLEXITY_L"
            )
        return {
            "baseUnits": base_units,
            "taskOptions": options,
            "complexities": list(COMPLEXITIES),
            "complexityFactors": complexity_factors,
        }
    finally:
        workbook.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read task choices from the project SOW template")
    parser.add_argument("--project-root", required=True, type=Path)
    root = parser.parse_args().project_root.resolve()
    try:
        print(json.dumps(read_contract(root / ".ai-sow/templates/sow-template.xlsx"), ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({"outcome": "BLOCKED", "summary": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
