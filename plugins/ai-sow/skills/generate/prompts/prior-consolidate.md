# 往期合同合并

读取唯一 DEPENDENCY_RESULT context wrapper 的 normalizedResult。无损原样保留全部 dependency entity（含 localKey/source/evidence）、source relation、supersession 和 unsupported region；不得丢失、重复或改写，只补充跨 dependency 关系直到唯一 root。

只接受 packet 授权的 PRIOR_SOW 来源、证据和 PROJECT_EFFECTIVE_START 日期。相对 plannedEffectiveDate 判断 deliveryStatus：明确排除、取消、未实施、未来计划分别使用 EXCLUDED/CANCELLED/NOT_IMPLEMENTED/FUTURE；其余肯定合同交付物默认 CURRENT_BY_CONTRACT。这是合同推定，非 telemetry 或现场部署验证。Demo 即使是有效目标范围证据，也不得进入本结果。

输出精确 PriorStateDecision：entities/sourceRelations/entitySupersessions/unsupportedRegions；entityKind 只允许 CONTRACT_ENTITY，隐含受控 discriminator 为固定 tuple ["CONTRACT_ENTITY"]。不得输出最终 ID、SourceRef、hash 或 snapshot。localKey 使用 packet workItemId 的冒号 namespace。

sourceRelations 端点按 sourceId 排序，只声明 DUPLICATE/COMPLEMENTARY/CONFLICT/UNRELATED。DUPLICATE 仅表示完整 source 实体集合等价，部分重合不可标为 DUPLICATE；程序不比较摘要判断等价。DUPLICATE 连通分量内替代端点只引用 sourceId 最小的 canonical source。替代仅支持完整 FULL entity replacement，精确 predecessor/successor localKeys 与版本、替代声明、有效日期或 replacement 证据；全部 successor CURRENT 表示已生效，全部 FUTURE 表示未生效。混合状态、未消解冲突和无法读取业务区域要求补材料后新 run，不按文件顺序或常识裁决。

visiblePriorId 可选：只声明 selected evidence 中可读 whole-cell ID literal，且该 ID 指向一个身份未改变、唯一可识别的合同实体。字面相等不证明语义匹配；Scope fresh Review 独立复核这一义务。无足够身份使用证据绑定的新身份，不猜测隐藏历史 ID。
