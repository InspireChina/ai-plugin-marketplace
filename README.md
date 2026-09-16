# AI Plugin Marketplace

面向 Codex 与 Claude Code 的开源插件市场。当前提供两个独立的 SOW 插件，将需求、技术方案和现状材料整理为可追溯的工作量估算与 Excel 交付。

## 选择插件

| 插件 | 适合的工作方式 | 当前发布版本 |
| --- | --- | --- |
| [AI SOW Lite](plugins/ai-sow-lite/README.md) | 从 PRD、HLD 和往期 SOW 生成首稿，查看 Excel 后通过 `clarify` 讨论并应用局部修改。 | [0.1.0-alpha.3](https://github.com/InspireChina/ai-plugin-marketplace/releases/tag/ai-sow-lite-v0.1.0-alpha.3) |
| [AI SOW](plugins/ai-sow/README.md) | 按需求、现状、设计、Story/AC、Task 和生成等阶段逐步评审批准，通过 `reconcile` 协调上游修正。 | [0.1.0-beta.1](https://github.com/InspireChina/ai-plugin-marketplace/releases/tag/ai-sow-v0.1.0-beta.1) |

Lite 的当前 Alpha 于 2026-09-16 发布，AI SOW 的当前 Beta 于 2026-09-11 发布，均为预发布版本，仍需用户核对结果。各插件独立安装、独立维护项目数据，无需同时安装。能力和限制见各插件 README，版本变化见 [CHANGELOG](CHANGELOG.md)。

## 使用前准备

准备支持插件安装的宿主，并确保安装和首次使用时可访问相应下载源。普通用户无需预装 Git、Python 或 uv；AI SOW 的 `setup`、Lite 的首次 `generate/clarify` 会自动准备插件隔离依赖。

| 插件 | 宿主与平台 | Excel 条件 |
| --- | --- | --- |
| AI SOW Lite | 已验证 macOS 普通本地目录中的 Codex 安装、生成与改稿；Windows 11 已验证 generate 全链路与 clarify 有限修改；其他组合见 [支持说明](plugins/ai-sow-lite/docs/support.md)。 | 导出需要已安装的 LibreOffice；Windows 未安装时可用 `scripts/lite.py --provision-office` 在插件目录内按需准备（免管理员、不注册到系统）。Microsoft Excel 可用于查看结果。 |
| AI SOW | 提供 Codex、Claude Code 入口，支持 macOS、Linux、Windows 11 x64；Windows 项目路径要求见 [前置条件](plugins/ai-sow/README.md#前置条件)。 | 插件保留模板公式，计算结果需在兼容的表格软件中复核。 |

Lite 的 Claude Code 完整业务执行、Linux、同步盘和网络盘暂未验证；Windows 11 已验证 generate 全链路与 clarify 有限修改（入口为 `scripts/bootstrap.ps1`），原型目录输入在 Windows 不支持；当前也没有速度或 token 达标承诺。验证范围分别记录在两个版本的 Release 和 [Lite 验证摘要](plugins/ai-sow-lite/docs/validation/README.md)中。

## 安装

每个宿主只需注册一次 marketplace，再按需选择插件。已有同名 Git marketplace 时，先按下方“更新与卸载”刷新快照，无需重复注册。

### Codex

在终端注册：

```text
codex plugin marketplace add InspireChina/ai-plugin-marketplace
```

按需执行对应的安装命令：

| 插件 | 命令 |
| --- | --- |
| AI SOW Lite | `codex plugin add ai-sow-lite@ai-plugin-marketplace` |
| AI SOW | `codex plugin add ai-sow@ai-plugin-marketplace` |

运行 `codex plugin list` 核对安装状态，然后在新会话中使用插件。

### Claude Code

在 Claude Code 会话中注册：

```text
/plugin marketplace add InspireChina/ai-plugin-marketplace
```

按需执行对应的安装命令；Lite 的完整业务支持范围以上文为准：

| 插件 | 命令 |
| --- | --- |
| AI SOW Lite | `/plugin install ai-sow-lite@ai-plugin-marketplace` |
| AI SOW | `/plugin install ai-sow@ai-plugin-marketplace` |

## 开始使用

在保存项目材料的目录中打开会话，明确所用插件和材料路径。

**AI SOW Lite：生成首稿，再按意见改稿。** 新项目需要 PRD 和高阶设计，旧项目另需往期 SOW；HTML/JS/CSS 原型可选。非原型材料支持 UTF-8 文本（默认 Markdown）和 `.xlsx`，暂不支持 PDF、DOCX、扫描件或 OCR。

```text
请使用 ai-sow-lite 的 generate 生成本期 SOW。
这是新项目，PRD 在 inputs/prd.md，高阶设计在 inputs/hld.md。
```

查看 Excel 后，可在同一项目的新会话中调用 `ai-sow-lite:clarify`，回答待确认事项或提出修改意见。插件讨论具体方案，确认后更新有限范围；初稿没有额外定稿步骤。完整用法见 [Lite 使用说明](plugins/ai-sow-lite/README.md)。

**AI SOW：从项目初始化开始，按阶段评审。**

```text
请使用 AI SOW 的 setup 初始化项目。
项目 ID 是 crm-modernization，项目名称是 CRM 现代化。
初始化后告诉我下一步需要提供什么。
```

AI SOW 提供七个主线阶段和一个 `reconcile` 维护入口，以 `ai-sow:<skill>` 命名。各阶段材料、角色职责和批准要求见 [AI SOW 使用说明](plugins/ai-sow/README.md)。

两个插件分别使用项目内的 `.ai-sow-lite/` 和 `.ai-sow/` 保存数据。后续修改或恢复需要保留对应目录；项目材料及生成文件可能包含客户信息，分享前按项目权限核对。安全问题见 [安全策略](SECURITY.md)。

## 更新与卸载

以下命令以 AI SOW 为例。操作 Lite 时，将插件标识替换为 `ai-sow-lite@ai-plugin-marketplace`。

**更新：** 先刷新 Git marketplace，再卸载并重新安装所选插件；之后在新会话使用。

| 步骤 | Codex（终端） | Claude Code（会话） |
| --- | --- | --- |
| 刷新 marketplace | `codex plugin marketplace upgrade ai-plugin-marketplace` | `/plugin marketplace update ai-plugin-marketplace` |
| 卸载所选插件 | `codex plugin remove ai-sow@ai-plugin-marketplace` | `/plugin uninstall ai-sow@ai-plugin-marketplace` |
| 重新安装 | `codex plugin add ai-sow@ai-plugin-marketplace` | `/plugin install ai-sow@ai-plugin-marketplace` |

**仅卸载：** 执行表中的“卸载所选插件”即可。仍需使用市场中的其他插件时，保留 marketplace 注册；全部不再使用时，再执行对应的移除命令：

| Codex（终端） | Claude Code（会话） |
| --- | --- |
| `codex plugin marketplace remove ai-plugin-marketplace` | `/plugin marketplace remove ai-plugin-marketplace` |

## 开发与贡献

每个插件自包含于 `plugins/<name>/`，拥有自己的运行时、依赖、资产和测试。marketplace 根目录负责目录发现、文档、治理与仓库检查；插件运行时不读取根目录或其他插件的文件。

```text
.agents/plugins/marketplace.json   Codex 插件目录
.claude-plugin/marketplace.json    Claude Code 插件目录
plugins/ai-sow-lite/               AI SOW Lite 插件包
plugins/ai-sow/                    AI SOW 插件包
scripts/                          仓库校验脚本
tests/                            Marketplace 级测试
.github/                          CI 与贡献模板
```

本地开发可用仓库 checkout 的绝对路径替换 marketplace 注册命令中的远端来源。同名 marketplace 已有注册时先核对来源；本地来源通过更新 checkout 获取变更，Git marketplace 的刷新命令不替代这一步。

- [贡献指南](CONTRIBUTING.md)：开发环境、完整检查和提交要求。
- [Marketplace 架构](docs/architecture/ai-plugin-marketplace-design.md)：插件边界、目录规范与发布约定。
- [Lite 开发维护](plugins/ai-sow-lite/docs/development.md)：Lite 测试、设计与历史记录入口。

## 许可证

采用 [Apache License 2.0](LICENSE)。项目原创模板、示例和文档使用同一许可证；依赖项保留各自许可证，详见 [NOTICE](NOTICE)。
