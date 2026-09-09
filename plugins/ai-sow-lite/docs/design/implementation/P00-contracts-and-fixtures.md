# P00 · 共用合同与验证夹具

[实施目录](README.md) · [D02 数据](../detailed/D02-shared-data-and-evidence.md) · [D07 操作与保存](../detailed/D07-tools-storage-and-recovery.md)

本文件补齐实现必须一致的机械表达；业务含义仍由 D01—D08 定义。它不安排独立的基础平台开发，字段在首次消费者对应的 I1/I2/I3 任务中实现。

## 1. 文件和协议版本

- 首个 `protocol_version`、交付/方案/工件 `schema_version` 均使用字符串 `"1.0"`；摘要格式为 `json-v1`，投影适配为 `lite-projection-v1`。插件包版本另由交付元数据维护，不与这些版本号混用。
- JSON Schema 使用 Draft 2020-12；未知协议/Schema/投影版本拒绝，未知业务字段拒绝。观测信息缺失可降级，非法业务字段不能按观测异常忽略。
- 稳定 ID 使用本地 UUID4；设计例中的 T-06 等只作可读映射。单个逻辑请求持续复用 request_id；工具生成 execution/operation/attempt/version ID，不能以换 ID 重置次数。
- `contracts/model.schema.json`、`pending-items.schema.json`、`decisions.schema.json`、`evidence.schema.json` 分别落实 D02。`protocol.schema.json` 管调用；`artifacts.schema.json` 用 `$defs` 管 project、candidate、manifest、reading、analysis、checkpoint、检查/投影报告；I3 的 `change-plan.schema.json` 管方案。不要为每个内部字典再建一份 Schema。
- 业务模型没有人天、倍率、数量乘数、人工 SIT/UAT 或估算完整性字段。未明复杂度直接 M+问题；其他 null、不适用、unestimated_work 按 D02，只表达业务事实，不驱动金额或公式。

所有下面的实现路径相对 `plugins/ai-sow-lite/`。运行文件相对显式项目目录；持久引用统一 POSIX 相对路径，解析后必须仍位于相应项目子目录。只有首次 ingest 的 source_path 可指向用户提供的外部材料；拷贝后只引用原件副本。符号链接逃逸、`..` 逃逸、未登记的外部引用拒绝，不把外部路径写入交付或遥测。

## 2. 唯一 CLI 与信封

```text
python scripts/lite.py --request <UTF-8-JSON-file>
```

脚本从自身位置加载同插件运行时；Skill 使用安装目录内的隔离 Python 和绝对脚本路径调用，项目通过信封显式传递。测试从不同 cwd 调用，证明不依赖仓库位置。

```json
{
  "protocol_version": "1.0",
  "request_id": "00000000-0000-4000-8000-000000000001",
  "project_path": "./example-project",
  "operation": "inspect",
  "payload": {"view": "current", "selector": {}, "limit": 20, "cursor": null}
}
```

project_path 相对调用 cwd 解析一次；示例请求需放在测试工作区，不能作为真实客户运行命令。可选 observation_context 仅含 D08 的 execution_id/activity_ids/slice_ids。

stdout 只输出一个 UTF-8 JSON 结果，固定字段 `ok/request_id/operation/result/diagnostics`。result 的大内容以 `{path, sha256}` 文件引用返回；小摘要包含数量、版本、范围和续读位置。结果预算只限制工具返回大小，不判断业务充分性。异常 stderr 保持脱敏，完整错误不回显输入。

退出码：0 表示操作完成（可有合法未知）；2 表示请求/版本/候选/边界不合法；3 表示可诊断的 I/O、锁或计算故障；4 表示观察到取消且未应用；未预料错误为 1 并给 `INTERNAL_ERROR`。如果已越过生效点，即使收尾失败也返回已应用事实；响应丢失由 recover 查询。错误结果也必须有信封，CLI 无法解析请求时 request_id 可为 null。

诊断结构固定 `code/target/message/preserved_paths`。target 使用文件引用、对象 ID 与字段，未知部分可 null；D07 已有错误码保持原值。补 `REQUEST_ID_CONFLICT` 表示同 ID 已封存意图不一致，`PROTOCOL_INVALID` 表示信封错误，`LOOP_LIMIT_REACHED` 表示已可见次数到限。一次返回全部同候选诊断，供 agent 合批处理；不逐个错误逼出往复调用。

### 操作 payload 与返回字段

表中未出现的专有字段不接受；空数组/可选值语义写入 Schema，不以缺字段猜默认业务值。所有 `*_path` 除 source_path 外均按项目相对路径。

| 操作 | payload | result 的必要字段 |
|---|---|---|
| ingest / sources | `kind="sources"`、`entrypoint`、`project_type`（new/existing）、`sources[]`；source 含 source_path、input_id（首登 null）、material_types、uses、use_regions（无区域为空） | project_id、input_refs、reading_refs、failures、checkpoint_ref；部分成功保留引用，整体 ok=false 且列失败 |
| ingest / analysis | `kind="analysis"`、entrypoint、`analysis_path` | analysis_ref、evidence_ids、topic_version_ids；只登记、不开 current |
| inspect | `view`、`selector`、`limit`、`cursor` | selected_version、items 或 content_ref、matched_count、returned_count、remaining_count、next_cursor、coverage、report_ref（不适用为 null） |
| check / candidate | `candidate_path`、`scope`（slice/full）、`plan_path`（无则 null） | check_ref、candidate_ref、plan_ref、review_ref、candidate_digest、valid_for_render、unknowns_count；无计划时 plan_ref/review_ref 为 null；slice 通过仍不能 render |
| check / edits | `edit_path`、`scope="full"`；与 candidate_path/plan_path 互斥 | 同上；先在 work 机械构造候选与具体计划，再检查；不改变 current、不代确认 |
| render | candidate_path、`check_path`、`expected_current`（指针对象或 null） | prepared_ref、version_id、workbook_ref、projection_ref、summary_ref、pending_items_ref、details_ref（无长内容为 null）、office_identity、verification_ref、pending_count；不激活、不返回金额状态 |
| apply | `entrypoint`、`prepared_path`、expected_current、plan_path（generate 为 null） | applied_version、manifest_ref、workbook_ref、idempotent、current_version；原请求已应用优先返回 |
| recover | `target_request_id` | state（applied/draft/cancelled/incompatible）、applied_version、preserved_paths、diagnostics_ref；只查事实，不激活孤立版本 |

ingest 续接只复核已知 project_type，不因新 payload 改项目身份。entrypoint 为 generate/clarify。analysis 的结构按 D02/D03：一个候选包含 evidence、topics、真实 observations 及引用附件；工具校验并拆存不可变工件。model.json 不能通过这一通道生效。

inspect.view 首版为 current、inputs、regions、topics、objects、standards、request、telemetry。selector 按 view 为互斥结构：版本/ID 集、已登记区域定位、关系查询、标题检索或问题状态；不得把任意路径/SQL/脚本塞进 selector。`objects` 关系查询返回查询条件、成员及所读版本，零结果同样保留查询和版本；串行改稿不维护用于自动合并的字段/关系成员摘要。`regions` 使用 D03 locator；`standards` 返回定性标准及规模门槛，不返回估算倍率副本。cursor 绑定查询、来源版本和上次结束位置，失效返回诊断；没有命中不扩大查询。默认20条、最多100条、单次正文最多64 KiB，超限提供准确续读；这些是首版可调整的物理分页参数，不是 token 配额。

### 纯语义活动怎样埋点

六项操作以外只提供一个内部观测入口：`python -m ai_sow_lite.telemetry --project <project-dir> --mark-file <mark.json>`，使用同一隔离 Python。mark 字段为 schema_version、request_id、execution_id、activity_ids、slice_ids、phase（start/end/milestone）和 name；程序填写实际 observed_at/事件身份，再调用 append_event。它不接受业务候选或下一阶段，不改变 checkpoint/current，失败按 D08 降级。只有没有现成宿主生命周期事件的大活动边界才调用，不每次思考都打一次工具点。

短命 CLI 的两个标记只能证明两个观察时刻，不能当作同一进程的单调时钟区间或精确模型耗时。报告保留这种时间口径；工具时长来自真实进程内时钟，模型耗时来自已验证宿主事件。request end 标记触发一次有界采集/报告重建，已交付 summary 保持原快照；不等待迟到 usage。此适配自 I1.4 实现，I2.3 验证能采到的实际粒度和自身开销。

## 3. 候选、检查与准备结果

候选由本请求 work 中的 `candidate.json` 描述，字段固定：schema_version、entrypoint、base_version_id、model_path、pending_items_path、decisions_path、evidence_ids、input_version_ids、topic_version_ids、template_hash。被引用 JSON 可在同一请求的 slice/merged 目录；完整 render 只接合并候选。依据本体由已登记不可变 analysis 工件解析，不在每个候选复制。

候选语义摘要覆盖以上实际内容、所用依据身份/内容、模板和基线；对象数组顺序保留，不能为了“同样内容”重排业务展示顺序。check 报告绑定实际文件字节、依赖摘要、Schema/验证器版本和 scope。检查缓存只能由程序生成并复核，不接纳 agent 写的 valid 标志。

render 分配本次准备的 version_id，保存 `prepared.json`：schema_version、version_id、candidate_ref、check_ref、expected_current、files、template_hash、projection_version、office_identity、verification_ref。files 含最终 model/pending/decisions/projection/sow/summary、可读 pending-items.md 及按需 details.md；manifest 在 apply 之前完成。summary 只写范围、变化、待确认与当前观测快照，不计算、解释或标记金额完整性；输出文件被绑定后不能为补最终 usage 改写。

prepared.json 是候选准备记录，不是已经应用的收据。apply 复核实际字节与有效检查记录；current 指针 `{version_id, manifest_hash}` 原子替换才生效。manifest 采用 D07 字段并列出所有可达输入/分析/观察附件/历史版本依赖。读取器选定一个 current 后始终读取该版。

### 有限编辑怎样构造完整候选

Clarify 的 Agent 不需要重输出全量模型或手写重复的 before/after、write_set、hash。它写一份 `edit-draft.json`，调用现有 `check` 的 edits 输入形式；I3.1 实现该机械接缝，I1 不提供伪实现。

编辑稿字段为 `schema_version/plan_id/revision/base_version_id/edits/read_selectors/read_boundary/conditions/unresolved_items/change_summary/additional_refs`。additional_refs 只含本次新增的 input_version_ids/topic_version_ids/evidence_ids 三个列表，无新增为空；均必须已通过 ingest 登记，基线已采用的引用由代码继承。read_selectors 每项为 {view, selector}，只使用 inspect 已支持的视图和选择器；专业依赖由 Agent 指定，代码不能从 diff 猜齐。工具从选定不可变版本及登记工件解析 observed_version，将带 view 的选择器和版本写入 read_set。

edits 的每项为 `op/collection/object_id/field` 加必要的 `value`。op 为 add/replace/remove；增删完整对象时 field=null，add/replace 必须给 value，remove 不给 value。编辑对象限于第4节的模型/问题/决定集合，依据集合由 additional_refs 登记；嵌入 AC 的编辑统一替换所属 Story 的 acs 字段，迁移 AC 明确编辑两个 Story.acs，不引入虚拟父字段或数组下标协议。lineage 沿用既有复合键。已有字段替换保留原顺序，完整对象新增按编辑稿顺序追加到所属父项的现有同级项之后；删除只移除明确对象，不自动级联。其他重排首版不支持。同一地址重复编辑、父对象/字段与子字段交叠、未知 ID 或隐式级联合批拒绝；新增引用按不可变身份去重，不删除基线引用。

构造过程固定为：核对 base_version_id 等于 current → 代码复制基线 JSON 到本请求 work → 应用明确编辑及新引用 → 派生实际 diff、write_set 和必要父容器地址 → 解析所选依赖版本 → 生成 plan.json、可读 review.md 和 candidate.json → 完成现有 full check。read_boundary 与业务条件原样来自 Agent；问题、决定及其状态必须由编辑稿明确给出，不根据数值变化自动关闭。失败保留草稿并合批返回诊断，不写稳定版本。

check 返回以上文件引用及少量诊断，不回显完整模型。相同编辑稿/基线可复用同内容工作工件；内容变化形成新计划修订，不能覆盖已展示并确认的版本。check 验证候选与计划相符；confirmation=null 不妨碍检查或草案预览，但 apply 必须有具体确认。用户确认 review 后，仅填 confirmation 的真实输入引用与摘要；后续 check/candidate、render、apply 复用同一候选，不再构造不同专业内容。生成的 read_set/write_set/changes/hash 都由代码维护，但确认所覆盖的语义仍由 Agent 与用户负责。

I1.3 首次消费投影合同：`projection.json` 内使用 D06 的 `projector_version`；prepared/manifest 沿用已有 `projection_version`。两者保存同一投影器版本值，分别属于各自工件的固定字段名，不在一个文件内添加兼容别名。

## 4. 摘要、变更与确认不得混用

文件摘要固定为原字节 SHA-256；文本来源摘录按 D03 保留原换行。JSON 语义摘要只用于候选与方案内容，定义如下，不能用于替代文件摘要：

```python
import hashlib
import json

def canonical_json_bytes(value: object) -> bytes:
    def validate(item: object) -> None:
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise TypeError("JSON object keys must be strings")
            for child in item.values():
                validate(child)
        elif isinstance(item, list):
            for child in item:
                validate(child)
        elif item is not None and not isinstance(item, (str, bool, int)):
            raise TypeError("digest values cannot contain floats or non-JSON types")
    validate(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")

def semantic_digest(value: object) -> str:
    return "json-v1:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()
```

输入解析拒绝重复 key、NaN/Infinity、孤立 surrogate；协议中的整数不转为浮点，机器 digest 对象禁止浮点，XLSX 数字摘要使用带类型的十进制字符串。JSON 字符串不 trim、不转大小写、不作 Unicode 归一化。测试固定 `{"z":"中文","a":[1,true,null]}` 的 bytes 为 `{"a":[1,true,null],"z":"中文"}`，并验证业务文字空白变化会变摘要、对象 key 顺序不会。

P03 方案沿用 D07 字段。changes 为稳定地址的操作数组：`op`（add/replace/remove）、`collection`、`object_id`、`field`（null 为整个对象）、`before`、`after`。collection 为 epics/features/stories/acs/tasks/dependencies/lineage/pending_items/decisions/input_refs/topic_refs/evidence_refs。三个引用集合的 object_id 为对应不可变身份，新增登记也纳入实际 changes/write_set，不作为计划外元信息；before/after 使用实际引用身份或 null。AC 地址用 AC ID，在 read/write_set 同时列父 Story.acs；没有数组下标 patch。lineage 本无 ID，以 from_version_id + 有序 from_ids 的规范键寻址；禁止为方便 diff 给所有域对象再套包装。

首版字段修改保持既有对象的相对顺序；新增按第3节的有限追加规则，删除仅移除明确对象。未表达在具体变化中的重排视为候选越界，不能因按 ID 做 diff 就忽略数组顺序漂移。

read_set 每项为 selector、observed_version，记录实际所读对象、来源、模板或关系查询所在的不可变版本。当前版整体身份不一致即拒绝应用，不设计字段/关系级冲突合并摘要。write_set 由实际 diff 派生，列目标字段或整个增删对象；read_boundary 为允许来源/主题/对象集合及最深层级（current/topic/source）。元信息变化同样列入；派生 Excel 的行位移不成为业务 changes。

确认内容摘要覆盖 plan_id/revision、original base_version_id、changes、read_set/write_set/read_boundary、conditions、unresolved_items 及可读 change_summary；**不包含 confirmation 自身或导出路径**。确认保存 digest、用户明确执行意思的最小输入引用、展示方案引用与所选变化。已展示且独立闭合的子集生成自身摘要并保留展示关系。任何专业内容/条件变化都重新核对确认，不能靠措辞概括授权任意改写。

项目由同一人串行生成和修改，原确认方案保持不可变。current 与 base_version_id/expected_current 不同即返回 BASE_STALE，保留草案与有效文件；不判断变化是否无关，不自动换基线、复用跨版本确认或重建候选。manifest 只保存本次 base_version_id，不另存实际应用基线。顺序进行的后续请求自然使用最新 current；过期草案需基于当前版定向续接，不能直接应用旧确认。

摘要只绑定**确认的内容**，不能证明**谁说了确认**。宿主有实际用户消息引用则保存引用；否则保存最少实际答复为补充输入。Skill 负责识别真正的用户执行意思；不得声称一个 JSON confirmed 标志能独立防止 agent 冒充用户。Generate 的原始生成请求已经授权首版，无附加确认。

讨论中的同请求可以按 D04B 修订；不可变意图摘要在 generate 交付候选或 clarify 已确认具体方案进入应用时封存，不能在第一句模糊反馈时封存整个未来方案。已应用同请求同意图返回原版本；已封存不同意图报冲突；后续真实新反馈另建请求。未应用的准备失败可重试相同意图，修法不自动扩大范围。

## 5. 内部模块的最小接缝

初版用标准库数据结构，`runtime/ai_sow_lite/contracts.py` 集中别名、严格 JSON 与摘要；不加入 Pydantic/状态机。`JsonObject` 为 `dict[str, JsonValue]`，JsonValue 递归含 null/bool/int/str/list/dict（含数值的读取附件用类型化字符串）。下表返回的 JsonObject 均有上文 Schema，不是无契约的任意返回。

| 所在模块 | 函数签名 | 约束 |
|---|---|---|
| cli | `execute(request: JsonObject) -> JsonObject` | 六操作分派，隔离异常与计时，不决定专业下一步 |
| inputs | `ingest_sources(project: Path, request_id: str, payload: JsonObject) -> JsonObject`；`ingest_analysis(project: Path, request_id: str, payload: JsonObject) -> JsonObject`；`inspect_view(project: Path, payload: JsonObject) -> JsonObject` | 初始化经 project；来源与读取分别登记 |
| validation | `check_candidate(project: Path, candidate_path: Path, scope: str, plan_path: Path | None) -> JsonObject` | 返回可保存检查报告；读取模板定性合同，不估算 |
| project | `initialize(project: Path, project_type: str, template: Path) -> JsonObject`；`apply_prepared(project: Path, request_id: str, payload: JsonObject) -> JsonObject`；`recover_request(project: Path, request_id: str) -> JsonObject` | project 参数为根目录，内部统一追加 .ai-sow-lite；锁内短操作 |
| workbook | `render_candidate(project: Path, request_id: str, payload: JsonObject) -> JsonObject` | 生成 prepared 及文件，不切 current |
| office | `recalculate(source: Path, destination: Path) -> JsonObject` | 身份/检查位置/耗时，真正重算；异常转稳定诊断 |
| telemetry | `append_event(project: Path, event: JsonObject) -> None`；`build_report(project: Path, request_id: str) -> JsonObject` | 白名单、来源去重与降级；不改变业务文件 |
| validation（I3） | `diff_bundle(before: JsonObject, after: JsonObject) -> list[JsonObject]`；`verify_plan(project: Path, plan_path: Path, candidate_path: Path) -> JsonObject` | 同一 ID/字段规则与确认比较，拒绝同字段异值 |
| validation（I3） | `prepare_edit(project: Path, request_id: str, edit_path: Path) -> JsonObject` | 只由 check/edits 调用；返回 candidate_ref/plan_ref/review_ref，构造 work 工件，不改变 current、不代作专业决定 |

大函数可按实际复杂度拆内部 helper，但不得改公共操作来推动专业步骤。模型集合加载一次，在内存中作引用/diff；不为这些函数新增数据库、HTTP 服务或跨插件 import。

## 6. 夹具必须能真的执行

I1 创建 `tests/__init__.py`、`tests/conftest.py` 与 `tests/support/fixtures.py`。Case 数据对象的字段为 project、request_id、candidate_path、template_hash、ids；ids 将 EX01 的可读别名映射到固定合法 UUID。I1.1 的 fixture `contract_case` 是直接构建的独立文件校验夹具：真实合成字节、实际定位/hash、按合同组织的源/分析文件，不声称调用了 ingest 或已交付。I1.2 完成后，fixture `case` 通过真实 ingest 取得身份/read_id/hash，再绑定已审阅候选；I1.5 及后续完整通道测试只用后者。模板始终来自 Lite assets。

共用测试 helper 放 `tests/support/cli.py`，接口 `run_request(project: Path, request_id: str, operation: str, payload: dict) -> dict`。它将信封用严格 JSON 写入测试临时目录，用 `sys.executable`、已解析的本插件脚本、`subprocess.run(..., capture_output=True, text=True, timeout=180)` 调用，解析唯一 stdout 信封并检查 exit/ok 一致；非零业务诊断返回给测试断言，超时则测试失败。timeout 是测试进程防挂起，不是生产总预算。

| 夹具目录 | 真实文件/变体 | 独立判定依据 |
|---|---|---|
| `tests/fixtures/generate/` | EX01 的 prd.md、hld.md、answers.md；candidate JSON；新增三类义务 expectations.json | 三类责任、公共单计、来源 AC、默认 M；期待义务不是固定生成措辞 |
| `tests/fixtures/excel/` | EX04/EX07 的候选变体描述、长文本、同名/通配符、未知分类、未拆明工作、无 gap | 既有模板填值/公式/结构保留、独立问题与长文本文件、Office 正常往返；不增加估算完整性断言 |
| `tests/fixtures/history/` | 合成 XLSX：无 AC/无 Task、API/事件候选、明确实例、不同用途区域 | 稀疏 as-is 可用，类型不等于实例，零匹配可受新来源影响 |
| `tests/fixtures/clarify/` | EX05 反馈、方案及独立预期 diff；真实基线由 I1 构建 | 具体确认、有限影响、历史去向、无关数据保留 |
| `tests/fixtures/telemetry/` | EX06 的增量/累计、跨活动、重复/迟到、时钟重启/损坏事件 | 不重计、不伪造粒度，未知与零不同 |
| `tests/fixtures/prototype/` | I4 创建自包含静态/动态 HTML/JS/CSS、模拟/不可达变体 | 真实观察及限制，非浏览器运行成功即业务成立 |

期待文件可列必要、禁止、允许差异、待确认和来源区域。机械夹具可固定数字结果，数字必须来自版本绑定的模板实算或已验证原测试证据；语义夹具不能把 I1 预制 model 喂给真实 generate 后宣称拆解通过。所有 JSON/附件只使用合成材料。

语义演练沿上述目录增补 `cases/<case-id>/inputs/`、`answers.md` 与 `expectations.json`，具体 case-id 和内容由 P02/P03/P04 的任务定义。inputs 仅含用户可提供的 PRD/HLD/历史/原型/反馈；answers 是评估者在实际提问后才提供的答复脚本，expectations 由评估者保管。复用 `tests/support/fixtures.py` 准备输入副本，不另建通用评测平台或产品 Schema。

真实 Agent 演练使用只含所需输入的临时项目及可加载的 Lite 副本；副本保留 manifests、Skill、references、runtime、scripts、依赖与资产，排除测试期待、候选答案、设计案例和验证报告。被测会话不继承含答案的开发历史，一次 generate 内仍是同一个主 session。机械用的 I1 candidate、旧示例 projection、预期金额不提供给被测 Agent；独立性不足的执行只能记为开发调试，不能记为首次真实生成验收。

`expectations.json` 是测试侧普通数据，固定使用 case_id、required、forbidden、allowed_variations、pending、source_refs 六项。下例由 P02 `three-scope` 的 EX01 输入支持；文件中的来源位置必须在夹具创建时落到真实章节/行，不能只有不可解析的别名：

```json
{
  "case_id": "three-scope",
  "required": ["公共查询客户端建设仅计一次", "迁移内含字段与记录核验"],
  "forbidden": ["另计同一迁移核验成果", "因记录条数缺失反复调查定档"],
  "allowed_variations": ["合理的 Epic/Feature/Story 标题及分片差异"],
  "pending": ["迁移 Task 使用默认 M，复杂度问题保持待确认"],
  "source_refs": ["inputs/hld.md#h-n1", "inputs/hld.md#h-d1"]
}
```

机械测试只检查这些文件可读、来源可定位和真实数据合同；required/forbidden 的自然语言结论由实际输出与依据评估，不转换成关键词通过器。验证记录逐项列输出位置、采用的依据和通过/失败/未验证；一项专业判断的失败定向修指引或输入理解，不通过增加重试轮次补救。案例规模、Task 数与旧金额不是通用验收标准。

I1 同步建立 checkpoint：request_id、entrypoint、目标集合/活动、初次覆盖游标、共享追加/返修计数、候选位置、最近进展或修法、退出原因。业务计数与 telemetry 分开；丢失不能按零重置。纯 agent 活动只记录可得信息，不把这一文件当强制调度器。
