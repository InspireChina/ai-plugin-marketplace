# AI SOW 决策驱动工作流详细合同

状态：设计提案；尚未实施  
日期：2026-08-31  
上位设计：[AI SOW 决策驱动工作流重构设计](ai-sow-workflow-refactor-design.md)  
目标插件合同：0.2.0  
SOW 计算标准：继续使用 v1.3

## 1. 文档目的

本文把上位设计细化为可实现、可验证的逻辑合同，固定：

- 领域对象、关系、Owner 和稳定性；
- 五个目标阶段的精确输入和输出；
- 五个门禁及最终签署确认的进入、通过、阻塞和失效条件；
- Candidate、Review、Approval、Publish 和 Stale 状态转换；
- Design、Delivery、Estimate 和 Planning 的反馈路径；
- 上游变更后的依赖闭包；
- Greenfield、Brownfield、Discovery 和计划不可行场景。

本文描述逻辑合同，不固定 Python 文件名、CLI 参数、目录布局或 JSON Schema 拆分方式。实现可以选择不同内部结构，但不得改变本文定义的 Owner、关系、门禁和停止条件。

## 2. 统一语言

### 2.1 工作流术语

| 术语 | 定义 |
|---|---|
| Phase | 为形成一个业务结果而组织的工作区间；Phase 内允许多个 Owner 迭代，不等于单个 Skill。 |
| Owner | 独占某类稳定业务语义、ID 和写权限的责任主体。 |
| Module | 通过小 interface 提供完整行为的实现单元；不等于 Owner 或 Phase。 |
| Gate | 判断是否可以承担下一项不可逆责任的门禁；只接受绑定的输入和候选结果。 |
| Candidate | 尚未发布、内容已冻结并可计算 hash 的 Owner 成果。 |
| Gate Packet | 绑定门禁输入、候选结果、风险和 Reviewer 结论的不可变审查对象；角色批准通过 sidecar 引用其 hash。 |
| Stable Output | Gate 通过后由唯一 Owner 发布、可供下游引用的业务数据。 |
| Decision Dependency | 一个稳定事实或决定对另一个决定的直接语义依赖。 |
| Impact Closure | 从变化对象沿 Decision Dependency 得到的全部受影响对象和 Gate。 |
| Materiality | 某问题的不同答案是否会改变范围、责任、交付、Task、工作模式、复杂度、人天、资源或里程碑。 |
| Committable | 信息、责任和估算足以由对应角色正式承诺；不是“信息很多”或“调查完整”的同义词。 |

### 2.2 领域术语

| 术语 | 定义 |
|---|---|
| Business Scope | 获批 BUSINESS Epic/Feature、业务规则、验收意图、范围边界和技术输入队列。 |
| Technical Input | 来源中需要由 Design 判断的技术陈述、约束或既有方案，不是已批准 TECHNICAL requirement。 |
| Coverage | 一个 BUSINESS Feature 相对于当前或项目开始时基线的 `COMPLETE / PARTIAL / MISSING` 结论。 |
| Current-State Fact | 调查截止时间已经存在或实际运行、且会影响一个决定的事实。 |
| Effective Start | 项目开始时可以依赖的能力、资产、承诺或责任边界。 |
| Investigation Request | 为支持或证伪一个具体决定而提出的最小调查问题。 |
| Investigation Result | As-Is Owner 对 Investigation Request 给出的 `SUPPORTED / FALSIFIED / UNKNOWN` 结论。 |
| Delivery Delta | Feature 目标结果减去 Effective Start 后仍需交付的差值。 |
| Technical Solution | Scope Decision、Design Item、Architecture Delta、Design Decision、TECHNICAL requirement 和上线责任的集合。 |
| Delivery Contract | Story、AC、Integration、Assumption/Risk 及其责任边界。 |
| Trial Estimate | 用于证明 Delivery Contract 可估算的 work-only Task 试拆分，不是正式 Estimate。 |
| Estimate Baseline | 已批准 Task、基础单元、工作模式、复杂度、理由和估算关系。 |
| Delivery Plan | 资源、依赖、迭代、里程碑和外部配合窗口；只在承诺日期或计划时成为稳定业务输出。 |
| Allowance | 对有上限未知的获批处理；必须表现为可枚举、可按模板计价的最大工作范围，不保存自由人天。 |
| Discovery Requirement | 无法安全进入实施估算时，独立调研 SOW 必须回答的问题、交付物和退出条件。 |
| Commercial Packet | 对同一范围、方案、Delivery Contract、Estimate、Plan、假设和例外的统一商业批准对象。 |
| SOW Package | 由 Commercial Packet 和当前 Owner receipt 确定性编译出的工作簿、自包含数据和 manifest。 |

## 3. 聚合与 Owner

### 3.1 稳定聚合

目标合同包含七个稳定业务聚合和一个最终交付聚合：

| 聚合 | 唯一 Owner | 必选 | 首次稳定发布时点 |
|---|---|---:|---|
| `ProjectShell` | Setup Module | 是 | Setup Gate |
| `BusinessScope` | Requirement Owner | 是 | Scope Gate |
| `CurrentStateLedger` | As-Is Owner | 是 | Commitment Gate |
| `TechnicalSolution` | Design Owner | 是 | Commitment Gate |
| `DeliveryContract` | Delivery Owner | 是 | Commitment Gate |
| `EstimateBaseline` | Estimate Owner | 是 | Commitment Gate |
| `DeliveryPlan` | Planning Owner | 条件必选 | Commitment Gate |
| `SowPackage` | SOW Compiler | 是 | Compilation Gate |

`CommercialPacket` 是跨聚合批准投影，不拥有新的业务事实。它只引用并绑定上述 Owner candidate 和风险处置；角色批准通过 sidecar 引用它的精确 hash。

### 3.2 Work-only 对象

以下对象不作为跨阶段长期稳定业务数据：

- Design Hypothesis；
- Investigation Request；
- 未被批准决定引用的 Investigation Result；
- Trial Estimate；
- Trial Finding；
- Gate Evaluation；
- Reviewer sidecar；
- Approval sidecar；
- Context fragment、claims、risk summary；
- Impact analysis 和发布 staging。

被最终批准决定引用的 Investigation Result，其结论、Evidence 和 Effective Start 必须由 As-Is Owner 编译进 `CurrentStateLedger`。未被引用的调查过程留在 work 目录，不进入稳定交接。

### 3.3 写权限

| Owner | 可以写 | 只读 | 禁止写 |
|---|---|---|---|
| Requirement | `BusinessScope` candidate/stable | Source、ProjectShell | Current State、Design、Delivery、Estimate |
| As-Is | `CurrentStateLedger` candidate/stable | BusinessScope、授权 Evidence | Design、Delivery、Estimate |
| Design | `TechnicalSolution` candidate/stable | BusinessScope、Current State candidate | BusinessScope、Current State、Delivery、Estimate |
| Delivery | `DeliveryContract` candidate/stable | BusinessScope、Current State、Technical Solution | Design、Estimate |
| Estimate | Trial Estimate、`EstimateBaseline` candidate/stable | Delivery、Design、Current State、模板目录 | Story、AC、Design、模板计算规则 |
| Planning | `DeliveryPlan` candidate/stable | Estimate、Delivery、项目约束 | Task、基础人天、Story/AC |
| SOW Compiler | `SowPackage` | 全部已批准稳定聚合、模板 | 所有上游业务聚合 |

Owner 发现上游错误时只能返回结构化 Finding，不能直接修复上游。

## 4. 领域对象模型

### 4.1 关系总览

```text
ProjectShell
  └─ BusinessScope
       ├─ BusinessFeature
       │    ├─ Coverage ── EffectiveStart ── CurrentStateFact ── EvidenceRef
       │    ├─ ScopeDecision
       │    ├─ DesignDecision
       │    └─ Story ── AcceptanceCriterion
       │                 └─ Task ── BaseUnit / WorkMode / Complexity
       └─ TechnicalInput
            └─ DesignDecision

DesignDecision ── InvestigationResult ── InvestigationRequest
Story ── Integration ── IntegrationTask
Task / Milestone ── DeliveryPlan
Uncertainty ── Handling ── Assumption | Allowance | DiscoveryRequirement | BLOCKED

BusinessScope
+ CurrentStateLedger
+ TechnicalSolution
+ DeliveryContract
+ EstimateBaseline
+ DeliveryPlan（条件）
  └─ CommercialPacket
       └─ SowPackage
```

### 4.2 `ProjectShell`

最小字段：

| 字段 | 约束 |
|---|---|
| `projectId` | 全局稳定，小写 kebab-case；项目语义不变时不变。 |
| `name` | 非空项目名称。 |
| `pluginContractVersion` | 固定为目标插件合同版本。 |
| `sowStandardVersion` | 本重构固定为 `1.3`。 |
| `templateFingerprint` | 当前项目模板内容 hash。 |
| `commitmentMode` | `EFFORT_ONLY / MILESTONE_COMMITTED`。 |

`commitmentMode` 决定 `DeliveryPlan` 是否为 Gate 必选输入：

- `EFFORT_ONLY`：只承诺范围和工作量，SOW 必须明确不承诺日期；
- `MILESTONE_COMMITTED`：承诺日期、里程碑或迭代，必须有可行的 Delivery Plan。

### 4.3 `BusinessScope`

包含：

- `BusinessEpic[]`；
- `BusinessFeature[]`；
- `BusinessRule[]`；
- `ScopeBoundary[]`；
- `TechnicalInput[]`；
- `BusinessAssumption[]`。

#### `BusinessFeature`

| 字段 | 约束 |
|---|---|
| `featureId` | 稳定 ID；语义实质变化时新建。 |
| `epicId` | 恰好一个父 Epic。 |
| `name` | 非空且在 Feature 集合内唯一。 |
| `outcome` | 业务可观察结果，不描述实现。 |
| `acceptanceIntent` | 足以指导 AC，但不是正式 AC。 |
| `scopeStatus` | `IN_SCOPE / OUT_OF_SCOPE / DEFERRED`。 |
| `sourceRefs` | 至少一个来源或明确的人类决定。 |

每个 `IN_SCOPE` Feature 必须进入 Coverage、Scope Decision 和 Delivery Contract；`OUT_OF_SCOPE / DEFERRED` 不生成 Story 或 Task。

#### `TechnicalInput`

| 字段 | 约束 |
|---|---|
| `technicalInputId` | 稳定 ID。 |
| `statement` | 来源技术陈述的忠实摘要。 |
| `sourceRef` | 单一可复核 anchor。 |
| `affectedFeatureIds` | 至少一个 Feature。 |
| `disposition` | Scope Gate 时固定为 `PENDING_DESIGN`。 |

Requirement Owner 不得把 `TechnicalInput` 标记为 `ACCEPTED_TECHNICAL_REQUIREMENT`。Design Owner 在后续将其处理为采用、替代、排除或进一步调查。

### 4.4 `CurrentStateLedger`

只保存被批准决定实际引用的最小现状闭包：

- `Coverage[]`；
- `CurrentStateFact[]`；
- `EffectiveStart[]`；
- `Commitment[]`；
- `Uncertainty[]`；
- `EvidenceRef[]`；
- `InvestigationResult[]`。

固定九个 Topic 只作为 `CoverageChecklist`，每个 Topic 恰有一个：

- `INVESTIGATED`：当前决定确实需要深挖；
- `BOUNDARY_DECLARED`：沿用或责任边界已明确，不深挖；
- `NOT_APPLICABLE`：有依据地不适用。

删除“证据不足但继续通过”的 Topic 状态。证据不足若影响决定，必须形成 `Uncertainty` 并由 Handling 决定是否阻塞；若不影响决定，则使用 `BOUNDARY_DECLARED`。

#### `Coverage`

每个 `IN_SCOPE` BUSINESS Feature 恰有一条：

| 字段 | 约束 |
|---|---|
| `featureId` | 唯一对应 Feature。 |
| `status` | `COMPLETE / PARTIAL / MISSING`。 |
| `effectiveStartIds` | `COMPLETE / PARTIAL` 至少一个；`MISSING` 为空。 |
| `commitmentIds` | 只含与该 Feature 重叠的往期承诺。 |
| `uncertaintyIds` | 只含会改变当前 Coverage 或后续决定的问题。 |
| `rationale` | 说明已有、缺失和边界，不复制证据全文。 |

#### `EvidenceRef`

| 字段 | 约束 |
|---|---|
| `evidenceId` | 稳定 ID。 |
| `kind` | `CODE / CONFIGURATION / CONTRACT / DEPLOYMENT / DOCUMENT / PRIOR_SOW / QUESTIONNAIRE / RUNTIME`。 |
| `reference` | 单一项目相对或合同逻辑 anchor。 |
| `sourceFingerprint` | 被引用来源的内容 hash。 |
| `observation` | 证据直接表明的事实，不扩展为目标方案。 |
| `supportsIds` | 直接支持的 Fact、Commitment、Effective Start、Coverage 或 Uncertainty。 |

Evidence 不保存源码、完整工具输出、凭据或本机绝对路径。同一业务判断默认只保留一条最佳 Evidence；只有冲突、复合责任或高影响决定确实需要时才保留多条。

#### `CurrentStateFact`

| 字段 | 约束 |
|---|---|
| `currentStateFactId` | 稳定 ID。 |
| `topic` | 固定九 Topic 之一。 |
| `factType` | `CAPABILITY / COMPONENT / INTEGRATION / DATA_ASSET / INFRASTRUCTURE / CONTROL / PROCESS / CONSTRAINT`。 |
| `name` | 非空且在 Ledger 内唯一。 |
| `statement` | 截止 `asOfDate` 已存在或实际运行的事实。 |
| `asOfDate` | ISO 日期。 |
| `affectedFeatureIds` | 至少一个，除非只支撑跨 Feature 上线责任。 |
| `evidenceIds` | 至少一条直接 Evidence。 |

一个 Fact 还必须满足至少一项：

- 被 Effective Start 引用；
- 支持 `COMPLETE / PARTIAL` Coverage；
- 被 Design Decision 引用；
- 支持 Task 的 `调整 / 接入复用`；
- 证明集成、迁移、平台、发布、安全或责任边界。

不能满足任一项的事实不进入稳定 Ledger。

#### `Commitment`

| 字段 | 约束 |
|---|---|
| `commitmentId` | 稳定 ID。 |
| `priorSowId` | 已登记往期 SOW。 |
| `sourceRef` | 原承诺单一逻辑 anchor。 |
| `changeType` | `ADD / REPLACE / RETIRE`。 |
| `implementationStatus` | `IMPLEMENTED / PARTIAL / NOT_IMPLEMENTED / UNVERIFIED / SUPERSEDED`。 |
| `treatment` | `CURRENT_BASELINE / EXPECTED_BEFORE_START / CARRY_FORWARD / EXCLUDE / NEEDS_DECISION`。 |
| `affectedFeatureIds` | 只含当前 BusinessScope 中实际重叠的 Feature。 |
| `evidenceIds` | 支持状态核对的 Evidence。 |

与当前 Feature 无关的往期承诺不进入稳定 Ledger。`UNVERIFIED / NEEDS_DECISION` 必须关联高影响 Uncertainty；`CARRY_FORWARD` 进入 Delivery Delta，不进入 Effective Start。

#### `EffectiveStart`

| 字段 | 约束 |
|---|---|
| `effectiveStartId` | 稳定 ID。 |
| `name` | 非空且在 Ledger 内唯一。 |
| `summary` | 明确项目开始时可以依赖的对象、能力和责任边界。 |
| `sourceFactIds` | 当前 Fact；可以为空。 |
| `commitmentIds` | 只允许预计开始前完成的 Commitment；可以为空。 |
| `evidenceIds` | 至少一条最佳 Evidence，除非来源只由已批准人类决定构成。 |

`sourceFactIds` 与 `commitmentIds` 至少一个非空。Effective Start 不预判 Task 工作模式。

#### `InvestigationRequest`

| 字段 | 约束 |
|---|---|
| `requestId` | work-only 稳定 ID。 |
| `decisionId` | 恰好一个待支持或证伪的决定。 |
| `question` | 一个可通过有限证据回答的问题。 |
| `affectedFeatureIds` | 至少一个。 |
| `materialityTargets` | `SCOPE / RESPONSIBILITY / SOLUTION / STORY / TASK_COUNT / WORK_MODE / COMPLEXITY / TESTING / RISK / PLAN` 的非空集合。 |
| `falsificationMethod` | 最小证伪方法。 |
| `allowedSourceIds` | 只含用户授权来源。 |
| `stopRule` | 得到哪一种证据即可停止。 |

禁止使用“全面分析系统”“调查所有接口”或“补充更多信息”作为问题或停止规则。

#### `InvestigationResult`

| 字段 | 约束 |
|---|---|
| `requestId` | 恰好对应一个 Request。 |
| `verdict` | `SUPPORTED / FALSIFIED / UNKNOWN`。 |
| `factIds` | `SUPPORTED / FALSIFIED` 时至少一个；`UNKNOWN` 可以为空。 |
| `evidenceIds` | 高影响结论至少一条；冲突时保留必要竞争 Evidence。 |
| `impact` | 明确影响哪些决定字段。 |
| `handling` | `ACCEPT / REVISE_DECISION / ASSUMPTION / ALLOWANCE / DISCOVERY / BLOCK`。 |

`UNKNOWN` 不能使用 `ACCEPT`。`FALSIFIED` 不能保持原 Decision candidate 不变。

#### `Uncertainty`

| 字段 | 约束 |
|---|---|
| `uncertaintyId` | Owner-local 稳定 ID。 |
| `question` | 一个仍未得到可靠答案的问题。 |
| `materialityTargets` | 与 Investigation Request 使用同一枚举；非空。 |
| `affectedDecisionIds` | 至少一个 Feature、Design Decision、Story、Task 或 Plan candidate。 |
| `evidenceIds` | 已有但不足或互相冲突的 Evidence；可以为空。 |
| `owner` | 能提供证据或作出决定的角色/团队。 |
| `handlingId` | 指向 Assumption、Allowance、Discovery Requirement 或显式 Blocker。 |
| `status` | `OPEN / HANDLED`。 |

`HANDLED` 不表示问题已经回答，只表示其影响已通过获批且可执行的方式封闭。没有 `handlingId` 的高 Materiality Uncertainty 必须保持 `OPEN` 并阻塞 Gate。

#### `DiscoveryRequirement`

| 字段 | 约束 |
|---|---|
| `discoveryRequirementId` | 稳定 ID。 |
| `uncertaintyIds` | 至少一个无法安全界定的高影响 Uncertainty。 |
| `questions` | Discovery 必须回答的有限问题集合。 |
| `deliverables` | 能被实施 SOW 直接消费的事实、决定或样本，不使用“调研报告”等空泛名称。 |
| `exitCriteria` | 每个问题达到何种证据和精度后可以重新估算。 |
| `responsibleRole` | 负责组织 Discovery 的角色。 |
| `affectedFeatureIds` | 被阻塞的实施范围。 |

Discovery Requirement 是当前实施 SOW 的阻塞输出，不与被阻塞的实施范围一起进入 Commitment Gate。Discovery 完成后，其结果作为新的授权输入重新进入相应 Owner。

### 4.5 `TechnicalSolution`

包含：

- `ScopeDecision[]`；
- `DesignItem[]`；
- `ArchitectureDelta[]`；
- `DesignDecision[]`；
- `TechnicalEpic[] / TechnicalFeature[]`；
- `TechnicalInputDisposition[]`；
- `GoLiveDisposition[]`。

#### `ScopeDecision`

每个 BUSINESS 和 TECHNICAL Feature 恰有一条：

- `IN_SCOPE`：需要 Design 和 Delivery；
- `FULLY_COVERED`：必须引用 `COMPLETE` Coverage 和支持 Evidence；
- `OUT_OF_SCOPE`：必须引用已批准 Scope Boundary，不能由 Design 单方面排除 BUSINESS Feature。

#### `DesignItem`

| 字段 | 约束 |
|---|---|
| `designItemId` | 稳定 ID。 |
| `type` | `COMPONENT / FLOW / DATA / INTEGRATION / INFRASTRUCTURE / QUALITY`。 |
| `name` | 目标设计内唯一。 |
| `description` | 目标状态及责任，不复述 Feature 或 Task。 |
| `affectedFeatureIds` | 至少一个 `IN_SCOPE` Feature。 |
| `designDecisionIds` | 至少一个产生或约束该 Item 的决定。 |

#### `ArchitectureDelta`

| 字段 | 约束 |
|---|---|
| `architectureDeltaId` | 稳定 ID。 |
| `designItemId` | 恰好一个目标 Design Item。 |
| `changeType` | `NEW / ADOPT / ADJUST / REPLACE / RETIRE`。 |
| `effectiveStartIds` | `ADOPT / ADJUST / REPLACE / RETIRE` 时至少一个；`NEW` 可以为空。 |
| `rationale` | 说明相对于 Effective Start 的目标变化。 |

Architecture Delta 不是 Task 工作模式。`REPLACE / RETIRE` 必须在 Delivery/Estimate 中展开为实际交付对象。

#### `TechnicalRequirement`

Technical Epic/Feature 继续使用统一 Epic/Feature 层级。每个 Technical Feature 还必须包含：

- `provenance: SOURCE_INPUT / DESIGN_DERIVED`；
- `designDecisionIds`；
- `affectedBusinessFeatureIds`；
- `sourceTechnicalInputIds`：仅 `SOURCE_INPUT` 必填；
- `derivationRationale`：仅 `DESIGN_DERIVED` 必填，说明决定、原因和缺失影响。

Design Owner 不能把 Business Feature 移入 Technical Requirement，也不能通过新 Technical Feature 暗中扩大商业范围。

#### `TechnicalInputDisposition`

Design Owner 不修改 `BusinessScope.TechnicalInput`，而是在自己的聚合中为每项输入恰好记录一条处置：

| 字段 | 约束 |
|---|---|
| `technicalInputId` | 引用 BusinessScope 中的输入。 |
| `status` | `ADOPTED / REPLACED / REJECTED / INVESTIGATION_REQUIRED`。 |
| `designDecisionIds` | 采用或替代时至少一个。 |
| `technicalRequirementIds` | 形成 TECHNICAL requirement 时至少一个。 |
| `investigationResultIds` | 需要现状判断时绑定结果。 |
| `rationale` | 说明为何采用、替代或拒绝，不改写来源陈述。 |

`INVESTIGATION_REQUIRED` 只允许出现在 working candidate；Solution Readiness Gate 不接受该状态。

#### `DesignDecision`

| 字段 | 约束 |
|---|---|
| `designDecisionId` | 稳定 ID。 |
| `affectedFeatureIds` | 至少一个。 |
| `decision` | 已选择方案。 |
| `alternativesRejected` | 至少说明真正被比较的替代方案；无替代时明确约束。 |
| `effectiveStartIds` | 设计基线；Greenfield 或 MISSING 可以为空。 |
| `investigationResultIds` | 只含支持或证伪本决定的结果。 |
| `responsibilityBoundary` | 项目、客户、平台或第三方责任。 |
| `failureImpact` | 当前前提错误时影响。 |

高 Materiality Design Decision 必须满足以下一项：

1. 有 `SUPPORTED` Investigation Result；
2. 明确 Greenfield/MISSING，方案不依赖现状复用；
3. 有获批 Assumption 或 Allowance；
4. 转为 Discovery，阻塞实施 SOW。

#### `GoLiveDisposition`

固定处理：生产范围、环境配置、部署/切换/回滚、数据迁移、生产验证、可观测性、运维移交、上线后支持、用户赋能、遗留退役。

每项只允许：

- `IN_SCOPE`：明确交付与责任；
- `CLIENT_PREREQUISITE`：明确客户输入、最晚时间和未满足后果；
- `OUT_OF_SCOPE`：有 Scope Boundary；
- `NOT_APPLICABLE`：有适用性理由。

不要求每项产生 Task；但 `IN_SCOPE` 必须在 Delivery/Estimate 中有闭包。

### 4.6 `DeliveryContract`

包含：

- `Story[]`；
- `AcceptanceCriterion[]`；
- `Integration[]`；
- `AssumptionRisk[]`。

#### `DeliveryDelta`

Delivery Delta 是每个 `IN_SCOPE` Feature 的目标结果与相关 Effective Start 之间的差值视图，不创建新的稳定顶级实体。Delivery Owner 将它编译为 Story 的 `gapRationale` 和 AC 的可观察结果：

```text
Feature outcome
  - Coverage / Effective Start
  + Carry-forward Commitment
  = Delivery Delta
```

`FULLY_COVERED` Feature 的 Delta 为空且不生成 Story；`MISSING` 必须明确无可用起点，不能制造占位 Effective Start。

#### `Story`

| 字段 | 约束 |
|---|---|
| `storyId` | 稳定 ID。 |
| `featureId` | 恰好一个 `IN_SCOPE` Feature。 |
| `name` | 唯一、非空、表达可交付结果。 |
| `deliveryOutcome` | 可独立交付、验收和结算。 |
| `effectiveStartIds` | 当前 Story 实际使用的起点；可以为空但必须声明 MISSING。 |
| `assumptionRiskIds` | 只含实际约束该 Story 的项。 |
| `uatRelevant` | 显式布尔值。 |

显式的 Story → Effective Start 关系是 Estimate context 选择的唯一依据。Estimate 不再保守加载全部 Effective Start。

#### `AcceptanceCriterion`

- 恰好属于一个 Story；
- 同一 Story 内 sequence 连续；
- 表达独立可观察结果；
- 引用 Delivery Delta 或明确 MISSING；
- 不描述 Task 实现步骤；
- 后续至少由一个 Trial Task 覆盖。

#### `Integration`

- 明确来源、目标、触发、方向、目的和责任；
- 至少关联一个 Story；
- `deliveryRequired=true` 时必须恰有一个 Integration Task；
- 只依赖现有集成而无项目侧工作时 `deliveryRequired=false`，不得生成 Task。

#### `AssumptionRisk`

| 字段 | 约束 |
|---|---|
| `assumptionRiskId` | 稳定 ID。 |
| `type` | `ASSUMPTION / RISK / CLIENT_PREREQUISITE`。 |
| `condition` | 假设成立条件、风险触发条件或客户必须提供的前置。 |
| `affectedStoryIds` | 至少一个 Story；BusinessScope 中的业务假设改为关联 Feature。 |
| `responsibleParty` | 负责确认、避免、接受或处理的角色/团队。 |
| `consequence` | 条件不成立或风险触发时对范围、估算或计划的结果。 |
| `handling` | 已批准的预防、缓解、变更控制或停止方式。 |
| `estimateImpact` | `NONE / BOUNDED / UNBOUNDED`。 |

`UNBOUNDED` 不能进入 Commitment Gate，必须形成 Discovery Requirement 或移除被影响实施范围。`BOUNDED` 必须引用 Allowance 或已经进入 Estimate 的明确 Task。Requirement Owner 拥有 Feature 级 Business Assumption；Delivery Owner 拥有 Story 级 Assumption/Risk，两者不得互相改写。

### 4.7 `TrialEstimate` 与 `EstimateBaseline`

#### `TrialEstimate`

Trial Estimate 使用候选 Delivery Contract 和当前模板目录生成，包含：

- `TrialTask[]`；
- `TrialFinding[]`；
- Story/AC/Integration 覆盖矩阵；
- 重复计价矩阵；
- Estimate readiness 结论。

Trial Task 与正式 Task 使用相同领域字段，但只能存在于 work/staging，不进入 SOW。

#### `TrialFinding`

| 字段 | 约束 |
|---|---|
| `findingId` | 当前 Trial run 唯一。 |
| `owner` | `DESIGN / DELIVERY / AS_IS / ESTIMATE / PLANNING`。 |
| `subjectIds` | 受影响的稳定或 candidate ID。 |
| `code` | 稳定机器 token。 |
| `problem` | 违反的领域不变量。 |
| `requiredDecision` | 上游必须作出的决定；不得直接给自由文本补丁。 |
| `blocking` | 影响可估算性时必须为 true。 |

#### `Task`

每个正式 Task：

- 恰好属于一个 Story；
- 恰好一个基础单元实例；
- 恰好一种 `新建 / 调整 / 接入复用`；
- 恰好一个 `S / M / L`；
- 覆盖同 Story 的至少一个 AC；
- `调整 / 接入复用` 必须引用 Story 允许的 Effective Start；
- `S / L` 必须有事实理由，`M` 不保存偏离理由；
- 不能使用 `X`；
- Integration Task 恰好引用一个 `deliveryRequired=true` Integration；
- 不保存计算人天。

#### `Allowance`

Allowance 不能绕过模板计算权威。它必须定义：

- 触发条件；
- 最大基础单元实例集合或最大实例数量；
- 每个实例允许的工作模式和复杂度上限；
- 责任方；
- 未触发时如何处理；
- 超出上限时的变更控制。

正式 Estimate 将上限范围编译为明确 Task；模板计算人天。无法用基础单元和有限实例表达的未知必须转为 Discovery。

### 4.8 `DeliveryPlan`

`MILESTONE_COMMITTED` 时包含：

- `ResourceRole[]`：角色、容量、可用窗口；
- `TaskDependency[]`：前置、后置和依赖类型；
- `ExternalWindow[]`：客户、平台、第三方、UAT 或发布窗口；
- `Milestone[]`：范围、完成条件和日期；
- `PlanningRisk[]`：触发、影响、负责人和处理。

不保存个人敏感信息；人员以角色或经批准的非敏感显示名表示。

每个 Milestone：

- 引用非空 Story/Task 集；
- 完成条件可观察；
- 所有前置依赖在时间上可满足；
- 所需角色容量不超过可用容量；
- 外部窗口与计划一致。

`EFFORT_ONLY` 时不生成虚假 Delivery Plan，只在 Commercial Packet 保存 `scheduleCommitment: NONE`。

### 4.9 `CommercialPacket`

Commercial Packet 是 Commitment Gate 的专用 Gate Packet。除通用 Gate Packet 字段外，它只投影并绑定：

- ProjectShell；
- BusinessScope；
- CurrentStateLedger candidate；
- TechnicalSolution candidate；
- DeliveryContract candidate；
- EstimateBaseline candidate；
- 条件性的 DeliveryPlan candidate；
- Assumption、Allowance、Discovery 和明确排除；
- Owner validation/review 结果；
- Gate Evaluation；
- 各对象 hash。

BA、TL、PM 的 Role Approval sidecar 分别引用同一 `packetSha256`，不写入 Packet 本身。Commercial Packet 不得新增或改写业务字段；摘要中出现而 Owner candidate 中不存在的决定必须使 Gate 失败。

## 5. 生命周期模型

### 5.1 Candidate 生命周期

每个 Owner 成果遵循：

```text
WORKING
  -> CANDIDATE
  -> REVIEWED
  -> APPROVED
  -> PUBLISHED
  -> STALE
```

| 状态 | 可变性 | 允许动作 |
|---|---|---|
| `WORKING` | 可变 | Owner 专业工作和局部修正。 |
| `CANDIDATE` | 不可原地改 | 计算 hash、机械验证、生成 review；修改必须产生新 candidate hash。 |
| `REVIEWED` | 不可变 | Reviewer 已对当前 hash PASS；可以请求角色批准。 |
| `APPROVED` | 不可变 | 所需角色已批准当前 packet hash；可以发布。 |
| `PUBLISHED` | 稳定 | 下游可以引用；只有 Owner 可产生替代版本。 |
| `STALE` | 只读 | 直接依赖变化；不得供新 Gate 使用。 |

状态不写回业务对象本身；由 sidecar/receipt 表达，避免稳定业务 JSON 混入流程元数据。

### 5.2 Gate 生命周期

```text
NOT_READY
  -> READY_FOR_REVIEW
  -> REVIEW_REQUIRED
  -> READY_FOR_APPROVAL
  -> APPROVED
  -> PUBLISHED

任一前置 hash 变化：
READY_FOR_REVIEW / REVIEW_REQUIRED / READY_FOR_APPROVAL / APPROVED / PUBLISHED
  -> STALE
```

`BLOCKED` 是评估结果，不是可继续前进的状态。解除 blocker 后必须重新计算 Gate Evaluation 和 packet hash，不能从旧 `BLOCKED` 或旧批准继续。

并非每个 Gate 使用全部生命周期状态：Setup/Compilation 由机械检查直接发布；Scope/Commitment 需要 Role Approval；Solution Readiness 在专业 Review 后结束于 `ESTIMATION_READY`，不进入 `APPROVED / PUBLISHED`。所有 Gate 都遵守相同 stale 规则。

### 5.3 原子批准与可恢复发布

Commitment Gate 同时绑定多个 Owner candidate，但不改变单一 Owner 写权限：

1. 各 Owner 在 staging 中形成 candidate；
2. Gate Packet 绑定所有 candidate 和直接输入；
3. Reviewer 与用户批准同一 packet hash；
4. publisher 只做 hash/check/publish；
5. 按固定技术顺序发布，receipt 最后写入；
6. 中断时只允许从已批准 packet 恢复，不重新解释业务；
7. 任一 candidate 字节变化使整个 packet 批准失效。

逻辑上这是一个批准集；物理实现可以是可恢复前向发布，不要求文件系统多文件事务。

### 5.4 Gate 工件模型

#### `DecisionDependency`

| 字段 | 约束 |
|---|---|
| `fromId` | 依赖方决定或事实。 |
| `toId` | 被依赖的稳定对象。 |
| `kind` | `SCOPE / EVIDENCE / BASELINE / SOLUTION / DELIVERY / ESTIMATE / PLAN`。 |
| `owner` | 声明该依赖的 Owner；必须拥有 `fromId`。 |
| `rationale` | 说明被依赖对象变化时为什么可能影响 `fromId`。 |

同一 `fromId + toId + kind` 只能出现一次。Dependency 方向固定为“依赖方 → 被依赖方”，Impact Closure 反向遍历消费者。

#### `GateEvaluation`

| 字段 | 约束 |
|---|---|
| `gateId` | `SETUP / SCOPE / SOLUTION_READINESS / COMMITMENT / COMPILATION`。 |
| `contractVersion` | 与目标插件合同一致。 |
| `inputBindings` | 按稳定名称绑定全部直接输入路径、业务版本和 SHA-256。 |
| `subjectIds` | 本次 Gate 实际判断的业务对象。 |
| `checks` | 每项包含稳定 code、`PASS / BLOCKED` 和受影响 ID。 |
| `blockingFindingIds` | outcome 为 `BLOCKED` 时非空。 |
| `outcome` | `READY_FOR_REVIEW / BLOCKED`。 |

Gate Evaluation 不包含自由裁量批准。任一机械 check 为 `BLOCKED` 时 outcome 必须为 `BLOCKED`，Stage 和 Reviewer 都不能改写。

#### `GatePacket`

| 字段 | 约束 |
|---|---|
| `algorithm` | 目标合同固定算法 token。 |
| `gateId` | 对应唯一 Gate。 |
| `inputBindings` | 与 Gate Evaluation 原字节一致。 |
| `candidateBindings` | 按 Owner 稳定名称绑定 candidate hash。 |
| `gateEvaluationHash` | 绑定机械判断。 |
| `reviewBindings` | 绑定专业 review、risk summary 和 Reviewer 结论。 |
| `openNonBlockingRiskIds` | 只含已处理且不阻塞的风险。 |
| `packetSha256` | 对 canonical packet 内容计算；字段自身不参与递归计算。 |

Packet 不保存角色批准；批准 sidecar 引用 `packetSha256`，避免自引用。Candidate、Evaluation、review 或输入任一字节变化都产生新 packet。

#### `RoleApproval`

| 字段 | 约束 |
|---|---|
| `gateId` | 角色正在批准的 Gate。 |
| `role` | `BA / TL / PM`。 |
| `packetSha256` | 完整精确 hash。 |
| `decision` | `APPROVED / REJECTED`。 |
| `decisionDate` | 用户确认的 ISO 日期。 |
| `responsibility` | 当前角色实际承担的批准范围，必须与 Gate 合同一致。 |

缺少必需角色、批准不同 packet、角色责任与 Gate 不符或任一 `REJECTED` 都不能进入 `APPROVED`。

#### `OwnerReceipt`

Owner receipt 绑定 Owner、合同版本、named inputs、stable output、正式 review、Gate Packet 和 Role Approval。Receipt 只证明当前发布与批准闭包一致，不重放 Owner 业务判断，也不复制业务字段。

## 6. Phase 输入输出合同

### 6.1 Phase 1：初始化

#### 输入

| 输入 | 必选 | 约束 |
|---|---:|---|
| `projectId` | 是 | 稳定合法 ID。 |
| `projectName` | 是 | 非空。 |
| 插件 manifest/lock | 是 | 与目标合同版本一致。 |
| SOW v1.3 模板 | 是 | 可以复读，计算权威不被复制。 |
| `commitmentMode` | 是 | `EFFORT_ONLY / MILESTONE_COMMITTED`。 |

#### 输出

- `ProjectShell.candidate`；
- runtime/template preflight；
- Setup Gate Evaluation。

#### 禁止输出

- Repo、往期 SOW、业务需求、As-Is、Design、Story、Task；
- 对 Greenfield/Brownfield 的判断。

### 6.2 Phase 2：定义商业范围

#### 输入

| 输入 | 必选 | 约束 |
|---|---:|---|
| 已发布 `ProjectShell` | 是 | 当前且未 stale。 |
| 获授权业务来源 | 是 | 至少一个来源或用户直接业务决定。 |
| 合同/招标/会议材料 | 条件 | 用户提供时登记并绑定。 |
| BA 回答 | 条件 | 只回答会改变业务范围的问题。 |

#### 输出

- `BusinessScope.candidate`；
- `TechnicalInput[]` 队列；
- Scope question/decision log；
- Scope Gate Packet。

#### 禁止输出

- TECHNICAL requirement；
- Current-State Fact；
- 目标架构或 Task；
- 对技术输入的方案采用决定。

### 6.3 Phase 3：塑造交付方案

#### 输入

| 输入 | 必选 | 约束 |
|---|---:|---|
| 已发布 `ProjectShell` | 是 | 当前模板和 commitment mode。 |
| 已发布 `BusinessScope` | 是 | Scope Gate receipt 当前。 |
| `TechnicalInput[]` | 条件 | 来源中存在时全部处置。 |
| 授权 Repo/文档/配置 | 条件 | 仅按 Investigation Request 读取。 |
| 往期 SOW | 条件 | 只处理与当前 Feature 重叠承诺。 |
| 负责人回答 | 条件 | 只回答定向问题。 |

#### 内部循环输出

- Coverage candidate；
- Design Hypothesis；
- Investigation Request/Result；
- `CurrentStateLedger.candidate`；
- `TechnicalSolution.candidate`；
- `DeliveryContract.candidate`；
- Solution Readiness Gate Evaluation。

#### Phase 输出

一个 `ESTIMATION_READY` candidate set，绑定：

- Current State；
- Technical Solution；
- Delivery Contract；
- 仍适用的 Assumption/Risk；
- 无未处理高影响 Unknown；
- 完整直接依赖。

这些 Candidate 尚未作为稳定输出发布。

### 6.4 Phase 4：形成可承诺估算

#### 输入

| 输入 | 必选 | 约束 |
|---|---:|---|
| `ESTIMATION_READY` candidate set | 是 | hash 当前。 |
| SOW v1.3 模板目录投影 | 是 | 不复制人天和公式。 |
| 资源与窗口输入 | `MILESTONE_COMMITTED` 时是 | 角色、容量、依赖和外部窗口。 |
| 商业假设/Allowance | 条件 | 已结构化且有责任方。 |

#### 内部循环输出

- Trial Estimate；
- Trial Findings；
- 修正后的 Owner candidate set；
- `EstimateBaseline.candidate`；
- 条件性的 `DeliveryPlan.candidate`；
- Commercial Packet candidate。

#### Phase 输出

Commitment Gate 通过后发布：

- `CurrentStateLedger`；
- `TechnicalSolution`；
- `DeliveryContract`；
- `EstimateBaseline`；
- 条件性的 `DeliveryPlan`；
- 各 Owner receipt；
- 已批准 Commercial Packet。

### 6.5 Phase 5：编译并签署 SOW

#### 输入

| 输入 | 必选 | 约束 |
|---|---:|---|
| 当前 `ProjectShell` | 是 | template fingerprint 匹配。 |
| 已批准 Commercial Packet | 是 | 角色批准绑定同一 hash。 |
| 五个专业 Owner stable/receipt | 是 | 与 Packet named inputs 完全匹配。 |
| 条件性的 Planning stable/receipt | 条件 | commitment mode 要求时存在。 |
| 项目模板 | 是 | 与 ProjectShell 当前 hash 一致。 |

#### 输出

- 内容寻址 `SowPackage`；
- `sow.xlsx`；
- manifest；
- Packet 与全部 stable/review/receipt 副本；
- Compilation Gate receipt；
- 角色签署确认。

#### 禁止输出

- 新的 Requirement、Current-State Fact、Design、Story、AC、Task、Allowance 或 Plan；
- 与模板不同的公式或人天规则。

### 6.6 当前能力到目标 Phase 的映射

| 当前能力 | 目标位置 | 变化 |
|---|---|---|
| `setup` | Phase 1 | 保持机械化；新增 commitment mode。 |
| `analyze-requirement` | Phase 2 / Requirement Owner | 只发布 BusinessScope 和 Technical Input 队列。 |
| `analyze-as-is` | Phase 3 / Decision Investigation Module + As-Is Owner | 从完整前置阶段改为按 Design/Estimate 决定调用。 |
| `generate-design` | Phase 3 / Design Owner | 与 As-Is、Delivery candidate 在 Gate 2 前共同收敛。 |
| `generate-story` | Phase 3 / Delivery Owner | Story/AC 先形成 candidate，通过 Trial Estimate 后才发布。 |
| `generate-task` | Phase 4 / Estimate Owner | 先产生 work-only Trial Estimate；Gate 3 后发布 EstimateBaseline。 |
| 人员与迭代规划 | Phase 4 / Planning Owner | 从流程外补充变成 commitment mode 驱动的条件性稳定 Owner。 |
| `generate-sow` | Phase 5 / SOW Compiler | 只编译和复读已批准 Commercial Packet。 |
| `reconcile` | 跨 Phase Impact Coordinator | 从固定阶段后缀改为 Decision Dependency 影响闭包；不拥有业务数据。 |

该映射描述 clean cutover 后的责任归属，不要求保留当前 Skill 名作为 alias。

## 7. Gate 合同

### 7.1 Gate 0：Setup Gate

#### 进入条件

- 目标目录可安全写入；
- 项目标识由用户提供；
- 插件资产可读取。

#### PASS 条件

1. ProjectShell Schema 有效；
2. 项目身份与已有项目不冲突；
3. 插件合同、锁文件和运行时一致；
4. 模板为 SOW v1.3 且可 round-trip；
5. 受管目录无越界或链接穿越；
6. commitment mode 明确。

#### BLOCK 条件

- 身份冲突；
- 不支持的合同或模板；
- runtime/bootstrap 失败；
- 路径不安全；
- 模板无法复读。

#### PASS 输出

发布 `ProjectShell`。失败不得留下半发布项目。

### 7.2 Gate 1：Scope Gate

#### 进入条件

- Setup Gate 当前；
- 至少一个获授权业务来源或用户直接业务决定；
- Requirement candidate 已形成。

#### 机械 PASS 条件

1. Epic/Feature ID 和名称唯一；
2. 每个 Feature 恰好一个 scope status；
3. 每个 `IN_SCOPE` Feature 有业务 outcome 和 acceptance intent；
4. 每个来源中的决策相关业务陈述被消费、排除或形成问题；
5. 每个 Technical Input 有 source anchor 和受影响 Feature；
6. BUSINESS 与 Technical Input 没有被错误混为 TECHNICAL requirement；
7. 不含凭据、绝对路径或客户原文复制。

#### 专业 PASS 条件

1. BA 确认业务结果和范围；
2. 范围内外及延期边界无冲突；
3. 会改变商业范围的关键问题已解决；
4. 仍存在的业务假设有触发、责任和未满足后果；
5. Design 可以直接消费 Technical Input 队列，不需重新通读全部来源来发现遗漏。

#### BLOCK 条件

- Feature 无法独立纳入、排除或验收；
- 来源冲突会改变范围但未决定；
- “沿用/不替换/仅集成”等边界未映射受影响 Feature；
- Technical Input 无来源或影响对象；
- BA 未批准当前 packet hash。

#### PASS 输出

发布 `BusinessScope` 和 Scope receipt。任何业务语义修改使 Gate stale。

### 7.3 Gate 2：Solution Readiness Gate

这是进入 Task 试拆分的内部专业门禁，不发布稳定 Design/Delivery，也不要求用户承担最终商业承诺。

#### 进入条件

- Scope Gate 当前；
- Current State、Technical Solution 和 Delivery Contract candidate 已形成；
- 所有 Investigation Request 已有 Result 或明确取消理由。

#### 机械 PASS 条件

1. 每个 `IN_SCOPE` BUSINESS Feature 恰有一条 Coverage；
2. 每个 Feature 恰有一个 Scope Decision；
3. `FULLY_COVERED` 只引用 COMPLETE Coverage 和 Evidence；
4. 每个 `IN_SCOPE` Feature 有 Design 覆盖和至少一个 Story；
5. 每个 Story 恰属一个 Feature，并至少有一个 AC；
6. Story 显式引用其 Effective Start 或 MISSING；
7. 每个高 Materiality Design Decision 有 Investigation/Greenfield/Assumption/Allowance/Discovery 处理；
8. 每个 Technical Input 有 `ADOPTED / REPLACED / REJECTED / INVESTIGATION_REQUIRED` 处置，且不得残留 `INVESTIGATION_REQUIRED`；
9. 十项 Go-live concern 恰各一条 disposition；
10. 所有引用闭包有效，无 orphan Fact、Evidence、Effective Start 或 Decision；
11. 稳定候选 As-Is 实体都被一个当前决定消费。

#### 专业 PASS 条件

1. 方案与业务范围一致；
2. Delivery Delta 能解释 Story 的必要性；
3. AC 可观察且不描述实现步骤；
4. Integration、迁移、生产、发布、验证、运维移交和支持责任明确；
5. 无未处理、可能推翻范围或估算的 Unknown；
6. TL 确认方案可进入估算，BA 确认 Delivery candidate 未改变商业意图。

#### BLOCK 条件与回退

| Blocker | 返回 Owner |
|---|---|
| Coverage/Effective Start/Evidence 不足 | As-Is |
| Technical Input 未处置、方案缺口 | Design |
| Story/AC 不可验收 | Delivery |
| 商业范围本身不明确 | Requirement，Scope Gate stale |
| 高影响未知无上限 | 形成 Discovery Requirement，阻塞实施 SOW |

#### PASS 输出

产生 hash-bound `ESTIMATION_READY` candidate set；不发布稳定专业数据。

### 7.4 Gate 3：Commitment Gate

#### 进入条件

- Solution Readiness Gate 当前；
- Trial Estimate 已运行；
- 所有 blocking Trial Finding 已关闭；
- Estimate 和条件性 Plan candidate 已形成；
- Commercial Packet 已绑定所有 candidate。

#### 机械 PASS 条件

1. 每个 Story 至少一个 Task；
2. 每个 AC 至少由一个同 Story Task 覆盖；
3. 每个 Task 恰好一个基础单元、工作模式和复杂度；
4. 没有 `X` 复杂度；
5. `调整 / 接入复用` 引用 Story 允许的 Effective Start；
6. 每个 `deliveryRequired=true` Integration 恰好一个 Integration Task；
7. 发布切换、迁移、诊断/整改不存在合同定义的重复计价；
8. Allowance 可以展开为有限 Task 且不保存自由人天；
9. `MILESTONE_COMMITTED` 时 Plan 完整且容量/依赖/窗口可行；
10. `EFFORT_ONLY` 时没有日期或里程碑承诺；
11. Commercial Packet 不含 Owner candidate 之外的新业务字段；
12. Reviewer、candidate、risk、Gate Evaluation 和 input hash 全部匹配。

#### 专业 PASS 条件

1. TL 批准 Technical Solution、Task、工作模式、复杂度和技术责任；
2. BA 批准 Story/AC 仍忠实表达商业范围；
3. PM 批准责任、资源、依赖和条件性里程碑；
4. Assumption、Allowance、客户前置和排除有明确触发与后果；
5. 三个角色批准同一 Commercial Packet hash；
6. 没有未关闭 blocking Finding。

#### BLOCK 条件与回退

| Blocker | 返回位置 |
|---|---|
| Task 对象或计数不明确 | Design 或 Delivery，重跑 Gate 2 |
| AC 无 Task 覆盖 | Delivery 或 Estimate |
| 工作模式无现状依据 | As-Is 或 Estimate |
| Integration 漏失或责任不清 | Design/Delivery |
| 复杂度只能为 X | Design/As-Is/Delivery |
| 资源或窗口不可行 | Planning；若需改范围则返回 Scope/Design |
| 未知无法界定上限 | Discovery，阻塞实施 SOW |
| 模板组合不适用 | Estimate；不得手写人天绕过 |

#### PASS 输出

- 发布 `CurrentStateLedger`、`TechnicalSolution`、`DeliveryContract` 和 `EstimateBaseline`；
- 按 commitment mode 发布或省略 Delivery Plan；
- 发布 Owner receipt；
- 发布获批 Commercial Packet。

### 7.5 Gate 4：Compilation Gate

#### 进入条件

- Commitment Gate 当前且已发布；
- 所有 Owner stable/review/receipt 与 Commercial Packet hash 匹配；
- 模板 fingerprint 当前。

#### PASS 条件

1. 输入不存在 missing、invalid、stale 或 unsupported；
2. 所有稳定 ID 可以投影为唯一非空名称；
3. 工作簿 Table、公式原型、样式、保护、下拉和跨 Sheet 引用复读一致；
4. 普通文本不被解释为公式；
5. package manifest 覆盖全部规定文件及 hash；
6. 相同输入产生相同 generation fingerprint 和 package；
7. 输出没有任何 Commercial Packet 之外的新业务决定。

#### BLOCK 条件

- Owner receipt stale；
- 模板变更未重新通过 Commitment Gate 的模板兼容检查；
- 名称冲突或引用无法投影；
- 工作簿复读失败；
- package ID 内容冲突；
- 生成器试图补充上游业务字段。

#### PASS 输出

发布内容寻址 `SowPackage` 和 Compilation receipt。

### 7.6 最终签署确认

签署确认不是新的业务 Gate。TL、BA、PM 只确认：

- package ID；
- Commercial Packet hash；
- 工作簿可打开；
- 生成内容与已批准 packet 一致；
- 对应角色的签署版本明确。

发现业务内容错误时回到真实 Owner 和受影响 Gate，不直接修改工作簿。

## 8. Finding 与回退合同

### 8.1 Finding 分类

| 分类 | 含义 | 默认 Owner |
|---|---|---|
| `SCOPE_AMBIGUOUS` | Feature 范围或业务结果不明确 | Requirement |
| `BASELINE_UNSUPPORTED` | Coverage/Effective Start 缺少依据 | As-Is |
| `DESIGN_PREMISE_FALSIFIED` | 方案依赖前提被证伪 | Design |
| `DELIVERY_NOT_ACCEPTABLE` | Story/AC 不能独立验收 | Delivery |
| `DELIVERY_NOT_ESTIMABLE` | Story 无法拆成有限 Task | Delivery/Design |
| `WORK_MODE_UNSUPPORTED` | 调整/复用无相关起点 | As-Is/Estimate |
| `TASK_DUPLICATED` | 同一工作重复计价 | Estimate |
| `INTEGRATION_CLOSURE_MISSING` | Integration 与 Task 闭包不完整 | Design/Delivery/Estimate |
| `PLAN_INFEASIBLE` | 容量、依赖或窗口不可行 | Planning |
| `UNKNOWN_UNBOUNDED` | 未知无法形成安全上限 | Discovery |
| `PACKAGE_MISMATCH` | 工作簿与批准 packet 不一致 | SOW Compiler |

### 8.2 回退原则

1. Finding 指向最早拥有错误语义的 Owner，而不是最接近报错的脚本。
2. 下游 Owner 不附带上游字段 patch；只描述违反的不变量和所需决定。
3. 修复生成新 candidate hash；旧 Review、Approval 和 Gate Packet 失效。
4. 只重跑受影响的直接消费者和传递闭包。
5. 商业范围变化必须重新通过 Scope Gate；名称或 anchor 变化不自动升级为范围变化。
6. 任何业务失败都不能在 SOW Compiler 中修复。

### 8.3 Task 试拆分反馈示例

```text
Finding: DELIVERY_NOT_ESTIMABLE
subjects: story-customer-migration
problem: 同一 Story 同时包含客户主数据迁移和生产切换，具有不同对象、责任和验收时点。
requiredDecision: Delivery Owner 将其拆为可独立验收的 Story，或由 Design Owner证明它们构成一个不可分交付窗口。
owner: DELIVERY
blocking: true
```

Estimate Owner 不直接拆分 Story；Delivery 修复后重新形成 candidate，再运行 Solution Readiness 和 Trial Estimate。

## 9. 依赖与变更模型

### 9.1 允许的直接依赖

| From | 可以直接依赖 |
|---|---|
| Coverage | Business Feature、Effective Start、Commitment、Uncertainty |
| Effective Start | Current-State Fact、Commitment、Evidence |
| Design Decision | Feature、Effective Start、Investigation Result、Technical Input |
| Story | Feature、Scope Decision、Design Decision、Effective Start、Assumption/Risk |
| AC | Story、Delivery Delta、Commitment |
| Integration | Story、Design Decision、Current-State Fact |
| Task | Story、AC、Effective Start、Integration、Base Unit |
| Delivery Plan | Task、Story、外部窗口、角色容量 |
| Commercial Packet | 全部 Owner candidate、Assumption、Allowance、Gate Evaluation |
| SOW Package | Commercial Packet、Owner stable/receipt、模板 |

禁止反向业务依赖：

- Business Feature 不依赖 Design/Story/Task；
- Current-State Fact 不依赖 Design/Task；
- Story/AC 不依赖正式 Task；Task 试拆分只是 Gate 证据；
- 模板不依赖项目业务数据。

### 9.2 变更类别

| 类别 | 示例 | 重新打开 |
|---|---|---|
| `PRESENTATION_ONLY` | 不改变身份的名称、格式 | 直接投影和 Compilation Gate |
| `EVIDENCE_REBIND` | anchor/hash 更新，事实语义不变 | As-Is receipt、直接引用验证、Compilation |
| `BASELINE_CHANGE` | Effective Start 能力变化 | 引用它的 Design/Story/Task/Plan |
| `SOLUTION_CHANGE` | Design Decision 或责任变化 | 关联 Story/AC/Task/Plan |
| `DELIVERY_CHANGE` | Story/AC/Integration 变化 | Trial Estimate、Estimate、Plan |
| `ESTIMATE_CHANGE` | Task、工作模式、复杂度变化 | Plan、Commercial Packet、Package |
| `PLAN_CHANGE` | 资源、窗口、里程碑变化 | Commercial Packet、Package |
| `SCOPE_CHANGE` | Feature 语义或范围变化 | Scope Gate 及相关完整闭包 |

### 9.3 Gate stale 规则

- Gate 任一 named input hash 变化立即 stale；
- 语义变化只要求重开 Impact Closure 内对象，但新的 Gate Packet 必须重新绑定未变化对象的当前 hash；
- `PRESENTATION_ONLY / EVIDENCE_REBIND` 不自动创建专业 finding；
- Reviewer 必须检查变更分类是否低估，不能由修改 Owner 单方面声明无影响；
- 已发布 SOW Package 永不原地覆盖；新批准产生新的 package ID。

## 10. 端到端场景

### 10.1 Greenfield，无代码库

1. Scope Gate 批准三个 `IN_SCOPE` Feature。
2. Coverage 全部为 `MISSING`。
3. 九 Topic 使用有依据的 `BOUNDARY_DECLARED / NOT_APPLICABLE`，不制造 Current-State Fact。
4. Design 以 Greenfield 明确处理高 Materiality 决定，不创建虚假 Evidence。
5. Story 显式声明 MISSING 起点。
6. Trial Task 使用“新建”；无需 work-mode Evidence。
7. Commitment Gate 可以通过。

预期：没有 Repo 不是 blocker；缺少现状不会自动变成无限问卷。

### 10.2 Brownfield，调整现有能力

1. Feature Coverage 为 `PARTIAL`。
2. Investigation Request 只询问现有客户档案服务是否包含可调整的目标对象。
3. As-Is 返回 `SUPPORTED`、一个 Fact、一条 Evidence 和一个 Effective Start。
4. Story 只引用该 Effective Start。
5. Trial Task 使用“调整”，并引用同一 Effective Start。
6. 不相关模块、CI、日志和数据表不进入稳定 Ledger。

预期：从调查问题到工作模式形成最短闭包。

### 10.3 接入复用

1. Investigation 证明既有身份平台保持不变。
2. Design 明确项目只负责应用注册、权限映射和专项验证。
3. Integration 标记项目侧工作必需。
4. Story/AC 描述接入后的可观察结果。
5. Task 使用“接入复用”，工作范围只包含项目侧责任。

预期：不会把依赖平台本身的建设或运营重复计价。

### 10.4 高影响未知，无安全上限

1. 数据量、质量和迁移来源均未知。
2. 不同答案会改变迁移 Task 数量、复杂度和停机方案。
3. 无法用有限基础单元实例定义 Allowance。
4. Gate 2 生成 Discovery Requirement 并阻塞实施 SOW。
5. Discovery 明确要交付数据剖析、迁移策略、停机方案和可估算输入。

预期：系统不通过风险倍率或自由人天猜估。

### 10.5 高影响未知，有有限上限

1. 最多存在三个外部租户需要配置，但具体数量尚未确认。
2. 每个租户对应一个已定义基础单元实例，工作模式和复杂度上限明确。
3. Allowance 编译为最多三个明确 Task，由模板计算。
4. Commercial Packet 写明触发、未触发和超出三项的变更控制。

预期：Allowance 不绕过模板计算权威。

### 10.6 Task 试拆分发现 Story 过大

1. Gate 2 产生一个包含迁移、接口和切换的 Story candidate。
2. Trial Estimate 返回 `DELIVERY_NOT_ESTIMABLE`。
3. Delivery 将 Story 拆为独立验收对象；Design 补充共享切换决定。
4. Gate 2 重新通过后重跑 Trial Estimate。
5. 没有稳定 Story/AC 被中途发布。

预期：正常收敛发生在稳定批准前，不触发正式 reconciliation。

### 10.7 里程碑不可行

1. Estimate 人天合法，但客户 UAT 只在目标日期后可用。
2. Planning 返回 `PLAN_INFEASIBLE`。
3. PM 不能直接移动业务范围或修改人天。
4. 用户选择调整里程碑、改为 `EFFORT_ONLY`，或返回 Scope/Design 分期。
5. 选择结果进入新 Commercial Packet。

预期：正确人天不会被误认为可承诺日期。

### 10.8 Evidence anchor 修正，语义不变

1. 已批准 Fact 的文件 anchor 因文档重排变化，内容语义不变。
2. 变更分类为 `EVIDENCE_REBIND`。
3. As-Is 更新 Evidence binding；Reviewer 检查分类。
4. 不重开无关 Design、Story、Task 专业判断。
5. 重新生成 receipt、Commercial Packet binding 和新 SOW Package。

预期：保持追溯完整，不进行固定后缀全量重审。

## 11. 可测验收条件

### 11.1 模型不变量

1. 每个 `IN_SCOPE` Business Feature 恰有一条 Coverage 和 Scope Decision。
2. 每个稳定 Current-State Fact 至少被一个 Effective Start、Coverage、Design Decision 或 Task 工作模式引用。
3. 每个高 Materiality Design Decision 有支持性处理或阻塞实施 SOW。
4. 每个 Story 恰属一个 Feature，并显式引用相关 Effective Start 或 MISSING。
5. 每个 AC 至少由一个同 Story Trial Task 和正式 Task 覆盖。
6. 每个正式 Task 恰好一个基础单元、工作模式和复杂度，且不为 `X`。
7. `调整 / 接入复用` Task 的 Effective Start 必须属于同 Story 允许集合。
8. 每个需要交付的 Integration 恰好一个 Integration Task。
9. Allowance 可以确定性展开为有限 Task，且不保存自由人天。
10. `MILESTONE_COMMITTED` 必须存在通过可行性检查的 Delivery Plan；`EFFORT_ONLY` 不得含日期承诺。

### 11.2 调查收敛

1. `hypothesis` 模式下，没有 Decision/Feature/Materiality 绑定的 Investigation Request 被拒绝。
2. stop rule 满足后不继续扫描同一事实族。
3. 非 Material 事实不能进入稳定 CurrentStateLedger。
4. Greenfield 可以用零 Current-State Fact 通过 Gate 2。
5. Task context 只包含 Story 显式引用的 Effective Start；不存在“为安全加载全部”路径。
6. 未处理高影响 `UNKNOWN` 不能进入 Commitment Gate。

### 11.3 Gate 行为

1. 每个 Gate 对缺失、无效、stale、unsupported 输入 fail closed。
2. Candidate 任一字节变化使 Reviewer 和 Approval binding 失效。
3. Gate 只发布自身定义的稳定输出。
4. Gate 失败不修改任何已发布稳定业务数据。
5. Commitment Gate 的所有角色批准绑定同一 Commercial Packet hash。
6. Compilation Gate 不运行上游业务分析或 validator，不补充缺失业务字段。

### 11.4 反馈与返工

1. Trial Finding 只能由声明 Owner 修复。
2. Estimate Owner 无法修改 Story/AC；Planning Owner 无法修改 Task/Estimate。
3. `PRESENTATION_ONLY / EVIDENCE_REBIND` 不触发无关专业重审。
4. `SCOPE_CHANGE` 必须重新通过 Scope Gate。
5. Impact Closure 外稳定对象保持原字节。
6. 任何新发布 Package 使用新内容寻址 ID，不覆盖旧 Package。

### 11.5 交付与兼容

1. SOW v1.3 模板、基础人天、复杂度、公式和取整规则原字节或合同保持不变。
2. 插件 0.2.0 不静默读取 0.1.0 receipt/packet 作为当前合同。
3. 插件独立复制后不读取 marketplace 根目录或其他插件。
4. 稳定数据和 package 不包含凭据、客户原文、源码、完整工具输出或本机绝对路径。
5. 相同 Commercial Packet、Owner stable/receipt 和模板产生相同 SowPackage。

## 12. 实现约束

1. 先固定逻辑 Schema 和 Gate diagnostics，再修改 Skill 文案；禁止只靠 prompt 表达核心门禁。
2. 每个 Owner 继续 Skill-local 拥有业务 Schema、renderer、validator 和测试。
3. 插件级 runtime 只实现 Owner-agnostic 的状态、hash、patch、Gate Packet、影响闭包和 project I/O。
4. `Decision Investigation` 可以内部使用搜索、语言工具、CodeGraph、文档或问卷 Adapter，但这些 Adapter 不进入外部 interface。
5. 两种以上真实调查 Adapter 存在前，不为每种工具创建公共 seam。
6. Gate Evaluation 返回稳定 diagnostics；Stage 不扫描实现源码预测失败。
7. 稳定业务对象不保存流程状态；状态由 receipt/sidecar 表达。
8. Commercial Packet 是批准投影，不成为第八份可被下游改写的业务真相。
9. 生成器继续只读取当前批准稳定数据和模板，不读取 Owner Schema、fixture、test 或工作目录猜测业务语义。
10. 实现必须 clean cutover 全部调用方、测试、fixture、文档和发布元数据，不保留旧阶段 alias。
