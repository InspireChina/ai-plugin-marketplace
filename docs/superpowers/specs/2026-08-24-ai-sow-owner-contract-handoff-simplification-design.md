# AI SOW Owner Skill 合同、质量闭环与交接简化设计

状态：书面设计候选——合同简化、“新工作树、代码重写、资产迁移”、Skill 独立 seam、纯技术 runtime、纵向 Phase 0–4、实施期轻量 TDD 和 Superpowers 隔离方向已获用户批准；实施计划、freeze manifest 与代码实施尚未授权

日期：2026-08-24

目标插件版本：`0.1.0-beta.2`

目标 SOW 标准版本：`1.3`

## 1. 文档关系与实施门禁

本设计拟取代以下冻结方案中“下游重复诊断上游业务语义”和“对抗性本机文件系统竞态”相关要求：

- freeze manifest SHA-256：`037d08f7765e3b4aff73ebba92a59d139dfb8f0d4332c91a10a9b5909ca8f048`；
- `2026-08-23-ai-sow-unified-correctness-performance-optimization-design.md`；
- `2026-08-23-ai-sow-unified-correctness-performance-optimization-plan.md`；
- `2026-08-23-ai-sow-unified-correctness-performance-optimization-execution-appendix.md`；
- `2026-08-23-ai-sow-unified-correctness-performance-traceability-matrix.md`。

在本书面设计经用户复核、形成新的实施计划、独立审查和新 freeze manifest 之前：

1. 旧 Task 7 fix round 2 保持暂停，不继续修改或验证；
2. 不把当前 Task 7 中间态标记为通过；
3. 不恢复文件，也不删除现有快照、报告或审查证据；
4. 不开始 Task 8 或后续 E2E/performance 任务；
5. 不 commit、stage、push、merge、publish 或 release；
6. 新实施必须由用户显式引用新的 freeze manifest SHA-256 授权，旧 SHA 不授权本设计。
7. 现有脏工作树保持原状，仅作为待审计资产与历史证据来源；在新实施计划、独立审查、freeze
   manifest 和用户精确 SHA 授权完成前，不创建新实现工作树，也不从现有工作树迁移文件。

## 2. 背景与问题

AI SOW 的真实用户流程是持续迭代的专业评审，而不是一次性把资料送入流水线：

1. 用户显式调用一个 Skill 并提供资料；
2. 当前 Skill 的 Orchestrator Agent 只编排本阶段，由 Worker Agent 形成可读的专业评审材料；
3. Reviewer Agent 独立审查，Worker Agent 修复，直至 Reviewer Agent `PASS`；
4. Orchestrator Agent 把已通过审查的结果提交用户；
5. 用户在聊天中或问卷中提出补充和修正后，Worker Agent/Reviewer Agent 循环重新执行；
6. 用户明确批准后，Worker Agent 才编译候选 JSON；Validator Agent 运行确定性脚本，Reviewer Agent
   独立核对候选 JSON 是否忠实表达获批评审，随后才把同一份候选字节发布为稳定 JSON 和交接凭证；
7. Orchestrator Agent 报告当前 Skill 完成、推荐下一 Skill，然后停止；只有用户再次显式调用，下一 Skill 才验证 handoff 并消费。

此前方案正确加强了 Owner Skill 语义、receipt、工作簿和确定性，但在 Task 7 审查过程中逐步把普通用户模型扩大为同一权限主体主动实施目录替换、symlink race、EXDEV 遍历注入和 rename 源 inode 偷换的对抗模型。这些问题主要来自审查员依据宽泛安全条款构造的定向探针，不是原始 E2E 用户流程暴露的主要失败。

同时，`generate-sow` 和部分下游 validator 为了“最终防御”重复实现上游 Owner Skill 的 CARRY_FORWARD、AC→Task、Decision、estimate readiness 等业务规则。重复实现会形成第二套业务语义：上游 Owner Skill 修改规则时，下游防御可能产生 false pass 或 false block，代码和测试复杂度随之扩大。

当前中间实现还把 receipt、hash、项目路径、validation report 和发布操作分别复制到多个
Skill 的大型入口函数中。即使逐项删除已否决的边缘场景，维护者和后续 Agent 仍需先理解旧实现、
识别可保留片段，再证明没有残留第二套语义。继续在该结构上裁剪会把历史探索成本长期留在
代码和测试表面，因此本设计不把现有中间实现作为后续实现基线。

本设计把数据质量责任收回唯一 Owner Skill，并用明确的生成前合同、相互独立的 Worker Agent、
Reviewer Agent、Validator Agent、用户批准、确定性 validator 脚本和内容寻址 handoff receipt
形成闭环。

## 3. 核心决策

采用以下原则：

> 生成前把本阶段输出合同讲清楚，生成后由 Owner Skill 保证质量；下游只验证交接是否有效，并验证自己创建的引用，不重复诊断上游内部语义。

四类质量目标及责任如下：

| 质量目标 | 主责任 | 确定性边界 |
| --- | --- | --- |
| 用户提供的输入足够 | Worker Agent、用户 | 关键输入缺失时形成问题、Uncertainty 或 `BLOCKED`，不猜测真实决定 |
| 产出符合 Schema | Validator Agent 与确定性脚本 | Schema、枚举、结构、Owner Skill-local 关系和 machine token |
| 产出足以支持下一步 | Validator Agent；下游 handoff matcher | Owner Skill 输出完整性、receipt/hash/contract；当前 Skill 自己创建的上游引用 |
| 产出合理且完备 | Reviewer Agent、用户 | 专业判断、证据充分性、范围遗漏、结论合理性和最终批准 |

不增加 JSONC、通用业务 preflight、跨 Skill 业务 Schema、共享业务编译器、第七份稳定业务 JSON或自动审批系统。

实现采用以下迁移原则：

> 保留已经确认的领域知识和可复现资产，不保留中间实现的代码形态；从干净仓库基线重新建立
> 小接口的技术模块、Owner Skill-local validator 和面向用户行为的测试。

这是 clean-slate implementation，不是 clean-slate requirements。现有工作树中的 Schema 语义、
canonical fixture、review template、Owner Skill 规则、工作簿资产和验证证据必须先进入显式
迁移清单，才允许带入新工作树；未列入清单的实现文件和测试默认不迁移。

本设计中的“Skill 独立”精确定义为：每个 Skill 独立拥有领域合同、Schema、fixture、review、
业务规则、执行顺序、diagnostics 和稳定数据所有权；每次用户调用只运行当前 Skill 并在完成后
停止。物理独立安装单元是整个 `plugins/ai-sow/` 插件，不要求单独复制一个 Skill 目录后脱离
插件 runtime 运行。共享插件技术 module 不得改变任何 Skill 的领域含义或阶段所有权。

## 4. 目标工作流

### 4.1 统一角色与术语

全文只使用以下四种 Agent 角色：

| 角色 | 职责 | 禁止事项 |
| --- | --- | --- |
| Orchestrator Agent | 当前 Skill 的用户接口与流程负责人；说明本阶段合同，调度其他 Agent，在不改变语义的前提下连同上下文传递用户反馈，检查机械门禁状态，汇报结果 | 不制作、修复或审查专业成果；不替 Validator Agent 解释或放宽失败；不自动调用下一 Skill；不在其他 Agent 不可用时兼任其角色 |
| Worker Agent | 独立于 Orchestrator Agent，读取本 Skill 合同与获准输入，完成专业分析、设计、拆分、生成、用户反馈修改和 Reviewer Agent findings 修复 | 不审查自己的专业成果；不替用户批准；不修改其他 Owner Skill 的稳定数据；不修改已安装插件的合同、代码或 bundled assets |
| Reviewer Agent | 独立于 Orchestrator Agent 和 Worker Agent，审查当前完整版本；Worker Agent 修复后重新审查，直至返回 `PASS` | 不直接修改成果；不替用户批准；不执行确定性 validator 的职责 |
| Validator Agent | 独立于 Orchestrator Agent、Worker Agent 和 Reviewer Agent，运行当前 Skill 自己的确定性脚本，保存并报告原始 outcome、diagnostics、hash 和 receipt | 不重解释业务合理性；不放宽或覆盖脚本失败；不修改成果 |

`Orchestrator Agent` 只拥有本次 Skill 的流程状态；`Owner Skill` 表示领域和稳定数据所有权，例如
`generate-design` 是 TECHNICAL requirements 的 Owner Skill，它不是 Agent 角色。机器字段、
receipt algorithm 和既有 `owner` token 保持合同原值。

Worker Agent、Reviewer Agent 和 Validator Agent 必须由彼此不同、且不同于 Orchestrator Agent
的独立 Agent 调用承担；它们可以顺序运行，不要求并行。运行环境无法创建所需独立 Agent、
无法维持角色隔离或无法让对应 Agent 使用必要工具时，Orchestrator Agent 必须返回 `BLOCKED`
并停止，不得自行兼任或把某一角色的结论伪装成另一角色的结果。`setup` 不使用 Reviewer
Agent，但其 Worker Agent 与 Validator Agent 仍必须相互独立。

Orchestrator Agent 是当前 Skill 唯一允许派发 Agent 的角色。Worker Agent、Reviewer Agent 和
Validator Agent 都是叶子 Agent，不得派发 helper、reviewer、validator 或任何其他 subagent；
Agent 树从当前 session 的 Orchestrator Agent 向下最大深度为一。单次 Skill invocation 中，
Orchestrator Agent 对每种需要的角色最多创建一个 Agent，并通过 follow-up 复用它完成 findings
修复、复审、候选编译和重跑；不得为每个 review round 创建新的 Worker/Reviewer/Validator。
如果平台已回收角色 Agent，只能根据项目内 artifact 和该角色的最小输入包重建，不得把完整
session 历史复制给新 Agent。跨 session 调用会建立新的 Orchestrator 和角色 Agent，不复用上一个
session 的私有上下文。

在面向最终用户的 Skill 运行中，Worker Agent 只写当前 Skill 合同允许的项目内 work、review、
questionnaire、候选 data、project metadata/template 或 output；具体写集合由各 Skill 声明。
任何 Worker Agent 都不得修改已安装插件的 `SKILL.md`、Schema、fixture、reference、script、
bundled template 或其他发布资产。若问题属于插件合同、validator、generator 或 bundled asset
缺陷，Orchestrator Agent 报告插件实现 blocker 并停止，转入单独的插件维护任务。

四种 Agent 是统一词汇，但按 Skill 职责使用：

- `setup` 使用 Orchestrator Agent、Worker Agent、Validator Agent；没有专业评审材料，不调用 Reviewer Agent；
- 五个稳定业务数据 Owner Skill 使用全部四种 Agent；
- `generate-sow` 使用全部四种 Agent：Reviewer Agent 只审查稳定数据到工作簿/package 的投影忠实度、交付包完整性、视觉和可读性，不重新判断上游业务语义。

七个 Skill 不强行使用同一套流程，而是按职责分成三类：

| 类型 | Skill | 工作流重点 |
| --- | --- | --- |
| 环境与项目初始化 | `setup` | Orchestrator Agent 编排；Worker Agent 检查并补齐 Python/uv、准备依赖和初始化；Validator Agent 验证项目外壳 |
| 稳定业务数据 Owner Skill | `analyze-requirement`、`analyze-as-is`、`generate-design`、`generate-story`、`generate-task` | Worker Agent 完成专业工作，Reviewer Agent 独立审查并复审，Validator Agent 在用户批准后校验/发布 handoff |
| 最终投影 | `generate-sow` | Worker Agent 投影 XLSX/package，Validator Agent 确定性验证，Reviewer Agent 独立检查投影忠实度与最终交付质量，用户复核后按问题归属处理 |

五个产生稳定业务数据的 Owner Skill 使用相同的阶段顺序：

```text
用户显式调用当前 Skill
→ Orchestrator Agent 启动且只启动当前 Skill
→ Worker Agent 读取本 Skill Schema、canonical fixture、review template 与必要专项规则
→ Worker Agent 评估输入并向 Orchestrator Agent 返回输出合同、已具备输入、缺口和阻塞问题
→ Orchestrator Agent 向用户说明并收集必要输入
→ Worker Agent 完成本阶段专业工作与 review draft
→ Reviewer Agent 检查合理性与完备性
→ 有 findings：Worker Agent 修复 → Reviewer Agent 复审
→ 循环直至 Reviewer Agent PASS
→ Orchestrator Agent 将已通过 Reviewer Agent 的结果提交用户 review
→ 用户批准？
   ├─ 否：Orchestrator Agent 将用户意见连同必要上下文、不改变语义地交给 Worker Agent
   │      → Worker Agent 针对性调整
   │      → Reviewer Agent 审查，Worker 修复，Reviewer 复审至 PASS
   │      → Orchestrator Agent 再次提交用户 review
   └─ 是：Worker Agent 在当前 Skill work 目录编译候选 JSON，不写稳定 data 路径
→ Validator Agent 对候选 JSON 运行 Owner Skill 的确定性 validator
→ Reviewer Agent 核对候选 JSON 是否忠实表达用户批准的 review artifact
→ 当前成果可修复：Worker Agent 修复 → Validator Agent 重跑 → Reviewer Agent 复核
→ 修复改变获批专业结论：回到完整 Reviewer Agent 审查和用户批准
→ Validator PASS 且 Reviewer Agent 确认编译忠实
→ Owner validator 原子发布同一份候选字节为稳定 JSON，并发布 handoff receipt
→ Orchestrator Agent 汇报当前 Skill 完成，推荐下一 Skill 及所需输入
→ STOP；等待用户下一次显式调用
```

### 4.2 生成前合同说明

Worker Agent 在开始完整生成前评估输入，Orchestrator Agent 只把结果以简洁中文向用户说明：

- 本阶段会形成哪些评审结论和稳定输出；
- 当前将读取哪些输入；
- 哪些关键输入已经充分；
- 哪些缺口会改变范围、责任、设计、交付对象或估算；
- 需要用户回答的问题；
- 哪些内容在缺失时必须保持 `BLOCKED`。

该说明存在于聊天或 Owner Skill work 记录，不新增稳定 JSON，也不引入通用 preflight 文件格式。

### 4.3 用户评审循环

评审材料是专业成果，不是 Schema 字段逐项填空。第一版评审材料必须先由 Worker Agent 完成
专业工作，再经过 Reviewer Agent 审查；Worker Agent 修复 findings，Reviewer Agent 对修复后
的完整版本复审至 `PASS`，用户才看到可评审版本。用户可以在聊天或 Owner Skill 问卷中修正；
用户批准前不发布稳定 JSON。

用户每次提出修改后，Orchestrator Agent 将意见连同必要上下文、不改变语义地交给 Worker Agent；Worker Agent 调整结果，
Reviewer Agent 对更新后的完整评审稿重新审查，Worker Agent/Reviewer Agent 循环直至 `PASS`，之后
Orchestrator Agent 才能把下一版交给用户。每一次面向用户的提交都经过同一质量闸，不以“变化是否实质”
作为跳过审查的理由。

稳定 JSON 和 receipt 首次发布后，若任一业务输入、评审结论或稳定输出发生实质变化，原批准和
receipt 失效，必须返回对应 Owner Skill 重新评审。首次从获批 review artifact 编译候选 JSON
不视为批准后变更，但候选 JSON 必须经过 Validator Agent 的机械校验和 Reviewer Agent 的编译
忠实度核对。

Reviewer Agent 和 Validator Agent 的失败不能一律交给 Worker Agent 无限循环。Orchestrator
Agent 只按来源路由，不自行解释专业或机械结论：

- 当前 Skill 成果可修复：Worker Agent 修复，原 Reviewer/Validator 门禁重跑；
- 缺少用户事实、选择或批准：Orchestrator Agent 向用户提出具体问题，同一 Skill 等待答复；
- 上游 Owner Skill 的事实、批准或 handoff 有问题：报告该 Owner Skill 并停止；
- 环境、权限、合同、插件实现或独立 Agent 能力不可用：返回带证据的 `BLOCKED` 并停止。

Reviewer Agent 在 findings 中标明上述归属；Validator Agent 保留脚本原始 outcome 和 diagnostics，
由其确定性错误码决定路由。只有明确属于当前成果的 finding 或 diagnostic 才允许进入 Worker
Agent 修复循环。

用户反馈按内容归属处理，而不是一律由当前 Skill 就地修改：

- 属于当前 Owner Skill 的问题，由 Worker Agent 更新 review draft，经 Reviewer Agent 审查至
  `PASS` 后，再由 Orchestrator Agent 提交用户批准；
- 属于上游事实或结论的问题，当前 Orchestrator Agent 报告唯一上游 Owner Skill、原被阻塞
  Skill 和必须经过的顺序影响复核链，然后停止；不得自动调用上游或任何后续 Skill；
- 仅属于工作簿投影、格式或 package 的问题，由 `generate-sow` 修正并重新生成，不改写任何上游稳定 JSON；
- 用户没有要求改变的已批准结论保持稳定，避免每轮反馈导致全链路无关重做。

#### 上游修正后的顺序影响复核

上游修正不能从 Owner Skill 直接跳回原被阻塞 Skill。稳定业务依赖顺序固定为：

```text
analyze-requirement
→ analyze-as-is
→ generate-design
→ generate-story
→ generate-task
→ generate-sow
```

若 `generate-task` 发现问题属于 `generate-design`，返回链是
`generate-design → generate-story → generate-task`；Requirement、As-Is 没有变化，不重跑。
若 `generate-sow` 发现同一问题，返回链继续到 `generate-sow`。任何已经存在但位于返回目标
之后的产物会因 hash 失效，只有用户以后显式调用对应 Skill 时才重新生成。

返回链按以下规则逐个执行：

1. 当前 Orchestrator Agent 在聊天或当前 work 记录中报告问题依据、唯一 Owner Skill、原被阻塞
   Skill、固定返回链和下一次应显式调用的 Skill，然后停止；不新增稳定 route JSON；
2. 用户显式调用 Owner Skill；该 Skill 完成修正、Reviewer/用户批准、候选校验、编译忠实度
   核对和新 receipt 发布后停止，并推荐它的直接下游；
3. 用户逐个显式调用返回链中的下游 Skill。每个下游先验证新上游 receipt，再由 Worker Agent
   对当前已批准 review、稳定 JSON 和更新后的上游输入进行影响复核；
4. 若专业结论不受影响，Reviewer Agent 独立确认 `Impact: NO_CHANGE`；Orchestrator Agent 将
   简洁影响说明交给用户确认，稳定 JSON 字节保持不变，Owner validator 仅发布绑定新上游
   input hash、当前 review hash 和原 output hash 的新 receipt；
5. 若专业结论受影响，当前 Skill 执行完整的 Worker 修改、Reviewer 审查、用户批准、候选 JSON
   校验、编译忠实度核对和发布流程；
6. 每个 Skill 完成后停止并推荐返回链中的下一 Skill。只有链上所有直接依赖 receipt 都已更新，
   原被阻塞 Skill 才能恢复；若影响复核发现问题实际属于更早 Owner Skill，则重新计算返回链并停止。

返回链中的 Skill 被显式调用时，其直接上游新 receipt 必须有效；当前 Skill 自己的旧 receipt 因
绑定旧上游而 stale 是预期的影响复核触发条件，不得把它误报成上游 Owner 修复失败或再次路由
回刚刚完成的 Owner Skill。

因此后续阶段必须逐个显式调用，但不等于全部从头重做。`NO_CHANGE` 路径复用稳定 JSON，
只重新完成影响说明、独立 Reviewer 确认、用户确认和 receipt 绑定。设计不增加字段级依赖图或
自动级联执行器；Skill 级顺序复核是可解释且足够简单的边界。

### 4.4 setup：运行环境准备与项目初始化

`setup` 不是业务数据 Owner Skill，不使用专业分析、用户批准、稳定 JSON 和 handoff receipt
循环，也没有需要 Reviewer Agent 判断的专业成果。Orchestrator Agent 只编排当前 setup；Worker
Agent 执行环境准备和初始化；Validator Agent 运行确定性验证。它的主职责只有一项：

> 在 AI SOW 插件已经安装并加载的前提下，检查并补齐 Python 与 uv，准备或复用插件锁定的
> Python 依赖环境，在用户指定的项目根目录初始化一个可运行、可继续后续 Skill 的 AI SOW
> 项目，并验证项目设置与 XLSX 模板可用。

这里的“环境配置与安装”按以下边界理解：

| 层次 | setup 的责任 |
| --- | --- |
| Codex 插件安装 | 前置条件；`setup` 被调用时插件已经安装。`setup` 不安装、升级或重新安装插件。 |
| Python 与 uv | Worker Agent 检查版本；缺失或不兼容时按当前操作系统使用受支持方式安装并复核，优先用户级、无管理员权限的安装。平台、网络或权限阻止安装时才报告确切 blocker。 |
| 插件 Python 依赖 | 通过插件自己的 `uv.lock` 准备或复用隔离的锁定运行环境；不向用户项目写入依赖，也不修改 lockfile。 |
| AI SOW 项目 | 写入四字段 `.ai-sow/project.json`，复制权威 `sow-template.xlsx`，创建后续 Skill 所需的受管父目录。 |
| XLSX 能力 | 验证锁定依赖可导入，并对插件模板执行打开、保存、重新读取的 round-trip。 |

采用“Orchestrator Agent 编排 + Worker Agent 执行 + Validator Agent 验证 + 最小确定性脚本”的边界：

- Orchestrator Agent 通过 `SKILL.md` 调度 Worker Agent 识别操作系统、检查/安装 uv、通过 uv 检查或安装所需 Python、准备锁定依赖环境并收集项目 ID/名称；
- `scripts/setup.py` 只负责 Project Schema 校验、精确写入四字段 `project.json`、创建固定目录、复制模板和 XLSX round-trip；
- Validator Agent 运行最小脚本的验证路径并报告原始结果，不重解释或放宽失败；
- 不新增 Shell/PowerShell bootstrap 脚本，也不让 Python 脚本承担“Python 尚未安装”时的自举；
- 需要判断平台和安装方式的步骤交给 Worker Agent；需要字节、字段和目录结果可重复的机械步骤交给脚本。

正常初始化流程固定为：

```text
用户显式调用 setup
→ Orchestrator Agent 启动且只启动 setup
→ Worker Agent 确认已加载插件并解析 plugin-root 与用户 project-root
→ Worker Agent 检查 uv；缺失或不兼容时安装并复核
→ Worker Agent 检查所需 Python；缺失或不兼容时通过 uv 安装并复核
→ 检查插件 lockfile
→ 由 uv 准备或复用隔离的锁定依赖环境
→ 获取并回显 projectId 与 name
→ 检查受管目标不存在身份或内容冲突
→ Worker Agent 调用最小 setup.py 创建 project.json、项目目录与模板副本
→ Validator Agent 校验 Project Schema、目录、依赖和 bundled template XLSX round-trip
→ Orchestrator Agent 报告项目就绪，推荐 analyze-requirement 及所需输入
→ STOP；等待用户显式调用 analyze-requirement
```

`setup` 不提供 `repair`。目标已经是完整、合法的 AI SOW 项目时只复读并报告就绪，不修改；
目标存在不完整或冲突的受管内容时返回 `BLOCKED`，不补目录、不覆盖模板、不修改项目身份，
也不触碰业务 data/review/validation/output。

`setup` 只负责创建项目模板的初始副本。初始化完成后，`.ai-sow/templates/sow-template.xlsx`
是项目级计算与投影输入；用户可在明确授权后要求 `generate-sow` Worker Agent 调整该项目模板，
这不属于 setup repair，也不得反向修改 bundled template。任何项目模板变化都会使既有 Task
估算校验和 SOW package 失效，相关 Skill 必须在用户显式调用后按 handoff/hash 门禁重跑。

版本迁移也不进入正常 `setup` 流程。本次 beta.1→beta.2 如需更新项目 metadata，使用独立、
显式且可单独验证的一次性升级操作；它不得由初始化静默触发，也不把 `setup` 扩展成
通用迁移框架。

### 4.5 generate-sow：投影、复核与反馈路由

`generate-sow` 不重复五个业务 Owner Skill 的专业分析，也不使用“批准后编译稳定业务
JSON”的流程。它使用全部四种 Agent，并按以下顺序工作：

```text
用户显式调用 generate-sow
→ Orchestrator Agent 启动且只启动 generate-sow
→ Validator Agent 验证五个 Owner Skill handoff 与六份稳定 JSON
→ Worker Agent 读取项目模板并确定性生成、复读 XLSX、manifest 和 package
→ Validator Agent 运行结构、公式、引用、样式、文本安全和 package 检查
→ Reviewer Agent 独立检查投影忠实度、package 完整性、视觉和可读性
→ 有 findings：Worker Agent 修复 → Validator Agent 重跑 → Reviewer Agent 复审
→ 循环直至 Validator PASS 且 Reviewer PASS
→ Orchestrator Agent 交给 BA、TL、PM 或用户最终复核
→ 用户提出投影问题：Worker Agent 修复 → Validator Agent/Reviewer Agent 重跑至 PASS → Orchestrator Agent 再提交
→ 用户确认最终 package 可交付
→ Orchestrator Agent 报告 generate-sow 完成
→ STOP
```

用户指出业务范围、现状、设计、Story、AC、Task 或估算输入问题时，Orchestrator Agent 只报告对应
Owner Skill 并停止，不得自动调用上游 Skill。用户显式调用该 Owner Skill，重新完成评审、
批准、validator 和 receipt 后，必须按 4.3 的固定依赖顺序逐个显式调用其直接下游；每个阶段
先走影响复核，直至重新回到 `generate-sow`。不得从较早 Owner Skill 直接跳回 `generate-sow`。
用户指出字段
落位、格式、公式原型、样式、可读性或 package 问题时，当前 `generate-sow` Worker Agent 只在
现有稳定数据、当前项目模板和生成合同允许的范围内重新生成，不直接手改最终 XLSX。用户明确
要求调整项目模板时，可以修改项目自己的 `.ai-sow/templates/sow-template.xlsx` 并重新生成；
bundled template、已安装 generator 或其他插件发布文件不得在 Skill 运行中被修改。若修正必须
改变 generator、bundled template 或合同，Orchestrator Agent 报告插件实现 blocker 并停止，
由单独的插件维护任务处理。

### 4.6 七个 Skill 的实际用户循环

| Skill | 当前 Skill 内的角色协作 | 完成与停止条件 |
| --- | --- | --- |
| `setup` | Worker Agent 补齐环境并初始化；Validator Agent 验证；Orchestrator Agent 汇报 | 验证通过后推荐 `analyze-requirement` 并停止，不自动推进 |
| `analyze-requirement` | Worker Agent 分析需求；Reviewer Agent 审查至 PASS；用户修改循环；批准后编译候选，Validator Agent 校验，Reviewer Agent 核对编译忠实度 | receipt 发布后推荐 `analyze-as-is` 并停止，不自动推进 |
| `analyze-as-is` | Worker Agent 调查现状；Reviewer Agent 审查至 PASS；用户修改循环；批准后编译候选，Validator Agent 校验，Reviewer Agent 核对编译忠实度 | receipt 发布后推荐 `generate-design` 并停止，不自动推进 |
| `generate-design` | Worker Agent 完成目标设计、Scope、技术需求、HLD 和 Go-live；Reviewer Agent 审查至 PASS；批准后编译候选，Validator Agent 校验，Reviewer Agent 核对编译忠实度 | 两个稳定 JSON 与 receipt 发布后推荐 `generate-story` 并停止，不自动推进 |
| `generate-story` | Worker Agent 形成 Gap、Story、AC、Integration 与 Assumption/Risk；Reviewer Agent 审查至 PASS；批准后编译候选，Validator Agent 校验，Reviewer Agent 核对编译忠实度 | receipt 发布后推荐 `generate-task` 并停止，不自动推进 |
| `generate-task` | Worker Agent 拆分 Task、基础单元、工作模式、复杂度和依据；Reviewer Agent 审查至 PASS；批准后编译候选，Validator Agent 校验，Reviewer Agent 核对编译忠实度 | receipt 发布后推荐 `generate-sow` 及 PM 补充项并停止，不自动推进 |
| `generate-sow` | Worker Agent 投影；Validator Agent 确定性检查；Reviewer Agent 独立检查最终质量；用户反馈循环 | 用户确认 package 后停止；若是上游业务问题，报告对应 Owner Skill、顺序返回链和下一次调用后立即停止 |

因此五个业务 Owner Skill 的真实主循环是“用户提供资料 → Worker Agent 完成专业工作 →
Reviewer Agent 审查 → Worker 修复 → Reviewer 复审至 PASS → Orchestrator Agent 提交用户 → 用户
反馈 → Worker Agent/Reviewer Agent 再循环”，直到用户明确批准。Orchestrator Agent 不制作、修复或审查专业
成果。批准后只增加候选 JSON 的机械校验和编译忠实度核对，不重新设计已批准内容。每个 Skill
只完成自己的工作，结束时最多推荐下一 Skill，并始终停止等待用户显式调用。

产品合同要求下一 Skill 必须由用户显式调用，但不强迫用户一定新建 Codex 任务/session。第 14 节
的 release E2E 刻意采用更严格的跨 session 方式，证明流程在没有上一阶段聊天记忆时仍能完成
用户交接；正常用户仍可在同一任务中显式开始下一 Skill。

## 5. Owner Skill 合同包

五个稳定数据 Owner Skill 使用自包含合同包：

```text
skills/<owner>/
├── SKILL.md
├── contracts/
│   └── <output>.schema.json
├── fixtures/
│   └── <output>.valid.json
├── references/
│   ├── review-template.md
│   └── <必要的专项规则>.md
├── scripts/
│   └── validate.py
└── tests/
```

“自包含合同包”表示理解或修改一个 Skill 的业务行为只需读取该 Skill 目录及明确声明的插件
runtime interface；不表示该 Skill 是单独安装包。Skill 不得 import、读取或执行其他 Skill 的
Schema、fixture、reference、test、asset 或 script。项目中的上游 stable data/receipt 是运行时
handoff 输入，不是对上游 Skill 实现目录的依赖。

`setup` 保留锁定运行环境准备与自检、项目身份、目录和项目模板初始化合同；
`generate-sow` 保留 manifest、工作簿和 package 合同。它们不承担专业业务分析，也不进入
五个业务 Owner Skill 的 review/receipt 循环。

### 5.1 重写后的代码结构

新实现不从当前大型 `validate.py` 或 `generate_sow.py` 中抽取一层 wrapper，而是从干净基线
按以下 seam 重新建立代码：

| Module | 小接口承担的完整行为 | 不得进入的内容 |
| --- | --- | --- |
| `runtime/handoff.py` | canonical bytes/hash、receipt shape、match、stale、`NO_CHANGE` rebind 和成功发布 | 任何 Requirement、As-Is、Design、Story、Task 业务语义 |
| `runtime/project_io.py` | 项目相对路径、命令开始时 symlink/reparse 拒绝、普通原子写入和 no-overwrite | 同权限攻击者竞态、inode 身份协议、EXDEV tree copy |
| `skills/generate-design/scripts/review_gates.py` | `generate-design` 自己的 HLD/Go-live review 解析、覆盖和引用门禁 | 其他 Owner Skill 业务规则；供下游重复调用的公共 interface |
| 各 Skill `scripts/validate.py` | 本 Skill 执行顺序、Schema、Owner-local 语义、自己创建的引用、diagnostics 路由和对共享技术 module 的显式调用 | 复制 receipt/path/report 实现；重放上游业务 validator |
| `generate-sow` generator/workbook | receipt-only 输入门禁、模板投影、复读验证和 package | 上游业务诊断或通用工作流状态机 |

依赖方向只能是：

```text
skills/<owner>/scripts/validate.py
  → runtime/handoff.py
  → runtime/project_io.py

skills/generate-design/scripts/validate.py
  → skills/generate-design/scripts/review_gates.py

runtime/*
  ✕ 不 import skills/*
  ✕ 不读取任何 Skill Schema/fixture/reference/test/asset/script
  ✕ 不硬编码 Owner 名称、Owner 路径、业务 ID、业务字段或 Schema ID
```

共享 runtime 只统一技术机制，不共享业务 Schema、业务规则、业务编译或 Owner 工作流。不得新增
`owner_pipeline.py`、通用 Owner runner、配置驱动业务引擎或其他负责 review→candidate→publish
完整顺序的共享 module。`runtime/handoff.py` 只对调用方显式传入的 path/hash/contract descriptor
执行通用匹配和发布原语；哪个输入必需、调用顺序、何时允许 publish、失败归属和业务 diagnostics
仍由当前 Skill 决定。少量清晰的 Skill-local 编排重复是有意取舍，不再为消除这些行引入框架。

公共 runtime 不保留任何共享领域语义例外。现有 `runtime/review_gates.py` 是旧方案为了让
`generate-design`、`generate-story` 和 `generate-sow` 重复执行同一 HLD/Go-live 门禁而形成的
实现，不迁移到新工作树。仍然有效的 HLD/Go-live 规则由 `generate-design` 的测试从合同重新
建立在 Skill-local `scripts/review_gates.py` 中，只由 `generate-design` validator 调用。
`generate-story` 和 `generate-sow` 只匹配该 Owner 的 receipt，并验证自己创建的引用或投影，
不得调用 HLD/Go-live 上游 validator。

根 `AGENTS.md` 的现行规则需要随实现精确更新为：禁止跨 Skill import 或读取其他 Skill 资产；
只允许 Skill 调用 `runtime/handoff.py` 和 `runtime/project_io.py` 两个插件级纯技术 module，
不允许新增共享业务 runtime。调用方和测试只面向这些 module 的小 interface，不依赖内部步骤、
临时文件名、syscall 顺序或故障注入钩子。

当前八份 Schema 保持唯一权威：

| 合同归属 Skill | Schema |
| --- | --- |
| setup | `skills/setup/contracts/project.schema.json` |
| analyze-requirement | `skills/analyze-requirement/contracts/source-requirements.schema.json` |
| analyze-as-is | `skills/analyze-as-is/contracts/asis.schema.json` |
| generate-design | `skills/generate-design/contracts/design.schema.json` |
| generate-design | `skills/generate-design/contracts/technical-requirements.schema.json` |
| generate-story | `skills/generate-story/contracts/delivery.schema.json` |
| generate-task | `skills/generate-task/contracts/estimate.schema.json` |
| generate-sow | `skills/generate-sow/contracts/manifest.schema.json` |

## 6. Schema 说明优化

八份 Schema 增加面向生成者的中文 `description`，但不复制机械约束。

### 6.1 必须说明的字段

- 每个稳定输出的顶级字段；
- 每个稳定实体的业务字段；
- 直接承载业务关系、结论、来源、自由文本或生成条件的嵌套字段。

每个说明按实际需要覆盖：

- 字段的业务含义；
- 结论或数据来源；
- 引用的实体；
- 自由文本必须表达的内容；
- 不得混入的内容；
- 选填字段何时生成、何时省略；
- 与其他字段的语义关系。

`type`、`enum`、`pattern`、`required`、`minItems` 等已由 Schema 表达的机械约束不在说明中重复。纯 helper scalar/array/object alias 可以豁免；一旦 `$defs` 中的 property 直接出现在稳定实体上，该 property 仍需说明。

只增加 `description` 不改变稳定 JSON 结构，也不单独升级对应 Schema `$id`。当前
Design、Technical Requirements、Delivery、Estimate 和 manifest 保持 `:0.2`；Project、
Source Requirements 和 As-Is 保持 `:0.1`。receipt contract version 与这些 Schema `$id`
独立。

### 6.2 说明完整性测试

仓库测试遍历八份 Schema，要求：

- 所有顶级稳定字段具有非空 `description`；
- 所有稳定实体业务字段具有非空 `description`；
- 中文自由文本说明包含中文字符；
- machine token、字段名、枚举、ID、路径和公式保持原值；
- helper 豁免使用显式 allowlist，不以路径模糊跳过。

## 7. Canonical fixture

canonical fixture 从“validator 能通过的最小数据”升级为 Worker Agent 可以参考的权威合法示例。

要求：

- 使用真实、具体但完全模拟的简体中文自由文本；
- 展示完整实体关系和稳定 ID；
- 覆盖常见选填字段及关键条件分支；
- 不使用 `N/A`、占位符或空泛理由；
- 不包含客户内容、凭据、私有仓库信息或本机路径；
- 每个 Skill 只读取自己的 fixture；
- 错误测试从合法 fixture 施加单点 mutation，不维护大量 invalid fixture。

fixture 组合如下：

| Skill | Canonical fixture |
| --- | --- |
| setup | 四字段项目数据与最小项目外壳 |
| analyze-requirement | 来源、normalized item、Epic、Feature 和常见选填字段 |
| analyze-as-is | Greenfield 与 Brownfield 两个示例 |
| generate-design | Design、`SOURCE_INPUT` TECHNICAL requirements、`DESIGN_DERIVED` TECHNICAL requirements |
| generate-story | 普通交付、上线、迁移、Integration、Assumption/Risk |
| generate-task | `新建`、`调整`、`接入复用`、S/M/L 和 Integration Task |
| generate-sow | receipt 完整的端到端项目 fixture |

每个稳定数据 fixture 必须通过自己的 Schema 和 Owner Skill validator；setup 的项目数据
fixture 只验证 Project Schema 与最小项目外壳。Python/uv 检查与缺失安装、锁定环境自检、
正常初始化和模板 round-trip 由 setup 操作流程测试验证，不把环境行为归给 fixture。setup
不维护 repair fixture 或 repair 测试。除 As-Is 的两个业务模式外，默认
维护一个主 fixture；只有无法在同一示例中清楚表达且确实影响生成方式的变体才新增 fixture。

## 8. Review template

五个 Owner Skill 新增 `references/review-template.md`。模板保证批准前已经形成编译稳定 JSON 所需的非机械专业结论，但不成为结构化草稿或新的数据权威。

同一模板支持上游变化后的简洁影响复核。首次执行不需要影响复核段；重新绑定上游时增加：

- 发生变化的直接上游 Owner Skill；
- 旧、新上游 receipt/input hash；
- `Impact: NO_CHANGE` 或 `Impact: CHANGED`；
- 判断理由和受影响或确认不受影响的稳定 ID。

`NO_CHANGE` 只表示当前 Skill 的专业结论和稳定 JSON 无需变化，不表示可以跳过 Reviewer Agent、
用户确认或 receipt 更新。确定性 validator 检查 hash 与 output bytes 复用；是否确实无语义影响
仍由 Reviewer Agent 和用户判断。

| Owner Skill | Review template 必须覆盖 |
| --- | --- |
| analyze-requirement | 来源、归一化、Epic/Feature、范围边界、问卷状态、稳定 ID 映射、输入充分性 |
| analyze-as-is | 调查范围、九个 Topic、Item、Commitment、Effective Start、Coverage、Uncertainty、Evidence、问卷记录 |
| generate-design | 目标设计、Architecture Delta、Decision、Scope、TECHNICAL requirements、HLD、十项 Go-live 矩阵 |
| generate-story | Feature→Gap→Story、AC、Integration、Assumption/Risk、问卷消费、十项上线映射 |
| generate-task | Story→Task、基础单元、工作模式、复杂度、现状依据、Integration 一对一、遗漏/重叠/排除理由 |

确定性 validator 只检查可机械证明的模板合同：

- 必需章节存在；
- 固定 machine declaration 精确；
- ID 清单和映射闭合；
- 问卷终态和批准状态有效；
- 评审与稳定输出中的 Owner Skill-local ID 集合一致。

确定性 validator 不通过关键词或自然语言推断评审叙述是否专业、充分或合理。这部分由
Reviewer Agent 和用户负责。

## 9. Reviewer Agent

合理性与完备性通过独立于 Worker Agent 的 Reviewer Agent 保证，不塞入确定性脚本，也不由
Orchestrator Agent 代审。

### 9.1 调用时机

- 完整 review draft 第一次提交给用户前必须由 Reviewer Agent 审查；
- 用户每次提出修改后，更新后的完整 review draft 在再次提交用户前必须重新审查；
- 每次 Reviewer Agent 返回 findings 后，Worker Agent 必须逐项修复或明确处置，再把修复后的
  完整版本交给 Reviewer Agent 复审；只有 Reviewer Agent 返回 `PASS` 才能提交用户；
- 用户批准后，候选 JSON 必须由 Reviewer Agent 对照获批 review artifact 做一次编译忠实度
  核对；该核对不重新设计业务内容，但必须发现 Schema 合法却遗漏、曲解或改写获批结论的编译；
- 不因修改被判断为文字润色、错别字、排版或“非实质变化”而跳过提交前 review。

### 9.2 审查范围

Reviewer Agent 的默认输入仅包括当前 Owner Skill 的 review template/rubric、必要专项规则、当前
完整 review draft，以及支撑结论所必需的已登记输入和项目内 evidence/upstream artifact 指针。
Reviewer Agent 自行读取这些指针，不接收 Worker Agent 的完整提示词、聊天或内部推理。
canonical fixture 默认只供 Worker Agent 学习输出合同；Reviewer Agent 只有在合同表达确有歧义时
才按需读取。Schema 默认由 Validator Agent 的脚本负责；Reviewer Agent 在核对字段业务含义或
批准后的编译忠实度时只读取相关 Schema 片段，不重复执行完整 Schema 校验。Reviewer Agent 检查：

- 输入与证据是否足以支持结论；
- 是否遗漏范围、关系、异常路径、责任边界或验收结果；
- 结论是否相互矛盾；
- 是否存在未经批准的猜测；
- 专业分解是否合理且完整；
- 未决问题是否被正确保留为问题、Uncertainty、Assumption 或 Risk。

Reviewer Agent 返回 `PASS`，或返回带归属的 findings：当前成果可由 Worker Agent 修复、需要
用户输入、需要返回上游 Owner Skill，或存在无法在当前运行中处理的 blocker。Reviewer Agent
不替用户批准、不直接发布稳定 JSON、不修改任何 Owner Skill 数据。Worker Agent 只负责修正
明确归属当前成果的问题；Reviewer Agent 负责对修复后的当前完整稿复审。Orchestrator Agent
只检查当前版本已经获得 Reviewer Agent `PASS`，然后提交用户，不做专业自检。

### 9.3 证据边界

产品不建设加密的 Agent 身份或角色调度协议。面向用户和最终 package 的 review artifact 只
保存专业成果、必要的简洁 finding 标识与处置摘要，以及当前版本的 Reviewer Agent `PASS`
状态；不得保存 Reviewer Agent 的完整内部推理、原始消息或其他 private reviewer payload，且
面向用户提交时不得存在未关闭 findings。Reviewer 原始输出只在当前编排上下文中短暂使用，
不进入稳定数据或 package。最终 Owner Skill receipt 通过 review hash 绑定用户实际看到并批准
的 review artifact。真实 E2E 观察 Worker Agent/Reviewer Agent 是否实际分离调用；若平台不能
维持这种分离则按 4.1 `BLOCKED`，确定性 validator 不伪造平台身份判断。

## 10. Validator Agent 与 Owner Skill validator 责任

Validator Agent 只运行并报告当前 Owner Skill 的确定性 validator；脚本本身是机械判断权威。
Validator Agent 不修改数据、不重解释 diagnostics，也不把失败改写为通过。每个 validator
脚本只负责：

1. 当前 Owner Skill 的候选输出及待发布稳定输出；
2. 当前 Owner Skill 的 review template 机械合同；
3. 当前 Owner Skill 创建的跨阶段引用；
4. 当前 Owner Skill 直接消费的上游 handoff 是否有效；
5. 当前 Owner Skill 的批准、候选字节原子发布、字节复用和 receipt 发布。

Validator Agent 的输入包只包含 project root、当前 Skill、候选或稳定 artifact 路径、运行模式和
精确命令。它不读取 canonical fixture、专业 review rubric、用户聊天或 Worker/Reviewer 原始输出；
需要的合同和规则由被执行脚本从已安装 Skill 内解析。Validator Agent 只返回脚本原始 outcome、
diagnostics、hash 和 receipt 摘要，不生成第二份解释性 review。

Validator Agent 必须保留脚本原始 outcome、diagnostics 和错误归属。当前候选成果错误才能路由
给 Worker Agent；缺少用户批准时回到用户门禁；上游 handoff 错误报告对应 Owner Skill 后停止；
环境、权限、合同或 validator 实现缺陷返回 `BLOCKED`。Validator Agent 不得要求 Worker Agent
通过修改已安装插件代码来让失败变成通过。

稳定数据发布分为两个确定性步骤：先校验 work 目录中的候选 JSON，再在 Reviewer Agent 确认
其忠实表达获批 review artifact 后，由 Owner validator 将相同候选字节原子发布到稳定 data
路径并签发 receipt。发布阶段不得重新生成、格式化或改写候选内容；候选 hash 与稳定输出 hash
必须相同。若发布前任一输入、review 或候选字节改变，前述 Validator/Reviewer 结果失效并重跑。

影响复核为 `Impact: NO_CHANGE` 时不生成新的候选 JSON。Owner validator 必须确认稳定 output
hash 与上一份成功 receipt 完全一致、直接上游 input/receipt hash 已更新、影响说明已由 Reviewer
Agent `PASS` 且用户确认，然后只发布绑定新 inputs、当前 review 和原 outputs 的新 receipt。
`NO_CHANGE` 下任何稳定 output bytes 变化都必须失败；`Impact: CHANGED` 则回到候选 JSON 的
完整发布流程。

### 10.1 analyze-requirement

负责来源登记、BUSINESS Epic/Feature、问卷声明、问题终态、`CLOSED`→BUSINESS ID 映射和 `APPROVED_DEFAULT` 完整性。

### 10.2 analyze-as-is

负责九个 Topic、Evidence、Uncertainty、Commitment、Effective Start、Coverage、自己选择消费的问卷记录及其编译关系。它验证 Requirement handoff，不重新诊断 Requirement 内部业务质量。

### 10.3 generate-design

负责全部 TECHNICAL requirements、目标设计、ScopeDecision、DesignDecision、typed obligations、
HLD 和 Go-live。HLD/Go-live review 的解析、覆盖、引用和批准门禁属于 `generate-design` 的
Skill-local 业务实现，只由其 validator 执行。它验证 Requirement/As-Is handoff，不重新实现
它们的内部 validator；下游也不重新执行它的 HLD/Go-live 门禁。

### 10.4 generate-story

负责 Gap、Story、AC、Integration、Assumption/Risk、Questionnaire 消费和十项上线映射。它检查自己创建的 Feature/Decision/Commitment 引用，但不重新判断 Requirement 问卷或 As-Is 内部 Item/Evidence/Commitment 是否自洽。

### 10.5 generate-task

负责 Story→Task、AC 覆盖、基础单元、工作模式、复杂度、Effective Start 引用、Integration Task、遗漏/重叠和实际使用的估算前提。它检查自己创建的引用，但不重新诊断 Story 或 Design 的内部质量。

## 11. Handoff receipt

当前 `ai-sow-owner-v1` receipt 已绑定输入、批准评审和输出字节。本设计保留算法并把 envelope 统一为可读的 named inputs/outputs。

### 11.1 合同

```json
{
  "owner": "generate-story",
  "passed": true,
  "diagnostics": [],
  "compilationReceipt": {
    "algorithm": "ai-sow-owner-v1",
    "subject": "generate-story",
    "validatorContractVersion": "0.3",
    "contractIds": [
      "urn:ai-sow:generate-story:delivery:0.2"
    ],
    "inputs": [
      {
        "name": "design",
        "kind": "FILE",
        "path": ".ai-sow/data/generate-design/design.json",
        "sha256": "<64-lowercase-hex>"
      }
    ],
    "reviews": [
      {
        "name": "approvedReview",
        "path": ".ai-sow/reviews/generate-story.md",
        "sha256": "<64-lowercase-hex>"
      }
    ],
    "outputs": [
      {
        "name": "delivery",
        "path": ".ai-sow/data/generate-story/delivery.json",
        "sha256": "<64-lowercase-hex>"
      }
    ]
  }
}
```

`passed` 与 `diagnostics` 属于 validation report；只有成功报告包含
`compilationReceipt`，失败报告不得携带可被下游接受的 current receipt。完全相同的
inputs、review 和 outputs 复用原 validation report bytes。

精确 input kind、name、path/identity 集合由各 Owner Skill 的本地 receipt 合同维护。`FILE`
输入使用项目相对 `path`；`CANONICAL_JSON`、`QUESTIONNAIRE_PRESENCE` 等逻辑输入使用
合同定义的 `identity`，不伪造文件路径。所有输入都有 `sha256`，不得保存本机绝对路径。
Review 和 output 均为 named project-relative file。Design 使用两个 named outputs，不再把
两个输出压缩成一个难以解释的业务摘要。Schema `$id` 与 receipt validator contract
version 独立：各稳定数据 Schema 保持当前 `:0.1` 或 `:0.2`，receipt envelope 升为
`0.3`。

### 11.2 下游 matcher

下游只检查：

- validation report 存在且顶层结构有效；
- report `passed = true` 且存在 `compilationReceipt`；
- `algorithm`、`subject`、`validatorContractVersion` 和 `contractIds` 受支持；
- inputs、reviews、outputs 的 name/path/kind 集合精确；
- 当前文件 SHA-256 与 receipt 一致；
- Owner Skill 当时消费的上游输出/receipt 仍是当前版本。

下游不调用上游 validator，也不重算上游业务结论。

## 12. 错误责任路由

下游 handoff 只返回四类稳定错误：

| Code | 含义 |
| --- | --- |
| `UPSTREAM_HANDOFF_MISSING` | 上游 receipt 或其声明的必要文件不存在 |
| `UPSTREAM_HANDOFF_INVALID` | receipt 结构、subject、集合、`passed` 或哈希格式无效 |
| `UPSTREAM_HANDOFF_STALE` | 当前输入、评审或输出字节与 receipt 不一致 |
| `UPSTREAM_CONTRACT_UNSUPPORTED` | receipt 或稳定输出合同版本不受当前 Skill 支持 |

诊断同时包含 `upstreamOwner` 和项目相对 path，明确指出对应 Owner Skill，不输出另一组上游
业务错误，也不自动调用该 Skill。Orchestrator Agent 结合当前 Skill 和 4.3 的固定阶段顺序，
向用户报告完整返回链和下一次应显式调用的 Skill；return route 只存在于聊天或当前 work 记录，
不扩展四类 handoff 错误，也不增加稳定 route JSON。

责任示例：

| 问题 | 报告方 |
| --- | --- |
| 上游没有通过 Owner Skill 校验 | 下游报告 handoff missing/invalid，指出上游 Owner Skill、返回链和下一次调用后停止 |
| 上游文件在批准后改变 | 下游报告 handoff stale |
| 当前 Story 引用了不存在的 Feature | Story Owner Skill |
| 当前 Task 引用了其他 Story 的 AC | Task Owner Skill |
| As-Is 内部 Commitment 不一致 | As-Is Owner Skill |
| 最终 workbook 投影、公式或结构错误 | generate-sow |

## 13. generate-sow 收缩

`generate-sow` 只拥有最终投影和 package，不重新判断 Requirement、As-Is、Design、Story 或 Task 的业务语义。

### 13.1 保留职责

- 项目、插件、SOW 标准、generator 和 template 合同版本；
- 五份 Owner Skill handoff receipt 与当前六份稳定 JSON、五份批准 review、模板字节的匹配；
- 支持的 `contractIds`；
- 六份 JSON 到 XLSX 的确定性投影；
- workbook Table、公式、样式、引用、动态范围、文本安全和复读；
- manifest、内容寻址 package、相同输入复用和普通 no-overwrite；
- 安装插件副本零漂移。

### 13.2 删除职责

- CARRY_FORWARD 业务覆盖重放；
- AC→Task 业务覆盖重放；
- Design Decision kind/Feature 资格重放；
- estimate parameter/risk readiness 重放；
- 任何其他已经由 Owner Skill receipt 证明通过的上游语义 validator；
- 同一权限主体在单次命令中主动实施目录替换、symlink race、源 inode 替换的对抗防御；
- EXDEV source-tree 复制和相应 fault injection。

若投影遇到 receipt 所声明合同本应保证但实际缺失的字段或引用，`generate-sow` 返回
`UPSTREAM_HANDOFF_INVALID`，标明对应 Owner Skill 和 path；这表示 Owner Skill contract/
validator 缺陷，不在生成器内补一套业务判断。

### 13.3 package 内容

成功 package 是自包含的审计投影，包含：

- `manifest.json`；
- `sow.xlsx`；
- 六份稳定 JSON；
- 五份批准 Owner Skill review；
- 五份 Owner Skill validation report/receipt；
- 项目模板。

不包含原始客户资料、repository 内容、prior SOW 原文、问卷全文或完整 Evidence 文件。它们只通过 Owner Skill receipt 的 hash-bound input identity 追溯。
五份批准 review 只包含用户实际评审的专业成果、必要的简洁 findings 处置摘要和当前 `PASS`
状态；Reviewer Agent 原始消息、完整内部推理和 private reviewer payload 不进入 package。

`packageId` 使用 `sow-sha256-<64-lowercase-hex>`，其 fingerprint 绑定以上 package source 的 name/path/hash、项目身份、插件版本、SOW 标准版本和 generator contract version。相同输入得到相同 package ID、manifest bytes、workbook bytes 和 package tree bytes。

### 13.4 普通发布模型

1. 在创建 staging 前验证所有 handoff、contract 和输入 hash；
2. 在 `.ai-sow/outputs/` 下创建唯一临时目录，确保与 final 位于同一 filesystem；
3. 生成、复读并验证完整 package tree；
4. final 不存在时执行平台普通的 no-overwrite publish；
5. final 已存在时只验证完整内容，相同则复用，不同则 `PACKAGE_CONTENT_MISMATCH`；
6. 运行时若报告 cross-device 或不支持 no-overwrite，返回 `PACKAGE_PUBLICATION_UNSUPPORTED`，不实现 EXDEV tree copy。

安全边界保留项目 containment、命令开始时的 symlink/reparse 拒绝、公式注入防护、隐私安全诊断和已有 final 不覆盖。不防御同一权限主体在命令执行过程中主动篡改已验证路径。

## 14. 实施与 E2E 运行 profile

### 14.1 运行 profile

业务 E2E 与插件实现工作流使用不同的运行 profile：

| Profile | 插件与流程技能 | 用途 |
| --- | --- | --- |
| `IMPLEMENTATION-LITE` | 新实现任务禁用 Superpowers 插件；保留 Codex 原生工具、原生 multi-agent、仓库命令和冻结计划 | Phase 0–3 实施；每个纵向切片只执行最小 RED→GREEN、focused suite 和一次 checkpoint 独立审查，不触发 executing-plans、subagent-driven-development、systematic-debugging 或多层 code-review 工作流 |
| `AI-SOW-only` | 启用 AI SOW、平台原生 multi-agent 和当前 Skill 必需工具；禁用 Superpowers 插件，不暴露或调用其 brainstorming、executing-plans、subagent-driven-development、TDD、debugging、code-review 等流程 Skill | 完整七阶段 release E2E 的唯一权威结果 |
| `SUPERPOWERS-COEXISTENCE` | AI SOW 与 Superpowers 同时安装/启用，但用户在本次 prompt 中明确只调用 `ai-sow:generate-design` 并禁止使用 Superpowers | 单阶段兼容 smoke；验证显式排除被遵守，不重复完整 E2E |

禁用 Superpowers 只隔离开发方法论，不关闭 Codex 原生 multi-agent，也不取消本设计自己的
Orchestrator/Worker/Reviewer/Validator 角色。设计、计划、独立计划审查与 freeze manifest 可在
当前启用 Superpowers 的任务中完成；freeze 后实施不得继续复用该任务。用户显式授权新 freeze
SHA 后，先禁用 Superpowers，再创建新的 `IMPLEMENTATION-LITE` Codex 任务并验证插件/Skill
可见集，然后才允许创建实现工作树或执行 Phase 0。实施任务直接按冻结计划运行仓库命令，
保留测试先行的行为证据，但不加载或调用 Superpowers 的 TDD、subagent、plan execution、
debugging 或 code-review Skill。

`IMPLEMENTATION-LITE` 中的原生 multi-agent 只用于计划明确要求的单次独立 checkpoint 审查，
不为每个测试、修复或文档步骤创建 Agent，也不允许 reviewer 再派发 subagent。实现期 review、
ledger 和上下文不得进入业务 E2E 证据或被计为 AI SOW 角色。

`SUPERPOWERS-COEXISTENCE` 只运行一个具备有效 Requirement/As-Is handoff 的代表性
`generate-design` 用户循环，覆盖一次 Worker draft、Reviewer review、用户反馈、复审、候选校验
和发布。它必须证明没有 Superpowers Skill 被调用、没有额外实现/代码 reviewer、没有嵌套 Agent，
但不重复 setup、其他 Owner Skill 或 generate-sow；完整正确性仍由 `AI-SOW-only` E2E 证明。

### 14.2 Agent 拓扑与上下文预算

每个 E2E session 只有一个 Orchestrator Agent，并遵守 4.1 的叶子 Agent 规则：

- `setup` 最多创建一个 Worker Agent 和一个 Validator Agent；
- 五个业务 Owner Skill 与 `generate-sow` 最多各创建一个 Worker Agent、一个 Reviewer Agent 和
  一个 Validator Agent；
- 同一 session 的修正、复审、候选编译和 validator 重跑通过 follow-up 复用原角色 Agent；
- Reviewer Agent 既负责专业 draft review，也在用户批准后负责候选编译忠实度核对，但两次
  调用使用不同的最小输入包，不再派发第二个 reviewer；
- 任一角色 Agent 派发子 Agent、Orchestrator 创建额外 helper/code-review Agent、Agent 树深度
  超过一，或 `AI-SOW-only` profile 出现 Superpowers Skill 调用，均使该次 E2E 失败。

E2E 证据只记录 profile、可见插件/Skill 集、session、角色 Agent identity、父子关系、每个角色
读取的项目内 artifact path/hash、outcome 和 STOP。它不保存完整 prompt、聊天、内部推理或
private reviewer payload。实现完成后的 Spec/Quality 代码审查是独立的实现门禁，只在业务 E2E
全部结束后运行一次，不嵌入任何 E2E session。

### 14.3 跨 session 用户流

E2E 围绕真实用户循环，而不是文件系统攻击测试。完整 E2E 必须把七个 Skill 表现为七次
彼此分离、且分别位于新的 Codex 任务/session 中的用户调用，即使七次调用由同一个用户完成。
`setup` 使用 4.4 的流程并停止；五个业务 Owner Skill 各自使用下面的流程并停止；
`generate-sow` 使用 4.5 的流程并停止。

每个新 session 只获得用户在该次调用中显式提供的项目根目录、输入资料或修正意见，以及项目内
已发布的 stable data、approved review、validation report/receipt 和其他合同允许的 artifact。
它不得继承、复制或由 E2E harness 注入上一 session 的隐藏聊天上下文、Agent 内部状态、Reviewer
原始输出或未发布候选。上一阶段 Orchestrator Agent 的自然语言完成说明只面向用户；下一阶段
是否可消费必须由项目内 handoff 和当前用户指令独立证明。

```text
用户显式调用当前 Skill
→ Orchestrator Agent 只启动当前 Skill
→ Worker Agent 评估输入；Orchestrator Agent 说明输出合同和输入缺口
→ Worker Agent 完成本阶段专业工作和 review draft
→ Reviewer Agent 审查
→ 有 findings：Worker Agent 修复 → Reviewer Agent 复审
→ Reviewer Agent PASS
→ Orchestrator Agent 将已审查版本提交用户
→ 用户批准？
   ├─ 否：Orchestrator Agent 转交用户意见
   │      → Worker Agent 调整
   │      → Reviewer Agent 审查，Worker 修复，Reviewer 复审至 PASS
   │      → Orchestrator Agent 再次提交用户
   └─ 是：Worker Agent 在当前 Skill work 目录编译候选 JSON
→ Validator Agent 对候选 JSON 运行确定性 validator
→ Reviewer Agent 核对候选 JSON 与获批 review artifact 的编译忠实度
→ Validator PASS 且 Reviewer Agent 确认忠实
→ Owner validator 发布同一份候选字节为 stable JSON 并发布 receipt
→ Orchestrator Agent 报告当前 Skill 完成、推荐下一 Skill
→ STOP
→ 同一用户新建 Codex 任务/session，并显式调用下一 Skill
→ 新 session 的 Orchestrator Agent 只根据本次用户指令和项目 artifact 启动当前 Skill
→ Validator Agent 验证 handoff 后才允许 Worker Agent 开始
```

正向 E2E 通过一组跨 session 的显式用户调用，证明环境自举、项目初始化、五个 Owner Skill
迭代、用户交接、工作簿复核和 package 重新生成完整闭合；任何单个 Skill 调用都不得自行进入
下一阶段。除七阶段各自使用新 session 外，认证还必须让至少一次同一 Owner Skill 的用户反馈
修正从新的 session 恢复：新 Orchestrator Agent 读取已保存的 review/work artifact 和用户修正
意见，重新建立 Worker/Reviewer 循环，不能依赖上一 session 的未保存记忆。

E2E 证据记录每次调用是独立 session、调用的 Skill、输入 artifact hash、最终 outcome 和 STOP；
不保存完整聊天、Agent 内部推理或 private reviewer payload，也不把 session identity 写入 stable
JSON、receipt 或最终 package。

上游回流至少认证两条真实路径：

```text
generate-task 发现 generate-design 问题并停止
→ 用户显式调用 generate-design 完成修正并停止
→ 用户显式调用 generate-story
   → NO_CHANGE：delivery.json 字节复用，Reviewer/用户确认，新 receipt 绑定新 Design
   → CHANGED：执行完整 Story 评审和发布
→ generate-story 停止并推荐 generate-task
→ 用户显式调用 generate-task，确认全部直接上游 receipt 当前后恢复
```

另一条从 `generate-sow` 路由到较早 Owner Skill，并逐个复核直到重新生成 package。返回链上的
每次显式 Skill 调用也分别使用新的 session。E2E 必须证明不能跳过中间依赖 Skill，不把
`NO_CHANGE` 误写成稳定 JSON 变化，并证明同一个用户跨 session 工作不会破坏 handoff。

负向 E2E 只覆盖有用户意义的边界：

- Python/uv 无法安装或锁定依赖环境无法准备；
- 关键输入缺失；
- 独立 Worker、Reviewer 或 Validator Agent 不可用；
- 用户尚未批准；
- Owner Skill 输出不符合 Schema；
- handoff missing/invalid/stale/unsupported；
- 当前 Skill 自己创建的引用错误；
- 新 session 缺少有效 handoff，且不能从上一 session 隐藏上下文恢复；
- `AI-SOW-only` profile 暴露或调用 Superpowers Skill；
- 角色 Agent 派发孙级 Agent、同一角色被无故重复创建或出现额外 helper/code-review Agent；
- workbook 投影、公式、结构或 package mismatch。

不把 same-user TOCTOU、rename source swap、EXDEV nested symlink 注入、非合作进程目录偷换作为 release gate。

## 15. 工作树与重写策略

### 15.1 两个工作树的职责

现有脏工作树不再作为实现基线。它保持未清理、未恢复、未提交的当前状态，只承担：

- 候选 Schema、fixture、模板和工作簿资产的来源；
- Tasks 1–7 的报告、快照、审查、定向探针和失败证据的只读来源；
- 发生语义争议时追溯某项规则为何存在的历史来源。

新实现使用独立的干净工作树，从当前干净仓库基线 commit `185774d` 创建，并使用 `codex/`
前缀的新分支。最终 freeze manifest 必须记录实际 base commit；若创建时 `185774d` 已不可用、
目标基线需要变化或基线测试不成立，则 fail closed，请求用户裁决，不静默改用更新的 `main`。
新工作树运行时、测试和发布均不得读取现有脏工作树。

创建新工作树、迁移资产和编写代码都属于实施。它们只能在新计划、独立审查、freeze manifest
完成，并由用户在实施任务中显式引用精确 SHA-256 授权后开始。本设计获批本身不授权这些动作。

### 15.2 迁移 allowlist

新 freeze 必须包含逐项迁移 manifest。每一项记录逻辑名称、来源相对路径、来源 SHA-256、目标
相对路径、保留理由、Owner、验证方式和隐私检查结果。只允许迁移：

- 本设计、新实施计划、审查记录、freeze manifest 和执行所需的权威合同文档；
- 已确认的八份 Schema 结构与中文 description；
- 已确认的 canonical fixture、review template 和必要专项规则；
- 从 Tasks 1–5 提炼的 Owner Skill-local 行为矩阵，包括规则来源、正例和单点负例；
- Task 5A 已确认的 `SIMULATED` descriptor/fixture 与 transport hash 隔离语义；
- 经来源、hash、公式、样式和视觉复核的 Task 6 模板、工作簿投影资产与确定性期望；
- 真实用户流所需、无客户内容的代表性 `SIMULATED` 输入资料。

迁移以单文件或文件内明确语义为单位，不允许复制整个目录。二进制 XLSX 必须先确认唯一权威
来源和预期 hash；同一模板的 bundled、fixture 和项目副本只能由权威模板按合同再生，不把多个
未知来源副本一起迁移。

### 15.3 默认不迁移

未进入 allowlist 的内容全部留在现有工作树。尤其不迁移：

- 当前 Tasks 1–5 的 `validate.py` 实现及其中复制的 receipt/path/report 代码；
- 当前修改过的七个 `SKILL.md`；新 Skill 指令从干净基线结合本设计重写；
- 当前大型测试文件、内部 helper 测试、fault injection 和 syscall/竞态实现细节断言；
- Task 7 的 `generate_sow.py`、测试、中间修复或 `task-7-before` 代码；
- Task 7 的快照、报告、原始 reviewer 输出和定向探针；它们仅留作历史证据；
- 生成 package、cache、临时目录、完整工具输出和 preserved `run-001`。

旧测试不是新测试数量或结构的基线。只有行为矩阵中仍属于本设计核心合同的 observable
behavior 才重新以 TDD 编写；测试不得为了证明“旧测试全部被移植”而重新引入旧实现 seam。

### 15.4 Clean-slate implementation

新工作树中的生产代码从基线重新编写：

1. 在新建且已验证 Superpowers 禁用的 `IMPLEMENTATION-LITE` 任务中，先建立 5.1 的共享技术
   module 及其小接口测试；
2. 逐个重写 Owner Skill validator，只加入自己的 Schema、业务规则、引用和 handoff 调用；
3. 基于迁移后的权威模板重写 `generate-sow` 的投影与 package 编排；
4. 每完成一个 module 或 Skill，用行为矩阵和当前接口测试替换旧测试，不叠加兼容 wrapper；
5. 只有所有调用方真实需要的行为才能进入共享 module；单一调用点的 helper 保持本地。

不设必须复用的旧代码行数，也不以 diff 小、测试数量相等或旧内部函数仍存在作为成功条件。
成功标准是同一用户合同由更小的接口表达、业务语义只有一个 Owner、实现可以在不读取历史
工作树的情况下理解和验证。

### 15.5 暂缓与历史证据

beta.2 migration、公共版本同步和真实用户流 E2E 在新工作树完成核心合同、Owner validator、
handoff 和 generate-sow 后按实施阶段顺序进行，不从旧 Task 编号续跑。

preserved `run-001` 继续只读，现有 3177 / `73c737c8ed4a5984aa4dc7814fe0bd224d568c69cc9da1abdd763ccff8cc44fb` 与冻结 3173 / `5ba6940b876bd6a4daf3b902c9b5a508a4e321904e0a444359b7a3c4cbad12d6` 的外部漂移不由本设计清理、恢复、迁移或重新定基线。

## 16. 实施阶段

### Phase 0：干净基线与资产迁移

- 在 freeze verifier 通过并获得精确 SHA 授权后，从 manifest 锁定的 base commit 创建独立
  `codex/` 实现工作树；
- 创建工作树前确认当前任务是新建的 `IMPLEMENTATION-LITE` 任务，Superpowers 插件已禁用且
  其 Skill 不可见；不在本设计/freeze 任务中继续实施；
- 在任何迁移前运行并记录干净基线检查；
- 按 15.2 的逐项 migration manifest 复制并复核合同、Schema、fixture、review template、
  行为矩阵和权威工作簿资产；
- 证明没有脚本、旧测试骨架、Task 7 实现、cache、客户内容、本机路径或 `run-001` 被带入；
- 迁移后重新计算目标文件 hash，并由独立 Reviewer Agent 对 manifest 与实际文件逐项复核。

### Phase 1：公共技术基础与 setup 纵向切片

- 从干净基线建立 `runtime/project_io.py` 和 `runtime/handoff.py` 的小 interface，不复制各 Skill
  的既有 helper；
- 一次确定 handoff 0.3 named input/review/output receipt envelope、hash closure、`NO_CHANGE`
  rebind 和下游四类稳定 matcher 诊断；
- 增加架构测试，禁止 runtime 反向 import/read `skills/*`、禁止 Skill 跨目录依赖，并禁止出现
  `owner_pipeline`、通用 Owner runner 或任何公共领域语义 module；
- 完成四种 Agent 角色、每个 Skill 完成即停止、Agent 不可用时 fail closed 和运行时项目写入
  边界等最小全局合同；
- 一次完成 `setup` 的 `SKILL.md`、环境检查与安装、项目身份/目录/模板初始化、Validator Agent
  验证、focused tests 和独立审查；
- 该阶段不修改六份稳定业务 JSON，也不提前实现任何 Owner Skill 业务规则。

### Phase 2：五个 Owner Skill 纵向切片

严格按 `analyze-requirement → analyze-as-is → generate-design → generate-story → generate-task`
顺序完成；不再先横向修改全部合同、再横向编写全部 validator、最后统一接 handoff。每个 Skill
在进入下一个 Skill 前一次完成：

- 自己的 Schema description、canonical fixture、review template、专项规则与 `SKILL.md` 生成前
  合同；
- Worker/Reviewer/Validator Agent 质量闭环、用户批准门禁、候选 JSON、Owner-local 业务与引用
  校验；
- 对直接上游 receipt 的匹配、自己稳定 JSON 与 receipt 的同字节发布，以及下游需要的完整 handoff；
- 上游变化时的 `Impact: NO_CHANGE`/`CHANGED` 复核；
- README/设计/`CONTEXT.md` 中属于该 Skill 的同步；
- RED→GREEN、focused suite、独立审查和阶段 checkpoint。

这里的 RED→GREEN 由实施 Agent 直接执行测试命令：先证明单个可观察行为失败，再写最小实现、
证明该行为通过并运行 focused suite；不调用 Superpowers TDD Skill，也不为每个循环创建
subagent。独立审查只在当前 Skill 纵向切片完成后运行一次。

五个切片共同遵守：

- 下游只报告四类 handoff 问题并验证自己创建的引用，不重放上游 validator；
- 不迁移旧大型 validator、旧测试骨架或兼容 wrapper，只从行为矩阵重建必要测试；
- 不迁移现有 `runtime/review_gates.py` 实现文件；在 `generate-design` 切片内从已批准合同和行为
  测试重建 Skill-local HLD/Go-live 门禁，`generate-story` 与 `generate-sow` 不调用该门禁；
- 当前切片未通过 checkpoint 时不得开始下一切片；后续集成发现问题时按 Owner Skill 返回，不在
  下游补第二套业务语义。

### Phase 3：generate-sow 纵向切片与 beta.2 同步

- 不恢复或复制 Task 7 pre/fix 文件，从干净基线一次完成 `generate-sow` Skill 合同、generator、
  workbook、package、tests 和独立审查；
- 只迁移经 Phase 0 确认的权威模板、工作簿投影资产和 observable determinism 期望；
- 只实现五个 Owner receipt 的 input gate、workbook projection、复读验证、自包含 deterministic
  package 和简单同 filesystem no-overwrite/reuse；
- 删除业务 defensive replay、HLD/Go-live replay 和对抗性 filesystem harness；
- 完成与正常 `setup` 分离的显式 beta.1→beta.2 项目 metadata 一次性升级；
- 同步 manifest、pyproject、lock、fixture、validator、README、设计、语言和 changelog，并验证
  cache-safe `uv run --isolated ... python -B` 命令与安装副本零漂移；
- 通过 focused suite、工作簿结构/公式/样式/visual、独立审查和阶段 checkpoint 后才进入最终认证。

### Phase 4：真实用户流与发布面认证

- 使用禁用 Superpowers 的 `AI-SOW-only` profile 运行完整 release E2E；
- Owner Skill focused tests；
- handoff missing/stale/unsupported tests；
- workbook 结构、公式、动态范围和 visual；
- repository tests、all Skill tests、copy-plugin smoke；
- 七个 Skill 分别在新的 Codex 任务/session 中由同一用户显式调用、完成后停止，再由用户新建
  session 调用下一 Skill 的正向认证；
- 新 session 只使用本次用户指令和项目内 artifact，不注入上一 session 聊天或 Agent 私有状态；
- 至少一次同一 Owner Skill 的用户反馈修正通过新 session 恢复并重新进入 Worker/Reviewer 循环；
- setup 每个 session 最多两个叶子角色 Agent，其他 Skill 最多三个；同一角色在修正/复审中复用，
  Agent 树深度不超过一；
- Worker Agent、Reviewer Agent、Validator Agent 角色分离与 Reviewer Agent `PASS` 后才提交用户的证据；
- 独立 Agent 不可用、Reviewer 发现用户输入/上游问题和 Validator 报告非当前成果错误时的
  fail-closed 路由证据；
- 候选 JSON 通过机械校验和编译忠实度核对后才以同一 hash 发布的证据；
- `generate-design → generate-story → generate-task` 和较早 Owner → `generate-sow` 的显式
  返回链；链上每次 Skill 调用使用新 session，并覆盖 `NO_CHANGE` 与 `CHANGED` 两条影响复核路径；
- 在完整 E2E 之外运行一次 `SUPERPOWERS-COEXISTENCE` generate-design smoke；
- 两个 E2E profile 均结束后，再独立运行一次实现 Spec/Quality 代码审查，不把该 reviewer 放入
  E2E session 或 AI SOW Agent 树。

## 17. 测试策略

### 17.0 替换而非叠加

新测试只面向 5.1 的 module interface 和用户可观察结果。旧工作树测试用于提炼行为矩阵和核对
历史意图，不复制到新工作树，也不要求逐个通过。测试分成五个足够的层次：

1. Schema/canonical fixture 与 Owner Skill-local 业务规则；
2. 共享 handoff/project I/O interface；
3. workbook/package 投影、复读和确定性；
4. 少量代表真实七次跨 session 显式调用、跨 session 反馈恢复和上游返回链的
   `AI-SOW-only` E2E；
5. 一个 `SUPERPOWERS-COEXISTENCE` generate-design smoke，不复制完整业务 E2E。

如果某个旧测试只观察 private helper、临时路径、syscall 顺序、inode、fault hook 或已删除的
上游语义 replay，它没有迁移价值。一个行为已经由深 module 的接口测试证明后，不在每个 Skill
重复同一组机制测试；各 Skill 只保留一条成功集成和与自身业务有关的失败集成。

### 17.1 确定性测试

- Schema description coverage；
- canonical fixture schema/validator PASS；
- review template 必需章节和 machine declarations；
- Owner Skill-local 业务规则、引用闭合和失败时 artifact immutability；
- 候选 JSON 校验、候选/稳定字节 hash 一致、发布前变化导致门禁失效；
- `NO_CHANGE` 下稳定 output hash 不变、上游 input/review hash 更新且新 receipt 有效；
- `NO_CHANGE` 下 output bytes 变化必须失败，`CHANGED` 必须进入候选 JSON 完整流程；
- 返回链中直接上游 receipt 有效而当前 Skill 自身旧 receipt stale 时进入影响复核，不错误回路由上游；
- receipt exact shape、hash closure、byte reuse 和失效；
- 下游四类 handoff error；
- runtime→Skill 反向依赖、跨 Skill import/read、公共领域语义 module 和下游 HLD/Go-live replay
  均被架构测试拒绝；
- generate-sow projection、workbook、determinism、normal collision/interruption；
- install copy regular-file manifest 零漂移。

### 17.2 专业质量验证

- Reviewer Agent 使用 Owner Skill-local rubric；
- 每一版提交用户的完整 review artifact 都有对应的独立 Reviewer Agent 审查、Worker Agent
  findings 修复和修复后 Reviewer Agent `PASS` 证据；
- 用户批准后，候选 JSON 具有独立 Reviewer Agent 的编译忠实度核对；
- 上游变化后，Worker Agent 形成影响说明，Reviewer Agent 独立判断 `NO_CHANGE`/`CHANGED`，
  用户确认后才允许续签 receipt 或修改稳定输出；
- Orchestrator Agent 没有制作、修复或审查专业成果，也没有自动调用下一 Skill；
- E2E 的新 session 没有继承上一 session 聊天或私有 Agent 状态，只通过当前用户指令和项目内
  handoff/artifact 恢复工作；
- `AI-SOW-only` profile 没有可见或被调用的 Superpowers Skill；共存 smoke 虽然安装/启用
  Superpowers，但遵守用户显式排除且没有调用其 Skill；
- setup Agent 树最多两个叶子角色，其他 Skill 最多三个；角色 Agent 没有子 Agent，同一角色在
  当前 session 的修正/复审循环中保持复用；
- Reviewer Agent 的专业 review 和编译忠实度核对使用同一个独立角色 Agent 与不同最小输入包，
  没有第二套 code-review/subagent-driven review；
- Worker、Reviewer 或 Validator Agent 不可用时没有角色降级，当前 Skill 明确 `BLOCKED`；
- 用户对 review artifact 明确批准；
- certification 对 representative `SIMULATED` 项目检查合理性、覆盖和遗漏；
- 自动测试不把“validator PASS”等同于专业结论合理。

### 17.3 不再要求的测试

- 同一权限攻击者在检查和 syscall 之间替换路径；
- final rename source-name swap；
- EXDEV source walker symlink 注入；
- mkdir→first-open replacement cleanup；
- 非合作进程故意破坏 staging identity；
- generate-sow 与 Owner Skill 对每一条业务 diagnostic 的双实现等价。

## 18. 兼容与版本

- 目标插件版本保持 `0.1.0-beta.2`；
- SOW 标准保持 `1.3`；
- 稳定业务 JSON 结构和各自现有 Schema `$id` 保持不变：Project、Source Requirements、
  As-Is 为 `:0.1`，Design、Technical Requirements、Delivery、Estimate 为 `:0.2`；
- Schema description、fixture 和 review template 增强不改变稳定 JSON bytes 的兼容规则；
- receipt envelope 升为 validator contract `0.3`，旧 receipt 由下游报告 `UPSTREAM_CONTRACT_UNSUPPORTED`，不静默迁移；
- beta.1→beta.2 一次性升级不由正常 `setup` 初始化静默触发，只修改项目
  metadata 和升级报告；六份稳定 JSON 必须由五个 Owner Skill 重新评审并发布 0.3 receipt；
- manifest/package 合同随新的 self-contained review/receipt tree 更新。

## 19. 隐私、语言与发布边界

- 中文自由文本使用简体中文；machine token、字段、枚举、ID、路径、hash、Sheet、Table 和公式保持原值；
- stable JSON、receipt、package 和公共 fixture 不保存凭据、客户原文、私有源码、完整工具输出或本机绝对路径；
- package 不复制 repository/prior-SOW/问卷/Evidence 原文；
- 插件运行时不读取自身安装目录之外的 marketplace 文件；
- template 继续是人天、倍率、公式、风险、SIT、UAT 和取整的唯一计算权威；
- 未经单独授权不 commit、push、merge、publish 或 release。

## 20. 验收标准

设计实施完成时必须同时满足：

1. 八份 Schema 的稳定字段 description 覆盖测试通过；
2. 五个业务 Owner Skill 的 Worker Agent 在生成前读取自己的 Schema、canonical fixture、review template 和必要专项规则；
3. 每个稳定数据 canonical fixture 通过自己的 Schema 和 Owner Skill validator；setup 的
   Worker Agent 能检查并在缺失时安装 Python/uv，通过插件 lockfile 准备或复用隔离依赖环境，
   调用最小脚本创建四字段项目元数据、受管目录和模板副本，并由 Validator Agent 验证
   Project Schema 与模板 round-trip；
4. review artifact 包含编译稳定 JSON 所需的非机械结论；
5. Worker Agent、Reviewer Agent 和用户评审循环在 Skill 合同中明确；每一版提交用户的 Owner Skill
   结果都先经过 Reviewer Agent 审查、Worker Agent 修复和 Reviewer Agent 复审至 `PASS`，
   用户批准后 Worker Agent 才编译候选 JSON；候选通过 Validator Agent 机械校验和 Reviewer
   Agent 编译忠实度核对后，Owner validator 才发布相同 hash 的稳定 JSON 与 receipt；
6. Validator Agent 只运行确定性脚本且不放宽失败；每个 Owner Skill validator 只诊断自己的
   数据和自己创建的引用；Reviewer/Validator 结果按当前成果、用户输入、上游 Owner Skill 或
   blocker 正确分流，不形成不可退出的 Worker 循环；
7. downstream 只报告四类 handoff 问题，不重复报告上游内部数据质量错误；Orchestrator Agent
   另外根据固定阶段顺序向用户说明 Owner Skill、返回链和下一次显式调用；
8. 上游输入、评审或输出改变后，downstream 通过 hash 报告 stale，并且不能绕过中间直接依赖
   Skill 跳回原被阻塞 Skill；
9. `generate-sow` 不重新判断 Requirement、As-Is、Design、Story 或 Task 业务语义；
10. workbook 动态范围、结构、样式、公式、引用、文本安全和视觉检查通过；
11. 相同输入产生相同 package ID、manifest bytes、workbook bytes 和 package tree；
12. 普通已有 package 不覆盖，内容相同复用、不同则 mismatch；
13. repository tests、all Skill tests、copy-plugin smoke 和跨 session 真实用户流 certification 通过；
14. 没有客户数据、本机路径、凭据或 private reviewer payload 进入公共文件；
15. 现有脏工作树、Task 7 旧复杂实现、快照证据和 `run-001` 均未被静默清理、恢复、迁移或重新定基线；
16. 七个 Skill 的用户流程在各自 `SKILL.md` 中与本设计一致：setup 初始化、五个 Owner Skill
    迭代评审、generate-sow 投影复核与反馈路由均可独立完成；每个 Skill 完成后停止，只推荐
    下一 Skill，且不得在没有用户显式调用时推进；
17. 全文 Agent 角色只使用 Orchestrator Agent、Worker Agent、Reviewer Agent 和 Validator Agent；
    Orchestrator Agent 不制作或审查专业成果，其他三种 Agent 由相互独立的 Agent 调用承担，
    Validator Agent 以脚本结果为权威；任一必需 Agent 不可用时 fail closed；
18. 运行中的 Worker Agent 只修改当前 Skill 明确拥有的项目内 artifact；除用户明确授权修改
    项目模板外，不修改其他 Skill 数据或任何已安装插件代码、合同和 bundled asset；
19. 根 `AGENTS.md`、插件设计、`CONTEXT.md`、七个 `SKILL.md` 和测试对 receipt-only handoff、
    HLD/Go-live 由 `generate-design` 唯一拥有且只在本 Skill 校验、四 Agent 角色与 Skill 停止
    边界不存在冲突；
20. 最终 package 中的 review 只含用户评审成果、简洁 findings 处置摘要和 `PASS` 状态，不含
    Reviewer Agent 原始消息、完整内部推理或 private reviewer payload；
21. 上游 Owner Skill 修正后，从其直接下游开始按固定阶段顺序逐个显式调用至原被阻塞 Skill；
    每个阶段先做影响复核，`NO_CHANGE` 时稳定 JSON bytes 保持不变并在 Reviewer/用户确认后
    更新 receipt，`CHANGED` 时执行完整评审和发布；每个阶段完成后停止，不自动级联；
22. 新实现任务在用户精确 SHA 授权后新建，使用 `IMPLEMENTATION-LITE` profile，Superpowers
    插件已禁用且其 Skill 不可见；新实现工作树来自 freeze manifest 锁定的干净 base commit，
    且运行时、测试、生成和发布均不读取现有脏工作树；
23. 所有迁移文件都存在逐项 path/hash/reason/owner/verification/privacy 记录，未列入 allowlist 的
    脚本、旧测试、Task 7 实现、cache 和证据文件没有进入新工作树；
24. 除空的 package marker `runtime/__init__.py` 外，公共 runtime 源文件只有 `handoff.py` 与
    `project_io.py`，且只承载共享技术机制；HLD/Go-live 门禁位于 `generate-design`，各 Owner
    Skill 其他业务语义也保持本地；调用方和测试不依赖 module 内部 syscall、临时文件或 helper；
25. 新 validator、generator 和测试从干净基线按原生轻量 TDD 建立：每个可观察行为保留
    RED→GREEN 与 focused suite 证据，不调用 Superpowers TDD/subagent/plan execution/review
    Skill；没有复制旧大型入口函数、为旧 helper 保留兼容 wrapper，或以旧测试数量/结构作为
    完成条件；
26. release E2E 中七个阶段分别由同一用户在新的 Codex 任务/session 显式调用，至少一次同一
    Owner Skill 用户反馈也在新 session 恢复；所有新 session 只依赖当前用户指令和项目内已保存
    artifact，证据证明上一 session 聊天或 Agent 私有状态未被注入，且最终 package 不包含 session
    identity 或完整聊天；
27. 完整 release E2E 使用 `AI-SOW-only` profile，Superpowers 插件被禁用且其 Skill 不可见、未被
    调用；Codex 原生 multi-agent 和 AI SOW 四角色仍正常工作；
28. 每个 E2E session 的 Agent 树深度不超过一：setup 最多两个叶子角色 Agent，其他 Skill 最多
    三个；同一角色在该 session 内复用，Reviewer 的专业 review 与编译忠实度核对不产生第二个
    reviewer，任何孙级或额外 helper/code-review Agent 都会使认证失败；
29. 独立的 `SUPERPOWERS-COEXISTENCE` generate-design smoke 在 Superpowers 安装/启用时遵守用户
    的显式排除，没有调用 Superpowers Skill 或产生额外 Agent；实现 Spec/Quality 代码审查只在
    E2E 外运行一次；
30. Skill 之间不存在代码或发布资产依赖：各 Skill 只读取自己的合同包和项目内上游 handoff；
    `runtime/handoff.py`、`runtime/project_io.py` 不反向读取或硬编码任何 Skill，且没有
    `owner_pipeline`、通用 Owner runner 或配置驱动业务引擎。独立复制整个插件后所有 Skill 仍可
    运行；不要求单独复制一个 Skill 目录脱离插件 runtime 运行；`generate-story` 与
    `generate-sow` 不调用或复制 `generate-design` 的 HLD/Go-live validator。

## 21. 非目标

- 不建设统一 AI SOW CLI、共享业务 runtime、共享业务 Schema 或自动审批系统；
- 不建设 `owner_pipeline`、通用 Owner runner 或以配置消除 Skill-local 工作流编排；
- 不把 HLD/Go-live 门禁放入公共 runtime，也不让下游重放该门禁；
- 不把“Skill 独立”扩大为单个 Skill 目录可脱离 AI SOW 插件物理安装和运行；
- 不保留当前中间实现的代码行、private helper、测试拓扑或 Task 编号连续性；
- 不把“新工作树”理解为重新讨论已批准领域合同；经 migration manifest 接受的领域知识继续有效；
- `setup` 不安装 Codex 插件，不向用户项目写入 Python 依赖，不提供 repair，也不自动迁移
  已有项目；Python 与 uv 缺失时由 Worker Agent 按 setup 合同补齐；
- 不让 E2E harness 创建、拥有或解释业务语义；
- 不在启用 Superpowers 的 profile 下重复完整七阶段 E2E，也不建设所有第三方插件组合的兼容矩阵；
- 不在 Phase 0–3 实施任务中启用 Superpowers，也不把禁用 Superpowers 解释为取消测试先行、
  focused suite 或 checkpoint 独立审查；
- 不用确定性脚本替代 Reviewer Agent 或用户的专业判断；
- 不把 Worker Agent、Reviewer Agent、Validator Agent 分工升级成加密角色身份系统；
- 不允许最终用户 Skill 运行自修改已安装插件代码、合同或 bundled assets；
- 不建设字段级依赖图或自动级联执行器；上游修正后的影响复核保持 Skill 级、顺序且由用户显式调用；
- 不强迫真实用户每个阶段都新建 session；跨 session 是 release E2E 的独立性认证方式，产品合同
  仍只要求用户显式调用当前 Skill；
- 不防御同一操作系统用户在单次命令运行中主动竞争修改已验证路径；
- 不支持 cross-filesystem package publication；
- 不用 CI 或合成测试声明 Windows 11/Excel Desktop 实机验收；
- 不修改、清理或重新定基线 preserved `run-001`；
- 不在本设计批准时自动开始实现。
