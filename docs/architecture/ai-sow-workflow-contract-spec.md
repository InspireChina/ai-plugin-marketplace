# AI SOW 决策驱动工作流详细合同（历史草案）

> 状态：已被
> [AI SOW Git 驱动、按需现状调查工作流优化方案](ai-sow-workflow-refactor-design.md)
> 取代；仅保留上一轮方案的分析记录，不得作为 0.2.0 实施合同。

- 原状态：设计提案；未实施
- 日期：2026-08-31
- 原目标插件合同：0.2.0
- SOW 计算标准：继续使用 v1.3

## 1. 文档目的

本文把上位设计细化为可实现、可验证的逻辑合同，固定：

- 领域对象、关系、Owner 和稳定性；
- 五个目标阶段的精确输入和输出；
- 五个门禁及最终签署确认的进入、通过、阻塞和失效条件；
- Candidate、Review、Approval、Publish 和 Stale 状态转换；
- Design、Delivery、Estimate 和 Planning 的反馈路径；
- Context、Claim、Subject Review 与 Agent 的最小信息流；
- 类型化引用派生的依赖闭包和 Evidence rebind；
- Greenfield、Brownfield、Discovery、计划不可行与定量浪费场景。

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
| Gate Packet | 绑定门禁输入、候选结果、风险和 Reviewer 结论的不可变审查对象；角色初次批准通过 sidecar 同时引用完整 Packet hash 和业务语义 hash。 |
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
| Technical Solution | Delivery Disposition、Design Item、Architecture Delta、Design Decision、TECHNICAL requirement 和上线责任的集合。 |
| Delivery Contract | Story、AC、Integration、Assumption/Risk 及其责任边界。 |
| Trial Estimate | 用于证明 Delivery Contract 可估算的 work-only Task 试拆分，不是正式 Estimate。 |
| Estimate Baseline | 已批准 Task、基础单元、工作模式、复杂度、理由和估算关系。 |
| Planning Disposition | 本次承诺模式、早期硬约束及条件性的 Delivery Plan；由 Planning Owner 拥有。 |
| Allowance | 对有上限未知的获批处理；必须表现为可枚举、可按模板计价的最大工作范围，不保存自由人天。 |
| Discovery Requirement | 无法安全进入实施估算时，独立调研 SOW 必须回答的问题、交付物和退出条件。 |
| Commercial Packet | 对同一范围、方案、Delivery Contract、Estimate、Plan、假设和例外的统一商业批准对象。 |
| SOW Package | 由 Commercial Packet 和当前 Owner receipt 确定性编译出的工作簿、自包含数据和 manifest。 |

## 3. 聚合与 Owner

### 3.1 稳定聚合

目标合同包含八个稳定业务聚合和一个最终交付聚合：

| 聚合 | 唯一 Owner | 必选 | 首次稳定发布时点 |
|---|---|---:|---|
| `ProjectShell` | Setup Module | 是 | Setup Gate |
| `BusinessScope` | Requirement Owner | 是 | Scope Gate |
| `CurrentStateLedger` | As-Is Owner | 是 | Commitment Gate |
| `TechnicalSolution` | Design Owner | 是 | Commitment Gate |
| `DeliveryContract` | Delivery Owner | 是 | Commitment Gate |
| `EstimateBaseline` | Estimate Owner | 是 | Commitment Gate |
| `PlanningDisposition` | Planning Owner | 是 | Commitment Gate |
| `SowPackage` | SOW Compiler | 是 | Compilation Gate |

`PlanningDisposition` 始终保存本次商业承诺是 `EFFORT_ONLY` 还是 `MILESTONE_COMMITTED`；只有后者包含 `DeliveryPlan`。`CommercialPacket` 是跨聚合批准投影，不拥有新的业务事实。它只引用并绑定上述 Owner candidate 和风险处置；角色批准绑定其业务语义 hash，完整技术 Packet 另有精确 hash。

### 3.2 Work-only 对象

以下对象不作为跨阶段长期稳定业务数据：

- Design Hypothesis；
- Investigation Request；
- 未被批准决定引用的 Investigation Result；
- Planning Premise；
- Trial Estimate；
- Trial Finding；
- Gate Evaluation；
- Gate Review Receipt；
- Owner Validation Receipt；
- Claim Verification Receipt；
- Context Bundle、context fragment、claims、risk summary；
- Reviewer sidecar；
- Packet Reviewer Judgment；
- Approval sidecar；
- Evidence Rebind Attestation；
- Impact analysis、Gate Run Metrics 和发布 staging。

被最终批准决定引用的 Investigation Result，其身份、问题、结论、Evidence 和影响必须由 As-Is Owner 编译进 `CurrentStateLedger`。未被引用的调查过程留在 work 目录，不进入稳定交接。

### 3.3 写权限

| Owner | 可以写 | 只读 | 禁止写 |
|---|---|---|---|
| Requirement | `BusinessScope` candidate/stable | Source、ProjectShell | Current State、Design、Delivery、Estimate、Planning |
| As-Is | `CurrentStateLedger` candidate/stable、`DiscoveryRequirement` | BusinessScope、授权 Evidence | Design、Delivery、Estimate、Planning |
| Design | `TechnicalSolution` candidate/stable | BusinessScope、Current State candidate、Technical Input 原文 anchor | BusinessScope、Current State、Delivery、Estimate |
| Delivery | `DeliveryContract` candidate/stable | BusinessScope、Current State、Technical Solution | Design、Estimate、Planning |
| Estimate | Trial Estimate、`EstimateBaseline` candidate/stable、`Allowance` | Delivery、Design、Current State、模板目录 | Story、AC、Design、模板计算规则 |
| Planning | Planning Premise、`PlanningDisposition` candidate/stable | Estimate、Delivery、项目约束 | Task、基础人天、Story/AC、BusinessScope |
| SOW Compiler | `SowPackage` | 全部已批准稳定聚合、模板 | 所有上游业务聚合 |

Owner 发现上游错误时只能返回结构化 Finding，不能直接修复上游。

## 4. 领域对象模型

### 4.1 关系总览

```text
ProjectShell
  └─ BusinessScope
       ├─ BusinessFeature
       │    ├─ Coverage ── EffectiveStart ── CurrentStateFact ── EvidenceRef
       │    ├─ DeliveryDisposition
       │    ├─ DesignDecision
       │    └─ Story ── AcceptanceCriterion
       │                 └─ Task ── BaseUnit / WorkMode / Complexity
       └─ TechnicalInput
            └─ TechnicalInputDisposition ── DesignDecision

DesignDecision ── InvestigationResult
InvestigationResult ── requestId（仅审计） / decisionId / EvidenceRef
Story ── Integration ── IntegrationTask
Task / Milestone ── PlanningDisposition
Uncertainty ── Handling ── Assumption | Allowance | DiscoveryRequirement | BLOCKED

BusinessScope
+ CurrentStateLedger
+ TechnicalSolution
+ DeliveryContract
+ EstimateBaseline
+ PlanningDisposition
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

ProjectShell 不保存范围、日期、里程碑、资源或 `commitmentMode`。这些属于专业 Owner 的项目约束与商业承诺，改变时不得使 Setup 或 Scope Gate stale。

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

每个 `IN_SCOPE` Feature 必须进入 Coverage、DeliveryDisposition 和 Delivery Contract；`OUT_OF_SCOPE / DEFERRED` 不进入 TechnicalSolution，也不生成 Story 或 Task。

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

人工评审投影必须保留每个 Commitment、Uncertainty 和 EvidenceRef 的稳定 ID 与名称映射；Owner
validator 从 candidate 逐条校验，禁止只在机器 JSON 中保留身份名称。

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
| `investigationResultId` | As-Is Owner 的稳定 ID；被稳定决定引用后进入 Ledger。 |
| `requestId` | 对应 work-only Request，仅用于审计；不得作为稳定引用目标。 |
| `decisionId` | 被支持或证伪的唯一决定；与 Request 原值一致。 |
| `question` | 从 Request 编译的有限问题，发布后可独立解释 Result。 |
| `materialityTargets` | 从 Request 编译的影响字段集合。 |
| `verdict` | `SUPPORTED / FALSIFIED / UNKNOWN`。 |
| `factIds` | `SUPPORTED / FALSIFIED` 时至少一个；`UNKNOWN` 可以为空。 |
| `evidenceIds` | 高影响结论至少一条；冲突时保留必要竞争 Evidence。 |
| `impact` | 明确影响哪些决定字段。 |
| `handling` | `ACCEPT / REVISE_DECISION / ASSUMPTION / ALLOWANCE / DISCOVERY / BLOCK`。 |

`UNKNOWN` 不能使用 `ACCEPT`。`FALSIFIED` 不能保持原 Decision candidate 不变。所有稳定消费者只引用 `investigationResultId`；删除 work 目录后 Result 仍必须可解析。

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

Discovery Requirement 由 As-Is Owner 作为 `CurrentStateLedger` 的阻塞对象拥有。它不与被阻塞的实施范围一起进入 Commitment Gate；Commercial Packet 只能引用其 ID 和阻塞处置，不能创建或改写 Discovery。Discovery 完成后，其结果作为新的授权输入重新进入相应 Owner。

### 4.5 `TechnicalSolution`

包含：

- `DeliveryDisposition[]`；
- `DesignItem[]`；
- `ArchitectureDelta[]`；
- `DesignDecision[]`；
- `TechnicalEpic[] / TechnicalFeature[]`；
- `TechnicalInputDisposition[]`；
- `GoLiveDisposition[]`。

#### `DeliveryDisposition`

BusinessScope 中每个 `IN_SCOPE` BUSINESS Feature，以及每个进入方案的 TECHNICAL Feature，恰有一条：

- `NEEDS_DELIVERY`：需要 Design 覆盖并形成 Delivery；
- `FULLY_COVERED`：必须引用 `COMPLETE` Coverage 和支持 Evidence，不生成 Story。

`OUT_OF_SCOPE / DEFERRED` 只由 BusinessScope 拥有，不进入 TechnicalSolution。Design Owner 不得重复写商业范围状态，也不得用 DeliveryDisposition 扩大或缩小获批范围。

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
| `sourceRef` | 与 Technical Input 绑定同一原文 anchor；Design 必须读取该片段自行确认，不能只接受摘要。 |
| `status` | `ADOPTED / REPLACED / REJECTED / INVESTIGATION_REQUIRED`。 |
| `designDecisionIds` | 采用或替代时至少一个。 |
| `technicalRequirementIds` | 形成 TECHNICAL requirement 时至少一个。 |
| `investigationResultIds` | 需要现状判断时绑定稳定 Result。 |
| `rationale` | 说明为何采用、替代或拒绝，不改写来源陈述。 |

`INVESTIGATION_REQUIRED` 只允许出现在 working candidate；Solution Readiness Gate 不接受该状态。Design context 只读取队列逐条点名的原文片段，不重新通读未入队来源。

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

Allowance 由 Estimate Owner 在 `EstimateBaseline` 中拥有，不能由 Commercial Packet 或 Delivery Owner 创建。它不能绕过模板计算权威，必须定义：

- `allowanceId`；
- 触发条件；
- 最大基础单元实例集合或最大实例数量；
- 每个实例允许的工作模式和复杂度上限；
- 责任方；
- 未触发时如何处理；
- 超出上限时的变更控制。

正式 Estimate 将上限范围编译为明确 Task；模板计算人天。无法用基础单元和有限实例表达的未知必须转为 As-Is Owner 拥有的 Discovery Requirement。

### 4.8 `PlanningDisposition`

#### `PlanningPremise`

Planning Owner 在 Scope Gate 后形成 work-only Planning Premise，只捕获可能提前否定方案的约束：

- 客户要求或明确排除的目标日期；
- UAT、变更冻结、发布、第三方和平台窗口；
- 关键角色的硬性不可用区间；
- 必须串行的外部依赖；
- 每项约束的来源、受影响 Feature 和违反后果。

Gate 2 只做粗粒度约束筛查，不编造 Task 级排期。明显不可行的硬约束必须形成 Finding；其余约束由 Phase 4 使用正式 Task 复核。

#### `PlanningDisposition`

Planning Owner 在 Commitment Gate 发布且始终包含：

| 字段 | 约束 |
|---|---|
| `planningDispositionId` | 稳定 ID。 |
| `commitmentMode` | `EFFORT_ONLY / MILESTONE_COMMITTED`。 |
| `planningPremiseHash` | 绑定进入 Gate 2 的硬约束闭包。 |
| `scheduleCommitment` | `EFFORT_ONLY` 时固定为 `NONE`；否则固定为 `PLAN_BOUND`。 |
| `feasibility` | `EFFORT_ONLY` 为 `NOT_APPLICABLE`；里程碑承诺必须为 `FEASIBLE`。 |
| `deliveryPlan` | 只在 `MILESTONE_COMMITTED` 时存在。 |

`deliveryPlan` 包含：

- `ResourceRole[]`：角色、容量、可用窗口；
- `TaskDependency[]`：前置、后置和依赖类型；
- `ExternalWindow[]`：客户、平台、第三方、UAT 或发布窗口；
- `Milestone[]`：范围、完成条件和日期；
- `PlanningRisk[]`：触发、影响、负责人和处理。

不保存个人敏感信息；人员以角色或经批准的非敏感显示名表示。每个 Milestone 必须引用非空 Story/Task 集，完成条件可观察，全部前置、容量和外部窗口均可满足。

从 `MILESTONE_COMMITTED` 改为 `EFFORT_ONLY` 只使 PlanningDisposition、Commercial Packet 和 SowPackage stale；如果用户同时修改范围、方案或责任，才按对应 Finding 扩大 Impact Closure。

### 4.9 `CommercialPacket`

Commercial Packet 是 Commitment Gate 的专用 Gate Packet。除通用 Gate Packet 字段外，它只投影并绑定：

- ProjectShell；
- BusinessScope；
- CurrentStateLedger candidate；
- TechnicalSolution candidate；
- DeliveryContract candidate；
- EstimateBaseline candidate；
- PlanningDisposition candidate；
- Owner candidate 中的 Assumption/Risk ID；
- EstimateBaseline 中的 Allowance ID；
- CurrentStateLedger 中的 Discovery Requirement ID 与处置；
- 明确排除；
- Owner validation/review 结果；
- Gate Evaluation；
- 各对象 hash。

BA、TL、PM 的 Role Approval sidecar 不写入 Packet 本身。Commercial Packet 不得新增或改写业务字段；摘要中出现而 Owner candidate 中不存在的决定必须使 Gate 失败。

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
| `REVIEWED` | 不可变 | 当前 subject 的专业判断已 PASS；未变化 subject 可以由后续 Packet 引用原 review。 |
| `APPROVED` | 不可变 | 所需角色已批准当前业务语义 hash；可以发布。 |
| `PUBLISHED` | 稳定 | 下游可以引用；只有 Owner 可产生替代版本。 |
| `STALE` | 只读 | 直接依赖变化；不得供新 Gate 使用。 |

状态不写回业务对象本身；由 sidecar/receipt 表达。聚合 candidate 任一字节变化会产生新 hash，但不自动使 Impact Closure 外 subject 的 review 或 claim verification 失效。

### 5.2 Gate 生命周期

```text
NOT_READY
  -> READY_FOR_REVIEW
  -> REVIEW_REQUIRED
  -> READY_FOR_APPROVAL
  -> APPROVED
  -> PUBLISHED

Solution Readiness:
READY_FOR_REVIEW -> REVIEW_REQUIRED -> ESTIMATION_READY

受影响前置 hash 变化：
current state -> STALE
```

`BLOCKED` 是评估结果，不是可继续前进的状态。解除 blocker 后必须重新计算受影响 subject 的 Gate Evaluation 和 Packet binding，不能从旧 `BLOCKED` 直接继续。

Setup/Compilation 由机械检查直接发布；Scope/Commitment 需要 Role Approval；Solution Readiness 由 `GateReviewReceipt(outcome=ESTIMATION_READY)` 结束，不进入 `APPROVED / PUBLISHED`。Gate 只因其 subject 或直接输入的受影响闭包变化而 stale；无关聚合对象变化不能使该 subject 的 review 失效。

### 5.3 原子批准与可恢复发布

Commitment Gate 同时绑定多个 Owner candidate，但不改变单一 Owner 写权限：

1. Current State、Technical Solution 和 Delivery Contract 在 staging 中通过 Solution Readiness；
2. Trial Estimate 基于上述精确 hash 运行，修复 finding 后只冻结新 candidate，不发布；
3. EstimateBaseline 与 PlanningDisposition 基于同一 candidate set 形成；
4. Gate Packet 绑定全部 candidate、最小上下文、Owner validation 和可复用 review；
5. 一个 Commitment Judgment Reviewer 只审新增 Estimate/Planning、跨聚合一致性和 Gate 2 未覆盖的商业风险；
6. 角色初次批准同时绑定完整 `packetSha256` 与 `semanticApprovalHash`；
7. publisher 只做 hash/check/publish，按固定技术顺序发布，receipt 最后写入；
8. 中断时只允许从已批准 Packet 恢复，不重新解释业务。

Gate 3 之前不得发布 CurrentStateLedger、TechnicalSolution、DeliveryContract、EstimateBaseline 或 PlanningDisposition。逻辑上这是一个批准集；物理实现可以是可恢复前向发布，不要求文件系统多文件事务。

### 5.4 Gate 工件模型

#### `DecisionDependency`

| 字段 | 约束 |
|---|---|
| `fromId` | 依赖方决定或事实。 |
| `toId` | 被依赖的稳定对象。 |
| `kind` | `SCOPE / EVIDENCE / BASELINE / SOLUTION / DELIVERY / ESTIMATE / PLAN`。 |
| `source` | `STRUCTURAL / SEMANTIC`。 |
| `owner` | 声明该依赖的 Owner；必须拥有 `fromId`。 |
| `rationale` | `SEMANTIC` 必填；说明结构引用无法表达的影响。 |

所有类型化 ID 引用必须由确定性 projector 派生 `STRUCTURAL` 边。Owner 只能补充无法从字段推导的 `SEMANTIC` 边；Gate 比较“Schema 应有结构边”与实际精确集合，缺边、多边、悬空边或方向错误均 BLOCK。同一 `fromId + toId + kind` 只能出现一次；Impact Closure 从变化对象反向遍历消费者。

#### `OwnerValidationReceipt`

每个 Owner-local validator 输出：

- Owner、合同版本和 candidate hash；
- `subjectIds`；
- 本 Owner 业务 check 与 diagnostics；
- 从本 Owner Schema 派生的结构依赖边；
- outcome：`PASS / BLOCKED`。

HLD/Go-live、Delivery、Estimate 和 Planning 专业规则只在各自 Owner validator 中执行。共享 Gate runtime 不读取 Owner Schema，不重放这些规则。

#### `GateEvaluation`

| 字段 | 约束 |
|---|---|
| `gateId` | `SETUP / SCOPE / SOLUTION_READINESS / COMMITMENT / COMPILATION`。 |
| `contractVersion` | 与目标插件合同一致。 |
| `inputBindings` | 按稳定名称绑定全部直接输入路径、业务版本和 SHA-256。 |
| `ownerValidationBindings` | 绑定当前 subject 的 Owner Validation Receipt。 |
| `subjectIds` | 本次 Gate 实际判断的业务对象。 |
| `crossOwnerChecks` | 只检查引用、hash、唯一 Owner、闭包和跨聚合不变量。 |
| `blockingFindingIds` | outcome 为 `BLOCKED` 时非空。 |
| `outcome` | `READY_FOR_REVIEW / BLOCKED`。 |

任一 Owner validation 或 cross-owner check 为 `BLOCKED` 时 outcome 必须为 `BLOCKED`，Coordinator 和 Reviewer 都不能改写。

#### `ContextBundle`

Gate 的最小上下文由确定性 Owner-local projector 生成并包含：

| 字段 | 约束 |
|---|---|
| `gateId / runId` | 唯一 Gate run。 |
| `subjectIds` | 与 Evaluation 一致。 |
| `fragmentBindings` | 每个唯一业务集合只投影一次，绑定路径、hash、字节数和 Owner。 |
| `claimBindings` | 绑定 claim text hash、anchor hash 和 subject。 |
| `verificationBindings` | 绑定可复用 Claim Verification Receipt。 |
| `sourceRevisions` | 绑定仓库、文档或问卷 revision。 |

同一 Agent 在一个 Gate run 中每个 fragment 最多读取一次；相同 `(projectorVersion, subjectIds, inputHashes)` 只投影一次并跨 Gate 复用。不同 Owner 可以引用同一 fragment binding，不得复制同一集合为多个内容不同的摘要。

#### `ClaimVerificationReceipt`

work-only claim 核验记录至少绑定 `claimTextHash + anchorHash + sourceRevision + verificationPolicyVersion`。四项均未变化且未被抽检时可以在首次发布前、Gate 2→Gate 3 和局部修复后复用；任一项变化、`UNVERIFIED` 或抽检命中使该 claim stale。发布时有效记录可以提升到 Owner receipt。

#### `GateReviewReceipt`

| 字段 | 约束 |
|---|---|
| `gateId` | 对应 Gate。 |
| `subjectBindings` | 每个 subject 的 candidate/object hash。 |
| `judgmentReviewHash` | 当前 Gate 完整 Judgment Review。 |
| `reusedReviewBindings` | 未变化 subject 的既有 review；必须证明依赖闭包未变。 |
| `diffReviewBindings` | 修改 subject 的 patch diff 与 Impact Closure review。 |
| `firstJudgmentBinding` | 绑定当前 Packet 第一次 `PASS / BLOCKED` 判断；同一 Packet 只能有一个 canonical 值。 |
| `outcome` | Scope/Commitment 为 `PASS / BLOCKED`；Solution Readiness 为 `ESTIMATION_READY / BLOCKED`。 |

Gate 3 以 Gate 2 Receipt 证明 Solution Readiness 当前；不重新执行未变化 Solution/Delivery 的完整 Judgment Review。
Reviewer 对同一 Packet 的后续相反判断不能覆盖 `firstJudgmentBinding`；只有 candidate、context、
Evidence、review 或其他 Gate input 变化并生成新 Packet hash 后才允许重新判断。

#### `ArtifactMetrics`

每个 Owner validator 从当前 candidate 确定性投影顶层业务集合数量与 candidate canonical hash，形成
work-only `ArtifactMetrics`。Stage、Coordinator 和用户可见摘要只能转发该对象；不得由模型自行统计
Story、AC、Evidence、Task 或其他集合，也不得在 stdout 缺少指标时补报推测数字。

#### `GatePacket`

| 字段 | 约束 |
|---|---|
| `algorithm` | 目标合同固定算法 token。 |
| `gateId` | 对应唯一 Gate。 |
| `inputBindings` | 与 Gate Evaluation 原字节一致。 |
| `candidateBindings` | 按 Owner 稳定名称绑定 candidate hash。 |
| `contextBindings` | 绑定 Context Bundle 与 fragment hash。 |
| `claimVerificationBindings` | 绑定当前或复用的 Claim Verification Receipt。 |
| `gateEvaluationHash` | 绑定机械判断。 |
| `reviewBindings` | 绑定专业 review、risk summary 和 Gate Review Receipt。 |
| `openNonBlockingRiskIds` | 只含已处理且不阻塞的风险。 |
| `semanticApprovalHash` | 对范围、方案、交付、估算、责任、假设和计划语义计算；排除纯 anchor/路径/格式 binding。 |
| `packetSha256` | 对完整 canonical Packet 计算；字段自身不参与递归计算。 |

Candidate、Evaluation、业务 review 或输入语义变化产生新的 `semanticApprovalHash` 和 Packet。只有纯 Evidence/路径 binding 变化允许 semantic hash 保持不变。

#### `RoleApproval`

| 字段 | 约束 |
|---|---|
| `gateId` | 角色正在批准的 Gate。 |
| `role` | `BA / TL / PM`。 |
| `approvedPacketSha256` | 初次批准时的完整精确 Packet hash。 |
| `semanticApprovalHash` | 角色承担责任的业务语义 hash。 |
| `decision` | `APPROVED / REJECTED`。 |
| `decisionDate` | 用户确认的 ISO 日期。 |
| `responsibility` | 当前角色实际承担的批准范围，必须与 Gate 合同一致。 |

缺少必需角色、角色批准不同 semantic hash、责任与 Gate 不符或任一 `REJECTED` 都不能进入 `APPROVED`。

#### `EvidenceRebindAttestation`

只允许 `EVIDENCE_REBIND` 使用，绑定旧/新 Packet、旧/新 Evidence binding、相同 `semanticApprovalHash`、受影响 subject 和独立 Reviewer 的语义等价结论。任一事实陈述、决定、责任或估算变化都拒绝 attestation 并要求新业务批准。有效 attestation 允许复用原 Role Approval，只重发 As-Is receipt、受影响直接引用、Commercial Packet binding 和 SowPackage。

#### `OwnerReceipt`

Owner receipt 绑定 Owner、合同版本、named inputs、stable output、Owner Validation Receipt、Gate Review Receipt、Gate Packet 和适用的 Role Approval/Evidence Rebind Attestation。Receipt 只证明当前发布与批准闭包一致，不重放 Owner 业务判断，也不复制业务字段。

## 6. Phase 输入输出合同

### 6.1 Phase 1：初始化

#### 输入

| 输入 | 必选 | 约束 |
|---|---:|---|
| `projectId` | 是 | 稳定合法 ID。 |
| `projectName` | 是 | 非空。 |
| 插件 manifest/lock | 是 | 与目标合同版本一致。 |
| SOW v1.3 模板 | 是 | 可以复读，计算权威不被复制。 |

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
| 已发布 `ProjectShell` | 是 | 当前模板与合同版本。 |
| 已发布 `BusinessScope` | 是 | Scope Gate receipt 当前。 |
| `TechnicalInput[]` 与原文 anchor | 条件 | 来源中存在时逐条读取点名片段并全部处置，不通读未入队来源。 |
| 授权 Repo/文档/配置 | 条件 | 仅按 Investigation Request 读取。 |
| 往期 SOW | 条件 | 只处理与当前 Feature 重叠承诺。 |
| 负责人回答 | 条件 | 只回答定向问题。 |
| 日期、窗口与容量硬约束 | 条件 | 由 Planning Owner 编译为 Planning Premise；不在 ProjectShell 保存。 |

#### 内部循环输出

- Coverage candidate；
- Design Hypothesis；
- Investigation Request/Result；
- `CurrentStateLedger.candidate`；
- `TechnicalSolution.candidate`；
- `DeliveryContract.candidate`；
- Planning Premise 与粗粒度约束筛查；
- Owner Validation Receipt；
- Context Bundle、Claim Verification Receipt；
- Solution Readiness Gate Evaluation 与 Gate Review Receipt。

#### Phase 输出

一个 `ESTIMATION_READY` candidate set，绑定：

- Current State；
- Technical Solution；
- Delivery Contract；
- Planning Premise；
- 仍适用的 Assumption/Risk；
- 无未处理高影响 Unknown；
- 机械证明完整的直接依赖；
- `GateReviewReceipt(outcome=ESTIMATION_READY)`。

这些 Candidate 尚未作为稳定输出发布。

### 6.4 Phase 4：形成可承诺估算

#### 输入

| 输入 | 必选 | 约束 |
|---|---:|---|
| `ESTIMATION_READY` candidate set | 是 | Gate Review Receipt 和 subject hash 当前。 |
| SOW v1.3 模板目录投影 | 是 | 不复制人天和公式。 |
| Planning Premise | 是 | Gate 2 已筛查硬约束。 |
| 最终商业承诺选择 | 是 | `EFFORT_ONLY / MILESTONE_COMMITTED`，由 Planning Owner 拥有。 |
| 资源与窗口明细 | `MILESTONE_COMMITTED` 时是 | 角色、容量、依赖和外部窗口。 |
| 商业假设/Allowance | 条件 | 已结构化且有唯一 Owner。 |

#### 内部循环输出

- Trial Estimate；
- Trial Findings；
- 修正后的 Owner candidate set；
- 受影响 subject 的 diff review；
- `EstimateBaseline.candidate`；
- `PlanningDisposition.candidate`；
- Commercial Packet candidate。

#### Phase 输出

Commitment Gate 一次通过后发布：

- `CurrentStateLedger`；
- `TechnicalSolution`；
- `DeliveryContract`；
- `EstimateBaseline`；
- `PlanningDisposition`；
- 各 Owner receipt；
- 已批准 Commercial Packet。

### 6.5 Phase 5：编译并签署 SOW

#### 输入

| 输入 | 必选 | 约束 |
|---|---:|---|
| 当前 `ProjectShell` | 是 | template fingerprint 匹配。 |
| 已批准 Commercial Packet | 是 | 角色批准绑定同一 semantic hash；完整 Packet 或有效 rebind attestation 当前。 |
| 六个业务 Owner stable/receipt | 是 | 与 Packet named inputs 完全匹配。 |
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
| `setup` | Phase 1 | 保持机械化；只写身份、合同版本和模板 binding。 |
| `analyze-requirement` | Phase 2 / Requirement Owner | 只发布 BusinessScope 和 Technical Input 队列。 |
| `analyze-as-is` | Phase 3 / Decision Investigation Module + As-Is Owner | 从完整前置阶段改为按 Design/Estimate 决定调用。 |
| `generate-design` | Phase 3 / Design Owner | 与 As-Is、Delivery candidate 在 Gate 2 前共同收敛。 |
| `generate-story` | Phase 3 / Delivery Owner | Story/AC 先形成 candidate，通过 Trial Estimate 后才发布。 |
| `generate-task` | Phase 4 / Estimate Owner | 先产生 work-only Trial Estimate；Gate 3 后发布 EstimateBaseline。 |
| 人员与迭代规划 | Phase 3/4 / Planning Owner | Gate 2 前筛查硬约束；Gate 3 发布 PlanningDisposition，只有里程碑承诺包含 DeliveryPlan。 |
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
5. 每个 Technical Input 有 source anchor、受影响 Feature 和可供 Design 定向读取的原文片段；
6. BUSINESS 与 Technical Input 没有被错误混为 TECHNICAL requirement；
7. 不含凭据、绝对路径或客户原文复制。

#### 专业 PASS 条件

1. BA 确认业务结果和范围；
2. 范围内外及延期边界无冲突；
3. 会改变商业范围的关键问题已解决；
4. 仍存在的业务假设有触发、责任和未满足后果；
5. Design 可以读取每项 Technical Input 点名的原文 anchor，不需通读未入队来源。

#### BLOCK 条件

- Feature 无法独立纳入、排除或验收；
- 来源冲突会改变范围但未决定；
- “沿用/不替换/仅集成”等边界未映射受影响 Feature；
- Technical Input 无来源或影响对象；
- BA 未批准当前 Scope Packet 的 semantic hash。

#### PASS 输出

发布 `BusinessScope`、Scope Gate Review Receipt 和 Scope receipt。任何业务语义修改使 Gate stale；纯来源 anchor rebind 使用 Evidence Rebind Attestation。

### 7.3 Gate 2：Solution Readiness Gate

这是进入 Task 试拆分的内部专业门禁，不发布稳定 Design/Delivery，也不要求真人 TL/BA 提前批准。TL/BA 在本 Gate 表示同一个 fresh-context Judgment Reviewer 的两种专业审查视角。

#### 进入条件

- Scope Gate 当前；
- Current State、Technical Solution、Delivery Contract candidate 和 Planning Premise 已形成；
- 所有 Investigation Request 已有 Result 或明确取消理由；
- 各 Owner Validation Receipt 当前；
- Context Bundle 与 Claim Verification Receipt 已形成。

#### 机械 PASS 条件

Owner-local validator 分别证明自己的业务不变量；Gate runtime 只组合 receipt 并检查：

1. 每个 `IN_SCOPE` BUSINESS Feature 恰有一条 Coverage 和 DeliveryDisposition；
2. `FULLY_COVERED` 只引用 COMPLETE Coverage 和 Evidence，`NEEDS_DELIVERY` 有 Design 覆盖和至少一个 Story；
3. 每个 Story 恰属一个 Feature、至少有一个 AC，并显式引用其 Effective Start 或 MISSING；
4. 每个高 Materiality Design Decision 有 Investigation/Greenfield/Assumption/Allowance/Discovery 处理；
5. 每个 Technical Input 的原文 anchor 已由 Design 读取，且有 `ADOPTED / REPLACED / REJECTED` 处置；
6. Design Owner Validation Receipt 证明十项 Go-live disposition 完整；
7. Planning Premise 中没有尚未处理的明显不可行硬约束；
8. 所有类型化引用对应精确结构依赖边，无 orphan Fact、Evidence、Effective Start、Result 或 Decision；
9. 稳定候选 As-Is 实体都被一个当前决定消费；
10. Context Bundle 没有重复集合，所有 claim 都有当前 verification 或明确深度 Review 路由。

#### 专业 PASS 条件

一个完整 Judgment Reviewer 使用同一 Packet，按 TL/BA 两个视角确认：

1. 方案与业务范围一致；
2. Delivery Delta 能解释 Story 的必要性；
3. AC 可观察且不描述实现步骤；
4. Integration、迁移、生产、发布、验证、运维移交和支持责任明确；
5. 无未处理、可能推翻范围或估算的 Unknown；
6. 当前方案可以进入 Trial Estimate，Delivery candidate 未改变商业意图；
7. 粗粒度日期/窗口约束未使当前方案明显不可行。

本 Gate 不请求 Role Approval，不产生第二份 TL/BA 人类确认。

#### BLOCK 条件与回退

| Blocker | 返回 Owner |
|---|---|
| Coverage/Effective Start/Evidence 不足 | As-Is |
| Technical Input 未处置、方案缺口 | Design |
| Story/AC 不可验收 | Delivery |
| 硬日期或窗口明显不可行 | Planning；若需改范围则返回 Requirement/Design |
| 商业范围本身不明确 | Requirement，Scope Gate stale |
| 高影响未知无上限 | As-Is 形成 Discovery Requirement，阻塞实施 SOW |

#### PASS 输出

产生 hash-bound `ESTIMATION_READY` candidate set 和 `GateReviewReceipt(outcome=ESTIMATION_READY)`；不发布稳定专业数据。

### 7.4 Gate 3：Commitment Gate

#### 进入条件

- Solution Readiness Gate Review Receipt 当前，且其 subject hash 与 candidate set 匹配；
- Trial Estimate 已运行；
- 所有 blocking Trial Finding 已关闭；
- EstimateBaseline 和 PlanningDisposition candidate 已形成；
- Commercial Packet 已绑定全部 candidate、Context Bundle、claim verification 和复用 review。

#### 机械 PASS 条件

1. 每个 Story 至少一个 Task；
2. 每个 AC 至少由一个同 Story Task 覆盖；
3. 每个 Task 恰好一个基础单元、工作模式和复杂度；
4. 没有 `X` 复杂度；
5. `调整 / 接入复用` 引用 Story 允许的 Effective Start；
6. 每个 `deliveryRequired=true` Integration 恰好一个 Integration Task；
7. 发布切换、迁移、诊断/整改不存在合同定义的重复计价；
8. Allowance 可以展开为有限 Task 且不保存自由人天；
9. `MILESTONE_COMMITTED` 时 PlanningDisposition 含完整可行 Plan；
10. `EFFORT_ONLY` 时 `scheduleCommitment=NONE` 且没有日期或里程碑承诺；
11. Commercial Packet 不含 Owner candidate 之外的新业务字段；
12. Gate 2 未变化 subject 绑定原 Gate Review Receipt，变化 subject 绑定 diff review；
13. Reviewer、candidate、Context Bundle、claim verification、risk、Gate Evaluation 和 input hash 全部匹配。

#### 专业 PASS 条件

Commitment Judgment Reviewer 不重做 Gate 2 的方案完整性 Review，只判断新增和交叉责任：

1. Estimate/Planning 与 Gate 2 candidate set 一致；
2. Assumption、Allowance、客户前置和排除有明确触发与后果；
3. Task、工作模式、复杂度、资源、依赖和计划没有引入新的范围或责任矛盾；
4. 没有未关闭 blocking Finding。

随后：

5. TL 批准 Technical Solution、Task、工作模式、复杂度和技术责任；
6. BA 批准 Story/AC 仍忠实表达商业范围；
7. PM 批准责任、PlanningDisposition 和条件性里程碑；
8. 三个角色批准同一 `semanticApprovalHash`。

#### BLOCK 条件与回退

| Blocker | 返回位置 |
|---|---|
| Task 对象或计数不明确 | Design 或 Delivery；只重跑受影响 subject 的 Gate 2 diff review |
| AC 无 Task 覆盖 | Delivery 或 Estimate |
| 工作模式无现状依据 | As-Is 或 Estimate |
| Integration 漏失或责任不清 | Design/Delivery |
| 复杂度只能为 X | Design/As-Is/Delivery |
| 资源或窗口不可行 | Planning；若需改范围则返回 Scope/Design |
| 未知无法界定上限 | As-Is Discovery，阻塞实施 SOW |
| 模板组合不适用 | Estimate；不得手写人天绕过 |

#### PASS 输出

- 一次发布 `CurrentStateLedger`、`TechnicalSolution`、`DeliveryContract`、`EstimateBaseline` 和 `PlanningDisposition`；
- 发布 Owner receipt；
- 发布获批 Commercial Packet。

### 7.5 Gate 4：Compilation Gate

#### 进入条件

- Commitment Gate 当前且已发布；
- 所有 Owner stable/review/receipt 与 Commercial Packet 的 semantic/full binding 匹配；
- Evidence rebind 时存在有效 attestation；
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
- Commercial Packet 的 `packetSha256` 与 `semanticApprovalHash`；
- 工作簿可打开；
- 生成内容与已批准 Packet 或有效 Evidence Rebind Attestation 一致；
- 对应角色的签署版本明确。

发现业务内容错误时回到真实 Owner 和受影响 Gate，不直接修改工作簿。

### 7.7 信息流与 Agent 编排

普通路径的 Agent 图固定为：

```text
Coordinator
  -> Owner-local projector / validator
  -> Claim Verifier[]（按 claim 并行，可缓存）
  -> 一个 Gate Judgment Reviewer
  -> Owner patch
  -> Patch/Diff Reviewer（只读影响闭包）
  -> Scope 或 Commitment 用户批准
  -> deterministic publisher
```

| 角色 | 最小输入 | 输出 | 并行边界 | 停止条件 | 禁止继承或写入 |
|---|---|---|---|---|---|
| Coordinator | Gate manifest、diagnostics、receipt hash | 调度、Impact Closure、Packet | 可并行启动无依赖 Owner/Verifier | Gate BLOCK 或所需 receipt 当前 | 不读取完整业务原文，不写 Owner candidate |
| Requirement Owner | 获授权来源、Scope subject | BusinessScope candidate | 来源处置可按条并行 | Scope 不确定性关闭 | 不写技术方案 |
| As-Is Owner | Investigation Request、授权来源 | Result、Ledger candidate | 独立 Request 并行 | Request stopRule 满足 | 不读取无关事实族，不写 Design |
| Design Owner | Scope、点名 Result/原文 anchor | TechnicalSolution candidate | 不依赖同一对象的 Decision 可并行 | 所有输入处置完成 | 不声明现状或商业范围 |
| Delivery Owner | Scope、Solution、相关起点 | DeliveryContract candidate | 独立 Feature/Story 可并行 | Story 可验收 | 不写 Task |
| Estimate Owner | 当前 Story/AC、模板目录、相关起点 | Trial/正式 Estimate candidate | 独立 Story 试拆分可并行 | 无 blocking Trial Finding | 不修改 Story/AC |
| Planning Owner | Planning Premise、Task/Estimate、外部约束 | PlanningDisposition candidate | 约束收集可与 Phase 3 并行；正式计划等 Task | 模式和可行性明确 | 不改范围、Task、人天 |
| Claim Verifier | 单 claim、最小 anchor、cache key | Verification Receipt | claim 间并行 | PASS/FAIL/UNVERIFIED | 不读取完整 candidate 或相邻 claim |
| Judgment Reviewer | Gate Packet、Context Bundle、验证结果 | Gate Review Receipt/findings | 每个 Gate 恰好一个完整实例 | 完备性通过或返回 findings | 不继承 Stage 聊天史，不重读已验证 anchor，抽检除外 |
| Patch/Diff Reviewer | patch diff、Impact Closure、闭包原文 | diff review | 独立 finding 闭包可并行 | 声明变化与闭包一致 | 不加载全仓库或 round-1 历史 |
| User approver | Scope/Commercial Packet 可读投影、hash | Role Approval | 同一 Packet 的角色可分别确认 | APPROVED/REJECTED | 不逐份批准 context、claim、receipt |
| SOW Compiler | 已批准 stable/receipt、模板 | SowPackage | 机械内部实现可并行 | round-trip 和 manifest 通过 | 不运行专业 Reviewer，不补业务字段 |

#### Gate 级复用规则

1. Scope、Solution Readiness、Commitment 普通路径各最多一个完整 Judgment Reviewer，总计三个；Compilation 不创建专业 Reviewer。
2. Gate 2 Receipt 中 subject hash 未变化时，Gate 3 直接复用其专业判断，只新增 Estimate/Planning 和跨聚合 Review。
3. Trial Finding 只使 `subjectIds` 的反向 Impact Closure stale；未变化 subject 绑定旧 review 和 claim verification。
4. Claim Verifier、Investigation Request 和独立 Story Trial 可以并行；同一 Owner 对同一 candidate 的写入必须串行合并后重新计算 hash。
5. Commercial Packet 只引用 Owner review/receipt/hash，不复制完整专业正文。
6. Reviewer 不继承 Coordinator 或 Owner 的聊天历史，只从 hash-bound Context Bundle 启动 fresh context。

#### 停止与失败

- 机械失败在创建 Judgment Reviewer 前返回 Owner；
- 任一 Claim `FAIL/UNVERIFIED` 不被深度 Reviewer 解决或显式处理时，Gate BLOCK；
- Owner 修复只能产生新 candidate 和 patch manifest，不能原地修改已绑定 candidate；
- Reviewer 第一次判断必须在任何 patch 或重复调用前按 Packet hash 记录；同一 Packet 的判断冲突
  机械返回 `REVIEW_JUDGMENT_CONFLICT`；
- 达到 token/工具预算时返回已完成、缓存命中和剩余 subject/claim，不静默扩大读取或视为 PASS；
- 单个并行任务失败只阻塞其 subject；共享输入无效才阻塞整个 Gate。

#### `GateRunMetrics`

每次 Gate run 机械记录但不进入稳定业务数据：

- projected fragment 数量与字节数；
- fragment read 次数；
- unique anchor read 次数；
- claim cache hit/miss/stale 数量；
- full Judgment Reviewer 与 Patch/Diff Reviewer 次数；
- reused/reviewed subject 数量；
- user approval request 数量；
- Investigation Request 数量及 stopRule 关闭数量。

这些指标只用于验收浪费边界，不进入 Commercial Packet 业务正文。

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
| `UNKNOWN_UNBOUNDED` | 未知无法形成安全上限 | As-Is |
| `PACKAGE_MISMATCH` | 工作簿与批准 packet 不一致 | SOW Compiler |

### 8.2 回退原则

1. Finding 指向最早拥有错误语义的 Owner，而不是最接近报错的脚本。
2. 下游 Owner 不附带上游字段 patch；只描述违反的不变量和所需决定。
3. 修复生成新 candidate hash；Impact Closure 外 review、claim verification 和此前未受影响 Gate 的 Role Approval 不自动失效。
4. 只重跑受影响的直接消费者和传递闭包；新 Packet 显式绑定复用项。
5. 当前 Gate 的商业语义变化产生新 `semanticApprovalHash` 并要求该 Gate 角色重新批准；纯 Evidence rebind 使用 Attestation。
6. 商业范围变化必须重新通过 Scope Gate；名称、格式或 anchor 变化不自动升级为范围变化。
7. 任何业务失败都不能在 SOW Compiler 中修复。

### 8.3 Task 试拆分反馈示例

```text
Finding: DELIVERY_NOT_ESTIMABLE
subjects: story-customer-migration
problem: 同一 Story 同时包含客户主数据迁移和生产切换，具有不同对象、责任和验收时点。
requiredDecision: Delivery Owner 将其拆为可独立验收的 Story，或由 Design Owner证明它们构成一个不可分交付窗口。
owner: DELIVERY
blocking: true
```

Estimate Owner 不直接拆分 Story；Delivery 修复后重新形成 candidate，只对该 Story 的 Impact Closure 运行 Solution Readiness diff review 和 Trial Estimate。无依赖 Story、Design Decision、claim 和 review 原绑定复用。

## 9. 依赖与变更模型

### 9.1 允许的直接依赖

| From | 可以直接依赖 |
|---|---|
| Coverage | Business Feature、Effective Start、Commitment、Uncertainty |
| Effective Start | Current-State Fact、Commitment、Evidence |
| DeliveryDisposition | Business Feature、Coverage、Evidence |
| Design Decision | Feature、Effective Start、Investigation Result、Technical Input |
| Story | Feature、DeliveryDisposition、Design Decision、Effective Start、Assumption/Risk |
| AC | Story、Delivery Delta、Commitment |
| Integration | Story、Design Decision、Current-State Fact |
| Task | Story、AC、Effective Start、Integration、Base Unit |
| PlanningDisposition | Task、Story、Planning Premise、外部窗口、角色容量 |
| Commercial Packet | 全部 Owner candidate、Assumption/Risk、Allowance、Discovery 处置、Gate Evaluation |
| SOW Package | Commercial Packet、Owner stable/receipt、模板 |

表中由 ID 字段表达的边全部确定性派生；只有责任、替代关系等没有结构字段的语义影响可以显式补边。Gate 必须证明结构边精确集合完整，不能用 Reviewer 猜测弥补漏边。

禁止反向业务依赖：

- Business Feature 不依赖 Design/Story/Task；
- Current-State Fact 不依赖 Design/Task；
- Story/AC 不依赖正式 Task；Task 试拆分只是 Gate 证据；
- 模板不依赖项目业务数据。

### 9.2 变更类别

| 类别 | 示例 | 重新打开 |
|---|---|---|
| `PRESENTATION_ONLY` | 不改变身份的名称、格式 | 直接投影和 Compilation Gate |
| `EVIDENCE_REBIND` | anchor/hash 更新，事实语义不变 | As-Is receipt、直接引用、Attestation、Commercial Packet binding、Compilation |
| `BASELINE_CHANGE` | Effective Start 能力变化 | 引用它的 Design/Story/Task/PlanningDisposition |
| `SOLUTION_CHANGE` | Design Decision 或责任变化 | 关联 Story/AC/Task/PlanningDisposition |
| `DELIVERY_CHANGE` | Story/AC/Integration 变化 | Trial Estimate、Estimate、PlanningDisposition |
| `ESTIMATE_CHANGE` | Task、工作模式、复杂度变化 | PlanningDisposition、Commercial Packet、Package |
| `PLAN_CHANGE` | 承诺模式、资源、窗口、里程碑变化 | PlanningDisposition、Commercial Packet、Package；只有同时改变范围/方案时扩大闭包 |
| `SCOPE_CHANGE` | Feature 语义或范围变化 | Scope Gate 及相关完整闭包 |

### 9.3 Gate stale 规则

- 只有 named input 中属于当前 `subjectIds` 或其反向 Impact Closure 的 hash 变化才使对应 Gate subject stale；
- 聚合 hash 变化时，新 Packet 必须逐项绑定复用 subject 与受影响 subject，不得把聚合变化等同于全量专业重审；
- 语义变化产生新 `semanticApprovalHash`；`PRESENTATION_ONLY / EVIDENCE_REBIND` 保持 semantic hash 并要求 diff/attestation；
- `PRESENTATION_ONLY / EVIDENCE_REBIND` 不自动创建专业 finding，也不请求新的业务 Role Approval；
- Reviewer 必须检查变更分类是否低估，不能由修改 Owner 单方面声明无影响；
- 已发布 SowPackage 永不原地覆盖；任何新 binding 产生新的内容寻址 package ID。

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
4. 只对受影响 Story/Decision 运行 Gate 2 diff review 和 Trial Estimate；未变化 subject 复用 review/claim verification。
5. 没有稳定 Story/AC 被中途发布。

预期：正常收敛发生在稳定批准前，不触发正式 reconciliation。

### 10.7 里程碑不可行

1. Planning Premise 已在 Gate 2 筛查当时已知的目标日期和硬约束。
2. Phase 4 才确认客户 UAT 只能在目标日期后执行，Planning 返回 `PLAN_INFEASIBLE`。
3. PM 不能直接移动业务范围或修改人天。
4. 用户选择调整里程碑、改为 `EFFORT_ONLY`，或返回 Scope/Design 分期。
5. 只改为 `EFFORT_ONLY` 时更新 PlanningDisposition 和 Commercial Packet；Scope、Gate 2、Trial Estimate 和 Estimate review 保持当前。

预期：已知硬约束尽早失败；晚到窗口不会把正确人天误认为可承诺日期，也不会无条件重做上游。

### 10.8 Evidence anchor 修正，语义不变

1. 已批准 Fact 的文件 anchor 因文档重排变化，内容语义不变。
2. 变更分类为 `EVIDENCE_REBIND`。
3. As-Is 更新 Evidence binding；独立 Reviewer 形成 Evidence Rebind Attestation。
4. `semanticApprovalHash` 不变，原 Role Approval 继续有效。
5. 不重开无关 Design、Story、Task 专业判断。
6. 重新生成 receipt、Commercial Packet binding 和新 SowPackage。

预期：保持追溯完整，不进行固定后缀全量重审，也不请求新的业务批准。

## 11. 可测验收条件

### 11.1 模型不变量

1. 每个 `IN_SCOPE` Business Feature 恰有一条 Coverage 和 DeliveryDisposition。
2. `OUT_OF_SCOPE / DEFERRED` 只存在于 BusinessScope；TechnicalSolution 不重复商业范围状态。
3. 每个稳定 Current-State Fact 至少被一个 Effective Start、Coverage、Design Decision 或 Task 工作模式引用。
4. 每个稳定 Investigation Result 有独立 ID、decision、问题、materiality、结论和证据，删除 work-only Request 后仍可解析。
5. 每个高 Materiality Design Decision 有支持性处理或阻塞实施 SOW。
6. 每个 Story 恰属一个 Feature，并显式引用相关 Effective Start 或 MISSING。
7. 每个 AC 至少由一个同 Story Trial Task 和正式 Task 覆盖。
8. 每个正式 Task 恰好一个基础单元、工作模式和复杂度，且不为 `X`。
9. `调整 / 接入复用` Task 的 Effective Start 必须属于同 Story 允许集合。
10. 每个需要交付的 Integration 恰好一个 Integration Task。
11. Allowance 由 Estimate Owner 拥有，可以确定性展开为有限 Task，且不保存自由人天。
12. Discovery Requirement 由 As-Is Owner 拥有，不由 Commercial Packet 创建。
13. `MILESTONE_COMMITTED` 的 PlanningDisposition 必须含可行 Delivery Plan；`EFFORT_ONLY` 固定 `scheduleCommitment=NONE`。

### 11.2 调查收敛

1. `hypothesis` 模式下，没有 Decision/Feature/Materiality 绑定的 Investigation Request 被拒绝。
2. stop rule 满足后不继续扫描同一事实族。
3. 非 Material 事实不能进入稳定 CurrentStateLedger。
4. Greenfield 可以用零 Current-State Fact 通过 Gate 2。
5. Task context 只包含 Story 显式引用的 Effective Start；不存在“为安全加载全部”路径。
6. Design 对每个 Technical Input 读取点名原文 anchor，但不通读未入队来源。
7. 未处理高影响 `UNKNOWN` 不能进入 Commitment Gate。
8. Gate 2 前对已知硬日期、窗口和容量约束完成粗粒度筛查。

### 11.3 Gate 行为

1. 每个 Gate 对缺失、无效、stale、unsupported 输入 fail closed。
2. Candidate 任一字节变化产生新 candidate/Packet hash，但只使 Impact Closure 内 subject review 失效。
3. Gate 只发布自身定义的稳定输出。
4. Gate 失败不修改任何已发布稳定业务数据。
5. Gate 2 使用 Gate Review Receipt 表达 `ESTIMATION_READY`，不请求 Role Approval。
6. Commitment Gate 的所有角色批准同一 `semanticApprovalHash`，初次批准同时绑定完整 Packet。
7. Gate 3 前不发布 Current State、Solution、Delivery、Estimate 或 PlanningDisposition。
8. Compilation Gate 不运行上游业务分析或 Owner validator，不补充缺失业务字段。
9. 同一 Packet 的第一次 Reviewer 判断不可覆盖；无新 Packet 的相反判断必须 fail closed。
10. Stage 完成或阻塞摘要中的对象数量必须与 Owner validator 的 `ArtifactMetrics` 完全一致。

### 11.4 反馈与返工

1. Trial Finding 只能由声明 Owner 修复。
2. Estimate Owner 无法修改 Story/AC；Planning Owner 无法修改 Task/Estimate。
3. 单 Story Finding 不重审无依赖 Story、Design Decision、Task、claim 或 review。
4. `PRESENTATION_ONLY / EVIDENCE_REBIND` 不触发无关专业重审或新业务批准。
5. `SCOPE_CHANGE` 必须重新通过 Scope Gate。
6. Impact Closure 外稳定对象保持原字节，其 review/verification binding 可复用。
7. 任何新发布 Package 使用新内容寻址 ID，不覆盖旧 Package。

### 11.5 交付与兼容

1. SOW v1.3 模板、基础人天、复杂度、公式和取整规则原字节或合同保持不变。
2. 插件 0.2.0 不静默读取 0.1.0 receipt/packet 作为当前合同。
3. 插件独立复制后不读取 marketplace 根目录或其他插件。
4. 稳定数据和 package 不包含凭据、客户原文、源码、完整工具输出或本机绝对路径。
5. 相同 Commercial Packet、Owner stable/receipt 和模板产生相同 SowPackage。

### 11.6 浪费与吞吐指标

1. 普通路径恰有 Scope、Solution Readiness、Commitment 三次完整 Judgment Review；Compilation 为零，Gate 3 不重跑未变化的 Gate 2 专业判断。
2. 普通路径用户业务批准请求恰有 Scope 和 Commitment 两轮；前者形成一个 BA sidecar，后者形成 TL/BA/PM 三个 Role Approval sidecar；最终签署确认不重新展示或批准业务正文。
3. 相同 `claimTextHash + anchorHash + sourceRevision + verificationPolicyVersion` 最多事实核验一次，抽检和显式失效除外。
4. 相同 `(projectorVersion, subjectIds, inputHashes)` 的 context fragment 最多投影一次；同一 Agent 每个 Gate run 最多读取一次。
5. 单 Story Trial Finding 的 `reviewedSubjectCount` 不包含 Impact Closure 外 Story/Decision/Task。
6. GateRunMetrics 必须能报告 fragment bytes/read、anchor read、cache hit/miss、完整/diff Reviewer 次数和 approval request 次数。
7. Commercial Packet 只引用 Owner review/receipt/hash，不复制完整专业正文。
8. Evidence rebind 的 `semanticApprovalHash` 不变且 approval request 数为零。
9. Greenfield、Brownfield 和单 Story 修复场景必须断言上述次数，而不只断言最终 Schema。
10. Current State review 中 Commitment、Uncertainty 和 EvidenceRef 的稳定 ID/名称映射与
    candidate 精确一致。

## 12. 实现约束

1. 先固定逻辑 Schema、Owner Validation Receipt、Gate diagnostics 和复用键，再修改 Skill 文案；禁止只靠 prompt 表达核心门禁。
2. 每个 Owner 继续 Skill-local 拥有业务 Schema、renderer、validator 和测试。
3. 插件级 runtime 只实现 Owner-agnostic 的状态、hash、patch、Gate Packet、Context Bundle binding、claim cache、影响闭包、metrics 和 project I/O。
4. Gate runtime 只组合 Owner receipt 和检查跨 Owner 引用；不得读取 Owner Schema 或复制 HLD/Go-live 等专业规则。
5. `Decision Investigation` 可以内部使用搜索、语言工具、CodeGraph、文档或问卷 Adapter，但这些 Adapter 不进入外部 interface。
6. 两种以上真实调查 Adapter 存在前，不为每种工具创建公共 seam。
7. Gate Evaluation 返回稳定 diagnostics；Coordinator 不扫描实现源码预测失败。
8. 稳定业务对象不保存流程状态；状态由 receipt/sidecar 表达。
9. Commercial Packet 是批准投影，不成为可被下游改写的额外业务真相。
10. 生成器继续只读取当前批准稳定数据和模板，不读取 Owner Schema、fixture、test 或工作目录猜测业务语义。
11. 实现必须 clean cutover 全部调用方、测试、fixture、文档和发布元数据，不保留旧阶段 alias。
