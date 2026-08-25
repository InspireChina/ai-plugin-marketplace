---
name: generate-sow
description: 当五位 Owner 的 0.3 收据、六份稳定 JSON、五份批准评审和项目模板均有效，并需要生成可离线评审、审计、估算或签署的确定性 XLSX 交付包时使用。
---

# 生成 SOW 工作簿

把已批准的稳定交接数据投影到项目模板。此 Skill 只写 `.ai-sow/outputs/`，不修改任何 Owner 输入，也不替用户重新决定需求、现状、设计、Story 或 Task。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。自由文本保持简体中文；machine token、字段、枚举、ID、路径、hash、Sheet、Table 和公式保持合同原值。

## 路径与执行边界

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。项目根目录保持为当前工作目录，命令中的占位符必须替换为绝对路径。

当前 Stage Agent 是本 Skill 的唯一用户接口，直接运行确定性生成器并原样报告结构化结果；不派发
叶子 Agent。生成器本身承担 receipt matcher、投影、工作簿复读、manifest 校验和原子发布，不调用
其他 Skill 的 validator。普通生成不产生新的专业判断；可见布局的额外人工检查属于发布认证或用户
显式要求，不是每次生成的默认门禁。

## 固定输入

生成前必须存在并逐字节匹配五位 Owner 的 validator contract `0.3` 收据：

- `.ai-sow/validation/analyze-requirement.json`
- `.ai-sow/validation/analyze-as-is.json`
- `.ai-sow/validation/generate-design.json`
- `.ai-sow/validation/generate-story.json`
- `.ai-sow/validation/generate-task.json`

收据分别绑定五份批准评审、六份稳定 JSON 及各 Owner 的直接输入。生成器通过公共 handoff matcher 重建预期 input 并检查当前 review/output 字节；只报告 missing、invalid、stale、unsupported，不重放上游业务规则、HLD/Go-live、Uncertainty、AC→Task、工作模式、复杂度或 Integration 语义。

投影输入固定为：

- `.ai-sow/data/analyze-requirement/requirements.json`
- `.ai-sow/data/analyze-as-is/asis.json`
- `.ai-sow/data/generate-design/design.json`
- `.ai-sow/data/generate-design/requirements.json`
- `.ai-sow/data/generate-story/delivery.json`
- `.ai-sow/data/generate-task/estimate.json`
- `.ai-sow/templates/sow-template.xlsx`

五份批准评审全部进入交付包；`generate-design.md` 仍是批准合同而不是第七份稳定 JSON。

## 运行

在项目根目录运行：

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/generate_sow.py" --project-root .
```

工作簿投影到 `01-需求`、`02-子需求`、`03-SOW主表`、`04-验收条件`、`05-任务明细`、`06-集成点`、`07-假设清单` 和 `90-系统现状`。动态 Table、样式、筛选、行高与跨 Sheet 引用来自模板；公式只能来自模板原型，Python 不保存基础人天、倍率、公式或取整规则，也不执行 Excel 公式。以 `=`、`+`、`-` 或 `@` 开头的普通文本按文本安全写入。

## 发布与完成条件

生成器在 `.ai-sow/outputs/` 内创建临时 staging 目录，完成工作簿复读和 manifest 校验后，以同文件系统 rename 发布：

```text
.ai-sow/outputs/sow-sha256-<generationFingerprint>/
├── sow.xlsx
├── manifest.json
├── sources/data/...
├── sources/reviews/...
├── sources/templates/sow-template.xlsx
└── validation/...
```

相同输入必须产生相同 `packageId` 和逐字节相同的完整包树；已有相同包返回 `REUSED`，已有不同内容返回 `PACKAGE_CONTENT_MISMATCH`，绝不覆盖。不支持原子发布的文件系统返回 `PACKAGE_PUBLICATION_UNSUPPORTED`。失败 staging 由本次运行清理，不实现跨设备 copy、项目锁或对抗同权限竞态的文件系统协议。

成功结果必须已经由生成器确认：五份收据与五份评审均在 manifest 和包树中；六份稳定 JSON 的
hash 一致；工作簿 Table 行数、公式原型、引用、样式和文本安全复读通过；交付包不含 repository、
往期 SOW、问卷或 Evidence 原文。当前 Stage Agent 报告 outcome、package ID、项目相对路径、
receipt/input match 与复读摘要，然后向用户交付包路径并 STOP；不得再次解释上游业务语义。

## Reconciliation Adapter

仅当用户显式调用 `ai-sow:reconcile` 且提供 `Reconciliation Run ID`、整体 review SHA-256 与项目内
staging root 时，本 Skill 作为最终投影 Adapter 运行。生成器使用同名 staging view 读取已完成的
五份 staged receipt、六份稳定 JSON、五份 review 与模板，并把内容寻址 package 写入 staging；
manifest 与 workbook 的 hash 必须来自 staged bytes，而不是 base。它仍只做 receipt-only 投影、
复读和 package 校验，不重放任何 Owner 业务规则。package 验证结果返回 reconciliation 的外层当前
Stage，由 batch publisher 先发布不可变 package，再发布 Owner 成果。普通独立调用和 STOP
行为保持不变。
