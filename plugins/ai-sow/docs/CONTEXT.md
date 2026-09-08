# AI SOW 术语与数据约定

本文件统一 `ai-sow:generate` 的领域语言。用户只接触一个 Skill；`intake`、三个 Owner compiler、
`final_review`、`package_renderer` 与 `generation_store` 是内部模块。

## 1. 运行、评审与发布

| 术语 | 定义 |
|---|---|
| request | 项目内、符合 `request.schema.json` 的本次输入声明。 |
| input revision | request、模板、政策、来源原字节与无损 block inventory 的不可变快照。 |
| run | 绑定一个 input revision 的可恢复执行事务；同一项目同时最多一个 active run。 |
| action | 一个 hash-bound 模型工作单元；拥有独立 prompt、packet、reference、output 和 execution receipt。 |
| action group | 可并行的 sibling action 集合；全部必需结果封存后才一次应用。 |
| SOW Model | `ai-sow-model-v1`；范围、设计、Story/AC、Task 和估算输入的唯一稳定业务真相。 |
| checkpoint | Stage 1/2/3 的不可变完成证明，绑定冻结计划、实际 Attempt、候选、validator、Review/PASS、输入和上游 checkpoint。 |
| fresh Review | 每个完整候选验证后发行的独立 singleton 评审，PASS 才关闭阶段。 |
| artifact | 已通过阶段 fresh Review、渲染和 Office 复读但尚未发布的不可变候选包。 |
| approval | 用户对精确 `artifactManifestSha256` 的决定；不是对内部阶段 token 的批准。 |
| generation | 已批准并发布的 SOW Model、证明闭包、工作簿和说明；发布后不可变。 |
| current | `.ai-sow/current.json` 指向的最近成功 generation。 |
| last-known-good | 新 run 失败、等待、放弃或崩溃时仍由 current 指向的有效结果。 |
| Package | `sow.xlsx` 与 `sow-notes.md`；只投影 reviewed SOW Model，不拥有新事实。 |

面向使用者的问题必须逐项呈现“问题、为什么要问、答案决定什么和未回答后果”。候选批准展示自然
语言摘要与可读文件；内部 ID、hash、Schema、checkpoint 和 stage token 只用于精确绑定。

## 2. NextAction 与上下文

| NextAction | 宿主行为 |
|---|---|
| `MODEL_ACTION_GROUP` | 在声明并发度内运行 typed model actions。 |
| `REQUEST_INPUT` | 集中向用户取得会改变范围、责任或估算的最少答案。 |
| `REQUEST_APPROVAL` | 展示 verified artifact，等待用户批准或放弃；范围变化 abandon/start。 |
| `DONE` | 报告 `PUBLISHED` 或安全终态并停止。 |

`FRESH_NO_HISTORY` 表示每个 worker 只获得本 action 的 prompt、packet、reference 和 hydrate 证据，不
继承主对话、兄弟 action、前序阶段或上一次 run 的聊天历史。同一 action 内的工具往返可以复用自身
上下文；跨 action 的状态只通过 Schema 有效、hash-bound 的项目文件传递。

## 3. 来源角色与权威

| 来源 | 权威语义 |
|---|---|
| PRD | 业务目标、范围、Feature、规则、角色、场景和验收意图 |
| DEMO | 页面、动作、状态、校验、权限、异常和可观察交互结果 |
| HLD/ADR | 系统上下文、目标设计、Integration、数据、NFR、环境和上线约束 |
| PRIOR_SOW | 可验证的 Brownfield 合同起点、历史承诺和 Effective Start |
| SUPPLEMENT | 当前事实、明确决策、责任说明及其他支持材料 |
| QUESTION_ANSWER | 绑定当前完整问题包 hash 的用户答案；未回答问题不构成证据 |
| SOW_TEMPLATE | 基础单元、任务规则、复杂度、SIT、UAT、公式和取整 |

PRD/HLD/ADR 使用 UTF-8 Markdown；DEMO 使用静态 HTML/CSS/JavaScript bundle；SUPPLEMENT 可使用
UTF-8 文本、HTML、TypeScript/TSX 或 XLSX；PRIOR_SOW 使用 XLSX。推断不能静默覆盖明确来源，冲突必须形成可审计 decision、finding、
`REQUEST_INPUT` 或安全终态。

Greenfield 不继承既有合同能力。Brownfield 提供往期 SOW 时，用其建立合同 As-Is；未提供时记录
`priorSowState = NOT_PROVIDED` 并建立新基线，不虚构历史承诺。Scope 按本期计划生效日形成合同推定的
生产 As-Is；完整重复保留审计且只使用 canonical 实体，已生效 FULL 替代排除 predecessor。

## 4. InputItem 与 Scope Closure

| 术语 | 定义 |
|---|---|
| Source Block | 从来源无损提取的最小覆盖单元，拥有内容 hash、locator 与上下文关系。 |
| InputItem | 原子 requirement、design decision、constraint、responsibility、exclusion 或 conflict candidate。 |
| Scope Closure | 每个 InputItem 的唯一处置，保存落点、限定条件、跨 Feature 规则与语义充分性。 |
| SourceRef | `(sourceId, blockId, sha256, locator)` 精确来源身份，不依赖聊天轮次或易漂移行号。 |
| ScopeDecision | Feature 的 `IN_SCOPE / FULLY_COVERED / OUT_OF_SCOPE`。 |
| DesignItem | 组件、流程、数据、基础设施或质量设计对象。 |
| Integration | 有方向、触发、目的、数据类别与责任边界的系统交互。 |
| NFR | 性能、容量、可用性、安全、隐私、审计、灾备和可观测性要求。 |
| PolicyInstance | Delivery Policy 对具体目标节点的结构化实例。 |

Scope 的冻结 DAG 包含 Source Scan、逐覆盖根独立 Source Audit、按容量需要的 Proposal/Join 和唯一 Scope root。其完整 IR 只在全部有效工作成功后物化，再执行机械校验和 fresh Review。

## 5. Epic、Feature、Story 与 AC

| 术语 | 定义 |
|---|---|
| Epic | 稳定业务域或长期技术能力域，以名词或名词短语命名。 |
| Feature | 可独立纳入、排除、延期、交付和评审的领域能力。 |
| Story | Feature 下单一、可独立移交、验收和关闭的具体结果。 |
| AcceptanceCriterion | 一行一个可观察、可独立通过或失败的结果。 |
| Coverage Set | Story/AC 明确关闭的 InputItem、Design 与 Policy obligation 集合。 |

Epic/Feature 不能靠“平台”“闭环”“保障”等抽象词混装异质能力。Story 通过唯一 `featureId` 归属，
至少两条 AC、最多四个 Task；目标、指标、政策类别、证据收集或测试活动本身不自动构成 Story。
跨切面规则必须进入所有适用具体 Story 的 AC 或项目级 gate，不能只落在报表/仪表盘 Story。

Stage 2 只能写 Story、AC 与 Delivery Annotation，不能反向修改 Stage 1。`StoryAcCheckpoint` 同时绑定
Scope checkpoint、Owner projection、输入和 action records。

## 6. Task 与估算

| 术语 | 定义 |
|---|---|
| Task | Story 下直接估算的最小明细；一行对应一个基础单元实例。 |
| 基础单元 | 模板 `90-估算标准` 中拥有明确计数口径和工作内容的对象。 |
| 工作模式 | 只允许 `新建 / 调整 / 接入复用`。 |
| 复杂度 | 按当前基础单元标准判断为 `S / M / L`。 |
| Effective Start Match | `调整 / 接入复用` Task 对可信既有能力的结构化匹配。 |
| 最终人天 | 模板公式计算结果；SOW Model 不保存计算值。 |

Task 名称必须点明与 `workTypeId` 匹配的单一计数对象；一个接口 Task 只对应一个可独立开发、测试和
估算的接口。Task 保存当前模板行的 `rowSemanticSha256`，避免把旧 Task 套入新任务规则。Stage 3 只能
写 Task、Dependency、Effective Start Match 和 Estimation Annotation，不能扩大 Story/AC。

## 7. fresh Review、Patch 与 CandidateResolution

Review 是完整机械验证后的 singleton control Action。`REPAIRABLE_SEMANTIC` 的 subjectIds 解析为当前
Owner root localKeys；新发修复使用 Review-bound `CANDIDATE_PATCH-v1`，只开放可证明的字段或 root 闭包。条件 Schema 需要 discriminator 与依赖字段同时变化时，Owner 可用 `SET_FIELDS` 在同一对象开放有限非身份字段及封闭 `oneOf` 分支，不授权整对象替换。
Schema 明确拒绝的附加属性由 Owner 发放无值 `REMOVE_FIELD` 槽位精确删除；它不授权替换所在对象。缺失身份字段可由窄 `SET_FIELD` 补齐，但已有身份不可改写或复用。
Patch 成功产生绑定规范化 Patch 的物理 RepairReceipt，模型原始 raw 仍由 Attempt 单独绑定并可在非 canonical JSON 情况下重放；完整 Owner 校验后产生派生 CandidateResolution。它不把原失败 Author
改为成功，也不能提供 Review PASS。新候选必须由 distinct fresh Review 复核。已发行旧 Repair 保持冻结合同。

## 8. 新 run、恢复与稳定 ID

新 run 只执行 FULL_COMPILE，以本轮原始来源和冻结政策重新编译。未完成 run 只恢复自己的 StagePlan、Attempt 与 StageCheckpoint。业务输入变化 abandon/start。身份由 stable_ids 的受控规则生成，模型不能自由生成最终节点 ID。同 run 的预算替换必须严格增加至少一项允许的限额，其余配置不变；正文相同也拒绝，且不创建业务 input revision。


## 9. 工作簿、说明与发布证明

当前只支持 XLSX 模板。每个 input revision 保存 `sow-template.xlsx` 本轮专用副本，Task 编译、评审、
渲染和 Office 复读使用同一不可变字节。模板是任务目录、基础人天、复杂度、SIT、UAT、公式与取整的
唯一权威；Python 不计算最终人天。

工作簿固定为 `01-需求故事 / 02-任务清单 / 03-工作量汇总 / 90-估算标准` 四个 Sheet 和五个命名
Table。LibreOffice 真实回算后，固定实现复读公式、缓存、Table 计算列、验证、保护、行高、打印设置、
全部业务行和汇总恒等关系。汇总 Sheet 的可见追溯区保存实体 ID 与公开 SourceRef，真实 Prior adapter 可仅用转交的 XLSX 读取。

每个工件 revision 只有一个 `ARTIFACT_VISUAL_REVIEW`，按稳定顺序覆盖全部可见 Sheet 的 Office PDF renders。`visualReview` 只绑定成功 AttemptRecord；全项和 overall PASS、完整深层验证通过后才进入 `AWAITING_FINAL_REVIEW`。失败不发布 ArtifactManifest/GenerationManifest 或 current。已冻结 XLSX 使用 `publish_new` 保证同字节幂等，不依赖文件系统权限位。

generation manifest 绑定 input revision、SOW Model、三个 checkpoint、review decision、artifact、
approval、template、renderer、workbook 与 notes hash。`current.json` 只在 generation 全部发布并复读后
原子切换。

## 10. 语言、运行时、隐私与法律边界

普通用户无需预装 Python/uv；平台 bootstrap 在插件安装副本内准备锁定运行时。Codex 与 Claude Code
只承载 Skill/worker，运行时不调用两者的 CLI。Windows、macOS 和 Linux 使用同一 Python API 与 POSIX
项目相对路径协议。

用户叙述、问题、评审、风险和自由文本默认使用简体中文；JSON 属性、Schema 枚举、ID、hash、路径、
文件名、Sheet/Table 名和公式保持合同原值。

`.ai-sow/` 包含客户输入和衍生数据，应默认被版本控制忽略。稳定 SOW Model、action record 和公共材料
不保存凭据、私有源码、完整工具输出或本机绝对路径。AI SOW 输出用于离线评审、估算和签署准备；自动
生成本身不构成客户签署、接受、承诺生效或法律意见。

内部 checkpoint 自动封存；运行中用户只回答问题或补充材料。严格顺序 Greenfield→Brownfield 的
pair harness 不属于插件业务 Owner。两侧 verified artifact 均完成后，共同展示两份 Excel，
只取得一个 PairDecision。APPROVE 深绑定共同 manifest 与双方工作簿；两个 generation/current
都匹配才算发布。中断重放同一决定；REJECT 使用 hash 寻址的完整新 request，按受影响侧重跑后重新共同评审。

模型选择属于宿主：`generate` 使用当前宿主已配置的模型，不维护 provider/model registry。Fresh Controller Session 指整次真实 E2E 的外层宿主 session 不继承开发或先前测试对话；Fresh Action Worker 指每个 `MODEL_PROVIDER` Action 使用新的 `FRESH_NO_HISTORY` worker。同一 Action 的 hydrate/tool loop 可复用上下文，但单并发顺序执行不等于跨 Action 复用对话。

Plugin-Controlled Request 是 `read_provider_request` 返回并可由插件 hash 绑定的 canonical bytes；宿主附加的 system、安全、工具或 sandbox context 属于不可观察的 provider wire request，不进入精确字节合同。Functional Acceptance 是必需功能门禁；Timing Observation 必须记录但不阻断；Token Observation 按 `COMPLETE / PARTIAL / UNAVAILABLE` 表示 `PROVIDER_REPORTED` 覆盖度，缺少实际 usage 不阻断功能。`LOCALLY_ESTIMATED` 只表示容量与规划值，实际绝对 token 只取 `inputTokens + outputTokens`，不含重复的 cached/reasoning breakdown，也不换算费用。

Scope 独占 PriorStateSnapshot 与 ChangeGraph。CODE_ONLY 是有剩余 intent review 义务的候选；全部 round 的采用项必须绑定 Scope fresh Review/PASS 后才构成正式范围。

生成后优先使用同一 Owner 的条件 Repair 收敛：保留正确结果与已封存上游，定向调整、合并或拆分，完整校验及 fresh Review 后继续。共享测试资产保留独立 Story/AC，只计量一次；工作簿明确展示覆盖与费用归属。

大表 Prior 分区采用 `ai-sow-prior-row-partition-v1`：evidence 保留全部完整证据行，sheet 保留结构元数据，headerEvidence 只供解释列与上下文，不扩大授权证据。阶段首组尚未发行时，可通过原 run 的 `FITTING_UNISSUED_PLAN` 容量恢复记录继续；已冻结计划、原型记录和消耗保持不变。

Prior v2 允许通过冻结 priorContext 与现有 hydrate 读取同一 source/workbook 的跨分区、跨 Sheet 原文，实体仍需所属 namespace 主证据。提取、覆盖、精确单元格身份和窄关系汇总的权威合同见[Scope Owner](../skills/generate/references/scope-owner.md)。v1 IR 保留原约束，历史 run 仍绑定原源码和冻结合同，不自动迁移。

终态恢复在 ABANDON 决定落实后结束；不可变 artifact 的候选由最终 Task checkpoint 决定，取证不依赖 active state 的当前候选。宿主中断保留原调用证据，未知用量与本地估算分开记录，再沿执行重试继续。

Task Repair 的 AC 重分配限于本轮受影响 roots 已有的覆盖；历史授权不能扩张后续无关修复。公开 submit 在成功 Attempt 封存前拒绝越界为 INVALID_IR，物化与 proof 回放使用相同 Task-local 校验。

XLSX 数组公式证据按原始公式文本读取，不执行公式或使用对象字符串；缺少公式时拒绝。修正后的新 Prepare 会生成确定性证据块，已发行的冻结 revision 和调用证据不回写。

ARTIFACT RENDER 的真实导出在成功事件前持久暂存；恢复只复用该事件精确 hash 绑定的原字节，复核篡改并记录恢复 I/O 时间。没有成功事件的孤儿暂存不授权复用；旧运行缺少暂存时仍重算并匹配原 hash。此规则不改变 renderer、工作簿或已批准预览。

Prior v2 的新增提取核验要求随 `PRIOR_EXTRACTION.reviewInstruction` 进入 hash-bound Review packet；既有 `SOURCE_SCOPE-v1` 提示词及合同 hash 保持不变，以便复读已封存的 Greenfield 候选。新义务与来源索引一起由 Scope Owner 生成和回放校验，不回写历史 packet。

新冻结计划采用 `PRIOR_ANALYZE-v3`，以版本固定既有无损表传输并覆盖初始请求；专业 prompt、Prior v2 schema 和限额不变，Consolidate 仍为 v2。现有支持布局的旧计划从已绑定合同版本重建估算、物化和证明，不跟随当前默认选择。旧请求保持原字节，历史输入布局不自动迁移。具体规则见[阶段自动封存](../skills/generate/references/stage-seal.md)。

未来 Task 计划使用 `TASK-v2`，其对应 `TASK_REPAIR-v2` 的完整规则读取上限为 65536；有效额度仍取 Action 合同与显式 run hydrate reserve 的较小值。原 v1 合同、prompt/schema、请求和冻结计划保留，Repair、物化及离线证明跟随冻结 Author 版本。增加 reserve 不放宽两轮累计响应或完整请求 context 检查；可用输入空间不足时仍等待。Task 身份碰撞在成功封存前按 `TASK_IDENTITY_COLLISION`/`INVALID_IR` 返回两个问题 localKey，沿既有 revision 2 修正；身份算法与后置复核不变，不按名称或工作类型制造新身份。

已批准的 SIT/UAT 界面自动化政策可直接以其 PRD 政策与各条 AC 的 PRD/Demo 证据支持 `TEST-UI-E2E`，适用范围限于无设计引用的对应 Story/AC。共享测试仍逐 Story 核对政策与证据；工作类型、模式、复杂度、计价和完整性继续由模板规则及独立评审验证，不据此推导后台或部署设计。


机械失败沿同一逻辑工作保留候选 raw、完整 `AttemptDiagnostic.findings` 和已成功依赖。默认每个逻辑工作最多 2 个候选版本、每个版本最多执行 2 次；用尽后进入 `WAITING_INPUT`，不因次数耗尽进入 `SYSTEM_FAILED`。可在 `resume --budget-policy ...` 中显式增加 `maxActionRevisions` 或 `maxExecutionAttempts`（各项 2–10，省略为 2），继续累计 revision/attempt；已发行 Envelope、旧失败、成功 checkpoint 与原计量不回写。新版本只绑定紧邻的前一次失败。该入口不会恢复已放弃的 run。

Story/Task 的机械诊断保留问题 roots 和全部具体路径。修复只允许这些 roots 及 Owner 定位的覆盖范围变化，无关对象和字段保持一致；跨 Story 边界拆分只使用被诊断 Story 已有的义务。越界候选被拒绝，中间的非法 JSON/Schema 也不能撤销先前的保护基线。成功后仍执行完整验证和 fresh Review，失败 raw 不作为成功成果发布。

候选收敛统一采用“候选 → 检查与诊断 → 最小范围修复 → 复验 → 推进”。Schema 不完整也保护有效的其他对象；Scan/Audit、Scope、Story/Task、Prior 和原型定位各自拥有的对象与依赖。宿主一次 Action 只提交一个候选，失败由插件安排后继。确定性步骤用 `maxDeterministicAttempts` 限定累计失败次数（默认 2），保存定位、下一步及原成功输出，与候选和执行限额一样可在原 run 显式有限增加。
