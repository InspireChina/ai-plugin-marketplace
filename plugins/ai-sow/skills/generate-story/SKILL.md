---
name: generate-story
description: 当已评审的业务需求、技术需求、现状和目标设计需要分解为可交付、可验收、可结算的 AI SOW 范围时使用。
---

# 生成交付 Story

把每个范围内 Feature 相对于 Effective Start 的差值直接分解为 Story、AC、Integration、Assumption 和 Risk；Delivery 不再保存中间 Gap 实体。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。业务自由文本使用简体中文；合同 token 保持原值。
按[插件运行时环境合同](../../references/runtime-environment.md)从 `<plugin-root>` 解析当前平台的 `<python-bin>`；后续命令直接使用 setup 已建立的插件 `.venv`。

## 精确批准快速路径

若本次新 session 的用户指令已经明确批准 Owner `generate-story` 和一个完整 packet SHA-256，本节优先于下方完整拆分流程。从当前 turn 的 Available skills 条目直接取得本 `SKILL.md` 的绝对路径；不得使用 `rg`、`find` 或 `rg --files` 枚举或重新定位 Skill。Stage 不得手写 approval JSON，必须严格依次只运行以下两条确定性命令；第一条用 canonical bytes 写固定 `ai-sow-owner-approval-v1` sidecar，第二条执行唯一发布 preflight：

```text
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode write-approval \
  --packet-sha256 "<用户明确批准的完整 packet SHA-256>"
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode publish-approved \
  --candidate .ai-sow/work/generate-story/delivery.candidate.json \
  --review-path .ai-sow/work/generate-story/review.candidate.md
```

`write-approval` 只校验 hash 格式并写固定 sidecar，不读取 packet 或专业成果；`publish-approved` 自己复算 packet、Reviewer、candidate、context、input、review、risk summary 与 approval 的全部绑定，是正式写入前唯一需要的 preflight。

此快速路径不得重新读取上游数据、Schema、reference、candidate、packet 或 Reviewer 内容，不得枚举项目或插件文件，不得运行 `--help` 或除上述两条以外的其他命令，不得运行 `prepare_context.py`、`render_review.py`、独立 `check`，也不得创建 Reviewer 或修改专业成果。任一命令返回 `BLOCKED` 时原样报告 diagnostics 并停止；不得探索实现或退回完整拆分。

## 精确 Reviewer 绑定

fresh-context Reviewer 只返回 `PASS` 或 findings，不写项目文件。Reviewer 对当前 packet 返回 `PASS` 后，当前 Stage 不得手写 reviewer JSON，必须立即运行下列唯一绑定命令；它只校验完整 hash 格式并以 canonical bytes 原子写入固定 `ai-sow-owner-reviewer-v1` sidecar，不读取 packet、candidate、上下文或上游数据：

```text
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode write-reviewer \
  --packet-sha256 "<Reviewer 已独立审查并 PASS 的完整 packet SHA-256>"
```

该命令只能消费实际 Reviewer 的 `PASS`，不能替代独立评审。命令返回 `BLOCKED` 时原样报告并停止；任何 packet 字节变化都必须重新创建 packet、交回 Reviewer 完整复审，再重新绑定。

## 路径

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。保持项目根目录为当前工作目录，并在执行前把命令中的路径占位符替换为绝对路径。

确定性脚本是本 Skill 的公开命令实现。Stage 与 Reviewer 不得复读 `scripts/*.py` 实现，也不得为预测 diagnostics 扫描源码；Stage 只按本 Skill 公布的命令执行并原样消费结构化 stdout。仅当脚本实际异常且公开 diagnostics 不足以定位执行故障时，才允许最小化读取直接报错位置。

开始专业工作前读取插件级[上下文纪律](../../references/context-discipline.md)、[降本评审合同](../../references/review-acceleration.md)与[模型路由](../../references/model-routing.md)。共享合同取代下文遗留的整体自由修复和携带完整历史复审做法；Story/AC 的业务所有权不变。

## 工作流

1. 当前 Stage Agent 是本 Skill 的唯一用户接口和专业执行者，不创建 Worker 或 Validator Agent。先运行 Owner-local context compiler；它用公共 matcher 验证 Requirement、As-Is 和 Design 三个 receipt，并只投影 ScopeDecision、Feature、相关 Design Decision、Effective Start、问卷决定、固定 Go-live Concern 以及关联 Commitment/Evidence/Uncertainty。任一 handoff 为 missing、invalid、stale 或 unsupported 时，报告对应 Owner Skill 并停止。不得调用上游 validator，不得重新执行 Design 的 HLD/Go-live 门禁，也不得重诊断 Requirement 问卷终态或 As-Is 内部实体：

   ```text
   "<python-bin>" "<skill-root>/scripts/prepare_context.py" --project-root .
   ```
2. 当前 Stage Agent 先读 `.ai-sow/work/generate-story/context/manifest.json`，再只读取其中点名的四个 fragment、固定 Schema `<skill-root>/contracts/delivery.schema.json` 和[评审模板](references/review-template.md)。closure 成功后按该精确路径读取 Schema 一次；不得用 `ls`、glob、`rg` 或目录枚举寻找 Schema，也不得读取 fixture/test 代替合同。BUSINESS 与 TECHNICAL requirements 仅在当前内存中联合，不写 merged requirements。对每个已批准的 `APPROVED_DEFAULT / ASSUMPTION_CANDIDATE` Question ID 恰好生成一个 Assumption，其 `handling` 保留 `analyze-requirement-questionnaire#<Question-ID>` 锚点并至少关联一个 Story。`CLOSED / INCORPORATED_BUSINESS:<stable-id>` 与 `CLOSED / NO_CHANGE` 不生成 Assumption。
3. 对每个 `IN_SCOPE` Feature，用目标结果减去其 Coverage 所连接的 Effective Start，直接形成一个或多个结果型 Story；每个 Story 只归属一个 Feature。每条 AC 用 `gapRationale` 引用相关 `effectiveStartItemId`，或在 Coverage 为 `MISSING` 时明确不存在有效起点；相关 `CARRY_FORWARD` Commitment 逐条写入 `carryForwardCommitmentIds`，不能当作基线。`FULLY_COVERED` Feature 不生成 Story；其完整性已由设计门禁中的 Effective Start、Evidence 和理由证明。
   已批准的 Story/AC 是业务交付合同。Task 可实施性反馈经 `generate-design` 细化实现机制、但未改变用户批准的交付结果时，保持 Delivery 原字节并走 packet-bound `Impact: NO_CHANGE` 发布；不得为实现机制创建 Story 或 AC。只有上游 Owner 经用户明确批准改变可独立验收的交付结果后，才按 `Impact: CHANGED` 重新评审 Story/AC。
4. 对每个 `IN_SCOPE` 生产上线 TECHNICAL Feature 优先拆成“上线准备”“发布切换”“生产验证与运维移交”三个结果型核心 Story；旧功能下线条件适用时单独生成 Story，不与发布切换合并。每个上线 Story 通常设置 `uatRelevant = false`，只有确实属于业务 UAT 分母且获得评审确认时才能设为 `true`。
5. 对每个 `IN_SCOPE` 数据迁移 TECHNICAL Feature 单独生成迁移 Story。迁移 Feature 和 Story 不得归入生产上线 Feature；发布切换只能把已完成的迁移结果写成前置条件或 AC，不能吞并迁移交付范围。
6. `POST_GO_LIVE_SUPPORT` 只能形成明确的合同边界、Assumption/Risk，或已经批准且可验收的具体交付工作；不得生成泛化“上线后支持”、驻场、待命容量或 24×7 支持 Story。若输入明确购买专职驻场、固定班次、待命容量或 24×7 支持，停止 Story 分解并返回 `generate-design`：由其登记 `affectsEstimate = true` 的 Uncertainty，转入独立服务容量模型或单独支持 SOW，在责任方带回获批容量估算或明确排除决定前保持 `BLOCKED`。UAT 缺陷责任、变更请求和支持边界写入 AC、Assumption/Risk 与责任边界，不生成开放式缺陷 Story。
7. 将其余差值拆成结果明确、可独立交付、验收和结算的 Story。Story 不保存类型；前端、后端、数据、集成、测试、迁移、调研等工作性质由后续 Task 表达。重要 Uncertainty 需要交付工作解决时创建具有明确问题和结论的 Story；否则形成带 trigger、handling 和 responsibility boundary 的 Assumption 或 Risk。带 `relatedBusinessFeatureIds` 的横切 TECHNICAL Feature 只有存在可独立验收、独立估算的共享边界或控制结果时才形成单独 Story；其 Story/AC 不得再次聚合相关 BUSINESS Story 已拥有的外部目标，也不得重述这些业务调用的字段映射、业务幂等、重试、异常处置或核对结果。提供方端到端结果由一个 BUSINESS Story 首次拥有，其他 Story 必须显式引用该 producing Story，不得复制能力。若无法证明独立的非重叠结果，返回 `generate-design` 并报告 `FEATURE_OVERLAP_SUSPECTED`，由其收敛 Feature/Scope。
8. 为每个 Story 编写有序 AC；每条 AC 是独立可观察、可通过或不通过的结果，不描述实现 Task。上线 AC 必须明确前置条件、成功判定、失败或回滚边界以及责任方；数据迁移 AC 与发布切换 AC 分开。
9. 把有证据支持的 Integration 作为顶级权威实体写入 `integrations`。每条 Integration 有唯一 `integrationId` 和非空 `name`，并明确 `storyId`、source、target、trigger、direction、purpose、owner 与交付边界。存在批准该边界、目标或类型化义务的 Design Decision 时，`decisionIds` 只引用其 `relatedFeatureIds` 包含当前 Story Feature 的决策；纯实现集成没有类型化 Design Decision 时允许空数组，但必须填写非空 `decisionRationale` 说明为何不需要类型化批准。每个 `requiredIntegrationBoundary` 非 `NONE` 的 Story 至少关联一条边界完全一致的 Integration；即使多个 Feature 复用同一适配能力，也不得只挂到共享使能 Story，必须分别表达各交付 Story 的可验收端口或端到端结果。反过来，共享 TECHNICAL Story 的 Integration 也不得把两个或更多相关 BUSINESS Story 已登记的 target 聚合为一个重复端到端边界；共享目标必须是一个独立的项目侧适配器或控制端口。Integration 不依赖 Story 类型，登记关系也不表示已经决定生成集成 Task；是否需要交付内部或外部系统对接工作由 `generate-task` 判断。
10. 把每个 Assumption 或 Risk 作为 `assumptions` 中的一条独立记录，相同语义只保留一行。需要表达不确定性的 Story 通过单个 `assumptionId` 选择一条足以说明该 Story 不确定性的记录；同一条记录可以被多个 Story 引用，不为每个 Story 复制同一假设。
11. 当前 Stage Agent 在 `.ai-sow/work/generate-story/delivery.candidate.json` 保存专业分解，再用确定性 renderer 整体生成 `.ai-sow/work/generate-story/review.candidate.md`；不得手写或局部修补投影。投影覆盖 Feature、Story、AC、Integration、Assumption/Risk、问卷消费和 `Concern -> Feature -> Story/Assumption/Risk`，并确认上线准备、发布切换、生产验证与运维移交、条件适用的下线、独立数据迁移、UAT 分母和支持边界无遗漏或重复：

   ```text
   "<python-bin>" "<skill-root>/scripts/render_review.py" --project-root . --candidate .ai-sow/work/generate-story/delivery.candidate.json --output .ai-sow/work/generate-story/review.candidate.md
   ```
12. 直接运行审批前机械闭环。`review` 生成 `risk-summary.md` 与 canonical `review-packet.json`，固定算法为 `ai-sow-owner-review-packet-v1`，并绑定 inputs、context manifest/fragments、candidate、review 与 risk summary。批准前不得写正式 review、Delivery 或 receipt：

   ```text
   "<python-bin>" "<skill-root>/scripts/validate.py" --project-root . --mode review --candidate .ai-sow/work/generate-story/delivery.candidate.json --review-path .ai-sow/work/generate-story/review.candidate.md
   ```
13. 为当前 packet 只创建一个不继承当前完整聊天的完整 fresh-context Reviewer。Reviewer 只读 packet、candidate、review、risk summary、评审模板和 packet 点名的 fragment；不运行机械校验、不修改成果、不代替用户批准。Reviewer 返回 finding 时，Stage 先确认 `delivery.candidate.json` 仍与 packet 绑定字节一致，把字段变更及 finding ID 写入 `patch.json`，再运行 Owner-local patch；不得直接编辑 candidate 或整段重写：

   ```text
   "<python-bin>" "<skill-root>/scripts/apply_patch.py" \
     --project-root "<project-root>" \
     --base .ai-sow/work/generate-story/delivery.candidate.json \
     --candidate .ai-sow/work/generate-story/delivery.candidate.json \
     --patch .ai-sow/work/generate-story/patch.json \
     --audit .ai-sow/work/generate-story/patch-audit.json
   ```

   `PATCH_FREEFORM_EDIT_DETECTED` 表示存在声明外变化；`PATCH_CLOSURE_UNSYNCED` 表示引用闭包尚未逐项修改或确认。只有脚本返回 `OK` 才整体重跑 renderer/`review` 并形成新 packet。修复后的 packet 由一个新的轻量 fresh-context Reviewer 做 diff-review；它只读取 `patch-audit.json`、影响闭包字段原文及新 packet 绑定，不加载完整上游或 round-1 历史。轻量 Reviewer 仍有 findings 时 `BLOCKED`，不创建第三个 Reviewer。`PASS` 后 Stage 只运行“精确 Reviewer 绑定”命令写 canonical work-only sidecar：

   ```json
   {"algorithm":"ai-sow-owner-reviewer-v1","decision":"PASS","owner":"generate-story","packetSha256":"<packet-sha256>"}
   ```
14. 向用户展示完整 review、risk summary、Reviewer 结果、packet path 与 SHA-256。用户必须明确批准 Owner `generate-story` 和该 hash，再写 canonical `approval.json`；任一 candidate、review、risk、context、input 或 packet 字节变化都会使 Reviewer 与用户批准失效：

   ```json
   {"algorithm":"ai-sow-owner-approval-v1","decision":"APPROVED","owner":"generate-story","packetSha256":"<packet-sha256>"}
   ```
15. 精确绑定有效后只运行 `publish-approved`。它在任何正式写入前复算全部 hash，把 work-only review 和 Delivery candidate 原字节发布到正式路径，并让 receipt `0.3` 最后写入；批准后不得再修改专业成果或调用 Reviewer：

   ```text
   "<python-bin>" "<skill-root>/scripts/validate.py" --project-root . --mode publish-approved --candidate .ai-sow/work/generate-story/delivery.candidate.json --review-path .ai-sow/work/generate-story/review.candidate.md
   ```
16. 直接上游 receipt 变化但专业结论不变时，review 记录 `Impact: NO_CHANGE`、发生变化的直接上游、旧/新 receipt hash 和点名全部稳定 ID 的影响理由。现有 `--mode rebind` 只保留为 reconciliation Adapter，必须携带 `--staging-root` 并证明稳定 Delivery 原字节不变；普通调用按同一 packet-bound 审批闭包形成原字节 candidate 后发布。
17. receipt 发布后报告完成，只推荐用户显式调用 `generate-task`，然后 STOP；不得自动启动下游 Skill。

## 完成条件

每个需要新增交付的范围内 Feature 至少关联一个 Story，每个 Story 至少有一条 AC；每条 AC 都说明相对 Effective Start 的差值并逐条承接相关 `CARRY_FORWARD` Commitment。`FULLY_COVERED` Feature 不制造 Story。横切 TECHNICAL Feature 若形成共享使能 Story，必须证明它与相关 BUSINESS Story 的提供方目标和端到端结果不重叠；范围内生产上线完整覆盖上线准备、发布切换、生产验证与运维移交，适用时单列旧功能下线；数据迁移使用独立 Feature 和 Story；上线 Story 的 UAT 分母、上线后支持边界及 UAT 缺陷/变更责任均有明确评审结论。每条有依据的 Integration 都作为独立记录关联一个 Story；每个 Assumption/Risk 只保存一次并用关系集合连接 Story。存在问卷时，每个 `APPROVED_DEFAULT` 都完整映射到一个稳定 Assumption 和至少一个 Story，且 `handling` 保留 Question ID 锚点；问卷本身仍是人类评审状态，不成为第七份稳定 JSON。Delivery 原字节发布并签发 receipt 后只推荐 `generate-task` 并停止。

## Reconciliation Adapter

仅当用户显式调用 `ai-sow:reconcile` 且提供 `Reconciliation Run ID`、整体 review SHA-256 与项目内
staging root 时，本 Skill 作为 Story Owner Adapter 运行。它继续独占 Story、AC、Integration、
Assumption、Risk、候选编译、`check/publish/rebind` 与写集合，但复用 reconciliation 的外层当前
Stage、一个 Reviewer 和一次 hash-bound 用户批准；确定性 Owner 命令由外层当前 Stage 直接调用。技术实现或 Task 细化未改变业务交付结果
时必须 `NO_CHANGE`，Delivery 原字节复用；只有整体 review 精确列出业务结果与 Story/AC diff，
并由同一次用户批准覆盖时才可 `CHANGED`。Owner 结果返回外层当前 Stage，本内部模式不在本阶段
STOP，也不调用 Task；普通独立调用保持原合同。

候选校验可在 `--mode check` 中用 `--review-path <project-relative-posix-path>` 读取本次 reconciliation
为 Story Owner 编译的 work-only review 投影；该路径同时作为 Story review 与上线映射诊断路径。
上游 Owner review 仍使用各自固定路径。`publish` 与 `rebind` 禁止 review override，必须回到固定
`REVIEW_PATH` 发布 Owner receipt。整体 review 本体只作为投影携带的批准 hash 绑定来源，不直接
传给 Owner-local `validate.py`。
