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
    "skills/analyze-as-is/contracts/asis.schema.json": "41532288016eb4c0b30843be6ef9df6c3786381e09353cae6bfa25c5ba49497b",
    "skills/analyze-requirement/contracts/source-requirements.schema.json": "8ca6d9738ba0eeebe253d5d7e3bd164c019a54bc318b536012e6a6b5f3bf4e98",
    "skills/generate-design/contracts/technical-requirements.schema.json": "b1988feebe12d86c9af3da02200aa40311376dd604143245891256267ab12583",
    "skills/generate-design/contracts/design.schema.json": "a28fe5d9107f411ff582c4145e2b2e89403f4bdad09cf72f4a0d03501c2f089d",
    "skills/generate-sow/contracts/manifest.schema.json": "568a944b9d64728b4bfd39f00c746f5fa512f19206403f778a880e8347afcf55",
    "skills/generate-story/contracts/delivery.schema.json": "04cfc549cc61ec6d39080735f19dd7e68246d47df7be34f07948faf0f167e0d6",
    "skills/generate-task/contracts/estimate.schema.json": "a1b5bbd829fc9bc5b2f3de29a0c07bd1f5daee81950cfc00fe47781701f35116",
    "skills/setup/contracts/project.schema.json": "ef74010eec8f68ad81030338daa12393caa8d27d2ca6b715933f35c35bc514d3",
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

TEMPLATE_SHA256 = "6d3e97f08c98139a2f64502460c4bb88265b8aca572e991f9c662016edfa6049"


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
            ".claude-plugin/plugin.json",
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

        for document in plugin_root.rglob("*.md"):
            if ".venv" in document.parts:
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
                with self.subTest(document=document, target=target):
                    self.assertTrue(resolved.is_relative_to(plugin_root.resolve()))
                    self.assertTrue(resolved.exists(), resolved)

    def test_manifest_identity_and_contract_version_match(self) -> None:
        plugin_root = REPO_ROOT / "plugins/ai-sow"
        release_version = "0.1.0"
        manifest = json.loads(
            (plugin_root / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
        )
        schema = json.loads(
            (plugin_root / "skills/setup/contracts/project.schema.json").read_text(encoding="utf-8")
        )
        project = json.loads(
            (
                plugin_root
                / "skills/generate-sow/fixtures/project/.ai-sow/project.json"
            ).read_text(encoding="utf-8")
        )
        package_schema = json.loads(
            (plugin_root / "skills/generate-sow/contracts/manifest.schema.json").read_text(encoding="utf-8")
        )
        pyproject_text = (plugin_root / "pyproject.toml").read_text(encoding="utf-8")
        lock_text = (plugin_root / "uv.lock").read_text(encoding="utf-8")
        self.assertEqual(manifest["name"], "ai-sow")
        self.assertEqual(manifest["version"], release_version)
        self.assertEqual(schema["properties"]["pluginVersion"]["const"], release_version)
        self.assertEqual(project["pluginVersion"], release_version)
        self.assertEqual(
            package_schema["properties"]["pluginVersion"]["const"], release_version
        )
        self.assertRegex(
            pyproject_text,
            r'(?ms)^\[project\].*?^version = "0\.1\.0"$',
        )
        self.assertRegex(
            lock_text,
            r'(?ms)^\[\[package\]\]\nname = "ai-sow-plugin-runtime"\nversion = "0\.1\.0"$',
        )
        self.assertEqual(project["sowStandardVersion"], "1.3")
        for relative in (
            "README.md",
            "CHANGELOG.md",
            "SECURITY.md",
            "docs/architecture/ai-plugin-marketplace-design.md",
            "plugins/ai-sow/README.md",
            "plugins/ai-sow/docs/AI_SOW_PLUGIN_DESIGN.md",
            "plugins/ai-sow/docs/reference/SOW任务分类与开发交付人天标准_v1.3.md",
        ):
            self.assertIn(
                release_version,
                (REPO_ROOT / relative).read_text(encoding="utf-8"),
                relative,
            )
        for relative in (
            "plugins/ai-sow/skills/setup/scripts/setup.py",
            "plugins/ai-sow/skills/generate-sow/scripts/generate_sow.py",
        ):
            self.assertIn(
                f'PLUGIN_VERSION = "{release_version}"',
                (REPO_ROOT / relative).read_text(encoding="utf-8"),
                relative,
            )

    def test_user_install_docs_match_bootstrapped_runtime(self) -> None:
        expected = {
            "README.md": "无需预装 Git、Python",
            "CONTRIBUTING.md": "普通插件用户由 `setup` 自动准备隔离运行时",
            "docs/architecture/ai-plugin-marketplace-design.md": "普通插件用户无需预装 uv、Python",
            "plugins/ai-sow/README.md": "不要求 uv 位于 PATH",
            "plugins/ai-sow/docs/CONTEXT.md": "普通用户无需预装 Python/uv",
            "plugins/ai-sow/references/runtime-environment.md": "普通插件用户无需预装 Python、`uv`",
        }
        for relative, statement in expected.items():
            self.assertIn(
                statement,
                (REPO_ROOT / relative).read_text(encoding="utf-8"),
                relative,
            )

        runtime_contract = (
            REPO_ROOT / "plugins/ai-sow/references/runtime-environment.md"
        ).read_text(encoding="utf-8")
        self.assertIn("<plugin-root>/.venv/bin/python", runtime_contract)
        self.assertIn("<plugin-root>/.venv/Scripts/python.exe", runtime_contract)

    def test_task_estimation_contract_has_no_removed_shape_or_modes(self) -> None:
        plugin_root = REPO_ROOT / "plugins/ai-sow"
        delivery = json.loads(
            (plugin_root / "skills/generate-story/contracts/delivery.schema.json").read_text(encoding="utf-8")
        )
        estimate = json.loads(
            (plugin_root / "skills/generate-task/contracts/estimate.schema.json").read_text(encoding="utf-8")
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
        claude_manifest = json.loads(
            (REPO_ROOT / "plugins/ai-sow/.claude-plugin/plugin.json").read_text(
                encoding="utf-8"
            )
        )
        claude_marketplace = json.loads(
            (REPO_ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
        )
        visible_values.append(claude_manifest["description"])
        visible_values.extend(
            entry["description"] for entry in claude_marketplace["plugins"]
        )
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
            text=True, encoding="utf-8",
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

    def test_repository_pins_line_endings_for_windows_checkouts(self) -> None:
        """Git for Windows defaults to core.autocrlf=true; a CRLF checkout breaks
        bootstrap.sh and changes the schema bytes the SHA-256 assertions pin."""
        attributes = REPO_ROOT / ".gitattributes"
        self.assertTrue(attributes.is_file(), attributes)
        self.assertIn("* text=auto eol=lf", attributes.read_text(encoding="utf-8"))

        probes = (
            "plugins/ai-sow/skills/setup/scripts/bootstrap.sh",
            "plugins/ai-sow/skills/setup/contracts/project.schema.json",
            "plugins/ai-sow/skills/setup/assets/sow-template.xlsx",
        )
        completed = subprocess.run(
            ["git", "check-attr", "eol", "binary", "--", *probes],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        resolved = completed.stdout
        for relative in probes[:2]:
            self.assertIn(f"{relative}: eol: lf", resolved)
        self.assertIn(f"{probes[2]}: binary: set", resolved)

        for relative in probes[:2]:
            self.assertNotIn(b"\r\n", (REPO_ROOT / relative).read_bytes(), relative)

    def test_publisher_identity_is_uniform(self) -> None:
        publisher = "Inspire"
        codex = json.loads(
            (REPO_ROOT / "plugins/ai-sow/.codex-plugin/plugin.json").read_text(
                encoding="utf-8"
            )
        )
        claude = json.loads(
            (REPO_ROOT / "plugins/ai-sow/.claude-plugin/plugin.json").read_text(
                encoding="utf-8"
            )
        )
        marketplace = json.loads(
            (REPO_ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(codex["author"]["name"], publisher)
        self.assertEqual(codex["interface"]["developerName"], publisher)
        self.assertEqual(claude["author"]["name"], publisher)
        self.assertEqual(marketplace["owner"]["name"], publisher)

        for relative in ("NOTICE", "plugins/ai-sow/NOTICE"):
            notice = (REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(f"Copyright 2026 {publisher}", notice, relative)

    def test_public_readme_documents_claude_code_lifecycle(self) -> None:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for command in (
            "/plugin marketplace add InspireChina/ai-plugin-marketplace",
            "/plugin install ai-sow@ai-plugin-marketplace",
            "/plugin marketplace update ai-plugin-marketplace",
            "/plugin uninstall ai-sow@ai-plugin-marketplace",
            "/plugin marketplace remove ai-plugin-marketplace",
        ):
            self.assertIn(command, text)

    def test_claude_marketplace_matches_codex_marketplace(self) -> None:
        claude = json.loads(
            (REPO_ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
        )
        codex = json.loads(
            (REPO_ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(claude["name"], codex["name"])
        self.assertTrue(claude["owner"]["name"].strip())
        self.assertEqual(
            {entry["name"] for entry in claude["plugins"]},
            {entry["name"] for entry in codex["plugins"]},
        )
        ai_sow_entries = [
            entry for entry in claude["plugins"] if entry.get("name") == "ai-sow"
        ]
        self.assertEqual(len(ai_sow_entries), 1)
        self.assertEqual(ai_sow_entries[0]["source"], "./plugins/ai-sow")

    def test_plugin_manifests_declare_one_release_identity(self) -> None:
        plugin_root = REPO_ROOT / "plugins/ai-sow"
        codex = json.loads(
            (plugin_root / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
        )
        claude = json.loads(
            (plugin_root / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
        )
        for field in ("name", "version", "description"):
            self.assertEqual(codex[field], claude[field], field)
        self.assertEqual(claude["name"], "ai-sow")

    def test_public_docs_exclude_internal_execution_plans(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8").split("\0")
        self.assertFalse(
            any(
                path.startswith((".superpowers/", "docs/superpowers/"))
                for path in tracked
            )
        )
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
            (REPO_ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
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
            text=True, encoding="utf-8",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
