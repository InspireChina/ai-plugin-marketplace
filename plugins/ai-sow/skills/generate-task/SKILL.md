---
name: generate-task
description: 当已评审的交付 Story 需要按权威模板的基础单元目录拆成可独立估算、验收和结算的 Task，并判断工作模式、复杂度、现状依据或 Integration 引用时使用。
---

# 生成原子 Task

把每个 Story 拆成一组基础单元实例；一条 Task 包含该实例必要的设计、实现、开发自测、单元验证和基本联调，不拆成固定活动流水线。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。该链接固定解析为 `<plugin-root>/references/output-language.md`，绝不位于 `<plugin-root>/skills/references/`。Task 名称和理由使用简体中文；模板枚举保持原值。
按[插件运行时环境合同](../../references/runtime-environment.md)从 `<plugin-root>` 解析当前平台的 `<python-bin>`；后续命令直接使用 setup 已建立的插件 `.venv`。

## 精确批准快速路径

若本次新 session 的用户指令已经明确批准 Owner `generate-task` 和一个完整 packet SHA-256，本节优先于下方完整估算拆分流程。从当前 turn 的 Available skills 条目直接取得本 `SKILL.md` 的绝对路径；不得使用 `rg`、`find` 或 `rg --files` 枚举或重新定位 Skill。Stage 不得手写 approval JSON，必须严格依次只运行以下两条确定性命令；第一条用 canonical bytes 写固定 `ai-sow-owner-approval-v1` sidecar，第二条执行唯一发布 preflight：

```text
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode write-approval \
  --packet-sha256 "<用户明确批准的完整 packet SHA-256>"
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode publish-approved \
  --candidate .ai-sow/work/generate-task/estimate.candidate.json \
  --review-path .ai-sow/work/generate-task/review.candidate.md
```

`write-approval` 只校验 hash 格式并写固定 sidecar，不读取 packet 或专业成果；`publish-approved` 自己复算 packet、Reviewer、candidate、context、input、review、risk summary 与 approval 的全部绑定，是正式写入前唯一需要的 preflight。

此快速路径不得重新读取上游数据、模板目录、Schema、reference、candidate、packet 或 Reviewer 内容，不得枚举项目或插件文件，不得运行 `--help` 或除上述两条以外的其他命令，不得运行 `prepare_context.py`、`render_review.py`、独立 `check`，也不得创建 Reviewer 或修改专业成果。任一命令返回 `BLOCKED` 时原样报告 diagnostics 并停止；不得探索实现或退回完整估算拆分。

## 精确 Reviewer 绑定

fresh-context Reviewer 只返回 `PASS` 或 findings，不写项目文件。Reviewer 对当前 packet 返回 `PASS` 后，当前 Stage 不得手写 reviewer JSON，必须立即运行下列唯一绑定命令；它只校验完整 hash 格式并以 canonical bytes 原子写入固定 `ai-sow-owner-reviewer-v1` sidecar，不读取 packet、candidate、上下文、模板或上游数据：

```text
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode write-reviewer \
  --packet-sha256 "<Reviewer 已独立审查并 PASS 的完整 packet SHA-256>"
```

该命令只能消费实际 Reviewer 的 `PASS`，不能替代独立评审。命令返回 `BLOCKED` 时原样报告并停止；任何 packet 字节变化都必须重新创建 packet、交回 Reviewer 完整复审，再重新绑定。

## 路径

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。保持项目根目录为当前工作目录，并在执行前把命令中的路径占位符替换为绝对路径。

确定性脚本是本 Skill 的公开命令实现。Stage 与 Reviewer 不得复读 `scripts/*.py` 实现，也不得为预测 diagnostics 扫描源码；Stage 只按本 Skill 公布的命令执行并原样消费结构化 stdout。仅当脚本实际异常且公开 diagnostics 不足以定位执行故障时，才允许最小化读取直接报错位置。

## 工作流

1. 当前 Stage Agent 是本 Skill 的唯一用户接口、专业执行者和工具派发者，不再创建独立 Worker 或机械校验角色。先运行 Owner-local context compiler；它用公共 matcher 验证 As-Is、Design 和 Story 三个 receipt，并只投影 Task 拆分必需的引用闭包。任一 handoff 为 missing、invalid、stale 或 unsupported 时，报告对应 Owner Skill 并停止。不得调用上游 validator，不得重新执行 HLD/Go-live 门禁，也不得重新诊断 Story 或 Design 的内部业务质量：

   ```text
   "<python-bin>" "<skill-root>/scripts/prepare_context.py" --project-root .
   ```
2. 当前 Stage Agent 先读取 `.ai-sow/work/generate-task/context/manifest.json`，再用一个工具回合把 manifest 点名的五个 fragment 各读取且只读取一次；不得预先加载完整上游 artifact，也不得在随后回合用 `jq`、`sed` 或其他命令重新筛选、摘要或复读这些 fragment。closure 成功后从固定路径 `<skill-root>/contracts/estimate.schema.json` 读取 Schema 一次，并读取[评审模板](references/review-template.md)。路径映射是确定的：若 `SKILL.md` 位于 `<plugin-root>/skills/generate-task/SKILL.md`，Schema 就位于 `<plugin-root>/skills/generate-task/contracts/estimate.schema.json`，绝不位于 `<plugin-root>/contracts/`。不得用 `ls`、glob、`rg` 或目录枚举寻找 Schema，也不得使用 `find` 或读取 test 代替合同。
3. context compiler 已用权威项目模板和同一模板读取器生成 `template-catalog.json`；它是普通运行中唯一需要读取的模板目录投影，包含 37 项基础单元、13 个任务族、计数口径、包含/排除边界、可用工作模式和 S/M/L/X 规则。普通 candidate 流程不得运行 `read_template.py`，不得再次读取项目 XLSX，也不得读取 Skill-local `fixtures/sow-template.xlsx`；fixture 只属于构建和测试。基础人天、倍率、公式、SIT、UAT、风险和取整值不进入 context、Python 或稳定 JSON。
4. 按计数口径识别实例，一实例一行。每个 Story 至少一条 Task；AC 与 Task 在同一 Story 内是多对多关系：每条 AC 至少由一个 Task 覆盖，多个不同基础单元 Task 可以共同满足同一 AC，一条 Task 也可以支持多条 AC。重复实例分行，不保存 `quantity`，也不保存 `professionalDomain`、`activity`、基础人天、倍率、Task 人天或 `sitEstimates`。不得为了适配 Task 计数口径反向拆分或改写已批准 Story/AC。
5. 工作模式只允许 `新建 / 调整 / 接入复用`。调整和接入复用必须以 `workModeEvidence` 点名一个 `matchedEffectiveStartItemIds` 中的 Effective Start，名称与上游记录完全一致，并在 Task 名称或理由中出现。只有该 Effective Start 的名称或摘要明确点名当前基础单元可调整的既有资产时才选择 `调整`；一般治理、平台、交付或运行边界本身不等于既有迁移方案、切换方案或测试资产，此时为新实例选择 `新建`，但按第 6 步继续引用受作用的 Effective Start。例如，复用既有 CI/CD 执行本项目的新切换仍是 `新建` 的发布切换；只有修改已存在的本项目切换方案或切换清单才是 `调整`。接入复用必须按 Schema 枚举顺序形成可独立估算的 `projectSideWorkTypes` 和 `projectSideWorkCommitment`，并令 `workModeRationale = "<effectiveStartItemName>保持不变；<projectSideWorkCommitment>。"` 精确成立；普通依赖引入或常规调用不单独生成 Task。
6. “替换”和“退役”不是工作模式。替换按替代能力、独立数据迁移、一个发布切换实例及系统功能下线拆分；新建的数据迁移、系统功能下线、同一根因问题整改，以及涉及现有运行能力的发布切换，也必须引用所作用的 Effective Start。
7. 按当前基础单元自己的标准选择 `S / M / L`。S/L 的 `complexityRationale` 写出实例偏离 M 的具体事实；M 不保存该字段。命中 X 时继续拆分、澄清，或先生成专题调研/架构方案设计 Task，不能进入正式 Estimate。
8. 每个顶级 Integration 恰好由一个内部或外部系统对接 Task 实现。Task 的 Story、Integration owner 和基础单元必须一致；非集成 Task 不得填写 `integrationId`。缺少登记时返回 `generate-story` 或 `generate-design`，不得临时编造。
9. 每个 Story 最多一个“发布切换”Task；数据迁移单列。“问题诊断与恢复”与“同一根因问题整改”不得为同一 Story 重复计算诊断。只有已批准范围明确要求时才生成用户培训；不得生成泛化上线后支持、待命或容量 Task。
10. 当前 Stage Agent 在 `.ai-sow/work/generate-task/` 形成 `estimate.candidate.json`，再调用确定性 renderer 从该 candidate 与项目模板哈希生成 `review.candidate.md`。不得手写或局部修补 review 投影；candidate 变化后必须整体重跑 renderer。投影覆盖 Story→Task、AC 多对多完整覆盖、基础单元、工作模式、复杂度、现状依据、Integration 一对一、Task 计价遗漏/重复/排除理由和实际使用的估算前提。多个 Task 引用同一 AC 是业务追溯，不等于基础单元重复计价。批准前不得改写正式 `.ai-sow/reviews/generate-task.md`、Estimate 或 receipt：

   ```text
   "<python-bin>" "<skill-root>/scripts/render_review.py" --project-root . --candidate .ai-sow/work/generate-task/estimate.candidate.json --output .ai-sow/work/generate-task/review.candidate.md
   ```
11. 对候选与评审运行审批前闭环。`review` 模式执行全部确定性门禁，生成 `risk-summary.md` 和 canonical `review-packet.json`；packet 精确绑定 context manifest 与五个 evidence fragment。上游 handoff、input、context 或模板错误必须原样报告并停止。若首次 `review` 只返回当前 Task candidate 可修复的机械 diagnostics，机械门禁只允许一次整体修正：当前 Stage 仅使用公开 diagnostics、已读取的 Schema/context/模板目录整体复核全部 Task，重跑 renderer 和 `review`；不得读取 validator 源码、fixture 或完整上游。第二次仍为 `BLOCKED` 则原样报告并停止。该机械修正在 Reviewer 创建之前完成，不占用第 12 步的一次专业 finding 修复额度。work-only `review.candidate.md` 中的 `Reviewer: PASS` 与 `User Approval: APPROVED` 是拟发布的最终声明，在 `reviewer.json` 和 `approval.json` 精确绑定当前 packet 前没有授权效力：

   packet 的固定算法 token 为 `ai-sow-owner-review-packet-v1`；它属于 Owner-local 审批合同，不进入公共 runtime。

   ```text
   "<python-bin>" "<skill-root>/scripts/validate.py" --project-root . --mode review --candidate .ai-sow/work/generate-task/estimate.candidate.json --review-path .ai-sow/work/generate-task/review.candidate.md
   ```
12. 只创建一个 Reviewer Agent，并使用不继承当前完整聊天的新上下文。Reviewer 只读取 `review-packet.json`、candidate、review、risk summary、[评审模板](references/review-template.md)和 packet 点名的证据 fragment；不读取 canonical fixture 或完整上游 artifact，不运行机械校验，不修改成果。Reviewer 返回有限 findings 或 `PASS`。finding 允许当前 Stage Agent 完成一次整体修复；整体修复必须对全部新增或变化的 Task 重新核对基础单元计数边界、工作模式、复杂度、现状依据、Integration 和非重复计价，而不是只改 finding 点名的字段。随后整体重跑 renderer 与 `review`，并交回同一 Reviewer 完整复审；第二次仍不通过时 `BLOCKED`。Reviewer `PASS` 后 Stage 只运行“精确 Reviewer 绑定”命令，把下列对象按递归 key 排序、紧凑分隔符和一个结尾换行写入 work-only `reviewer.json`：

   ```json
   {"algorithm":"ai-sow-owner-reviewer-v1","decision":"PASS","owner":"generate-task","packetSha256":"<packet-sha256>"}
   ```
13. 当前 Stage Agent 向用户展示 review、risk summary、Reviewer 结果、packet path 与 packet SHA-256。用户必须明确批准 Owner `generate-task` 与该 hash；随后把下列 canonical 对象写入 work-only `approval.json`。任何 candidate、review、risk summary、input 或 packet 字节变化都使 Reviewer 与用户绑定失效，必须生成新 packet 并重新审查、批准：

   ```json
   {"algorithm":"ai-sow-owner-approval-v1","decision":"APPROVED","owner":"generate-task","packetSha256":"<packet-sha256>"}
   ```
14. Reviewer 与用户绑定均有效后运行精确发布。`publish-approved` 在任何正式写入前复算全部 hash，只把 work-only review 与 candidate 原字节发布到正式路径，并让 receipt 最后写入；批准后不得再修改专业成果或调用 Reviewer：

   ```text
   "<python-bin>" "<skill-root>/scripts/validate.py" --project-root . --mode publish-approved --candidate .ai-sow/work/generate-task/estimate.candidate.json --review-path .ai-sow/work/generate-task/review.candidate.md
   ```
15. 直接上游 receipt 变化但专业结论不变时，work-only review 记录
    `Impact: NO_CHANGE`、变化的直接上游、旧/新 receipt hash 和点名全部 Task ID 的
    影响理由，但仍使用完整 candidate-first packet 与 `publish-approved`；Estimate candidate
    可与稳定输出原字节相同。Legacy `--mode rebind` 只作为 Reconciliation Adapter，必须携带
    `--staging-root` 并证明 Estimate 稳定原字节不变。
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
