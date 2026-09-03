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
| DeliveryBundle | 交付稳定数据，拥有 Story、AcceptanceCriterion、Task、顶层依赖和估算判断依据；假设/风险仍由 Scope 拥有。 |
| 自动终审 | 对完整受影响闭包执行的跨层检查，结果为 `PASS / PASS_WITH_NOTES / BLOCKED`。 |
| generation | 一次成功发布的 ScopeBundle、DeliveryBundle、manifest、工作簿和配套说明；发布后不可变。 |
| current | `.ai-sow/current.json` 指向的最近成功 generation。 |
| last-known-good | 新请求失败、崩溃或阻断时仍由 current 指向的上一份有效结果。 |
| Package | `sow.xlsx` 与 `sow-notes.md`；只投影已通过终审的稳定数据，不拥有新的范围事实。 |

`PASS_WITH_NOTES` 表示范围和估算已有固定边界，但仍需披露假设、责任、排除项、Design Task 或变更
触发条件；它不是无限责任。只有无法建立可信范围或估算，且不同解释会实质改变交付时才允许
`BLOCKED`。

面向使用者的每个问题都是一份自包含记录，紧邻展示问题、为什么要问、答案决定什么和未回答后果。
fresh-context 终审自动执行；只有确实需要用户输入或确认时，才展示自然语言结论，内容较长时同时给出
可打开的 Markdown 或 Excel 文件。内部 ID、hash、Schema 名和阶段 token 只用于精确绑定，不代替
用户可读内容。

## 2. 来源角色与权威

| 来源 | 权威语义 |
|---|---|
| PRD | 业务目标、In/Out Scope、Feature、业务规则、角色、场景和验收意图 |
| HLD | 系统上下文、目标架构、Integration、数据、NFR、环境、部署和上线约束 |
| PRIOR_SOW | Brownfield 的合同 As-Is、历史承诺、Effective Start 和延续范围 |
| SUPPLEMENT | 当前事实、明确决策、责任说明，以及原型的功能和交互证据 |
| QUESTION_ANSWER | 通过当前完整问题包 hash 校验的用户答案；未回答问题不构成证据 |
| SOW_TEMPLATE | 基础单元、基础人天、复杂度、SIT、UAT、风险、公式和取整 |

PRD/HLD 只接受 UTF-8 Markdown；PRIOR_SOW 只接受 `.xlsx`；SUPPLEMENT 接受 UTF-8 纯文本、HTML、
TypeScript、TSX 或 `.xlsx`。原型需要提取页面、动作、触发、状态、校验、权限、异常和可观察结果，
必要时运行 Demo 并用浏览器自动化或 Computer Use 核验。任何推断都不能静默覆盖明确来源。

## 3. 需求与范围

| 术语 | 定义 |
|---|---|
| Epic | 一条独立业务线、完整业务域或长期技术能力域，形成业务或技术价值闭环并容纳多个 Feature。 |
| Feature | Epic 下用户可感知、可归责，并可独立纳入、排除、延期、交付和评审的功能模块。 |
| SourceRef | 文档或问答的逻辑标识、语义定位和内容指纹；不依赖页码、易漂移行号、聊天轮次或模型摘要。 |
| ScopeDecision | 对 Feature 的 `IN_SCOPE / FULLY_COVERED / OUT_OF_SCOPE` 判断。 |
| DesignItem | 目标设计中的组件、流程、数据、集成、基础设施或质量对象。 |
| Integration | 一次有明确来源、目标、触发、方向、目的、数据类别和责任归属的系统交互。 |
| NFR | 性能、容量、可用性、安全、隐私、审计、灾备、可观测性等非功能要求。 |
| Fixed Boundary | 用假设、责任、排除项、Design Task、估算适用范围和变更触发条件形成的可信边界。 |

每个 Feature 必须追溯到来源锚点。`IN_SCOPE` 必须具有目标设计或明确的待设计处置；
`FULLY_COVERED` 必须有 Effective Start 证据；`OUT_OF_SCOPE` 必须说明理由。适用 NFR 不能留空，只能有
明确目标、待设计状态或不适用结论。`IN_SCOPE` 还必须至少引用一条 `VENDOR` 责任边界；只有客户或
第三方责任的事项不进入供应商计价范围。待确认假设只有在责任方、处理方式、估算边界和变化触发条件
都已固定时才可由 `PASS_WITH_NOTES` 承接。

每个有效 bound answer 形成一个 `QUESTION_ANSWER` 锚点：source/anchor ID 只依赖稳定 `questionId`，
内容 hash 绑定 canonical 完整问题包和精确答案。只改变答案时锚点 identity 不变且变更类型为
`MODIFIED`；未回答问题不生成锚点，绑定无效时 intake 不写入 pending。Scope、Effective Start、假设和
AC 对答案的依赖都使用该锚点的精确 `(sourceId, anchorId, sha256)`。一个请求内的 `questionId` 必须
唯一；文档 sourceId 与合成问答 sourceId 冲突时 intake 在写入 pending 前阻断。

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
| Story | 一个 Feature 下单一、可独立交付、验收和结算的最小结果，通过唯一 `featureId` 归属。 |
| AcceptanceCriterion | 一行一个可观察、可独立通过或失败的结果；描述结果，不描述实现步骤。 |
| Task | Story 下直接估算的最小明细；一行对应一个基础单元实例的完整工作。 |
| Design Task | 可独立估算的架构设计、专题调研、PoC 或关键方案决策，通常归属受影响的实施 Story。 |
| 依赖 | 一个 Story/Task 使用另一个已计价交付对象的关系；不能据此重复估算共享工作。 |
| UAT 适用性 | Story 是否需要业务 UAT 的明确判断，不从任务族推导。 |

Epic、Feature、Story 按业务或技术结果拆分，不按前端、后端、测试、架构或运维岗位拆分。Story 标题采用
自然的 `[模块/接口] 角色或对象＋动作` 风格，不以“完成”或“实现”开头；每个 Story 至少两条可观察、
可判定且被 Task 覆盖的 AC。Story 稳定数据不保存 `description` 或用户故事三段式字段。

默认不创建独立 Design Story。常规设计包含在实施基础单元中；只有可独立估算的设计成果才生成 Design
Task。每个 Story 最多四个 Task；试拆分超过上限时按独立验收结果拆分。跨业务 Feature 的可靠性、
质量验证、发布或移交工作先形成有来源的技术 Feature，再由对应 Story 承载并通过依赖连接；不得用一个
横跨多个 Feature 的主 Story 汇总。每个需要交付的 Integration 恰好对应一个集成 Task。

Delivery 编写固定先完成 Story/AC，再进入 Task：第一遍从已验证 Scope 和来源建立 Epic → Feature →
Story → AC 闭包并反查来源遗漏；第二遍只以已成立的 Story/AC、Design/Integration/NFR、Effective Start
和本轮模板为输入拆分 Task。两遍仍形成一份 DeliveryBundle，不引入中间稳定数据或额外批准，也不允许
Task 反向扩大或改写 Story/AC。

Delivery 只保留影响判断、评审、追踪或模板投影的字段：Story 不保存常量类型或描述；AC 顺序由列表表达且不
复制理由；Task 依赖只在顶层 `dependencies` 表达；`调整 / 接入复用` 只保存
`workModeEvidence.effectiveStartItemId`，名称从 Scope 解析。Task 的计数边界理由、工作方式理由和 S/L
复杂度理由继续保留。

### 5.1 Task 估算语义

| 术语 | 定义 |
|---|---|
| 任务族 | 组织、汇总和查漏补缺的上层分类，由基础单元确定。 |
| 基础单元 | 有明确计数口径和工作内容的估算对象；当前目录与标准只从本轮模板读取。 |
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

Task 名称采用“动作＋业务或技术对象＋单一交付物”，直接暴露模板计数对象。`业务服务与接口` 中，一个
接口 Task 只对应一个可独立开发、测试和估算的接口；接口内部校验归入该接口的 AC，只有形成独立调用
契约时才另建 Task。没有独立接口的内部处理以一个可独立验收的业务操作计数。泛化“开发某某服务”或
在一个标题中并列多个接口均不能进入稳定 Delivery。

## 6. 增量切片与 ID

输入 diff 的基准是最近成功 revision 与本次 pending 输入。变更从来源锚点定位 Feature，并扩展到相关
DesignItem、Integration、NFR、Story、AC、Task，以及共享这些对象且交付或估算会变化的其他 Feature。
新增锚点先通过候选 Scope 对象的实际引用定位基线 Feature；无法可靠定位时才扩大到业务域或全项目。

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

`.ai-sow/templates/sow-template.xlsx` 的项目副本默认来自插件权威模板。只有项目副本仍匹配已知内置模板
哈希时才会自动升级；首次发布前或发布后的项目定制都必须保留。模板中的基础人天、复杂度系数、
SIT、UAT、公式和取整是唯一计算依据。工作簿固定为 `01-需求故事 / 02-任务清单 / 03-工作量汇总 /
90-估算标准` 四个 Sheet 和五个命名 Table。Python 只投影数据；LibreOffice 负责真实回算，随后 Python
从同一文件分别读取公式与缓存结果，完整复核模板公式、Table 计算列、数据验证、保护、目录、参数、
每行结果、校验列和汇总恒等关系。发布存储层对暂存件再次独立审计并核对 manifest 证据。只有
`VERIFIED` 结果可以发布，候选件和缺少计算引擎的结果都不能冒充正式输出，也不把计算值写回稳定
Delivery JSON。

当前只支持 XLSX 模板。每轮 `prepare` 把项目模板原字节保存为 `.ai-sow/work/run-template.xlsx`
本轮专用副本；Task 拆解、终审、渲染和复读不再重读可变的项目模板。下一轮发现模板与上一份
generation 不同时重新编译 Delivery 并重新终审。发布后的 generation 在 `input/sow-template.xlsx`
保留自身的模板副本，并与 manifest 中的 `templateSha256` 精确绑定。

`01-需求故事` 固定为九列，不保存内部“故事路径”；Task 的“所属故事”直接引用交付包内唯一 Story 名称。
Story 只归属一个 Feature、至少两条 AC 且最多四个 Task。每条 AC 以 `• ` 开头并独占一行；任务列表逐行
显示 `[任务类型/工作方式/复杂度] 任务名称`，其中任务类型取自模板基础单元名称。Story 行备注只显示
对象特有的特殊情况、不确定性、风险、例外、依赖或评审边界：仅关联一个 Feature 的特殊事项在该
Feature 第一条 Story 上投影一次；跨 Feature 或在多个 Feature 中复制同文案的通用事项只进入
`sow-notes.md`，无对象特有信息时留空。Story 人天仅用于结果展示和后续基准校准，不作为拆分正确性或评审通过门禁；需求、子需求、Story、AC 与 Task 的语义边界和可独立验收性才是粒度判断依据。项目直接开发人天直接汇总 Task 人天，
UAT 按适用 Story 下的原始 Task 人天计算，避免只改变 Story 包装方式时改变项目计价。

`sow-notes.md` 至少记录输入 revision、适用来源、Evidence Boundary、关键解释、估算假设、Design
Task、各方责任、排除项、冲突处置、未决 NFR、风险和变更触发条件。所有 `PASS_WITH_NOTES` 事项都
必须出现在这里。

普通文本以 `= / + / - / @` 开头时仍按文本写入。公式只能来自模板原型。

generation 的 `changeCounts` 对 Feature、Story、AC、Task 统一报告 `affected / recomputed / reused /
deleted / final`；`affected` 只指基线旧对象，候选新 ID 不混入替换集合。
初次完整编译没有基线，`replacesFeatureIds` 必须为空；新增来源只能按
`(sourceId, anchorId, sha256)` 精确身份映射到候选 Scope 引用。

## 8. 语言、隐私与法律边界

普通用户无需预装 Python/uv；平台 bootstrap 在插件安装副本内准备锁定运行时。用户不需要理解内部
Module 或执行环境命令。

用户叙述、说明、问题、风险和自由文本默认使用简体中文；JSON 属性、Schema 枚举、ID、hash、路径、
文件名、Sheet/Table 名和公式保持合同原值。

`.ai-sow/` 包含客户输入和衍生数据，应默认被版本控制忽略。稳定数据和公共材料不保存凭据、客户无关
原文、私有源码、完整工具输出或本机绝对路径。

AI SOW 输出用于离线评审、估算和签署准备。自动生成本身不构成客户签署、接受、承诺生效或法律意见。
