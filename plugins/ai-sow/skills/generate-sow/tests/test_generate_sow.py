from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest
from openpyxl.utils import range_boundaries


SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPT = SKILL_ROOT / "scripts/generate_sow.py"
FIXTURE = SKILL_ROOT / "fixtures/project"
TABLES = {
    "EpicTable",
    "FeatureTable",
    "SOWStoryTable",
    "AcceptanceCriterionTable",
    "TaskTable",
    "IntegrationTable",
    "AssumptionRiskTable",
    "AsIsTopicTable",
    "AsIsDetailTable",
}
SPEC = importlib.util.spec_from_file_location("generate_sow_script", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
GENERATOR = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPT.parent))
SPEC.loader.exec_module(GENERATOR)


def test_skill_uses_current_stage_without_leaf_agents() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "当前 Stage Agent 是本 Skill 的唯一用户接口" in skill
    assert "直接运行确定性生成器" in skill
    for forbidden in ("Orchestrator", "Worker", "Validator Agent", "Reviewer"):
        assert forbidden not in skill


def copy_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE, project)
    return project


def run_generator(project: Path) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(project)],
        cwd=PLUGIN_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(completed.stdout)
    return completed, payload


def package_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def table_index(workbook: openpyxl.Workbook) -> dict[str, tuple[object, object]]:
    return {
        name: (worksheet, worksheet.tables[name])
        for worksheet in workbook.worksheets
        for name in worksheet.tables
    }


def test_receipt_only_generation_is_deterministic_and_reuses_identical_package(tmp_path: Path) -> None:
    first_project = copy_project(tmp_path / "first")
    second_project = copy_project(tmp_path / "second")

    first, first_result = run_generator(first_project)
    second, second_result = run_generator(second_project)

    assert first.returncode == second.returncode == 0, (first.stderr, first.stdout, second.stderr, second.stdout)
    assert first_result["outcome"] == second_result["outcome"] == "OK"
    assert first_result["packageId"] == second_result["packageId"]
    first_package = first_project / str(first_result["packagePath"])
    second_package = second_project / str(second_result["packagePath"])
    assert package_tree(first_package) == package_tree(second_package)

    repeated, repeated_result = run_generator(first_project)
    assert repeated.returncode == 0
    assert repeated_result["publication"] == "REUSED"
    assert package_tree(first_package) == package_tree(second_package)


def test_package_fingerprint_binds_every_source_name_path_and_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = copy_project(tmp_path)
    files = GENERATOR.ProjectFiles.open(project_root)
    project = json.loads((project_root / GENERATOR.PROJECT_PATH).read_text(encoding="utf-8"))

    payload = GENERATOR.package_fingerprint_payload(files, project)

    def expected(name: str, package_path: str, source_path: str) -> dict[str, str]:
        return {
            "name": name,
            "path": package_path,
            "sha256": hashlib.sha256((project_root / source_path).read_bytes()).hexdigest(),
        }

    assert payload["projectIdentity"] == {
        "projectId": project["projectId"],
        "pluginVersion": project["pluginVersion"],
        "sowStandardVersion": project["sowStandardVersion"],
    }
    assert payload["project"] == expected("project", GENERATOR.PROJECT_PATH, GENERATOR.PROJECT_PATH)
    assert payload["inputs"] == [
        expected(name, GENERATOR.PACKAGE_DATA_PATHS[name], source_path)
        for name, source_path in GENERATOR.DATA_PATHS.items()
    ]
    assert payload["reviews"] == [
        expected(name, GENERATOR.PACKAGE_REVIEW_PATHS[name], source_path)
        for name, source_path in GENERATOR.REVIEW_PATHS.items()
    ]
    assert payload["validationReceipts"] == [
        expected(name, GENERATOR.PACKAGE_VALIDATION_PATHS[name], source_path)
        for name, source_path in GENERATOR.VALIDATION_PATHS.items()
    ]
    assert payload["template"] == expected(
        "template",
        GENERATOR.PACKAGE_TEMPLATE_PATH,
        GENERATOR.TEMPLATE_PATH,
    )

    original = GENERATOR.package_fingerprint(files, project)
    monkeypatch.setitem(
        GENERATOR.PACKAGE_DATA_PATHS,
        "sourceRequirements",
        "sources/data/analyze-requirement/requirements-v2.json",
    )
    assert GENERATOR.package_fingerprint(files, project) != original


def test_package_fingerprint_reads_staged_owner_artifacts(tmp_path: Path) -> None:
    project_root = copy_project(tmp_path)
    staging_relative = ".ai-sow/.stage-0123456789ab"
    staging_root = project_root / staging_relative
    staging_root.mkdir(parents=True)
    source_path = GENERATOR.DATA_PATHS["delivery"]
    staged_path = staging_root / source_path.removeprefix(".ai-sow/")
    staged_path.parent.mkdir(parents=True)
    staged_payload = b'{"staged":"delivery"}\n'
    staged_path.write_bytes(staged_payload)

    base_files = GENERATOR.ProjectFiles.open(project_root)
    staged_files = GENERATOR.ProjectFiles.open_view(project_root, staging_relative)
    project = json.loads((project_root / GENERATOR.PROJECT_PATH).read_text(encoding="utf-8"))
    base = GENERATOR.package_fingerprint_payload(base_files, project)
    staged = GENERATOR.package_fingerprint_payload(staged_files, project)

    base_entries = {entry["name"]: entry for entry in base["inputs"]}
    staged_entries = {entry["name"]: entry for entry in staged["inputs"]}
    assert staged_entries["delivery"]["sha256"] == hashlib.sha256(staged_payload).hexdigest()
    assert staged_entries["delivery"] != base_entries["delivery"]
    assert staged_entries["estimate"] == base_entries["estimate"]


@pytest.mark.parametrize(
    "receipt",
    [
        "analyze-requirement.json",
        "analyze-as-is.json",
        "generate-design.json",
        "generate-story.json",
        "generate-task.json",
    ],
)
def test_every_owner_receipt_is_required_and_exact(tmp_path: Path, receipt: str) -> None:
    project = copy_project(tmp_path)
    path = project / ".ai-sow/validation" / receipt
    path.unlink()

    completed, result = run_generator(project)

    assert completed.returncode == 2
    assert result["outcome"] == "BLOCKED"
    assert result["diagnostics"][0]["code"] == "UPSTREAM_HANDOFF_MISSING"


def test_asis_inputs_do_not_rebind_prior_sow_logical_evidence(tmp_path: Path) -> None:
    project = copy_project(tmp_path)
    files = GENERATOR.ProjectFiles.open(project)
    data = json.loads(
        (project / GENERATOR.DATA_PATHS["asis"]).read_text(encoding="utf-8")
    )
    expected = GENERATOR.asis_inputs(files, data)
    data["evidence"].append(
        {
            "evidenceId": "evidence-prior-sow-logical-reference",
            "kind": "PRIOR_SOW",
            "reference": "prior-sow:sow-phase-one#commitment-profile-fields",
            "summary": "逻辑引用由 analysisScope.priorSowSnapshots 绑定的文件输入支持。",
            "supportsIds": ["commitment-profile-fields"],
        }
    )

    assert GENERATOR.asis_inputs(files, data) == expected


def test_repository_document_logical_anchor_resolves_through_snapshot(tmp_path: Path) -> None:
    project = copy_project(tmp_path)
    asis_path = project / GENERATOR.DATA_PATHS["asis"]
    asis = json.loads(asis_path.read_text(encoding="utf-8"))
    evidence = next(
        item
        for item in asis["evidence"]
        if item["evidenceId"] == "evidence-operations-assets"
    )
    evidence["reference"] = "customer-portal:docs/operations-and-test-assets.md#baseline"
    asis_path.write_bytes(GENERATOR.canonical_json_bytes(asis))

    for relative in GENERATOR.VALIDATION_PATHS.values():
        receipt_path = project / relative
        validation = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt = validation["compilationReceipt"]
        for section in ("inputs", "outputs", "reviews"):
            for artifact in receipt[section]:
                path = artifact.get("path")
                if isinstance(path, str):
                    artifact["sha256"] = hashlib.sha256((project / path).read_bytes()).hexdigest()
        receipt_path.write_bytes(GENERATOR.canonical_json_bytes(validation))

    completed, result = run_generator(project)

    assert completed.returncode == 0, (completed.stderr, completed.stdout)
    assert result["outcome"] == "OK"


def test_changed_existing_package_fails_closed(tmp_path: Path) -> None:
    project = copy_project(tmp_path)
    completed, result = run_generator(project)
    assert completed.returncode == 0
    package = project / str(result["packagePath"])
    (package / "sow.xlsx").write_bytes(b"different")

    repeated, repeated_result = run_generator(project)

    assert repeated.returncode == 2
    assert repeated_result["diagnostics"][0]["code"] == "PACKAGE_CONTENT_MISMATCH"


def test_unsupported_same_filesystem_publication_has_stable_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = tmp_path / "staging"
    final = tmp_path / "final"
    staging.mkdir()

    def unsupported(source: Path, target: Path) -> None:
        raise OSError(18, "cross-device")

    monkeypatch.setattr(GENERATOR.os, "replace", unsupported)
    with pytest.raises(GENERATOR.GenerationError) as captured:
        GENERATOR.publish_staging(staging, final)
    assert captured.value.code == "PACKAGE_PUBLICATION_UNSUPPORTED"
    assert staging.is_dir()
    assert not final.exists()


def test_workbook_projects_six_jsons_and_preserves_dynamic_tables_and_formulas(tmp_path: Path) -> None:
    project = copy_project(tmp_path)
    completed, result = run_generator(project)
    assert completed.returncode == 0, (completed.stderr, completed.stdout)
    package = project / str(result["packagePath"])
    workbook_path = package / "sow.xlsx"

    workbook = openpyxl.load_workbook(workbook_path, data_only=False, read_only=False)
    try:
        index = table_index(workbook)
        assert TABLES.issubset(index)
        requirements = json.loads((project / ".ai-sow/data/analyze-requirement/requirements.json").read_text())
        technical = json.loads((project / ".ai-sow/data/generate-design/requirements.json").read_text())
        delivery = json.loads((project / ".ai-sow/data/generate-story/delivery.json").read_text())
        estimate = json.loads((project / ".ai-sow/data/generate-task/estimate.json").read_text())
        expected_counts = {
            "EpicTable": len(requirements["epics"]) + len(technical["epics"]),
            "FeatureTable": len(requirements["features"]) + len(technical["features"]),
            "SOWStoryTable": len(delivery["stories"]),
            "AcceptanceCriterionTable": len(delivery["acceptanceCriteria"]),
            "TaskTable": len(estimate["tasks"]),
        }
        for name, expected in expected_counts.items():
            worksheet, table = index[name]
            min_col, min_row, max_col, max_row = range_boundaries(table.ref)
            assert max_row - min_row == expected
            formulas = [
                worksheet.cell(row, column).value
                for row in range(min_row + 1, max_row + 1)
                for column in range(min_col, max_col + 1)
                if worksheet.cell(row, column).data_type == "f"
            ]
            if name in {"SOWStoryTable", "TaskTable"}:
                assert formulas
        assert workbook.calculation.calcMode == "auto"
        projected_hashes = {
            workbook["00-使用说明"].cell(row, 1).value: workbook["00-使用说明"].cell(row, 2).value
            for row in range(44, 50)
        }
        assert projected_hashes == {
            key: hashlib.sha256((project / path).read_bytes()).hexdigest()
            for key, path in {
                "sourceRequirements": ".ai-sow/data/analyze-requirement/requirements.json",
                "asis": ".ai-sow/data/analyze-as-is/asis.json",
                "design": ".ai-sow/data/generate-design/design.json",
                "derivedRequirements": ".ai-sow/data/generate-design/requirements.json",
                "delivery": ".ai-sow/data/generate-story/delivery.json",
                "estimate": ".ai-sow/data/generate-task/estimate.json",
            }.items()
        }
    finally:
        workbook.close()

    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["inputs"]) == {
        "sourceRequirements",
        "asis",
        "design",
        "derivedRequirements",
        "delivery",
        "estimate",
    }
    assert set(manifest["reviews"]) == {
        "analyzeRequirement",
        "analyzeAsIs",
        "generateDesign",
        "generateStory",
        "generateTask",
    }
    assert set(manifest["validationReceipts"]) == set(manifest["reviews"])
    schema = json.loads((SKILL_ROOT / "contracts/manifest.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"] == "urn:ai-sow:generate-sow:manifest:0.2"


def test_beta1_project_is_not_implicitly_migrated(tmp_path: Path) -> None:
    project = copy_project(tmp_path)
    metadata = project / ".ai-sow/project.json"
    value = json.loads(metadata.read_text(encoding="utf-8"))
    value["pluginVersion"] = "0.1.0-beta.1"
    metadata.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    completed, result = run_generator(project)

    assert completed.returncode == 2
    assert result["diagnostics"][0]["code"] == "PROJECT_SCHEMA_INVALID"


def test_generator_has_no_owner_validator_or_legacy_gate_dependency() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "runtime.review_gates" not in source
    assert "skills.analyze" not in source
    assert "skills.generate" not in source
    for forbidden in ("CARRY_FORWARD", "validate_design_gates", "shutil.copytree", "PosixOutputAnchor"):
        assert forbidden not in source
