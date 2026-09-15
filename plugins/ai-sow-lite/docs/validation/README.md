# 验证摘要

面向 `0.1.0-alpha.2`，Windows 兼容与可靠性基线为 `8f05418`，合并提交为 `16df55e`。这是验证入口，不是插件运行步骤。安装、生成、局部改稿和 Excel 已有实际证据；最终发布提交、发布前回归与远端安装结果统一记录在 [GitHub Release](https://github.com/InspireChina/ai-plugin-marketplace/releases/tag/ai-sow-lite-v0.1.0-alpha.2)。首个 Alpha 的业务与文档基线分别为 `08f01ef`、`d5cde4f`，历史结果保持原执行归属。

## Windows 兼容与 macOS 回归

2026-09-15，PR #10 的同一运行时提交 `8f05418` 完成两端验收，合并后的文件树相同：

| 环境 | Lite 完整套件 | 证据与边界 |
|---|---|---|
| Windows 11、Python 3.12.13、PowerShell 7.6.5、LibreOffice 26.8.0.3 | 846 通过、86 条件跳过，0 失败/错误 | [Windows 实机报告](https://github.com/InspireChina/ai-plugin-marketplace/pull/10#issuecomment-5677442113)；跳过为 POSIX 原型目录、符号链接权限及 Bash 分支，PowerShell 和真实 Office 已执行 |
| macOS 26.5.2 arm64、Python 3.12.13、uv 0.11.7、LibreOffice 26.8.0.3 | 920 通过、12 条件跳过，0 失败/错误 | [macOS 复验](https://github.com/InspireChina/ai-plugin-marketplace/pull/10#issuecomment-5677709075)；12 项均因未安装 PowerShell，真实 Office 独立副本生成与改稿已执行 |

两端根测试、仓库验证器和 163 条场景台账结构检查通过；macOS 的旧 AI SOW 全量为 539 通过、4 条件跳过，独立复制 smoke 通过。原有 6 项缺陷复现在 macOS 均通过。本次是脚本与合成消费者验证，不扩大模型业务质量或性能承诺。

`alpha.2` 的发布收尾只同步版本元数据、校验测试和文档，不修改上述已验收的运行时、启动脚本、Skill、模板或业务合同。发布提交的本机回归与远端安装检查记录于本版本 Release，Windows 验证沿用上述实机证据。

## 验证结果与边界

| 能力 | 已有结果 | 证据与限制 |
|---|---|---|
| 独立安装与入口 | 本地 marketplace 安装、首次依赖准备、原生发现两个 Skill，并完成 generate → clarify | [安装联合验证](../archive/validation/I9-release-smoke.md)；基于 macOS 和已记录宿主版本。远端安装结果单独记录在上述 Release，不将本地证据等同于远端验证 |
| 首稿生成 | 已覆盖业务、技术、交付三类范围，以及公共单计、未知 M 和输入澄清 | [Generate 验证](../archive/validation/I2-generate.md)、[两期串联](../archive/validation/I7-final-e2e.md)；保留首跑错误和局部修正，不承诺首稿免 review |
| 局部修改 | 明确采用 M、部分答复、重复意见、新会话续接及历史版本保护已有实测 | [Clarify 验证](../archive/validation/I3-clarify.md)、[安装后改稿](../archive/validation/I9-release-smoke.md) |
| Excel | 四张原表、完整 AC 原列交付、目标行备注及模板公式；真实 Office 重算、结构与缓存复读 | [四表交付](../archive/validation/I6-inline-acceptance.md)、[Task 判断原因](../archive/validation/I6-task-note-reasons.md)、[近期定向验证](../archive/validation/I10-reference-gaps-and-skills.md) |
| 待确认的估算相关性 | 独立消费者验证：无估算影响的细目不追问，真实范围/责任问题保留，M 问题不自动关闭 | [最新语义验证](../archive/validation/I11-estimation-relevance.md)；有限案例不代表所有新稿都会准确判断 |
| 故障与恢复 | 输入读取、版本保存、Office 故障、有限重试及串行续接的实际与机械验证 | [可靠交付](../archive/validation/I1-reliable-delivery.md)、[输入与复杂修改](../archive/validation/I4-inputs-and-changes.md) |
| 耗时与 token | 工具耗时、大活动标记及特定原生来源的响应计量已有证据 | [宿主记录](../archive/validation/host-support.md)、[成本记录](../archive/validation/I10-reference-gaps-and-skills.md#耗时与-token)；性能未达标，逐活动精确归属未完成 |

当前规则只记录影响估算的未知。早期 I9/I10 曾把规范明细完整性作为问题标准，已经被 I11 收窄；原始结果保留在档案中，不再要求为出稿补齐不影响估算的开发规范。

## 最新 Excel 局部预览

2026-09-11，基于已有五个 Story、七个 Task 的合成项目，通过当前 clarify 工具生成修改后预览：撤销查询规则与字段映射两组无估算影响的追问，保留迁移记录数量未知、复杂度暂用 M 的问题。

- 五个 Story 行的备注移除相关问题；既有范围和责任说明保留，校验结果由“待确认”变为“通过”。
- 迁移 Task 的 M、问题正文和“待确认”状态保持；全部 Story/AC/Task 及原模型字节不变。
- 四张表、1,304 个公式表达式和单元格样式保持；工作量及汇总缓存结果相同。差异仅为五格 Story 备注和五格校验缓存。
- 原有效版本和原 Excel 哈希保持。该文件是用户要求的预览，未切换项目 current；用户已看过并认可显示效果。
- 本次采用真实 Office 导出与独立复读，静态渲染仅核对文本列布局；没有新增原生 Excel 全表检查或完整 generate/安装实跑。渲染器不能正确复现部分公式，不用其计算结果证明 Excel 正确性。

预览工作簿 SHA-256：`59a3f69140d5bdf38c418d725178fa458710a0d3c367825df7e0e82b60d60b93`。合成项目、Excel 和临时验证脚本留本地，不作为插件资产发布；此处不声明最新一轮端到端耗时或 token 改善。

## 自动检查与覆盖解释

首个 Alpha 的产品基线回归记录为 Lite **888 通过、12 条件跳过**；根测试 52 项、旧插件回归 388 通过/4 条件跳过及独立复制 smoke 通过，详情见 [I11](../archive/validation/I11-estimation-relevance.md)。这些数字保留其原执行归属，不当作每次文档整理新跑的结果。

2026-09-11 发布文档整理后重新执行：Lite **888 通过、12 条件跳过**（692.05 秒），旧插件整个目录 **539 通过、4 条件跳过**（53.28 秒），根测试 **52 项通过**（4.657 秒），独立复制 smoke 成功。两插件锁定依赖同步、仓库验证器、场景台账及 diff 检查通过；809 条相对文档链接有效，12 份原始指标 JSON 保持原字节。导航/合同与场景的定向检查另有 41 项通过；本次没有调用模型重跑业务 E2E，也没有扩大平台支持。

[场景台账](scenario-coverage.json) 共 163 条，区分直接验证、机制覆盖和条件实验；台账结构通过不是 163 次语义验收。后续修改先验证受影响行为，再按 [开发维护](../development.md) 完成所需回归。

平台、输入、性能及长文本限制统一见 [支持说明](../support.md)。开发原始证据通过 [档案目录](../archive/README.md) 查阅。
