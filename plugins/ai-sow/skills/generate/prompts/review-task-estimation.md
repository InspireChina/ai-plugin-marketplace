# 独立阶段评审 v1

只使用本 Action 的 candidate、来源证据、风险、ownerIndex 与列明的 reviewObligations；不读取 Author 历史。返回唯一 ReviewDecisionIR：decision 与 findings。PASS 必须没有 finding，其他 decision 至少一个 finding；finding 只有 code、path、subjectIds、evidenceIds、message。

机械校验已先完成。独立判断范围、来源权威、完整性、计量对象、模式与复杂度的语义充分性。REPAIRABLE_SEMANTIC 只用于本 Owner 可修复的语义问题，每个 subjectId 必须是 ownerIndex 中的 root localKey。INPUT_REQUIRED 表示需要新业务材料；CONTRACT_GAP 表示当前合同不支持；OWNER_BUG 表示固定实现错误。SYSTEM 只能由宿主报告 Attempt failure。

对列出的每个 PROTOTYPE_INTENT，PASS 明确确认该原始 round、Attempt、observation 的 CODE_ONLY 目标意图及其候选映射成立。对 PRIOR_IDENTITY 及 PRIOR_SOURCE_EQUIVALENCE，核对原单元格可见 ID 的唯一实体语义、完整 DUPLICATE 来源等价与本轮真实一对一保持；部分重合不得标成完整 DUPLICATE，缺乏判定材料返回 INPUT_REQUIRED。字符串相同或机械验证通过均不能代替此语义判断。

PASS 不增加正面批准字段；所有断言由当前精确 packet/candidate/Attempt 绑定。不得泛化为通用 patch，不得改动上游或发明来源。政策 Story、设计落点、Task 计价边界必须逐项检查。只有 REPAIRABLE_SEMANTIC 可创建后继 Repair。

核对政策的实际交付物：SIT/UAT 自动化必须有可执行的测试代码或脚本，联调方案、人工执行记录或常规支持不能替代。上线工程化须有来源支持的版本化脚本、配置或发布工程产物；同一应用、环境与批次只按其真实对象计量，不能按功能重复收费，也不能以“免费/只计一次”的文字声明抵消实际存在的计价 Task。独立应用、环境或批次仍须保留有独立来源支持的计量。

先读取 taskRules 中本候选全部已选工作类型的完整本轮模板规则；用包含/排除、计量单位、模式、复杂度、拆分和不建 Task 条件判断，不靠工作类型名称推测。逐项核对 Task 自身引用的 AC/证据是否支持其全部声明，再遍历可能重叠的 Task 组合，包括不同工作类型。共同设计或来源不足以证明重复；工程资产形成与正式执行只有在产物、验收边界清楚且不重复包含同次执行时才可分别计价。需要修正时一次报告当前候选中全部可确认的问题和对应 Owner roots，不在发现首个问题后停止；不要求增加来源未提出的交付物。
