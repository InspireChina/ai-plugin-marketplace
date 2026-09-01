from __future__ import annotations

import copy
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import openpyxl


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = SKILL_ROOT / "fixtures"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from contracts import canonical_json_bytes, load_schema_registry  # noqa: E402
from intake import (  # noqa: E402
    IntakeRequestError,
    compare_input_revisions,
    load_request,
    prepare_pending,
)
from runtime.project_io import ProjectFiles  # noqa: E402


NOW = lambda: datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_request(project: Path, mode: str = "greenfield") -> Path:
    request = read_json(FIXTURES / mode / "request.json")
    inputs = project / "inputs"
    inputs.mkdir(exist_ok=True)
    for source in request["sources"]:
        filename = {
            "PRD": "prd.md",
            "HLD": "hld.md",
            "PRIOR_SOW": "prior-sow.xlsx",
            "SUPPLEMENT": "supplement.md",
        }[source["role"]]
        path = inputs / filename
        if source["role"] == "PRIOR_SOW":
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "Scope"
            sheet.append(["Feature", "Effective Start"])
            sheet.append(["Refund", "Existing capability"])
            workbook.save(path)
        else:
            path.write_text(
                f"# {source['role']}\n\n退款服务的合成范围与结果说明。\n",
                encoding="utf-8",
            )
        source["path"] = str(path.absolute())
    target = project / "request.json"
    target.write_bytes(canonical_json_bytes(request))
    return target


@pytest.fixture
def registry():
    return load_schema_registry(SKILL_ROOT)


def diagnostic_codes(result) -> set[str]:
    return {diagnostic.code for diagnostic in result.diagnostics}


def prepare_from_request(project: Path, request_file: Path, registry, revision="000001"):
    files = ProjectFiles.open(project)
    request = load_request(files, request_file.relative_to(project).as_posix(), registry)
    return prepare_pending(files, request, revision_id=revision, now=NOW)


def test_greenfield_intake_copies_sources_and_sanitizes_paths(
    tmp_path: Path, registry
) -> None:
    request_file = write_request(tmp_path)
    result = prepare_from_request(tmp_path, request_file, registry)
    manifest = read_json(tmp_path / ".ai-sow/inputs/pending/manifest.json")
    assert result.outcome == "READY"
    assert all(not Path(source["path"]).is_absolute() for source in manifest["sources"])
    assert str(tmp_path) not in json.dumps(manifest, ensure_ascii=False)
    assert "/.ai-sow/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert not any(source["originalName"] == "sow-template.xlsx" for source in manifest["sources"])


def test_invalid_request_is_blocked_before_ai_sow_creation(tmp_path: Path, registry) -> None:
    request_file = write_request(tmp_path)
    request = read_json(request_file)
    del request["project"]["name"]
    request_file.write_bytes(canonical_json_bytes(request))
    with pytest.raises(IntakeRequestError) as captured:
        load_request(ProjectFiles.open(tmp_path), "request.json", registry)
    assert "CONTRACT_REQUIRED" in {item.code for item in captured.value.diagnostics}
    assert not (tmp_path / ".ai-sow").exists()


def test_brownfield_without_prior_sow_is_blocked_without_touching_current(
    tmp_path: Path, registry
) -> None:
    files = ProjectFiles.open(tmp_path)
    files.write_atomic(".ai-sow/current.json", b'{"sentinel":true}\n')
    current_before = files.read_bytes(".ai-sow/current.json")
    request_file = write_request(tmp_path, "brownfield")
    request = read_json(request_file)
    request["sources"] = [
        source for source in request["sources"] if source["role"] != "PRIOR_SOW"
    ]
    request_file.write_bytes(canonical_json_bytes(request))
    with pytest.raises(IntakeRequestError) as captured:
        load_request(files, "request.json", registry)
    assert "BROWNFIELD_PRIOR_SOW_REQUIRED" in {
        item.code for item in captured.value.diagnostics
    }
    assert files.read_bytes(".ai-sow/current.json") == current_before


def test_heading_move_is_not_a_semantic_change(tmp_path: Path) -> None:
    from source_readers import extract_document

    before = extract_document(
        FIXTURES / "incremental/moved-heading-before.md",
        source_id="prd-main",
        role="PRD",
    )
    after = extract_document(
        FIXTURES / "incremental/moved-heading-after.md",
        source_id="prd-main",
        role="PRD",
    )
    previous_manifest = {
        "sources": [{"sourceId": "prd-main", "version": "1", "sha256": "1" * 64}],
        "questionnaireAnswers": [],
        "responsibilityBoundaries": [],
    }
    pending_manifest = {
        "sources": [{"sourceId": "prd-main", "version": "2", "sha256": "2" * 64}],
        "questionnaireAnswers": [],
        "responsibilityBoundaries": [],
    }
    changes = compare_input_revisions(
        previous_manifest,
        [anchor.__dict__ for anchor in before],
        pending_manifest,
        [anchor.__dict__ for anchor in after],
    )
    assert {change.change for change in changes.source_changes} == {"MOVED_UNCHANGED"}
    assert changes.exact_match is False


def test_pending_resume_retains_revision_and_deduplicates_answers(
    tmp_path: Path, registry
) -> None:
    request_file = write_request(tmp_path)
    first = prepare_from_request(tmp_path, request_file, registry, revision="000007")
    assert first.outcome == "READY"

    request = read_json(request_file)
    request["questionnaireAnswers"].append(
        {"questionId": "question-migration-owner", "answer": "客户负责数据准备。"}
    )
    request_file.write_bytes(canonical_json_bytes(request))
    second = prepare_from_request(tmp_path, request_file, registry, revision="000099")
    manifest = read_json(tmp_path / ".ai-sow/inputs/pending/manifest.json")
    assert second.outcome == "READY"
    assert manifest["revisionId"] == "000007"
    assert [
        item["questionId"] for item in manifest["questionnaireAnswers"]
    ].count("question-migration-owner") == 1


def test_conflicting_answer_is_retained_and_asked_once(tmp_path: Path, registry) -> None:
    request_file = write_request(tmp_path)
    prepare_from_request(tmp_path, request_file, registry)
    request = read_json(request_file)
    request["questionnaireAnswers"][0]["answer"] = "测试环境由供应商准备。"
    request_file.write_bytes(canonical_json_bytes(request))
    result = prepare_from_request(tmp_path, request_file, registry, revision="000002")
    answers = read_json(tmp_path / ".ai-sow/inputs/pending/answers.json")
    assert len(
        [item for item in answers if item["questionId"] == "question-environment-readiness"]
    ) == 2
    assert len(result.questions) == 1


@pytest.mark.parametrize("suffix", [".docx", ".pdf"])
def test_unsupported_source_is_rejected_before_project_writes_without_leaking_text(
    tmp_path: Path, registry, suffix: str
) -> None:
    request_file = write_request(tmp_path)
    request = read_json(request_file)
    confidential = "绝密客户原文-不得输出"
    bad = tmp_path / f"inputs/bad{suffix}"
    bad.write_text(confidential, encoding="utf-8")
    request["sources"][0]["path"] = str(bad)
    request_file.write_bytes(canonical_json_bytes(request))
    with pytest.raises(IntakeRequestError) as captured:
        load_request(ProjectFiles.open(tmp_path), "request.json", registry)
    assert {item.code for item in captured.value.diagnostics} == {
        "SOURCE_FORMAT_UNSUPPORTED"
    }
    assert confidential not in repr(captured.value.diagnostics)
    assert not (tmp_path / ".ai-sow").exists()


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        (" \n", "SOURCE_BLANK"),
        ("# 示例模板\n\n仅供参考，请填写范围。\n", "SOURCE_IRRELEVANT_SAMPLE"),
    ],
)
def test_invalid_prd_content_is_retained_as_blocked_pending(
    tmp_path: Path, registry, content: str, expected_code: str
) -> None:
    request_file = write_request(tmp_path)
    request = read_json(request_file)
    source = Path(request["sources"][0]["path"])
    source.write_text(content, encoding="utf-8")
    result = prepare_from_request(tmp_path, request_file, registry)
    assert result.outcome == "BLOCKED"
    assert expected_code in diagnostic_codes(result)
    assert (tmp_path / ".ai-sow/inputs/pending").is_dir()


@pytest.mark.parametrize("suffix", [".html", ".ts", ".tsx"])
def test_prototype_supplement_is_copied_and_anchored_as_text(
    tmp_path: Path, registry, suffix: str
) -> None:
    request_file = write_request(tmp_path)
    request = read_json(request_file)
    prototype = tmp_path / f"inputs/prototype{suffix}"
    prototype.write_text(
        '<button onClick={() => setStatus("submitted")}>Submit refund</button>\n',
        encoding="utf-8",
    )
    request["sources"].append(
        {
            "sourceId": f"prototype-{suffix[1:]}",
            "role": "SUPPLEMENT",
            "version": "1.0",
            "path": str(prototype),
        }
    )
    request_file.write_bytes(canonical_json_bytes(request))

    result = prepare_from_request(tmp_path, request_file, registry)
    manifest = read_json(tmp_path / ".ai-sow/inputs/pending/manifest.json")
    anchors = json.loads(
        (tmp_path / ".ai-sow/inputs/pending/anchors.json").read_text(encoding="utf-8")
    )
    prototype_entry = next(
        source
        for source in manifest["sources"]
        if source["sourceId"].startswith("prototype-")
    )
    prototype_text = " ".join(
        anchor["normalizedText"]
        for anchor in anchors
        if anchor["sourceId"] == prototype_entry["sourceId"]
    )
    assert result.outcome == "READY"
    assert prototype_entry["mediaType"].startswith("text/")
    assert "setStatus" in prototype_text


def test_symlink_gitignore_is_blocked_without_touching_target(
    tmp_path: Path, registry
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-gitignore"
    outside.write_bytes(b"outside\n")
    try:
        (tmp_path / ".gitignore").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不允许创建 symlink")
    request_file = write_request(tmp_path)
    result = prepare_from_request(tmp_path, request_file, registry)
    assert result.outcome == "BLOCKED"
    assert diagnostic_codes(result) == {"GITIGNORE_UNSAFE"}
    assert outside.read_bytes() == b"outside\n"
    assert not (tmp_path / ".ai-sow").exists()


def test_work_request_is_removed_after_outcome(tmp_path: Path, registry) -> None:
    write_request(tmp_path)
    work = tmp_path / ".ai-sow/work"
    work.mkdir(parents=True)
    request = read_json(tmp_path / "request.json")
    work_request = work / "request.json"
    work_request.write_bytes(canonical_json_bytes(request))
    files = ProjectFiles.open(tmp_path)
    loaded = load_request(files, ".ai-sow/work/request.json", registry)
    result = prepare_pending(files, loaded, revision_id="000001", now=NOW)
    assert result.outcome == "READY"
    assert not work_request.exists()


def test_existing_gitignore_bytes_are_preserved(tmp_path: Path, registry) -> None:
    original = b"build/\n.env"
    (tmp_path / ".gitignore").write_bytes(original)
    result = prepare_from_request(tmp_path, write_request(tmp_path), registry)
    assert result.outcome == "READY"
    assert (tmp_path / ".gitignore").read_bytes() == original + b"\n/.ai-sow/\n"


def test_interrupted_pending_swap_restores_previous_pending(
    tmp_path: Path, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_file = write_request(tmp_path)
    prepare_from_request(tmp_path, request_file, registry, revision="000003")
    pending = tmp_path / ".ai-sow/inputs/pending"
    before = {
        path.relative_to(pending).as_posix(): path.read_bytes()
        for path in pending.rglob("*")
        if path.is_file()
    }
    real_replace = os.replace
    calls = 0

    def fail_new_pending(source, target):
        nonlocal calls
        if Path(target) == pending:
            calls += 1
            if calls == 1:
                raise OSError("simulated rename interruption")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_new_pending)
    result = prepare_from_request(tmp_path, request_file, registry, revision="000004")
    after = {
        path.relative_to(pending).as_posix(): path.read_bytes()
        for path in pending.rglob("*")
        if path.is_file()
    }
    assert result.outcome == "BLOCKED"
    assert diagnostic_codes(result) == {"PENDING_PUBLISH_FAILED"}
    assert after == before
