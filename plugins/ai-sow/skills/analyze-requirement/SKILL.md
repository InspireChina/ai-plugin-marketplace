---
name: analyze-requirement
description: 当 AI SOW 项目需要从业务简报、招标文件、研讨会记录或利益相关方陈述中确认业务范围、目标、规则、优先级或验收意图时使用。
---

# 分析业务需求

形成可评审的 BUSINESS Epic 与 Feature。技术要求和设计问题保留在已登记来源中，由 `generate-design` 统一处理。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。业务自由文本使用简体中文，合同 token 保持原值。

## 路径

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。保持项目根目录为当前工作目录，并在执行前把命令中的路径占位符替换为绝对路径。

## 工作流

1. 将用户提供的需求来源复制或登记到 `.ai-sow/inputs/analyze-requirement/`。为每份来源分配稳定 `sourceDocumentId`，记录项目相对路径、原文件名和 SHA-256；稳定数据不保存完整原文。
2. 只分析业务结果、参与者、范围、业务规则、优先级、验收意图、冲突和未知项。将来源中明确的技术约束或方案留给 `generate-design`，不在本阶段分类或产出 TECHNICAL 需求。
3. 当信息单薄、冲突或歧义可能改变业务范围、目标、规则、优先级或验收意图时，读取[需求澄清问卷](references/requirement-clarification-questionnaire.md)，生成 `.ai-sow/reviews/analyze-requirement-questionnaire.md`，与用户评审并回填答案、决策日期、状态证据和处置。关键问题关闭前保持需求评审为 `BLOCKED`。非关键未知项只有经用户明确回答并批准默认处理后才标记 `APPROVED_DEFAULT`；问卷保留为 `generate-story` 编译 Assumption 的唯一人类决策 handoff，不把它加入 BUSINESS JSON。
4. 在 `.ai-sow/work/analyze-requirement/` 形成来源归一化记录以及 Epic → Feature 分解。Epic 聚合同一业务结果；Feature 是可独立纳入、排除、延期和评审的最小需求范围。
5. 将人类可读成果写入 `.ai-sow/reviews/analyze-requirement.md`。评审应显示来源追溯、范围边界、已关闭问卷项、获批默认项和仍阻塞的问题，并明确写一项 `Questionnaire: NOT_REQUIRED` 或 `Questionnaire: .ai-sow/reviews/analyze-requirement-questionnaire.md`。`CLOSED` 且改变业务结论的答案必须在获批 BUSINESS Epic/Feature 中显示对应稳定 ID；不改变业务结论的 `APPROVED_DEFAULT` 留在问卷中等待下游消费。
6. 获得用户批准后，编译 `.ai-sow/data/analyze-requirement/requirements.json`。`epics` 和 `features` 全部为 `BUSINESS` 与 `SOURCE_INPUT`；使用 `epic-`、`feature-` 稳定 ID，并追溯到 BUSINESS `normalizedItems`。
7. 运行：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" --project-root .
   ```

## 字段质量

- Epic `description` 只介绍背景、范围和业务能力，不混入目标结果、技术方案或 Task。
- 只有证据支持明确内容时才生成 `involvedSystemsData`、`targetOutcome`、`commonConstraintsOutOfScope`、Feature `involvedSystemsData` 或 `constraintsNfr`；无价值时省略。
- 不用 `N/A`、空泛理由或推测填充选填字段。

## 完成条件

用户已批准 BUSINESS 需求评审，所有问卷项均处于可交接终态：关键项为 `CLOSED`，非关键默认项为字段完整的 `APPROVED_DEFAULT`；不存在 `OPEN`、`ANSWERED` 或缺失问卷。validator 以 exit code 0 结束。失败时保留上一份有效稳定文件；本 Skill 不创建 TECHNICAL Epic/Feature，也不修改其他 Skill 的文件。
