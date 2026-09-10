# Lite 工具合同

Generate 首次编写可按活动读取 [命令与候选编写](generate-authoring.md)，遇到具体字段/诊断再查本页相应定义；无需预加载全部 Schema。

当前提供真实文本/XLSX `ingest/sources`、`ingest/analysis`、定向 `inspect`、`check/candidate` 与只查事实的 `recover`。公共 `render` 使用真实模板和隔离 Office，完成投影、计算和最终复读；`apply` 核验实际准备包后保存版本。Clarify 支持有限 `check/edits`、带 `plan_path` 的检查及具体确认后的应用；专业变化由 Agent 提供。运行时不依赖旧插件，不生成模拟观察或交付。

```text
<Lite 隔离 Python> <Lite 安装目录>/scripts/lite.py --request <UTF-8 请求文件>
```

请求固定字段为 `protocol_version="1.0"`、UUID4 `request_id`、显式 `project_path`、`operation`、`payload`。`check/candidate` 的 payload 为 `candidate_path`、`scope="full"/"slice"`、`plan_path`（Generate 为 null，Clarify 为同请求的具体计划路径）。项目路径相对调用 cwd 解析一次；其余引用使用项目相对 POSIX 路径。候选及其三份业务 JSON 限定在本请求 `.ai-sow-lite/work/<entrypoint>/<request_id>/`，不得通过 `..` 或符号链接逃逸。

## 七份 Schema 与实际文件位置

- [model.schema.json](../contracts/model.schema.json)：D02 的 Epic/Feature/Story/内嵌 AC/Task/Dependency/Lineage。
- [pending-items.schema.json](../contracts/pending-items.schema.json)：`schema_version/items`；target 为 `{object_id, field}`。resolved 精确为 `{decision_id, request_id, summary}`；superseded 为 `{replacement_item_ids, lineage_refs, request_id, reason}`，其中 lineage 引用 `{from_version_id, from_ids}`。
- [decisions.schema.json](../contracts/decisions.schema.json)：`schema_version/items`；决定的 `applies_to` 同 target。
- [evidence.schema.json](../contracts/evidence.schema.json)：`schema_version/items`；analysis 的 `evidence[]` 使用其 `$defs/item`。来源定位为 `text_lines`、`xlsx_range`、`observation`。
- [protocol.schema.json](../contracts/protocol.schema.json)：请求及 `$defs/response`。支持的 payload 和 inspect 选择器采用封闭结构；不接受任意路径、脚本或绕过开关。I1.1 的空占位调用仍明确返回未支持。
- [artifacts.schema.json](../contracts/artifacts.schema.json)：首次消费者的工件结构，按 `$defs` 校验。增加 prepared、request、intent、analysis_index；checkpoint 保存业务续接信息，manifest/current 由公共核验后的存储内核写入。projection 与 verification 由 I1.3 实际消费者核对完整交付。

- [change-plan.schema.json](../contracts/change-plan.schema.json)：具体计划；`$defs/edit_draft` 定义有限编辑稿，`$defs/confirmation` 定义内容与实际执行输入的绑定。

以下路径由真实登记/检查操作消费。既有 I1.1 `contract_case` 与 seed history 保持独立合成单测含义；新增 `build_ingested_case` 使用真实 CLI ingest→inspect→analysis→check，保留真实返回的身份和定位。

| 文件 | Schema 定义及关键字段 |
| --- | --- |
| `.ai-sow-lite/project.json` | artifacts `project`：schema_version、project_id、project_type（new/existing）、template_hash |
| `.ai-sow-lite/template/<sha256>/sow-template.xlsx` | 原 Lite assets 模板的逐字节副本 |
| `.ai-sow-lite/inputs/index.json` | artifacts `input_index`：schema_version、items；input 含 input_version_id/input_id/content_hash/relative_path/format/material_types/uses/use_regions，文本增加 encoding="utf-8" 或识别 BOM 后的 "utf-8-sig" |
| `.ai-sow-lite/inputs/originals/<input-version-id>/<filename>` | 不可变源文件字节；relative_path 指到这里 |
| `.ai-sow-lite/analysis/topics/<topic-version-id>/analysis.json` | artifacts `analysis`：schema_version、evidence[]、topics[]、observations[]（文件引用）；topics 使用 `$defs/topic`，版本 ID 须与目录及候选一致 |
| `.ai-sow-lite/inputs/readings/<read-id>/reading.json` | artifacts `reading`：绑定真实 input_version_id/content_hash，文本适配器 lite-text-v1、options={}；XLSX 适配器 lite-xlsx-v1、固定 options={data_only:false}、selection、目录或区域附件引用 |
| `.ai-sow-lite/analysis/observations/<observation-id>/observation.json` | artifacts `observation`；必须是真实观察记录，不得写模拟成功 |
| `.ai-sow-lite/work/generate/<request-id>/candidate.json` | artifacts `candidate`；引用同请求的 model/pending-items/decisions，列所采用 evidence_ids/input_version_ids/topic_version_ids 和 template_hash |
| `.ai-sow-lite/work/generate/<request-id>/checks/<sha256>.json` | artifacts `check`；真实 CLI 检查报告，字节和依赖绑定 |

`analysis.topics[]` 必需字段：topic_id、topic_version_id、title、input_version_ids、uses、covered_regions、uncovered_regions、evidence_refs、related_object_ids、external_responsibilities、limitations、conclusion、historical_items。`covered_regions` 使用完整 source_ref（input_version_id、locator、excerpt_hash）。无相关对象可用空 related_object_ids；无 gap 的语义结论由 Agent 作出，工具只核对分析存在和引用一致。分析文件可包含共享依据；同 ID 的共享依据须字节语义一致，不能覆盖冲突内容。

每个 `topic_version_id` 对应唯一内容和 topic_id，并须在自身目录的 analysis.json 中出现。同一文件不能重复声明主题版本；不同文件共享该主题时内容必须完全一致。历史条目以 `(topic_version_id, id)` 定位，同版本 ID 不重复，显式 `parent_id` 只在该主题版本内解析且不能成环；`instance_facts[].evidence_refs` 同样核对依据闭合，不补造未知历史层级。

covered/uncovered 区域的 input_version_id 必须同时属于登记索引、候选和所在主题的输入集合。已支持 text_lines 的 start_line 不得大于 end_line，path 遵循下面的单文件规则。uncovered 区域没有成功摘录，不要求 excerpt_hash，不用已读行数或解码结果冒称该区域已经读取；本项检查仅说明声明的身份和基本定位一致。

`text_lines` 的 start_line/end_line 为 1 起始、含端点。单文件 `path` 可省略；提供时必须精确等于该 input_version_id 登记的 `relative_path` 或其 basename（如 `prd.md`）。工具始终读取登记原件，只将 locator.path 用于一致性核对，不跟随任意路径；错误文件名、未登记路径、绝对路径和逃逸路径均拒绝。摘录按已登记编码严格解码，保留原换行后以 UTF-8 编码计算 SHA-256；基线登记的 utf-8+BOM 保留原 BOM，新的 utf-8-sig 登记按其显式编码去除 BOM，字符串不 trim 或 Unicode 归一化。UUID 示例短别名不能作为生产 ID。真实模板身份与标准行必须从 assets 读取，不能复制计算数值或旧业务合同。

## 返回与限制

stdout 仅一个 JSON：`ok/request_id/operation/result/diagnostics`。检查报告本体含 schema_version、validator_version、scope、candidate_ref、candidate_digest、dependencies、valid_for_render、unknowns_count、diagnostics；直接 `check_candidate(project, candidate_path, scope, plan_path)` 返回此本体且不写文件。CLI 保存报告，result 返回 check_ref/candidate_ref/plan_ref/review_ref/candidate_digest/valid_for_render/unknowns_count。slice 无错误也不能作为 render 权威。

诊断为 `code/target/message/preserved_paths`，target 为 `{path, object_id, field}`，未知部分 null。退出码 0 完成，2 不合法/不支持，3 本地 I/O/输入读取/锁/工作簿故障，4 已观察取消且未应用，1 未预期故障。部分输入失败返回 ok=false，同时保留成功引用；技术失败不冒充业务待确认。

I1.1 保留的 CLI/校验错误码：`PROTOCOL_INVALID`、`VERSION_INCOMPATIBLE`、`OPERATION_UNSUPPORTED`、`CANDIDATE_INVALID`、`EVIDENCE_MISSING`、`IO_FAILED`、`INTERNAL_ERROR`。自举错误码：`BOOTSTRAP_DIRECTORY_FAILED`、`UV_INSTALL_DOWNLOAD_FAILED`、`UV_INSTALL_DOWNLOADER_MISSING`、`UV_INSTALL_FAILED`、`UV_INSTALL_INVALID`、`UV_CHECK_FAILED`、`UV_VERSION_INVALID`、`PYTHON_INSTALL_FAILED`、`DEPENDENCY_SYNC_FAILED`、`VENV_MISSING`、`PYTHON_CHECK_FAILED`、`PYTHON_VERSION_INVALID`、`DEPENDENCY_IMPORT_FAILED`。自举失败使用相同信封、request_id/operation=null 和退出码 3。不回显原始异常或业务输入。合法未知、默认 M、有值 open 问题和未拆明工作不会被自动改值或关闭；工具不判断金额或语义充分性。

UUID4 必须恰好 36 字符，SHA-256 恰好 64 字符，json-v1 摘要恰好 72 字符；均拒绝尾随换行，不修剪或改写。业务文件或登记/分析文件无效时保留其真实诊断，继续运行其余有效依赖足以支持的检查；不会把无效文件当作合法空集合制造悬空引用。`valid_for_render=false` 的报告不授予任何交付权威；pending 文件无效时 `unknowns_count` 的占位 0 不代表业务没有待确认项，以文件诊断为准。

实际定位校验支持已登记单文件文本的 `text_lines` 和类型化 XLSX 的 `xlsx_range`；原型包内文本和 `observation` 属于 I4，当前明确拒绝，不冒充附件已验证。历史复合键及恢复沿 current → manifest 的摘要绑定基线链读取；存储验证不等于工作簿交付验证。候选语义摘要覆盖所采用主题分析及依据；报告另绑定实际文件字节和依赖摘要，不把字节格式变化当作业务文字变化。

Lineage 仅检查 current 到显式 from_version_id 所需的已绑定历史区间。对象保持 `(version_id, object_id)` 身份；继承记录须与该区间已保存的同复合键记录完全一致，以其首次出现的后继模型定位替换发生版本。原对象须在替换前持续存在，去向须在该次模型存在；已退出的中间去向只能由时间更晚的有效替换继续到当前对象或明确删除。缺少摘要绑定模型、缺少实际继承记录或只在任意早期历史找到同名 ID 的链不支持据此通过，会返回文件或 lineage 诊断；不推断发生顺序、不恢复缺件、不扫描显式区间以外的无关历史。

Bash/PowerShell 自举迁入来源为 D00 的 `2fc8588`，只适配身份、路径与单请求 CLI。脚本固定 uv 0.11.7、Python 3.12 和锁定依赖；缓存/下载安装放在 Lite 副本 `.ai-sow-tools/`。没有沿用旧 Windows 97 字符支持声明；本轮平台验证范围以任务报告为准。


## I3.1 有限编辑、具体计划与确认

`check` 的 edits payload 固定为 `{"edit_path":"<本请求编辑稿路径>","scope":"full"}`，与 candidate_path/plan_path 互斥。
编辑稿放在本请求 `work/clarify/<request-id>/`，字段为 schema_version/plan_id/revision/base_version_id/
edits/read_selectors/read_boundary/conditions/unresolved_items/change_summary/additional_refs。
revision 首次为1，同请求沿同一 plan_id 最多修订到2；每份方案从原完整基线构造。
可选 repair 绑定上一不可变 draft_ref、同根因 operation 和实际 reason；可选 subset_of 绑定原展示 plan_ref。
机械返修保持专业 revision，同候选一次、请求共享两批、同根因一次；每份专业方案只有一个严格子集槽，
不嵌套提取、不以新计划身份刷新额度。具体保存与确认示例见 [局部修改参考](clarify-changes.md)。

每项 edit 为 `{op,collection,object_id,field,value}`；op 为 add/replace/remove，remove 不带 value。
field=null 只允许完整对象的 add/remove，值须含同一稳定身份；字段增删须符合原字段存在性。
collection 为 epics/features/stories/acs/tasks/dependencies/lineage/pending_items/decisions/
input_refs/topic_refs/evidence_refs。AC 通过明确替换父 Story.acs 编辑；跨 Story 迁移须同时提供两个父数组。
lineage 地址是 `[from_version_id,有序from_ids]` 的规范 JSON 字符串，其他业务地址使用对象 UUID4。
不接受数组下标、隐式级联、重叠写入或既有对象重排；新对象接在同父对象的既有成员之后。

新增引用仅通过 additional_refs 的 input_version_ids/topic_version_ids/evidence_ids 三个列表提供，
输入与分析先经既有 ingest 登记；基线引用完整继承。新引用也列入 changes/write_set。
read_selectors 每项精确为 `{view,selector}`，复用 inputs/regions/topics/current/objects/standards 的选择器，
不含 limit/cursor。运行时解析实际 observed_version，不猜专业依赖；AC 变化同时记录父 Story.acs 容器。
read_boundary 为 `{input_version_ids,topic_version_ids,object_ids,depth}`，depth 为 current/topic/source；
conditions 为关键条件文字列表，unresolved_items 只能引用候选中仍 open 的问题 ID。

`validation.prepare_edit` 委托有限 changes 模块复制原三份业务文件、保留未涉及 JSON 字节和展示顺序，
在 `plans/<plan-id>/r<revision>/` 保存 candidate.json、plan.json、review.md、原编辑稿、input-index.json
及 construction.json；返修或子集使用其固定 repair/subset 子目录。construction 使用 artifacts.edit_construction，绑定构造时完整 current 与实际文件 hash。
check/edits 返回 candidate_ref/plan_ref/review_ref/check_ref、candidate_digest、valid_for_render、unknowns_count，
另有 no_change/current_version；真正无变化仅指回现版，不 render 或创建版本。M 保持 M 但采用新依据/决定或
处理问题仍是实际变化。`diff_bundle` 比较实际前后值；`verify_plan` 返回完整检查报告，不写文件。

计划固定含 schema_version/plan_id/revision/base_version_id/changes/read_set/write_set/read_boundary/
conditions/unresolved_items/change_summary/confirmation。changes 为实际 `{op,collection,object_id,field,before,after}`，
read_set 为 `{selector,observed_version}`，write_set 为稳定地址。hash 使用现有 json-v1，覆盖 plan_id/revision/
base_version_id/changes/read_set/write_set/read_boundary/conditions/unresolved_items/change_summary，
子集另绑定 subset_of；排除 confirmation 自身、机械 repair 元数据和导出路径。候选原字节及完整 current 的 version_id、manifest_hash 均须保持一致。

confirmation=null 可检查和预览。Agent 识别实际执行意思后，把最少真实答复作为 answer 输入登记，
按真实 inspect 摘录形成 confirmation：`digest`、`input_ref`（source_ref）、`shown_plan_ref`（file_ref）、
`selected_changes`（该具体候选的完整 changes）。另存确认版计划，复用原 candidate；不改已展示计划。
检查报告附 plan_ref/plan_digest/input_index_snapshot_ref。第一次有效 CLI 检查或 apply 以同请求
`confirmations/<内容摘要>.json`（file_ref）封存确认版原字节；随后改路径或字节均拒绝。
这不增加用户确认轮次，也不认证人类身份；任意 confirmed 布尔值不能代替来源与内容绑定。

确认登记可向原输入索引追加新项，必须保留快照的全部既有项、字节语义和顺序，重新校验 Schema/唯一 ID；
所选读取结果及采用的不可变原件、reading、analysis、registration、模板、历史依赖仍逐项复查。
仅 inputs/index.json 在这个已验证追加条件下可改变记录 hash，不忽略其他依赖变化。
显式读取整个 inputs 集合时新增成员仍使读取失效；定向读取必须保持选中登记项不变。
严格子集继承原展示计划的 read_set 与原 input-index 快照；选择器、边界和条件必须相同，
不能在选择答复追加后重算 observed_version。原完整候选仍复查。确认永久依赖仅保留不可变来源、
分析、模板和历史；work、current、实时 inputs/index 只作当前校验，原展示字节随版本归档。

确认后新 check 引用不强制重算：候选精确字节、计划内容摘要、模板和完整基线一致，且原 prepared
通过实际文件复核时，render 复用原准备包。apply 再读候选和采用来源，沿既有短锁原子生效。
版本目录保留 plan.json、shown-plan.json、candidate.json、prepared.json 的原字节，以及
artifacts.clarify_confirmation 的 confirmation.json；后者用版本内可达引用绑定展示/执行计划、
实际 input_record/source_ref/digest/selected_changes。原来源进入 manifest 依赖，确认输入不自动成为业务采用依据。
同请求同意图重复 apply 返回原结果；current 变化不能自动换基线或复用跨版本确认。

## I1.2 登记与查询

新增诊断包括 INPUT_UNAVAILABLE、FORMAT_UNSUPPORTED、INPUT_ID_CONFLICT、PROJECT_ID_CONFLICT、IDENTITY_CONFLICT、REQUEST_ID_CONFLICT、PATH_UNSAFE、CHECKPOINT_UNKNOWN、LOOP_LIMIT_REACHED、BASE_STALE、WRITE_BUSY、REQUEST_CANCELLED、WORKBOOK_INVALID、RESULT_TOO_LARGE。游标失效沿用 VERSION_INCOMPATIBLE。

`ingest/sources` payload：`kind="sources"`、`entrypoint="generate"/"clarify"`、`project_type="new"/"existing"`、`sources[]`。每项必须含 source_path、input_id（首登 null）、material_types、uses、use_regions（无区域为空）。首次初始化固定项目身份和内置模板逐字节副本；后续项目类型/模板冲突拒绝；已有原件而索引丢失时保留文件并诊断，不重建空索引。ingest 不创建 current。

读取 `.md`、`.markdown`、`.txt` 的严格 UTF-8、`.xlsx` 和显式原型目录包；原型清单身份、资源边界与观察采用见 [原型输入](prototype-inputs.md)。UTF-8 BOM 只按识别出的 utf-8-sig 解码，CRLF/LF/CR 保留，拒绝伪装成文本的常见二进制格式。外部 source_path 是唯一允许的项目外读取位置；普通文件的目录别名可解析，源文件链接拒绝，原型包根与成员也拒绝链接。所有持久项目路径拒绝链接/reparse 重定向。每项先复制并复读 hash，再登记；解码失败也保留已登记原件，不影响同批其他输入。相同原字节复用 input_version_id 和 reading；显式已有 input_id 的新内容获得新版本，旧原件不覆盖；未知 input_id 拒绝。新增材料角色/用途合并到登记索引，原件字节不改。

相同原字节以不同文件名再次导入时，先按本次 source_path 的 basename 核对输入 locator；复用身份后，将本次用途区域中显式提供的 locator.path 绑定到实际保存原件的 basename 再合并。返回区域可原样用于 inspect/regions；原件身份、字节和 reading 保持不变，未保存的别名仍不能用于读取。

返回 project_id、input_refs（登记项）、reading_refs（文件引用）、failures（诊断）和 checkpoint_ref。文本原件下的 reading-ref.json 指向不可变读取记录；XLSX 使用 originals/<input-version-id>/readings/<读取身份哈希>.json。后续复用复核原件、记录和摘录附件。读取成功只证明物理读取可用。完整字段、边界与历史理解方法见 [输入分析](input-analysis.md)。

`ingest/analysis` payload：`kind="analysis"`、entrypoint、analysis_path。文件必须在本请求 work 内。共用候选的来源、摘要、依据图与主题校验后，保存实际输入分析字节至 `analysis/registrations/<sha256>/analysis.json`，按 topic_version_id 拆存分析并登记 `analysis/index.json`。各主题保存 registration-ref.json 以回查原始登记候选。返回 analysis_ref、evidence_ids、topic_version_ids；同依据/主题版本冲突拒绝；新依据须由新的主题版本实际承载，不能通过重复旧主题返回未保存的依据身份。observations 可引用本请求 work 中的真实观察或已登记观察，核对后保留不可变记录和附件；每个主题仅保留其输入相关观察。不支持的 locator 明确拒绝。登记不代表当前 SOW 已采用。

复用已有主题前核对索引成员及摘要、主题实际字节和 registration-ref 绑定的原始候选。若现存有效索引仅缺本主题一项，且主题与来源已完整保存、来源绑定与本次候选原字节完全相同，重试只补缺失索引项，不重写主题或来源。主题/来源损坏、ref 缺失或冲突、候选字节不同均不据此返回成功；整个索引丢失时不重建，不提供通用恢复层。

`inspect` payload 为 view、selector；limit 默认20、最大100，cursor 默认 null。只读，不修改索引、current 或业务文件。选择器如下；表外组合和字段拒绝：

| view | selector | 返回范围 |
| --- | --- | --- |
| current | `{}` | 当前指针和 manifest 引用；核对指针结构、manifest 摘要/结构/版本身份；没有 current 为显式空集合，所读绑定损坏则诊断 |
| inputs | `{}`，或 input_version_ids，或 input_ids | 所选登记目录页 |
| regions | input_version_id；可选 locator | 省略 locator 读目录；text_lines 返回实际行，原型源码须指定包内path；xlsx_range 返回类型化单元格和实际区域read_id；observation 返回采用记录与附件引用。定位与摘要使用coverage中的实际值 |
| topics | `{}`，或 topic_version_ids，或 topic_ids，或 uses，或 historical_label 加可选 uses | 所选不可变主题；historical_label 返回历史条目并保留零命中范围摘要；分析索引/工件损坏不会当作空集合 |
| objects | collection，加 object_ids/title 二选一；可选 version_id | 定向对象或标题子串命中；collection 为 epics/features/stories/acs/tasks/dependencies/pending_items/decisions，pending_items 的 title 检索 question，AC 附所属 story_id |
| objects | collection="pending_items"、status；可选 version_id | open/resolved/superseded 问题 |
| objects | collection="dependencies"、relation={object_id,direction}；可选 version_id | from_story_id/to_story_id 的 outgoing/incoming/both 关系；空结果保留查询条件与所读版本 |
| standards | `{}`，或 work_type_ids，或 work_type_names | 空选择器仅返回类型目录；指定类型返回定性规则、包含边界和 S/M/L/X 规模门槛。逐次从项目固定模板读取，不返回 PD/倍率/公式 |
| request | request_id | 本请求恢复事实，损坏返回诊断 |
| telemetry | request_id | 真实遥测指标分页与 report_ref；未接入的宿主 usage 为 null/unknown，游标绑定来源事件摘要 |

current 查询只读取项目身份、current 和其摘要绑定的 manifest，不读取工作簿、原件或业务文件。objects 默认读取一次 current 后固定该版；显式 version_id 仅沿摘要绑定的 base_version_id manifest 链选择历史版本，不读取孤立目录。选定版本后，仅复核所选 collection 所在业务 JSON 的实际字节摘要与 Schema，再筛选对象；不匹配也必须先完成该文件复核。问题/决定分别读取 pending-items.json/decisions.json，其他 collection 读取 model.json；单个选中文件仍完整读取，不新增数据库或缓存。

current 的 coverage.verification_scope 为 manifest，verified_file_ref 为 null；objects 成功读取业务文件时为 selected_file，并在 verified_file_ref 返回所核对文件引用，无 current 时为 manifest/null。这些范围不证明整包、原件或 Office 交付完整性；未选文件损坏可能不影响窄查询。apply/recover 保留完整版本文件及依赖校验，不能用 inspect 成功替代。

`objects` 不接受空 selector。结果含 selected_version、items、matched_count、returned_count、remaining_count、next_cursor、coverage、report_ref（不适用 null）。正文物理上限64 KiB；文本长行分为有 character_offset 的有限片段，逐页拼接保持原字节，coverage 保留完整所选行范围的 excerpt_hash。区域的数量按正文片段计，另给 line_count。coverage.complete 仅指查询分页完成。超大的单个非文本对象明确返回 RESULT_TOO_LARGE，不静默截断或假称覆盖完成。

cursor 绑定查询、实际来源/索引/所读版本和续读位置。绑定变化或游标不合法统一返回 VERSION_INCOMPATIBLE；调用方必须用 cursor=null 明确选择新集合。没有历史输入集合快照，不因零命中扩大查询。

## 检查点、应用与恢复边界

请求 work 内 `request.json` 记录请求/入口，`checkpoint.json` 保存 P00 活动、目标、游标、追加调查/返修计数、候选、最近进展/修法和退出原因。已知计数不得倒退；未知用 null 保留，不能自动归零。可选 recovery_queries 为0/1/null，operation_retries 的每个已知操作/根因计数至多1。`save_checkpoint` 只持久化有界计数和续接事实，不决定专业活动，不拦截宿主内的纯模型活动。

检查点缺失/损坏/计数未知时，ensure_request 先以不可变 unknown-recovery.json 记录一次恢复查询尝试，查询后仍未知就 CHECKPOINT_UNKNOWN 退出；再次调用不忙等或重置。真正新增材料可定向登记，不刷新旧探索/返修额度。工具内部不自动重试、backoff、重算或重新生成；共享语义批次仍由调用方按 D04B 记录。源登记、业务恢复与未来 telemetry 分开保存。

公共 apply payload 固定 entrypoint、prepared_path、expected_current、plan_path。当前拒绝条件：

- Clarify 缺具体确认计划，或 Generate 带 plan_path：SCOPE_EXCEEDED。Clarify 依上节重新核验方案内容、实际执行输入和候选字节，保留具体越界诊断。
- 准备/候选/检查/文件结构或实际摘要不一致：协议、候选或依据诊断；已有非预期 current：BASE_STALE。
- 其余准备包：`workbook.verify_prepared` 复核实际投影、Office 记录、原始产物和最终工作簿；不符返回 WORKBOOK_INVALID，target.field=verification_ref。自填 `valid=true` 无效；没有 skip/force/failpoint 等生产绕过参数。

I1.3 已接入函数为 `workbook.verify_prepared(project: Path, prepared: JsonObject) -> JsonObject`，成功必须返回 `{"diagnostics": []}`，失败返回同结构的标准诊断列表。它是实际 Python 核验实现，须独立复核最终工作簿、投影、真实 Office 核验记录及候选/模板/version_id/最终字节绑定；不能只读取成功标志；当前核验还须验证原四表原列全文、目标行 open 备注、范围行和校验优先级，外部 Markdown 完整不能替代。此调用在锁外执行，只核验、不重算、不激活。prepared 的固定字段为 schema_version、version_id、candidate_ref、check_ref、expected_current、files、template_hash、projection_version、office_identity、verification_ref；引用指向本请求 work。files 至少包含 model.json、pending-items.json、decisions.json、projection.json、sow.xlsx、summary.md、pending-items.md，新输出不含 details.md；verification_ref 独立指向核验记录。

公共入口在重新执行完整候选检查并通过实际 I1.3 核验后，冻结业务 JSON 和输入记录快照，将可达输入/分析/读取附件列入 manifest；不把可变 inputs/index 或 work 当稳定依赖，再交给 `_commit_version` 存储内核。`application.json` 绑定原应用调用，`intent.json` 在应用候选进入保存时封存意图，讨论/分析登记不会提前封存。

存储内核在锁外构造并刷新完整目录，要求与 versions 同一文件系统；Unix 用 flock，Windows 用 msvcrt 对固定字节非阻塞加锁。锁忙立即 WRITE_BUSY。锁内复核意图、取消、current 和摘要，保存不可变版本，最后以 fsync 临时指针 + os.replace 切换 current。已生效后的日志/响应失败不撤销事实；锁中不运行 Office、模型或等待用户。Windows 无标准库目录 fsync 分支会如实返回不支持该刷新，不以此声称断电持久性。真实平台覆盖以验证报告为准；没有网络/同步盘承诺。

`recover` payload 只有 target_request_id；沿 current 和摘要绑定的 base_version_id 历史链核实，返回 applied/draft/cancelled/incompatible、applied_version、preserved_paths、diagnostics_ref。损坏诊断进入公共信封，diagnostics_ref 无独立文件时为 null；查询不会写源数据或激活孤立版本。已成功请求返回原 applied_version 与当前 current_version，后续串行版本不会被旧请求倒回。取消只能通过已观察到的本地 `cancel_request` 记录执行边界，不承诺收到任意宿主 UI 的取消事件。

`storage_package` 及 `_commit_version` 单测只验证文件事务；其 sow.xlsx 特意不是 Office 工作簿，不能经公共 apply 绕过核验。真实交付回归使用 `office` marker，存储单测不作为 Excel 交付证据。独立复制及真实包中断覆盖见 [I1.5 交付验收](../docs/validation/I1-delivery.md)。

## I1.3 模板投影与真实 Office

`render` payload 必须为 candidate_path、check_path、expected_current。首版 Generate 的期望指针为 null。工具重新执行 full check，并与指定检查文件完整比较；slice、候选/来源字节变化、自填通过标志均不能作为导出依据。候选和检查文件必须属于本请求 work，原业务 JSON 逐字节复制。

版本 ID 在 render 分配。返回 prepared_ref、version_id、workbook_ref、projection_ref、summary_ref、pending_items_ref、details_ref（新输出为 null）、office_identity、verification_ref、pending_count（仅 open）。引用均为项目相对 `{path, sha256}`，不返回金额结论。

`render-<version_id>/` 保留 projected.xlsx（Office 前输入）、sow.office-raw.xlsx（Office 原始输出）、最终 sow.xlsx 和同版 JSON/Markdown。失败保留工作目录及可得 raw，failure.json 记录诊断，不产生成功 prepared，不切换 current。正式文件集合仍是 model/pending-items/decisions/projection JSON、sow.xlsx、summary.md、pending-items.md，新输出不生成 details.md；apply 另保存 verification 和输入索引快照。raw/投影输入只用于 work 核验，不成为不可变版本的 work 依赖。

新模板 SHA 为 `7b96f9d2d6f6f6175c4d99d875ee3cf0743df3d6884d64258271993432299919`。唯一兼容旧 SHA 为 `6abc55d44bc66476a60c2251e18c0dfdb66709e07539c246dfdec3a0373f5332`：在内存从新版资产仅复制校验列 prototype/A2 说明，再按原项目模板投影；不改旧项目模板字节和 hash，prepared/projection 仍绑定实际项目 hash。其余模板拒绝，不自动重建项目。Story A:E、Task A:G 是输入；Story D 是 AC，F:I 和 Task H:K 保留原公式；Story J / Task L 校验使用新版模板原型，空行空、待确认优先、否则原校验，不改人天/金额/SIT/UAT 规则。标准 Q/R 分别为 SIT/UAT。容量内保留 Story 5—64、Task 5—204；超容量仅按模板原型追加，保留样式、保护、数组公式 ref、Table/filter 与计算列元数据。当前固定模板使用结构化跨表引用、整列 DV/条件格式和数据表空 print_area，扩行无需改写这些范围或公式。未知模板字节/原型返回 VERSION_INCOMPATIBLE。

业务字符串由 write_literal 强制写为字符串，不加单引号。Story/Task 名分别按 NFC、casefold 和 trim 比较键检查碰撞；安全原名保留。通配符、criteria 运算符、数值/布尔/错误码形名称、换行和超过120个 UTF-16 单元的名称使用稳定 ID 别名；原文完整保留在对应备注，模型名称不改。

当前 v6 输出只含原四表。完整 AC 在 Story D，正常 Story E / Task G 备注为空；仅投影必要责任例外、安全别名原名及 open 问题。open 的真实 question + current_handling 以“待确认：”开始写在目标行；AC 指明哪条，父项问题落实际受影响的 Story，Task 问题只落 Task 行。无 Story 的未拆明 Epic/Feature 在 01 表末尾追加范围行，仅实际父项和问题，Story/AC/人天空。resolved/superseded 不在 Excel，只留项目 JSON/MD 历史；依赖、分类依据、Task 清单、证据 ID 和外部路径不自动写备注。

长文保存在原列，行高最多 409 点；最终单格文本超过 32767 UTF-16 单元时返回对象/字段定向 diagnostic 并沿既有有界修复，不摘要、不截断或另起说明表。任务列表 H 保留原公式、数组属性和 Office 原样结果，全部任务在 TaskTable，不复制到备注。

projection.json 使用 **projector_version**；prepared/manifest 使用既有 **projection_version**，均为 lite-projection-v1，不接受双别名。projection 仍含 schema_version、version_id、template_hash、model_hash、pending_items_hash、decisions_hash、workbook_hash、objects、pending_items、details。objects 为 object_id/kind/sheet/table/rows/display_name/fields；单行使用 rows 数组，未拆明父项含实际范围行。fields 为 `{field,cells}`，cell 为 `{sheet,cell}`；AC 增加1起始 entry，保留自身 ID。问题 targets 为 object_id/field/cells，历史问题 cells 为空。pending path/anchor 继续指向项目 pending-items.md；新输出 details=[]、details_ref=null，不生成 details.md。历史 v1 字段合同和旧 applied 文件不变。

Excel 可单独查看与分享，clarify 仍需完整项目 JSON、依据及版本目录。 [I6.1](../docs/validation/I6-self-contained.md) 保留 v5 实测状态，不证明本次提示效果；当前活动设计见 [D06](../docs/design/detailed/D06-excel-projection-and-delivery.md)。

### 引擎与最终封存

`office.recalculate(source, destination)` 从 AI_SOW_LITE_OFFICE_BIN 或 PATH 的 soffice/libreoffice 发现引擎；探测10秒、单次重算120秒。每次使用独立输入、输出、配置目录与所属进程组；超时清理所属进程树和临时目录，不接管桌面 Excel，不安装宿主工具，无内部二次重算。Office 不存在为 OFFICE_ENGINE_UNAVAILABLE，超时/非零退出/退出0却无文件为 CALCULATION_FAILED，实际文件/缓存/保护损坏为 WORKBOOK_INVALID。

按 Controller Ruling3（先前复用已验证旧机械能力的用户授权下的实现裁定，并非新收到的用户决定），raw 先经公式视图、data_only、OOXML 与元数据核验，再只允许两项变换：已有 Table 身份、列和 ref 完全一致时补缺失的 calculatedColumnFormula 子节点；DV 规则未变且 sqref 精确符合已观察到的占用末行+1000裁切时恢复原范围。不整段替换 Table/保护，不改任何单元格、公式、缓存或保护。变换前后公式/cache 清单哈希一致，最终路径再次只读核验。Office 保存后不调用 openpyxl.save。

只读比较承认的等价表示包括引号外 TRUE→TRUE()；缺省保护属性的解码值；空白单元格的有效行/列样式继承；Table part ID/样式 ID 重编号；未指定打印项显式化；list/custom 规则不适用的默认 operator 与 formula2；单条条件规则的优先级编号及同色 differential fill 表示；行高向下量化到0.75pt。这些不触发写入修复。其余范围、规则、已指定打印设置、有效样式/锁定、原公式及数组 ref 均核对。行 hidden/collapsed/outlineLevel、声明字体和实际主题字体（含 CJK）、charset/family 默认值、上标/下标及其他字体显示属性也纳入复读。

唯一字体例外是 Controller 为已观察保存回退限定的三个固定说明格：01-需求故事/02-任务清单/03-工作量汇总 的 A2，模板 Calibri/minor → raw Arial Unicode MS/无 scheme。文本、其余字体属性及原 minor 主题字体必须不变；这是观察到的 fallback，不是相同主题或有效字体。业务格、其他位置或字体对、主题/文本/样式变动和隐藏行仍拒绝。此例外只影响只读比较，不恢复字体或修改 OOXML；增加本机已有 Office 字体目录的隔离探针仍未保留原 A2 字体身份，因此没有增加字体发现或安装子系统。

verification 绑定版本、候选摘要和 Office 记录：真实路径脱敏的引擎名/版本、可执行文件 hash、平台、固定参数、退出码、实际单调时钟毫秒、Office 输入/raw/最终字节 hash，以及实际公式/缓存清单与兼容变换记录。office_identity 是引擎记录的稳定 sha256 字符串。它是本地执行记录，不是签名执行证明；不能抵御有权重写整个项目与全部收据的攻击者。程序仍从模板/候选重新构造预期映射并读取实际文件，不信任自填 valid 标志，不用 Python 验算金额。

修改版投影从同次完整检查绑定的基线model/projection继承未改对象显示名；新同名对象不能夺用旧别名。summary.md使用绑定计划，说明本次具体变化；严格子集只列实际选中的变化，不沿用包含暂缓内容的整案摘要。旧成功准备包只有完整复核并匹配原成功记录时才保留历史正文。

### 复用、变动与测试入口

render-attempt.json 记录具体输入、检查、期望指针、投影器和引擎选择摘要。Generate沿用请求目录的记录；Clarify将记录放在既有不可变候选槽内，首次预览r1/r2/严格子集不算故障重试，返回旧槽复用已成功包。槽位仍由原有限构造约束控制；失败后有条件变化的重试继续消耗全请求共享额度。实现修订 `implementation_version=lite-render-v6` 另计入 attempt 签名，交付数据合同继续为 `lite-projection-v1`。修复前未含实现修订或为 lite-render-v2/v3/v4/v5 的失败 attempt 可以在原请求中按新实现重试一次，保留旧目录并消耗原 D04B 返修额度；不删除 attempt 或归零计数。旧失败收据没有候选身份时保守继承其失败历史，改变引擎签名不能证明是独立新槽；原预算耗尽即退出。旧 applied 版本保留原成功事实及内容，不就地升级。修复前成功 prepared/预览的旧签名只有在相同检查/指针/引擎且通过当前完整复核时才可复用；旧成功收据、相同 Schema 或历史验证器不能绕过 v6 的四表原列全文、目标行备注、范围行和校验优先级核验。完全相同的有效 prepared 只复读复用；损坏不重算。失败后相同输入/环境/实现不重试；有具体变化才允许一次 render 重试，同时消耗 D04B 请求 repair_batches。检查点未知、次数到限、取消或 current 变化分别退出，不自动重建基线。apply 核验后再核对原候选/来源字节，继承 I1.2 的原子生效与幂等恢复。

项目 pending-items.md 的来源标签按真实 locator 显示：文本保留文件名和起止行，XLSX 使用文件名、Sheet 和 range；judgment 沿 basis_refs 回溯相同来源标签，不猜文本行号。此显示修复不改候选、模板、标准或公式。

测试命令：

```text
uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_workbook.py plugins/ai-sow-lite/tests/test_office.py plugins/ai-sow-lite/tests/test_template_uat.py -q
```

office marker 表示真实引擎；没有引擎时允许解释 skip，但 I1 退出仍需至少一个环境没有真实引擎跳过。受控子进程测试仅用于超时、输出丢失与重试边界，存储夹具仍不冒充 Office。

测试专用 native-QA builder 在 tests/support/excel.py。对新的临时/ignored 项目目录运行：

```text
uv run --project plugins/ai-sow-lite --locked python plugins/ai-sow-lite/tests/support/excel.py --project <新的QA项目目录> --variant representative
uv run --project plugins/ai-sow-lite --locked python plugins/ai-sow-lite/tests/support/excel.py --project <另一个新的QA项目目录> --variant expanded
uv run --project plugins/ai-sow-lite --locked python plugins/ai-sow-lite/tests/support/excel.py --project <新的中等列表QA目录> --variant medium-list
```

builder 真实 ingest/inspect/analysis/check/render，并输出准备包引用。representative 含三个范围、默认 M 与待确认；expanded 含61 Story/201 Task、特殊名称和长正文；medium-list 含1 Story/3 Task、短 AC/空备注和中等任务名，另登记其较小范围的测试分析，不改既有登记记录。原生 Excel 保存/重开应使用整包副本，保持已绑定原文件不变。该入口是测试资产，不是 I1.5 独立安装验收，也不运行 Controller 的独立 CLI smoke。

## I1.4 观测接口

CLI 的五个顶层字段与退出码保持原合同。合法业务信封的实际执行在 `result.observation`
附带 `{recording, gaps, report_path}`：recording 为 recorded/degraded，gaps 为去重后的稳定缺口码，
report_path 为 `.ai-sow-lite/telemetry/<request_id>/report.json` 或 null。它只描述观测；
不进入业务 diagnostics，不改变 ok、取消/I/O 退出码或触发业务重试。即使观测目录完全不可写，
该字段仍一次返回 TELEMETRY_RECORDING_FAILED。非法可选 observation_context 单独降级为
OBSERVATION_CONTEXT_INVALID；非法业务信封仍按 PROTOCOL_INVALID 拒绝。

内部函数固定为 `append_event(project, event) -> None`、`build_report(project, request_id) -> dict`。
Schema 位于 artifacts 的 telemetry_event/telemetry_report 定义。每个实际写者使用独立 producer_id，
写入 `telemetry/<request_id>/events/<execution_id>/<producer_id>.jsonl`；重放保留原事件身份。
事件信封为 schema_version/event_id/event_type/request_id/execution_id/producer_id/sequence/
observed_at/activity_ids/slice_ids/data。lifecycle 的 data 保存 name/phase/span_id/parent_span_id/
clock_domain/monotonic_ns/status/operation_id/attempt_id/host_call_id，工具另填 operation 和 timing。
同一逻辑查询再次实际执行仍产生新的 operation/attempt 与成本；无宿主调用身份时 host_call_id=null。

纯语义活动通过同一隔离 Python 的模块入口标记。由于运行时未安装为 Python package，须在**本次子进程**
设置 `PYTHONPATH=<Lite 安装目录>/runtime`，再执行以下命令；不修改持久宿主环境、依赖或 bootstrap：

```text
<Lite 隔离 Python> -m ai_sow_lite.telemetry --project <显式项目目录> --mark-file <标记 JSON>
```

mark 只接受 schema_version/request_id/execution_id/activity_ids/slice_ids/phase/name。
name=request 且 phase=start/end 表示请求观察边界；end 做一次有界报告重建。其他可用 name 为
activity/input_analysis/outline/generation/merge/design_discussion/export/user_wait/useful_feedback/usable_file。
phase 可为 start/end/milestone；不接受 token、客户正文、路径或业务 payload。
短命进程的标记没有 monotonic_ns/clock_domain；request_wall_ns 的 basis.kind 为
utc_observed_interval，绝不作为模型时间。该观测专用命令 stdout 为同样的 recording/gaps/report_path 小对象，
观测降级仍退出0，不触发业务重试。

报告 metrics 为列表，每项固定 name/value/unit/scope/basis/coverage/attribution/diagnostics；
时间为整数 ns，字节为 bytes，token 为非负整数或 null。初始工具指标为 tool_duration_ns、
model_duration_ns、request_wall_ns、user_wait_ns、input_bytes/output_bytes；无 usage 的 total_tokens 为
null、coverage=unknown。字节统计为规范化业务信封及附加 observation 前响应的 UTF-8 字节数，
不包含原始材料内容大小，也不换算 token。旧规范化来源不提升宿主能力；有下述已适配原生来源时
request_usage 可显示 partial，其他能力仍为 unverified。合成事件不能证明当前宿主完整可采。

### 规范化 usage、边界及查询

原有规范化分支计算 `adapter_version="normalized-v1"`、`source_schema_version="1.0"` 的事件。
`producer_version` 必须非 null、等于来源明确声明的 `verified_producer_version`，同一 source_id 的声明
必须一致；未知版本/语义或声明变化保留事件并产生 SOURCE_UNVERIFIED/SOURCE_VERSION_CHANGED，
不推断总量。source_kind 为 synthetic/normalized_host，来源 capability 声明只绑定该来源，
不能提升 report.host_capabilities。EX06 夹具使用 synthetic-ex06-v1，明显标为合成。
`observed_at` 固定为 UTC **YYYY-MM-DDTHH:MM:SS.ffffffZ**，恰好6位小数；例如
`2026-09-09T00:00:00.000000Z`。该时间是接收时刻，不是 usage 覆盖边界。

usage 的 data 使用 `source/scope_kind/scope_id/counter_epoch/native_event_id/source_sequence/revision/
observation_kind/host_call_id/counts/coverage`。source 另含 source_id、上述版本、semantics、role 和五项
capabilities。source_sequence 是明确来源流的原生顺序/游标，须在该 source_id 下跨 epoch 持续可比较；
重启后无法维持此语义时使用新的明确来源身份，不能把进程重启当零基线。
observation_kind 为 cumulative/call_absolute/delta；revision 为非负整数或 null，物理调用修订必须可排序。
原生身份缺失为 null 并留缺口，不生成 host_call_id；call_absolute 要求 call_identity=verified、
scope_kind=call 且 scope_id 等于真实 host_call_id。相同 source/native_event/revision 去重，最新调用修订
取代旧值，真实重试用新调用身份计费。同来源混用累计/调用或重叠 native scope 不求和；多个 primary 来源
同样不求和。role=cross_check 的来源仅保留核对证据，不加入 primary 总量，当前不自动解释二者差额。

coverage 固定 `{start,end,boundary,complete,exclusive}`：start/end 是真实原生边界身份，boundary 为
request_start/request_end/interval/unknown；exclusive 表示该区间确实只属于本请求，complete 表示该区间
结束覆盖完整。累计差值只在同 scope/epoch 按源顺序计算；缺请求前起点时 total_tokens 为 null，仍可在
known_tokens 列出已覆盖区间。缺尾段返回 partial；下降不裁零、不猜 reset，后续同 epoch 区间也保留未知。
边界不相接/混合请求的差值留在 host 范围；跨活动只给一个 activity_group，绝不逐活动重复或按时长分摊。
显式 delta 首版只接受源顺序下首尾相接、无重复边界的链；不能据接收 UTC 宣称区间互斥。

counts 只接受 total/input/output/cached_input/cache_write_input/reasoning_output 的 `*_tokens` 字段，
每项为非负整数或 null。semantics=native_total 只使用原生 total；total_is_input_plus_output 才允许
在 total 缺失且 input/output 都存在时求和并标记 derived。该语义同时声明 cached_input 属于 input、
reasoning_output 属于 output；cache_write 保留原义，所有细分均不再加到 total。
未测实的语义使用 unverified；不从字符、文件大小、上下文窗口或账户限额转换 token。

事件先 flush/fsync，再原子推进 `cursors/<source_id>.json`；游标写入失败可重放既有事件后重试游标，
不重跑业务。尾部无换行的断行标 EVENT_TAIL_INCOMPLETE，中间损坏标 EVENT_MIDDLE_CORRUPT；
保留可读事件，拒绝继续向损坏的同一写者文件追加。内部 gap 事件只接受 Schema 枚举的稳定缺口码。

每次报告最多读取256个事件文件、10000行、8 MiB，目录枚举最多768个条目；单事件最多64 KiB。
报告最多2000项指标。到限明确 READ_LIMIT/REPORT_LIMIT 和部分覆盖，不轮询补齐、不设 token 预算。
报告有 as_of/source_digest/event_count/sources/limits；context.json 是可重建的身份/来源能力视图。
文件分别原子替换，整体不是多文件事务；写入失败通过 result.observation 通知，旧报告可能仍存在。

`inspect` 使用 `view="telemetry", selector={"request_id":"<UUID4>"}`，只返回该请求的指标分页和
`report_ref={path,sha256}`；limit 默认20、最大100，单页指标正文64 KiB。游标绑定来源事件摘要，迟到事件后
返回 VERSION_INCOMPATIBLE，需显式 cursor=null 重读。该查询与纯标记不递归记录工具事件，避免报告自改
导致游标立即失效。无 telemetry 的合法项目查询也可生成全未知报告；不读取 current 或业务候选。

tool_duration_ns 是完整工具调用耗时之和；tool_union_ns/processing_ns 只在同域可对齐且端点完整时按
区间并集计算。user_wait_ns 单列等待并集，UTC 标记使用 utc_observed_union；不完整/不可对齐则 null。
exclusive_duration_ns 是完整父区间减完整子区间并集，仍不能称精确模型耗时；model_duration_ns 保持未知。
无结束的 span 有 duration_ns=null、LIFECYCLE_INCOMPLETE。KeyboardInterrupt 仅记录 interrupted 并原样传播，
不判断业务是否已生效、不创建 cancelled.json；指针生效后的事实仍由已有 recover 核验。业务明确返回
REQUEST_CANCELLED 才记录 cancelled。迟到 usage、request end 和显式查询仅写 telemetry 文件，
不会改 model/Excel/manifest/summary/current/checkpoint。

### 原生响应的有界采集

内部`host_usage.collect_native_usage(project, request_id, *, source_path, binding, limits=None)`只读取
一个显式提供、已授权的常规文件。CLI复用观测模块，进程内的PYTHONPATH仍指向本插件runtime：

```text
<Lite 隔离 Python> -m ai_sow_lite.telemetry --project <项目目录> --collect-file <关联JSON> --native-source <已知原生文件>
```

`--collect-file`与`--mark-file`互斥。关联JSON仅含以下字段，UUID与宿主标识均替换为实际已知值：

```json
{
  "schema_version": "1.0", "request_id": "<UUID4>", "execution_id": "<UUID4>",
  "source_id": "<UUID4>", "host_thread_id": "<实际thread-id>",
  "host_turn_ids": ["<实际turn-id>"]
}
```

source_id/关联在同一次来源续读中保持固定；改变thread/turn选择或execution绑定会使native cursor失效。
首版不自动扩展选中turn，也不通过换source_id重复计量已有范围。缺少可靠关联就保留未知，不扫描宿主目录。
原生路径仅由本次参数传入，不写入事件、游标、报告或诊断。普通`inspect(view=telemetry)`只重建已有事件，
不会自动读取宿主文件。请求收尾做一次有界采集；生产者结束后仅后续显式采集补迟到数据，不忙等或后台监听。

当前唯一native分支为source_kind=`codex_session_jsonl`、producer_name=`codex-desktop`、
producer_version=`0.153.4`、adapter_version=`codex-jsonl-v1`；原生未提供schema/epoch，分别保持null。
未知producer/version/字段形状产生SOURCE_UNVERIFIED/SOURCE_VERSION_CHANGED等稳定缺口并停止此适配，
保留Python工具计时和已应用文件。未知producer名称仅保存`unknown`分类，不回显任意原始metadata。

规范化usage新增`scope_kind=response`及`observation_kind=response_absolute`。source另保存已绑定的
host_thread_id/host_turn_ids；data.native白名单为thread_id/turn_id/session_id/root_turn_id/response_id、
turn_counts/thread_counts及byte_start/byte_end/line_sha256。六项响应counts为primary，turn/thread累计仅
核对分解的连续性，不再计入总量。原生ordinal用作source_sequence，原生未给event_id/revision时保留null。
重复同响应同值去重；同响应冲突为NATIVE_RESPONSE_CONFLICT，累计核对失败为NATIVE_COUNTER_MISMATCH，
失败区间不能进入请求known_tokens。独立host_call_id仍null，不用response数冒充model_call_count。
来源未证明活动关联时activity_ids/slice_ids为空；已有明确集合的共享观察只计一次，不均分或逐片复制。
无活动绑定的response_absolute报告条目使用scope.kind=response、原生response_id与basis.event_ids回链，显示
USAGE_BOUNDARY_UNKNOWN并保持unassigned。请求汇总与逐响应条目不可相加；这不是精确逐活动成本。

原生task_started/task_complete/turn_aborted作为`timing=native_turn`的processing生命周期保存，
data.native含实际turn、原生timestamp、可得duration_ms及字节定位。native_turn_duration_ns只换算宿主报告的
duration_ms，basis为native_reported_turn_duration；它与Python单调时钟、纯模型耗时和请求墙钟分别列示。
缺起点/终点为NATIVE_TURN_START_UNKNOWN/NATIVE_TURN_END_UNKNOWN。即使native EOF和成对turn均可见，
本分支的请求usage仍为partial，不宣称完整Skill请求、首次有用反馈或等待边界；这些由实际大活动mark记录。

一次native读取上限8 MiB、10,000行、单原生行512 KiB；header/游标锚点复读也计入该预算。与规范化报告的
8 MiB/64 KiB事件上限分别计算。可选内部limits仅能降低max_bytes/max_lines；没有业务token预算。
超限/断尾/中间坏行分别为NATIVE_READ_LIMIT/NATIVE_RECORD_LIMIT/NATIVE_TAIL_INCOMPLETE/
NATIVE_MIDDLE_CORRUPT，保持已接受前缀；没有进展时不得忙重试。返回read摘要含实际bytes_read/lines_read、
start_offset/end_offset/eof，collector_duration_ns仅描述该次采集，不换算token。eof描述本次文件观察范围。

`cursors/<source_id>-native.json`保存绑定/头部摘要、文件身份、最后完整行锚点、ordinal、offset和固定写者UUID4。
事件先fsync，随后原子推进native游标。游标落盘失败可按旧位置重放，并复用原event_id/producer_id/observed_at；
不新增原生调用。替换、截短、锚点或关联变化产生NATIVE_CURSOR_INVALID。原始transcript、提示词、工具正文、
本机路径均不复制。采集进程收到KeyboardInterrupt时记录INTERRUPTED并原样传播，不能据此声称宿主可中断模型。


`inspect/telemetry`中的`first_useful_feedback_ns`和`first_usable_file_ns`按实际可对齐request起点计算，包含等待，coverage为partial。多个执行段须UTC根各自完整、标签配对且不重叠，才沿用最早观测起点；缺失、歧义、负间隔或时钟不兼容保留unknown及诊断。basis记录起点/终点事件和含等待口径，不能视为用户开场、纯模型耗时或精确逐步token。

Python 编写时可用 `ai_sow_lite.telemetry.record_mark(project, mark)` 消费同一 telemetry_mark 信封，或用 [Client.mark](python-client.md#直接活动埋点) 复用真实标签；两者记录实际调用时刻，失败仅返回观测降级。原 mark-file CLI 共用同一实现，未增加业务操作。
