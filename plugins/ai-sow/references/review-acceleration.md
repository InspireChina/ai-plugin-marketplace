# Owner 降本评审合同

该合同由 `analyze-requirement`、`analyze-as-is`、`generate-design`、`generate-story` 与 `generate-task` 共用。

## 机械内循环

Stage 在创建任何 Reviewer 前，自行循环运行公开的 renderer、`prepare_context.py` 与 `validate.py --mode review`，直到 outcome 为 `REVIEW_REQUIRED`。可预期的 Schema、引用、路径、数量、重复事实或 packet 机械失败不得带出 Stage。

## 断言核验与完备性

`prepare_context.py` 将 candidate 的专业自由文本确定性投影为 work-only `claims.json`，并作为 context fragment 绑定 packet。每条 claim 只携带一个 Owner 字段及其最小 anchor。

- Claim Verifier 按 claim 分片并发，每片返回 `PASS`、`FAIL` 或 `UNVERIFIED`；`PASS` 必须引用原文行号。
- `analyze-requirement` 以来源处置条目为事实分片，不让单个 Reviewer 逐份顺序复读完整来源。
- Judgment Reviewer 使用 fresh context，只处理证据充分性、设计缺陷和完备性，并执行模型路由规定的抽检。
- 完备性只回答“事实族是否漏 claim”和“方案假设是否漏 premise”，不重新浏览全部仓库。

含绝对化或数量表述的 FACTUAL claim 必须在 `anchors` 中增加机械 count anchor：`path` 点名最小依据，`glob` 只匹配项目内文件，`expr` 使用 `files`、`lines`、`regex:<pattern>` 或 `json:<JSON Pointer>`，`expected` 保存声明值。As-Is 的仓库数量优先用 `glob: .ai-sow/work/analyze-as-is/repo-facts.json` 加 `json:` pointer，不重新扫描仓库。

停止条件是“未验证 claim 数为零且完备性检查通过”，不是连续若干轮没有 finding。

## 字段级修复与轻量复审

Reviewer finding 的修复使用 Owner-local `scripts/apply_patch.py`。patch 采用 JSON Pointer 的 `replace`、`add` 或 `remove`，每条 operation 带 `findingId`；禁止直接自由编辑 candidate 或整段重写。

脚本比较 patch 前后字节并计算稳定 ID 的引用传递闭包：声明外变化触发 `PATCH_FREEFORM_EDIT_DETECTED`；闭包内未修改且未明确确认的对象触发 `PATCH_CLOSURE_UNSYNCED`。修复后的复审由新的轻量 Reviewer 执行，只读取 patch diff、影响闭包和闭包字段原文，不加载仓库或 round-1 历史。

## 已验证断言复用

Owner receipt 可累积 `verifiedClaims`。claim 文本 hash 与 anchor hash 均不变时跳过重新核验；任一变化、`UNVERIFIED`、抽检命中或仓库 revision 变化都使缓存失效。抽检必须包含缓存命中项。

## 预算与深度

项目级 Owner 控制使用 `investigationMode`、`reviewDepth` 与 `tokenBudget`。达到预算时立即输出已核验数量、总 claim 数和剩余 claim ID，不静默重试或把未验证项视为通过。模型分流遵循[模型路由](model-routing.md)。
