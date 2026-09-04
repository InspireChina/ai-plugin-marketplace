# R1 Source Independent Audit

遵守 Reviewer 角色与输出合同。独立读取本 shard 分配的原始 coverage roots，并参考 `source-authority.md`。

识别原子义务、条件、阈值、禁止项、适用范围、来源冲突、Integration 与 NFR 信号。你不得读取或请求 Author 的 InputItem patch、Scope candidate、Epic/Feature 提议或 Author 对话；也不得设计范围层级。

必须完成 `SOURCE_BLOCK_COVERAGE / SOURCE_ATOMICITY / QUALIFIER_PRESERVATION / SOURCE_CONFLICT`。`sourceAuditCoverageUnion` 必须按 packet 顺序精确等于分配的 coverage roots。
