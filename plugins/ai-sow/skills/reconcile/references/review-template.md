# AI SOW 影响集整体评审

本文件是一次 reconciliation 的整体专业评审材料。全部 Owner-local candidate、review projection、
staged receipt、SOW package、redo manifest、diff 和风险摘要完成机械验证后，由 `review-packet.json`
绑定完整闭包；Reviewer 与用户批准都绑定 packet SHA-256，不在批准后改写本文件或 staged closure。

## 修正与范围

```text
Run ID: <12-lowercase-hex>
Correction Owner: <analyze-requirement | analyze-as-is | generate-design | generate-story | generate-task>
Impact Suffix: <从修正 Owner 到 generate-sow 的逗号分隔连续阶段列表>
Correction Fact: <已确认的修正事实>
Evidence: <已在 baseline 正式路径存在的证据与 anchor>
```

说明为什么只有一个 Owner 对修正事实拥有写权限，以及为什么无需返回影响起点之前。

## Owner 影响矩阵

按 `Impact Suffix` 中从修正 Owner 到 `generate-task` 的固定 Owner 顺序逐行填写；不得为
`generate-sow` 增加伪稳定 output 行。`generate-sow` 始终作为最后的 package 投影保留在
`Impact Suffix` 中。

| Owner | Impact | Before Output SHA-256 | After Output SHA-256 | Stable IDs | Rationale |
|---|---|---|---|---|---|
| `<owner>` | `CHANGED / NO_CHANGE` | `<named-output>=<64-lowercase-hex>` | `<named-output>=<64-lowercase-hex>` | `<全部受影响或确认不受影响的稳定 ID>` | `<专业理由>` |

Before/After 单元格使用 canonical named-output 顺序；每项严格写成 `name=64-lowercase-hex`，多份 output 以 `; ` 连接。例如 Design 必须按 `design=<hash>; technicalRequirements=<hash>` 填写。逐个列出该 Owner 的全部稳定 output，不使用 `old`、`new`、省略号或其他占位。

`NO_CHANGE` 的每个 named output 前后 hash 必须相同。`CHANGED` 只能改变该 Owner 的 named output；语义未变的 ID 保持稳定。Publisher 将这两列逐 Owner、逐 named output 与获批 redo operation 的 before/after SHA-256 完全对账。

## Owner-local 评审

为影响矩阵中的每个 Owner 设置一个同名三级标题，并忠实覆盖该 Owner `SKILL.md` 与 review template 要求的完整专业内容：

```text
### generate-design
<目标设计、Decision、Scope、TECHNICAL requirements、HLD/Go-live 等 Owner-local 结论>
```

不得把一个 Owner 的业务规则移入另一个 Owner 的章节。每个 Owner 的正式 review 投影必须携带：

```text
Reconciliation Run ID: <run-id>
Reconciliation Review SHA-256: <本文件批准前完整字节的 SHA-256>
```

## Story / AC 冻结

精确保留以下声明：

```text
Story/AC Outcome Change: NO_CHANGE
Story/AC Exact Diff: NONE
```

技术设计、实现机制、Task 拆分、基础单元、工作模式或复杂度变化使用上述 `NO_CHANGE`。只有修正事实本身改变可独立验收的业务交付结果时，改为：

```text
Story/AC Outcome Change: CHANGED
Story/AC Exact Diff: <逐个 Story ID 与 AC ID 列出 before -> after，不得写概括性占位>
```

Task 章节只能说明如何满足已批准 Story/AC，不能以 Task 计数口径反向修改业务合同。

## Task 与估算影响

说明 Task、AC 覆盖、基础单元、工作模式、复杂度、Effective Start、Integration 和模板影响。列出所有变化的 Task ID；没有变化时明确 `NO_CHANGE` 及理由。

## 发布与恢复确认

确认：

- 所有修正证据和 Owner input 在 baseline 前已存在于正式项目路径；
- staging 只包含获批 Owner review、candidate/output、receipt 和 SOW package；
- 发布使用单一写入者，package 先于 Owner 正式路径发布；
- 中断只使用同一 redo manifest 前向恢复；第三种 hash 转人工核对。

## Packet 与独立批准

本文件不写 `Reviewer: PASS` 或用户批准。确定性 assemble 把本文件及全部 staged closure 编入
`review-packet.json`；Reviewer `PASS` 写入同目录 `reviewer.json`，用户明确批准写入同目录
`approval.json`，二者都绑定相同的 `run-id + packet SHA-256`。当前 Stage 展示本文件完整内容、风险
摘要、package ID、run ID 和 packet SHA-256；任何绑定字节变化都必须形成新 packet 并重新整体复审、
批准。
