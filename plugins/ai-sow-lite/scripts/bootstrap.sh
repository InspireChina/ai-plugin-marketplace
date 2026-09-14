#!/bin/sh
# Mechanical bootstrap adapted from ai-sow 2fc8588; no professional runner.
set -u
UV_VERSION="0.11.7"
SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd -P) || exit 3
PLUGIN_ROOT=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd -P) || exit 3
TOOLS_ROOT="$PLUGIN_ROOT/.ai-sow-tools"
TOOLS_BIN="$TOOLS_ROOT/bin"
LOCAL_UV="$TOOLS_BIN/uv"
INSTALLER="$TOOLS_ROOT/install-uv.sh"
blocked() {
  printf '%s\n' "{\"ok\":false,\"request_id\":null,\"operation\":null,\"result\":{},\"diagnostics\":[{\"code\":\"$1\",\"target\":{\"path\":null,\"object_id\":null,\"field\":null},\"message\":\"$2\",\"preserved_paths\":[]}]}"
  exit 3
}
uv_version_matches() {
  case "$1" in "uv $UV_VERSION"|"uv $UV_VERSION "*) return 0 ;; *) return 1 ;; esac
}
# This script assumes POSIX layout (.venv/bin, forward-slash uv output). Under
# Git Bash / MSYS the Windows uv.exe reports backslash paths and the venv lives
# in .venv/Scripts, so fail with the actionable entry point instead of a
# misleading "managed Python does not belong to this copy" further down.
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    blocked "BOOTSTRAP_HOST_UNSUPPORTED" "Windows 请改用 scripts/bootstrap.ps1 -Request <request-file>。"
    ;;
esac
# Check only owned write roots before mkdir/install/clear/sync; version aliases below python are valid.
for RUNTIME_ROOT in .venv .ai-sow-tools .ai-sow-tools/bin .ai-sow-tools/cache .ai-sow-tools/python; do
  if [ -L "$PLUGIN_ROOT/$RUNTIME_ROOT" ]; then
    blocked "BOOTSTRAP_PATH_UNSAFE" "插件运行时根目录 $RUNTIME_ROOT 不能是链接；请使用本副本的真实目录。"
  fi
done
mkdir -p "$TOOLS_BIN" "$TOOLS_ROOT/cache" || blocked "BOOTSTRAP_DIRECTORY_FAILED" "无法创建插件隔离环境目录。"
export UV_CACHE_DIR="$TOOLS_ROOT/cache"
export UV_PYTHON_INSTALL_DIR="$TOOLS_ROOT/python"
export UV_PROJECT_ENVIRONMENT="$PLUGIN_ROOT/.venv"
export UV_NO_MODIFY_PATH=1
export PYTHONUTF8=1
UV_BIN=
if [ -x "$LOCAL_UV" ]; then
  LOCAL_VERSION=$("$LOCAL_UV" --version 2>/dev/null)
  if uv_version_matches "$LOCAL_VERSION"; then UV_BIN="$LOCAL_UV"; fi
fi
if [ -z "$UV_BIN" ] && command -v uv >/dev/null 2>&1; then
  PATH_UV=$(command -v uv)
  PATH_VERSION=$("$PATH_UV" --version 2>/dev/null)
  if uv_version_matches "$PATH_VERSION"; then UV_BIN="$PATH_UV"; fi
fi
if [ -z "$UV_BIN" ]; then
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf "https://astral.sh/uv/0.11.7/install.sh" -o "$INSTALLER" 2>/dev/null || blocked "UV_INSTALL_DOWNLOAD_FAILED" "无法下载 uv 官方安装器。"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "https://astral.sh/uv/0.11.7/install.sh" -O "$INSTALLER" 2>/dev/null || blocked "UV_INSTALL_DOWNLOAD_FAILED" "无法下载 uv 官方安装器。"
  else
    blocked "UV_INSTALL_DOWNLOADER_MISSING" "当前系统缺少 HTTPS 下载工具。"
  fi
  env UV_UNMANAGED_INSTALL="$TOOLS_BIN" UV_NO_MODIFY_PATH=1 sh "$INSTALLER" >/dev/null 2>&1 || blocked "UV_INSTALL_FAILED" "uv 自动安装失败。"
  rm -f "$INSTALLER"
  [ -x "$LOCAL_UV" ] || blocked "UV_INSTALL_INVALID" "uv 安装后仍无法执行。"
  UV_BIN="$LOCAL_UV"
fi
UV_VERSION_TEXT=$("$UV_BIN" --version 2>/dev/null) || blocked "UV_CHECK_FAILED" "uv 版本检查失败。"
uv_version_matches "$UV_VERSION_TEXT" || blocked "UV_VERSION_INVALID" "uv 不是锁定版本。"
# Installation is idempotent within this copy; never register a user-bin/registry entry.
"$UV_BIN" python install 3.12 --no-bin --no-registry >/dev/null 2>&1 || blocked "PYTHON_INSTALL_FAILED" "Python 3.12 自动安装失败。"
MANAGED_PYTHON=$("$UV_BIN" python find 3.12 --managed-python --no-project --system --resolve-links 2>/dev/null) || blocked "PYTHON_CHECK_FAILED" "无法定位本插件的 managed Python。"
case "$MANAGED_PYTHON" in "$TOOLS_ROOT/python/"*) ;; *) blocked "PYTHON_CHECK_FAILED" "managed Python 不属于本插件副本。" ;; esac
PYTHON_BIN="$PLUGIN_ROOT/.venv/bin/python"
# uv sync can retain a same-version venv backed by another copy, even with --python.
if [ -d "$UV_PROJECT_ENVIRONMENT" ]; then
  VENV_BASE=$("$PYTHON_BIN" -c 'import os,sys; print(os.path.realpath(sys._base_executable))' 2>/dev/null) || VENV_BASE=
  if [ "$VENV_BASE" != "$MANAGED_PYTHON" ]; then
    "$UV_BIN" venv --no-project --clear --no-python-downloads --python "$MANAGED_PYTHON" "$UV_PROJECT_ENVIRONMENT" >/dev/null 2>&1 || blocked "VENV_MISSING" "无法重建本插件隔离环境。"
  fi
fi
"$UV_BIN" sync --project "$PLUGIN_ROOT" --locked --no-python-downloads --python "$MANAGED_PYTHON" >/dev/null 2>&1 || blocked "DEPENDENCY_SYNC_FAILED" "插件锁定依赖同步失败。"
[ -x "$PYTHON_BIN" ] || blocked "VENV_MISSING" "插件隔离环境未创建。"
VENV_BASE=$("$PYTHON_BIN" -c 'import os,sys; print(os.path.realpath(sys._base_executable))' 2>/dev/null) || blocked "PYTHON_CHECK_FAILED" "隔离 Python 无法执行。"
[ "$VENV_BASE" = "$MANAGED_PYTHON" ] || blocked "PYTHON_CHECK_FAILED" "隔离 Python 不属于本插件副本。"
PYTHON_VERSION=$("$PYTHON_BIN" --version 2>/dev/null) || blocked "PYTHON_CHECK_FAILED" "隔离 Python 无法执行。"
case "$PYTHON_VERSION" in "Python 3.12."*) ;; *) blocked "PYTHON_VERSION_INVALID" "隔离 Python 不是 3.12。" ;; esac
"$PYTHON_BIN" -c 'import jsonschema, openpyxl' >/dev/null 2>&1 || blocked "DEPENDENCY_IMPORT_FAILED" "隔离依赖复核失败。"
"$PYTHON_BIN" "$PLUGIN_ROOT/scripts/lite.py" "$@"
exit $?
