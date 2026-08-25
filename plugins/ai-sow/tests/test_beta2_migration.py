from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "migrations/beta1_to_beta2.py"
SPEC = importlib.util.spec_from_file_location("beta1_to_beta2", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def beta1_project() -> dict[str, str]:
    return {
        "projectId": "migration-fixture",
        "name": "迁移测试项目",
        "pluginVersion": "0.1.0-beta.1",
        "sowStandardVersion": "1.3",
    }


def write_project(root: Path, value: dict[str, str]) -> None:
    directory = root / ".ai-sow"
    directory.mkdir(parents=True)
    (directory / "project.json").write_bytes(MODULE.canonical_json_bytes(value))


def test_migration_changes_only_project_metadata_and_reuses_identical_report(tmp_path: Path) -> None:
    write_project(tmp_path, beta1_project())
    unrelated = tmp_path / ".ai-sow/data/stable.json"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b'{"stable":true}\n')

    first_publication, first_report = MODULE.migrate(tmp_path)
    report_path = tmp_path / MODULE.REPORT_PATH
    first_bytes = report_path.read_bytes()
    second_publication, second_report = MODULE.migrate(tmp_path)

    assert first_publication == "CREATED"
    assert second_publication == "REUSED"
    assert first_report == second_report
    assert report_path.read_bytes() == first_bytes
    assert unrelated.read_bytes() == b'{"stable":true}\n'
    project = json.loads((tmp_path / MODULE.PROJECT_PATH).read_text(encoding="utf-8"))
    assert project == {**beta1_project(), "pluginVersion": "0.1.0-beta.2"}
    assert first_report["businessDataChanged"] is False
    assert first_report["stableDataAction"] == "REVIEW_AND_REPUBLISH_0_3"


def test_interruption_after_project_write_resumes_safely(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_project(tmp_path, beta1_project())
    original = MODULE.ProjectFiles.publish_new

    def interrupt(*args: object, **kwargs: object) -> str:
        raise OSError("simulated interruption")

    monkeypatch.setattr(MODULE.ProjectFiles, "publish_new", interrupt)
    with pytest.raises(OSError, match="simulated interruption"):
        MODULE.migrate(tmp_path)
    project = json.loads((tmp_path / MODULE.PROJECT_PATH).read_text(encoding="utf-8"))
    assert project["pluginVersion"] == "0.1.0-beta.2"
    monkeypatch.setattr(MODULE.ProjectFiles, "publish_new", original)

    publication, _ = MODULE.migrate(tmp_path)

    assert publication == "CREATED"


def test_different_existing_report_fails_closed(tmp_path: Path) -> None:
    write_project(tmp_path, beta1_project())
    report = tmp_path / MODULE.REPORT_PATH
    report.parent.mkdir(parents=True)
    report.write_bytes(b"{}\n")

    with pytest.raises(MODULE.ProjectIOError) as captured:
        MODULE.migrate(tmp_path)

    assert captured.value.code == "PROJECT_CONTENT_CONFLICT"


@pytest.mark.parametrize(
    "value",
    [
        {**beta1_project(), "pluginVersion": "0.1.0-beta.0"},
        {**beta1_project(), "extra": True},
        {**beta1_project(), "projectId": "invalid"},
    ],
)
def test_migration_rejects_unsupported_or_invalid_project(tmp_path: Path, value: dict[str, object]) -> None:
    write_project(tmp_path, value)  # type: ignore[arg-type]
    with pytest.raises(MODULE.MigrationError):
        MODULE.migrate(tmp_path)
