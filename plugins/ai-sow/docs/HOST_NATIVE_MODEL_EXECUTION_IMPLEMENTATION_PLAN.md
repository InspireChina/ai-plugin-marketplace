# 宿主原生模型执行与验收分层实施计划

- 状态：已完成
- 设计依据：[宿主原生模型执行与验收分层设计](HOST_NATIVE_MODEL_EXECUTION_DESIGN.md)
- 实施范围：文档与 `plugins/ai-sow/tests/` 的真实宿主 E2E/benchmark 支持层
- 生产兼容：不修改 Action、Usage、Attempt、Owner、checkpoint、Office、generation 或公开命令合同
- 发布边界：本计划不改版本、不发布、不引入厂商 CLI/API 依赖

## 1. 实施目标

以最小改动实现三项结果：

1. 真实功能 E2E 使用当前宿主的当前模型，并以新 Controller Session、逐 Action fresh worker 顺序运行；
2. Functional Acceptance 不再依赖实际 token 是否可见；
3. 时间始终记录，实际 token 尽力记录并明确 `COMPLETE / PARTIAL / UNAVAILABLE`，不统计费用。

完成后，缺少 provider usage 只影响 token observation，不阻断 Prior/Task 小样本、Greenfield、Brownfield、Office、视觉、portable proof 或 Functional Acceptance。

## 2. 固定合同

实施前固定以下决定，后续 Task 不得另起第二套语义：

### 2.1 模型与执行

- 模型由宿主当前配置选择；插件不接收 provider/model 选择参数；
- `modelProfileId` 仍是容量 estimator profile，不是模型 ID；
- 真实 E2E 固定 `maxConcurrency = 1`；
- 整轮使用新的 Controller Session；
- 每个 `MODEL_PROVIDER` Action 使用新的 Action Worker；
- 同一 Action 的 hydrate/tool loop 可以复用该 worker；
- `HOST_BROWSER` 由 Controller 执行。

### 2.2 输入证明

- 证明 `pluginRequestSha256`，即 `read_provider_request` 返回的插件控制 bytes；
- 不证明或保存完整 provider wire request；
- 宿主附加的安全、工具和 system context 不属于插件控制面；
- 不要求厂商 CLI/API adapter。

### 2.3 Usage 与性能

- 生产 Attempt 继续使用现有 `PROVIDER_REPORTED / LOCALLY_ESTIMATED`；
- `LOCALLY_ESTIMATED` 继续服务容量与规划预算；
- 实际 token observation 只汇总 `PROVIDER_REPORTED`；
- `inputTokens + outputTokens` 是绝对 token，总量不重复加入 cached/reasoning breakdown；
- 时间从现有 Attempt/RunEvent 重算；
- 不增加金额、币种、价格表或费用门禁。

## 3. 最小文件边界

### 3.1 必须修改

| 文件 | 原因 |
|---|---|
| `skills/generate/SKILL.md` | 明确当前宿主模型、Fresh Controller 与逐 Action Fresh Worker；usage 不可见不阻断 |
| `skills/generate/references/stage-seal.md` | 区分 Plugin-Controlled Request 与不可观察的 provider wire request |
| `docs/AI_SOW_PLUGIN_DESIGN.md` | 同步宿主责任 seam、功能/性能分层和非费用边界 |
| `docs/CONTEXT.md` | 增加最终采用的领域术语，不写实现细节 |
| `tests/README.md` | 给出真实宿主 E2E 的全新 session、单并发、逐 Action worker 操作顺序 |
| `tests/contracts/benchmark-result.schema.json` | 增加功能结果与 token observation 状态；允许 token 指标不可用 |
| `tests/support/run_paired_benchmark.py` | 验证宿主隔离证据；拆开功能门禁和性能一致性校验 |
| `tests/support/benchmark_calculation.py` | 计算时间、token completeness、partial subtotal 和可空比率 |
| `tests/test_real_benchmark_contracts.py` | 覆盖三种 token 状态和功能不受影响 |
| `tests/test_benchmark_calculation_e2e.py` | 证明无 provider usage 的真实记录仍能完成 Functional Acceptance |
| `CHANGELOG.md` | 记录用户可见的验收语义变化 |

### 3.2 新增一个测试合同

```text
plugins/ai-sow/tests/contracts/host-invocation-observation.schema.json
```

它只保存宿主不可从生产 ledger 推导的隔离事实，不保存业务内容、凭据或 provider wire request。

### 3.3 明确不修改

- `skills/generate/contracts/action.schema.json`
- `skills/generate/contracts/run-budget-policy.schema.json`
- `skills/generate/contracts/execution-policy-v1.json`
- `skills/generate/scripts/models.py`
- `skills/generate/scripts/action_ledger.py`
- `skills/generate/scripts/orchestrator.py`
- 各 Owner compiler、`candidate_repair.py`、`final_review.py`
- Office、renderer、template、artifact/generation contracts
- marketplace manifest 与插件版本
- 历史 `baseline-75970b2` 和已取代 benchmark 资产

这些现有生产 Module 已能用 `LOCALLY_ESTIMATED` 推进功能，并已声明 `FRESH_NO_HISTORY`；为测试可见性修改生产协议会扩大兼容面，故不在范围内。

## 4. Task 1：同步宿主执行语义

### 修改

在以下文档只保留一套定义：

- `skills/generate/SKILL.md`
- `skills/generate/references/stage-seal.md`
- `docs/AI_SOW_PLUGIN_DESIGN.md`
- `docs/CONTEXT.md`
- `tests/README.md`

写入：

1. 当前宿主模型由宿主选择，插件不固定 provider/model；
2. Fresh Controller Session 与 Fresh Action Worker 的区别；
3. “单代理顺序”改称“单并发顺序、逐 Action fresh worker”；
4. Plugin-Controlled Request 的 hash 范围；
5. token usage 不可见时使用现有本地规划记录，但不冒充实际 token；
6. Functional Acceptance、Timing Observation、Token Observation 的阻断关系；
7. Cost 明确为非目标。

### 不做

- 不加入任何厂商命令示例；
- 不要求读取用户认证文件；
- 不声称能观察宿主隐藏 system context；
- 不复制 Action/Usage Schema 字段表。

### 完成标准

五份文档使用相同术语；全文不存在“缺少 provider usage 就不能执行功能 E2E”或“provider wire request 必须只有两条 message”的现行指令。

## 5. Task 2：增加最小宿主隔离证据

### 新合同

`host-invocation-observation.schema.json` 使用 test-only v1 合同，建议形态：

```json
{
  "contract": "ai-sow-host-invocation-observation-v1",
  "pairRunId": "...",
  "controllerSessionFresh": true,
  "maxConcurrency": 1,
  "actions": [
    {
      "side": "GREENFIELD",
      "runId": "...",
      "actionId": "...",
      "pluginRequestSha256": "...",
      "contextPolicy": "FRESH_NO_HISTORY",
      "freshWorker": true,
      "workerInvocationIdSha256": null,
      "host": null,
      "model": null
    }
  ]
}
```

规则：

- `actions` 必须覆盖 Greenfield/Brownfield ledger 中每个实际发行的 `MODEL_PROVIDER` Action；
- 同一 `actionId` 恰有一行；
- `pluginRequestSha256` 必须等于该 Action 当前完整 `read_provider_request` bytes；
- `controllerSessionFresh = true`；
- `maxConcurrency = 1`；
- 每行 `contextPolicy = FRESH_NO_HISTORY` 且 `freshWorker = true`；
- 非空 `workerInvocationIdSha256` 不得重复；
- `host`、`model`、worker ID 均为可选观察值，不是功能 PASS 条件；
- 不允许 message 正文、客户输入、凭据、绝对路径或 provider wire request。

### 保存方式

Controller 在两侧模型 Action 完成后一次性写入：

```text
<pair-root>/host-invocations/<sha256>.json
```

文件名绑定 canonical bytes。计算入口要求同一 `pairRunId` 恰有一份合法报告，不使用可替换的 current pointer。

### 修改入口

在 `run_paired_benchmark.py` 增加 test-support 校验函数和 CLI：

```text
verify-host-invocations --output-root <pair-root> --pair-run-id <pair-id>
```

该入口只复读生产 ledger 和 observation，不调用模型、不创建 session、不修改 run。

### 测试

在 `test_real_benchmark_contracts.py` 覆盖：

- 完整两侧 Action；
- 缺 Action；
- 重复 Action；
- 错误 request hash；
- `freshWorker=false`；
- worker ID 重用；
- host/model 为 null；
- 添加 message、凭据或绝对路径字段被闭合 Schema 拒绝。

### 完成标准

宿主隔离事实可独立验证；验证器不导入或调用任何厂商实现。

## 6. Task 3：拆开功能门禁与性能观测

### 保留一个内容寻址结果

为减少文件迁移，保留现有文件名和计算入口，但将 test-only 结果合同干净切换为 v2：

```text
ai-sow-benchmark-result-v2
benchmark-result.schema.json
calculate_benchmark_result(pair_root, pair_run_id)
```

所有当前消费者一次迁移到 v2；不保留 v1 alias。生产 generate 合同和插件版本不随这个 test-only 合同变化。

但把同一结果中的字段分成独立语义区，不创建第二个 aggregate 文件：

- Functional Acceptance 字段：现有零缺陷/全覆盖、两侧状态、Prior transfer、claim mapping，加 `functionalOutcome = PASS`；
- Timing Observation 字段：现有 `activeWallTime`、`userWaitingTime`；
- Token Observation 字段：现有 token rows/ratios，加完整性和绝对量字段。

新增字段：

```text
functionalOutcome: PASS
tokenObservationState: COMPLETE | PARTIAL | UNAVAILABLE
modelAttemptCount: integer
providerReportedAttemptCount: integer
observedActualTokens: integer | null
completeActualTokens: integer | null
```

调整字段：

```text
tokensPerFormalNode: number | null
retryAmplification: number | null
budgetVarianceTokens: integer | null
```

语义：

- `observedActualTokens` 是已有 `PROVIDER_REPORTED` Attempt 的 `inputTokens + outputTokens` subtotal；`PARTIAL/COMPLETE` 时为整数，`UNAVAILABLE` 时为 null，绝不用 0 冒充未知；
- `completeActualTokens` 仅在 `COMPLETE` 时等于 `observedActualTokens`，否则为 null；
- `tokensPerFormalNode`、`retryAmplification`、`budgetVarianceTokens` 只允许在 `COMPLETE` 时计算；比率分母为零时仍为 null，`PARTIAL/UNAVAILABLE` 时三者均为 null；
- `tokensByCategoryProvenanceAndKind` 继续保留 provenance，便于同时审计实际值与本地规划值；
- `invalidIrRate`、`repairRate` 从 Attempt 状态计算，不依赖 token completeness。

### 校验函数

删除把所有内容混成一个硬门禁的 `_validate_benchmark_result`，改为两个明确函数：

```text
_validate_functional_acceptance(value, host_observation)
_validate_performance_observation(value)
```

`calculate_benchmark_result` 先重放生产 proof，再：

1. 必须通过 Functional Acceptance；
2. 必须生成合法时间值；
3. 根据实际 usage 生成任一合法 Token Observation 状态；
4. 不因 `PARTIAL/UNAVAILABLE` 抛错；
5. 不比较 token 阈值，不生成性能 PASS。

### 测试

`test_real_benchmark_contracts.py` 增加三组：

- 全部 `PROVIDER_REPORTED` -> `COMPLETE`，绝对量包含失败、superseded、Repair；
- provider/local 混合 -> `PARTIAL`，subtotal 保留、完整比率为 null、功能 PASS；
- 全部 `LOCALLY_ESTIMATED` -> `UNAVAILABLE`，实际完整总量为 null、功能 PASS。

`test_benchmark_calculation_e2e.py` 的 synthetic/fixture run 当前全部是 `LOCALLY_ESTIMATED`，预期改为：

```text
functionalOutcome = PASS
tokenObservationState = UNAVAILABLE
activeWallTime > 0
```

不再断言 `tokensPerFormalNode > 0`。

### 完成标准

同一功能事实在三种 token 状态下得到相同 `functionalOutcome`；只有性能观测字段不同。

## 7. Task 4：定义真实宿主 E2E 操作顺序

在 `tests/README.md` 增加一个可由 Codex、Claude Code 或其他宿主执行的顺序，不提供 CLI wrapper：

### Controller 启动

1. 用户开启全新宿主 session；
2. 该 session 只加载固定 E2E handoff、Skill 和测试输入；
3. 固定 `maxConcurrency=1`、候选/执行/确定性次数；
4. 初始化 host invocation observation；
5. 不固定 provider/model。

### 每个模型 Action

1. Controller 调用 `read_provider_request` 取得初始请求；
2. 通过宿主原生能力创建 fresh worker，只提供本 Action 的 Plugin-Controlled Request 和附件；
3. 每次正式 hydrate 后复读 `read_provider_request`，只在同一 worker 内追加 response；
4. 保存唯一 raw，并对最后一次完整请求计算 `pluginRequestSha256`；
5. usage 可见时写 `PROVIDER_REPORTED`，否则写现有 `LOCALLY_ESTIMATED`；
6. 写 UTC timing 并 `submit`；
7. observation 追加一行；
8. 返回 Controller，下一 Action 创建新 worker。

### 顺序

```text
Prior/Task 小样本
  -> Greenfield
  -> Brownfield（绑定 Greenfield XLSX）
  -> Office/visual
  -> verify-host-invocations
  -> Functional Acceptance
  -> Timing/Token Observation
```

### 完成标准

没有 provider usage 的宿主可以执行到 Functional Acceptance；没有 fresh worker 能力的宿主明确停止于 `HOST_FRESH_SESSION_UNAVAILABLE`。

## 8. Task 5：清理旧耦合措辞

### 修改

- 删除当前文档中把实际 provider usage 作为功能 E2E 前置条件的表述；
- 将“真实 benchmark 批准”拆成“Functional Acceptance 必需、Performance Observation 非阻断”；
- 删除当前计划/交接中的美元上限和费用汇总要求；
- 保留历史 benchmark 文件原文，不回写历史事实；
- `actualProviderVerified=false` 继续只描述 fixture smoke，不改成 true。

### 不做

- 不全仓重命名历史 `costShiftGuards`、`firstCostDivergence` 等已取代字段；
- 不删除历史 benchmark schema/fixture；
- 不把 token observation 引入生产 generation。

### 完成标准

当前权威文档、测试指南和新结果合同没有费用要求；历史材料仍明确是历史材料。

## 9. 验证顺序

实现时按最小失败面顺序执行：

1. Host invocation Schema 与 validator 单元测试；
2. Token `COMPLETE/PARTIAL/UNAVAILABLE` 计算和闭合 Schema 测试；
3. `test_real_benchmark_contracts.py`；
4. `test_benchmark_calculation_e2e.py`，使用 `LOCALLY_ESTIMATED` 证明功能不阻断；
5. `test_paired_benchmark.py`；
6. 文档/合同同步测试；
7. 完整插件 pytest；
8. 根 unittest；
9. repository validator；
10. copy smoke；
11. `git diff --check`；
12. 最后在全新宿主 Controller Session 执行真实 Prior/Task、Greenfield、Brownfield。

真实 E2E 报告必须分别列出：

- Functional Acceptance；
- Timing Observation；
- Token Observation 状态和可用 subtotal；
- 未执行或不可观测项；
- 不包含费用。

## 10. 计划完成条件

实施只有在以下条件全部成立时完成：

- 插件仍不依赖任何厂商 CLI/API；
- 当前宿主模型可直接承担真实 Action；
- E2E 的外层 session 和每个 Action worker 都是 fresh；
- token `PARTIAL/UNAVAILABLE` 不阻断功能；
- 时间始终可重算；
- token `COMPLETE` 时绝对总量无漏算和重复计数；
- 没有费用字段或费用门禁进入当前合同；
- 生产 runtime 合同未改变；
- 两份设计/计划文档逐项对应，无额外 provider、重试、遥测或发布范围。

## 11. 设计匹配与最小性复核

### 11.1 逐项匹配

| 设计决定 | 实施位置 | 匹配结果 |
|---|---|---|
| 模型由宿主当前配置选择 | Task 1、Task 4 | 不增加 provider/model 选择参数或厂商 Adapter |
| Fresh Controller + 每 Action Fresh Worker | Task 1、Task 2、Task 4 | 外层隔离与逐 Action 隔离分别记录，单并发不再等于复用对话 |
| 只证明 Plugin-Controlled Request | Task 1、Task 2 | 保存 `pluginRequestSha256`，不引入 provider wire request |
| Functional Acceptance 必需 | Task 3、Task 4 | 宿主隔离和现有业务/工件门禁仍阻断 |
| Timing Observation 始终记录 | Task 3 | 复用 Attempt/RunEvent，不增加计时 Module |
| Token Observation 是 Nice-to-have | Task 3 | `PARTIAL/UNAVAILABLE` 合法且不改变功能结果 |
| 实际绝对 token 不重复 cached/reasoning | Task 3 | 只以 `inputTokens + outputTokens` 形成 subtotal/total |
| 不统计费用 | Task 1、Task 5 | 当前合同不增加金额、价格或币种；历史材料不回写 |
| 生产协议保持兼容 | 第 3 节 | 明确排除 Action、Usage、Attempt、orchestrator、Owner 与 generation |

结论：计划覆盖设计的每项决定；没有设计外的业务输入、重试、遥测、发布或 provider 能力。

### 11.2 最小性

保留的最小改动只有三类：

1. **权威措辞**：否则宿主当前模型、两层 fresh session 和 token 非阻断语义仍会被旧说明反向覆盖；
2. **一份 test-only 隔离合同**：fresh session 是生产 ledger 无法推导的唯一外部事实；
3. **现有 benchmark 结果 v2 与计算/测试**：否则 token null 仍会被当前硬门禁拒绝。

没有创建第二个 aggregate、provider registry、厂商 Adapter、生产 execution receipt、价格表或新公开命令。删除任一保留项都会分别失去权威语义、fresh-worker 证明或 token 非阻断行为；再增加生产协议修改则没有解决本请求之外的问题。因此这是满足设计的最小方案。
