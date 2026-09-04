# AI SOW 插件方案

- 状态：当前正式合同
- 插件版本：`0.1.0-beta.1`
- SOW 标准：`1.3`
- 适用宿主：Codex、Claude Code、CI 与自定义本机宿主
- 公开入口：`ai-sow:generate`
- 领域语义：[CONTEXT.md](CONTEXT.md)
- 计算权威：[sow-template.xlsx](../skills/generate/assets/sow-template.xlsx)
- 运行时合同：[插件运行时环境合同](../references/runtime-environment.md)

## 1. 设计目标

AI SOW 用一个公开 Skill 完成首次生成、增量更新、输入恢复、候选批准与不可变发布。用户只提供项目
资料和必要决策；内部阶段、action group、checkpoint、hash 和 reviewer shard 都是可测试 seam，不是
额外用户命令。

核心原则：

1. PRD 决定业务结果，HLD/ADR 决定高层技术边界，往期 SOW 只提供可验证的 Brownfield 合同起点；
2. 一份 reviewed `SOW Model` 是范围、设计、Story/AC、Task 与估算输入的唯一稳定业务真相；
3. 模型只提交 hash-bound typed result，固定实现拥有静态字段、引用、checkpoint、事务和发布；
4. 每个模型 action 都使用 `FRESH_NO_HISTORY`，不继承主对话、兄弟 action 或前序阶段历史；
5. 不完整输入、失败 action、Schema/hash 漂移或 Office 验证失败都 fail closed，并保留 last-known-good；
6. Excel 模板是任务目录、基础人天、复杂度、SIT、UAT、公式和取整的唯一计算权威；
7. 用户只批准已通过评审和 Office 复读的精确 artifact manifest；自动生成不等于客户签署。

## 2. 包结构与独立安装边界

```text
plugins/ai-sow/
├── .codex-plugin/plugin.json
├── .claude-plugin/plugin.json
├── pyproject.toml
├── uv.lock
├── runtime/
├── references/
├── docs/
├── tests/
└── skills/generate/
    ├── SKILL.md
    ├── assets/
    ├── contracts/
    ├── fixtures/
    ├── prompts/
    ├── references/
    ├── scripts/
    └── tests/
```

`runtime/` 只提供业务无关的诊断和安全项目 I/O。`generate` 独占 SOW Model、Action、Run State、Stage
Checkpoint、Review/Repair、Artifact Approval、Generation Manifest 等业务合同，以及编译器、模板、
renderer、fixture 和测试。运行时不得读取插件目录之外的实现文件，也不得依赖 marketplace 根目录。

内部模块所有权：

| Module | 所有权与边界 |
|---|---|
| `intake` | cheap gate、格式校验、来源 block、不可变 input revision 与模板快照 |
| `scope_compiler` | Stage 1 的 InputItem、Scope Closure、Epic/Feature、Design/Integration/NFR/Policy 与返修 |
| `delivery_compiler` | Stage 2 的 Story/AC，不能反向改变 Stage 1 |
| `task_compiler` | Stage 3 的 Task、Dependency、Effective Start Match 与 Estimation Annotation |
| `final_review` | R1、R2/R3 leaf review、Theme Join、Adjudication 和 repair plan |
| `sow_model` | 唯一模型的结构、引用、Owner 写集合与 checkpoint 闭包 |
| `package_renderer` | 从 reviewed SOW Model 与 revision 模板确定性渲染 Package |
| `generation_store` | 独立复核暂存件、批准绑定、不可变 generation 与原子 current 切换 |

`orchestrator` 只维护公开状态机、路由、action 发放和事务，不拥有业务判断。

## 3. 宿主中立 NextAction 协议

公共操作固定为 `start / submit / hydrate / resume / approve / abandon / status`。bootstrap 只是准备隔离
Python 环境并调用同一个 orchestrator；运行时不调用 Codex CLI、Claude Code CLI 或其他代理产品命令。

宿主循环按 `nextAction.kind` 处理：

1. `MODEL_ACTION_GROUP`：在 `maxConcurrency` 内运行一个或多个 action。每个 worker 只读取 envelope
   指定的 `promptPath`、`packetPath`、`referencePaths` 与本 action hydrate 返回的证据；
2. worker 把唯一 typed result 写入锁定的 `outputPath`。宿主另写 execution JSON，记录 provider/model、
   工具、耗时、尝试次数和真实 token usage；无法取得 usage 时必须显式标记本地估算；
3. `submit` 校验 result、execution、packet 与 action hash，并封存不可变 record。只有整组必需 shard
   全部完成，`resume` 才一次应用，绝不部分推进；
4. `REQUEST_INPUT` 集中展示最少问题。新 request 先通过 cheap gate，再关闭旧 run、创建新 revision；
5. `REQUEST_APPROVAL` 展示不可变候选包与可读文件。用户批准精确
   `artifactManifestSha256` 后才允许发布；
6. `DONE` 报告 `PUBLISHED`、`REUSED` 或安全终态并停止。

同一 worker 只在单个 action 的工具往返中复用上下文。action record 不复制 submission、证据正文或
完整工具输出，只保存项目相对结果路径和 SHA-256；需要重建时从不可变文件复读并验 hash。

## 4. 输入合同与不可变 revision

PRD、DEMO、HLD、ADR、PRIOR_SOW、SUPPLEMENT 和 QUESTION_ANSWER 都进入统一来源 inventory：

| 输入角色 | 支持格式与规则 |
|---|---|
| PRD/HLD/ADR | UTF-8 Markdown |
| DEMO/SUPPLEMENT | UTF-8 文本、Markdown、HTML、TypeScript/TSX 或 XLSX |
| PRIOR_SOW | XLSX；提供时作为合同起点，不自动证明当前生产状态 |
| QUESTION_ANSWER | 绑定当前完整问题包 hash 的精确用户答案 |

Greenfield 不继承历史合同能力。Brownfield 可以提供适用往期 SOW；未提供时记录
`priorSowState = NOT_PROVIDED` 并建立新基线，不虚构历史承诺。若缺口会改变范围、责任或估算，流程
返回 `REQUEST_INPUT` 或安全终态。

intake 先完成格式、路径、必需字段、来源状态和模板 Table 的 cheap gate，然后创建不可变 revision：

```text
.ai-sow/inputs/revisions/<revision>/
├── manifest.json
├── sow-template.xlsx
└── sources/
```

manifest 绑定 request、模板、Delivery Policy、Execution Policy、prior SOW、source 和无损 block hash。
模型不读取原始聊天历史，来源证据由 packet inventory 与 `hydrate` 精确提供。

## 5. 三阶段 SOW Model 编译

唯一 `ai-sow-model-v1` 同时保存：

- `inputItems` 与逐项 `scopeClosure`；
- `epics / features / designItems / integrations / nfrs / policyInstances`；
- `stories / acceptanceCriteria`；
- `tasks / dependencies / effectiveStartMatches`；
- 各 Owner annotations 与结构化 decisions。

阶段顺序和写集合固定：

```text
Stage 1 Scope
  -> R1 Source Audit
  -> R1 Scope Join
  -> ScopeClosureCheckpoint
Stage 2 Story/AC
  -> StoryAcCheckpoint
Stage 3 Task/Estimation
  -> TaskCheckpoint
Layered Review
  -> Artifact + Office verification
  -> User approval
  -> Publication
```

模型提交 replacement set，并为所有已存在的 upsert/delete 节点提供 expected hash。Owner 编译器只允许
修改本阶段写集合；兄弟 shard 完成前不应用；跨阶段引用、SourceRef、Policy、Task catalog row semantic
hash 和 checkpoint 都由固定实现验证。

Story 必须是 Feature 下单一、可独立移交、验收和关闭的具体结果。每个 Story 至少两条可观察 AC、最多
四个 Task。Task 一行只对应模板目录中的一个计数对象、一种工作模式和一个 S/M/L 复杂度；模板语义不
允许由 Python 或模型复制计算。

## 6. 分层独立评审与返修

R1 先对每个来源 shard 做独立 Source Audit，再对完整 audit union 和 Stage 1 projection 做 Scope Join。
R1 finding 只允许一次最小 Stage 1 repair；repair 必须绑定 finding、editable/locked node 和 expected
hash，完成后必须再运行新的 R1 Scope Recheck，之后才允许进入 Stage 2。

R2 `STORY_DESIGN` 与 R3 `TASK_ESTIMATION` 按逻辑主题拆成最多八个物理 shard。多 shard 主题必须经过
Theme Join：join 绑定全部 leaf result hash，且不得丢弃任一 finding。不同评审对同一 subject 给出不同
结论时，必须发出新的 `FRESH_NO_HISTORY` Adjudicator action，显式选择保留的 finding；编排器不能按
顺序覆盖或自行猜测。

`INPUT_REQUIRED` 回到用户输入，`CONTRACT_GAP` 安全终止，Owner finding 生成最小影响 repair plan。
所有通过的 review decision 绑定 SOW Model、三个 checkpoint 和每个 leaf/join/adjudication result hash。

## 7. 重用、渲染与增量路由

路由只由完整 hash proof closure 决定：

| Route | 条件与行为 |
|---|---|
| `REUSE` | 路由基础全部相同；直接复用 current generation，不创建 action |
| `RENDER_ONLY` | 变化仅限 `templateSha256`/`rendererSha256` 且任务目录语义未变；复用 SOW Model、checkpoint 和 review decision，不启动 Reviewer |
| `DELTA_COMPILE` | 语义输入、Policy、任务目录或阶段证明变化；克隆已发布 SOW Model 为基线，重编译并保留未受影响节点原字节 |
| `FULL_COMPILE` | 首次生成、执行政策变化、旧合同或 generation proof closure 无效；从 Stage 1 开始 |

`lowestRecoveryStage` 由变化 hash 的最早 Owner 决定。任何局部恢复都必须证明上游 checkpoint 可复用；
无法证明时扩大到更早阶段。模板任务目录或估算语义变化会重新编译 Delivery 并重新评审，不能只把旧
Task 套入新标准；纯输出字节变化才允许 `RENDER_ONLY`。

## 8. 项目事务与不可变发布

```text
.ai-sow/
├── current.json
├── inputs/revisions/<revision>/
├── generations/<generation>/
│   ├── manifest.json
│   ├── data/sow-model.json
│   └── output/{sow.xlsx,sow-notes.md}
└── work/
    ├── active-run.json
    └── runs/<run>/{actions,groups,candidates,checkpoints,reviews,artifacts}
```

一个项目同一时间只有一个 active run。request、input revision、run state、candidate、action、result、
execution、record、group plan、checkpoint、review decision 和 artifact manifest 都用项目相对路径与 hash
闭合。crash 后 `status/resume` 从这些文件恢复，不依赖聊天上下文。

artifact 先在 work 中渲染并由 Office 回算复读；用户批准后，`generation_store` 再独立验证 SOW Model、
模板、renderer、workbook/notes 和批准绑定，发布新 generation，最后原子替换 `current.json`。批准前、
失败、崩溃、输入等待或手工放弃都不会覆盖 last-known-good。

## 9. Package 与工作簿

当前只支持 XLSX 模板。每个 input revision 保存 `sow-template.xlsx` 本轮专用副本；Task 编译、评审、
渲染和复读始终使用同一份不可变模板。正式工作簿固定为 `01-需求故事`、`02-任务清单`、
`03-工作量汇总`、`90-估算标准` 四个 Sheet 和五个命名 Table。

Python 只投影业务文本与关系并保留公式、Table 计算列、样式、行高、筛选、验证、保护和打印设置。
LibreOffice 在项目内隔离临时目录真实回算；随后分别复读公式与缓存值，并核对全部输入行、目录、参数、
公式错误和汇总恒等关系。只有 `workbookVerification.trustState = VERIFIED` 才能请求批准和发布。

普通文本以 `= / + / - / @` 开头时仍按文本写入。`sow-notes.md` 必须披露输入边界、关键解释、假设、
责任、排除项、待设计事项、风险和变更触发条件；不能只存在于执行日志。

## 10. 运行时、跨平台与隐私

平台 bootstrap 在插件安装副本内准备 uv 0.11.7、managed Python 3.12、锁定依赖和 `.venv`。普通用户
无需预装 Python/uv，也无需激活虚拟环境：

- macOS/Linux：`bootstrap.sh` 与 `.venv/bin/python`；
- Windows 11 x64：`bootstrap.ps1` 与 `.venv/Scripts/python.exe`。

所有公开结果是唯一 UTF-8 JSON。Windows PowerShell 5.1 的脚本编码、`PSModulePath` 和长路径预算由
运行时合同约束；插件不会静默修改机器级策略。正式发布仍需可执行 LibreOffice。

`.ai-sow/` 包含客户原文和衍生数据，应默认被版本控制忽略。稳定 SOW Model、generation manifest 和
action record 不保存凭据、私有源码、完整工具输出或本机绝对路径。项目 I/O 拒绝绝对路径、上跳、
符号链接穿越和插件外写入。插件不执行 Git 网络、历史改写、提交、推送或发布。

## 11. 验证与非目标

验证覆盖合同/Owner 单测、公共 NextAction E2E、锁定输入的 fail-fast validation campaign、性能/Token
benchmark，以及独立复制插件 smoke。配对 benchmark 只有在 `compare` 机械验证精确 32 样本矩阵、
必需 ACTION/STAGE 覆盖、按 policy 重算全部 ACTION/STAGE/RUN 收据 outcome、ACTION→STAGE→RUN
计量聚合、收据哈希/签名、相同输入/环境/cache namespace、同执行配置和全部目标，并生成 PASS
comparison receipt 后，才允许声明数值改善；仓库验证器
会按 receipt 绑定的 policy 与两份 manifest 重新求值，不能仅靠路径或 hash 字符串把门禁改成
`SATISFIED`。copy smoke 直接使用 Python API，覆盖 Greenfield、Brownfield、
输入恢复、`REUSE`、无 Reviewer 的 `RENDER_ONLY` 和保留未受影响下游节点的 `DELTA_COMPILE`；读取守卫
证明 marketplace 零读取，失败收据与 worker stdout/stderr 在清理前保留。

历史提交 `75970b2` 只保留了聚合指标和匿名缺陷分类，没有逐样本收据、完整执行配置或可靠冷热配对，
因此被登记为 `PARTIAL_BASELINE_CHECKPOINT`，只可用于根因定位和修复排序。它不能证明任何候选版本的
相对性能。数值改善结论必须由两个通过 `pipeline-benchmark.schema.json` 校验的完整 manifest 支持：每个
manifest 至少 32 个样本，三种成功规模分别执行五次 `COLD` 和五次 `WARM`，另含两个阻断场景，并保持
模型、reasoning、工具、Office、计量和 cache protocol 一致。门禁未满足时，70% 目标只能作为政策目标，
不能表述为已达成结果。

本版本明确不提供：Codex/Claude CLI 运行时依赖、旧命令兼容、旧业务数据迁移、字段级未校验 patch、
Python 公式执行、PDF/Word/PPT 解析、自动 Git 操作或客户签署判断。CI 的 Linux/macOS/Windows 矩阵
证明协议与路径实现可移植，不等同于物理设备或 Excel Desktop 的实机认证。
