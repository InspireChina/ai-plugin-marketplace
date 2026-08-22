from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SKILL_ROOT = Path(__file__).parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "validate.py"
FIXTURE = SKILL_ROOT / "fixtures" / "requirements.valid.json"
SOURCE_BYTES = b"Customer profile source document.\n"


def run_validator(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(project_root)],
        capture_output=True,
        text=True,
        check=False,
    )


def write_requirements(project_root: Path, payload: dict[str, object]) -> None:
    path = project_root / ".ai-sow/data/analyze-requirement/requirements.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def prepare_valid(project_root: Path) -> dict[str, object]:
    payload = json.loads(FIXTURE.read_text())
    source_path = project_root / payload["sourceDocuments"][0]["file"]
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(SOURCE_BYTES)
    write_requirements(project_root, payload)
    return payload


def test_accepts_valid_source_requirements(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["outcome"] == "OK"
    validation = json.loads(
        (tmp_path / ".ai-sow/validation/analyze-requirement.json").read_text()
    )
    assert validation["passed"] is True
    assert payload["epics"][0]["epicId"].startswith("epic-")
    assert payload["features"][0]["featureId"].startswith("feature-")
    assert payload["features"][0]["epicId"] == payload["epics"][0]["epicId"]


@pytest.mark.parametrize(
    ("collection", "field"),
    [
        ("epics", "involvedSystemsData"),
        ("epics", "targetOutcome"),
        ("epics", "commonConstraintsOutOfScope"),
        ("features", "involvedSystemsData"),
        ("features", "constraintsNfr"),
    ],
)
def test_rejects_empty_optional_semantic_field(
    tmp_path: Path,
    collection: str,
    field: str,
) -> None:
    payload = prepare_valid(tmp_path)
    payload[collection][0][field] = ""
    write_requirements(tmp_path, payload)

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(item["code"] == "SCHEMA_INVALID" for item in json.loads(result.stdout)["diagnostics"])


@pytest.mark.parametrize(
    ("collection", "field", "value"),
    [
        ("epics", "epicId", "feature-wrong-kind"),
        ("features", "featureId", "epic-wrong-kind"),
    ],
)
def test_rejects_wrong_entity_id_prefix(
    tmp_path: Path,
    collection: str,
    field: str,
    value: str,
) -> None:
    payload = prepare_valid(tmp_path)
    payload[collection][0][field] = value
    write_requirements(tmp_path, payload)

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(item["code"] == "SCHEMA_INVALID" for item in json.loads(result.stdout)["diagnostics"])


def test_rejects_technical_epic(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    payload["epics"][0]["type"] = "TECHNICAL"
    write_requirements(tmp_path, payload)

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(item["code"] == "SCHEMA_INVALID" for item in json.loads(result.stdout)["diagnostics"])


def test_rejects_old_requirement_collections(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    payload["subFeatures"] = []
    write_requirements(tmp_path, payload)

    assert run_validator(tmp_path).returncode == 2


@pytest.mark.parametrize(
    "file",
    [
        "../outside.md",
        "/tmp/source.md",
        ".ai-sow/inputs/analyze-as-is/source.md",
        ".ai-sow/inputs/analyze-requirement/../secret.md",
        "C:\\source.md",
    ],
)
def test_rejects_unsafe_or_unowned_source_document_file(tmp_path: Path, file: str) -> None:
    payload = prepare_valid(tmp_path)
    payload["sourceDocuments"][0]["file"] = file
    write_requirements(tmp_path, payload)

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(item["code"] == "SCHEMA_INVALID" for item in json.loads(result.stdout)["diagnostics"])


def test_rejects_source_document_hash_mismatch(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    payload["sourceDocuments"][0]["sha256"] = "0" * 64
    write_requirements(tmp_path, payload)

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(item["code"] == "SOURCE_DOCUMENT_HASH_MISMATCH" for item in json.loads(result.stdout)["diagnostics"])


def test_rejects_unknown_source_document_reference(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    payload["normalizedItems"][0]["sourceDocumentId"] = "source-document-unknown"
    write_requirements(tmp_path, payload)

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(item["code"] == "SOURCE_DOCUMENT_REF_UNKNOWN" for item in json.loads(result.stdout)["diagnostics"])


def test_rejects_unknown_epic_reference(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    payload["features"][0]["epicId"] = "epic-unknown"
    write_requirements(tmp_path, payload)

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(item["code"] == "EPIC_REF_UNKNOWN" for item in json.loads(result.stdout)["diagnostics"])


def test_rejects_unknown_normalized_item_reference(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    payload["features"][0]["source"]["normalizedItemIds"] = ["norm-not-found"]
    write_requirements(tmp_path, payload)

    result = run_validator(tmp_path)

    assert result.returncode == 2
    diagnostics = json.loads(result.stdout)["diagnostics"]
    assert any(item["code"] == "NORMALIZED_ITEM_REF_UNKNOWN" for item in diagnostics)


@pytest.mark.parametrize("symlink_kind", ["directory", "report"])
def test_blocks_validation_output_symlink_escape(
    tmp_path: Path,
    symlink_kind: str,
) -> None:
    prepare_valid(tmp_path)
    validation_path = tmp_path / ".ai-sow/validation/analyze-requirement.json"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-validation"
    outside.mkdir()
    if symlink_kind == "directory":
        validation_path.parent.symlink_to(outside, target_is_directory=True)
    else:
        validation_path.parent.mkdir(parents=True)
        validation_path.symlink_to(outside / "escaped.json")

    result = run_validator(tmp_path)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    assert any(item["code"] == "OUTPUT_PATH_UNSAFE" for item in payload["diagnostics"])
    assert list(outside.iterdir()) == []


def test_portable_directory_snapshot_rejects_windows_reparse_point() -> None:
    spec = importlib.util.spec_from_file_location("analyze_requirement_reparse", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    snapshot = SimpleNamespace(
        st_mode=stat.S_IFDIR | 0o755,
        st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
    )
    path = SimpleNamespace(stat=lambda *, follow_symlinks: snapshot)

    with pytest.raises(OSError, match="reparse point"):
        module._safe_directory_snapshot(path)


def test_portable_report_write_rejects_windows_reparse_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_path = tmp_path / ".ai-sow/validation/analyze-requirement.json"
    validation_path.parent.mkdir(parents=True)
    validation_path.write_text("original\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("analyze_requirement_report_reparse", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_stat = Path.stat

    def stat_with_reparse(path: Path, *, follow_symlinks: bool = True) -> object:
        snapshot = original_stat(path, follow_symlinks=follow_symlinks)
        if path == validation_path and not follow_symlinks:
            return SimpleNamespace(
                st_mode=snapshot.st_mode,
                st_dev=snapshot.st_dev,
                st_ino=snapshot.st_ino,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return snapshot

    monkeypatch.setattr(Path, "stat", stat_with_reparse)

    with pytest.raises(OSError, match="reparse point"):
        module._write_validation_report_portable(
            tmp_path,
            validation_path,
            "replacement\n",
        )
    assert validation_path.read_text(encoding="utf-8") == "original\n"


@pytest.mark.parametrize("race_kind", ["directory", "report"])
@pytest.mark.parametrize("writer_backend", ["native", "portable"])
def test_blocks_validation_symlink_swap_after_safety_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    race_kind: str,
    writer_backend: str,
) -> None:
    prepare_valid(tmp_path)
    validation_path = tmp_path / ".ai-sow/validation/analyze-requirement.json"
    validation_path.parent.mkdir(parents=True)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-race"
    outside.mkdir()
    original_validation_dir = validation_path.parent.with_name("validation-before-race")
    spec = importlib.util.spec_from_file_location("analyze_requirement_race", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if writer_backend == "portable":
        monkeypatch.setattr(
            module,
            "write_validation_report",
            module._write_validation_report_portable,
        )
    original_check = module.validation_output_diagnostic

    def check_then_swap(project_root: Path, report_path: Path) -> dict[str, str] | None:
        result = original_check(project_root, report_path)
        assert result is None
        if race_kind == "directory":
            validation_path.parent.rename(original_validation_dir)
            validation_path.parent.symlink_to(outside, target_is_directory=True)
        else:
            validation_path.symlink_to(outside / "escaped.json")
        return result

    monkeypatch.setattr(module, "validation_output_diagnostic", check_then_swap)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--project-root", str(tmp_path)],
    )

    returncode = module.main()
    payload = json.loads(capsys.readouterr().out)

    assert returncode == 2
    assert payload["outcome"] == "BLOCKED"
    assert any(item["code"] == "OUTPUT_UNWRITABLE" for item in payload["diagnostics"])
    assert list(outside.iterdir()) == []
