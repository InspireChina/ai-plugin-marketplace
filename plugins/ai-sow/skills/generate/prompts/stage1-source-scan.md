# Stage 1 Source Scan

遵守 `prompts/fragments/roles/author.md`、`prompts/fragments/outputs/author-result.md` 和 `references/source-authority.md`。

只读取 packet 分配的 `sourceBlockIds`，逐项提取原子 requirement、design decision、constraint、responsibility、exclusion 和 conflict candidate。保留精确 SourceRef、条件、阈值、禁止项与适用范围。

不要摘要成章节结论，不要合并尚不能证明等价的要点，不要生成 Epic、Feature、Story、AC 或 Task，也不要决定最终范围处置。

返回 `SOURCE_SCAN_PATCH` 和完整 `blockCoverage`：每个分配 block 必须恰好标记一次 `READ`，或以带结构化诊断的 `PARSE_ISSUE` 标记。`replacementSet` 只可写 `inputItems`。
