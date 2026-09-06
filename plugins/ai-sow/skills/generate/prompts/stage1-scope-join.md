# Scope Decision v1

无损保留所有 dependency 的事实处置并统一边界。只读 frozen contextRefs 与唯一 planner DEPENDENCY_RESULT wrapper，不继承会话历史。
只返回 ScopeDecisionIR {decisions}；每个 factIds 句柄恰好有一个处置，句柄为 coverageRootId:localKey。priorEntityIds 选择 Prior root 的精确 entity localKey，Owner 转为 snapshot ID；不得自行散列 ID。
decisionKind 为 EPIC/FEATURE/DESIGN_ITEM/INTEGRATION/NFR/POLICY_INSTANCE/EXCLUDE/RETIRE。boundaryEvidence 含 name、classification、evidenceIds、facetFacts、observationKeys；仅 INTEGRATION 还必须提供 responsibilityBoundaryIds，从 SCOPE_CONTEXT.responsibilityBoundaries 中选择已有 responsibilityBoundaryId，禁止自行生成。不能嵌套最终节点。classification 必须匹配该类型的封闭 enum。
name 必须受所选来源证据支持；它不参与身份。facetFacts 以 role/factId 选择来源事实，禁止发明设计事实。Feature 必须通过 PARENT 指向 Epic；其他关系仅选择实际 localKey 与来源证据。
关系为 PARENT/APPLIES_TO/DESIGN/POLICY/REUSE_DEPENDENCY/ADJUST/SPLIT/MERGE/UNCHANGED_IDENTITY；新 SPLIT/MERGE 身份不继承。UNCHANGED_IDENTITY 只用于证据证明的唯一1:1未变匹配，fresh Review 独立复核。
EXCLUDE/RETIRE 必须有 exclusionReason。RETIRE 必须有 Prior 证据与本轮明确移除证据；本期未提及不代表退役。不能猜 n:m 中间实体。
原型只是目标候选：完整 round/result/Attempt 绑定由 Owner 提供。采用 CODE_ONLY 的 observationKeys 形成独立 Scope Review 意图义务；不生成批准字段。未解决的来源/边界问题保存在 uncertainty 并要求输入，不能伪装通过。

读取 SCOPE_CONTEXT.deliveryPolicy：全局结果必须对 policy-sit-automation、policy-uat-automation、policy-go-live 各显式生成唯一 POLICY_INSTANCE，通过 APPLIES_TO 选择本轮 Epic/Feature。Proposal 保留本片适用候选，Join 合并成全局唯一政策处置。policy-data-migration 仅在 sourceRoles 允许的当前来源明确提出迁移或持续同步时生成，必须选择对应 factIds；不能靠关键词猜测或无来源实例化。
DESIGN_ITEM 只能选择 sourceDirectory 中 role=HLD/ADR 且 status=APPROVED 的来源证据。其他来源只能表达需求或原型意图，不能证明批准设计。缺少批准设计/边界时保留 uncertainty，不猜节点。
INTEGRATION 的 facetFacts 必须各有一个 DIRECTION/TRIGGER/PURPOSE 和至少一个 DATA_CATEGORY；NFR 必须有一个 TARGET；其他类型的 facetFacts 为空。字段文本由 Owner 从选中的事实原文生成。
PARENT 仅用于 FEATURE→唯一 EPIC；APPLIES_TO 用于 DESIGN_ITEM/INTEGRATION/NFR→FEATURE 和 POLICY_INSTANCE→EPIC/FEATURE；DESIGN/POLICY 用于 EPIC/FEATURE→对应类型。REUSE_DEPENDENCY/ADJUST 只能1:1，SPLIT只能1:n，MERGE只能n:1；同一 Prior 或目标只能进入一个显式变更组。

证据 ID 与政策 ID 属于不同集合：boundaryEvidence.evidenceIds 和 relations[].evidenceIds 只能选择冻结 DEPENDENCY_RESULT 事实/历史实体已有的 evidenceIds，或 PROTOTYPE_OBSERVATION_REF.evidenceIds。policy-sit-automation 等 policyId 只能用于 POLICY_INSTANCE.classification，绝不能填入 evidenceIds。默认交付政策由 deliveryPolicy 确定，政策实例和其 APPLIES_TO/POLICY 关系须引用本轮实施范围的真实来源证据（例如所关联 Epic 的交付事实）；不把政策 ID 伪造为来源证据。每个 observationKeys 也必须在全局恰好处置一次。

POLICY_INSTANCE 的 APPLIES_TO 已表达政策目标，不要求对业务 Epic/Feature 增加反向 POLICY。POLICY 关系会选择该节点自身的交付生命周期；不得把 SIT、UAT、GO_LIVE 三个不同阶段的政策同时作为同一个业务节点的 POLICY 关系。常规业务节点保持其业务分类；默认三项政策分别用 POLICY_INSTANCE 的 APPLIES_TO 关联实际范围即可。ASSUMPTION 事实是项目级前提，Owner 投影为 PROJECT_GATE/PROJECT_LEVEL_ONLY，不自动成为供应商 Story/Task；可以把它关联到依赖该前提的集成边界，不发明额外交付能力。

粒度与关系类型必须分别检查：不同协议或接口对象（例如身份协议与业务 API）各自形成独立 INTEGRATION，不能仅因责任方相同就合并。DESIGN_ITEM/INTEGRATION/NFR 的 APPLIES_TO 目标只允许 FEATURE，绝不指向 EPIC；适用于整个组件的设计应列出其实际覆盖的所有 Feature，而非用 Epic 替代。只有 POLICY_INSTANCE 的 APPLIES_TO 可指向 Epic。修复仍须遵守这些类型约束；若单个授权 root 无法完成所需拆分，不添加未授权 root 或伪称修复完成。

每个 factId 只由一条 decision.factIds 处置；其他 root 可引用同一证据或 facetFacts，但不得重复取得事实归属。Integration 的 DIRECTION 应选描述该接口交互的具体事实，不使用同时列举多项客户提供物的综合责任事实。Integration 的 facetFacts 角色仅为 DIRECTION、TRIGGER、PURPOSE、DATA_CATEGORY，不含 TARGET。
