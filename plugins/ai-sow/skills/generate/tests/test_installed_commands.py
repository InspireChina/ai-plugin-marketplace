from __future__ import annotations

TEST_LAYER = "integration"

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest


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


def test_new_material_requires_new_run_cli_rejects_resume_request(tmp_path):
    from test_orchestrator import managed_snapshot, write_budget_policy, write_run_store_request
    import orchestrator
    request = write_run_store_request(tmp_path)
    orchestrator.run_mode(tmp_path, "start", request=request, budget_policy=write_budget_policy(tmp_path))
    before = managed_snapshot(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts/orchestrator.py"),
         "--project-root", str(tmp_path), "--mode", "resume", "--request", request],
        capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert json.loads(result.stdout)["diagnostics"][0]["code"] == "CLI_ARGUMENTS_INVALID"
    assert managed_snapshot(tmp_path) == before


def test_public_budget_policy_seam_cli_accepts_explicit_policy(tmp_path):
    if str(SKILL_ROOT / "tests") not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT / "tests"))
    from test_orchestrator import write_budget_policy, write_run_store_request

    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts/orchestrator.py"),
         "--project-root", str(tmp_path), "--mode", "start", "--request", request,
         "--budget-policy", budget],
        capture_output=True, check=False,
    )
    body = json.loads(result.stdout)
    assert result.returncode == 0, body
    assert body["nextAction"]["budgetPolicySha256"]


@pytest.mark.parametrize("platform", ["posix", "powershell"])
def test_public_budget_policy_seam_bootstrap_forwards_explicit_policy(platform):
    if os.name != "posix":
        pytest.skip("此隔离复制运行时用例验证 POSIX 主机上的两种参数转发。")
    pwsh = shutil.which("pwsh")
    if platform == "powershell" and pwsh is None:
        pytest.skip("需要显式提供 portable pwsh 以执行参数行为验证。")
    if str(SKILL_ROOT / "tests") not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT / "tests"))
    from test_orchestrator import write_budget_policy, write_run_store_request

    with tempfile.TemporaryDirectory(prefix="sow-cli-", dir="/tmp") as directory:
        root = Path(directory)
        plugin = root / "plugin"
        project = root / "project"
        project.mkdir()
        shutil.copytree(PLUGIN_ROOT, plugin, symlinks=True,
                        ignore=shutil.ignore_patterns(".ai-sow-tools", "__pycache__", ".pytest_cache"))
        request = write_run_store_request(project)
        budget = write_budget_policy(project)
        scripts = plugin / "skills/generate/scripts"
        environment = {**os.environ, "POWERSHELL_TELEMETRY_OPTOUT": "1",
                       "XDG_CACHE_HOME": str(root / "cache"), "XDG_CONFIG_HOME": str(root / "config")}
        if platform == "posix":
            command = ["sh", str(scripts / "bootstrap.sh"), "--project-root", str(project),
                       "--mode", "start", "--request", request, "--budget-policy", budget]
        else:
            windows_layout = plugin / ".venv/Scripts"
            windows_layout.mkdir(exist_ok=True)
            (windows_layout / "python.exe").symlink_to("../bin/python")
            command = [pwsh, "-NoProfile", "-File", str(scripts / "bootstrap.ps1"),
                       "-ProjectRoot", str(project), "-Mode", "start", "-Request", request,
                       "-BudgetPolicy", budget]
        result = subprocess.run(command, capture_output=True, check=False, env=environment)
        assert result.returncode == 0, (result.stdout, result.stderr)
        body = json.loads(result.stdout)
        assert body["outcome"] == "ACTIVE"
        assert body["nextAction"]["budgetPolicySha256"]


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
