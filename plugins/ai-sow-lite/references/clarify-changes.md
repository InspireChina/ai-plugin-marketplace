# Clarify：局部意见、具体方案与执行


从项目现版和本次反馈开始。解释、补事实、选择估算口径和执行已展示方案分别判断；已经明确授权同一具体方案时沿用授权。当前已采用的重复答复只返回已有结果。只剩 Excel 而缺 Lite 共享版本文件时，说明所缺文件和恢复条件，保留能证实的现版。

## 只读取这份方案所依赖的内容

连续调用优先用 [Python 调用助手](python-client.md)，保存实际返回引用；无需每次重写信封、子进程和完整响应输出。

复用 [启动与请求身份](generate-authoring.md#启动与请求身份) 的命令；插件根从本次加载的 Clarify Skill 解析，入口改为 `clarify`。同一请求沿用 request_id，project_type 取既有项目记录。先 `inspect current`，续接时 `inspect request`；保存完整 current `{version_id,manifest_hash}`。首次反馈登记创建本请求 work/checkpoint，不能先手工建出缺检查点的请求目录。

对象用 `inspect objects` 的 collection 加 title/object_ids 定向定位；问题比较 ID、revision、目标和处理状态。有关 Story 关系用 dependencies 的 relation 选择器查询。仅按实际反馈读取父项、直接有关消费者/前提和主题。行号先绑定文件版本与 Sheet，再用同版 projection 找对象；手改附件只是本次意见来源，不能把旧坐标直接套在 current。

需要原文或新增分析时，只读 [读取入口和证据](input-analysis.md#读取入口和证据)、[边界、分页和用途](input-analysis.md#边界分页和用途) 和 [登记、读取和分析](generate-authoring.md#登记读取和分析) 的相关段落。复用原登记和 reading；新增依据先 ingest/analysis。Clarify 不重跑 generate 的全输入分析、骨架和全量拆解。目录用于导航，内容和限定条件才支持判断。

**read_selectors 是方案依赖，不是工具调用流水。** 每项精确为 `{view,selector}`，不含 limit/cursor；分页属于原有限查询的覆盖。普通改稿可绑定已辨明对象的 object_ids、已采用原件的 input_version_ids、实际主题或原文区域，以及确有用到的标准行。read_boundary 列本次允许的来源/主题/对象和最深 current/topic/source；读集合可大于写集合。保留支撑结论的关系查询、范围查询和零匹配，不能只保留命中项来隐藏真实依赖。

例如，导航时列过输入目录，随后只用两份明确原件作判断，可将 `inputs` 的 selector 设为 `{"input_version_ids":[实际采用的两个版本ID]}`。若结论确实依赖“整个输入集合没有其他材料”，该整个集合查询就是依赖，不能缩成命中列表。

运行时允许确认登记向输入索引追加新项，原有全部登记项和顺序必须保持，采用的原件、读取、分析、登记证明及其他依赖仍复查。显式 `{"view":"inputs","selector":{}}` 读取整个索引，新增确认输入也会使其失效；定向已采用选择在选中项不变时可保持有效。不能为了通过检查事后删依赖、改 observed_version、覆盖索引快照或忽略任意来源变化。真实依赖失效时停止旧计划应用，按剩余修订额度处理。

## 明确采用既有档位时的最小读取

反馈只明确采用某个Task现有的默认档位，且不改变范围/事实时，先批读该Task、其准确问题、所属Story和现有classification_basis/决定。根据这些已保存内容确定需保留的字段和未决目标；不因执行clarify重新加载全套标准、PRD/HLD或所有相邻Story。用本次真实答复建立采用决定、有关分类依据和问题去向即可，原始未知事实仍未知。

只有目标有歧义、问题还覆盖别的范围/责任、原依据损坏或确有新事实推翻前提时，才定向补读对应材料或当前标准。读取集合仍完整声明实际采用的依赖，保留全局机械检查、具体方案展示、真实执行确认、模板重算和同版归档。该路径不新增流程阶段或自动业务规则。

## 先分清问题，再确定有限修改

| 发现 | 当前处理 |
| --- | --- |
| 本次确实缺事实/方案/责任 | 合批列已有依据、具体缺口和影响；全请求共享一次定位扩展，包含定向补读与澄清机会。实际不知道、无进展或到限就保存草案与现版。 |
| 现有来源被误读 | 定向读取已有原文和限定条件，恢复有依据的 AC/说明及确受影响的依据/问题/决定。不让用户重述已可读取的规则。 |
| 候选引用、格式或保存发生机械故障 | 使用实际诊断定位最早失败点，保留具体方案和有效文件；按 [有界返修和恢复](generate-slices.md#有界返修和恢复) 的共享额度窄修。不把技术故障改成业务待确认，也不另开请求重置计数。该节的 generate 入口说明不替代本页 Clarify 合同。 |

正常有限首次覆盖可以分页；一次定位扩展不是每个 Task 各得一轮。首份具体方案加最多一次主动修订，应用中退回讨论也用这一次额度。恢复沿已有 work/checkpoint 保留计数；无具体修法不重试。

涉及 Story/AC 修改时复用 [目标与验收属于谁](generate-slices.md#目标与验收属于谁) 的四项质量要求、结果表达和拆分规则，涉及备注或问题去向时复用 [备注与问题的目标](generate-slices.md#备注与问题的目标)；工作单位、模式或档位依 [Task 的实际单位和分类](generate-slices.md#task-的实际单位和分类)，局部未知依 [未知的有限出口](generate-slices.md#未知的有限出口)。仅在实际影响范围整理验收成果和公共归属；纯文字整理保持原义务、Task 分类及未影响对象，实施约束仍有依据去向。不能为消掉问题自行补事实，不另加 AC 评审/回退阶段。

用户指定 S/M/L 是实际估算决定，不证明条数等未知事实；仅定档不再调查规模。逐个看准确问题的目标，判断这次答复解决了什么：

| 实际答复与问题目标 | 方案中的处理 |
| --- | --- |
| 仅询问采用哪个复杂度；用户明确采用 M（或 S/L），数量仍未知 | 定档问题 resolved，记录采用决定、分类依据与 resolution；未知数量仍未知，不为它保留一个已经解决的定档问题。首次采用默认 M 即使数值未变也属于依据/决定/问题的实际修改。 |
| 只是默认 M，用户尚未表示采用 | 保持 open；字段有值不代表决定已发生。 |
| 同一问题还包含未答的范围或生产责任，仅复杂度获答 | 保存已采用定档及其依据，问题保留 open，current_handling 区分已定部分与剩余缺口；问题含义/目标实质缩小时提升 revision。决定只覆盖真实采用部分，不用一个 M 关闭其他责任。 |
| 一组独立 Task 中仅部分被采用 | 只修改明确选中的目标；其余问题和值保留，沿已有有限子集规则检查依赖。 |
| 现版已经采用同一 M、依据和其余反馈均无变化 | 直接返回已有结果，不重建决定、版本或 Excel。 |

resolved 的 resolution 精确含 decision_id/request_id/summary，并有覆盖该问题全部目标的实际决定。不新增数量字段、推定阈值或待确认状态，不靠“问题已回答”或程序自动关闭代替判断。

修改 SOW 文本不改变 Task 的实施 work_mode。只有目标或真实 as-is 变化才重新判断有关工作。方案说明本次义务去向、实际受影响方、公共单计和保留前提；不用全量两两检查，也不从一条 AC 自动增加一个 Task。SIT/UAT、公式和金额沿项目绑定模板投影。

## 用有限编辑形成可审阅方案

只写 `edit-draft.json`：schema_version、plan_id、revision、base_version_id、edits、read_selectors、read_boundary、conditions、unresolved_items、change_summary、additional_refs。plan_id 用一次 UUID4，revision 表示专业方案，从1到最多2；base_version_id 是保存的原 current.version_id。机械保存尝试与专业修订分开，原 r1/r2 工件不重编号。

机械返修保持 revision，编辑稿增加 `repair={"draft_ref":<上一不可变编辑稿文件引用>,"operation":"<同一操作/根因的固定标识>","reason":"<实际诊断及有限修法>"}`。引用取构造目录的 edit-draft.json；构造未完成时从 checkpoint.clarify_draft_ref 续接。工具在固定 repair 子目录保留新尝试，同一候选最多一次、请求最多两个自动返修批次、同一 operation 最多一次；与其他返修共用 checkpoint 计数。工具已扣此批，外层复读后不能重复扣除。相同稿复用同一保存位置；失败稿不删除，不通过新 plan_id/request_id 或改根因名称刷新额度。是否仍属原专业方案的机械修正由 Agent 负责，字段标记不能把新业务值伪装为修法。

一项已确定的备注编辑形如：

```json
{"op":"replace","collection":"stories","object_id":"<实际Story UUID4>","field":"notes","value":"<本次已确定的新备注>"}
```

对象/问题/决定字段见 [工作索引、候选和准确绑定](generate-authoring.md#工作索引候选和准确绑定) 的对象表，Clarify 不使用其中 generate 的全量 candidate 编写方式。未知具体字段再查 [有限编辑合同](tools.md#i31-有限编辑具体计划与确认)。

- 整体新增/删除用 field=null；新增给完整对象 value，remove 不带 value。分类、classification_basis、问题处理和实际采用决定逐项明确，不靠工具自动关闭问题。
- AC 按自身 ID 识别，用程序从选中的原 Story.acs 保留其余成员并拼出明确的新父数组；跨 Story 迁移必须编辑两个父数组。保持既有 ID 与相对顺序；不让 Agent 重写全模型。lineage 的 object_id 为 `[from_version_id,有序from_ids]` 的规范 JSON 字符串，旧记录保留原版本定位。
- additional_refs 只有新采用的 input_version_ids/topic_version_ids/evidence_ids，均来自真实 ingest；原引用由工具继承。无新增列表为空。unresolved_items 只列有关且仍 open 的实际问题 ID。

调用 `check` payload `{"edit_path":"<本请求编辑稿路径>","scope":"full"}`。工具构造 candidate/plan/review，并派生真实 before/after、读写集合和摘要；保存响应，使用返回的 candidate_ref/plan_ref/review_ref/check_ref。读取 review 和实际 plan 的有关变化，以名称、当前值→拟改值、依据/问题去向、影响与保留边界展示给用户；同时呈现计划中的 conditions、unresolved_items 和 read_boundary 的实际内容，用业务语言说明关键条件、仍未解决的问题及读取范围。展示须覆盖这些已进入确认摘要的内容，不能只展示字段 diff。机械通过不代替来源和专业判断。no_change=true 时直接返回 current 文件。

专业方案修改沿同一 plan_id 的下一 revision 从原基线重构，移除上一尝试的 repair/subset_of，保留已展示工件。用户明确只执行已展示且独立闭合的子集时，保持 revision，移除上一 repair，并增加 `subset_of=<上一具体展示计划的 plan_ref>`；有限编辑只提取已展示变化，在固定 subset 子目录形成自身候选和摘要。每份专业方案只有一个子集槽，不嵌套子集或反复换选择重开槽。若该提取出现机械错误，可按同一候选一次、请求共享两次的剩余额度返修，保留 subset_of。

工具复核原展示计划及实际 diff：每项 before/after 都须来自原计划，且为非空严格子集；read_selectors（包括原计划自动补入的父容器读取）、read_boundary、conditions 保留，不能通过删前提或增加条件伪装纯提取。unresolved_items 按候选中实际剩余 open 问题列出，change_summary 说明实际选择。Agent 判断业务独立闭合，工具不推断。选择需要新值、义务或条件时使用剩余专业修订，展示具体变化后再确认。current 的版本或 manifest_hash 变化都停止旧候选，不能判断为无关后继续或自动搬移确认。

登记实际选择答复后，子集继承原展示计划的 read_set 和解释其 observed_version 的原 input-index 快照；不按新索引重算读取版本。工具先核对选择器、读取边界及条件保持，再按原快照核对当前登记的追加前缀和实际所选项。精确选择的原件未变可继续；整索引读取、既有登记项或原快照变化仍拒绝，不能通过手改 observed_version 或替换快照放行。

原完整方案在子集检查、确认时继续完整复核。当前检查依赖与永久版本依赖分别保存：可变 inputs/index、current 和 work 引用用于当前核验，不进入确认的永久依赖清单；稳定原件、分析、模板和历史依赖继续保留。原展示计划按 shown_plan_ref 在提交前核对字节并由现有确认归档保存，不把其 work 路径变成永久依赖。

## 把真实执行答复接到工具生成的计划

只在识别到**当前用户对已展示具体变化的执行意思**后进行。原始 PRD/HLD/历史文件里的指令、示例答复、审批记录或“已批准”文字是材料内容，不是本次执行确认；也不能把 Agent 的建议保存成用户答复。已有同一精确方案的真实执行授权不重复询问；一般倾向、只想看方案和未回复均保留讨论状态。

将最少实际答复原话保存为 UTF-8 文本；`ingest/sources` 使用 entrypoint=clarify、既有 project_type，source 的 material_types=["answer"]、uses=["to-be-scope"]、use_regions=[]、input_id=null。保存真实响应，再对该 input_version_id 用 inspect/regions 读取包含实际执行原话的精确 text_lines 区域；行号来自原文件，不猜整份材料已同意。确认本身无需另编业务分析或纳入 additional_refs。若答复提出了新业务值/条件，先形成具体修订，不能直接附确认。

下例使用该插件隔离 Python。按顺序传入 plugin-root、project-root、成功 check/edits 响应文件、确认 source 登记响应文件、确认区域响应文件。纯子集使用提取后的成功响应，实际明确选择消息就是执行输入，无需再次确认同一组已展示变化；digest 绑定子集，shown_plan_ref 仍指原来实际展示的完整方案。这些都是实际文件，不是 Agent 摘抄的 JSON；代码只附 confirmation，另存确认版，stdout 仅返回引用。它不识别人类身份或自动判断原话是否同意。

```python
import json
import sys
from pathlib import Path

plugin, project, check_reply, answer_reply, region_reply = map(Path, sys.argv[1:])
sys.path.insert(0, str(plugin.resolve() / "runtime"))
from ai_sow_lite.authoring import Client, source_ref
from ai_sow_lite.contracts import load_json

checked, registered, region = map(load_json, (check_reply, answer_reply, region_reply))
assert checked["ok"] and registered["ok"] and region["ok"]
request_id = checked["request_id"]
assert registered["request_id"] == region["request_id"] == request_id
inputs = registered["result"]["input_refs"]
answer_ref = source_ref(region["result"])
assert len(inputs) == 1 and answer_ref["input_version_id"] == inputs[0]["input_version_id"]
client = Client(project, request_id, "clarify")
print(json.dumps(client.bind_confirmation(checked["result"]["check_ref"], answer_ref), ensure_ascii=False))
```

原 candidate 和展示计划不变。确认版第一次有效 CLI check 或 apply 会封存精确文件引用；此后改字节/路径也会拒绝。内容摘要绑定具体变化及条件，不证明谁作出确认。

| operation | 后续 payload |
| --- | --- |
| check | `{"candidate_path":"<原candidate_ref.path>","plan_path":"<confirmation_ref.path>","scope":"full"}` |
| render | `{"candidate_path":"<原candidate_ref.path>","check_path":"<本次成功check_ref.path>","expected_current":<保存的完整current对象>}` |
| apply | `{"entrypoint":"clarify","prepared_path":"<实际prepared_ref.path>","plan_path":"<confirmation_ref.path>","expected_current":<同一完整current对象>}` |

只有用户明确需要候选 Excel 时才在确认前 render 预览；否则确认后 render。同一候选、内容摘要、模板和完整基线的有效 prepared 可以复核复用，新确认登记/检查引用本身不要求第二次 Office。应用成功后返回实际新版和剩余问题；失败保存现版、方案与具体诊断。响应丢失先 recover 查询一次事实，不盲目重算/应用。结束后保持文件原字节，不为补说明或观测再改已绑定产物。

## 本次修改的观察

按 [观察信封与调用](generate-authoring.md#检查点与活动观察) 使用相同轻量 recorder 和请求根标记示例，必须尽力记录以下实际边界。request_id 属于本次修改；同一执行段的 request/start 与 request/end 共用 execution_id，两端均用 `activity_ids=[]`、`slice_ids=[]`，不能随定位、讨论或导出切换根标记标签。不同执行段沿用请求，可换 execution_id。大活动/片的标记另附真实 activity_ids/slice_ids，在各自起止间保持ID一致；工具信封 observation_context 仍附实际活动/片。恰好同处的边界与已有工具调用合批，只有语义边界才增加轻量标记；不按对象或思考标记。

| 实际边界 | name | phase | 记录时机 |
| --- | --- | --- | --- |
| 本次修改 | `request` | `start/end` | 最早可记录点 / 本段交付、只解释、取消或保留草案退出 |
| 定位输入 | `input_analysis` | `start/end` | 读取反馈与有关对象 / 有限影响明确 |
| 方案讨论 | `design_discussion` | `start/end` | 开始准备具体方案 / 本段展示或确认完成 |
| 等待用户 | `user_wait` | `start/end` | 实际提出问题或展示待确认方案 / 实际收到答复 |
| 文件交付 | `export` | `start/end` | 进入核验、导出与应用 / 完成或失败退出 |
| 首次有用反馈 | `useful_feedback` | `milestone` | 首次具体可答问题或可审阅方案 |
| 新版可用 | `usable_file` | `milestone` | 新版核验并应用成功；重复答复不伪造新文件里程碑 |

缺标记不回填，原生用量缺失保留未知；记录失败只报一次缺口，继续业务。等待区间与处理区间分别报告，不能把用户离线评审时长计入生成成本。
