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
AI_SOW_LITE_ENTRY = {
    "name": "ai-sow-lite",
    "source": {"source": "local", "path": "./plugins/ai-sow-lite"},
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


def write_valid_ai_sow_lite_release(root: Path) -> Path:
    plugin_root = write_plugin(root, "ai-sow-lite", "0.1.0-alpha.1")
    for relative in (
        "LICENSE", "NOTICE", "README.md", "scripts/lite.py",
        "scripts/bootstrap.sh", "scripts/bootstrap.ps1",
        "runtime/ai_sow_lite/cli.py", "assets/sow-template.xlsx",
        "skills/generate/SKILL.md", "skills/clarify/SKILL.md",
        "tests/support/smoke_plugin.py",
    ):
        path = plugin_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("release fixture\n", encoding="utf-8")
    (plugin_root / "pyproject.toml").write_text(
        '[project]\nname = "ai-sow-lite-runtime"\nversion = "0.1.0a1"\n', encoding="utf-8"
    )
    (plugin_root / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "ai-sow-lite-runtime"\n'
        'version = "0.1.0a1"\nsource = { virtual = "." }\n', encoding="utf-8"
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
    def test_repository_validates_each_plugins_release_identity(self) -> None:
        cases = (
            (".codex-plugin/plugin.json", "0.1.0-alpha.1", "0.1.0", "AI SOW Lite plugin version"),
            (".claude-plugin/plugin.json", "0.1.0-alpha.1", "0.1.0-beta.1", "AI SOW Lite plugin version"),
            ("pyproject.toml", "0.1.0a1", "0.1.0b1", "AI SOW Lite pyproject version"),
            ("pyproject.toml", "ai-sow-lite-runtime", "ai-sow-plugin-runtime", "AI SOW Lite pyproject name"),
            ("uv.lock", "0.1.0a1", "0.1.0b1", "AI SOW Lite uv.lock package version"),
            ("uv.lock", "ai-sow-lite-runtime", "ai-sow-plugin-runtime", "expected one ai-sow-lite-runtime package"),
            ("uv.lock", 'virtual = "."', 'virtual = "../ai-sow"', "AI SOW Lite uv.lock package source"),
        )
        for relative, original, replacement, diagnostic in cases:
            with self.subTest(relative=relative, replacement=replacement), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                write_valid_ai_sow_release(root)
                lite = write_valid_ai_sow_lite_release(root)
                initialize_repository(root, [AI_SOW_ENTRY, AI_SOW_LITE_ENTRY])
                self.assertEqual(validate_repository(root), [])
                target = lite / relative
                target.write_text(target.read_text(encoding="utf-8").replace(original, replacement), encoding="utf-8")
                errors = validate_repository(root)
                self.assertTrue(any(diagnostic in error for error in errors), errors)
                self.assertEqual(validate_ai_sow_release(root, root / "plugins/ai-sow"), [])

    def test_repository_rejects_missing_lite_release_files(self) -> None:
        for relative in ("LICENSE", "NOTICE", "skills/clarify/SKILL.md", "assets/sow-template.xlsx"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                write_valid_ai_sow_release(root)
                lite = write_valid_ai_sow_lite_release(root)
                initialize_repository(root, [AI_SOW_ENTRY, AI_SOW_LITE_ENTRY])
                (lite / relative).unlink()
                self.assertIn(f"missing release file: plugins/ai-sow-lite/{relative}", validate_repository(root))

    def test_repository_rejects_malformed_lite_release_metadata(self) -> None:
        for relative, diagnostic in (("pyproject.toml", "invalid AI SOW Lite pyproject"),
                                     ("uv.lock", "invalid AI SOW Lite lock file")):
            for replacement in (None, b"\xff", b"[", b"", b"package = 1\n"):
                with self.subTest(relative=relative, replacement=replacement), tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    write_valid_ai_sow_release(root)
                    lite = write_valid_ai_sow_lite_release(root)
                    initialize_repository(root, [AI_SOW_ENTRY, AI_SOW_LITE_ENTRY])
                    target = lite / relative
                    if replacement is None:
                        target.unlink()
                    else:
                        target.write_bytes(replacement)
                    errors = validate_repository(root)
                    self.assertTrue(any(diagnostic in error for error in errors), errors)

    def test_repository_rejects_lite_release_file_outside_package(self) -> None:
        for relative in ("assets/sow-template.xlsx", ".codex-plugin/plugin.json",
                         ".claude-plugin/plugin.json", "pyproject.toml", "uv.lock"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                write_valid_ai_sow_release(root)
                lite = write_valid_ai_sow_lite_release(root)
                initialize_repository(root, [AI_SOW_ENTRY, AI_SOW_LITE_ENTRY])
                target = lite / relative
                shared = root / "shared-file"
                target.rename(shared)
                try:
                    target.symlink_to(shared)
                except OSError as exc:
                    self.skipTest(f"symlinks unavailable: {exc}")
                self.assertIn(f"release file escapes plugin: plugins/ai-sow-lite/{relative}", validate_repository(root))

    def test_marketplace_requires_both_release_entries(self) -> None:
        for missing in ("ai-sow", "ai-sow-lite"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                write_valid_ai_sow_release(root)
                write_valid_ai_sow_lite_release(root)
                initialize_repository(root, [entry for entry in (AI_SOW_ENTRY, AI_SOW_LITE_ENTRY) if entry["name"] != missing])
                self.assertIn(f"marketplace must contain exactly one {missing} entry", validate_repository(root))

    def test_marketplace_checks_lite_policy_and_source(self) -> None:
        for field, replacement, diagnostic in (
            ("policy", {}, "ai-sow-lite marketplace policy is invalid"),
            ("category", "Other", "ai-sow-lite category must be Productivity"),
            ("source", {"source": "local", "path": "./plugins/ai-sow"}, "ai-sow-lite source must be ./plugins/ai-sow-lite"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                write_valid_ai_sow_release(root)
                write_valid_ai_sow_lite_release(root)
                initialize_repository(root, [AI_SOW_ENTRY, {**AI_SOW_LITE_ENTRY, field: replacement}])
                self.assertIn(diagnostic, validate_marketplace(root))

    def test_manifest_declared_paths_must_exist_inside_each_plugin(self) -> None:
        for name in ("ai-sow", "ai-sow-lite"):
            with self.subTest(plugin=name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                plugin = write_plugin(root, name, "0.1.0-alpha.1")
                (plugin / "skills").rmdir()
                self.assertIn("manifest skills path does not exist: ./skills", validate_plugin_manifest(root, plugin))

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
            write_valid_ai_sow_lite_release(root)
            write_plugin(root, "sample-plugin", "1.2.3")
            initialize_repository(
                root,
                [
                    AI_SOW_ENTRY,
                    AI_SOW_LITE_ENTRY,
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
