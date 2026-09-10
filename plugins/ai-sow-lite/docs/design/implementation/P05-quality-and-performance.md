# P05 · E2E 后质量修复与性能优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 逐项执行本计划；这是开发组织方式，产品仍只有一个主 session。执行前按任务使用 TDD；专业行为用真实案例评估，不以关键词测试代替。

**Goal:** 先解决 AC 质量、估算问题闭合及 Excel 可读性，再用可信观测降低机械往返和上下文消耗。

**Architecture:** 保留 generate/clarify、原数据合同、单份专业指引及有限修改。代码只做机械构造、引用/版本/确认校验、投影和观测；语义由 Agent 负责。各项完成后分别 commit，不自动推送或发布。

**Tech Stack:** 沿用 Python 3.12、uv、jsonschema、openpyxl、pytest 和已验证 Office；不换模型、执行框架或解析栈。

**Spec:** [14 · 修复与优化方案](../14-e2e-remediation-and-optimization.md)。状态：实施中；I7.1 已完成有限专业修复，其他阶段按下列勾选及 [I7 验证](../../validation/I7-quality-and-performance.md) 查看，未完成项仍是拟实现设计。

## Global Constraints

- 准确性和减少可避免返工优先；未知不猜，复杂度未知默认 M+待确认，实例不明按既定新建口径+问题。
- 保留原四表、D 列 AC 全文、目标行待确认、必要备注、模板公式/金额/SIT/UAT 的唯一计算权威。
- 原模板资产不修改；布局只投影到新输出。旧 applied、源材料和冻结 E2E oracle 不改写。
- 不增加 AC 数量门禁、自动语义重写器、逐 AC→Task 映射、额外评审循环、subagent 产品阶段或资源预算门禁。
- 同义文字修改不改变 Task 工作模式/档位；实质拆合按现有 ID/lineage 与有限变更规则处理。
- 每个昂贵的真实 Agent 案例先安排首跑和一轮针对根因的复验；仍失败先重新分析方案，不反复重跑全案洗掉失败。必要代码修复/单元回归继续，未通过阶段不标完成。

## 执行顺序和文件归属

`I7.1 AC → I7.2 问题闭合 → I7.3 布局 → I7.4 观测 → I7.5 输入构造 → I7.6 配对优化与串联验收`

专业权威在 `references/generate-slices.md`，Clarify 只引用；调用帮助在 `runtime/ai_sow_lite/authoring.py`；协议入口在 `cli.py`；观测在 `telemetry.py` / `host_usage.py`；Excel 在 `workbook.py` / `office.py`。这些都已存在，不新建领域流程运行器。

新增开发案例目录为 `tests/fixtures/quality/ac-and-decisions/`；其中 `cases.md` 保存来源/反馈，`rubric.md` 保存评审义务，二者分离。复用已冻结的两期资料，不复制一套稍有不同的 PRD/HLD。执行者只收到资料/实际用户反馈与产品指引，评审者读取 rubric。每阶段证据新增到 `docs/validation/I7-quality-and-performance.md`，原报告保留。

## I7.1 · AC 与 Story 语义整理（P0）

**Files:** 修改 `references/generate-slices.md`、`references/clarify-changes.md` 的引用说明；同步 `docs/design/02-inputs-and-domain-model.md`、`detailed/D04-generate-and-context.md`。新增上述 cases/rubric；复用 `tests/test_skill_contracts.py` 检查引用和示例可用性。

**Interfaces:** 消费原 `Story.acs[].text/evidence_refs`、来源主题及已有 Task；输出相同模型合同。规则统一涵盖四条质量要求与例外边界，引用改写不成为丢弃实现约束的手段。

- [x] 固定四类反例：G1 事务/重放、B1 服务商权限/敏感信息、公共审计消费与建设、迁移/发布交付。加入“材料未给时限/次数，不补猜”的变体。
- [x] 用新 rubric 对旧输出评估并记录失败位置；一项缺少依据、内部 How、混合结果或跨 Story 重复均单列，不能由总分抵消。
- [x] 更新单份专业规则和少量正反例，不增加运行时阶段、schema 字段或质量打分代码。
- [x] 真实 Agent 从源材料完成有限生成及一次 AC 局部改稿；独立核对七个维度。除实际义务变化外，Task、分类、数量及未影响对象保持；原机制约束有可追溯去向。
- [x] 运行引用/示例测试和完整 Lite 检查；记录与提交 `fix(ai-sow-lite): align acceptance criteria with observable outcomes`。

验收用例必须逐项回答以下义务，代码只检查记录完整，不能自动给语义 pass：

```text
Q-AC01 同次重试不重复受理与独立报修不误合并均保留，业务AC无事务实现要求。
Q-AC02 转派后无权读取，响应不泄露敏感数据；不能只验收页面隐藏。
Q-AC03 公共机制与本业务实际消费各有归属，既有公共能力不重复计量。
Q-AC04 技术/交付Story仍有可验证成果，没有全部改成空泛业务口号。
Q-AC05 未给出的2秒/三次锁定等不引入；已有明确性能条件不能删掉或变严。
Q-AC06 不按条数拆Story，不用分号包降条数，不把细节全转塞备注。
Q-AC07 文字整理不自动改Task模式/复杂度，实质拆合保留义务与ID去向。
```

## I7.2 · 估算决定与未知事实闭合（P0）

**Files:** `references/clarify-changes.md`、必要时 `skills/clarify/SKILL.md`；新 cases/rubric；复用 `tests/test_clarify.py`、`test_clarify_lifecycle.py`、`test_workbook_inline.py`。本阶段默认不改 `changes.py`，除非真实反例证明现有机械能力不足。

**Interfaces:** 原 `pending.items[].targets/status/revision/current_handling/resolution` 和 `decisions.items[]`；不用新状态或默认 M 自动关闭规则。

- [x] 固定真实 G2 失败：仅复杂度目标，用户明确采用 M、数量未知；旧 Agent 结果应在新评估中失败。
- [x] 固定对照：M 尚未采用；问题含复杂度+生产责任且只采用 M；接口组部分采纳；再次回复已采用 M。实际答复只在展示方案后发送。
- [x] 在专业指引中给出目标级处理表：仅定档问题 resolved；剩余责任按已有 revision 规则保留；原未知事实不补成数值。
- [x] 真实 clarify 得到草稿后才检查、确认、应用。对应测试断言：

```python
# actual_* 来自本次真实产物；绝不先把输入伪造成 resolved。
assert actual_task['complexity'] == 'M'
assert actual_estimate_question['status'] == 'resolved'
assert actual_estimate_question['resolution']['decision_id'] in adopted_decision_ids
# 另从实际依据、决定及正文核对：未虚构迁移数量，不新增 quantity 字段。
# 含未答责任的独立对照仍为 open；重复答复不新增版本或 render。
```

- [x] 机械回归复用现有 `test_registered_complexity_choice_changes_only_explicit_basis_issue_and_decision`，新增对照只验证当前实际缺口；完成专业评估、相关全量检查后提交。

## I7.3 · 原列 AC 可读性（P0）

**Files:** `runtime/ai_sow_lite/workbook.py`、必要的 render 修订常量、`tests/test_workbook_inline.py`、`test_workbook.py`、`docs/design/detailed/D06-excel-projection-and-delivery.md`。模板资产不变；不创建说明 sheet/续行协议。

**Interfaces:** `_required_height` / `_fill_inputs` / `_fit_task_lists` 的机械布局；原 `project_workbook`、`render_candidate`、`verify_prepared`。新增拟定诊断 `WORKBOOK_LAYOUT_OVERFLOW` 精确指向原对象/字段/单元格；需要与现有诊断 schema 核对后按最小兼容增量实现。

- [x] 留存原 G1 D5 476 字符裁切反例，增加 I7.1 整理后的合格长 AC、长备注、任务列表、中文/英文混排、正常短文。先证明旧实现的视觉缺陷及静默截顶。
- [x] 只读演示输出 D=72/顶对齐/换行，字号不变；最多比较一次 D=88，选可读且较窄布局。未通过则保留失败，不扩大到新模板或无限调整。
- [x] 固化通过视觉检查的布局；一次计算高度。预计仍超上限返回局部布局诊断并保留候选/current，不让 Agent 为凑宽度删义务。不得因单格 32767 字符以内就视为可见性通过。
- [x] 新增机械测试断言正文等值、公式/保护/表关联保持、模板哈希不变、确知布局溢出有目标诊断；同时修订旧“任意长文本成功即正确”的测试预期，保留无 AC 数量门禁。
- [x] 真实 Office 重算后原生 Excel 查看最长行/首尾 AC、筛选、备注、汇总及打印布局；结构测试不能替代此项。同步 D06、prepared 兼容与 render 修订，完成检查后提交。

最低文字保真断言沿现有夹具：

```python
from .test_workbook import bundle, project
import openpyxl

def test_layout_keeps_acceptance_text(tmp_path):
    model, pending, decisions = bundle()
    project(tmp_path, model, pending, decisions)
    book = openpyxl.load_workbook(tmp_path / 'projected.xlsx')
    expected = '\n'.join(f'{i}. {ac["text"]}'
                         for i, ac in enumerate(model['stories'][0]['acs'], 1))
    assert book['01-需求故事']['D5'].value == expected
    assert book['01-需求故事']['F5'].protection.locked
```

此测试只是保真回归，不能单独宣称修好裁切；真正红绿证据包括原生视觉前后结果。

## I7.4 · 观测边界和入口失败（P1）

**Files:** `runtime/ai_sow_lite/cli.py`、`telemetry.py`，按需 `authoring.py`；`references/generate-authoring.md` 的活动示例；`tests/test_telemetry.py`、`test_telemetry_milestones.py`、`test_host_usage.py`、`test_skill_contracts.py`；同步 D08。

**Interfaces:** 保留原 response、诊断和 `Client.mark(name, phase)`；新增失败观测只使用经验证的最小身份。业务 payload 无效不意味着其 project/request 值天然可信。

- [ ] 用 B1 错误字段最小请求先复现：返回 `PROTOCOL_INVALID`，但无失败 tool span。
- [ ] 新增反例：可信身份+无效 payload 应有一次失败计时；未知/越界身份不写项目；观测失败不改变业务响应；取消保留真实状态；重复采集不加倍。
- [ ] 将安全最小身份验证与完整业务校验分离，仅允许前者通过的请求开始观测；原业务 validator 仍返回相同诊断。不要持久化完整无效 payload。
- [ ] 修正示例的活动开始位置，跨工具沿同一 activity，等待单列。用真实 Agent 构造/分析耗时跨多个工具的案例核对 start 早于工作、end 晚于成果；不能只包文件保存函数。
- [ ] 单一绑定收集全部实际回合并核对独立原生统计；活动 token 无精确映射仍 unknown。故意两个 primary 继续拒绝，不为“通过”删保护规则。
- [ ] 定向及完整相关回归通过后记录、提交；建立质量修复后的观察基线，供后两阶段比较。

关键预期：

```text
业务诊断前后相同；一次可信协议拒绝 => 一个失败span，duration来自同进程monotonic。
坏project/request => 无任意路径写入；遥测故障 => 原业务结果保持。
跨活动response且无明细 => shared/unknown；绝不按时间切token。
B1原3.5毫秒outline标记不能继续代表完整骨架工作；实际边界可复核。
```

## I7.5 · 限定的机械输入构造（P1）

**Files:** `runtime/ai_sow_lite/authoring.py`、`references/python-client.md`、`generate-authoring.md`、`tests/test_authoring.py`、`test_skill_contracts.py`。现有 `Client.call` 和协议 validator 保留。

**Interfaces:** 拟新增 `source_use_region(region_results, *, material_type, use) -> dict`，只返回现有 `sources[].use_regions[]` 中的一项 `{material_type, use, locators}`，不是完整 ingest payload。多个结果须属于同一 input_version_id，保持读取结果中的实际 locator/read_id；版本身份仅校验，不作为新字段输出。Agent 明确提供用途、材料类型及外层来源，助手不猜。

- [ ] 先按真实 region response 写测试：文本及 XLSX 单区域、同原件多区域、混原件拒绝、缺身份拒绝、类型/用途非法仍由原 schema 拒绝；原 dict 不被修改。
- [ ] 实现纯机械映射：核对实际来源版本 ID，取各 `source_ref(result)['locator']` 组装 `material_type/use/locators`；不同原件不自动合并。外层仍使用已登记来源的 source_path/input_id/material_types/uses，不用 input_version_id 替代 input_id，也不新增 ingest kind。
- [ ] 将 B1 场景的运行示例改用助手，实际调用公开 ingest；删掉该示例重复手写字段的部分，不扩成泛化 schema DSL。
- [ ] 真实有限分析样本对照协议失败次数、输出/未缓存输入和时间；功能及来源一致。若只是薄 API 可用但 Agent 未采用，要如实记录效果，不以单测冒充改善。
- [ ] 完整相关检查、文档同步后提交。

拟议调用形式（source_spec 为调用方选定的原 sources 条目，registered_source 为其实际登记结果；新增用途须由 Agent 显式声明，此例沿用已有用途）：

```python
from copy import deepcopy

assert {source_ref(r)['input_version_id'] for r in selected_region_results} == {
    registered_source['input_version_id']}
assert chosen_material_type in source_spec['material_types']
assert chosen_use in source_spec['uses']
source_entry = deepcopy(source_spec)
source_entry['input_id'] = registered_source['input_id']
source_entry['use_regions'].append(source_use_region(
    selected_region_results, material_type=chosen_material_type, use=chosen_use))
registered = client.call('ingest', dict(
    kind='sources', entrypoint=client.entrypoint,
    project_type=project_type, sources=[source_entry]))
```

实际来源及内容核验仍由原 ingest 负责；已有角色/用途/区域不被覆盖。不得把这个助手扩成自动材料分类、任务编排、重试或专业判断服务。

## I7.6 · 同质量配对优化与最终串联（P2）

**Files:** 以 `skills/generate/SKILL.md`、`skills/clarify/SKILL.md`、对应编写参考为主要写集合；只有新反例证明现有 helper 不足才改 `authoring.py`。评测来源/结果放新 I7 验证记录，旧资料和数字不覆盖。

**Interfaces:** 沿现有 Client 和 `{path,sha256}` 返回引用合批；不增加 `next/submit`、状态机或统一自动执行器。

- [ ] I7.4 后固定同质量基线：同一资料、用户意见、模型/effort、宿主条件及新 AC rubric。以首次方案返回和确认后交付分别计量。
- [ ] 先让 generate 完成简短身份/材料开场，之后再读所需专业参考。Clarify 只读实际对象和准确问题，标准/原文依据能复用即复用；保留真实 read_selectors 与所有必要覆盖，不能靠缩依赖让旧计划过检。
- [ ] 确认后直接复用现有 `bind_confirmation → check → render → apply` 连续调用示例。失败即停并保留成功引用；成功响应只输出必要引用和诊断，不再输出完整模型。
- [ ] 开展至多两组配对，完整记录每组质量、处理时间、响应数、缓存/未缓存输入、输出、峰值输入、失败成本和未知。缓存状态不同如实说明，不宣称统计显著或保证提速；出现任何义务回退先拒绝该优化。
- [ ] 最终运行一次完整 G1→G2→历史Excel→B1→B2→B3；以原29项加Q-AC01—07复核，同一串联内验证AC修改、采用M闭合、部分采纳及重复答复。
- [ ] 若发现新缺陷，只定向复验受影响段，旧失败和版本保留。完成产品全量、根测试、仓库验证、独立副本/Office与原生视觉检查后提交。未达到的指标写限制，不靠平均值宣布完成。

## 每阶段固定关闭条件

1. 对应真实问题有反例，机械变更有红绿证据，专业行为有实际输入/输出与逐义务评估。
2. 满足 14 的不回退条件，全部修改落在本任务文件和必要同步文档内。
3. 先运行邻近测试；行为变更提交前按 CONTRIBUTING 运行完整 Lite、根测试、仓库验证及相关独立副本/Office检查，跳过明确说明。纯规划文档至少根测试、仓库验证和 `git diff --check`。
4. 更新同一 I7 记录中的状态、实际自主选择、消耗及未解决事项；通过后该阶段一个 commit，不顺带发布。

本计划不设置产品运行 token 门禁，也不预先承诺“几分钟内必达”。完成的判断首先是正确性改善，其次才是同质量下可复核的成本变化。
