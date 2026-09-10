# AI SOW Lite 设计

Lite 采用两个独立入口：generate 补足必要输入后出首稿，clarify 根据反馈讨论并应用有限修改；两者通过项目文件衔接。准确性和减少返工优先，耗时与 token 持续观测，不设置资源预算审批。

本目录用于领域和架构维护。当前用户说明见 [README](../../README.md)，实现与验证状态见 [验证摘要](../validation/README.md)；实施计划、设计审阅和阶段指标已归入 [历史档案](../archive/README.md)。

## 已定边界

- 单人串行使用，一个主 session 完成专业工作；工具管理来源、机械检查、Excel 和版本，不用逐 Action 编排业务推理。
- 往期 SOW 构建估算 as-is，PRD/HLD 及可选原型构建 to-be，识别业务、技术、交付三类 gap。共享能力建设与业务接入分清，避免重复计量。
- Epic/Feature 骨架后按相关范围切片，逐步形成 Story、简明 AC 和 Task。信息不足、无进展和返修都遵守有限出口。
- 待确认只服务工作量估算；未知复杂度默认 M，历史候选实例未明先按新建并留问题，其他无据结论不编造。
- Excel 四表原列交付，完整 AC 和目标行备注可独立阅读；估算与适用性由 [模板](../../assets/sow-template.xlsx) 计算。
- 用户可直接使用首稿，无需定稿。Clarify 在具体方案确认后更新有限切片，保留历史版本。

## 按主题阅读

| 主题 | 文档 |
|---|---|
| 领域用语与边界决定 | [CONTEXT](CONTEXT.md)、[已定边界](13-self-review-and-decisions.md) |
| 用户流程与输入 | [01 流程与用户介入](01-workflow-and-user-input.md)、[02 输入与模型](02-inputs-and-domain-model.md) |
| Agent 工作与修改 | [03 专业执行](03-agent-execution-and-review.md)、[04 有限修改与恢复](04-bounded-change-and-recovery.md) |
| Excel 与观测 | [05 交付](05-excel-and-delivery.md)、[06 资源与验证](06-observability-and-validation.md) |
| 数据与输入补充 | [09 共享文件](09-shared-files.md)、[10 草稿输入](10-draft-inputs.md) |
| 场景与取舍 | [07 决策目录](07-gaps-and-decisions.md)、[08 场景目录](08-scenario-catalog.md) |
| 数据合同、调用与异常 | [详细设计 D00—D09](detailed/README.md) |
| 流程图源 | [整体流程](diagrams/workflow.mmd)、[两个入口](diagrams/entrypoints.mmd)、[生成分片](diagrams/generate-slices.mmd)、[改稿时序](diagrams/clarify-change-sequence.mmd) |

设计中的合成走读不是执行证明。现行运行协议以 [工具合同](../../references/tools.md) 与对应 Schema 为准，专业入口规则在 Skill 和 references 中维护。
