# 目标设计评审

当前 Stage 先把以下内容写入 work-only
`.ai-sow/work/generate-design/review-source.json`，再由 `render_review.py` 与两份 candidate
确定性投影本评审。source 顶层只使用 `targetDesign`、`architectureDeltaReview`、
`designDecisionReview`、`scopeReview`、`technicalRequirementsReview` 与 `concerns`；前五项为
非空中文说明，且不得手写 candidate 对象数量；对象数量由 renderer 从两份 candidate
确定性投影为唯一 `Structure Counts` 声明。`concerns` 每行使用：

```json
{
  "concern": "PRODUCTION_SCOPE",
  "disposition": "IN_SCOPE",
  "featureIds": ["feature-example"],
  "effectiveStartIds": [],
  "evidenceIds": [],
  "responsibilityBoundary": "项目负责获批技术范围，客户负责生产审批。",
  "basis": "获批范围要求该技术能力达到生产可用。"
}
```

Reviewer 与用户批准的是 `review-packet.json` 的精确 SHA-256。评审正文中的
`Reviewer: PASS` 与 `User Approval: APPROVED` 是候选投影；只有 `reviewer.json` 和
`approval.json` 都绑定同一 packet 后才能正式发布。

## 目标设计

说明目标能力、系统边界、关键流程、数据与质量目标，并明确仍需用户决定的事项。

Design IDs: design-example
Technical IDs: epic-example, feature-example
Structure Counts: designItems=1, architectureDeltas=1, decisions=1, scopeDecisions=2, technicalEpics=1, technicalFeatures=1

## Architecture Delta

逐项说明相对 Effective Start 的 `NEW / ADOPT / ADJUST / REPLACE / RETIRE` 变化及稳定 ID。

## Design Decision

逐项说明选择、理由、Design Item、Feature、Effective Start、Evidence 与 `decisionKind`；类型化义务不得只写隐含结论。

## Scope

为每个 BUSINESS 与 TECHNICAL Feature 给出唯一 Scope Decision，并说明 Design Item、Effective Start、集成边界和所需决策类别。

## TECHNICAL requirements

分别列出 `SOURCE_INPUT` 与 `DESIGN_DERIVED` TECHNICAL Epic/Feature，并说明来源或派生关系。

## 高阶设计覆盖门禁

说明全部 Feature、Architecture Delta、Design Decision、typed obligations 与未解决 Uncertainty 的覆盖结论。

HLD Coverage: PASSED

## 上线范围门禁

| Concern | Disposition | Feature IDs | Effective Start IDs | Evidence IDs | 责任边界 | 依据 |
|---|---|---|---|---|---|---|
| PRODUCTION_SCOPE | IN_SCOPE | feature-example | — | — | 项目负责已批准技术范围，客户负责生产审批。 | 已批准范围要求该技术能力达到生产可用。 |
| ENVIRONMENT_CONFIGURATION | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| DEPLOYMENT_CUTOVER_ROLLBACK | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| DATA_MIGRATION | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| PRODUCTION_VALIDATION | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| OBSERVABILITY | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| OPERATIONS_HANDOVER | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| POST_GO_LIVE_SUPPORT | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| USER_ENABLEMENT | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |
| LEGACY_RETIREMENT | NOT_APPLICABLE | — | — | — | 本项目不负责该关注点。 | 已确认与当前范围无关。 |

Go-live Assessment: PASSED

## 审查与批准

Reviewer: PASS
User Approval: APPROVED

重新绑定上游且结论不变时，另行增加以下 machine declarations；首次发布不要保留这些行：

```text
Impact: NO_CHANGE
Upstream: analyze-requirement, analyze-as-is
Previous Receipt SHA-256: analyze-requirement=<old-hash>, analyze-as-is=<old-hash>
Current Receipt SHA-256: analyze-requirement=<new-hash>, analyze-as-is=<new-hash>
Impact Rationale: design-example、epic-example、feature-example 均确认不受影响。
```
