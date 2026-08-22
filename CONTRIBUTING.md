# 贡献指南

感谢你帮助改进 AI Plugin Marketplace。大型变更请先通过 GitHub Issues 提交公开缺陷
报告或功能建议，以便提前确认范围。Issue 和 fixture 中不得包含客户 SOW 内容、凭据、
私有仓库详情或其他敏感信息。

## 开发环境

安装 Python 3.12 和 uv 0.11.7 或兼容版本，然后运行：

```text
uv sync --project plugins/ai-sow --locked
```

每个插件都必须自包含，不得依赖自身安装目录以外的文件。实现行为变更前先添加测试，
并保持 manifest、合同版本、文档和发布说明一致。

## 必需检查

```text
uv run --project plugins/ai-sow --locked python -m unittest discover -s tests -v
uv run --project plugins/ai-sow --locked python scripts/validate_repository.py
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow/skills -q
uv run --project plugins/ai-sow --locked python plugins/ai-sow/tests/support/smoke_plugin.py --copy-plugin
```

提交 Pull Request 前请在本地运行全部检查。Pull Request 应说明问题、选定边界、用户可见
行为、测试结果，以及任何隐私或兼容性影响。提交应保持小而聚焦。

冒烟命令只把插件包复制到独立临时目录，在该目录之外创建用户项目，依次运行 setup、
全部五个 Owner validator 并生成工作簿。最终 JSON 报告会包含临时工作目录，便于检查。

提交贡献即表示你同意该贡献采用 Apache License 2.0。
