# AI Plugin Marketplace

一个面向实用、可评审 AI 工作流的开源 Codex 插件市场。首个插件 AI SOW
可以把需求和系统上下文转换为可追溯的工作说明书（SOW）工作簿。

## 插件

| 插件 | 版本 | 用途 |
| --- | --- | --- |
| [AI SOW](plugins/ai-sow/README.md) | 0.1.0 | 分析范围、核对系统现状、估算交付工作并生成可评审的 XLSX。 |

## 平台验证状态

| 平台 | 状态 | 证据边界 |
| --- | --- | --- |
| macOS | 已验证（`Verified`） | 已在真实 Mac 上运行仓库测试、本地 Codex marketplace 安装、已安装插件目录执行和大型 Brownfield 工作流。 |
| Linux | CI 覆盖（`CI-covered`） | GitHub 托管 CI 覆盖仓库和插件测试，但不声明桌面 Excel 验收。 |
| Windows 11 | 临时支持（`Provisional`） | 已具备可移植分支和 Windows CI，但仍未完成实机验收。 |

CI 和合成测试不能作为 Windows 11 实机验收结果。开放风险、实机检查清单和
状态变更所需证据见 [Windows 11 验证状态](docs/windows-11-validation.md)。

## 安装

普通插件用户只需要支持本地 marketplace 的 Codex，安装时能访问 marketplace，首次
`setup` 时能访问 Astral 官方下载源；无需预装 Git、Python、[uv](https://docs.astral.sh/uv/) 或 Python 依赖，也
无需管理员权限或终端操作。`setup` 会在插件安装副本内自动准备 uv 0.11.7、managed Python 3.12、
锁定依赖和插件 `.venv`，后续阶段直接复用该隔离环境。

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

## 更新

先刷新 Git marketplace 快照，再重新安装插件，使 Codex 使用更新后的安装包：

```text
codex plugin marketplace upgrade ai-plugin-marketplace
codex plugin remove ai-sow@ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
```

如果 marketplace 注册自本地 checkout，请先拉取该 checkout；`marketplace upgrade`
只负责刷新已配置的 Git marketplace。

## 卸载

先删除插件，再删除 marketplace 注册：

```text
codex plugin remove ai-sow@ai-plugin-marketplace
codex plugin marketplace remove ai-plugin-marketplace
```

## 仓库结构

```text
.agents/plugins/marketplace.json  Marketplace 目录
plugins/ai-sow/                   自包含插件包
scripts/                          仓库与插件包冒烟检查
tests/                            Marketplace 级测试
.github/                          贡献模板与 CI
```

插件包自行拥有运行时依赖，运行时不读取 marketplace 根目录中的文件。因此，从已安装
插件目录运行时仍能保持完整功能。

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

## 添加其他插件

1. 创建 `plugins/<stable-plugin-name>/.codex-plugin/plugin.json`。
2. 将插件的运行时代码、依赖、资产、文档和测试全部保存在该插件目录下。
3. 在 `.agents/plugins/marketplace.json` 中添加一项本地来源配置。
4. 扩展仓库验证器和测试，使其覆盖新插件包。
5. 在提交 Pull Request 前补充插件文档和发布说明。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。项目自行编写的模板、示例和文档采用同一
许可证；依赖项仍适用各自许可证。详见 [NOTICE](NOTICE)。
