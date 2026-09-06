# 贡献指南

感谢你帮助改进 AI Plugin Marketplace。大型变更请先通过 GitHub Issues 提交公开缺陷
报告或功能建议，以便提前确认范围。Issue 和 fixture 中不得包含客户 SOW 内容、凭据、
私有仓库详情或其他敏感信息。

## 开发环境

本节只适用于仓库贡献者。普通插件用户由 `ai-sow:generate` 的 bootstrap 自动准备隔离运行时，不需要执行这些命令。
贡献者安装 Git、Python 3.12、uv 0.11.7 和 LibreOffice 后运行：

```text
uv sync --project plugins/ai-sow --locked
```

SOW 正式工作簿必须由真实 LibreOffice 重新计算并复读，不能用合成缓存或跳过测试代替。
系统会优先读取 `AI_SOW_OFFICE_BIN` 指定的 `soffice`/`libreoffice` 可执行文件，其次从
`PATH` 自动发现。CI 在 Linux、macOS 和 Windows 上均安装 LibreOffice，并显式设置该变量。

每个插件都必须自包含，不得依赖自身安装目录以外的文件。实现行为变更前先添加测试，
并保持 manifest、合同版本、文档和发布说明一致。

## 每 Task 验收与最终验证

每个 Task 仅验证本次新增/修复行为和直接受影响的契约、调用边界，不默认运行整文件、整插件或完整端到端。
单元、局部集成和完整端到端使用独立 pytest markers；命令与层级说明见
[插件测试指南](plugins/ai-sow/tests/README.md)。已有测试的重复内容应合并并说明承接断言，保留关键失败与边界回归。

以下为计划最终集成/交付门禁，不是每个 Task 的默认检查：

```text
uv run --project plugins/ai-sow --locked python -m unittest discover -s tests -v
uv run --project plugins/ai-sow --locked python scripts/validate_repository.py
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow -q
uv run --project plugins/ai-sow --locked python plugins/ai-sow/tests/support/smoke_plugin.py --copy-plugin
```

提交 Pull Request 前请在安装真实 LibreOffice 的环境中运行全部检查，确认 Office 往返测试
实际执行而不是被跳过。Pull Request 应说明问题、选定边界、用户可见
行为、测试结果，以及任何隐私或兼容性影响。提交应保持小而聚焦。

冒烟命令把插件包复制到独立临时目录，并在其外创建用户项目，通过 Python `NextAction` API 验证
Greenfield、Brownfield、同 run 恢复、abandon/start，以及相同输入、模板变化和业务变化时的新 run 完整编译。
每轮都必须完成三阶段 fresh Review。它同时检查不可变输入和输出、工作簿 Table/公式、last-known-good，
并用读取守卫证明运行时不访问复制插件或测试项目之外的文件。完整发布 smoke 在最终集成门禁执行；
失败保留 work-dir、failure receipt 和 worker stdout/stderr，成功报告包含临时工作目录。

提交贡献即表示你同意该贡献采用 Apache License 2.0。
