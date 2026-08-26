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
