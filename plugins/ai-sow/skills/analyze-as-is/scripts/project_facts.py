from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


CANDIDATE_PATH = ".ai-sow/work/analyze-as-is/asis.candidate.json"
PREMISES_PATH = ".ai-sow/work/analyze-as-is/premises.json"
OUTPUT_PATH = ".ai-sow/work/analyze-as-is/repo-facts.json"
DEFAULT_FAMILIES = (
    "modules",
    "deploymentResources",
    "criticalConfiguration",
    "springProfiles",
    "migrationTables",
    "ciWorkflows",
)
ALL_FAMILIES = {
    *DEFAULT_FAMILIES,
    "kafkaBoundaries",
    "testInfrastructure",
    "codegraphCoverage",
}
TEXT_SUFFIXES = {".yml", ".yaml", ".properties", ".toml", ".sql", ".gradle", ".kts", ".xml"}
SECRET_KEY = re.compile(r"(?:password|secret|token|credential|private[-_.]?key)", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Project deterministic As-Is repository facts")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--candidate", default=CANDIDATE_PATH)
    parser.add_argument("--premises", default=PREMISES_PATH)
    parser.add_argument("--output", default=OUTPUT_PATH)
    parser.add_argument("--families", nargs="*", choices=sorted(ALL_FAMILIES))
    return parser.parse_args()


def _project_file(root: Path, relative: str) -> Path:
    value = (root / relative).resolve()
    if not value.is_relative_to(root.resolve()) or not value.is_file():
        raise ValueError(f"registered repository file is unavailable: {relative}")
    return value


def _repository_files(project_root: Path, repository_path: str) -> list[Path]:
    root = project_root if repository_path == "." else (project_root / repository_path)
    resolved_root = root.resolve()
    if not resolved_root.is_relative_to(project_root.resolve()) or not resolved_root.is_dir():
        raise ValueError(f"registered repository is unavailable: {repository_path}")
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not any(part in {".ai-sow", ".git", ".gradle", "node_modules", "build", "dist", "target"} for part in path.parts)
    )


def _relative(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def _read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Dockerfile", "Jenkinsfile"}:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _module_facts(project_root: Path, files: list[Path]) -> dict[str, object]:
    build_names = {"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "package.json"}
    paths = sorted({_relative(project_root, path.parent) or "." for path in files if path.name in build_names})
    return {"count": len(paths), "paths": paths}


def _deployment_facts(project_root: Path, files: list[Path]) -> dict[str, object]:
    resources: list[dict[str, str]] = []
    for path in files:
        if path.suffix.lower() not in {".yml", ".yaml"}:
            continue
        text = _read_text(path)
        if text is None:
            continue
        kinds = re.findall(r"(?m)^\s*kind\s*:\s*(Job|CronJob)\s*$", text)
        names = re.findall(r"(?m)^\s*name\s*:\s*['\"]?([A-Za-z0-9._-]+)", text)
        for index, kind in enumerate(kinds):
            resources.append(
                {
                    "kind": kind,
                    "name": names[index] if index < len(names) else path.stem,
                    "path": _relative(project_root, path),
                }
            )
    counts = Counter(resource["kind"] for resource in resources)
    return {"counts": dict(sorted(counts.items())), "resources": resources}


def _critical_configuration(project_root: Path, files: list[Path]) -> dict[str, object]:
    values: list[dict[str, str]] = []
    key_pattern = re.compile(
        r"(?m)^\s*([A-Za-z0-9_.-]*(?:relay\.strategy|relay-strategy|relay_strategy))\s*[:=]\s*([^#\r\n]+)"
    )
    for path in files:
        text = _read_text(path)
        if text is None:
            continue
        for key, raw in key_pattern.findall(text):
            values.append(
                {
                    "key": key,
                    "path": _relative(project_root, path),
                    "value": "REDACTED" if SECRET_KEY.search(key) else raw.strip().strip("'\""),
                }
            )
    return {"count": len(values), "values": values}


def _spring_profiles(project_root: Path, files: list[Path]) -> dict[str, object]:
    values: list[dict[str, str]] = []
    patterns = (
        re.compile(r"(?m)^\s*spring\.profiles\.active\s*[:=]\s*([^#\r\n]+)"),
        re.compile(r"(?m)^\s*SPRING_PROFILES_ACTIVE\s*[:=]\s*([^#\r\n]+)"),
    )
    for path in files:
        text = _read_text(path)
        if text is None:
            continue
        for pattern in patterns:
            for match in pattern.finditer(text):
                values.append(
                    {"path": _relative(project_root, path), "value": match.group(1).strip().strip("'\"")}
                )
    return {"count": len(values), "values": values}


def _migration_tables(project_root: Path, files: list[Path]) -> dict[str, object]:
    tables: list[dict[str, str]] = []
    pattern = re.compile(r"(?i)\b(?:create|alter)\s+table\s+(?:if\s+not\s+exists\s+)?[`\"]?([A-Za-z0-9_.-]+)")
    for path in files:
        if path.suffix.lower() != ".sql":
            continue
        text = _read_text(path)
        if text is None:
            continue
        for table in pattern.findall(text):
            tables.append({"path": _relative(project_root, path), "table": table})
    return {"count": len(tables), "tables": tables}


def _ci_workflows(project_root: Path, files: list[Path]) -> dict[str, object]:
    workflows: list[dict[str, object]] = []
    for path in files:
        relative = _relative(project_root, path)
        if "/.github/workflows/" not in f"/{relative}" or path.suffix.lower() not in {".yml", ".yaml"}:
            continue
        text = _read_text(path) or ""
        jobs: list[str] = []
        in_jobs = False
        for line in text.splitlines():
            if re.fullmatch(r"jobs:\s*", line):
                in_jobs = True
                continue
            if in_jobs and line and not line.startswith((" ", "\t")):
                break
            match = re.match(r"^\s{2}([A-Za-z0-9_-]+):\s*$", line) if in_jobs else None
            if match:
                jobs.append(match.group(1))
        workflows.append({"jobs": jobs, "path": relative})
    return {"count": len(workflows), "workflows": workflows}


def _kafka_boundaries(project_root: Path, files: list[Path]) -> dict[str, object]:
    boundaries: list[dict[str, str]] = []
    topic_pattern = re.compile(r"(?m)^\s*([A-Za-z0-9_.-]*(?:topic|topics|acl)[A-Za-z0-9_.-]*)\s*[:=]\s*([^#\r\n]+)", re.IGNORECASE)
    for path in files:
        text = _read_text(path)
        if text is None:
            continue
        for key, value in topic_pattern.findall(text):
            boundaries.append({"key": key, "path": _relative(project_root, path), "value": value.strip().strip("'\"")})
    return {"count": len(boundaries), "values": boundaries}


def _test_infrastructure(project_root: Path, files: list[Path]) -> dict[str, object]:
    symbols = ("KafkaContainer", "ElasticsearchContainer", "EmbeddedKafka", "PostgreSQLContainer")
    occurrences: list[dict[str, str]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for symbol in symbols:
            if symbol in text:
                occurrences.append({"path": _relative(project_root, path), "symbol": symbol})
    return {"count": len(occurrences), "occurrences": occurrences}


def _codegraph_coverage(project_root: Path, files: list[Path]) -> dict[str, object]:
    suffix_counts = Counter(path.suffix.lower() or "<none>" for path in files)
    return {"fileCount": len(files), "fileTypes": dict(sorted(suffix_counts.items()))}


COLLECTORS = {
    "modules": _module_facts,
    "deploymentResources": _deployment_facts,
    "criticalConfiguration": _critical_configuration,
    "springProfiles": _spring_profiles,
    "migrationTables": _migration_tables,
    "ciWorkflows": _ci_workflows,
    "kafkaBoundaries": _kafka_boundaries,
    "testInfrastructure": _test_infrastructure,
    "codegraphCoverage": _codegraph_coverage,
}


def _selected_families(files: ProjectFiles, premises_path: str, explicit: list[str] | None) -> tuple[str, ...]:
    if explicit:
        return tuple(explicit)
    try:
        premises = files.read_json(premises_path)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING":
            raise
        return DEFAULT_FAMILIES
    selected = premises.get("factFamilies", []) if isinstance(premises, dict) else []
    if not isinstance(selected, list) or not selected:
        return DEFAULT_FAMILIES
    unknown = set(selected) - ALL_FAMILIES
    if unknown:
        raise ValueError(f"unknown fact families: {', '.join(sorted(unknown))}")
    return tuple(dict.fromkeys(str(value) for value in selected))


def build_repo_facts(
    project_root: Path,
    candidate: dict[str, Any],
    families: tuple[str, ...],
) -> dict[str, object]:
    scope = candidate.get("analysisScope")
    if not isinstance(scope, dict) or not isinstance(scope.get("repositorySnapshots"), list):
        raise ValueError("As-Is candidate does not contain repository snapshots")
    repositories: list[dict[str, Any]] = []
    for snapshot in scope["repositorySnapshots"]:
        if not isinstance(snapshot, dict):
            raise ValueError("repository snapshot must be an object")
        repo_files = _repository_files(project_root, str(snapshot["path"]))
        facts = {
            family: COLLECTORS[family](project_root, repo_files)
            for family in families
        }
        repositories.append(
            {
                "facts": facts,
                "repoId": snapshot["repoId"],
                "revision": snapshot["revision"],
                "snapshotSha256": sha256_bytes(canonical_json_bytes(snapshot)),
            }
        )
    return {
        "algorithm": "ai-sow-repo-facts-v1",
        "factFamilies": list(families),
        "repositories": repositories,
    }


def main() -> int:
    args = parse_args()
    files = ProjectFiles.open(args.project_root)
    diagnostics: list[dict[str, str]] = []
    try:
        candidate = files.read_json(args.candidate)
        if not isinstance(candidate, dict):
            raise ValueError("As-Is candidate must be a JSON object")
        families = _selected_families(files, args.premises, args.families)
        output = build_repo_facts(args.project_root, candidate, families)
        files.write_atomic(args.output, canonical_json_bytes(output))
    except (ProjectIOError, OSError, UnicodeError, ValueError, KeyError, json.JSONDecodeError) as error:
        diagnostics.append(
            {
                "code": getattr(error, "code", "REPO_FACTS_INVALID"),
                "message": str(error),
                **({"path": getattr(error, "relative_path")} if getattr(error, "relative_path", "") else {}),
            }
        )
    print(
        json.dumps(
            {
                "diagnostics": diagnostics,
                "outcome": "OK" if not diagnostics else "BLOCKED",
                "outputs": [args.output] if not diagnostics else [],
            },
            ensure_ascii=False,
        )
    )
    return 0 if not diagnostics else 2


if __name__ == "__main__":
    raise SystemExit(main())
