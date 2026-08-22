from __future__ import annotations

import errno
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import openpyxl
import pytest
from openpyxl.utils.cell import range_boundaries


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPT = SKILL_ROOT / "scripts/generate_sow.py"
FIXTURE = SKILL_ROOT / "fixtures/project"
ASIS_VALIDATE = SKILL_ROOT.parent / "analyze-as-is/scripts/validate.py"
DESIGN_VALIDATE = SKILL_ROOT.parent / "generate-design/scripts/validate.py"
TABLE_FORMULA_HEADERS = {
    "SOWStoryTable": {"需求", "子需求", "验收条件", "任务明细", "人天", "关联假设ID", "假设状态"},
    "TaskTable": {"任务族", "基础人天", "复杂度倍率", "人天小计"},
    "IntegrationTable": {"集成Task ID", "工作模式", "复杂度", "支持单价", "SIT人天"},
    "AssumptionRiskTable": {"关联 Story 人天"},
}
BARE_TEXTJOIN = re.compile(rb"(?<!_xlfn\.)(?<!_xludf\.)TEXTJOIN\(")


def load_generate_sow_module():
    spec = importlib.util.spec_from_file_location("ai_sow_generate_race_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    scripts = str(SKILL_ROOT / "scripts")
    sys.path.insert(0, scripts)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts)
    return module


def prepare(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    return root


def run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_committed_brownfield_fixture_passes_as_is_validation(tmp_path: Path) -> None:
    root = prepare(tmp_path)

    result = subprocess.run(
        [sys.executable, str(ASIS_VALIDATE), "--project-root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout


def test_accepts_source_input_technical_feature_after_owner_validation(
    tmp_path: Path,
) -> None:
    root = prepare(tmp_path)
    requirements_path = root / ".ai-sow/data/generate-design/requirements.json"
    requirements = json.loads(requirements_path.read_text())
    requirements["epics"][0]["source"] = {
        "type": "DESIGN_DERIVED",
        "designDecisionIds": ["decision-profile-api"],
        "effectiveStartItemIds": ["effective-start-customer-profile"],
        "rationale": "来源技术平台约束需要由目标设计决策细化。",
    }
    requirements["features"][0]["source"] = {
        "type": "SOURCE_INPUT",
        "sourceDocumentIds": ["source-document-customer-profile"],
        "sourceReferences": ["customer-profile.md#technical-api"],
    }
    requirements_path.write_text(json.dumps(requirements))

    owner_result = subprocess.run(
        [sys.executable, str(DESIGN_VALIDATE), "--project-root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert owner_result.returncode == 0, owner_result.stdout

    result = run(root)

    assert result.returncode == 0, result.stdout


def test_rejects_uncalibrated_complexity_factor_in_project_template(
    tmp_path: Path,
) -> None:
    root = prepare(tmp_path)
    template = root / ".ai-sow/templates/sow-template.xlsx"
    workbook = openpyxl.load_workbook(template)
    try:
        workbook["91-项目参数"]["F5"] = "待样本校准"
        workbook.save(template)
    finally:
        workbook.close()

    result = run(root)

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "ERROR"
    assert "complexity factor is not calibrated: S" in payload["summary"]


@pytest.mark.parametrize(
    ("rationale", "activity_types", "commitment"),
    [
        (
            "可复用的客户档案框架保持不变，本项目侧认证、映射和适配均不需要。",
            ["AUTHENTICATE", "MAP", "ADAPT"],
            "本项目负责并交付：认证、映射、适配",
        ),
        (
            "可复用的客户档案框架保持不变，配置不是本项目工作。",
            ["CONFIGURE"],
            "本项目负责并交付：配置",
        ),
        (
            "可复用的客户档案框架保持不变，本项目不会开展专项验证。",
            ["SPECIALIZED_VERIFY"],
            "本项目负责并交付：专项验证",
        ),
        (
            "可复用的客户档案框架保持不变，本项目不负责配置，只直接调用。",
            ["CONFIGURE"],
            "本项目负责并交付：配置",
        ),
        (
            "可复用的客户档案框架保持不变，认证、映射和适配全部由客户团队完成，本项目只直接调用。",
            ["AUTHENTICATE", "MAP", "ADAPT"],
            "本项目负责并交付：认证、映射、适配",
        ),
        (
            "可复用的客户档案框架保持不变，配置没有必要，本项目只直接调用。",
            ["CONFIGURE"],
            "本项目负责并交付：配置",
        ),
        (
            "可复用的客户档案框架保持不变，本项目既不配置，也不适配，只直接调用。",
            ["CONFIGURE", "ADAPT"],
            "本项目负责并交付：配置、适配",
        ),
    ],
)
def test_rejects_reuse_without_separately_estimable_integration_work(
    tmp_path: Path,
    rationale: str,
    activity_types: list[str],
    commitment: str,
) -> None:
    root = prepare(tmp_path)
    estimate_path = root / ".ai-sow/data/generate-task/estimate.json"
    estimate = json.loads(estimate_path.read_text())
    estimate["tasks"][2]["workModeRationale"] = rationale
    estimate["tasks"][2]["workModeEvidence"]["projectSideWorkTypes"] = activity_types
    estimate["tasks"][2]["workModeEvidence"]["projectSideWorkCommitment"] = commitment
    estimate_path.write_text(json.dumps(estimate))

    result = run(root)

    assert result.returncode == 2
    assert any(
        item["code"] == "WORK_MODE_REUSE_NOT_ESTIMABLE"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_estimate_affecting_unresolved_uncertainty(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["uncertainties"] = [
        {
            "uncertaintyId": "uncertainty-estimate-boundary",
            "topic": "DELIVERY_CONSTRAINTS",
            "question": "是否需要第二个部署环境？",
            "impact": "若需要，将新增第二个部署环境并导致额外开发与延期。",
            "affectsEstimate": True,
            "owner": "项目发起人",
            "recommendedHandling": "估算前确认范围",
            "relatedFeatureIds": ["feature-customer-profile"],
        }
    ]
    asis_path.write_text(json.dumps(asis))

    result = run(root)

    assert result.returncode == 2
    assert any(
        item["code"] == "ESTIMATE_UNCERTAINTY_UNRESOLVED"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_blocked_design_review_gate(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    review_path = root / ".ai-sow/reviews/generate-design.md"
    review_path.write_text(
        review_path.read_text().replace("HLD Coverage: PASSED", "HLD Coverage: BLOCKED")
    )

    result = run(root)

    assert result.returncode == 2
    assert any(
        item["code"] == "HLD_GATE_NOT_PASSED"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_unknown_effective_start_reference_in_shared_gate(
    tmp_path: Path,
) -> None:
    root = prepare(tmp_path)
    design_path = root / ".ai-sow/data/generate-design/design.json"
    design = json.loads(design_path.read_text())
    design["decisions"][0]["effectiveStartItemIds"] = ["effective-start-missing"]
    design_path.write_text(json.dumps(design))

    result = run(root)

    assert result.returncode == 2
    assert any(
        item["code"] == "EFFECTIVE_START_REF_UNKNOWN"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_duplicate_release_cutover_in_generated_package(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    estimate_path = root / ".ai-sow/data/generate-task/estimate.json"
    estimate = json.loads(estimate_path.read_text())
    for sequence in (1, 2):
        estimate["tasks"].append(
            {
                "taskId": f"task-release-cutover-{sequence}",
                "storyId": "story-customer-profile",
                "name": f"执行第 {sequence} 个发布切换实例",
                "baseUnit": "BU-RELEASE-CUTOVER",
                "workMode": "新建",
                "workModeRationale": f"为新环境建立第 {sequence} 个独立切换窗口与回滚清单。",
                "complexity": "M",
                "matchedEffectiveStartItemIds": [],
                "rationale": "完成统一发布范围、执行顺序、回滚与确认记录。",
            }
        )
    estimate_path.write_text(json.dumps(estimate))

    result = run(root)

    assert result.returncode == 2
    assert any(
        item["code"] == "RELEASE_CUTOVER_DUPLICATE"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_problem_diagnosis_and_remediation_overlap_in_package(
    tmp_path: Path,
) -> None:
    root = prepare(tmp_path)
    estimate_path = root / ".ai-sow/data/generate-task/estimate.json"
    estimate = json.loads(estimate_path.read_text())
    estimate["tasks"].extend(
        [
            {
                "taskId": "task-problem-diagnosis",
                "storyId": "story-customer-profile",
                "name": "诊断客户档案提交失败并恢复服务",
                "baseUnit": "BU-TECH-SUPPORT",
                "workMode": "新建",
                "workModeRationale": "对明确故障收集证据、定位原因并形成恢复记录。",
                "complexity": "M",
                "matchedEffectiveStartItemIds": [],
                "rationale": "输出统一的问题描述、诊断过程和恢复结论。",
            },
            {
                "taskId": "task-root-cause-remediation",
                "storyId": "story-customer-profile",
                "name": "整改客户档案提交失败的确认根因",
                "baseUnit": "BU-ROOT-CAUSE-REMEDIATION",
                "workMode": "新建",
                "workModeRationale": "针对已确认的字段校验根因实施一次代码整改。",
                "complexity": "M",
                "matchedEffectiveStartItemIds": [
                    "effective-start-customer-profile"
                ],
                "rationale": "交付经验证的根因整改，不重复计算诊断工作。",
            },
        ]
    )
    estimate_path.write_text(json.dumps(estimate))

    result = run(root)

    assert result.returncode == 2
    assert any(
        item["code"] == "PROBLEM_TASK_OVERLAP"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_uncertainty_without_explicit_estimate_impact_flag(
    tmp_path: Path,
) -> None:
    root = prepare(tmp_path)
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["uncertainties"][0].pop("affectsEstimate")
    asis_path.write_text(json.dumps(asis))

    result = run(root)

    assert result.returncode == 2
    assert any(
        item["code"] == "SHAPE_INVALID"
        and "affectsEstimate must be a boolean" in item["message"]
        for item in json.loads(result.stdout)["diagnostics"]
    )


@pytest.mark.parametrize(
    ("collection", "field", "value"),
    [
        ("epics", "type", "BUSINESS"),
        ("features", "source", {"type": "UNSUPPORTED"}),
    ],
)
def test_rejects_invalid_technical_requirement_type_or_provenance(
    tmp_path: Path,
    collection: str,
    field: str,
    value: object,
) -> None:
    root = prepare(tmp_path)
    requirements_path = root / ".ai-sow/data/generate-design/requirements.json"
    requirements = json.loads(requirements_path.read_text())
    requirements[collection][0][field] = value
    requirements_path.write_text(json.dumps(requirements))

    result = run(root)

    assert result.returncode == 2
    assert any(
        item["code"] == "SOURCE_TYPE_INVALID"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def table_values(workbook_path: Path, table_name: str, column_name: str) -> list[object]:
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        for worksheet in workbook.worksheets:
            if table_name not in worksheet.tables:
                continue
            table = worksheet.tables[table_name]
            min_col, min_row, max_col, max_row = range_boundaries(table.ref)
            headers = [worksheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
            column = min_col + headers.index(column_name)
            return [worksheet.cell(row, column).value for row in range(min_row + 1, max_row + 1)]
    finally:
        workbook.close()
    raise AssertionError(f"missing table: {table_name}")


def table_headers(workbook_path: Path, table_name: str) -> list[object]:
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        for worksheet in workbook.worksheets:
            if table_name not in worksheet.tables:
                continue
            table = worksheet.tables[table_name]
            min_col, min_row, max_col, _ = range_boundaries(table.ref)
            return [
                worksheet.cell(min_row, column).value
                for column in range(min_col, max_col + 1)
            ]
    finally:
        workbook.close()
    raise AssertionError(f"missing table: {table_name}")


def table_ref(workbook_path: Path, table_name: str) -> str:
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        for worksheet in workbook.worksheets:
            if table_name in worksheet.tables:
                return worksheet.tables[table_name].ref
    finally:
        workbook.close()
    raise AssertionError(f"missing table: {table_name}")


def table_ref_and_filter(workbook_path: Path, table_name: str) -> tuple[str, str | None]:
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        for worksheet in workbook.worksheets:
            if table_name in worksheet.tables:
                table = worksheet.tables[table_name]
                return table.ref, table.autoFilter.ref if table.autoFilter is not None else None
    finally:
        workbook.close()
    raise AssertionError(f"missing table: {table_name}")


def cell_value_and_type(workbook_path: Path, sheet_name: str, coordinate: str) -> tuple[object, str]:
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        cell = workbook[sheet_name][coordinate]
        return cell.value, cell.data_type
    finally:
        workbook.close()


def calculated_formula_headers(workbook_path: Path, table_name: str) -> set[str]:
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        for worksheet in workbook.worksheets:
            if table_name not in worksheet.tables:
                continue
            table = worksheet.tables[table_name]
            return {
                column.name
                for column in table.tableColumns
                if column.calculatedColumnFormula is not None
                and column.calculatedColumnFormula.text
            }
    finally:
        workbook.close()
    raise AssertionError(f"missing table: {table_name}")


def calculated_formulas(workbook_path: Path, table_name: str) -> list[str]:
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        for worksheet in workbook.worksheets:
            if table_name not in worksheet.tables:
                continue
            return [
                column.calculatedColumnFormula.text
                for column in worksheet.tables[table_name].tableColumns
                if column.calculatedColumnFormula is not None
                and column.calculatedColumnFormula.text
            ]
    finally:
        workbook.close()
    raise AssertionError(f"missing table: {table_name}")


def blank_formula_records(workbook_path: Path) -> list[str]:
    blank: list[str] = []
    with ZipFile(workbook_path) as archive:
        for name in archive.namelist():
            if not name.startswith("xl/worksheets/sheet") or not name.endswith(".xml"):
                continue
            content = archive.read(name)
            if b"<f></f>" in content or b"<f/>" in content or b"<f />" in content:
                blank.append(name)
    return blank


def bare_textjoin_formula_parts(workbook_path: Path) -> list[str]:
    with ZipFile(workbook_path) as archive:
        return [
            name
            for name in archive.namelist()
            if name.startswith(("xl/worksheets/", "xl/tables/"))
            and name.endswith(".xml")
            and BARE_TEXTJOIN.search(archive.read(name))
        ]


def downgrade_textjoin_serialization(workbook_path: Path) -> None:
    source_bytes = workbook_path.read_bytes()
    output = BytesIO()
    replacements = 0
    with ZipFile(BytesIO(source_bytes)) as source, ZipFile(output, "w") as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename in {"xl/worksheets/sheet4.xml", "xl/tables/table3.xml"}:
                replacements += payload.count(b"_xlfn.TEXTJOIN(")
                payload = payload.replace(b"_xlfn.TEXTJOIN(", b"TEXTJOIN(")
            target.writestr(info, payload)
    assert replacements > 0
    workbook_path.write_bytes(output.getvalue())


def orphan_table_formulas(workbook_path: Path) -> list[str]:
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        orphaned: list[str] = []
        for worksheet in workbook.worksheets:
            table_ranges = [
                range_boundaries(worksheet.tables[name].ref)
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
        return orphaned
    finally:
        workbook.close()


def test_packages_six_inputs_and_merges_requirements_only_in_workbook(tmp_path: Path) -> None:
    root = prepare(tmp_path)

    result = run(root)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "OK"
    output = Path(payload["outputs"][0])
    assert output.name.startswith("sow-")
    assert (output / "sow.xlsx").is_file()
    manifest = json.loads((output / "manifest.json").read_text())
    assert list(manifest["inputs"]) == [
        "sourceRequirements",
        "asis",
        "design",
        "derivedRequirements",
        "delivery",
        "estimate",
    ]
    assert (output / "data/analyze-requirement/requirements.json").is_file()
    assert (output / "data/generate-design/requirements.json").is_file()
    assert not (output / "data/requirements.json").exists()
    assert not (output / "inputs/prior-sows").exists()
    assert manifest["projectMode"] == "BROWNFIELD"
    assert manifest["pluginVersion"] == "0.1.0-beta.1"
    assert manifest["sowStandardVersion"] == "1.3"
    assert manifest["repositories"] == [
        {
            "repoId": "customer-portal",
            "setupRevision": "0123456789abcdef0123456789abcdef01234567",
        }
    ]
    assert manifest["priorSows"] == [
        {
            "priorSowId": "sow-phase-one",
            "sha256": "6aaa4f5427e455cde2603adb68209ac6ab5a75b32c02e0da866914a757ac93b8",
        }
    ]
    assert "originalName" not in json.dumps(manifest)
    assert '"file"' not in json.dumps(manifest)
    workbook_path = output / "sow.xlsx"
    assert table_values(workbook_path, "EpicTable", "Epic ID") == [
        "epic-customer-management",
        "epic-platform",
    ]
    assert table_values(workbook_path, "FeatureTable", "Feature ID") == [
        "feature-customer-profile",
        "feature-profile-api",
        "feature-production-scope",
    ]
    assert table_values(workbook_path, "TaskTable", "Task ID") == [
        "task-customer-profile-page",
        "task-profile-api",
        "task-profile-integration",
    ]
    assert table_values(workbook_path, "TaskTable", "系统现状匹配") == [
        "effective-start-customer-profile",
        "effective-start-customer-profile",
        "effective-start-customer-profile",
    ]

    effective_start_ids = {
        row_id
        for row_type, row_id in zip(
            table_values(workbook_path, "AsIsDetailTable", "记录类型"),
            table_values(workbook_path, "AsIsDetailTable", "记录 ID"),
            strict=True,
        )
        if row_type == "EFFECTIVE_START"
    }
    task_matches = {
        match_id
        for value in table_values(workbook_path, "TaskTable", "系统现状匹配")
        for match_id in str(value or "").split("、")
        if match_id
    }
    assert task_matches <= effective_start_ids


def test_projects_v13_entity_tables_and_optional_semantics(tmp_path: Path) -> None:
    root = prepare(tmp_path)

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        assert workbook.sheetnames[2] == "02-子需求"
    finally:
        workbook.close()
    assert table_headers(workbook_path, "EpicTable") == [
        "Epic ID",
        "需求类型",
        "需求名称",
        "需求描述",
        "涉及系统/数据",
        "目标结果",
        "公共约束/范围外",
    ]
    assert "需求 ID" not in table_headers(workbook_path, "EpicTable")
    assert table_headers(workbook_path, "FeatureTable") == [
        "Feature ID",
        "Epic ID",
        "Epic 名称",
        "子需求名称",
        "场景/范围描述",
        "涉及系统/数据",
        "约束/NFR",
        "来源类型",
        "推断理由",
    ]
    assert table_values(workbook_path, "EpicTable", "涉及系统/数据") == [None, None]
    assert table_values(workbook_path, "EpicTable", "目标结果") == [None, None]
    assert table_values(workbook_path, "FeatureTable", "约束/NFR") == [
        None,
        None,
        None,
    ]
    assert table_headers(workbook_path, "SOWStoryTable") == [
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
    assert table_headers(workbook_path, "TaskTable") == [
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
    assert table_values(workbook_path, "TaskTable", "基础单元ID") == [
        "BU-UI-INTERACTION",
        "BU-BUSINESS-SERVICE-API",
        "BU-INTERNAL-INTEGRATION",
    ]
    assert table_values(workbook_path, "TaskTable", "Integration ID") == [
        None,
        None,
        "integration-profile-api",
    ]
    assert table_values(workbook_path, "IntegrationTable", "集成Task ID") == [
        "=IF(A5=\"\",\"\",IFERROR(INDEX(TaskTable[Task ID],MATCH(A5,TaskTable[Integration ID],0)),\"\"))"
    ]
    for removed in ("类型", "专业域", "活动", "数量"):
        assert removed not in table_headers(workbook_path, "TaskTable")
    assert all("数量" not in formula for formula in calculated_formulas(workbook_path, "TaskTable"))


def test_projects_present_optional_semantics_exactly(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    requirements_path = root / ".ai-sow/data/analyze-requirement/requirements.json"
    requirements = json.loads(requirements_path.read_text())
    requirements["epics"][0].update(
        {
            "involvedSystemsData": "Customer Portal / customer_profile",
            "targetOutcome": "客户档案可用",
            "commonConstraintsOutOfScope": "不含历史数据迁移",
        }
    )
    requirements["features"][0].update(
        {
            "involvedSystemsData": "Customer Portal / customer_profile",
            "constraintsNfr": "P95 < 300ms",
        }
    )
    requirements_path.write_text(json.dumps(requirements))

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    assert table_values(workbook_path, "EpicTable", "涉及系统/数据")[0] == (
        "Customer Portal / customer_profile"
    )
    assert table_values(workbook_path, "EpicTable", "目标结果")[0] == "客户档案可用"
    assert table_values(workbook_path, "EpicTable", "公共约束/范围外")[0] == (
        "不含历史数据迁移"
    )
    assert table_values(workbook_path, "FeatureTable", "涉及系统/数据")[0] == (
        "Customer Portal / customer_profile"
    )
    assert table_values(workbook_path, "FeatureTable", "约束/NFR")[0] == "P95 < 300ms"


def test_projects_top_level_integrations_and_aggregates_assumption_story_ids(
    tmp_path: Path,
) -> None:
    root = prepare(tmp_path)
    delivery_path = root / ".ai-sow/data/generate-story/delivery.json"
    delivery = json.loads(delivery_path.read_text())
    delivery["assumptionStories"] = [
        {
            "assumptionId": "assumption-profile-api-availability",
            "storyId": "story-profile-integration",
        },
        {
            "assumptionId": "assumption-profile-api-availability",
            "storyId": "story-customer-profile",
        },
        {
            "assumptionId": "assumption-profile-api-availability",
            "storyId": "story-profile-integration",
        },
        {
            "assumptionId": "assumption-risk-profile-alert-channel",
            "storyId": "story-profile-integration",
        },
    ]
    delivery_path.write_text(json.dumps(delivery))

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    assert table_values(workbook_path, "IntegrationTable", "Integration ID") == [
        "integration-profile-api"
    ]
    assert table_values(workbook_path, "IntegrationTable", "来源") == [
        "Customer Portal（客户门户）"
    ]
    assert table_values(workbook_path, "AssumptionRiskTable", "假设ID") == [
        "assumption-profile-api-availability",
        "assumption-risk-profile-alert-channel",
    ]
    assert table_values(workbook_path, "AssumptionRiskTable", "关联 Story ID") == [
        "story-profile-integration、story-customer-profile",
        "story-profile-integration",
    ]


def test_rejects_removed_story_task_and_sit_fields(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    delivery_path = root / ".ai-sow/data/generate-story/delivery.json"
    delivery = json.loads(delivery_path.read_text())
    delivery["stories"][0]["type"] = "BUSINESS"
    delivery_path.write_text(json.dumps(delivery))
    estimate_path = root / ".ai-sow/data/generate-task/estimate.json"
    estimate = json.loads(estimate_path.read_text())
    estimate["tasks"][0]["professionalDomain"] = "前端"
    estimate["sitEstimates"] = []
    estimate_path.write_text(json.dumps(estimate))

    result = run(root)

    assert result.returncode == 2
    diagnostics = json.loads(result.stdout)["diagnostics"]
    messages = "\n".join(item["message"] for item in diagnostics)
    assert "stories[0] has unexpected fields: ['type']" in messages
    assert "professionalDomain" in messages
    assert "sitEstimates" in messages


def test_rejects_missing_or_duplicate_integration_task(tmp_path: Path) -> None:
    missing_root = prepare(tmp_path / "missing")
    missing_path = missing_root / ".ai-sow/data/generate-task/estimate.json"
    missing_estimate = json.loads(missing_path.read_text())
    missing_estimate["tasks"] = [
        task for task in missing_estimate["tasks"] if "integrationId" not in task
    ]
    missing_path.write_text(json.dumps(missing_estimate))

    missing_result = run(missing_root)

    assert missing_result.returncode == 2
    assert "INTEGRATION_COVERAGE_MISSING" in {
        item["code"] for item in json.loads(missing_result.stdout)["diagnostics"]
    }

    duplicate_root = prepare(tmp_path / "duplicate")
    duplicate_path = duplicate_root / ".ai-sow/data/generate-task/estimate.json"
    duplicate_estimate = json.loads(duplicate_path.read_text())
    duplicate_task = dict(duplicate_estimate["tasks"][-1])
    duplicate_task["taskId"] = "task-profile-integration-duplicate"
    duplicate_estimate["tasks"].append(duplicate_task)
    duplicate_path.write_text(json.dumps(duplicate_estimate))

    duplicate_result = run(duplicate_root)

    assert duplicate_result.returncode == 2
    assert "INTEGRATION_COVERAGE_DUPLICATE" in {
        item["code"] for item in json.loads(duplicate_result.stdout)["diagnostics"]
    }


def test_rejects_integration_owner_and_base_unit_mismatch(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    estimate_path = root / ".ai-sow/data/generate-task/estimate.json"
    estimate = json.loads(estimate_path.read_text())
    estimate["tasks"][-1]["baseUnit"] = "BU-EXTERNAL-INTEGRATION"
    estimate_path.write_text(json.dumps(estimate))

    result = run(root)

    assert result.returncode == 2
    assert "INTEGRATION_OWNER_MISMATCH" in {
        item["code"] for item in json.loads(result.stdout)["diagnostics"]
    }


def test_projects_as_is_topics_details_and_header(tmp_path: Path) -> None:
    root = prepare(tmp_path)

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    assert table_values(workbook_path, "AsIsTopicTable", "主题") == [
        "系统边界与参与方",
        "能力与流程",
        "应用与组件",
        "集成与外部依赖",
        "数据与存储",
        "平台、环境与部署",
        "安全与合规",
        "运维与质量",
        "交付与约束",
    ]
    assert table_values(workbook_path, "AsIsDetailTable", "记录类型") == [
        "CURRENT_FACT",
        "COMMITMENT",
        "EFFECTIVE_START",
        "COVERAGE",
        "UNCERTAINTY",
        "EVIDENCE",
    ]
    assert "NOT_IMPLEMENTED / CARRY_FORWARD" in table_values(
        workbook_path, "AsIsDetailTable", "分类/状态"
    )
    assert table_values(workbook_path, "AsIsDetailTable", "关联 ID")[3] == (
        "effective-start-customer-profile、commitment-profile-fields、"
        "uncertainty-profile-alert-channel"
    )
    assert table_values(workbook_path, "AsIsDetailTable", "证据引用")[0] == (
        "customer-portal/src/profile.ts#L12"
    )
    assert table_ref_and_filter(workbook_path, "AsIsTopicTable") == ("A4:G13", "A4:G13")
    assert table_ref_and_filter(workbook_path, "AsIsDetailTable") == ("A17:I23", "A17:I23")
    topic_bounds = range_boundaries(table_ref(workbook_path, "AsIsTopicTable"))
    detail_bounds = range_boundaries(table_ref(workbook_path, "AsIsDetailTable"))
    assert topic_bounds[3] < detail_bounds[1]
    assert cell_value_and_type(workbook_path, "90-系统现状", "A2") == (
        "模式：BROWNFIELD | As-of：2026-08-19 | "
        "Repo：customer-portal@0123456789ab | 排除范围：旧版批量导出",
        "s",
    )


def test_projects_runtime_evidence_outcome(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["evidence"][0]["kind"] = "RUNTIME"
    asis["evidence"][0]["runtimeOutcome"] = "PASSED"
    asis_path.write_text(json.dumps(asis))

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    assert table_values(workbook_path, "AsIsDetailTable", "分类/状态")[-1] == (
        "RUNTIME / PASSED"
    )


def test_runtime_evidence_without_outcome_keeps_staging(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["evidence"][0]["kind"] = "RUNTIME"
    asis_path.write_text(json.dumps(asis))

    result = run(root)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    assert {
        "code": "SHAPE_INVALID",
        "message": "evidence[0].runtimeOutcome must be PASSED, FAILED, or BLOCKED",
    } in payload["diagnostics"]
    assert Path(payload["staging"]).is_dir()
    assert not list((root / ".ai-sow/outputs").glob("sow-*"))


def test_long_as_is_detail_rows_expand_to_show_wrapped_ids(tmp_path: Path) -> None:
    root = prepare(tmp_path)

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        worksheet = workbook["90-系统现状"]
        assert worksheet["H23"].alignment.wrap_text is True
        assert worksheet.row_dimensions[23].height >= 60
    finally:
        workbook.close()


def test_long_as_is_topic_summary_expands_without_changing_short_rows(
    tmp_path: Path,
) -> None:
    root = prepare(tmp_path)
    template = openpyxl.load_workbook(
        root / ".ai-sow/templates/sow-template.xlsx", data_only=False
    )
    try:
        prototype_height = template["90-系统现状"].row_dimensions[5].height
    finally:
        template.close()
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    for assessment in asis["topicAssessments"]:
        assessment["summary"] = "已评估"
    asis["topicAssessments"][0]["summary"] = "系统边界结论" * 40
    asis_path.write_text(json.dumps(asis))

    result = run(root)

    assert result.returncode == 0, result.stdout
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        worksheet = workbook["90-系统现状"]
        assert prototype_height is not None
        assert worksheet.row_dimensions[5].height > prototype_height
        assert worksheet.row_dimensions[6].height == prototype_height
    finally:
        workbook.close()


def test_long_multi_repo_metadata_expands_header_without_changing_short_header(
    tmp_path: Path,
) -> None:
    short_root = prepare(tmp_path / "short")
    template = openpyxl.load_workbook(
        short_root / ".ai-sow/templates/sow-template.xlsx", data_only=False
    )
    try:
        prototype_height = template["90-系统现状"].row_dimensions[2].height
    finally:
        template.close()
    short_result = run(short_root)
    assert short_result.returncode == 0, short_result.stdout
    short_workbook_path = Path(json.loads(short_result.stdout)["outputs"][0]) / "sow.xlsx"
    short_workbook = openpyxl.load_workbook(short_workbook_path, data_only=False)
    try:
        short_height = short_workbook["90-系统现状"].row_dimensions[2].height
    finally:
        short_workbook.close()

    root = prepare(tmp_path / "long")
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    snapshots = []
    for index in range(12):
        repo_id = f"customer-domain-repository-{index}"
        repo_path = f"repositories/{repo_id}"
        (root / repo_path).mkdir(parents=True)
        revision = f"{index:x}" * 40
        snapshots.append(
            {"repoId": repo_id, "path": repo_path, "revision": revision, "dirty": False}
        )
    asis["analysisScope"]["repositorySnapshots"] = snapshots
    asis["analysisScope"]["excludedAreas"] = [
        f"Legacy operational boundary {index}" for index in range(12)
    ]
    asis_path.write_text(json.dumps(asis))

    result = run(root)

    assert result.returncode == 0, result.stdout
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        assert short_height == prototype_height
        assert workbook["90-系统现状"].row_dimensions[2].height > short_height
    finally:
        workbook.close()


def test_generated_workbook_preserves_as_is_review_settings(tmp_path: Path) -> None:
    root = prepare(tmp_path)

    result = run(root)

    assert result.returncode == 0, result.stdout
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        as_is_sheet = workbook["90-系统现状"]
        assert as_is_sheet.freeze_panes == "A4"
        assert not as_is_sheet.data_validations.dataValidation
        assert workbook.calculation.calcMode == "auto"
        assert workbook.calculation.calcOnSave is True
        assert workbook.calculation.fullCalcOnLoad is True
        assert workbook.calculation.forceFullCalc is True
    finally:
        workbook.close()


def test_empty_projection_tables_remain_valid_excel_tables(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    delivery_path = root / ".ai-sow/data/generate-story/delivery.json"
    delivery = json.loads(delivery_path.read_text())
    integration_story_ids = {
        integration["storyId"] for integration in delivery["integrations"]
    }
    delivery["stories"] = [
        story
        for story in delivery["stories"]
        if story["storyId"] not in integration_story_ids
    ]
    delivery["acceptanceCriteria"] = [
        criterion
        for criterion in delivery["acceptanceCriteria"]
        if criterion["storyId"] not in integration_story_ids
    ]
    delivery["integrations"] = [
        integration
        for integration in delivery["integrations"]
        if integration["storyId"] not in integration_story_ids
    ]
    delivery["assumptions"] = []
    delivery["assumptionStories"] = []
    delivery_path.write_text(json.dumps(delivery))
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    for collection in (
        "items",
        "commitments",
        "effectiveStartItems",
        "coverage",
        "uncertainties",
        "evidence",
    ):
        asis[collection] = []
    asis["topicAssessments"][7]["uncertaintyIds"] = []
    asis_path.write_text(json.dumps(asis))
    estimate_path = root / ".ai-sow/data/generate-task/estimate.json"
    estimate = json.loads(estimate_path.read_text())
    estimate["tasks"] = [
        task
        for task in estimate["tasks"]
        if task["storyId"] not in integration_story_ids
    ]
    for task in estimate["tasks"]:
        task["matchedEffectiveStartItemIds"] = []
        task["workMode"] = "新建"
        task.pop("workModeEvidence", None)
        task["workModeRationale"] = "当前范围没有可调整或接入复用的既有交付对象，因此新建该基础单元实例。"
    estimate_path.write_text(json.dumps(estimate))

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    assert table_ref(workbook_path, "IntegrationTable") == "A4:M5"
    assert table_ref(workbook_path, "AssumptionRiskTable") == "A4:I5"
    assert table_values(workbook_path, "IntegrationTable", "Integration ID") == [None]
    assert table_values(workbook_path, "AssumptionRiskTable", "假设ID") == [None]
    assert table_ref(workbook_path, "AsIsTopicTable") == "A4:G13"
    assert table_ref(workbook_path, "AsIsDetailTable") == "A17:I18"
    assert table_values(workbook_path, "AsIsDetailTable", "记录 ID") == [None]


def test_generated_workbook_preserves_excel_calculated_columns(tmp_path: Path) -> None:
    root = prepare(tmp_path)

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    all_formulas: list[str] = []
    for table_name, expected in TABLE_FORMULA_HEADERS.items():
        assert calculated_formula_headers(workbook_path, table_name) == expected
        for formula in calculated_formulas(workbook_path, table_name):
            assert "@" not in formula
            assert "数量" not in formula
            all_formulas.append(formula)
    assert any("BaseUnitCatalogTable" in formula for formula in all_formulas)
    assert any("ProjectParameterTable" in formula for formula in all_formulas)
    assert all("BaseEffortTable" not in formula for formula in all_formulas)
    assert all("ComplexityRuleTable" not in formula for formula in all_formulas)


def test_generated_workbook_serializes_textjoin_for_excel_recalculation(
    tmp_path: Path,
) -> None:
    root = prepare(tmp_path)

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    assert bare_textjoin_formula_parts(workbook_path) == []


def test_generated_workbook_repairs_legacy_bare_textjoin_formulas(
    tmp_path: Path,
) -> None:
    root = prepare(tmp_path)
    downgrade_textjoin_serialization(
        root / ".ai-sow/templates/sow-template.xlsx",
    )

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    assert bare_textjoin_formula_parts(workbook_path) == []


def test_generated_workbook_has_no_blank_formula_records(tmp_path: Path) -> None:
    root = prepare(tmp_path)

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    assert blank_formula_records(workbook_path) == []
    assert orphan_table_formulas(workbook_path) == []


def test_generated_workbook_clears_styles_below_shrunk_integration_table(
    tmp_path: Path,
) -> None:
    root = prepare(tmp_path)

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        worksheet = workbook["06-集成点"]
        assert worksheet.tables["IntegrationTable"].ref == "A4:M5"
        assert [worksheet.row_dimensions[row].height for row in (6, 7)] == [
            None,
            None,
        ]
        assert all(
            not worksheet.cell(row, column).has_style
            for row in (6, 7)
            for column in range(1, 14)
        )
    finally:
        workbook.close()


def test_invalid_reference_keeps_staging_and_publishes_no_package(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    estimate_path = root / ".ai-sow/data/generate-task/estimate.json"
    estimate = json.loads(estimate_path.read_text())
    estimate["tasks"][0]["storyId"] = "story-not-found"
    estimate_path.write_text(json.dumps(estimate))

    result = run(root)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    staging = Path(payload["staging"])
    assert staging.is_dir()
    assert any(item["code"] == "STORY_REF_UNKNOWN" for item in payload["diagnostics"])
    assert not list((root / ".ai-sow/outputs").glob("sow-*"))


def test_tampered_registered_prior_sow_blocks_before_package_manifest(
    tmp_path: Path,
) -> None:
    root = prepare(tmp_path)
    prior_sow = root / ".ai-sow/inputs/analyze-as-is/prior-sows/sow-phase-one.md"
    prior_sow.write_bytes(b"tampered after setup\n")

    result = run(root)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    assert any(
        item["code"] == "PRIOR_SOW_HASH_MISMATCH"
        for item in payload["diagnostics"]
    )
    staging = Path(payload["staging"])
    assert staging.is_dir()
    assert not (staging / "manifest.json").exists()
    assert not list((root / ".ai-sow/outputs").glob("sow-*"))


def test_registered_repository_symlink_escape_blocks_package(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    repository = root / "repositories/customer-portal"
    shutil.rmtree(repository)
    outside = tmp_path / "outside-repository"
    outside.mkdir()
    repository.symlink_to(outside, target_is_directory=True)

    result = run(root)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    assert any(
        item["code"] == "REGISTERED_PATH_INVALID"
        for item in payload["diagnostics"]
    )
    assert not list((root / ".ai-sow/outputs").glob("sow-*"))


def test_outputs_symlink_escape_blocks_before_writing_package(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    outside = tmp_path / "outside-outputs"
    outside.mkdir()
    (root / ".ai-sow/outputs").symlink_to(outside, target_is_directory=True)

    result = run(root)

    assert result.returncode != 0
    assert json.loads(result.stdout)["outcome"] in {"BLOCKED", "ERROR"}
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd race regression")
def test_outputs_swap_after_path_check_cannot_receive_package_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Catches output writes that resolve the path again after its safety check."""
    root = prepare(tmp_path)
    outputs = root / ".ai-sow" / "outputs"
    outputs.mkdir()
    displaced = root / ".ai-sow" / "outputs-displaced"
    outside = tmp_path / "outside-raced-outputs"
    outside.mkdir()
    module = load_generate_sow_module()
    original_reject = module.reject_managed_symlink_chain
    swapped = False

    def reject_then_swap(project_root: Path, target: Path) -> None:
        nonlocal swapped
        original_reject(project_root, target)
        if not swapped and target == outputs:
            outputs.rename(displaced)
            outputs.symlink_to(outside, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(module, "reject_managed_symlink_chain", reject_then_swap)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--project-root", str(root)])

    assert module.main() != 0
    capsys.readouterr()
    assert swapped is True
    assert list(outside.rglob("*")) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd race regression")
def test_staging_swap_during_generation_cannot_receive_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Catches workbook/manifest writes through a raced managed staging path."""
    root = prepare(tmp_path)
    outputs = root / ".ai-sow" / "outputs"
    outputs.mkdir()
    outside = tmp_path / "outside-raced-staging"
    outside.mkdir()
    module = load_generate_sow_module()
    original_write_workbook = module.write_workbook
    swapped = False

    def race_then_write(*args, **kwargs) -> None:
        nonlocal swapped
        managed_staging = list(outputs.glob(".staging-*"))
        if managed_staging:
            staging = managed_staging[0]
            staging.rename(outputs / ".displaced-staging")
            staging.symlink_to(outside, target_is_directory=True)
            swapped = True
        original_write_workbook(*args, **kwargs)

    monkeypatch.setattr(module, "write_workbook", race_then_write)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--project-root", str(root)])

    result = module.main()
    capsys.readouterr()
    assert result == 0
    assert list(outside.rglob("*")) == []
    packages = list(outputs.glob("sow-*"))
    assert len(packages) == 1
    assert packages[0].is_dir() and not packages[0].is_symlink()


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd fallback regression")
def test_cross_device_publish_copies_into_anchored_outputs_before_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Catches reliance on system temp and project outputs sharing a filesystem."""
    root = prepare(tmp_path)
    module = load_generate_sow_module()
    real_rename = module.os.rename
    simulated_exdev = False

    def rename_with_cross_device_source(source, destination, *args, **kwargs):
        nonlocal simulated_exdev
        if Path(source).is_absolute() and kwargs.get("dst_dir_fd") is not None:
            simulated_exdev = True
            raise OSError(errno.EXDEV, "simulated cross-device publish")
        return real_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(module.os, "rename", rename_with_cross_device_source)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--project-root", str(root)])

    result = module.main()
    capsys.readouterr()
    assert simulated_exdev is True
    assert result == 0
    packages = list((root / ".ai-sow/outputs").glob("sow-*"))
    assert len(packages) == 1
    assert (packages[0] / "sow.xlsx").is_file()
    assert (packages[0] / "manifest.json").is_file()
    assert not list((root / ".ai-sow/outputs").glob(".transfer-*"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX fd lifecycle regression")
def test_cross_device_copy_closes_source_fd_when_destination_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a source descriptor leak on destination creation failure."""
    module = load_generate_sow_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.json").write_text("{}", encoding="utf-8")
    destination = tmp_path / "destination"
    destination.mkdir()
    destination_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
    real_open = module.os.open
    source_fds: list[int] = []

    def fail_destination_open(path, flags, *args, **kwargs):
        if Path(path).is_absolute() and flags & os.O_RDONLY == os.O_RDONLY:
            file_descriptor = real_open(path, flags, *args, **kwargs)
            source_fds.append(file_descriptor)
            return file_descriptor
        if kwargs.get("dir_fd") == destination_fd and flags & os.O_WRONLY:
            raise OSError(errno.EIO, "simulated destination open failure")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", fail_destination_open)
    try:
        with pytest.raises(OSError, match="simulated destination open failure"):
            module.PosixOutputAnchor.copy_tree_into(source, destination_fd)
        assert source_fds
        for file_descriptor in source_fds:
            with pytest.raises(OSError):
                os.fstat(file_descriptor)
    finally:
        for file_descriptor in source_fds:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        os.close(destination_fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX fd lifecycle regression")
def test_cross_device_copy_preserves_fdopen_error_and_closes_raw_fds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches descriptor double-close masking when the second fdopen fails."""
    module = load_generate_sow_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.json").write_text("{}", encoding="utf-8")
    destination = tmp_path / "destination"
    destination.mkdir()
    destination_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
    real_open = module.os.open
    real_fdopen = module.os.fdopen
    opened_fds: list[int] = []
    fdopen_calls = 0

    def track_file_open(path, flags, *args, **kwargs):
        file_descriptor = real_open(path, flags, *args, **kwargs)
        if not flags & os.O_DIRECTORY:
            opened_fds.append(file_descriptor)
        return file_descriptor

    def fail_second_fdopen(file_descriptor, *args, **kwargs):
        nonlocal fdopen_calls
        fdopen_calls += 1
        if fdopen_calls == 2:
            raise OSError(errno.EIO, "simulated fdopen failure")
        return real_fdopen(file_descriptor, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", track_file_open)
    monkeypatch.setattr(module.os, "fdopen", fail_second_fdopen)
    try:
        with pytest.raises(OSError, match="simulated fdopen failure"):
            module.PosixOutputAnchor.copy_tree_into(source, destination_fd)
        assert len(opened_fds) == 2
        for file_descriptor in opened_fds:
            with pytest.raises(OSError):
                os.fstat(file_descriptor)
    finally:
        for file_descriptor in opened_fds:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        os.close(destination_fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX transfer cleanup regression")
def test_cross_device_publish_cleans_transfer_when_initial_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches an orphan transfer directory when its first no-follow open fails."""
    root = prepare(tmp_path)
    module = load_generate_sow_module()
    anchor = module.PosixOutputAnchor(root)
    source = tmp_path / "trusted-package"
    source.mkdir()
    (source / "payload.json").write_text("{}", encoding="utf-8")
    real_open = module.os.open
    injected = False

    def fail_first_transfer_open(path, flags, *args, **kwargs):
        nonlocal injected
        if not injected and str(path).startswith(".transfer-"):
            injected = True
            raise OSError(errno.EIO, "simulated transfer open failure")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", fail_first_transfer_open)
    try:
        with pytest.raises(OSError, match="simulated transfer open failure"):
            anchor.copy_then_publish(source, "sow-test")
        assert injected is True
        assert not list((root / ".ai-sow/outputs").glob(".transfer-*"))
        assert not (root / ".ai-sow/outputs/sow-test").exists()
    finally:
        anchor.close()


def test_fixed_input_symlink_escape_blocks_before_staging_copy(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    outside = tmp_path / "outside-inputs"
    outside.mkdir()
    outside_asis = outside / "asis.json"
    outside_asis.write_bytes(asis_path.read_bytes())
    asis_path.unlink()
    asis_path.symlink_to(outside_asis)

    result = run(root)

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["outcome"] in {"BLOCKED", "ERROR"}
    outputs = root / ".ai-sow/outputs"
    assert not outputs.exists() or not list(outputs.glob("sow-*"))


def test_generate_sow_is_self_contained_without_setup_skill_tree(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    isolated_plugin = tmp_path / "isolated-plugin"
    isolated_skill = isolated_plugin / "skills/generate-sow"
    shutil.copytree(SKILL_ROOT, isolated_skill)
    shutil.copytree(PLUGIN_ROOT / "runtime", isolated_plugin / "runtime")

    result = subprocess.run(
        [
            sys.executable,
            str(isolated_skill / "scripts/generate_sow.py"),
            "--project-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout


def test_unknown_effective_start_reference_keeps_staging(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    estimate_path = root / ".ai-sow/data/generate-task/estimate.json"
    estimate = json.loads(estimate_path.read_text())
    estimate["tasks"][0]["matchedEffectiveStartItemIds"] = ["effective-start-not-found"]
    estimate_path.write_text(json.dumps(estimate))

    result = run(root)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    assert any(
        item["code"] == "EFFECTIVE_START_REF_UNKNOWN"
        for item in payload["diagnostics"]
    )
    assert Path(payload["staging"]).is_dir()
    assert not list((root / ".ai-sow/outputs").glob("sow-*"))


def test_projection_array_shape_keeps_staging(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["evidence"][0]["supportsIds"] = "asis-customer-profile"
    asis_path.write_text(json.dumps(asis))

    result = run(root)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert any(
        item["code"] == "SHAPE_INVALID"
        and "evidence[0].supportsIds must be an array" in item["message"]
        for item in payload["diagnostics"]
    )
    assert Path(payload["staging"]).is_dir()


@pytest.mark.parametrize(
    ("case", "expected_message"),
    [
        ("item-name", "items[0].name must be a string"),
        ("topic", "topicAssessments[0].topic must be a string"),
        ("supports-id", "evidence[0].supportsIds[0] must be a string"),
        (
            "effective-start-id",
            "effectiveStartItems[0].effectiveStartItemId must be a string",
        ),
        (
            "task-match-id",
            "tasks[0].matchedEffectiveStartItemIds[0] must be a string",
        ),
    ],
)
def test_malformed_projection_scalars_keep_staging(
    tmp_path: Path,
    case: str,
    expected_message: str,
) -> None:
    root = prepare(tmp_path)
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    estimate_path = root / ".ai-sow/data/generate-task/estimate.json"
    estimate = json.loads(estimate_path.read_text())
    if case == "item-name":
        asis["items"][0]["name"] = []
    elif case == "topic":
        asis["topicAssessments"][0]["topic"] = []
    elif case == "supports-id":
        asis["evidence"][0]["supportsIds"] = [[]]
    elif case == "effective-start-id":
        asis["effectiveStartItems"][0]["effectiveStartItemId"] = 7
    else:
        estimate["tasks"][0]["matchedEffectiveStartItemIds"] = [7]
    asis_path.write_text(json.dumps(asis))
    estimate_path.write_text(json.dumps(estimate))

    result = run(root)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    assert {
        "code": "SHAPE_INVALID",
        "message": expected_message,
    } in payload["diagnostics"]
    assert Path(payload["staging"]).is_dir()
    assert not list((root / ".ai-sow/outputs").glob("sow-*"))


@pytest.mark.parametrize(
    ("field", "expected_message"),
    [
        ("projectId", "project is missing projectId"),
        ("pluginVersion", "project is missing pluginVersion"),
        ("sowStandardVersion", "project is missing sowStandardVersion"),
    ],
)
def test_missing_project_projection_fields_keep_staging(
    tmp_path: Path,
    field: str,
    expected_message: str,
) -> None:
    root = prepare(tmp_path)
    project_path = root / ".ai-sow/project.json"
    project = json.loads(project_path.read_text())
    del project[field]
    project_path.write_text(json.dumps(project))

    result = run(root)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    assert {
        "code": "SHAPE_INVALID",
        "message": expected_message,
    } in payload["diagnostics"]
    assert Path(payload["staging"]).is_dir()
    assert not list((root / ".ai-sow/outputs").glob("sow-*"))


def test_integration_projection_requires_relationship_fields(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["items"][0]["itemType"] = "INTEGRATION"
    asis_path.write_text(json.dumps(asis))

    result = run(root)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert any(
        item["code"] == "SHAPE_INVALID"
        and "items[0] is missing source" in item["message"]
        for item in payload["diagnostics"]
    )
    assert Path(payload["staging"]).is_dir()


def test_greenfield_header_uses_no_repository(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["analysisScope"]["mode"] = "GREENFIELD"
    asis["analysisScope"]["repositorySnapshots"] = []
    asis["analysisScope"]["priorSowSnapshots"] = []
    asis["commitments"] = []
    asis_path.write_text(json.dumps(asis))

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    header, data_type = cell_value_and_type(workbook_path, "90-系统现状", "A2")
    assert header == (
        "模式：GREENFIELD | As-of：2026-08-19 | Repo：无 | "
        "排除范围：旧版批量导出"
    )
    assert data_type == "s"


def test_escapes_formula_like_user_text(tmp_path: Path) -> None:
    root = prepare(tmp_path)
    requirements_path = root / ".ai-sow/data/analyze-requirement/requirements.json"
    requirements = json.loads(requirements_path.read_text())
    requirements["features"][0]["name"] = "=not-a-formula"
    requirements_path.write_text(json.dumps(requirements))
    asis_path = root / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["items"][0]["name"] = "=not-an-item-formula"
    asis["evidence"][0]["reference"] = "@not-an-evidence-formula"
    asis_path.write_text(json.dumps(asis))

    result = run(root)

    assert result.returncode == 0, result.stderr
    workbook_path = Path(json.loads(result.stdout)["outputs"][0]) / "sow.xlsx"
    assert table_values(workbook_path, "FeatureTable", "子需求名称")[0] == "'=not-a-formula"
    assert table_values(workbook_path, "AsIsDetailTable", "名称")[0] == "'=not-an-item-formula"
    assert table_values(workbook_path, "AsIsDetailTable", "证据引用")[0] == (
        "'@not-an-evidence-formula"
    )
