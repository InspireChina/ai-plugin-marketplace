# DESIGN_DERIVED 理由合同

每个 `DESIGN_DERIVED` Feature 的 `rationale` 必须是一个字符串，并严格使用以下顺序和分隔符：

```text
设计决策/Decision: <designDecisionId 与具体决策>；产生原因/Cause: <该决策产生本 Feature 的具体原因>；不交付影响/Non-delivery impact: <影响类别> | <具体影响对象> -> <具体后果>
```

约束：

- `设计决策/Decision` 子句必须包含 provenance 中每个 `designDecisionId`，去除 ID 后仍须有至少 8 个字母、数字、汉字或下划线字符来描述具体决策。
- `产生原因/Cause` 子句须有至少 12 个字母、数字、汉字或下划线字符，说明决策与本 Feature 之间的因果关系。
- 影响类别只能是 `流程/Process`、`接口/API`、`质量属性/Quality attribute` 或 `责任边界/Responsibility boundary`。
- 具体影响对象须有至少 3 个有效字符，且不得只写“系统”“功能”“模块”“业务”或相应英文词。
- 具体后果须有至少 8 个有效字符，且不得使用“会受到影响”“功能不可用”“系统无法工作”“项目失败”等通用结论。
- 两条理由不得完全重复；也不得只替换 Feature ID、Feature 名称、design decision ID、design decision 标题或影响对象而复用同一模板。

合格示例：

```text
设计决策/Decision: decision-profile-api 使用专用 API 边界处理客户档案操作；产生原因/Cause: 客户档案操作 API 需要为 UI 与未来渠道提供统一操作边界；不交付影响/Non-delivery impact: 接口/API | Customer Portal -> 无法通过统一边界创建或检索客户档案
```
