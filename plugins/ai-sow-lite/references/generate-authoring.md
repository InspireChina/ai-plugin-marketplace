# Generate 命令与候选编写

按当前活动读取本文件相应部分；特殊诊断或完整机械定义再查 [工具合同](tools.md)，字段歧义只打开对应 Schema 的定义。专业内容由 Agent 从真实输入选择，可用 Python 序列化这些内容、生成 UUID4/摘要和拼装文件；代码不负责推导 Story、分类、充分性或下一活动。

## 启动与请求身份

`<plugin-root>` 从已加载 `skills/generate/SKILL.md` 的位置解析，`<project-root>` 为显式用户项目目录。业务 JSON 路径均为项目相对 POSIX 路径。先生成一个 UUID4 作为逻辑 `request_id`，同一请求的所有工具调用沿用它；请求信封可分别落文件。

首次 `ingest` 会创建项目和本请求 work/checkpoint。**不要提前创建 `.ai-sow-lite/work/generate/<request-id>/`**，否则它会被视为已存在但缺失检查点的请求。把首个请求信封放项目内该 work 之外，待 ingest 成功再写分析/候选。

macOS/Linux 首次调用：

```sh
sh "<plugin-root>/scripts/bootstrap.sh" --request "<request-file>"
```

Windows PowerShell 首次调用：

```powershell
& "<plugin-root>/scripts/bootstrap.ps1" -Request "<request-file>"
```

后续复用该副本隔离 Python，不修改用户 PATH、依赖或宿主设置：

```sh
"<plugin-root>/.venv/bin/python" "<plugin-root>/scripts/lite.py" --request "<request-file>"
```

Windows 对应 `& "<plugin-root>/.venv/Scripts/python.exe" "<plugin-root>/scripts/lite.py" --request "<request-file>"`。bootstrap 准备 uv 0.11.7、Python 3.12 和锁定依赖；首次可联网下载到插件副本。Office 由已有 `soffice/libreoffice` 或当前执行环境的 `AI_SOW_LITE_OFFICE_BIN` 发现，缺引擎时报诊断，不代装宿主工具。

## 登记、读取和分析

每份请求用下面的信封结构。占位符须换成实际值；例子只演示登记，不表示 PRD 单独足以生成：

```json
{
  "protocol_version": "1.0",
  "request_id": "<request-id>",
  "project_path": "<project-root>",
  "operation": "ingest",
  "payload": {
    "kind": "sources", "entrypoint": "generate", "project_type": "new",
    "sources": [{"source_path": "<prd-path>", "input_id": null,
      "material_types": ["PRD"], "uses": ["to-be"], "use_regions": []}]
  }
}
```

同批添加 HLD；旧项目使用 `project_type="existing"` 并登记历史 SOW，历史用途为 `as-is`，其余本期材料为 `to-be`。一文件承担多用途时，按 [输入分析](input-analysis.md) 登记实际用途区域，不能仅靠标签宣称补齐 PRD/HLD。响应 `result.input_refs` 是实际输入登记项，采用其中的 input_id/input_version_id 及返回 reading，不猜 ID、行号或哈希。

| operation | payload 与返回的用途 |
| --- | --- |
| inspect | `{"view":"current","selector":{}}` 或 `{"view":"request","selector":{"request_id":"<UUID4>"}}`：已有项目/请求的事实 |
| inspect | `{"view":"regions","selector":{"input_version_id":"<UUID4>"},"limit":20,"cursor":null}`：目录；同 selector 加实际 `locator` 读原文/区域，按下例映射定位与摘录哈希；正常分页沿 `next_cursor` |
| inspect | `{"view":"standards","selector":{},"limit":100,"cursor":null}`：类型目录；按片用 `work_type_ids` 或 `work_type_names` 数组合批读取相关定性规则 |
| ingest | `{"kind":"analysis","entrypoint":"generate","analysis_path":"<work>/analysis.json"}`：登记已写的分析，返回 evidence_ids/topic_version_ids |
| check | `{"candidate_path":"<work>/merged/candidate.json","scope":"full","plan_path":null}`：返回 check_ref、valid_for_render 和 diagnostics；片内改用 scope="slice" |
| render | `{"candidate_path":"<work>/merged/candidate.json","check_path":"<实际 check_ref.path>","expected_current":null}`：真实 Office 投影复读，返回 prepared_ref、version_id 及文件引用 |
| apply | `{"entrypoint":"generate","prepared_path":"<实际 prepared_ref.path>","expected_current":null,"plan_path":null}`：核验准备包，保存有效版本 |
| recover | `{"target_request_id":"<原 request_id>"}`：只查询实际应用事实，不重算或激活孤立结果 |

`<work>` 表示 `.ai-sow-lite/work/generate/<request-id>`，不是实际 token。工具 stdout 为单个 `ok/request_id/operation/result/diagnostics` JSON；保存响应文件，读取必要 result/诊断即可，不把整份工具输出当业务来源。失败保留已成功引用；检查错误、原件变化或真实 Office 失败必须按有界返修处理。

以下映射可直接执行：`region_result` 是成功的**区域查询**响应的 `result`（不是目录），`standard_row` 是 Agent 已选标准查询的 `result.items` 中一项。文本定位取 `coverage.selector.locator`，XLSX 定位取 `coverage.locator` 以保留实际区域 read_id；两者摘要均取 `coverage.excerpt_hash`。标准返回的精确键为 `工作类型 ID` 和 `工作类型`。

```python
coverage = region_result["coverage"]
selector = coverage["selector"]
locator = (coverage["locator"] if selector["locator"]["kind"] == "xlsx_range"
           else selector["locator"])
source_ref = {
    "input_version_id": selector["input_version_id"],
    "locator": locator,
    "excerpt_hash": coverage["excerpt_hash"],
}
standard_id = standard_row["工作类型 ID"]
work_type_name = standard_row["工作类型"]
```

分析文件形状为 `{"schema_version":"1.0","evidence":[],"topics":[],"observations":[]}`；topics 必须非空且有实际依据。没有采用实际观察时 observations 为空；有目录原型及真实观察时，按 [原型输入](prototype-inputs.md) 填已保存记录的file_ref并核对附件，不能伪造浏览器状态。初次分析可先用主题 ID，实际业务对象尚未形成时 related_object_ids 为空。

| 记录 | 字段与实际来源 |
| --- | --- |
| evidence item | `id, kind, text, source_refs, basis_refs, limitations`；kind 为 statement/observation/judgment。当前直接材料用 statement，source_refs 非空；专业推断用 judgment，basis_refs 非空并最终回到真实来源 |
| source_ref | `input_version_id, locator, excerpt_hash`，按上例从真实区域响应取得；文本 start_line/end_line 为含端点的 1 起始行，XLSX 用返回区域 read_id，不能用目录 read_id 代替 |
| topic | `topic_id, topic_version_id, title, input_version_ids, uses, covered_regions, uncovered_regions, evidence_refs, related_object_ids, external_responsibilities, limitations, conclusion, historical_items`；related_object_ids 只放业务模型中的 Epic/Feature/Story/AC/Task 及 dependency ID，不放待确认项、决定或依据 ID。答复待确认项时关联其 targets 指向的实际业务对象；问题处理通过 pending_items/decisions 的原有关系记录 |
| topic 区域 | covered_regions 是 source_ref 数组；uncovered_regions 每项为 `input_version_id, locator, reason`。只声明真实覆盖，conclusion 保存 Agent 的分析结论 |
| historical_item | 必需 `id, label, description, evidence_refs`；仅已有时加 level/parent_id/type_hint/instance_facts，instance_facts 项为 `text, evidence_refs` |

正式分析登记后不可改旧主题/依据含义；新增内容用新的 topic_version_id，保持语义相同的 topic_id/依据 ID。同 ID 共用依据内容必须一致。需要字段细节时查 [analysis/topic 定义](../contracts/artifacts.schema.json) 和 [evidence 定义](../contracts/evidence.schema.json)，不必一次加载全部 Schema。

实际用户答复按原话保存到 work 的文本文件，作为 source 再登记/读取，再以来源支持 adopted fact 或 scope_decision。不是用户原话的解释只能作为 judgment。问题先在工作记录中关联主题，生成对象后才能填正式 targets；不要为保存答复提前造业务对象。

## 工作索引、候选和准确绑定

`input-review.md`、`input-questions.json`、`skeleton.json`、`slice-index.json`、`activity-record.json` 是工作文件，可按本请求最小需要组织，不塞进稳定 JSON。问题记录保存实际问题批次、实际答复原文路径、采用/仍缺事实、主题关联及最终决定/问题去向。activity-record 保存逻辑目标、每批有限覆盖、主动提问次数、重分片次数、各候选修正次数、根因/修法、退出原因与有效候选位置；压缩后从这里续接。

每片在 `slices/<slice-id>/` 保存候选和必要父项；全片首次结束后在 `merged/` 形成完整候选。业务 JSON 的必需容器与字段如下，详细约束按链接查询：

| 文件/对象 | 必需字段 |
| --- | --- |
| [model](../contracts/model.schema.json) | `schema_version="1.0", epics, features, stories, tasks, dependencies, lineage`；六个集合均为数组，首版 lineage 为空 |
| Epic | `id, title, evidence_refs` |
| Feature | `id, epic_id, title, evidence_refs` |
| Story | `id, feature_id, title, acs, notes, evidence_refs`；AC 内嵌，每项 `id, text, evidence_refs` |
| Task | `id, story_id, name, work_type_name, work_mode, complexity, integration_type, notes, not_applicable_fields, evidence_refs, classification_basis` |
| classification_basis 项 | `fields, evidence_refs, standard_id, rationale`；fields 为分类字段数组，standard_id 取所选 standards 行的 `工作类型 ID`，rationale 说明已选事实与该规则的关系 |
| Dependency | `id, from_story_id, to_story_id, kind, notes, evidence_refs`；kind 为 uses/delivery_precondition，由消费/依赖方指向提供/前提方 |
| [pending-items](../contracts/pending-items.schema.json) | `schema_version="1.0", items`；每项 `id, revision, question, targets, evidence_refs, current_handling, unestimated_work, status, resolution` |
| [decisions](../contracts/decisions.schema.json) | `schema_version="1.0", items`；每项 `id, kind, text, evidence_refs, applies_to`，kind 为 fact/scope_decision；首次可无决定 |
| [candidate](../contracts/artifacts.schema.json) | `schema_version="1.0", entrypoint="generate", base_version_id=null, model_path, pending_items_path, decisions_path, evidence_ids, input_version_ids, topic_version_ids, template_hash` |

业务 ID 使用 UUID4，在请求内保存在小型 ID 映射中复用；语义改变不复用旧 ID。candidate 的三个文件路径和 candidate 自身均在同请求 work 中；所采用输入/主题/依据采用登记返回的真实 ID，template_hash 读取项目身份。文件引用 `{path,sha256}` 的 sha256 是实际文件字节 SHA-256；不要自填工具报告、prepared 或版本 manifest。

Task 的 work_type_name 精确采用标准名；work_mode 为该标准允许的新建/调整/接入复用或 null，complexity 为 S/M/L，integration_type 为内部集成/外部集成或 null。非集成类型明确不适用时 `not_applicable_fields=["integration_type"]` 且该字段为 null；其他情况不放入这个数组。四个分类字段的有效值和明确不适用都需要 classification_basis 覆盖，可以由同一依据项覆盖多个字段；未知类型时 standard_id=null。

targets/applies_to 均为 `{object_id,field}` 数组，field 必须是该对象实际字段名或对象级 null，不能使用 `Task.complexity` 或点路径。默认 M 的 open 问题用 Task ID 加 `field="complexity"`；其他未知分类字段同样精确绑定。未拆明工作用 Epic/Feature/Story ID、field=null、unestimated_work=true。新问题 revision=1、status="open"、resolution=null。空 acs 需要指向 Story 的 `field="acs"` 问题，空父项需要未拆明工作；全部 gap 已满足的空模型应有充分主题结论，不能留占位父项。resolved 仅在实际决定覆盖全部目标后使用，其 resolution 为 `decision_id,request_id,summary`。

补充依据需先登记新的分析版本，再更新采用的 candidate 引用。片内尚未绑定的跨片关联留在 work，合并时转正式 Dependency；full check 前不能剩下虚构 ID。输入问题在合并时逐项落到同版决定、open 问题或明确排除/已满足的主题结论，空范围也不为绑定决定造 Task。

## 检查点与活动观察

已有 checkpoint 中的 additional_investigation_batches、repair_batches、recovery_queries 和 operation_retries 按实际消耗保存；其他专业次数保存在 activity-record，避免扩展运行时领域合同。更新 checkpoint 使用已有 `ai_sow_lite.project.ensure_request`/`save_checkpoint`：在本次隔离 Python 子进程中令 `PYTHONPATH=<plugin-root>/runtime`，加载原 checkpoint、只修改本批已知事实、调用 save_checkpoint。不要重建或归零已有/未知计数。render 可能自己消耗 repair_batches，外层更新前先复读，不能用旧字典覆盖。

每次 generate **必须尽力记录**请求边界、首次有用反馈、首个可用文件和实际大活动。生成 request_id 后，在最早可执行工具的位置记录 request/start；缺失的前段如实保留为未观测，结束本次处理前记录 request/end。发生过的边界才记录，缺标记不回填时间。它们是同一专业工作的观察，不增加专业阶段、问答或审批；记录失败给一次简短缺口后继续业务。

| 实际边界 | name | phase | 记录时机 |
| --- | --- | --- | --- |
| 本请求执行 | `request` | `start/end` | 最早可记录点 / 交付或补料等本次处理退出前；恢复沿原 request_id，执行段可换 execution_id |
| 输入理解 | `input_analysis` | `start/end` | 开始读取分析 / 本段输入判断形成 |
| 骨架与分片 | `outline` | `start/end` | 开始组织义务 / 骨架与片索引形成 |
| 联合生成 | `generation` | `start/end` | 当前片开始 / 本片候选形成；附当前 slice_ids |
| 语义合并 | `merge` | `start/end` | 开始整合 / 合并候选形成 |
| 文件交付 | `export` | `start/end` | 进入核验、导出与应用 / 本段完成或实际失败退出 |
| 等待用户 | `user_wait` | `start/end` | 实际提出需要答复的问题 / 实际收到答复；未配对区间保持未知 |
| 首次有用反馈 | `useful_feedback` | `milestone` | 首次给出可回答的问题包或可用方案；普通进度消息不算 |
| 首个可用文件 | `usable_file` | `milestone` | 首版已核验并应用、可以交给用户时 |

使用同一隔离 Python、仅在本次进程设置上述 PYTHONPATH，执行 `-m ai_sow_lite.telemetry --project "<project-root>" --mark-file "<mark-file>"`。多个恰好同处的边界可与已有工具命令合在一次宿主调用中执行；标记不能移动到事后伪造起点。已有业务信封附 `observation_context={"execution_id":"<execution-id>","activity_ids":["<activity-id>"],"slice_ids":[]}`，保持当前活动/片标签。纯语义边界才补轻量mark，不逐思考或逐 Task 埋点。

以下是请求起点mark；复制后按实际边界更换name/phase，活动ID沿当前大活动复用，片ID只填实际关联：

<!-- observation-mark-example -->
```json
{
  "schema_version": "1.0",
  "request_id": "<request-id>",
  "execution_id": "<execution-id>",
  "activity_ids": ["<activity-id>"],
  "slice_ids": [],
  "name": "request",
  "phase": "start"
}
```

request/end记录发生在最终答复用量到达之前，报告可为partial。宿主明确提供已授权来源路径和准确thread/turn关联时，按[原生采集合同](tools.md#原生响应的有界采集)执行一次有界采集；源不可得即保留unknown，不搜索聊天目录。生产者结束后只有显式采集才补迟到用量。响应结束时间不证明活动独占token；跨活动有证据就记shared，无法关联就未归属。记录故障不重跑模型、Office或专业工作。

## 有效交付

full check 通过后采用返回 check_ref；候选或依赖字节改变则旧检查失效。render 负责真实计算和复读，成功后把返回 prepared_ref.path 传给 apply，首版两者 expected_current 都是 null。apply 保存的 `.ai-sow-lite/versions/<version_id>/` 包含同版 sow.xlsx、summary.md、pending-items.md 及业务/投影 JSON，必要时有 details.md；以 apply 返回为准链接这些文件，不能把 work 中预览冒充已生效版本。

current 已有版本或同一请求结果不明时先用 inspect/recover 核实。已有结果可直接返回；首版入口不执行版本修改，不能删除 current 或换 request_id 重生成。对现版的解释和有限修改交给 [Clarify](../skills/clarify/SKILL.md)。
