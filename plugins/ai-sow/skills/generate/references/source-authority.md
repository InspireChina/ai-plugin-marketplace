# 来源权威与提取规则

## 来源角色

- `PRD` 是本期业务需求的主要且必需来源。
- 用户明确选入的 `DEMO` 与 PRD 共同构成需求并集，但 Demo 只能证明可观察的页面、入口、动作、状态、校验、权限与结果，不能证明后端、数据、集成或部署设计。
- 只有状态为 `APPROVED` 的 `HLD` 或 `ADR` 可作为实施设计依据。
- `SUPPLEMENT` 与已绑定的问答只补充其明确陈述的事实，不静默覆盖其他来源。
- `PRIOR_SOW` 只用于后续 Effective Start 匹配，不用于创造本期范围、设计或复杂度。

## 原子提取

一个 InputItem 表达一个可独立判断的事实。不同主体、条件、阈值、禁止项、适用范围或责任方不能因位于同一段落而被无依据合并。原文同时包含多个独立义务时拆成多个 InputItem，并让每项保留相同的精确 SourceRef。

`kind` 只使用：`REQUIREMENT`、`DESIGN_DECISION`、`CONSTRAINT`、`RESPONSIBILITY`、`EXCLUSION`、`CONFLICT_CANDIDATE`。发现来源互斥时只记录 conflict candidate，不自行选择优先级。

`text` 保留足以独立理解的完整命题；`conditions`、`thresholds`、`prohibitions`、`applicableScopes` 分别保存命题中的限定信息。没有某类限定时使用空数组，不得补造默认值。

## SourceRef

每个 InputItem 至少引用一个 packet 分配的 block。`sourceId/blockId/sha256/locator` 必须与 Input Revision 完全一致。不能用章节摘要、候选节点或模型记忆替代 SourceRef。

## 写入与错误边界

Source Scan 只写 `inputItems`。Epic/Feature、设计对象规范化、范围闭包和交付政策实例由 Global Scope Join 决定；Story/AC/Task 属于后续 Owner。解析问题写 `PARSE_ISSUE`，权威事实缺失写 `GAP_CANDIDATE`，合同缺口写 `DIAGNOSTIC_CANDIDATE`。
