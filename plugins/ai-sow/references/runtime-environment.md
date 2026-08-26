# 插件运行时环境合同

普通插件用户无需预装 Python、`uv` 或 Python 依赖。权威流程从 `setup` 开始：setup bootstrap 在
插件安装副本内准备 `uv 0.11.7`、managed Python 3.12、锁定依赖和 `.venv`，再初始化或只读复核项目。

setup 确实使用平台脚本，而不是要求用户预先执行环境命令：

- macOS/Linux：`skills/setup/scripts/bootstrap.sh`
- Windows：`skills/setup/scripts/bootstrap.ps1`

macOS 路径已有实机证据，Linux 由 GitHub-hosted CI 覆盖。Windows runner 已运行根测试和
完整插件 pytest，PowerShell 路径及 `uv --version` 后缀匹配也有自动化回归；合成测试另覆盖
重解析点拒绝。这些证据不能代替 Windows 11 实机验收，因此 Windows 当前仍是
`Provisional`。

在以下实机边界全部通过之前，不得将 Windows 描述为 `Verified`：

- 从没有预装 Python、`uv` 且无管理员权限的普通用户环境，由 Codex 调用已安装插件的
  `setup`，验证固定版 `uv`、managed Python 3.12、锁定依赖和 `.venv` 都能自动完成；
- 在 NTFS 上验证目录符号链接、junction 和其他 reparse point 拒绝，以及同文件系统
  package rename、相同内容复用和不同内容拒绝覆盖；
- 从含空格、非 ASCII 字符和长路径的项目执行，并验证真实 Git for Windows 与受控
  `.cmd` Git shim 发现；
- 从已安装插件目录跑通 `setup` → 五个 Owner → `generate-sow`，不依赖源码 checkout；
- 在 Microsoft Excel Desktop 中打开最终工作簿，完成普通计算、全量计算、保存和重新打开，
  确认公式缓存值与公式错误。

这些项目需要记录 Windows 版本、build、文件系统、工具版本、路径与权限策略、命令结果、
文件哈希和 Excel 结果。任何跳过项都必须继续作为支持限制公开可见。

后续 Skill 不依赖 shell profile 或 PATH 中的 `uv`，而是直接使用 setup 已建立的 `<python-bin>`：

- macOS/Linux：`<plugin-root>/.venv/bin/python`
- Windows：`<plugin-root>/.venv/Scripts/python.exe`

每个 Skill 从已加载的 `SKILL.md` 解析 `<plugin-root>`，按当前平台替换 `<python-bin>` 后执行自己的
确定性脚本。`uv --version` 可以带平台/安装来源后缀，但首个版本 token 必须精确为 `0.11.7`。插件
升级后若 `.venv` 不存在、损坏或版本不符，先重新调用 `setup`；完整项目会被只读
复核，bootstrap 只刷新插件安装副本的运行时，不要求用户打开终端或手工安装工具。

仓库贡献者和 CI 可以继续使用根 README/CONTRIBUTING 中的 `uv` 开发命令；该开发工具链不属于
普通插件用户的安装前置条件。
