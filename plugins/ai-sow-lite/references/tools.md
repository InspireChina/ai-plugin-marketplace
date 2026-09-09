# Lite I1.1 工具合同

I1.1 仅提供严格 JSON/摘要与 `check/candidate`。`ingest`、`inspect`、`render`、`apply`、`recover`、`check/edits` 及带 `plan_path` 的检查尚未实现，返回 `OPERATION_UNSUPPORTED`，不生成假登记或交付。运行时不依赖旧插件。

```text
<Lite 隔离 Python> <Lite 安装目录>/scripts/lite.py --request <UTF-8 请求文件>
```

请求固定字段为 `protocol_version="1.0"`、UUID4 `request_id`、显式 `project_path`、`operation="check"`、`payload`。payload 为 `candidate_path`、`scope="full"/"slice"`、`plan_path=null`。项目路径相对调用 cwd 解析一次；其余引用使用项目相对 POSIX 路径。候选及其三份业务 JSON 限定在本请求 `.ai-sow-lite/work/<entrypoint>/<request_id>/`，不得通过 `..` 或符号链接逃逸。

## 六份 Schema 与实际文件位置

- [model.schema.json](../contracts/model.schema.json)：D02 的 Epic/Feature/Story/内嵌 AC/Task/Dependency/Lineage。
- [pending-items.schema.json](../contracts/pending-items.schema.json)：`schema_version/items`；target 为 `{object_id, field}`。resolved 精确为 `{decision_id, request_id, summary}`；superseded 为 `{replacement_item_ids, lineage_refs, request_id, reason}`，其中 lineage 引用 `{from_version_id, from_ids}`。
- [decisions.schema.json](../contracts/decisions.schema.json)：`schema_version/items`；决定的 `applies_to` 同 target。
- [evidence.schema.json](../contracts/evidence.schema.json)：`schema_version/items`；analysis 的 `evidence[]` 使用其 `$defs/item`。来源定位为 `text_lines`、`xlsx_range`、`observation`。
- [protocol.schema.json](../contracts/protocol.schema.json)：请求及 `$defs/response`。未来操作只识别操作名并明确拒绝，尚不宣称其 payload 已可执行。
- [artifacts.schema.json](../contracts/artifacts.schema.json)：首次消费者的工件结构，按 `$defs` 校验。未来 manifest/projection/checkpoint 定义仅为结构，当前没有写入/应用实现。

I1.1 的独立合同夹具直接写以下文件；这不是 `ingest` 已实现的证明。Agent 探测也只可在临时项目准备合同输入和 work 候选。

| 文件 | Schema 定义及关键字段 |
| --- | --- |
| `.ai-sow-lite/project.json` | artifacts `project`：schema_version、project_id、project_type（new/existing）、template_hash |
| `.ai-sow-lite/template/<sha256>/sow-template.xlsx` | 原 Lite assets 模板的逐字节副本 |
| `.ai-sow-lite/inputs/index.json` | artifacts `input_index`：schema_version、items；input 含 input_version_id/input_id/content_hash/relative_path/format/material_types/uses/use_regions，文本增加 encoding="utf-8" |
| `.ai-sow-lite/inputs/originals/<input-version-id>/<filename>` | 不可变源文件字节；relative_path 指到这里 |
| `.ai-sow-lite/analysis/topics/<topic-version-id>/analysis.json` | artifacts `analysis`：schema_version、evidence[]、topics[]、observations[]（文件引用）；topics 使用 `$defs/topic`，版本 ID 须与目录及候选一致 |
| `.ai-sow-lite/inputs/readings/<read-id>/reading.json` | artifacts `reading`：绑定输入、内容哈希、适配器/选项和摘录文件引用；I1.1 尚无读取器 |
| `.ai-sow-lite/analysis/observations/<observation-id>/observation.json` | artifacts `observation`；必须是真实观察记录，不得写模拟成功 |
| `.ai-sow-lite/work/generate/<request-id>/candidate.json` | artifacts `candidate`；引用同请求的 model/pending-items/decisions，列所采用 evidence_ids/input_version_ids/topic_version_ids 和 template_hash |
| `.ai-sow-lite/work/generate/<request-id>/checks/<sha256>.json` | artifacts `check`；真实 CLI 检查报告，字节和依赖绑定 |

`analysis.topics[]` 必需字段：topic_id、topic_version_id、title、input_version_ids、uses、covered_regions、uncovered_regions、evidence_refs、related_object_ids、external_responsibilities、limitations、conclusion、historical_items。`covered_regions` 使用完整 source_ref（input_version_id、locator、excerpt_hash）。无相关对象可用空 related_object_ids；无 gap 的语义结论由 Agent 作出，工具只核对分析存在和引用一致。分析文件可包含共享依据；同 ID 的共享依据须字节语义一致，不能覆盖冲突内容。

每个 `topic_version_id` 对应唯一内容和 topic_id，并须在自身目录的 analysis.json 中出现。同一文件不能重复声明主题版本；不同文件共享该主题时内容必须完全一致。历史条目以 `(topic_version_id, id)` 定位，同版本 ID 不重复，显式 `parent_id` 只在该主题版本内解析且不能成环；`instance_facts[].evidence_refs` 同样核对依据闭合，不补造未知历史层级。

covered/uncovered 区域的 input_version_id 必须同时属于登记索引、候选和所在主题的输入集合。已支持 text_lines 的 start_line 不得大于 end_line，path 遵循下面的单文件规则。uncovered 区域没有成功摘录，不要求 excerpt_hash，不用已读行数或解码结果冒称该区域已经读取；本项检查仅说明声明的身份和基本定位一致。

`text_lines` 的 start_line/end_line 为 1 起始、含端点。单文件 `path` 可省略；提供时必须精确等于该 input_version_id 登记的 `relative_path` 或其 basename（如 `prd.md`）。工具始终读取登记原件，只将 locator.path 用于一致性核对，不跟随任意路径；错误文件名、未登记路径、绝对路径和逃逸路径均拒绝。摘录按已登记编码严格解码，保留原换行后以 UTF-8 编码计算 SHA-256；字符串不 trim 或 Unicode 归一化。UUID 示例短别名不能作为生产 ID。真实模板身份与标准行必须从 assets 读取，不能复制计算数值或旧业务合同。

## 返回与限制

stdout 仅一个 JSON：`ok/request_id/operation/result/diagnostics`。检查报告本体含 schema_version、validator_version、scope、candidate_ref、candidate_digest、dependencies、valid_for_render、unknowns_count、diagnostics；直接 `check_candidate(project, candidate_path, scope, plan_path)` 返回此本体且不写文件。CLI 保存报告，result 返回 check_ref/candidate_ref/plan_ref/review_ref/candidate_digest/valid_for_render/unknowns_count。slice 无错误也不能作为 render 权威。

诊断为 `code/target/message/preserved_paths`，target 为 `{path, object_id, field}`，未知部分 null。退出码 0 完成，2 不合法/不支持，3 I/O，1 未预期故障；取消与可靠交付尚未实现，不返回虚假的取消/生效事实。

当前 CLI/校验错误码：`PROTOCOL_INVALID`、`VERSION_INCOMPATIBLE`、`OPERATION_UNSUPPORTED`、`CANDIDATE_INVALID`、`EVIDENCE_MISSING`、`IO_FAILED`、`INTERNAL_ERROR`。自举错误码：`BOOTSTRAP_DIRECTORY_FAILED`、`UV_INSTALL_DOWNLOAD_FAILED`、`UV_INSTALL_DOWNLOADER_MISSING`、`UV_INSTALL_FAILED`、`UV_INSTALL_INVALID`、`UV_CHECK_FAILED`、`UV_VERSION_INVALID`、`PYTHON_INSTALL_FAILED`、`DEPENDENCY_SYNC_FAILED`、`VENV_MISSING`、`PYTHON_CHECK_FAILED`、`PYTHON_VERSION_INVALID`、`DEPENDENCY_IMPORT_FAILED`。自举失败使用相同信封、request_id/operation=null 和退出码 3。不回显原始异常或业务输入。合法未知、默认 M、有值 open 问题和未拆明工作不会被自动改值或关闭；工具不判断金额或语义充分性。

UUID4 必须恰好 36 字符，SHA-256 恰好 64 字符，json-v1 摘要恰好 72 字符；均拒绝尾随换行，不修剪或改写。业务文件或登记/分析文件无效时保留其真实诊断，继续运行其余有效依赖足以支持的检查；不会把无效文件当作合法空集合制造悬空引用。`valid_for_render=false` 的报告不授予任何交付权威；pending 文件无效时 `unknowns_count` 的占位 0 不代表业务没有待确认项，以文件诊断为准。

I1.1 实际定位校验仅支持已登记单文件文本的 `text_lines`；`xlsx_range`、原型包内文本、`observation` 的登记/复核适配属于 I1.2，当前返回明确诊断，不冒充附件已验证。历史复合键可只读核对 current → manifest 依赖链及相应旧模型；这些读取不实现可靠生效、恢复或完整交付核验。候选语义摘要覆盖所采用主题分析及依据；报告另绑定实际文件字节和依赖摘要，不把字节格式变化当作业务文字变化。

Lineage 仅检查 current 到显式 from_version_id 所需的已绑定历史区间。对象保持 `(version_id, object_id)` 身份；继承记录须与该区间已保存的同复合键记录完全一致，以其首次出现的后继模型定位替换发生版本。原对象须在替换前持续存在，去向须在该次模型存在；已退出的中间去向只能由时间更晚的有效替换继续到当前对象或明确删除。缺少摘要绑定模型、缺少实际继承记录或只在任意早期历史找到同名 ID 的链不支持据此通过，会返回文件或 lineage 诊断；不推断发生顺序、不恢复缺件、不扫描显式区间以外的无关历史。

Bash/PowerShell 自举迁入来源为 D00 的 `2fc8588`，只适配身份、路径与单请求 CLI。脚本固定 uv 0.11.7、Python 3.12 和锁定依赖；缓存/下载安装放在 Lite 副本 `.ai-sow-tools/`。没有沿用旧 Windows 97 字符支持声明；本轮平台验证范围以任务报告为准。
