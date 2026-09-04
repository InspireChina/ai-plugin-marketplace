# 分层独立评审与返修

`SOURCE_AUDIT / SOURCE_SCOPE / STORY_DESIGN / TASK_ESTIMATION` 都在 fresh context 中执行，不继承 Author 或其他 Reviewer 对话。物理 shard 只用于上下文容量；`logicalThemeId` 保留跨 shard 的业务主题。一个逻辑主题出现多个 leaf 时必须执行 `THEME_JOIN`，并 hash 绑定全部 leaf 结果；单 leaf 主题可直接采用该结果。

Theme Join 不得静默删除 finding。不同 review kind 产生的同 ID、同内容 finding 在进入裁决和 repair plan 前全局去重；同 ID 绑定不同内容时返回结构化冲突诊断，不继续生成 repair plan。对同一 subject 的相互矛盾命题由新的 `ADJUDICATION` action 选择仍成立的 finding；Adjudicator 不修改 candidate。

`OWNER_FIX_REQUIRED` 形成最小 repair plan。`earliestOwner` 决定恢复阶段，后续 Owner 只处理连续受影响后缀；每个 wave 显式列出可编辑节点、只读上下文和锁定节点。`INPUT_REQUIRED` 返回证据绑定问题，`CONTRACT_GAP` 停在合同层处理，二者不能伪装成 Owner patch。返修后所有受影响 checkpoint 与 review 都必须重算，未受影响结果可在 hash 仍匹配时复用。
