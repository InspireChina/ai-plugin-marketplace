# AI SOW Codex 插件方案

- 状态：当前正式合同
- SOW 标准：v1.3
- 插件合同版本：0.1.0-beta.2
- 适用宿主：Codex；首发支持原生 macOS Apple Silicon 与原生 Windows 11 x64
- 领域语义：[CONTEXT.md](CONTEXT.md)
- 计算权威：[sow-template.xlsx](../skills/setup/assets/sow-template.xlsx)
- 性能合同：[AI SOW 性能优化设计修正](../../../docs/superpowers/specs/2026-08-25-ai-sow-performance-optimization-design.md)

本插件通过七个阶段 Skill，把来源材料和现状证据转换为可评审的专业成果、六份稳定交接数据和
一份权威 XLSX 交付包；另提供一个不属于业务阶段的 `reconcile` 维护 Skill，在已有下游产物后用
一次整体评审协调上游修正的固定影响后缀。

## 1. 流程与原则

```text
setup
  -> analyze-requirement
  -> analyze-as-is
  -> generate-design
  -> generate-story
  -> generate-task
  -> generate-sow
```

1. 五个专业 Owner 都在 work 目录先形成 candidate、评审预览和风险摘要，由当前 Stage Agent 直接运行 Owner-local 确定性 validator、一个 fresh-context Reviewer 审查精确 packet、用户批准 packet hash 后执行原字节发布。普通路径不创建 Worker 或 Validator 叶子 Agent；稳定 JSON 在所有路径上都只能于用户批准后发布。
2. `analyze-requirement` 独占 BUSINESS，`generate-design` 独占 TECHNICAL。
3. 每项稳定事实只有一个 Owner；下游只匹配内容寻址 handoff receipt，并验证自己创建的引用，不重放上游业务 validator。
4. BUSINESS 与 TECHNICAL requirements 仅在内存中联合。
5. XLSX 是任务规则、基础人天、复杂度、SIT、UAT、风险、公式和取整的唯一计算权威。
6. 每个 Skill 独立拥有领域合同、脚本、测试和工作目录；公共 runtime 只提供项目 I/O 与 handoff 技术机制。HLD/Go-live 语义由 `generate-design` 独占并在本 Skill 校验，下游只验证其 receipt。
7. Owner 表示专业规则、稳定路径和写权限，不等于独立 session。普通主线逐阶段运行；已有完整
   产物后的修正由 `reconcile` 的当前 Stage 在批准前完成固定后缀的 Owner staged pass、package 和
   packet，只保留一个完整闭包 Reviewer；批准后只做确定性 check/publish。

## 2. Skill 包结构

```text
plugins/ai-sow/
├── .codex-plugin/plugin.json
├── pyproject.toml
├── uv.lock
├── references/output-language.md
├── runtime/project_io.py
├── runtime/handoff.py
└── skills/
    ├── setup/
    ├── analyze-requirement/
    ├── analyze-as-is/
    ├── generate-design/
    ├── generate-story/
    ├── generate-task/
    ├── generate-sow/
    └── reconcile/
```

每个 Skill 只创建实际需要的 `contracts/`、`scripts/`、`fixtures/`、`tests/`、`references/` 或 `assets/`。脚本不跨 Skill import，不调用其他 Skill 脚本，也不读取其他 Skill 的 schema、fixture、test、reference 或 asset。`reconcile` 的 Agent 可按其合同读取受影响 Owner 的 `SKILL.md` 和项目 artifact，但其 Python 发布器仍只处理技术 manifest。`runtime/project_io.py` 只处理项目相对路径、staging view 和原子单文件写入；`runtime/handoff.py` 只处理 canonical hash、receipt、match、publish 和 `NO_CHANGE` rebind，不包含 Owner 业务语义。

## 3. 项目 seam

```text
.ai-sow/
├── project.json
├── inputs/
│   ├── analyze-requirement/
│   └── analyze-as-is/prior-sows/
├── templates/sow-template.xlsx
├── work/<owner-skill>/
├── reviews/
│   ├── analyze-requirement-questionnaire.md
│   └── <owner-skill>.md
├── data/
│   ├── analyze-requirement/requirements.json
│   ├── analyze-as-is/asis.json
│   ├── generate-design/design.json
│   ├── generate-design/requirements.json
│   ├── generate-story/delivery.json
│   └── generate-task/estimate.json
├── validation/<owner-skill>.json
└── outputs/<package-id>/
```

`project.json` 只有 `projectId`、`name`、`pluginVersion`、`sowStandardVersion`。代码库、往期 SOW、模式与其他现状证据属于 As-Is `analysisScope`。五个 Owner Skill 的成功 validation report 包含 `ai-sow-owner-v1`、validator contract `0.3` 的 named input/review/output receipt；下游只接受当前字节与 receipt 完全匹配的 handoff。

六份 JSON 是全部稳定交接数据。`analyze-requirement-questionnaire.md` 是受控人类决策 seam：不增加稳定文件，也不改变 BUSINESS requirements 的四个顶级数组；默认项进入稳定数据的唯一方式是由 `generate-story` 编译为 delivery Assumption。`generate-design.md` 是批准合同而非第七份稳定 JSON：其中精确的 `HLD Coverage: PASSED`、`Go-live Assessment: PASSED` 和固定十项上线矩阵只由 `generate-design` validator 判断并绑定到 receipt；下游不重放这些门禁。

## 4. 七个阶段 Skill 与一个维护 Skill

### setup

当前 Stage Agent 直接检查并按平台支持方式补齐 uv 与 Python 3.12、准备插件锁定依赖环境，再调用一次确定性 setup Module。该 Module 写四字段项目元数据、复制模板、创建固定父目录，并在返回前复读 Project Schema 与模板 round-trip；不为同一机械结果派发或重复运行叶子 Agent。完整项目只读复用；不完整或冲突项目 `BLOCKED`。setup 不提供 repair、不自动迁移已有项目，也不接收代码库、往期 SOW 或模式。

### analyze-requirement

登记原始需求来源，只识别 BUSINESS Epic/Feature。信息单薄、冲突或歧义会影响业务结论时，生成可回填 Markdown 问卷；关键问题关闭后才能批准稳定需求。需求评审声明问卷路径或 `Questionnaire: NOT_REQUIRED`。每个 `APPROVED_DEFAULT` 保留用户 Answer、决策日期、状态证据和 `ASSUMPTION_CANDIDATE` 处置。技术内容保留在来源中，由设计阶段读取。

五个专业 Owner 共享同一 candidate-first 生命周期，但不共享业务编译器：各自的 `prepare_context.py` 只投影本阶段必要闭包，`render_review.py` 确定性投影专业评审，`validate.py --mode review` 生成 `ai-sow-owner-review-packet-v1` packet；唯一 Reviewer 与用户批准分别用 `ai-sow-owner-reviewer-v1`、`ai-sow-owner-approval-v1` 绑定同一 packet SHA-256，`publish-approved` 复算全部绑定后才发布正式 review、稳定输出与 receipt `0.3`。任一输入、candidate、context、review 或风险摘要字节变化都使 Reviewer 与批准失效。

### analyze-as-is

按需登记代码库、往期 SOW、配置和部署证据，确定模式并调查九个 Topic。CodeGraph 路径为 MCP → 已有 CLI → `.ai-sow/work/analyze-as-is/tooling/` 项目局部安装和索引 → 已记录静态回退。默认不启动服务；运行验证只回答重要且静态证据无法解决的问题。每条 Uncertainty 结构化标记是否影响估算。

### generate-design

读取原始来源、BUSINESS requirements 和 As-Is，形成目标设计、Architecture Delta、Scope Decision 和全部 TECHNICAL Epic/Feature。`SOURCE_INPUT` 追溯来源文档及锚点；`DESIGN_DERIVED` 追溯设计决策、产生原因和缺失影响。`IN_SCOPE` 必须有 Design Item 覆盖；`FULLY_COVERED` 由 Effective Start、Evidence 和具体理由证明，BUSINESS 还要求同组 Effective Start 的 COMPLETE Coverage。Task 反馈的实现机制缺口优先细化已有 Decision、Design Item 或职责相同的 TECHNICAL Feature；没有新的用户批准交付结果时，不新增 Feature，也不反向要求修改 Story/AC。设计评审声明 HLD 门禁，并用固定七列矩阵处置生产范围、环境、切换回滚、数据迁移、生产验证、可观测性、运维移交、上线后支持、用户赋能和遗留退役十项 Concern。

### generate-story

在内存中联合两份 requirements；先验证 Requirement、As-Is 与 Design 的当前 handoff，再只为 `IN_SCOPE` Feature 相对 Effective Start 形成 Gap、Story 和 AC，`FULLY_COVERED` 不生成 Story。Story/AC 获批后是业务交付合同；若 Design 只因 Task 可实施性反馈细化实现机制而交付结果未变，`generate-story` 保持稳定 Delivery 原字节并走 `NO_CHANGE` rebind，不为实现机制新增 Gap、Story 或 AC。它不重新执行 Design 的 HLD/Go-live validator。读取可选需求问卷；问卷缺失或状态不完整时阻塞，每个 `APPROVED_DEFAULT` 恰好编译为一个 Assumption，并在 review 中保留 `Question ID -> assumptionId -> storyIds`。已折入 BUSINESS requirements 的 `CLOSED` 答案不重复消费。Integration 是顶级权威；Assumption/Risk 每个语义只保存一次，通过关系集合连接 Story。

### generate-task

按模板计数口径把 Story 拆为一实例一行的基础单元 Task。从单张配置表读取 37 项基础单元、13 个任务族、三个工作模式的人天列和逐单元 S/M/L 标准，并从项目参数读取复杂度系数；Task 保存基础单元、工作模式、复杂度、理由、Effective Start 引用、`调整 / 接入复用` 的结构化 `workModeEvidence` 和必要的 `integrationId`。接入复用的项目侧工作类型确定性生成标准正向交付承诺和工作模式理由，避免用自由文本推断责任。发布计划与实际切换合并为每 Story 至多一个发布切换 Task，数据迁移独立；问题诊断与根因整改不得重复计价；用户培训使用专门基础单元，未明确购买的上线后支持不得生成。任务族由模板带出，不使用活动、数量、固定任务对或统一工作模式倍率。

`generate-task` 的 `prepare_context.py` 先匹配 As-Is、Design、Story receipt，并把 Delivery、关联
Design/As-Is/TECHNICAL 引用与不含计算值的模板目录投影到 work-only context closure；Delivery 没有
完备 Story→Effective Start 关系时保守保留全部 Effective Start。当前 Stage Agent 只形成
`estimate.candidate.json`，`render_review.py` 从 candidate 与模板确定性投影逐 Task 的计数、包含、
排除和非重复计价边界。`validate.py --mode review` 在批准前完成全部机械校验并生成风险摘要与绑定
context manifest/fragment 的 canonical review packet；唯一 Reviewer 使用不继承完整聊天的上下文
审查该 packet。用户批准 packet SHA-256 后，`--mode publish-approved` 复算 candidate、review、
context、input、Reviewer 与 approval 绑定，再发布正式 review、Estimate 和 receipt。现有
`check/publish/rebind` 继续作为 reconciliation Adapter，receipt contract 仍为 `0.3`。

### generate-sow

当前 Stage Agent 直接调用一次确定性生成器。生成器验证五个 Owner receipt、六份稳定数据、五份批准 review 与项目模板的当前 hash，并把这些获批输入确定性投影、复读和发布为工作簿及自包含交付包；普通生成不创建模型 Reviewer。它不读取上游 schema、不重诊断上游业务语义，也不执行 Excel 公式。SIT 由集成 Task 触发，UAT 由 Story 的 `uatRelevant` 决定。

### reconcile

只处理已经存在有效下游产物后的用户修正。当前 Stage 确认唯一 Owner，按固定阶段顺序读取到
`generate-sow` 的完整后缀，在批准前形成各 Owner `CHANGED/NO_CHANGE` 结论、全部 candidate 与
work-only review projection，并在同一 flat staging view 完成一次前向 pass：`CHANGED` 先 `check`
再 `publish`，`NO_CHANGE` 直接 `rebind` 并物化原 output 字节；最后从完整 staged handoff 生成并
复读 package。Skill-local `assemble` 确定性生成 redo/diff/risk 和绑定 review、Owner artifacts、
receipt inputs、package tree、manifest 的 packet。一个 fresh-context Reviewer 与用户批准都绑定精确
`run-id + packet SHA-256`；任一 staged byte 变化必须重新 packet/复审/批准。批准后 publisher 只执行
hash/check/publish，先发布 package，再按 Owner 顺序前向发布且 receipt 最后写入。它不解释业务、
不建 DAG、不新增稳定 JSON。Story/AC 默认冻结；只有同一 packet 明确列出业务结果 diff 时才允许
Story `CHANGED`，Task 永远无权反向修改 Story/AC。

## 5. 稳定合同与工作簿

| Sheet | 实体 | 关键语义 |
|---|---|---|
| `01-需求` | EPIC | BUSINESS 与 TECHNICAL 联合视图 |
| `02-子需求` | FEATURE | 最小需求范围与来源追溯 |
| `03-SOW主表` | STORY | 可交付、可验收、可结算 |
| `04-验收条件` | AC | 独立可观察结果 |
| `05-任务明细` | TASK | 一行一个基础单元实例 |
| `06-集成点` | INTEGRATION | 顶级集成权威 |
| `07-假设清单` | ASSUMPTION | 一项一行，多 Story 关系 |
| `90-系统现状` | ASIS | Topic、事实、承诺、起点、Coverage、Uncertainty、Evidence |
| `91-项目参数` | PARAMETER | S/M/L 复杂度系数及 SIT、UAT、风险和取整参数 |
| `92-基础人天` | BASE UNIT | 37 项基础单元、13 个任务族、逐单元标准与三个工作模式的人天列 |

选填需求字段只有在内容具体时生成；省略时工作簿留空。`DESIGN_DERIVED` 理由必须关联具体决策、产生原因和缺失影响。Story 不保存类型；Task 不保存任务族、活动、数量或计算人天。模板按基础单元行和工作模式对应的人天列取得 M 档基础人天，再按项目参数中的复杂度倍率计算。

## 6. 发布、隔离与安全

- 输入、输出和 Evidence anchor 使用项目相对路径；稳定数据不保存凭据、绝对路径、源码或完整工具输出。
- setup 和生成器拒绝受管路径越界与符号链接穿越。
- Git 只负责普通协作；插件不 clone、pull、reset、commit 或 push。
- `generate-sow` 在 `.ai-sow/outputs/` 内写入 staging，完成工作簿复读和 manifest 校验后，同文件系统 rename 为 `sow-sha256-<generationFingerprint>` 输出目录；相同内容复用，不同内容拒绝覆盖，失败 staging 由本次运行清理。
- `reconcile` 使用项目内短 staging path、显式 tombstone 和 work-only canonical redo manifest；
  package 先发布，Owner review/output/receipt 再按固定顺序前向写入。它假定单一受支持写入者；
  baseline/after 之外的第三种 hash fail closed。
- 普通 XLSX 文本以 `=`、`+`、`-` 或 `@` 开头时按文本写入；公式只来自模板。

## 7. 验证

每个 Owner 的 validator 检查自己的合同、自己创建的引用和必要上游 handoff；下游 handoff 失败只报告 missing、invalid、stale、unsupported 四类稳定错误。HLD/Go-live 只在 `generate-design` 本地判定。插件测试保持静态，不启动应用或容器。工作簿测试验证八个领域 Sheet、37 项基础单元、13 个任务族、命名 Table、公式原型、引用、可选字段留空、顶级 Integration、单行 Assumption 投影和一实例一行的 Task。

仓库级验证负责插件布局、manifest、资产身份和发布面；七阶段主线与 `reconcile` smoke 位于
`plugins/ai-sow/tests/support/`。

## 8. 非目标

插件不建设统一 AI SOW CLI、共享业务 Python 内核、共享业务 Schema、通用 Owner runner、自动审批系统、项目锁、不可变 revision store、活动指针、对抗同权限竞态的 inode 协议、EXDEV tree copy、自动 Git 操作、公式执行或 XLSX 反向导入。
