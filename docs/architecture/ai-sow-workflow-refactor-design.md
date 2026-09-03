# AI SOW 决策驱动工作流重构设计

状态：已取代的设计提案；不代表当前实现
日期：2026-08-31  
适用范围：`plugins/ai-sow/` 的阶段职责、Owner seam、评审门禁、返工路径和最终生成边界  
当前基线：插件 0.1.0、SOW 标准 v1.3

> 当前权威实现见 `plugins/ai-sow/docs/AI_SOW_PLUGIN_DESIGN.md`。本文保留早期七阶段与十一 Sheet 分析
> 作为历史决策记录；其中阶段边界、稳定数据和 Excel 投影均已被单入口四 Sheet 实现取代。

详细领域对象、阶段输入输出、状态转换、门禁条件和回退合同见
[AI SOW 决策驱动工作流详细合同](ai-sow-workflow-contract-spec.md)。

## 1. 结论

当前七阶段链路把“完成一个领域的完整成果”当作进入下一阶段的主要条件：

```text
setup
  -> analyze-requirement
  -> analyze-as-is
  -> generate-design
  -> generate-story
  -> generate-task
  -> generate-sow
```

这种结构能够提供强追溯和明确数据所有权，但它把本应由下游决策决定深度的工作提前完成，主要表现为：

- 在目标方案问题尚未出现前完整调查系统现状；
- 在 Task 可估算性尚未验证前冻结 Story 和 AC；
- 在资源、依赖和里程碑可行性尚未验证前完成估算；
- 把确定性工作簿生成继续作为业务分析阶段；
- 用阶段顺序近似真实依赖，导致局部修改扩大为整段返工。

本设计把工作流改为“少量不可逆决策门禁 + 门禁内部定向迭代”：

```text
初始化
  -> 定义商业范围
  -> 塑造交付方案
  -> 形成可承诺估算
  -> 编译并签署 SOW
```

核心决定如下：

1. SOW 的默认目标是形成可承诺的范围、人天和责任边界，不是完成系统尽调。
2. 系统现状调查不再作为设计前一次性完成的完整阶段；它成为总体设计按决策调用的现状证据 module。
3. As-Is 与 Design 的数据所有权仍然分离，防止把方案假设写成现状事实。
4. 商业范围状态只由 Requirement Owner 拥有；Design 只决定 `NEEDS_DELIVERY / FULLY_COVERED`。
5. Design、Story/AC 和 Task 保持不同 Owner，但在正式批准前通过候选结果双向收敛。
6. Gate 2 只产生可复用的 `ESTIMATION_READY` Review；Gate 3 一次批准并发布全部专业聚合，不提前发布 Design/Delivery。
7. 只有 Scope 和 Commitment 需要用户批准；Gate 2 是一个 fresh-context Judgment Reviewer 的 TL/BA 双视角检查。
8. 角色批准绑定业务语义 hash；纯 Evidence rebind 由等价 attestation 处理，不重新请求商业批准。
9. `generate-sow` 是确定性编译 module，不再承担业务内容决策。
10. 上游修正按机械完整的决策依赖闭包重新打开成果，并复用闭包外 review、claim verification 和 context。
11. Reviewer 对同一 Gate Packet 的首次判断不可被过程压力翻转；阶段对象数量只采用 validator 从
    candidate 确定性投影的指标，不采用 Agent 自报统计。

## 2. 目标与非目标

### 2.1 目标

1. 每项调查、设计和评审工作都能说明它将改变哪个范围、责任、交付或估算决定。
2. Brownfield 项目只调查足以确认 Effective Start、交付差值和估算工作模式的现状。
3. Greenfield 项目不因固定 Topic 清单被迫制造现状 Item 或 Evidence。
4. Story/AC 只有通过 Task 试拆分证明可估算后才正式冻结。
5. 硬日期和窗口在 Gate 2 前筛查；承诺日期或迭代计划进入 SOW 时再用正式 Task 验证资源和依赖可行性。
6. 普通路径业务批准恰有 Scope 和 Commitment 两次，不与内部文件数量绑定。
7. Gate 2→Gate 3、局部修复和 Evidence rebind 能机械复用未变化 review、claim 和 context。
8. 局部事实变化只重开实际依赖该事实的设计、交付和估算决定。
9. 保留稳定数据 Owner、证据追溯、hash 绑定、隐私边界和确定性生成能力。

### 2.2 非目标

- 不把 Requirement、As-Is、Design、Delivery、Estimate 合并成一个共享业务 JSON。
- 不让 Design Owner 声明未经 As-Is Owner 确认的当前事实。
- 不建设完整企业架构库、CMDB、代码知识图谱产品或持续系统发现平台。
- 不为了减少阶段数而创建通用 Owner runner 或配置驱动业务引擎。
- 不改变 SOW v1.3 的基础人天、复杂度、SIT、UAT、风险、公式和取整权威。
- 不在本设计中修改工作簿 Sheet、基础单元或计算公式。
- 不在兼容性未知时静默迁移已有项目数据。

## 3. 问题发现

### 3.1 现状调查发生得过早、过完整

业务需求批准后可以确定调查范围，但仍不能确定全部调查问题。真正有价值的问题通常来自候选设计，例如：

- 现有身份平台是否支持目标租户声明；
- 现有部署能力是否只可复用流水线，还是也可复用本项目切换方案；
- 外部系统是否提供目标接口，以及哪一方负责适配；
- 当前数据质量是否允许直接迁移。

在设计假设出现前，按系统边界、能力、应用、集成、数据、平台、安全、运维和交付约束平均调查，只能形成通用盘点。它不能稳定判断哪些事实会改变 Story、Task、工作模式或人天。

当前合同已经部分承认这个问题：`hypothesis` 是默认 `investigationMode`，Topic 可以使用 `BOUNDARY_DECLARED` 或 `NOT_APPLICABLE`，As-Is 在深挖前应形成可证伪 premise。但 `investigationMode` 主要作为 Schema 和 context binding，系统仍依赖 Stage Agent 自觉收敛；它尚未形成机械调查边界。

### 3.2 As-Is 数据面大于最终决策面

As-Is 稳定数据同时包含 Topic、Item、Commitment、Effective Start、Coverage、Uncertainty 和 Evidence。它们分别有合理用途，但容易让“能够记录”变成“应当完整记录”。

代表性端到端 fixture 包含：

- 9 个 Topic；
- 11 个 Item；
- 4 个 Commitment；
- 11 个 Effective Start；
- 12 个 Coverage；
- 4 个 Uncertainty；
- 7 个 Evidence。

共 58 个结构化条目。最终工作簿的 `90-系统现状` 可见投影只使用 11 个 Effective Start。其他条目可以支持设计和审计，但该比例说明默认流程已经接近现状尽调，而不是最小估算证据链。该 fixture 只用于说明结构扩张，不作为生产项目平均值。

### 3.3 下游无法精确选择所需现状

Design context 当前整体接收 Topic、Coverage、Commitment、Uncertainty、Effective Start、Item 和 Evidence。Task context 因缺少完整 Story 到 Effective Start 关系，保守加载全部 Effective Start。

这使每一个新增现状事实产生持续携带成本：

```text
新增 As-Is 事实
  -> Design 阅读和评审成本
  -> Story 引用选择成本
  -> Task 工作模式判断成本
  -> receipt、claim 和返工成本
```

问题不只是 token 使用量。过多候选事实会增加选错起点、误判复用和用户漏审关键差异的风险。

### 3.4 Design 到 Story 是单向交接

Design 回答系统如何变化，Story/AC 回答客户购买什么以及如何判断完成。两者责任不同，但不能完全串行：

- Design 可能围绕技术模块完整，却无法形成独立验收和结算的 Story；
- AC 细化可能暴露异常路径、迁移、切换、生产验证或责任边界缺失；
- Story 若只能迁就已经冻结的 Design，就不能成为有效交付合同。

当前单向流程把这种正常收敛变成跨阶段返工。

### 3.5 Story/AC 在 Task 可估算性验证前冻结

Task 试拆分最容易发现：

- 一个 Story 包含多个独立交付对象；
- AC 无法映射到具体工作；
- Integration、迁移、发布或测试责任缺失；
- 一个 Story 跨越多个团队或合同责任；
- 任务只能用 `X` 复杂度，说明方案或范围仍不充分。

Task Owner 不应反向修改 Story/AC，但 Task 试拆分应成为 Story/AC 正式批准的输入。先冻结再试拆分，会迫使 Task 适配错误合同，或触发不必要的完整返工。

### 3.6 估算与资源、迭代可行性脱节

人天正确不等于交付承诺可行。承诺日期或迭代计划还取决于：

- 专业角色何时可用；
- 哪些任务可并行；
- 外部系统和客户团队配合窗口；
- UAT、变更冻结和发布窗口；
- 环境、数据和审批的前置依赖。

如果 PM 只在 Task 完成后补充人员和迭代计划，计划只能被动接受估算，无法及时反馈分期、范围和方案。

### 3.7 最终生成混合了内容批准与投影检查

`generate-sow` 应只把已批准数据确定性投影到模板。若最终 Excel 评审仍重新决定需求、设计、Story、Task 或估算，则前置批准没有建立稳定商业合同。

最终阶段应区分：

- 机械一致性：漏行、名称投影、引用、公式原型、样式和 package hash；
- 商业签署：范围、人天、责任、假设、里程碑和例外是否可以承诺。

前者属于编译器验证，后者属于生成前的商业就绪门禁。

### 3.8 批准对象过度贴合文件，而不是决策

Candidate、review、risk summary、context fragment、claims 和 receipt 都需要校验与留痕，但不等于用户必须逐份批准。用户真正需要承担责任的是：

- 商业范围；
- 目标方案和上线责任；
- Story/AC 交付合同；
- Task、估算、资源与商业假设；
- 最终签署版本。

把每个中间 artifact 都升级为独立批准对象，会增加重复阅读，并让正常候选迭代承担正式返工成本。

### 3.9 固定阶段后缀不能表达真实影响

阶段顺序是安全的保守近似，但不是实际依赖图。例如：

- 修复 Evidence anchor 不一定改变 Effective Start；
- Effective Start 名称变化不一定改变 Design Decision；
- Design 实现机制细化不一定改变 Story/AC；
- Story 文案修正不一定改变 Task 或人天。

按固定后缀整体复核会放大无语义变更；完全跳过又可能漏掉真实影响。正确依据应是稳定决策引用和语义变化类型。

## 4. 设计原则

### 4.1 SOW 不是系统尽调

默认调查只服务以下决定：

- Feature 当前覆盖；
- 项目启动时可依赖的 Effective Start；
- 目标交付差值；
- Story 和 AC；
- Task 数量、工作模式和复杂度；
- 集成、迁移、发布、测试、支持和责任；
- 人天、风险、资源和里程碑。

不能改变这些决定的现状细节最多进入工作记录，不默认进入稳定 As-Is、review 或 claim。

### 4.2 范围决定对象，设计决定问题，估算决定深度

- 没有批准的业务范围，不启动系统性调查。
- 没有候选设计或交付假设，不深挖通用 Topic。
- 不能说明估算影响的问题，不作为正式估算 blocker。

### 4.3 执行协同不等于数据所有权合并

As-Is Owner 继续独占当前事实、证据和 Effective Start；Design Owner 继续独占目标设计和 TECHNICAL requirements；Delivery Owner 继续独占 Story/AC；Estimate Owner 继续独占 Task 和估算输入。

Owner 间允许在同一个决策门禁内多次形成 candidate，但任何 Owner 都不能直接写另一个 Owner 的稳定结果。

### 4.4 先用候选闭环，再批准不可逆决定

候选 Design、Story/AC 和 Task 试拆分可以在 work/staging 中迭代。只有满足门禁后才发布稳定数据并请求用户批准。批准之后若语义变化，再按依赖闭包重开决定。

### 4.5 未知按影响处理，不按是否存在处理

未知问题只有在答案可能改变范围、责任、设计、交付对象、Task 数量、工作模式、复杂度、人天或里程碑时才阻塞可承诺 SOW。

不影响估算的未知必须明确边界或风险处理，但不触发继续尽调。

## 5. 目标工作流

### 5.1 总览

```text
┌─────────────────────┐
│ 1. 初始化           │
│ 项目身份、模板、规则 │
└─────────┬───────────┘
          ↓
┌─────────────────────┐
│ 2. 定义商业范围     │
│ 业务结果、范围、约束 │
└─────────┬───────────┘
          ↓
┌─────────────────────────────────────────────┐
│ 3. 塑造交付方案                            │
│ 现状筛查 ↔ 方案假设 ↔ 定向调查 ↔ Design/Story │
│                  ↔ 早期计划约束筛查           │
└─────────┬───────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────┐
│ 4. 形成可承诺估算                          │
│ Task 试拆分 ↔ Design/Story 修正             │
│            ↔ 资源、依赖和迭代可行性        │
└─────────┬───────────────────────────────────┘
          ↓
┌─────────────────────┐
│ 5. 编译并签署 SOW   │
│ 确定性生成、最终签署 │
└─────────────────────┘
```

### 5.2 初始化

职责保持机械化：

- 建立项目身份；
- 绑定插件和 SOW 标准版本；
- 复制并复读模板；
- 建立受管目录；
- 校验运行环境。

初始化不接收业务材料、代码库、往期 SOW 或目标方案，不承担专业判断。

### 5.3 定义商业范围

本阶段批准：

- 业务目标和结果；
- 可以独立纳入、排除或延期的 Feature；
- 业务规则与验收意图；
- 合同范围、明确排除和责任约束；
- 来源中的技术输入清单，但不在本阶段决定技术方案。

技术输入只作为 Design 决策队列交接，并为每项绑定一个可定向读取的原文 anchor。Design 必须逐条读取该片段自行确认，但不通读未入队来源；Requirement Owner 不把技术偏好直接编译成稳定 TECHNICAL requirement。

**商业范围门禁：** 每个 Feature 足以确定是否属于本次项目；尚未解决且可能改变商业范围的问题已经回答、明确排除，或转为获批商业假设。

### 5.4 塑造交付方案

这是主要专业迭代区，内部包含五项协同工作。

#### 5.4.1 现状快速筛查

对每个范围内 Feature 只回答：

1. `COMPLETE / PARTIAL / MISSING`；
2. 是否存在可能影响方案或工作模式的 Effective Start；
3. 是否存在与本期重叠的未完成往期承诺；
4. 哪些未知可能推翻方案或估算。

九个 Topic 继续作为防遗漏清单，但不是九项默认深挖任务。Topic 只有在影响当前 Feature、设计决定或估算时才展开 Item 和 Evidence；否则使用有依据的边界声明或不适用结论。

迁移期间现有 As-Is 离线 review 必须至少把 Commitment、Uncertainty 和 Evidence 的稳定 ID 与名称
成对投影，并由 Owner validator 对 candidate 逐条核对。该门禁先消除已知的评审盲区，不替代
0.2.0 `CurrentStateLedger` 的 clean-cut 数据重塑。

#### 5.4.2 形成可证伪方案假设

Design Owner 为每个关键范围决定提出候选方案，并明确：

- 依赖的当前事实；
- 最小证伪方法；
- 如果前提错误会影响什么；
- 需要由 As-Is Owner 回答的精确问题。

#### 5.4.3 定向现状调查

As-Is 不对外暴露完整调查实现，只提供一个决策级接口：

```text
输入：
- decisionId
- investigationQuestion
- affectedFeatureIds
- materiality：可能改变哪些范围、责任或估算字段
- allowedSources：获授权的仓库、文档、往期 SOW 或负责人

输出：
- verdict：SUPPORTED / FALSIFIED / UNKNOWN
- effectiveStart：项目开始时可依赖的事实或明确 MISSING
- evidence：一条最佳可复核 anchor；冲突时保留必要的竞争证据
- impact：对 Design、Story、Task、工作模式、复杂度或责任的影响
- handling：接受、修改方案、形成假设、安排 Discovery 或阻塞
```

只有以下情况继续深挖：

- 当前证据互相冲突；
- 第一条证据不足以支持高影响决定；
- 运行行为无法由静态材料判断且会实质改变设计或估算。

#### 5.4.4 Design 与 Story/AC candidate 共同收敛

Design 回答系统变化，Story/AC 回答客户购买的可交付结果。两者在稳定发布前允许双向迭代：

```text
Design candidate
  -> Story / AC candidate
  -> 验收、结算、异常路径和责任检查
  -> 必要时返回 Design candidate
```

#### 5.4.5 早期计划约束筛查

Planning Owner 在 Scope Gate 后并行收集目标日期、UAT/冻结/发布窗口、关键角色硬性不可用区间和外部串行依赖，形成 work-only Planning Premise。Gate 2 只判断这些已知硬约束是否已明显否定当前方案，不提前制造 Task 级排期；最终容量和关键路径仍在下一阶段复核。

**方案与交付门禁：**

- BusinessScope 中每个 `IN_SCOPE` Feature 有明确 `NEEDS_DELIVERY / FULLY_COVERED` Delivery Disposition；
- 每个需要交付的 Feature 有 Design 覆盖和至少一个 Story；
- 每个 Story 有可观察 AC；
- Integration、迁移、生产范围、发布、验证、运维移交和支持责任有明确结论；
- 所有高影响现状前提已获支持，或已采用获批的安全处理；
- 已知硬日期、窗口和容量约束没有使当前方案明显不可行；
- Story/AC 尚未正式冻结，等待下一阶段 Task 试拆分。

### 5.5 形成可承诺估算

#### 5.5.1 Task 试拆分

Estimate Owner 在 work/staging 中对 Story/AC candidate 试拆分 Task。试拆分只回答：

- 每个 Story 是否能映射到独立基础单元实例；
- AC 是否有实际工作覆盖；
- 是否遗漏集成、迁移、发布、测试、诊断、培训或下线工作；
- `新建 / 调整 / 接入复用` 是否有足够 Effective Start；
- 是否存在重复计价；
- 是否出现 `X` 复杂度或无法确定计数对象。

若失败，Estimate Owner 返回结构化 finding，指明应由 Design 还是 Delivery Owner 修正；它不直接修改上游稳定数据。

#### 5.5.2 冻结交付候选

只有 Task 试拆分证明 Story/AC 可估算后，Design 与 Delivery candidate 才冻结为 Gate 3 输入，不在此时批准或发布。Estimate Owner 基于同一绑定 candidate 形成正式 Task 和 Estimate candidate；Planning Owner 形成始终存在的 PlanningDisposition candidate。Gate 3 一次批准和发布 Current State、Solution、Delivery、Estimate 与 PlanningDisposition。

#### 5.5.3 资源与计划可行性

PlanningDisposition 始终明确 `EFFORT_ONLY / MILESTONE_COMMITTED`。若承诺日期、里程碑或迭代计划，Planning Owner 必须基于正式 Task 确认：

- 关键角色和容量；
- 任务依赖与可并行性；
- 客户、平台和第三方配合窗口；
- UAT、变更冻结、发布和支持窗口；
- 计划与估算、范围和责任一致。

若只承诺工作量，PlanningDisposition 固定 `scheduleCommitment=NONE`，不要求虚构人员排期。承诺模式不属于 ProjectShell，单独改变模式不会使 Scope 或 Gate 2 stale。

**可承诺估算门禁：**

- Story/AC 已通过 Task 试拆分；
- 每个 Task 有明确对象、工作模式和可接受复杂度；
- 所有估算相关未知已经解决、由 Estimate Owner 量化为有限 allowance，或由 As-Is Owner 转入独立 Discovery SOW；
- 没有重复计价或无责任方工作；
- PlanningDisposition 与已批准 Planning Premise 一致，适用时资源与里程碑可行；
- Gate 2 未变化专业判断已复用；
- TL、BA 和 PM 分别批准其责任范围内的同一 `semanticApprovalHash`。

### 5.6 编译并签署 SOW

SOW Compiler 只执行：

- 验证已批准商业 packet 和各 Owner 当前 receipt；
- 将稳定 ID 投影为唯一名称；
- 写入模板；
- 保留 Table、公式、样式、保护和引用；
- 复读工作簿和 package；
- 内容寻址发布。

它不得重新决定范围、设计、Story、AC、Task、工作模式、复杂度、人天、资源或计划。

最终角色检查分为：

1. **机械一致性检查：** 生成器和自动化验证负责；
2. **签署检查：** TL、BA、PM 确认生成包正是前一步批准的商业 packet，没有新增决定。

## 6. Owner 与 seam

| Owner / Module | 独占内容 | 向其他 Owner 提供的 interface | 不得承担 |
|---|---|---|---|
| Setup Module | 项目身份、模板、运行环境 | 可复读 ProjectShell | 业务分析、承诺模式、Repo 调查 |
| Requirement Owner | BUSINESS 范围、规则、验收意图 | 获批 Feature、技术输入队列及原文 anchor | TECHNICAL 方案 |
| As-Is Owner | 当前事实、Evidence、Effective Start、Commitment、Discovery Requirement | 稳定可解析的决策级调查结果 | 目标设计、Task 工作模式 |
| Design Owner | 目标方案、Delivery Disposition、TECHNICAL requirement、上线责任 | 设计 candidate 与决策依赖 | 商业范围、未经确认的现状 |
| Delivery Owner | Story、AC、Integration、Assumption/Risk | 可验收交付合同 candidate | 技术实现 Task、计算人天 |
| Estimate Owner | Task、工作模式、复杂度、估算输入、Allowance | 试拆分 findings 与正式 Estimate | 改写 Story/AC、创建 Discovery |
| Planning Owner | Planning Premise、承诺模式、资源、依赖与条件性计划 | PlanningDisposition | 修改范围、Task、基础人天或公式 |
| SOW Compiler | 名称投影、工作簿、manifest、package | 确定性交付包 | 新业务决定 |

关键 seam 是 `Decision Investigation`。删除该 module 后，定向调查、证据选择、未知影响和现状/目标隔离会重新散落到 Design、Delivery 和 Estimate；因此它应是深 module，而不是一次性阶段或薄转发层。

## 7. 调查深度与停止规则

每个调查事实必须通过以下 materiality 判断：

> 如果该事实不同，会不会改变 Feature 覆盖、Effective Start、Design Decision、Story/AC、Task 数量、工作模式、复杂度、SIT/UAT、风险、资源、里程碑或责任边界？

| 结果 | 处理 |
|---|---|
| 会改变 | 调查并建立最短证据链 |
| 可能改变但未知 | 形成高影响 Uncertainty；解决、批准 allowance、安排 Discovery 或阻塞 |
| 不会改变 | 最多写边界摘要，不创建稳定 Item/Evidence/claim |
| 只增加系统理解 | 保留在临时工作记录，不进入默认 SOW 流程 |

默认停止条件：

```text
Feature
  -> Coverage
  -> Effective Start 或明确 MISSING
  -> Delivery Delta
  -> Design Decision
  -> Story / AC
  -> Task / 工作模式 / 复杂度
```

链路完整，且没有未处理的高影响 Uncertainty 时停止调查。

`exhaustive` 只用于用户明确购买系统尽调、架构评估或 Discovery 的场景。它不是普通实施 SOW 的高质量模式。

## 8. 未知与 Discovery 处理

可承诺估算不能用未经限定的未知替代事实。未知按影响和可界定程度处理：

| 情况 | 处理 |
|---|---|
| 高影响且无法界定上限 | 阻塞实施 SOW，先形成独立 Discovery/Assessment SOW |
| 高影响但可限定最大工作 | 写入明确 allowance、触发条件、责任和超出处理，并由用户批准 |
| 影响范围但由客户负责 | 写入前置条件、最晚提供时间和未满足后果 |
| 不影响范围或人天 | 记录为非阻塞风险或边界，不继续调查 |
| 证据冲突 | 不选择有利答案；记录竞争事实并交由责任人决定 |

Discovery 的输出必须是能够关闭实施估算问题的决定和证据，不是泛化的“进一步调研”。

## 9. Gate、批准与 Agent 编排

### 9.1 Gate 与批准

目标工作流使用五个 Gate，但只有两个 Gate 承担业务批准：

1. **Setup Gate：** 机械确认项目身份、运行时和模板，不接收承诺模式或专业判断。
2. **Scope Gate：** BA 批准 BUSINESS Feature、范围、规则、验收意图和技术输入队列。
3. **Solution Readiness Gate：** 一个 fresh-context Judgment Reviewer 使用 TL/BA 两个专业视角判断 candidate 是否可进入 Trial Estimate；不请求真人批准，不发布稳定 Design/Delivery。
4. **Commitment Gate：** 复用未变化的 Gate 2 Review；TL、BA、PM 分别批准同一 `semanticApprovalHash`，一次确认方案、交付合同、Task、估算、假设、责任和 PlanningDisposition。
5. **Compilation Gate：** 机械确认工作簿和 package 是 Commercial Packet 的确定性投影。

生成后另做一次签署确认，只核对 package ID、完整 `packetSha256`、`semanticApprovalHash` 和工作簿可打开，不重新批准业务内容。

初次 Role Approval 同时绑定完整 Packet 与业务语义 hash。纯 Evidence anchor/path 变化会产生新完整 Packet，但语义 hash 保持不变；只有独立 Reviewer 形成 Evidence Rebind Attestation 后才可复用原批准。事实陈述、责任、范围或估算变化不能使用该路径。

### 9.2 Gate 2 到 Gate 3 的复用

- Scope、Solution Readiness、Commitment 普通路径各最多一个完整 Judgment Reviewer；
- Gate 2 产生 hash-bound `GateReviewReceipt(outcome=ESTIMATION_READY)`；
- Gate 3 不重做未变化 Solution/Delivery 的完整性 Review，只审新增 Estimate/Planning、跨聚合一致性和风险；
- Trial Finding 只对 `subjectIds` 的 Impact Closure 运行 Patch/Diff Reviewer；
- candidate 聚合 hash 变化不等于全部 subject 专业判断失效；
- 首次发布前也能按 claim text、anchor、source revision 和 policy version 复用事实核验。
- 每个 Packet 的第一次 `PASS / BLOCKED` 判断按 Packet hash 内容寻址保存；没有新的 Packet hash 时，
  重复 Reviewer 不能覆盖或翻转原判断。
- Owner validator 直接输出绑定 candidate 的 `artifactMetrics`；Coordinator 和 Stage 只转发这些数量，
  不从自然语言总结重新统计 Story、AC、Evidence、Task 或其他对象。
- 现有 As-Is 迁移切片先机械保证 Commitment、Uncertainty 和 Evidence 的 ID/名称完整投影；目标
  `CurrentStateLedger` 继续按新合同收窄数据面。

### 9.3 Context 与 Agent 流

```text
Coordinator
  -> Owner-local projector / validator
  -> Claim Verifier[]（按 claim 并行）
  -> 一个 Gate Judgment Reviewer
  -> Owner patch
  -> Patch/Diff Reviewer（只读影响闭包）
  -> Scope 或 Commitment 用户批准
  -> deterministic publisher
```

Coordinator 只读取 Gate manifest、diagnostics 和 receipt hash，不能读取完整业务原文或写 Owner candidate。Owner、Claim Verifier 和 Reviewer 都从 hash-bound Context Bundle 启动；Reviewer 不继承 Stage 聊天历史。同一 `(projectorVersion, subjectIds, inputHashes)` 只投影一次，同一 Agent 每个 fragment 每个 Gate run 最多读取一次。Commercial Packet 只引用专业 review/receipt/hash，不复制完整正文。

Gate 级机械判断只组合 Owner Validation Receipt 并检查跨 Owner 引用；HLD/Go-live、Delivery、Estimate 和 Planning 规则仍由各 Owner-local validator 独占。

## 10. 依赖驱动返工

所有类型化 ID 引用由确定性 projector 生成结构依赖边；Owner 只补充结构字段无法表达的语义边。Gate 必须比较 Schema 应有边与实际精确集合，不能由 Reviewer 猜测是否漏边。

语义变更后，从变化对象沿引用形成影响闭包：

```text
Evidence / Current Fact
  -> Effective Start / Coverage
  -> Design Decision / Delivery Disposition
  -> Story / AC / Integration
  -> Task / Estimate
  -> PlanningDisposition / Commercial Packet
  -> SowPackage
```

变更分为：

1. **展示变化：** 只重做投影和 Compilation。
2. **Evidence rebind：** 形成语义等价 attestation，复用原业务批准。
3. **局部语义变化：** 只重开实际引用对象及传递闭包，复用闭包外 review/claim/context。
4. **范围或责任变化：** 从商业范围或方案门禁重开相关 Feature 的完整闭包。
5. **承诺模式或计划变化：** 默认只重开 PlanningDisposition、Commercial Packet 和 Package；只有同时改变范围/方案时扩大闭包。

任何 Owner 都只能修改自己的 candidate；Coordinator 只计算依赖、影响、复用和发布顺序，不拥有业务 Schema 或稳定数据。

## 11. 迁移与发布边界

本重构改变阶段 interface、批准门禁和 receipt 语义，必须作为新的插件合同发布，不能在 0.1.0 合同下原地重新解释。

采用以下兼容策略：

1. 插件版本升级到 0.2.0；Owner receipt、packet 和项目合同使用新的明确版本。
2. SOW v1.3 的工作簿与计算规则保持不变，因此本重构本身不升级 SOW 标准版本。
3. 0.1.0 项目数据不由 0.2.0 静默迁移或混读。检测到旧合同后 fail closed，并说明继续使用旧插件版本或显式重新进入最早受影响门禁。
4. 不维护新旧两套长期兼容路径，也不添加 deprecated stage alias。
5. 实现时一次迁移全部 Skill 调用、文档、Schema、fixture、validator、receipt、smoke 和发布元数据；不保留旧阶段作为隐藏回退。
6. 如果未来确认必须自动迁移真实用户项目，迁移器作为独立、显式、可复读的产品能力设计，不夹入普通 Stage 调用。

## 12. 实施切片

### 12.1 固定新合同

- 定义五组目标阶段、五个 Gate 和 Scope/Commitment 两个业务批准点；
- 定义 `Decision Investigation` interface 和稳定 Investigation Result；
- 用 Delivery Disposition 替代 Design 对商业范围状态的重复表达；
- 定义 Story/AC candidate、Task 试拆分和 Gate 3 原子发布 seam；
- 定义 Planning Premise、PlanningDisposition 和条件性 Delivery Plan；
- 定义 Owner Validation、Gate Review、Context、Claim Verification 和 Evidence Rebind 合同；
- 定义不可覆盖的 Packet Reviewer Judgment 与 candidate-derived `artifactMetrics`；
- 固定 0.2.0 版本与 receipt/packet 双 hash 合同。

### 12.2 重塑 Owner 数据与 handoff

- Requirement 只交接商业范围、技术输入队列和点名原文 anchor；
- As-Is 只稳定保存决策相关事实、证据、稳定 Result 和 Discovery Requirement；
- Design 显式记录所依赖的 Investigation Result；
- Delivery candidate 显式关联所用 Effective Start；
- Estimate context 只接收当前 Story 实际关联的 Effective Start，Allowance 由 Estimate 独占；
- Planning 在 Gate 2 前筛查硬约束，在 Gate 3 发布 PlanningDisposition。

### 12.3 建立门禁内部迭代

- Design 与 Delivery candidate 在 work/staging 内双向修正；
- Task 试拆分只返回结构化 findings；
- 上游 Owner 修复后只重跑 Impact Closure；
- Gate 2 产生可复用 Gate Review Receipt；
- Gate 3 前不发布 Current State、Solution、Delivery、Estimate 或 PlanningDisposition。

### 12.4 简化批准与最终生成

- 合并重复人类批准，Gate 2 只做 Agent 专业检查；
- 将生成前 Commercial Packet 设为最终业务批准投影；
- 分离完整 Packet hash 与业务语义 hash；
- Evidence rebind 使用等价 attestation，不重批业务；
- 将 `generate-sow` 收窄为确定性编译和 package 校验；
- 最终 Excel 复核只验证投影一致性和签署版本。

### 12.5 替换返工和重复读取机制

- 从类型化引用机械派生完整依赖图；
- 区分展示、Evidence rebind、局部语义、范围和计划变化；
- 用 subject review、claim verification 和 Context Bundle binding 复用闭包外判断；
- 删除固定后缀业务判断和 Gate 2→Gate 3 的重复专业复核；
- 记录 GateRunMetrics，验证 fragment、anchor、Reviewer 和 approval 次数；
- 保留 fail-fast、hash binding 和可恢复前向发布。

## 13. 验证策略

实现必须以行为场景证明新工作流，而不是只检查文案或 Schema 存在。

### 13.1 Greenfield

- 九个 Topic 可以通过边界或不适用结论关闭；
- 不制造虚假的现状 Item、Effective Start 或 Evidence；
- Design 和 Story 仍能形成完整交付合同和估算。

### 13.2 Brownfield 调整

- 一个现有资产足以支持相关 Task 使用“调整”；
- 不相关模块、配置和流程不进入稳定 As-Is；
- Estimate context 只加载当前 Story 引用的 Effective Start。

### 13.3 接入复用

- 调查明确既有能力保持不变和本项目侧责任；
- Design、Story、Integration 和 Task 使用同一责任边界；
- 普通依赖使用不会被错误计为独立接入 Task。

### 13.4 高影响未知

- 无法界定的未知阻塞实施 SOW，并生成具体 Discovery 输出要求；
- 有上限的未知只能通过明确 allowance 和用户批准进入估算；
- 非估算未知不触发无止境调查。

### 13.5 Task 试拆分反馈

- Task 发现 Story 不可估算时只返回 finding，不修改 Story/AC；
- Delivery 或 Design 修复后只复审该 Story 的 Impact Closure；
- Gate 2 未变化 subject 的 review、claim verification 和 context 继续复用；
- Story/AC 只有通过试拆分后才发布。

### 13.6 资源和计划

- 已知硬日期、窗口和容量约束在 Gate 2 前完成粗粒度筛查；
- 承诺里程碑的项目必须基于正式 Task 通过容量和依赖检查；
- 只承诺人天时 PlanningDisposition 明确 `scheduleCommitment=NONE`，不制造排期；
- 只改变承诺模式时不重开 Scope、Gate 2 或 Estimate。

### 13.7 局部返工

- Evidence anchor 修正且语义不变时形成 attestation，不重审无关专业判断或重批业务；
- Effective Start 语义变化时只重开实际引用它的闭包；
- 商业范围变化时完整重开相关 Feature 的下游决定；
- 依赖图完整性由类型化引用精确集合测试，而不是只测试示例边。

### 13.8 最终生成

- SOW Compiler 对相同商业 packet 产生相同 package；
- 生成器不能修改或补充任何业务决定；
- 工作簿继续遵守 SOW v1.3 模板公式和样式合同。

### 13.9 浪费与吞吐

- 普通路径只有 Scope、Solution Readiness、Commitment 三次完整 Judgment Review；
- Gate 3 不重跑未变化的 Gate 2 方案完整性判断；
- 同一 claim/anchor/source revision/policy 最多核验一次，抽检除外；
- 同一 Context Bundle fragment 每个 Agent/Gate run 最多读取一次；
- 单 Story finding 的 reviewed subject 不包含 Impact Closure 外对象；
- 普通路径只有 Scope、Commitment 两轮业务批准请求，Evidence rebind 的批准请求为零。
- 同一 Packet 的 Reviewer 判断不能在无新输入的重复调用中翻转；
- Stage 报告的领域对象数量与 Owner validator 的 `artifactMetrics` 原字节一致。

## 14. 验收标准

1. 普通实施 SOW 不再要求在 Design 前完成完整九 Topic 深度调查。
2. 每个稳定 As-Is Item、Evidence、Result 和 Uncertainty 都能追溯到具体 Feature、Design Decision 或估算影响。
3. `hypothesis` 调查模式成为机械边界；默认不激活与当前决定无关的事实族。
4. As-Is 与 Design 保持不同 Owner；Result 删除 work-only Request 后仍可独立解析。
5. BusinessScope 独占商业范围状态，Design 只写 Delivery Disposition。
6. Design 对 Technical Input 只读取点名原文 anchor，不通读未入队来源。
7. Design 与 Story/AC candidate 在稳定批准前可以双向收敛。
8. Story/AC 必须通过 Task 试拆分后才能正式发布；Gate 3 前不发布专业聚合。
9. Estimate Owner 只能返回上游 finding，不能修改 Story、AC 或 Design；Allowance/Discovery 各有唯一 Owner。
10. 已知计划硬约束在 Gate 2 前筛查，PlanningDisposition 不属于 ProjectShell。
11. 用户只在 Scope Gate 和 Commitment Gate 批准业务责任；Gate 2 不产生额外真人批准。
12. Gate 3 复用 Gate 2 Review，普通路径完整 Judgment Reviewer 恰为三次。
13. Evidence rebind 保持 semantic hash，使用 attestation 且不请求新业务批准。
14. 结构依赖边从类型化引用机械派生，Impact Closure 外 review、claim 和 context 可复用。
15. Context/claim/GateRunMetrics 可以证明 fragment、anchor、Reviewer 和 approval 次数上限。
16. `generate-sow` 只执行确定性投影、复读和 package 发布，不承担业务分析。
17. SOW v1.3 模板、基础人天和计算权威保持不变。
18. 新流程以插件 0.2.0 和新 receipt/packet 合同 clean cutover，不静默混读 0.1.0 项目数据。
19. Greenfield、Brownfield、接入复用、高影响未知、Task 反馈、计划、Evidence rebind 和局部返工均有端到端行为与次数测试。
20. 独立复制后的插件仍不读取 marketplace 根目录或其他插件文件。
21. 同一 Packet 的首次 Reviewer 判断被内容寻址冻结；无新 Packet 时任何相反判断机械失败。
22. 阶段完成和阻塞摘要中的对象数量来自 Owner validator 的 candidate-derived `artifactMetrics`，
    不能由模型手算或覆盖。
23. As-Is 人工评审面逐条包含 Commitment、Uncertainty 和 Evidence 的稳定 ID/名称映射，且映射
    缺失或错配时由 Owner validator 阻塞。

## 15. 否决的方案

### 15.1 只缩短 As-Is 提示词

否决。下游 context、稳定数据面、批准和返工仍鼓励完整调查，模型克制不能成为可靠产品边界。

### 15.2 把 As-Is 全部并入 Design Owner

否决。它会消除当前事实与目标方案之间最重要的责任隔离，设计假设容易被写成既有能力。

### 15.3 Design 完成后再统一调查

否决。虽然问题更具体，但关键现状可能推翻已经完成的方案，返工风险过高。

### 15.4 Task 阶段才确认现状

否决。此时发现的集成、数据、平台和责任问题通常需要修改 Design 或 Story，已经太晚。

### 15.5 保持七阶段，只增加更多回退命令

否决。它保留“阶段完整性优先于决策相关性”的根因，并继续扩大流程 interface。

### 15.6 长期同时支持新旧工作流

否决。双合同会把每个 Owner、validator、receipt、fixture、smoke 和文档都扩展成兼容矩阵，却不能提高新流程质量。
