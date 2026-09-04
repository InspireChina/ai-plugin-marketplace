# Stage 1 Global Scope Proposal

遵守 Author 角色/输出合同，并使用 `source-authority.md`、`epic-authoring.md`、`feature-authoring.md`、`technical-work-classification.md` 与 `delivery-lifecycle-policy.md`。

读取 packet 的全量 `inputItemIdInventory`、分配的 `localInputItems`、相邻 `boundarySummaries` 和跨 shard affinity。提出候选价值边界、工作性质和关联，但不要生成或宣称最终 Epic/Feature ID/归属，不要写 SOW Model replacement。

覆盖对象数量不是拆分依据。共享配置、责任、验收和发布边界的多个服务保持一个候选能力；仅当独立定制、责任、验收或发布边界由来源证明时建议拆分。保留指向其他 shard 的关系，不按来源章节、前后端岗位或预想 Feature 分片。

返回 `SCOPE_PROPOSAL`；`inputItemIds` 必须精确覆盖本 shard 分配，`boundaryCandidates` 只使用 proposal-local `boundaryId`。
