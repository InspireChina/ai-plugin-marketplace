#!/usr/bin/env python3
"""Validate public marketplace structure and release metadata."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

RELEASE_VERSION = "0.1.0-beta.2"
PYTHON_RUNTIME_VERSION = "0.1.0b2"
SOW_STANDARD_VERSION = "1.3"
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
    path = repo_root / ".agents/plugins/marketplace.json"
    try:
        data = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid marketplace manifest: {exc}"]
    if not isinstance(data, dict):
        return ["marketplace manifest must be a JSON object"]

    if data.get("name") != "ai-plugin-marketplace":
        errors.append("marketplace name must be ai-plugin-marketplace")
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


def validate_plugin_manifest(repo_root: Path, plugin_path: Path) -> list[str]:
    errors: list[str] = []
    if not _inside(plugin_path, repo_root):
        return ["plugin path escapes the repository"]
    manifest_path = plugin_path / ".codex-plugin/plugin.json"
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
    for key in ("skills", "mcpServers"):
        relative = data.get(key)
        if relative is None:
            continue
        if not isinstance(relative, str) or not relative.strip():
            errors.append(f"manifest {key} path must be a non-empty string")
            continue
        if not _inside(plugin_path / relative, plugin_path):
            errors.append(f"manifest {key} path escapes the plugin")
    return errors


def validate_ai_sow_release(repo_root: Path, plugin_root: Path) -> list[str]:
    """Validate the release identity and plugin-scoped support surface."""
    errors: list[str] = []
    required = (
        plugin_root / "tests/support/smoke_plugin.py",
        plugin_root / "docs/reference/SOW任务分类与开发交付人天标准_v1.3.md",
        plugin_root / "docs/reference/SOW估算与生成示例_v1.3.xlsx",
    )
    for path in required:
        if not path.is_file():
            errors.append(f"missing release file: {path.relative_to(repo_root)}")
    if (repo_root / "scripts" / "smoke_plugin.py").exists():
        errors.append("AI SOW smoke implementation must be plugin-scoped")

    manifest_path = plugin_root / ".codex-plugin/plugin.json"
    try:
        manifest = load_json(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid AI SOW plugin manifest: {exc}")
    else:
        if not isinstance(manifest, dict):
            errors.append("invalid AI SOW plugin manifest: expected a JSON object")
        elif manifest.get("version") != RELEASE_VERSION:
            errors.append(f"AI SOW plugin version must be {RELEASE_VERSION}")

    project_path = (
        plugin_root / "skills/generate-sow/fixtures/project/.ai-sow/project.json"
    )
    try:
        project = load_json(project_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid AI SOW fixture project: {exc}")
    else:
        if not isinstance(project, dict):
            errors.append("invalid AI SOW fixture project: expected a JSON object")
        else:
            if project.get("pluginVersion") != RELEASE_VERSION:
                errors.append(f"fixture pluginVersion must be {RELEASE_VERSION}")
            if project.get("sowStandardVersion") != SOW_STANDARD_VERSION:
                errors.append(
                    f"fixture sowStandardVersion must be {SOW_STANDARD_VERSION}"
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


def _marketplace_plugin_paths(repo_root: Path) -> list[tuple[str, Path]]:
    """Return valid local marketplace plugin names and paths for manifest checks."""
    try:
        data = load_json(repo_root / ".agents/plugins/marketplace.json")
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
            errors.append(f"tracked macOS metadata: {path.relative_to(repo_root)}")
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if home_prefix in text:
            errors.append(f"tracked local absolute path: {path.relative_to(repo_root)}")
        for forbidden in FORBIDDEN_PUBLIC_TEXT:
            if forbidden in text:
                errors.append(
                    f"tracked forbidden public text in {path.relative_to(repo_root)}: "
                    f"{forbidden}"
                )
    return errors


def validate_repository(repo_root: Path) -> list[str]:
    repo_root = repo_root.resolve()
    plugin_root = repo_root / "plugins/ai-sow"
    errors = validate_marketplace(repo_root)
    for name, path in _marketplace_plugin_paths(repo_root):
        errors.extend(
            f"{name}: {error}"
            for error in validate_plugin_manifest(repo_root, path)
        )
    errors.extend(validate_ai_sow_release(repo_root, plugin_root))
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
