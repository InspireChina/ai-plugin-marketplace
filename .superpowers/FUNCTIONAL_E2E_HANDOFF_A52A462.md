# Functional E2E Handoff (post-batch repair)

## Goal

从提交 `a52a462` 启动新的宿主 Controller Session 和此前未使用的 pair root，完整执行真实 Greenfield → Brownfield Functional E2E。Functional Acceptance 必须阻断；Timing 必记；Token Observation 尽力记录且不阻断。

## Start

- Worktree: `/Users/yuan.li/Documents/ai-plugin-marketplace/.worktrees/ai-sow-generate-plan`
- Required HEAD: `af882a4 fix(ai-sow): batch source scan repairs`
- New pair root: `/Users/yuan.li/Documents/ai-sow-e2e/functional-e2e-current-host-20260908-postfix-003`
- Frozen source: `/Users/yuan.li/Documents/ai-sow-e2e/real-benchmark-greenfield-brownfield-rerun-20260905`
- LibreOffice: `/Applications/LibreOffice.app/Contents/MacOS/soffice`

Completion criterion: HEAD exact and clean; new pair root absent before preparation.

## Current domain contract

Integration 在 SOW 阶段只确定：

- 参与系统与 `direction`；
- API、文件、消息、OIDC 等高层 `method`；
- `purpose`；
- `responsibilityBoundaryIds` 与 `counterpartyBoundary`。

稳定 Integration 不再包含 `trigger` 或 `dataCategories`。具体触发时机、endpoint、payload、字段映射、token/claim、重试和错误处理在迭代开始时确认，不形成 Scope 输入门禁。

Scope `facetFacts` 对 Integration 只允许并要求 `DIRECTION / METHOD / PURPOSE`。`ScopeDecisionIR` 不再保存 `uncertainty`；正常 fresh Review 不是输入缺口。只有缺失会改变高层范围、参与方、direction、method、purpose 或责任边界的外部事实时才报告输入缺口。

## Host execution

- 使用宿主当前模型；不选择或硬编码 provider/model。
- `maxConcurrency = 1`。
- 每个 `MODEL_PROVIDER` Action 创建新的 `FRESH_NO_HISTORY` worker，包括 Author、Review、Repair、`CANDIDATE_PATCH-v1` 和 `ARTIFACT_VISUAL_REVIEW`。
- 同一 Action 的 hydrate loop 可复用该 worker；新 Action 不继承 Controller、兄弟或前序 Action 对话。
- 每个模型的唯一 final raw 原样写入正式 `resultPath`，再写 execution facts 并正式 `submit`。不私下验证和重写到通过。
- usage 只有宿主实际暴露时写 `PROVIDER_REPORTED`；否则写 `LOCALLY_ESTIMATED`，实际 token 统计保持 null。
- `BUDGET_EXHAUSTED` 可按合同逐次单调增加次数上限至 10，其它 policy 字段不变。

Completion criterion: 每个已发行模型 Action 都有独立 fresh-worker 事实、最后一次 `read_provider_request` 的 `pluginRequestSha256`、raw、Attempt 和真实 UTC timing。

## HOST_BROWSER

Controller 真实执行 frozen scenario：

- 等价干净 replay；
- `document.fonts.ready`；
- 目标 selector/value 稳定；
- blur active element、清 hover、连续两个 `requestAnimationFrame`；
- `browserProfileSha256 = sha256(canonical_json_bytes(browserProfile))`，包含 canonical 末尾换行；
- trace `files` 按 inventory 原顺序严格投影，每项只能含 `relativePath` 与 `sha256`；
- screenshot hash 绑定原始 PNG；critical replay 字节稳定。

Completion criterion: 正式 `PROTOTYPE_BROWSER-v1` submit 成功，独立 browser evidence verifier 不返回 `PROTOTYPE_UNSTABLE` 或 `HOST_BROWSER_INVALID_TRACE`。

## Pair sequence

1. 复制 frozen inputs、expectation draft、demo conversion draft、六个 demo 文件及 policy；仅将 `maxConcurrency` 改为 1，保持 canonical JSON 末尾换行。
2. `run_paired_benchmark.py prepare`。
3. Greenfield 逐 Action 推进到 `AWAITING_FINAL_REVIEW`，workbook 必须 `VERIFIED`。
4. 使用 `instantiate-brownfield-request` 将该 Greenfield XLSX 的精确 bytes 绑定为唯一 Prior。
5. Brownfield 逐 Action推进到 `AWAITING_FINAL_REVIEW`。
6. 完成 Office、reference recalculation、double reread、全部 visible Sheet render 与实际 visual review。
7. 写唯一 canonical `ai-sow-host-invocation-observation-v1` 到 `<pair-root>/host-invocations/<sha256>.json`，精确覆盖两侧所有已发行模型 Action。
8. `verify-host-invocations` 必须返回 `{"outcome":"VERIFIED"}`。
9. 两侧保持未批准，在 `AWAITING_FINAL_REVIEW` 时计算 `ai-sow-benchmark-result-v2`。

Completion criterion: benchmark `functionalOutcome` PASS；Timing Observation 完整；Token Observation 为事实支持的 `COMPLETE / PARTIAL / UNAVAILABLE`。

## Do not reuse

以下只保留诊断证据，不能复制或恢复其 Actions、Attempts、host observation、Patch 或 run：

- `functional-e2e-current-host-20260908-001`
- `functional-e2e-current-host-20260908-002`
- `functional-e2e-current-host-20260908-003`
- `functional-e2e-current-host-20260908-cycle1` 至 `cycle5`
- `functional-e2e-current-host-20260908-postfix-001`

`postfix-001` 的 `ScopeInputRequired` 来自旧 Integration 粒度；`a52a462` 已做 clean cutover。不要把旧 run 重新解释为新合同结果。

## Verification already completed

- Scope compiler: 41 passed
- SOW Model: 16 passed
- Task compiler: 77 passed
- Action contracts: 106 passed
- Final Skill suite: 1226 passed, 1 skipped
- Root suite: 66 passed
- Repository validator: passed
- Copy-plugin smoke: Greenfield/Brownfield/blocked resume all `PUBLISHED`
- `git diff --check`: passed

## Stop conditions

真正不可恢复门禁时停止，不伪造后续证据。报告精确 Action/Attempt/raw/record/event、可恢复性和根因分类。宿主强制收尾不是产品 FAIL：返回 `INCOMPLETE` 和尚未开始的 next Action，由另一个 fresh Controller 从不可变 run 接管同一 pair。
