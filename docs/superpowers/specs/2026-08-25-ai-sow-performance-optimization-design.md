# AI SOW 性能优化设计修正

状态：用户于 2026-08-25 确认本方向；`generate-task` 自动化纵向试点、流程隔离 Agent A/B、两次
自然专业拆分发布与预埋遗漏检出均已通过，candidate-first 生命周期已经推广到五个专业 Owner。
五个 Owner 的 Owner-local closure/renderer、hash-bound packet、一个 fresh-context Reviewer、精确
批准和原字节发布均已有聚焦合同测试；setup 与 generate-sow 已改为当前 Stage 直接调用确定性
Module，reconcile 也已把 Owner staged pass、package、redo/diff/risk 和完整 packet 移到批准前，
contract `0.2` publisher 在批准后只执行 hash/check/publish。E2E 认证仍按硬停止点延后。

适用目标版本：`0.1.0-beta.2`

本修正建立在以下已批准设计之上：

- [Owner Contract Handoff 简化设计](2026-08-24-ai-sow-owner-contract-handoff-simplification-design.md)；
- [影响集整体协调设计修正](2026-08-25-ai-sow-impact-set-reconciliation-amendment.md)；
- [generate-task 性能 A/B 记录](2026-08-25-ai-sow-generate-task-performance-ab.md)。

推广完成后，本修正取代其中关于四 Agent 角色、批准后编译 candidate、批准后编译忠实度复审、
独立 Validator Agent、Reviewer 无界循环和批准后 reconciliation staging/package 构建的条款。
唯一 Owner、六份稳定 JSON、receipt-only handoff、HLD/Go-live 所有权、Excel 模板计算权威、
flat staging、固定前向顺序和 fail-closed 发布语义保持不变。

## 1. 问题与目标

当前 Owner 主线把一次专业工作拆成 Orchestrator、Worker、Reviewer 和 Validator 四种 Agent 角色。
用户批准前先审阅 Markdown，批准后再由 Worker 编译 JSON、Validator 运行脚本、Reviewer 核对编译
忠实度。该顺序导致同一 Skill 合同、上游 artifact 和评审材料被多个 Agent 重复读取；批准后的
candidate 修复还可能重新进入 Worker、Validator 与 Reviewer 循环。

`reconcile` 已把多个 Owner 收敛到一个 session，但仍在批准后编译全部 candidate、执行完整
staging pass、生成 package 和构造 redo manifest。批准没有绑定最终可发布的完整字节闭包。

本修正的目标是：

1. 每个专业 Owner 只保留当前 Stage Agent 和一个独立 Reviewer Agent；
2. 删除独立 Validator Agent，确定性脚本直接由当前 Stage Agent 调用；
3. candidate、机械校验、结构化预览、风险摘要和语义审查全部发生在用户批准前；
4. 用户批准绑定精确 review packet，批准后不再发生专业推理、candidate 修改或 Reviewer 调用；
5. 使用 Owner-local 引用闭包代替跨角色重复加载完整上游 artifact；
6. 不弱化现有 schema、业务断言、receipt、staging、hash 和发布门禁；
7. 先在 `generate-task` 做纵向试点，用同一 fixture 比较质量、token 和耗时，再决定推广。

## 2. 外部 Module 与 Interface

每个 Owner Skill 仍是独立 Module，外部 Interface 收敛为四种结果：

```text
NEEDS_INPUT
REVIEW_REQUIRED(packetPath, packetSha256)
PUBLISHED
BLOCKED
```

普通调用分为两个用户可见阶段：

```text
准备并审查
  -> NEEDS_INPUT | REVIEW_REQUIRED | BLOCKED

批准精确 packet
  -> PUBLISHED | BLOCKED
```

`REVIEW_REQUIRED` 必须指向已经通过 Owner-local 确定性校验和独立语义审查的精确 packet。
用户批准后，当前 Stage Agent 只验证批准值并派发 publish/rebind 命令。Skill-only 交互仍需要一个
模型 turn 接收用户批准，因此本设计承诺的是“批准后零专业推理、零叶子 Agent、零 artifact 修订”，
而不是字面意义上的零模型调用。

当新 session 已携带 Owner 与完整 packet SHA-256 的精确批准时，五个 Owner 使用显式快速路径：
依次调用 Owner-local `write-approval` 与一次 `publish-approved`。前者只校验 Owner、固定 work-only
路径和用户提供的 64 位小写 packet SHA-256，再确定性写 canonical approval sidecar；后者是 packet、
Reviewer、candidate、context、input、review、risk summary 与 approval 的唯一发布前总复核。Stage 不得
手写 approval JSON，也不再枚举项目、预读这些 artifact、运行 `--help`/closure/renderer/独立 `check`
或重新进入专业流程。

## 3. Agent 拓扑

### 3.1 当前 Stage Agent

当前用户任务中的 Agent 同时承担原 Orchestrator 与 Worker 的职责：

- 维护本 Skill 的执行顺序、停止点和用户交互；
- 完成当前 Owner 的专业分析；
- 调用 Owner-local context、validator、renderer 和 publisher；
- 修复 Reviewer finding，但不得审查或批准自己的成果；
- 不派发 Validator Agent 或额外 helper Agent。

Orchestrator 与 Worker 的分离不再是外部 seam。删除这层分离后，专业上下文只在当前任务中读取
一次；复杂度没有转移给其他调用方。

### 3.2 Reviewer Agent

五个专业 Owner 各保留最多一个独立 Reviewer Agent。Reviewer：

- 使用不继承当前完整聊天记录的新上下文；
- 只读取 review packet、candidate、专业评审材料、Reviewer checklist 和精确证据引用闭包；
- 不读取 canonical fixture、完整上游 artifact 或与 finding 无关的原始工具输出；
- 不运行机械 validator，不修改成果，不代替用户批准；
- 只审查 Python 不能可靠判断的专业完整性、遗漏、证据边界和跨对象一致性；
- 返回 `PASS` 或有限、可定位的 findings。

正常路径只调用 Reviewer 一次。Reviewer 返回 finding 时，允许当前 Stage Agent 完成一次整体修复、
重新机械校验并交回同一 Reviewer 完整复审；第二次仍不能 `PASS` 时返回 `BLOCKED`，不得自动无限
循环。用户反馈改变成果时生成新的 packet，并按同一规则重新审查。

### 3.3 确定性工具

Validator 是 Owner-local Python Module，不再对应 Agent 身份。当前 Stage Agent 直接调用它，并把
结构化 outcome 和 diagnostics 原样提交。机械失败不得由 Agent 解释为通过。

`setup` 和 `generate-sow` 没有新的专业结论，不创建 Reviewer Agent；它们由当前 Stage Agent 调用
确定性脚本并报告结果。

按当前 Skill 合同计算，正常七阶段主线的叶子 Agent 上限由 19 个降为 5 个；一次 reconciliation
的叶子 Agent 上限由 3 个降为 1 个。

## 4. Owner 审批前闭环

五个 Owner 使用同一生命周期，但继续各自拥有业务规则、Schema、renderer、validator 和测试：

```text
Owner-local context preparation
-> 当前 Stage Agent 形成 review notes 与 candidate
-> Owner-local validator check
-> Owner-local renderer 形成 preview/diff/risk summary
-> Reviewer 审查精确 packet
-> 用户批准 packet SHA-256
-> Owner-local publish/rebind
-> receipt match
-> STOP
```

### 4.1 Work-only artifact

批准前只允许写当前 Owner 的 work 目录：

```text
.ai-sow/work/<owner>/
├── context/
│   ├── manifest.json
│   └── fragments/...
├── review-notes.md
├── <output>.candidate.json
├── review.candidate.md
├── risk-summary.md
├── review-packet.json
├── reviewer.json
└── approval.json
```

批准前不得改写正式 `.ai-sow/reviews/<owner>.md`、`.ai-sow/data/<owner>/...` 或
`.ai-sow/validation/<owner>.json`。现有稳定结果存在时，全部正式字节保持 baseline。

`candidate` 是 work-only、待批准的结构化表达，不是稳定数据，也不能替代专业分析。当前 Stage
Agent 同时形成 `review-notes.md`；Owner-local renderer 把 candidate 中的实体、引用和差异与专业
说明组合为 `review.candidate.md`。用户看到的结构化表格和风险摘要必须来自同一 candidate，而不是
批准后再次编译。

### 4.2 Review packet

`review-packet.json` 使用 canonical UTF-8 JSON，至少包含：

```json
{
  "algorithm": "ai-sow-owner-review-packet-v1",
  "candidateOutputs": [],
  "context": {"manifest": {}, "fragments": []},
  "inputArtifacts": [],
  "owner": "generate-task",
  "review": {"path": "", "sha256": ""},
  "riskSummary": {"path": "", "sha256": ""},
  "status": "READY_FOR_REVIEW",
  "validatorContractVersion": "0.3"
}
```

`inputArtifacts` 使用 Owner receipt 的 named input 顺序；`candidateOutputs` 使用 Owner receipt 的
named output 顺序。每项至少包含项目相对 path 与 SHA-256。packet hash 是用户批准的唯一精确对象。

Reviewer `PASS` 不写入 packet 本体，也不直接写项目文件，避免 Reviewer 消息成为稳定业务数据。
Reviewer 只返回 `PASS` 或 findings；`PASS` 后当前 Stage 必须把已审 packet 的完整 SHA-256 传给
Owner-local `validate.py --mode write-reviewer --packet-sha256 <hash>`。该命令只验证固定路径和 hash
格式，以 canonical bytes 原子写入下列 work-only sidecar，不读取 candidate、上游或 Schema：

```json
{
  "algorithm": "ai-sow-owner-reviewer-v1",
  "decision": "PASS",
  "owner": "generate-task",
  "packetSha256": "<64-lowercase-hex>"
}
```

向用户展示时同时报告 packet path、packet SHA-256、Reviewer 结果和风险摘要。Reviewer 返回 finding
时不运行 `write-reviewer`；Stage 的一次整体修复会产生新 packet，原 Reviewer 结论自动失效。
Stage 不得手写、格式化或补全 reviewer JSON；`write-reviewer` 只能消费实际 fresh-context Reviewer
对精确 packet 的 `PASS`，不能替代独立评审。

### 4.3 Approval 与发布

用户必须明确批准 Owner 与 packet SHA-256。当前 Stage Agent 随后只把该精确值传给 Owner-local
`validate.py --mode write-approval --packet-sha256 <hash>`；该命令不读取 candidate、上游或 Schema，
只验证参数并在 Owner 固定 work-only 路径确定性写入 canonical `approval.json`：

```json
{
  "algorithm": "ai-sow-owner-approval-v1",
  "decision": "APPROVED",
  "owner": "generate-task",
  "packetSha256": "<64-lowercase-hex>"
}
```

Stage 不得手写、格式化或补全该 JSON。`write-approval` 成功后必须紧接着只调用一次
`publish-approved`；只有后者承担全部 artifact 与 hash 发布前复核。

publish/rebind 在任何正式写入前重新验证：

- approval、packet、review、risk summary、candidate 和全部 input hash；
- Owner validator contract version；
- 当前正式输入未相对 packet 漂移；
- candidate bytes 与 packet named output 完全一致；
- `NO_CHANGE` 时原稳定 output 仍逐字节相同。

通过后才把 `review.candidate.md` 发布为正式 review，把 candidate 原字节发布为稳定 output，并让
receipt 最后写入。现有 handoff receipt contract `0.3` 继续绑定 input/review/output；approval 和
review packet 是发布授权证据，不成为第七份稳定业务 JSON。

任何 candidate、review 或 input 字节变化都生成新 packet，并要求新的用户批准。批准后不得运行
Worker 修复、Reviewer 复审或 candidate 编译。

三个固定算法 token 分别为 `ai-sow-owner-review-packet-v1`、`ai-sow-owner-reviewer-v1` 和
`ai-sow-owner-approval-v1`。packet、Reviewer sidecar 与 approval sidecar 均使用递归 key 排序、
紧凑分隔符和一个结尾换行的 canonical UTF-8 JSON；算法和生命周期属于每个 Owner 的本地合同，
不得抽成公共业务 runtime、通用 Owner runner 或中央状态。

## 5. Owner-local Context Closure

不建设中央 `slice_context()`、共享业务 context compiler 或 `global_pipeline_state.json`。每个 Owner
在自己的 Skill 内提供 `scripts/prepare_context.py`，输出可丢弃、可重新生成的 work-only closure。
对已有明确 closure 命令的 Owner，该命令是 Stage 的第一条项目命令，并同时承担直接上游 receipt
启动门禁；Stage 不先枚举 `.ai-sow`、探测 Git 或复读完整上游 artifact。closure 成功后只读取
manifest 点名的 fragment 和完成专业分析确需的 source anchor。

`context/manifest.json` 至少记录输入 path、hash、选择规则、选中稳定 ID 和各 fragment 字节数；
它不拥有业务事实，正式判断仍引用稳定 artifact 和 receipt。

固定选择原则：

- `analyze-requirement`：来源 inventory、hash、问卷状态；来源正文按需读取；
- `analyze-as-is`：证据 inventory、九个 Topic、仓库/往期 SOW anchor；源码和文档按需读取；
- `generate-design`：Requirements、As-Is Coverage、Uncertainty、Effective Start 与来源 anchor 闭包；
  As-Is 仓库 `DOCUMENT` Evidence 按登记 repoId 把逻辑 `<repoId>:<anchor>` 重建为 receipt 中的真实
  项目相对路径，不复制或重放 As-Is 业务校验；source anchor 同时保留用于追溯的逻辑 `reference`
  与只供 Stage 读取文件的项目相对 `resolvedPath`，禁止模型自行猜测磁盘位置；两份 candidate
  Schema 由 Skill 公布精确文件名，Stage 不枚举插件目录寻找合同；BUSINESS Epic/Feature、
  Effective Start/Item/Commitment 和 source/Evidence/snapshot 分别只在一个 fragment 投影，避免
  同一集合被 packet 与模型重复加载；
- `generate-story`：ScopeDecision、Feature、Effective Start、问卷决定和十项 Go-live Concern 闭包；
- `generate-task`：Story/AC/Integration、关联 Design Item/Delta、关联 Effective Start 和模板任务目录；
- Reviewer：只读取最终 packet 及 packet 点名的专业证据 fragment。

context compiler 不复制基础人天、倍率、公式、SIT、UAT、风险或取整数据。`generate-task` 仍通过
项目模板读取任务目录和 S/M/L/X 规则；最终计算权威不变。

当 closure 较大时，Agent 先读取 manifest，再按稳定 ID 读取 fragment；不得为了方便预先加载完整
项目 artifact。大小只产生可见诊断，不设置可能截断业务事实的固定 token 上限。

## 6. Deterministic Preview 与风险摘要

每个 Owner 的 renderer 只投影 candidate、review notes、baseline 和已验证 input，输出：

- 新增、删除和变化的稳定 ID；
- named input/output hash；
- Owner-local 覆盖和引用计数；
- unresolved question、Uncertainty、HLD/Go-live、Story/AC、Integration 或 Task 风险；
- `CHANGED/NO_CHANGE` 与精确原因；
- validator diagnostics 和 Reviewer finding 处置摘要。

`generate-task` 可显示 Story、AC、Task、Integration 数量，S/L Task、缺失引用、重复计价门禁和模板
组合可用性；不得计算或声称总人天、基础人天、倍率、公式结果或取整结果。

renderer 不是第二套业务 validator。能够确定性判定的失败仍由 Owner validator 拦截；renderer 只把
已判定结果组织成人类可审查的视图。

## 7. Reconciliation 优化

`reconcile` 的一次整体批准必须绑定已经完成机械验证的完整 staged closure，而不是批准后才生成的
专业 candidate。目标顺序为：

```text
当前 Stage Agent 形成整体影响 review、全部 CHANGED candidate 和 Owner review projection
-> CHANGED staged check/publish
-> NO_CHANGE staged rebind
-> generate-sow 从完整 staged Owner closure 生成并复读 package
-> reconcile.py 确定性 assemble redo manifest、diff 与 risk summary
-> 一个 Reviewer 审查完整精确 packet
-> 用户批准 review/candidates/inputs/package/manifest hash closure
-> publisher 只执行 check/publish
-> STOP
```

批准前所有写入仍限于 `.ai-sow/work/reconcile/<run-id>/`、flat `.ai-sow/.stage-<run-id>/` 和
generate-sow 自己的 staged output；正式 Owner 和 package baseline 不变。

`redo.json` 不再由 Agent 手工拼装。`reconcile/scripts/reconcile.py` 增加 Skill-local assemble
Interface，根据 baseline、staging、批准 packet 所需 closure 和固定 Owner 后缀生成 canonical
manifest。该 Module 只处理 path、hash、`WRITE/DELETE`、顺序和 package tree，不调用 Owner 脚本、
不解释业务语义，也不成为通用 Owner runner。

Reviewer 在批准前只调用一次；批准后不得编译 candidate、修复 Owner projection、重新做 fidelity
review 或重新生成 package。任何 staged byte 变化都生成新 packet 并重新取得整体批准。

当前 flat staging、`NO_CHANGE` 直接 staged rebind、package 先发布、receipt 最后写入、第三种 hash
阻塞和幂等前向恢复语义保持不变。

真实 recovery E2E 进一步要求调度合同本身可复制：`reconcile/SKILL.md` 固定列出 Owner stable、
candidate、review、receipt 路径和 `--staging-root` 命令，`NO_CHANGE` 的 previous/current 分别来自
base Owner receipt 与 staged upstream receipt。Stage 不预读尚未创建的 work 文件，不复制 flat
ProjectView 可回退读取的 base 产物；任一失败 receipt 终止当前 run 并从新 run ID 重测，避免重试
输出在后续模型回合反复累计。
Skill-local `reconcile.py --mode inspect` 在任何项目 artifact 读取之前一次返回该固定后缀的路径、hash、
base validation inputs 和 review ID 声明。它属于既有 path/hash seam，不调用 Owner、不读取其他 Skill
Schema，也不解释业务字段；Stage 不再自行选择 `sha256sum/shasum` 或加载完整 `NO_CHANGE` artifact。
reconciliation-only `prepare-no-change` 从 base review/receipt 与 staged upstream receipt 自动生成
完整 Stable ID/hash binding，`stage-owner` 固定 flat path 投影；Owner validator 仍由 Stage 直接
调用且每个动作必须是独立 fail-fast tool call。这样消除漏列 ID、双层 `.ai-sow` 和失败后继续，
同时不让 reconcile Python 执行/import Owner、读取业务 Schema 或成为通用 Owner runner。命令使用
单路径 `uv --directory <plugin-root> run --project .`，不依赖 shell 临时变量或重复 cache path。
该形式只用于传入绝对 `--project-root` 的 Adapter/Owner 脚本；项目 artifact 读取保持项目 cwd，
避免 `--directory` 改变子进程 cwd 后误解相对路径。
任何 staging 前，`inspect-work` 只读返回 CHANGED candidate named hashes，Stage 先冻结整体
`review.md`，再由 `prepare-changed` 绑定 CHANGED work review；这消除先发布 Design、后发现整体
review 尚不存在的返工。

## 8. Setup 与 Generate SOW

`setup` 的确定性脚本已经能够初始化后复读 project Schema、目录和 XLSX template。当前 Stage Agent
直接运行同一命令并报告结构化结果；不再创建 Worker 与 Validator 两个叶子 Agent。

普通 `generate-sow` 只消费五份匹配 receipt、六份稳定 JSON、五份 review 和项目模板，生成器已经
承担 receipt matching、投影、XLSX 复读、manifest 和内容寻址发布。当前 Stage Agent 直接运行并报告
package summary；不再创建默认 Reviewer。真实 Excel 可见布局仍由 release 视觉检查或用户显式审查
覆盖，不把每次普通生成升级成一个模型 Reviewer。

## 9. 宿主优化层

Skill 文档使用渐进披露：当前 Stage Agent 只加载当前 Skill；Reviewer 只加载 Reviewer checklist。
固定角色说明和输出约束放在 prompt 前部，动态项目 path、hash 和 fragment 放在后部，以便宿主对相同
前缀应用缓存。

Structured Outputs、显式 Prompt Caching、Programmatic Tool Calling 或特定模型配置属于宿主/API
能力。本插件可以提供兼容的 JSON Schema 和稳定 prompt 形状，但不把这些能力作为正确性前提，
也不新增只为调用 OpenAI API 的 MCP server。所有输出仍由本地 Python validator fail closed。

## 10. 兼容性与发布边界

- 六份稳定业务 JSON 路径和 Schema 在本性能修正中不变；
- handoff receipt contract `0.3` 和 named input/output 语义不变；
- HLD/Go-live 继续由 `generate-design` 唯一拥有并验证；
- `runtime/handoff.py` 与 `runtime/project_io.py` 继续只承载纯技术机制；
- 不新增公共 runtime Module、共享业务 Schema、通用 Owner runner 或阶段注册表；
- 不增加中央状态文件，不允许下游修改上游稳定数据；
- candidate-first 改变 work/review 生命周期，现有 beta.2 项目无需迁移稳定 JSON；未完成 work draft
  可删除后重新生成；
- 用户可见流程、Skill 合同、架构测试、README、设计文档和 `CHANGELOG.md` 在推广时同步；
- 已安装插件缓存必须在最终 E2E 前刷新，不能用旧缓存声明新流程已验证。

## 11. 纵向试点与推广

第一阶段只修改 `generate-task`：

1. 保存同一 fixture、模型和宿主配置下的当前基线；
2. 添加 Owner-local context closure；
3. 让 review draft 和 candidate 在批准前同时形成；
4. 扩展 validator 生成并核对 review packet/approval；
5. 把结构化 preview、diff 和 risk summary 置于用户评审前；
6. 删除 Worker/Validator 叶子 Agent，只保留 fresh-context Reviewer；
7. 保持普通 publish、rebind 与 Reconciliation Adapter 兼容；
8. 运行 focused suite 和一条真实 Task Owner session。

试点达标后按 `generate-story -> generate-design -> analyze-as-is -> analyze-requirement` 推广，再简化
`setup`、`generate-sow`，最后调整 `reconcile`。不得在试点未证明质量和成本前同时改写全部 Skill。

### 11.1 当前试点证据

截至 2026-08-25，`generate-task` 已具备 Owner-local context closure、确定性 review renderer、
审批前 `review`、精确 Reviewer/approval sidecar、`publish-approved` 和 receipt `0.3` 兼容路径；
聚焦 Skill 测试、跨模块 staging/reconcile/generate-sow 测试、仓库测试和仓库验证器均通过。

使用仓库代表性 fixture 只比较“完整稳定业务输入 + 模板目录”和“单次 Stage context closure”时，
字节代理从 104,723 降到 80,213，下降 23.4%。该代理不包含旧流程多个 Agent 重复加载同一输入的
成本，也不能等价为模型 token 或 wall time。

随后使用 Codex CLI `0.149.0`、`gpt-5.6-terra`、`medium`、相同输入树、并行 clean session 与冻结
Task 专业决策完成流程隔离 A/B。optimized 相对 baseline 的总 input token 下降 53.8%，总墙钟下降
44.2%，两边发布相同 JSON 语义并通过 receipt `0.3` 和独立 validator。流程性能目标已达到。

随后在同一冻结业务输入上运行两个不提供 Task 决策的干净自然样本。两个样本分别自然形成 27 与
30 个 Task，均由一个 fresh-context Reviewer 在一次整体修复后完整复审 `PASS`，经精确批准发布
candidate 原字节，并通过 receipt `0.3` 与独立 `check`。预埋遗漏样本删除安全与隐私专项测试、
保留 AC 的机械覆盖；validator 允许进入评审，而 Reviewer 根据 TECHNICAL requirement、Delivery 和
模板目录准确阻塞。自然专业拆分、重复采样和遗漏检出门禁已通过，详细证据见 A/B 记录。

## 12. 成功条件

纵向试点至少证明：

1. 一个专业 Owner 的叶子 Agent 上限由三个降为一个；
2. candidate、review、risk summary、机械校验和 Reviewer `PASS` 全部先于用户批准；
3. 批准后只发生一次薄调度和确定性 publish/rebind；
4. packet、approval、candidate、review、input 任一 hash 漂移都在正式写入前阻塞；
5. publish 保持 candidate 原字节，receipt contract `0.3` 和下游 matcher 兼容；
6. `NO_CHANGE` 保持稳定 output 原字节；
7. Reviewer 不继承完整聊天，不重复执行 Python 已覆盖的机械规则；
8. 同一代表性 fixture 的总 input token 至少降低 50%，端到端 wall time 至少降低 40%；
9. 预埋的专业遗漏仍被 Reviewer 发现，确定性 validator 的缺陷检出不下降；
10. 工作区无新的稳定业务 JSON、中央状态、跨 Skill import 或模板计算复制。

全量推广完成后运行一次仓库完整验证、一条普通主线 E2E 和一条同时包含 `CHANGED/NO_CHANGE` 的
reconciliation E2E。旧的七 session、多 Validator Agent release certification 不再作为新合同的
完成条件；Windows 同文件系统与 Excel Desktop 仍按现有 `Provisional` 证据边界声明。

## 13. 非目标与拒绝方案

- 不彻底删除独立语义 Reviewer，以 Worker self-reflection 代替会失去独立专业检查；
- 不保留独立 Validator Agent，运行确定性命令不形成有价值的 Agent seam；
- 不建设 `global_pipeline_state.json`，它会与六份 Owner 稳定数据形成第二事实源；
- 不建设中央 `slice_context()` 或共享业务 context compiler；
- 不让 Python 计算人天、倍率、公式、SIT、UAT、风险或取整；
- 不依赖 Structured Outputs 或 Prompt Caching 才能正确运行；
- 不为减少 tool call 建设跨 Skill Python runner；模型 roundtrip 和重复上下文才是主要优化对象；
- 不承诺 Reviewer 对任意规模项目只读取固定 token 上限而牺牲完整性；
- 不在本设计落盘时自动宣称全部 Owner、reconcile 或 release E2E 已实现。
