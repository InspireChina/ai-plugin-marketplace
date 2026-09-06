# Task Owner 确定性合同

Task Owner 消费已评审的 Story/AC，拥有 Stage 3 的 Task 与 Effective Start Match。公开 fresh Review、checkpoint 封存、恢复避免重复转换、必经 pre-seal callback 与实际 active-time 门禁由 orchestrator 集成；本 Owner 不拥有预算、运行事件或另一个 receipt。

## 输入和计划

`prepare_task_inputs(story_candidate_bytes, checkpoint_bytes, *, checkpoint_sha256, task_catalog, input_revision_bytes, prior_state_bytes=None, prior_state_sha256=None, change_graph_bytes=None, change_graph_sha256=None)` 消费调用者已解析、授权的上游字节和 hash。检查当前唯一 Schema、Story/AC PASS、非空 Author/Review 引用、无 outstanding obligation、完整 Stage 2 projection、候选/来源/政策/validator hash、revision 和本轮模板 hash。`TaskStandardCatalog` 由唯一模板读取器提供；不在 Task 阶段重读来源、Demo 或 Prior workbook。

有 Prior 时必须同时提供已授权的 Prior snapshot 与 ChangeGraph 字节/hash。复用现有 effective Prior 和 ChangeGraph 验证器，只投影当前有效实体、摘要、确切目标映射及来源定位。packet 不包含 workbook cells、文件内容或第二次现状分析。初始 Author 的 `调整 / 接入复用` 选择该技术对象在 ChangeGraph 中的明确起点；仅 Feature 级能力或名称相似不能自动授权其下全部技术 Task。未提供 Prior 的 revision 不接受注入的现状证明。公开证明链与 no-reparse 的真实恢复测试仍由后续集成完成。

`storyLocalKey = story:<sealed storyId>`，`acceptanceCriterionKey = ac:<sealed ACId>`，`technicalTarget = target:<sealed nodeId>`；政策目标使用 `target:<policyInstanceId>:story:<storyId>`，避免共享政策跨 Story 借用技术依据。非政策 Story 在明确引用批准技术设计时另有 `target:<storyId>:implementation`。它们是程序生成的选择句柄，不是前一个模型的自由 localKey。目标来自适用的批准 DesignItem、Integration、已定义 NFR、Story 的政策、UI 或批准设计下的 Story 实现；每个 Integration 优先选择承接其 Scope 事实归属的 Story，再比较真实来源锚点交集、优先非政策 Story，最终仅用稳定 Story ID 打破并列，保持唯一责任 Story 并避免拆包重复计价。

每个 AtomicWorkItem 对应一条 Story/AC 义务，使用 `STORY_AC_CHECKPOINT / checkpoint hash / 按 (storyId, acceptanceCriterionId) 排序的 ordinal`，workItemId 为 versioned obligation body hash。`build_task_work_descriptors` 使用共享 `make_planned_work`，按完整 Story 保持不可分边界、稳定 next-fit，明确 context 和空 dependency 集合。每 packet 只保留关联目标、AC 和来源 context；所有输入使用唯一两集合 packet 及三字段 context wrapper。

每 packet 带全目录精简索引。`hydrate_task_rules` 使用同一个冻结 catalog，返回所选、相邻和 challenger 的规则。`decision_catalog` 只投影选型、计量、模式、S/M/L、拆分和不建 Task 规则，不输出基础人天、倍率、公式或取整参数。完整规则不复制到每个 packet。实际 hydrate/repair 请求容量仍由公共发行边界检查。

## 精确 IR 与来源权威

TaskDecisionIR 顶层只有 `tasks`；每项精确为 `localKey / storyLocalKey / acceptanceCriterionKeys / workTypeId / technicalTarget / deliverableBoundary / workModeDecision / complexityDecision / evidenceIds`。技术对象选当前句柄；交付边界是非空中文文本；模式为模板允许的 `新建 / 调整 / 接入复用`；复杂度为 `S / M / L`。Task、AC key 数组和 evidence 数组按集合归一化，普通自由文本原样保留。

初始 Author 关闭本 Story 全部 AC；授权共享修复按实际被覆盖 Story 分别验证全部 AC、设计和政策，每 Story 最多四项；重复来源对象/工作类型计价、孤立引用、非法目录/模式、未落实设计/政策、错误或重复 Integration、非当前目标的证据均拒绝。精确 IR 未提供独立免计费字段，因此不通过自由文本跳过义务；需要免计费边界时先使上游交付依据闭合，不发明 Task 类型。

政策目标保留其政策来源，并按各 Story 的 Feature 单独附带同一 sealed Scope 中已批准 DesignItem、Integration 和已定义 NFR 的批准技术来源。共享 `policy-go-live` 仅可扩展到该 Story 完整 coverage 与政策明确 Feature/Epic 目标的交集；其他政策保持单 Feature 隔离。政策 Task 承接该范围内 Story 已引用的批准设计，表达测试/上线依据，不要求再次建设同一组件。政策范围之外的 Feature 设计仍被排除，PRD/Demo 不提升为技术依据。

`STORY_IMPLEMENTATION` 目标表达在批准设计约束下实现本 Story 的业务结果。它只承接本 Story 明确引用、适用于所属 Feature 且有批准技术来源的设计；未引用设计、其他 Feature、PRD/Demo 不形成该目标的技术授权。各业务事务可继承共享部署或存储约束，共享运行环境等独立计量对象仍只计一次，不能按 Story 数重复建设。UI 目标保持原来源和覆盖边界。完整设计落实、独立交付物是否遗漏以及共享对象是否重复计量仍须 fresh Review 判断。

UI 可使用 Demo 交互证据，包括 hash 绑定的整文件锚点。非 UI 工作类型必须有该目标的 HLD/ADR/补充决定/用户答案技术依据；Demo 和 PRD 本身不能升级为后台、数据、集成、认证或部署设计。L 档必须有目标技术依据或明确计量约束；同一批准设计可按独立来源锚点拆为多个计量对象；只改localKey或边界文案不构成另一次计价。机械验证只验证证据绑定和合法选择，计量充分性、工作类型/目标语义与 S/M/L 标准符合性由 fresh Review 判断。

`validate_bound_task_context` 在当前输出错误转换之外检查冻结 context。`validate_bound_task_result(packet, normalized_bytes)` 只做纯绑定校验，无 Schema/文件读取、写记录或预算决定；复用唯一 normalization 和 INVALID_IR/revision 2 路径。

## 物化、身份与独立验证

`task_review_rules(candidate, task_catalog)` 校验候选模板及每个已选工作类型的行 hash，确定性提供已选类型去重后的完整选择规则。fresh Task Review 与恢复都绑定该内容；不包含基础人天、倍率或公式，不继承 Author 历史。Reviewer 按完整包含/排除与验收边界判断跨类型重叠，不能只凭名称或共同来源推断计价。

`materialize_task_candidate(inputs, plan, ledger, budget_policy)` 复核确定性输入投影、完整 StagePlan、全部 effective SUCCEEDED Attempt、实际 packet/合同/normalized hash、同一 run/revision。全部 work 完成后才一次产生完整候选，执行 retry 与完成顺序不改变其字节。

`stable_ids.py` 是唯一身份算法；同一受控表加入 TASK 的 `USER_INTERFACE / STORY_IMPLEMENTATION / DESIGN_ITEM / INTEGRATION / NFR / POLICY_INSTANCE`。父身份是 sealed Story ID，锚点为真实来源及目标来源。localKey、名称、顺序、估算类型/模式/复杂度、Prior 状态不进入身份；来源无法区分的对象要求补证据，不加位置后缀。程序注入最终 ID、Story/AC 引用、SourceRef、目录 rowSemanticSha256、设计/Integration/NFR/政策引用和 Effective Start Match。

`TaskMaterialization` 仅为内存值。`validate_task_candidate` 单独验证完整模型、上游写边界、覆盖、hash 以及 sealed IR 每个节点的全部字段；不重放 ledger/plan 或重新装配完整候选。`publish_task_candidate` 内容寻址发布；相同字节不重写，新语义候选保留旧文件。Task 的 sourceRefs 在通用模型 Schema 暂为 optional，以保留尚待公开切换的旧 fixture；新 Owner 的完整节点绑定强制要求。

新示例为 `fixtures/pipeline/stage3/task-decision-results.json`。旧 PATCH fixture/动态公开驱动已移除；恢复和 fresh Review 按[阶段自动封存](stage-seal.md)执行。模板、人天、公式和 renderer 字节语义没有改变；Story planner fixture hash 仅随当前 validator Schema bytes 绑定更新。

测试按[分层入口](../../../tests/README.md)选择本次行为；完整产品、Office、浏览器与正式 Benchmark 留给最终集成门禁。


## 已有结果的修复

`prepare_task_repair_packet` 只在 Repair revision 添加确定性授权集合及当前责任承诺候选，不改变初始 Author 计划。当前起点候选必须同时有 sealed PROJECT_GATE/ASSUMPTION、与准确 Integration 相交的来源和范围、明确责任边界及批准技术来源；EXTERNAL/名称/Demo 单独不能形成候选。候选保留完整事实与条件，只允许模型据模板选择对端不变的接入复用，不证明供应商实现已存在，也不授权调整。原文条件是否足够由 fresh Review 判断。

共享 Task 保留一个主 Story，其外来 AC 必须来自被授权 roots，并处于同一批准目标或明确 Feature 覆盖范围。政策与设计引用由原受影响目标确定性合并；不改原 Story/AC。无授权、遗漏义务、无关范围和额外计量均拒绝。checkpoint proof 重新绑定原结果、修复结果、完整上下文以及全部实际候选，验证上游原值。Task 输入中重复 Story 正文可无损字典化，展开后验证原 packet SHA 与每个 workItem/context hash。

`generation-renderer-v12` 对共享 Story 投影任务列表与覆盖校验公式，并显示人天计入哪个主 Story；同一 TaskTable 只保留一行。全部计价、SIT/UAT、汇总、取整公式和目录保持原模板。政策 ID 的显示名使用具体 Story 与模板工作类型名称，模型原 ID 和来源保存在审计数据中。

仅实施澄清时使用[阶段澄清恢复](stage-seal.md)：用户明确选择当前问题 Task 的既有批准目标，答案同时进入 Repair 与 fresh Review；累计授权保留之前已通过的共享覆盖，不复活已合并 Task。新增组件或业务范围不属于该入口。

达到自动修复上限后，支持阶段合同中的明确人工裁定恢复，仅调整被批准的既有字段。完整共享覆盖、此前澄清、失败链和累计次数持续保留；不全量重新生成 Task。
