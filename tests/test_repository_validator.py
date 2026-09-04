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
    RENDERER_FINGERPRINT_FILES,
    validate_ai_sow_release,
    validate_claude_marketplace,
    validate_renderer_contract_consistency,
    validate_marketplace,
    validate_marketplace_parity,
    validate_model_efficiency_gate,
    validate_plugin_manifest,
    validate_plugin_manifest_parity,
    validate_publisher_identity,
    validate_repository,
)


AI_SOW_DESCRIPTION = (
    "一次提供 PRD、HLD 和适用的往期 SOW，自动生成或增量更新可追溯的 SOW 工作簿，"
    "并用 LibreOffice 回算后发布。"
)

AI_SOW_ENTRY = {
    "name": "ai-sow",
    "description": AI_SOW_DESCRIPTION,
    "source": {"source": "local", "path": "./plugins/ai-sow"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity",
}

AI_SOW_GENERATE_SUPPORT_FILES = (
    "skills/generate/contracts/action.schema.json",
    "skills/generate/contracts/artifact-approval.schema.json",
    "skills/generate/contracts/common.schema.json",
    "skills/generate/contracts/current.schema.json",
    "skills/generate/contracts/generation-manifest.schema.json",
    "skills/generate/contracts/input-revision.schema.json",
    "skills/generate/contracts/request.schema.json",
    "skills/generate/contracts/review-repair.schema.json",
    "skills/generate/contracts/run-state.schema.json",
    "skills/generate/contracts/sow-model.schema.json",
    "skills/generate/contracts/stage-checkpoint.schema.json",
    "skills/generate/references/acceptance-criteria.md",
    "skills/generate/references/delivery-decomposition.md",
    "skills/generate/references/delivery-lifecycle-policy.md",
    "skills/generate/references/delivery-work-classification.md",
    "skills/generate/references/effective-start-matching.md",
    "skills/generate/references/epic-authoring.md",
    "skills/generate/references/feature-authoring.md",
    "skills/generate/references/layered-review.md",
    "skills/generate/references/source-authority.md",
    "skills/generate/references/story-authoring.md",
    "skills/generate/references/task-authoring.md",
    "skills/generate/references/technical-work-classification.md",
)
AI_SOW_SCHEMA_IDS = {
    name: f"urn:ai-sow:generate:next:{name.removesuffix('.schema.json')}:1"
    for name in (
        "action.schema.json",
        "artifact-approval.schema.json",
        "common.schema.json",
        "current.schema.json",
        "generation-manifest.schema.json",
        "input-revision.schema.json",
        "request.schema.json",
        "review-repair.schema.json",
        "run-state.schema.json",
        "sow-model.schema.json",
        "stage-checkpoint.schema.json",
    )
}


def claude_entry(entry: dict[str, object]) -> dict[str, object]:
    """Project a Codex marketplace entry onto its Claude Code equivalent."""
    source = entry.get("source")
    path = source.get("path") if isinstance(source, dict) else source
    return {
        "name": entry["name"],
        "source": path,
        "description": str(entry.get("description") or f"{entry['name']} 插件"),
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
    codex_manifest = json.loads(
        (plugin_root / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
    )
    codex_manifest["description"] = AI_SOW_DESCRIPTION
    codex_manifest["interface"] = {
        "developerName": "Inspire",
        "shortDescription": "一次输入材料，自动生成和增量更新 SOW。",
        "longDescription": "一次提供 PRD、HLD 和适用的往期 SOW，自动完成范围编译、交付分解和终审，并用 LibreOffice 回算、复读后发布可追溯 SOW。",
        "defaultPrompt": [
            "使用 ai-sow:generate，根据 PRD 和 HLD 创建 Greenfield SOW。",
            "使用 ai-sow:generate，根据 PRD、HLD 和往期 SOW 创建 Brownfield SOW。",
            "使用 ai-sow:generate，用补充输入增量更新现有 SOW。",
        ],
    }
    write_json(plugin_root / ".codex-plugin/plugin.json", codex_manifest)
    claude_manifest = json.loads(
        (plugin_root / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
    )
    claude_manifest["description"] = AI_SOW_DESCRIPTION
    write_json(plugin_root / ".claude-plugin/plugin.json", claude_manifest)
    for relative in (
        "skills/generate/SKILL.md",
        "skills/generate/scripts/bootstrap.sh",
        "skills/generate/scripts/bootstrap.ps1",
        "skills/generate/scripts/orchestrator.py",
        "skills/generate/assets/sow-template.xlsx",
        "tests/support/smoke_plugin.py",
        "tests/contracts/case-manifest.schema.json",
        "tests/fixtures/explicit-architecture/case-manifest.json",
        "docs/reference/SOW任务分类与开发交付人天标准_v1.3.md",
        "docs/reference/SOW估算与生成示例_v1.3.xlsx",
        *AI_SOW_GENERATE_SUPPORT_FILES,
    ):
        path = plugin_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (plugin_root / "pyproject.toml").write_text(
        '[project]\nname = "ai-sow-plugin-runtime"\nversion = "0.1.0b1"\n',
        encoding="utf-8",
    )
    (plugin_root / "uv.lock").write_text(
        'version = 1\nrevision = 3\n\n[[package]]\n'
        'name = "ai-sow-plugin-runtime"\nversion = "0.1.0b1"\n',
        encoding="utf-8",
    )
    write_json(
        plugin_root / "tests/benchmarks/model-efficiency-policy-v1.json",
        {
            "pairedBenchmarkGate": {
                "status": "REQUIRED_NOT_SATISFIED",
                "claimStatus": "FORBIDDEN_UNTIL_VALIDATED_MANIFESTS",
                "baselineManifest": None,
                "candidateManifest": None,
                "comparisonReceipt": None,
            }
        },
    )
    generator_root = plugin_root / "skills/generate"
    renderer_payloads = {
        "scripts/package_renderer.py": b"render package\n",
        "scripts/workbook.py": b"render workbook\n",
        "scripts/office_engine.py": b"run office engine\n",
        "scripts/story_notes.py": b"project story notes\n",
    }
    for relative, payload in renderer_payloads.items():
        path = generator_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    for name, schema_id in AI_SOW_SCHEMA_IDS.items():
        value: dict[str, object] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": schema_id,
            "type": "object",
        }
        if name == "generation-manifest.schema.json":
            value["required"] = [
                "sowModelSha256",
                "stageCheckpointSha256s",
                "reviewDecisionSha256",
                "artifactManifestSha256",
                "approvalSha256",
                "templateSha256",
                "effectivePolicyDecisionSha256",
                "workbookSha256",
                "notesSha256",
            ]
            value["properties"] = {
                "rendererContract": {"const": "generation-renderer-v8"}
            }
        write_json(generator_root / "contracts" / name, value)
    (generator_root / "scripts/generation_store.py").touch()
    write_json(
        generator_root / "contracts/renderer-fingerprint-baseline.json",
        {
            "rendererContract": "generation-renderer-v8",
            "files": {
                relative: hashlib.sha256(payload).hexdigest()
                for relative, payload in renderer_payloads.items()
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
    def test_satisfied_model_efficiency_gate_requires_real_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin_root = Path(temp_dir) / "plugins/ai-sow"
            write_json(
                plugin_root / "tests/benchmarks/model-efficiency-policy-v1.json",
                {
                    "pairedBenchmarkGate": {
                        "status": "SATISFIED",
                        "claimStatus": "ALLOWED_AFTER_TARGET_EVALUATION",
                        "baselineManifest": "tests/benchmarks/baseline/manifest.json",
                        "candidateManifest": "tests/benchmarks/candidate/manifest.json",
                        "comparisonReceipt": {
                            "path": "tests/benchmarks/comparison.json",
                            "sha256": "a" * 64,
                        },
                    }
                },
            )

            errors = validate_model_efficiency_gate(plugin_root)

            self.assertIn(
                "model efficiency baselineManifest evidence is missing", errors
            )
            self.assertIn(
                "model efficiency candidateManifest evidence is missing", errors
            )
            self.assertIn(
                "model efficiency comparisonReceipt evidence is missing", errors
            )

    def test_repository_validator_uses_generate_renderer_baseline(self) -> None:
        self.assertEqual(
            RENDERER_FINGERPRINT_FILES,
            (
                "scripts/package_renderer.py",
                "scripts/workbook.py",
                "scripts/office_engine.py",
                "scripts/story_notes.py",
            ),
        )

    def test_ai_sow_release_rejects_staged_manifest_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_valid_ai_sow_release(root)
            initialize_repository(root, [AI_SOW_ENTRY])
            manifest_path = plugin_root / ".codex-plugin/plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["interface"]["longDescription"] = "七阶段生成 SOW。"
            manifest["interface"]["defaultPrompt"][0] = "请指导我进入下一阶段。"
            write_json(manifest_path, manifest)

            errors = validate_ai_sow_release(root, plugin_root)

            self.assertIn(
                "AI SOW longDescription must advertise one automatic generate flow",
                errors,
            )
            self.assertIn(
                "AI SOW defaultPrompt must only advertise ai-sow:generate",
                errors,
            )

    def test_renderer_fingerprint_matches_the_current_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_valid_ai_sow_release(root)

            self.assertEqual(
                validate_renderer_contract_consistency(root, plugin_root),
                [],
            )

    def test_renderer_fingerprint_rejects_changed_projection_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_valid_ai_sow_release(root)
            workbook = (
                plugin_root / "skills/generate/scripts/workbook.py"
            )
            workbook.write_bytes(workbook.read_bytes() + b"changed projection\n")

            errors = validate_renderer_contract_consistency(root, plugin_root)

            self.assertTrue(
                any(
                    "renderer fingerprint mismatch for "
                    "plugins/ai-sow/skills/generate/scripts/workbook.py"
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

    def test_ai_sow_release_requires_cutover_contracts_and_references(self) -> None:
        for relative in AI_SOW_GENERATE_SUPPORT_FILES:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                plugin_root = write_valid_ai_sow_release(root)
                (plugin_root / relative).unlink()

                self.assertIn(
                    f"missing release file: plugins/ai-sow/{relative}",
                    validate_ai_sow_release(root, plugin_root),
                )

    def test_ai_sow_release_requires_exact_cutover_schema_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_valid_ai_sow_release(root)
            path = plugin_root / "skills/generate/contracts/action.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema["$id"] = "urn:ai-sow:generate:action:legacy"
            write_json(path, schema)

            self.assertIn(
                "AI SOW contract action.schema.json must use $id "
                "urn:ai-sow:generate:next:action:1",
                validate_ai_sow_release(root, plugin_root),
            )

    def test_ai_sow_release_requires_generation_proof_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_valid_ai_sow_release(root)
            path = plugin_root / "skills/generate/contracts/generation-manifest.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema["required"].remove("approvalSha256")
            write_json(path, schema)

            self.assertIn(
                "generation manifest must require the v2 self-contained proof closure",
                validate_ai_sow_release(root, plugin_root),
            )

    def test_ai_sow_release_rejects_legacy_schema_or_extra_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_root = write_valid_ai_sow_release(root)
            legacy = plugin_root / "skills/setup/SKILL.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("legacy", encoding="utf-8")
            write_json(
                plugin_root / "skills/generate/contracts/run-plan.schema.json",
                {"$id": "urn:ai-sow:generate:run-plan:1"},
            )

            errors = validate_ai_sow_release(root, plugin_root)

            self.assertIn(
                "AI SOW public skills must be exactly ['generate'], found ['generate', 'setup']",
                errors,
            )
            self.assertTrue(
                any(error.startswith("AI SOW contract set must be") for error in errors)
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
