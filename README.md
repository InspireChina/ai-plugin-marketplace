# AI Plugin Marketplace

一个面向实用、可评审 AI 工作流的开源插件市场，同时发布 Codex 与 Claude Code 两套安装入口。
提供 AI SOW 与 AI SOW Lite 两个独立插件，用于生成可追溯的工作说明书（SOW）工作簿。

## 插件

| 插件 | 版本 | 用途 |
| --- | --- | --- |
| [AI SOW](plugins/ai-sow/README.md) | 0.1.0-beta.1 | 分析范围、核对系统现状、估算交付工作并生成可评审的 XLSX。 |
| [AI SOW Lite](plugins/ai-sow-lite/README.md) | 0.1.0-alpha.1（预发布） | 从 PRD、HLD 与往期 SOW 生成本期首版 Excel、摘要和待确认事项，再按确认意见作有限修改。 |

Lite 提供 `generate`、`clarify` 两个入口，使用独立的 `.ai-sow-lite/` 项目数据，
不需要安装 AI SOW。首个 Alpha 试用版已发布；安装与使用见 [Lite README](plugins/ai-sow-lite/README.md)，版本记录见 [GitHub Release](https://github.com/InspireChina/ai-plugin-marketplace/releases/tag/ai-sow-lite-v0.1.0-alpha.1)。

## 支持平台

AI SOW 的既有支持范围为 macOS、Linux 和 Windows 11 x64。三个平台使用同一套 Skill 与同一份计算权威模板，
只有 `setup` 的环境自举脚本按平台区分（macOS/Linux 用 `bootstrap.sh`，Windows 用
`bootstrap.ps1`）。Windows 上项目路径需短于 97 个字符，或已启用长路径支持。

AI SOW Lite 已验证 macOS 普通本地目录中的 Codex 安装、生成与改稿流程，Excel 导出需要
已安装的 LibreOffice。Claude Code 的完整业务执行、Windows/Linux、同步盘和网络盘暂未验证。
完整边界见 [Lite 支持与限制](plugins/ai-sow-lite/docs/support.md)，证据见
[验证摘要](plugins/ai-sow-lite/docs/validation/README.md)。

## 安装

以下 AI SOW 安装说明适用于原插件。普通插件用户只需要支持本地 marketplace 的 Codex 或 Claude Code，安装时能访问 marketplace，首次
`setup` 时能访问 Astral 官方下载源；无需预装 Git、Python、[uv](https://docs.astral.sh/uv/) 或 Python 依赖，也
无需管理员权限或终端操作。`setup` 会在插件安装副本内自动准备 uv 0.11.7、managed Python 3.12、
锁定依赖和插件 `.venv`，后续阶段直接复用该隔离环境。

### Codex

```text
codex plugin marketplace add InspireChina/ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
codex plugin list
```

本地开发时，改为克隆仓库并注册本地 checkout：

```text
git clone https://github.com/InspireChina/ai-plugin-marketplace.git
codex plugin marketplace add /absolute/path/to/ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
```

### Claude Code

在 Claude Code 会话中使用斜杠命令：

```text
/plugin marketplace add InspireChina/ai-plugin-marketplace
/plugin install ai-sow@ai-plugin-marketplace
```

本地开发时注册本地 checkout：

```text
git clone https://github.com/InspireChina/ai-plugin-marketplace.git
/plugin marketplace add /absolute/path/to/ai-plugin-marketplace
/plugin install ai-sow@ai-plugin-marketplace
```

AI SOW 安装后八个 Skill 以 `ai-sow:<skill>` 命名空间出现，可直接用自然语言调用，无需记忆命令名。

### AI SOW Lite 试用入口

从远端 marketplace 安装 Lite：

```text
codex plugin marketplace add InspireChina/ai-plugin-marketplace
codex plugin add ai-sow-lite@ai-plugin-marketplace
```

已有同名 Git marketplace 时，先执行 `codex plugin marketplace upgrade ai-plugin-marketplace` 刷新快照，再安装 Lite，无需重复注册。

Claude Code 的目录中也有同名条目，但完整业务执行暂未验证：

```text
/plugin marketplace add InspireChina/ai-plugin-marketplace
/plugin install ai-sow-lite@ai-plugin-marketplace
```

Lite 没有 setup 入口，首次 generate/clarify 自动准备插件内隔离依赖。输入要求、Excel 阅读和
局部修改见 [Lite 使用说明](plugins/ai-sow-lite/README.md)。

## 更新

以下示例更新 AI SOW；更新 Lite 时将插件标识替换为 `ai-sow-lite@ai-plugin-marketplace`。

### Codex

先刷新 Git marketplace 快照，再重新安装插件，使 Codex 使用更新后的安装包：

```text
codex plugin marketplace upgrade ai-plugin-marketplace
codex plugin remove ai-sow@ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
```

如果 marketplace 注册自本地 checkout，请先拉取该 checkout；`marketplace upgrade`
只负责刷新已配置的 Git marketplace。

### Claude Code

```text
/plugin marketplace update ai-plugin-marketplace
/plugin uninstall ai-sow@ai-plugin-marketplace
/plugin install ai-sow@ai-plugin-marketplace
```

## 卸载

先删除所选插件，再按需删除 marketplace 注册。以下示例删除 AI SOW；删除 Lite 时
将插件标识替换为 `ai-sow-lite@ai-plugin-marketplace`。仍需使用其他插件时保留 marketplace：

```text
codex plugin remove ai-sow@ai-plugin-marketplace
codex plugin marketplace remove ai-plugin-marketplace
```

Claude Code 使用对应的斜杠命令：

```text
/plugin uninstall ai-sow@ai-plugin-marketplace
/plugin marketplace remove ai-plugin-marketplace
```

## 仓库结构

```text
.agents/plugins/marketplace.json    Codex marketplace 目录
.claude-plugin/marketplace.json     Claude Code marketplace 目录
plugins/ai-sow/                     自包含插件包
plugins/ai-sow-lite/                Lite 自包含预发布插件包
scripts/                            仓库与插件包冒烟检查
tests/                              Marketplace 级测试
.github/                            贡献模板与 CI
```

两份 marketplace 目录发布同一组插件和同一份来源路径，由仓库验证器强制保持一致。

插件包自行拥有运行时代码、锁文件和资产，运行时不读取 marketplace 根目录中的文件，
也不读取其他插件。独立副本的实际验证范围由各插件的验证记录说明。

公开的 [marketplace 架构](docs/architecture/ai-plugin-marketplace-design.md)
记录插件包边界和发布决策。执行清单与本机计划有意不放入公共仓库。Windows 11 清单定义
的是发布支持边界，因此作为公共文档保留。

## 开发

以下命令面向仓库贡献者，不是普通插件用户的安装步骤。贡献者需要 Git、Python 3.12 和 uv 0.11.7：

```text
uv sync --project plugins/ai-sow --locked
uv run --project plugins/ai-sow --locked python -m unittest discover -s tests -v
uv run --project plugins/ai-sow --locked python scripts/validate_repository.py
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow/skills -q
```

完整验证流程见 [贡献指南](CONTRIBUTING.md)。

上面的 pytest 命令针对 AI SOW。仅检查两个插件的 root 目录与发布元数据时，可运行
`python -m unittest discover -s tests -p 'test_repository*.py' -v` 和
`python scripts/validate_repository.py`；Lite 的独立开发验证命令见
[Lite 开发维护](plugins/ai-sow-lite/docs/development.md)。root 检查不替代各插件的业务、Office 或安装验收。

## 添加其他插件

1. 创建 `plugins/<stable-plugin-name>/.codex-plugin/plugin.json` 和
   `plugins/<stable-plugin-name>/.claude-plugin/plugin.json`，两者的 `name`、`version`
   和 `description` 必须一致。
2. 将插件的运行时代码、依赖、资产、文档和测试全部保存在该插件目录下。
3. 在 `.agents/plugins/marketplace.json` 和 `.claude-plugin/marketplace.json` 中各添加
   一项指向同一目录的本地来源配置。
4. 扩展仓库验证器和测试，使其覆盖新插件包。
5. 在提交 Pull Request 前补充插件文档和发布说明。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。项目自行编写的模板、示例和文档采用同一
许可证；依赖项仍适用各自许可证。详见 [NOTICE](NOTICE)。
