# 插件运行时环境合同

普通插件用户无需预装 Python、`uv` 或 Python 依赖。权威流程从 `setup` 开始：setup bootstrap 在
插件安装副本内准备 `uv 0.11.7`、managed Python 3.12、锁定依赖和 `.venv`，再初始化或只读复核项目。

setup 确实使用平台脚本，而不是要求用户预先执行环境命令：

- macOS/Linux：`skills/setup/scripts/bootstrap.sh`
- Windows：`skills/setup/scripts/bootstrap.ps1`

macOS、Linux 和 Windows 11 x64 都受支持。Windows 上未启用长路径支持时，项目根目录必须
短于 97 个字符；`setup` 在写入任何文件前检查该预算，不足时返回
`WINDOWS_LONG_PATH_REQUIRED` 且不创建 `.ai-sow`。

后续 Skill 不依赖 shell profile 或 PATH 中的 `uv`，而是直接使用 setup 已建立的 `<python-bin>`：

- macOS/Linux：`<plugin-root>/.venv/bin/python`
- Windows：`<plugin-root>/.venv/Scripts/python.exe`

## 标准输出编码

所有 Skill 脚本的 stdout 与 stderr 一律是 UTF-8，调用方按 UTF-8 解码，不依赖宿主 locale
或 Windows 控制台代码页：

- 每个写 stdout 的 Python 入口脚本在产生任何输出前调用
  `sys.stdout.reconfigure(encoding="utf-8")` 与 `sys.stderr.reconfigure(encoding="utf-8")`；
- `bootstrap.ps1` 设置 `[Console]::OutputEncoding` 为无 BOM 的 UTF-8，并置 `PYTHONUTF8=1`；
- `bootstrap.ps1` 自身以 UTF-8 **带 BOM** 保存。Windows PowerShell 5.1 会把无 BOM 的 `.ps1`
  按 ANSI 代码页解码，中文诊断会损坏，非 ASCII 内容还可能直接导致脚本解析失败；
  `bootstrap.sh` 相反，必须不带 BOM。

在非 UTF-8 代码页（例如简体中文 Windows 的 cp936）上，缺少上述任何一项都会让结构化
`OK`/`BLOCKED` JSON 变成调用方无法解码的字节，等同于阻塞诊断丢失。

`bootstrap.ps1` 还会把本进程的 `$PSHOME\Modules` 前置到 `PSModulePath`。从 PowerShell 7
启动的会话会把 7.x 模块目录带进环境变量，使 Windows PowerShell 5.1 加载到不兼容的内置
模块，导致官方 uv 安装器无法执行。

## Windows 长路径

未启用长路径支持的 Windows 把路径限制在 `MAX_PATH`（260）以内。本插件最深的受管路径是
`.ai-sow/.stage-<12 hex>/outputs/sow-sha256-<64 hex>/sources/data/<owner>/<file>`，长度 162
个字符，因此项目根目录必须短于 97 个字符。

`setup` 在写入任何文件前计算该预算，不足时返回 `WINDOWS_LONG_PATH_REQUIRED` 并且不创建
`.ai-sow`；`runtime/project_io.py` 另把写入期的 `ERROR_FILENAME_EXCED_RANGE` 转换成
`PROJECT_PATH_TOO_LONG`，避免以原始 `WinError 206` 冒泡。

补救方案有两个，由用户选择：缩短项目路径，或启用 Windows 长路径支持。后者修改机器级
系统策略并需要管理员权限，只能在向用户说明影响并取得明确同意后，由
`skills/setup/scripts/enable_long_paths.ps1 -Apply` 执行；不带 `-Apply` 时该脚本只报告
当前状态。任何情况下都不得静默修改系统策略或绕过 UAC 提示。

每个 Skill 从已加载的 `SKILL.md` 解析 `<plugin-root>`，按当前平台替换 `<python-bin>` 后执行自己的
确定性脚本。`uv --version` 可以带平台/安装来源后缀，但首个版本 token 必须精确为 `0.11.7`。插件
升级后若 `.venv` 不存在、损坏或版本不符，先重新调用 `setup`；完整项目会被只读
复核，bootstrap 只刷新插件安装副本的运行时，不要求用户打开终端或手工安装工具。

仓库贡献者和 CI 可以继续使用根 README/CONTRIBUTING 中的 `uv` 开发命令；该开发工具链不属于
普通插件用户的安装前置条件。
