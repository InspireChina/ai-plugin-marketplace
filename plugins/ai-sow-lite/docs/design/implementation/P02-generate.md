# P02 · Generate 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不提供预制业务模型，只输入项目材料和必要答复，在一个主 session 中产生可带走的初版 SOW。

**Architecture:** generate Skill 自主完成输入理解、gap、骨架、语义分片及联合拆解，调用 I1 的机械工具交付。文件按需读取，工作摘要用于续接，不增加 Python 专业调度。

**Tech Stack:** P01 的 Python/uv/Schema/Excel 组合；当前实际可验证宿主的原生交互与 usage 接口。

**Spec:** [D01](../detailed/D01-interaction-and-outcomes.md)、[D03](../detailed/D03-input-analysis-and-exploration.md)、[D04](../detailed/D04-generate-and-context.md)、[D04A](../detailed/D04A-single-session-panorama.md)、[D04B](../detailed/D04B-bounded-loops.md)、[D08](../detailed/D08-telemetry-and-performance.md)、[P00](P00-contracts-and-fixtures.md)。

## Global Constraints

- 开场只负责新/旧项目和必需输入；PRD/HLD 必需，旧项目另有往期 SOW，原型可选。分析后只问输入相关的业务/技术/交付事项。
- 非原型输入只支持可读文本和 XLSX；无 PDF/DOCX/OCR、全量 IR、嵌入检索服务或代码充分性打分。
- 稀疏历史为 as-is，其余材料为 to-be；实例不明的新建、默认 M 及问题沿既定口径，不追加穷举调查。
- 一主 session，无 subagent；按片联合 Story/AC/Task，公共建设单计，技术/NFR/交付主动识别，不新增方案。
- 首轮批量问题加最多一次补问，输入分析共用一次追加调查；返修执行 D04B，文件化不宣称清空聊天历史。
- 依赖 I1 已有真实 Excel/保存证据。本增量的无原型例通过，不代表原型探索已验证。
- [12 资料吸收评估](../12-reference-absorption.md) 的专业方法落实在本计划指定的参考文件和案例中；来源只作开发依据，运行时不加载旧插件、整套设计或旧 prompts。当前模板为唯一标准，SIT/UAT 适用不自动增加测试/上线范围。

## I2.1 · 文本/XLSX 读取、主题与历史范围

**Files:** 扩展 runtime/ai_sow_lite/inputs.py、artifacts.schema.json、tests/test_inputs.py；创建 history 夹具和 references/input-analysis.md。复用 D00 source_readers 的 bounded XLSX/Markdown 方法，删除旧领域 extract_document 和关键词“材料充分”判定。

**Interfaces:** 消费 P00 ingest_sources/ingest_analysis/inspect_view；产出实际 text_lines/xlsx_range、可复用 reading、按用途的 topics/evidence、历史候选范围摘要。读取事实与语义结论仍分别保存。

- [ ] 创建多 Sheet 历史 XLSX、合并区域、隐藏附注、公式有/无缓存、空白行/同名条目和单文件 PRD/HLD 区域夹具。文本采用 UTF-8 严格解码，BOM 只按已识别编码解释；无法解码返回 INPUT_UNAVAILABLE 并要求可读文本，不装自动转码/解析服务。XLSX ZIP 预检沿既有解压/成员上限，超限给明确区域/文件诊断，不返回半份完整假象。
- [ ] 实现 XLSX 结构目录与指定区域读取。附件保留地址、类型化原值/公式、缓存有无、合并/附注/隐藏状态；original_hash/reader_version/options/selection 共同确定读取身份。时间/数字保留类型，不转成不带类型的显示字符串再冒充原值。
- [ ] 实现查询、分页与精确覆盖；来源/选择器改变使游标失效，相同游标无进展拒绝继续。新增用途复用物理读取但新建用途分析；新增历史成员使相关候选范围摘要变化，包括原来零命中的范围。

```python
def test_cursor_pins_input_snapshot(case):
    from tests.support.cli import run_request
    payload = {"view": "inputs", "selector": {}, "limit": 1, "cursor": None}
    first = run_request(case.project, case.request_id, "inspect", payload)
    assert first["ok"]
    assert first["result"]["returned_count"] <= 1
    assert first["result"]["coverage"] is not None
```

此片段检查分页合同的起点；同一测试中再用真实 ingest 增加夹具材料，以首个 next_cursor 续读时，固定读取其已绑定旧快照。旧来源不可变，不混入新增成员；查询最新集合需从 cursor=null 开始并返回新范围摘要。若绑定快照缺失则 VERSION_INCOMPATIBLE，不静默转到最新集合。

- [ ] 分析候选落盘前验证实际来源/摘要；输入问题仍在 work，I2.2 绑定正式目标。稀疏历史不要求 AC/Task/type_hint；无依据的历史完整层级不得由工具补造。references 给出 API/事件候选与实例区分、零匹配依赖和统一补问规则。
- [ ] 在 references/input-analysis.md 写清历史理解方法：表头、合并/跨行与附注共同确定条目，分页不切断语义；目录/标准/示例不当成历史交付，明确取消/排除/未来范围保留限定；部分内容相同不合并整条。使用下述 sparse-history 夹具核对读取结果和定位，语义判断交给 I2.2。合并既有分析只补新增关系与必要修正，不重新输出全部历史，也不增加历史 AC 补全或多层汇聚阶段。
- [ ] 执行 `uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_inputs.py -q`；记录 source_readers 的迁入方法与差异。测试只证明读取/失效机制，历史复用判断在 I2.2 真实演练。

## I2.2 · 一个 Skill 的完整初版生成

**Files:** 创建 skills/generate/SKILL.md、references/generate-slices.md、tests/test_skill_contracts.py；更新 references/{input-analysis,tools}.md、必要 checkpoint Schema；创建开发插件 manifest 的两宿主副本与 Lite README，入口只声明当前已实现内容。

**Interfaces:** 消费真实 sources、I1 六操作及 D03 分析工件；产出 work 中的 analysis、skeleton、slices、merged candidate、问题去向和有效版本。Skill 从已加载文件定位本插件，资料够时直接推进；工具不返回专业下一步。

Skill 的必备执行段落按下表组织；它定义输入/交付边界，不把片内思考逐条写成工具 action。

| 活动 | 读取什么 | 落盘什么 | 进入下一活动的依据 |
|---|---|---|---|
| 开场/接收 | 用户已给类型、PRD/HLD/历史/可选原型路径 | 原件登记、项目身份、缺件清单 | 必需材料可用；缺件立即列具体材料，不启动长问卷 |
| 全输入分析 | 内容/目录/未读面、历史范围、标准定性说明 | 主题/必要依据、稀疏历史、三类 gap/排除、输入问题与覆盖 | 业务/技术/交付基础是否足够，由 agent 判断 |
| 按需澄清 | 合批后的输入事实/冲突/决定 | 最少实际答复、采用/仍缺事实、剩余次数 | 足够即继续；两轮后基础不足结束，局部问题移交 |
| 骨架/分片 | 有效 gap、责任、公共建设/消费关系 | skeleton.json、slice-index.json、简短覆盖与公共归属 | 每个本期义务有片或明确局部缺口，片以目标/依据/依赖划分 |
| 片内联合生成 | 本片主题/原文定位、骨架邻域、公共边界、相关标准 | slices/<slice-id>/candidate、必要依据和待确认 | 来源 AC、实际 Task 单元和分类；复杂度不明立刻 M |
| 合并/交付 | 各片候选、骨架义务、未决关联/问题 | merged candidate、正式引用、summary 与同版 Excel | 一次语义整合，完整机械检查，I1 render/apply |

skeleton/slice-index 是本请求工作文件，不进入新的稳定领域模型。最小字段为骨架 ID/标题/依据及预期责任，片含 slice_id、目标对象/主题、公共边界引用、candidate_path、完成/限制摘要。引用完整性检查由工具完成，片先后及大小由 agent 决定。旧片正文不复制进每个新片；新候选共享必要原件/依据引用。

### 片内专业指引的具体内容

以下内容写入 `references/generate-slices.md`，输入用途与历史规则引用 input-analysis，不再复制。它们是 Agent 在既有骨架、联合生成和合并活动内采用的方法，不转成 Python 专业门禁或额外检查阶段。

| 判断 | 指引要求 | 需要避免的误判 |
|---|---|---|
| 技术/NFR 的承载 | 业务触发的约束写入适用 Story 的来源 AC；有依据且独立交付/消费的公共能力才单列建设。项目级约束保留在主题/依据/备注，消费者仅做自身工作与实际适配 | 看到“性能/安全/审计”就创建平台；把测量指标的看板当成满足指标；因不单列 Story 而漏掉约束 |
| 交付责任 | 按输入识别迁移、演练、上线准备及外部依赖，区分资产建设与实际执行；分别形成标准成果才分项计量 | 默认增加 SIT/UAT 自动化、生产执行、PoC 或设计工作来填补未知；把外部依赖删出所有说明 |
| Story 与 AC | 按目标/交付边界组织层级，保留角色、触发、阈值、时限、否定/排除与异常条件；AC 所描述的行为属于所在 Story | 章节/页面直接变树、固定子项数或 Task 上限、每条 AC 生成一份实现、为补齐 AC 编造条件 |
| Task 单元与模式 | 批量读取当前片相关标准的单位、交付成果、模式和包含边界；调整仅看本次变化/必要回归，复用仅看项目侧适配，平台存在不等于新业务对象是复用 | 只看类型名称；SOW 文本改稿就选调整；普通配置/调用另计工作；消费者重复承担公共建设 |
| 交叠与公共工作 | 先明确成果和公共归属，合并时核对有关联的 Task：集成/内部同步、迁移/内含核验、IaC/普通配置、测试资产/重复执行 | 不同类型便认定不重复，或相同来源便删除不同成果；全量 Task 两两评审 |
| 未知出口 | 仅定档不足即 M+问题；候选实例未明即新建+问题；其余局部无依据字段留空。已知多个独立实例有限拆分，已知超界且无法拆明保留未估工作 | 为 M 再检索/补问、把已知超界涂成 M、用设计/Spike Task 代替缺失的基础方案 |

标准候选按片合批读取所需行，允许按既有分页合同续读，已有有效读取优先复用；存在具体歧义才比较相邻类型，不为每个 Task 强制读取 challenger 或重复 hydration。片间复用依据和规则，仅带本片目标、边界、关联与必要标准；合并沿 D04B 一次整合及既有返修上限。Skill 正文不嵌入全部标准、案例或本表的重复副本。

### 首批语义夹具与验收

按 [P00 夹具规则](P00-contracts-and-fixtures.md) 制作下表的五组输入，完整输入放到相应目录的 `cases/<case-id>/inputs/`。answers/expectations 留在评估侧；表中替换要求在生成夹具时形成自洽原件，不把新旧相互矛盾的段落一起交给 Agent。

| case-id 与目录 | 输入的具体内容/变体 | 必须观察的结果与反例 |
|---|---|---|
| `three-scope`，generate | 将 EX01 P1/H1 写为 prd.md/hld.md，保留公共客户端、两消费页、迁移内含核验与待确认交付责任；条数缺失。answers 使用 A1。另作 local-nfr 变体：H-N1/H-N2 明确各页面内部实现同一约束，本期不交付独立程序库，其余边界保留 | 主例三类工作有据，公共建设一次、消费内含接入、迁移内含核验；默认 M 不补问条数。local-nfr 保留两页异常/迟到响应 AC，不创造公共平台或丢掉 NFR。两者均保留只读、不得自动重试有副作用操作、外部承担生产执行等限定 |
| `sparse-history`，history | EX03 订单查询 API/外发事件候选，未说明本期实例适用。history.xlsx 设历史范围、附注、标准目录三个 Sheet：历史条目跨行且缺 AC/类型，附注限制责任并排除一项未来接口，目录列出工作类型但不表示做过；本期 PRD/HLD 齐备 | 能用稀疏 as-is，类型相关而实例未定时新建+问题；附注/排除不丢，不把标准目录或未来接口当现状；保留局部相同条目的不同范围。读取分页/合并后的物理定位可核对 |
| `confirmed-instance`，history | 用小型 PRD/HLD/历史说明同一订单 API，明确本次改变其过滤规则与必要回归，事件范围不在本例。输入给出目标实例和变化，实际标准以当前模板为准 | 同一对象实际变化支持调整；不因所属项目是旧项目而把所有工作选调整，不另计没有发生的复用工作 |
| `already-satisfied`，history | 仅包含一个本期查询目标，PRD/HLD 与历史及本次明确答复确认同一 API 已满足，且本期无其他技术/交付变化 | 有充分分析依据的空 gap，不为凑层级或工作数量造 Task；不能通过漏读其余义务得到空范围 |
| `insufficient-input`，generate | 分别只给 PRD 而缺 HLD，以及仅给 Epic/Feature draft 与 tech note；均不提供可替代的完整高阶方案 | 明确要求所缺材料并结束，不开始拆解或用默认 M 掩盖基础不足，不交付空零版 |

主例与 local-nfr 对照各运行一次，其余必要变体首次各运行一次。跨类型重叠先用 EX01 的迁移/核验与公共/消费覆盖，集成/同步等组合在 I4.2 扩展；不因旧例有59项工作就全量复刻。已明确多实例的标准单元反例并入主例的定向变体：两个独立查询目标不得仅因同类型合并；只改这一处时不必重新跑全部场景。

标准类型和复杂度按当前行与夹具事实判断；允许合理命名、层级和片数差异。每项期待记录实际输出位置、依据、缺口/问题及结果，不新增机器业务字段或关键词评分器。失败按首次出错位置改输入读取、专业指引或机械实现，再仅复验受影响变体。

- [ ] 写出上述 Skill 和按需参考，优先复用当前已给材料；正常返回只有版本/文件和关键待确认，不在聊天重复整份 SOW。references 的业务规则只维护一个位置，Skill 链接它，不复制 D00—D09 全文进上下文。
- [ ] 建立轻量文本合同检查：链接目标存在、命令指向自身工具、没有 next/submit 或强制出稿审批、没有依赖另一插件；检查文本不代替实际演练。
- [ ] 运行以下真实宿主提示，不提供 I1 model、期待文件或 generate 聊天答案。输入由人工/独立评估者保留期待义务，agent 只见合成原件；需要答复时按 fixture 提供真实用户消息。

```text
这是新项目。请用给定 PRD 和 HLD 生成本期 SOW。
迁移的本期责任在材料中有待确认，我会回答输入相关问题。
请把需要后续确认的事项随 Excel 一起给出。
```

- [ ] 创建并运行上述五组夹具及必要对照；记录实际提供的输入/答复、首次问题批次、分类依据和输出位置。确认测试上下文没有预制 candidate/expectations；基础不足必须给补料出口，不能交付空零版。
- [ ] 检验公共建设一次、消费者只做自身工作/适配、AC 有来源、无证据指标未编造、默认 M 及时使用、其他未知精确绑定、没有机械 AC→Task。源码文本测试无法证明这些，保留实际产出和逐义务结论。
- [ ] 做有限问答和压缩续接演练：首轮部分答复、一次补问后仍缺基础、后期局部未知、同根因再失败、已耗计数续接、重复 generate。检查实际消息与文件；没有新用户回答不能当默认批准，用户离线也不新增定稿阶段。
- [ ] 执行 `uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_skill_contracts.py plugins/ai-sow-lite/tests/test_contracts.py -q`，然后把真实演练证据写入 docs/validation/I2-generate.md。专业判断不按固定 Story/Task 数判通过。

## I2.3 · 宿主边界与首个真实性能基线

**Files:** 扩展 runtime/ai_sow_lite/telemetry.py（确有体量再拆 host adapter）、tests/test_telemetry.py、docs/validation/I2-generate.md；新增 docs/validation/host-support.md；同步 D08/D09/README。

**Interfaces:** 消费 D08/EX06 已定位的原生 usage 来源及 I2 请求/活动标记；产出有版本/身份/覆盖证据的采集能力和单 session 基线，不增加模型 SDK/账户额度推算。

最小候选和宿主边界探针已前置到 I1.1，先检查这些记录。本任务补真实 generate 通道、完整活动和版本适配的集成证据；已有且边界未变的基础读取证据复用，不把 I1 的候选实验冒称本任务已通过。

- [ ] 对当前实际宿主做一次受控读取，确认 producer/version、request 起点/终点、事件身份、epoch 和是否能区分物理模型调用。若来源不兼容仅禁用该适配器并保留工具计时；不扫描无关聊天、不拷贝 transcript。另一个宿主未实际测过就明确未验证。
- [ ] 随现有调用附活动标签；纯语义活动在大边界标记，记录 request start、首次有用反馈、首版文件、end。以 D08 白名单接入，不为每条思考增加 CLI 往返。一次调用跨片记 shared，不能均摊。
- [ ] 使用 I2.2 首次实际运行作为基线，统计等待、读取/回显/写候选/重算/恢复、可得 tokens、重复背景和观测开销。缺起点/最终答复用量时报告缺口，不能把线程累计当本请求；做一次取消传播检查，记录实际观测点与无法强制结束的边界。
- [ ] 随同一运行记录参考/标准读取的实际路径、选择范围、重复回读与候选重写量，检查是否重复加载整套规则、整份历史或整份旧片。它们作为成本线索，与原生 usage 分别列示；不能按文件长度换算 token，也不因增加指引而提高 D04B 的调查/返修额度。

```python
def test_unknown_host_format_keeps_business_result(case):
    from ai_sow_lite.telemetry import build_report
    report = build_report(case.project, case.request_id)
    assert report["request_id"] == case.request_id
    assert all(m["coverage"] in {"complete", "partial", "unknown"}
               for m in report["metrics"])
```

相应 fixture 放未知 producer/version 的白名单事件和一个已应用业务版本；测试还须逐字节比较 build_report 前后的 current/manifest/sow，且报告应包含具体不兼容诊断。此段是报告合同断言，不宣称没有事件也验证了适配降级。

- [ ] 在明确授权的宿主开发加载环境验证 generate 发现/调用；只创建可加载副本不等于安装到用户全局环境。独立复制 smoke 与对应 telemetry 测试通过，支持矩阵填实测值，不根据两个 manifest 宣称两宿主全支持。

**I2 退出：** 真正从输入完成 generate，允许的问答有效，三类义务有依据，用户可直接拿走 Excel。文件可续接，观察到真实耗时和实际可得 usage 粒度。逐步计量若尚不完整保留 G12，不阻塞 P03 的文件修改设计；不得把这解释成资源目标已完成。
