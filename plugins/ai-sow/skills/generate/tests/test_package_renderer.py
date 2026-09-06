from __future__ import annotations

TEST_LAYER = "integration"

import json
import sys
from pathlib import Path

import openpyxl
import pytest


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SKILL_ROOT / "tests"))
ASSETS = SKILL_ROOT / "assets"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from package_renderer import PackageRenderError, prepare_draft  # noqa: E402
import story_notes  # noqa: E402
from task_standard_catalog import catalog as task_standard_catalog  # noqa: E402
import workbook  # noqa: E402


@pytest.mark.unit
def test_office_viewports_keep_original_geometry_and_cover_large_sheet_with_overlap():
    from pypdf import PageObject
    from package_renderer import office_page_viewports
    original=PageObject.create_blank_page(width=5200,height=13000)
    pages=office_page_viewports(original)
    assert len(pages)>1 and tuple(original.mediabox)==(0,0,5200,13000)
    assert all(float(p.mediabox.width)<=1200 and float(p.mediabox.height)<=1200 for p in pages)
    boxes=[tuple(map(float,p.mediabox)) for p in pages]
    # Sample the full visible sheet, including all boundaries: nothing may disappear.
    for x in range(0,5201,100):
        for y in range(0,13001,100): assert any(left<=x<=right and bottom<=y<=top for left,bottom,right,top in boxes)
    assert max(right for _,_,right,_ in boxes)==5200 and max(top for *_,top in boxes)==13000
    assert len(office_page_viewports(PageObject.create_blank_page(width=800,height=600)))==1


def reviewed_sow_model() -> dict[str, object]:
    from test_workbook import render_model
    return render_model()


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
        "_sharedTaskReferences",
    }
    assert rows['SOWStoryTable'][0]['_sharedTaskReferences']==[]
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


def test_template_projection_notes_and_task_catalog_are_model_derived():
    model=reviewed_sow_model(); source=task_standard_catalog(ASSETS/'sow-template.xlsx')
    rows=workbook.build_rows(model,source)
    assert rows['TaskTable'][0]['工作类型ID']==model['tasks'][0]['workTypeId']
    assert model['tasks'][0]['taskId'] not in rows['SOWStoryTable'][0]['任务列表']
    notes=story_notes.render_model_notes(model,{'decision':'PASS'},source)
    assert '默认纳入的自动化与上线工程' in notes and '用户排除与输入决定' in notes


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


def test_staged_renderer_bytes_move_to_canonical_paths_and_match_v10_fingerprint() -> None:
    baseline = json.loads(
        (SKILL_ROOT / "contracts/renderer-fingerprint-baseline.json").read_text(
            encoding="utf-8"
        )
    )
    assert baseline["rendererContract"] == "generation-renderer-v12"
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


@pytest.mark.unit
def test_visible_sheet_review_exact_ir_and_ordered_normalization():
    from contracts import action_contract_binding, normalize_action_result
    import package_renderer
    assert callable(getattr(package_renderer, 'visual_identity', None)), 'visual singleton missing'
    _, digest = action_contract_binding(SKILL_ROOT, 'ARTIFACT_VISUAL_REVIEW-v1')
    envelope = {'actionContractId':'ARTIFACT_VISUAL_REVIEW-v1','actionContractSha256':digest}
    value = {'sheets':[{'sheetKey':key,'checks':{name:'PASS' for name in ('clipping','readability','unexpectedBlank','styleLoss')},
        'decision':'PASS','findings':[]} for key in ['sheet-b','sheet-a']], 'overallDecision':'PASS'}
    normalized = normalize_action_result(envelope, canonical_json_bytes(value), skill_root=SKILL_ROOT)
    assert json.loads(normalized)['sheets'][0]['sheetKey'] == 'sheet-b'
    assert package_renderer.visual_identity('a'*64,['b'*64,'c'*64],digest) != package_renderer.visual_identity('a'*64,['c'*64,'b'*64],digest)
    for field in ('runId','workbookSha256','path'):
        with pytest.raises(ValueError): normalize_action_result(envelope,canonical_json_bytes({**value,field:'forbidden'}),skill_root=SKILL_ROOT)


@pytest.mark.e2e
def test_visible_sheet_review_renders_actual_office_pages(tmp_path):
    import package_renderer
    assert callable(getattr(package_renderer, 'render_visible_sheets', None)), 'visible sheet renderer missing'
    from office_engine import require_office_engine, recalculate_workbook
    path = tmp_path/'candidate.xlsx'; final = tmp_path/'final.xlsx'
    workbook.write_workbook(ASSETS/'sow-template.xlsx',reviewed_sow_model(),path)
    recalculate_workbook(path,final,require_office_engine())
    renders = package_renderer.render_visible_sheets(final, tmp_path/'renders')
    book = openpyxl.load_workbook(final)
    try: assert [r['sheetKey'] for r in renders] == [s.title for s in book if s.sheet_state == 'visible']
    finally: book.close()
    for item in renders:
        raw = (tmp_path/'renders'/item['path']).read_bytes()
        assert raw.startswith(b'%PDF') and sha256_bytes(raw) == item['sha256']
        from pypdf import PdfReader
        page=PdfReader(tmp_path/'renders'/item['path']).pages[0]
        if item['sheetKey']=='01-需求故事':assert '需求故事' in page.extract_text()
        if item['sheetKey']=='03-工作量汇总':assert page.mediabox.width >= 350
