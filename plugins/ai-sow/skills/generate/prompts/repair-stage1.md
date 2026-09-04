# Stage 1 Owner Repair

处理 packet 中已审核的 Stage 1 findings，只修改 `editableNodeIds` 内的节点，并把 `contextNodeIds` 与 `lockedNodeIds` 当作只读上下文。

返回 `ai-sow-stage-result-v1` 的 `PATCH`。`reviewedEvidenceIds` 必须按顺序覆盖 repair wave 的全部 `findingIds`，`selfCheck.completedCheckIds` 必须与 packet 的 `requiredCheckIds` 完全一致。不得修改 Story、Acceptance Criteria、Task 或脚本拥有区域；完成后必须交回独立 R1 Scope Review 复核。
