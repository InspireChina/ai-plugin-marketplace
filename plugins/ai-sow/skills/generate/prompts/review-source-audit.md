# SOURCE_AUDIT v1

独立读取 contextRefs 中的同一原始 SOURCE_BLOCK 和唯一 DEPENDENCY_RESULT normalized FactDecision。不读取 Author 会话历史。
逐 coverage root 检查 THRESHOLD、NEGATION、EXCLUSION、EXCEPTION、ROLE、TIME，每类恰好一次。
返回精确 SourceAuditIR {checks}，COVERED 引用对应 root 的 relatedFactKeys；MISSING 和 NOT_APPLICABLE 必须说明理由。所有 evidenceIds 属于该原始块。
MISSING 保留执行事实，但阻止 Scope 完成；不能把漏读改为 NOT_APPLICABLE、复制事实正文或生成 Scope 节点/ID/hash。
