# 当前步骤候选的增量修复 v1

本协议只处理当前未封存工作。`Origin.sourceKind` 区分 `AUTHOR_FAILURE` 与 `SEMANTIC_REVIEW`：
前者绑定原始失败 Attempt/raw；后者绑定成功的非 PASS Review、程序侧 Owner IR base 和
`semanticSourceSha256`。`CANDIDATE_REPAIR_PROTOCOL_SELECTED` 在 lineage 首个 Patch 发行前固定协议与合同 hash。

Owner 诊断并提供 `SET_FIELD / REMOVE_FIELD / APPEND_OBJECT / REMOVE_OBJECT / TRANSFORM_ROOTS` 槽位；模型只填写增量。
`REMOVE_FIELD` 仅删除 Schema 明确拒绝的现存附加属性，不携带 `value`；`REMOVE_OBJECT` 仍只删除 Owner 明确授权的集合成员。Patch 必须提交全部普通槽位，并从每个 `alternativeSet` 恰选一个。程序拒绝重叠写集合、重复集合修改、
过期 base、越权引用、身份复用和不完整引用闭包。后续计划以 `previousReceiptSha256` 绑定紧邻的成功
RepairReceipt；匿名重复行沿 receipt 保持 occurrence 身份。

模型只接收本组问题、当前字段、必要证据与邻居。完整候选、保护索引和语义 Owner IR base 留在程序侧。
非法 JSON 仍走既有有界格式恢复；可解析的 Schema-invalid 候选走槽位修复，后续非法 raw 不能撤销
receipt-bound 保护基线。

原失败 Attempt 保持 FAILED。成功 Patch 先保存 raw、RepairReceipt 与物理 AttemptRecord，再由
CandidateResolution 解析完整有效 Owner IR；派生结果不会进入 `effectiveAttemptRecordSha256s`。
语义修复只证明 Owner 机械合同通过，随后必须物化新候选并发行 distinct fresh Review；只有该 Review
返回 PASS 才能封存阶段。已物理发行的旧 `*_REPAIR-v1/v2` 仍按冻结合同完成，不转换为 Patch。

次数、执行、hydrate、active-time 和 token 沿原 run 累计。相同候选、诊断、证据、授权和无效提议
不再发行；输入、合同缺口、Owner 缺陷、执行和真实预算/容量分别路由。portable proof 重放 base、
semantic source、plan、patch、receipt、对象索引、选择事件、物理记录和 CandidateResolution。
