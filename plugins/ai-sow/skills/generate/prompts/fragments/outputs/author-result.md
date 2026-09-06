# Author 结果合同

只输出 envelope 的 `resultPayloadSchema` 接受的一个 JSON 对象，不附加 Markdown 或解释文本。

- 正常候选使用当前 action 指定的 patch result kind，`replacementSet` 只包含允许集合的 upsert/delete，并精确绑定既有节点 hash。
- `reviewedEvidenceIds` 只能来自本 action 的初始证据或 hydration 记录。
- `selfCheck.completedCheckIds` 必须与 packet 的 required checks 完全一致；未解决项放入 `selfCheck.unresolvedItems`。
- 权威事实缺失使用 `GAP_CANDIDATE`；已成立事实无法由合同表达使用 `DIAGNOSTIC_CANDIDATE`。
- 不构造下一条命令、下一阶段、路由或用户批准。
