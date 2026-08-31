from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest
from openpyxl.utils import range_boundaries

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/workbook.py"
SPEC = importlib.util.spec_from_file_location("generate_sow_workbook", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_user_text_that_looks_like_formula_is_written_as_text() -> None:
    assert MODULE.safe_text("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert MODULE.safe_text("+1") == "'+1"
    assert MODULE.safe_text("-1") == "'-1"
    assert MODULE.safe_text("@name") == "'@name"
    assert MODULE.safe_text("普通文本") == "普通文本"


def test_projection_labels_are_chinese_and_machine_values_are_not_translated() -> None:
    assert MODULE.topic_label("SYSTEM_CONTEXT") == "系统边界与参与方"
    assert MODULE.topic_label("UNKNOWN_MACHINE_TOKEN") == "UNKNOWN_MACHINE_TOKEN"


def test_projection_rejects_blank_or_ambiguous_display_names() -> None:
    with pytest.raises(ValueError, match="display name is blank"):
        MODULE.require_unique_names([{"name": ""}], "Story")
    with pytest.raises(ValueError, match="display name is duplicated"):
        MODULE.require_unique_names(
            [{"name": "重复名称"}, {"name": "重复名称"}],
            "Feature",
        )


def test_feature_rationale_replaces_overlapping_ids_once_with_names() -> None:
    feature = {
        "source": {
            "rationale": (
                "decision-api + decision-api-auth + decision-api-v2 + "
                "xdecision-api + decision-apiX"
            ),
            "designDecisionIds": ["decision-api", "decision-api-auth"],
        }
    }
    assert MODULE.feature_rationale(
        feature,
        {
            "decision-api": "短决策（含 decision-api-auth 字样）",
            "decision-api-auth": "长决策",
        },
    ) == (
        "短决策（含 decision-api-auth 字样） + 长决策 + decision-api-v2 + "
        "xdecision-api + decision-apiX"
    )
    with pytest.raises(ValueError, match="after Excel projection"):
        MODULE.require_unique_names(
            [{"name": "Portal"}, {"name": "portal"}],
            "Story",
        )
    with pytest.raises(ValueError, match="after Excel projection"):
        MODULE.require_unique_names(
            [{"name": "=名称"}, {"name": "'=名称"}],
            "Task",
        )


def test_generated_workbook_preserves_formula_like_user_content_as_text(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures/project/.ai-sow"

    def read(relative: str) -> dict[str, object]:
        return json.loads((fixture / relative).read_text(encoding="utf-8"))

    business = read("data/analyze-requirement/requirements.json")
    technical = read("data/generate-design/requirements.json")
    business["epics"][0]["name"] = "=FORMULA_LIKE_NAME"  # type: ignore[index]
    custom_template = tmp_path / "custom-template.xlsx"
    template_workbook = openpyxl.load_workbook(
        fixture / "templates/sow-template.xlsx",
        data_only=False,
        read_only=False,
    )
    try:
        template_workbook["03-SOW主表"].freeze_panes = "C6"
        template_workbook["07-假设清单"].protection.sheet = True
        template_workbook.save(custom_template)
    finally:
        template_workbook.close()
    data = {
        "requirements": {
            "epics": [*business["epics"], *technical["epics"]],  # type: ignore[index]
            "features": [*business["features"], *technical["features"]],  # type: ignore[index]
        },
        "asis": read("data/analyze-as-is/asis.json"),
        "design": read("data/generate-design/design.json"),
        "technicalRequirements": technical,
        "delivery": read("data/generate-story/delivery.json"),
        "estimate": read("data/generate-task/estimate.json"),
    }
    output = tmp_path / "safe-text.xlsx"
    MODULE.write_workbook(
        custom_template,
        data,
        output,
        {name: "0" * 64 for name in ("sourceRequirements", "asis", "design", "derivedRequirements", "delivery", "estimate")},
    )

    workbook = openpyxl.load_workbook(output, data_only=False, read_only=False)
    try:
        assert workbook["03-SOW主表"].freeze_panes == "C6"
        assert workbook["07-假设清单"].protection.sheet is True
        worksheet = workbook["01-需求"]
        table = worksheet.tables["EpicTable"]
        min_col, min_row, max_col, _ = range_boundaries(table.ref)
        headers = [worksheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
        cell = worksheet.cell(min_row + 1, min_col + headers.index("需求名称"))
        assert cell.value == "'=FORMULA_LIKE_NAME"
        assert cell.data_type == "s"
    finally:
        workbook.close()


def test_generated_workbook_expands_wrapped_rows_for_visible_long_text(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures/project/.ai-sow"

    def read(relative: str) -> dict[str, object]:
        return json.loads((fixture / relative).read_text(encoding="utf-8"))

    business = read("data/analyze-requirement/requirements.json")
    technical = read("data/generate-design/requirements.json")
    delivery = read("data/generate-story/delivery.json")
    estimate = read("data/generate-task/estimate.json")
    long_text = "这是一段用于验证最终可见文本自动换行行高的内容。" * 16

    business["epics"][0]["targetOutcome"] = long_text  # type: ignore[index]
    business["features"][0]["description"] = long_text  # type: ignore[index]
    delivery["acceptanceCriteria"][0]["name"] = long_text  # type: ignore[index]
    estimate["tasks"][0]["name"] = long_text  # type: ignore[index]
    estimate["tasks"][0]["rationale"] = long_text  # type: ignore[index]
    delivery["integrations"][0]["purpose"] = long_text  # type: ignore[index]
    delivery["assumptions"][0]["trigger"] = long_text  # type: ignore[index]

    data = {
        "requirements": {
            "epics": [*business["epics"], *technical["epics"]],  # type: ignore[index]
            "features": [*business["features"], *technical["features"]],  # type: ignore[index]
        },
        "asis": read("data/analyze-as-is/asis.json"),
        "design": read("data/generate-design/design.json"),
        "technicalRequirements": technical,
        "delivery": delivery,
        "estimate": estimate,
    }
    template = fixture / "templates/sow-template.xlsx"
    output = tmp_path / "long-text.xlsx"
    MODULE.write_workbook(
        template,
        data,
        output,
        {name: "0" * 64 for name in ("sourceRequirements", "asis", "design", "derivedRequirements", "delivery", "estimate")},
    )

    template_workbook = openpyxl.load_workbook(template, data_only=False, read_only=False)
    workbook = openpyxl.load_workbook(output, data_only=False, read_only=False)
    try:
        def row_for(table_name: str, header: str, value: object) -> int:
            for worksheet in workbook.worksheets:
                if table_name not in worksheet.tables:
                    continue
                table = worksheet.tables[table_name]
                min_col, min_row, max_col, max_row = range_boundaries(table.ref)
                headers = [worksheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
                column = min_col + headers.index(header)
                return next(
                    row
                    for row in range(min_row + 1, max_row + 1)
                    if worksheet.cell(row, column).value == value
                )
            raise AssertionError(f"table not found: {table_name}")

        first_story_id = delivery["acceptanceCriteria"][0]["storyId"]  # type: ignore[index]
        first_story = next(
            story for story in delivery["stories"]  # type: ignore[index]
            if story["storyId"] == first_story_id
        )
        cases = [
            ("EpicTable", "需求名称", business["epics"][0]["name"]),  # type: ignore[index]
            ("FeatureTable", "子需求名称", business["features"][0]["name"]),  # type: ignore[index]
            ("SOWStoryTable", "故事名称", first_story["name"]),
            ("AcceptanceCriterionTable", "验收条件名称", long_text),
            ("TaskTable", "任务名称", long_text),
            ("IntegrationTable", "业务目的", long_text),
            ("AssumptionRiskTable", "假设/风险名称", delivery["assumptions"][0]["name"]),  # type: ignore[index]
        ]
        for table_name, identity_header, identity_value in cases:
            worksheet = next(
                sheet for sheet in workbook.worksheets
                if table_name in sheet.tables
            )
            template_worksheet = template_workbook[worksheet.title]
            _, min_row, _, _ = range_boundaries(worksheet.tables[table_name].ref)
            prototype_height = template_worksheet.row_dimensions[min_row + 1].height or 15
            row = row_for(table_name, identity_header, identity_value)
            assert (worksheet.row_dimensions[row].height or 15) > prototype_height, table_name
    finally:
        workbook.close()
        template_workbook.close()
