# I1.5 独立副本交付验收

本项基于 `e05ebe0` 的 I1.1—I1.4，实现可重复执行的独立插件复制验收。范围限于测试支持、
集成测试及说明；不修改运行时、合同、原模板或旧插件。业务内容来自 P00 合成 Case，材料登记、
完整检查、Office 重算、应用和恢复均执行真实公共 CLI，不自填 prepared 成功标志。

## 可重复入口

从仓库根执行：

```text
uv sync --project plugins/ai-sow-lite --locked
uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_delivery.py -q
uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests -q
uv run --project plugins/ai-sow-lite --locked python plugins/ai-sow-lite/tests/support/smoke_plugin.py --copy-plugin
```

[`prepare_case(case)`](../../tests/support/fixtures.py) 接收已有 Case，只执行 full check → 从实际
check_ref 取路径 → render(expected_current=null)，返回 render.result。
[`smoke_plugin.py`](../../tests/support/smoke_plugin.py) 复制插件时排除环境与缓存，在副本创建锁定
`.venv`，另建带中文和空格的普通本地项目，并从不同 cwd 执行。成功输出 JSON 验收摘要并删除
自身临时工作区；失败输出明确 retained_path。uv 锁、请求文件及 Office 临时目录均纳入自身范围。
该开发验收要求可用的 uv 和 LibreOffice；缺少引擎返回失败，不伪造 Office 成功。

## 已实现的断言

- 首次应用与两种重复应用（准备包仍在、准备目录已移除）返回相同已应用身份；版本文件字节及
  current 不变，不产生新版本。复制运行的 Python 子进程启动审计确认只有一次 Office 转换。
- 已交付包的模型、问题、决定、投影、Excel、摘要、可读问题、details、核验记录和输入快照逐项
  复读，所有文件摘要匹配 manifest。默认 M 与 open 问题、真实未知留空、全文入口同版存在；
  四张 Sheet、五个 Table、保护、实际公式和缓存均可读取，不用金额完整性判断交付。
- 直接从登记原件、reading/摘录和 topic/登记来源枚举所需依赖，与 manifest 的完整集合比较：
  项目身份1、原件3、读取记录及摘录6、分析2、模板1，共13项；没有可变 work/index 依赖。
- 同一真实 prepared 包复制后分别在准备完成、版本安装完成、current 替换前、替换后和返回响应
  前终止真实子进程。前三处 recover=draft，后两处 recover=applied；锁释放，重试只应用或复用
  原 version_id。测试只在子进程给既有存储函数加确定性屏障，公共 apply 和实际核验器均执行。
- 项目身份、原件、reading、摘录、topic、登记来源、模板七类依赖分别删除或损坏，14种情况下
  recover 均拒绝报告有效交付，保留原 current 字节。
- 真实工具耗时大于零；没有宿主 usage 时 token 保持 null/unknown。查询和重复调用不改变版本包。

AD06 明确本项只验当前首版 Generate 可达的已支持依赖。观察附件登记尚未实现，由 I4.1 验收；
前序业务版本链的真实交付验收属于 I3.3。本样本 observations 与历史引用均为空，不以空集合
通过冒称这两项能力已实现，后续责任仍保留在全局计划。

## 读取边界和证据限制

复制 worker 与各 CLI 子进程在业务模块加载前安装 Python open 审计，按复制插件、显式项目、
受管 Python、临时文件、选定 Office 可执行文件及标准库系统 MIME 配置分类。路径先 resolve，
越界读取被拒绝并使验收失败；外部文件及经符号链接越界的反例单独覆盖。成功报告只含计数，
不保存客户正文或本机读取路径。此证据覆盖 Python open 事件，不是 OS 沙箱，不覆盖解释器启动
前读取、扩展模块内部系统调用或原生 Office 的文件读取；不宣称全系统文件追踪。

原生 Excel 证据沿用 [I1.3 记录](I1-reliable-delivery.md)：
`a47346e` 中常规、61 Story/201 Task 扩行与三任务中等列表，使用 Microsoft Excel 16.112.3
实际打开、保存 QA 副本、关闭、重开且无修复提示；输入、公式/数组范围、保护和 Table 复核通过。
本项投影器、Office 代码、模板和布局夹具均未改，因此没有再次操作桌面 Excel。

模板 SHA256 保持 `6abc55d44bc66476a60c2251e18c0dfdb66709e07539c246dfdec3a0373f5332`。
过程终止只能证明当前 Mac 普通本地文件系统的应用级一致性，不等于断电持久性；Windows、
Linux、同步盘和网络盘没有在本项实跑。不宣称真实 Generate 专业语义、宿主 usage 或提速已验收。

## 实测结果

本项在 macOS 普通本地目录完成以下验证，所有执行输入在最终运行期间保持原字节：

| 验证 | 实际结果 |
|---|---|
| 锁定环境同步 | `uv sync --project plugins/ai-sow-lite --locked` 退出0 |
| 首片 TDD | prepare_case 缺失：1 failed → 真实交付链1 passed（10.07s） |
| 复制入口 TDD | smoke 脚本缺失时1 failed；首次完整集成21 passed、1 failed（62.34s），失败为 uv 临时锁未清理；修复后原断言1 passed、21 deselected（14.40s） |
| 最终 Lite 全量 | **370 passed、1 skipped（330.77s）**，包含全部22项新增交付测试；唯一跳过为缺少 PowerShell |
| 最终 standalone copy smoke | **ok=true、copied=true、locked_environment=true、cleaned=true**；真实 LibreOffice 26.8.0.3，转换3,664ms；13项完整依赖、1个 open 问题及同版 details |
| 复制读取与重算 | 31个 Python 进程；复制插件14,755次、显式项目1,358次读取，越界0；Office 转换恰好1次 |
| 观测边界 | 工具耗时合计6,892,529,959ns，total_tokens=null；仅本机单次观察，不作提速比较 |

实施期间曾出现测试审计拒绝标准库 MIME 配置，以及验收脚本漏列项目身份依赖、误写原模板
Sheet/Table 期望的失败，均依据实际合同修正并保留失败记录；不当作运行时缺陷或已通过证据。
uv 临时锁清理则由真实失败断言驱动修复，原断言保留。最终全部40份执行输入摘要复核不变，
其中37份未修改的执行输入与 `e05ebe0` 一致；独立任务审查与全局验收由 Controller 单独记录。

## 独立审查与增量结论

I1.5 独立审查 Spec 通过、Quality Approved，无 Critical/Important。审查保留一项非阻断 Minor：当前汇总实际审计收据及数量门槛，未逐 CLI 进程对账；没有发现本次实际漏审。按 [AD09](implementation-decisions.md) 在 I3.3 扩展使用周期时补收据与 stderr 完整性检查。本项只声明实际收到31份收据及其零越界结果，不扩大为全系统追踪。

仓库根42项测试、验证器以及旧插件539项通过/4项跳过、旧插件独立复制 setup/generate 已通过。代码/测试与已验证冻结输入一致，原模板、旧插件和投影/Office 实现未改。I1 已达到可靠程序交付退出条件，下一任务为 I2.1。
