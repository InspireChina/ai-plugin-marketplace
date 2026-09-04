# R1 Source Scope Join

遵守 Reviewer 角色与输出合同。读取全部已验证 Source Audit result、按 logical shard 排序的 leaf hash、完整 Stage 1 candidate 与全量原始 coverage root inventory。

反向核对 PRD 与选入 Demo 的需求并集、批准 HLD/ADR 的设计权威、InputItem 原子性与限定词、ScopeClosure 唯一落点、Epic/Feature 边界、Integration、NFR、跨 Feature 规则、范围扩张和交付政策。不得使用 PRIOR_SOW 对象内容判断本期范围。

必须完成 `SOURCE_TO_INPUT / SCOPE_CLOSURE / TECHNICAL_CLASSIFICATION / EPIC_FEATURE_BOUNDARY / DESIGN_SUFFICIENCY / SCOPE_EXPANSION / DELIVERY_POLICY`。`sourceAuditCoverageUnion` 必须精确等于全部 audit shard union。PASS 只返回常量级统计字段与空 findings。
