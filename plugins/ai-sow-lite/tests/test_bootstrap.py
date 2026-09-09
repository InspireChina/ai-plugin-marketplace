"""Adapted installation boundary tests from ai-sow 2fc8588; no old runner."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from .support.fixtures import PLUGIN, write_json


def test_script_encodings_preserve_chinese_on_shell_and_windows_powershell():
    bash = (PLUGIN / "scripts/bootstrap.sh").read_bytes()
    powershell = (PLUGIN / "scripts/bootstrap.ps1").read_bytes()
    assert not bash.startswith(b"\xef\xbb\xbf")
    assert powershell.startswith(b"\xef\xbb\xbf")
    assert bash.decode("utf-8")
    assert powershell.decode("utf-8-sig")


@pytest.mark.parametrize("arguments", [[], ["--not-supported"], ["--request", "missing.json"]])
def test_cli_argument_and_io_failures_have_one_json_envelope(tmp_path, arguments):
    proc = subprocess.run([sys.executable, str(PLUGIN / "scripts/lite.py"), *arguments], cwd=tmp_path,
                          capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert proc.returncode in (2, 3)
    result = json.loads(proc.stdout)
    assert result["ok"] is False
    assert set(result) == {"ok", "request_id", "operation", "result", "diagnostics"}
    assert not proc.stderr


@pytest.mark.parametrize("text", ['{"private":"机密","a":1,"a":2}', '"\\ud800"', '{broken'])
def test_cli_bad_json_is_redacted(tmp_path, text):
    request = tmp_path / "输入.json"
    request.write_text(text, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(PLUGIN / "scripts/lite.py"), "--request", str(request)],
                          capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["diagnostics"][0]["code"] == "PROTOCOL_INVALID"
    assert "机密" not in proc.stdout and not proc.stderr


@pytest.mark.parametrize("platform", ["bash", "powershell"])
def test_bootstrap_reuses_isolated_environment_and_forwards_utf8_request(tmp_path, platform):
    pwsh = shutil.which("pwsh")
    if platform == "powershell" and pwsh is None:
        pytest.skip("PowerShell is unavailable; Windows execution is not verified")
    if platform == "bash" and os.name != "posix":
        pytest.skip("Bash execution requires POSIX")
    # Use a real uv sync in an isolated copy, without modifying host plugin installs.
    plugin = tmp_path / "插件目录 with spaces"
    shutil.copytree(PLUGIN, plugin, ignore=shutil.ignore_patterns(".venv", ".ai-sow-tools", "__pycache__", ".pytest_cache"))
    project = tmp_path / ("中文项目-" * 12) / "用户项目"
    project.mkdir(parents=True)
    request = tmp_path / "请求 信封.json"
    write_json(request, dict(protocol_version="1.0", request_id="00000000-0000-4000-8000-000000000001",
                            project_path=str(project), operation="inspect", payload={}))
    # Source version adaptation: longest actual work/report path, not old 97-char threshold.
    longest = project / ".ai-sow-lite/work/generate/00000000-0000-4000-8000-000000000001/checks" / ("f" * 64 + ".json")
    longest.parent.mkdir(parents=True)
    longest.write_text("中文 UTF-8", encoding="utf-8")
    assert longest.read_text(encoding="utf-8") == "中文 UTF-8"
    if platform == "bash":
        command = ["sh", str(plugin / "scripts/bootstrap.sh"), "--request", str(request)]
    else:
        command = [pwsh, "-NoProfile", "-File", str(plugin / "scripts/bootstrap.ps1"), "-Request", str(request)]
    env = {**os.environ, "PYTHONUTF8": "1", "POWERSHELL_TELEMETRY_OPTOUT": "1"}
    first = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert first.returncode == 2, (first.stdout, first.stderr)
    assert json.loads(first.stdout)["diagnostics"][0]["code"] == "OPERATION_UNSUPPORTED"
    executable = plugin / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    identity = executable.stat().st_mtime_ns
    second = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert second.returncode == 2, (second.stdout, second.stderr)
    assert executable.stat().st_mtime_ns == identity
    assert json.loads(second.stdout)["request_id"] == "00000000-0000-4000-8000-000000000001"
    assert not (project / ".ai-sow-lite/current.json").exists()
