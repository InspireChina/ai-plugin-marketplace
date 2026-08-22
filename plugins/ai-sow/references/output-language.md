# 输出语言合同

本插件默认使用简体中文进行解释、提问、评审、工作记录、用户叙述和总结。每项输出都按以下两个槽位处理：

- **中文自由文本**：名称、标题、描述、陈述、摘要、理由、影响、目的、问题、回答、处理建议、验收条件、假设、风险和任务说明等承载业务语义的自由文本，使用简体中文。
- **原值 machine token**：合同或追溯所需的机器值和原文保持原值，不翻译、不改写、不音译。

以下内容属于 **原值 machine token**，必须按原值保留：

- JSON 属性名和顶层集合名；
- schema 的 `enum`、`const`、格式、正则和条件约束；
- `projectId`、Epic、Feature、Item、Commitment、Evidence、Story、Task 等稳定 ID；
- `GREENFIELD`、`BROWNFIELD`、`ASSESSED`、`CARRY_FORWARD`、`IN_SCOPE`、`INTERNAL`、`EXTERNAL` 等 machine token；
- 模板定义的任务族、基础单元、工作模式和复杂度；
- sheet 名、表名、列名、公式、数据验证、命名范围和 OOXML 结构；
- Git revision、SHA-256、路径、文件名、代码符号、API、协议、产品名和必要的英文专有名词；
- 证据引用中的仓库相对 anchor 和源材料原文。

中文叙述引用英文标识符时，保留标识符并在相邻文本中用中文解释，确保可追溯性。若用户提供的正式名称、专有名词、源材料原文或引用不是中文，保留原文，并在相邻的 **中文自由文本** 中给出中文说明。
