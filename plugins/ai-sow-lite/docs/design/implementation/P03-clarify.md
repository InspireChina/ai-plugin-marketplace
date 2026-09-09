# P03 · Clarify 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户在保留 `.ai-sow-lite/` 共享文件的原项目中开启新会话，回答问题或提出意见，讨论具体方案后，只更新确认范围并得到新 Excel；不依赖原聊天，也不承诺仅凭 Excel 附件恢复。

**Architecture:** 单人串行 clarify 独立读取文件；Agent 定位影响并提交有限编辑，Python 构造完整候选/具体计划、检查 diff 与确认并一致生效。I1 的原模板填值通道复用，讨论本身不改 current。

**Tech Stack:** P01 的 Python/JSON Schema/本地文件/Office，P02 的来源读取与真实宿主交互。

**Spec:** [D05](../detailed/D05-clarify-and-change-scope.md)、[EX05](../detailed/examples/EX05-clarify-changes.md)、[D02](../detailed/D02-shared-data-and-evidence.md)、[D04B](../detailed/D04B-bounded-loops.md)、[D07](../detailed/D07-tools-storage-and-recovery.md)、[P00](P00-contracts-and-fixtures.md)。

## Global Constraints

- 初版 SOW 已有效，不需定稿；clarify 是新请求，generate 聊天不作为必要输入。
- 先准备具体可审阅变化，用户确认后应用；已明确授权同一具体方案不重复问。
- 对象、字段、问题修订/目标/标记、决定、依据和 lineage 均纳入范围；没有“顺手修全部”的自动回退。
- 同一个人串行修改；current 不等于方案基线即拒绝旧候选应用，不做并发修改衔接、无关变化判定或跨版本确认复用。
- 金额让既有模板计算，插件只填输入、保留公式和检查文件；不改模板、不增加金额状态/保护或差额算法。
- 首份方案加最多一次主动修订；应用返回讨论占同一额度，恢复/返修执行 D04B。
- 修改 SOW 文字不是实施方式“调整”；确认 M 可保持分类值并产生问题/决定的新版本；真正无变化不新建版本。
- [12 资料吸收评估](../12-reference-absorption.md) 的错误归因和局部修正方法写入 references/clarify-changes.md。输入缺事实、对已有证据的误读、程序错误分别处理；不把 Agent/程序错误包装成用户补料，也不引入 Owner 回退或重新执行 generate。

## I3.1 · 稳定地址差异、实际方案和确认绑定

**Files:** 新建 contracts/change-plan.schema.json（用 $defs 同时定义计划和有限编辑稿）、tests/test_clarify.py、clarify 夹具；扩展 runtime/ai_sow_lite/{validation,project,cli}.py、protocol.schema.json、artifacts.schema.json、references/tools.md。

**Interfaces:** 消费 P00 prepare_edit/diff_bundle/verify_plan 与 check/edits，派生 changes/read_set/write_set、具体 review 和确认摘要；Agent 提供专业编辑及 read_boundary。analysis 先通过 ingest 登记，新引用纳入实际计划写集合，复用 I1 prepared。

- [x] 建立三种最小基线与反馈：默认 M→S；确认默认 M 不变；仅修 AC/备注。基线由真实 I1 交付生成，旧版本可查；反馈作为实际最少文本输入登记，不凭空创建“用户已确认”的决定。
- [x] 实现 P00 的 edit-draft 和 prepare_edit：check/edits 只接有限新值/增删、明确问题和决定处理、依赖选择与边界；从当前基线复制文件到 work，机械构造候选、plan 和 review。返回文件引用，不回显全量模型；不自动关闭问题、补分类或增加语义依赖。未知 ID、重复矛盾编辑、隐式级联和过期基线合批诊断。
- [x] 在包含数百个 Task 的受控基线仅提交一个 Task 分类及对应依据/问题/决定的有限编辑，断言所有未涉及对象与顺序不变，派生 before/after/write_set 与实际差异一致。记录模型侧输入/输出及文件写入量；不能把完整文件复制称为 Agent 已重生成。嵌入 AC 的替换/跨 Story 迁移按 P00 明确父数组编辑测试。
- [x] 实现按 ID/字段的 diff，保留模型展示顺序，新增/删除比较完整内容。覆盖 AC ID 与父 Story.acs、问题 revision/resolution、classification_basis、决定、关系、lineage 和候选采用依据；不将 Excel 行位移混入业务 diff。替换后的具体值也必须一致，不只看字段在白名单。
- [x] check full + plan 同时验证：候选实际差异等于 changes；变化均落派生 write_set；read_set 所读版本和已登记来源可解析；current 仍是原基线；待确认状态和义务去向闭合。义务范围/含义由 Agent 核对，不为串行用法实现字段/关系级冲突合并摘要。

```python
def test_same_field_different_value_is_not_confirmed():
    from ai_sow_lite.validation import diff_bundle
    before = {"tasks": [{"id": "00000000-0000-4000-8000-000000000006",
                         "complexity": "M"}]}
    after = {"tasks": [{"id": "00000000-0000-4000-8000-000000000006",
                        "complexity": "L"}]}
    changes = diff_bundle(before, after)
    assert len(changes) == 1
    assert changes[0]["field"] == "complexity"
    assert changes[0]["before"] == "M"
    assert changes[0]["after"] == "L"
```

diff_bundle 按传入集合计算结构差异，此小例不冒充完整模型。对应完整夹具展示并确认 M→S，候选却为 L 时，verify_plan/apply 必须 SCOPE_EXCEEDED；候选不能通过“字段是 complexity”获准。

- [x] 实现 P00 确认绑定，hash 排除 confirmation 自身/文件路径，包含具体内容和关键条件。用户原确认输入与被展示方案可达；没有实际执行意思保持 work。程序校验绑定不等于独立认证用户身份。
- [x] 测 field 相同值不同、超范围改备注、漏记 question.revision、删除未拆明工作问题但义务仍在、lineage 错版本、open 指向退出对象、检查后改候选字节。错误合批返回；默认 M 不因 issue open 被非法拒绝。
- [x] 执行 `uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_clarify.py plugins/ai-sow-lite/tests/test_contracts.py -q`。这些测试通过后再接实际交互，避免只在 Skill 中口头限定范围。

## I3.2 · 文件独立的讨论、有限方案与应用

**Files:** 创建 skills/clarify/SKILL.md、references/clarify-changes.md；扩展 tests/test_skill_contracts.py、README/插件元数据；新增 docs/validation/I3-clarify.md。

**Interfaces:** 消费现版指针/manifest/projection、输入答复与 P00 six operations；产出 work/clarify/<request-id>/plan.json、可读方案、具体候选和用户确认引用，然后复用 I1 render/apply。

- [ ] 入口先用 inspect current/request 获取身份、待确认索引和本次反馈相关对象；行号必须绑定版本+Sheet，经 projection 反查。不明名称返回少量候选，旧 Excel 被手改/重排先读取对应附件或按名称/父项核对，不拿旧坐标直接写 current。
- [ ] 只读取本次所需对象、关系邻域与原文；新材料按 D03 登记。Agent 写有限编辑、问题/决定去向、read_selectors/read_boundary 和关键条件，调用 check/edits 后读取其 review；前后值/写集合/摘要由工具派生。公共/交付影响在展示前说清，不能让用户确认“修改这个 Story”后再决定具体内容。
- [ ] 在 references/clarify-changes.md 落实下表的归因和处理方法；语义问题由 Agent 判断，程序只返回具体结构/引用/保存诊断。相关标准与输入规则引用既有参考文件，不再次复制整套生成指引。使用 `tests/fixtures/clarify/cases/` 下的给定反馈与独立期待，沿 P00 隔离被测输入。

| case-id / 触发 | 具体方案与验收 | 不应发生的行为 |
|---|---|---|
| `correct-source-reading`：EX01 的原 PRD 明确“迟到响应不覆盖新查询”；一个已交付的合成基线误写成“迟到响应覆盖当前结果”。用户指出与输入不符 | 用真实 I1 通道构建该结构合法的错误基线，标明故障由测试植入。定位原文，拟恢复有关 AC 及其依据，展示确切修改；确认后只改变受影响字段/问题/决定与派生输出，其他任务含模式/复杂度保留 | 让用户重新定义已有规则、重新上传已可读取的 PRD，或因此重拆全部 Story。机械校验通过不能被写成已证明语义正确 |
| `answer-complexity`：用户“迁移复杂度按 S”；另一个变体为“默认 M 就可以” | 沿 I3.1 三种基线中的现成两种执行：前者更新档位及依据/问题，后者保留 M 但记录决定并关闭问题。不补造条数，未答问题继续保留 | 为确认档位重新调查规模，或 M→M 首次采用被误判成无操作 |
| `candidate-reference-error`：讨论方案已明确，测试在候选中植入悬空依据 ID | 程序合批返回引用诊断，保存原有效版。已有正确依据可达时，仅修候选引用并在 D04B 额度内重检；无法修好则保留草案和具体错误。若修正改变了已展示语义/范围，沿同一方案修订额度重新讨论 | 把程序错误转成业务待确认项、要求用户决定一个 ID 或多给一轮返修额度；未正确修复仍应用候选 |

`correct-source-reading` 与 `answer-complexity` 用真实交互验证，不另设独立 Reviewer；`candidate-reference-error` 使用 I3.1 的机械故障测试并核对用户出口。用户指定档位时，仅关闭已由估算口径决定解决的事项；原问题若还包含影响范围、方案或责任的事实缺口，按部分答复规则保留，不能把用户定档记为事实已补足。确认绑定范围按 P00 保持一致，任何修法都不能绕开用户对具体业务变化的确认。

用户可审阅方案使用以下固定信息，而不要求技术字段名出现在用户流程：

```text
拟将“资料迁移”的复杂度由当前默认 M 调整为 S，其他 Task 保持现有内容。
对应待确认事项采用你指定的 S 口径并关闭；不补造迁移条数等事实。
需要更新的范围：该 Task 的复杂度、依据、该问题及本次采用决定。
工作簿相关金额和汇总由模板重算。原业务范围和迁移责任仍是本方案依据。
```

这是具体候选的可读投影；实际标题/值/影响从当前文件取得。不能先发泛泛“调整这个 Story”，确认后才决定 Task 内容。

- [ ] 仅在用户明确要求候选 Excel 时批量生成原模板预览，不计算或比较金额；只解释/无变化不 render。确认后同一候选、模板和基线未变则复用 prepared。用户明确选择已展示的独立子集时，将对应有限编辑交给同一构造入口生成其候选和摘要，不提交完整包；若需新义务/新值才成立，先展示修订，不能机械裁剪依赖。
- [ ] 未确认、取消或超过一次主动修订则保存讨论草案结束，current 不变；用户未回复不能算认可。真正已采用的重复答复直接给当前文件和说明，不造空版本；这个只读结果由 request work 记录引用，不需要伪造 apply manifest。
- [ ] 接收明确确认后调用 verify/check、必要 render、apply；合法未知仍随新版本保留。按同版状态处理部分答案，未解目标继续 open；目标实质缩小升 revision，不能把未答内容关闭。
- [ ] 从 **只提供 I2 项目文件的新会话** 运行三个基础反馈。默认 M→M 必须更新依据/决定/问题，M→S 改值，备注改稿必须保留原 Task 工作方式。只解释已有决定则无新版本、不重算。
- [ ] 将上述误读修正并入 AC/备注反馈演练，比较应用前后每个未涉及对象及相关问题状态；正确方案第一次展示即应完整，不能靠逐轮发现漏改来完成。后续真正的新用户反馈另建请求，本次重试/修订计数不重置。
- [ ] 执行 Skill 合同与 clarify 测试；把实际展示内容、用户执行意思、前后差异、未改对象摘要和最终文件记录在合成验证包，证明无需 generate 聊天。不把写入测试候选的结果当实际 agent 讨论验证。

## I3.3 · 串行基线、恢复与实际使用周期

**Files:** 扩展 tests/{test_clarify,test_project,test_telemetry}.py、tests/support/smoke_plugin.py、docs/validation/I3-clarify.md 与 D09。

**Interfaces:** 消费冻结方案、原 read_set、当前有效基线和 I1 的短锁提交；产出正确的新版本/未应用诊断/已成功结果，以及独立 clarify 成本报告。

- [ ] 先验证顺序的两次 clarify：第二次读取第一次成功的 current，保留不相关对象，分别记录确认和结果；回查旧请求成功结果不能倒退 current。
- [ ] 故障测试中替换 current 身份或提交过期草案，断言 BASE_STALE 且 current/旧版本原字节保留，不比较变化相关性、不重建候选或复用旧确认。误重复调用遇短锁时 WRITE_BUSY，不持锁回查或等待；这不是并发改稿成功场景。
- [ ] 覆盖取消在 render 前、Office 中、锁前与指针后到达；仅“已观察到”取消可强制判断，宿主不能传信号时写明限制。指针后不撤销已成功版；返回旧请求成功事实并允许用户后续用新 clarify 撤回具体内容。
- [ ] 真实包在 apply 前和响应返回前注入中断，恢复查询一次；同 ID 意图一致幂等返回，不同意图拒绝。已应用结果不因 telemetry 收尾失败重算或重复应用。

```python
def test_recover_does_not_activate_a_draft(case):
    from tests.support.cli import run_request
    from tests.support.fixtures import prepare_case
    prepare_case(case)
    reply = run_request(case.project, case.request_id, "recover",
                        {"target_request_id": case.request_id})
    assert reply["ok"]
    assert reply["result"]["state"] == "draft"
    assert not (case.project / ".ai-sow-lite" / "current.json").exists()
```

这是 I1 基础防线在 clarify 包上的复用；完整 clarify 故障夹具已有 current，需进一步比较前后 pointer 与旧版本字节不变。recover 本身不是 apply，也不把工作簿存在当确认已获准。

- [ ] 实际完成 generate→离线查看→新会话 clarify→确认→新 Excel 一次使用周期。单独记录方案准备、可观察的用户等待、确认到文件耗时/usage、取消/失败成本；不把整个离线评审期计入 generate。
- [ ] 扩展 smoke 时落实 AD09：记录实际 CLI 进程/操作，逐一核对审计收据并检查启动/退出 stderr；用缺失单条收据反例证明不会仅凭数量门槛报告完整。执行 Lite 全部测试与独立复制 smoke，核对新 Skill 只从插件及项目读文件；更新两入口当前能力与限制。跨片拆合/复杂子集在 P04 扩展，其尚未验证分支不能提前宣布全支持。

**I3 退出：** 新会话完成文件独立修改，实际变化与确认一致，必要派生输出完整、无无关重拆和重复应用。用户接受当前结果后无需再次调用插件；接下来 P04 补承诺范围与性能证据。
