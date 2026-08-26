# AI SOW 术语与数据约定

本文件统一当前插件使用的术语。各 Skill 先完成分析、设计或任务拆分，交由用户确认；确认后，再把需要交给下一步和写入 XLSX 的结论整理成规定格式的数据。

## 1. 交付成果与计算依据

| 术语 | 定义 |
|---|---|
| 评审材料 | 各 Skill 在整理正式数据前形成的分析、设计或拆分结果，供用户阅读和确认；具体形式由该 Skill 决定。 |
| 数据整理 | 用户确认后，把评审材料中的最终结论整理为本 Skill 规定的 Schema 数据。结构化数据不能代替分析和判断过程。 |
| 正式交接数据 | 五个 Skill 产生的六份 JSON：来源需求、As-Is、设计、设计产生的技术需求、交付内容和估算输入。 |
| 项目元数据 | 由 setup 初始化的 `.ai-sow/project.json`；只登记 `projectId`、`name`、`pluginVersion`、`sowStandardVersion`，不计入上述六份正式交接数据。 |
| 数据归属 | 每项正式数据只由一个 Skill 负责。后续 Skill 只读取 `.ai-sow/data/...`，不修改上一步的文件。 |
| 影响集协调 | 已有完整下游产物后，用 `reconcile` 在一次整体评审中处理某个 Owner 修正及其固定下游后缀；它不拥有稳定业务数据。 |
| 固定 ID | 使用小写 kebab-case 和对象前缀，并且在项目数据中唯一，例如 `feature-order-status`。所指内容不变时沿用原 ID，内容发生实质变化时新建 ID。 |
| 计算依据 | `.ai-sow/templates/sow-template.xlsx`。任务规则、基础人天、复杂度、系数、公式、取整和最终人天不在 Python 或 JSON 中重复保存。 |
| 配套 Markdown | 与当前 SOW 标准版本一致的任务分类和开发交付人天说明，用于解释分类、填写、验收和估算规则，不另设一套计算口径。 |
| 最终 XLSX | 把六份正式数据写入模板后生成的工作簿。Excel 打开工作簿后按模板公式计算；插件不执行公式，也不读取缓存中的计算结果。 |

数组中的先后顺序就是最终展示顺序。只有 AcceptanceCriterion 使用同一 Story 内从 1 开始的连续 `sequence`；一对多关系由子项保存父项 ID，多对多关系单独保存关联记录。

## 2. 处理顺序与数据路径

```text
setup
  -> analyze-requirement
  -> analyze-as-is
  -> generate-design
  -> generate-story
  -> generate-task
  -> generate-sow
```

| 负责 Skill | 正式输出 |
|---|---|
| `analyze-requirement` | `.ai-sow/data/analyze-requirement/requirements.json` |
| `analyze-as-is` | `.ai-sow/data/analyze-as-is/asis.json` |
| `generate-design` | `.ai-sow/data/generate-design/design.json` 与独立的 `requirements.json` |
| `generate-story` | `.ai-sow/data/generate-story/delivery.json` |
| `generate-task` | `.ai-sow/data/generate-task/estimate.json` |

`setup` 写入项目元数据并复制模板；`generate-sow` 生成待确认的交付文件。两者都不负责业务分析。

普通首次生成仍按七阶段顺序逐项完成。上游修正发生在已有完整产物之后时，用户可显式调用
`reconcile`：Owner 仍分别拥有业务语义、稳定路径和确定性 validator，但不再要求用户逐阶段重启
session。当前 Stage 在批准前按固定后缀完成各 Owner 的 `CHANGED/NO_CHANGE` staged pass、SOW
package 复读及 canonical redo/diff/risk，并由完整 packet 绑定；一个 fresh-context Reviewer 与一次
用户批准绑定同一 packet SHA-256，批准后只做 check/publish。六份稳定 JSON 集合保持不变。

五个专业 Owner 都遵守 candidate-first 生命周期：由当前 Stage 开展分析、设计或拆分，并在 work 目录提前形成和机械校验结构化
candidate，再确定性生成 review 投影、风险摘要和 hash-bound review packet。packet 绑定本 Owner
的 named inputs、candidate、context manifest/fragments、review 与风险摘要，供唯一 fresh-context
Reviewer 与用户确认；它不是稳定 JSON，也不能代替专业分析。用户批准精确 packet 后才按 candidate
原字节发布稳定交接数据，任一绑定字节变化都必须重新整体评审和批准。

## 3. 需求

| 术语 | 定义 |
|---|---|
| 原始输入 | 用户提供的文件、文本、访谈或仓库，只在处理过程中读取，不写入正式数据或交付文件。 |
| normalizedItem | 从来源材料中抽取、合并并去重后的最小条目，用于记录每项来源需求对应哪些原始材料。 |
| 来源处置 | `analyze-requirement` 的 work-only 完整来源检查表；把决策相关陈述唯一分类为 `BUSINESS / DESIGN_INPUT / SCOPE_BOUNDARY / EXCLUDED`，由 review packet 绑定并投影到正式 review，但不新增稳定 JSON。 |
| Epic | 围绕同一业务结果或技术目标的一组 Feature。 |
| Feature | 可以独立纳入、排除、延期和评审的最小需求范围；每个 Feature 只属于一个 Epic。 |
| 来源业务需求 | `SOURCE_INPUT` BUSINESS Epic 与 Feature，由 `analyze-requirement` 负责，每项需求都要关联相应的 normalizedItem。 |
| 技术需求 | `SOURCE_INPUT / DESIGN_DERIVED` TECHNICAL Epic 与 Feature，由 `generate-design` 负责；设计产生的技术需求必须对应到设计决策、适用的有效起点和具体原因。 |
| 需求合并结果 | 后续 Skill 在内存中按“来源需求在前、设计产生的技术需求在后”的顺序合并；不另存第三份 merged requirements。 |

`generate-design` 不追加或改写来源业务 requirements。它从已登记原始来源读取 Requirement review 中标记的 `DESIGN_INPUT`，再自行确认并形成 `SOURCE_INPUT` TECHNICAL 需求；来源处置摘要不能替代原文证据。发现业务需求变化时，退回 `analyze-requirement` 处理；经来源确认或由设计产生的技术需求，写入 `generate-design` 自己的 `requirements.json`。

## 4. As-Is 与设计

| 术语 | 定义 |
|---|---|
| As-Is 调查 | 独立判断当前能力、系统交互、基础设施、承诺变化、证据和有效起点的调查工作。可以根据需要使用搜索、语言工具、CodeGraph、接口说明、配置、部署材料或访谈。 |
| Topic Assessment | 每次 As-Is 对九个 Topic 各给出且只给出一条评估：系统边界与参与方、能力与流程、应用与组件、集成与外部依赖、数据与存储、平台/环境与部署、安全与合规、运维与质量、交付与约束。状态为 `ASSESSED / NOT_APPLICABLE / INSUFFICIENT_EVIDENCE`。 |
| As-Is Item | 已存在或实际运行的 `CAPABILITY / COMPONENT / INTEGRATION / DATA_ASSET / INFRASTRUCTURE / CONTROL / PROCESS / CONSTRAINT` 当前事实。 |
| Commitment | 从往期 SOW 等有效承诺提取的 `ADD / REPLACE / RETIRE` 变化；同时记录 `implementationStatus`（实现对账结果）与 `treatment`（范围处理方式）。 |
| Effective Start | 项目预计有效起点，只能由当前 Item 与 `EXPECTED_BEFORE_START` Commitment 组成。 |
| Carry-forward | `treatment = CARRY_FORWARD` 的未完成承诺；进入 Coverage、设计和 Story gap，属于本期仍需交付的范围，不是 Effective Start。 |
| As-Is Coverage | 对每个来源 Feature 给出 `COMPLETE / PARTIAL / MISSING`、相关有效起点和理由。`MISSING` 是合法事实。 |
| Evidence | 后续判断所需的依据。问卷中已经确认的答案整理为 `QUESTIONNAIRE` Evidence；正式数据不保存完整工具输出、源码、凭证、绝对路径或缓存。 |
| Uncertainty | 调查和定向问卷后仍未回答、相互矛盾或证据不足的问题。每条记录显式保存 `affectsEstimate`；答案可能改变范围、责任、设计、交付对象、工作量或人天时必须为 `true`，并在关闭前阻止正式估算。只有确认不影响估算时才可为 `false`。`INSUFFICIENT_EVIDENCE` Topic 必须关联 Uncertainty。 |
| DesignItem | 目标设计中的 `COMPONENT / FLOW / DATA / INTEGRATION / INFRASTRUCTURE / QUALITY` 对象。 |
| ArchitectureDelta | 相对于有效起点的 `NEW / ADOPT / ADJUST / REPLACE / RETIRE` 设计变化；它不是 Task 工作模式，`REPLACE / RETIRE` 到 Task 阶段要拆成明确的基础单元。 |
| ScopeDecision | 对每个来源 Feature 或设计产生的 Feature 给出 `IN_SCOPE / FULLY_COVERED / OUT_OF_SCOPE` 结论和理由。 |
| HLD Coverage | 目标设计批准门禁。每个 Feature 恰有 ScopeDecision；`IN_SCOPE` 有 Design Item 覆盖，`FULLY_COVERED` 有 Evidence 支持的 Effective Start 和具体完整覆盖理由。 |
| Go-live Assessment | 上线批准门禁。固定处置生产范围、环境配置、部署切换回滚、数据迁移、生产验证、可观测性、运维移交、上线后支持、用户赋能和遗留退役十项 Concern，并明确责任边界和依据。 |

As-Is 不要求所有工具使用同一种中间数据格式，也不限定必须使用某种调查工具。调查顺序为：先看仓库和文档，再看接口约定、配置、部署和运行证据，最后通过定向问卷补充信息。完整调查过程保留在该 Skill 自己的 work 目录中；正式 `asis.json` 只保存后续步骤确实需要的结论。

`.ai-sow/reviews/generate-design.md` 以精确 `PASSED` 声明和固定七列矩阵保存两个批准门禁。它不是第七份正式 JSON；门禁语义只由 `generate-design` validator 判断并绑定到 receipt。`generate-story`、`generate-task` 和 `generate-sow` 只匹配当前 Design handoff，不复制或重放 HLD/Go-live 业务判断。
Design review 的对象计数由 renderer 从当前 Design/TECHNICAL candidate 写入唯一
`Structure Counts` 声明；review-source 自由文本不得重复手写这些计数，避免专业整体修正后出现
旧计数与候选不一致。

## 5. 交付 Story

| 术语 | 定义 |
|---|---|
| Delivery Gap | 一个 `IN_SCOPE` Feature 从有效起点到本期交付目标仍缺少的能力。 |
| SOW Story | 可独立交付、验收和结算的条目；恰有一个来源 Gap。 |
| AcceptanceCriterion | 一行一个可独立通过或不通过的可观察结果。描述结果，不描述实现 Task。 |
| Integration | 独立于 Story 类型和 Task，记录一次有明确方向的系统交互；保存来源、目标、触发、`INBOUND / OUTBOUND`、目的和 `INTERNAL / EXTERNAL` 责任归属，并关联 Story。登记 Integration 不等于已经生成集成 Task。 |
| UAT 适用性 | Story 对业务 UAT 是否适用的明确判断；不从 Story 类型或 Task 任务族推导。 |
| 假设/风险 | 保存类型、名称、触发条件、责任边界、`已明确 / 待确认` 状态和处理方式，并通过关系行关联 Story。 |

每个 IN_SCOPE Feature 至少有一个 Gap，每个 Gap 至少有一个 Story，每个 Story 至少有一条 AC。Story 不保存类型，可以包含任意任务族的 Task。Story/AC 获批后作为业务交付合同保持只读；Task 与同 Story AC 是多对多覆盖，Task 只能满足合同，不能反向修改 Story/AC。Task 反馈的实现机制缺口由 `generate-design` 在既有交付结果内细化时，`generate-story` 只做 `NO_CHANGE` rebind；只有用户明确批准交付结果变化后才重新评审 Story/AC。

## 6. Task 与估算输入

| 术语 | 定义 |
|---|---|
| Task | Story 下直接估算人天的最小明细；一行对应一个基础单元实例需要完成的全部工作。 |
| 任务类型 | `任务族 → 基础单元` 两层目录；Task 只选择基础单元，系统根据基础单元自动确定任务族。 |
| 任务族 | 用于组织、汇总和查漏补缺的上层分类，不由 Task 人工填写，也不直接参与基础人天查找。 |
| 基础单元 | 有明确计数口径和具体工作内容的估算对象；一个基础单元实例对应一个 Task。 |
| 发布切换 | 一个统一窗口、统一责任范围和回滚方案的生产发布实例；上线计划、Go/No-Go、演练、实际部署/切换、检查、回滚和确认合并估算，每个 Story 最多一个。数据迁移始终独立。 |
| 问题处理 | “问题诊断与恢复”覆盖分诊、证据、诊断和恢复；“同一根因问题整改”只覆盖确认根因后的实现与验证，同一 Story 不重复计算诊断。 |
| 用户培训与使用材料 | 面向一个明确用户群体及一项连贯能力的材料与培训交付；不包含运维交接、翻译或长期培训运营。 |
| 工作模式 | 只允许 `新建 / 调整 / 接入复用`。新建是新增一个基础单元实例；调整是保留现有对象及其主要范围并进行修改；接入复用是不改动已有能力本身，只完成本项目一侧的接入和适配。 |
| 替换/退役变化 | 不是 Task 工作模式。替换按替代功能、数据迁移、发布切换和系统功能下线拆分；单纯下线使用“系统功能下线”。 |
| 工作模式理由 | 说明相对 Effective Start 为什么是新建、调整或接入复用，并引用与当前 Task 对象语义相关的现状依据；测试、迁移和切换的调整还要指出被修改的既有资产。 |
| 工作模式证据 | `调整 / 接入复用` 的结构化 `workModeEvidence`。保存一项已匹配 Effective Start 的 ID 和精确名称；`接入复用` 还保存非空 `projectSideWorkTypes` 及由它确定性生成的 `projectSideWorkCommitment`，明确本项目负责并交付的注册、配置、封装、映射、适配、认证、租户设置、权限设置或专项验证工作。 |
| 复杂度 | 按当前基础单元自己的标准判断为 `S / M / L`；`X` 表示需要继续拆分、澄清，或先做调研和架构设计，不能进入正式 JSON 数据。 |
| 复杂度理由 | 仅 S/L Task 保存，说明哪些已知事实使当前实例低于或高于默认 M 档；不是对标准的复述。M Task 不保存。 |
| 基础人天匹配 | 基础单元配置表每行直接提供“新建 / 调整 / 接入复用”三个 M 档人天列；正数表示组合可用，`❌` 表示不适用。数值缺失时校验不通过。复杂度系数必须为正数且状态为固定规则、已校准或已批准；工作模式不使用全局系数。 |
| 集成 Task | 基础单元为“内部系统对接”或“外部系统对接”的 Task；通过 `integrationId` 实现且只实现一个 Integration。每个需要交付的 Integration 都有且只有一个集成 Task。 |
| SIT 判断 | 集成 Task 触发 SIT；仅有 Integration 记录时不直接触发。 |
| 最终人天 | XLSX 按“M档基础人天 × 复杂度系数”计算 Task 人天，并继续计算 SIT、UAT、风险、取整和总计。结构化 JSON 不保存插件计算结果。 |

Task 通过 `matchedEffectiveStartItemIds` 关联 Effective Start：“调整 / 接入复用”至少引用一项；“新建”通常可以不填，但数据迁移、系统功能下线、同一根因问题整改，以及涉及现有运行能力的发布切换，仍要引用相关现状。Effective Start 再通过 `sourceItemIds` 和 `commitmentIds` 关联当前事实以及预计在项目开始前完成的承诺。

“接入复用”只有在本项目侧存在可独立估算的注册、配置、封装、映射、适配、认证、租户、权限或专项验证工作时才成立。其 `workModeRationale` 使用固定格式 `<有效起点名称>保持不变；本项目负责并交付：<中文工作类型>。`，必须与结构化工作类型及承诺完全一致，不解析任意自由文本来判断责任。普通依赖引入、常规调用或直接按既有约定使用不单独生成 Task。任何 `affectsEstimate = true` 的未关闭 Uncertainty 都会阻止正式估算和 XLSX 生成；`impact` 只负责解释影响，不作为关键词门禁。

一个 Task 只能包含一个基础单元实例、一种工作模式和一个复杂度结论。重复实例拆成多个 Task；一个 Task 可以包含多少工作，以基础单元的计数口径和复杂度标准为准。必要的设计、实现或配置、开发自测、单元级验证、说明和基本联调，都计入该基础单元，不再固定拆成一条“设计”Task 和一条“实现”Task。

识别 Integration 不依赖 Story 类型。先根据已有证据登记 Integration；是否需要生成“内部系统对接”或“外部系统对接”Task、使用哪种工作模式、复杂度如何，都在拆分 Task 时确定。集成 Task 必须引用已经登记的 Integration，不能为了生成 Task 而倒推一个没有依据的 Integration。

`generate-task` 的 `read_template.py` 只读取项目模板中合并后的基础单元/人天配置表和项目参数里的复杂度系数；`validate.py` 检查 Story/As-Is 引用、Story 是否拆出了必要 Task、工作模式依据、S/L 偏离理由以及模板组合。两者都不调用 setup 或 generate-sow 的代码。

## 7. 项目文件、Skill 隔离与交付

setup 由当前 Stage Agent 只调用一次平台 bootstrap；它在插件安装副本内自动准备固定 uv、managed
Python 3.12、锁定依赖和 `.venv`，再调用确定性 Module 创建项目目录、四字段项目元数据和模板，并在
返回前复读 Project Schema 与模板。普通用户无需预装 Python/uv，后续 Skill 直接使用插件 `.venv`
的跨平台 Python 路径。完整项目只读验证，合法的项目级模板定制按当前项目模板合同复读，不与
bundled template 强制比较字节；不完整、损坏或身份冲突项目 fail closed。setup 不 repair、不自动
迁移，也不接入 Repo 或往期 SOW。`analyze-as-is` 在开展现状调查时按需登记 Repo、往期 SOW、配置、
部署材料及其他现状证据，并负责自己输入目录中的文件和元数据。没有 Repo 或往期 SOW 也可以正常
开展调查，但必须说明实际检查了哪些现状材料。

`.ai-sow/project.json` 保存 `projectId`、`name`、`pluginVersion` 和 `sowStandardVersion`。每个 Skill 只写自己的 work、review、data、validation 或 output 目录。

Skill 之间：

- 不跨 Skill 导入 Python 模块；
- 不调用另一个 Skill 的脚本；
- 不读取另一个 Skill 的 Schema、Fixture、测试或资源文件；
- 只通过规定的正式数据路径、批准 review、validation report/receipt、ID 和必要字段进行协作；
- 只允许调用插件级 `runtime/project_io.py` 与 `runtime/handoff.py` 的纯技术接口，HLD/Go-live 等领域规则保持 Owner Skill-local。

`reconcile` 是唯一 Agent-level 协调例外：当前 Stage 可读取受影响 Owner 的 `SKILL.md` 并在批准前
执行其公开命令；完整 staged closure 只创建一个 fresh-context Reviewer。批准后 Skill-local
publisher 只验证 packet/hash 并前向发布。Skill Python 仍不跨 Skill import、读取 Schema/fixture
或共享业务规则；Owner 只写自己的 review/candidate/output/receipt，Task 不能修改 Delivery、Story
或 AC。协调合同公开五个 Owner 的精确 Adapter 路径和 `--staging-root` 参数；`NO_CHANGE` 从 base
Owner receipt 与 staged upstream receipt 构造 before/current 绑定，只先 stage review 再执行
`rebind`。任一失败 receipt 都终止当前 run 并用新 run ID 整体重跑，不在已污染的 staging 内试错；
未覆盖路径由 flat ProjectView 回退读取 base，无需复制影响集之前的稳定产物。
reconciliation 的第一条项目命令固定为只读 `inspect`，集中投影固定 Owner 后缀的 baseline hash、
validation inputs、candidate/review 路径与 review ID 声明；它不写项目、不调用 Owner，也不解释业务。
`reconcile.py --mode prepare-no-change` 从 base review/receipt 与 staged upstream receipt 自动投影
完整 Stable ID 和 hash binding，`stage-owner` 只做 flat staging 写入；Owner validator 仍由 Stage
直接调用。每一动作必须是独立 fail-fast tool call，reconcile Python 不执行/import Owner、不读取
Owner Schema，也不形成通用 Owner runner；命令统一使用 setup 建立的 `<plugin-root>/.venv` Python
和绝对脚本路径，避免 PATH uv、shell 临时赋值展开和重复 cache path 拼写。所有 Adapter/Owner 命令
接收绝对 `--project-root`，直接 Python 调用不改变项目 cwd。
任何 staging 前先用只读 `inspect-work` 固定 CHANGED candidate hashes、写完整体 `review.md`，再用
`prepare-changed` 绑定 CHANGED work review；整体 review 不存在时所有 projection 准备均 fail closed。
批准后 publisher 的进度对外按全部 manifest operation 计数；`before == after` 的 `NO_CHANGE`
原字节复用路径天然属于完成状态，完整发布后的复查必须返回
`completedOperations == totalOperations`，不能把内部的 changed-prefix 计数暴露成未完成进度。

`generate-sow` 由当前 Stage Agent 直接调用确定性生成器；普通生成不创建模型 Reviewer。生成器先精确匹配五位 Owner 的 0.3 receipt 及其当前 input/review/output 字节，再读取六份正式数据和项目模板填充可扩展的 Table；它不重放上游业务 validator。As-Is 的仓库 `DOCUMENT` Evidence 使用 `repositorySnapshots` 将逻辑 `<repoId>:<anchor>` 重建为 receipt 绑定的项目相对路径，普通项目文档路径保持原值。`90-系统现状` 使用固定九行的 `AsIsTopicTable` 和按明细数量扩展的 `AsIsDetailTable` 写入完整 As-Is；Task 页的“系统现状匹配”显示 Task 对应的 Effective Start。普通文本以 `= / + / - / @` 开头时按文本处理，避免被 Excel 当作公式；公式只能来自模板中的原型行。

生成结果先写入 `.ai-sow/outputs/.staging-*` 临时目录。工作簿复读和 manifest 校验通过后，再把目录改名为 `.ai-sow/outputs/sow-sha256-<generationFingerprint>/`。成功目录包含 `sow.xlsx`、`manifest.json`、六份稳定数据、五份批准评审、五份 validation receipt 和模板副本；相同包逐字节复用，不同内容 fail closed，失败 staging 由本次运行清理。

插件不提供统一 CLI，也不建设共享业务 Python 内核、项目锁、不可变 revision store、活动指针、
自动回滚、自动 Git commit、统一管理的 Python/uv 运行环境、公式执行、OOXML 全量基准或 XLSX
反向导入。`reconcile` 仅使用 work-only run ID、显式 tombstone 和 canonical redo manifest 做单写者
前向恢复；这些不是稳定业务合同或通用事务系统。

Git 只用于普通的协作记录。需要调查本地 Repo 时，由 `analyze-as-is` 执行只读 Git 检查，确认工作树根目录并记录调查时的 `HEAD` revision 和 dirty 状态；它不 clone、不 fetch、不 pull，也不修改目标仓库。
