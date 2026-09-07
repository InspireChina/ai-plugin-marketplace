from __future__ import annotations

TEST_LAYER = "integration"

import ast
import hashlib
import json
import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1]
SKILL_ROOT = PLUGIN_ROOT / "skills/generate"
RUNTIME = PLUGIN_ROOT / "runtime"
SCRIPTS = SKILL_ROOT / "scripts"
EXPECTED_RUNTIME = {"__init__.py", "diagnostics.py", "project_io.py"}
REQUIRED_PYTHON_MODULES = {'action_ledger.py',
 'candidate_repair.py',
 'change_graph.py',
 'contracts.py',
 'delivery_compiler.py',
 'final_review.py',
 'generation_store.py',
 'intake.py',
 'owner_callbacks.py',
 'models.py',
 'office_engine.py',
 'orchestrator.py',
 'package_renderer.py',
 'prior_state.py',
 'prototype_analysis.py',
 'provider_adapter.py',
 'questions.py',
 'run_events.py',
 'scope_compiler.py',
 'source_readers.py',
 'sow_model.py',
 'stable_ids.py',
 'stage_planner.py',
 'story_notes.py',
 'task_compiler.py',
 'task_standard_catalog.py',
 'workbook.py'}
LEGACY_PROTOCOL_TOKENS = (
    "ai-sow-owner-v1",
    "publish-approved",
    "write-approval",
    "Reconciliation Run ID",
    ".ai-sow/validation/",
)
EXPECTED_DELIVERY_REFERENCES = {
    "delivery-decomposition.md",
    "delivery-lifecycle-policy.md",
    "technical-work-classification.md",
    "delivery-work-classification.md",
    "effective-start-matching.md",
    "epic-authoring.md",
    "feature-authoring.md",
    "layered-review.md",
    "source-authority.md",
    "story-authoring.md",
    "acceptance-criteria.md",
    "task-authoring.md",
}


def python_sources(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if ".venv" not in path.parts and "__pycache__" not in path.parts
    )


def source_text(*roots: Path) -> str:
    paths = sorted(
        path
        for root in roots
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix in {".py", ".sh", ".ps1", ".json", ".md"}
    )
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in paths)


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_generate_is_the_only_public_skill() -> None:
    assert {
        path.parent.name for path in PLUGIN_ROOT.glob("skills/*/SKILL.md")
    } == {"generate"}


def test_generate_contains_the_complete_internal_module_set() -> None:
    python_modules = {path.name for path in SCRIPTS.glob("*.py")}
    assert python_modules == REQUIRED_PYTHON_MODULES
    assert {
        path.name for path in SCRIPTS.iterdir() if path.is_file() and path.suffix != ".py"
    } == {"bootstrap.ps1", "bootstrap.sh", "enable_long_paths.ps1"}


def test_task_standard_catalog_is_owner_local_and_has_no_prior_sow_index_logic() -> None:
    path = SCRIPTS / "task_standard_catalog.py"
    assert imports(path).isdisjoint(
        {"delivery_compiler", "scope_compiler", "source_readers"}
    )
    text = path.read_text(encoding="utf-8")
    for token in ("PRIOR_SOW", "prior_sow", "Prior SOW", "往期 SOW"):
        assert token not in text


def test_runtime_contains_only_owner_agnostic_infrastructure() -> None:
    assert {path.name for path in RUNTIME.glob("*.py")} == EXPECTED_RUNTIME
    runtime_text = source_text(RUNTIME)
    for token in ("urn:ai-sow", "scope-bundle", "delivery-bundle", "skills/"):
        assert token not in runtime_text


def test_runtime_does_not_import_generate_and_generate_has_no_cross_skill_imports() -> None:
    for path in python_sources(RUNTIME):
        assert not any(name == "skills" or name.startswith("skills.") for name in imports(path))
    for path in python_sources(SCRIPTS):
        text = path.read_text(encoding="utf-8")
        assert "skills/" not in text
        assert "skills." not in text


def test_generate_dependency_graph_is_acyclic_and_orchestrator_is_the_only_coordinator() -> None:
    module_names = {path.stem for path in SCRIPTS.glob("*.py")}
    graph: dict[str, set[str]] = {}
    for path in SCRIPTS.glob("*.py"):
        graph[path.stem] = {
            name.split(".", 1)[0]
            for name in imports(path)
            if name.split(".", 1)[0] in module_names
        }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        assert node not in visiting, f"cycle through {node}: {graph}"
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for module in graph:
        visit(module)
    end_to_end_seams = {"intake", "package_renderer"}
    assert end_to_end_seams.issubset(graph["orchestrator"])
    for module, dependencies in graph.items():
        if module != "orchestrator":
            assert not end_to_end_seams.issubset(dependencies), (module, dependencies)


def test_runtime_and_generate_source_have_no_legacy_protocol_tokens() -> None:
    text = source_text(RUNTIME, SKILL_ROOT)
    for token in LEGACY_PROTOCOL_TOKENS:
        assert token not in text


def test_public_skill_exposes_one_orchestrator_and_no_legacy_stage_commands() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "Python orchestrator" in skill
    assert "NextAction" in skill
    for token in (
        "setup",
        "analyze-requirement",
        "analyze-as-is",
        "generate-design",
        "generate-story",
        "generate-task",
        "generate-sow",
        "reconcile",
    ):
        assert token not in skill


def test_orchestrator_cli_modes_are_exact() -> None:
    source = (SCRIPTS / "orchestrator.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    choices: tuple[str, ...] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "choices" and isinstance(keyword.value, ast.Tuple):
                values = tuple(
                    element.value
                    for element in keyword.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                )
                if "start" in values:
                    choices = values
    assert choices == (
        "start",
        "submit",
        "hydrate",
        "resume",
        "approve",
        "abandon",
        "status",
    )


def test_command_files_pin_utf8_and_platform_encodings() -> None:
    orchestrator = (SCRIPTS / "orchestrator.py").read_text(encoding="utf-8")
    assert "sys.stdout.buffer.write(canonical_json_bytes(result))" in orchestrator
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        for node in ast.walk(ast.parse(orchestrator))
    )
    shell = (SCRIPTS / "bootstrap.sh").read_bytes()
    powershell = (SCRIPTS / "bootstrap.ps1").read_bytes()
    assert not shell.startswith(b"\xef\xbb\xbf")
    assert powershell.startswith(b"\xef\xbb\xbf")
    assert "[Console]::OutputEncoding" in powershell.decode("utf-8-sig")


def test_renderer_fingerprint_binds_all_current_renderer_sources() -> None:
    baseline = json.loads(
        (SKILL_ROOT / "contracts/renderer-fingerprint-baseline.json").read_text(
            encoding="utf-8"
        )
    )
    assert baseline["rendererContract"] == "generation-renderer-v12"
    assert set(baseline["files"]) == {
        "scripts/package_renderer.py",
        "scripts/workbook.py",
        "scripts/office_engine.py",
        "scripts/story_notes.py",
    }
    assert baseline["files"] == {
        name: hashlib.sha256((SKILL_ROOT / name).read_bytes()).hexdigest()
        for name in baseline["files"]
    }


def test_generate_owns_the_only_bundled_sow_template() -> None:
    bundled = [
        path
        for path in PLUGIN_ROOT.rglob("sow-template.xlsx")
        if ".venv" not in path.parts
    ]
    assert bundled == [SKILL_ROOT / "assets/sow-template.xlsx"]


def test_no_generic_owner_pipeline_or_compatibility_wrapper_exists() -> None:
    forbidden_names = {
        "owner_pipeline.py",
        "owner_runner.py",
        "pipeline.py",
        "reconcile.py",
    }
    assert not [path for path in PLUGIN_ROOT.rglob("*.py") if path.name in forbidden_names]
    assert not (PLUGIN_ROOT / "contracts").exists()


def test_generate_action_protocol_can_route_every_delivery_reference() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "referencePaths" in skill
    for name in EXPECTED_DELIVERY_REFERENCES:
        assert (SKILL_ROOT / "references" / name).is_file()


def test_task_authoring_does_not_copy_live_catalog_values() -> None:
    task_authoring = (SKILL_ROOT / "references/task-authoring.md").read_text(
        encoding="utf-8"
    )
    assert "新建M档人天" not in task_authoring
    assert "37 个基础单元" not in task_authoring


def test_every_retired_legacy_fixture_has_a_hash_bound_replacement_and_test() -> None:
    manifest = json.loads(
        (
            SKILL_ROOT
            / "fixtures/pipeline/legacy-fixture-retirement.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["contract"] == "ai-sow-legacy-fixture-retirement-v1"
    assert len(manifest["entries"]) == 10
    for entry in manifest["entries"]:
        assert not (SKILL_ROOT / entry["legacyPath"]).exists()
        replacement = SKILL_ROOT / entry["replacementPath"]
        assert replacement.is_file()
        assert hashlib.sha256(replacement.read_bytes()).hexdigest() == entry[
            "replacementSha256"
        ]
        test_file, test_name = entry["replacementTest"].split("::", 1)
        test_source = (SKILL_ROOT / "tests" / test_file).read_text(encoding="utf-8")
        assert f"def {test_name}" in test_source
