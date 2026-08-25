from __future__ import annotations

import json
import hashlib
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
HAN_CHARACTER = re.compile(r"[\u4e00-\u9fff]")
SPREADSHEET_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
STRUCTURED_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_.]*)\[([^\]]+)\]"
)

SCHEMA_SHA256 = {
    "skills/analyze-as-is/contracts/asis.schema.json": "0f9421a1000b9c7c157cc34f6683954ee0c67f7f2a8d2eea2f8c7b87d759d137",
    "skills/analyze-requirement/contracts/source-requirements.schema.json": "70562d9dbd6ac63f86ab8271f7f216e9c49799a1a6ac4f765a4dc9a6dd736c80",
    "skills/generate-design/contracts/technical-requirements.schema.json": "b1988feebe12d86c9af3da02200aa40311376dd604143245891256267ab12583",
    "skills/generate-design/contracts/design.schema.json": "27acb2adb696931bc16a103603fd9bc89b6b7c9d71c65ede51708edf9554d12f",
    "skills/generate-sow/contracts/manifest.schema.json": "b42c30a82e76709f0021caa3f7aac8bdaeb40ebb83d237f168f8f9fba8ebaee5",
    "skills/generate-story/contracts/delivery.schema.json": "d76137028a6879000ff08ed50ece9c6cb7c95022a9b219c164fc7817c65596d3",
    "skills/generate-task/contracts/estimate.schema.json": "34986edeb7fe53984b6e4696c979cd44f90ae2ff0c662d3665db6d748c5534c6",
    "skills/setup/contracts/project.schema.json": "6c10d9695de6eaffb2e1b3af79447467127c5c1e1dd4dd6ca37d788b63386e2d",
}

SCHEMA_ENUMS = {
    "skills/analyze-as-is/contracts/asis.schema.json": {
        "$.$defs.analysisScope.properties.mode": ["GREENFIELD", "BROWNFIELD"],
        "$.$defs.topic": ["SYSTEM_CONTEXT", "CAPABILITY", "APPLICATION", "INTEGRATION", "DATA", "PLATFORM", "SECURITY_COMPLIANCE", "OPERATIONS_QUALITY", "DELIVERY_CONSTRAINTS"],
        "$.$defs.itemType": ["CAPABILITY", "COMPONENT", "INTEGRATION", "DATA_ASSET", "INFRASTRUCTURE", "CONTROL", "PROCESS", "CONSTRAINT"],
        "$.$defs.topicAssessment.properties.status": ["ASSESSED", "NOT_APPLICABLE", "INSUFFICIENT_EVIDENCE"],
        "$.$defs.item.properties.direction": ["INBOUND", "OUTBOUND"],
        "$.$defs.commitment.properties.changeType": ["ADD", "REPLACE", "RETIRE"],
        "$.$defs.commitment.properties.implementationStatus": ["IMPLEMENTED", "PARTIAL", "NOT_IMPLEMENTED", "UNVERIFIED", "SUPERSEDED"],
        "$.$defs.commitment.properties.treatment": ["CURRENT_BASELINE", "EXPECTED_BEFORE_START", "CARRY_FORWARD", "EXCLUDE", "NEEDS_DECISION"],
        "$.$defs.coverage.properties.status": ["COMPLETE", "PARTIAL", "MISSING"],
        "$.$defs.coverage.allOf[0].if.properties.status": ["COMPLETE", "PARTIAL"],
        "$.$defs.evidence.properties.kind": ["RUNTIME", "CONTRACT", "CONFIGURATION", "CODE", "DEPLOYMENT", "PRIOR_SOW", "QUESTIONNAIRE", "DOCUMENT"],
        "$.$defs.evidence.properties.runtimeOutcome": ["PASSED", "FAILED", "BLOCKED"],
    },
    "skills/analyze-requirement/contracts/source-requirements.schema.json": {},
    "skills/generate-design/contracts/technical-requirements.schema.json": {},
    "skills/generate-design/contracts/design.schema.json": {
        "$.$defs.designItem.properties.type": ["COMPONENT", "FLOW", "DATA", "INTEGRATION", "INFRASTRUCTURE", "QUALITY"],
        "$.$defs.architectureDelta.properties.changeType": ["NEW", "ADOPT", "ADJUST", "REPLACE", "RETIRE"],
        "$.$defs.decision.properties.decisionKind": ["INTEGRATION_BOUNDARY", "PROVIDER_TARGET", "OPERATIONAL_THRESHOLD", "ENVIRONMENT_AUTHORITY", "CUTOVER_ROLLBACK", "OTHER"],
        "$.$defs.scopeDecision.properties.decision": ["IN_SCOPE", "FULLY_COVERED", "OUT_OF_SCOPE"],
        "$.$defs.scopeDecision.properties.requiredIntegrationBoundary": ["NONE", "PORT_ONLY", "END_TO_END"],
        "$.$defs.scopeDecision.properties.requiredDecisionKinds.items": ["INTEGRATION_BOUNDARY", "PROVIDER_TARGET", "OPERATIONAL_THRESHOLD", "ENVIRONMENT_AUTHORITY", "CUTOVER_ROLLBACK"],
    },
    "skills/generate-sow/contracts/manifest.schema.json": {
        "$.properties.projectMode": ["GREENFIELD", "BROWNFIELD"],
    },
    "skills/generate-story/contracts/delivery.schema.json": {
        "$.$defs.integration.properties.direction": ["INBOUND", "OUTBOUND"],
        "$.$defs.integration.properties.owner": ["INTERNAL", "EXTERNAL"],
        "$.$defs.integration.properties.deliveryBoundary": ["PORT_ONLY", "END_TO_END"],
        "$.$defs.integration.properties.targetKind": ["PORT", "ADAPTER", "SYSTEM", "PROVIDER"],
        "$.$defs.story.properties.requiredIntegrationBoundary": ["NONE", "PORT_ONLY", "END_TO_END"],
        "$.$defs.acceptanceCriterion.properties.decisionGate": ["NOT_REQUIRED", "REQUIRED"],
        "$.$defs.assumption.properties.type": ["假设", "风险"],
        "$.$defs.assumption.properties.status": ["已明确", "待确认"],
    },
    "skills/generate-task/contracts/estimate.schema.json": {
        "$.$defs.complexity": ["S", "M", "L"],
        "$.$defs.workModeEvidence.properties.projectSideWorkTypes.items": ["REGISTER", "CONFIGURE", "WRAP", "MAP", "ADAPT", "AUTHENTICATE", "TENANT_SETUP", "PERMISSION_SETUP", "SPECIALIZED_VERIFY"],
        "$.$defs.task.properties.workMode": ["新建", "调整", "接入复用"],
        "$.$defs.task.allOf[0].if.properties.complexity": ["S", "L"],
        "$.$defs.task.allOf[1].if.properties.workMode": ["调整", "接入复用"],
    },
    "skills/setup/contracts/project.schema.json": {},
}

TEMPLATE_SHA256 = "dc17a4ccb2902ba12379e7b964a2612d07f138a9b542cc6774bc05b4d3bf2e48"


def enum_arrays(value: object, path: str = "$") -> dict[str, list[object]]:
    if isinstance(value, dict):
        result = {path: value["enum"]} if "enum" in value else {}
        for key, child in value.items():
            result.update(enum_arrays(child, f"{path}.{key}"))
        return result
    if isinstance(value, list):
        result: dict[str, list[object]] = {}
        for index, child in enumerate(value):
            result.update(enum_arrays(child, f"{path}[{index}]"))
        return result
    return {}


class RepositoryLayoutTests(unittest.TestCase):
    def test_xlsx_formulas_only_reference_existing_table_columns(self) -> None:
        plugin_root = REPO_ROOT / "plugins/ai-sow"
        workbooks = [
            plugin_root / "skills/setup/assets/sow-template.xlsx",
            plugin_root / "docs/reference/SOW估算与生成示例_v1.3.xlsx",
        ]

        for workbook in workbooks:
            with self.subTest(workbook=workbook.name), ZipFile(workbook) as archive:
                tables: dict[str, set[str]] = {}
                for member in archive.namelist():
                    if not member.startswith("xl/tables/table") or not member.endswith(
                        ".xml"
                    ):
                        continue
                    table = ET.fromstring(archive.read(member))
                    tables[table.attrib["name"]] = {
                        column.attrib["name"]
                        for column in table.findall(
                            "x:tableColumns/x:tableColumn", SPREADSHEET_NS
                        )
                    }

                invalid_references: set[str] = set()
                for member in archive.namelist():
                    if not member.endswith(".xml") or not member.startswith(
                        ("xl/worksheets/", "xl/tables/")
                    ):
                        continue
                    root = ET.fromstring(archive.read(member))
                    formula_nodes = root.findall(".//x:f", SPREADSHEET_NS)
                    formula_nodes.extend(
                        root.findall(".//x:calculatedColumnFormula", SPREADSHEET_NS)
                    )
                    for node in formula_nodes:
                        for table_name, column_name in STRUCTURED_REFERENCE.findall(
                            node.text or ""
                        ):
                            if column_name not in tables.get(table_name, set()):
                                invalid_references.add(f"{table_name}[{column_name}]")

                self.assertEqual(set(), invalid_references, workbook)

    def test_ai_sow_package_is_self_contained(self) -> None:
        plugin_root = REPO_ROOT / "plugins/ai-sow"
        required = [
            ".codex-plugin/plugin.json",
            "pyproject.toml",
            "uv.lock",
            "README.md",
            "runtime/handoff.py",
            "runtime/project_io.py",
            "skills/setup/SKILL.md",
            "skills/generate-sow/SKILL.md",
            "skills/setup/assets/sow-template.xlsx",
            "tests/support/smoke_plugin.py",
            "docs/reference/SOW任务分类与开发交付人天标准_v1.3.md",
            "docs/reference/SOW估算与生成示例_v1.3.xlsx",
        ]
        for relative in required:
            self.assertTrue((plugin_root / relative).is_file(), relative)

    def test_manifest_identity_and_contract_version_match(self) -> None:
        plugin_root = REPO_ROOT / "plugins/ai-sow"
        manifest = json.loads(
            (plugin_root / ".codex-plugin/plugin.json").read_text()
        )
        schema = json.loads(
            (plugin_root / "skills/setup/contracts/project.schema.json").read_text()
        )
        project = json.loads(
            (
                plugin_root
                / "skills/generate-sow/fixtures/project/.ai-sow/project.json"
            ).read_text()
        )
        pyproject_text = (plugin_root / "pyproject.toml").read_text()
        lock_text = (plugin_root / "uv.lock").read_text()
        self.assertEqual(manifest["name"], "ai-sow")
        self.assertEqual(manifest["version"], "0.1.0-beta.2")
        self.assertEqual(schema["properties"]["pluginVersion"]["const"], "0.1.0-beta.2")
        self.assertEqual(project["pluginVersion"], "0.1.0-beta.2")
        self.assertRegex(
            pyproject_text,
            r'(?ms)^\[project\].*?^version = "0\.1\.0b2"$',
        )
        self.assertRegex(
            lock_text,
            r'(?ms)^\[\[package\]\]\nname = "ai-sow-plugin-runtime"\nversion = "0\.1\.0b2"$',
        )
        self.assertEqual(project["sowStandardVersion"], "1.3")

    def test_task_estimation_contract_has_no_removed_shape_or_modes(self) -> None:
        plugin_root = REPO_ROOT / "plugins/ai-sow"
        delivery = json.loads(
            (plugin_root / "skills/generate-story/contracts/delivery.schema.json").read_text()
        )
        estimate = json.loads(
            (plugin_root / "skills/generate-task/contracts/estimate.schema.json").read_text()
        )
        self.assertNotIn("type", delivery["$defs"]["story"]["properties"])
        task_properties = estimate["$defs"]["task"]["properties"]
        for field in (
            "professionalDomain",
            "activity",
            "quantity",
            "taskFamily",
            "baseEffort",
            "complexityFactor",
            "personDays",
        ):
            self.assertNotIn(field, task_properties)
        self.assertNotIn("sitEstimates", estimate["properties"])
        self.assertEqual(
            task_properties["workMode"]["enum"],
            ["新建", "调整", "接入复用"],
        )

    def test_release_assets_and_smoke_implementation_use_plugin_scope(self) -> None:
        plugin_root = REPO_ROOT / "plugins/ai-sow"
        self.assertFalse((REPO_ROOT / "scripts" / "smoke_plugin.py").exists())
        self.assertTrue((plugin_root / "tests/support/smoke_plugin.py").is_file())

    def test_manifest_user_content_is_chinese(self) -> None:
        manifest = json.loads(
            (REPO_ROOT / "plugins/ai-sow/.codex-plugin/plugin.json").read_text(
                encoding="utf-8"
            )
        )
        visible_values = [
            manifest["description"],
            manifest["interface"]["shortDescription"],
            manifest["interface"]["longDescription"],
            *manifest["interface"]["defaultPrompt"],
        ]
        for value in visible_values:
            self.assertRegex(value, HAN_CHARACTER)

    def test_all_skills_resolve_shared_output_language_reference(self) -> None:
        plugin_root = REPO_ROOT / "plugins/ai-sow"
        shared_reference = plugin_root / "references/output-language.md"
        self.assertTrue(shared_reference.is_file(), shared_reference)

        skill_paths = sorted((plugin_root / "skills").glob("*/SKILL.md"))
        self.assertEqual(
            {path.parent.name for path in skill_paths},
            {
                "setup",
                "analyze-requirement",
                "analyze-as-is",
                "generate-design",
                "generate-story",
                "generate-task",
                "generate-sow",
                "reconcile",
            },
        )
        for skill_path in skill_paths:
            declared_references = [
                Path(target)
                for target in re.findall(
                    r"\[[^\]]+\]\(([^)]+)\)",
                    skill_path.read_text(encoding="utf-8"),
                )
                if target.endswith("output-language.md")
            ]
            self.assertEqual(len(declared_references), 1, skill_path)
            resolved = (skill_path.parent / declared_references[0]).resolve()
            self.assertTrue(resolved.is_relative_to(plugin_root.resolve()), resolved)
            self.assertEqual(resolved, shared_reference.resolve())

    def test_open_source_release_files_exist(self) -> None:
        required = [
            "LICENSE",
            "NOTICE",
            "README.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            "SECURITY.md",
            "plugins/ai-sow/LICENSE",
            "plugins/ai-sow/NOTICE",
        ]
        for relative in required:
            self.assertTrue((REPO_ROOT / relative).is_file(), relative)

    def test_repository_relative_markdown_links_resolve(self) -> None:
        completed = subprocess.run(
            ["git", "ls-files", "*.md"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        for relative in completed.stdout.splitlines():
            document = REPO_ROOT / relative
            if not document.is_file():
                continue
            for raw_target in re.findall(
                r"!?(?:\[[^\]]*\])\(([^)]+)\)",
                document.read_text(encoding="utf-8"),
            ):
                target = raw_target.strip()
                if target.startswith("<") and ">" in target:
                    target = target[1 : target.index(">")]
                else:
                    target = target.split(maxsplit=1)[0]
                if target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                target = unquote(target.split("#", 1)[0])
                if not target:
                    continue
                resolved = (document.parent / target).resolve()
                with self.subTest(document=relative, target=target):
                    self.assertTrue(resolved.is_relative_to(REPO_ROOT.resolve()))
                    self.assertTrue(resolved.exists(), resolved)

    def test_public_readme_documents_plugin_lifecycle(self) -> None:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("<repository-url>", text)
        for command in (
            "codex plugin marketplace add InspireChina/ai-plugin-marketplace",
            "codex plugin add ai-sow@ai-plugin-marketplace",
            "codex plugin marketplace upgrade ai-plugin-marketplace",
            "codex plugin remove ai-sow@ai-plugin-marketplace",
            "codex plugin marketplace remove ai-plugin-marketplace",
        ):
            self.assertIn(command, text)

    def test_readme_distinguishes_verified_and_provisional_platforms(self) -> None:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("| macOS | 已验证（`Verified`） |", text)
        self.assertIn("| Windows 11 | 临时支持（`Provisional`） |", text)
        self.assertIn(
            "[Windows 11 验证状态](docs/windows-11-validation.md)",
            text,
        )
        self.assertIn(
            "CI 和合成测试不能作为 Windows 11 实机验收结果。",
            text,
        )

    def test_windows_11_plan_covers_physical_machine_risks_and_evidence(self) -> None:
        plan_path = REPO_ROOT / "docs/windows-11-validation.md"
        self.assertTrue(plan_path.is_file(), plan_path)
        text = plan_path.read_text(encoding="utf-8")
        for required in (
            "Provisional",
            "Windows 11 实机",
            "NTFS 目录联接",
            "重解析点",
            "同文件系统发布",
            "不同内容拒绝覆盖",
            "非 ASCII",
            "长路径",
            ".cmd Git shim",
            "uv",
            "Codex marketplace",
            "已安装插件目录",
            "pytest",
            "setup",
            "五个 Owner validator",
            "generate-sow",
            "Microsoft Excel Desktop",
            "F9",
            "公式缓存值",
            "公式错误",
            "开发者模式",
            "符号链接权限",
            "GitHub Actions",
            "证据记录",
            "合成测试",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

        architecture = (
            REPO_ROOT / "docs/architecture/ai-plugin-marketplace-design.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Windows 11 仍为临时支持（`Provisional`）", architecture)

    def test_public_docs_exclude_internal_execution_plans(self) -> None:
        self.assertFalse((REPO_ROOT / "docs/superpowers/plans").exists())
        self.assertTrue(
            (REPO_ROOT / "docs/architecture/ai-plugin-marketplace-design.md").is_file()
        )

    def test_ci_covers_all_supported_operating_systems(self) -> None:
        text = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for runner in ("ubuntu-latest", "macos-latest", "windows-latest"):
            self.assertIn(runner, text)

    def test_public_text_has_no_private_paths_or_internal_plan(self) -> None:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        )
        home_prefix = str(Path.home().resolve()) + "/"
        forbidden_plan = "2026-08-19-" + "as-is-output-contract.md"
        for raw_path in completed.stdout.split(b"\0"):
            if not raw_path:
                continue
            path = REPO_ROOT / raw_path.decode()
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            self.assertNotIn(home_prefix, text, path)
            self.assertNotIn(forbidden_plan, text, path)

    def test_template_copies_are_identical(self) -> None:
        plugin_root = REPO_ROOT / "plugins/ai-sow"
        paths = [
            plugin_root / "skills/setup/assets/sow-template.xlsx",
            plugin_root / "skills/generate-task/fixtures/sow-template.xlsx",
            plugin_root
            / "skills/generate-sow/fixtures/project/.ai-sow/templates/sow-template.xlsx",
        ]
        hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
        self.assertEqual(hashes, [TEMPLATE_SHA256] * 3)

    def test_markdown_reference_describes_the_v13_estimation_model(self) -> None:
        path = (
            REPO_ROOT
            / "plugins/ai-sow/docs/reference/"
            / "SOW任务分类与开发交付人天标准_v1.3.md"
        )
        text = path.read_text(encoding="utf-8")
        for required in (
            "Epic → Feature → Story → Task",
            "一行 Task 对应一个基础单元实例",
            "新建 / 调整 / 接入复用",
            "K_COMPLEXITY_S",
            "affectsEstimate = true",
            "基础单元目录与 M 档基础人天合并为一张表",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)
        self.assertFalse(path.with_suffix(".docx").exists())

    def test_markdown_reference_lists_all_37_base_units(self) -> None:
        path = (
            REPO_ROOT
            / "plugins/ai-sow/docs/reference/"
            / "SOW任务分类与开发交付人天标准_v1.3.md"
        )
        text = path.read_text(encoding="utf-8")
        effort_section = text.split("### 12.3 推荐 M 档基础人天矩阵", 1)[1]
        effort_section = effort_section.split("### 12.4 Task 表", 1)[0]
        rows = [
            line
            for line in effort_section.splitlines()
            if line.startswith("| ")
            and not line.startswith("| 任务族 ")
            and not line.startswith("|---")
        ]
        self.assertEqual(len(rows), 37)

    def test_schema_hashes_and_enum_values_are_unchanged(self) -> None:
        plugin_root = REPO_ROOT / "plugins/ai-sow"
        for relative, expected_hash in SCHEMA_SHA256.items():
            with self.subTest(schema=relative):
                path = plugin_root / relative
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_hash)
                self.assertEqual(
                    enum_arrays(json.loads(path.read_text(encoding="utf-8"))),
                    SCHEMA_ENUMS[relative],
                )

    def test_marketplace_points_to_ai_sow(self) -> None:
        marketplace = json.loads(
            (REPO_ROOT / ".agents/plugins/marketplace.json").read_text()
        )
        self.assertEqual(marketplace["name"], "ai-plugin-marketplace")
        self.assertEqual(
            marketplace["interface"]["displayName"], "AI Plugin Marketplace"
        )
        ai_sow_entries = [
            entry
            for entry in marketplace["plugins"]
            if entry.get("name") == "ai-sow"
        ]
        self.assertEqual(len(ai_sow_entries), 1)
        self.assertEqual(
            ai_sow_entries[0],
            {
                "name": "ai-sow",
                "source": {
                    "source": "local",
                    "path": "./plugins/ai-sow",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            },
        )

    def test_repository_validator_reports_no_errors(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts/validate_repository.py")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
