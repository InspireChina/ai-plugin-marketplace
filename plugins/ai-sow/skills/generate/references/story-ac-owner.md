# Story/AC Owner 确定性合同

本接口消费已评审 Scope，拥有 Stage 2 的 Story、AC 和 Delivery Annotation。公开状态机切换、fresh Review、checkpoint 封存和恢复避免重复计算由 orchestrator 集成；Owner 局部验证不是完整产品验收。

## 输入与计划

`prepare_story_inputs(scope_candidate_bytes, checkpoint_bytes, *, checkpoint_sha256)` 接收调用者已解析的 sealed Scope 字节和授权 hash，校验当前唯一 checkpoint Schema、PASS、非空 action/review 引用、候选 hash、Stage 1 projection、来源/政策 hash 和当前模型 Schema 绑定。当前使用现存 `SCOPE_CLOSURE` checkpoint 合同；公开完整 Review/Attempt 证明解析在统一 checkpoint 切换时接入，不能把任意带 PASS 的对象视为已授权证明。

Owner 不接收或重读 workbook、cells、Demo 源码或 Prior 分析。相关需求、设计、Feature 和跨 Feature 规则均来自 Scope；未来 checkpoint 的 Prior 引用只按已验证 hash 传递。

复用 `derive_story_obligations`。一般交付义务按具体 Feature 展开；`scopeDecisionKey` 是程序生成的义务句柄。`sourceFactIds` 选择 `fact:<inputItemId>`；`actorKey` 选择其中支持角色/执行对象的事实句柄，其语义充分性由 fresh Review 判断。SIT/UAT 等 Epic 目标政策展开到具体 Feature，只继承该 Feature 的适用设计与 coverage；SOURCE_GATED 政策只授权其 SourceRef 支持的事实。一个 `policy-go-live` 实例保留一份共享义务，以排序首个 Feature 为层级归属，同时保留全部 assignedFeatureIds、coverageSet、来源事实、适用设计及 Feature contexts；不因覆盖多个功能复制发布计量。不同政策实例仍独立，单个共享上线 Story 中具有独立来源的应用/环境/批次也仍可形成不同 Task。Scope 已有 `NO_DELIVERY`、项目级处置和合法 `EXCLUDED_BY_USER` 不生成新交付义务；IR 不增设排除字段，也不能在 Story 阶段重新排除范围。

AtomicWorkItem 使用 `SCOPE_CHECKPOINT / checkpoint hash / 按 subjectId、Feature ID、义务 key 排序的 ordinal`；workItemId 是 versioned obligation body hash。义务展开到单个 Feature 后，边界 key 也按该 Feature 重新计算，保留原独立限定词、限定引用及跨 Feature 规则/目标；共享设计原先适用于多个 Feature 本身不构成当前 Feature 内的另一个独立交付边界。跨 Feature Story 或明确独立结果仍不可合并。`build_story_work_descriptors` 显式调用共享 `make_planned_work`，无 Story 特有 planner。兼容边界保持一起，next-fit 组合独立边界；每个 packet 仅携带其关联事实、Feature、设计和 checkpoint hash context。所有 contexts 使用共享三字段 wrapper，无第二种 packet/normalization 表示。已知 base 超限阻止规划；完整 dependency/repair request 的发行前容量由公共发行边界再次检查。

## 精确 IR 和义务闭合

Story 只包含 `localKey / scopeDecisionKeys / actorKey / deliverableOutcome / sourceFactIds / acceptanceCriteria`；AC 只包含 `localKey / condition / observableResult / sourceFactIds`。每 Story 至少一条可观察 AC，完整关闭所有选中义务；数量由来源支持的独立结果决定，不要求固定两条。只把 Story、AC、引用数组视为集合排序，普通文本不归一化。最终 node、Feature/Story/AC ID、SourceRef、hash、checkpoint 和 replacementSet 均不由模型提供。

`verify_story_ac_decision` 读取当前 Schema 并校验绑定。全部 packet 义务必须关闭，每个 Feature 单独覆盖；不同独立责任、验收或发布边界不能合并。边界检查包括 DELIVERY_POLICY，不能将独立政策与业务义务或另一政策合并成一个 Story；这不阻止同 Feature、同边界的共享设计约束并入业务 Story。AC 事实必须属于 Story；限定词必须由相关 AC 的条件/可观察结果逐字保留。同一 Feature、来源和条件的重复或矛盾结果生成 diagnostic。

`validate_bound_story_context` 在当前输出失败转换范围外准备上下文；`validate_bound_story_result(packet, normalized_bytes)` 复用同一纯绑定核心，不读 Schema/文件、不写记录、不决定预算。公共 `finish` 已完成严格 JSON/schema 和唯一 normalization 后调用它，拒绝结果沿现有 INVALID_IR/revision 2 路径处理。

## 身份、物化和验证

唯一 `stable_ids.py` 受控表扩展 `STORY: DELIVERABLE_OUTCOME`、`ACCEPTANCE_CRITERION: OBSERVABLE_RESULT`。Story 父身份为 Feature；AC 父身份为 Story。程序提供排序来源锚点，Story 额外区分 actor 来源角色与唯一受控表中的政策标签（标签仍绑定实际来源锚点）；名称、localKey、输出顺序不参与身份。选中证据/父身份变化改变 ID。相同锚点无法区分多个身份时要求补充来源，不能用模型自由文本或位置后缀消除碰撞。

`materialize_story_candidate(inputs, plan, ledger, budget_policy)` 复核确定性输入投影、完整 plan、每个 effective SUCCEEDED Attempt、实际 packet/合同/normalized hash 和本轮 Scope 绑定。所有 work 封存后才一次产生候选；各 action 的 localKey 仅在自身命名空间内有意义，完整 union 还检查跨 work 重复规则。

Story/AC 由程序注入父子关系、ID、SourceRef、coverage/requirement/design/policy 引用并按最终 ID 排序。纯 SIT 自动化和上线工程化政策 Story 的 UAT 适用性为 false，业务/技术结果、UAT 自动化和迁移能力为 true，由冻结义务机械推导。上游字节投影不变；结果是内存不可变值，没有新增持久化 receipt。`validate_story_candidate` 独立执行模型、上游写边界、义务、AC 数量和物化字节 hash 校验，并逐节点核对 sealed IR 的完整身份/文本/SourceRef/coverage/UAT 字段及禁止未授权 annotation。节点绑定复用同一纯规则，不重放 ledger/StagePlan 或重新装配完整候选。`publish_story_candidate` 使用内容寻址 `publish_new`，相同字节不重写，新的语义修订保留原文件。

`generation-renderer-v8` 的模型备注投影同步为按稳定 Story/Annotation ID 排序后选择目标与备注顺序；这是本次 fingerprint 更新的可见字节语义依据，未改模板/公式/估算。公开新 IR 示例为 `fixtures/pipeline/stage2/story-ac-decision-results.json`；旧 PATCH fixture 和动态驱动已移除。

测试按 [分层入口](../../../tests/README.md) 选择本次行为；完整 Office/浏览器/E2E 门禁保留至最终集成。
