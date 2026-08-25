---
name: generate-task
description: 当已评审的交付 Story 需要按权威模板的基础单元目录拆成可独立估算、验收和结算的 Task，并判断工作模式、复杂度、现状依据或 Integration 引用时使用。
---

# 生成原子 Task

把每个 Story 拆成一组基础单元实例；一条 Task 包含该实例必要的设计、实现、开发自测、单元验证和基本联调，不拆成固定活动流水线。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。Task 名称和理由使用简体中文；模板枚举保持原值。

## 路径

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。保持项目根目录为当前工作目录，并在执行前把命令中的路径占位符替换为绝对路径。

## 工作流

1. 当前 Stage Agent 是本 Skill 的唯一用户接口、专业执行者和工具派发者，不再创建独立 Worker 或机械校验角色。先运行 Owner-local context compiler；它用公共 matcher 验证 As-Is、Design 和 Story 三个 receipt，并只投影 Task 拆分必需的引用闭包。任一 handoff 为 missing、invalid、stale 或 unsupported 时，报告对应 Owner Skill 并停止。不得调用上游 validator，不得重新执行 HLD/Go-live 门禁，也不得重新诊断 Story 或 Design 的内部业务质量：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/prepare_context.py" --project-root .
   ```
2. 当前 Stage Agent 先读取 `.ai-sow/work/generate-task/context/manifest.json`，再按稳定 ID 读取其中点名的 fragment；不得预先加载完整上游 artifact。另读取本 Skill 的 Schema、[评审模板](references/review-template.md)和 Skill-local `fixtures/sow-template.xlsx`。canonical fixture 只在合同歧义时按需读取，不作为每次运行的默认上下文。Skill-local 模板仅用于理解合同和测试；项目实际拆分只读取 `.ai-sow/templates/sow-template.xlsx`，运行时不得跨 Skill 读取 setup asset。
3. context compiler 已调用同一模板读取器。它只返回 37 项基础单元、13 个任务族、计数口径、包含/排除边界、可用工作模式和 S/M/L/X 规则；需要单独复读时运行下列命令。基础人天、倍率、公式、SIT、UAT、风险和取整值不进入 Python 或稳定 JSON：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/read_template.py" --project-root .
   ```
4. 按计数口径识别实例，一实例一行。每个 Story 至少一条 Task；AC 与 Task 在同一 Story 内是多对多关系：每条 AC 至少由一个 Task 覆盖，多个不同基础单元 Task 可以共同满足同一 AC，一条 Task 也可以支持多条 AC。重复实例分行，不保存 `quantity`，也不保存 `professionalDomain`、`activity`、基础人天、倍率、Task 人天或 `sitEstimates`。不得为了适配 Task 计数口径反向拆分或改写已批准 Story/AC。
5. 工作模式只允许 `新建 / 调整 / 接入复用`。调整和接入复用必须以 `workModeEvidence` 点名一个 `matchedEffectiveStartItemIds` 中的 Effective Start，名称与上游记录完全一致，并在 Task 名称或理由中出现。接入复用必须按枚举顺序形成可独立估算的项目侧工作类型和 `projectSideWorkCommitment`；普通依赖引入或常规调用不单独生成 Task。
6. “替换”和“退役”不是工作模式。替换按替代能力、独立数据迁移、一个发布切换实例及系统功能下线拆分；新建的数据迁移、系统功能下线、同一根因问题整改，以及涉及现有运行能力的发布切换，也必须引用所作用的 Effective Start。
7. 按当前基础单元自己的标准选择 `S / M / L`。S/L 的 `complexityRationale` 写出实例偏离 M 的具体事实；M 不保存该字段。命中 X 时继续拆分、澄清，或先生成专题调研/架构方案设计 Task，不能进入正式 Estimate。
8. 每个顶级 Integration 恰好由一个内部或外部系统对接 Task 实现。Task 的 Story、Integration owner 和基础单元必须一致；非集成 Task 不得填写 `integrationId`。缺少登记时返回 `generate-story` 或 `generate-design`，不得临时编造。
9. 每个 Story 最多一个“发布切换”Task；数据迁移单列。“问题诊断与恢复”与“同一根因问题整改”不得为同一 Story 重复计算诊断。只有已批准范围明确要求时才生成用户培训；不得生成泛化上线后支持、待命或容量 Task。
10. 当前 Stage Agent 在 `.ai-sow/work/generate-task/` 形成 `estimate.candidate.json`，再调用确定性 renderer 从该 candidate 与项目模板哈希生成 `review.candidate.md`。不得手写或局部修补 review 投影；candidate 变化后必须整体重跑 renderer。投影覆盖 Story→Task、AC 多对多完整覆盖、基础单元、工作模式、复杂度、现状依据、Integration 一对一、Task 计价遗漏/重复/排除理由和实际使用的估算前提。多个 Task 引用同一 AC 是业务追溯，不等于基础单元重复计价。批准前不得改写正式 `.ai-sow/reviews/generate-task.md`、Estimate 或 receipt：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/render_review.py" --project-root . --candidate .ai-sow/work/generate-task/estimate.candidate.json --output .ai-sow/work/generate-task/review.candidate.md
   ```
11. 对候选与评审运行审批前闭环。`review` 模式执行全部确定性门禁，生成 `risk-summary.md` 和 canonical `review-packet.json`；packet 精确绑定 context manifest 与五个 evidence fragment。work-only `review.candidate.md` 中的 `Reviewer: PASS` 与 `User Approval: APPROVED` 是拟发布的最终声明，在 `reviewer.json` 和 `approval.json` 精确绑定当前 packet 前没有授权效力：

   packet 的固定算法 token 为 `ai-sow-owner-review-packet-v1`；它属于 Owner-local 审批合同，不进入公共 runtime。

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" --project-root . --mode review --candidate .ai-sow/work/generate-task/estimate.candidate.json --review-path .ai-sow/work/generate-task/review.candidate.md
   ```
12. 只创建一个 Reviewer Agent，并使用不继承当前完整聊天的新上下文。Reviewer 只读取 `review-packet.json`、candidate、review、risk summary、[评审模板](references/review-template.md)和 packet 点名的证据 fragment；不读取 canonical fixture 或完整上游 artifact，不运行机械校验，不修改成果。Reviewer 返回有限 findings 或 `PASS`。finding 允许当前 Stage Agent 完成一次整体修复；整体修复必须对全部新增或变化的 Task 重新核对基础单元计数边界、工作模式、复杂度、现状依据、Integration 和非重复计价，而不是只改 finding 点名的字段。随后整体重跑 renderer 与 `review`，并交回同一 Reviewer 完整复审；第二次仍不通过时 `BLOCKED`。Reviewer `PASS` 后把下列对象按递归 key 排序、紧凑分隔符和一个结尾换行写入 work-only `reviewer.json`：

   ```json
   {"algorithm":"ai-sow-owner-reviewer-v1","decision":"PASS","owner":"generate-task","packetSha256":"<packet-sha256>"}
   ```
13. 当前 Stage Agent 向用户展示 review、risk summary、Reviewer 结果、packet path 与 packet SHA-256。用户必须明确批准 Owner `generate-task` 与该 hash；随后把下列 canonical 对象写入 work-only `approval.json`。任何 candidate、review、risk summary、input 或 packet 字节变化都使 Reviewer 与用户绑定失效，必须生成新 packet 并重新审查、批准：

   ```json
   {"algorithm":"ai-sow-owner-approval-v1","decision":"APPROVED","owner":"generate-task","packetSha256":"<packet-sha256>"}
   ```
14. Reviewer 与用户绑定均有效后运行精确发布。`publish-approved` 在任何正式写入前复算全部 hash，只把 work-only review 与 candidate 原字节发布到正式路径，并让 receipt 最后写入；批准后不得再修改专业成果或调用 Reviewer：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" --project-root . --mode publish-approved --candidate .ai-sow/work/generate-task/estimate.candidate.json --review-path .ai-sow/work/generate-task/review.candidate.md
   ```
15. 直接上游 receipt 变化但专业结论不变时，review 记录 `Impact: NO_CHANGE`、变化的直接上游、旧/新 receipt hash 和点名全部 Task ID 的影响理由；同一 Reviewer PASS 且用户确认后运行 `--mode rebind`。rebind 必须证明 Estimate 稳定原字节不变。纵向试点暂保留既有 rebind Adapter；推广阶段再让普通 rebind 使用相同 packet-bound approval。
16. receipt 发布后报告完成，只推荐用户显式调用 `generate-sow`，并提示在生成前完成模板参数校准、项目元数据、合同、商业条款等 PM 补充项，然后 STOP；不得自动启动下游 Skill。

## 完成条件

每个 Story 至少有一条 Task，每条 AC 至少由一个同 Story Task 覆盖；AC 与 Task 允许多对多追溯，Task 拆分不得反向修改 Story/AC。每条 Task 只对应一个模板允许的基础单元实例与工作模式。调整/接入复用、需要作用于现状的新建工作、复杂度偏离、Integration 一对一、发布切换、迁移及诊断/整改边界均有可追溯证据。稳定 Estimate 不保存任何计算结果；项目模板仍是基础人天、倍率、公式、SIT、UAT、风险和取整的唯一权威。Estimate 原字节发布并签发 receipt 后只推荐 `generate-sow` 与 PM 补充项并停止。

## Reconciliation Adapter

仅当用户显式调用 `ai-sow:reconcile` 且提供 `Reconciliation Run ID`、整体 review SHA-256 与项目内
staging root 时，本 Skill 作为 Task Owner Adapter 运行。它继续独占 Estimate、模板计数口径、
Task/AC 多对多覆盖、工作模式、复杂度、候选编译、`check/publish/rebind` 与写集合，但复用
reconciliation 的单一当前 Stage Agent、一个 Reviewer 和一次 hash-bound 用户批准；确定性命令由
外层当前 Stage Agent 直接调用。任何 Delivery、Story 或 AC 写入都属于 Owner 越权并阻塞整批；
Task 只能满足已批准业务合同。Owner 结果返回外层当前 Stage Agent，本内部模式不在本阶段 STOP，
也不调用 generate-sow。批准后，外层当前 Stage Agent 可在
`check` 中通过 `--review-path <project-relative-posix-path>` 校验为 Task Owner 编译的 work-only review
投影；该参数默认仍为 `.ai-sow/reviews/generate-task.md`，非默认路径不得用于 `publish` 或 `rebind`。
整体 review 本体只作为投影携带的批准 hash 绑定来源，不直接传给 Owner validator。普通独立调用
保持原合同。
