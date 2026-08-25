---
name: reconcile
description: 当已有 AI SOW Owner 稳定产物因一项上游修正需要在一次批准中整体复核连续影响后缀、更新 receipt 并重新生成 SOW 包时使用。
---

# 整体协调 AI SOW 影响集

在一个 session 中协调一次已登记修正及其完整下游影响。普通首次生成继续使用七阶段 Skill；本
Skill 不拥有稳定业务 JSON，也不解释或复制 Owner 业务规则。

执行前完整读取并遵守[输出语言合同](../../references/output-language.md)。整体评审使用简体中文；
Owner、路径、hash、枚举和其他 machine token 保持原值。

## 当前任务与固定边界

当前 Stage Agent 是本 Skill 的唯一用户接口、专业协调者和确定性命令派发者；不创建 Worker 或
Validator 叶子 Agent。批准前只创建一个不继承当前完整聊天的 fresh-context Reviewer；同一次调用
最多使用该 Reviewer 完成一次完整审查，发现 findings 时允许 Stage 一次整体修复并重新机械闭环后，
交回同一 Reviewer 完整复审。第二次仍有 findings 时 `BLOCKED`。

固定顺序为：

```text
analyze-requirement
-> analyze-as-is
-> generate-design
-> generate-story
-> generate-task
-> generate-sow
```

影响集只能从唯一修正 Owner 开始，连续延伸至 `generate-sow`。整体 review 的 `Impact Suffix` 必须
显式包含最后的 `generate-sow`；Owner 影响矩阵和 redo `owners` 只列拥有稳定数据的 Owner，到
`generate-task` 为止，`generate-sow` 由 package 段表示。不得跳过中间 Owner、配置阶段图或建立
字段级依赖。修正证据、来源、问卷和 prior SOW 必须在建立 baseline 前已位于正式项目路径；staging
不登记或发布新的 Owner input。

每个受影响 Owner 只能为 `CHANGED` 或 `NO_CHANGE`：

- `CHANGED`：只修改该 Owner 的 work-only review projection、candidate、staged output 和 receipt；
  语义未变的 ID 保持稳定。
- `NO_CHANGE`：不编译 candidate、不运行拒绝 `Impact: NO_CHANGE` 的 check；稳定 output 原字节复用，
  只把获批 review projection staged 后执行 Owner-local `rebind`。
- 设计、实现机制、基础单元、工作模式、复杂度或 Task 边界变化默认保持 Story/AC 不变。只有修正
  本身改变业务交付结果，且整体评审包含 `Story/AC Outcome Change: CHANGED` 和精确差异时，
  `generate-story` 才能为 `CHANGED`。Task 不得修改 Delivery、Story 或 AC。

任一 Owner 归属不唯一、修正需要回到影响起点之前、Owner-local 门禁失败或同一项目存在并发写入时
返回 `BLOCKED`。

## 批准前完整闭包

为本次运行生成 12 位小写十六进制 `<run-id>`，只使用：

```text
.ai-sow/work/reconcile/<run-id>/review.md
.ai-sow/work/reconcile/<run-id>/diff.json
.ai-sow/work/reconcile/<run-id>/risk-summary.md
.ai-sow/work/reconcile/<run-id>/redo.json
.ai-sow/work/reconcile/<run-id>/review-packet.json
.ai-sow/work/reconcile/<run-id>/reviewer.json
.ai-sow/work/reconcile/<run-id>/approval.json
.ai-sow/.stage-<run-id>/
```

当前 Stage 先读取[整体评审模板](references/review-template.md)和受影响 Owner 的完整 `SKILL.md`、
Owner-local 必需 reference、当前稳定 output/review/receipt 与修正证据，形成 `review.md`、全部
`CHANGED` candidate 和每个 Owner 的 work-only review projection。影响矩阵 Before/After 必须按
Owner receipt 的 named output 顺序使用 canonical `name=64-lowercase-hex`；多份 output 以 `; `
连接。`NO_CHANGE` 的 Before/After hash 必须相同。

批准前在同一个 flat staging view 完成一次固定顺序的前向 pass：

1. `CHANGED` Owner-local `check` 通过 `--review-path` 读取 work-only projection，再把 projection 写入
   staging 固定 review 路径并执行 `publish`；candidate After hash 必须等于整体 review 的 named
   After hash。
2. `NO_CHANGE` 直接把 projection 写入 staging 固定 review 路径，执行 Owner-local `rebind`，并把
   原稳定 output 原字节物化到 staging closure。
3. 两类 Owner 都必须匹配刚生成的 staged receipt，才允许下游读取完整 staged handoff；
   `publish/rebind` 不允许 review-path override，HLD/Go-live 仍只由 `generate-design` 判断。
4. 当前 Stage 直接调用 `generate-sow` Reconciliation Adapter，从完整 staged receipt/output/review
   生成并复读内容寻址 package。manifest 与 workbook hash 必须来自 staged bytes，不得回退到 base。

以上步骤只写 work 与 `.ai-sow/.stage-<run-id>/`；正式 Owner 路径和正式 package baseline 保持原字节。
全部通过后，当前 Stage 运行确定性 assemble：

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/reconcile.py" \
  --project-root "<project-root>" \
  --run-id "<run-id>" \
  --mode assemble
```

`assemble` 不调用 Owner 脚本，也不解释业务语义。它从 baseline、flat staging、固定 Owner 后缀和
已验证 package 确定性生成 contract `0.2` 的 canonical `redo.json`、技术 `diff.json`、风险摘要与
`ai-sow-reconciliation-review-packet-v1` packet。packet 精确绑定：整体 review、全部 staged Owner
review/output/receipt、receipt inputs、package tree、diff、risk summary 和 redo manifest。`redo.json`
只记录固定路径与顺序、`WRITE/DELETE`、before/after state、package tree、packet/Reviewer/approval
固定路径和 `writerMode: SINGLE_WRITER`；不得由 Agent 手工拼接。

批准前 `reviewer.json`、`approval.json` 不存在。Reviewer 只读取精确 packet 及其点名的闭包，审查
Owner-local 专业结论、跨阶段一致性、遗漏、Story/AC 冻结、candidate/projection 忠实度、完整 staged
package 与发布风险。`PASS` 后当前 Stage 写 canonical：

```json
{"algorithm":"ai-sow-reconciliation-reviewer-v1","decision":"PASS","packetSha256":"<packet-sha256>","runId":"<run-id>"}
```

Stage 向用户展示整份 `review.md`、risk summary、package ID、run ID 与 packet SHA-256。用户必须明确
批准该 `<run-id>` 和精确 packet SHA-256；随后写 canonical：

```json
{"algorithm":"ai-sow-reconciliation-approval-v1","decision":"APPROVED","packetSha256":"<packet-sha256>","runId":"<run-id>"}
```

任何 input、candidate、Owner projection、staged receipt、package、diff、risk、redo 或整体 review
字节变化都必须重新运行 assemble，形成新 packet，由同一 Reviewer 完整复审并重新取得用户批准。
不得只修 packet 中未点名的影子文件绕过批准。

## 批准后只运行确定性发布

批准后只运行以下两个命令；不得再编译 candidate、修复专业结论、修改 Owner projection、调用
Reviewer、执行 Owner validator/publish/rebind 或重新生成 package：

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/reconcile.py" \
  --project-root "<project-root>" \
  --manifest ".ai-sow/work/reconcile/<run-id>/redo.json" \
  --mode check

uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/reconcile.py" \
  --project-root "<project-root>" \
  --manifest ".ai-sow/work/reconcile/<run-id>/redo.json" \
  --mode publish
```

Publisher 先复算 contract `0.2` redo、packet、Reviewer、approval、全部 staged bytes、receipt closure 和
package tree；任一漂移都在正式发布前 `BLOCKED`。它先发布或复用已验证的不可变 package，再按 Owner
顺序写 review/output，并让每个 receipt 最后写入；`generate-task` receipt 是整批最后一个正式 Owner
写入。正式状态必须属于 manifest 的 before/after，已完成的 after 只能形成有序前缀；第三种 hash、
staged-only receipt input、批准漂移或并发写迹象都不得覆盖。

删除只允许 Requirement Owner 以显式 tombstone 删除已存在的可选 questionnaire review，不允许用
staging 新增 Owner input。Publisher 按 `ai-sow-package-v1` 与 `receipt-only-beta2-v1` 机械复算最终
`generationFingerprint`，绑定 project、六份 output、五份 review、五份 receipt 和正式模板原字节；
这些检查只比较固定字段、路径和 hash，不重放 Owner 业务规则。

发布中断后复用同一个 run ID、packet、批准和 redo manifest 重跑 `publish`；只做幂等前向恢复，
不自动回滚、不创建 revision store、活动指针或项目锁。需要人工处理时报告具体 path、before/after/
current hash 和已发布 package；人工确认前不得生成新 redo 覆盖证据。contract `0.1` 仅由 publisher
保留读取兼容，当前流程不得新建该旧格式。

## 完成

只有 package 已发布、全部 Owner 路径达到 after、五份最终 receipt 的 `FILE` hash closure 完整且
Task receipt 已最后写入时返回 `PUBLISHED`。报告 run ID、packet SHA-256、整体 review、package、各
Owner impact、receipt 和是否发生前向恢复，然后 `STOP`；不得继续修改其他项目内容。
