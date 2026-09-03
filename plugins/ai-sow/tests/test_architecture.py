from __future__ import annotations

import ast
import json
import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1]
SKILL_ROOT = PLUGIN_ROOT / "skills/generate"
RUNTIME = PLUGIN_ROOT / "runtime"
SCRIPTS = SKILL_ROOT / "scripts"
EXPECTED_RUNTIME = {"__init__.py", "diagnostics.py", "project_io.py"}
EXPECTED_PYTHON_MODULES = {
    "contracts.py",
    "delivery_compiler.py",
    "final_review.py",
    "generation_store.py",
    "impact.py",
    "intake.py",
    "models.py",
    "office_engine.py",
    "orchestrator.py",
    "package_renderer.py",
    "questions.py",
    "review_material.py",
    "scope_compiler.py",
    "source_readers.py",
    "story_notes.py",
    "workbook.py",
}
LEGACY_PROTOCOL_TOKENS = (
    "ai-sow-owner-v1",
    "publish-approved",
    "write-approval",
    "Reconciliation Run ID",
    ".ai-sow/validation/",
)
EXPECTED_DELIVERY_REFERENCES = {
    "delivery-authoring.md",
    "delivery-decomposition.md",
    "technical-work-classification.md",
    "delivery-work-classification.md",
    "effective-start-matching.md",
    "question-authoring.md",
    "epic-authoring.md",
    "feature-authoring.md",
    "story-authoring.md",
    "acceptance-criteria.md",
    "task-authoring.md",
    "delivery-examples.md",
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
    assert {path.name for path in SCRIPTS.glob("*.py")} == EXPECTED_PYTHON_MODULES
    assert {
        path.name for path in SCRIPTS.iterdir() if path.is_file() and path.suffix != ".py"
    } == {"bootstrap.ps1", "bootstrap.sh", "enable_long_paths.ps1"}


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
    assert "orchestrator.py" in skill
    assert "一次连续调用" in skill
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
                if "prepare" in values:
                    choices = values
    assert choices == (
        "prepare",
        "accept-scope",
        "accept-delivery",
        "prepare-review",
        "accept-review",
        "publish",
        "status",
    )


def test_command_files_pin_utf8_and_platform_encodings() -> None:
    orchestrator = (SCRIPTS / "orchestrator.py").read_text(encoding="utf-8")
    assert "sys.stdout.buffer.write(canonical_json_bytes(result))" in orchestrator
    assert "print(" not in orchestrator
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
    assert baseline["rendererContract"] == "generation-renderer-v7"
    assert set(baseline["files"]) == {
        "scripts/package_renderer.py",
        "scripts/workbook.py",
        "scripts/office_engine.py",
        "scripts/story_notes.py",
    }
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", value)
        for value in baseline["files"].values()
    )


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


def test_generate_skill_routes_every_delivery_reference() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    for name in EXPECTED_DELIVERY_REFERENCES:
        assert f"references/{name}" in skill


def test_task_authoring_does_not_copy_live_catalog_values() -> None:
    task_authoring = (SKILL_ROOT / "references/task-authoring.md").read_text(
        encoding="utf-8"
    )
    assert "新建M档人天" not in task_authoring
    assert "37 个基础单元" not in task_authoring
