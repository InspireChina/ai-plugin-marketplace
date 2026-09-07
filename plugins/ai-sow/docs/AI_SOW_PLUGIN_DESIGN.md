# AI SOW 插件方案

- 状态：当前正式合同
- 插件版本：`0.1.0-beta.2`
- SOW 标准：`1.3`
- 适用宿主：Codex、Claude Code、CI 与自定义本机宿主
- 公开入口：`ai-sow:generate`
- 领域语义：[CONTEXT.md](CONTEXT.md)
- 计算权威：[sow-template.xlsx](../skills/generate/assets/sow-template.xlsx)
- 运行时合同：[插件运行时环境合同](../references/runtime-environment.md)

## 1. 设计目标

AI SOW 用一个公开 Skill 完成首次生成、输入更新、执行恢复、候选批准与不可变发布。用户只提供项目
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
| `scope_compiler` | Stage 1 的 InputItem、Scope Closure、Epic/Feature、Design/Integration/NFR/Policy、PriorStateSnapshot、ChangeGraph 与返修 |
| `delivery_compiler` | Stage 2 的 Story/AC，不能反向改变 Stage 1 |
| `task_compiler` | Stage 3 的 Task、Dependency、Effective Start Match 与 Estimation Annotation |
| `owner_callbacks` | 将冻结 Action 绑定到对应 Owner validator/RepairPlan；只做依赖反转与责任路由，不保存状态或业务规则 |
| `final_review` | fresh Review/条件 Repair、定向 root 修复与 StageCheckpoint 证明 |
| `sow_model` | 唯一模型的结构、引用、Owner 写集合与 checkpoint 闭包 |
| `package_renderer` | 从 reviewed SOW Model 与 revision 模板确定性渲染 Package |
| `generation_store` | 独立复核暂存件、批准绑定、不可变 generation 与原子 current 切换 |

`orchestrator` 只维护公开状态机、FULL_COMPILE 与本轮恢复、action 发放和事务，不拥有业务判断。

## 3. 宿主中立 NextAction 协议

公共操作固定为 `start / submit / hydrate / resume / approve / abandon / status`。bootstrap 只是准备隔离
Python 环境并调用同一个 orchestrator；运行时不调用 Codex CLI、Claude Code CLI 或其他代理产品命令。

宿主循环按 `nextAction.kind` 处理：

1. `MODEL_ACTION_GROUP`：在 `maxConcurrency` 内运行一个或多个 action。每个模型 Action 使用宿主当前配置模型和新的 `FRESH_NO_HISTORY` worker，只读取 envelope 指定的 `promptPath`、`packetPath`、`referencePaths` 与本 Action hydrate 返回的证据；
2. worker 把唯一 typed result 写入锁定的 `resultPath`。宿主另写 execution JSON，记录 UTC timing、结构化 failure 和 Usage；能取得 completion usage 时使用 `PROVIDER_REPORTED`，否则使用 `LOCALLY_ESTIMATED`，不猜测 provider/model 或实际 token；
3. `submit` 校验 result、execution、packet 与 action hash，并封存不可变 record。只有整组必需 shard
   全部完成，`resume` 才一次应用，绝不部分推进；
4. `WAITING_INPUT` 集中展示最少问题。业务输入变化先 abandon，再以完整新 request start；
5. `REQUEST_APPROVAL` 展示不可变候选包与可读文件。用户批准精确
   `artifactManifestSha256` 后才允许发布；
6. `DONE` 报告 `PUBLISHED` 或安全终态并停止。

同一 worker 只在单个 action 的工具往返中复用上下文。action record 不复制 submission、证据正文或
完整工具输出，只保存项目相对结果路径和 SHA-256；需要重建时从不可变文件复读并验 hash。

## 4. 输入合同与不可变 revision

PRD、DEMO、HLD、ADR、PRIOR_SOW、SUPPLEMENT 和 QUESTION_ANSWER 都进入统一来源 inventory：

| 输入角色 | 支持格式与规则 |
|---|---|
| PRD/HLD/ADR | UTF-8 Markdown |
| DEMO | 无需构建的静态 HTML/CSS/JavaScript bundle，入口与所有文件均显式声明 |
| SUPPLEMENT | UTF-8 文本、Markdown、HTML、TypeScript/TSX 或 XLSX |
| PRIOR_SOW | XLSX；由 Scope 按计划生效日形成合同推定的生产 As-Is |
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
Scope StagePlan → materialize → validate → fresh Review → ScopeCheckpoint
Story/AC StagePlan → materialize → validate → fresh Review → StoryAcCheckpoint
Task StagePlan → materialize → validate → fresh Review → TaskCheckpoint
```

各 Owner 只接收窄 IR，由程序注入稳定 ID 和节点引用；全部 sibling 工作成功后才整体物化。Review 需要语义修复时最多增加一个 Owner IR revision，并重新完整验证和 fresh Review。三个 checkpoint 关闭后交给工作簿与发布后缀；完整生成的 Office、批准发布验收独立进行。

Story 必须是 Feature 下单一、可独立移交、验收和关闭的具体结果。每个 Story 至少一条完整关闭义务的可观察 AC（不按固定数量凑数）、最多
四个 Task。Task 一行只对应模板目录中的一个计数对象、一种工作模式和一个 S/M/L 复杂度；模板语义不
允许由 Python 或模型复制计算。

## 6. 阶段自动封存与受限修复

每个 Owner 的 StagePlan 取得有效结果后，只物化当前 IR，执行完整机械验证，再发行 fresh Review。
机械候选失败和新发生的 `REPAIRABLE_SEMANTIC` 使用 `CANDIDATE_PATCH-v1`：Owner 发放字段设置、未授权附加字段删除、对象追加/删除或
原子 root 变换槽位，程序继承其余数据并生成 CandidateResolution。`REMOVE_FIELD` 只处理 Schema 明确拒绝的现存字段，不扩大对象或集合写权限；缺失身份可由窄 `SET_FIELD` 补齐，已有身份仍不可改写或复用。RepairReceipt 绑定规范化 Patch，物理 Attempt 保留并绑定模型原始 raw，使非 canonical JSON 仍可确定性恢复。
语义来源另绑定 Review Attempt、Review decision/candidate、程序侧 Owner IR base 与 semantic source descriptor；Patch 不能写 PASS。
修复后必须重新物化、完整验证和发行 distinct fresh Review。已物理发行的旧 `*_REPAIR-v1/v2` 原字节完成。

## 7. 新 run 与恢复

公开 start 只执行 FULL_COMPILE，不读取旧 generation 决定业务内容。同一未完成 run 从自己的不可变 StagePlan、Attempt 和 checkpoint 恢复；已完成的物化/校验不重做。业务输入变化先 abandon，再以完整新 request 启动。政策只允许至少一项 token、active-time、未来请求的上下文容量、hydrate reserve、候选/执行次数或 Demo 限额严格增加，其余值保持原值；正文相同也拒绝。替换只发布 content-addressed policy 和 RunEvent，不创建业务 revision 或重排冻结计划。Brownfield 只消费本次明列的 PRIOR_SOW 与 declaredChangeContext。

只保留 FULL_COMPILE 与同 run 恢复。

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
execution、record、完整 StagePlan、checkpoint、review decision 和 artifact manifest 都用项目相对路径与 hash
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
公式错误和汇总恒等关系。`generation-renderer-v12` 在现有汇总 Sheet 追加可见实体 ID 与公开 SourceRef 追溯区，并经真实只读 Prior adapter 验证往返。

Office identity 只保存 executable basename、可执行文件 SHA-256、完整 version、platform、无路径的 normalizedArguments 和零 exit code。所有可见 Sheet 按工作簿顺序由真实 LibreOffice 导出 PDF；隐藏 Sheet 不要求 render。单个 `ARTIFACT_VISUAL_REVIEW` 使用模型 REVIEW Attempt，窄 IR 仅包含逐 Sheet checks/decision/findings 与 overallDecision；Sheet 和 render 顺序保留，不作为集合排序。

`ai-sow-artifact-manifest-v2` 深绑定唯一 SOW Model、三个 StageCheckpoint 及完整 Attempt/packet/result/实际步骤事件证明、可选 Prior、模板/renderer、Office、公式/结构复读、全部 renders 和最终 XLSX。visualReview 只保存成功 AttemptRecord hash。最终 XLSX 通过 `publish_new` 冻结后只读；所有验证与视觉 PASS 完成后才进入 `AWAITING_FINAL_REVIEW`。generation 携带完整离线证明闭包，批准和复读均不需要原 run 或输入目录。

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

## 11. 历史 benchmark（已取代）与验证边界

验证覆盖合同/Owner 单测、公共 NextAction E2E、锁定输入的 fail-fast validation campaign、性能/Token
benchmark，以及独立复制插件 smoke。配对 benchmark 只有在 `compare` 机械验证精确 32 样本矩阵、
必需 ACTION/STAGE 覆盖、按 policy 重算全部 ACTION/STAGE/RUN 收据 outcome、ACTION→STAGE→RUN
计量聚合、收据哈希/签名、相同输入/环境/cache namespace、同执行配置和全部目标，并生成 PASS
comparison receipt 后，才允许声明数值改善；仓库验证器
会按 receipt 绑定的 policy 与两份 manifest 重新求值，不能仅靠路径或 hash 字符串把门禁改成
`SATISFIED`。copy smoke 直接使用 Python API，覆盖 Greenfield、Brownfield、
同 run 恢复、新输入完整编译与逐阶段 fresh Review；读取守卫
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

内部 checkpoint 自动封存；运行中用户只回答问题或补充材料。严格顺序 Greenfield→Brownfield 的
pair harness 不属于插件业务 Owner。两侧 verified artifact 均完成后，共同展示两份 Excel，
只取得一个 PairDecision。APPROVE 深绑定共同 manifest 与双方工作簿；两个 generation/current
都匹配才算发布。中断重放同一决定；REJECT 使用 hash 寻址的完整新 request，按受影响侧重跑后重新共同评审。

Scope 独占 PriorStateSnapshot 与 ChangeGraph，唯一 stable_ids 实现受控身份。snapshot 绑定显式 revision 原字节；
无 Prior 时 checkpoint 省略 priorStateSha256，有 Prior 时 Story/Task 只消费该 hash，不能重新解析工作簿。
相同 workbook 的不同 sourceId 保留分别的 audit evidence；DUPLICATE 组件只取 canonical source 进入 effective view。
visiblePriorId 必须是源单元格中的精确完整 ID，且语义唯一、不变、一对一匹配经 Scope fresh Review 验证；
重复引用同一实体可以保留，歧义、split/merge 不继承。Brownfield 仅从转交 XLSX 恢复这些事实。

当前来源合同：DEMO 是无需构建的静态 HTML/CSS/JavaScript bundle。HOST_BROWSER 报告实际 browserProfile，
同 run 所有 trace 精确匹配；关键 scenario 两次，实际不稳定结果必须一次 bounded replay。预算跨全部 rounds/replays 累计。
Scope 消费所有轮次的 ObservationIR。采用的 CODE_ONLY candidate、source evidence 和 round/Attempt 绑定进入唯一 Scope Review packet；
ReviewDecisionIR 的 PASS 显式确认完整 intent obligations，缺项或 stale/unrelated proof 不能封 checkpoint。

模型由宿主当前配置选择，插件不接收 provider/model 选择参数。宿主读取 `read_provider_request` 的 canonical Plugin-Controlled Request 与 `maxOutputTokens`；`host-canonical-messages-v1` 和 `utf8-bytes-v1` 只定义规划表示与 UTF-8 byte-count，不是模型身份，也不证明真实 tokenizer、模型容量或 provider 用量。宿主可附加自身 system、安全、工具和 sandbox context；这些 provider wire request 内容不属于插件控制面。

每个 `MODEL_PROVIDER` Action 使用新的 `FRESH_NO_HISTORY` worker；同一 Action 的 hydrate/tool loop 可复用该 worker，但新 Action 不继承 Controller、兄弟或前序 Action 历史。真实 E2E 还要求全新的外层 Controller Session 和 `maxConcurrency = 1`，逐 Action worker 隔离不能由“外层 session 是新的”替代。测试以每个 Action 的 `pluginRequestSha256` 和 test-only 宿主观察报告证明该边界，不修改生产 Action、Usage、Attempt 或 generation。
packet 只有 workItems/contextRefs；基础 context 是 refId/canonicalContent/contentSha256，dependency context 是
refId/canonicalContent，其正文为 kind=DEPENDENCY_RESULT、logicalWorkId、attemptRecordSha256、normalizedResult。
规划只计已知 bytes，发放前再次验证包含全部 dependency/repair 的实际请求容量；不足时等待，不修改冻结计划。
MATERIALIZE、VALIDATE、OFFICE 和复读独立检查 active-time，并记录实际完成区间；等待不计时，重叠区间只算一次。

真实验收分为三层：Functional Acceptance 对实际模型执行、fresh worker、业务/checkpoint/Office/工件闭包保持必需且阻断；Timing Observation 始终从 Attempt/RunEvent 重算但不设功能阈值；Token Observation 只汇总 `PROVIDER_REPORTED`，按 `COMPLETE / PARTIAL / UNAVAILABLE` 报告且不阻断功能。实际绝对 token 为 `inputTokens + outputTokens`，cached/reasoning 只作 breakdown；`LOCALLY_ESTIMATED` 只用于容量与计划，不冒充实际消耗。当前验收不计算金额、价格、币种或费用门禁。

上述历史 32 样本比较器仅分析历史收据，不是当前执行入口；当前真实配对验收的 B.a–B.p、oracle、浏览器、
严格顺序双 workbook 和逐项硬门槛必须另行完成。当前仓库 fixture 通过不代表这些实际验收已完成。

生成后的 Scope、Story/AC 和 Task 优先按 findings 及影响范围局部修复，保留正确结果；普通 Repair 可调整、合并或拆分授权对象；共享测试资产保留独立 Story/AC，只计量一次，工作簿展示覆盖与费用归属。自动停止后，`resume --decision` 可绑定原终态与失败 Review，按明确用户裁定仅修允许字段、追加一个候选并 fresh Review，完整保留累计次数与消耗。具体合同见 [阶段自动封存](../skills/generate/references/stage-seal.md)。

往期 Excel 大表按完整证据行分组，保留全部单元格、位置、哈希与表头，避免整张 Sheet 超出单次请求容量。阶段尚未发行计划工作便因容量等待时，修复分组后可从原 run 恢复，复用已完成的原型观察和检查点，不提高模型容量或重置消耗。

Prior v2 允许通过冻结 priorContext 与现有 hydrate 读取同一 source/workbook 的跨分区、跨 Sheet 原文，实体仍需所属 namespace 主证据。提取、覆盖、精确单元格身份和窄关系汇总的权威合同见[Scope Owner](../skills/generate/references/scope-owner.md)。v1 IR 保留原约束，历史 run 仍绑定原源码和冻结合同，不自动迁移。

ABANDON 恢复完成后立即结束恢复后缀，避免再次读取已移除的 active marker。artifact 取证从最终 Task checkpoint 及预览修复授权事件恢复不可变候选绑定，离线读取不依赖当前候选指针。

Task Repair 的 AC 重分配限于本轮受影响 roots 已有的覆盖；历史授权不能扩张后续无关修复。公开 submit 在成功 Attempt 封存前拒绝越界为 INVALID_IR，物化与 proof 回放使用相同 Task-local 校验。

ARTIFACT RENDER 的真实导出在成功事件前持久暂存；恢复只复用该事件精确 hash 绑定的原字节，复核篡改并记录恢复 I/O 时间。没有成功事件的孤儿暂存不授权复用；旧运行缺少暂存时仍重算并匹配原 hash。此规则不改变 renderer、工作簿或已批准预览。

XLSX 数组公式按原始公式文本提取证据，不使用带进程地址的对象字符串；缺少公式文本和无原公式文本的数据表公式明确拒绝。已冻结输入保持原字节，后续新 Prepare 使用确定性结果。

新冻结计划采用 `PRIOR_ANALYZE-v3`，以版本固定既有无损表传输并覆盖初始请求；专业 prompt、Prior v2 schema 和限额不变，Consolidate 仍为 v2。现有支持布局的旧计划从已绑定合同版本重建估算、物化和证明，不跟随当前默认选择。旧请求保持原字节，历史输入布局不自动迁移。具体规则见[阶段自动封存](../skills/generate/references/stage-seal.md)。

未来 Task 计划使用 `TASK-v2`，其对应 `TASK_REPAIR-v2` 的完整规则读取上限为 65536；有效额度仍取 Action 合同与显式 run hydrate reserve 的较小值。原 v1 合同、prompt/schema、请求和冻结计划保留，Repair、物化及离线证明跟随冻结 Author 版本。增加 reserve 不放宽两轮累计响应或完整请求 context 检查；可用输入空间不足时仍等待。Task 身份碰撞在成功封存前按 `TASK_IDENTITY_COLLISION`/`INVALID_IR` 返回两个问题 localKey，沿既有 revision 2 修正；身份算法与后置复核不变，不按名称或工作类型制造新身份。

已批准的 SIT/UAT 界面自动化政策可直接以其 PRD 政策与各条 AC 的 PRD/Demo 证据支持 `TEST-UI-E2E`，适用范围限于无设计引用的对应 Story/AC。共享测试仍逐 Story 核对政策与证据；工作类型、模式、复杂度、计价和完整性继续由模板规则及独立评审验证，不据此推导后台或部署设计。


机械失败沿同一逻辑工作保留候选 raw、完整 `AttemptDiagnostic.findings` 和已成功依赖。默认每个逻辑工作最多 2 个候选版本、每个版本最多执行 2 次；用尽后进入 `WAITING_INPUT`，不因次数耗尽进入 `SYSTEM_FAILED`。可在 `resume --budget-policy ...` 中显式增加 `maxActionRevisions` 或 `maxExecutionAttempts`（各项 2–10，省略为 2），继续累计 revision/attempt；已发行 Envelope、旧失败、成功 checkpoint 与原计量不回写。新版本只绑定紧邻的前一次失败。该入口不会恢复已放弃的 run。

Scope 的 Scan/Audit/决策、Story/Task、Prior Analyze 和原型 Scenario/Observation 的机械诊断保留问题对象及具体路径。Prior Consolidate 保留已成功的依赖实体，只修新增关系。修复只允许这些 roots 及 Owner 定位的覆盖范围变化，无关对象和字段保持一致；跨 Story 边界拆分只使用被诊断 Story 已有的义务。越界候选被拒绝，中间的非法 JSON/Schema 也不能撤销先前的保护基线。成功后仍执行完整验证和 fresh Review，失败 raw 不作为成功成果发布。首版 Schema 不完整时，已经符合 Schema 的其他对象仍受保护；后续非法候选不能撤销该基线。

每个 Action 提交一次完整候选，错误也必须进入插件的正式 submit/Attempt 诊断链；宿主不得在同一 Action 内循环预检、重写到通过才提交。新的候选由插件绑定原失败、定位及保留要求后发行。

确定性 MATERIALIZE、VALIDATE、OFFICE、OFFICE_REFERENCE、RENDER、FINAL_VALIDATE 保存阶段、语义版本、步骤、失败次数和定位。成功输出先落盘，再绑定完成事件；resume 复用原成功字节。默认每步骤最多失败 2 次，用尽进入预算等待，可显式增加 `maxDeterministicAttempts`（2–10，省略为 2）。失败响应给出同阶段下一步；预算等待列出 `pendingSteps`，不清空候选、其他步骤或 checkpoint。外部文件或工具故障必须实际解决后复验，诊断记录不会代替验证成功。

Action 发放与 Envelope 复验按其冻结的 `maxHydrateTokens` 预留读取空间（不超过 run 的 hydrate reserve），避免为其他阶段较大的读取额度重复占用容量；阶段分组仍沿用原保守规划。原请求、预算、次数与完整 hydration 请求容量复核保持有效，尚未发行的修复满足原限额即可从同一 run 接续。
