# 贡献指南

感谢你帮助改进 AI Plugin Marketplace。大型变更请先通过 GitHub Issues 提交公开缺陷
报告或功能建议，以便提前确认范围。Issue 和 fixture 中不得包含客户 SOW 内容、凭据、
私有仓库详情或其他敏感信息。

## 开发环境

本节只适用于仓库贡献者。普通插件用户由 `setup` 自动准备隔离运行时，不需要执行这些命令。
贡献者安装 Git、Python 3.12 和 uv 0.11.7 后运行：

```text
uv sync --project plugins/ai-sow --locked
```

每个插件都必须自包含，不得依赖自身安装目录以外的文件。实现行为变更前先添加测试，
并保持 manifest、合同版本、文档和发布说明一致。

## 必需检查

```text
uv run --project plugins/ai-sow --locked python -m unittest discover -s tests -v
uv run --project plugins/ai-sow --locked python scripts/validate_repository.py
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow -q
uv run --project plugins/ai-sow --locked python plugins/ai-sow/tests/support/smoke_plugin.py --copy-plugin
```

提交 Pull Request 前请在本地运行全部检查。Pull Request 应说明问题、选定边界、用户可见
行为、测试结果，以及任何隐私或兼容性影响。提交应保持小而聚焦。

冒烟命令只把插件包复制到独立临时目录，在该目录之外创建用户项目：先建立复制插件的 `.venv`，
再通过该 Python 运行 setup、复核 fixture 中五份 Owner 0.3 receipt，并生成确定性交付包。它不重放
Owner 专业 validator；这些规则由前一条全量 pytest 覆盖。最终 JSON 报告会包含临时工作目录，便于检查。
beta.1 项目 metadata 只能显式运行 `plugins/ai-sow/migrations/beta1_to_beta2.py` 升级；正常
`setup` 不自动迁移，六份稳定数据必须由 Owner 重新评审并发布 0.3 收据。

提交贡献即表示你同意该贡献采用 Apache License 2.0。
