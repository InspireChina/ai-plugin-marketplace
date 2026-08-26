from __future__ import annotations

import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_CONTRACT = PLUGIN_ROOT / "references/runtime-environment.md"
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

RUNTIME_SKILL_NAMES = tuple(name for name in SKILL_NAMES if name != "setup")


def test_every_skill_uses_installed_plugin_paths() -> None:
    for skill_name in SKILL_NAMES:
        skill_root = PLUGIN_ROOT / "skills" / skill_name
        text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        assert "plugin/skills/" not in text, skill_name
        assert "<plugin-root>" in text, skill_name


def test_post_setup_skills_use_bootstrapped_python_without_path_uv() -> None:
    assert RUNTIME_CONTRACT.is_file()
    runtime_contract = RUNTIME_CONTRACT.read_text(encoding="utf-8")
    assert "<plugin-root>/.venv/bin/python" in runtime_contract
    assert "<plugin-root>/.venv/Scripts/python.exe" in runtime_contract
    assert "无需预装" in runtime_contract
    for skill_name in RUNTIME_SKILL_NAMES:
        text = (PLUGIN_ROOT / "skills" / skill_name / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "../../references/runtime-environment.md" in text, skill_name
        assert '"<python-bin>"' in text, skill_name
        assert "uv run --project" not in text, skill_name
        assert "uv --directory" not in text, skill_name


def test_every_referenced_skill_script_exists() -> None:
    pattern = re.compile(r'<skill-root>/scripts/([^"\s`]+)')
    for skill_name in SKILL_NAMES[:-1]:
        skill_root = PLUGIN_ROOT / "skills" / skill_name
        text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        scripts = pattern.findall(text)
        assert scripts, skill_name
        for script in scripts:
            assert (skill_root / "scripts" / script).is_file(), (
                skill_name,
                script,
            )
