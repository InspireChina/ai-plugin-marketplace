# 基于 PRD、HLD 的自动化 SOW 工作流最终方案

- 状态：已实现
- 执行日期：2026-09-02
- 实现基准：`d6738ee25cace4eb97db1cd204f769c6c63b7128`
- 适用范围：`plugins/ai-sow/`
- 方案性质：已落地的目标合同；实现由当前正式合同与测试共同约束
- 当前运行合同：[AI_SOW_PLUGIN_DESIGN.md](AI_SOW_PLUGIN_DESIGN.md)

## 1. 决策摘要

AI SOW 重构为一个面向用户的深 Skill：

```text
ai-sow:generate
```

用户在首次调用时一次性提交标准输入。插件随后自动完成输入归档、范围编译、交付分解、审核和 SOW
渲染；不再要求用户逐阶段调用 Skill、确认 Batch 或批准 hash-bound packet。只有确实无法形成可信范围
或估算时，插件才集中询问最少量问题。

后续输入变化时，插件不执行字段级 patch，也不整体重做项目，而是：

```text
识别变更来源
  -> 定位受影响 Feature
  -> 扩展关联闭包
  -> 重算整个受影响切片
  -> 替换旧切片
  -> 完整重渲染 SOW
```

最终用户体验是“一个入口、通常一次生成、例外时一次集中补充”。

## 2. 目标与非目标

### 2.1 目标

- 将 PRD 和 HLD 作为所有项目的标准输入；
- 将至少一份适用往期 SOW 作为 Brownfield 的强制 As-Is 输入；
- 在首次调用中完成输入收集，不把输入准备拆散到后续阶段；
- 自动串联专业分析、Story/Task 分解、估算准备和工作簿生成；
- 在高阶输入粒度下仍能生成有固定边界的 SOW；
- 用配套说明承接非阻断不确定性；
- 根据输入语义变化重算受影响业务切片；
- 保留输入版本、来源追踪、ID 稳定性和输出可追溯性；
- 失败或阻断时保留上一份有效 SOW；
- 保持 Excel 模板为计算规则的唯一权威。

### 2.2 非目标

本方案不要求：

- PRD 包含 Story、Task、开发级 AC 或详细技术设计；
- HLD 包含 Feature 到 Design Coverage 矩阵；
- HLD 包含完整接口字段、类设计、逐接口异常处理或完整上线 Runbook；
- 用户逐阶段批准中间产物；
- 插件维护字段级 patch、事件溯源或复杂运行状态机；
- 将所有领域对象合并成一个巨大 JSON；
- 在 Python 或 JSON 中复制 Excel 公式、倍率或取整规则；
- 自动生成等同于客户签署或正式接受 SOW；
- 兼容任何旧 Skill、旧项目结构或旧 Schema。

## 3. 单一公开 Skill 与内部 Module

插件只公开：

```text
ai-sow:generate
```

其内部结构为：

```text
ai-sow:generate
  |- orchestrator
  |- intake             -> InputManifest
  |- scope_compiler     -> ScopeBundle
  |- delivery_compiler  -> DeliveryBundle
  `- package_renderer   -> Package
```

### 3.1 `orchestrator`

`orchestrator` 负责选择首次生成、无变化复用、受影响切片更新或阻断恢复，并串联其他 Module。它只协调
事务、校验和发布，不拥有 Feature、Design、Story、Task 或估算业务规则。

### 3.2 `intake`

`intake` 负责：

- 识别 Greenfield / Brownfield；
- 收集强制输入、项目基本信息和最小问卷；
- 保存本次有效输入快照；
- 将文档拆成可定位的语义锚点；
- 计算文件、章节和问卷答案的内容指纹；
- 与最近一次成功输入 revision 比较；
- 输出 `InputManifest` 和变更来源。

### 3.3 `scope_compiler`

`scope_compiler` 负责把 PRD、HLD、往期 SOW 和补充输入编译成 `ScopeBundle`。它可以在 Bundle 内保持
相互独立的业务需求、Effective Start、目标设计、Integration 和 NFR 视图，但必须联合检查范围差值、
来源引用和责任边界。

### 3.4 `delivery_compiler`

`delivery_compiler` 负责把受影响的 Scope 切片编译成 `DeliveryBundle`，在一次事务中共同生成和验证：

```text
Feature
  -> Story
  -> Acceptance Criteria
  -> Design / Implementation Task
  -> 依赖与估算投影
```

Story 和 Task 不再分成需要用户分别批准的阶段。

### 3.5 `package_renderer`

`package_renderer` 只读取已通过终审的 `ScopeBundle`、`DeliveryBundle` 和 SOW 模板，确定性生成工作簿
与配套说明。它不重新解释 PRD、HLD 或往期 SOW，也不重新执行范围判断。

这些 Module 是内部可测试 seam，不是新的用户命令，也不重新形成多 Skill 工作流。

## 4. 标准输入合同

### 4.1 所有项目

所有项目必须提供：

- PRD；
- HLD；
- 项目标识、名称和计划生效日期；
- 客户、供应商和第三方的高层责任边界。

所有项目必须使用适用的 SOW Excel 模板；未指定项目模板时使用插件内置权威模板，不要求用户额外
上传一份模板。

输入格式按来源角色固定：PRD 和 HLD 只接受 UTF-8 Markdown（`.md`）；往期 SOW 只接受
Excel（`.xlsx`）；补充材料接受 UTF-8 纯文本或 `.xlsx`。补充文本默认按 Markdown 理解，也可以是
HTML、TypeScript、TSX 等原型源码，但 intake 只按文本提取语义锚点，不引入对应语言的专用解析器。
PDF、Word、PowerPoint 和其他需要专用解析器的格式暂不支持。标准模板用于降低准备成本，不要求已有
客户文档使用完全相同的标题、目录或版式；校验关注必需语义，不按标题机械拒绝文档。

原型 Demo 作为 `SUPPLEMENT` 输入时，插件不能只把它当普通附件。`scope_compiler` 必须结合源码识别
页面或入口、用户动作、触发条件、状态变化、校验、权限、异常路径以及可观察业务结果。源码不足以确认
真实交互且 Demo 可以运行时，可以在本地启动它，并按需使用 Playwright 或 Computer Use 验证交互。
运行观察必须可追溯到对应原型来源，不得静默覆盖 PRD/HLD；发现冲突时仍按第 6 节处理。

空白模板、仅含占位符的文件、无法读取的文件或与项目无关的样例不算有效输入。

### 4.2 Greenfield

Greenfield 不要求往期 SOW。它以“本期新建、不继承既有合同能力”为默认 Effective Start，并只收集
确实影响范围、责任或估算的最小问卷，不开展完整 As-Is 调查。

最小问卷仅补充 PRD/HLD 未覆盖的必要信息，例如项目责任、环境准备、第三方依赖或数据迁移责任。
可以用有界假设承接的信息不得触发追加问答。

### 4.3 Brownfield

Brownfield 必须额外提供至少一份适用于本次范围的往期 SOW。缺少适用往期 SOW 时直接返回
`BLOCKED`，不提供“精简 Current State Baseline”等替代路径。

往期 SOW 是合同口径的 As-Is、Effective Start、既有承诺和延续范围来源，但不自动证明当前生产状态。
因此首次输入必须包含一项现状增量声明：

> 自所提供往期 SOW 生效以来，生产系统是否存在已知的范围、架构、集成或部署变化？

用户可以回答“无已知变化”，也可以提供变更清单或补充材料。插件不再运行多轮 As-Is Batch；未提供
实时证据但仍可形成边界时，以 `PASS_WITH_NOTES` 披露证据限制。

多份往期 SOW 按适用范围、签署或生效状态、版本和日期判断适用关系。只有冲突会实质改变本次范围
或估算，且无法从材料中确定优先级时，才允许阻断。

## 5. PRD 与 HLD 标准模板

标准模板约束“必须表达什么”，不要求作者提供插件内部追踪矩阵或低阶设计。

### 5.1 PRD 模板

PRD 模板包含：

- 项目背景、待解决问题、目标和成功指标；
- In Scope / Out of Scope；
- 用户、角色和核心业务场景；
- Feature、业务结果、业务规则和验收意图；
- 优先级、阶段安排、业务约束、依赖和假设；
- 涉及的业务数据、合规要求和外部参与方。

每个 Feature 至少能够回答：

```text
谁
  -> 在什么场景或触发条件下
  -> 要得到什么业务结果
  -> 有哪些关键业务规则或重要异常
```

这不是完整开发级 AC，但必须足以判断业务完成边界和合理的 Story 拆分。

PRD 不要求：

- API、数据表或技术组件设计；
- Story 和 Task 分解；
- 完整开发级验收条件；
- 穷举所有异常分支；
- Feature 到 Design Coverage 矩阵。

### 5.2 HLD 模板

HLD 模板包含：

- 系统上下文、参与方和系统职责；
- 目标架构和关键业务流；
- 跨系统 Integration；
- 数据流、迁移、保留和安全分类；
- 性能、容量、可用性、安全、隐私、审计、灾备和可观测性等 NFR；
- 环境、部署、切换和上线约束；
- 已确定的关键技术决策；
- 明确需要实现、但详细方案尚未确定的设计事项。

每个跨系统交互至少说明：

- 来源系统和目标系统；
- 交互目的；
- 业务触发事件；
- 交换的数据类别；
- 系统责任归属；
- 已确定方案，或者明确标记为待设计。

协议、字段、错误码、重试和补偿可以留待设计。

每项适用 NFR 至少处于以下状态之一：

- 已有明确目标；
- 需要满足，但目标值或实现方案待设计；
- 不适用。

适用 NFR 不能简单留空。第二种状态生成 Design Task，并在 `sow-notes.md` 中声明估算边界。

HLD 不要求：

- PRD Feature 到 Design Coverage 矩阵；
- 完整接口、事件或批处理目录；
- 字段级接口定义或完整时序图；
- 类设计、Task 级方案或代码结构；
- 逐接口超时、重试、幂等和补偿设计；
- 完整监控阈值、回滚步骤和生产验证清单。

Requirement、Feature、Design、Integration、Story、Task 和 AC 的追踪关系由插件编译，不属于 HLD
作者的责任。

## 6. 来源权威与冲突处理

不同输入各自拥有明确语义：

- PRD：业务目标、业务范围、Feature、业务规则和验收意图；
- HLD：目标架构、跨系统设计、Integration、NFR 和上线约束；
- 往期 SOW：Brownfield 的合同 As-Is、历史承诺和 Effective Start；
- 当前问卷答案和明确补充：责任、现状变化、本次明确决策，以及原型中的功能与交互证据；
- SOW 模板：任务分类、基础人天、公式、倍率、风险和取整规则。

往期 SOW 不得覆盖当前 PRD/HLD 对本期目标的定义。PRD 决定“要交付什么业务结果”，HLD 决定“高层
上如何实现以及受什么技术约束”；两者出现实质矛盾时，不能简单按文件顺序覆盖。

冲突按以下顺序处理：

1. 如果可以通过明确假设、责任或排除范围建立固定边界，以 `PASS_WITH_NOTES` 继续；
2. 如果不同解释会改变 Feature、交付责任或估算，且无法建立可信边界，返回 `BLOCKED`；
3. 用户明确补充的本次决定写入结构化输入 revision，成为后续 diff 的正式来源；
4. 插件推断永远不能静默覆盖明确来源，重要推断必须进入 `sow-notes.md`。

## 7. 稳定数据与来源追踪

插件只维护三类核心稳定数据：

```text
InputManifest
ScopeBundle
DeliveryBundle
```

`Package` 是从它们和 SOW 模板确定性渲染的结果，不拥有新的范围事实。

### 7.1 内嵌追踪

不创建独立、要求用户维护的 Coverage Matrix。每个编译对象自行携带最小追踪信息：

```text
Feature
  source_refs: PRD 章节、往期 SOW 条目、用户补充

DesignItem / Integration / NFR
  source_refs: HLD 章节、往期 SOW 条目、用户补充
  feature_ids: 受其影响的 Feature

Story
  feature_ids

Task
  story_id
  design_item_ids
  integration_ids
  nfr_ids
```

`source_refs` 使用“文档逻辑标识 + 标题、表格项等定位信息 + 内容指纹”，不依赖容易漂移的页码或
行号。运行时从对象引用生成反向索引，不另存第三份追踪合同。

### 7.2 ID 规则

- 语义未变化的对象保留原 ID；
- 只发生文字澄清且交付含义未变化时保留 ID；
- 实质含义变化时创建新 ID；
- 被删除且新切片不再生成的对象直接消失；
- 不允许复用旧 ID 指代新的业务或技术含义。

## 8. 输入 revision 与隐私

语义 diff 必须比较前后有效输入，因此插件记录每次对范围有影响的输入，而不是保存完整聊天记录。

每个输入 revision 至少包含：

- 当次实际使用的 PRD、HLD、往期 SOW 和补充材料快照；
- 结构化问卷答案、用户事实、明确决策和变更说明；
- 文档逻辑角色、版本、时间和 SHA-256；
- 解析后的章节锚点、规范化内容和内容指纹。

输入 revision 创建后不可回写。生成状态、所用输入 revision、Bundle hash、模板 hash 和输出文件 hash
记录在对应的 generation manifest 中。

无关对话、推理过程和未成为范围输入的聊天消息不进入 revision。

Diff 基准固定为：

```text
最近一次成功输入 revision
  vs
本次 pending 输入
```

新输入先写入 `pending/`。成功后固化成不可变 revision 并更新 `current.json`；被阻断时保留
`pending/`，用户补充后直接续跑，不重复询问已经提供的信息。

输入快照可能包含客户原文和衍生数据，因此：

- `.ai-sow/` 默认必须被版本控制忽略；
- 公共仓库、测试 fixture、日志和文档不得保存真实客户内容；
- 面向用户的诊断不得输出完整敏感原文；
- 清理或分享项目时必须把 `.ai-sow/` 视为客户数据目录。

## 9. 首次生成和后续调用

用户始终调用同一个 Skill。`orchestrator` 自动选择行为：

| 项目状态 | 行为 |
|---|---|
| 尚无有效项目 | 收集并校验输入，然后全量生成 |
| 输入与规则均未变化 | 复用当前有效结果 |
| 输入发生变化 | 重算受影响切片 |
| 上次为 `BLOCKED` 且已补充材料 | 基于 `pending/` 继续生成 |
| 仅 SOW 模板变化 | 仅完整重渲染 Package |
| 编译合同或算法版本变化 | 重新编译其影响的全部数据 |

首次生成：

```text
intake
  -> scope_compiler
  -> delivery_compiler
  -> 自动终审
  -> package_renderer
```

后续更新：

```text
比较输入 revision
  -> 计算受影响 Feature 闭包
  -> 重算并替换受影响切片
  -> 自动终审
  -> 完整重渲染 Package
```

不持久化 `COLLECTING / RUNNING_SCOPE / RUNNING_DELIVERY` 等业务状态机。有效基线由 `current.json`
指向的不可变 generation 表达，待处理输入由 `pending/` 表达，本次临时过程由 `work/` 表达。

## 10. 受影响切片全量替换

插件不产生字段级 patch。每次变更先定位来源锚点，再从直接关联 Feature 出发扩展引用闭包，完整重算
该闭包并替换旧切片。

修改或删除的来源锚点通过上一份 `source_refs` 定位已有对象；新增锚点由 `scope_compiler` 根据其业务
场景、系统域和相邻语义建立新的 Feature 或关联已有 Feature。若无法可靠确定唯一 Feature，影响范围
按“所在 Feature -> 所在系统或业务域 -> 整个 ScopeBundle”逐级扩大。插件宁可扩大内部重算范围，
也不能为了维持小切片而遗漏影响；这种扩大本身不要求用户确认。

闭包至少覆盖：

- 直接引用已变化来源的 Feature；
- 这些 Feature 的 DesignItem、Integration 和 NFR；
- 对应 Story、AC 和 Task；
- 与其共享已变化 DesignItem、Integration、NFR、Assumption 或 Task 的其他 Feature；
- 依赖上述对象且会改变交付或估算的对象。

未受影响切片保留原对象内容和 ID。只有当共享对象的引用闭包实际扩展到整个项目时，才退化为全项目
重算。

切片替换规则：

- 新切片中仍存在且语义未变的对象保留原 ID；
- 新切片中新增的对象获得新 ID；
- 旧切片中存在、但新切片不再生成的对象自动删除；
- 不保留 `add / replace / remove` patch 列表；
- 每次替换后重新运行跨切片引用和估算校验；
- XLSX 和 `sow-notes.md` 始终完整重渲染，不局部修改 OOXML。

### 10.1 删除“API 完成后发送消息”的示例

- 如果 PRD 同时取消通知业务结果，相关 Feature、Story 和 Task 在重算后自然消失；
- 如果 PRD 仍要求通知，但 HLD 删除发送消息方案，业务 Feature/Story 保留，技术设计重新计算，必要时
  生成 Design Task、假设和变更触发条件；
- 如果 HLD 将发送消息改为轮询，业务结果不变时 Feature/Story 通常保留原 ID，只重算技术设计、
  Integration 和 Task。

## 11. Story、Task 与待设计事项

默认不创建独立 `Design Story` 类型。交付结果明确且实施属于当前 SOW 时，创建正常实施 Story，并在
其下按需要生成 `Design` 类型 Task，例如架构方案设计、专题调研或 PoC。

规则如下：

- Design Task 必须属于受该决策影响的实施 Story；
- Design Task 通过 AC 引用或依赖关系关联其支持的实施结果；
- 跨多个 Story 的设计事项只计算一次，由一个主 Story 承载，并记录其他依赖 Story；
- 常规、已包含在实施基础单元中的设计活动不重复计价；
- 只有可独立估算的架构设计、专题调研、PoC 或关键方案决策才创建 Design Task；
- 只有设计成果本身独立采购、独立验收且实施不在本 SOW 中时，才创建独立普通技术 Story；
- 设计结论突破既定系统、接口、数据、容量或责任边界时，触发变更评估。

例如：

```text
Story：完成客户主数据跨系统同步
  |- 架构方案设计 Task
  |- 接口或适配实现 Task
  |- 数据处理 Task
  `- 联调验证 Task
```

## 12. 自动审核与阻断

工作流不再设置阶段审批、Batch 确认或 packet SHA 批准。所有受影响切片完成后，只执行一次自动终审：

```text
编译全部受影响切片
  -> 机械校验引用与数据完整性
  -> 一次跨层终审
  -> 发布稳定数据和 Package
```

审核结果只有：

- `PASS`：直接生成完整 SOW；
- `PASS_WITH_NOTES`：在固定边界内生成完整 SOW，并披露未决事项；
- `BLOCKED`：无法形成可信范围或估算时停止。

### 12.1 固定边界

`PASS_WITH_NOTES` 不是无限责任或无条件估算。插件必须把未明确内容转化为：

- 估算假设；
- 客户及第三方责任；
- 明确排除项；
- Design Task；
- 估算适用范围；
- 触发重新评估或变更请求的条件。

详细设计缺失、接口字段未定、技术产品未选型、部署参数待确认等，默认不构成阻断。只要业务结果、
系统范围、责任和估算边界能够确定，就继续生成。

### 12.2 `BLOCKED` 门槛

只有同时满足以下条件才允许 `BLOCKED`：

1. 无法建立可信的固定范围边界；
2. 不同解释会实质改变 Feature、交付责任、验收结果或估算；
3. 无法通过假设、排除项、责任或 Design Task 安全承接。

典型阻断包括：

- 缺少当前项目模式的强制输入；
- 文档损坏、加密或无法读取；
- 项目模式、范围或关键责任无法识别；
- PRD/HLD 存在无法自行裁决的实质冲突；
- 未知设计会改变系统数量或工作规模，且无法限定；
- SOW 模板无法安全计算或渲染。

发生阻断时，不覆盖上一次有效结果；插件一次性汇总最少量问题。用户补充后，从受影响切片继续，
不重新要求确认已经有效的内容。

## 13. 输出合同

每次成功执行都生成：

```text
sow.xlsx
sow-notes.md
```

### 13.1 `sow.xlsx`

工作簿是可离线评审、估算和签署的交付包。基础人天、任务规则、复杂度、SIT、UAT、风险、公式和
取整规则只来自 SOW 模板。生成器必须保留命名 Table、公式原型、样式、行高、自动筛选和跨 Sheet
引用，并在生成后复读验证。

### 13.2 `sow-notes.md`

配套说明每次都生成；没有重大未决事项时明确写明。它至少包含：

- 对应输入 revision、文件版本和适用关系；
- As-Is / Effective Start 的证据边界；
- 关键解释和有实质影响的推断；
- 估算假设及适用范围；
- Design Task 和待完成设计；
- 客户、供应商和第三方责任；
- 外部系统责任和排除范围；
- 输入冲突及采用的处置；
- 尚未明确的 NFR；
- 风险和变更评估触发条件；
- 往期 SOW 与本次范围的承接关系。

所有 `PASS_WITH_NOTES` 事项都必须进入该文档，不能只保存在内部日志。

### 13.3 用户可见执行摘要

命令完成后只汇报：

- `PASS` 或 `PASS_WITH_NOTES`；
- 本次新增、更新、删除的 Feature 数量；
- 被重新计算的 Story 和 Task 数量；
- SOW 与配套说明的位置。

自动生成不代表客户已经签署、接受或赋予 SOW 法律效力。

## 14. 项目目录

目标项目结构：

```text
.ai-sow/
|- current.json
|- inputs/
|  |- pending/
|  `- revisions/
|     `- 000001/
|        |- manifest.json
|        |- answers.json
|        |- sources/
|        `- anchors.json
|- generations/
|  `- 000001/
|     |- manifest.json
|     |- data/
|     |  |- scope.json
|     |  `- delivery.json
|     `- output/
|        |- sow.xlsx
|        `- sow-notes.md
`- work/
```

- `current.json` 指向最近一次成功 generation 及其输入 revision；
- `pending/` 保存尚未成功发布的本次输入；
- `revisions/` 保存不可变有效输入快照；
- `generations/` 保存不可变的稳定 Bundle、交付包和 generation manifest；
- `work/` 只保存本次候选数据和临时审计信息。

候选数据、审核和渲染全部在 `work/` 中完成。全部通过后，将输入 revision 和 generation 作为不可变
目录发布，最后原子替换 `current.json`。指针切换前的新目录不视为有效；即使进程中断，旧 generation
仍完整保留。成功切换后清空 `pending/`；下一次运行可以清理未被 `current.json` 引用的孤立候选。

用户不需要浏览 generation 结构；命令直接返回当前 generation 下 `sow.xlsx` 和 `sow-notes.md` 的路径。

不再创建 Owner work 目录、review packet、receipt、validation 阶段目录或 reconcile 目录。

## 15. 故障与恢复

- 输入解析失败：保留 `pending/`，报告具体不可读文件，不修改稳定结果；
- 编译或终审失败：保留诊断和 `pending/`，不发布候选 Bundle；
- 工作簿渲染或复读失败：不更新 `current.json`，上一份 generation 和输出保持完整；
- 用户补充阻断信息：合并到 `pending/`，只重算受影响切片；
- 输入未变化：验证当前 hash 后复用现有 Package；
- `work/` 遗留：下一次运行可以安全清理或覆盖，不把它当作有效状态。

面向用户的阻断说明必须聚合、去重并只询问改变结果所需的信息。

## 16. 删除旧流程且不保留兼容

插件尚未发布，本次重构不建设兼容层、迁移器、命令别名、Schema 双轨、功能开关或弃用期。

实现已删除以下公开 Skill：

```text
setup
analyze-requirement
analyze-as-is
generate-design
generate-story
generate-task
generate-sow
reconcile
```

同时删除：

- Owner receipt 和多阶段稳定交接合同；
- review packet、packet SHA 和逐包批准；
- As-Is Batch 问答；
- 阶段 handoff 和独立 `reconcile` 协议；
- legacy fixtures、旧命令文档和兼容测试。

旧实现中仍有效的专业规则、Schema 校验、模板读取和工作簿生成逻辑已经迁移到
`ai-sow:generate` 的内部 Module，但不得保留旧公开流程的形状。插件公共发布面最终只包含：

```text
ai-sow:generate
PRD 标准模板
HLD 标准模板
Greenfield 最小问卷
SOW 模板
```

## 17. 验证策略

### 17.1 Module 测试

分别通过 Interface 测试 `intake`、`scope_compiler`、`delivery_compiler` 和 `package_renderer`，覆盖
正常结果、错误结果和不变量。测试不穿透 Module seam 依赖内部文件结构。

### 17.2 合同测试

覆盖：

- 来源引用完整性；
- Feature、Design、Integration、NFR、Story 和 Task 引用；
- ID 保留、新建和删除规则；
- 受影响闭包；
- 固定边界和 `BLOCKED` 判定；
- generation manifest 对输入 revision、Bundle、模板和输出 hash 的绑定；
- 工作簿公式、Table、样式和跨 Sheet 引用。

### 17.3 增量测试

至少覆盖：

- PRD/HLD 新增、修改和删除；
- 标题移动但语义未变；
- 删除某项设计但保留业务结果；
- 同时删除业务结果和技术设计；
- 一个共享 Integration 或 NFR 影响多个 Feature；
- 无关 Feature 不被重算；
- 新切片未生成的旧 Story/Task 自动消失；
- 输入完全未变化时复用当前结果；
- 仅 SOW 模板变化时只重渲染。

### 17.4 E2E 与故障测试

至少覆盖：

1. Greenfield：PRD + HLD + 最小问卷，一次生成完整 SOW；
2. Brownfield：PRD + HLD + 往期 SOW + 现状增量声明，一次生成完整 SOW；
3. 非阻断缺口生成 `PASS_WITH_NOTES`、Design Task 和配套说明；
4. 真正不可推进时返回 `BLOCKED`，保留 `pending/` 和上一份有效 SOW；
5. 用户补充后自动续跑；
6. 解析、终审或渲染中途失败不污染稳定结果；
7. 任意当前 SOW 能追溯到唯一输入 revision；
8. 插件独立复制后不读取 marketplace 根目录或其他插件文件仍可运行。

## 18. 实施完成条件

实现已按以下行为完成，并由对应 Module、合同、E2E、copy smoke 与仓库验证测试证明：

1. 用户只调用 `ai-sow:generate` 即可完成首次生成、更新和阻断恢复；
2. Greenfield 不要求往期 SOW，也不运行完整 As-Is 调查；
3. Brownfield 缺少适用往期 SOW 时稳定 `BLOCKED`；
4. Brownfield 用往期 SOW 和现状增量声明建立合同 Effective Start；
5. 非标准标题但满足最低语义的 PRD/HLD 可以被接受；
6. PRD/HLD 保持高阶，不要求用户提供内部 Coverage Matrix；
7. 待设计事项成为实施 Story 下的 Design Task，不默认创建 Design Story；
8. 非阻断缺口以固定边界生成 `PASS_WITH_NOTES`；
9. 只有无法建立可信范围或估算边界时才询问用户；
10. 每次影响范围的有效输入提交都形成不可变 revision，阻断输入保存在 `pending/`；
11. 输入变化只重算受影响 Feature 闭包，未受影响切片保持稳定；
12. 受影响旧对象在新切片中未生成时自动删除；
13. 失败或阻断不覆盖上一份有效 SOW；
14. XLSX 与 `sow-notes.md` 每次完整重渲染并通过复读验证；
15. 源码、文档、Schema、测试和 fixture 中不存在旧流程兼容分支；
16. 插件独立复制后仍能完成完整 E2E。

## 19. 实施边界

本文件记录本次重构的目标与验收边界；当前运行行为以
[AI_SOW_PLUGIN_DESIGN.md](AI_SOW_PLUGIN_DESIGN.md)、`ai-sow:generate` 的合同和测试为准。
本次实现不提供旧流程迁移或兼容层，也未创建 tag、推送或发布版本。
