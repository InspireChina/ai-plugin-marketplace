# Reviewer 模型路由

模型名称只影响 Reviewer 调度，不改变 Owner、Schema、hash-bound packet、用户批准或稳定数据合同。宿主支持哪一列就使用哪一列；不得把深度判断降级到事实核验模型。

| 工作 | Claude 路由 | Codex 路由 |
|---|---|---|
| 结构、引用、Schema、绝对化与数量门禁 | 确定性脚本 | 确定性脚本 |
| 单条事实 claim 对 anchor | Haiku 4.5，高并发 | `gpt-5.6-luna`，`low`，高并发 |
| 来源处置表单条核对 | Haiku 4.5，高并发 | `gpt-5.6-luna`，`low`，高并发 |
| 文档一致性、patch 回归与 diff-review | Sonnet 5 | `gpt-5.6-terra`，`high` |
| As-Is 前提证伪 | Sonnet 5 | `gpt-5.6-terra`，`high` |
| 证据充分性、设计缺陷、业务完备性 | Opus，不可降级 | `gpt-5.6-sol`，`max`，不可降级 |

只有 `confidence: HIGH` 且至少有一个可解析 anchor 的 `FACTUAL` claim 可进入廉价通道；其他 claim 直接进入深度判断通道。事实核验 `PASS` 必须给出原文行号，给不出时返回 `UNVERIFIED`。深度判断 Reviewer 随机复验至少 10% 的廉价通道 `PASS`，并覆盖缓存命中项；命中一个假阴性就把当前批次全部升级到深度判断模型重跑。
