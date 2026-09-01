# Scope 编译合同

Scope 编译把当前输入 revision 转换为一个完整的 `ScopeBundle`。PRD 对业务目标、业务结果、业务规则和验收意图具有权威性；HLD 对目标架构、Integration、NFR 与上线约束具有权威性；往期 SOW 只作为 Brownfield 的合同 As-Is、历史承诺和 Effective Start；当前问卷及补充材料负责责任、现状变化、本次明确决定，以及原型中的功能与交互证据。SOW 模板只拥有估算目录和计算规则，不定义 Scope。

## 必须形成的边界

- 每个 Feature 必须有且只有一个 `IN_SCOPE`、`FULLY_COVERED` 或 `OUT_OF_SCOPE` 结论。
- `IN_SCOPE` 必须连接目标 Design；`FULLY_COVERED` 必须连接有来源证据的 Effective Start。
- Integration 至少说明来源、目标、目的、触发、责任和 `DEFINED | DESIGN_REQUIRED` 状态。
- NFR 使用 `TARGET_DEFINED | DESIGN_REQUIRED | NOT_APPLICABLE`。`DESIGN_REQUIRED` 必须写明当前估算边界和未来变更触发条件，后续形成 Design Task。
- 假设和风险必须有责任方、处理方式、估算边界和变化触发条件。能够固定边界的低阶设计缺口不得升级为 `BLOCKED`。
- 只有缺失事实会改变 Feature/系统数量或责任、材料不能确定、且无法通过明确假设或排除范围固定时，才允许阻断。

## Greenfield 与 Brownfield

Greenfield 的最低起点是“本期新建、不继承既有合同能力”，不制造 Current State。Brownfield 必须存在适用的往期 SOW 和现状增量声明；不得用推断基线替代。往期承诺按适用范围和生效关系处置为延续、起点、排除或待决定。会改变范围或估算的 `NEEDS_DECISION` 必须在编译前解决。

## 来源、冲突与原型

每个 Scope 对象都要引用当前 revision 的语义锚点。PRD/HLD 冲突优先通过明确假设、责任或排除范围固定；插件推断不得覆盖明确来源。HTML、TypeScript 或 TSX 原型作为补充文本时，必须识别页面入口、用户动作、触发、状态变化、校验、权限、异常和可观察结果；源码不足且 Demo 可运行时，可用 Playwright 或 Computer Use 验证，观察结论仍须追溯到该原型来源。

## ID 与切片替换

语义不变使用 `UNCHANGED`，仅说明性文字或来源定位变化且交付含义不变使用 `CLARIFIED`，实质变化必须用新 ID 和 `CHANGED`，新对象使用 `NEW`。切片替换删除受影响闭包中的旧对象，再插入完整新切片；未受影响对象保持规范字节不变。跨越闭包的共享 Design、Integration、NFR 或假设必须先扩大 ImpactPlan，不能留下半更新引用。
