from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_repository import (
    validate_ai_sow_release,
    validate_marketplace,
    validate_plugin_manifest,
    validate_repository,
)


AI_SOW_ENTRY = {
    "name": "ai-sow",
    "source": {"source": "local", "path": "./plugins/ai-sow"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity",
}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_plugin(root: Path, name: str, version: str) -> Path:
    plugin_root = root / "plugins" / name
    write_json(
        plugin_root / ".codex-plugin/plugin.json",
        {"name": name, "version": version, "skills": "./skills"},
    )
    (plugin_root / "skills").mkdir(parents=True)
    return plugin_root


def write_valid_ai_sow_release(root: Path) -> Path:
    plugin_root = write_plugin(root, "ai-sow", "0.1.0-beta.1")
    for relative in (
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
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


class RepositoryValidatorTests(unittest.TestCase):
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
                "0.1.0-beta.1+build.5",
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
            write_plugin(root, "ai-sow", "0.1.0-beta.1")
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
                "sample-plugin: plugin version must use MAJOR.MINOR.PATCH semver",
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
                "AI SOW plugin version must be 0.1.0-beta.1",
                validate_ai_sow_release(root, plugin_root),
            )

    def test_ai_sow_release_reports_missing_and_malformed_inputs(self) -> None:
        cases = (
            (
                "manifest missing",
                ".codex-plugin/plugin.json",
                None,
                "invalid AI SOW plugin manifest:",
            ),
            (
                "manifest malformed",
                ".codex-plugin/plugin.json",
                "{",
                "invalid AI SOW plugin manifest:",
            ),
            (
                "manifest non-UTF-8",
                ".codex-plugin/plugin.json",
                b"\xff",
                "invalid AI SOW plugin manifest:",
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


if __name__ == "__main__":
    unittest.main()
