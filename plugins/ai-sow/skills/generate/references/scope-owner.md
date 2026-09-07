# Scope Owner 确定性合同

本文件说明业务 Owner 接口。公开 `start/submit/resume` 的 StagePlan 切换、计时、必经 callback、Review 和 checkpoint 编排由 orchestrator 集成；不能把 Owner 局部验证当成完整产品流程已通过。

## 输入和结果

`prepare_scope_inputs` 从 canonical InputRevision、匹配的 request、原文和完整 Prior inventories 生成原子项。每个 Scan item 绑定一个 coverage root 和原始上下文块；独立 Audit 重读相同块。Scope context 保留完整责任边界、交付政策以及来源 role/status/blockIds，模型可判断批准设计权威。

`SOURCE_SCAN` 返回 FactDecisionIR 数组，Audit 返回六类 checks。Scope 的 factIds 选择 `coverageRootId:localKey` 句柄；priorEntityIds 选择唯一 Prior root IR 的 entity localKey。它们都是已提供的局部引用，最终实体 ID 由程序生成。

ScopeDecisionIR 的 boundaryEvidence 保存名称、封闭分类、来源证据、facetFacts 和 observationKeys。仅 Integration 提供 responsibilityBoundaryIds，选择 request 已声明的 ID。Integration 的 direction/trigger/purpose/dataCategories、NFR target 来自选中的事实语句。其他字段不接收最终节点、SourceRef、ID 或 hash。

关系的类型、完整性、变更基数、显式集合互斥、退役双证据和显式 DESIGN/POLICY 链一致性在纯 pre-seal callback 校验。callback 只读取已验证 packet 和 normalized bytes，不读文件、不产生业务等待。合法的 MISSING Audit 或 uncertainty 可以作为执行结果保存，由 Owner 完成边界阻止 Scope 完成。

## DAG 和容量

`build_scope_work_descriptors → plan_stage` 生成 Scan/Audit、可选多层 Prior Consolidate、direct Scope Synthesis 或 Proposal/多层 Join。原子项采用稳定顺序 contiguous next-fit；0 Prior 不生成替代 work 或 snapshot，多个 Prior leaf 形成唯一 root。所有 Scope work 完成后才允许物化。

fan-in width 固定为 `floor(usableInput / (outputReserve + referenceOverhead))`。规划校验真实可知的 base provider request；未知 dependency/repair 字节不伪造 hash 或测量。发行前必须再次检查完整实际 provider request，超限进入预算等待，不能修改已冻结 StagePlan。

## 原型、Prior 和身份

`prepare_scope_prototype_contexts` 校验完整封存轮次、真实 Attempt/result 绑定、交互处置和最终 ledger。Scope plan 引用所有轮次，packet 不复制 ObservationIR 正文。未解决的发现不能关闭 Scope，CODE_ONLY 只能作为有来源支持的目标候选。

原型 whole-file SourceRef 使用 inventory evidence ID、原始文件 hash 和 `file:<revision-relative path>` locator；源文件集合必须匹配 InputRevision。该证据不证明生产 As-Is 或批准设计。Epic/Feature 的程序生成 sourceRefs 保留 boundary 和原型的直接来源。

选中的 observationKeys 从冻结 context 和实际有效 Analyze Attempt 解析。程序核对结果 hash、完整 handle 集和来源集，再将每个对象实际选中的 observation 来源与其 boundary evidence 合并，用于 SourceRefs、稳定身份和独立评审索引；模型无需重复枚举观察中的来源，其他观察的来源不会被补入。未知或失配绑定仍拒绝，NON_SCOPE 的两向处置和批准设计／政策的来源权威检查保持有效。

`stable_entity_id` 是唯一 ID 算法：版本、类型、可选父身份、排序证据锚点和合同封闭 discriminator 决定 hash。名称、状态、估算、模型 localKey 不参与。证据不足以区分身份时要求补充输入，不增加位置后缀。Prior 调用同一函数，保留已接受的 sourceId/priorEvidenceId 身份基底。只有经验证且语义唯一、身份未变的 1:1 匹配可保留旧可见 ID。

ChangeGraph 只保存显式 changeGroups 和 retiredPrior。NEW/KEEP 来自当前目标和 effective Prior 的补集，不持久化；duplicate 的非 canonical 对象和已生效 FULL predecessor 不进入 KEEP。

Prior v2 优先一次分析整本工作簿，超过输入块容量才按完整行分组。模型在 Analyze 中理解标题、横纵布局和附注，不另生成布局 IR。只有本项目明确的合同交付形成实体；通用目录、示例、重复汇总给出未提取理由。全局验收、责任、排除和时间限定进入相关实体 semanticSummary 与 evidenceIds；无法确定适用对象时用 unsupportedRegions，不隐藏为无关内容。

`PRIOR_ANALYZE-v2` 用 `unextractedEvidence` 的 sourceId/evidenceIds/reason 按行分组说明，程序检查 assigned evidence 全部被引用或说明。`priorContext` 是同来源、同 workbook hash 的完整行位置索引，Analyze 和 Scope Review 通过现有 hydrate 读取原文，继续使用两轮及 token 限额；每个实体仍需所属 workItem 的主证据。

同一组行证据无法区分多个对象时，实体才提供原始主证据中的 `cellAnchors`，以 `prior-entity-id-v2` 参与稳定 ID；未提供则保留 v1 身份基底。Snapshot 结构不增加字段，准确锚点保留于 Prior IR/Attempt 和 Review obligation；Snapshot、Scope、ChangeGraph 复用同一个身份映射，不按整行覆盖多个对象。

`PRIOR_CONSOLIDATE-v2` 原始输出只有新增 sourceRelations/entitySupersessions。Owner 标准化绑定实际 packet，保留 dependencies 的全部实体、说明和既有关系；完整 normalized result 仍由原有 Attempt hash、唯一 root 和 generation raw 重放证明。旧 v1 prompt/schema 与 IR 可读，不自动升级旧结果；完整历史 run 绑定原源码及合同，不提供新规划器对旧 StagePlan 的透明迁移。

## 物化、验证与评审

`materialize_scope_candidate` 复核完整 StagePlan、实际 packet/hash 和所有有效结果，返回 candidate_bytes、change_graph_bytes、可选 prior_state_bytes、局部 key→最终 ID 映射及 review_obligations。revision 2 复用真实失败 Attempt 的 repair context，不重新规划。

模型必须显式处置三项必需/默认政策，源码有依据时才实例化迁移政策。普通业务/技术实体采用 BUILD/BUILD/SOURCE_GATED；显式 POLICY 关联的实体从对应政策行读取分类、阶段和 inclusion。程序不会补默认候选节点。

`validate_scope_candidate` 单独检查完整 SOW Model 与 ChangeGraph 闭包。`publish_scope_candidate` 通过 publish_new 保存内容寻址的 graph/candidate，重复发布相同字节不重写旧文件。纯转换重复调用应得到相同字节；恢复时避免重复计算及 active-time 边界由 orchestrator 已绑定状态控制，不能新增平行收据。

每个采用的 CODE_ONLY 观察都有 round/Attempt/result/localKey/证据/目标绑定的 PROTOTYPE_INTENT 义务；每个变更匹配和 RETIRE 都有 Prior root/state/证据绑定的 PRIOR_IDENTITY 义务。fresh Scope Review 的 PASS 必须确认这些义务，不能在机械候选生成前要求未来 Review 已存在，也不能增加批准字段。正式关闭还需 orchestrator 把 PASS、候选和完整 Attempt 链共同绑定到 ScopeCheckpoint。

Prior v2 的 PRIOR_EXTRACTION 义务携带未提取说明、原文位置索引和必要的精确锚点。Reviewer 必须补读被排除行，核验项目交付、目录、汇总和限定；机械覆盖不是语义批准。冻结 Prior 错误而 Scope root Repair 无法修改时报告 OWNER_BUG，不删除依赖掩盖问题。

## 校验缓存与测试

Schema 定义检查仅按精确内容字节在进程内复用成功结果，LRU 上限 128。每次仍重新读文件、检查 ID、建立独立 registry 并验证实例和绑定。Scope 独立验证入口也重新读取当前 Schema。

按 [测试分层指南](../../../tests/README.md) 选择当前行为的 unit/integration 节点。Owner 的 direct、57-item、多 Prior、原型及修订恢复测试属于局部 integration；完整 Office、宿主和产品 E2E 保留到最终集成验收。

真实大工作簿的同来源位置索引作为额外上下文完整保留，不消耗 64 KB 的行数据分组目标；完整 packet（含索引、表头、依赖和修复正文）仍由原 model policy 的实际请求预算检查，超容量仍等待。此规则不提高模型容量或截断来源，仅用于尚未发行的新分组。

新计划的 Analyze Action 为 `PRIOR_ANALYZE-v3`：只把既有无损表传输用于初始请求，继续使用上述 v2 专业规则、schema 和证据绑定。更紧凑的请求允许同一预算内共同读取更多完整行；不自动合并实体、不排除索引，也不保证语义通过。旧计划继续使用其冻结合同版本，详见[阶段自动封存](stage-seal.md)。
