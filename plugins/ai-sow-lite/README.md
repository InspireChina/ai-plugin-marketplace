# AI SOW Lite

AI SOW Lite 根据 PRD、HLD 和旧项目的往期 SOW，生成本期首版 SOW Excel、摘要与待确认事项。专业分析和联合拆解由一个主 session 完成，插件工具负责可追溯读取、机械检查、模板投影、真实 Office 核验和版本保存。

当前是 `0.1.0-alpha.1` 开发插件（Python 版本 `0.1.0a1`），提供 [generate](skills/generate/SKILL.md) 和 [clarify](skills/clarify/SKILL.md) 两个入口。两宿主 manifest 共用这些 Skill，仓库双 marketplace 已包含预发布条目；尚未公开发布或安装到日常宿主。当前范围与实际证据见[I4 交付汇总](docs/validation/I4-delivery.md)、 [I2 生成验证](docs/validation/I2-generate.md)、[I1 交付验证](docs/validation/I1-delivery.md) 和 [宿主支持记录](docs/validation/host-support.md)；入口和文本合同通过不代表真实语义场景通过。

## 使用

在已加载开发插件副本的会话中，可直接说：

```text
这是新项目。请用给定 PRD 和 HLD 生成本期 SOW。
迁移的本期责任在材料中有待确认，我会回答输入相关问题。
请把需要后续确认的事项随 Excel 一起给出。
```

提供实际 PRD/HLD 路径；旧项目另外提供往期 SOW。材料已齐时直接分析，只有输入事实、冲突或责任影响推进时才合批提问。基础充分后的局部未知随初稿交付，复杂度不明立即用 M 并附待确认；基础材料不足则给具体补料清单。生成初稿不要求审批。

当前可读取 UTF-8 `.md/.markdown/.txt`、`.xlsx` 和显式原型目录包，保留物理定位、附注和未读范围；不支持 PDF/DOCX/OCR。原型可选，宿主Agent自主选择有限观察目标，工具保留资源、实际观察及附件并核对来源；不能运行时保留具体限制，详见 [原型输入](references/prototype-inputs.md)。Clarify 基于共享项目文件讨论具体修改，只更新已确认的有限范围；当前验证边界见 [I3 修改验证](docs/validation/I3-clarify.md)。重复 generate 恢复已有结果，不覆盖有效版本。

查看 Excel 后，可以使用 clarify 回答某条待确认事项，或提出自己的修改意见，例如：“资料迁移复杂度按 S，先展示具体调整方案。”无需原生成聊天，也没有定稿环节。首次接受默认 M 会记录决定并处理对应问题；已经采用的重复答复直接返回现有文件。讨论时默认展示内容变化，只有明确要求候选 Excel 才提前生成预览。

同一个人按现版串行修改，历史版本保留。中断后先查询实际结果；已经成功的旧请求返回其原成功事实，同时保留最新current。旧草稿遇到基线变化会停止应用，确认原件和已采用来源随版本校验。完整使用周期及可观察取消边界见 [I3验证](docs/validation/I3-clarify.md)。

运行时、锁文件和模板均在插件目录内。首次调用按 [命令与编写参考](references/generate-authoring.md) 使用本副本 bootstrap，准备隔离 uv/Python/依赖，后续复用 `.venv`，可用 [Python 调用助手](references/python-client.md) 连续执行 Agent 已选择的机械操作；不需要安装旧 AI SOW 插件。Excel 投影使用已有 LibreOffice 引擎，缺少引擎时保留候选并返回诊断，不伪造计算结果。平台实测范围以宿主支持记录为准。

Python 安装不写用户 bin 或注册表，只使用本插件副本的 managed Python。已有 `.venv` 的基础解释器指向其他副本或已失效时，bootstrap 会重建本插件的 `.venv` 并同步锁定依赖；正常环境直接复用。

`.venv`、`.ai-sow-tools` 及其 `bin`、`cache`、`python` 根目录必须是本副本的真实目录；若为符号链接或 Windows 重解析点（包括悬空链接/junction），bootstrap 在任何目录创建、安装或环境重建前返回 `BOOTSTRAP_PATH_UNSAFE`，保留链接和外部目标。`python` 内部的 managed 版本别名不受此限制。

交付保存在项目 `.ai-sow-lite/versions/<version_id>/`，含 `sow.xlsx`、`summary.md`、`pending-items.md` 和同版 JSON。`.ai-sow-lite/work/` 保留未完成分析和可恢复候选。输入、工作文件和工作簿可能含客户衍生资料，共享或提交前按项目隐私要求检查；不要把它们复制进插件包。

Excel 只保留原四张表，完整验收条件直接放在“验收条件”列。Story 备注通常为空，仅补充输入或用户已确认且 AC 未表达的必要范围、责任和外部前提说明。Task 备注列出非新建工作方式、非 M 复杂度的判断原因。尚未解决的问题与当前处理写在实际受影响的行上，以“待确认：”开头，校验列显示“待确认”；只有已确认说明或判断原因不会变成待确认。Task 问题不自动上卷到 Story；内容与来源规则见 [备注与问题的目标](references/generate-slices.md#备注与问题的目标)。已解决或已被替代的问题留在项目历史中。尚未拆明且没有 Story 的范围保留实际 Epic/Feature 与问题，不虚构工作。Excel 可单独阅读和分享。

既有项目可以继续使用，仍需保留项目文件供后续 clarify 定位和修改。具体兼容规则、长内容限制见 [Excel 投影合同](docs/design/detailed/D06-excel-projection-and-delivery.md)，验证进展与限制见 [原列验收记录](docs/validation/I6-inline-acceptance.md) 和 [Task 判断原因](docs/validation/I6-task-note-reasons.md)。

工具耗时和大活动标记保存在项目的独立资源报告中。原生 token 采集只接已验证版本、明确选定且属于本次请求的来源；无法确定的调用次数或活动归属保留未知，不按文件大小估算 token，也不设置 token 预算门禁。观测失败不重做业务交付，迟到用量只更新资源报告。当前真实粒度与性能基线见 [宿主观测](docs/validation/host-support.md) 和 [性能记录](docs/validation/performance.md)。

## 当前交付范围

完整生成与有限修改已有真实输入、Office及文件续接证据；性能仍是明确限制。此前典型/长例Generate约13分钟，局部改稿方案约5—9分钟，见[性能记录](docs/validation/performance.md)。最新[Greenfield → Brownfield 串联实测](docs/validation/E2E-greenfield-brownfield.md)完成两期生成、方案修订、部分采纳和重复答复：29项检查中26通过、2失败、1部分通过，保留已采用M的问题闭合和长AC可见性缺陷。该案例两次Generate约22.5/16.9分钟、两次Clarify约12.4/9.4分钟，均为原生处理时间，不含全部用户等待；逐活动token仍未知，没有速度SLA或相对旧版提速比例。

追加评审发现 AC 还混入实现方法及多个验收结果，原 26/29 不能作为 AC 质量达标的结论。[修复与优化方案](docs/design/14-e2e-remediation-and-optimization.md)将 AC 语义放在首位，后续按 [I7.1—I7.6](docs/design/implementation/P05-quality-and-performance.md) 分阶段处理问题闭合、可读性、观测和同质量性能；当前只有方案，尚未实施修复。

声明范围以[宿主支持](docs/validation/host-support.md)为准：当前实际业务验证基于macOS本地目录及Codex桌面显式加载副本；Claude认证失败，Windows/Linux和同步/网络盘未验证。仓库双marketplace目录已准备预发布安装入口，本次未执行宿主安装。复制包本身不依赖仓库README或其他插件。

## 开发

从仓库根目录运行定向合同检查：

```sh
uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_skill_contracts.py plugins/ai-sow-lite/tests/test_contracts.py -q
```

完整开发检查：

```sh
uv sync --project plugins/ai-sow-lite --locked
uv run --project plugins/ai-sow-lite --locked pytest -c plugins/ai-sow-lite/pyproject.toml plugins/ai-sow-lite/tests -q
uv run --project plugins/ai-sow-lite --locked python plugins/ai-sow-lite/tests/support/check_scenario_coverage.py --ledger docs/validation/scenario-coverage.json
```

完整测试包含真实Office独立复制消费者；不可用引擎/平台的跳过不能当作平台验收。场景脚本检查163条编号、主责、引用和状态，不评判语义正确率。

开发验证使用独立插件副本，不修改日常宿主的插件安装或设置。真实语义演练的运行副本排除 tests/fixtures 和设计答案，只提供选定原始输入；期待和按需答复留在评估侧。测试结果、平台限制和剩余工作记录在上述验证文档中。

专业方法见 [输入分析](references/input-analysis.md) 和 [联合生成](references/generate-slices.md)，机械接口见 [工具合同](references/tools.md)。设计与实施范围见 [设计目录](docs/design/README.md)；设计文档不作为生成时的运行依赖。
