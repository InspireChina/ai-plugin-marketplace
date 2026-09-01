from __future__ import annotations

from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
GENERATE_SKILL = SKILL_ROOT / "SKILL.md"
BOOTSTRAP_SH = SKILL_ROOT / "scripts/bootstrap.sh"
BOOTSTRAP_PS1 = SKILL_ROOT / "scripts/bootstrap.ps1"
ENABLE_LONG_PATHS = SKILL_ROOT / "scripts/enable_long_paths.ps1"


def test_generate_is_the_only_new_public_entry_before_legacy_removal() -> None:
    assert GENERATE_SKILL.is_file()
    assert "orchestrator.py" in GENERATE_SKILL.read_text(encoding="utf-8")


def test_bootstrap_invokes_only_generate_orchestrator() -> None:
    for script in (BOOTSTRAP_SH, BOOTSTRAP_PS1):
        text = script.read_text(encoding="utf-8-sig")
        assert "skills/generate/scripts/orchestrator.py" in text
        assert "skills/setup" not in text


def test_bootstrap_contract_is_pinned_and_self_contained() -> None:
    shell = BOOTSTRAP_SH.read_bytes()
    powershell = BOOTSTRAP_PS1.read_bytes()
    assert not shell.startswith(b"\xef\xbb\xbf")
    assert powershell.startswith(b"\xef\xbb\xbf")
    for text in (shell.decode("utf-8"), powershell.decode("utf-8-sig")):
        assert "0.11.7" in text
        assert "3.12" in text
        assert "--locked" in text
        assert "orchestrator.py" in text


def test_skill_has_no_stage_approval_stop() -> None:
    text = GENERATE_SKILL.read_text(encoding="utf-8")
    for token in ("packet SHA-256", "用户批准", "逐阶段", "reconcile"):
        assert token not in text


def test_skill_covers_one_shot_branches_and_supported_sources() -> None:
    text = GENERATE_SKILL.read_text(encoding="utf-8")
    for token in (
        "READY_FOR_SCOPE",
        "READY_FOR_DELIVERY",
        "REVIEW_REQUIRED",
        "READY_TO_RENDER",
        "REUSED",
        "BLOCKED",
        "Playwright",
        "Computer Use",
        "HTML",
        "TypeScript",
        "Markdown",
        "XLSX",
    ):
        assert token in text


def test_generate_owns_long_path_remedy() -> None:
    assert ENABLE_LONG_PATHS.is_file()
    text = ENABLE_LONG_PATHS.read_text(encoding="utf-8-sig")
    assert "LongPathsEnabled" in text
    assert "[switch]$Apply" in text
