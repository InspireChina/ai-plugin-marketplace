# 开发维护

普通使用从 [README](../README.md) 开始。本页面向维护者，说明文档归属和验证方法。

## 目录职责

| 位置 | 内容与维护方式 |
|---|---|
| `README.md` | 安装、输入、生成、改稿、交付和恢复；不追加开发轮次日志 |
| `CHANGELOG.md` | 按发布版本说明用户可见变化，不按 I1/I2 等实施任务排列 |
| [support.md](support.md) | 当前支持范围、前置条件和已知限制 |
| [validation/README.md](validation/README.md) | 当前验证摘要，链接具体证据；旧结果不回写为新通过 |
| [design/](design/README.md) | 领域约定、架构、专题设计和流程图 |
| [archive/](archive/README.md) | 历史实施计划、验证轮次和原始性能指标；仅用于追溯 |
| `skills/`、`references/` | Agent 的运行入口及按需使用的专业规则、工具协议 |
| `tests/` | 可复用测试、合成输入及期望；不向真实语义消费者提供预制答案 |

临时控制脚本、会话日志、工作目录和生成文件留本地验证目录。值得长期保留的结果归入验证摘要或测试；过时的单次工作快照由 Git 历史追溯。历史统计不复制到 README 的每个段落，也不生成新的“文档整理轮次报告”。

本次发布文档整理将 47 份历史计划、开发依赖图、验证及指标文件归档，移除 13 份早期候选快照，保留其 Git 来源。未改变 Skill、运行时、Schema、模板、估算语义或版本号；归档仍位于插件目录，未改变 marketplace 的整目录分发方式。后续若要缩小安装包，需单独明确打包边界。测试导航改指当前验证摘要；冻结样本索引仅刷新 README 链接调整后的哈希，PRD/HLD/原型的内容和哈希保持。

## 验证命令

以下从 marketplace 仓库根目录执行；贡献者需具备 uv。普通插件用户无需执行。

```sh
uv sync --project plugins/ai-sow-lite --locked
uv run --project plugins/ai-sow-lite --locked pytest -c plugins/ai-sow-lite/pyproject.toml plugins/ai-sow-lite/tests -q
uv run --project plugins/ai-sow-lite --locked python plugins/ai-sow-lite/tests/support/check_scenario_coverage.py --ledger docs/validation/scenario-coverage.json
uv run --project plugins/ai-sow-lite --locked python -m unittest discover -s tests -v
uv run --project plugins/ai-sow-lite --locked python scripts/validate_repository.py
git diff --check
```

完整 Lite 测试包含独立复制插件和真实 Office 消费者。引擎或平台不可用导致的跳过不能当成该环境支持证据；场景台账通过只证明结构、编号和引用有效，不代表全部语义场景实跑。

涉及整个仓库时同时运行贡献指南要求的旧插件回归和复制 smoke。新增文档及迁移链接也应纳入检查，归档不能切断场景台账的证据引用。

## 发布维护

对外发布时同步 README、版本说明和支持状态；manifest、`pyproject.toml`、锁文件和目录身份保持一致。最终提交完成规定检查后再执行合并、推送及发布；发布后确认远端安装和入口发现。资料和客户衍生产物不放入发布源码。
