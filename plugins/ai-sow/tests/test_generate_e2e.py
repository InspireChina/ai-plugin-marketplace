from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

PLUGIN_ROOT = Path(__file__).parents[1]
TEST_ROOT = PLUGIN_ROOT / "tests"
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from support.smoke_plugin import run_smoke  # noqa: E402


CASE_MANIFEST = PLUGIN_ROOT / "tests/fixtures/explicit-architecture/case-manifest.json"
CASE_SCHEMA = PLUGIN_ROOT / "tests/contracts/case-manifest.schema.json"


def test_case_manifest_is_single_skill_and_schema_valid() -> None:
    manifest = json.loads(CASE_MANIFEST.read_text(encoding="utf-8"))
    schema = json.loads(CASE_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(manifest)
    assert {case["mode"] for case in manifest["cases"]} == {
        "GREENFIELD",
        "BROWNFIELD",
    }
    assert "owner" not in json.dumps(manifest).lower()
    for case in manifest["cases"]:
        for key, value in case.items():
            if key.endswith("Path"):
                assert (PLUGIN_ROOT / value).is_file(), (key, value)


@pytest.fixture(scope="module")
def smoke_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    return run_smoke(
        PLUGIN_ROOT,
        tmp_path_factory.mktemp("generate-copy-smoke"),
        copy_plugin=True,
    )


def test_copy_smoke_runs_both_project_modes_and_incremental_reuse(
    smoke_report: dict[str, object],
) -> None:
    assert smoke_report["pluginName"] == "ai-sow"
    assert smoke_report["publicSkills"] == ["generate"]
    assert smoke_report["greenfieldOutcome"] == "PUBLISHED"
    assert smoke_report["brownfieldOutcome"] == "PUBLISHED"
    assert smoke_report["blockedResumeOutcome"] == "PUBLISHED"
    assert smoke_report["reuseOutcome"] == "REUSED"
    assert smoke_report["marketplaceReadCount"] == 0


def test_copy_smoke_outputs_remain_in_customer_projects(
    smoke_report: dict[str, object],
) -> None:
    project_roots = [Path(value).resolve() for value in smoke_report["projectRoots"]]
    plugin_root = Path(smoke_report["pluginRoot"]).resolve()
    for value in smoke_report["workbookPaths"]:
        workbook = Path(value).resolve()
        assert workbook.is_file()
        assert any(workbook.is_relative_to(root) for root in project_roots)
        assert not workbook.is_relative_to(plugin_root)
