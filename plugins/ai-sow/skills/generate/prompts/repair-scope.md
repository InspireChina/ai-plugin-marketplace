# SCOPE 语义修复 v1

根据 reviewDecision 修复现有结果，使用原 scope-decision IR。只返回 authorizedRootKeys 范围的完整替换对象，其余 ownerIR 由程序原样保留。允许：原位调整；将多个授权 roots 合并为一个并保留其中一个 localKey；将授权 root 拆成 root:repair:<有意义的后缀>。拆分后缀只使用 localKey Schema 允许的字符。合并或拆分时，返回受影响子图的全部保留对象；原 finding 指定范围中未返回的 roots 会移除；仅因引用而进入影响闭包的其它 roots 未返回时由程序保留，所有事实、限定条件、设计、政策、AC 和引用义务仍须完整关闭。修复目的只限本次 findings 及其必要影响范围。

保留已经正确的内容。先核对来源和模板，修正最小必要边界，再检查完整结果。不得重写整个 Owner、修改上游 checkpoint、制造计价对象或提交 patch/value、最终 ID。局部修复会生成一个新候选，完整机械校验和独立 fresh Review 均通过才封存；仍有问题时报告真实缺口，不能靠重试碰运气。

证据 ID 与政策 ID 属于不同集合：boundaryEvidence.evidenceIds 和 relations[].evidenceIds 只能选择冻结 DEPENDENCY_RESULT 事实/历史实体已有的 evidenceIds，或 PROTOTYPE_OBSERVATION_REF.evidenceIds。policy-sit-automation 等 policyId 只能用于 POLICY_INSTANCE.classification，绝不能填入 evidenceIds。默认交付政策由 deliveryPolicy 确定，政策实例和其 APPLIES_TO/POLICY 关系须引用本轮实施范围的真实来源证据（例如所关联 Epic 的交付事实）；不把政策 ID 伪造为来源证据。每个 observationKeys 也必须在全局恰好处置一次。

POLICY_INSTANCE 的 APPLIES_TO 已表达政策目标，不要求对业务 Epic/Feature 增加反向 POLICY。POLICY 关系会选择该节点自身的交付生命周期；不得把 SIT、UAT、GO_LIVE 三个不同阶段的政策同时作为同一个业务节点的 POLICY 关系。常规业务节点保持其业务分类；默认三项政策分别用 POLICY_INSTANCE 的 APPLIES_TO 关联实际范围即可。ASSUMPTION 事实是项目级前提，Owner 投影为 PROJECT_GATE/PROJECT_LEVEL_ONLY，不自动成为供应商 Story/Task；可以把它关联到依赖该前提的集成边界，不发明额外交付能力。

粒度与关系类型必须分别检查：不同协议或接口对象（例如身份协议与业务 API）各自形成独立 INTEGRATION，不能仅因责任方相同就合并。DESIGN_ITEM/INTEGRATION/NFR 的 APPLIES_TO 目标只允许 FEATURE，绝不指向 EPIC；适用于整个组件的设计应列出其实际覆盖的所有 Feature，而非用 Epic 替代。只有 POLICY_INSTANCE 的 APPLIES_TO 可指向 Epic。修复仍须遵守这些类型约束；Scope 的 authorizedRootKeys 已包含引用问题 root 的同 Owner 影响闭包；拆分或合并后须同步更新这些关系，所有 targetLocalKeys 指向保留对象。

每个 factId 只由一条 decision.factIds 处置；其他 root 可引用同一证据或 facetFacts，但不得重复取得事实归属。Integration 的 DIRECTION 应选描述该接口交互的具体事实，不使用同时列举多项客户提供物的综合责任事实。Integration 的 facetFacts 角色仅为 DIRECTION、TRIGGER、PURPOSE、DATA_CATEGORY，不含 TARGET。
