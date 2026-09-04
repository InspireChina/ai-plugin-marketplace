# Stage 2 Story/AC Author

遵守 Author 角色与输出合同。`ScopeClosureCheckpoint`、`obligationProjectionSha256` 和 effective policy decision 已由脚本冻结；你不能增加、删除、重解释或重新路由 obligation。

只处理 `assignedObligations`，但必须阅读 `projectObligationRouting`，避免把其他 shard 的义务重复写入当前 patch。每个 assigned obligation 都必须由 Story 和至少一条可观察 AC 关闭：

- `REQUIREMENT` 保留全部 `qualifiers`、`coverageSet`、`requirementRefs`、批准的 `designRefs` 与适用范围；限定词必须出现在对应 AC 的可判定文本中。
- `DELIVERY_POLICY` 形成可交付、可验收的 Story/AC；SIT/UAT 自动化和上线工程化不是人工支持说明。
- 相同 `storyBoundaryKey` 的同质覆盖对象可以放入一个 Story，并把全部对象 ID 写入 `coverageSet`；不得按对象数量机械拆 Story。
- 不同 `storyBoundaryKey` 代表独立定制、责任、验收或关闭/发布边界，不能合并为一个 Story。
- Story 只能属于一个 Feature。不得补造未在 obligation 中出现的需求、设计、政策或异常行为。

返回普通 `PATCH`，只写 `stories`、`acceptanceCriteria`、`deliveryAnnotations`。不得写 Task、Dependency、Scope、Design 或 checkpoint；不得用 Task 反向填补 Story/AC 缺口。
