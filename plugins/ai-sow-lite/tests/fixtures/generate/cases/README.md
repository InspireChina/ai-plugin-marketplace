# Generate 语义验收输入

各案例的 `inputs/` 是实际提供给被测新会话的合成原件；`answers.md` 由评估者按真实提问提供，`expectations.json` 留在评估侧。它们不是业务模型或固定 Story/Task 答案，不得随被测插件副本提供。

`three-scope` 与 `local-nfr` 比较独立公共建设和页面内部约束；`multiple-query-instances` 用同一业务对象的两个独立 API 验证标准工作单元；两个 `insufficient-*` 案例分别缺 HLD、仅有草稿和技术便笺；`bounded-input-questions` 验证实际答复仍不足时的有限退出。历史候选、明确实例、已满足目标在 [历史案例](../../history/cases) 中。

每项期待包含 required、forbidden、allowed_variations、pending 和 source_refs；按实际义务和来源人工核对，允许合理命名、层级和分片差异。案例存在不代表执行通过，真实输出与限制见 [验证记录](../../../../docs/archive/validation/I2-generate.md)。

`delivery-source-boundaries` 是真实 S1/S2 失败后的有限交付范围变体，核对标准不能扩充 AC、未知验证数据责任不能成为事实；它只重验受影响范围，不替换原失败记录。

`existing-unsupported-hld` 补旧项目缺历史、HLD 仅为不支持格式的批量缺件出口。PDF 是扩展名拒绝夹具，不是有效 PDF 或解析/渲染测试；Agent 只见 inputs，实际运行保留最少接收记录后结束。
