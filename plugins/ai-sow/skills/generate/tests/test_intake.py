from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import openpyxl
import pytest


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from contracts import canonical_json_bytes  # noqa: E402
from intake import prepare  # noqa: E402
from runtime.project_io import ProjectFiles  # noqa: E402


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_next_request(
    project: Path,
    *,
    mode: str = "GREENFIELD",
    design_status: str = "APPROVED",
    include_prior: bool = False,
    include_demos: bool = False,
) -> Path:
    inputs = project / "inputs"
    inputs.mkdir(exist_ok=True)
    (inputs / "prd.md").write_text(
        "# 退款范围\n\n用户提交退款并看到处理结果。\n",
        encoding="utf-8",
    )
    (inputs / "hld.md").write_text(
        "# 目标架构\n\n门户调用退款服务。\n\n"
        "## 部署\n\n退款服务部署到生产环境并支持回退。\n",
        encoding="utf-8",
    )
    sources: list[dict[str, object]] = [
        {
            "sourceId": "prd-main",
            "role": "PRD",
            "path": "inputs/prd.md",
            "status": "APPROVED",
        },
        {
            "sourceId": "hld-main",
            "role": "HLD",
            "path": "inputs/hld.md",
            "status": design_status,
        },
    ]
    if include_prior:
        prior = openpyxl.Workbook()
        prior.active.title = "Scope"
        prior.active.append(["Feature", "Effective Start"])
        prior.active.append(["Refund", "Existing capability"])
        prior.save(inputs / "prior.xlsx")
        sources.append(
            {
                "sourceId": "prior-main",
                "role": "PRIOR_SOW",
                "path": "inputs/prior.xlsx",
                "status": "APPLICABLE",
            }
        )
    if include_demos:
        (inputs / "selected.html").write_text(
            "<button id='refund'>提交退款</button>", encoding="utf-8"
        )
        sources.extend(
            [
                {
                    "sourceId": "demo-selected",
                    "role": "DEMO",
                    "path": "inputs/selected.html",
                    "status": "SELECTED",
                },
                {
                    "sourceId": "demo-ignored",
                    "role": "DEMO",
                    "path": "inputs/does-not-exist.html",
                    "status": "NOT_SELECTED",
                },
            ]
        )
    value = {
        "contract": "ai-sow-generate-request-v2",
        "project": {
            "projectId": "project-refund",
            "name": "退款项目",
            "plannedEffectiveDate": "2026-10-01",
        },
        "mode": mode,
        "responsibilityBoundaries": [
            {
                "responsibilityBoundaryId": "responsibility-vendor",
                "party": "VENDOR",
                "name": "供应商交付责任",
                "responsibilities": ["实现并验证范围内能力"],
            }
        ],
        "sources": sources,
        "questions": [],
        "questionnaireAnswers": [],
        "currentStateDelta": (
            {
                "status": "NO_KNOWN_CHANGES",
                "summary": "未发现会改变本期范围的现状变化。",
                "supplementalSourceIds": [],
            }
            if mode == "BROWNFIELD"
            else None
        ),
    }
    path = project / "next-request.json"
    path.write_bytes(canonical_json_bytes(value))
    return path


def test_prepare_runs_cheap_gate_before_full_parse_or_project_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_path = write_next_request(tmp_path, design_status="DRAFT")
    calls: list[str] = []

    def unexpected_parse(*args, **kwargs):
        calls.append("parse")
        raise AssertionError("full parser must not run before the cheap gate passes")

    monkeypatch.setattr("intake.extract_source_blocks", unexpected_parse)

    result = prepare(request_path.name, files=ProjectFiles.open(tmp_path))

    assert result.value is None
    assert {item.code for item in result.diagnostics} == {
        "DESIGN_SOURCE_NOT_APPROVED"
    }
    assert calls == []
    assert not (tmp_path / ".ai-sow").exists()


def test_input_revision_is_immutable_and_atomically_accepted(tmp_path: Path) -> None:
    request_path = write_next_request(tmp_path)
    files = ProjectFiles.open(tmp_path)

    first = prepare(request_path.name, files=files)

    assert first.value is not None
    assert first.path is not None
    assert first.sha256 == hashlib.sha256(
        canonical_json_bytes(first.value)
    ).hexdigest()
    first_root = tmp_path / Path(first.path).parent
    assert (first_root / "sow-template.xlsx").read_bytes() == (
        SKILL_ROOT / "assets/sow-template.xlsx"
    ).read_bytes()
    assert (first_root / "delivery-policy.json").read_bytes() == (
        SKILL_ROOT / "contracts/delivery-policy-v1.json"
    ).read_bytes()
    assert (first_root / "execution-policy.json").read_bytes() == (
        SKILL_ROOT / "contracts/execution-policy-v1.json"
    ).read_bytes()
    assert not (tmp_path / ".ai-sow/work").exists()
    assert not any(first_root.rglob("*catalog*"))
    assert not any(first_root.rglob("*index*"))
    first_snapshot = {
        path.relative_to(first_root).as_posix(): path.read_bytes()
        for path in first_root.rglob("*")
        if path.is_file()
    }
    assert not any((tmp_path / ".ai-sow/inputs/pending").glob(".stage-*"))

    (tmp_path / "inputs/prd.md").write_text(
        "# 退款范围\n\n用户提交退款后还可撤销。\n", encoding="utf-8"
    )
    second = prepare(request_path.name, files=files)

    assert second.value is not None
    assert second.path != first.path
    assert {
        path.relative_to(first_root).as_posix(): path.read_bytes()
        for path in first_root.rglob("*")
        if path.is_file()
    } == first_snapshot
    assert not any((tmp_path / ".ai-sow/inputs/pending").glob(".stage-*"))


def test_selected_demo_is_hash_bound_as_requirement_source(tmp_path: Path) -> None:
    request_path = write_next_request(tmp_path, include_demos=True)

    result = prepare(request_path.name, files=ProjectFiles.open(tmp_path))

    assert result.value is not None
    sources = {item["sourceId"]: item for item in result.value["sources"]}
    assert "demo-selected" in sources
    assert "demo-ignored" not in sources
    selected = sources["demo-selected"]
    assert selected["role"] == "DEMO"
    assert selected["status"] == "SELECTED"
    assert selected["rawSha256"] == hashlib.sha256(
        (tmp_path / "inputs/selected.html").read_bytes()
    ).hexdigest()
    assert selected["blockIds"]


def test_input_revision_never_uses_external_temporary_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile  # noqa: PLC0415

    request_path = write_next_request(tmp_path)
    monkeypatch.setattr(
        tempfile,
        "TemporaryDirectory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("external temporary directory used")
        ),
    )

    result = prepare(request_path.name, files=ProjectFiles.open(tmp_path))

    assert result.value is not None
    assert not any((tmp_path / ".ai-sow/inputs/pending").glob(".build-*"))


def test_hld_or_adr_requires_approved_status(tmp_path: Path) -> None:
    request_path = write_next_request(tmp_path, design_status="REJECTED")

    rejected = prepare(request_path.name, files=ProjectFiles.open(tmp_path))

    assert rejected.value is None
    assert {item.code for item in rejected.diagnostics} == {
        "DESIGN_SOURCE_NOT_APPROVED"
    }
    assert not (tmp_path / ".ai-sow").exists()

    request = read_json(request_path)
    request["sources"][1].update({"role": "ADR", "status": "APPROVED"})
    request_path.write_bytes(canonical_json_bytes(request))
    approved = prepare(request_path.name, files=ProjectFiles.open(tmp_path))

    assert approved.value is not None
    assert any(source["role"] == "ADR" for source in approved.value["sources"])


def test_brownfield_without_prior_sow_records_not_provided(tmp_path: Path) -> None:
    request_path = write_next_request(tmp_path, mode="BROWNFIELD")

    result = prepare(request_path.name, files=ProjectFiles.open(tmp_path))

    assert result.value is not None
    assert result.value["priorSowState"] == "NOT_PROVIDED"
    assert result.value["priorSowSha256s"] == []


def test_parse_failure_never_changes_current_generation_or_project_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_path = write_next_request(tmp_path)
    managed = tmp_path / ".ai-sow"
    (managed / "generations/000001").mkdir(parents=True)
    current_payload = b'{"generationId":"000001"}\n'
    (managed / "current.json").write_bytes(current_payload)
    template_payload = (SKILL_ROOT / "assets/sow-template.xlsx").read_bytes()
    (managed / "templates").mkdir()
    (managed / "templates/sow-template.xlsx").write_bytes(template_payload)

    def fail_parse(*args, **kwargs):
        from source_readers import SourceReadError

        raise SourceReadError("SOURCE_UNREADABLE", "合成解析失败。")

    monkeypatch.setattr("intake.extract_source_blocks", fail_parse)
    result = prepare(request_path.name, files=ProjectFiles.open(tmp_path))

    assert result.value is None
    assert {item.code for item in result.diagnostics} == {"SOURCE_UNREADABLE"}
    assert (managed / "current.json").read_bytes() == current_payload
    assert (
        managed / "templates/sow-template.xlsx"
    ).read_bytes() == template_payload
