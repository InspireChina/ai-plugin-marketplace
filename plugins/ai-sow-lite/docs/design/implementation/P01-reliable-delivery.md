# P01 · 可靠程序交付实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 合成候选与真实依据经检查、Office 重算和原子生效，交付可打开、可追溯、可恢复的同版 Excel。

**Architecture:** 六项机械工具沿 P00 文件协议接入；Python 不拆解业务、不匹配语义、不重写估算算法。先完成一个可执行的纵向通道，再在同一通道验证合法未知与中断。

**Tech Stack:** Python 3.12、uv 0.11.7、jsonschema 4.26.0、openpyxl 3.1.5、pytest 8.4.1、LibreOffice headless。

**Spec:** [D00](../detailed/D00-technology-stack.md)、[D02](../detailed/D02-shared-data-and-evidence.md)、[D06](../detailed/D06-excel-projection-and-delivery.md)、[D07](../detailed/D07-tools-storage-and-recovery.md)、[D08](../detailed/D08-telemetry-and-performance.md)、[P00](P00-contracts-and-fixtures.md)。

## Global Constraints

- 所有代码和资产位于 Lite 插件，项目输出位于显式项目的 `.ai-sow-lite/`；不依赖 checkout cwd 或旧插件运行时。
- 迁入 D00 指定提交 `2fc8588` 的机械能力；不迁入旧业务 Schema、Owner/Reviewer 门禁、隐藏辅助列或阶段运行器。
- 原模板资产和既有表/列/公式语义保持不变；输出只填可写输入，超容量按已有原型扩行。待确认/超长内容使用独立说明文件，不新增输出 Sheet 或金额保护公式。
- 未明复杂度 M+问题；类型等真实未知留空；未拆明工作明确列为业务待确认。SIT/UAT、人天及汇总全部让原模板计算，插件不判断金额完整性或添加部分汇总。
- 每个请求的修复/重试与恢复计数执行 D04B；观测不作为预算门禁。
- 以下路径相对 Lite 插件；命令从仓库根执行。尚未实现的命令不能计作本轮验证。

## I1.1 · 最小环境、合同与可执行夹具

**Files:** 新建 pyproject.toml、uv.lock、scripts/bootstrap.sh、scripts/bootstrap.ps1、scripts/lite.py、runtime/ai_sow_lite/{__init__,contracts,cli,validation}.py；P00 的四份 D02 Schema、protocol.schema.json、artifacts.schema.json；tests/{conftest,test_contracts,test_bootstrap}.py、tests/support/{__init__,cli,fixtures}.py 及 generate/excel 夹具。`references/tools.md` 自此维护实际已实现的字段和错误码。

**Interfaces:** 消费 P00 信封、candidate 和 D02 字段；产出 execute、check_candidate、严格 JSON/摘要及 Case/run_request。I1.2 尚未完成前用 P00 的 contract_case 测校验单元，不伪造 CLI ingest 成功；未实现操作返回明确不支持，不能返回假成功。

- [x] 从 D00 来源读取 bootstrap 与对应安装测试，迁入身份/路径适配；pyproject 使用上述锁定依赖和 `runtime` 包位置，CLI 仅用 argparse 的 --request，不加入 Typer/MCP。uv 首次生成锁文件后以 --locked 验证重建；已有测试保留。
- [x] 迁入隔离环境复用和中文路径/UTF-8 的适用测试；检查 PowerShell 与 Bash 的源文件编码、子进程输入输出和 Lite 最长实际路径。旧 runtime-environment 的路径长度常量不直接沿用；仅在实际平台验证后写支持声明。不为复用旧说明加入 PDF/OCR 依赖或旧专业运行器。
- [x] 创建 EX01 合成 PRD/HLD/答复和预期义务，固定 UUID 映射；读取真实模板标准 ID。严格 JSON tests 先验证重复 key/未知版本/文本空白摘要，首次运行应因尚无实现失败。
- [x] 在合同首次可校验后、扩展完整版本保存/投影/事件聚合前，前置 I2.2 的 `three-scope` 最小候选演练和 I2.3 的受控宿主 usage 探针。隔离会话只给真实合成输入、必要指引和模板标准，不给预制 candidate/expectations；观察三类义务、默认 M、候选与依据编写/修正负担，以及请求边界和活动归属实际可得性。仅形成 work 候选及最小观测记录，不伪装未实现 CLI 或正式交付。结果归入既定 I2-generate/host-support 验证记录，I2 在真实通道接通后补其集成证据；不增加新里程碑、运行时阶段或第二套正式验收。
- [x] 实现 Schema 与跨文件检查：唯一 ID/父引用、AC 来源、分类/null/不适用、standard_id 对应、问题/决定状态、未拆明工作及空父项、依据图可达且无循环。每批输出全部诊断，不回写业务字段。resolution 精确编码为 resolved 的 decision_id/request_id/summary，superseded 的 replacement_item_ids/lineage_refs/request_id/reason；lineage_refs 使用 P00 的历史复合键。
- [x] 为以下反例参数化测试：无说明的 null；complexity=null/X；类型未知但 default M 的 standard_id=null；非集成 null；default M 与新建有值但 open；有 Task 又有未拆明工作；空父项无缺口；循环 judgment；合法空 gap 候选与无分析支持的空候选。最后一项代码只能核对分析记录存在及一致，语义充分性在 I2 演练，不能建关键词充分性规则。

```python
def test_null_complexity_is_not_a_legal_unknown(contract_case):
    import json
    from ai_sow_lite.validation import check_candidate
    case = contract_case
    candidate = json.loads(case.candidate_path.read_text(encoding="utf-8"))
    model_path = case.project / candidate["model_path"]
    model = json.loads(model_path.read_text(encoding="utf-8"))
    model["tasks"][0]["complexity"] = None
    model_path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    report = check_candidate(case.project, case.candidate_path, "full", None)
    assert report["valid_for_render"] is False
    assert any(d["target"]["field"] == "complexity" for d in report["diagnostics"])
```

check_candidate 返回报告本体，CLI 将其落盘并返回 check_ref；报告固定含 diagnostics 和 valid_for_render，与 CLI result 不混用。有效 slice 也为 valid_for_render=false。

- [x] 执行 `uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_contracts.py plugins/ai-sow-lite/tests/test_bootstrap.py -q`；失败预期转为当前可测范围全部通过后关闭此任务，其他平台执行面明确未验证。记录严格摘要向量和真实模板身份，不提交生成缓存；I1.5 再以独立副本验证完整安装/交付。

**完成证据：** I1.1 已通过 TDD 回归和独立审阅收口，完整 Lite 144项通过、1项因缺少 pwsh 跳过；真实 Agent 候选及宿主探针已记录。见 [I1 验证](../../validation/I1-reliable-delivery.md)。后续任务的完成范围以各节证据为准。

## I1.2 · 文本登记与有效版本保存

**Files:** 新建 runtime/ai_sow_lite/{inputs,project}.py、tests/{test_inputs,test_project}.py；扩展 artifacts.schema.json、cli.py 与 tests/support/fixtures.py。

**Interfaces:** 消费 initialize、ingest_sources/analysis、inspect_view、apply_prepared、recover_request 的 P00 签名；产出真实输入/依据身份、短锁提交、current/manifest 和 checkpoint。Excel 准备文件由 I1.3 提供，早期 project 单测使用内容受控的准备包，不能宣称其工作簿已通过交付检查。

- [x] 用临时本地目录测试首次 ingest、重复输入、部分失败、身份冲突和符号链接逃逸；实现逐输入拷贝后验 hash、不可变原件、严格文本解码与保留换行的 text_lines，登记分析候选及其实际来源。已有文件和读取成功结果不因另一输入失败丢失；ingest 不创建 current。
- [x] 建立 P00 checkpoint 与请求意图记录。原子写临时文件后 replace；分开源记录、业务恢复和 telemetry。没有可用计数时先 recover 一次，再明确退出，不自动归零。真正新增材料可定向读取，不重置旧探索额度。
- [x] 实现提交协议：锁外验证/准备完整目录；同文件系统；操作系统释放型锁（Unix flock、Windows msvcrt 对固定锁字节非阻塞锁定）；锁内复核意图/取消/current/摘要，再保存不可变版本和切换指针。锁争用立即 WRITE_BUSY，锁内没有 Office、模型或等待用户。

指针替换的关键代码形态如下；调用方已经持锁且目标版本完整。文件和目录刷新平台差异分别测试，不将此片段声称为断电持久性证明。

```python
import os
import uuid
from pathlib import Path
from ai_sow_lite.contracts import canonical_json_bytes

def replace_current(root: Path, pointer: dict) -> None:
    temp = root / (".current-" + str(uuid.uuid4()) + ".tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(canonical_json_bytes(pointer))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, root / "current.json")
    finally:
        temp.unlink(missing_ok=True)
```

- [x] 对完整准备后、版本目录写完后、replace 前/后、成功响应前注入进程中断。故障注入放测试 monkeypatch/子进程屏障，不暴露生产 CLI 任意 failpoint。recover 只在 current 或其有效 base_version_id 历史链找到本请求时确认已应用；孤立 versions 目录不能自动激活。加快检索的索引不能替代这项事实。
- [x] 测 generate expected_current=null 的首次成功、意外已存在 current 的拒绝、同请求重试不重导出、后续串行请求成功后的旧请求查询、取消和未知响应。只加一次短锁繁忙/过期误调用的保护测试，不设计并行改稿成功场景。已成功请求返回原 applied_version 与当前 current_version，不倒回指针；后续日志失败不改变已应用事实。
- [x] 执行 `uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_inputs.py plugins/ai-sow-lite/tests/test_project.py -q`；各平台只报告实际可测锁与 replace 结果。纯 project 单测通过还不关闭 I1，必须接 I1.3 实际包。

**完成证据：** I1.2 已通过测试先行实现及独立审阅/定点复核：聚焦71项通过，完整 Lite 215项通过、1项因缺少 PowerShell 跳过，独立副本的10次公共 CLI 验收通过。输入登记、定向查询与受控包存储事实已验证；公共 apply 仍等待 I1.3 实际工作簿核验器，I1 整体未关闭。详见 [I1 验证](../../validation/I1-reliable-delivery.md)。

## I1.3 · 模板投影、真实计算与最终复读

**Files:** 新建 runtime/ai_sow_lite/{workbook,office}.py、tests/{test_workbook,test_office}.py；扩展 cli/validation、excel 夹具；保留 assets/sow-template.xlsx 与 tests/test_template_uat.py。

**Interfaces:** 消费已完整检查的 candidate、真实模板与 expected_current；产出 render_candidate/recalculate 和 P00 prepared，接入 I1.2 apply。版本 ID 在 render 分配，投影/summary/manifest 使用同一身份。

- [x] 迁入旧 workbook 的 safe_text、Table 扩行/样式和 OOXML 检查方法，以及 office_engine 的隔离重算/身份/超时；只按方法适配，build_rows、旧模型关联、隐藏身份列、旧审阅合同不复制。保留引擎探测10秒、单次重算120秒的既有默认，超时必须清理所属进程/目录；内部没有自动二次重算。
- [x] 按 D06 §2.1 映射真实列：Story A:E 可填、F:J 公式，AC=D；Task A:G 可填、H:L 公式；标准 Q=SIT/R=UAT。校验 Sheet/Table/表头/公式原型，未知原型报 VERSION_INCOMPATIBLE。依据真实 Table 扩展公式、样式、保护、下拉、筛选、打印及跨表范围。
- [x] 生成与 Excel 同版的 pending-items.md，按需生成 details.md；既有可写备注只附问题/全文定位。输出保持四张表和原汇总/标准/参数，不增加金额完整性标签、缺值保护、部分汇总或 SIT/UAT 三态规则。结构检查合法缺值与问题一致，金额/适用性缓存由原模板产生，不据问题改变公式或输出值。
- [x] 处理 D06 稳定安全别名、120 UTF-16 单元上限、同名/大小写/Unicode、`~*?`、超长 AC/任务列表和 `=+-@` 起始文本。名称可能触发现有模板的匹配运算时采用无特殊运算字符的身份别名，原文保存在模型/details.md，不能改模板 criteria。超长内容明确引用独立全文，不写计算列或静默丢字。

```python
def write_literal(cell, value: str) -> None:
    cell.value = value
    cell.data_type = "s"

def test_literal_task_name_is_not_a_formula():
    from openpyxl import Workbook
    from ai_sow_lite.workbook import write_literal
    cell = Workbook().active["B5"]
    write_literal(cell, "=SUM(A1:A9)")
    assert cell.data_type == "s"
    assert cell.value == "=SUM(A1:A9)"
```

实际生产实现放 workbook.py，测试调用该函数；OOXML 写入后和 Office 后再次检查类型与原文本，上述内存测试不能独自证明安全交付。

- [x] 用完整分类、缺类型/方式/集成、default M、候选新建、父级未拆明工作、有行缺工作及真实空 gap 的样本核对实际输入与独立待确认一致，原模板公式/参数原值保留。0/1/60/61 Story 和200/201 Task 验证原预留区及必要扩行的关联、缓存保存与保护。Office 结果只用于证明原模板正常往返，不为缺值制定另一套应当空白/为零/完整/部分的金额期待，也不重做标准人天算法验收。
- [x] 正常调用一次 Office；最终结果用公式视图和 data_only 双复读，OOXML 检查核对原元数据和缓存保存；按 D06 §8 仅处理已验证的 LibreOffice 计算列元数据省略与整列校验范围裁剪，再只读核验并绑定最终文件，不重写单元格公式或缓存。发现自身写入错误时修正填表实现并重新生成；不修原模板公式。重算后若输入或文件内容变化必须使准备记录失效，不用旧 cache。Office 返回0但 Table/保护/缓存保存错误仍 WORKBOOK_INVALID。
- [x] 执行 `uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_workbook.py plugins/ai-sow-lite/tests/test_office.py plugins/ai-sow-lite/tests/test_template_uat.py -q`。真实 Office 测试用 `office` marker 区分；本机缺引擎可解释 skip，但 **I1 退出要求至少一个真实引擎环境无此跳过**。在 Microsoft Excel 原生打开代表性输出、保存、重开检查内容修复提示与布局，不操作用户原模板。

**完成证据：** I1.3 已通过测试先行实现、两项审阅问题的定点修复与独立复核：完整 Lite279项通过、1项因缺少 PowerShell 跳过；冻结副本30次公共 CLI 调用通过，常规/扩行/三任务边界均完成原生 Excel 打开、保存、重开。原模板与旧插件未修改；已知引擎保存差异按 D06 的窄范围处理。实际证据及 Windows 限制见 [I1 验证](../../validation/I1-reliable-delivery.md)。下一项为 I1.4，I1 整体保持未完成。

## I1.4 · 从第一个工具开始测量

**Files:** 新建 runtime/ai_sow_lite/telemetry.py、tests/test_telemetry.py、telemetry 夹具；扩展 cli 的调用边界和 artifacts.schema.json。

**Interfaces:** 消费 D08 原生事件与 observation_context；产出 append_event/build_report。report.metrics 为指标列表，每项保留 D08 的 value/unit/scope/basis/coverage/attribution；value 不可得为 null。时间用整数纳秒，token 用非负整数，不从文字长度换算。

- [x] 在 CLI execute 外层记录 monotonic_ns 的 start/end、真实 operation/attempt、状态和字节；每执行段独立时钟域，不能跨进程相减。录入失败/取消/重试成本；无 end 标 incomplete，用户等待单列。默认一次轻量收尾，记录失败不重跑业务。
- [x] 按 I1.1 已观察到的宿主能力，实现 P00 的 telemetry 模块 --mark-file 入口，供没有原生事件的纯语义大活动标记；只写观测，request end 有界生成报告。测试标记缺失/乱序、跨进程时钟和非法内容，不能把两个 UTC 观察点伪装成精确模型耗时或偷偷改变业务状态。
- [x] 先实现事件白名单落盘和重建报告，再用 EX06 事件夹具测试重复/累计/乱序、epoch、父子重叠、跨活动共享和晚到。源原生身份缺失不造 host_call_id；累计未知起点不能当本请求总量。

```python
def test_empty_usage_is_unknown(tmp_path):
    from ai_sow_lite.telemetry import build_report
    report = build_report(tmp_path, "00000000-0000-4000-8000-000000000001")
    tokens = next(m for m in report["metrics"] if m["name"] == "total_tokens")
    assert tokens["value"] is None
    assert tokens["coverage"] == "unknown"
```

- [x] 一个写者一条 JSONL；先保存事件再推进游标，重放去重。尾行中断与中间损坏不同诊断；迟到仅刷新 report，断言版本目录/current 字节完全不变。测日志盘满/源版本变化，业务成功仍成功，报告说明缺口。
- [x] 执行 `uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_telemetry.py -q`。此处只证明工具计时/事件算法；真实宿主 usage 在 I2 接入，不能由合成事件宣称逐步 token 已采集。

I1.4 已完成工具计时、纯语义标记及规范化事件报告；TDD、独立审阅和定点返修复核通过。修复前完整 Lite340项通过、1项因 PowerShell 缺失跳过；最终统计/报告返修后相关196项通过，新副本公共入口与迟到事件验收通过。原模板、旧插件及 Office 实现未改，真实宿主 usage 仍由 I2.3 验证。完整证据及快照范围见 [I1 验证](../../validation/I1-reliable-delivery.md)。下一项为 I1.5，I1 整体保持未完成。

## I1.5 · 独立副本的完整交付与失败验收

**Files:** 新建 tests/support/smoke_plugin.py、docs/validation/I1-delivery.md；更新 references/tools.md、CHANGELOG.md 与 D09 证据状态。

**Interfaces:** 消费 I1.1—I1.4 的真实 CLI、文件及事件；产出独立复制验收结果、可读 Excel 与 I2 可用基线。smoke 支持 `--copy-plugin`，仅复制插件到临时目录，另建普通本地项目；测试结束清理自身工件，失败可保留明确路径供定位。

- [x] 在 tests/support/fixtures.py 增加 `prepare_case(case) -> dict`：run_request(check full) → 取 check_ref.path → run_request(render expected_current=null) → 返回 render.result。它复用 P00 Case，不直接写 prepared 成功标志。
- [x] 用真实 ingest 的 Case 接 prepare_case，再 apply 和 recover；在已经 apply 后重复 apply，验证没有新增版本或重算，返回相同已应用身份。

```python
def test_first_delivery_and_retry(case):
    from tests.support.cli import run_request
    from tests.support.fixtures import prepare_case
    prepared = prepare_case(case)
    payload = {"entrypoint": "generate", "prepared_path": prepared["prepared_ref"]["path"],
               "expected_current": None, "plan_path": None}
    first = run_request(case.project, case.request_id, "apply", payload)
    again = run_request(case.project, case.request_id, "apply", payload)
    assert first["ok"] and again["ok"]
    assert again["result"]["idempotent"] is True
    assert first["result"]["applied_version"] == again["result"]["applied_version"]
```

- [x] 使用同一真实包重跑 I1.2 的生效点故障，避免只证明假 workbook 的事务；核对首版实际采用的全部原件/分析/模板依赖；观察附件在 I4.1、已应用业务历史链在 I3.3 接真实包验证，不伪造当前尚未支持的工件。扫描复制运行的读取范围，不能打开旧插件或仓库根运行文件。
- [x] 执行 `uv sync --project plugins/ai-sow-lite --locked`、`uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests -q`、`uv run --project plugins/ai-sow-lite --locked python plugins/ai-sow-lite/tests/support/smoke_plugin.py --copy-plugin`，以及根指南要求的检查。记录原生打开和模板 hash 不变的证据。

**I1 退出：** 合成模型正确填写原模板，公式和结构保留，待确认/长内容与 Excel 同版可读；current 始终指向完整文件包，独立副本运行，工具耗时与 usage 缺口可见。不以金额完整性判交付，也不宣称已证明真实 generate 语义能力或提速；通过后进入 P02。

**完成证据：** 完整 Lite370项通过、1项因缺少 PowerShell 跳过；独立副本使用自己的锁定环境，真实交付/重复/恢复成功，31份审计收据未发现越界、一次 Office 转换。五个生效点中断及14项依赖损坏检查通过，独立审查无阻断项；审计收据逐进程对账的加固按 AD09 归入 I3.3。见 [I1.5 验证](../../validation/I1-delivery.md)。I1 可靠程序通道已完成，接 P02 的 I2.1；真实 Agent 生成与宿主 usage 不在 I1 完成声明内。
