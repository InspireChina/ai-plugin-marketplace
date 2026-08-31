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
from openpyxl.worksheet.formula import ArrayFormula


SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPT = SKILL_ROOT / "scripts/generate_sow.py"
FIXTURE = SKILL_ROOT / "fixtures/project"
REFERENCE_WORKBOOK = PLUGIN_ROOT / "docs/reference/SOW估算与生成示例_v1.3.xlsx"
TABLES = {
    "EpicTable",
    "FeatureTable",
    "SOWStoryTable",
    "AcceptanceCriterionTable",
    "TaskTable",
    "IntegrationTable",
    "AssumptionRiskTable",
    "AsIsDetailTable",
}
SPEC = importlib.util.spec_from_file_location("generate_sow_script", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
GENERATOR = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPT.parent))
SPEC.loader.exec_module(GENERATOR)
WORKBOOK = sys.modules["workbook"]


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
        text=True, encoding="utf-8",
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


def package_tree_sha256(root: Path) -> str:
    entries = [
        {"path": path, "sha256": digest}
        for path, digest in package_tree(root).items()
    ]
    return hashlib.sha256(GENERATOR.canonical_json_bytes(entries)).hexdigest()


def table_index(workbook: openpyxl.Workbook) -> dict[str, tuple[object, object]]:
    return {
        name: (worksheet, worksheet.tables[name])
        for worksheet in workbook.worksheets
        for name in worksheet.tables
    }


def test_long_text_fixture_preserves_wrapping_and_expands_visible_row_height(
    tmp_path: Path,
) -> None:
    template = FIXTURE / ".ai-sow/templates/sow-template.xlsx"
    workbook = openpyxl.load_workbook(template, data_only=False)
    description = "项目开工时可依赖现有能力，但生产切换仍需逐项验证。" * 24

    WORKBOOK.fill_table(
        workbook,
        "AsIsDetailTable",
        [
            {
                "主题名称": "应用与组件",
                "现状条目名称": "长文本布局认证",
                "现状描述": description,
                "起点可用性": "当前已存在",
            }
        ],
    )
    output = tmp_path / "long-text-certification.xlsx"
    workbook.save(output)

    reloaded = openpyxl.load_workbook(output, data_only=False)
    worksheet, table = table_index(reloaded)["AsIsDetailTable"]
    min_col, min_row, max_col, _ = range_boundaries(table.ref)
    headers = [worksheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
    description_column = min_col + headers.index("现状描述")
    data_row = min_row + 1

    assert worksheet.cell(data_row, description_column).value == description
    assert worksheet.cell(data_row, description_column).alignment.wrap_text is True
    assert worksheet.row_dimensions[data_row].height is not None
    assert worksheet.row_dimensions[data_row].height > 100


def test_as_is_projection_distinguishes_current_and_expected_start_availability() -> None:
    rows = WORKBOOK.build_asis_detail_rows(
        {
            "items": [
                {
                    "asIsItemId": "ASI-001",
                    "summary": "当前已有客户查询接口",
                }
            ],
            "commitments": [
                {
                    "commitmentId": "COM-001",
                    "summary": "统一认证改造完成",
                }
            ],
            "effectiveStartItems": [
                {
                    "topic": "APPLICATION",
                    "name": "客户查询服务",
                    "summary": "项目开工时可依赖客户查询接口，但不含客户档案修改能力。",
                    "sourceItemIds": ["ASI-001"],
                    "commitmentIds": [],
                },
                {
                    "topic": "SECURITY_COMPLIANCE",
                    "name": "统一认证能力",
                    "summary": "项目开工时预计可依赖统一认证能力，但不含生产租户授权。",
                    "sourceItemIds": [],
                    "commitmentIds": ["COM-001"],
                },
            ],
        }
    )

    assert rows == [
        {
            "主题名称": "应用与组件",
            "现状条目名称": "客户查询服务",
            "现状描述": "项目开工时可依赖客户查询接口，但不含客户档案修改能力。",
            "起点可用性": "当前已存在",
        },
        {
            "主题名称": "安全与合规",
            "现状条目名称": "统一认证能力",
            "现状描述": "项目开工时预计可依赖统一认证能力，但不含生产租户授权。",
            "起点可用性": "预计开工前具备",
        },
    ]


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
    assert (first_package / "sow.xlsx").read_bytes() == REFERENCE_WORKBOOK.read_bytes()
    assert first_result["generatorContract"] == "receipt-only-v2"
    assert first_result["workbookSha256"] == hashlib.sha256(
        (first_package / "sow.xlsx").read_bytes()
    ).hexdigest()
    assert first_result["manifestSha256"] == hashlib.sha256(
        (first_package / "manifest.json").read_bytes()
    ).hexdigest()
    assert first_result["packageTreeSha256"] == package_tree_sha256(first_package)
    assert first_result["fileCount"] == len(package_tree(first_package))
    manifest = json.loads((first_package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generatorContract"] == "receipt-only-v2"

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
    assert payload["generatorContract"] == "receipt-only-v2"
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
        assert len(workbook.sheetnames) == 12
        assert sum(len(worksheet.tables) for worksheet in workbook.worksheets) == 11
        assert sum(
            cell.data_type == "f"
            for worksheet in workbook.worksheets
            for row in worksheet.iter_rows()
            for cell in row
        ) == 578
        assert TABLES.issubset(index)
        requirements = json.loads((project / ".ai-sow/data/analyze-requirement/requirements.json").read_text(encoding="utf-8"))
        technical = json.loads((project / ".ai-sow/data/generate-design/requirements.json").read_text(encoding="utf-8"))
        asis = json.loads((project / ".ai-sow/data/analyze-as-is/asis.json").read_text(encoding="utf-8"))
        delivery = json.loads((project / ".ai-sow/data/generate-story/delivery.json").read_text(encoding="utf-8"))
        estimate = json.loads((project / ".ai-sow/data/generate-task/estimate.json").read_text(encoding="utf-8"))
        expected_counts = {
            "EpicTable": len(requirements["epics"]) + len(technical["epics"]),
            "FeatureTable": len(requirements["features"]) + len(technical["features"]),
            "SOWStoryTable": len(delivery["stories"]),
            "AcceptanceCriterionTable": len(delivery["acceptanceCriteria"]),
            "TaskTable": len(estimate["tasks"]),
            "AsIsDetailTable": len(asis["effectiveStartItems"]),
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

        story_sheet, story_table = index["SOWStoryTable"]
        min_col, min_row, max_col, max_row = range_boundaries(story_table.ref)
        story_headers = [
            str(story_sheet.cell(min_row, column).value)
            for column in range(min_col, max_col + 1)
        ]
        story_columns = {column.name: column for column in story_table.tableColumns}
        for header in ("验收条件", "任务明细"):
            column = min_col + story_headers.index(header)
            calculated = story_columns[header].calculatedColumnFormula
            assert calculated is not None
            assert calculated.array is True
            assert "_xlfn._xlws." not in calculated.text
            for row in range(min_row + 1, max_row + 1):
                cell = story_sheet.cell(row, column)
                formula = cell.value
                assert isinstance(formula, ArrayFormula)
                assert formula.ref == cell.coordinate
                assert isinstance(formula.text, str)
                assert f"C{row}" in formula.text
                assert '"• "&' in formula.text
                assert "_xlfn._xlws." not in formula.text

        def rows(table_name: str) -> list[dict[str, object]]:
            worksheet, table = index[table_name]
            min_col, min_row, max_col, max_row = range_boundaries(table.ref)
            headers = [worksheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
            return [
                {
                    str(header): worksheet.cell(row, column).value
                    for header, column in zip(headers, range(min_col, max_col + 1), strict=True)
                }
                for row in range(min_row + 1, max_row + 1)
            ]

        business_headers = {
            header
            for table_name in TABLES
            for header in rows(table_name)[0]
        }
        assert not {header for header in business_headers if header.endswith("ID")}
        task_rows = rows("TaskTable")
        effective_start_names = {
            item["effectiveStartItemId"]: item["name"]
            for item in asis["effectiveStartItems"]
        }
        expected_system_names = {
            effective_start_names[task["matchedEffectiveStartItemId"]]
            for task in estimate["tasks"]
            if task.get("matchedEffectiveStartItemId")
        }
        assert {row["关联现状条目"] for row in task_rows if row["关联现状条目"]} == expected_system_names
        assert all(not str(row["基础单元名称"]).startswith("BU-") for row in task_rows)

        task_names = {task["taskId"]: task["name"] for task in estimate["tasks"]}
        integration_rows = rows("IntegrationTable")
        assert {row["集成任务名称"] for row in integration_rows} == {
            task_names[next(task["taskId"] for task in estimate["tasks"] if task.get("integrationId") == integration["integrationId"])]
            for integration in delivery["integrations"]
        }
        assert {row["方向"] for row in integration_rows}.issubset({"入站", "出站"})
        assert {row["责任边界"] for row in integration_rows}.issubset({"内部", "外部"})
        assert {row["需求类型"] for row in rows("EpicTable")}.issubset({"业务", "技术"})
        feature_rows = rows("FeatureTable")
        assert {row["来源类型"] for row in feature_rows}.issubset({"来源输入", "设计派生"})
        projected_features = {row["子需求名称"]: row for row in feature_rows}
        decision_names = {
            decision["designDecisionId"]: decision["name"]
            for decision in json.loads(
                (project / ".ai-sow/data/generate-design/design.json").read_text(encoding="utf-8")
            )["decisions"]
        }
        for feature in technical["features"]:
            rationale = str(projected_features[feature["name"]]["推断理由"])
            for decision_id in feature["source"].get("designDecisionIds", []):
                assert decision_id not in rationale
                assert decision_names[decision_id] in rationale
        asis_detail_rows = rows("AsIsDetailTable")
        assert list(asis_detail_rows[0]) == [
            "主题名称", "现状条目名称", "现状描述", "起点可用性"
        ]
        assert {row["现状条目名称"] for row in asis_detail_rows} == {
            entry["name"] for entry in asis["effectiveStartItems"]
        }
        assert {row["起点可用性"] for row in asis_detail_rows} == {"当前已存在"}
        first_start = asis["effectiveStartItems"][0]
        first_row = next(
            row for row in asis_detail_rows
            if row["现状条目名称"] == first_start["name"]
        )
        assert first_row["现状描述"] == first_start["summary"]
        assert list(rows("AssumptionRiskTable")[0]) == [
            "假设/风险名称", "类型", "触发条件", "责任边界", "状态", "处理方式"
        ]
        asis_sheet = workbook["90-系统现状"]
        assert asis_sheet.protection.sheet is False
        assert asis_sheet["A2"].protection.locked is False
        assert asis_sheet["A2"].fill.fgColor.rgb[-6:] == "FFFFFF"
        for sheet_name in WORKBOOK.PROTECTED_SHEETS:
            protection = workbook[sheet_name].protection
            assert protection.sheet is True
            assert protection.formatColumns is False
            assert protection.formatRows is False
            assert protection.autoFilter is False
            assert protection.sort is False
            assert protection.formatCells is True
        _, table = index["AsIsDetailTable"]
        min_col, min_row, max_col, max_row = range_boundaries(table.ref)
        headers = [
            asis_sheet.cell(min_row, column).value
            for column in range(min_col, max_col + 1)
        ]
        for row in range(min_row + 1, max_row + 1):
            for offset, header in enumerate(headers):
                cell = asis_sheet.cell(row, min_col + offset)
                assert cell.protection.locked is False
                expected_fill = "FFF2CC" if header in {"主题名称", "起点可用性"} else "FFFFFF"
                assert cell.fill.fgColor.rgb[-6:] == expected_fill
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
    assert manifest["generatorContract"] == "receipt-only-v2"
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
    assert manifest["repositories"] == [
        {
            "repoId": item["repoId"],
            "name": item["name"],
            "setupRevision": item["revision"],
        }
        for item in asis["analysisScope"]["repositorySnapshots"]
    ]
    assert manifest["priorSows"] == [
        {
            "priorSowId": item["priorSowId"],
            "name": item["name"],
            "sha256": item["sha256"],
        }
        for item in asis["analysisScope"]["priorSowSnapshots"]
    ]
    schema = json.loads((SKILL_ROOT / "contracts/manifest.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"] == "urn:ai-sow:generate-sow:manifest:0.3"


def test_unsupported_project_version_is_rejected(tmp_path: Path) -> None:
    project = copy_project(tmp_path)
    metadata = project / ".ai-sow/project.json"
    value = json.loads(metadata.read_text(encoding="utf-8"))
    value["pluginVersion"] = "9.9.9"
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
