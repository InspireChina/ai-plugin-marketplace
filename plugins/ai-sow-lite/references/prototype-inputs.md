# 原型资源与观察登记

遇到目录原型、需要核对实际页面状态、已有观察附件或原型无法运行时，使用本参考。工具提供原字节、定位与依赖检查；业务解释、观察目标和是否足以出稿仍由当前主 session 判断。

## 资源边界和静态读取

通过既有 `ingest` 的 `kind="sources"` 提供资源包目录为 `source_path`，`material_types=["prototype"]`，用途按材料实际内容登记。目录是明确边界，必须包含需要采用的入口、代码、图片和本地说明。单个 HTML 文件当前不支持；请提供明确整理的目录包，工具不会递归摄入其所在父目录。登记不执行源码、启动服务、安装依赖或下载浏览器。

一个包最多2048成员（包括空目录）、16层、合计50 MiB；空目录参与枚举上限但不构成资源字节身份。所有普通文件原字节保存，含当前无法解释的二进制。符号链接、特殊文件、重定向目录、`..`、冒号、反斜杠及控制字符路径拒绝；超限给 `RESULT_TOO_LARGE`，没有半份完整登记。包内文件名保持原值，不翻译、改大小写或做 Unicode 规范化。读取时绑定已核对的目录句柄，并相对该句柄打开后代；目录被替换不能引入包外字节。缺少目录 fd/no-follow 能力的平台结构化返回 `OPERATION_UNSUPPORTED`，目前没有 Windows 原型包实测或兼容承诺。

`input.relative_path` 指向不可变 `manifest.json`。`input.resources` 是按包内相对路径排序的 `{path,sha256}` 数组；`input.content_hash` 为该数组经 P00 canonical JSON 编码后的原字节 SHA-256。资源实际保存于同一原件目录的 `resources/<包内路径>`。资源名或字节变化形成新版本；相同清单复用同一物理版本与 `lite-prototype-v1` reading。观察需要的资源引用使用 `inspect/regions` 目录项的 `file_ref`，不是包内相对路径本身。

`inspect` 使用 `view="regions", selector={input_version_id}` 分页列出每个资源、可读状态、准确 `file_ref` 与文本 `locator`。HTML/JS/MJS/CSS/JSON/SVG/Markdown/TXT 可按严格 UTF-8 读取；BOM 解码为 utf-8-sig，保留 CRLF/LF/CR，原件不重写。其他二进制、空文本、解码失败分别显示真实可读范围。源码定位必须带精确包内路径，例如：

```json
{"view":"regions","selector":{"input_version_id":"<UUID4>","locator":{"kind":"text_lines","path":"assets/app.js","start_line":1,"end_line":8}},"limit":20,"cursor":null}
```

采用响应中的 `coverage.locator/excerpt_hash`。长行可按 `line_number/character_offset/text` 有限续读；默认20项、最多100项、完整信封最多64 KiB。目录和分页结束仅表示物理查询完成。

## 观察与原始记录

先按本次 PRD/HLD 疑点组成有限首批观察目标，自主选择路径。输入、历史和原型共用至多一次追加调查；新路由不能自动刷新额度。运行条件不足时保留具体缺口，使用源码及其他材料判断影响。源码没有运行不成为实际状态证据；无法进入某分支不证明其不存在。

实际观察记录使用 artifacts 中既有 `observation` 合同：`schema_version/observation_id/input_version_id/entrypoint/preconditions/actions/observed_at/result/resource_refs/attachments/limitations`。ID 使用 UUID4；入口记录实际路由和对象；前置、动作、时间、结果由实际观察填写。无工具捕获附件时 `attachments=[]`，在 limitations 说明只有观察者文字、未保留捕获附件。机器校验摘要无法证明观察真实性，也不会生成补充观察。

同名按钮可能属于不同路由或对象；记录所见的具体状态和反馈。设置一个已勾选控件为相同值，调用成功不证明触发了 change；核对状态变化计数。模拟成功仅能证明本地演示，不能证明真实后端或 as-is。源码存在但不可达的分支保留静态来源与未观察限制。取消和迟到结果同样记录实际所见，不修改原型以制造结果。

将原始观察 JSON 与必要截图/状态附件放入**本请求** work。`resource_refs` 使用该原型版本已登记资源的项目相对 file_ref；`attachments` 使用 work 中真实文件的项目相对 file_ref。一份观察最多1 MiB JSON、64附件且附件合计50 MiB；每个 file_ref 按文件原字节取 SHA-256。不要把预期、合成记录或静态 HTML 摘要写成动态观察。

分析的 `observations` 列出这些 work 观察 JSON 的 file_ref，或已登记的不可变观察 file_ref；没有新 CLI 操作。证据使用 `locator={kind:"observation",observation_id}`，`excerpt_hash` 为原始观察 JSON 原字节摘要；可选 `attachment` 指原始记录列出的附件路径或其采用后的路径，`region` 只作显示提示，代码不验证图像区域含义。附件 hash 独立检查，不能替代观察记录 hash。

登记保留原始 JSON 原字节到 `analysis/observations/<observation_id>/observation.json`，附件采用到该目录的 `attachments/<从0开始的索引>/<原文件名>`；原始观察 JSON 中的 work 引用作为来源说明保留，不重写其字节。`registration-ref.json` 绑定不可变观察摘要。登记前批量核对观察及附件，登记过程中失败保留有效字节，可按精确同内容重试；分析失败也可能保留已核对的观察，不能据此声称主题已登记或 current 已改变。

主题文件保存采用后的 observation refs。同一观察可在多个主题共用，不复制截图；每个拆分主题保留其 `input_version_ids` 对应的观察。新增观察须有新的 topic_version_id 承载，同 ID 不同原字节报冲突。重复采用已登记观察时复核不可变副本，后续不依赖 work 原附件。原型资源、观察记录、登记引用和所有采用附件进入 check 的真实依赖，并由既有 prepared/apply 通路保留；缺失、修改或链接替换给 `EVIDENCE_MISSING`，current 保留。

## 可执行登记消费者

以下代码消费主 session 已经写好的合法 `analysis`（含主题、依据及真实观察 source_ref），以及本请求 work 中真实观察 JSON；它只填充 file_ref 并调用既有操作。调用方提供已解析安装副本的 `python`、`lite_script`、项目 `project`、`request_id`、`analysis` 字典、`observation_path` 和 `observation_input_version_id`。观察 JSON 的 attachments/resource_refs 及 analysis 中的 excerpt_hash 必须预先由实际文件计算。代码没有浏览器动作或预制语义结果。

```python
from pathlib import Path
import hashlib
import json
import subprocess

project = Path(project).resolve()
work = project / '.ai-sow-lite/work/generate' / request_id
observation_path = Path(observation_path)
observation_bytes = observation_path.read_bytes()
observation = json.loads(observation_bytes)
observation_ref = {
    'path': observation_path.relative_to(project).as_posix(),
    'sha256': hashlib.sha256(observation_bytes).hexdigest(),
}
analysis['observations'] = [observation_ref]
analysis_path = work / 'observation-analysis.json'
analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def call(operation, payload):
    envelope = dict(protocol_version='1.0', request_id=request_id,
                    project_path=str(project), operation=operation, payload=payload)
    request_file = work / 'observation-request.json'
    request_file.write_text(json.dumps(envelope, ensure_ascii=False), encoding='utf-8')
    completed = subprocess.run([str(python), str(lite_script), '--request', str(request_file)],
                               capture_output=True, text=True, encoding='utf-8', timeout=180)
    response = json.loads(completed.stdout)
    if not response['ok']:
        raise RuntimeError(response['diagnostics'])
    return response['result']

registered_analysis = call('ingest', dict(kind='analysis', entrypoint='generate',
                           analysis_path=analysis_path.relative_to(project).as_posix()))
observed_region = call('inspect', dict(view='regions', selector={
    'input_version_id': observation_input_version_id,
    'locator': {'kind': 'observation', 'observation_id': observation['observation_id']},
}, limit=20, cursor=None))
```

成功时 `registered_analysis.analysis_ref` 指原始分析登记，`observed_region.coverage.excerpt_ref` 指采用的观察 JSON，`attachment_refs` 给采用附件的路径与摘要。超大观察正文返回 `RESULT_TOO_LARGE` 和保存路径，从该记录定向读取，不截断冒充完整观察。正式候选采用返回的 topic_version_ids/evidence_ids 及相关 input_version_ids，再使用原有 check/render/apply。
