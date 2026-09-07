#!/usr/bin/env python3
"""Validate public marketplace structure and release metadata."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

RELEASE_VERSION = "0.1.0-beta.2"
PYTHON_RUNTIME_VERSION = "0.1.0b2"
SOW_STANDARD_VERSION = "1.3"
MARKETPLACE_NAME = "ai-plugin-marketplace"
PUBLISHER_NAME = "Inspire"
AI_SOW_DESCRIPTION = '每次仅根据明确提供的 PRD、HLD 和适用往期 SOW，完整编译并逐阶段评审可追溯的 SOW 工作簿，经 LibreOffice 双复读和全部可见 Sheet 视觉评审后请求批准发布。'
CODEX_MARKETPLACE = ".agents/plugins/marketplace.json"
CLAUDE_MARKETPLACE = ".claude-plugin/marketplace.json"
CODEX_PLUGIN_MANIFEST = ".codex-plugin/plugin.json"
CLAUDE_PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\."
    r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
TEXT_SUFFIXES = {
    "",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
FORBIDDEN_PUBLIC_TEXT = (
    "2026-08-19-" + "as-is-output-contract.md",
    "-----BEGIN OPENSSH " + "PRIVATE KEY-----",
    "-----BEGIN " + "PRIVATE KEY-----",
)
RENDERER_FINGERPRINT_FILES = (
    "scripts/package_renderer.py",
    "scripts/workbook.py",
    "scripts/office_engine.py",
    "scripts/story_notes.py",
)
AI_SOW_GENERATE_SUPPORT_FILES = (
    "skills/generate/contracts/action.schema.json",
    "skills/generate/contracts/candidate-repair.schema.json",
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
    "skills/generate/prompts/candidate-patch.md",
    "skills/generate/references/candidate-repair-v1.md",
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
AI_SOW_SCHEMA_IDS = {'action.schema.json': 'urn:ai-sow:generate:next:action:1',
 'artifact-repair-authorization.schema.json': 'urn:ai-sow:generate:next:artifact-repair-authorization:1',
 'artifact-approval.schema.json': 'urn:ai-sow:generate:next:artifact-approval:1',
 'change-graph.schema.json': 'urn:ai-sow:generate:next:change-graph:1',
 'candidate-repair.schema.json': 'urn:ai-sow:generate:next:candidate-repair:1',
 'common.schema.json': 'urn:ai-sow:generate:next:common:1',
 'current.schema.json': 'urn:ai-sow:generate:next:current:1',
 'fact-decision.schema.json': 'urn:ai-sow:generate:next:fact-decision:1',
 'generation-manifest.schema.json': 'urn:ai-sow:generate:next:generation-manifest:1',
 'input-revision.schema.json': 'urn:ai-sow:generate:next:input-revision:1',
 'owner-clarification.schema.json': 'urn:ai-sow:generate:next:owner-clarification:1',
 'owner-repair-authorization.schema.json': 'urn:ai-sow:generate:next:owner-repair-authorization:1',
 'prior-state-decision.schema.json': 'urn:ai-sow:generate:next:prior-state-decision:1',
 'prior-state-decision-v2.schema.json': 'urn:ai-sow:generate:next:prior-state-decision:2',
 'prior-state-snapshot.schema.json': 'urn:ai-sow:generate:next:prior-state-snapshot:1',
 'prototype-observation.schema.json': 'urn:ai-sow:generate:next:prototype-observation:1',
 'prototype-scenario.schema.json': 'urn:ai-sow:generate:next:prototype-scenario:1',
 'prototype-trace.schema.json': 'urn:ai-sow:generate:next:prototype-trace:1',
 'request.schema.json': 'urn:ai-sow:generate:next:request:1',
 'review-repair.schema.json': 'urn:ai-sow:generate:next:review-repair:1',
 'run-budget-policy.schema.json': 'urn:ai-sow:generate:next:run-budget-policy:1',
 'run-event.schema.json': 'urn:ai-sow:generate:next:run-event:1',
 'run-state.schema.json': 'urn:ai-sow:generate:next:run-state:1',
 'scope-decision.schema.json': 'urn:ai-sow:generate:next:scope-decision:1',
 'source-audit.schema.json': 'urn:ai-sow:generate:next:source-audit:1',
 'sow-model.schema.json': 'urn:ai-sow:generate:next:sow-model:1',
 'stage-checkpoint.schema.json': 'urn:ai-sow:generate:next:stage-checkpoint:1',
 'story-ac-decision.schema.json': 'urn:ai-sow:generate:next:story-ac-decision:1',
 'task-decision.schema.json': 'urn:ai-sow:generate:next:task-decision:1',
 'visual-review.schema.json': 'urn:ai-sow:generate:visual-review:1'}


def load_json(path: Path) -> object:
    """Load a UTF-8 JSON document."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_toml(path: Path) -> dict[str, object]:
    """Load a UTF-8 TOML document through the Python 3.12 standard library."""
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _is_template_path_mismatch(test: ast.expr) -> bool:
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        return any(_is_template_path_mismatch(value) for value in test.values)
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "template_path"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.NotEq)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Name)
        and test.comparators[0].id == "expected_path"
    )


def _body_has_effective_raise(body: list[ast.stmt]) -> bool:
    for statement in body:
        if isinstance(statement, ast.Raise):
            return True
        if isinstance(statement, (ast.Return, ast.Break, ast.Continue)):
            return False
        if isinstance(statement, (ast.With, ast.AsyncWith)) and _body_has_effective_raise(
            statement.body
        ):
            return True
        if (
            isinstance(statement, ast.If)
            and statement.orelse
            and _body_has_effective_raise(statement.body)
            and _body_has_effective_raise(statement.orelse)
        ):
            return True
    return False


def generation_store_binds_immutable_template(path: Path) -> bool:
    """Return whether generation storage enforces its owned template copy."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return False
    verifier = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_verify_staged_template"
        ),
        None,
    )
    if verifier is None:
        return False

    expected_path = False
    rejection_guard = any(
        isinstance(statement, ast.If)
        and _is_template_path_mismatch(statement.test)
        and _body_has_effective_raise(statement.body)
        for statement in verifier.body
    )
    staged_member = False
    for node in ast.walk(verifier):
        if isinstance(node, ast.JoinedStr):
            parts = "".join(
                part.value
                for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            if parts == ".ai-sow/generations//input/sow-template.xlsx":
                expected_path = any(
                    isinstance(part, ast.FormattedValue)
                    and isinstance(part.value, ast.Name)
                    and part.value.id == "generation_id"
                    for part in node.values
                )
        elif (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant)
            and node.right.value == "input/sow-template.xlsx"
            and any(
                isinstance(child, ast.Name)
                and child.id == "staged_generation_root"
                for child in ast.walk(node.left)
            )
        ):
            staged_member = True
    return expected_path and rejection_guard and staged_member


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def validate_marketplace(repo_root: Path) -> list[str]:
    errors: list[str] = []
    path = repo_root / CODEX_MARKETPLACE
    try:
        data = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid marketplace manifest: {exc}"]
    if not isinstance(data, dict):
        return ["marketplace manifest must be a JSON object"]

    if data.get("name") != MARKETPLACE_NAME:
        errors.append(f"marketplace name must be {MARKETPLACE_NAME}")
    interface = data.get("interface")
    if not isinstance(interface, dict) or interface.get("displayName") != "AI Plugin Marketplace":
        errors.append("marketplace displayName must be AI Plugin Marketplace")

    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        return [*errors, "marketplace plugins must be a non-empty array"]

    names: set[str] = set()
    source_paths: set[str] = set()
    for index, entry in enumerate(plugins):
        if not isinstance(entry, dict):
            errors.append(f"marketplace plugin entry {index} must be an object")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"marketplace plugin entry {index} must have a name")
        elif name in names:
            errors.append(f"duplicate marketplace plugin name: {name}")
        else:
            names.add(name)
        source = entry.get("source")
        if not isinstance(source, dict):
            errors.append(f"marketplace plugin {name or index} source must be an object")
            continue
        if source.get("source") != "local":
            errors.append(f"marketplace plugin {name or index} source must be local")
        source_path = source.get("path")
        if not isinstance(source_path, str) or not source_path.strip():
            errors.append(f"marketplace plugin {name or index} path must be non-empty")
        elif not _inside(repo_root / source_path, repo_root):
            errors.append(f"marketplace plugin {name or index} path escapes the repository")
        else:
            if source_path in source_paths:
                errors.append(f"duplicate marketplace plugin source: {source_path}")
            else:
                source_paths.add(source_path)
            source_directory = repo_root / source_path
            if not source_directory.is_dir():
                errors.append(
                    f"marketplace plugin {name or index} source directory is missing"
                )
            elif isinstance(name, str) and name != source_directory.name:
                errors.append(
                    f"marketplace plugin {name} name must match source directory "
                    f"{source_directory.name}"
                )

    ai_sow_entries = [
        entry
        for entry in plugins
        if isinstance(entry, dict) and entry.get("name") == "ai-sow"
    ]
    if len(ai_sow_entries) != 1:
        return [*errors, "marketplace must contain exactly one ai-sow entry"]
    entry = ai_sow_entries[0]
    expected_source = {"source": "local", "path": "./plugins/ai-sow"}
    if entry.get("source") != expected_source:
        errors.append("ai-sow source must be ./plugins/ai-sow")
    if entry.get("policy") != {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }:
        errors.append("ai-sow marketplace policy is invalid")
    if entry.get("category") != "Productivity":
        errors.append("ai-sow category must be Productivity")
    return errors


def _claude_marketplace_source(entry: dict[str, object]) -> str | None:
    """Return a Claude marketplace entry's local source path, if it declares one."""
    source = entry.get("source")
    if isinstance(source, str):
        return source
    if isinstance(source, dict) and source.get("source") == "local":
        path = source.get("path")
        return path if isinstance(path, str) else None
    return None


def validate_claude_marketplace(repo_root: Path) -> list[str]:
    """Validate the Claude Code marketplace directory published alongside the Codex one."""
    errors: list[str] = []
    path = repo_root / CLAUDE_MARKETPLACE
    try:
        data = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid Claude marketplace manifest: {exc}"]
    if not isinstance(data, dict):
        return ["Claude marketplace manifest must be a JSON object"]

    if data.get("name") != MARKETPLACE_NAME:
        errors.append(f"Claude marketplace name must be {MARKETPLACE_NAME}")
    owner = data.get("owner")
    if not isinstance(owner, dict) or not str(owner.get("name") or "").strip():
        errors.append("Claude marketplace owner must declare a name")

    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        return [*errors, "Claude marketplace plugins must be a non-empty array"]

    names: set[str] = set()
    for index, entry in enumerate(plugins):
        if not isinstance(entry, dict):
            errors.append(f"Claude marketplace plugin entry {index} must be an object")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"Claude marketplace plugin entry {index} must have a name")
        elif name in names:
            errors.append(f"duplicate Claude marketplace plugin name: {name}")
        else:
            names.add(name)
        source_path = _claude_marketplace_source(entry)
        if source_path is None:
            errors.append(
                f"Claude marketplace plugin {name or index} must declare a local source"
            )
            continue
        if not _inside(repo_root / source_path, repo_root):
            errors.append(
                f"Claude marketplace plugin {name or index} path escapes the repository"
            )
            continue
        source_directory = repo_root / source_path
        if not source_directory.is_dir():
            errors.append(
                f"Claude marketplace plugin {name or index} source directory is missing"
            )
        elif isinstance(name, str) and name != source_directory.name:
            errors.append(
                f"Claude marketplace plugin {name} name must match source directory "
                f"{source_directory.name}"
            )
    return errors


def validate_marketplace_parity(repo_root: Path) -> list[str]:
    """Both marketplace directories must publish the same plugins from the same paths."""
    try:
        codex = load_json(repo_root / CODEX_MARKETPLACE)
        claude = load_json(repo_root / CLAUDE_MARKETPLACE)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"cannot compare marketplace manifests: {exc}"]
    if not isinstance(codex, dict) or not isinstance(claude, dict):
        return ["marketplace manifests must both be JSON objects"]

    def codex_entries(data: dict[str, object]) -> set[tuple[str, str]]:
        plugins = data.get("plugins")
        if not isinstance(plugins, list):
            return set()
        result: set[tuple[str, str]] = set()
        for entry in plugins:
            if not isinstance(entry, dict):
                continue
            source = entry.get("source")
            path = source.get("path") if isinstance(source, dict) else None
            if isinstance(entry.get("name"), str) and isinstance(path, str):
                result.add((entry["name"], path.lstrip("./")))
        return result

    def claude_entries(data: dict[str, object]) -> set[tuple[str, str]]:
        plugins = data.get("plugins")
        if not isinstance(plugins, list):
            return set()
        result: set[tuple[str, str]] = set()
        for entry in plugins:
            if not isinstance(entry, dict):
                continue
            path = _claude_marketplace_source(entry)
            if isinstance(entry.get("name"), str) and isinstance(path, str):
                result.add((entry["name"], path.lstrip("./")))
        return result

    errors: list[str] = []
    if codex.get("name") != claude.get("name"):
        errors.append("Codex and Claude marketplace names must match")
    missing = codex_entries(codex) ^ claude_entries(claude)
    if missing:
        rendered = ", ".join(sorted(f"{name}@{path}" for name, path in missing))
        errors.append(f"Codex and Claude marketplaces publish different plugins: {rendered}")
    return errors


def validate_plugin_manifest(
    repo_root: Path,
    plugin_path: Path,
    manifest_relative: str = CODEX_PLUGIN_MANIFEST,
) -> list[str]:
    errors: list[str] = []
    if not _inside(plugin_path, repo_root):
        return ["plugin path escapes the repository"]
    manifest_path = plugin_path / manifest_relative
    try:
        data = load_json(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid plugin manifest: {exc}"]
    if not isinstance(data, dict):
        return ["plugin manifest must be a JSON object"]
    if data.get("name") != plugin_path.name:
        errors.append("plugin manifest name must match its directory")
    version = data.get("version")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        errors.append("plugin version must use MAJOR.MINOR.PATCH semver")
    for key in ("skills", "commands", "agents", "hooks", "mcpServers"):
        declared = data.get(key)
        if declared is None:
            continue
        relatives = declared if isinstance(declared, list) else [declared]
        for relative in relatives:
            if not isinstance(relative, str) or not relative.strip():
                errors.append(f"manifest {key} path must be a non-empty string")
                continue
            if not _inside(plugin_path / relative, plugin_path):
                errors.append(f"manifest {key} path escapes the plugin")
    return errors


def validate_plugin_manifest_parity(plugin_path: Path) -> list[str]:
    """Codex and Claude plugin manifests must declare the same release identity."""
    manifests: dict[str, dict[str, object]] = {}
    for relative in (CODEX_PLUGIN_MANIFEST, CLAUDE_PLUGIN_MANIFEST):
        try:
            data = load_json(plugin_path / relative)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return [f"invalid plugin manifest {relative}: {exc}"]
        if not isinstance(data, dict):
            return [f"plugin manifest {relative} must be a JSON object"]
        manifests[relative] = data

    codex = manifests[CODEX_PLUGIN_MANIFEST]
    claude = manifests[CLAUDE_PLUGIN_MANIFEST]
    return [
        f"Codex and Claude plugin manifests disagree on {field}"
        for field in ("name", "version", "description", "author")
        if codex.get(field) != claude.get(field)
    ]


def validate_publisher_identity(repo_root: Path, plugin_root: Path) -> list[str]:
    """Every host-visible publisher field must name the same publisher."""
    errors: list[str] = []
    sources = (
        (CODEX_PLUGIN_MANIFEST, plugin_root / CODEX_PLUGIN_MANIFEST, ("author", "name")),
        (
            CODEX_PLUGIN_MANIFEST,
            plugin_root / CODEX_PLUGIN_MANIFEST,
            ("interface", "developerName"),
        ),
        (CLAUDE_PLUGIN_MANIFEST, plugin_root / CLAUDE_PLUGIN_MANIFEST, ("author", "name")),
        (CLAUDE_MARKETPLACE, repo_root / CLAUDE_MARKETPLACE, ("owner", "name")),
    )
    for label, path, keys in sources:
        try:
            document = load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid publisher source {label}: {exc}")
            continue
        value: object = document
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        if value != PUBLISHER_NAME:
            errors.append(
                f"{label} {'.'.join(keys)} must be {PUBLISHER_NAME}, found {value!r}"
            )
    return errors


def validate_ai_sow_release(repo_root: Path, plugin_root: Path) -> list[str]:
    """Validate the release identity and plugin-scoped support surface."""
    errors: list[str] = []
    required = (
        plugin_root / "skills/generate/SKILL.md",
        plugin_root / "skills/generate/scripts/bootstrap.sh",
        plugin_root / "skills/generate/scripts/bootstrap.ps1",
        plugin_root / "skills/generate/scripts/orchestrator.py",
        plugin_root / "skills/generate/scripts/generation_store.py",
        plugin_root / "skills/generate/assets/sow-template.xlsx",
        plugin_root / "skills/generate/contracts/generation-manifest.schema.json",
        plugin_root / "skills/generate/contracts/renderer-fingerprint-baseline.json",
        plugin_root / "tests/support/smoke_plugin.py",
        plugin_root / "tests/contracts/case-manifest.schema.json",
        plugin_root / "tests/fixtures/explicit-architecture/case-manifest.json",
        plugin_root / "docs/reference/SOW任务分类与开发交付人天标准_v1.3.md",
        plugin_root / "docs/reference/SOW估算与生成示例_v1.3.xlsx",
        *(plugin_root / relative for relative in AI_SOW_GENERATE_SUPPORT_FILES),
    )
    for path in required:
        if not path.is_file():
            errors.append(f"missing release file: {path.relative_to(repo_root).as_posix()}")
    if (repo_root / "scripts" / "smoke_plugin.py").exists():
        errors.append("AI SOW smoke implementation must be plugin-scoped")

    contract_root = plugin_root / "skills/generate/contracts"
    actual_schema_names = {
        path.name for path in contract_root.glob("*.schema.json")
    }
    expected_schema_names = set(AI_SOW_SCHEMA_IDS)
    if actual_schema_names != expected_schema_names:
        errors.append(
            "AI SOW contract set must be the exact final generate schemas, "
            f"found {sorted(actual_schema_names)}"
        )
    for name, expected_id in AI_SOW_SCHEMA_IDS.items():
        path = contract_root / name
        if not path.is_file():
            continue
        try:
            value = load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid AI SOW contract {name}: {exc}")
            continue
        if not isinstance(value, dict) or value.get("$id") != expected_id:
            errors.append(f"AI SOW contract {name} must use $id {expected_id}")

    generation_schema_path = contract_root / "generation-manifest.schema.json"
    if generation_schema_path.is_file():
        generation_schema = load_json(generation_schema_path)
        required_fields = (
            generation_schema.get("required")
            if isinstance(generation_schema, dict)
            else None
        )
        proof_fields = {
            "sowModelSha256",
            "stageCheckpointSha256s",
            "reviewDecisionSha256",
            "artifactManifestSha256",
            "approvalSha256",
            "templateSha256",
            "effectivePolicyDecisionSha256",
            "workbookSha256",
            "notesSha256",
        }
        if not isinstance(required_fields, list) or not proof_fields <= set(
            required_fields
        ):
            errors.append(
                "generation manifest must require the v2 self-contained proof closure"
            )

    public_skills = sorted(
        path.parent.name for path in (plugin_root / "skills").glob("*/SKILL.md")
    )
    if public_skills != ["generate"]:
        errors.append(
            "AI SOW public skills must be exactly ['generate'], "
            f"found {public_skills}"
        )

    for relative in (CODEX_PLUGIN_MANIFEST, CLAUDE_PLUGIN_MANIFEST):
        try:
            manifest = load_json(plugin_root / relative)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid AI SOW plugin manifest {relative}: {exc}")
            continue
        if not isinstance(manifest, dict):
            errors.append(
                f"invalid AI SOW plugin manifest {relative}: expected a JSON object"
            )
        elif manifest.get("version") != RELEASE_VERSION:
            errors.append(f"AI SOW plugin version in {relative} must be {RELEASE_VERSION}")
        if isinstance(manifest, dict) and manifest.get("description") != AI_SOW_DESCRIPTION:
            errors.append(
                f"AI SOW plugin description in {relative} must advertise the "
                "automatic generate flow"
            )
        if relative == CODEX_PLUGIN_MANIFEST and isinstance(manifest, dict):
            interface = manifest.get("interface")
            long_description = (
                interface.get("longDescription")
                if isinstance(interface, dict)
                else None
            )
            prompts = (
                interface.get("defaultPrompt")
                if isinstance(interface, dict)
                else None
            )
            if not isinstance(long_description, str) or not long_description.startswith(
                "一次提供 PRD、HLD"
            ):
                errors.append(
                    "AI SOW longDescription must advertise one automatic generate flow"
                )
            if (
                not isinstance(prompts, list)
                or len(prompts) != 3
                or any(
                    not isinstance(prompt, str)
                    or "ai-sow:generate" not in prompt
                    or "下一阶段" in prompt
                    for prompt in prompts
                )
            ):
                errors.append(
                    "AI SOW defaultPrompt must only advertise ai-sow:generate"
                )

    for relative in (CODEX_MARKETPLACE, CLAUDE_MARKETPLACE):
        path = repo_root / relative
        if not path.is_file():
            continue
        try:
            marketplace = load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        plugins = marketplace.get("plugins") if isinstance(marketplace, dict) else None
        ai_sow = next(
            (
                entry
                for entry in plugins
                if isinstance(entry, dict) and entry.get("name") == "ai-sow"
            ),
            None,
        ) if isinstance(plugins, list) else None
        if not isinstance(ai_sow, dict) or ai_sow.get("description") != AI_SOW_DESCRIPTION:
            errors.append(
                f"AI SOW marketplace description in {relative} must match the "
                "automatic generate flow"
            )

    pyproject_path = plugin_root / "pyproject.toml"
    try:
        pyproject = load_toml(pyproject_path)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"invalid AI SOW pyproject: {exc}")
    else:
        project_table = pyproject.get("project")
        if not isinstance(project_table, dict):
            errors.append("invalid AI SOW pyproject: missing [project] table")
        elif project_table.get("version") != PYTHON_RUNTIME_VERSION:
            errors.append(f"pyproject version must be {PYTHON_RUNTIME_VERSION}")

    lock_path = plugin_root / "uv.lock"
    try:
        lockfile = load_toml(lock_path)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"invalid AI SOW lock file: {exc}")
    else:
        packages = lockfile.get("package")
        ai_sow_packages = [
            package
            for package in packages if isinstance(package, dict)
            and package.get("name") == "ai-sow-plugin-runtime"
        ] if isinstance(packages, list) else []
        if len(ai_sow_packages) != 1:
            errors.append(
                "invalid AI SOW lock file: expected one ai-sow-plugin-runtime package"
            )
        elif ai_sow_packages[0].get("version") != PYTHON_RUNTIME_VERSION:
            errors.append(f"uv.lock package version must be {PYTHON_RUNTIME_VERSION}")
    return errors


def validate_renderer_contract_consistency(
    repo_root: Path,
    plugin_root: Path,
) -> list[str]:
    """Bind deterministic renderer bytes to the generation contract token."""
    errors: list[str] = []
    skill_root = plugin_root / "skills/generate"
    manifest_path = skill_root / "contracts/generation-manifest.schema.json"
    baseline_path = skill_root / "contracts/renderer-fingerprint-baseline.json"
    try:
        manifest = load_json(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid generation manifest schema: {exc}"]
    try:
        baseline = load_json(baseline_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid renderer fingerprint baseline: {exc}"]

    properties = manifest.get("properties") if isinstance(manifest, dict) else None
    renderer_contract = (
        properties.get("rendererContract")
        if isinstance(properties, dict)
        else None
    )
    contract = None
    if isinstance(renderer_contract, dict):
        const = renderer_contract.get("const")
        supported = renderer_contract.get("enum")
        if isinstance(const, str):
            contract = const
        elif (
            isinstance(supported, list)
            and supported
            and all(isinstance(item, str) and item for item in supported)
        ):
            # Historical generation manifests remain readable; the last enum
            # value is the only contract allowed for new renderer output.
            contract = supported[-1]
    if not isinstance(contract, str) or not contract:
        errors.append(
            "generation manifest schema must declare a current rendererContract"
        )

    baseline_contract = (
        baseline.get("rendererContract") if isinstance(baseline, dict) else None
    )
    baseline_files = baseline.get("files") if isinstance(baseline, dict) else None
    if baseline_contract != contract:
        errors.append(
            "renderer fingerprint baseline rendererContract must match the "
            f"manifest schema: expected {contract!r}, found {baseline_contract!r}"
        )
    if not isinstance(baseline_files, dict):
        return [*errors, "renderer fingerprint baseline files must be an object"]

    expected_files = set(RENDERER_FINGERPRINT_FILES)
    actual_files = set(baseline_files)
    if actual_files != expected_files:
        missing = ", ".join(sorted(expected_files - actual_files)) or "none"
        extra = ", ".join(sorted(actual_files - expected_files)) or "none"
        errors.append(
            "renderer fingerprint baseline file set is invalid: "
            f"missing [{missing}], extra [{extra}]"
        )

    for relative in RENDERER_FINGERPRINT_FILES:
        path = skill_root / relative
        expected = baseline_files.get(relative)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            errors.append(
                f"cannot read renderer fingerprint file "
                f"{path.relative_to(repo_root).as_posix()}: {exc}"
            )
            continue
        actual = hashlib.sha256(payload).hexdigest()
        if expected != actual:
            errors.append(
                "renderer fingerprint mismatch for "
                f"{path.relative_to(repo_root).as_posix()}: expected {expected!r}, "
                f"found {actual}; deterministic generator changes require a "
                "rendererContract bump and baseline refresh"
            )
    return errors


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _model_efficiency_policy_sha256(policy: dict[str, object]) -> str:
    normalized = json.loads(json.dumps(policy))
    gate = normalized.get("pairedBenchmarkGate")
    if not isinstance(gate, dict):
        return ""
    gate.update(
        {
            "status": "REQUIRED_NOT_SATISFIED",
            "claimStatus": "FORBIDDEN_UNTIL_VALIDATED_MANIFESTS",
            "baselineManifest": None,
            "candidateManifest": None,
            "comparisonReceipt": None,
        }
    )
    return hashlib.sha256(_canonical_json_bytes(normalized)).hexdigest()


def validate_model_efficiency_gate(plugin_root: Path) -> list[str]:
    """Require SATISFIED claims to be derived from exact recomputed evidence."""

    policy_path = plugin_root / "tests/benchmarks/model-efficiency-policy-v1.json"
    runner_path = plugin_root / "tests/support/analyze_historical_benchmark.py"
    try:
        policy = load_json(policy_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid model efficiency policy: {exc}"]
    if not isinstance(policy, dict):
        return ["model efficiency policy must be a JSON object"]
    gate = policy.get("pairedBenchmarkGate")
    if not isinstance(gate, dict):
        return ["model efficiency policy must declare pairedBenchmarkGate"]
    if gate.get("status") != "SATISFIED":
        if (
            gate.get("status") != "REQUIRED_NOT_SATISFIED"
            or gate.get("claimStatus") != "FORBIDDEN_UNTIL_VALIDATED_MANIFESTS"
            or any(
                gate.get(field) is not None
                for field in (
                    "baselineManifest",
                    "candidateManifest",
                    "comparisonReceipt",
                )
            )
        ):
            return ["unsatisfied model efficiency gate has inconsistent claim state"]
        return []

    errors: list[str] = []
    evidence_paths: dict[str, Path] = {}
    for field in ("baselineManifest", "candidateManifest"):
        relative = gate.get(field)
        if not isinstance(relative, str) or not relative or not _inside(
            plugin_root / relative, plugin_root
        ):
            errors.append(f"model efficiency {field} path is invalid")
            continue
        path = plugin_root / relative
        if not path.is_file():
            errors.append(f"model efficiency {field} evidence is missing")
            continue
        evidence_paths[field] = path
    comparison = gate.get("comparisonReceipt")
    if not isinstance(comparison, dict):
        errors.append("model efficiency comparisonReceipt binding is invalid")
    else:
        relative = comparison.get("path")
        expected_sha256 = comparison.get("sha256")
        if not isinstance(relative, str) or not relative or not _inside(
            plugin_root / relative, plugin_root
        ):
            errors.append("model efficiency comparisonReceipt path is invalid")
        else:
            comparison_path = plugin_root / relative
            if not comparison_path.is_file():
                errors.append("model efficiency comparisonReceipt evidence is missing")
            else:
                actual_sha256 = hashlib.sha256(comparison_path.read_bytes()).hexdigest()
                if actual_sha256 != expected_sha256:
                    errors.append("model efficiency comparisonReceipt hash mismatch")
                else:
                    evidence_paths["comparisonReceipt"] = comparison_path
    if errors:
        return errors

    try:
        receipt = load_json(evidence_paths["comparisonReceipt"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid model efficiency comparisonReceipt: {exc}"]
    if not isinstance(receipt, dict):
        return ["model efficiency comparisonReceipt must be a JSON object"]
    checks = receipt.get("checks")
    if (
        receipt.get("verdict") != "PASS"
        or not isinstance(checks, dict)
        or not checks
        or not all(value is True for value in checks.values())
        or receipt.get("failureCodes") != []
        or receipt.get("policySha256") != _model_efficiency_policy_sha256(policy)
        or receipt.get("baselineManifestSha256")
        != hashlib.sha256(evidence_paths["baselineManifest"].read_bytes()).hexdigest()
        or receipt.get("candidateManifestSha256")
        != hashlib.sha256(evidence_paths["candidateManifest"].read_bytes()).hexdigest()
    ):
        return ["model efficiency SATISFIED evidence binding is invalid"]
    if not runner_path.is_file():
        return ["model efficiency evidence validator is missing"]
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(runner_path),
                "validate-policy",
                "--policy",
                str(policy_path),
            ],
            cwd=plugin_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ["model efficiency evidence validator could not run"]
    if completed.returncode != 0:
        return ["model efficiency SATISFIED evidence failed mechanical reevaluation"]
    return []


def _marketplace_plugin_paths(repo_root: Path) -> list[tuple[str, Path]]:
    """Return valid local marketplace plugin names and paths for manifest checks."""
    try:
        data = load_json(repo_root / CODEX_MARKETPLACE)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list):
        return []
    result: list[tuple[str, Path]] = []
    for entry in plugins:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        source = entry.get("source")
        path = source.get("path") if isinstance(source, dict) else None
        if (
            isinstance(name, str)
            and name
            and isinstance(source, dict)
            and source.get("source") == "local"
            and isinstance(path, str)
            and path
            and _inside(repo_root / path, repo_root)
        ):
            result.append((name, repo_root / path))
    return result


def _tracked_files(repo_root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return [repo_root / item.decode() for item in completed.stdout.split(b"\0") if item]


def validate_public_tree(repo_root: Path) -> list[str]:
    errors: list[str] = []
    home_prefix = str(Path.home().resolve()) + "/"
    try:
        files = _tracked_files(repo_root)
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"cannot enumerate tracked files: {exc}"]
    for path in files:
        if ".DS_Store" in path.name:
            errors.append(f"tracked macOS metadata: {path.relative_to(repo_root).as_posix()}")
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if home_prefix in text:
            errors.append(f"tracked local absolute path: {path.relative_to(repo_root).as_posix()}")
        for forbidden in FORBIDDEN_PUBLIC_TEXT:
            if forbidden in text:
                errors.append(
                    f"tracked forbidden public text in {path.relative_to(repo_root).as_posix()}: "
                    f"{forbidden}"
                )
    return errors


def validate_current_behavior_text(repo_root: Path) -> list[str]:
    """Current operation docs may not advertise a retired protocol."""
    paths = [repo_root / name for name in ('README.md', 'AGENTS.md', 'CONTRIBUTING.md',
             'docs/architecture/ai-plugin-marketplace-design.md', 'plugins/ai-sow/README.md',
             'plugins/ai-sow/docs/AI_SOW_PLUGIN_DESIGN.md', 'plugins/ai-sow/docs/CONTEXT.md',
             'plugins/ai-sow/skills/generate/SKILL.md')]
    for relative in ('plugins/ai-sow/references', 'plugins/ai-sow/skills/generate/references'):
        paths.extend((repo_root / relative).glob('*.md'))
    retired = ('currentStateDelta', 'REFERENCE_ONLY', 'RENDER_ONLY', 'DELTA_COMPILE',
               '固定 3×8', 'stage approval', 'Demo-as-current-state')
    return [f'retired current behavior token in {path.relative_to(repo_root)}: {token}'
            for path in paths if path.is_file()
            for token in retired if token in path.read_text(encoding='utf-8')]


def validate_repository(repo_root: Path) -> list[str]:
    repo_root = repo_root.resolve()
    plugin_root = repo_root / "plugins/ai-sow"
    errors = validate_marketplace(repo_root)
    errors.extend(validate_claude_marketplace(repo_root))
    errors.extend(validate_marketplace_parity(repo_root))
    for name, path in _marketplace_plugin_paths(repo_root):
        for relative in (CODEX_PLUGIN_MANIFEST, CLAUDE_PLUGIN_MANIFEST):
            errors.extend(
                f"{name} ({relative}): {error}"
                for error in validate_plugin_manifest(repo_root, path, relative)
            )
        errors.extend(
            f"{name}: {error}" for error in validate_plugin_manifest_parity(path)
        )
    errors.extend(validate_ai_sow_release(repo_root, plugin_root))
    errors.extend(validate_renderer_contract_consistency(repo_root, plugin_root))
    errors.extend(validate_model_efficiency_gate(plugin_root))
    errors.extend(validate_publisher_identity(repo_root, plugin_root))
    errors.extend(validate_public_tree(repo_root))
    errors.extend(validate_current_behavior_text(repo_root))
    return errors


def main(argv: list[str] | None = None) -> int:
    del argv
    repo_root = Path(__file__).resolve().parents[1]
    errors = validate_repository(repo_root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("repository validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
