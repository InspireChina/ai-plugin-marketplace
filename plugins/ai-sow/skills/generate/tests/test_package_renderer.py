from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl
import pytest


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
ASSETS = SKILL_ROOT / "assets"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from package_renderer import PackageRenderError, prepare_draft  # noqa: E402
import story_notes  # noqa: E402
from task_standard_catalog import catalog as task_standard_catalog  # noqa: E402
import workbook  # noqa: E402


def reviewed_sow_model() -> dict[str, object]:
    from test_layered_review import review_state  # noqa: PLC0415

    return review_state()["candidate"]


def test_renderer_consumes_only_reviewed_sow_model_and_derived_projections() -> None:
    model = reviewed_sow_model()
    task_catalog = task_standard_catalog(ASSETS / "sow-template.xlsx")

    rows = workbook.build_rows(model, task_catalog)

    assert len(rows["SOWStoryTable"]) == len(model["stories"])
    assert len(rows["TaskTable"]) == len(model["tasks"])
    assert set(rows["SOWStoryTable"][0]) == {
        "需求",
        "子需求",
        "故事",
        "UAT适用",
        "验收条件",
        "备注",
        "任务列表",
    }
    assert set(rows["TaskTable"][0]) == {
        "所属故事",
        "任务名称",
        "工作类型ID",
        "工作方式",
        "复杂度",
        "SIT支持分类",
        "SIT计费点ID",
        "备注",
    }


def test_task_sheet_projects_v6_name_mode_complexity_and_unique_sit_assignment() -> None:
    model = reviewed_sow_model()
    task_catalog = task_standard_catalog(ASSETS / "sow-template.xlsx")

    rows = workbook.build_rows(model, task_catalog)
    integration_row = next(
        row for row in rows["TaskTable"] if row["工作类型ID"] == "IN-INTEGRATION"
    )
    story_row = next(
        row
        for row in rows["SOWStoryTable"]
        if "新增退款事件通知集成" in row["任务列表"]
    )

    assert integration_row["工作方式"] == "新建"
    assert integration_row["复杂度"] == "M"
    assert integration_row["SIT支持分类"] == "INTERNAL"
    assert integration_row["SIT计费点ID"] == "integration-refund-event"
    assert "IN-INTEGRATION" not in story_row["任务列表"]
    assert task_catalog.by_work_type_id["IN-INTEGRATION"]["工作类型名称"] in (
        story_row["任务列表"]
    )
    assert "task-refund-integration" not in story_row["任务列表"]


def test_notes_list_default_automation_and_concentrated_default_decisions() -> None:
    model = reviewed_sow_model()
    task_catalog = task_standard_catalog(ASSETS / "sow-template.xlsx")

    notes = story_notes.render_model_notes(
        model,
        {"contract": "ai-sow-layered-review-decision-v1", "decision": "PASS"},
        task_catalog,
    )

    assert "默认纳入的自动化与上线工程" in notes
    assert "policy-instance-sit" in notes
    assert "policy-instance-uat" in notes
    assert "用户排除与输入决定" in notes


def test_formula_like_business_text_remains_text(tmp_path: Path) -> None:
    model = reviewed_sow_model()
    model["tasks"][0]["name"] = "=SUM(A1:A2)"
    target = tmp_path / "candidate.xlsx"

    workbook.write_workbook(ASSETS / "sow-template.xlsx", model, target)

    opened = openpyxl.load_workbook(target, data_only=False, read_only=False)
    try:
        task = opened["02-任务清单"].cell(5, 2)
        assert task.value == "'=SUM(A1:A2)"
        assert task.data_type == "s"
    finally:
        opened.close()


def test_prepare_draft_rejects_review_that_is_not_bound_to_the_model() -> None:
    model = reviewed_sow_model()
    review = {
        "decision": "PASS",
        "candidateSha256": "0" * 64,
        "scopeClosureCheckpointSha256": "1" * 64,
        "storyAcCheckpointSha256": "2" * 64,
        "taskCheckpointSha256": "3" * 64,
    }

    with pytest.raises(PackageRenderError) as caught:
        prepare_draft(
            model,
            template_path=ASSETS / "sow-template.xlsx",
            review_decision=review,
        )

    assert caught.value.code == "REVIEW_DECISION_STALE"


def test_staged_renderer_bytes_move_to_canonical_paths_and_match_v8_fingerprint() -> None:
    baseline = json.loads(
        (SKILL_ROOT / "contracts/renderer-fingerprint-baseline.json").read_text(
            encoding="utf-8"
        )
    )
    assert baseline["rendererContract"] == "generation-renderer-v8"
    assert set(baseline["files"]) == {
        "scripts/package_renderer.py",
        "scripts/workbook.py",
        "scripts/office_engine.py",
        "scripts/story_notes.py",
    }
    for canonical_path, expected_sha256 in baseline["files"].items():
        assert expected_sha256 == sha256_bytes((SKILL_ROOT / canonical_path).read_bytes())


def test_no_staging_renderer_path_remains_after_cutover() -> None:
    assert not (SCRIPTS / "next").exists()
    assert not (SKILL_ROOT / "contracts/next").exists()
    assert not (ASSETS / "sow-template-v6.next.xlsx").exists()
