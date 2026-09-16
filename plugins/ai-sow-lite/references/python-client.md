# Python 调用助手

隔离环境就绪后，用插件自己的 Python 执行以下代码。`plugin` 来自已加载 Skill 的位置，`project` 为用户项目，`request_id` 沿本次请求保持。按实际阶段填写 `entrypoint` 和观察上下文。构造 Client 不创建项目或检查点；首次先完成 ingest，再保存草稿。execution_id、activity_ids/slice_ids 中的各ID均为UUID4，可用 `str(uuid4())` 生成一次后保存沿用；活动名称只传给 mark 的 name，不作为ID。

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(plugin).resolve() / "runtime"))
from ai_sow_lite.authoring import Client, source_ref

client = Client(project, request_id, entrypoint, observation_context=observation_context)
```

新项目先按 [登记、读取和分析](generate-authoring.md#登记读取和分析) 调用 ingest。Clarify 对既有交付项目先调用 `client.call("inspect", {"view":"current", "selector":{}})` 保存基线。

| 调用 | 作用 |
| --- | --- |
| `client.call(operation, payload)` | 执行一次既有操作，返回成功响应的 **result**。payload 同 [工具合同](tools.md)。失败抛出 OperationError，其 `.response` 保留完整真实响应及诊断，当前批次随之停止。 |
| `client.mark(name, phase)` | 以当前真实 execution/activity/slice 标签记录当前边界，request 根活动/片集合自动为空。返回 recorded/degraded，不抛业务异常，不自动开始下一阶段。 |
| `client.save(name, value)` | 输入登记成功后，将 Agent 编写的 JSON 存入本请求 `authoring/`，返回 `{path,sha256}`。name 只含文件名；同名同内容复用，不同内容拒绝覆盖。新稿选新名，保持原请求及修订额度。 |
| `source_ref(region_result)` | 从实际区域查询的 result 取 input_version_id、locator、excerpt_hash；XLSX 保留实际 read_id。 |
| `source_use_region(region_results, *, material_type, use)` | 同一输入版本的实际区域结果映射为一个 use_regions 条目，仅含 material_type/use/locators；空选择、身份缺失或混版本拒绝，XLSX read_id 保持。类型/用途和真实来源由原 ingest 校验。 |
| `client.bind_confirmation(check_ref, answer_ref)` | 核验实际成功检查和展示计划原字节，将 Agent 已识别的真实执行答复引用附到确认副本，返回文件引用。后续 check 仍核验来源、候选和确认。只适用于 Clarify。 |

原始输入 `source_path` 必须为绝对路径；项目内反馈可用 `str(client.project / "feedback.md")`。返回的 candidate/check/plan 等已保存工件引用则用项目相对路径，直接沿用真实返回值。

业务内容由 Agent 编写。每个工具操作仍单独校验和记录时间；连续、已确定的机械操作可放同一 Python 调用中，减少模型往返。遇到需要解释或决策的结果就读必要字段再继续；OperationError 不自动重试。保存必要引用供下一轮续接；完整正文只在本轮需要时输出。

## Windows 路径与 CLI 子进程

连续操作优先调用同进程 `Client.call`，减少子进程启动、命令行引号和 shell 路径转换环节。`Client` 仍需要调用方提供当前 Python 能识别的正确路径，并不会修复错误路径。

原生 Windows Python 中，`plugin`、`project`、请求文件及原件的绝对路径用 `C:/work/...` 或 `C:\work\...`；Python 字符串中的反斜杠用 raw string，例如 `Path(r"C:\work\project")`。Git Bash 的 `/c/work/...` 属于 shell 路径语法，不能直接沿用到原生 Python 的 `Path` 或 `subprocess.run` 参数。`Path.resolve()` 不会把 `/c/...` 自动转换为盘符路径；应在进入 Python 前确定真实原生路径，不按字母或目录存在性猜测盘符。

确需调用 CLI 时，从本插件的隔离 Python 启动当前脚本，使用 `sys.executable` 和参数列表，保留已有命令合同：

```python
import subprocess
import sys
from pathlib import Path

# plugin 和 request_file 已是当前系统可识别的真实绝对路径。
completed = subprocess.run(
    [sys.executable, str(Path(plugin) / "scripts" / "lite.py"),
     "--request", str(Path(request_file))],
    capture_output=True, text=True, encoding="utf-8", check=True,
)
```

参数列表无需为含空格路径额外嵌入引号，也无需 `shell=True`；它不会触发 Git Bash 的路径转换。项目内已保存工件引用仍沿用工具返回的相对 POSIX 路径，不改成 Windows 绝对路径。

## 区域结果与证据引用

Python 构造 `source_refs`、`covered_regions` 或确认答复引用时，统一调用 `source_ref(region_result)`；参数是成功区域查询的 **result**，CLI 响应需先取 `response["result"]`，`Client.call` 已返回这一层。目录读取仅用于选区域，不能充当区域证据。

| 字段 | 文本区域结果 | XLSX 区域结果 |
| --- | --- | --- |
| `coverage.selector.locator` | 请求中的行定位，作为证据 locator | 请求回显，可能包含选区时使用的目录 read_id；不能替代实际区域 locator |
| `coverage.locator` | 不按 XLSX 形状推取 | 实际区域 locator，含本次区域读取的 read_id；证据采用此处 |
| `coverage.selector.input_version_id` | 实际输入版本 | 实际输入版本 |
| `coverage.excerpt_hash` | 实际文本摘录哈希 | 实际区域摘录哈希 |

纯 CLI 调用者可按上表手工构造 `{input_version_id, locator, excerpt_hash}`；逐字保留实际返回值。XLSX 即使 sheet/range 相同，目录与区域 read_id 的证据含义也不同，不能互换或自行生成。助手处理两种定位形状并复制真实引用，不增加响应字段，也不替代实际读取。

## 连续执行已确认的修改

例如用户已经明确执行刚展示的具体方案，实际答复已登记并读取后，Agent 可显式连续调用：

```python
# checked 为原方案成功 check 的 result；region 为真实执行答复区域的 result。
# baseline 为讨论前保存的完整 current，不能用新的 current 替换旧基线。
confirmation = client.bind_confirmation(checked["check_ref"], source_ref(region))
verified = client.call("check", {
    "candidate_path": checked["candidate_ref"]["path"],
    "plan_path": confirmation["path"], "scope": "full"})
prepared = client.call("render", {
    "candidate_path": checked["candidate_ref"]["path"],
    "check_path": verified["check_ref"]["path"], "expected_current": baseline})
applied = client.call("apply", {
    "entrypoint": "clarify", "prepared_path": prepared["prepared_ref"]["path"],
    "plan_path": confirmation["path"], "expected_current": baseline})
```

此例的执行前提仍由 [真实确认规则](clarify-changes.md#把真实执行答复接到工具生成的计划) 约束。构造确认引用不表示来源是同意，也不认证用户身份。执行中失败保留已成功的引用，按原有限返修/恢复处理；不会因重新构造 Client 清零额度。

## 用实际读取结果登记用途区域

一份材料兼有多种用途时，Agent 先明确对应区域、材料类型及用途，再调用这个机械助手。`source_spec` 是调用方已选原件的原 sources 条目，`registered_source` 是其真实登记项；`selected_region_results` 是该原件已读取区域的 result。保留原有声明，外层使用实际 input_id，不能写成 input_version_id，也不新增 ingest kind。

<!-- source-use-region-example -->
```python
from copy import deepcopy
from ai_sow_lite.authoring import source_ref, source_use_region

assert {source_ref(r)["input_version_id"] for r in selected_region_results} == {
    registered_source["input_version_id"]}
assert chosen_material_type in source_spec["material_types"]
assert chosen_use in source_spec["uses"]
region_entry = source_use_region(selected_region_results,
    material_type=chosen_material_type, use=chosen_use)
source_entry = deepcopy(source_spec)
source_entry["input_id"] = registered_source["input_id"]
source_entry["use_regions"].append(region_entry)
registered = client.call("ingest", dict(kind="sources", entrypoint=client.entrypoint,
    project_type=project_type, sources=[source_entry]))
```

助手不判断用途、不扩读材料、不合并不同原件或版本。已有用途/区域由原 ingest 追加去重；仍须声明真实采用的读取，不用助手补造覆盖。

## 直接活动埋点

在现有 Python 调用里直接记录已发生的边界，无需写 mark-file 或启动观测子进程：

```python
client.mark("request", "start")
client.mark("input_analysis", "start")
# 在这里执行本次实际输入分析。
client.mark("input_analysis", "end")
# 确实切换活动后，更新 client.observation_context，再记录下一活动。
client.mark("request", "end")
```

调用前提供真实 observation_context，至少含本执行段已确定的 execution_id；缺少身份返回 degraded，不能自行补造新执行段去闭合旧边界。大活动和片沿实际ID记录，跨用户轮次的 user_wait 两端继续用已保存的同一 execution/activity 标签；新执行段另用其实际身份。可用保存的旧上下文构造另一个 Client 只记录旧等待的结束，仍是同一请求。

每个 mark 只记调用当时，不回填早先时刻，也不改 Client 上下文或业务检查点。recorded/degraded 只反映观测，失败按一次缺口报告后继续业务。直接底层接口为 `ai_sow_lite.telemetry.record_mark(project, mark)`，使用原 [标记信封](generate-authoring.md#检查点与活动观察)；原 CLI 仍可用。这些标记不提供活动 token 的精确归属。
