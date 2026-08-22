# AI SOW v1.3 领域模型、Skill 与工作簿设计

状态：方案已确认，等待文档复核
日期：2026-08-20  
目标插件版本：0.1.0-beta.1
目标 SOW 标准版本：v1.3

## 1. 背景与结论

大规模独立测试发现，问题不只是中文输出不自然。当前实现还存在交付层级与工作簿不一致、Skill 职责交叉、过早接入输入、字段含义丢失、需求理由和 Task 内容套用固定模板，以及把开发期工具带入正式流程等问题。

本设计发生于 AI SOW 首次公开预发布之前。`0.1.0-beta.1` 直接采用新格式，不为内部原型提供兼容层、自动迁移或新旧格式并行处理。

## 2. 目标

1. 统一 EPIC、FEATURE、STORY、AC、TASK、ASIS、INTEGRATION、ASSUMPTION 的业务含义、Sheet 和 ID。
2. 让 `analyze-requirement` 只拥有业务需求，让 `generate-design` 统一拥有技术需求。
3. 让 setup 适合尚不知道代码库上下文的 BA 首次使用。
4. 只有分析结果确有内容时才填写选填字段，不用空泛内容填表。
5. 让设计产生的技术需求理由和 Task 明细如实反映设计与工作内容，不再套用固定模板。
6. CodeGraph 可用时优先使用；不可用时先尝试项目局部安装 CLI，失败后才回退。
7. 正式流程默认不启动服务，不依赖 Testcontainers 或 cachebuster。
8. 每个 Skill 独立负责自己的数据、评审材料和脚本。

## 3. 本次不处理的事项

- 不建设统一 AI SOW CLI 或共享 Python 内核。
- 不让 setup clone、拉取或分析代码库。
- 不在正式数据中保存完整原始文档、源码、工具缓存或凭证。
- 不自动执行工作簿公式，不从 XLSX 反向导入业务数据。
- 不为首次公开预发布前的内部原型数据格式提供迁移工具或新旧格式同时读取的处理逻辑。
- 不要求每个 Story 具有固定数量或固定类型的 Task。

## 4. 问题定性

| 问题 | 定性 | 设计处理 |
|---|---|---|
| CodeGraph 不可用即回退 | 正式流程缺少安装策略 | MCP、CLI、项目局部安装 CLI、`rg` 四级降级 |
| 测试启动 Testcontainers | 目标仓库测试带入，不是插件固有需要 | 默认静态分析，运行验证按需且说明原因 |
| Sheet 与领域类型错位 | 领域模型和数据格式问题 | 全链路改为 EPIC → FEATURE → STORY → AC → TASK |
| `02-故事` 命名错误 | 真实模板问题 | 改为 `02-子需求` |
| 需求描述内容与列名不符 | 真实生成规则问题 | 描述只介绍需求，不混入目标、技术方案或 Task |
| 需求选填列全空 | 来源信息存在，但 Schema 和写入规则没有保留 | 增加选填字段，并按分析结果写入 |
| 子需求列全空、推断理由重复 | 生成规则和质量校验问题 | 选填字段按需生成；产生该需求的理由必须具体 |
| SOW Task 明细普遍一两行 | 单个案例可能正常，大规模同质化不正常 | 不固定任务数，按真实基础单元实例分解 |
| 根目录 AI SOW smoke 脚本 | 存放位置不合理 | 移到插件级测试支持目录 |
| cachebuster 进入测试说明 | 开发期手段泄漏到产品流程 | 正式 Skill 和测试完全移除 |
| setup 与按需安装职责不清 | Skill 职责问题 | setup 只准备基本目录、元数据和模板，专用工具由实际使用它的 Skill 管理 |
| Task 使用数量 | 估算模型掩盖具体工作 | 删除数量，一行一个基础单元实例 |

## 5. 统一领域模型

| Sheet | 对应对象 | ID 前缀 | 负责 Skill |
|---|---|---|---|
| `01-需求` | EPIC | `epic-` | `analyze-requirement` 或 `generate-design` |
| `02-子需求` | FEATURE | `feature-` | 与所属 Epic 相同 |
| `03-SOW主表` | STORY | `story-` | `generate-story` |
| `04-验收条件` | AC | `ac-` | `generate-story` |
| `05-任务明细` | TASK | `task-` | `generate-task` |
| `06-集成点` | INTEGRATION | `integration-` | `generate-story` |
| `07-假设清单` | ASSUMPTION | `assumption-` | `generate-story` |
| `90-系统现状` | ASIS | `asis-` | `analyze-as-is` |

As-Is 中的 Commitment、Effective Start、Uncertainty 和 Evidence 继续使用 `commitment-`、`effective-start-`、`uncertainty-` 和 `evidence-` 前缀，以免不同对象混淆。

Epic 是一组围绕同一业务结果或技术目标的 Feature。Feature 是可以独立纳入、排除、延期和评审的最小需求范围。Story 是相对于有效起点仍需完成、可以独立验收和结算的工作。Story 不再区分类型。Task 是 Story 下直接估算人天的最小明细，一行对应一个基础单元实例需要完成的全部工作。

Integration 作为单独的数据对象保存，不再只是 Story 里的一个字段。它根据已有证据记录一次有明确方向的系统交互，不依赖 Story 类型，也不等同于用于估算的集成 Task。每项 Assumption 只保存一行，再通过关联记录连接一个或多个 Story，避免重复记录同一假设。

## 6. 需求归属与合并使用

### 6.1 业务需求

`analyze-requirement` 只输出 `BUSINESS` Epic 和 Feature。它不识别、不分类、不产出 `TECHNICAL` 需求。

来源文件中可能包含技术约束或已有方案。`analyze-requirement` 登记原始来源，并只建立 BUSINESS 需求与来源材料之间的对应关系，不整理或转换其中的技术内容。相关内容保留在已登记的原始来源中，由 `generate-design` 结合业务需求和 As-Is 读取、判断并记录技术要求来自哪里。

### 6.2 技术需求

`generate-design` 输出全部 `TECHNICAL` Epic 和 Feature：

- 来源中明确提出并经设计阶段确认的技术要求使用 `SOURCE_INPUT` provenance。
- 由目标设计决策新增的技术要求使用 `DESIGN_DERIVED` provenance。

每个 `DESIGN_DERIVED` Feature 必须对应到具体设计决策，并说明：

1. 采用了什么设计决策；
2. 为什么该决策产生此 Feature；
3. 如果不交付会造成什么具体影响。

只替换对象名称、其余内容完全相同的套话不合格。

### 6.3 全量需求

后续 Skill 在内存中合并以下两份正式数据，得到完整需求：

```text
BUSINESS requirements from analyze-requirement
+
TECHNICAL requirements from generate-design
```

两份 JSON 仍由各自的 Skill 负责，不另存第三份 merged requirements。`generate-story`、`generate-task` 和 `generate-sow` 使用相同的合并顺序和规则。

## 7. 字段说明

### 7.1 Epic

- `name`：简洁的需求名称。
- `description`：介绍需求背景、范围和能力，不复述目标结果，不写解决方案或 Task。
- `involvedSystemsData`：选填；只有分析发现明确系统、参与方或数据对象时才生成。
- `targetOutcome`：选填；只有来源能够支持明确目标结果时才生成。
- `commonConstraintsOutOfScope`：选填；只记录适用于整个 Epic 的公共约束或范围外内容。

### 7.2 Feature

- `description`：具体场景、范围和业务或技术能力。
- `involvedSystemsData`：选填；只记录与该 Feature 直接相关的系统或数据。
- `constraintsNfr`：选填；只记录已确认且适用于该 Feature 的约束或 NFR。

选填字段可以不出现在 JSON 中，工作簿对应单元格也可以留空。校验时不要求用 `N/A` 或空泛理由凑数；字段一旦出现，就必须有具体内容，并符合负责该字段的 Skill 所规定的证据要求。

## 8. Skill 职责和处理顺序

```text
setup
  -> analyze-requirement (BUSINESS + 按需澄清问卷)
  -> analyze-as-is (按需接入 Repo、往期 SOW 与现状证据)
  -> generate-design (TECHNICAL + 目标设计)
  -> generate-story (Story、AC、有证据支持的 Integration、Assumption、Risk)
  -> generate-task (基础单元 Task、Integration 与集成 Task 的对应关系、估算输入)
  -> generate-sow (合并数据、写入工作簿并生成交付文件)
```

### 8.1 setup

setup 只创建项目所需的基本目录和文件：项目 ID、名称、插件版本、模板版本、模板和父目录，并检查 Python、uv、锁定依赖以及模板能否完整读写。`.ai-sow/project.json` 不再保存 mode、Repo 或往期 SOW。

setup 不接收 mode、Repo 或往期 SOW，不安装 CodeGraph，不安装 Testcontainers，不使用 cachebuster，也不写业务数据。项目是否具有现有系统、代码库或历史承诺由后续现状调查确定；`GREENFIELD / BROWNFIELD` 如仍用于交付展示，应由 `analyze-as-is` 在完成输入登记后判定并保存。

### 8.2 analyze-requirement

该 Skill 在使用时将需求来源复制或登记到 `.ai-sow/inputs/analyze-requirement/`，保存固定的来源 ID、项目内相对路径和哈希。先判断现有材料是否足以整理业务需求；如果信息不足、含义不清或相互冲突，并且可能改变范围、目标、业务规则、优先级或验收意图，就在 `.ai-sow/reviews/analyze-requirement-questionnaire.md` 生成结构化澄清问卷。

问卷至少包含问题 ID、类型、来源、缺失或冲突之处、业务影响、可选答案、建议选项及理由、用户答案和状态。关键问题解决前不能批准正式业务需求；非关键未知项只有在用户确认默认处理方式后才能转为 Assumption。技术设计问题不在本问卷中解决，交给 `generate-design` 处理。

### 8.3 analyze-as-is

该 Skill 在使用时询问并登记代码库、往期 SOW、配置、部署或其他现状证据。没有代码库也是正常情况，但 Skill 仍需说明实际调查范围，并形成可供设计使用的 As-Is。

### 8.4 generate-design

该 Skill 读取已登记的原始来源、已批准的 BUSINESS 需求与 As-Is，形成目标方案、范围决策和全部 TECHNICAL 需求。技术信息不足时，由它提出有针对性的补充证据要求或设计问题；只有确认涉及业务范围变化时，才退回业务需求阶段处理。

### 8.5 下游 Skill

`generate-story` 形成 Delivery Gap、Story、AC、Integration、Assumption 和 Risk。它根据来源需求、现状和目标设计中的证据记录 Integration，但不判断或生成集成 Task。`generate-task` 拆分基础单元 Task，并根据 Story、Integration 和 Effective Start，为每个需要交付的 Integration 生成且只生成一个“内部系统对接”或“外部系统对接”Task。`generate-sow` 只负责把正式数据写入模板并生成交付文件。

## 9. CodeGraph 和运行验证

CodeGraph 的使用规则由 `analyze-as-is` 负责：

1. 优先使用当前可调用的 CodeGraph MCP。
2. MCP 不可用时检查现有 CodeGraph CLI。
3. 两者都不可用时，在 `.ai-sow/work/analyze-as-is/tooling/` 安装项目局部 CLI，并初始化当前调查需要的索引。
4. 安装和索引成功后必须使用 CodeGraph。
5. 安装、初始化或索引失败后才回退到 `rg`、语言原生工具或其他只读静态方法，并在工作材料中记录原因。

永久安装 MCP 会修改客户端配置，而且通常需要重启，因此不作为本轮调查继续进行的必要条件。用户明确要求永久安装时，可以使用官方安装方式并说明需要重启；本轮调查仍优先使用可以立即运行的 CLI。

AI SOW 默认进行静态调查，不启动应用服务、数据库或容器。只有静态证据无法解决会实质影响设计的重要不确定性，并且针对性运行验证能够回答该问题时，才运行目标仓库已有的测试或探针并说明原因。

Testcontainers 从来不是插件依赖。目标仓库的必要测试自身依赖 Testcontainers 时，才可能作为该仓库验证的间接执行方式。

## 10. Story 和 Task 拆分规则

Story 数量和 Task 数量不设置固定比例。一个 Story 只有一项 Task 可能合理，但大规模 Story 都出现同样的一两项通用 Task 属于质量异常。

Task 删除 `quantity`、`activity` 和人工填写的 `professionalDomain`。一行对应一个基础单元实例需要完成的全部工作，并满足：

- 只有一个基础单元实例、一个明确对象和一个清晰的工作范围；
- 必要的设计、实现或配置、开发自测、单元级验证、说明和基本联调，都计入该基础单元；
- 重复实例拆成多个 Task；一个 Task 可以包含多少工作，以基础单元的计数口径和复杂度标准为准；
- 同一 Task 只有一种工作模式和一个复杂度结论；
- Task 工作模式只允许“新建 / 调整 / 接入复用”；“接入复用”表示不改动已有能力本身，只完成本项目一侧的接入和适配；
- Task 只选择基础单元，系统根据基础单元自动确定任务族；
- “内部系统对接”或“外部系统对接”Task 必须通过 `integrationId` 引用它所实现的唯一 Integration，其他 Task 不保存该字段；
- M 是默认复杂度，不要求理由；S/L 必须说明哪些事实导致当前实例偏离 M，而不是复述标准；
- 无需工作时不生成 Task。

`基础单元 + 工作模式` 决定 M 档基础人天；复杂度按该基础单元自己的标准判断，再使用统一系数。工作模式不使用全局倍率。设计阶段仍可用 `REPLACE / RETIRE` 描述 ArchitectureDelta，但 Task 不保存“替换 / 退役”工作模式：替换要按替代功能、数据迁移、发布切换和系统功能下线分别拆分；如果只是下线，则使用“系统功能下线”。完整的基础单元目录、具体工作内容、复杂度标准、公式和迁移规则见 [Task 估算模型设计](../superpowers/specs/2026-08-21-ai-sow-task-estimation-model-design.md)。每个需要交付的 Integration 必须有且只有一个带 `integrationId` 的集成 Task；如果拆分任务时发现尚未登记的系统交互，要先退回 `generate-story` 或 `generate-design` 补齐。SIT 由集成 Task 触发，UAT 由 Story 明确是否适用；风险和取整仍由正式模板计算。

`03-SOW主表` 的任务明细汇总该 Story 的全部 Task，因此可以是一行或多行，但不能为了套用固定模板而让大量 Story 长期只有完全相同的 Task。

## 11. Skill 文案和工具使用范围

所有 Skill 删除有关开发期缓存、cachebuster、旧版本兼容和迁移的说明。资源路径只说明如何根据当前 `SKILL.md` 找到 Skill 根目录和插件根目录，不介绍插件缓存的实现方式。

通用依赖在 setup 阶段验证。只服务单一 Skill 的专用工具在该 Skill 使用时检查和安装：CodeGraph 属于 `analyze-as-is`；模板读取属于 `generate-task`；交付打包属于 `generate-sow`。

根目录 `scripts/validate_repository.py` 继续负责整个 marketplace。跨越七个 AI SOW Skill 的 `scripts/smoke_plugin.py` 移到 `plugins/ai-sow/tests/support/`，而不是放入任一单独 Skill，以保持 Skill 隔离。

## 12. 工作簿与配套文档更新

所有模板和参考工作簿同步更新 Sheet 名、表名、列头、公式、数据验证和跨表引用。配套 Markdown 标准同步更新领域术语、任务拆分和无数量估算规则，并升级到 v1.3。

生成器不得依赖固定行号或旧 Sheet 名。工作簿只写入两份需求数据合并后的内容，不把合并结果反写到 JSON。

## 13. 验证策略

实现遵循测试先行：

1. 先把现有独立大规模测试暴露的问题固化为失败测试。
2. Schema 测试验证 Epic/Feature 前缀、业务/技术需求归属、选填字段和无 `quantity`。
3. Skill 文案测试验证职责、问卷、CodeGraph 降级、静态优先以及正式措辞。
4. 生成质量测试应能识别空泛的需求理由和机械重复的 Task。
5. 工作簿测试验证 `02-子需求`、列头、公式、Table 和引用。
6. 使用工作簿工具渲染并逐页检查每个 Sheet；检查配套 Markdown 的结构、链接和基础人天矩阵与模板一致。
7. 运行插件全部单元测试、插件 smoke 和 marketplace 仓库验证。

插件测试不启动服务或容器。针对目标仓库的运行验证与插件数据格式测试分开执行。

## 14. 采用的方案和未采用的方案

选择一次性完成整体调整，因为只改工作簿名称，JSON、Skill 和最终交付仍会继续使用互相冲突的术语。

否决以下方案：

- 只改工作簿：无法修复需求归属、Task 数量和输入接入问题。
- 同时支持新旧数据格式：会为尚未发布的版本增加没有实际收益的复杂度和测试工作。
- setup 统一安装所有工具：会迫使 BA 在尚无代码上下文时承担无关依赖。
- 固定每个 Story 的 Task 模板：无法反映真实工作，导致估算失真。

## 15. 验收标准

1. 所有正式数据对象的 ID 前缀与统一领域模型一致。
2. 工作簿使用八个确定的领域 Sheet，其中第二个 Sheet 名为 `02-子需求`。
3. `analyze-requirement` 的正式数据只含 BUSINESS Epic/Feature；`generate-design` 的正式需求只含 TECHNICAL Epic/Feature。
4. 后续 Skill 合并使用两份需求，但不创建第三份 merged requirements。
5. 选填字段缺失时工作簿合法留空，存在时内容具体。
6. `DESIGN_DERIVED` 理由能够关联具体设计决策、原因和影响。
7. Story 的正式数据中不存在 Story 类型；Task 的正式数据、模板和公式中不存在专业域输入、活动、数量字段或数量乘数。
8. Task 一行对应一个基础单元实例，能够表达 Story 的实际交付工作，不再固定为通用的一两行。
9. setup 不接收 Repo、往期 SOW 或 mode；`analyze-as-is` 按需接入这些信息。
10. CodeGraph 安装成功时优先使用；失败后才允许静态回退并记录原因。
11. 插件测试不依赖 Testcontainers、服务启动或 cachebuster。
12. Skill 不包含缓存加载、旧版本迁移或开发期临时处理说明。
