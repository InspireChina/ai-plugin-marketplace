"""Windows-platform storage and Office-projection boundaries.

These cases pin behaviour that a platform fix could plausibly loosen: index
recovery must re-prove every source, queries must stay read-only, an interrupted
first registration must remain replayable, and the accepted Office width
conversion must be one factor for the whole sheet rather than a per-column band.
"""
import shutil
import xml.etree.ElementTree as ET
import zipfile
from uuid import uuid4

import pytest

from ai_sow_lite import _prototype, inputs
from ai_sow_lite.cli import execute
from ai_sow_lite.contracts import PLUGIN_ROOT, canonical_json_bytes
from ai_sow_lite.project import StorageError, file_ref, initialize
from ai_sow_lite.workbook import audit_workbook

from .support.fixtures import build_ingested_case, read_json, write_json
from .support.observed import seed_observed_topic
from .test_workbook import project as build_workbook_project

TEMPLATE = PLUGIN_ROOT / "assets/sow-template.xlsx"

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


@pytest.mark.parametrize("damage", ["evidence_text", "evidence_dropped", "topic_title"])
def test_recovery_refuses_records_that_contradict_their_registration(tmp_path, damage):
    """A lost index must never mint a fresh trusted digest for altered bytes."""
    case = build_ingested_case(tmp_path / "corruption")
    topic_path = only_topic(case)
    record = read_json(topic_path)
    if damage == "evidence_text":
        record["evidence"][0]["text"] = "修改后的依据，不属于登记原文。"
    elif damage == "evidence_dropped":
        record["evidence"] = []
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


def test_deleting_a_topics_observations_is_refused_by_recovery(tmp_path):
    """The expected observation set comes from the registration, not from the record.

    A subset comparison passes trivially once the observations are gone, and
    rebuilding the expected bytes out of the record under test proves nothing. The
    record is rewritten with canonical bytes so only the missing observation, and
    not an incidental formatting difference, can cause the refusal.
    """
    project = tmp_path / "observation-deleted"
    project.mkdir()
    initialize(project, "new", TEMPLATE)
    case = seed_observed_topic(project)
    record = read_json(case["record"])
    assert len(record["observations"]) == 1, "fixture must carry a real observation"

    record["observations"] = []
    case["record"].write_bytes(canonical_json_bytes(record))
    case["index"].unlink()

    with pytest.raises(StorageError, match="EVIDENCE_MISSING"):
        inputs.recover_analysis_index(project)
    assert not case["index"].exists(), "a record missing its observations was granted an index"


def test_healthy_observed_topic_still_recovers(tmp_path):
    """The independent derivation must accept the bytes registration actually wrote."""
    project = tmp_path / "observation-healthy"
    project.mkdir()
    initialize(project, "new", TEMPLATE)
    case = seed_observed_topic(project, observations=2)
    expected = read_json(case["index"])
    case["index"].unlink()

    inputs.recover_analysis_index(project)

    assert read_json(case["index"])["items"] == expected["items"]
    assert len(read_json(case["record"])["observations"]) == 2


@pytest.mark.parametrize("operation", ["check", "recover"])
@pytest.mark.parametrize("adopted", [False, True])
@pytest.mark.parametrize("damage", ["missing_record", "changed_record", "missing_ref", "invalid_ref"])
def test_topic_proof_depends_only_on_registered_observations(tmp_path, operation, adopted, damage):
    """Unrelated incomplete/corrupt observations are not a healthy topic's dependencies.

    The adopted controls ensure ignoring an ineligible lookup candidate never
    turns a missing required observation into a successful proof.
    """
    project = tmp_path / "observation-boundary"
    project.mkdir()
    initialize(project, "new", TEMPLATE)
    case = seed_observed_topic(project, observations=2)
    analysis = read_json(case["record"])
    version = case["topic"]["topic_version_id"]
    expected_index = case["index"].read_bytes()
    assert len(_prototype.topic_dependencies(project, version, analysis)) == 3
    observation = project / case["observation_refs"][0]["path"]
    if not adopted:
        # An independent observation; it never belongs to this registration.
        record = read_json(observation)
        record["observation_id"], record["input_version_id"] = str(uuid4()), str(uuid4())
        observation = observation.parent.parent / record["observation_id"] / "observation.json"
        observation.parent.mkdir()
        observation.write_bytes(canonical_json_bytes(record))
        write_json(observation.with_name("registration-ref.json"), file_ref(project, observation))

    if damage == "missing_record":
        observation.unlink()
    elif damage == "changed_record":
        observation.write_bytes(b"changed observation bytes")
    elif damage == "missing_ref":
        observation.with_name("registration-ref.json").unlink()
    else:
        observation.with_name("registration-ref.json").write_bytes(b"invalid registration bytes")

    if operation == "recover":
        case["index"].unlink()

    def prove():
        if operation == "check":
            return _prototype.topic_dependencies(project, version, analysis)
        inputs.recover_analysis_index(project)
        return read_json(case["index"])["items"]

    if adopted:
        with pytest.raises(StorageError, match="EVIDENCE_MISSING"):
            prove()
        if operation == "recover":
            assert not case["index"].exists()
    else:
        assert prove()
        assert case["index"].read_bytes() == expected_index


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


def test_atomic_write_survives_a_deep_but_legal_project_path(tmp_path):
    """The sibling temp name must not be what pushes a write past MAX_PATH.

    Windows rejects paths at 260 characters unless long paths are enabled. A
    project directory can legally sit deep enough that the target file fits but
    '.<name>-<uuid4>.tmp' does not, which surfaced as an opaque IO_FAILED during
    render rather than as anything the caller could act on.
    """
    from ai_sow_lite.project import atomic_bytes

    target = tmp_path
    while len(str(target)) < 200:
        target = target / "深层目录"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "candidate.xlsx"
    assert len(str(path)) < 260, "the target itself must be legal for this to test the temp name"

    atomic_bytes(path, b"deep write")

    assert path.read_bytes() == b"deep write"
    assert not list(target.glob(".*tmp")), "the temporary sibling must not be left behind"
