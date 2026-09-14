"""Windows-platform storage and Office-projection boundaries.

These cases pin behaviour that a platform fix could plausibly loosen: index
recovery must re-prove every source, queries must stay read-only, an interrupted
first registration must remain replayable, and the accepted Office width
conversion must be one factor for the whole sheet rather than a per-column band.
"""
import shutil
import xml.etree.ElementTree as ET
import zipfile

import pytest

from ai_sow_lite import inputs
from ai_sow_lite.cli import execute
from ai_sow_lite.project import StorageError
from ai_sow_lite.workbook import audit_workbook

from .support.fixtures import build_ingested_case, read_json, write_json
from .test_workbook import project as build_workbook_project

NAMESPACE = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def inspect_topics(case):
    return execute(dict(protocol_version="1.0", request_id=case.request_id,
                        project_path=str(case.project), operation="inspect",
                        payload=dict(view="topics", selector={}, limit=100, cursor=None)))


def registration_request(case):
    return dict(protocol_version="1.0", request_id=case.request_id,
                project_path=str(case.project), operation="ingest",
                payload=dict(kind="analysis", entrypoint="generate",
                             analysis_path=case.file("analysis.json")
                             .relative_to(case.project).as_posix()))


def index_of(case):
    return case.project / ".ai-sow-lite/analysis/index.json"


def only_topic(case):
    return case.project / read_json(index_of(case))["items"][0]["path"]


@pytest.mark.parametrize("damage", ["evidence_text", "evidence_dropped", "observations", "topic_title"])
def test_recovery_refuses_records_that_contradict_their_registration(tmp_path, damage):
    """A lost index must never mint a fresh trusted digest for altered bytes."""
    case = build_ingested_case(tmp_path / "corruption")
    topic_path = only_topic(case)
    record = read_json(topic_path)
    if damage == "evidence_text":
        record["evidence"][0]["text"] = "修改后的依据，不属于登记原文。"
    elif damage == "evidence_dropped":
        record["evidence"] = []
    elif damage == "observations":
        record["observations"] = []
    else:
        record["topics"][0]["title"] = "改写后的主题标题"
    write_json(topic_path, record)
    index_of(case).unlink()

    response = inspect_topics(case)
    assert not response["ok"], "query accepted a record that contradicts its registration"
    assert not index_of(case).exists(), "damaged bytes were granted a new trusted index"

    # The explicit write path must refuse it too, not just the query.
    replay = execute(registration_request(case))
    assert not replay["ok"], "registration adopted a record that contradicts its source"
    assert not index_of(case).exists()


@pytest.mark.parametrize("state", ["healthy", "corrupt"])
def test_queries_never_write_business_files(tmp_path, state):
    """inspect is read-only: it reports a missing index, it does not rebuild one."""
    case = build_ingested_case(tmp_path / "readonly")
    if state == "corrupt":
        record = read_json(only_topic(case))
        record["evidence"][0]["text"] = "被改写的依据。"
        write_json(only_topic(case), record)
    index_of(case).unlink()
    analysis = case.project / ".ai-sow-lite/analysis"
    before = {path: path.read_bytes() for path in sorted(analysis.rglob("*")) if path.is_file()}

    inspect_topics(case)

    after = {path: path.read_bytes() for path in sorted(analysis.rglob("*")) if path.is_file()}
    assert after == before, "a query modified business files"
    assert not index_of(case).exists(), "a query created the business index"


def test_healthy_index_loss_is_repaired_by_the_write_path(tmp_path):
    """Recovery still exists; it belongs to registration, not to a query."""
    case = build_ingested_case(tmp_path / "recoverable")
    expected = read_json(index_of(case))
    index_of(case).unlink()

    replayed = execute(registration_request(case))

    assert replayed["ok"], replayed["diagnostics"]
    assert index_of(case).exists()
    assert read_json(index_of(case))["items"] == expected["items"]


@pytest.mark.parametrize("interrupt_at", ["registration-ref.json", "analysis.json"])
def test_interrupted_first_registration_replays_within_the_same_request(tmp_path, monkeypatch,
                                                                        interrupt_at):
    """Either half-written state must finish on replay, not wedge the project."""
    case = build_ingested_case(tmp_path / "interruption")
    shutil.rmtree(case.project / ".ai-sow-lite/analysis")
    request = registration_request(case)
    original = inputs.write_json

    def interrupt(project, relative, *args, **kwargs):
        if relative.startswith(".ai-sow-lite/analysis/topics/") and relative.endswith(interrupt_at):
            raise OSError(f"injected crash before {interrupt_at}")
        return original(project, relative, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(inputs, "write_json", interrupt)
        failed = execute(request)
    assert not failed["ok"] and failed["diagnostics"][0]["code"] == "IO_FAILED"
    assert not index_of(case).exists()

    retried = execute(request)
    assert retried["ok"], retried["diagnostics"]
    assert index_of(case).exists()


def rewrite_widths(source, destination, changes):
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(destination, "w") as after:
        for item in before.infolist():
            raw = before.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                sheet = ET.fromstring(raw)
                for column in sheet.findall("m:cols/m:col", NAMESPACE):
                    key = column.get("min")
                    if key in changes:
                        column.set("width", changes[key](float(column.get("width"))))
                raw = ET.tostring(sheet)
            after.writestr(item, raw)


def test_width_audit_rejects_an_isolated_column_change(tmp_path):
    """One narrowed column is a layout edit, not a platform conversion."""
    build_workbook_project(tmp_path)
    source = tmp_path / "projected.xlsx"
    changed = tmp_path / "one-column-narrowed.xlsx"
    rewrite_widths(source, changed, {"4": lambda _: "78"})
    with pytest.raises(StorageError, match="WORKBOOK_INVALID"):
        audit_workbook(changed, source, caches=False)


def test_width_audit_accepts_the_observed_platform_rescale(tmp_path):
    """Windows LibreOffice rescales every column by ~0.91; that must still pass."""
    build_workbook_project(tmp_path)
    source = tmp_path / "projected.xlsx"
    rescaled = tmp_path / "platform-rescaled.xlsx"
    columns = {str(index): (lambda width: f"{width * 0.91:.2f}") for index in range(1, 40)}
    rewrite_widths(source, rescaled, columns)
    assert audit_workbook(rescaled, source, caches=False)["formula_count"]
