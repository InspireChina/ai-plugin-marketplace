from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_repository import (
    validate_ai_sow_release,
    validate_claude_marketplace,
    validate_generator_contract_consistency,
    validate_marketplace,
    validate_marketplace_parity,
    validate_plugin_manifest,
    validate_plugin_manifest_parity,
    validate_publisher_identity,
    validate_repository,
)


AI_SOW_ENTRY = {
    "name": "ai-sow",
    "source": {"source": "local", "path": "./plugins/ai-sow"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity",
}


def claude_entry(entry: dict[str, object]) -> dict[str, object]:
    """Project a Codex marketplace entry onto its Claude Code equivalent."""
    source = entry.get("source")
    path = source.get("path") if isinstance(source, dict) else source
    return {
        "name": entry["name"],
        "source": path,
        "description": f"{entry['name']} 插件",
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_plugin(root: Path, name: str, version: str) -> Path:
    plugin_root = root / "plugins" / name
    manifest = {
        "name": name,
        "version": version,
        "description": f"{name} 插件",
        "author": {"name": "Inspire"},
        "skills": "./skills",
    }
    write_json(
        plugin_root / ".codex-plugin/plugin.json",
        {**manifest, "interface": {"developerName": "Inspire"}},
    )
    write_json(plugin_root / ".claude-plugin/plugin.json", manifest)
    (plugin_root / "skills").mkdir(parents=True)
    return plugin_root


def write_valid_ai_sow_release(root: Path) -> Path:
    plugin_root = write_plugin(root, "ai-sow", "0.1.0-beta.1")
    for relative in (
        "assets/sow-template.xlsx",
        "tests/support/smoke_plugin.py",
        "docs/reference/SOW任务分类与开发交付人天标准_v1.3.md",
        "docs/reference/SOW估算与生成示例_v1.3.xlsx",
    ):
        path = plugin_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    write_json(
        plugin_root / "skills/generate-sow/fixtures/project/.ai-sow/project.json",
        {
            "projectId": "validator-fixture",
            "name": "Validator Fixture",
            "pluginVersion": "0.1.0-beta.1",
            "sowStandardVersion": "1.3",
        },
    )
    (plugin_root / "pyproject.toml").write_text(
        '[project]\nname = "ai-sow-plugin-runtime"\nversion = "0.1.0b1"\n',
        encoding="utf-8",
    )
    (plugin_root / "uv.lock").write_text(
        'version = 1\nrevision = 3\n\n[[package]]\n'
        'name = "ai-sow-plugin-runtime"\nversion = "0.1.0b1"\n',
        encoding="utf-8",
    )
    generator_root = plugin_root / "skills/generate-sow"
    generator_payloads = {
        "scripts/generate_sow.py": b"generate sow\n",
        "scripts/workbook.py": b"render workbook\n",
    }
    for relative, payload in generator_payloads.items():
        path = generator_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    write_json(
        generator_root / "contracts/manifest.schema.json",
        {
            "type": "object",
            "properties": {
                "generatorContract": {"const": "receipt-only-v2"},
            },
        },
    )
    write_json(
        generator_root / "contracts/generator-fingerprint-baseline.json",
        {
            "generatorContract": "receipt-only-v2",
            "files": {
                relative: hashlib.sha256(payload).hexdigest()
                for relative, payload in generator_payloads.items()
            },
        },
    )
    return plugin_root


def initialize_repository(root: Path, entries: list[dict[str, object]]) -> None:
    write_json(
        root / ".agents/plugins/marketplace.json",
        {
            "name": "ai-plugin-marketplace",
            "interface": {"displayName": "AI Plugin Marketplace"},
            "plugins": entries,
        },
    )
    write_json(
        root / ".claude-plugin/marketplace.json",
        {
            "name": "ai-plugin-marketplace",
            "owner": {"name": "Inspire"},
            "plugins": [claude_entry(entry) for entry in entries],
        },
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


class RepositoryValidatorTests(unittest.TestCase):
    def test_current_generator_projection_declares_v4_everywhere(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        generator_root = repo_root / "plugins/ai-sow/skills/generate-sow"
        manifest = json.loads(
            (generator_root / "contracts/manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        baseline = json.loads(
            (generator_root / "contracts/generator-fingerprint-baseline.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            manifest["properties"]["generatorContract"]["const"],
            "receipt-only-v4",
        )
        self.assertEqual(baseline["generatorContract"], "receipt-only-v4")

    def test_generator_fingerprint_matches_the_current_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_valid_ai_sow_release(root)

            self.assertEqual(
                validate_generator_contract_consistency(root, plugin_root),
                [],
            )

    def test_generator_fingerprint_rejects_changed_projection_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_valid_ai_sow_release(root)
            workbook = (
                plugin_root / "skills/generate-sow/scripts/workbook.py"
            )
            workbook.write_bytes(workbook.read_bytes() + b"changed projection\n")

            errors = validate_generator_contract_consistency(root, plugin_root)

            self.assertTrue(
                any(
                    "generator fingerprint mismatch for "
                    "plugins/ai-sow/skills/generate-sow/scripts/workbook.py"
                    in error
                    for error in errors
                ),
                errors,
            )

    def test_marketplace_accepts_ai_sow_and_another_valid_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_valid_ai_sow_release(root)
            write_plugin(root, "sample-plugin", "1.2.3")
            initialize_repository(
                root,
                [
                    AI_SOW_ENTRY,
                    {
                        "name": "sample-plugin",
                        "source": {
                            "source": "local",
                            "path": "./plugins/sample-plugin",
                        },
                    },
                ],
            )

            self.assertEqual(validate_repository(root), [])

    def test_generic_manifest_accepts_any_semver(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_plugin(
                root,
                "sample-plugin",
                "1.2.3-rc.4+build.5",
            )

            self.assertEqual(validate_plugin_manifest(root, plugin_root), [])

    def test_marketplace_rejects_a_missing_plugin_source_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_json(
                root / ".agents/plugins/marketplace.json",
                {
                    "name": "ai-plugin-marketplace",
                    "interface": {"displayName": "AI Plugin Marketplace"},
                    "plugins": [AI_SOW_ENTRY],
                },
            )

            self.assertIn(
                "marketplace plugin ai-sow source directory is missing",
                validate_marketplace(root),
            )

    def test_marketplace_reports_malformed_and_duplicate_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_plugin(root, "ai-sow", "0.1.0")
            write_json(
                root / ".agents/plugins/marketplace.json",
                {
                    "name": "ai-plugin-marketplace",
                    "interface": {"displayName": "AI Plugin Marketplace"},
                    "plugins": [
                        AI_SOW_ENTRY,
                        {"name": "alias", "source": AI_SOW_ENTRY["source"]},
                        {"name": "broken", "source": "./plugins/broken"},
                    ],
                },
            )

            errors = validate_marketplace(root)
            self.assertIn(
                "duplicate marketplace plugin source: ./plugins/ai-sow",
                errors,
            )
            self.assertIn(
                "marketplace plugin alias name must match source directory ai-sow",
                errors,
            )
            self.assertIn(
                "marketplace plugin broken source must be an object",
                errors,
            )

    def test_marketplace_reports_non_utf8_json_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            marketplace = root / ".agents/plugins/marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_bytes(b"\xff")

            errors = validate_marketplace(root)

            self.assertEqual(len(errors), 1)
            self.assertTrue(
                errors[0].startswith("invalid marketplace manifest:"), errors
            )

    def test_repository_validates_every_marketplace_plugin_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_valid_ai_sow_release(root)
            write_plugin(root, "sample-plugin", "not-semver")
            initialize_repository(
                root,
                [
                    AI_SOW_ENTRY,
                    {
                        "name": "sample-plugin",
                        "source": {
                            "source": "local",
                            "path": "./plugins/sample-plugin",
                        },
                    },
                ],
            )

            self.assertIn(
                "sample-plugin (.codex-plugin/plugin.json): plugin version must use "
                "MAJOR.MINOR.PATCH semver",
                validate_repository(root),
            )

    def test_generic_manifest_reports_non_utf8_json_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = root / "plugins/sample-plugin"
            manifest = plugin_root / ".codex-plugin/plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_bytes(b"\xff")

            errors = validate_plugin_manifest(root, plugin_root)

            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].startswith("invalid plugin manifest:"), errors)

    def test_ai_sow_version_is_a_release_specific_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_valid_ai_sow_release(root)
            write_json(
                plugin_root / ".codex-plugin/plugin.json",
                {"name": "ai-sow", "version": "9.9.9", "skills": "./skills"},
            )

            self.assertEqual(validate_plugin_manifest(root, plugin_root), [])
            self.assertIn(
                "AI SOW plugin version in .codex-plugin/plugin.json must be 0.1.0-beta.1",
                validate_ai_sow_release(root, plugin_root),
            )

    def test_ai_sow_release_reports_missing_and_malformed_inputs(self) -> None:
        cases = (
            (
                "manifest missing",
                ".codex-plugin/plugin.json",
                None,
                "invalid AI SOW plugin manifest .codex-plugin/plugin.json:",
            ),
            (
                "manifest malformed",
                ".codex-plugin/plugin.json",
                "{",
                "invalid AI SOW plugin manifest .codex-plugin/plugin.json:",
            ),
            (
                "manifest non-UTF-8",
                ".codex-plugin/plugin.json",
                b"\xff",
                "invalid AI SOW plugin manifest .codex-plugin/plugin.json:",
            ),
            (
                "fixture missing",
                "skills/generate-sow/fixtures/project/.ai-sow/project.json",
                None,
                "invalid AI SOW fixture project:",
            ),
            (
                "fixture malformed",
                "skills/generate-sow/fixtures/project/.ai-sow/project.json",
                "{",
                "invalid AI SOW fixture project:",
            ),
            (
                "fixture non-UTF-8",
                "skills/generate-sow/fixtures/project/.ai-sow/project.json",
                b"\xff",
                "invalid AI SOW fixture project:",
            ),
            (
                "pyproject missing",
                "pyproject.toml",
                None,
                "invalid AI SOW pyproject:",
            ),
            (
                "pyproject malformed",
                "pyproject.toml",
                "[project\n",
                "invalid AI SOW pyproject:",
            ),
            (
                "pyproject non-UTF-8",
                "pyproject.toml",
                b"\xff",
                "invalid AI SOW pyproject:",
            ),
            (
                "lock missing",
                "uv.lock",
                None,
                "invalid AI SOW lock file:",
            ),
            (
                "lock malformed",
                "uv.lock",
                "[[package]\n",
                "invalid AI SOW lock file:",
            ),
            (
                "lock non-UTF-8",
                "uv.lock",
                b"\xff",
                "invalid AI SOW lock file:",
            ),
        )
        for name, relative, replacement, diagnostic in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                plugin_root = write_valid_ai_sow_release(root)
                target = plugin_root / relative
                if replacement is None:
                    target.unlink()
                elif isinstance(replacement, bytes):
                    target.write_bytes(replacement)
                else:
                    target.write_text(replacement, encoding="utf-8")

                errors = validate_ai_sow_release(root, plugin_root)
                self.assertTrue(
                    any(error.startswith(diagnostic) for error in errors),
                    errors,
                )

    def test_ai_sow_release_reports_missing_assets_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_valid_ai_sow_release(root)
            missing = plugin_root / "tests/support/smoke_plugin.py"
            missing.unlink()

            self.assertIn(
                "missing release file: plugins/ai-sow/tests/support/smoke_plugin.py",
                validate_ai_sow_release(root, plugin_root),
            )

            formal_template = plugin_root / "assets/sow-template.xlsx"
            formal_template.unlink()
            self.assertIn(
                "missing release file: plugins/ai-sow/assets/sow-template.xlsx",
                validate_ai_sow_release(root, plugin_root),
            )


    def test_claude_marketplace_requires_owner_and_resolvable_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_plugin(root, "ai-sow", "0.1.0")
            write_json(
                root / ".claude-plugin/marketplace.json",
                {
                    "name": "ai-plugin-marketplace",
                    "plugins": [
                        {"name": "ai-sow", "source": "./plugins/ai-sow"},
                        {"name": "alias", "source": "./plugins/ai-sow"},
                        {"name": "missing", "source": "./plugins/missing"},
                        {"name": "escaping", "source": "../outside"},
                    ],
                },
            )

            errors = validate_claude_marketplace(root)
            self.assertIn("Claude marketplace owner must declare a name", errors)
            self.assertIn(
                "Claude marketplace plugin alias name must match source directory ai-sow",
                errors,
            )
            self.assertIn(
                "Claude marketplace plugin missing source directory is missing",
                errors,
            )
            self.assertIn(
                "Claude marketplace plugin escaping path escapes the repository",
                errors,
            )

    def test_marketplace_parity_detects_diverging_plugin_sets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_plugin(root, "ai-sow", "0.1.0")
            write_plugin(root, "sample-plugin", "1.2.3")
            write_json(
                root / ".agents/plugins/marketplace.json",
                {
                    "name": "ai-plugin-marketplace",
                    "interface": {"displayName": "AI Plugin Marketplace"},
                    "plugins": [AI_SOW_ENTRY],
                },
            )
            write_json(
                root / ".claude-plugin/marketplace.json",
                {
                    "name": "ai-plugin-marketplace",
                    "owner": {"name": "Inspire"},
                    "plugins": [
                        claude_entry(AI_SOW_ENTRY),
                        {"name": "sample-plugin", "source": "./plugins/sample-plugin"},
                    ],
                },
            )

            errors = validate_marketplace_parity(root)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("sample-plugin@plugins/sample-plugin", errors[0])

    def test_plugin_manifest_parity_detects_release_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_plugin(root, "ai-sow", "0.1.0")
            self.assertEqual(validate_plugin_manifest_parity(plugin_root), [])

            write_json(
                plugin_root / ".claude-plugin/plugin.json",
                {"name": "ai-sow", "version": "9.9.9", "description": "漂移"},
            )

            self.assertEqual(
                validate_plugin_manifest_parity(plugin_root),
                [
                    "Codex and Claude plugin manifests disagree on version",
                    "Codex and Claude plugin manifests disagree on description",
                    "Codex and Claude plugin manifests disagree on author",
                ],
            )


    def test_publisher_identity_must_be_uniform_across_host_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_valid_ai_sow_release(root)
            initialize_repository(root, [AI_SOW_ENTRY])
            self.assertEqual(validate_publisher_identity(root, plugin_root), [])

            write_json(
                plugin_root / ".claude-plugin/plugin.json",
                {
                    "name": "ai-sow",
                    "version": "0.1.0",
                    "description": "ai-sow 插件",
                    "author": {"name": "Someone Else"},
                },
            )
            write_json(
                root / ".claude-plugin/marketplace.json",
                {
                    "name": "ai-plugin-marketplace",
                    "plugins": [claude_entry(AI_SOW_ENTRY)],
                },
            )

            errors = validate_publisher_identity(root, plugin_root)
            self.assertIn(
                ".claude-plugin/plugin.json author.name must be Inspire, "
                "found 'Someone Else'",
                errors,
            )
            self.assertIn(
                ".claude-plugin/marketplace.json owner.name must be Inspire, found None",
                errors,
            )


if __name__ == "__main__":
    unittest.main()
