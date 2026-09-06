from __future__ import annotations

TEST_LAYER = "e2e"

import hashlib
import os
import shutil
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SKILL_ROOT / "tests"))
sys.path.insert(0, str(SKILL_ROOT.parents[1]))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import office_engine  # noqa: E402
from office_engine import (  # noqa: E402
    OfficeEngineError,
    deterministic_external_attr,
    discover_office_engine,
    require_office_engine,
)
import workbook as workbook_module  # noqa: E402


def installed_soffice() -> Path:
    explicit = os.environ.get("AI_SOW_OFFICE_BIN")
    executable = explicit or shutil.which("soffice") or shutil.which("libreoffice")
    if executable is None:
        pytest.skip("当前测试环境未安装 LibreOffice")
    return Path(executable).resolve()


def reviewed_sow_model() -> dict[str, object]:
    from test_workbook import render_model
    return render_model()


def named_table_records(workbook, sheet_name: str, table_name: str):
    sheet = workbook[sheet_name]
    table = sheet.tables[table_name]
    min_col, min_row, max_col, max_row = range_boundaries(table.ref)
    headers = [sheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
    return [
        {
            str(header): sheet.cell(row, column).value
            for header, column in zip(headers, range(min_col, max_col + 1), strict=True)
        }
        for row in range(min_row + 1, max_row + 1)
    ]


def calculated_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    executable = installed_soffice()
    monkeypatch.setenv("AI_SOW_OFFICE_BIN", str(executable))
    engine = require_office_engine()
    model = reviewed_sow_model()
    template = SKILL_ROOT / "assets/sow-template.xlsx"
    candidate = tmp_path / "candidate.xlsx"
    calculated = tmp_path / "calculated.xlsx"
    workbook_module.write_workbook(template, model, candidate)
    office_engine.recalculate_workbook(candidate, calculated, engine)
    return model, template, candidate, calculated, engine


def test_office_reaudit_checks_v6_catalog_task_sit_and_summary_invariants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, template, _candidate, calculated, engine = calculated_fixture(
        tmp_path, monkeypatch
    )

    audit = workbook_module.audit_calculated_workbook(
        calculated,
        template,
        model,
        engine,
    )

    assert audit.trust_state == "VERIFIED"
    assert audit.story_count == len(model["stories"])
    assert audit.task_count == len(model["tasks"])
    assert audit.total_days == pytest.approx(
        audit.direct_days + audit.sit_days + audit.uat_days
    )
    opened = load_workbook(calculated, data_only=True, read_only=False)
    try:
        standards = named_table_records(opened, "90-估算标准", "TaskStandardTable")
        tasks = named_table_records(opened, "02-任务清单", "TaskTable")
        assert len(standards) == 88
        assert {row["工作类型ID"] for row in tasks}
        billed = [row["SIT计费点ID"] for row in tasks if row["SIT计费点ID"]]
        assert len(billed) == len(set(billed))
    finally:
        opened.close()


def test_office_engine_prefers_explicit_supported_binary(monkeypatch) -> None:
    executable = installed_soffice()
    monkeypatch.setenv("AI_SOW_OFFICE_BIN", str(executable))

    engine = discover_office_engine()

    assert engine is not None
    assert engine.executable == str(executable)
    assert engine.name == "LibreOffice"
    assert "LibreOffice" in engine.version


def test_office_engine_falls_back_to_path_after_invalid_explicit_binary(
    monkeypatch,
) -> None:
    executable = installed_soffice()
    monkeypatch.setenv("AI_SOW_OFFICE_BIN", "/missing/ai-sow-office")
    monkeypatch.setattr(
        office_engine.shutil,
        "which",
        lambda name: str(executable) if name == "soffice" else None,
    )

    engine = discover_office_engine()

    assert engine is not None
    assert engine.executable == str(executable)


def test_missing_office_engine_is_not_a_verified_result(monkeypatch) -> None:
    monkeypatch.delenv("AI_SOW_OFFICE_BIN", raising=False)
    monkeypatch.setenv("PATH", "")

    with pytest.raises(OfficeEngineError) as caught:
        require_office_engine()

    assert caught.value.code == "OFFICE_ENGINE_UNAVAILABLE"


def test_real_office_roundtrip_is_isolated_and_byte_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, template, candidate, first, engine = calculated_fixture(tmp_path, monkeypatch)
    candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
    second = tmp_path / "second.xlsx"
    office_engine.recalculate_workbook(candidate, second, engine)

    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == candidate_sha256
    assert hashlib.sha256(first.read_bytes()).hexdigest() == hashlib.sha256(
        second.read_bytes()
    ).hexdigest()
    assert workbook_module.audit_calculated_workbook(
        second, template, model, engine
    ).trust_state == "VERIFIED"


def test_calculated_workbook_audit_rejects_formula_changed_after_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, template, _candidate, calculated, engine = calculated_fixture(
        tmp_path, monkeypatch
    )
    opened = load_workbook(calculated, data_only=False, read_only=False)
    try:
        opened["02-任务清单"]["L5"] = "=999"
        opened.save(calculated)
    finally:
        opened.close()

    with pytest.raises(ValueError, match="formula"):
        workbook_module.audit_calculated_workbook(
            calculated,
            template,
            model,
            engine,
        )


def test_zip_external_attributes_are_host_independent() -> None:
    windows_archive_bit = 0x20
    unix_regular_file = 0o100644 << 16

    assert deterministic_external_attr(windows_archive_bit) == (
        deterministic_external_attr(unix_regular_file)
    )


@pytest.mark.unit
def test_office_identity_is_non_sensitive_and_rejects_paths_or_failure(tmp_path):
    from contracts import canonical_json_bytes
    binary = tmp_path/'customer-secret'/'soffice'; binary.parent.mkdir(); binary.write_bytes(b'binary')
    engine = office_engine.OfficeEngine(str(binary), 'LibreOffice', 'LibreOffice 26.2.0.0 build abc')
    assert callable(getattr(office_engine, 'office_identity', None)), 'Office identity producer missing'
    identity = office_engine.office_identity(engine)
    assert set(identity) == {'executableBasename','binarySha256','version','platform','normalizedArguments','exitCode'}
    assert identity['binarySha256'] == hashlib.sha256(b'binary').hexdigest()
    assert b'customer-secret' not in canonical_json_bytes(identity)
    for field, value in [('exitCode',1),('executableBasename','/private/soffice'),
                         ('normalizedArguments',['--outdir','/customer/output']),('version','/private/customer')]:
        bad = {**identity, field:value}
        with pytest.raises(ValueError): office_engine.validate_office_identity(bad)


def test_dual_reopen_rejects_missing_formula_and_cache(tmp_path, monkeypatch):
    model, template, candidate, calculated, engine = calculated_fixture(tmp_path, monkeypatch)
    from workbook import dual_reopen
    report = dual_reopen(calculated, candidate)
    assert report['formulaCount'] > 0 and report['cachedValueCount'] == report['formulaCount']
    import zipfile
    for mutation in ('formula','cache','cache_type'):
        bad = tmp_path/(mutation+'.xlsx')
        with zipfile.ZipFile(calculated) as source, zipfile.ZipFile(bad,'w') as target:
            changed = False
            for name in source.namelist():
                raw = source.read(name)
                if name.startswith('xl/worksheets/') and not changed:
                    import re
                    if mutation == 'cache_type':
                        pattern = rb'(<c\b[^>]*?)(?: t="[^"]*")?(><f\b[^>]*>.*?</f>)<v>.*?</v>'
                        raw, count = re.subn(pattern, rb'\1 t="str"\2<v>wrong-cache-type</v>', raw, count=1)
                    else:
                        pattern = rb'<f\b[^>]*>.*?</f>' if mutation == 'formula' else rb'(<f\b[^>]*>.*?</f>)(<v>.*?</v>)'
                        raw, count = re.subn(pattern, b'' if mutation == 'formula' else rb'\1<v></v>', raw, count=1)
                    changed = bool(count)
                target.writestr(name, raw)
        assert changed
        if mutation == 'cache_type':
            opened = load_workbook(bad,data_only=True)
            try: assert any(cell.value == 'wrong-cache-type' for sheet in opened for row in sheet for cell in row)
            finally: opened.close()
            with pytest.raises(ValueError):
                workbook_module.audit_calculated_workbook(bad,template,model,engine,
                    expected_layout_path=candidate,reference_path=calculated)
        else:
            with pytest.raises(ValueError): dual_reopen(bad, candidate)


@pytest.mark.unit
def test_immutable_final_xlsx_uses_publish_new_and_hash_reopen(tmp_path):
    from runtime.project_io import ProjectFiles
    import generation_store
    assert callable(getattr(generation_store, 'freeze_workbook', None)), 'immutable final producer missing'
    files = ProjectFiles.open(tmp_path); path = '.ai-sow/work/runs/run/artifact/sow.xlsx'
    digest = hashlib.sha256(b'one').hexdigest()
    generation_store.freeze_workbook(files, path, b'one', digest)
    generation_store.freeze_workbook(files, path, b'one', digest)
    with pytest.raises(ValueError): generation_store.freeze_workbook(files, path, b'two', digest)
    with pytest.raises(Exception): generation_store.freeze_workbook(files, path, b'two', hashlib.sha256(b'two').hexdigest())
    assert files.read_bytes(path) == b'one'
