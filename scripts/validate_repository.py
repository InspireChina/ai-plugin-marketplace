#!/usr/bin/env python3
"""Validate public marketplace structure and release metadata."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

RELEASE_VERSION = "0.1.0-beta.1"
PYTHON_RUNTIME_VERSION = "0.1.0b1"
SOW_STANDARD_VERSION = "1.3"
MARKETPLACE_NAME = "ai-plugin-marketplace"
PUBLISHER_NAME = "Inspire"
AI_SOW_DESCRIPTION = (
    "一次提供 PRD、HLD 和适用的往期 SOW，自动生成或增量更新可追溯的 SOW 工作簿。"
)
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
)


def load_json(path: Path) -> object:
    """Load a UTF-8 JSON document."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_toml(path: Path) -> dict[str, object]:
    """Load a UTF-8 TOML document through the Python 3.12 standard library."""
    return tomllib.loads(path.read_text(encoding="utf-8"))


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
        plugin_root / "skills/generate/assets/sow-template.xlsx",
        plugin_root / "skills/generate/contracts/generation-manifest.schema.json",
        plugin_root / "skills/generate/contracts/renderer-fingerprint-baseline.json",
        plugin_root / "tests/support/smoke_plugin.py",
        plugin_root / "tests/contracts/case-manifest.schema.json",
        plugin_root / "tests/fixtures/explicit-architecture/case-manifest.json",
        plugin_root / "docs/reference/SOW任务分类与开发交付人天标准_v1.3.md",
        plugin_root / "docs/reference/SOW估算与生成示例_v1.3.xlsx",
    )
    for path in required:
        if not path.is_file():
            errors.append(f"missing release file: {path.relative_to(repo_root).as_posix()}")
    if (repo_root / "scripts" / "smoke_plugin.py").exists():
        errors.append("AI SOW smoke implementation must be plugin-scoped")

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

    for mode in ("greenfield", "brownfield"):
        request_path = plugin_root / f"skills/generate/fixtures/{mode}/request.json"
        try:
            request = load_json(request_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid AI SOW {mode} fixture request: {exc}")
            continue
        project = request.get("project") if isinstance(request, dict) else None
        project_id = project.get("projectId") if isinstance(project, dict) else None
        project_name = project.get("name") if isinstance(project, dict) else None
        if (
            not isinstance(project_id, str)
            or not project_id.strip()
            or not isinstance(project_name, str)
            or not project_name.strip()
        ):
            errors.append(f"{mode} fixture projectId and name must be non-empty")
        if not isinstance(request, dict) or request.get("mode") != mode.upper():
            errors.append(f"{mode} fixture mode must be {mode.upper()}")

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
    contract = (
        renderer_contract.get("const")
        if isinstance(renderer_contract, dict)
        else None
    )
    if not isinstance(contract, str) or not contract:
        errors.append("generation manifest schema must declare rendererContract const")

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
    errors.extend(validate_publisher_identity(repo_root, plugin_root))
    errors.extend(validate_public_tree(repo_root))
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
