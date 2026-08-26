# 插件运行时环境合同

普通插件用户无需预装 Python、`uv` 或 Python 依赖。权威流程从 `setup` 开始：setup bootstrap 在
插件安装副本内准备 `uv 0.11.7`、managed Python 3.12、锁定依赖和 `.venv`，再初始化或只读复核项目。

后续 Skill 不依赖 shell profile 或 PATH 中的 `uv`，而是直接使用 setup 已建立的 `<python-bin>`：

- macOS/Linux：`<plugin-root>/.venv/bin/python`
- Windows：`<plugin-root>/.venv/Scripts/python.exe`

每个 Skill 从已加载的 `SKILL.md` 解析 `<plugin-root>`，按当前平台替换 `<python-bin>` 后执行自己的
确定性脚本。插件升级后若 `.venv` 不存在、损坏或版本不符，先重新调用 `setup`；完整项目会被只读
复核，bootstrap 只刷新插件安装副本的运行时，不要求用户打开终端或手工安装工具。

仓库贡献者和 CI 可以继续使用根 README/CONTRIBUTING 中的 `uv` 开发命令；该开发工具链不属于
普通插件用户的安装前置条件。
