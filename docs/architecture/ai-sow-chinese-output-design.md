# AI SOW 中文产出设计规格

日期：2026-08-20
状态：中文表达规则仍有效；领域、Skill、稳定数据和工作簿结构以 [AI SOW v1.3 合同设计](ai-sow-v1.3-contract-design.md) 为准。本文与 v1.3 冲突的结构性约定已被取代。

## 目标

AI SOW 默认使用简体中文进行解释、提问、评审和业务产出，同时保持 machine contract、稳定 ID、来源锚点和权威模板的精确语义。

## 中文自由文本

以下内容默认使用简体中文：

- 七个 Skill 的用户交互、工作说明和结果摘要；
- `.ai-sow/work/` 与 `.ai-sow/reviews/` 中的专业成果和问卷；
- 稳定 JSON 中的名称、描述、陈述、摘要、理由、影响、目的、问题、回答、处理建议、AC、Assumption、Risk 和 Task 说明；
- 最终工作簿中由上述内容投影的业务文本。

用户提供的正式名称或原文不是中文时，保留原文，并在相邻自由文本中用中文解释。引用外部原文时保持可追溯锚点。

## 保持原值的内容

- JSON 属性名、顶层集合名、schema `enum`、`const`、正则和格式；
- `epic-`、`feature-`、`story-`、`ac-`、`task-`、`asis-`、`integration-`、`assumption-` 等稳定 ID；
- `BUSINESS`、`TECHNICAL`、`SOURCE_INPUT`、`DESIGN_DERIVED`、`GREENFIELD`、`BROWNFIELD`、`ASSESSED`、`CARRY_FORWARD`、`IN_SCOPE`、`INTERNAL`、`EXTERNAL` 等 machine token；
- 模板定义的任务族、基础单元、工作模式、复杂度、Sheet、Table、列名、公式和数据验证；
- Git revision、SHA-256、项目相对路径、文件名、代码符号、API、协议、产品名和 Evidence anchor。

中文叙述引用英文标识符时，保留标识符并给出中文语义，不为追求全中文而破坏校验或追溯。

## Skill 语言职责

1. `setup` 用中文报告四字段项目初始化和环境能力。
2. `analyze-requirement` 用中文生成 BUSINESS Epic/Feature 评审和按需澄清问卷。
3. `analyze-as-is` 用中文生成范围、Topic 结论、承诺核对、Effective Start、Evidence 摘要和 Uncertainty。
4. `generate-design` 用中文生成目标方案、Scope Decision、TECHNICAL Epic/Feature 和具体派生理由。
5. `generate-story` 用中文生成 Gap、Story、AC、Integration、Assumption 和 Risk。
6. `generate-task` 用中文生成原子 Task 名称和理由，模板枚举保持原值。
7. `generate-sow` 不翻译模板或 machine token，只投影已评审自由文本。

## 完成标准

- 所有用户交互和业务自由文本默认使用简体中文；
- machine token、ID、模板结构和 Evidence anchor 保持精确；
- BUSINESS 与 TECHNICAL 所有权、八个领域 Sheet 和稳定文件遵循 v1.3 合同；
- 中文化不造成 validator 失败、公式变化或追溯断裂。
