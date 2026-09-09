# AI SOW Lite · 实现前统一 Review

[设计总览](README.md) · [详细设计目录](detailed/README.md) · [实施计划目录](implementation/README.md)

当前已推进到**可以按任务开始实现**的交接点：D00—D09 描述产品与详细设计，P00—P04 补齐共用机械接口、任务依赖、测试夹具和验收顺序。当前只完成设计与计划；没有实现 Lite Skill/内核、修改模板、安装或发布插件。

## 1. 建议的 Review 顺序

本次优先看 [实施目录第4节](implementation/README.md#4-已落实的资料吸收与验收归属) 和下文第3.1节：专业方法与反例已经落实到执行任务。来源/取舍见 [12 旧版专业资料吸收评估](12-reference-absorption.md)。既有流程/合同与14项任务保持不变，尚未进入实现。

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
| 部分金额是否误导 | 工作未拆明、字段缺值和当前有值待确认分开；前两类按实际依赖阻止完整金额，不吞成0 | D02/D06、I1.1/I1.3 |
| 修改的真实范围 | 提前形成具体变化，确认绑定实际内容/元信息；无关基线更新不偷改原确认，相关变化有限重讨论 | D05/D07、P00/P03 |
| 上下文与资源 | 单 session 先测真实输入/回显/回读/生成成本；有界循环减少浪费，usage 缺失不估填，不增加 token 审批 | D04A/D04B/D08、I1.4/I2.3/I4.3 |
| 测试时机与复用 | I1 先测金额/保存，I2 测真实语义，I3 测确认/新会话；I4 扩组合。复用旧机械证据，不重新选型或继承旧流程 | D00/D09、P01—P04 |

## 5. 当前仍需要实证的事项

设计没有以“以后再决定”为由留下一个必须先改变产品方向的空缺。以下事项都有实施任务；它们不能靠统一 review 代替验证，也不需要变成新一轮开场问卷：

- Lite 输出的真实公式、合法未知/工作缺口保护、Office 后 OOXML 与原生打开：I1.3/I1.5。
- 本地锁/指针生效、崩溃和取消传播、确认应用与无关基线重建：I1.2/I1.5/I3.3。
- 真实 Agent 的三类需求识别、稀疏历史匹配、输入充分性和有限循环遵守：I2.2；复杂组合 I4.1/I4.2。
- 宿主逐步 usage 的真实粒度、请求边界、版本适配与实际提速：I2.3/I4.3，G12 保持开放。拿不到逐步数值要报告真实能力和缺口，不能改称目标已满足。

统一 review 后，执行起点为 **I1.1**，然后按依赖做到第一份真实重算的可靠交付；本轮没有自动进入实现。

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
