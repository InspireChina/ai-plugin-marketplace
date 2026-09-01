# AI Plugin Marketplace

一个面向实用、可审查 AI 工作流的开源插件市场，同时发布 Codex 与 Claude Code 安装入口。
首个插件 AI SOW 通过唯一入口 `ai-sow:generate`，把 PRD、HLD、适用的往期 SOW 和补充材料
自动转换为可追溯的 SOW 工作簿及配套说明。

## 插件

| 插件 | 版本 | 用途 |
|---|---|---|
| [AI SOW](plugins/ai-sow/README.md) | 0.1.0-beta.1 | 一次生成、增量更新或恢复 SOW，并保留不可变输入与输出历史。 |

## 支持平台

支持 macOS、Linux 和 Windows 11 x64。普通插件用户无需预装 Git、Python、
[uv](https://docs.astral.sh/uv/) 或 Python 依赖；`ai-sow:generate` 的平台 bootstrap 会在插件
安装副本内准备 uv 0.11.7、managed Python 3.12、锁定依赖和隔离 `.venv`。Windows 未启用长路径
支持时，项目根路径需短于 97 个字符。

## 安装

### Codex

```text
codex plugin marketplace add InspireChina/ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
codex plugin list
```

本地开发时可注册本地 checkout：

```text
git clone https://github.com/InspireChina/ai-plugin-marketplace.git
codex plugin marketplace add /absolute/path/to/ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
```

### Claude Code

```text
/plugin marketplace add InspireChina/ai-plugin-marketplace
/plugin install ai-sow@ai-plugin-marketplace
```

本地开发时使用同样的仓库 checkout：

```text
git clone https://github.com/InspireChina/ai-plugin-marketplace.git
/plugin marketplace add /absolute/path/to/ai-plugin-marketplace
/plugin install ai-sow@ai-plugin-marketplace
```

安装后只出现 `ai-sow:generate`。用户用自然语言给出项目资料和目标即可，不需要了解内部模式或
分阶段命令。

## 使用 AI SOW

每次调用都提供或更新一份标准请求：

- PRD：UTF-8 Markdown（`.md`）；
- HLD：UTF-8 Markdown（`.md`）；
- 往期 SOW：仅 Excel（`.xlsx`），Brownfield 至少一份；
- 补充材料：UTF-8 纯文本（默认 Markdown）、HTML、TypeScript、TSX 或 `.xlsx`；
- 项目标识、名称、生效日期，以及客户、供应商和第三方的高层责任边界。

PDF、Word、PowerPoint 和其他需要专用解析器的格式当前不支持。HTML/TypeScript/TSX 原型会被
作为功能与交互证据分析；源码不足且 Demo 可运行时，可以启动后用浏览器自动化或 Computer Use
核验页面、动作、状态、校验、权限、异常和可观察结果。

示例请求：

```text
使用 ai-sow:generate，根据 PRD、HLD 和 Greenfield 问卷生成本项目 SOW。
```

```text
使用 ai-sow:generate，根据 PRD、HLD、往期 SOW 和现状变化说明增量更新 SOW。
```

工作流会自动完成输入归档、范围编译、交付分解、一次终审、工作簿渲染和发布。资料不足但仍能建立
固定边界时返回 `PASS_WITH_NOTES`；只有无法形成可信范围或估算时才返回 `BLOCKED`，并一次汇总最少量
问题。补充答案后再次调用同一 Skill 即可从 pending 输入继续。

成功输出位于当前 generation：

```text
.ai-sow/generations/<revision>/output/sow.xlsx
.ai-sow/generations/<revision>/output/sow-notes.md
```

`.ai-sow/current.json` 始终指向最近一次成功结果。失败或阻断不会覆盖上一份有效 SOW；输入未变化时
直接复用，模板单独变化时只重新渲染，语义输入变化时只重算受影响 Feature 闭包并完整重渲染输出。

自动生成结果用于评审和估算，不代表客户已经签署、接受或赋予 SOW 法律效力。

## 数据与隐私

`.ai-sow/` 包含客户原文、输入快照和衍生数据，应默认加入用户项目的 `.gitignore`，除非团队已经
明确批准其存储和共享策略。公共仓库、Issue、日志和测试 fixture 不得包含客户 SOW、凭据、私有源码
或完整敏感工具输出。

## 更新与卸载

Codex：

```text
codex plugin marketplace upgrade ai-plugin-marketplace
codex plugin remove ai-sow@ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
```

```text
codex plugin remove ai-sow@ai-plugin-marketplace
codex plugin marketplace remove ai-plugin-marketplace
```

Claude Code：

```text
/plugin marketplace update ai-plugin-marketplace
/plugin uninstall ai-sow@ai-plugin-marketplace
/plugin install ai-sow@ai-plugin-marketplace
```

```text
/plugin uninstall ai-sow@ai-plugin-marketplace
/plugin marketplace remove ai-plugin-marketplace
```

## 仓库与开发

```text
.agents/plugins/marketplace.json    Codex marketplace 目录
.claude-plugin/marketplace.json     Claude Code marketplace 目录
plugins/ai-sow/                     自包含插件包
scripts/                            仓库验证器
tests/                              Marketplace 级测试
.github/                            贡献模板与 CI
```

插件运行时不读取 marketplace 根目录或其他插件。架构和发布边界见
[Marketplace 设计规格](docs/architecture/ai-plugin-marketplace-design.md)。

以下命令仅面向贡献者；贡献者需要 Git、Python 3.12 和 uv 0.11.7：

```text
uv sync --project plugins/ai-sow --locked
uv run --project plugins/ai-sow --locked python -m unittest discover -s tests -v
uv run --project plugins/ai-sow --locked python scripts/validate_repository.py
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow/skills -q
uv run --project plugins/ai-sow --locked python plugins/ai-sow/tests/support/smoke_plugin.py --copy-plugin
```

完整要求见[贡献指南](CONTRIBUTING.md)。

## 添加其他插件

1. 创建 `plugins/<stable-plugin-name>/.codex-plugin/plugin.json` 和
   `plugins/<stable-plugin-name>/.claude-plugin/plugin.json`，保持名称、版本和描述一致。
2. 将运行时代码、依赖、资产、文档和测试全部放在插件目录内。
3. 在两份 marketplace 目录中添加指向同一插件目录的本地来源。
4. 扩展仓库验证器、测试、文档和发布说明。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。项目自行编写的模板、示例和文档采用同一许可证；
依赖项仍适用各自许可证。详见 [NOTICE](NOTICE)。
