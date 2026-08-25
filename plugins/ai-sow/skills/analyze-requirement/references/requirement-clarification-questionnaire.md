# 需求澄清问卷

当需求来源不足以稳定确定业务范围、目标、规则、优先级或验收意图时使用本参考。问卷是供人评审和回填的 Markdown 状态，不是稳定业务 JSON。

## 生成条件

先完成来源登记和直接分析。仅为可能改变业务结论的缺口、冲突或歧义提问；技术架构、实现方式和技术选型交给 `generate-design`。

建议路径：`.ai-sow/reviews/analyze-requirement-questionnaire.md`。

## 问题记录

每个问题使用 `### <Question ID>` 标题和独立表格，并填写全部字段：

| 字段 | 内容 |
|---|---|
| Question ID | 稳定、唯一，例如 `ARQ-001` |
| Type | `GAP`、`CONFLICT` 或 `AMBIGUITY` |
| Source | `sourceDocumentId` 与可复核的页、章节或段落锚点 |
| Gap or conflict | 缺失、冲突或歧义的原始事实 |
| Business impact | 对范围、目标、规则、优先级或验收意图的具体影响 |
| Options | 互斥选项及其范围影响；允许明确的自由回答 |
| Recommendation | 建议选项 |
| Rationale | 建议为何最符合现有业务证据，以及采用它的影响 |
| Answer | 用户回填的选择或文字答案 |
| Status | `OPEN`、`ANSWERED`、`APPROVED_DEFAULT` 或 `CLOSED` |
| Blocking | `YES` 或 `NO`，并说明判定依据 |
| Decision date | 用户确认答案或默认处理的日期 |
| Decision evidence | 可复核的评审记录或用户确认摘要；不得只写“已批准” |
| Disposition | `INCORPORATED_BUSINESS:<epic-or-feature-id>`、`ASSUMPTION_CANDIDATE` 或 `NO_CHANGE` |

## 评审与回填

1. 生成后向用户呈现问题、业务影响和建议，不代替用户填写 `Answer`。
2. 将收到的答案逐项回填，并记录 `Decision date` 和可复核的 `Decision evidence`；冲突答案保持 `OPEN`，直到用户明确裁决。
3. `Blocking: YES` 的问题必须在稳定 BUSINESS 需求获批前变为 `CLOSED`。答案改变业务结论时使用 `INCORPORATED_BUSINESS:<stable-id>`，先更新并批准对应 BUSINESS Epic/Feature；下游不再把它编译为 Assumption。
4. `Blocking: NO` 的未知项只有在用户明确接受默认处理时才能标记 `APPROVED_DEFAULT`，且 `Disposition` 必须为 `ASSUMPTION_CANDIDATE`。它保留在本问卷中，由 `generate-story` 恰好消费一次；未获批的默认项仍是开放问题。
5. 不改变业务结论且无需默认处理的关闭问题使用 `CLOSED` 与 `NO_CHANGE`。问卷保留完整状态作为跨会话评审证据，不复制到另一份 review 或新增稳定 JSON。

## 下游 handoff

`.ai-sow/reviews/analyze-requirement-questionnaire.md` 是 `APPROVED_DEFAULT` 的唯一消费源。需求评审用 `Questionnaire: <path>` 声明它，或用 `Questionnaire: NOT_REQUIRED` 明确本次没有问卷。`generate-story` 只把同时具备 Question ID、用户 Answer、Decision date、Decision evidence、`Status: APPROVED_DEFAULT` 和 `Disposition: ASSUMPTION_CANDIDATE` 的记录编译为 Assumption 候选。声明、文件、字段或状态不完整时，下游必须阻塞并返回本阶段补全；不得根据上下文猜测。

## 完成检查

- 每个问题可追溯到来源和具体业务影响；
- 所有关键问题已关闭；
- 每个获批默认项均有明确用户答案、决策日期、状态证据和 `ASSUMPTION_CANDIDATE` 处置；
- 每个改变业务结论的关闭答案都引用已获批的 BUSINESS Epic/Feature；
- 技术问题未在本问卷中被擅自解决；
- 只有批准后的业务结论进入 `requirements.json`。
