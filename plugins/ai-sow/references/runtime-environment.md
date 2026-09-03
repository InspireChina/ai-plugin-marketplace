# 插件运行时环境合同

普通插件用户无需预装 Python、`uv` 或 Python 依赖。权威流程从 `ai-sow:generate` 开始：generate bootstrap 在
插件安装副本内准备 `uv 0.11.7`、managed Python 3.12、锁定依赖和 `.venv`，再调用唯一生成编排器。

Python bootstrap 不包含电子表格计算引擎。发布正式 `sow.xlsx` 时必须存在可执行的 LibreOffice：优先
使用 `AI_SOW_OFFICE_BIN` 指定路径，否则从 PATH 查找 `soffice` 或 `libreoffice`。引擎在隔离 profile
中无界面回算；缺失、超时或失败均返回稳定阻断，不发布仅含公式但没有可信缓存结果的候选件。

generate 使用平台脚本，而不是要求用户预先执行环境命令：

- macOS/Linux：`skills/generate/scripts/bootstrap.sh`
- Windows：`skills/generate/scripts/bootstrap.ps1`

macOS、Linux 和 Windows 11 x64 都受支持。Windows 上未启用长路径支持时，项目根目录必须
短于 97 个字符；generate bootstrap 在写入任何项目文件前检查该预算，不足时返回
`WINDOWS_LONG_PATH_REQUIRED` 且不创建 `.ai-sow`。

后续调用不依赖 shell profile 或 PATH 中的 `uv`，而是复用 generate bootstrap 已建立的 `<python-bin>`：

- macOS/Linux：`<plugin-root>/.venv/bin/python`
- Windows：`<plugin-root>/.venv/Scripts/python.exe`

## 标准输出编码

所有公开执行结果一律是 UTF-8 JSON，调用方按 UTF-8 解码，不依赖宿主 locale 或 Windows 控制台
代码页：

- `orchestrator.py` 直接向 `sys.stdout.buffer` 写 canonical UTF-8 JSON bytes；
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

未启用长路径支持的 Windows 把路径限制在 `MAX_PATH`（260）以内。不可变 input revision、generation
及其临时发布目录包含固定宽度的 revision/generation 标识与 hash 文件名，因此项目根目录必须短于
97 个字符。

generate bootstrap 在写入任何项目文件前计算该预算，不足时返回 `WINDOWS_LONG_PATH_REQUIRED` 并且不创建
`.ai-sow`；`runtime/project_io.py` 另把写入期的 `ERROR_FILENAME_EXCED_RANGE` 转换成
`PROJECT_PATH_TOO_LONG`，避免以原始 `WinError 206` 冒泡。

补救方案有两个，由用户选择：缩短项目路径，或启用 Windows 长路径支持。后者修改机器级
系统策略并需要管理员权限，只能在向用户说明影响并取得明确同意后，由
`skills/generate/scripts/enable_long_paths.ps1 -Apply` 执行；不带 `-Apply` 时该脚本只报告
当前状态。任何情况下都不得静默修改系统策略或绕过 UAC 提示。

generate 从已加载的 `SKILL.md` 解析 `<plugin-root>`，由平台 bootstrap 调用唯一 `orchestrator.py`。
`uv --version` 可以带平台/安装来源后缀，但首个版本 token 必须精确为 `0.11.7`。以后调用复用同一
插件 `.venv`；插件升级后若环境不存在、损坏或版本不符，bootstrap 只刷新插件安装副本的运行时，
不要求用户打开终端或手工安装工具。所有业务模式都留在 `generate` 内部，不形成额外公开命令。

仓库贡献者和 CI 可以继续使用根 README/CONTRIBUTING 中的 `uv` 开发命令；该开发工具链不属于
普通插件用户的安装前置条件。
