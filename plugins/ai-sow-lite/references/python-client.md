# Python 调用助手

隔离环境就绪后，用插件自己的 Python 执行以下代码。`plugin` 来自已加载 Skill 的位置，`project` 为用户项目，`request_id` 沿本次请求保持。按实际阶段填写 `entrypoint` 和观察上下文。构造 Client 不创建项目或检查点；首次先完成 ingest，再保存草稿。

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
| `client.save(name, value)` | 输入登记成功后，将 Agent 编写的 JSON 存入本请求 `authoring/`，返回 `{path,sha256}`。name 只含文件名；同名同内容复用，不同内容拒绝覆盖。新稿选新名，保持原请求及修订额度。 |
| `source_ref(region_result)` | 从实际区域查询的 result 取 input_version_id、locator、excerpt_hash；XLSX 保留实际 read_id。 |
| `client.bind_confirmation(check_ref, answer_ref)` | 核验实际成功检查和展示计划原字节，将 Agent 已识别的真实执行答复引用附到确认副本，返回文件引用。后续 check 仍核验来源、候选和确认。只适用于 Clarify。 |

业务内容由 Agent 编写。每个工具操作仍单独校验和记录时间；连续、已确定的机械操作可放同一 Python 调用中，减少模型往返。遇到需要解释或决策的结果就读必要字段再继续；OperationError 不自动重试。保存必要引用供下一轮续接；完整正文只在本轮需要时输出。

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

观察上下文可在实际活动切换时更新 `client.observation_context`；请求根和大活动标记仍按 [检查点与活动观察](generate-authoring.md#检查点与活动观察) 记录，和上述调用合批。调用助手不增加模型调用、活动状态机或 token 推算。
