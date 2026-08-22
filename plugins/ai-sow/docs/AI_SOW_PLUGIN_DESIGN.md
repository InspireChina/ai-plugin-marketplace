# AI SOW Codex 插件方案

- 状态：当前正式合同
- SOW 标准：v1.3
- 插件合同版本：0.1.0-beta.1
- 适用宿主：Codex；首发支持原生 macOS Apple Silicon 与原生 Windows 11 x64
- 领域语义：[CONTEXT.md](CONTEXT.md)
- 计算权威：[sow-template.xlsx](../skills/setup/assets/sow-template.xlsx)

本插件通过七个自包含 Skill，把来源材料和现状证据转换为可评审的专业成果、六份稳定交接数据和一份权威 XLSX 交付包。

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

1. Owner Skill 先完成专业分析，再请用户评审，批准后才编译稳定数据。
2. `analyze-requirement` 独占 BUSINESS，`generate-design` 独占 TECHNICAL。
3. 每项稳定事实只有一个 Owner；下游只读稳定路径。额外的受控 seam 只有需求问卷中的获批默认项，以及 `.ai-sow/reviews/generate-design.md` 中经批准的 HLD/Go-live 门禁合同。
4. BUSINESS 与 TECHNICAL requirements 仅在内存中联合。
5. XLSX 是任务规则、基础人天、复杂度、SIT、UAT、风险、公式和取整的唯一计算权威。
6. 每个 Skill 独立拥有合同、脚本、测试和工作目录；跨阶段必须完全一致的 HLD/Go-live 语义由插件级 `runtime/review_gates.py` 统一实现，其余校验保持 Owner 内聚。

## 2. Skill 包结构

```text
plugins/ai-sow/
├── .codex-plugin/plugin.json
├── pyproject.toml
├── uv.lock
├── references/output-language.md
├── runtime/review_gates.py
└── skills/
    ├── setup/
    ├── analyze-requirement/
    ├── analyze-as-is/
    ├── generate-design/
    ├── generate-story/
    ├── generate-task/
    └── generate-sow/
```

每个 Skill 只创建实际需要的 `contracts/`、`scripts/`、`fixtures/`、`tests/`、`references/` 或 `assets/`。脚本不跨 Skill import，不调用其他 Skill 脚本，也不读取其他 Skill 的 schema、fixture、test 或 asset；只有设计、Story 和最终生成 validator 共同导入插件级门禁运行时。

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

`project.json` 只有 `projectId`、`name`、`pluginVersion`、`sowStandardVersion`。代码库、往期 SOW、模式与其他现状证据属于 As-Is `analysisScope`。

六份 JSON 是全部稳定交接数据。`analyze-requirement-questionnaire.md` 是受控人类决策 seam：不增加稳定文件，也不改变 BUSINESS requirements 的四个顶级数组；默认项进入稳定数据的唯一方式是由 `generate-story` 编译为 delivery Assumption。`generate-design.md` 是批准合同而非第七份稳定 JSON：下游必须复核其中精确的 `HLD Coverage: PASSED`、`Go-live Assessment: PASSED` 和固定十项上线矩阵。

## 4. 七个 Skill

### setup

检查 Python、锁定依赖和模板 round-trip；写四字段项目元数据、复制模板、创建父目录。不接收代码库、往期 SOW 或模式，不安装专用调查工具。

### analyze-requirement

登记原始需求来源，只识别 BUSINESS Epic/Feature。信息单薄、冲突或歧义会影响业务结论时，生成可回填 Markdown 问卷；关键问题关闭后才能批准稳定需求。需求评审声明问卷路径或 `Questionnaire: NOT_REQUIRED`。每个 `APPROVED_DEFAULT` 保留用户 Answer、决策日期、状态证据和 `ASSUMPTION_CANDIDATE` 处置。技术内容保留在来源中，由设计阶段读取。

### analyze-as-is

按需登记代码库、往期 SOW、配置和部署证据，确定模式并调查九个 Topic。CodeGraph 路径为 MCP → 已有 CLI → `.ai-sow/work/analyze-as-is/tooling/` 项目局部安装和索引 → 已记录静态回退。默认不启动服务；运行验证只回答重要且静态证据无法解决的问题。每条 Uncertainty 结构化标记是否影响估算。

### generate-design

读取原始来源、BUSINESS requirements 和 As-Is，形成目标设计、Architecture Delta、Scope Decision 和全部 TECHNICAL Epic/Feature。`SOURCE_INPUT` 追溯来源文档及锚点；`DESIGN_DERIVED` 追溯设计决策、产生原因和缺失影响。`IN_SCOPE` 必须有 Design Item 覆盖；`FULLY_COVERED` 由 Effective Start、Evidence 和具体理由证明，BUSINESS 还要求同组 Effective Start 的 COMPLETE Coverage。设计评审声明 HLD 门禁，并用固定七列矩阵处置生产范围、环境、切换回滚、数据迁移、生产验证、可观测性、运维移交、上线后支持、用户赋能和遗留退役十项 Concern。

### generate-story

在内存中联合两份 requirements；先复核 HLD/Go-live 门禁，再只为 `IN_SCOPE` Feature 相对 Effective Start 形成 Gap、Story 和 AC，`FULLY_COVERED` 不生成 Story。读取可选需求问卷；问卷缺失或状态不完整时阻塞，每个 `APPROVED_DEFAULT` 恰好编译为一个 Assumption，并在 review 中保留 `Question ID -> assumptionId -> storyIds`。已折入 BUSINESS requirements 的 `CLOSED` 答案不重复消费。Integration 是顶级权威；Assumption/Risk 每个语义只保存一次，通过关系集合连接 Story。

### generate-task

按模板计数口径把 Story 拆为一实例一行的基础单元 Task。从单张配置表读取 37 项基础单元、13 个任务族、三个工作模式的人天列和逐单元 S/M/L 标准，并从项目参数读取复杂度系数；Task 保存基础单元、工作模式、复杂度、理由、Effective Start 引用、`调整 / 接入复用` 的结构化 `workModeEvidence` 和必要的 `integrationId`。接入复用的项目侧工作类型确定性生成标准正向交付承诺和工作模式理由，避免用自由文本推断责任。发布计划与实际切换合并为每 Story 至多一个发布切换 Task，数据迁移独立；问题诊断与根因整改不得重复计价；用户培训使用专门基础单元，未明确购买的上线后支持不得生成。任务族由模板带出，不使用活动、数量、固定任务对或统一工作模式倍率。

### generate-sow

验证六份稳定数据的投影字段、跨文件引用和设计批准合同，并从项目模板复读估算目录，防止直接生成绕过门禁或 Task 校验。它填充模板并生成交付包，不读取上游 schema，也不执行 Excel 公式。SIT 由集成 Task 触发，UAT 由 Story 的 `uatRelevant` 决定。

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
- `generate-sow` 写入唯一 staging 目录，完成复读与引用校验后 rename 为 UUID 输出目录；失败保留 staging 供诊断。
- 普通 XLSX 文本以 `=`、`+`、`-` 或 `@` 开头时按文本写入；公式只来自模板。

## 7. 验证

每个 Owner 的 validator 检查自己的合同与必要上游引用；共享门禁运行时保证设计、Story 与最终 SOW 使用相同的 HLD/Go-live 判定。插件测试保持静态，不启动应用或容器。工作簿测试验证八个领域 Sheet、37 项基础单元、13 个任务族、命名 Table、公式原型、引用、可选字段留空、顶级 Integration、单行 Assumption 投影和一实例一行的 Task。

仓库级验证负责插件布局、manifest、资产身份和发布面；跨七个 Skill 的 smoke 位于 `plugins/ai-sow/tests/support/`。

## 8. 非目标

插件不建设统一 AI SOW CLI、共享业务 Python 内核、共享业务 Schema、审批系统、项目锁、事务回执、崩溃恢复、自动 Git 操作、受管运行时、公式执行或 XLSX 反向导入。
