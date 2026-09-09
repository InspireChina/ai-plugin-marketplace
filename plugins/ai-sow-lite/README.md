# AI SOW Lite

AI SOW Lite 根据 PRD、HLD 和旧项目的往期 SOW，生成本期首版 SOW Excel、摘要与待确认事项。专业分析和联合拆解由一个主 session 完成，插件工具负责可追溯读取、机械检查、模板投影、真实 Office 核验和版本保存。

当前是 `0.1.0-alpha.1` 开发插件（Python 版本 `0.1.0a1`），提供 [generate](skills/generate/SKILL.md) 和 [clarify](skills/clarify/SKILL.md) 两个入口。两宿主 manifest 共用这些 Skill，供独立副本开发验证；尚未注册到仓库 marketplace，不表示已经公开发布。当前范围与实际证据见 [I2 生成验证](docs/validation/I2-generate.md)、[I1 交付验证](docs/validation/I1-delivery.md) 和 [宿主支持记录](docs/validation/host-support.md)；入口和文本合同通过不代表真实语义场景通过。

## 使用

在已加载开发插件副本的会话中，可直接说：

```text
这是新项目。请用给定 PRD 和 HLD 生成本期 SOW。
迁移的本期责任在材料中有待确认，我会回答输入相关问题。
请把需要后续确认的事项随 Excel 一起给出。
```

提供实际 PRD/HLD 路径；旧项目另外提供往期 SOW。材料已齐时直接分析，只有输入事实、冲突或责任影响推进时才合批提问。基础充分后的局部未知随初稿交付，复杂度不明立即用 M 并附待确认；基础材料不足则给具体补料清单。生成初稿不要求审批。

当前可读取 UTF-8 `.md/.markdown/.txt` 和 `.xlsx`，保留物理定位、附注和未读范围；不支持 PDF/DOCX/OCR。原型可选，其观察与附件校验仍未实现，不宣称已验证。Clarify 基于共享项目文件讨论具体修改，只更新已确认的有限范围；当前验证边界见 [I3 修改验证](docs/validation/I3-clarify.md)。重复 generate 恢复已有结果，不覆盖有效版本。

查看 Excel 后，可以使用 clarify 回答某条待确认事项，或提出自己的修改意见，例如：“资料迁移复杂度按 S，先展示具体调整方案。”无需原生成聊天，也没有定稿环节。首次接受默认 M 会记录决定并处理对应问题；已经采用的重复答复直接返回现有文件。讨论时默认展示内容变化，只有明确要求候选 Excel 才提前生成预览。

运行时、锁文件和模板均在插件目录内。首次调用按 [命令与编写参考](references/generate-authoring.md) 使用本副本 bootstrap，准备隔离 uv/Python/依赖，后续复用 `.venv`；不需要安装旧 AI SOW 插件。Excel 投影使用已有 LibreOffice 引擎，缺少引擎时保留候选并返回诊断，不伪造计算结果。平台实测范围以宿主支持记录为准。

Python 安装不写用户 bin 或注册表，只使用本插件副本的 managed Python。已有 `.venv` 的基础解释器指向其他副本或已失效时，bootstrap 会重建本插件的 `.venv` 并同步锁定依赖；正常环境直接复用。

`.venv`、`.ai-sow-tools` 及其 `bin`、`cache`、`python` 根目录必须是本副本的真实目录；若为符号链接或 Windows 重解析点（包括悬空链接/junction），bootstrap 在任何目录创建、安装或环境重建前返回 `BOOTSTRAP_PATH_UNSAFE`，保留链接和外部目标。`python` 内部的 managed 版本别名不受此限制。

交付保存在项目 `.ai-sow-lite/versions/<version_id>/`，含 `sow.xlsx`、`summary.md`、`pending-items.md` 和同版 JSON；必要时另有 `details.md`。`.ai-sow-lite/work/` 保留未完成分析和可恢复候选。输入、工作文件和工作簿可能含客户衍生资料，共享或提交前按项目隐私要求检查；不要把它们复制进插件包。

工具耗时和大活动标记保存在项目的独立资源报告中。原生 token 采集只接已验证版本、明确选定且属于本次请求的来源；无法确定的调用次数或活动归属保留未知，不按文件大小估算 token，也不设置 token 预算门禁。观测失败不重做业务交付，迟到用量只更新资源报告。当前真实粒度与性能基线见 [宿主观测](docs/validation/host-support.md) 和 [I2 验证](docs/validation/I2-generate.md)。

## 开发

从仓库根目录运行定向合同检查：

```sh
uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests/test_skill_contracts.py plugins/ai-sow-lite/tests/test_contracts.py -q
```

开发验证使用独立插件副本，不修改日常宿主的插件安装或设置。真实语义演练的运行副本排除 tests/fixtures 和设计答案，只提供选定原始输入；期待和按需答复留在评估侧。测试结果、平台限制和剩余工作记录在上述验证文档中。

专业方法见 [输入分析](references/input-analysis.md) 和 [联合生成](references/generate-slices.md)，机械接口见 [工具合同](references/tools.md)。设计与实施范围见 [设计目录](docs/design/README.md)；设计文档不作为生成时的运行依赖。
