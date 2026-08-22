from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import openpyxl
import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "setup.py"
TEMPLATE = Path(__file__).parents[1] / "assets" / "sow-template.xlsx"
TEMPLATE_COPIES = (
    TEMPLATE,
    Path(__file__).parents[3] / "skills/generate-task/fixtures/sow-template.xlsx",
    Path(__file__).parents[3]
    / "skills/generate-sow/fixtures/project/.ai-sow/templates/sow-template.xlsx",
)
TABLE_FORMULA_HEADERS = {
    "SOWStoryTable": {"需求", "子需求", "验收条件", "任务明细", "人天", "关联假设ID", "假设状态"},
    "TaskTable": {"任务族", "基础人天", "复杂度倍率", "人天小计"},
    "IntegrationTable": {"集成Task ID", "工作模式", "复杂度", "支持单价", "SIT人天"},
    "AssumptionRiskTable": {"关联 Story 人天"},
}
EXPECTED_TASK_FAMILIES = {
    "前端",
    "后端",
    "数据与报表",
    "系统集成",
    "质量验证",
    "共性技术能力",
    "工程平台",
    "数据迁移",
    "发布与切换",
    "问题处理",
    "架构设计",
    "分析与调研",
    "交付与移交",
}
EXPECTED_TASK_HEADERS = [
    "Task ID",
    "Story ID",
    "任务说明",
    "基础单元ID",
    "任务族",
    "工作模式",
    "工作模式理由",
    "复杂度",
    "复杂度理由",
    "Integration ID",
    "系统现状匹配",
    "判断依据与备注",
    "基础人天",
    "复杂度倍率",
    "人天小计",
]
EXPECTED_CATALOG_HEADERS = [
    "任务族ID",
    "任务族名称",
    "基础单元ID",
    "基础单元名称",
    "计数口径",
    "包含内容",
    "不包含内容",
    "新建M档人天",
    "调整M档人天",
    "接入复用M档人天",
    "S标准",
    "M标准",
    "L标准",
    "X/拆分条件",
]
BARE_TEXTJOIN = re.compile(rb"(?<!_xlfn\.)(?<!_xludf\.)TEXTJOIN\(")
DIRECT_CROSS_SHEET_VALIDATION = re.compile(r"^'?[^']+'?!\$?[A-Z]+\$")


def workbook_tables(workbook: openpyxl.Workbook) -> dict[str, object]:
    return {
        name: worksheet.tables[name]
        for worksheet in workbook.worksheets
        for name in worksheet.tables
    }


def table_rows(
    workbook: openpyxl.Workbook,
    table_name: str,
) -> list[dict[str, object]]:
    table = workbook_tables(workbook)[table_name]
    worksheet = next(
        sheet for sheet in workbook.worksheets if table_name in sheet.tables
    )
    min_column, min_row, max_column, max_row = openpyxl.utils.range_boundaries(
        table.ref
    )
    headers = [
        worksheet.cell(min_row, column).value
        for column in range(min_column, max_column + 1)
    ]
    return [
        dict(
            zip(
                headers,
                (
                    worksheet.cell(row, column).value
                    for column in range(min_column, max_column + 1)
                ),
                strict=True,
            )
        )
        for row in range(min_row + 1, max_row + 1)
    ]


def excel_compatibility_errors(workbook_path: Path) -> list[str]:
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    errors: list[str] = []
    try:
        for worksheet in workbook.worksheets:
            for table in worksheet.tables.values():
                min_column, min_row, max_column, _ = openpyxl.utils.range_boundaries(
                    table.ref
                )
                visible_headers = [
                    worksheet.cell(min_row, column).value
                    for column in range(min_column, max_column + 1)
                ]
                metadata_headers = [column.name for column in table.tableColumns]
                if visible_headers != metadata_headers:
                    errors.append(f"{worksheet.title}:{table.name}:table headers")

            for validation in worksheet.data_validations.dataValidation:
                formula = str(validation.formula1 or "").lstrip("=")
                if DIRECT_CROSS_SHEET_VALIDATION.match(formula):
                    errors.append(
                        f"{worksheet.title}:{validation.sqref}:cross-sheet validation"
                    )

            merged_ranges = list(worksheet.merged_cells.ranges)
            for index, left in enumerate(merged_ranges):
                for right in merged_ranges[index + 1 :]:
                    if (
                        left.min_col <= right.max_col
                        and right.min_col <= left.max_col
                        and left.min_row <= right.max_row
                        and right.min_row <= left.max_row
                    ):
                        errors.append(
                            f"{worksheet.title}:{left}:{right}:overlapping merges"
                        )
    finally:
        workbook.close()
    return errors


def load_setup_module():
    spec = importlib.util.spec_from_file_location("ai_sow_setup_race_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bare_textjoin_formula_parts(workbook_path: Path) -> list[str]:
    with ZipFile(workbook_path) as archive:
        return [
            name
            for name in archive.namelist()
            if name.startswith(("xl/worksheets/", "xl/tables/"))
            and name.endswith(".xml")
            and BARE_TEXTJOIN.search(archive.read(name))
        ]


def test_bundled_template_copies_have_dynamic_as_is_tables() -> None:
    digests = {hashlib.sha256(path.read_bytes()).hexdigest() for path in TEMPLATE_COPIES}
    assert len(digests) == 1

    for template in TEMPLATE_COPIES:
        workbook = openpyxl.load_workbook(template, data_only=False)
        try:
            tables = {
                name: worksheet.tables[name]
                for worksheet in workbook.worksheets
                for name in worksheet.tables
            }
            assert tables["AsIsTopicTable"].ref == "A4:G13"
            assert [
                column.name for column in tables["AsIsTopicTable"].tableColumns
            ] == [
                "主题",
                "评估状态",
                "结论",
                "当前事实数",
                "承诺数",
                "有效起点数",
                "未决数",
            ]
            assert tables["AsIsDetailTable"].ref == "A17:I18"
            assert [
                column.name for column in tables["AsIsDetailTable"].tableColumns
            ] == [
                "主题",
                "记录类型",
                "记录 ID",
                "分类/状态",
                "名称",
                "摘要/理由",
                "关系/流向",
                "关联 ID",
                "证据引用",
            ]
            assert "系统现状匹配" in [
                column.name for column in tables["TaskTable"].tableColumns
            ]
            assert [
                workbook["00-使用说明"].cell(32, column).value
                for column in range(1, 8)
            ] == [
                "90-系统现状",
                "动态 As-Is 投影",
                "Topic / 当前事实 / 承诺 / 有效起点 / Coverage / Uncertainty / Evidence",
                "无",
                "九主题完整、稳定 ID 与证据引用可追溯",
                "project.json / asis.json",
                "设计 / Story / Task / 审计",
            ]
            assert not workbook["90-系统现状"].data_validations.dataValidation
        finally:
            workbook.close()


def test_bundled_template_copies_open_without_excel_repairs() -> None:
    for template in TEMPLATE_COPIES:
        assert excel_compatibility_errors(template) == []


def test_bundled_template_implements_task_estimation_catalog() -> None:
    workbook = openpyxl.load_workbook(TEMPLATE, data_only=False)
    try:
        tables = workbook_tables(workbook)
        assert [
            column.name for column in tables["SOWStoryTable"].tableColumns
        ] == [
            "Story ID",
            "Story名称",
            "Feature ID",
            "UAT分母",
            "需求",
            "子需求",
            "验收条件",
            "任务明细",
            "人天",
            "关联假设ID",
            "假设状态",
        ]
        assert [
            column.name for column in tables["TaskTable"].tableColumns
        ] == EXPECTED_TASK_HEADERS
        assert [
            column.name for column in tables["BaseUnitCatalogTable"].tableColumns
        ] == EXPECTED_CATALOG_HEADERS
        assert "BaseEffortTable" not in tables
        assert "WorkModeTable" not in tables
        assert "ComplexityRuleTable" not in tables
        assert "93-复杂度规则" not in workbook.sheetnames

        catalog = table_rows(workbook, "BaseUnitCatalogTable")
        assert len(catalog) == 37
        assert len({row["基础单元ID"] for row in catalog}) == 37
        assert {row["任务族名称"] for row in catalog} == EXPECTED_TASK_FAMILIES
        assert all(
            row[header]
            for row in catalog
            for header in (
                "任务族ID",
                "基础单元ID",
                "基础单元名称",
                "计数口径",
                "包含内容",
                "不包含内容",
                "S标准",
                "M标准",
                "L标准",
                "X/拆分条件",
            )
        )

        mode_columns = {
            "新建": "新建M档人天",
            "调整": "调整M档人天",
            "接入复用": "接入复用M档人天",
        }
        efforts_by_name_mode = {}
        for row in catalog:
            configured_modes = 0
            for mode, column in mode_columns.items():
                effort = row[column]
                assert effort == "❌" or (
                    isinstance(effort, (int, float))
                    and not isinstance(effort, bool)
                    and effort > 0
                )
                if effort != "❌":
                    configured_modes += 1
                    efforts_by_name_mode[(row["基础单元名称"], mode)] = effort
            assert configured_modes >= 1
        assert len(efforts_by_name_mode) == 86
        assert efforts_by_name_mode[("内部系统对接", "新建")] == 2.0
        assert efforts_by_name_mode[("内部系统对接", "调整")] == 1.5
        assert efforts_by_name_mode[("内部系统对接", "接入复用")] == 1.0
        assert efforts_by_name_mode[("外部系统对接", "新建")] == 3.0
        assert efforts_by_name_mode[("外部系统对接", "调整")] == 2.0
        assert efforts_by_name_mode[("外部系统对接", "接入复用")] == 2.0
        assert efforts_by_name_mode[("开发工具与工程规范", "新建")] == 1.5
        assert efforts_by_name_mode[("开发工具与工程规范", "调整")] == 1.0
        assert efforts_by_name_mode[("开发工具与工程规范", "接入复用")] == 0.5
        assert efforts_by_name_mode[("用户培训与使用材料", "新建")] == 1.5
        assert efforts_by_name_mode[("用户培训与使用材料", "调整")] == 1.0

        parameters = {
            row["参数代码"]: row["值"]
            for row in table_rows(workbook, "ProjectParameterTable")
        }
        assert parameters["K_COMPLEXITY_S"] == 0.6
        assert parameters["K_COMPLEXITY_M"] == 1.0
        assert parameters["K_COMPLEXITY_L"] == 1.5

        task_formulas = {
            header: workbook["05-任务明细"].cell(5, column).value
            for column, header in enumerate(EXPECTED_TASK_HEADERS, start=1)
            if header in TABLE_FORMULA_HEADERS["TaskTable"] | {"任务族"}
        }
        assert all(
            isinstance(formula, str) and formula.startswith("=")
            for formula in task_formulas.values()
        )
        assert all("数量" not in formula for formula in task_formulas.values())
        assert "BaseUnitCatalogTable" in task_formulas["基础人天"]
        assert "ProjectParameterTable" in task_formulas["复杂度倍率"]
        assert all(
            "BaseEffortTable" not in formula
            and "ComplexityRuleTable" not in formula
            for formula in task_formulas.values()
        )
    finally:
        workbook.close()


def test_bundled_template_copies_serialize_textjoin_for_excel_recalculation() -> None:
    for template in TEMPLATE_COPIES:
        assert bare_textjoin_formula_parts(template) == []


def run_setup(
    project_root: Path,
    *extra: str,
    no_site: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if no_site:
        command.append("-S")
    command.extend(
        [
            str(SCRIPT),
            "--project-root",
            str(project_root),
            "--project-id",
            "bookstore-modernization",
            "--name",
            "在线书店 2.0",
            *extra,
        ]
    )
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        cwd=project_root,
        env=os.environ | (env or {}),
    )


def test_setup_creates_minimal_project_shell(tmp_path: Path) -> None:
    result = run_setup(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "OK"
    project_path = tmp_path / ".ai-sow/project.json"
    assert json.loads(project_path.read_text()) == {
        "projectId": "bookstore-modernization",
        "name": "在线书店 2.0",
        "pluginVersion": "0.1.0-beta.1",
        "sowStandardVersion": "1.3",
    }
    assert (tmp_path / ".ai-sow/templates/sow-template.xlsx").is_file()
    for relative in (
        "work",
        "data",
        "reviews",
        "validation",
        "outputs",
        "runtime/setup",
    ):
        assert (tmp_path / ".ai-sow" / relative).is_dir()


def test_setup_refuses_to_overwrite_existing_project(tmp_path: Path) -> None:
    assert run_setup(tmp_path).returncode == 0
    project_path = tmp_path / ".ai-sow/project.json"
    original = project_path.read_bytes()

    result = run_setup(tmp_path)

    assert result.returncode == 2
    assert json.loads(result.stdout)["outcome"] == "BLOCKED"
    assert project_path.read_bytes() == original


def test_setup_reports_missing_python_dependencies(tmp_path: Path) -> None:
    result = run_setup(tmp_path, no_site=True)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "NEEDS_INPUT"
    assert "uv sync --locked" in payload["nextStep"]
    assert not (tmp_path / ".ai-sow").exists()


@pytest.mark.parametrize(
    "extra",
    [
        ("--project-id", "different-project"),
        ("--name", "Different Project"),
    ],
)
def test_repair_blocks_identity_mismatch(
    tmp_path: Path,
    extra: tuple[str, ...],
) -> None:
    assert run_setup(tmp_path).returncode == 0
    original_project = (tmp_path / ".ai-sow/project.json").read_bytes()

    result = run_setup(tmp_path, "--repair", *extra)

    assert result.returncode == 2
    assert json.loads(result.stdout)["outcome"] == "BLOCKED"
    assert "does not match registered project" in json.loads(result.stdout)["summary"]
    assert (tmp_path / ".ai-sow/project.json").read_bytes() == original_project


@pytest.mark.parametrize("legacy_option", ["--mode", "--repo", "--prior-sow"])
def test_setup_rejects_removed_technical_intake_options(
    tmp_path: Path,
    legacy_option: str,
) -> None:
    result = run_setup(tmp_path, legacy_option, "legacy-value")

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_repair_reuses_only_persisted_identity_fields(tmp_path: Path) -> None:
    assert run_setup(tmp_path).returncode == 0
    project_path = tmp_path / ".ai-sow/project.json"
    original = project_path.read_bytes()
    (tmp_path / ".ai-sow/templates/sow-template.xlsx").unlink()

    result = run_setup(tmp_path, "--repair")

    assert result.returncode == 0, result.stdout
    assert project_path.read_bytes() == original
    assert (tmp_path / ".ai-sow/templates/sow-template.xlsx").read_bytes() == TEMPLATE.read_bytes()


def test_repair_rejects_project_relative_path_outside_four_field_contract(
    tmp_path: Path,
) -> None:
    assert run_setup(tmp_path).returncode == 0
    project_path = tmp_path / ".ai-sow/project.json"
    project = json.loads(project_path.read_text())
    project["projectRelativePath"] = ".ai-sow"
    project_path.write_text(json.dumps(project))

    result = run_setup(tmp_path, "--repair")

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    assert "registered project manifest is invalid" in payload["summary"]


def test_fresh_setup_rejects_symlink_in_write_chain(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    ai_sow = tmp_path / ".ai-sow"
    ai_sow.mkdir()
    (ai_sow / "templates").symlink_to(outside, target_is_directory=True)

    result = run_setup(tmp_path)

    assert result.returncode == 2
    assert json.loads(result.stdout)["outcome"] == "BLOCKED"
    assert "symlink" in json.loads(result.stdout)["summary"]
    assert not (ai_sow / "project.json").exists()
    assert list(outside.iterdir()) == []
    assert not list(ai_sow.glob(".setup-staging-*"))


def test_portable_setup_publication_writes_template_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_setup_module()
    project = {
        "projectId": "customer-portal",
        "name": "Customer Portal",
        "pluginVersion": "0.1.0-beta.1",
        "sowStandardVersion": "1.3",
    }
    monkeypatch.delattr(module.os, "O_DIRECTORY")

    template_path = module.install_project_shell(
        tmp_path,
        project,
        TEMPLATE.read_bytes(),
        publish_manifest=True,
    )

    assert template_path.read_bytes() == TEMPLATE.read_bytes()
    assert json.loads((tmp_path / ".ai-sow/project.json").read_text()) == project


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd race regression")
def test_setup_blocks_ai_sow_swap_after_path_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches unanchored writes after .ai-sow passed the symlink checks."""
    module = load_setup_module()
    project_root = tmp_path / "project"
    project_root.mkdir()
    ai_sow = project_root / ".ai-sow"
    ai_sow.mkdir()
    displaced = project_root / ".ai-sow-displaced"
    outside = tmp_path / "outside-ai-sow"
    outside.mkdir()
    original_reject = module.reject_symlink_chain
    swapped = False

    def reject_then_swap(root: Path, target: Path) -> None:
        nonlocal swapped
        original_reject(root, target)
        if not swapped and target == ai_sow / "runtime" / "setup":
            ai_sow.rename(displaced)
            ai_sow.symlink_to(outside, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(module, "reject_symlink_chain", reject_then_swap)

    with pytest.raises((module.BlockedError, OSError)):
        module.install_project_shell(
            project_root,
            {
                "projectId": "customer-portal",
                "name": "Customer Portal",
                "pluginVersion": "0.1.0-beta.1",
                "sowStandardVersion": "1.3",
            },
            TEMPLATE.read_bytes(),
            publish_manifest=True,
        )

    assert swapped is True
    assert list(outside.rglob("*")) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd race regression")
def test_setup_blocks_templates_swap_after_path_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches an unanchored template publish through a raced subdirectory."""
    module = load_setup_module()
    project_root = tmp_path / "project"
    templates = project_root / ".ai-sow" / "templates"
    templates.mkdir(parents=True)
    displaced = project_root / ".ai-sow" / "templates-displaced"
    outside = tmp_path / "outside-templates"
    outside.mkdir()
    original_reject = module.reject_symlink_chain
    swapped = False

    def reject_then_swap(root: Path, target: Path) -> None:
        nonlocal swapped
        original_reject(root, target)
        if not swapped and target == templates:
            templates.rename(displaced)
            templates.symlink_to(outside, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(module, "reject_symlink_chain", reject_then_swap)

    with pytest.raises((module.BlockedError, OSError)):
        module.install_project_shell(
            project_root,
            {
                "projectId": "customer-portal",
                "name": "Customer Portal",
                "pluginVersion": "0.1.0-beta.1",
                "sowStandardVersion": "1.3",
            },
            TEMPLATE.read_bytes(),
            publish_manifest=True,
        )

    assert swapped is True
    assert list(outside.rglob("*")) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd race regression")
def test_setup_blocks_managed_subdirectory_swap_after_fd_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches success after an anchored write lands in a displaced subdirectory."""
    module = load_setup_module()
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside-templates"
    outside.mkdir()
    displaced = tmp_path / "displaced-templates"
    original_publish = module.publish_file_at
    swapped = False

    def publish_after_swap(
        parent_fd: int,
        name: str,
        payload: bytes,
        *,
        label: str,
    ) -> bool:
        nonlocal swapped
        if not swapped and label == "setup-owned template":
            target = project_root / ".ai-sow" / "templates"
            target.rename(displaced)
            target.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_publish(parent_fd, name, payload, label=label)

    monkeypatch.setattr(module, "publish_file_at", publish_after_swap)
    with pytest.raises(module.BlockedError):
        module.install_project_shell(
            project_root,
            {
                "projectId": "customer-portal",
                "name": "Customer Portal",
                "pluginVersion": "0.1.0-beta.1",
                "sowStandardVersion": "1.3",
            },
            TEMPLATE.read_bytes(),
            publish_manifest=True,
        )

    assert swapped is True
    assert list(outside.rglob("*")) == []
    assert not (project_root / ".ai-sow/project.json").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd race regression")
def test_setup_removes_new_manifest_when_subdirectory_changes_during_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a success manifest that points to a displaced template."""
    module = load_setup_module()
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside-template-after-manifest"
    outside.mkdir()
    displaced = tmp_path / "displaced-template-after-manifest"
    original_publish = module.publish_file_at
    swapped = False

    def publish_then_swap(
        parent_fd: int,
        name: str,
        payload: bytes,
        *,
        label: str,
    ) -> bool:
        nonlocal swapped
        published = original_publish(parent_fd, name, payload, label=label)
        if not swapped and label == "project manifest":
            templates = project_root / ".ai-sow/templates"
            templates.rename(displaced)
            templates.symlink_to(outside, target_is_directory=True)
            swapped = True
        return published

    monkeypatch.setattr(module, "publish_file_at", publish_then_swap)

    with pytest.raises(module.BlockedError):
        module.install_project_shell(
            project_root,
            {
                "projectId": "customer-portal",
                "name": "Customer Portal",
                "pluginVersion": "0.1.0-beta.1",
                "sowStandardVersion": "1.3",
            },
            TEMPLATE.read_bytes(),
            publish_manifest=True,
        )

    assert swapped is True
    assert list(outside.rglob("*")) == []
    assert not (project_root / ".ai-sow/project.json").exists()


def test_fresh_setup_blocks_conflicting_template_target(tmp_path: Path) -> None:
    template = tmp_path / ".ai-sow/templates/sow-template.xlsx"
    template.parent.mkdir(parents=True)
    template.write_bytes(b"not the bundled template\n")

    result = run_setup(tmp_path)

    assert result.returncode == 2
    assert json.loads(result.stdout)["outcome"] == "BLOCKED"
    assert template.read_bytes() == b"not the bundled template\n"
    assert not (tmp_path / ".ai-sow/project.json").exists()
    assert not list((tmp_path / ".ai-sow").glob(".setup-staging-*"))


def test_bundled_template_contains_formula_prototypes() -> None:
    workbook = openpyxl.load_workbook(TEMPLATE, data_only=False)
    try:
        tables = {
            name: worksheet.tables[name]
            for worksheet in workbook.worksheets
            for name in worksheet.tables
        }
        for table_name, expected_headers in TABLE_FORMULA_HEADERS.items():
            table = tables[table_name]
            worksheet = next(
                sheet for sheet in workbook.worksheets if table_name in sheet.tables
            )
            min_column, min_row, _, _ = openpyxl.utils.range_boundaries(table.ref)
            headers = [column.name for column in table.tableColumns]
            for expected_header in expected_headers:
                column_offset = headers.index(expected_header)
                formula = worksheet.cell(min_row + 1, min_column + column_offset).value
                assert isinstance(formula, str) and formula.startswith("=")
                assert "@" not in formula
                assert "数量" not in formula
    finally:
        workbook.close()


def test_bundled_template_has_no_blank_formula_records() -> None:
    with ZipFile(TEMPLATE) as archive:
        blank = [
            name
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet")
            and name.endswith(".xml")
            and any(marker in archive.read(name) for marker in (b"<f></f>", b"<f/>", b"<f />"))
        ]
    assert blank == []

    workbook = openpyxl.load_workbook(TEMPLATE, data_only=False)
    try:
        orphaned = []
        for worksheet in workbook.worksheets:
            table_ranges = [
                openpyxl.utils.range_boundaries(worksheet.tables[name].ref)
                for name in worksheet.tables
            ]
            for row in worksheet.iter_rows():
                for cell in row:
                    if cell.data_type != "f" or not isinstance(cell.value, str):
                        continue
                    if "@" not in cell.value and "[#This Row]," not in cell.value:
                        continue
                    inside_table = any(
                        min_col <= cell.column <= max_col
                        and min_row < cell.row <= max_row
                        for min_col, min_row, max_col, max_row in table_ranges
                    )
                    if not inside_table:
                        orphaned.append(f"{worksheet.title}!{cell.coordinate}")
        assert orphaned == []
    finally:
        workbook.close()
