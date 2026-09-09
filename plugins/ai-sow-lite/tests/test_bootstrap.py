"""Adapted installation boundary tests from ai-sow 2fc8588; no old runner."""
import json
import os
from pathlib import Path
import shlex
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


@pytest.fixture(scope="module")
def python_seed(tmp_path_factory):
    """A real managed install; an optional local seed avoids another download."""
    uv = shutil.which("uv")
    assert uv and subprocess.check_output([uv, "--version"], text=True).startswith("uv 0.11.7")
    supplied = os.environ.get("AI_SOW_LITE_TEST_PYTHON_SEED")
    if supplied:
        return uv, Path(supplied)
    root = tmp_path_factory.mktemp("managed-python-seed")
    env = {**os.environ, "UV_PYTHON_INSTALL_DIR": str(root / "python"),
           "UV_PYTHON_BIN_DIR": str(root / "user-bin"), "UV_CACHE_DIR": str(root / "cache")}
    subprocess.run([uv, "python", "install", "3.12", "--no-bin", "--no-registry"],
                   env=env, check=True, capture_output=True, timeout=180)
    assert not (root / "user-bin").exists()
    return uv, root / "python"


def copy_managed_python(seed, plugin):
    target = plugin / ".ai-sow-tools/python"
    # Independent file bytes; retain only symlinks resolving inside the new copy.
    target.mkdir(parents=True)
    for install in seed.glob("cpython-*"):
        if install.is_dir() and not install.is_symlink():
            shutil.copytree(install, target / install.name, symlinks=True)
    for path in target.rglob("*"):
        if path.is_symlink():
            assert path.resolve().is_relative_to(target.resolve()), path


@pytest.mark.parametrize("script", ["bootstrap.sh", "bootstrap.ps1"])
def test_python_install_disables_host_registration(script):
    text = (PLUGIN / "scripts" / script).read_text(encoding="utf-8-sig")
    install = next(line for line in text.splitlines() if 'python install' in line or '"python", "install"' in line)
    assert "--no-bin" in install and "--no-registry" in install


def tree_state(root):
    """Capture only a test-owned tree, including names and original file bytes."""
    if not root.exists():
        return None
    return {str(path.relative_to(root)): (os.readlink(path) if path.is_symlink()
            else None if path.is_dir() else path.read_bytes()) for path in root.rglob("*")}


@pytest.mark.parametrize("platform", ["bash", "powershell"])
@pytest.mark.parametrize("dangling", [False, True], ids=["live", "dangling"])
@pytest.mark.parametrize("relative", [".venv", ".ai-sow-tools", ".ai-sow-tools/bin",
                                      ".ai-sow-tools/cache", ".ai-sow-tools/python"])
def test_bootstrap_refuses_linked_write_roots_before_any_writes_or_uv(tmp_path, platform, dangling, relative):
    pwsh = shutil.which("pwsh")
    if platform == "powershell" and pwsh is None:
        pytest.skip("PowerShell unavailable; reparse/junction execution is not verified")
    if platform == "bash" and os.name != "posix":
        pytest.skip("POSIX shell unavailable")
    plugin = tmp_path / "plugin"
    shutil.copytree(PLUGIN / "scripts", plugin / "scripts")
    outside = tmp_path / "foreign runtime"
    outside.mkdir()
    link = plugin / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                       check=True, capture_output=True, timeout=30)
    else:
        link.symlink_to(outside, target_is_directory=True)
    if dangling:
        outside.rmdir()
    else:
        (outside / "unrelated-sentinel.txt").write_bytes(b"keep\r\n\x00original")
        (outside / "nested").mkdir()
        (outside / "nested/original.bin").write_bytes(bytes(range(256)))
    before, local_before = tree_state(outside), tree_state(plugin)
    # A tripwire at the external-command boundary: rejection must precede any uv call.
    tools = tmp_path / "tripwire-bin"
    tools.mkdir()
    audit = tmp_path / "uv-called.txt"
    if os.name == "nt":
        (tools / "uv.cmd").write_text(f'@echo off\necho called >> "{audit}"\nif "%~1"=="--version" (echo uv 0.11.7 & exit /b 0)\nexit /b 90\n')
    else:
        shim = tools / "uv"
        shim.write_text(f"#!/bin/sh\nprintf '%s\\n' called >> {shlex.quote(str(audit))}\n"
                        'if [ "$1" = "--version" ]; then printf "uv 0.11.7\\n"; exit 0; fi\nexit 90\n')
        shim.chmod(0o755)
    env = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
           "UV_OFFLINE": "1", "UV_PYTHON_BIN_DIR": str(tmp_path / "captured-bin")}
    request = tmp_path / "unused-request.json"
    command = (["sh", str(plugin / "scripts/bootstrap.sh"), "--request", str(request)] if platform == "bash"
               else [pwsh, "-NoProfile", "-File", str(plugin / "scripts/bootstrap.ps1"), "-Request", str(request)])
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 3
    response = json.loads(result.stdout)
    assert response["diagnostics"][0]["code"] == "BOOTSTRAP_PATH_UNSAFE", response
    assert response["ok"] is False and response["request_id"] is None
    assert not result.stderr and not audit.exists()
    assert tree_state(outside) == before
    assert tree_state(plugin) == local_before
    assert not (tmp_path / "captured-bin").exists()


def test_bootstrap_directory_symlink_preserves_external_bytes_with_real_uv(tmp_path, python_seed):
    if os.name != "posix":
        pytest.skip("Real POSIX uv cleanup seam; Windows execution is separately conditional")
    uv, seed = python_seed
    plugin = tmp_path / "plugin"
    shutil.copytree(PLUGIN, plugin, ignore=shutil.ignore_patterns(
        ".venv", ".ai-sow-tools", "__pycache__", ".pytest_cache", "tests"))
    copy_managed_python(seed, plugin)
    outside = tmp_path / "foreign-venv"
    (outside / "nested").mkdir(parents=True)
    (outside / "unrelated-sentinel.txt").write_bytes(b"preserve this external environment\r\n")
    (outside / "nested/original.bin").write_bytes(bytes(range(256)))
    (plugin / ".venv").symlink_to(outside, target_is_directory=True)
    before = tree_state(outside)
    audit = tmp_path / "actual-uv-calls.txt"
    local_uv = plugin / ".ai-sow-tools/bin/uv"
    local_uv.parent.mkdir()
    # Transparent audit wrapper delegates every invocation to the real pinned uv.
    local_uv.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {shlex.quote(str(audit))}\nexec {shlex.quote(uv)} "$@"\n')
    local_uv.chmod(0o755)
    env = {**os.environ, "UV_OFFLINE": "1", "UV_PYTHON_BIN_DIR": str(tmp_path / "captured-bin")}
    result = subprocess.run(["sh", str(plugin / "scripts/bootstrap.sh"), "--request", str(tmp_path / "unused.json")],
                            env=env, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    calls = audit.read_text() if audit.exists() else ""
    assert tree_state(outside) == before, {"response": result.stdout, "real_uv_calls": calls}
    assert (plugin / ".venv").is_symlink() and not calls
    assert result.returncode == 3 and not result.stderr
    assert json.loads(result.stdout)["diagnostics"][0]["code"] == "BOOTSTRAP_PATH_UNSAFE"
    assert not (tmp_path / "captured-bin").exists()


@pytest.mark.parametrize("platform", ["bash", "powershell"])
@pytest.mark.parametrize("foreign_venv", [False, True], ids=["fresh-copy", "recover-foreign-venv"])
def test_bootstrap_reuses_isolated_environment_and_forwards_utf8_request(tmp_path, platform, foreign_venv, python_seed):
    pwsh = shutil.which("pwsh")
    if platform == "powershell" and pwsh is None:
        pytest.skip("PowerShell is unavailable; Windows execution is not verified")
    if platform == "bash" and os.name != "posix":
        pytest.skip("Bash execution requires POSIX")
    # Both copies execute real uv/bootstrap; all possible user-bin links are captured.
    uv, seed = python_seed
    first_plugin = tmp_path / "第一份 插件"
    plugin = tmp_path / "第二份 插件 with spaces"
    for destination in (first_plugin, plugin):
        shutil.copytree(PLUGIN, destination, ignore=shutil.ignore_patterns(
            ".venv", ".ai-sow-tools", "__pycache__", ".pytest_cache", "tests"))
    copy_managed_python(seed, first_plugin)
    if foreign_venv:
        copy_managed_python(seed, plugin)
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
    def command_for(path):
        if platform == "bash":
            return ["sh", str(path / "scripts/bootstrap.sh"), "--request", str(request)]
        return [pwsh, "-NoProfile", "-File", str(path / "scripts/bootstrap.ps1"), "-Request", str(request)]

    user_bin = tmp_path / "captured-user-bin"
    user_bin.mkdir()
    (user_bin / "unrelated.txt").write_text("keep", encoding="utf-8")
    env = {**os.environ, "PYTHONUTF8": "1", "POWERSHELL_TELEMETRY_OPTOUT": "1",
           "UV_PYTHON_BIN_DIR": str(user_bin)}
    initial = subprocess.run(command_for(first_plugin), cwd=tmp_path, env=env, capture_output=True,
                             text=True, encoding="utf-8", timeout=180)
    assert initial.returncode == 2, (initial.stdout, initial.stderr)
    relative_python = ".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"
    base_probe = ["-c", "import os,sys; print(os.path.realpath(sys._base_executable))"]
    first_python = first_plugin / relative_python
    first_base = Path(subprocess.check_output([str(first_python), *base_probe], text=True).strip())
    assert first_base.is_relative_to((first_plugin / ".ai-sow-tools/python").resolve())
    if foreign_venv:
        subprocess.run([uv, "venv", "--no-project", "--no-python-downloads", "--python", str(first_base),
                        str(plugin / ".venv")], env=env, cwd=tmp_path, check=True, capture_output=True, timeout=30)
    env.update(PATH=os.pathsep.join([str(first_python.parent), str(first_base.parent), env["PATH"]]),
               VIRTUAL_ENV=str(first_plugin / ".venv"), UV_PYTHON=str(first_base),
               UV_PROJECT_ENVIRONMENT=str(first_plugin / ".venv"))
    command = command_for(plugin)
    first = subprocess.run(command, cwd=first_plugin, env=env, capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert first.returncode == 2, (first.stdout, first.stderr)
    assert json.loads(first.stdout)["diagnostics"][0]["code"] == "OPERATION_UNSUPPORTED"
    executable = plugin / relative_python
    base = Path(subprocess.check_output([str(executable), *base_probe], text=True).strip())
    assert base.is_relative_to((plugin / ".ai-sow-tools/python").resolve()), base
    assert sorted(path.name for path in user_bin.iterdir()) == ["unrelated.txt"]
    assert (user_bin / "unrelated.txt").read_text(encoding="utf-8") == "keep"
    # Removing the other copy must not break this runtime or cause a new download.
    shutil.rmtree(first_plugin)
    usable = subprocess.run([str(executable), "-c", "import jsonschema, openpyxl"], capture_output=True, timeout=30)
    assert usable.returncode == 0, usable.stderr
    identity = executable.stat().st_mtime_ns
    managed_identity = base.stat().st_mtime_ns
    env["UV_OFFLINE"] = "1"
    second = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert second.returncode == 2, (second.stdout, second.stderr)
    assert executable.stat().st_mtime_ns == identity
    assert base.stat().st_mtime_ns == managed_identity
    assert sorted(path.name for path in user_bin.iterdir()) == ["unrelated.txt"]
    assert json.loads(second.stdout)["request_id"] == "00000000-0000-4000-8000-000000000001"
    assert not (project / ".ai-sow-lite/current.json").exists()
