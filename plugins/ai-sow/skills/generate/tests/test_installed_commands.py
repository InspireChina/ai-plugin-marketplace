from __future__ import annotations

from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
GENERATE_SKILL = SKILL_ROOT / "SKILL.md"
BOOTSTRAP_SH = SKILL_ROOT / "scripts/bootstrap.sh"
BOOTSTRAP_PS1 = SKILL_ROOT / "scripts/bootstrap.ps1"
ENABLE_LONG_PATHS = SKILL_ROOT / "scripts/enable_long_paths.ps1"
EXECUTION_ENVELOPE = SKILL_ROOT / "prompts/fragments/execution-envelope.md"


PUBLIC_OPERATIONS = (
    "start",
    "submit",
    "hydrate",
    "resume",
    "approve",
    "abandon",
    "status",
)


def test_generate_is_the_only_public_entry() -> None:
    assert GENERATE_SKILL.is_file()
    assert "NextAction" in GENERATE_SKILL.read_text(encoding="utf-8")


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


def test_skill_has_no_legacy_stage_modes_or_product_cli_dependency() -> None:
    text = GENERATE_SKILL.read_text(encoding="utf-8")
    for token in (
        "accept-scope",
        "accept-story-ac",
        "accept-delivery",
        "prepare-review",
        "accept-review",
        "codex exec",
        "claude -p",
    ):
        assert token not in text


def test_skill_covers_host_neutral_next_action_loop_and_supported_sources() -> None:
    text = GENERATE_SKILL.read_text(encoding="utf-8")
    for token in (
        "MODEL_ACTION_GROUP",
        "REQUEST_INPUT",
        "REQUEST_APPROVAL",
        "DONE",
        "FRESH_NO_HISTORY",
        "Windows",
        "macOS",
        "Linux",
        "HTML",
        "TypeScript",
        "Markdown",
        "XLSX",
    ):
        assert token in text


def test_bootstraps_expose_exactly_seven_public_operations() -> None:
    powershell = BOOTSTRAP_PS1.read_text(encoding="utf-8-sig")
    skill = GENERATE_SKILL.read_text(encoding="utf-8")
    for operation in PUBLIC_OPERATIONS:
        assert f'"{operation}"' in powershell
        assert operation in skill
    for retired in (
        "accept-scope",
        "accept-story-ac",
        "accept-delivery",
        "prepare-review",
        "accept-review",
        '"publish"',
    ):
        assert retired not in powershell


def test_generate_owns_long_path_remedy() -> None:
    assert ENABLE_LONG_PATHS.is_file()
    text = ENABLE_LONG_PATHS.read_text(encoding="utf-8-sig")
    assert "LongPathsEnabled" in text
    assert "[switch]$Apply" in text


def test_execution_envelope_is_host_neutral_and_forbids_history_inheritance() -> None:
    text = EXECUTION_ENVELOPE.read_text(encoding="utf-8")
    for token in (
        "FRESH_NO_HISTORY",
        "inheritConversation = false",
        "packetPath",
        "outputPath",
        "recordPath",
        "hydrate",
        "submit",
    ):
        assert token in text
    for host_command in ("codex exec", "claude -p", "bash -c", "powershell -Command"):
        assert host_command not in text
