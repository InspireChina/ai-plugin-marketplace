from __future__ import annotations

import ast
import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1]
RUNTIME = PLUGIN_ROOT / "runtime"
SKILL_NAMES = (
    "setup",
    "analyze-requirement",
    "analyze-as-is",
    "generate-design",
    "generate-story",
    "generate-task",
    "generate-sow",
    "reconcile",
)
PROFESSIONAL_OWNER_NAMES = (
    "analyze-requirement",
    "analyze-as-is",
    "generate-design",
    "generate-story",
    "generate-task",
)
OWNER_REVIEW_ALGORITHMS = (
    "ai-sow-owner-review-packet-v1",
    "ai-sow-owner-reviewer-v1",
    "ai-sow-owner-approval-v1",
)
MODULE_TO_SKILL = {name.replace("-", "_"): name for name in SKILL_NAMES}
ASSET_CATEGORIES = "contracts|fixtures|tests|assets|scripts|references"
SKILL_ASSET = re.compile(
    rf"(?:^|/)(?P<target>{'|'.join(map(re.escape, SKILL_NAMES))})/"
    rf"(?P<category>{ASSET_CATEGORIES})/(?P<rest>[^\s`'\"]+)"
)

# Task 7 completes the transition: no cross-Skill or legacy runtime edge remains.
TRANSITION_DEPENDENCY_EDGES: set[tuple[str, str, str]] = set()


def python_sources(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if ".venv" not in path.parts and "__pycache__" not in path.parts
    )


def _import_target(module: str, caller_skill: str) -> str | None:
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "skills":
        return None
    target_skill = MODULE_TO_SKILL.get(parts[1])
    if target_skill is None or target_skill == caller_skill:
        return None
    suffix = "/".join(parts[2:])
    return f"skills/{target_skill}/{suffix}.py" if suffix else f"skills/{target_skill}"


def _divided_string_fragments(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value.strip("/")]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _divided_string_fragments(node.left) + _divided_string_fragments(node.right)
    return []


def dependency_edges_from_tree(
    tree: ast.AST,
    relative: str,
    caller_skill: str,
) -> set[tuple[str, str, str]]:
    edges: set[tuple[str, str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "runtime.review_gates":
                edges.add((relative, "runtime/review_gates.py", "IMPORT"))
            target = _import_target(node.module, caller_skill)
            if target:
                edges.add((relative, target, "IMPORT"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "runtime.review_gates":
                    edges.add((relative, "runtime/review_gates.py", "IMPORT"))
                target = _import_target(alias.name, caller_skill)
                if target:
                    edges.add((relative, target, "IMPORT"))
        candidates: list[str] = []
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            candidates.append(node.value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            fragments = _divided_string_fragments(node)
            if fragments:
                candidates.append("/".join(fragments))
        for candidate in candidates:
            for match in SKILL_ASSET.finditer(candidate):
                target_skill = match.group("target")
                if target_skill == caller_skill:
                    continue
                target = (
                    f"skills/{target_skill}/{match.group('category')}/"
                    f"{match.group('rest')}"
                )
                kind = "EXECUTE" if match.group("category") == "scripts" else "READ"
                edges.add((relative, target, kind))
    return edges


def dependency_edges() -> set[tuple[str, str, str]]:
    edges: set[tuple[str, str, str]] = set()
    for source in python_sources(PLUGIN_ROOT / "skills"):
        relative = source.relative_to(PLUGIN_ROOT).as_posix()
        caller_skill = source.relative_to(PLUGIN_ROOT / "skills").parts[0]
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        edges.update(dependency_edges_from_tree(tree, relative, caller_skill))
    return edges


def _writes_to_stdout(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        for node in ast.walk(tree)
    )


def assigned_string(path: Path, name: str) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id == name
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def test_skill_entry_scripts_pin_utf8_standard_streams() -> None:
    """Windows 控制台代码页不是 UTF-8，未固定编码的脚本会输出调用方无法解码的字节。"""
    unpinned: list[str] = []
    for path in python_sources(PLUGIN_ROOT / "skills"):
        if path.parent.name != "scripts":
            continue
        source = path.read_text(encoding="utf-8")
        if not _writes_to_stdout(ast.parse(source)):
            continue
        if (
            'sys.stdout.reconfigure(encoding="utf-8")' not in source
            or 'sys.stderr.reconfigure(encoding="utf-8")' not in source
        ):
            unpinned.append(str(path.relative_to(PLUGIN_ROOT)))
    assert unpinned == []


def test_runtime_is_plugin_shared_owner_agnostic_infrastructure() -> None:
    assert {path.name for path in RUNTIME.glob("*.py")} == {
        "__init__.py",
        "authorization.py",
        "context_pages.py",
        "claims.py",
        "controls.py",
        "diagnostics.py",
        "fact_source.py",
        "handoff.py",
        "patch.py",
        "project_io.py",
        "review_checks.py",
        "text_gates.py",
    }
    for name in {path.name for path in RUNTIME.glob("*.py")} - {"__init__.py"}:
        text = (RUNTIME / name).read_text(encoding="utf-8")
        assert "skills/" not in text
        assert "skills." not in text
        assert "urn:ai-sow:" not in text


def test_generator_contract_is_versioned_and_reconcile_uses_the_same_contract() -> None:
    generator = PLUGIN_ROOT / "skills/generate-sow/scripts/generate_sow.py"
    reconcile = PLUGIN_ROOT / "skills/reconcile/scripts/reconcile.py"

    assert assigned_string(generator, "GENERATOR_CONTRACT") == "receipt-only-v2"
    assert assigned_string(reconcile, "GENERATOR_CONTRACT") == "receipt-only-v2"


def test_shared_review_gates_have_one_implementation_and_all_owners_call_them() -> None:
    gate_definitions = {
        "validate_review_artifacts": "review_checks.py",
        "validate_text_gates": "text_gates.py",
        "validate_unique_fact_sources": "fact_source.py",
        "validate_patch_audit": "patch.py",
    }
    runtime_sources = {
        path.name: path.read_text(encoding="utf-8") for path in python_sources(RUNTIME)
    }
    for function, owner_module in gate_definitions.items():
        definitions = [
            module for module, text in runtime_sources.items()
            if re.search(rf"^def {re.escape(function)}\(", text, re.MULTILINE)
        ]
        assert definitions == [owner_module]
    for owner in PROFESSIONAL_OWNER_NAMES:
        validator = (
            PLUGIN_ROOT / "skills" / owner / "scripts" / "validate.py"
        ).read_text(encoding="utf-8")
        assert "validate_review_artifacts(" in validator, owner
        wrapper = PLUGIN_ROOT / "skills" / owner / "scripts" / "apply_patch.py"
        assert wrapper.is_file(), owner
        assert "runtime.patch" in wrapper.read_text(encoding="utf-8"), owner


def test_transition_dependency_edges_are_complete_and_exact() -> None:
    assert dependency_edges() == TRANSITION_DEPENDENCY_EDGES
    for _, target, _ in TRANSITION_DEPENDENCY_EDGES:
        assert (PLUGIN_ROOT / target).exists(), target


def test_dependency_scanner_detects_new_import_and_split_path_edges() -> None:
    source = """
from skills.setup.scripts.setup import main

schema = root / "generate-design" / "contracts" / "design.schema.json"
"""
    edges = dependency_edges_from_tree(
        ast.parse(source),
        "skills/generate-story/scripts/example.py",
        "generate-story",
    )
    assert edges == {
        (
            "skills/generate-story/scripts/example.py",
            "skills/setup/scripts/setup.py",
            "IMPORT",
        ),
        (
            "skills/generate-story/scripts/example.py",
            "skills/generate-design/contracts/design.schema.json",
            "READ",
        ),
    }
    assert not edges.issubset(TRANSITION_DEPENDENCY_EDGES)


def test_runtime_does_not_import_skills() -> None:
    for source in python_sources(RUNTIME):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not [
            name for name in imported if name == "skills" or name.startswith("skills.")
        ]


def test_no_generic_owner_pipeline_or_runner_exists() -> None:
    forbidden = {"owner_pipeline.py", "owner_runner.py", "pipeline.py"}
    assert not [path for path in PLUGIN_ROOT.rglob("*.py") if path.name in forbidden]


def test_all_professional_owners_freeze_owner_local_candidate_first_interface() -> None:
    for owner in PROFESSIONAL_OWNER_NAMES:
        skill_root = PLUGIN_ROOT / "skills" / owner
        assert {
            path.name for path in (skill_root / "scripts").glob("*.py")
        }.issuperset({"prepare_context.py", "render_review.py", "validate.py"})

        skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        validator = (skill_root / "scripts" / "validate.py").read_text(encoding="utf-8")
        assert "当前 Stage" in skill
        assert "不得复读 `scripts/*.py` 实现" in skill, owner
        assert "## 精确批准快速路径" in skill, owner
        assert "不得枚举项目或插件文件" in skill, owner
        assert "不得运行 `--help`" in skill, owner
        assert "独立 `check`" in skill, owner
        assert "正式写入前唯一需要的 preflight" in skill, owner
        assert "不得手写 approval JSON" in skill, owner
        assert "不得手写 reviewer JSON" in skill, owner
        assert "--mode record-reviewer" in skill, owner
        assert "--review-decision PASS" in skill, owner
        assert "--mode write-approval" in skill, owner
        assert "--packet-sha256" in skill, owner
        assert "不得使用 `rg`、`find` 或 `rg --files`" in skill, owner
        for algorithm in OWNER_REVIEW_ALGORITHMS:
            assert algorithm in skill, (owner, algorithm)
            assert algorithm in validator, (owner, algorithm)
        for mode in (
            "review",
            "record-reviewer",
            "write-reviewer",
            "write-approval",
            "publish-approved",
            "check",
            "publish",
            "rebind",
        ):
            assert f'"{mode}"' in validator, (owner, mode)

    as_is_skill = (
        PLUGIN_ROOT / "skills/analyze-as-is/SKILL.md"
    ).read_text(encoding="utf-8")
    as_is_validator = (
        PLUGIN_ROOT / "skills/analyze-as-is/scripts/validate.py"
    ).read_text(encoding="utf-8")
    assert "--mode upstream-check" in as_is_skill
    assert '"upstream-check"' in as_is_validator

    story_skill = (
        PLUGIN_ROOT / "skills/generate-story/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "contracts/delivery.schema.json" in story_skill
    assert "不得用 `ls`、glob、`rg` 或目录枚举寻找 Schema" in story_skill
    assert "每个 `requiredIntegrationBoundary` 非 `NONE` 的 Story" in story_skill
    assert "不得只挂到共享使能 Story" in story_skill
    assert "INTEGRATION_SCOPE_OVERLAP" in (
        PLUGIN_ROOT / "skills/generate-story/scripts/validate.py"
    ).read_text(encoding="utf-8")
    assert "不得再次聚合相关 BUSINESS Story 已拥有的外部目标" in story_skill
    task_skill = (
        PLUGIN_ROOT / "skills/generate-task/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "contracts/estimate.schema.json" in task_skill
    assert "不得用 `ls`、glob、`rg` 或目录枚举寻找 Schema" in task_skill
    assert (
        '`workModeRationale = "<effectiveStartItemName>保持不变；'
        '<projectSideWorkCommitment>。"`'
    ) in task_skill
    assert "明确点名当前基础单元可调整的既有资产" in task_skill
    assert "复用既有 CI/CD 执行本项目的新切换仍是 `新建`" in task_skill
    assert "机械门禁只允许一次整体修正" in task_skill
    assert (
        "`<plugin-root>/skills/generate-task/contracts/estimate.schema.json`"
        in task_skill
    )
    assert "五个 fragment 各读取且只读取一次" in task_skill
    assert "普通 candidate 流程不得运行 `read_template.py`" in task_skill
    assert "`<plugin-root>/references/output-language.md`" in task_skill
    assert "`<plugin-root>/skills/references/`" in task_skill
    for public_treatment_rule in (
        "`IMPLEMENTED` → `CURRENT_BASELINE`",
        "`PARTIAL / NOT_IMPLEMENTED` → `EXPECTED_BEFORE_START / CARRY_FORWARD / NEEDS_DECISION`",
        "`UNVERIFIED` → `NEEDS_DECISION`",
        "`SUPERSEDED` → `EXCLUDE`",
    ):
        assert public_treatment_rule in as_is_skill


def test_candidate_first_algorithms_remain_owner_contract_not_shared_runtime() -> None:
    design = (
        PLUGIN_ROOT / "docs" / "AI_SOW_PLUGIN_DESIGN.md"
    ).read_text(encoding="utf-8")
    context = (PLUGIN_ROOT / "docs" / "CONTEXT.md").read_text(encoding="utf-8")
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8") for path in python_sources(RUNTIME)
    )
    for algorithm in OWNER_REVIEW_ALGORITHMS:
        assert algorithm not in runtime_text
    assert "candidate-first" in design
    assert "candidate-first" in context


def test_reconcile_publisher_does_not_interpret_story_ac_business_review() -> None:
    source = (
        PLUGIN_ROOT / "skills/reconcile/scripts/reconcile.py"
    ).read_text(encoding="utf-8")
    for token in ("Story/AC", "STORY_AC", "Outcome Change", "Exact Diff"):
        assert token not in source


def test_reconcile_uses_public_project_view_tombstone_contract() -> None:
    source = (
        PLUGIN_ROOT / "skills/reconcile/scripts/reconcile.py"
    ).read_text(encoding="utf-8")
    assert ".is_tombstoned(" in source
    assert "._is_tombstoned(" not in source
    assert "._parts(" not in source
