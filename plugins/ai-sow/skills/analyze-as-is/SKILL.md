---
name: analyze-as-is
description: 当 AI SOW 在方案设计前需要独立调查代码、集成、数据、配置、部署、证据、往期承诺或有效起点时使用。
---

# 分析现状

先形成证据完整、可独立批准的人类可读评审，再编译稳定 As-Is 数据。没有代码库或往期 SOW 是合法的 Greenfield 情况；仍须明确九个 Topic 的覆盖边界和未知项。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。中文用于结论、问卷、证据摘要和评审；合同 token 保持原值。
按[插件运行时环境合同](../../references/runtime-environment.md)从 `<plugin-root>` 解析当前平台的 `<python-bin>`；后续命令直接使用 setup 已建立的插件 `.venv`。

## 精确批准快速路径

若本次新 session 的用户指令已经明确批准 Owner `analyze-as-is` 和一个完整 packet SHA-256，本节优先于下方完整调查流程。从当前 turn 的 Available skills 条目直接取得本 `SKILL.md` 的绝对路径；不得使用 `rg`、`find` 或 `rg --files` 枚举或重新定位 Skill。Stage 不得手写 approval JSON，必须严格依次只运行以下两条确定性命令；第一条用 canonical bytes 写固定 `ai-sow-owner-approval-v1` sidecar，第二条执行唯一发布 preflight：

```text
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode write-approval \
  --packet-sha256 "<用户明确批准的完整 packet SHA-256>"
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode publish-approved \
  --candidate .ai-sow/work/analyze-as-is/asis.candidate.json \
  --review-path .ai-sow/work/analyze-as-is/review.candidate.md
```

`write-approval` 只校验 hash 格式并写固定 sidecar，不读取 packet 或专业成果；`publish-approved` 自己复算 packet、Reviewer、candidate、context、input、review、risk summary 与 approval 的全部绑定，是正式写入前唯一需要的 preflight。

此快速路径不得重新读取上游数据、证据、Schema、reference、candidate、packet 或 Reviewer 内容，不得枚举项目或插件文件，不得运行 `--help` 或除上述两条以外的其他命令，不得运行 `prepare_context.py`、`render_review.py`、独立 `check`，也不得创建 Reviewer 或修改专业成果。任一命令返回 `BLOCKED` 时原样报告 diagnostics 并停止；不得探索实现或退回完整调查。

## 精确 Reviewer 绑定

fresh-context Reviewer 只返回 `PASS` 或 findings，不写项目文件。Reviewer 对当前 packet 返回 `PASS` 后，当前 Stage 不得手写 reviewer JSON，必须立即运行下列唯一绑定命令；它只校验完整 hash 格式并以 canonical bytes 原子写入固定 `ai-sow-owner-reviewer-v1` sidecar，不读取 packet、candidate、上下文或证据：

```text
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode write-reviewer \
  --packet-sha256 "<Reviewer 已独立审查并 PASS 的完整 packet SHA-256>"
```

该命令只能消费实际 Reviewer 的 `PASS`，不能替代独立评审。命令返回 `BLOCKED` 时原样报告并停止；任何 packet 字节变化都必须重新创建 packet、交回 Reviewer 完整复审，再重新绑定。

## 路径与边界

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。项目根目录保持为当前工作目录，命令中的占位符使用解析后的绝对路径。

确定性脚本是本 Skill 的公开命令实现。Stage 与 Reviewer 不得复读 `scripts/*.py` 实现，也不得为预测 diagnostics 扫描源码；Stage 只按本 Skill 公布的命令执行并原样消费结构化 stdout。仅当脚本实际异常且公开 diagnostics 不足以定位执行故障时，才允许最小化读取直接报错位置。

开始专业工作前读取插件级[上下文纪律](../../references/context-discipline.md)、[降本评审合同](../../references/review-acceleration.md)与[模型路由](../../references/model-routing.md)。共享合同取代下文遗留的整体自由修复和携带完整历史复审做法；Owner、packet 与用户批准边界不变。

本 Skill 只写以下 owned artifacts：

- `.ai-sow/work/analyze-as-is/**`
- `.ai-sow/reviews/analyze-as-is.md`
- `.ai-sow/inputs/analyze-as-is/**`
- `.ai-sow/data/analyze-as-is/asis.json`
- `.ai-sow/validation/analyze-as-is.json`

不得修改 Requirement 稳定数据、评审或 receipt，不得修改其他 Owner Skill 的文件，也不得把源码、完整工具输出、凭据或本机绝对路径编译进稳定数据。

## Agent 角色

- **Stage Agent：** 在当前 session 内维护输入门禁、调查、candidate、Owner-local context、确定性命令、停止点和用户门禁；承担 As-Is 专业结论，但不批准自己的成果。
- **Reviewer Agent：** 使用 fresh context 独立检查专业完整性、证据边界、承诺处置、Coverage 和问卷消费，给出 `PASS` 或 findings；只读取 packet 点名的 candidate、review、risk summary、context fragments 和允许的项目相对 anchor，不继承当前完整聊天，也不修改成果。

Validator 是本 Skill 的确定性脚本，不再单独创建 Agent。Stage 原样报告它的 outcome、diagnostics、hash 和 receipt，不重解释结论，也不放宽失败。

## 输入门禁

Stage 在读取 Requirements 或开始调查前只运行以下确定性输入门禁；不得用 `check` 或 `review` 代替：

```text
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode upstream-check
```

`upstream-check` 不需要 As-Is candidate，也不写任何 work、review、data 或 validation 文件；它只验证当前 `analyze-requirement` handoff。下游只接受 `ai-sow-owner-v1`、validator contract `0.3` 和 Source Requirements Schema `:0.1`；只报告 `UPSTREAM_HANDOFF_MISSING`、`UPSTREAM_HANDOFF_INVALID`、`UPSTREAM_HANDOFF_STALE` 或 `UPSTREAM_CONTRACT_UNSUPPORTED`，不得重跑或复述 Requirement 的业务 diagnostics。

Requirement handoff 无效时立即停止，报告对应 Owner Skill 和项目相对 path，建议用户显式返回 `analyze-requirement`。

## Stage 调查

1. 读取 `.ai-sow/project.json` 的四个必填身份字段、可选 Owner 控制项和已发布 Requirements。询问可用的本地代码库、往期 SOW、配置、部署材料和其他证据；只登记用户提供或明确授权取得的输入。仓库与往期 SOW 都同时记录稳定 ID 和非空名称；仓库另存项目相对 path、revision 与 dirty，往期 SOW 复制到 `.ai-sow/inputs/analyze-as-is/prior-sows/` 并记录原文件名和 SHA-256。`repositorySnapshot.path` 只允许 `.` 或项目根下的相对子目录；代码库位于项目根之外时，把经授权的只读快照复制到项目子目录后登记，不能保存绝对路径、`..`、符号链接或 NTFS junction。依据证据确定 `GREENFIELD` 或 `BROWNFIELD`，不回写项目元数据。
2. 在深挖前先基于已发布 Requirements 形成一句话目标方案假设，并写 `.ai-sow/work/analyze-as-is/premises.json`：显式列出依赖前提、最小证伪方法、verdict、影响和按需激活的 `factFamilies`。逐条证伪；不做无目标的全仓穷举。
3. 按合同顺序评估 `SYSTEM_CONTEXT`、`CAPABILITY`、`APPLICATION`、`INTEGRATION`、`DATA`、`PLATFORM`、`SECURITY_COMPLIANCE`、`OPERATIONS_QUALITY`、`DELIVERY_CONSTRAINTS`。九项均不得沉默，每项 `status` 只取 `RELEVANT_INVESTIGATED / RELEVANT_INSUFFICIENT_EVIDENCE / BOUNDARY_DECLARED / NOT_APPLICABLE`：只有 `RELEVANT_INVESTIGATED` 深挖 Item、Evidence 与 anchor；`RELEVANT_INSUFFICIENT_EVIDENCE` 必须关联 `affectsEstimate=true` 的 Uncertainty；`BOUNDARY_DECLARED` 写清沿用前提与责任边界并关联 `affectsEstimate=false` 的 Uncertainty；`NOT_APPLICABLE` 只写证据支持的依据。
4. 对代码库先运行 `scripts/project_facts.py`，按 premises 激活的事实族生成 `.ai-sow/work/analyze-as-is/repo-facts.json`；数量、配置键、profile、部署资源、迁移表与 CI 名称只引用该确定性投影，不在多个摘要中手写。需要图查询时再读取[CodeGraph 参考](references/codegraph.md)，依次采用 MCP、已有 CLI、项目局部 CLI、已记录静态回退。生成代码、动态分派、配置、部署和运行边界必须由直接证据佐证，否则记录 Uncertainty。
5. 从每份往期 SOW 提取 Commitment，核对 `implementationStatus` 与 `treatment`。Commitment 的
   `sourceReference` 与 `PRIOR_SOW` Evidence 的 `reference` 固定使用
   `prior-sow:<priorSowId>#<anchor>`，例如 `prior-sow:prior-sow-phase-one#Profile!A12`；冒号后的
   ID 必须与已登记 `priorSowId` 完全一致，原材料内的 `!` 等定位符放在 `#` 后。只有当前 Item
   和 `EXPECTED_BEFORE_START` Commitment 可构成 Effective Start；`CARRY_FORWARD` 仍是待交付范围。
   Commitment 的状态与处置矩阵固定为：
   - `IMPLEMENTED` → `CURRENT_BASELINE`
   - `PARTIAL / NOT_IMPLEMENTED` → `EXPECTED_BEFORE_START / CARRY_FORWARD / NEEDS_DECISION`
   - `UNVERIFIED` → `NEEDS_DECISION`
   - `SUPERSEDED` → `EXCLUDE`
6. 为每个 BUSINESS Feature 建立一条 Coverage；无对应现状时使用 `MISSING`，不编造有效起点。
7. 默认不启动应用、数据库或容器。静态证据无法解决会实质影响设计的重要不确定性时，读取[运行时验证参考](references/runtime-verification.md)，说明原因后仅运行目标仓库已有的最小测试或只读探针。
8. 直接调查结束后仍有缺口时，读取[现状证据问卷](references/current-state-questionnaire.md)，只选择实际需要的问题并写入 `.ai-sow/work/analyze-as-is/questionnaire.md`。已确认回答可形成 `QUESTIONNAIRE` Evidence；`UNKNOWN` 或冲突回答形成 Uncertainty。Item、Commitment、Effective Start、Uncertainty 和 Evidence 都同时保存稳定 ID 与非空名称；每条 Uncertainty 必须明确 `affectsEstimate`。
9. 将完整专业结论先写入 `.ai-sow/work/analyze-as-is/asis.candidate.json`。它是 work-only candidate，不是稳定交接数据；批准前不写正式 review、稳定 As-Is 或 validation receipt。

`As-Is Item` 只记录调查截止日期已经存在或实际运行的事实。`Effective Start` 是 Design 与 Task 共用的项目起点基线；名称必须唯一，摘要必须具体点明项目开工时可以依赖的对象、能力和边界，并通过 `sourceItemIds`、`commitmentIds` 追溯事实或开工前承诺。本 Skill 不为 Effective Start 预判 Task 工作模式。

## 机械门禁输入合同

在生成评审前一次性自检全部候选：Item、Commitment、Effective Start、Uncertainty 与 Evidence 的显示名跨集合唯一；每条 Uncertainty 被同 Topic 的 `uncertaintyIds` 反向列出；`IMPLEMENTED` Commitment 至少关联一个 Item；Commitment 的每个 `relatedFeatureId` 都在对应 Coverage 的 `commitmentIds` 中，`NEEDS_DECISION` 与 `UNVERIFIED` 另有 Coverage→Uncertainty 决策链；Coverage 理由出现的 `commitment-*` 必须属于本行 `commitmentIds`。Evidence anchor 必须解析到单个文件，目录不构成证据。候选中的显式“几类/几项/几个/几份”枚举与同一 Evidence 的文件、节点、边数量必须内部一致；Effective Start 可见摘要使用名称和业务语言，不写 `asis-*`、`commitment-*` 等稳定 ID。

## 候选评审与发布

Stage 先确定性准备 Owner-local closure 并投影 review：

```text
"<python-bin>" "<skill-root>/scripts/prepare_context.py" \
  --project-root "<project-root>"
"<python-bin>" "<skill-root>/scripts/render_review.py" \
  --project-root "<project-root>"
```

`prepare_context.py` 只保存 Requirements receipt closure、九个 Topic、登记 repository/prior SOW 和 Evidence inventory/项目相对 anchor；源码、往期 SOW 正文、完整工具输出、凭据和本机绝对路径不进入 fragment。`render_review.py` 从同一 candidate 确定性生成 `.ai-sow/work/analyze-as-is/review.candidate.md`，完整投影调查范围、Topic、Item、Commitment、Effective Start、Coverage、Uncertainty、Evidence、问卷记录和稳定 ID。

随后生成 hash-bound packet：

```text
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode review \
  --candidate .ai-sow/work/analyze-as-is/asis.candidate.json \
  --review-path .ai-sow/work/analyze-as-is/review.candidate.md
```

脚本校验有效 Requirement handoff、As-Is Schema、Owner-local ID/关系、九个 Topic、登记输入、Evidence anchor、问卷消费和 review 机械合同，再写 work-only `risk-summary.md` 与 canonical `review-packet.json`。packet 算法固定为 `ai-sow-owner-review-packet-v1`，绑定 named inputs、candidate、context manifest/fragments、review、risk summary 及其 SHA-256；返回 `REVIEW_REQUIRED`。此步骤不写正式 data、review 或 validation report。

当前 packet 只创建一个完整 fresh-context Reviewer。Reviewer 对照登记输入、Evidence anchor、问卷、Schema 和[评审模板](references/review-template.md)完整审查当前 packet，并采用模板中的 finding 严重度下限。`PASS` 时 Stage 只运行“精确 Reviewer 绑定”命令写 canonical `.ai-sow/work/analyze-as-is/reviewer.json`，使用 `ai-sow-owner-reviewer-v1` 并绑定精确 packet SHA-256。

Reviewer 返回 findings 时，Stage 先确认 `asis.candidate.json` 仍与 packet 绑定字节一致，把字段变更及 finding ID 写入 `patch.json`，再运行 Owner-local patch；不得直接编辑 candidate 或整段重写：

```text
"<python-bin>" "<skill-root>/scripts/apply_patch.py" \
  --project-root "<project-root>" \
  --base .ai-sow/work/analyze-as-is/asis.candidate.json \
  --candidate .ai-sow/work/analyze-as-is/asis.candidate.json \
  --patch .ai-sow/work/analyze-as-is/patch.json \
  --audit .ai-sow/work/analyze-as-is/patch-audit.json
```

`PATCH_FREEFORM_EDIT_DETECTED` 表示存在声明外变化；`PATCH_CLOSURE_UNSYNCED` 表示引用闭包尚未逐项修改或确认。只有脚本返回 `OK` 才重新生成 context、review、risk summary 与 packet。修复后的 packet 由一个新的轻量 fresh-context Reviewer 做 diff-review；它只读取 `patch-audit.json`、影响闭包字段原文及新 packet 绑定，不加载仓库、完整证据或 round-1 历史。轻量 Reviewer 仍有 findings 时返回 `BLOCKED`，不创建第三个 Reviewer，也不写 Reviewer sidecar 或任何正式路径。

Reviewer `PASS` 后，Stage 向用户展示 Owner、packet path、精确 SHA-256、risk summary 和正式目标路径。只有用户明确批准该精确 packet，才写 canonical `.ai-sow/work/analyze-as-is/approval.json`，使用 `ai-sow-owner-approval-v1` 并绑定相同 packet SHA-256，然后只运行：

```text
"<python-bin>" "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode publish-approved \
  --candidate .ai-sow/work/analyze-as-is/asis.candidate.json \
  --review-path .ai-sow/work/analyze-as-is/review.candidate.md
```

`publish-approved` 重新计算并核对所有 hash、packet、Reviewer 与 approval sidecar；任一 input、candidate、review、risk summary、context 或 sidecar 漂移都在正式写入前阻塞。通过后把 review candidate 原字节发布为 `.ai-sow/reviews/analyze-as-is.md`，把 candidate 原字节发布为 `.ai-sow/data/analyze-as-is/asis.json`，最后发布 `.ai-sow/validation/analyze-as-is.json` 的 validator contract `0.3` receipt。receipt 继续绑定 project、Requirement validation/output、repository snapshot、prior SOW、可解析 Evidence anchor、questionnaire presence、当前 review 和稳定输出。批准后不再修改专业结论，也不再次创建 Reviewer。

## 普通上游影响复核

Requirement receipt/output 更新时，普通调用始终重新执行完整 candidate-first review、
Reviewer 绑定、精确 packet 批准和 `publish-approved`。专业结论无需变化时，Stage 在
work-only review 记录新旧 receipt hash、理由、稳定 ID 和 `Impact: NO_CHANGE`，并形成
与稳定 As-Is 原字节相同的 candidate；发布器复用输出并最后更新 receipt。
repository、prior SOW、Evidence anchor 或问卷输入变化也必须由 Reviewer 判断影响，
普通调用不使用 legacy `publish/rebind`。

## 完成与停止

receipt 发布后，Stage 报告稳定 As-Is 与 validation 的项目相对路径，推荐用户显式调用 `generate-design` 并说明其所需输入，然后立即停止。不得自动调用下一 Skill。

## Reconciliation Adapter

仅当用户显式调用 `ai-sow:reconcile` 且提供 `Reconciliation Run ID`、整体 review SHA-256 与项目内
staging root 时，本 Skill 作为 As-Is Owner Adapter 运行。它继续独占现状调查语义、证据引用、
候选编译、legacy `check/publish/rebind` 与写集合，但复用外层当前 Stage、一个 Reviewer 和一次 hash-bound 用户批准；
确定性 Owner 命令由外层 Stage 直接调用。修正证据、问卷、repository 或 prior SOW 必须在 baseline
前已存在于正式项目；不得把 staged-only input 绑定进 receipt。Owner 结果只返回外层当前 Stage，
本内部模式不在本阶段 STOP，也不调用下游。候选机械检查可用
`--review-path <project-relative-posix-path>` 读取 `.ai-sow/work/analyze-as-is/` 下的 work-only Owner
review；该 override 仅允许 `--mode check`，不传时仍读取正式
`.ai-sow/reviews/analyze-as-is.md`。`publish/rebind` 禁止 review override，继续只绑定正式 review，
且只能携带 `--staging-root` 写入 reconciliation staging view。
