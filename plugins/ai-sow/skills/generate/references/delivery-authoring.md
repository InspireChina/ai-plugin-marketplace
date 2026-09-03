# Delivery 编写导航

本页只负责把编写者带到正确的参考；它不替代当前项目的 PRD、HLD、往期 SOW、补充材料、已验证 Scope 或权威模板。示例、标题风格和分类规则均不能成为 `sourceRefs`，也不能据此产生项目范围、技术选型或估算。

## 固定编写顺序

Delivery 必须在同一候选内分两遍完成。第一遍只从已验证 Scope 和当前来源形成 Story 与 AC，并在工作上下文建立一次性来源义务闭包清单，复核 Epic → Feature → Story 的层级、Story 触发归属、每条 AC 的精确来源与可观察性，以及来源条件、跨 Feature 规则和适用 Integration/NFR 是否遗漏。该清单不发布为稳定 JSON。第二遍只能以已经完成的 Story/AC 为输入，再读取当前模板、Effective Start 与设计/集成对象拆分 Task 和依赖。不得先按模板目录罗列 Task，再反向拼 Story 或补写 AC；也不得为两遍流程增加新的稳定 JSON、Owner 或用户批准点。

## 按对象查阅

| 要编写或复核的对象 | 先读 | 再读 |
| --- | --- | --- |
| Epic | [Epic 编写](epic-authoring.md) | [动态拆解](delivery-decomposition.md) |
| Feature | [Feature 编写](feature-authoring.md) | [技术工作分类](technical-work-classification.md) |
| Story | [Story 编写](story-authoring.md) | [动态拆解](delivery-decomposition.md) |
| AC | [Acceptance Criteria](acceptance-criteria.md) | 当前来源锚点 |
| Task | [Task 编写](task-authoring.md) | [Effective Start 匹配](effective-start-matching.md) |

## 按判断查阅

- 需要在 Epic、Feature、Story、AC、Task 之间继续拆分、合并或回退：读[动态拆解](delivery-decomposition.md)。
- 需要判断技术项是 NFR、DoD、Task 还是 Technical Epic / Feature / Story：读[技术工作分类](technical-work-classification.md)。
- 需要判断自动化测试、迁移、发布、切换或交接是否计入本次交付：读[交付工作分类](delivery-work-classification.md)。
- 需要判断已有能力能否修改或复用：读[Effective Start 匹配](effective-start-matching.md)。
- 需要向用户澄清或提供确认材料：读[问题编写](question-authoring.md)。
- 需要校对名称与层级风格：读[非证据性示例](delivery-examples.md)，随后回到当前项目来源验证。

## 不可省略的边界

稳定 Delivery 与模板交互、引用、Task 覆盖和 ID 规则以[Delivery 编译合同](delivery-compilation.md)为准。模板基础单元、计数口径、允许工作方式与复杂度判断只能由运行时读取权威模板；静态参考不得复制目录行、数量、人天或复杂度标准。
