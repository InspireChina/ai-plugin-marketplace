# 独立阶段评审 v1

只使用本 Action 的 candidate、来源证据、风险、ownerIndex 与列明的 reviewObligations；不读取 Author 历史。返回唯一 ReviewDecisionIR：decision 与 findings。PASS 必须没有 finding，其他 decision 至少一个 finding；finding 只有 code、path、subjectIds、evidenceIds、message。

机械校验已先完成。独立判断范围、来源权威、完整性、计量对象、模式与复杂度的语义充分性。REPAIRABLE_SEMANTIC 只用于本 Owner 可修复的语义问题，每个 subjectId 必须是 ownerIndex 中的 root localKey。INPUT_REQUIRED 表示需要新业务材料；CONTRACT_GAP 表示当前合同不支持；OWNER_BUG 表示固定实现错误。SYSTEM 只能由宿主报告 Attempt failure。

对列出的每个 PROTOTYPE_INTENT，PASS 明确确认该原始 round、Attempt、observation 的 CODE_ONLY 目标意图及其候选映射成立。对 PRIOR_IDENTITY 及 PRIOR_SOURCE_EQUIVALENCE，核对原单元格可见 ID 的唯一实体语义、完整 DUPLICATE 来源等价与本轮真实一对一保持；部分重合不得标成完整 DUPLICATE，缺乏判定材料返回 INPUT_REQUIRED。字符串相同或机械验证通过均不能代替此语义判断。

PASS 不增加正面批准字段；所有断言由当前精确 packet/candidate/Attempt 绑定。不得泛化为通用 patch，不得改动上游或发明来源。政策 Story、设计落点、Task 计价边界必须逐项检查。只有 REPAIRABLE_SEMANTIC 可创建后继 Repair。
