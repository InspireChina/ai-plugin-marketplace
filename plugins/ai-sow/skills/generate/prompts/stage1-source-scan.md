# SOURCE_SCAN v1

只读 packet.workItems 的 SourceBlock、来源角色和紧凑目录；不继承任何 Author 历史。
返回 FactDecisionIR 数组，每个 coverageRootId 恰好一条；FACT 必须含带证据事实，NO_RELEVANT_FACT 必须空 facts 并解释理由。
事实只写 localKey、factKind、statement、evidenceIds、qualifiers。localKey 在该 root 内唯一；evidenceIds 只能选该 work item 授权的证据。
保留阈值、否定、排除、例外、角色、时间条件及其语义顺序。不能写最终实体、ID、SourceRef、hash、checkpoint 或旧 replacementSet。

客户或第三方负责提供、且不由本供应商交付的已有服务、环境、资源或访问条件，标为 ASSUMPTION 项目前提；不能仅因句式为“提供”就标成供应商 REQUIREMENT。供应商需实现的对接行为使用其独立来源事实保留为 REQUIREMENT/CONSTRAINT，不把外部系统本体采购进来。
