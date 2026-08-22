---
name: generate-sow
description: 当六份已评审的 AI SOW 稳定交接文件全部有效，并需要生成可离线评审、审计、估算或签署的权威 XLSX 交付包时使用。
---

# 生成 SOW 工作簿

将已批准数据确定性地投影到项目模板。本 Skill 只拥有 `.ai-sow/outputs/` 及其暂存目录。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。模板和 machine token 保持原值；已评审自由文本按原文投影。

## 路径

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。保持项目根目录为当前工作目录，并在执行前把命令中的路径占位符替换为绝对路径。

## 输入与联合视图

读取项目元数据、项目模板和六份稳定数据：

- `.ai-sow/data/analyze-requirement/requirements.json`
- `.ai-sow/data/analyze-as-is/asis.json`
- `.ai-sow/data/generate-design/design.json`
- `.ai-sow/data/generate-design/requirements.json`
- `.ai-sow/data/generate-story/delivery.json`
- `.ai-sow/data/generate-task/estimate.json`

同时读取设计批准合同 `.ai-sow/reviews/generate-design.md`。它不成为第七份稳定 JSON，也不进入 manifest 的六输入集合，但 HLD Coverage、Go-live Assessment 和固定十项上线矩阵必须全部通过，最终生成才能继续。

仅在内存中联合 BUSINESS 与 TECHNICAL requirements，保持各自顺序和所有权，不生成或打包第三份合并 JSON。

## 运行

在项目根目录运行：

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/generate_sow.py" --project-root .
```

脚本验证投影所需字段、引用和覆盖；接入复用 Task 的项目侧工作类型、标准正向交付承诺和工作模式理由必须严格互相匹配，不从自由文本猜测责任边界。验证通过后写入：

- `01-需求`：EPIC；
- `02-子需求`：FEATURE；
- `03-SOW主表`：STORY；
- `04-验收条件`：AC；
- `05-任务明细`：TASK；
- `06-集成点`：INTEGRATION，以顶级 `integrations` 为权威；
- `07-假设清单`：ASSUMPTION/RISK，每个顶级实体一行并投影 Story 关系；
- `90-系统现状`：ASIS。

选填字段缺失时对应单元格合法留空。Task 明细逐行投影原子工作；公式仅来自模板，插件不执行公式或维护并行人天模型。

生成前脚本会从项目模板的单张配置表复读 37 项基础单元、13 个任务族及三个工作模式人天列，并从项目参数复读状态为固定规则、已校准或已批准的 S/M/L 系数，然后防御性复核 Task 的工作模式、结构化 `workModeEvidence`、调整资产、可估算复用工作、S/L 复杂度理由、Integration 一对一关系、每 Story 一个发布切换实例，以及问题诊断与根因整改不重叠。任何门禁失败或 `affectsEstimate = true` 的未关闭 Uncertainty 都会阻止生成；该结构化标志是唯一不确定性门禁依据，不从 `impact` 自由文本猜测。Story 不保存类型；Task 不保存任务族、活动、数量、基础人天、倍率或人天。Task 表由公式带出任务族并计算人天；Integration 表从关联的集成 Task 带出工作模式和复杂度，由此触发 SIT。UAT 只读取 Story 的 `uatRelevant`。

## 完成条件

成功结果是新的 UUID 输出目录，包含 `sow.xlsx`、`manifest.json` 和六份稳定输入副本。输出完成复读并通过跨文件引用检查后才从唯一 staging 目录发布；失败时保留 staging 路径和简明诊断。脚本不读取其他 Skill 的 schema、fixture、test、asset 或 script，也不修改任何输入。
