# 插件运行时环境合同

普通插件用户无需预装 Python、`uv` 或 Python 依赖。权威流程从 `setup` 开始：setup bootstrap 在
插件安装副本内准备 `uv 0.11.7`、managed Python 3.12、锁定依赖和 `.venv`，再初始化或只读复核项目。

setup 确实使用平台脚本，而不是要求用户预先执行环境命令：

- macOS/Linux：`skills/setup/scripts/bootstrap.sh`
- Windows：`skills/setup/scripts/bootstrap.ps1`

macOS 路径已有实机证据，Linux 由 CI 覆盖；PowerShell 路径有自动化回归，但 Windows 11 尚未完成
实机验收，因此当前仍是 `Provisional`。公开支持状态和 Windows 验收边界以仓库根 README 与
`docs/windows-11-validation.md` 为准。

后续 Skill 不依赖 shell profile 或 PATH 中的 `uv`，而是直接使用 setup 已建立的 `<python-bin>`：

- macOS/Linux：`<plugin-root>/.venv/bin/python`
- Windows：`<plugin-root>/.venv/Scripts/python.exe`

每个 Skill 从已加载的 `SKILL.md` 解析 `<plugin-root>`，按当前平台替换 `<python-bin>` 后执行自己的
确定性脚本。`uv --version` 可以带平台/安装来源后缀，但首个版本 token 必须精确为 `0.11.7`。插件
升级后若 `.venv` 不存在、损坏或版本不符，先重新调用 `setup`；完整项目会被只读
复核，bootstrap 只刷新插件安装副本的运行时，不要求用户打开终端或手工安装工具。

仓库贡献者和 CI 可以继续使用根 README/CONTRIBUTING 中的 `uv` 开发命令；该开发工具链不属于
普通插件用户的安装前置条件。
