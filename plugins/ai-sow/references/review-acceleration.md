# Owner 降本评审合同

该合同由 `analyze-requirement`、`analyze-as-is`、`generate-design`、`generate-story` 与 `generate-task` 共用。

## 机械内循环

Stage 在创建任何 Reviewer 前，自行循环运行公开的 renderer、`prepare_context.py` 与 `validate.py --mode review`，直到 outcome 为 `REVIEW_REQUIRED`。可预期的 Schema、引用、路径、数量、重复事实或 packet 机械失败不得带出 Stage。

## 断言核验与完备性

输入 context 与 review claims 是两个绑定对象：`fragments` 只包含上游输入闭包；candidate 尚未形成时
manifest 的 `reviewClaims.status` 为 `PENDING_CANDIDATE`，且不得写空 `claims.json`。candidate 形成后
重跑 `prepare_context.py`，将专业自由文本确定性投影为 work-only `claims.json`，以独立
`reviewClaims.fragment` 绑定 packet。每条 claim 只携带一个 Owner 字段及其最小 anchor。

- `reviewRoute: FACT_VERIFIER_LOW` 只用于有可解析 anchor 的 `FACTUAL` claim；Claim Verifier 按 claim
  分片并发，每片返回 `PASS`、`FAIL` 或 `UNVERIFIED`，`PASS` 必须引用原文行号。
- 其他 claim 固定为 `reviewRoute: JUDGMENT_REVIEWER_DEEP`，不得进入廉价事实通道；结构、引用和
  Schema 完整性继续由确定性 validator 处理，不创建模型 claim。
- `analyze-requirement` 以来源处置条目为事实分片，不让单个 Reviewer 逐份顺序复读完整来源。
- Judgment Reviewer 使用 fresh context，只处理证据充分性、设计缺陷和完备性，并执行模型路由规定的抽检。
- 完备性只回答“事实族是否漏 claim”和“方案假设是否漏 premise”，不重新浏览全部仓库。

含绝对化或数量表述的 FACTUAL claim 必须至少有一个可解析的最小来源 anchor；来源本身含该业务
事实时交给低成本 verifier 逐行核验。由仓库或结构化投影推导、无法直接逐行核对的数量必须增加机械
count anchor：`path` 点名最小依据，`glob` 只匹配项目内文件，`expr` 使用 `files`、`lines`、
`regex:<pattern>` 或 `json:<JSON Pointer>`，`expected` 保存声明值。As-Is 的仓库数量优先用
`glob: .ai-sow/work/analyze-as-is/repo-facts.json` 加 `json:` pointer，不重新扫描仓库。

停止条件是“未验证 claim 数为零且完备性检查通过”，不是连续若干轮没有 finding。

## Reviewer 判断冻结与机器摘要

Reviewer 对当前 packet 的第一次判断必须立即通过 Owner-local validator 记录；`PASS` 与 `BLOCKED`
都不能只留在聊天文本中：

```text
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode record-reviewer \
  --packet-sha256 "<当前 packet SHA-256>" \
  --review-decision PASS

"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode record-reviewer \
  --packet-sha256 "<当前 packet SHA-256>" \
  --review-decision BLOCKED \
  --finding-id "<finding-id>"
```

`BLOCKED` 必须逐项传入非空、唯一的 finding ID。命令在
`.ai-sow/work/<owner>/review-judgments/<packet-sha256>.json` 保存内容寻址判断；同一 packet 的首次
判断不可改写，也不能在没有新 candidate、context、Evidence 或 review 字节的情况下从 findings
翻转为 `PASS`。新证据必须先生成新的 packet hash。`PASS` 同时写现有
`ai-sow-owner-reviewer-v1` sidecar；`write-reviewer` 只保留为 `PASS` 兼容入口，并服从同一冻结记录。

Owner validator 的结构化 stdout 使用 `artifactMetrics` 投影 candidate 顶层集合数量和 canonical
hash。Stage 的阶段完成/阻塞摘要必须逐字使用该对象，不得由 Agent 自行手算 Story、AC、Evidence、
Task 或其他集合数量。stdout 没有 `artifactMetrics` 时不得补报推测数字。

## 字段级修复与轻量复审

Reviewer finding 的修复使用 Owner-local `scripts/apply_patch.py`。patch 采用 JSON Pointer 的 `replace`、`add` 或 `remove`，每条 operation 带 `findingId`；禁止直接自由编辑 candidate 或整段重写。

patch 的固定结构如下；`acknowledgedClosureIds` 只能逐项列出已阅读且确认无需同步修改的当前 Owner 对象 ID，匿名对象使用 `@<JSON Pointer>`，不得使用通配符或 `ALL`：

```json
{
  "operations": [
    {"op": "replace", "path": "/items/0/summary", "value": "修复后的值", "findingId": "F-1"}
  ],
  "acknowledgedClosureIds": ["coverage-one", "@/anonymous-boundary"]
}
```

同一 finding 必须同步修改一个 Owner 的多个候选文档时，使用顶层 `documents` 数组；每项只允许
`path / operations / acknowledgedClosureIds`，且 `path` 必须在 Owner wrapper 公布的候选白名单内。
多文档不得与顶层单文档字段混用，所有文档、audit、context、review 和 post-check 只提交一次；任一
文档失败则全部回滚且不消耗 patch 轮次。

脚本比较 patch 前后字节并计算当前 Owner 文档内的引用传递闭包；上游 Feature、Decision、Commitment 等非本阶段所有的外部 ID 只作为叶子引用，不得充当连接两个 Owner 对象的遍历枢纽。有稳定 ID 的对象以 ID 标识，没有稳定 ID 但持有引用的对象以 `@<JSON Pointer>` 标识。声明外变化触发 `PATCH_FREEFORM_EDIT_DETECTED`；闭包内未修改且未明确确认的对象触发 `PATCH_CLOSURE_UNSYNCED`。

`PATCH_CLOSURE_UNSYNCED` 是原子拒绝：脚本不写 candidate 或 audit，诊断返回 `candidateUpdated: false`、`retryAllowed: true`、`consumesPatchRound: false` 和确认字段名。Owner-local `apply_patch.py` 把 candidate、audit、context、确定性 review 投影、Owner `review` post-check 与新 diff packet 作为一个 staging 事务；任一步骤失败都不改当前工作集，stdout 返回 `patchRoundConsumed: false`。只有整笔事务提交并返回 `OK` 才令 `patchRoundConsumed: true`，Stage 不再另行重跑 renderer 或 `review`。只要 base/candidate 仍与 round-1 packet 原字节绑定、finding ID 未变化且没有扩大语义范围，Stage 必须按 `syncSuspects` 逐项修改或确认后重试一次；该修正重试不是新的 Reviewer 修复轮。修正后的命令再次被原子拒绝时才返回 `BLOCKED`。

任何 Owner 生成与当前内容不同的新 `review-packet.json` 时，都在同一文件事务中把旧 packet、`reviewer.json` 与 `approval.json` 归档到 `.ai-sow/work/<owner>/archive/<old-packet-sha256>/`，并从当前路径撤销旧授权；内容寻址的 `review-judgments/` 保持原位。新 packet 与当前 packet 原字节相同时不旋转 sidecar。

修复后的复审由新的轻量 Reviewer 执行，只读取 `patch-audit.json` 中的 `diffReview`：变更字段前后值、
一跳直接闭包、相关 `acceptanceCriterionId -> storyId -> featureId` 映射和新 packet 绑定，不加载传递
闭包全文、仓库或 round-1 历史。`diffReview.payloadBytes` 的硬上限是 65536；超限触发
`PATCH_DIFF_BUDGET_EXCEEDED`，原子拒绝且不消耗 patch 轮次。

轻量 Reviewer 的第一次判断仍按新 packet 冻结。Owner Skill 只有在自身合同明确授权时，才可把
“由首次 patch 引入、完全局限于当前 Owner candidate、无需改变上游语义且不扩大范围”的 finding
归为一次纠错 patch；纠错继续使用 finding-bound 字段操作、原子 post-check、新 packet 和最终轻量
diff-review。Owner Skill 必须同时规定成功 patch 与 Reviewer 的硬上限。需要修改上游 Owner 数据、
最终轻量 Reviewer 仍有 finding 或超出显式额度时停止，不能通过重启 Reviewer 翻转同一 packet。

## 已验证断言复用

Owner receipt 可累积 `verifiedClaims`。claim 文本 hash 与 anchor hash 均不变时跳过重新核验；任一变化、`UNVERIFIED`、抽检命中或仓库 revision 变化都使缓存失效。抽检必须包含缓存命中项。

## 预算与深度

项目级 Owner 控制使用 `investigationMode`、`reviewDepth` 与 `tokenBudget`。达到预算时立即输出已核验数量、总 claim 数和剩余 claim ID，不静默重试或把未验证项视为通过。模型分流遵循[模型路由](model-routing.md)。

## 结构化 Finding 路由

当前 Owner 无法在自身写集合内修复时，Stage 输出一个由 `runtime/findings.py` 定义的路由对象；自由
文本 `summary` 只解释问题，不决定路由：

```json
{
  "findingId": "finding-example",
  "discoveredBy": "generate-task",
  "correctionOwner": "generate-design",
  "category": "UPSTREAM",
  "subjectIds": ["story-example"],
  "summary": "已批准交付结果内缺少可实施的设计机制。",
  "requiresUserDecision": false
}
```

- `LOCAL` 表示当前 Owner 可在自身写集合内修复，`correctionOwner` 为当前 Owner。
- `UPSTREAM` 表示另一个既定 Owner 可在不新增用户决策的情况下修正，`correctionOwner` 点名该 Owner。
- `DECISION` 表示范围、责任、验收结果、商业承诺或服务容量需要用户决定，`correctionOwner` 为
  `null`，`requiresUserDecision` 为 `true`。
- `MECHANICAL` 表示 Schema、renderer、validator、receipt 或投影问题，不通过修改业务数据绕过。

`discoveredBy` 与非空 `correctionOwner` 只允许五个专业 Owner；`subjectIds` 点名实际受影响对象。
Stage 用 Owner 公开的 finding validator 校验后再停止或路由。该对象只承载机械路由元数据，不进入
六份稳定业务 JSON，不替代 Reviewer 的 packet-bound finding ID，也不启用自动 reconciliation。

## 确定性输出信任

任何 `scripts/*.py` 返回等价于 `outcome: OK`（或该脚本定义的成功状态）且 `diagnostics` 为空时，
该结构化结果就是同一 artifact 的最终机械依据。Stage 直接引用 stdout 已提供的 hash、摘要、数量、
路径或状态字段并继续下一步。

对同一 artifact 不再重新计算已返回的 hash、重新枚举刚写入的目录、重新读取刚写入的文件核对字节，
也不再发起第二次等价的确定性调用。需要后续门禁时只运行合同明确列出的下一条命令；后续命令发现
漂移或失败时，原样报告其 diagnostics。
