# P04 · 首版范围与性能收口实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 I1—I3 已可用且异常可退出的基础上，覆盖承诺的复杂输入/修改，形成可核实的支持与性能说明，准备独立安装包。

**Architecture:** 复用同一 Skill、数据和交付协议，按已有场景扩展真实夹具与必要适配。性能优化依据活动测量，先减重复读取、回显、候选重写和重算；子 agent/并发保留为另有证据时的实验。

**Tech Stack:** D00 已选组合；原型优先宿主现有浏览器，只有确有能力缺口且验证有用时才增加 Playwright Python/Chromium。

**Spec:** [D03](../detailed/D03-input-analysis-and-exploration.md)、[D05](../detailed/D05-clarify-and-change-scope.md)、[D08](../detailed/D08-telemetry-and-performance.md)、[D09](../detailed/D09-validation-and-implementation.md)、[场景目录](../08-scenario-catalog.md)、[P00](P00-contracts-and-fixtures.md)。

## Global Constraints

- 此处扩展复杂组合，不把 I1 Excel/保存、I2 输入充分性、I3 串行确认/过期拒绝的首次验证推迟到这里。
- 不增加 PDF/DOCX/扫描件支持、无损手改回导、固定多 agent 团队、模型执行服务或预算门禁。
- 技术/交付义务和来源覆盖必须保留，不能靠漏项、少记 usage 或更早失败宣称更快。
- 支持矩阵只填写已有来源的适用证据与 Lite 实测，不因 manifest/库存在就宣称平台可用。
- 可安装包准备不等于安装、发布或提交授权；本轮计划不进行这些动作。
- [12 资料吸收评估](../12-reference-absorption.md) 的原型/复杂边界案例按下文加入现有任务。旧示例假设只有显式写进合成输入才可采用，旧 projection/金额留在评估侧；不复制旧行动串联或全阶段复审。

## I4.1 · 原型、多用途材料和 BA Draft

**Files:** 扩展 inputs.py、artifacts.schema.json、references/input-analysis.md、tests/test_inputs.py；新增 tests/fixtures/prototype/、tests/test_prototype_records.py、docs/validation/I4-inputs-and-changes.md；根据证据更新 Skill 支持说明。

**Interfaces:** 消费 P00 已有 source/analysis 两种 ingest 和 D03 observation locator；产出真实原型资源版本、不可变观察/必要附件与范围限制。浏览器动作由宿主 agent 决定，工具不返回点击 Action 列表。

- [ ] 创建自包含 HTML/JS/CSS：列表→详情、一个输入后才可见状态、模拟成功按钮、不可达状态、取消后的迟到结果；一个启动型变体附完整本地运行说明。夹具不接真实业务端点；启动服务归本请求，记录/清理自身进程，不能全局杀浏览器。
- [ ] 原型作为资源清单拷贝，拒绝包外逃逸。observation 记录实际入口/前置、最少操作、结果、限制及附件 hash；同源多主题复用同一观察。静态 HTML 不能充当动态观察的 hash。无浏览能力如实返回限制，不能写“交互不存在”。
- [ ] 在实际宿主分别做一次静态观察与需交互观察；用首批目标集合及一次共享追加验证有限退出。新路由不断出现不递归重开批次；有生产写入风险的资料只能在已有授权内观察，说明实际缺口，不预设所有原型都能运行。
- [ ] 将以下观察边界写入 references/input-analysis.md 的原型段，并并入同一合成资源包；期待在评估侧，不向 Agent 提供预先规定的点击列表。使用已有首次观察与一次共享追加额度，未覆盖目标记真实限制。

| 包内反例 | 预期的观察与结论 |
|---|---|
| 详情页有初始已勾选的控件和变化计数，重复设置为相同值不会触发变化 | 操作调用成功不当作事件已触发；检查实际状态/反馈，说明看到了什么 |
| 列表与详情具有相同文案按钮，但属于不同路由和对象 | 记录实际入口、对象与状态，不把一个路径的观察推广到另一条路径 |
| 模拟成功仅改变本地页面；另一个分支在源码存在但无法进入 | 前者可作为原型交互证据，不能证明真实后端/as-is；后者记录静态依据和未观察限制，不能认定该行为不存在或无限追查 |

```python
def test_observation_cannot_replace_source_with_unregistered_attachment(case):
    from tests.support.cli import run_request
    payload = {"kind": "analysis", "entrypoint": "generate",
               "analysis_path": ".ai-sow-lite/work/generate/" + case.request_id +
                                "/unregistered-observation.json"}
    reply = run_request(case.project, case.request_id, "ingest", payload)
    assert reply["ok"] is False
    assert reply["diagnostics"]
```

在 test_prototype_records 的 fixture 中先创建该合法结构的分析文件，仅让 observation 附件指向未登记资源；进一步断言 EVIDENCE_MISSING、原件保留且 current 不变。再提供真实包/附件正例通过，防止一个不存在的 JSON 路径冒充来源校验测试。

- [ ] 使用同一 XLSX 的不同区域分别作历史与 draft，验证原件只登记一次、用途分别分析。BA draft 只给 Epic/Feature 时，配完整 PRD/HLD 能复用其有效骨架；仅 draft+tech note 必须按不足退出；冲突明确定位，不把 draft 默认为更高权威。手改 SOW 作为意见/辅助输入，没有无损回导承诺。
- [ ] 执行 `uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_inputs.py plugins/ai-sow-lite/tests/test_prototype_records.py -q`；真实观察另记录宿主、资源/引擎版本与未覆盖面。没有实际浏览器证据的场景保留未验证，不用 source reader 测试代替。

## I4.2 · 拆合、共享与交付变化、部分子集

**Files:** 扩展 clarify 夹具、tests/{test_clarify,test_project,test_workbook}.py、references/clarify-changes.md、docs/validation/I4-inputs-and-changes.md；需要时最小修订 validation/project/workbook 的既有边界。

**Interfaces:** 消费 I3 实际方案/diff/read_set/lineage 和当前/历史 projection；产出范围闭合、历史可达的真实修改包，不增加自动回退引擎。

- [ ] 创建 EX05/EX07 的六组差异：Story 拆分/合并；公共能力契约与消费者；迁移/上线责任；新历史改变原零匹配；多个问题只答部分/选择独立子集；未拆明工作补齐或明确退出。每组预期分别列必变、必保留、历史出处、未决问题和写入模板的定性值。
- [ ] 在公共/交付两组中加入下面的成果边界变体，更新 references/clarify-changes.md 对相关标准与有限邻域的使用指引；输入形成完整 PRD/HLD 变更说明，不能只给预制分类答案。实例同名/类型不同不直接决定合并或删除。

| 变体 | 输入变化与必须保留的边界 |
|---|---|
| 集成内含同步 → 独立持续同步成果 | 原来同步只是一次集成内部实现，不另计；新明确输入要求独立调度、维护和验收的持续同步能力，才重新判断有关 Task 的包含边界。保留仍需交付的集成成果，避免重复计量其内含部分 |
| 迁移内含核验 → 独立周期核验 | 原来迁移字段/记录核验内含；用户明确增加上线后持续运行的周期核验结果，才识别新增范围。当前模板决定可用类型与标准单元，不因名称含“核验”就删掉其中一个真实成果 |
| 公共能力调整与消费者接入 | 来源先明确公共变化及哪些消费者实际需要适配；公共建设一次，消费工作按实际变化计量，未受影响的消费者内容保留。不能自动为所有消费者各加一份调整和复用 |
| 本期制作发布方案，生产执行由外部转给本期 | 新答复须明确应用/批次、执行与回滚责任和已给方案；只改有关交付义务/任务/依据及派生金额。缺少决定实际执行范围的基础时有限讨论，不凭使用旧流水线就判“复用”或自动增加培训/自动化 |

前两种交叠分别作为“共享/交付成果新增”的输入变体。真实交互先使用一组公共/交付变化和既定部分子集样例；其余机械夹具只能证明差异/保存机制，专业边界未实际演练则标未验证。发现其是当前发布范围的未验证语义时补对应单例，不通过扩大整套回归轮数或捏造覆盖关闭。
- [ ] 拆合保持未变 ID，实质新义务生成新 ID；lineage.from_version_id 指原确切版本。终态问题可回查旧对象，open 问题必须指当前；删除不是回答，退出依据仍可达。合并两个 Story 不能把两个实际 Task 当同名自动去重。
- [ ] 公共/交付变化先定位关联义务与有限回查深度；能闭合时展示完整具体差异，不能闭合且修订已耗尽则保留原版和草案。对跨原片的局部修改使用真实依赖边界，不按原片号机械全量回退。
- [ ] 子集确认只包含已展示且独立闭合内容；不适用的确认不能被“部分选择”放行。试算文件过期、变模板/公式/基线必须失效；同一候选未变复用完整投影。默认 M 的答复不可为补规模重开调查。

```python
def test_empty_diff_has_no_new_version_obligation():
    from ai_sow_lite.validation import diff_bundle
    model = {"tasks": [], "stories": [], "pending_items": [], "decisions": []}
    assert diff_bundle(model, model) == []
```

对应完整回归还必须证明已答问题的真实重复反馈无新版本/无重算；确认 M 首次关闭问题的 diff **非空**。此小断言不是无 gap 的充分性测试，也不能抹掉同值下的元信息变化。

- [ ] 真实交互优先选择公共能力变化和一组部分子集；其余用完整文件机械夹具验证。实际 agent 若漏影响，修专业分析参考/第一次方案准备；程序越界或错误填值则修对应合同/写入；原模板计算行为不属于插件修复范围。不要统一靠提高修订上限补救。
- [ ] 执行上述三类测试，按变更涉及布局做代表性原生打开；每个失败保留旧有效版并可定位恢复。更新 D09 场景清单，将基础机制证据和复杂组合证据分别标记。

## I4.3 · 性能、支持矩阵与交付准备

**Files:** 新建 docs/validation/performance.md、tests/support/check_scenario_coverage.py；更新 docs/validation/host-support.md、D09、README/CHANGELOG、插件 manifest、LICENSE/NOTICE、pyproject/uv.lock 与 smoke。准备入 marketplace 时同时修改仓库根 `.agents/plugins/marketplace.json`、`.claude-plugin/marketplace.json`、scripts/validate_repository.py、tests/test_repository_layout.py、tests/test_repository_validator.py 和 README；这些根发布边界文件不进入插件运行依赖。

**Interfaces:** 消费 I1—I3 真实事件、质量义务、D09 的163场景主责与本轮覆盖；产出可比较的性能记录、实际支持范围及完整插件包。场景记录不是自动把“设计过”标成“通过”。

- [ ] 建立场景证据清单，每条含 id、owner、earliest_increment、state、evidence_refs、limitation。state 为 verified、covered_by_mechanism、unsupported、conditional；后两项写具体限制。covered_by_mechanism 必须指已验证机制并解释适用性；同编号只一条主记录。AN27/AN28、FS13、OB11 为未启用委派的条件实验，不能为填满表被迫实现多 agent。

```python
def assert_scenario_catalog_complete(catalog_ids: set[str], records: list[dict]) -> None:
    ids = [row["id"] for row in records]
    assert len(ids) == len(set(ids))
    assert set(ids) == catalog_ids
    for row in records:
        assert row["state"] in {"verified", "covered_by_mechanism", "unsupported", "conditional"}
        if row["state"] in {"verified", "covered_by_mechanism"}:
            assert row["evidence_refs"]
        else:
            assert row["limitation"]
```

该检查还要验证引用文件存在、被引用机制已验证、最早增量符合 D09；覆盖率不是语义正确率，不能将尚未支持的核心 generate/clarify 场景改标签后宣称满足首版。

- [ ] 性能先使用 I2/I3 已采基线，覆盖小型、典型及至少一组长材料的单 session generate 和局部 clarify；长材料不以小样本先发现瓶颈为前提。长例核对后段义务、决定、待确认项、重复回读和实际开销，并记录是否发生自然压缩；未发生不能写成已验证压缩行为，压缩续接仍使用 I2 的定向演练。只对实际开销来源做一次目标优化配对，保持同输入/模板/模型配置、相同起始上下文和缓存条件；结果不稳定才重复对应组，不默认大规模跑分。
- [ ] 每组同时列首个有用反馈、首版 Excel、clarify 方案、确认到新文件、用户等待、工具/Office、可得 token 与归属缺口、实际轮次/重读/写入量、语义义务/来源覆盖、未知/未拆明范围。旧 ai-sow 明细不齐只比较同口径可得项，不为补历史日志强制重跑整套旧流程。
- [ ] 优化一次只改变一个已测开销来源：减少冗余 stdout/原件回读，复用有效依据/完整试算，或缩短换片工作摘要。优化后先检查义务与来源，再比较速度/token。没有合格对照只报告基线；不写虚构“降低 X%”。宿主上下文压缩/隔离/并发若需额外实验，另列已知成本和问题，不加入首版默认路径。
- [ ] 将 I2.3 的参考读取记录加入既定配对：区分首次规则读取、未变标准/历史/旧片重读、上下文继承和候选重写。优先用已有小型/典型样例验证按片批读与单份规则维护；两组保持相同语义期待。文件更短或调用更少只记成本线索，节省结论必须来自同口径实际时间/usage；资料吸收不引入额外评审轮次或资源审批。
- [ ] 核对宿主的问答、文件调用、原型、usage 和取消，平台的自举、Office、原生 Excel 与本地锁。Windows/网络盘/同步盘没有相应证据则明确范围，不能把 macOS 的原子替换实测推广成所有存储保证。G12 精确逐步计量若仍有缺口继续开放，并说明当前还能据哪些指标优化。
- [ ] 依据 root marketplace 架构和插件创建规则准备双 manifest/双 marketplace 变更；保持 ai-sow-lite 目录/名称一致，版本按已验证成熟度标预发布。现有 ai-sow 常量/测试不能被 Lite 版本替换；验证器按插件分别核对，旧条目原值保留。README 只写真实已实现安装/使用/支持范围；NOTICE 记录实际迁入来源，不包含客户内容。
- [ ] 执行 Lite 全部测试、独立复制 smoke、场景覆盖脚本及仓库根完整检查；输出一个交付证据汇总。安装、推送、发布只在后续明确授权时进行，这些动作不是本计划默认收尾。

**I4 退出：** 声明范围内的两入口及关键异常有实际证据，原型/draft/复杂修改限制清楚，性能与计量结论可追溯，插件具备独立交付条件。尚未解决的宿主能力不包装成已解决；若影响核心使用或数值可信度，交付准备保持未通过，定位相应任务修复而不是重新推翻设计。
