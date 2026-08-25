from __future__ import annotations

import hashlib
from pathlib import Path

import openpyxl


GENERATE_SOW_TEMPLATE = Path(__file__).resolve().parents[1] / "fixtures/project/.ai-sow/templates/sow-template.xlsx"
EXPECTED_SHA256 = "dc17a4ccb2902ba12379e7b964a2612d07f138a9b542cc6774bc05b4d3bf2e48"


def workbook_signature(path: Path) -> tuple[list[str], dict[str, str], int]:
    workbook = openpyxl.load_workbook(path, data_only=False, read_only=False)
    try:
        tables = {
            name: worksheet.tables[name].ref
            for worksheet in workbook.worksheets
            for name in worksheet.tables
        }
        formulas = sum(
            cell.data_type == "f"
            for worksheet in workbook.worksheets
            for row in worksheet.iter_rows()
            for cell in row
        )
        return workbook.sheetnames, tables, formulas
    finally:
        workbook.close()


def test_skill_local_template_copies_match_the_authoritative_fingerprint() -> None:
    assert hashlib.sha256(GENERATE_SOW_TEMPLATE.read_bytes()).hexdigest() == EXPECTED_SHA256
    sheets, tables, formulas = workbook_signature(GENERATE_SOW_TEMPLATE)
    assert len(sheets) == 12
    assert len(tables) == 12
    assert formulas == 41


def test_generate_sow_runtime_and_tests_do_not_read_another_skill_asset() -> None:
    skill_root = Path(__file__).resolve().parents[1]
    forbidden = "skills/" + "setup/assets"
    for path in [*skill_root.joinpath("scripts").glob("*.py"), *skill_root.joinpath("tests").glob("*.py")]:
        text = path.read_text(encoding="utf-8")
        assert forbidden not in text
