# 宿主原生模型执行与验收分层设计

- 状态：已实施；当前真实宿主 E2E 与 test-only benchmark 合同
- 范围：`ai-sow:generate` 的模型 Action 执行方式、真实功能 E2E 与可选性能观测
- 不变边界：插件不调用或依赖 Codex、Claude Code、OpenAI、Anthropic 或其他厂商 CLI/API
- 关联权威：[插件设计](AI_SOW_PLUGIN_DESIGN.md)、[领域约定](CONTEXT.md)、[阶段封存合同](../skills/generate/references/stage-seal.md)
- 配套计划：[宿主原生模型执行实施计划](HOST_NATIVE_MODEL_EXECUTION_IMPLEMENTATION_PLAN.md)

## 1. 问题

当前产品方向已经是宿主中立的：Python orchestrator 发行 hash-bound Action，宿主负责模型执行。但真实验收曾把三个不同问题绑在一起：

1. 功能是否能由当前宿主的当前模型完成；
2. 每个 Action 是否在无历史 worker 中执行；
3. provider 是否返回完整 token usage，以及这些 usage 是否满足性能门槛。

这会造成错误阻断：宿主能够真实运行模型并完成完整 SOW，但只因不能暴露 provider token usage，功能 E2E 和后续工件验证就不能开始。另一个错误前提是要求 provider wire request 只能包含插件构造的两条 message；Codex、Claude Code 等宿主必然附加自身的安全、工具和运行时 system context，插件既不能观察，也不应绕过。

本设计把功能验收与性能观测分开。功能是必需门禁；时间总是记录；实际 token 能取得就记录，不能取得时明确不可用，但不阻塞功能、Office、视觉、发布或后续测试。

## 2. 决策

### 2.1 模型选择归宿主

`ai-sow:generate` 不选择 provider 或 model。模型是宿主当前配置：

```text
Codex 当前 session      -> Codex 当前模型
Claude Code 当前 session -> Claude Code 当前模型
其他兼容宿主             -> 该宿主当前模型
```

插件只发行 Action 及其受控输入、输出位置和限额。宿主可以记录它观察到的 host/model 原值，但这些值不是插件配置，也不是功能 PASS 条件。无法观察 model 标识时记录不可用，不猜测、不从产品名反推。

现有 `modelProfileId = host-canonical-messages-v1` 是容量估算 profile，不是模型选择器或模型身份。保持该语义，不因宿主当前模型变化把它改造成 provider registry。

### 2.2 两层 fresh session

真实 E2E 使用两层隔离：

1. **Fresh Controller Session**：整次 E2E 从一个新宿主 session 启动，不继承开发、修复或先前测试对话；
2. **Fresh Action Worker**：每个 `MODEL_PROVIDER` Action 创建一个新的 worker session，只接收本 Action 授权的插件输入。

Controller Session 可以贯穿同一 run，但只负责 NextAction/file protocol、浏览器与提交，不承担 Owner 专业生成或评审。Action Worker 不继承 Controller、兄弟 Action、上游 Owner、Author 或 Reviewer 的对话。

测试中的“单代理、顺序执行”统一解释为：

```text
maxConcurrency = 1
每次只运行一个 Action
每个 Action 使用新的 worker session
```

它不再表示“所有 Action 复用一个持久模型对话”。同一 Action 的 hydrate/tool loop 可以在该 worker 内继续；新 Action 必须新建 worker。

### 2.3 插件控制输入，不声明 provider wire request

插件可验证并 hash 绑定的内容称为 **Plugin-Controlled Request**：

- Action contract instruction；
- packet；
- reference；
- hydrate response；
- `maxOutputTokens`；
- 对应 `actionId`、revision、attempt 与输入/checkpoint hash。

宿主实际发送给 provider 的完整 wire request 可能额外包含宿主 system、安全、工具或 sandbox context。该部分不属于插件控制面，也不作为功能验收的精确字节条件。

真实 E2E 只要求：

- worker 收到完整 Plugin-Controlled Request；
- 宿主没有把 Controller、兄弟或前序 Action 对话加入 worker 用户上下文；
- raw result 来自该 worker，并只提交给绑定的 Action；
- 不在正式 `submit` 前私下循环改写到通过。

测试证据记录本 Action 最后一次 hydrate 后完整 `read_provider_request` bytes 的 `pluginRequestSha256`。不新增 `providerWireRequestSha256`，也不声明 provider 隐藏 system context 可观察。

### 2.4 使用现有 Usage 双轨，不增加货币模型

现有生产合同已经区分：

- `PROVIDER_REPORTED`：宿主能从真实 completion 取得的 token；
- `LOCALLY_ESTIMATED`：插件按现有 estimator 得到的规划值。

保留这两个 machine token 和现有 `Usage` 结构，不新增费用、价格表或币种字段，也不把 `LOCALLY_ESTIMATED` 改名成实际消耗。

规则：

1. 功能执行始终可以使用 `LOCALLY_ESTIMATED` 完成 Attempt 记录和预算保护；
2. 实际 token 统计只消费 `PROVIDER_REPORTED`；
3. `LOCALLY_ESTIMATED` 只用于容量、计划预算和诊断，不进入“实际 token 消耗”结论；
4. 不用零值表示未知；未知由性能观测状态表达；
5. 不统计美元、价格或供应商账单。

`maxPlannedTokens`、`modelContextLimitTokens`、output/hydrate reserve 继续是安全规划限制，不是性能 PASS 门槛，也不是实际 token 观测。

## 3. 目标 Module 与 seam

### 3.1 Host Invocation Seam

宿主在现有 NextAction/file protocol 上承担一个逻辑 Interface：

```text
invokeFreshWorker(Action, PluginControlledRequest, Attachments)
  -> RawResult + ExecutionFacts
```

Interface 的约束：

- 使用宿主当前模型；
- 每个 Action 新建 worker；
- 输入绑定 `pluginRequestSha256`；
- 遵守 `maxOutputTokens`；
- 输出唯一 raw bytes；
- 提供 UTC timing；
- token 可用时提供 `PROVIDER_REPORTED`，否则使用现有 `LOCALLY_ESTIMATED`；
- `HOST_BROWSER` 仍由 Controller 执行，不构造模型请求。

这是宿主责任 seam，不是插件内的新 provider Module。仓库不提供 Codex/Claude/OpenAI/Anthropic Adapter。

### 3.2 证据边界

生产 run 继续以现有 Envelope、packet、Attempt、raw、normalized result、checkpoint 和 artifact proof 为业务证明。新增的宿主隔离事实只属于真实 E2E 测试证据，不进入稳定 SOW Model 或客户 generation。

最小的测试证据包含：

```text
Fresh Controller Session attestation
  + 每个 MODEL_PROVIDER actionId
  + pluginRequestSha256
  + FRESH_NO_HISTORY
  + freshWorker = true
  + 可选的宿主 invocation ID hash
  + 可选的 host/model 观察值
```

宿主 invocation ID 只保存不可逆 hash；宿主不提供时允许为空。功能门禁依赖明确的 fresh-worker attestation 和 Action 全覆盖，不依赖 invocation ID 是否可见。

## 4. 验收分层

### 4.1 Functional Acceptance：必需且阻断

Functional Acceptance 只判断产品是否完成正确工作：

- 真实宿主当前模型实际执行每个 `MODEL_PROVIDER` Action；
- 每个 Action 使用 fresh worker；
- Action、raw、Attempt、CandidateResolution 和 checkpoint 完整绑定；
- Prior/Task 小样本确实经过诊断、Patch 和复验；
- Greenfield 严格先于 Brownfield；
- Brownfield 使用 Greenfield verified XLSX 的精确 bytes；
- Scope、Story/AC、Task fresh Review 全部闭合；
- Office 回算、reference 回算、双复读、全部可见 Sheet render 与视觉检查通过；
- 两侧到达 `AWAITING_FINAL_REVIEW`；
- 失败 raw、Attempt、状态和工件保留。

任何 token observation 状态都不能改变 Functional Acceptance：

```text
COMPLETE    -> 功能按事实 PASS/FAIL
PARTIAL     -> 功能按事实 PASS/FAIL
UNAVAILABLE -> 功能按事实 PASS/FAIL
```

### 4.2 Timing Observation：必需记录，不作为功能门禁

时间从现有 Attempt timing 和 RunEvent 重算：

- active wall time；
- user waiting time；
- Action/Stage/Run 分段；
- deterministic Office/render 时间。

合法 ledger 必然提供这些时间。性能较慢只形成观测，不把功能 PASS 改成 FAIL。本轮不设置时间阈值，不声明性能改善。

### 4.3 Token Observation：Nice-to-have

Token Observation 使用三个状态：

| 状态 | 定义 | 允许结论 |
|---|---|---|
| `COMPLETE` | 每个已启动 `MODEL_PROVIDER` Attempt 都有 `PROVIDER_REPORTED` usage | 可报告实际绝对总量、分类总量、每正式节点 token 与 retry amplification |
| `PARTIAL` | 只有部分已启动 Attempt 有 `PROVIDER_REPORTED` usage | 报告已观察 subtotal、覆盖的 Attempt 数；整体比率为 null |
| `UNAVAILABLE` | 没有已启动 Attempt 提供 `PROVIDER_REPORTED` usage | 不报告实际总量或比率；保留本地规划值但不称为实际消耗 |

实际绝对总量定义为所有可计量 Attempt 的：

```text
inputTokens + outputTokens
```

`cachedInputTokens` 与 `reasoningTokens` 作为 breakdown 单独报告，不再次加入绝对总量，避免重复计数。失败、被 supersede 和 Repair Attempt 都属于实际消耗；不能只统计最终成功 Action。

部分 usage 不外推完整总量，不用本地估值补齐 provider subtotal。

### 4.4 不再存在 Cost Acceptance

本设计没有：

- `actualCostUsd`；
- price table；
- currency；
- provider 账单对账；
- 货币硬上限；
- 费用 PASS/FAIL。

不同接入方式的价格差异不属于插件功能或性能事实。

## 5. 真实 E2E 流程

```text
新建 Fresh Controller Session
  -> 固定测试输入、次数上限与 maxConcurrency=1
  -> Prior/Task 最小真实样本
     -> 每个 Action 新建 Fresh Action Worker
     -> 功能 PASS 才继续
  -> Greenfield 完整链
     -> verified workbook
  -> Brownfield 完整链
     -> 显式使用 Greenfield workbook
  -> Office/visual/portable proof
  -> Functional Acceptance
  -> Timing Observation
  -> Token Observation（COMPLETE/PARTIAL/UNAVAILABLE）
```

如果宿主不能创建 fresh worker，返回 `HOST_FRESH_SESSION_UNAVAILABLE` 并阻断 Functional Acceptance；这是功能前提缺失。宿主不能提供 token usage 时不返回输入缺失，不阻断任何功能步骤。

## 6. 具体场景

### 场景 A：Claude Code 能创建 fresh subagent，但不暴露 usage

- 使用 Claude Code 当前模型；
- 每个 Action 新建 subagent；
- 功能链正常执行；
- Timing Observation 完整；
- Token Observation = `UNAVAILABLE`；
- Functional Acceptance 可以 PASS。

### 场景 B：Codex 宿主提供每次 invocation usage

- 使用 Codex 当前模型；
- 每个 Action 新建 worker；
- 所有 Attempt 都报告 usage；
- Token Observation = `COMPLETE`；
- 报告绝对 token 总量，但不换算费用。

### 场景 C：部分 Action 有 usage，视觉 Review 没有

- 功能链继续；
- 已观察 token 原值保留；
- Token Observation = `PARTIAL`；
- 报告已观察 Attempt 数和 subtotal；
- `tokensPerFormalNode` 与 `retryAmplification` 为 null。

### 场景 D：只开一个新测试 session，所有 Action 在同一对话连续执行

- Fresh Controller 成立；
- Fresh Action Worker 不成立；
- Functional Acceptance FAIL；
- 不能用“测试 session 是新的”替代逐 Action 隔离。

### 场景 E：宿主模型标识不可见

- host/model observation 为空；
- 使用当前模型的事实由宿主执行方式保证；
- 不阻断功能；
- 若要跨运行比较性能，结果标记不可比较，而不是功能失败。

## 7. 最小变更边界

选定方案不修改生产生成协议的核心结构：

- 不改 `ActionEnvelope`；
- 不改 `Usage` machine token；
- 不改 `AttemptRecord`；
- 不改 public operations；
- 不新增 provider registry；
- 不新增厂商 Adapter；
- 不改 Owner、Candidate Patch、checkpoint、Office 或 publication 语义；
- 不修改已冻结 run。

只修改两类内容：

1. 文档和真实 E2E 操作合同，明确宿主当前模型、两层 fresh session 与 Plugin-Controlled Request；
2. 测试/benchmark 支持层，将 Functional Acceptance、Timing Observation 和 Token Observation 解耦，并允许 token `PARTIAL/UNAVAILABLE`。

历史 `baseline-75970b2`、已取代 benchmark 记录及其中的旧 `cost` 命名只作历史追溯，不迁移、不改写。当前实现没有真实货币计算，因此不为删除历史措辞扩大范围。

## 8. 方案比较

| 方案 | 功能 | 代价 | 结论 |
|---|---|---|---|
| 在插件内实现 Codex/Claude/OpenAI/Anthropic Adapter | 可取得部分模型/usage 信息 | 绑定厂商、凭据和 CLI/API；破坏安装边界 | 不采用 |
| 要求 provider wire request 与插件两条 message 完全相等 | 便于实验室比较 | 宿主原生环境不可观察且通常不成立 | 不采用 |
| 仅开一个新 session，所有 Action 复用其历史 | 实现最少 | Author/Review/Repair 相互污染 | 不采用 |
| token 缺失时跳过整条 E2E | 保留现有 benchmark 逻辑 | 功能被 Nice-to-have 指标错误阻断 | 不采用 |
| 宿主当前模型 + Fresh Controller + 每 Action Fresh Worker + 分层验收 | 保持宿主中立；功能可验证；usage 尽力记录 | 需要测试侧隔离证明和结果拆分 | 采用 |

采用方案是最小的深 Module 设计：Host Invocation seam 的 Interface 只要求 fresh worker、完整插件输入、raw、timing 和可选 usage；厂商调用复杂度全部留在宿主实现。删除该 seam 会迫使每个测试和调用方分别解释模型选择、隔离和 usage，说明它具备实际 Depth。

## 9. 完成标准

实施后必须同时成立：

1. 在 Codex 或 Claude Code 的全新 Controller Session 中，可以不配置厂商 CLI/API adapter 而运行真实功能 E2E；
2. 测试固定 `maxConcurrency=1`，且每个模型 Action 有独立 fresh-worker 证据；
3. Token Observation 为 `PARTIAL` 或 `UNAVAILABLE` 时，Prior/Task、Greenfield、Brownfield、Office、视觉和 Functional Acceptance 仍可继续；
4. Token Observation 为 `COMPLETE` 时，实际绝对 token 总量包含成功、失败、superseded 和 Repair Attempt，且不重复 cached/reasoning breakdown；
5. Timing Observation 始终从不可变记录重算；
6. 任何输出都不包含货币费用或价格推导；
7. Fixture smoke 仍明确 `actualProviderVerified=false`，不冒充真实模型功能 E2E；
8. 生产 Action、Usage、Attempt、checkpoint 和 generation 合同保持兼容。
