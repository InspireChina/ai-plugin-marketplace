from __future__ import annotations

import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SKILL_NAMES = (
    "setup",
    "analyze-requirement",
    "analyze-as-is",
    "generate-design",
    "generate-story",
    "generate-task",
    "generate-sow",
)


def test_every_skill_uses_installed_plugin_paths() -> None:
    for skill_name in SKILL_NAMES:
        skill_root = PLUGIN_ROOT / "skills" / skill_name
        text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        assert "plugin/skills/" not in text, skill_name
        assert "<plugin-root>" in text, skill_name
        assert 'uv run --project "<plugin-root>" --locked python' in text, skill_name


def test_every_referenced_skill_script_exists() -> None:
    pattern = re.compile(r'<skill-root>/scripts/([^"\s`]+)')
    for skill_name in SKILL_NAMES:
        skill_root = PLUGIN_ROOT / "skills" / skill_name
        text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        scripts = pattern.findall(text)
        assert scripts, skill_name
        for script in scripts:
            assert (skill_root / "scripts" / script).is_file(), (
                skill_name,
                script,
            )
