from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import openpyxl


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = SKILL_ROOT / "fixtures"
ASSETS = SKILL_ROOT / "assets"
PUBLIC_WORKBOOK = SKILL_ROOT.parents[1] / "docs/reference/SOW估算与生成示例_v1.3.xlsx"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from package_renderer import render_package  # noqa: E402


def fixture(mode: str, name: str) -> dict[str, object]:
    return json.loads((FIXTURES / mode / name).read_text(encoding="utf-8"))


def render_fixture(root: Path, mode: str = "brownfield"):
    manifest = fixture(mode, "input-manifest.json")
    scope = fixture(mode, "scope.json")
    delivery = fixture(mode, "delivery.json")
    delivery["scopeSha256"] = sha256_bytes(canonical_json_bytes(scope))
    review = fixture(mode, "final-review.json")
    review["scopeSha256"] = sha256_bytes(canonical_json_bytes(scope))
    review["deliverySha256"] = sha256_bytes(canonical_json_bytes(delivery))
    result = render_package(
        generation_id="000001",
        template_path=ASSETS / "sow-template.xlsx",
        output_root=root,
        input_manifest=manifest,
        scope=scope,
        delivery=delivery,
        review=review,
    )
    return result, manifest, scope, delivery, review


def test_renderer_uses_scope_and_delivery_only(tmp_path: Path) -> None:
    rendered, _manifest, _scope, _delivery, _review = render_fixture(tmp_path)
    assert rendered.workbook_sha256
    assert rendered.notes_sha256
    assert rendered.files == ("output/sow-notes.md", "output/sow.xlsx")
    assert not any("validation/" in path or "reviews/" in path for path in rendered.files)


def test_all_pass_with_notes_items_are_in_sow_notes(tmp_path: Path) -> None:
    rendered, _manifest, _scope, _delivery, review = render_fixture(tmp_path)
    notes = Path(rendered.notes_path).read_text(encoding="utf-8")
    for note in review["notes"]:
        assert notes.count(note["sowNotesText"]) == 1


def test_formula_like_user_text_remains_text(tmp_path: Path) -> None:
    manifest = fixture("greenfield", "input-manifest.json")
    scope = fixture("greenfield", "scope.json")
    scope["features"][0]["name"] = '=HYPERLINK("x")'
    delivery = fixture("greenfield", "delivery.json")
    delivery["scopeSha256"] = sha256_bytes(canonical_json_bytes(scope))
    review = fixture("greenfield", "final-review.json")
    review["scopeSha256"] = sha256_bytes(canonical_json_bytes(scope))
    review["deliverySha256"] = sha256_bytes(canonical_json_bytes(delivery))
    rendered = render_package(
        generation_id="000001",
        template_path=ASSETS / "sow-template.xlsx",
        output_root=tmp_path,
        input_manifest=manifest,
        scope=scope,
        delivery=delivery,
        review=review,
    )
    workbook = openpyxl.load_workbook(rendered.workbook_path, data_only=False)
    try:
        matches = [
            cell
            for row in workbook["02-子需求"].iter_rows()
            for cell in row
            if cell.value == "'=HYPERLINK(\"x\")"
        ]
        assert len(matches) == 1
        assert matches[0].data_type == "s"
    finally:
        workbook.close()


def test_repeated_render_is_byte_identical(tmp_path: Path) -> None:
    first, manifest, scope, delivery, review = render_fixture(tmp_path / "first")
    second = render_package(
        generation_id="000001",
        template_path=ASSETS / "sow-template.xlsx",
        output_root=tmp_path / "second",
        input_manifest=copy.deepcopy(manifest),
        scope=copy.deepcopy(scope),
        delivery=copy.deepcopy(delivery),
        review=copy.deepcopy(review),
    )
    assert Path(first.workbook_path).read_bytes() == Path(second.workbook_path).read_bytes()
    assert Path(first.notes_path).read_bytes() == Path(second.notes_path).read_bytes()


def test_public_synthetic_workbook_is_generated_from_brownfield_fixture(
    tmp_path: Path,
) -> None:
    rendered, _manifest, _scope, _delivery, _review = render_fixture(tmp_path)
    assert Path(rendered.workbook_path).read_bytes() == PUBLIC_WORKBOOK.read_bytes()


def test_business_sheets_do_not_expose_stable_ids(tmp_path: Path) -> None:
    rendered, _manifest, scope, delivery, _review = render_fixture(tmp_path)
    forbidden = {
        str(value)
        for collection in (
            "epics",
            "features",
            "commitments",
            "effectiveStartItems",
            "designItems",
            "designDecisions",
            "integrations",
            "nfrs",
            "assumptions",
        )
        for item in scope[collection]
        for key, value in item.items()
        if key.endswith("Id") and isinstance(value, str)
    } | {
        str(value)
        for collection in ("stories", "acceptanceCriteria", "tasks", "dependencies")
        for item in delivery[collection]
        for key, value in item.items()
        if key.endswith("Id") and isinstance(value, str)
    }
    workbook = openpyxl.load_workbook(rendered.workbook_path, data_only=False)
    try:
        visible = {
            str(cell.value)
            for name in (
                "01-需求",
                "02-子需求",
                "03-SOW主表",
                "04-验收条件",
                "05-任务明细",
                "06-集成点",
                "07-假设清单",
                "90-系统现状",
            )
            for row in workbook[name].iter_rows()
            for cell in row
            if cell.value is not None
        }
        assert forbidden.isdisjoint(visible)
    finally:
        workbook.close()
