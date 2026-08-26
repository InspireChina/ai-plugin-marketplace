#!/bin/sh

set -u

UV_VERSION="0.11.7"
UV_INSTALLER_URL="https://astral.sh/uv/0.11.7/install.sh"
SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd -P) || exit 3
PLUGIN_ROOT=$(CDPATH= cd "$SCRIPT_DIR/../../.." && pwd -P) || exit 3
TOOLS_ROOT="$PLUGIN_ROOT/.ai-sow-tools"
TOOLS_BIN="$TOOLS_ROOT/bin"
LOCAL_UV="$TOOLS_BIN/uv"
INSTALLER="$TOOLS_ROOT/install-uv.sh"

blocked() {
  code=$1
  summary=$2
  printf '%s\n' "{\"outcome\":\"BLOCKED\",\"summary\":\"$summary\",\"diagnostics\":[{\"code\":\"$code\",\"message\":\"$summary\"}],\"nextStep\":\"Codex 需要获得一次必要的联网或文件写入权限后自动重试；用户无需手工安装或执行命令。\"}"
  exit 2
}

mkdir -p "$TOOLS_BIN" "$TOOLS_ROOT/cache" || blocked "BOOTSTRAP_DIRECTORY_FAILED" "无法创建插件隔离环境目录"
if [ -z "${UV_CACHE_DIR:-}" ]; then
  UV_CACHE_DIR="$TOOLS_ROOT/cache"
fi
export UV_CACHE_DIR
export UV_NO_MODIFY_PATH=1

if command -v uv >/dev/null 2>&1; then
  UV_BIN=$(command -v uv)
  UV_SOURCE="PATH"
elif [ -x "$LOCAL_UV" ]; then
  UV_BIN="$LOCAL_UV"
  UV_SOURCE="PLUGIN_LOCAL"
else
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf "$UV_INSTALLER_URL" -o "$INSTALLER" || blocked "UV_INSTALL_DOWNLOAD_FAILED" "无法下载 uv 官方安装器"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$UV_INSTALLER_URL" -O "$INSTALLER" || blocked "UV_INSTALL_DOWNLOAD_FAILED" "无法下载 uv 官方安装器"
  else
    blocked "UV_INSTALL_DOWNLOADER_MISSING" "当前系统缺少可用的 HTTPS 下载工具"
  fi
  env UV_UNMANAGED_INSTALL="$TOOLS_BIN" UV_NO_MODIFY_PATH=1 sh "$INSTALLER" || blocked "UV_INSTALL_FAILED" "uv 自动安装失败"
  rm -f "$INSTALLER"
  [ -x "$LOCAL_UV" ] || blocked "UV_INSTALL_INVALID" "uv 自动安装完成后仍无法执行"
  UV_BIN="$LOCAL_UV"
  UV_SOURCE="PLUGIN_LOCAL"
fi

UV_VERSION_TEXT=$("$UV_BIN" --version 2>&1) || blocked "UV_CHECK_FAILED" "uv 版本检查失败"

if ! "$UV_BIN" python find 3.12 >/dev/null 2>&1; then
  if ! "$UV_BIN" python install 3.12; then
    export UV_PYTHON_INSTALL_DIR="$TOOLS_ROOT/python"
    "$UV_BIN" python install 3.12 || blocked "PYTHON_INSTALL_FAILED" "Python 3.12 自动安装失败"
  fi
fi

"$UV_BIN" sync --project "$PLUGIN_ROOT" --locked --python 3.12 || blocked "DEPENDENCY_SYNC_FAILED" "插件锁定依赖同步失败"

PYTHON_BIN="$PLUGIN_ROOT/.venv/bin/python"
[ -x "$PYTHON_BIN" ] || blocked "VENV_MISSING" "插件隔离 .venv 未创建"
PYTHON_VERSION=$($PYTHON_BIN --version 2>&1) || blocked "PYTHON_CHECK_FAILED" "插件隔离 Python 无法执行"
case "$PYTHON_VERSION" in
  "Python 3.12."*) ;;
  *) blocked "PYTHON_VERSION_INVALID" "插件隔离 Python 不是 3.12" ;;
esac
"$PYTHON_BIN" -c 'import jsonschema, openpyxl' || blocked "DEPENDENCY_IMPORT_FAILED" "插件隔离依赖复核失败"

if [ "$#" -gt 0 ]; then
  "$UV_BIN" run --project "$PLUGIN_ROOT" --locked python "$SCRIPT_DIR/setup.py" "$@"
  exit $?
fi

printf '%s\n' "{\"outcome\":\"OK\",\"summary\":\"AI SOW 插件隔离环境已就绪\",\"uvVersion\":\"$UV_VERSION_TEXT\",\"uvSource\":\"$UV_SOURCE\",\"pythonVersion\":\"$PYTHON_VERSION\",\"venv\":\".venv\"}"
