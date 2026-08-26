# Windows 11 验证状态

AI Plugin Marketplace 0.1.0-beta.2 对 Windows 11 的支持状态为**临时支持
（`Provisional`）**。仓库已经具备 Windows CI 和针对部分可移植分支的合成测试，但尚未
在 Windows 11 实机上完成下方清单。CI 和合成测试是有价值的回归信号，但都不能作为
NTFS、Codex Desktop 或 Microsoft Excel Desktop 的验收结果。

本文档定义首次实机运行前的公开支持边界和证据计划。勾选检查项时必须附带证据记录；
只修改复选框不足以证明完成验收。

## 当前自动化能够证明什么

- GitHub Actions 在 `windows-latest` 上运行根仓库测试和完整插件 pytest 测试套件。
- Windows runner 会执行 PowerShell `uv --version` 后缀匹配回归；合成测试另覆盖重解析点
  （reparse point）属性拒绝。当前没有独立自动化证据证明 `PATH` 分隔、`.cmd Git shim`
  发现或可移植验证报告写入器，这些仍属于下方实机验收范围。
- macOS 测试覆盖真实 POSIX 符号链接和竞态替换，但不会创建 NTFS 目录联接
  （NTFS junction）或原生 Windows 重解析点。

这些测试只验证受控输入下的分支逻辑，不能证明相同分支与 Windows 文件系统、进程、
权限、路径、Codex 安装或 Excel 的实际交互正确。

## 开放风险与问题

| 领域 | 实机测试前状态 | 必需结论 |
| --- | --- | --- |
| NTFS 间接引用 | 未确认 | 创建目录符号链接、NTFS 目录联接（NTFS junction）和其他可访问的重解析点形式。确认指向项目外部的 `.ai-sow/validation` 和报告目标会被拒绝，且外部目标保持不变。 |
| 同文件系统发布 | 未确认 | 确认项目内临时目录与最终 package 的 rename、相同内容复用和不同内容拒绝覆盖在 NTFS 上行为一致。 |
| Windows 路径 | 未确认 | 从包含非 ASCII 字符和空格的项目路径运行。另行测试长路径（long path），并记录是否启用 Windows 长路径支持。 |
| Git 发现 | 未自动化确认 | 确认真正的 Git for Windows 和受控 `.cmd Git shim` 都能被发现，并使用预期的 optional-lock 环境设置调用。 |
| 工具链与已安装插件 | 未确认 | 从未预装 Python、`uv` 且没有管理员权限的普通用户环境运行 `setup`，确认插件自动准备 `uv 0.11.7`、managed Python 3.12、锁定依赖和插件 `.venv`；再确认 Codex marketplace 注册、插件安装、已安装插件目录发现，以及从已安装插件而非源码 checkout 运行 `pytest`。 |
| Codex 工作流 | 未确认 | 通过已安装插件目录，在空项目中依次运行 `setup`、五个 Owner validator 和 `generate-sow`；确认全部七个 Skill 都从该目录解析。 |
| Excel 结果 | 未确认 | 在 Microsoft Excel Desktop 中打开生成的工作簿，使用 `F9` 计算，再执行完整计算，保存并检查公式缓存值和公式错误。 |
| 开发者功能 | 未确认 | 在记录开发者模式（Developer Mode）和普通符号链接权限的情况下重复文件系统测试；记录需要提权或无法创建的场景。 |

项目 I/O 已拒绝受管路径中的重解析点；生成器只实现同文件系统 rename 与内容一致性复用，
不声明对同权限攻击者竞态或跨设备 copy 的防护。在上述原生 NTFS 场景完成前，不能宣传为
已解决的 Windows 兼容性。

## Windows 11 实机验收清单

使用一次性 Windows 用户配置或 VM 快照，不复用客户数据。命令记录和哈希保存在证据
记录中。

- [ ] 记录 Windows 版本、build、架构、文件系统、shell、Python、`uv`、Git、Codex 和
  Excel 版本，以及开发者模式、长路径策略和符号链接权限。
- [ ] 把仓库克隆到普通路径，运行根测试、仓库验证器、锁定依赖同步和完整插件 pytest
  测试套件。
- [ ] 从包含非 ASCII 字符和空格的路径重复运行根测试和插件检查。
- [ ] 如果已启用长路径支持，从超过 260 个字符的路径重复运行。如果未启用，则记录预期
  失败边界，不静默修改系统策略。
- [ ] 运行真实 Git for Windows 路径和受控 `.cmd Git shim` 路径；记录解析后的可执行
  文件与命令结果。
- [ ] 为 `.ai-sow/validation` 和每个报告目标创建受支持的目录符号链接、NTFS 目录联接
  和重解析点场景。确认所有外部目标保持字节一致。
- [ ] 针对验证目录和现有报告执行并发检查、写入、重命名竞态。确认没有外部写入、截断
  或被拒绝后留下的零字节残留。
- [ ] 使用 `codex plugin marketplace add` 注册 checkout、安装 AI SOW，并保存注册
  命令及输出和 `codex plugin list` 输出。
- [ ] 恢复到未预装 Python 和 `uv` 的普通用户快照，不授予管理员权限；从已安装插件调用
  `setup`，确认它通过固定版官方安装器在插件副本内准备 `uv`，自动安装 managed Python
  3.12、创建 `.venv`、同步锁定依赖并初始化项目。用户不得手工打开终端或执行安装命令。
- [ ] 分别断开网络和拒绝插件缓存写入后调用 `setup`；确认返回结构化 `BLOCKED`，未创建
  半成品 `.ai-sow`。恢复对应权限后由 Codex 自动重试同一 bootstrap，并确认成功。
- [ ] 在不使用源码路径的情况下定位已安装插件目录；对该目录运行锁定 pytest 和仓库提供
  的独立副本冒烟检查。
- [ ] 在新项目中运行 `setup`，然后按工作流顺序运行五个 Owner validator：
  `analyze-requirement`、`analyze-as-is`、`generate-design`、`generate-story` 和
  `generate-task`，最后运行 `generate-sow`。确认生成的合同、验证报告、包 manifest
  和工作簿位于文档规定路径。
- [ ] 启动新的 Codex 会话，确认七个主线 Skill 和 `reconcile` 维护 Skill 均可发现，并从已安装插件目录运行。
- [ ] 在 Microsoft Excel Desktop 中打开最终工作簿，按 `F9` 执行普通计算，再执行
  Calculate Full（例如 `Ctrl+Alt+F9`），保存、重新打开并检查公式缓存值。记录任何公式
  错误的数量和位置。
- [ ] Excel 验收完成后重新运行全部测试套件，并把最终 GitHub Actions 运行记录与实机
  证据一起归档。

## 证据记录

实机运行时，在 `docs/validation/windows-11/` 下创建一份带日期的 Markdown 记录，
内容必须包括：

- commit SHA 和工作区清洁状态；
- 硬件或 VM 说明，以及上方列出的全部版本与策略值；
- 完整命令、退出码、测试数量和对应 GitHub Actions 运行链接；
- 三份源模板、已安装插件模板和最终工作簿的哈希；
- 文件系统场景结果，包括链接或重解析点类型，以及是否使用提权；
- Excel 重新计算与保存证据，以及公式缓存错误扫描结果；
- 每个失败或跳过的检查项、责任人和后续 Issue。

只有适用检查项全部在 Windows 11 实机环境通过且证据记录完成评审后，Windows 11 才能从
**临时支持（`Provisional`）**变更为**已验证（`Verified`）**。任何跳过项都必须继续
作为支持限制公开可见。
