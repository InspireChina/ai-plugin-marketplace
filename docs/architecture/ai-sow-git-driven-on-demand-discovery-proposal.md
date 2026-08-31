# AI SOW Git 驱动、按需现状调查工作流优化方案

- 状态：架构提案；尚未实施
- 日期：2026-09-01
- 目标版本：插件 0.2.0
- 当前基线：插件 0.1.0-beta.1、SOW 标准 v1.3
- 适用范围：`plugins/ai-sow/` 的项目初始化、现状调查、Owner 协作、评审批准、返工和最终生成

本文件是在已经实施的
[`AI SOW 决策驱动工作流重构设计`](ai-sow-workflow-refactor-design.md) 和
[`详细合同`](ai-sow-workflow-contract-spec.md) 基础上的下一轮优化方案。现行 0.1.0-beta.1 合同仍以
[`AI_SOW_PLUGIN_DESIGN.md`](../../plugins/ai-sow/docs/AI_SOW_PLUGIN_DESIGN.md) 和
[`CONTEXT.md`](../../plugins/ai-sow/docs/CONTEXT.md) 为准；本提案未实施前，不得把下述目标行为解释为
现有插件能力。

## 1. 执行摘要

本次优化保留 Requirement、As-Is、Design、Story、Task 和 SOW Compiler 的专业所有权，但改变三项
底层机制：

1. 每个 AI SOW 项目强制使用 Git；以小步提交、提交范围和批准引用承担版本历史、差异、回滚和
   精确快照，不再让用户确认一串 artifact hash。
2. `analyze-as-is` 保留为启动阶段，但只建立粗粒度 `CurrentStateMap`；之后任何 Owner 在真正需要
   现状时，都可以发起 `CurrentStateNeed`，由 As-Is Owner 定向调查并增量更新共享 `asis.json`。
3. 项目不只按“新项目/老项目”二分。Setup 记录 `GREENFIELD / EXISTING_SYSTEM / HYBRID / UNKNOWN`
   的初始 `DeliveryContext` 和已知系统来源；具体调查方式由每个 Solution Area 的实际情况决定。

目标流程仍保留熟悉的主线名称：

```text
setup
  -> analyze-requirement
  -> analyze-as-is       # 只建立现状地图和初始 Ledger
  -> generate-design
  -> generate-story
  -> generate-task
  -> generate-sow
```

但该顺序不再表示“前一阶段一次性查清全部信息”。Design、Story 和 Task 都可以在需要时进入同一条
调查回路：

```text
任一 Owner 发现现状信息不足
  -> 提交 CurrentStateNeed
  -> 查询共享 CurrentStateLedger
  -> 选择仓库、文档、环境或问卷 Adapter
  -> As-Is Owner 发布 InvestigationResult
  -> 计算语义 Impact Closure
  -> 原 Owner 继续，或由 Finding 路由上游修正
```

Requirement 不会被 Target Design 取代，As-Is 也不会并入 Design。决定“要做什么”的可能是业务范围、
设计、Story 可验收性或 Task 可估算性；决定“什么时候查现状”的是当下是否出现了一个会影响范围、
责任、方案、交付或估算的具体问题。

## 2. 当前问题

### 2.1 As-Is 仍然前置物化过多信息

当前流程虽然允许 `BOUNDARY_DECLARED`、`NOT_APPLICABLE` 和 hypothesis 模式，但在 Design 前仍要求
一次性形成九个 Topic 的状态、每个 BUSINESS Feature 的 Coverage，以及全部估算相关 Uncertainty 的
关闭结论。这使 As-Is 在真实设计、验收和估算问题出现前，就承担了接近系统尽调的工作量。

### 2.2 现状需要不是 Design 独有

Design 会需要架构、集成和平台事实；Story 会需要当前业务流程、责任和可验收边界；Task 会需要具体
资产、复用条件、迁移对象、工作模式和复杂度依据。把现状调查改成“由 Target Design 驱动”仍然过窄，
只是把前置调查换成了另一个单一调用者。

### 2.3 Greenfield 与 Existing System 的证据渠道不同

纯 Greenfield 没有待搜索的目标系统代码，但仍有当前业务流程、外部系统、数据来源、组织标准、
安全、部署和运维约束。Existing System 则通常有一个或多个本地/远程仓库、运行环境、历史文档或
往期 SOW。用同一种固定仓库调查流程处理两者，会让 Greenfield 制造虚假现状，也让 Existing System
漏掉可复核代码证据。

### 2.4 二元项目类型不足以描述真实项目

“新建门户并接入现有 CRM”“重写服务但迁移既有数据”“新建应用并复用企业身份平台”都属于
Hybrid。项目级类型只能提供启动路由，不能替代每个 Solution Area 的判断。

### 2.5 文件 hash 把正常迭代变成授权失效

现有 candidate、context fragment、review、risk summary、Reviewer sidecar、approval sidecar 和
receipt 通过多层 SHA-256 绑定。它能检测字节变化，但也会产生以下成本：

- 用户必须面对机器 hash，而不是直接批准可理解的变化；
- 文案、路径或 Evidence anchor 变化容易使整份 packet 失效；
- Owner receipt 和固定阶段后缀把文件变化近似为语义变化；
- 工作流实现重复建设 Git 已经提供的历史、差异、快照和回滚能力。

### 2.6 固定后缀返工大于真实影响

Task 发现现状错误时，可能只影响工作模式，也可能推翻 Design、Story 甚至 BUSINESS 范围。固定从某个
Owner 到末尾全部 `CHANGED/NO_CHANGE`，既不能准确表达影响，也要求为无变化 Owner 生成额外绑定。

## 3. 目标与非目标

### 3.1 目标

1. 只在某个决定确实需要现状时调查，并建立最短、可复核的证据链。
2. 保留共享 `asis.json`，让不同阶段积累和复用同一份当前状态知识。
3. 保留 As-Is 单一写 Owner；其他 Owner 只能提出调查需求和消费结果。
4. Setup 提前建立项目上下文和系统来源目录，使后续调查有的放矢。
5. Greenfield 优先问卷，Existing System 优先仓库/文档证据，Hybrid 按 Solution Area 组合。
6. Task 可以发现并路由上游问题，但不能直接修改 Design、Story 或 Requirement。
7. 用 Git 小步提交替代自建 revision store 和工作流可见 hash 确认。
8. 用稳定 ID、类型化引用和语义依赖图计算真实 Impact Closure。
9. 保持 SOW v1.3 工作簿、基础人天、复杂度、公式、SIT、UAT、风险和取整权威不变。
10. 最终包能够从一个精确 Approved Commit 确定性重建。

### 3.2 非目标

- 不把 Requirement、As-Is、Design、Delivery 和 Estimate 合并为一个共享业务文件。
- 不把 As-Is Owner 变成持续扫描全部代码库的知识图谱系统。
- 不允许下游 Owner 直接写上游稳定数据。
- 不用 Git diff 代替领域语义、Owner 所有权、Finding 分类或 Impact Closure。
- 不自动 push、创建远程仓库或把客户资料发送到外部服务。
- 不在 0.1.0-beta.1 中原地改变合同语义。

## 4. 统一领域语言

| 术语 | 定义 |
|---|---|
| `SowWorkspaceRepository` | 保存 `.ai-sow/` 工作流数据的强制 Git 工作树。它与被调查系统仓库是两个不同概念。 |
| `DeliveryContext` | Setup 阶段的项目级启动路由：`GREENFIELD / EXISTING_SYSTEM / HYBRID / UNKNOWN`。它是初始提示，不是所有范围项的永久结论。 |
| `SolutionArea` | 一组可独立判断交付方式和现状来源的业务/技术范围；状态为 `NEW_BUILD / CHANGE_EXISTING / INTEGRATE_EXISTING / MIGRATE_EXISTING / UNKNOWN`。 |
| `SystemSource` | 现状调查可使用的仓库、文档、环境、往期 SOW 或负责人等逻辑来源。 |
| `SourceBinding` | 把 `SystemSource` 绑定到本地路径、远程地址或宿主连接的本机配置；不得包含凭据。 |
| `SourceRevision` | 某次调查实际读取的来源版本，例如目标仓库 Git commit 或文档修订号；它是 Evidence provenance，不是用户批准对象。 |
| `CurrentStateMap` | As-Is 启动阶段生成的粗粒度导航图，只告诉后续 Owner 去哪里寻找事实，不声称已经完成调查。 |
| `CurrentStateLedger` | 共享 `asis.json` 中随工作流增量积累的事实、Evidence、Effective Start、Commitment、Investigation Result 和 Uncertainty。 |
| `CurrentStateNeed` | 任一 Owner 为完成当前专业判断而提出的最小现状问题。 |
| `InvestigationRequest` | As-Is Owner 接受的 work-only 调查任务，包含问题、materiality、subject 和允许来源。 |
| `InvestigationResult` | 可被后续 Owner 稳定引用的调查结论；包含 verdict、Evidence、适用范围、来源修订和未知处理。 |
| `Finding` | Owner 无法在自己的写集合内修复时使用的结构化路由信息，继续使用 `LOCAL / UPSTREAM / DECISION / MECHANICAL`。 |
| `ChangeSet` | 围绕同一目的的一组小步 Git commits；可以跨多个 Owner，但每个 commit 的写集合仍归属于一个 Owner。 |
| `ImpactClosure` | 从变化的稳定 subject 沿类型化和显式语义依赖边得到的最小受影响对象集合。 |
| `ApprovedCommit` | 用户或责任角色批准的精确 Git commit，由 AI SOW 管理的本地 approval ref 指向。 |
| `PackageFingerprint` | 最终不可变 SOW 包的内容标识；它不参与普通阶段批准。 |

`GREENFIELD` 不等于“没有现状”；它只表示本项目不修改一个已经存在的目标实现。外部集成、当前流程、
数据来源、组织和运行约束仍然是现状。`EXISTING_SYSTEM` 也不等于“必须能够访问代码”；缺少代码时
必须登记 `ACCESS_GAP`，再明确使用文档、环境或访谈证据，不能悄悄降级为 Greenfield。

## 5. Setup：Git、项目上下文与来源登记

### 5.1 强制 Git

Setup 必须在写入项目数据前确认：

- `git` 命令可用；
- 项目根位于非 bare Git 工作树；
- `HEAD` 可解析；新仓库已经有初始化 commit；
- Git author 配置可用于创建本地 commit；
- AI SOW 受管路径没有来源不明的未提交修改；
- 当前分支不是 detached HEAD，默认建议使用 `ai-sow/<project-id>`。

不满足时返回稳定错误，例如 `GIT_REPOSITORY_REQUIRED`、`GIT_HEAD_REQUIRED`、
`GIT_IDENTITY_REQUIRED` 或 `MANAGED_PATHS_DIRTY`。Setup 可以在用户明确同意后执行 `git init`、创建
初始 commit 或新建 AI SOW 分支，但不能自动 push、改写已有历史或提交非 `.ai-sow/` 文件。

Git 的写权限只覆盖 AI SOW 受管路径。提交前使用显式文件清单暂存，不得使用会带入用户其他修改的
宽泛 `git add .`。

### 5.2 项目上下文

Setup 要求用户提供一个初始 `DeliveryContext`：

```text
GREENFIELD | EXISTING_SYSTEM | HYBRID | UNKNOWN
```

`UNKNOWN` 允许初始化，但在 As-Is Bootstrap 结束前必须解析为前三者之一。Requirement 后续识别出的
每个 Solution Area 还要分别确定自己的状态；项目级值不强行覆盖局部事实。

### 5.3 系统来源

Setup 同时登记已经知道的 `SystemSource`：

- `LOCAL_GIT_REPOSITORY`
- `REMOTE_GIT_REPOSITORY`
- `DOCUMENT_SET`
- `RUNTIME_ENVIRONMENT`
- `PRIOR_SOW`
- `QUESTIONNAIRE_RESPONDENT`

对于 `EXISTING_SYSTEM` 和 `HYBRID`，Setup 至少需要一个可用来源，或者一条明确的 `ACCESS_GAP`。
远程地址本身不是 Evidence；调查实际使用后，Result 必须记录读取到的 `SourceRevision`。

稳定来源目录只保存 `sourceId`、类型、用途、责任方和 `AVAILABLE / UNAVAILABLE / UNKNOWN` 状态。
本机绝对路径、私有远程地址和宿主连接标识写入 Git 忽略的
`.ai-sow/local/source-bindings.json`；凭据永不写入项目。

### 5.4 目标项目结构

```text
.ai-sow/
├── project.json
├── sources/catalog.json
├── local/source-bindings.json       # gitignored
├── inputs/
├── work/
├── reviews/
├── data/
│   ├── analyze-requirement/requirements.json
│   ├── analyze-as-is/asis.json
│   ├── generate-design/design.json
│   ├── generate-design/requirements.json
│   ├── generate-story/delivery.json
│   └── generate-task/estimate.json
├── validation/
├── approvals/                       # gitignored 可读投影；权威批准是 Git ref
└── outputs/
```

## 6. As-Is Bootstrap：先建地图，不做完整尽调

`analyze-as-is` 仍然是主线阶段，但首次运行只完成以下工作：

1. 确认项目级 `DeliveryContext`；
2. 将 Requirement 识别出的范围划分为 Solution Area；
3. 复核来源目录和访问缺口；
4. 形成 `CurrentStateMap`；
5. 记录少量已经确定、会影响全部后续工作的现状事实；
6. 初始化共享 `CurrentStateLedger`。

建议的地图字段为：

```text
repositories
applicationLandmarks
integrationLocations
dataLocations
deploymentLocations
testAndOperationsLocations
priorSowSources
processAndOrganizationSources
unknownAreas
```

地图条目只需要给出逻辑位置、用途、可访问性和适用 Solution Area。它不要求形成完整 Component、
Integration、Data Asset 或 Evidence 清单，也不要求在 Design 前关闭全部九 Topic。

### 6.1 Greenfield

Greenfield 使用精简的现状基线问卷，优先确认：

- 当前业务流程、参与者和责任边界；
- 必须交互的外部系统；
- 数据来源、数据所有者和迁移要求；
- 组织既定的技术平台、安全与合规标准；
- 部署、运维、支持和发布约束；
- 已知决策与尚未决定的事项。

这不是一次性问完未来可能出现的所有问题。问卷只建立后续可以复用的基线；Design、Story 或 Task
后来出现新的 material question 时，仍然可以通过同一个 Questionnaire Adapter 追问。已经有有效答案
的内容直接复用，不重复询问。问卷只是取证方式，不改变数据所有权：“当前使用 Azure AD”进入
As-Is，“必须支持 MFA”进入 Requirement，“拟采用 Keycloak”进入 Design 或待决 Decision。

### 6.2 Existing System

Existing System 根据已登记来源生成粗粒度地图：读取仓库根、主要目录、入口文档、部署/配置位置和
已知集成索引，但不默认展开全部源码、接口、数据模型或运行行为。只有后续 `CurrentStateNeed` 点名
具体决定后，才进行定向搜索。

### 6.3 Hybrid

Hybrid 按 Solution Area 选择策略。例如“新建门户并接入现有 CRM”：

- 门户实现标记为 `NEW_BUILD`，使用问卷确认平台和运营约束；
- CRM 交互标记为 `INTEGRATE_EXISTING`，使用 CRM 仓库、接口文档或负责人证据；
- 若存在客户数据迁移，再增加 `MIGRATE_EXISTING` Area 并调查源数据。

## 7. 按需现状调查 Module

### 7.1 Interface

所有专业 Owner 使用同一个深 Module，而不是分别实现搜索逻辑：

```text
resolve_current_state_need(CurrentStateNeed) -> InvestigationResult
```

`CurrentStateNeed` 至少包含：

```text
needId
requestingOwner
question
subjectIds
materiality
requiredByDecision
allowedSourceIds
```

`InvestigationResult` 至少包含：

```text
resultId
question
verdict: CONFIRMED | REFUTED | PARTIAL | UNKNOWN
statement
applicableSubjectIds
evidenceIds
sourceRevisions
effectiveStartIds
uncertaintyId
observedAt
```

Request 是 work-only 的执行输入；Result 必须在删除 Request 后仍可独立解释。其他 Owner 只引用
`resultId`、相关 Stable ID 和当前 Result revision，不绑定整个 `asis.json` 的文件 hash。调用 Owner
先明确自己正在形成的专业决定以及缺少的事实，再提出最小 Need；它既不先完成一次全量 As-Is，也不把
未经验证的 Greenfield 假设直接固化为正式决定。

### 7.2 Adapter 路由

Module 根据 Solution Area、来源可用性和问题性质选择一个或多个 Adapter：

| Adapter | 适用场景 |
|---|---|
| `RepositorySearchAdapter` | Existing System 的实现、配置、测试和部署事实 |
| `DocumentEvidenceAdapter` | 接口、架构、运行手册、往期 SOW 和治理标准 |
| `EnvironmentInspectionAdapter` | 静态证据无法回答且获授权的运行行为 |
| `QuestionnaireAdapter` | Greenfield 基线、组织事实、责任、访问缺口和无法从系统读取的信息 |

Greenfield 的“直接问”与 Existing System 的“去搜索”只是不同 Adapter，阶段调用者不需要维护两套
流程。一个 Hybrid Need 也可以先搜索仓库，再用定向问题确认代码无法证明的责任或运营事实。

### 7.3 调查停止规则

每个 Need 都必须回答：如果答案不同，会不会改变以下至少一项？

- BUSINESS 范围或责任；
- Design Decision 或上线责任；
- Story/AC 的交付结果；
- Task 数量、基础单元、工作模式或复杂度；
- Integration、迁移、SIT/UAT、风险、资源或里程碑。

如果不会改变，只记录必要边界，不继续调查。如果可能改变但无法获得足够证据，则形成明确
Uncertainty、Allowance、Discovery 或 DECISION Finding。默认目标是最短充分证据链，不是最大系统理解。

### 7.4 共享 Ledger 与单一写者

目标 `asis.json` 继续是共享增量 Ledger，建议保留：

```text
analysisScope
map
items
commitments
effectiveStarts
evidence
investigationResults
uncertainties
```

Design、Story 和 Task 可以提出 Need，但只有 As-Is Owner 可以新增或修改上述现状数据。调用 Owner 在
As-Is commit 完成后继续工作；任何 Owner 都不能把自己的假设直接写成当前事实。

Result 的有效性按稳定 ID 和来源修订判断。目标仓库 commit 改变、问卷答案被责任人更新或出现竞争
Evidence 时，只标记引用该 Result 的 subject 需要复核；不能因为 `asis.json` 其他区域变化就使全部
下游失效。

## 8. Finding 与上游修正

Task 阶段发现的新事实可以证明上游错误，但必须通过 Finding 路由到拥有该语义的 Owner：

| 新发现的影响 | 修正路径 |
|---|---|
| 只改变 Task 基础单元、工作模式或复杂度 | `As-Is -> Task` |
| 改变实现机制，但不改变客户购买的交付结果 | `As-Is -> Design -> Task`；Story 保持不变 |
| 改变可验收交付结果或 Integration 边界 | `As-Is -> Design -> Story -> Task` |
| 改变 BUSINESS 范围、责任或商业承诺 | `DECISION -> Requirement -> Design -> Story -> Task` |
| 只修正 Evidence anchor，事实语义不变 | 只提交 As-Is 变化；下游不制造 `NO_CHANGE` 文件 |

每个 Finding 至少包含 `findingId`、发现 Owner、目标 Owner、变化 subject、证据、建议影响类型和是否
需要用户决策。Coordinator 根据稳定 ID 引用生成 `ImpactClosure`；Owner 仍只修改自己的 candidate。

现有 `reconcile` 的角色应从“固定阶段后缀发布器”调整为 ChangeSet Coordinator：

- 建立或恢复 ChangeSet；
- 按 Impact Closure 调度受影响 Owner；
- 验证每个 Owner 的写集合和 commit；
- 汇总 review diff；
- 不拥有任何业务 Schema，也不替 Owner 作专业判断。

## 9. Git 驱动的版本、评审与批准

### 9.1 小步提交

Git commit 是工作流 revision。每个通过 Owner-local validator 的连贯语义变化形成一个 commit；无效
草稿留在 work 目录，不因为每次编辑都创建历史。建议使用以下 subject 前缀：

```text
requirement:
asis:
design:
story:
task:
sow:
```

跨 Owner ChangeSet 使用相同 trailer 串联：

```text
AI-SOW-Change-Set: change-<id>
AI-SOW-Owner: <owner>
AI-SOW-Finding: <finding-id>          # 可选
AI-SOW-Subjects: <stable-id-list>
```

commit message 只保存稳定 ID 和非敏感摘要，不保存客户原文、私有仓库地址、凭据或完整工具输出。

### 9.2 Git 能替代什么

删除或大幅收窄以下自建机制：

- packet SHA-256 的用户确认；
- 每个输入、candidate、review 和输出的重复 named hash；
- before/current hash 驱动的 `NO_CHANGE` receipt；
- 按 packet hash 命名的 review 归档；
- 自建不可变 revision store、活动指针、redo history 和自动回滚；
- 因任意文件字节变化而使整阶段授权失效的规则。

Git 提供 commit、tree、blob、diff、branch、merge-base 和恢复能力。Commit ID 可以由工具内部使用，
但面向用户显示的是 ChangeSet 摘要、subject 列表和可读 diff，不要求用户复制或核对 SHA。

### 9.3 Git 不能替代什么

以下能力仍然必须由领域合同提供：

- Owner 写权限和稳定数据归属；
- Stable ID 与类型化引用；
- Finding 分类与用户决策路由；
- Impact Closure；
- Schema、业务 validator、HLD/Go-live 和估算规则；
- Evidence provenance 和未知处理；
- 最终 SOW 的确定性生成。

### 9.4 Review Snapshot 与批准

Reviewer 和用户审查的是一个 Git commit range：

```text
last-approved-commit..candidate-commit
```

Review material 投影以下内容：

- ChangeSet 目的；
- 变化的 Stable IDs；
- 语义 diff 与 Impact Closure；
- Validator 结果；
- 未解决 Finding、Uncertainty 和用户决策；
- 对 SOW 范围、人天、责任和风险的影响。

批准后，由 AI SOW 管理的本地 ref 指向 `ApprovedCommit`，例如：

```text
refs/ai-sow/approved/scope
refs/ai-sow/approved/commitment
```

用户批准的是可读 ChangeSet/Snapshot，不是 ref 名或 SHA。新的 commit 不会改写旧批准；它只让当前
分支领先于 Approved Commit。插件根据变化 subject 判断需要重新打开哪个批准，而不是让所有 Owner
重新确认。

批准 ref 默认只存在本地；插件不自动 push。若团队希望共享批准记录，可以显式发布约定 ref 或导出
签署记录，但这不是本地工作流的前置条件。

### 9.5 简化 receipt

Owner receipt 只保存机械交接所需信息，不再复制文件 hash 树：

```json
{
  "owner": "generate-task",
  "validatedCommit": "<git-commit>",
  "changeSetId": "change-example",
  "outputs": [".ai-sow/data/generate-task/estimate.json"],
  "consumedSubjectIds": ["story-example"],
  "validationOutcome": "PASSED"
}
```

`validatedCommit` 由工具解析并展示为分支/ChangeSet，不要求用户操作。下游必须确认当前数据来自该
commit 或其语义未变的后继，而不是重新计算并比较每个文件的 SHA。

### 9.6 仍保留的 hash

仅在确实需要内容完整性的 seam 保留显式 digest：

- 非 Git 外部文件 Evidence 的内容 digest；
- 最终不可变 SOW package 的 `PackageFingerprint`；
- 生成器合同版本，避免不同投影语义复用同一 package ID。

目标系统 Git 仓库的 commit 属于 `SourceRevision`；它由 Git 管理，既不是自定义 artifact hash，也不
要求用户批准。

## 10. 各阶段目标职责

| 阶段 | 目标职责 | 现状调查行为 |
|---|---|---|
| `setup` | 建立 Git 工作区、项目身份、DeliveryContext、来源目录和模板 | 只验证来源可用性，不调查业务事实 |
| `analyze-requirement` | 拥有 BUSINESS 范围、规则和验收意图 | 可提出 Need；不能把现状答案写入 Requirement |
| `analyze-as-is` | 初始化 Map，拥有共享 Ledger，执行所有定向调查 | 唯一稳定写者 |
| `generate-design` | 拥有目标设计、TECHNICAL requirement 和上线责任 | 按 Design Decision 提出 Need |
| `generate-story` | 拥有 Story、AC、Integration 和 Assumption/Risk | 按交付、验收和责任问题提出 Need |
| `generate-task` | 拥有 Task、工作模式、复杂度和估算输入 | 按可实施性和估算问题提出 Need；可路由上游 Finding |
| `generate-sow` | 从 Approved Commit 确定性编译 package | 不产生新调查或业务决定 |
| `reconcile` | 协调 ChangeSet 和 Impact Closure | 不拥有现状或其他业务数据 |

## 11. 最终生成与完成门禁

`generate-sow` 必须从精确 `ApprovedCommit` 读取六份稳定 JSON、模板和必要评审投影，而不是依赖当前
工作目录中可能尚未批准的字节。生成前至少验证：

1. 所有 Investigation Result 引用存在且来源修订仍有效；
2. `调整 / 接入复用` Task 有对应 Effective Start 和证据；
3. Greenfield 的新建范围没有被迫引用虚假现状资产；
4. 所有 material CurrentStateNeed 已关闭，或转为已批准 Uncertainty、Allowance 或 Discovery；
5. 没有未解决的 `DECISION` 或会改变承诺的 Finding；
6. 每个变化 subject 的 Impact Closure 已完成；
7. 当前待生成 commit 已获得所需批准；
8. AI SOW 受管路径干净；
9. 工作簿仍符合 SOW v1.3 模板、公式和样式合同。

manifest 至少记录：

```text
sourceCommit
generatorContract
packageFingerprint
```

相同 Approved Commit、模板和生成器合同必须产生相同 package。最终 package digest 只保护交付包，
不重新引入逐阶段 hash 审批。

## 12. 隐私与协作边界

- Git 默认只记录在用户本机，不自动添加 remote 或 push。
- Git 历史会保留已删除内容，因此客户原文、凭据、私有源码、绝对路径和完整工具输出不得进入 commit。
- 私有路径和远程地址保留在 gitignored SourceBinding；稳定数据使用逻辑 `sourceId`。
- 调查目标仓库默认只读；clone、fetch 或运行环境访问必须符合宿主授权和项目策略。
- AI SOW 自动 commit 只暂存受管文件，发现同一受管文件有未知修改时 fail closed。
- 最终包仍按项目隐私策略决定是否提交或分享。

## 13. 迁移与发布策略

本方案同时改变 Git 前置条件、Setup Schema、As-Is 生命周期、receipt、批准和 reconciliation 语义，
属于 breaking contract，必须发布为插件 0.2.0，不能解释为 0.1.0-beta.1 的兼容增强。SOW 标准仍为
v1.3，因为工作簿计算规则没有变化。

0.1.0 项目的显式迁移流程：

1. 使用旧插件验证现有六份稳定 JSON、五份 Owner receipt 和模板；
2. 初始化或确认 `SowWorkspaceRepository`；
3. 将旧项目状态导入为只读 migration baseline commit；
4. 声明 DeliveryContext，登记 SystemSource 和本地 SourceBinding；
5. 从旧 As-Is 提取可复用 Stable ID，并生成初始 CurrentStateMap；
6. 建立 approved baseline ref；
7. 后续变化使用 0.2.0 ChangeSet 流程。

迁移必须是显式命令，完整复读后再 commit；不得静默混读 0.1.0 receipt 与 0.2.0 Git approval。若不
迁移，项目继续使用与其合同匹配的 0.1.0 插件版本。

## 14. 实施切片

### 14.1 固定 0.2.0 合同

- 定义本文件中的领域术语和 Schema；
- 明确当前正式合同与目标合同的 clean cutover；
- 定义 Git 错误、SourceBinding 隐私边界和受管写集合。

### 14.2 建立 Git Project Module

- 实现 repository preflight、managed-path status 和显式暂存；
- 实现 Owner commit、ChangeSet trailer、approval ref 和 Approved Commit 读取；
- 用 Git history 替换 packet archive、before/current hash 和 redo revision store；
- 增加 dirty worktree、detached HEAD、空仓库和混入用户修改的测试。

### 14.3 扩展 Setup

- 增加 DeliveryContext、SystemSource catalog 和 SourceBinding；
- 对 Existing/Hybrid 强制来源或 ACCESS_GAP；
- 支持用户确认后的 Git 初始化和 AI SOW 分支创建；
- 保持不自动 push、不保存凭据。

### 14.4 重塑 As-Is

- 将首次 As-Is 收窄为 CurrentStateMap 和基线 Ledger；
- 为 Greenfield 增加精简问卷 Adapter；
- 为 Existing System 增加定向仓库/文档 Adapter；
- 增加 CurrentStateNeed、InvestigationRequest 和 InvestigationResult；
- 让 Result 使用 Stable ID 与 SourceRevision，而不是整体文件 hash。

### 14.5 建立语义影响协调

- 从类型化 ID 引用机械生成依赖边；
- 允许 Owner 补充 Schema 无法表达的语义边；
- 把 Task Finding 路由到正确 Owner；
- 将 `reconcile` 从固定后缀调整为 ChangeSet/ImpactClosure Coordinator。

### 14.6 简化评审与批准

- 以 Git commit range 生成 review material；
- 让 Reviewer 和用户批准可读 ChangeSet；
- 删除工作流可见 packet SHA 和无变化 Owner 的 rebind；
- 保留 Owner-local validator 和必要的 fresh-context 专业评审。

### 14.7 更新生成与迁移

- 从 Approved Commit 构建最终包；
- manifest 增加 `sourceCommit`；
- 保留 package fingerprint 和 generator contract；
- 提供显式 0.1.0 baseline migration。

### 14.8 完成发布面

- 同步 Skill、Schema、fixture、validator、README、设计文档、CONTEXT、CHANGELOG、manifest、版本和锁；
- 增加复制插件 smoke，证明独立安装后仍可完成 Git workflow；
- 在 macOS、Linux 和 Windows 上验证路径、Git 和确定性 package。

## 15. 核心行为场景

### 15.1 纯 Greenfield

- Setup 选择 `GREENFIELD`，不要求目标代码仓库；
- As-Is 通过基线问卷建立外部系统、数据、平台和运营地图；
- Design/Story/Task 只在出现新问题时定向追问；
- 不制造不存在的 Component 或 Effective Start；
- 仍可形成完整新建 Task 和估算。

### 15.2 Hybrid 新门户接入 CRM

- 门户为 `NEW_BUILD`，CRM 为 `INTEGRATE_EXISTING`；
- Setup 登记 CRM 远程仓库或接口文档；
- As-Is 只建立两块导航地图；
- Design 提问 CRM 身份和接口能力，Task 提问项目侧适配工作；
- 两次 Result 写入同一 Ledger，但可以引用不同 SourceRevision。

### 15.3 Existing System 调整

- Setup 登记一个或多个本地/远程 Repo；
- As-Is 只识别主要应用、集成、数据、部署和测试位置；
- Task 为某个基础单元判断“调整”时，只搜索相关对象；
- 不相关模块不进入稳定 As-Is 或 review。

### 15.4 Task 推翻上游方案

- Task 发现目标平台不支持 Design 假定的机制；
- As-Is Owner 确认事实并 commit Result；
- Task 发出 UPSTREAM Finding；
- Design Owner 修改机制并 commit；
- 若交付结果未变，Story 不产生无意义 commit；
- Task 只重新处理 Impact Closure 中的对象。

### 15.5 来源变化

- 目标系统仓库从 SourceRevision A 更新到 B；
- 只把引用 A 且其 anchor/语义可能变化的 Results 标记为待复核；
- `asis.json` 中其他 Result 和闭包外批准继续有效。

### 15.6 Existing System 无代码访问权

- Setup 记录 `ACCESS_GAP`，并登记文档或负责人；
- 调查使用文档和问卷 Evidence；
- 关键实现事实无法确认时形成 Uncertainty/Discovery；
- 不把项目误标为 Greenfield，也不伪造代码证据。

## 16. 验收标准

1. Setup 在任何项目数据写入前验证 Git，并且不能自动 push 或提交非受管文件。
2. 每个项目明确 `GREENFIELD / EXISTING_SYSTEM / HYBRID`；`UNKNOWN` 不能越过 As-Is Bootstrap。
3. Existing/Hybrid 必须登记来源或 ACCESS_GAP，私有 locator 不进入 tracked 稳定数据。
4. 首次 As-Is 只生成 CurrentStateMap、初始 Ledger 和少量全局事实，不要求九 Topic 全面调查。
5. Design、Story 和 Task 都能通过同一 Interface 请求现状，不复制调查实现。
6. Greenfield 默认由 Questionnaire Adapter 提供现状，且后续只追问新增 material Need。
7. Existing System 默认从地图定向搜索，不扫描与当前决定无关的仓库区域。
8. `asis.json` 是共享增量 Ledger，但只有 As-Is Owner 能写稳定现状数据。
9. Investigation Result 删除 work-only Request 后仍能独立解析，并保留 SourceRevision。
10. Task Finding 能根据影响类型修正 Design、Story 或 Requirement 链路，Task 本身不越权写上游。
11. 语义不变的 Evidence 修正不会制造下游 `NO_CHANGE` 文件或固定后缀重审。
12. 每个受影响对象由 Stable ID 依赖图进入 Impact Closure，闭包外内容可以复用。
13. 普通评审向用户展示 ChangeSet、subject 和可读 diff，不要求用户核对 SHA-256。
14. Owner 变化形成小步 Git commit；跨 Owner 修正由 ChangeSet trailer 关联。
15. 插件只暂存明确受管文件，遇到受管路径未知修改时 fail closed。
16. Approval ref 精确指向 Approved Commit，新 commit 不覆盖既有批准。
17. 最终包从 Approved Commit 确定性生成，并记录 `sourceCommit`、`generatorContract` 和
    `packageFingerprint`。
18. 只有外部非 Git Evidence 和最终 package 保留显式 digest；普通阶段不再维护重复 hash 树。
19. 0.1.0 项目只能显式迁移，不与 0.2.0 receipt/approval 混读。
20. SOW v1.3 的模板、基础人天、复杂度、SIT、UAT、风险、公式和样式保持不变。

## 17. 否决的方案

### 17.1 只分“新项目/老项目”

否决。真实项目经常同时包含 New Build、Existing Integration 和 Migration；二元类型只能作为启动
提示，不能表达 Solution Area。

### 17.2 Greenfield 一次问完，后续禁止调查

否决。Task 或 Story 仍可能出现初始化时无法预见的问题。正确边界是“不搜索不存在的目标系统，按需
追问新增 material question”，不是“一次问卷永久封闭”。

### 17.3 完全删除 As-Is 阶段

否决。后续 Owner 需要一个共享地图、统一 Ledger、单一事实写者和证据 provenance。删除后会让每个
阶段自行搜索并产生互相冲突的现状。

### 17.4 只由 Design 驱动调查

否决。Story 的验收边界和 Task 的实施/估算问题同样会产生新的现状需要。

### 17.5 仍在 Design 前完成全面 As-Is

否决。它继续把系统尽调成本前置，并在真实问题尚未出现时制造低价值事实。

### 17.6 只在 Task 阶段调查

否决。部分事实会在 Design 或 Story 阶段提前影响方案和交付结果；Task 可以调查和反馈，但不是唯一
调查点。

### 17.7 保留全部 packet hash，只在界面隐藏

否决。复杂度仍然存在于 invalidation、rebind、归档和实现中，只是用户看不到。Git 已经提供对应的
版本原语，应从合同中删除重复机制。

### 17.8 只用 Git diff，不保留领域依赖

否决。Git 能指出哪些行改变，不能判断某个 Effective Start 会影响哪些 Design Decision、Story 或
Task。语义 Impact Closure 仍然不可替代。

### 17.9 自动 push 作为完成条件

否决。版本历史只要求本地 Git；远程分享涉及凭据、隐私和团队策略，必须由用户显式决定。
