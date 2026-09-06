# 测试分层与任务验收

每 Task 选择本次行为和直接调用边界的测试 node ID 或 `-k`；不默认跑整个测试文件或全量。
文件用 `TEST_LAYER` 声明默认层级，混合文件的单项用 `@pytest.mark.<layer>` 覆盖；收集时保证每项只有
一个有效层级。命令从仓库根目录执行，可在下列命令中附加当前 Task 的路径或 `-k`：

```text
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow -m unit -q
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow -m integration -q
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow -m e2e -q
```

- `unit`：单模块/契约行为，可使用临时文件；不得运行完整生成、Office/浏览器或批准发布准备。
- `integration`：Owner、planner/ledger、公开 API 等直接调用边界；不运行完整产品流程。
- `e2e`：完整产品、真实 Office/浏览器、批准发布或复制插件流程。共享完整基线的测试仍属此层。

`test_orchestrator.py` 的完整 artifact fixture 消费者与 `test_generate_e2e.py` 的 copy smoke 消费者显式
归入 e2e；同文件的局部用例保持 integration。责任边界回归属于 integration；Story→Task 公开链路属于 e2e。
新增混合用例必须根据实际准备/调用链归类，不能依文件名猜测。

最终集成/交付执行全部层级、根测试、仓库校验器、独立安装 smoke 和计划的真实顺序基准；移出 Task
默认门禁不代表取消最终验收。不得通过 skip/xfail 掩盖错误。删除或合并测试必须在变更记录中指明原有
独立行为由哪个更合适的断言承接。

## Task 14 同步与测试承接

`analyze_historical_benchmark.py` 只保留已取代基准的 compare/validate/validate-policy 分析，
由 `test_historical_benchmark.py` 的 22 项用例承接。旧 session 初始化、public prepare、五样本、
cache namespace、run/stage 重复 usage 汇总及旧失败样本推进协议随旧执行入口删除，不保留兼容实现。
当前运行与失败恢复由 `test_action_ledger.py`、`test_orchestrator.py` 的公开 start/submit/resume/
budget/diagnostic 断言负责；两侧隔离与单次决定由 `test_paired_benchmark.py` 负责。
真实基准的原始记录计算由 `test_real_benchmark_contracts.py` 分项实现，尚未实现的范围不能以历史分析替代。

直接重建第二份 Scope plan 的旧 `test_scope_owner_e2e_code_only_candidate_binds_all_rounds_and_pending_intent_review`
退出；相同行为由公开 `test_fresh_control_review_code_only_all_original_rounds_and_obligations` 与
`test_checkpoint_deep_binding_*` 承接，包括第一轮独有观察、完整原文、缺失/未接受/陈旧义务拒绝。
两项三个 Owner 消费边界测试在 DRAFT 停止；实际 artifact 后缀由完整 E2E 与 copy smoke 承接。

planner 的固定 hash 同步至最终 SOURCE_SCAN 指令与完整 canonical request 预算表示；精确 packet、
logical/group/plan hash 断言和 57 项、每批最多 8 项的可达性断言均保留。
模块重定位只消除依赖环：canonical serializer 仍只有一份，双复读仍比较同一公式与缓存。

copy smoke 每个 Action 启动独立 fixture 解释器并核对 request hash、输出限额和进程身份，报告
`fixtureProcessIsolation=ONE_PROCESS_PER_ACTION`、`actualProviderVerified=false`。它验证安装隔离、
真实 Office 与 fixture 进程配置；不作为真实模型调用、模型容量、token 用量或基准批准证据。
必须执行实际模型宿主验证后才可将真实基准提交共同终审。

## Task 10 协议切换与测试承接

旧 PATCH、动态 group plan、R1 / Theme Join / Adjudication 和跨 run 增量复用合同已取代，相关测试及
fixture 随旧入口删除；不保留兼容 helper 或 skip。新行为由以下实际断言承接（文件均在
[generate/tests](../skills/generate/tests)）：

| 原断言或测试族 | 当前承接 |
| --- | --- |
| SourceScan/Audit 完整来源、限定词与事实边界 | `test_scope_compiler.py::test_source_scan_coverage_root_seals_only_facts_and_explicit_no_relevance`、`test_independent_source_audit_requires_every_category_and_bound_fact_keys`、Scope 窄 IR pre-seal 与关系测试 |
| Scope proposal/join、全组完成、Prior/政策/技术来源权威 | 同文件 `test_scope_materialize_once_per_revision_*`、`test_scope_owner_e2e_*` 与 `test_scope_design_authority_is_visible_to_model_and_rejected_before_seal`；语义来源等价由公开 fresh Review 决定 |
| Story 旧 prepare/apply/checkpoint 与 obligation closure | `test_delivery_compiler.py` 的 `test_story_ac_input_boundary_*`、`test_story_ac_obligation_closure_*`、`test_story_ac_materialize_once_per_revision_*` |
| Task 旧 prepare/apply/checkpoint 与目录/覆盖约束 | `test_task_compiler.py` 的 `test_task_obligation_coverage_*`、`test_task_materialize_once_per_revision_*`、`test_demo_task_authority_*` |
| 旧 R1/layered Review、通用 PATCH Repair | `test_final_review.py::test_fresh_control_review_exact_ir_identity_and_set_normalization`、`test_bounded_semantic_repair_exact_roots_and_lineage_closure`；公开 Review/Repair 链在 `test_orchestrator.py` 的同名前缀测试 |
| Task 2 遗漏的 `test_checkpoint_kinds_require_owner_coverage_and_kind_specific_proof` | `test_final_review.py::test_checkpoint_deep_binding_exact_required_proof_fields` 逐字段拒绝缺失或额外字段；`test_checkpoint_deep_binding_complete_real_chain` 校验实际 Owner/Review/Repair/候选/validator/Prior 证明；旧 coverage/projection 字段不再属于合同 |
| 旧动态发行、packet hash logical identity、八项截断 | `test_orchestrator.py::test_public_stage_plan_cutover_freezes_complete_owner_dag_before_issuance`、`test_public_stage_plan_cutover_low_cap_interrupted_issuance_complete_groups` |
| Task 4 cap=1 双兄弟意图、旧 concurrency frozen 测试与 partial-sibling issuance 重复测试 | 上述 low-cap 测试覆盖 cap=1 顺序单 work group 和 cap=2 组内部分发行中断；遍历完整 Scope DAG，校验原 Envelope 字节、唯一事件、冻结并发上限与全部 work 可达 |
| 旧 batch budget wait 重复测试 | `test_public_stage_plan_cutover_whole_batch_budget_preflight_and_replacement`：整组预算不足时零发行，提高预算后原 plan 发完全部成员 |
| 旧 `issued.json` / group `plan.json` 恢复边界 | `test_single_writer_atomic_recovery_retries_interrupted_issuance` 的 content-addressed StagePlan、packet、Envelope、发行 event 边界；`test_public_budget_policy_seam_replacement_finishes_frozen_issuance_first` 的 initial/partial/retry 三种替换次序 |
| 旧 unsealed group 元数据篡改 | `test_single_writer_atomic_recovery_rejects_conflicting_unsealed_group` 拒绝冻结 plan 变更、重复 plan 与错误原始 base candidate |
| 旧 hydrate、submit 幂等、bounded retry / 非重试失败 | `test_planned_token_guard_hydration_uses_full_canonical_byte_threshold`、`test_public_task_rule_hydration_uses_frozen_catalog_and_capacity`、`test_single_writer_atomic_recovery_submit_reuses_completion`、`test_public_non_retry_attempt_routes_and_wait_closure` 与实际 issued-retry 恢复测试 |
| 原 `test_story_checkpoint_revalidates_records_against_group_base_candidate` | 保留于 [regressions/test_e2e_regressions.py](../skills/generate/tests/regressions/test_e2e_regressions.py)：真实公开链到 Task 后，Story Author 仍绑定原 Scope candidate；篡改原 base 导致 resume 拒绝 |
| Prototype preprocessing 与 CodeOnly 范围审查 | `test_fresh_control_review_code_only_all_original_rounds_and_obligations`：全部 rounds 完成前无 Scope plan；第一轮独有观察保留；缺 obligation 和拒绝 intent 不能 checkpoint |
| 默认自动化排除后原地重编译、REUSE / RENDER_ONLY / DELTA_COMPILE、跨 Owner generic repair | 旧行为明确退出，不作“等价通过”声明。新 run 全量编译、业务输入变化 abandon/start；最终 artifact/publication 测试由后续集成迁移和验收 |

静态示例已切换为 `source-scan-decision-results.json`、`source-audit-decision-results.json`、
`scope-decision-results.json`、`review-decision.json` 与三份精确 StageCheckpoint。Story/Task planner fixture
hash 的变化仅来自上游 checkpoint 字段合同变化；模板和 renderer 指纹未改。历史 E2E lock 中仅更新本次
删除/替换路径的直接引用；它不代表重新执行整轮 Benchmark，最终完整锁验收仍待执行。

评审修复定向回归：`test_bounded_semantic_repair_excluded_scope_root_is_reviewable` 覆盖 EXCLUDE/RETIRE；
`test_stage_seal_order_step_output_transaction_recovers_exact_timing` 覆盖 M/V 完成事件后、输出发布前/后
中断，核对实际恢复区间、同一输出 hash 和已完成步骤不重复；
`test_checkpoint_deep_binding_rehashed_review_input_cannot_replace_completed_output` 拒绝重新寻址的伪造索引、与完成事件 hash 联合改写的空索引，以及同名节点交换索引。
CodeOnly 原公开测试新增 ObservationIR 原文与实际 normalized result 的逐字段一致性断言。

`test_checkpoint_deep_binding_prior_graph_recovery_uses_sealed_owner_sources` 进一步覆盖 RETIRE 场景：
同步改写 Prior 正文或 ChangeGraph、相关义务和完成事件 hash，也必须由原库存与 sealed IR 拒绝。

## Task 11 显式输入与测试承接

- 旧 `plan_route`、RouteDecision、routing proof 与 route matrix（含 lowest-stage/hash-only DTO 测试）随旧入口删除；未使用的 incremental change-cases fixture 同步删除。新路由边界由 `test_no_cross_run_reuse_has_no_legacy_route_api` 与 FULL_COMPILE/终态 Schema 负例承接。
- `test_fresh_run_independence_no_cross_run_reuse_with_deleted_or_corrupt_history` 通过真实 start/resume/abandon，禁止读取旧 current、generation 和其他 run 文件，并逐字节比较旧历史存在、损坏、删除时的完整 Scope StagePlan。这个局部零读取证明不需要运行 Office。
- `test_explicit_brownfield_inputs_only_selected_prior_and_current_change_context` 覆盖零/一 Prior、本次声明进入真实冻结 Scope context，以及下次声明不继承旧正文。
- 旧 E2E 中只启动便 abandon/start 的重复测试合并到 integration `test_new_material_requires_new_run_and_preserves_old_audit`，核对唯一 revision binding、完整新来源和旧审计字节；CLI 单独拒绝 resume request。
- 预算原单调限制测试更名为 `test_budget_update_not_business_input_*`，新增同正文、contract/model/estimator 变化负例、五种独立合法限额增加、真实已完成 checkpoint 不变，以及发布事件后中断使用无参数 resume 恢复。
- 旧 EXCLUDE transition 故障分支删除；APPROVE 的 current/terminal 和 ABANDON 的 terminal 恢复矩阵保留。局部 artifact 决策测试只验证拒绝排除与幂等放弃，使用 decision-only fixture，不模拟 Office 成功或完整发布。
- 完整发布 E2E 扩展为 `test_fresh_run_independence_full_compile_reaches_verified_approval_then_publishes`；copy smoke 的旧 REUSE/RENDER_ONLY/DELTA 断言统一为相同输入、模板字节变化、业务变化的三次 FULL_COMPILE 与独立三阶段评审。它们仍由 Task12 的 artifact 后缀集成及最终全量门禁执行，本 Task 未宣称完整工作簿/Office/发布 E2E 通过。

Task11 独审收口：`DECLARED_CHANGE_CONTEXT` 随本轮 input revision 作为 Scope review obligation，从冻结
context 派生并由现有义务全集校验独立重建；`test_explicit_brownfield_inputs_fresh_review_binds_each_current_declaration`
验证两个 run 的 Review 分别看到各自声明，并保留冲突 finding 的 WAIT 门禁；
`test_explicit_brownfield_inputs_review_declaration_restored_from_frozen_context` 联合改写义务与完成事件 hash，
验证缺失/篡改声明均不能恢复发行 Review。Marketplace 架构规格和遗留 artifact lowest-stage 字段同时收口。


## Task 12 产物后缀与测试承接

- 旧 `reviewed_artifact_state/fixture_renderer/prepare_fixture_artifact` 及基于 `b"verified-workbook"` 的五项 artifact 测试删除。模板、文本安全、ZIP/公式错误、visible ID 和真实 Prior 往返由 `test_workbook.py` 承接；Office identity/双复读与 publish_new 同字节幂等由 `test_office_engine.py` 承接。
- 旧 renderer 的特定退款 fixture/目录/SIT/notes 断言使用纯 `render_model`；目录、SIT 语义仍由原 Owner/catalog 测试验证，不通过已移除 layered-review helper 获得模型。
- generation store 的重复 fixture 生成合并为实际 `verified_artifact`。`test_generation_store.py` 验证精确字节发布、无 renderer/Office 重算、删除原 work/input 后离线复读、批准幂等、stale approval 和 current 切换前中断。`test_artifact_lifecycle.py` 验证深层篡改、完整 Visual Attempt/packet/result 和真实生产预算边界。
- 每步的消费证据与实际 DETERMINISTIC_STEP_FINISHED 输出 hash 深绑定。三种真实 producer 用例覆盖写表后、Office 已开始并自然结束、复读前预算耗尽；增加政策后在发布事件中断，再无 policy resume 恢复，已完成步骤字节保持且不重复计算。这不是 Task4 的 consumer fixture 替代。
- 当前合成完整发布 E2E 使用 PRD/HLD 权威来源；旧 `demo-selected` 实际为 REFERENCE_ONLY SUPPLEMENT，合成 driver 未做语义分类，不能作为 Task 权威来源，已从这两个 request fixture 删除。Proposal/Join 的容量触发由 planner/Scope 定向测试承接，完整发布 trace 按当前容量执行 SCOPE_SYNTHESIS；真实 Demo/补充资料语义仍在最终对应场景验证，未削弱生产来源校验。
- 自动 fixture 的 VisualReview PASS 仅验证协议；最终真实 Greenfield→Brownfield、实际模型视觉审查、Benchmark、浏览器和两份 verified XLSX 仍须最终执行。本 Task 不声称这些最终门禁已完成。

## Task 13 成对评审与运营支持

`support/run_paired_benchmark.py` 仅属于测试/运营支持层。它直接调用生产 `run_mode` 的显式预算
start/resume/approve/abandon，不加载旧 benchmark 的执行协议，也不实现模型 worker。
Pair review 的 `__all__` 导出保持以下三个函数：

- `instantiate_brownfield_request(template_path, prior_path, output_path)`：模板和输出放在 Brownfield
  项目根目录，模板只有一个 `PRIOR_SOW`，其 path/expectedSha256 分别为 `${PRIOR_SOW_PATH}` /
  `${PRIOR_SOW_SHA256}`。只复制选定 XLSX 到按内容寻址的 `pair-inputs`，复读 bytes，替换这两个值，
  验证其它 canonical 字段及完整 v3 request 后以 `publish_new` 输出。所有其它来源须已在项目内明确声明。
- `prepare_pair_review(green, brown)`：两侧 descriptor 都提供 `projectRoot`、`requestPath` 和
  `budgetPolicyPath`；Brown 另提供 `templatePath`。只有两侧为 `AWAITING_FINAL_REVIEW` 且工件深验
  通过才返回 manifest，其中同时列出两份 workbook 的路径和 hash；宿主须把两份 Excel 共同呈现。
- `submit_pair_decision(manifest, decision)`：决定使用 `ai-sow-pair-decision-v1`，绑定完整 manifest 的
  canonical SHA256。APPROVE 不带其它业务字段；REJECT 只另带 `side` 和项目相对 `feedbackInputPath`，
  后者为被否决侧完整 canonical v3 request，必须为
  `pair-feedback/request-<正文SHA256>.json`。宿主先用 `publish_new` 保存该请求再构造决定；正文 hash
  通过既有 path 字段进入决定本身，未增加字段或收据。每轮用户只给一个决定；相同决定的机器重试恢复事务，不再次询问用户。

### 冻结基准与只读计算入口

基准支持另提供以下三个 CLI 子命令，以及显式导入的
`calculate_benchmark_result(pair_root, pair_run_id)`。CLI 成功输出 canonical JSON 并返回 0；
缺少输入、输入漂移或未完成预算输出结构化 JSON 并返回非零。prepare 不启动模型或生产 run。

```text
run_paired_benchmark.py prepare --baseline-root <baseline> --output-root <pair-root> --expectation-draft <draft.json>
run_paired_benchmark.py instantiate-brownfield-request --output-root <pair-root> --pair-run-id <pair-id> --prior-path <greenfield.xlsx>
run_paired_benchmark.py verify-browser-evidence --output-root <pair-root> --pair-run-id <pair-id> --side greenfield|brownfield
```

prepare 要求预先在独立 output-root 中准备 canonical `run-budget-policy-source.json`，以及
`oracle/demo-conversion-draft.json`。后者有 greenfield/brownfield 两项，每项包含
`entrypoint`、`files`（relativePath/sourceId/draftPath）和 `reverseMappings`。
转换草稿是从原始 Demo Markdown 独立编写的本地 HTML/CSS/JS；原 Markdown 原样封存在
`frozen/inputs`，不作为运行时 Demo。每个 SOURCE 解析块、DOM selector 和 SCENARIO 交互
都必须恰有一条反向映射：kind/subject/disposition/sourceLocators。disposition 为
SOURCE_MAPPED 或 NON_SCOPE_PRESENTATION；交互不允许后者。sourceLocators 使用
`sourceId#exactLocator`，只引用同侧冻结原始来源。此校验核对枚举和出处，语义忠实性仍需独立评审。

八份基线文件的固定 SHA256、六份原始来源解析块、两份机械迁移请求、静态 Demo 字节、
共享预算及独立 expectation manifest 一起决定 pairRunId。原始业务字段不可借迁移改变；
Brownfield 批量上限为 100，500 只保留为历史纠错记录。首次 ACTION_ISSUED 后禁止重新 prepare。
两侧运行各自在首个 Action 前发布同一来源的初始预算，后续调整由各自 RunEvents 授权。

浏览器宿主把原始截图 PNG 以内容 hash 保存到各 run 的
`.ai-sow/work/runs/<run-id>/browser-screenshots/<sha256>.png`。核验入口复读所有连续发现轮次的
typed trace、冻结 Demo 字节、环境字段及截图，要求外部请求为零；未完成发现或关键场景回放
返回 WAITING_INPUT/INCOMPLETE_BUDGET。fixture 轨迹和 PNG 只验证传输边界，不证明实际浏览器运行。
覆盖率取 Scope StagePlan hash 绑定的 sealed Prototype Ledger，并沿实际三类 Attempt 复核其
Analyze 处置，包含合法的 EXCLUDED/NOT_EXERCISED；仅完成 Browser 而未封存 Analyze 的结果不能通过。

总计算入口不接收 metrics 参数，不读取 `benchmark-result.json`、session/run summary 或聊天记录。
它从事件绑定的最终 ArtifactManifest 复读两侧 InputRevision、三个 Owner proof、全部实际
Attempt/Envelope/packet/raw/normalized 字节，重验生产 checkpoint proof，并用冻结 oracle 的
精确 locator 计算 Scope、Brownfield ChangeGraph、覆盖、token 和时间指标。Prior 来源只经
ScopeCheckpoint 绑定的快照及工作簿可见 SourceRef 恢复；四个传递点必须大小和 SHA256 相同。
两侧必须顺序完成且均停在 AWAITING_FINAL_REVIEW；最终结果经过闭合 schema 的全部精确门槛。
完整交付文件集合仍由生产 resume、prepare_pair_review 和批准入口的 artifact validator 复读；
指标计算通过不替代这些交付门禁。三类 Owner repair Action 的 versioned usageCategory 均为 REPAIR。
只有实际宿主满足 fresh canonical request、输出限制和逐 Action usage 证据后，真实基准才可执行。
`test_benchmark_calculation_e2e.py` 使用 synthetic IR 与实际 Office，仅为完整记录链回归。

APPROVE 顺序发布，只有两份 GenerationManifest 与 current 都深验并绑定同一 pair decision 与获批
Excel 才返回 `PUBLISHED`。相同 decision/artifact 在 current 切换前后中断均不复制 generation。
Pair 控制文件位于 Greenfield 项目 `pair-reviews/<manifest hash>/`；它们不作为 Brownfield 业务输入。
生产 approval/generation 仅增加可选 `pairDecisionSha256`，由 generation store 交叉校验；未增加
ApprovalReceipt 或新的发布入口。

REJECT 先验证决定中反馈路径绑定的正文 SHA256，再把旧 pair 标为 `SUPERSEDED`。所有恢复都在
abandon/start 前重新验 hash，不读取可替换的反馈映射文件；同一决定始终只消费同一份请求正文。返回 `rerun` descriptor 后，宿主继续使用生产
start/resume/NextAction 循环（必须携带 descriptor 中的显式 budget 启动；恢复沿用已冻结预算）。完成
这一侧后重放同一个已保存 REJECT：Green 被否决时继续经唯一实例化函数启动 Brown；Brown 被否决时
保留 Green。两侧完成后返回 `nextPairManifestPath`，须再次共同呈现两份 Excel，取得针对新 manifest
的一个决定。旧 APPROVE、另一份 REJECT、篡改后的工件或错误 Prior 绑定都不能发布。

测试承接：隔离/封闭 union/完整反馈/schema 状态为 unit；真实未封存 run 的 readiness 为 integration；
真实 Office 工件、双发布中断恢复、批准前 bytes 失效、两侧否决实际重跑为 e2e，按层独立执行。
完整工作簿基线只由 e2e fixture 按顺序生成一次后复制，unit 不导入或运行完整生成 helper。原
`test_generation_store.py` 的 publication 测试保留，新增 pair 在 generation 已落盘但 current 未切换时
恢复及 pair hash 深绑定回归；没有删除独立行为或新增 skip/xfail。

反馈回归覆盖正文与内部映射联合替换、无 hash 路径拒绝，以及首次结果落盘前后中断；原内部
binding-before-copy 回归随该可替换映射设计删除，由决定直接绑定正文与上述中断测试承接。

这些 fixture 的模型结果与批准只验证协议，不代表真实用户业务批准、实际模型质量或最终 benchmark
结论。真实模型、浏览器、严格顺序 Greenfield→Brownfield 和两份 verified XLSX 仍在最终验收执行。
