# 现状评审

本评审由 As-Is candidate 确定性投影。`Reviewer: PASS` 与 `User Approval: APPROVED` 是拟发布声明；只有 `reviewer.json` 和 `approval.json` 同时绑定当前 `review-packet.json` 的精确 SHA-256 后才具有授权效力。

## 调查范围

说明 Greenfield/Brownfield、as-of 日期、登记仓库、往期 SOW、包含与排除边界。

## 九个 Topic

按合同顺序说明九个 Topic 的状态、结论和关联 Uncertainty。Topic 摘要只陈述结论与边界并指向 Evidence；计数、清单和索引统计只在 Evidence 摘要或对应工作记录中维护一份权威陈述，不在 Topic、Evidence 与工作记录之间复制。

## Item

逐项说明当前 Item、所属 Topic、仓库关系和证据依据。

## Commitment

逐项以 ID 和名称核对往期承诺、实现状态、处置和关联 Feature。

## Effective Start

说明由当前 Item 与 `EXPECTED_BEFORE_START` Commitment 组成的有效起点。

## Coverage

逐个 BUSINESS Feature 说明 `COMPLETE`、`PARTIAL` 或 `MISSING` 的理由及关联。

## Uncertainty

逐项以 ID 和名称说明问题、影响、估算影响、负责人、建议处理和关联 Feature。

## Evidence

逐项以 ID 和名称列出每条结论的项目相对 anchor、简要证据摘要和受支持 ID；不得粘贴源码或完整工具输出，也不得写入凭据或本机绝对路径。

## 问卷记录

Questionnaire: NOT_REQUIRED
Questionnaire IDs: NONE

若使用问卷，将第一行改为 `.ai-sow/work/analyze-as-is/questionnaire.md`，按文件顺序列出全部选中 Question ID，并在本节逐条原样复现用户实际批准的五个固定字段。每条记录使用：

```text
Question ID: <权威目录中的 ID>
Answer: <已知值 | UNKNOWN | NOT_APPLICABLE>
Owner: <负责人、团队或 UNKNOWN>
Evidence reference: <证据引用或 UNKNOWN>
Effective date: <YYYY-MM-DD 或 UNKNOWN>
```

## 审查与批准

Stable IDs: <按 Item、Commitment、Effective Start、Uncertainty、Evidence 顺序列出 Owner-local ID；无 ID 时写 NONE>

上游变化后的影响复核才增加：

```text
Upstream: analyze-requirement
Previous Receipt SHA-256: <旧值>
Current Receipt SHA-256: <新值>
Impact: NO_CHANGE | CHANGED
Impact Rationale: <判断理由与受影响或确认不受影响的稳定 ID>
```

Reviewer: PASS
User Approval: APPROVED

## Reviewer 检查清单

Reviewer 对当前完整 packet 逐项确认：九个 Topic 恰好各一条；Commitment、Uncertainty 和 Evidence 的 ID 与名称均已投影；`INSUFFICIENT_EVIDENCE` 均关联 Uncertainty；每条 Uncertainty 明确 `affectsEstimate`；Effective Start 只由当前 Item 和 `EXPECTED_BEFORE_START` Commitment 组成；每个 BUSINESS Feature 有 Coverage；Commitment 实现状态、处置与 Coverage 一致；选中问卷被逐条原样消费；每个现状声明有允许的项目相对 Evidence anchor 或明确 Uncertainty；packet、review 和稳定候选中均不包含源码或完整工具输出、凭据、本机绝对路径、未授权 repository 或 prior SOW 内容。

Finding 严重度下限：只报告违反合同的事实与证据不符、内部矛盾或误述、结构或引用违规、追溯断裂和隐私越界。不报告单纯措辞偏好、可读性建议、可选补充细节、没有形成冲突断言的描述简略，或对技术方案的个人偏好。
