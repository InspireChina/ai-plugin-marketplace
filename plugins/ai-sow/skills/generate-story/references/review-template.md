# 交付 Story 评审

普通流程先把本模板确定性投影为 `.ai-sow/work/generate-story/review.candidate.md`。其中
`Reviewer: PASS` 与 `User Approval: APPROVED` 是拟发布声明，只有
`ai-sow-owner-reviewer-v1` 和 `ai-sow-owner-approval-v1` sidecar 同时绑定当前
`ai-sow-owner-review-packet-v1` packet 后才具有授权效力；批准前不得写正式 review。

## Feature → Story

逐项说明每个 `IN_SCOPE` Feature 相对 Effective Start 的差值、AC 的 `gapRationale`、逐条纳入的 `CARRY_FORWARD` Commitment 及结果型 Story；`FULLY_COVERED / OUT_OF_SCOPE` 不生成 Story。

Stable IDs: story-example, ac-example, integration-example, assumption-example

## Acceptance Criteria

逐个 Story 列出有序、独立、可观察且可判定通过或不通过的 AC，并说明 UAT 分母、上线前置、失败/回滚边界和责任方。

## Integration

列出 Integration 的 source、target、trigger、direction、purpose、owner、delivery boundary、target kind、Design Decision 引用和可选 `decisionRationale`。有类型化 Design Decision 时逐项核对它关联当前 Story Feature；`decisionIds` 为空时，确认 `decisionRationale` 具体说明该集成为何只是无需类型化批准的实现边界。逐项确认每个 `requiredIntegrationBoundary != NONE` 的 Story 至少有一条边界一致的 Integration；共享适配能力不能替代各交付 Story 自身的可验收集成结果。反向检查带 `relatedBusinessFeatureIds` 的横切 TECHNICAL Story：它只能拥有独立可验收的项目侧共享适配器/控制端口，不得把两个或更多相关 BUSINESS Story 已登记的提供方 target 聚合成重复端到端 Integration，也不得用 AC 重复声明这些业务调用的映射、幂等、重试、异常处置或核对。

## Assumption / Risk

每项 Assumption/Risk 只保存一次，明确 trigger、handling、responsibility boundary、status 与关联 Story。

## Questionnaire consumption

没有获批默认项时：

Questionnaire Map: NONE

存在获批默认项时，每个 Question ID 恰好映射一个 Assumption 和至少一个 Story，例如：

```text
Questionnaire Map: ARQ-001=assumption-example->story-example
```

## 上线映射

恰好列出十个 Concern。`IN_SCOPE` 行必须映射到当前交付的 Feature 以及 Story 或 Assumption/Risk；不适用项明确责任边界和依据。

| Concern | Disposition | Feature IDs | Story IDs | Assumption/Risk IDs | 责任边界 | 依据 |
|---|---|---|---|---|---|---|
| PRODUCTION_SCOPE | IN_SCOPE | feature-example | story-example | — | 项目负责获批生产交付，客户负责生产审批。 | 已批准技术范围要求该能力达到生产可用。 |
| ENVIRONMENT_CONFIGURATION | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| DEPLOYMENT_CUTOVER_ROLLBACK | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| DATA_MIGRATION | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| PRODUCTION_VALIDATION | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| OBSERVABILITY | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| OPERATIONS_HANDOVER | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| POST_GO_LIVE_SUPPORT | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| USER_ENABLEMENT | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| LEGACY_RETIREMENT | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |

Go-live Mapping: PASSED

## 审查与批准

Reviewer: PASS
User Approval: APPROVED

上游变化且结论不变时增加以下 machine declarations，并逐项点名全部 Stable ID；首次发布删除这些行：

```text
Impact: NO_CHANGE
Upstream: generate-design
Previous Receipt SHA-256: generate-design=<old-hash>
Current Receipt SHA-256: generate-design=<new-hash>
Impact Rationale: story-example、ac-example、integration-example、assumption-example 均确认不受影响。
```
