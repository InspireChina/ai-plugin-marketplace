# AI SOW 术语与数据约定

本文件统一 `ai-sow:generate` 使用的领域语言。用户只接触一个生成入口；`intake`、
`scope_compiler`、`delivery_compiler`、`final_review` 和 `package_renderer` 是内部模块。

## 1. 生成、审核与发布

| 术语 | 定义 |
|---|---|
| 标准请求 | 一次调用实际使用的项目身份、模式、责任边界、PRD、HLD、往期 SOW、补充材料和问卷答案。 |
| pending 输入 | 尚未成功发布的请求快照；`BLOCKED` 后补充内容合并到这里。 |
| input revision | 成功执行所使用的不可变输入、锚点、答案和 hash 集合。 |
| ScopeBundle | 范围稳定数据，拥有 Epic、Feature、Effective Start、DesignItem、Integration、NFR 与 SourceRef。 |
| DeliveryBundle | 交付稳定数据，拥有 Story、AcceptanceCriterion、Task、依赖、假设/风险和估算投影。 |
| 自动终审 | 对完整受影响闭包执行的跨层检查，结果为 `PASS / PASS_WITH_NOTES / BLOCKED`。 |
| generation | 一次成功发布的 ScopeBundle、DeliveryBundle、manifest、工作簿和配套说明；发布后不可变。 |
| current | `.ai-sow/current.json` 指向的最近成功 generation。 |
| last-known-good | 新请求失败、崩溃或阻断时仍由 current 指向的上一份有效结果。 |
| Package | `sow.xlsx` 与 `sow-notes.md`；只投影已通过终审的稳定数据，不拥有新的范围事实。 |

`PASS_WITH_NOTES` 表示范围和估算已有固定边界，但仍需披露假设、责任、排除项、Design Task 或变更
触发条件；它不是无限责任。只有无法建立可信范围或估算，且不同解释会实质改变交付时才允许
`BLOCKED`。

## 2. 来源角色与权威

| 来源 | 权威语义 |
|---|---|
| PRD | 业务目标、In/Out Scope、Feature、业务规则、角色、场景和验收意图 |
| HLD | 系统上下文、目标架构、Integration、数据、NFR、环境、部署和上线约束 |
| PRIOR_SOW | Brownfield 的合同 As-Is、历史承诺、Effective Start 和延续范围 |
| SUPPLEMENT | 当前事实、明确决策、责任说明，以及原型的功能和交互证据 |
| SOW_TEMPLATE | 基础单元、基础人天、复杂度、SIT、UAT、风险、公式和取整 |

PRD/HLD 只接受 UTF-8 Markdown；PRIOR_SOW 只接受 `.xlsx`；SUPPLEMENT 接受 UTF-8 纯文本、HTML、
TypeScript、TSX 或 `.xlsx`。原型需要提取页面、动作、触发、状态、校验、权限、异常和可观察结果，
必要时运行 Demo 并用浏览器自动化或 Computer Use 核验。任何推断都不能静默覆盖明确来源。

## 3. 需求与范围

| 术语 | 定义 |
|---|---|
| Epic | 围绕同一业务结果或技术目标的一组 Feature。 |
| Feature | 可以独立纳入、排除、延期、交付和评审的最小需求范围。 |
| SourceRef | 文档逻辑标识、标题/表格等定位信息和内容指纹；不依赖页码或易漂移的行号。 |
| ScopeDecision | 对 Feature 的 `IN_SCOPE / FULLY_COVERED / OUT_OF_SCOPE` 判断。 |
| DesignItem | 目标设计中的组件、流程、数据、集成、基础设施或质量对象。 |
| Integration | 一次有明确来源、目标、触发、方向、目的、数据类别和责任归属的系统交互。 |
| NFR | 性能、容量、可用性、安全、隐私、审计、灾备、可观测性等非功能要求。 |
| Fixed Boundary | 用假设、责任、排除项、Design Task、估算适用范围和变更触发条件形成的可信边界。 |

每个 Feature 必须追溯到来源锚点。`IN_SCOPE` 必须具有目标设计或明确的待设计处置；
`FULLY_COVERED` 必须有 Effective Start 证据；`OUT_OF_SCOPE` 必须说明理由。适用 NFR 不能留空，只能有
明确目标、待设计状态或不适用结论。

## 4. As-Is 与 Effective Start

| 术语 | 定义 |
|---|---|
| Greenfield | 不继承既有合同能力；默认起点为本期新建，不强制往期 SOW。 |
| Brownfield | 基于至少一份适用往期 SOW 建立合同起点，并补充其生效后的已知变化。 |
| As-Is | 调查截止时已经存在或合同上预计开工前可依赖的能力、对象和边界。 |
| Commitment | 往期 SOW 的历史承诺及其本期处置。 |
| Effective Start | Design 与 Task 共用的项目起点，只包含当前存在或预计开工前具备的可信能力。 |
| Carry-forward | 尚未完成且仍属于本期交付的历史承诺；它是差值，不是 Effective Start。 |
| Evidence Boundary | 往期合同和补充材料能够证明什么、不能证明什么的明确界线。 |

往期 SOW 不自动证明当前生产状态，也不能覆盖当前 PRD/HLD 对本期目标的定义。没有实时证据但仍能
建立固定边界时记录为 `PASS_WITH_NOTES`；缺少 Brownfield 强制往期 SOW 时直接阻断。

## 5. Story、AC 与 Task

| 术语 | 定义 |
|---|---|
| Story | 可独立交付、验收和结算的结果，关联一个或多个 Feature。 |
| AcceptanceCriterion | 一行一个可观察、可独立通过或失败的结果；描述结果，不描述实现步骤。 |
| Task | Story 下直接估算的最小明细；一行对应一个基础单元实例的完整工作。 |
| Design Task | 可独立估算的架构设计、专题调研、PoC 或关键方案决策，通常归属受影响的实施 Story。 |
| 依赖 | 一个 Story/Task 使用另一个已计价交付对象的关系；不能据此重复估算共享工作。 |
| UAT 适用性 | Story 是否需要业务 UAT 的明确判断，不从任务族推导。 |

默认不创建独立 Design Story。常规设计包含在实施基础单元中；只有可独立估算的设计成果才生成 Design
Task。跨多个 Story 的共享设计或能力由一个主 Story 承载，其余记录依赖。每个需要交付的 Integration
恰好对应一个集成 Task。

### 5.1 Task 估算语义

| 术语 | 定义 |
|---|---|
| 任务族 | 组织、汇总和查漏补缺的上层分类，由基础单元确定。 |
| 基础单元 | 有明确计数口径和工作内容的估算对象；模板包含 13 个任务族、37 个基础单元。 |
| 工作模式 | 只允许 `新建 / 调整 / 接入复用`。 |
| 复杂度 | 按基础单元自己的标准判断为 `S / M / L`；`X` 只能用于候选澄清，不能发布。 |
| 工作模式证据 | `调整 / 接入复用` 对唯一 Effective Start 的结构化引用。 |
| 最终人天 | 模板按基础单元、工作模式和复杂度公式计算；稳定 JSON 不保存计算结果。 |

“调整”修改既有对象本身；“接入复用”保持既有能力不变，只交付本项目侧注册、配置、封装、映射、
适配、认证、租户、权限或专项验证。普通依赖引入和常规调用不单独生成 Task。

替换与退役不是工作模式。完整替换按替代能力、数据迁移、发布切换和系统功能下线拆分。数据迁移、
功能下线、根因整改，以及涉及既有运行能力的发布切换，即使工作模式为“新建”也应引用 Effective Start。

一个 Task 只能有一个基础单元实例、一种工作模式和一个复杂度结论。多个对象拆成多行，不能用数量或
复杂度合并。S/L 必须说明偏离 M 的具体事实；M 不需要理由。

## 6. 增量切片与 ID

输入 diff 的基准是最近成功 revision 与本次 pending 输入。变更从来源锚点定位 Feature，并扩展到相关
DesignItem、Integration、NFR、Story、AC、Task，以及共享这些对象且交付或估算会变化的其他 Feature。
无法可靠定位时扩大到业务域或全项目。

受影响切片整体重编译和替换，不保存字段 patch：

- 语义未变化的对象保留原 ID；
- 仅措辞澄清且交付含义未变时保留 ID；
- 新对象或实质含义变化的对象使用新 ID；
- 新切片未再生成的旧对象自动删除；
- 未受影响切片保持内容和 ID；
- 工作簿与说明始终完整重渲染。

稳定 ID 使用合同规定的前缀和值；关系字段只保存目标 ID。最终 Excel 以唯一非空名称展示和引用业务
对象，不把稳定 ID 作为业务 Sheet 的阅读字段。

## 7. 工作簿与说明

`.ai-sow/templates/sow-template.xlsx` 的项目副本来自插件权威模板。模板中的基础人天、复杂度系数、
SIT、UAT、风险、公式和取整是唯一计算依据。Python 只投影数据并复读结构，不执行公式，也不把计算值
写入 JSON。

`sow-notes.md` 至少记录输入 revision、适用来源、Evidence Boundary、关键解释、估算假设、Design
Task、各方责任、排除项、冲突处置、未决 NFR、风险和变更触发条件。所有 `PASS_WITH_NOTES` 事项都
必须出现在这里。

普通文本以 `= / + / - / @` 开头时仍按文本写入。公式只能来自模板原型。

## 8. 语言、隐私与法律边界

普通用户无需预装 Python/uv；平台 bootstrap 在插件安装副本内准备锁定运行时。用户不需要理解内部
Module 或执行环境命令。

用户叙述、说明、问题、风险和自由文本默认使用简体中文；JSON 属性、Schema 枚举、ID、hash、路径、
文件名、Sheet/Table 名和公式保持合同原值。

`.ai-sow/` 包含客户输入和衍生数据，应默认被版本控制忽略。稳定数据和公共材料不保存凭据、客户无关
原文、私有源码、完整工具输出或本机绝对路径。

AI SOW 输出用于离线评审、估算和签署准备。自动生成本身不构成客户签署、接受、承诺生效或法律意见。
