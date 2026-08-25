# 业务需求评审

本模板说明 candidate-first 专业评审的完整投影。Stage 先形成 `requirements.candidate.json`，再由
`render_review.py` 确定性生成 work-only `review.candidate.md`；自由文本必须说明结论、依据和边界，
固定声明保持原值。

## 来源与归一化

列出每份 `sourceDocumentId`、项目相对路径、原文件名、内容哈希，以及归一化条目的合并、拆分或去重理由。

## Epic 与 Feature

按 BUSINESS Epic 展开 Feature，说明业务结果、参与者、规则、优先级和验收意图；技术约束只登记来源位置，不在本阶段解决。

## 范围边界

说明纳入、排除、延期和共同约束，指出哪些选填结论有直接证据，哪些字段因无具体内容而省略。

## 问卷状态

精确保留以下声明之一：

```text
Questionnaire: NOT_REQUIRED
Questionnaire: .ai-sow/reviews/analyze-requirement-questionnaire.md
```

若使用问卷，逐项说明 `CLOSED` 的业务结论去向，以及 `APPROVED_DEFAULT` 留给下游的假设候选。

## 稳定 ID 映射

用一行列出本评审最终采用的全部来源、归一化、Epic 和 Feature ID；顺序与候选 JSON 一致：

```text
Stable IDs: source-document-..., norm-..., epic-..., feature-...
```

## 输入充分性

说明来源是否足以支持当前业务结论；会改变范围、目标、规则、优先级或验收意图的缺口必须保留为阻塞问题，不得猜测。

上游或来源变化后的影响复核在本节后增加：

```text
Impact: NO_CHANGE
Impact: CHANGED
```

`NO_CHANGE` 必须说明新旧输入 hash、判断理由和确认不受影响的稳定 ID。

## 审查与批准

确定性投影保留拟发布声明：

```text
Reviewer: PASS
```

用户明确批准当前完整版本后才能写：

```text
User Approval: APPROVED
```

这两行本身不授予发布权限。Reviewer 必须把 `PASS` 作为 canonical
`.ai-sow/work/analyze-requirement/reviewer.json` sidecar 绑定当前 `review-packet.json` SHA-256；用户必须
明确批准同一 packet hash，并由 `.ai-sow/work/analyze-requirement/approval.json` 绑定。任一 candidate、
context、input、review 或 risk-summary 字节变化都使旧 sidecar 失效。

## NO_CHANGE 复核

仅 `rebind` 的正式 review 可以增加：

```text
Impact: NO_CHANGE
```

并说明新旧输入 hash、判断理由和全部不受影响的稳定 ID。来源文件字节变化不得声明
`NO_CHANGE`，必须回到 candidate-first review 与精确 packet 批准。
