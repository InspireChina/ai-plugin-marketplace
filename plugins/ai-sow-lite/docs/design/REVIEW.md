# AI SOW Lite · 实现前统一 Review

[设计总览](README.md) · [详细设计目录](detailed/README.md) · [实施计划目录](implementation/README.md)

当前设计已按用户决定收口：**同一人串行使用；金额交给既有模板计算，插件不改模板。** [13 自检结论与已定边界](13-self-review-and-decisions.md) 记录决定及成本取舍；P00/D07/P03 已补齐有限编辑到完整候选的机械构造入口。以下是待实施的设计和计划，Lite Skill/内核仍未实现，本轮未改模板、安装或发布插件。

## 1. 建议的 Review 顺序

本次优先看 [13 已定边界](13-self-review-and-decisions.md) 和下文第9节，再核对 D05/D06/P00/P03 的对应合同。前次资料吸收见 [实施目录第4节](implementation/README.md#4-已落实的资料吸收与验收归属)、下文第3.1节及 [12](12-reference-absorption.md)。两项产品选择已同步到合同，14项实施任务保留，尚未进入实现。

1. [总览](README.md) + [D01](detailed/D01-interaction-and-outcomes.md)：generate 快速初版、允许的输入交互、clarify 有限修改、无定稿。
2. [D04A 单 session 全景](detailed/D04A-single-session-panorama.md) + [D04B 有限环路](detailed/D04B-bounded-loops.md)：各步实际需要什么、上下文怎样累积、哪些地方必须停止。
3. [D02](detailed/D02-shared-data-and-evidence.md) / [D03](detailed/D03-input-analysis-and-exploration.md) / [D05](detailed/D05-clarify-and-change-scope.md) / [D06](detailed/D06-excel-projection-and-delivery.md)：依据、三类 gap、修改范围和 Excel 完整性。正常/异常及用户参与见各专题 Mermaid 流程/时序。
4. [D09](detailed/D09-validation-and-implementation.md)：163 个场景的主责/最早检查点、I1—I4 结果边界。先看收口表和退出判据，无需逐条重复阅读场景文字。
5. [P00](implementation/P00-contracts-and-fixtures.md) + [P01—P04](implementation/README.md)：接口和实施任务是否足以直接编码；观测真实性仍以 [D08](detailed/D08-telemetry-and-performance.md) 为准。

EX01—EX07 是走读/反例，EX06 另有有限只读探针；它们不是插件端到端已执行证据。手填模板已有验证也不代表新投影/保存/Skill 已验证。

## 2. 实施交接包新增的 7 份 Markdown

| 文档 | 内容 |
|---|---|
| 本文件 `REVIEW.md` | 统一阅读顺序、变更清单、重点和仍待实证的事项 |
| [implementation/README.md](implementation/README.md) | 执行依赖、任务关闭方式、授权和范围 |
| [P00-contracts-and-fixtures.md](implementation/P00-contracts-and-fixtures.md) | 版本、CLI payload、小结果、候选/准备记录、摘要/确认/基线、模块接口、真实夹具 |
| [P01-reliable-delivery.md](implementation/P01-reliable-delivery.md) | 5 项任务：合同夹具、输入/保存、Excel、计时事件、独立交付验收 |
| [P02-generate.md](implementation/P02-generate.md) | 3 项任务：文本/XLSX、单 Skill 生成、宿主与基线 |
| [P03-clarify.md](implementation/P03-clarify.md) | 3 项任务：精确差异/确认、独立讨论应用、基线/恢复/使用周期 |
| [P04-scope-and-performance.md](implementation/P04-scope-and-performance.md) | 3 项任务：原型/draft、复杂修改、支持/性能/交付准备 |

这些文档都在本插件 `docs/design/` 下，共14项实施任务，P00 嵌入首次使用它的任务，不额外安排一轮基础平台建设。后续资料评估另新增 `12-reference-absorption.md`，同步本文件、设计总览和 CHANGELOG；不计入上述7份实施交接文件。

## 3. 首次实施交接同步的已有文档

| 文档 | 本次改动 |
|---|---|
| [README](README.md)、[详细目录](detailed/README.md)、[路线图](11-detailed-design-roadmap.md) | 接到统一 review 和实际实施计划；明确当前停在实现前 |
| [D02](detailed/D02-shared-data-and-evidence.md) | 接 P00 的具体编码与 I1/I3 消费者，保留业务数据权威 |
| [D06](detailed/D06-excel-projection-and-delivery.md) | 修正 projection 中 AC 的旧列号 F→D；接 I1 差异验收 |
| [D07](detailed/D07-tools-storage-and-recovery.md) | CLI/编码与 P00 对齐；明确意图在具体应用时封存，避免锁死正常讨论修订 |
| [D08](detailed/D08-telemetry-and-performance.md) | 接 P00 的纯语义大活动埋点入口，区分观察时刻与真实模型耗时 |
| [D09](detailed/D09-validation-and-implementation.md) | 接 I1—I4 的具体实施任务，补最小共用合同模块/Schema 的文件归属 |
| [07 剩余验证](07-gaps-and-decisions.md) | 补 G01—G17 的首个实施消费者，修正 G14 提问次数表述 |
| [CHANGELOG](../../CHANGELOG.md) | 记录新增实施交接包，区分计划和实际完成 |

未改 `assets/sow-template.xlsx`、现有模板测试、旧 ai-sow 实现或 marketplace 发布文件。

### 3.1 本次执行计划收口：更新10份，未新增文档

| 更新文件 | 本次落实的内容 |
|---|---|
| [P00](implementation/P00-contracts-and-fixtures.md) | 用户输入、后续答复、独立期待与预制候选的隔离；评价文件最小字段和来源定位，避免把渲染预制答案当真实生成 |
| [P01](implementation/P01-reliable-delivery.md) | 隔离环境/编码/实际路径迁入测试及完整副本验证，保持首个可靠 Excel 里程碑 |
| [P02](implementation/P02-generate.md) | 三类范围/NFR 承载、AC 语义、标准单元/交叠和历史读取的专业指引；五组真实输入、必要对照、默认 M 与首批读取成本记录 |
| [P03](implementation/P03-clarify.md) | 已有证据误读、档位答复、程序引用错误的归因及有限修改，明确具体差异与未改对象验收 |
| [P04](implementation/P04-scope-and-performance.md) | 原型观察反例、集成/同步和迁移/核验等成果边界、共享/交付变化及真实性能对照 |
| [实施目录](implementation/README.md)、[12](12-reference-absorption.md) | 吸收内容已落到任务的对应表、首个里程碑和执行起点 |
| 本文件、[设计总览](README.md)、[CHANGELOG](../../CHANGELOG.md) | 当前状态、变更清单与统一 review 导航 |

本次 review 核对三点：专业方法是否具体而保持 Agent 自主；首批输入/反例是否能暴露误判且不泄露答案；修改及探索是否仍有有限出口。无新增运行时阶段、业务字段、估算参数、资源审批或默认 Reviewer；所有实现复选框仍未完成。

## 4. 优先核对的六个设计边界

| 重点 | 本稿采用的结论 | 位置 |
|---|---|---|
| 专业自由度与稳定性 | Agent 自主安排分析/探索/分片；程序只控制文件/引用/范围/生效，不加入领域阶段运行器 | D04/D07、P00/P02 |
| 快速出稿与未知 | 基础不足退出；复杂度不明 M，候选实例不明新建+问题，其他合法缺值留空；没有为定档反复找证据 | D01/D04B、P01/P02 |
| 金额职责 | 插件只写定性输入并保留原公式；业务缺口在独立说明中呈现，不控制金额、完整性或部分汇总 | D02/D06、I1.1/I1.3 |
| 修改的真实范围 | 单人串行；工具从有限编辑构造候选与精确计划，确认后复用；过期基线直接拒绝，不自动重建 | D05/D07、P00/P03 |
| 上下文与资源 | 单 session 先测真实输入/回显/回读/生成成本；有界循环减少浪费，usage 缺失不估填，不增加 token 审批 | D04A/D04B/D08、I1.4/I2.3/I4.3 |
| 测试时机与复用 | I1.1 前置最小候选/usage 探针；I1 测原模板填值/保存，I2 接真实生成，I3 测串行修改，I4 扩组合和长材料。复用旧机械证据 | D00/D09、P01—P04 |

## 5. 当前仍需要实证的事项

两项范围决定和机械构造接口已写入设计，以下事项仍需实证。下列验证不能靠文档审阅代替，也不变成插件用户的新开场问卷：

- 原模板填值、真实输入空白、独立问题/全文、Office 后公式/OOXML 保留及原生打开：I1.3/I1.5。
- 本地锁/指针生效、崩溃和取消传播、有限编辑构造/确认及过期基线拒绝：I1.2/I1.5/I3.3。
- 真实 Agent 的三类需求识别、稀疏历史匹配、输入充分性和有限循环遵守：I2.2；复杂组合 I4.1/I4.2。
- 宿主逐步 usage 的真实粒度、请求边界、版本适配与实际提速：I2.3/I4.3，G12 保持开放。拿不到逐步数值要报告真实能力和缺口，不能改称目标已满足。

已定边界及机械接口同步后，执行起点仍为 **I1.1**：先取得最小候选及宿主能力探针，再按依赖做到第一份真实重算的可靠交付；本轮没有自动进入实现。

## 6. 首次文档交接的验证记录

已检查相对链接/锚点、JSON 示例、Python 代码片段语法、18 对 Mermaid 正文与图源、163 个场景的唯一主责/最早增量、14项实施任务与依赖，以及新增/修改文件清单。模板 SHA-256 保持 `6abc55d44bc66476a60c2251e18c0dfdb66709e07539c246dfdec3a0373f5332`；没有运行计划中的 Lite 命令或声称新能力已通过。

仓库根42项测试、仓库验证器和旧 ai-sow 独立副本 smoke 通过。扩展执行旧插件全目录 pytest 的结果为 **537 passed、4 skipped、2 failed**；两项失败均在旧 `plugins/ai-sow/tests/test_architecture.py`：

- `test_runtime_is_plugin_shared_owner_agnostic_infrastructure`：现有 runtime 包含 findings.py，测试的精确模块集合未包含它。
- `test_all_professional_owners_freeze_owner_local_candidate_first_interface`：测试要求的“五个 fragment 各读取且只读取一次”文本在现有 generate-task Skill 中不存在。

相关测试、runtime 文件和 Skill 与当前 HEAD 逐字节一致，旧插件没有本轮修改；因此单列为仓库基线检查问题，没有在 Lite 设计任务中改动。上述结果不等于所有仓库测试通过，也不代替后续 Lite 的实际实现验证。

## 7. 本次执行计划同步的验证记录

- 更新10份已有 Markdown，未新增文件；模板与非文档文件保持原字节。检查42份设计/变更文档的423个相对链接及锚点、6段 JSON、13段 Python 示例语法，14项任务及其未完成状态；差异空白检查通过。
- `uv sync --locked`、仓库根42项测试、仓库验证器和旧插件独立副本 smoke 通过。完整旧插件 pytest 再次为 **537 passed、4 skipped、2 failed**，仍为第6节的两项架构基线问题；相关文件重新与 HEAD 对照一致。
- 本轮没有执行尚未实现的 Lite 命令，也没有把合成夹具方案或专业指引视为语义/性能实测。执行计划已可统一 review，实施起点仍为 I1.1。

## 8. 首次可行性、一致性与复杂度自检记录

以 `c121086` 为审阅基线，新增 [13 自检与待抉择事项](13-self-review-and-decisions.md)。复核概要、详细设计、案例与执行计划后，保留两项用户范围选择和一项待补机械构造接口；明确偏差及验证顺序已修正。此段保留首次自检时的记录；后续用户决定及当前合同以第9节和13为准。

- 新增1份、更新13份 Markdown；原型新路径/新增目标、项目共享文件保留、用户定档与事实缺口、长材料覆盖及早期探针已同步。两项待选合同、运行时代码、模板和发布文件未变；本次未提交 Git。
- 检查43份 Markdown 的相对链接/锚点、6段 JSON、13段 Python 示例及18份 Mermaid 图源与正文的一致性；`git diff --check` 通过。模板 SHA-256 与第6节相同。
- `uv sync --project plugins/ai-sow --locked`、仓库根42项测试、仓库验证器、旧插件独立复制 smoke 通过；根指南指定的旧 Skill 范围 pytest 为 **388 passed、4 skipped**。
- 此次未重跑旧插件全目录 pytest；第6—7节记录的两项既有架构测试失败未修复，不能将本次指定范围通过写成全仓库测试通过。以上检查也不证明尚未实现的 Lite 语义、性能或新公式已通过。

## 9. Q1/Q2 决定与机械接口收口记录

本次依据用户明确答复，把单人串行改稿及原模板独占计算同步到概要、详细设计、案例、163项场景映射、Mermaid 和14项实施任务。P00/D07/P03 补 check/edits：Agent 只提交有限编辑，工具复制基线并派生完整候选、精确计划及可读 review；不新增工作流操作，不把确认前的工作工件作为有效版本。

- 相对自检基线 `c121086`，累计修改41份已有文档/图源，新增13号自检文档；包括首次自检及本次决定同步。没有改模板、模板测试、旧插件或发布文件，没有提交 Git。
- 复核43份 Markdown 的相对链接/锚点、6段 JSON、13段 Python 示例、18对 Mermaid 正文/图源、163项场景的完整唯一映射、14项任务及未完成状态；差异空白检查通过。模板 SHA-256 保持第6节原值。
- 锁定依赖同步、仓库根42项测试、仓库验证器、旧插件独立副本 smoke 通过；旧插件全目录 pytest 为 **537 passed、4 skipped、2 failed**，仍是第6节的两项架构断言。相关测试、runtime 文件和 Skill 均与 HEAD/main 原字节一致；未修复无关基线问题。
- 两项产品选择已关闭；真实 Agent 效果、逐步 usage、原模板新投影和有限编辑接口仍按实施计划验证。这些文档检查不代表 Lite 已实现或性能已达标，执行起点仍为 I1.1。
