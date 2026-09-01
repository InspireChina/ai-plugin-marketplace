# AI SOW 跨层终审合同

终审者必须在全新上下文中工作，只读取本文件、精确的 `review-packet.json`，以及 packet 的 `sourceRefInventory` 指向的 pending 来源快照。不得读取对话历史、Git 历史、旧 Owner 评审、未引用项目文件或其他客户材料。

## 输入与输出

- 输入 packet 已绑定 InputManifest、完整 Scope、完整 Delivery、ID 决定、ImpactPlan、模板哈希和机械校验结果。
- 来源快照只用于核对已列出的 SourceRef。不得把来源全文复制到评审结果。
- 输出只能是一个符合 `final-review.schema.json` 的 JSON 对象，不得创建用户批准 sidecar。
- `PASS` 不带 notes/questions；`PASS_WITH_NOTES` 的每条 note 必须绑定真实固定边界；`BLOCKED` 必须给出最少、去重、可由用户回答的问题。

## 必查清单

1. 来源忠实度：业务结果服从 PRD，目标实现机制服从 HLD；二者冲突不得静默调和。
2. Brownfield 起点：往期承诺已经逐项处置，Effective Start 有来源、适用边界和复用依据。
3. Scope 完整性：Feature、Design、Integration、NFR、假设、责任和排除项彼此一致；所有 `IN_SCOPE` 结果均有可交付落点。
4. Delivery 追踪：每个 Story 连接 Feature，每条 AC 可观察且被同 Story Task 覆盖，每个 Task 只使用模板允许的基础单元、工作模式和复杂度。
5. 设计与集成：需要设计的 Integration/NFR 有 DESIGN Task；每个需实现 Integration 恰好有一个 Integration Task；常规设计工作不得重复计价。
6. 增量连续性：受影响切片被完整替换；未受影响对象与 ID 保留；实质变化对象使用新 ID；删除对象不再被引用。
7. 估算边界：系统数、接口数、实例数、数据量、环境、迁移、测试和第三方责任足以选择模板计数单位；未知项已有固定边界与 change trigger。
8. 责任与排除：供应商、客户、第三方的输入、环境、验收和依赖责任清楚；排除内容不能以笼统“支持”任务回流。
9. 隐私与呈现：不包含凭据、本机绝对路径、私有仓库信息、完整工具输出或无关客户原文；用户摘要中的 Feature/Story/Task 数量与 packet 一致。

## BLOCKED 判定

只有同时满足以下三项才允许 `BLOCKED`：缺失事实会改变范围、验收或估算；无法由已有来源或固定边界推导；问题可以由用户给出一个明确答案。不得要求详细 API 字段、低层设计或额外用户批准，只要可以用 Design Task、estimate boundary 和 change trigger 固定风险。
