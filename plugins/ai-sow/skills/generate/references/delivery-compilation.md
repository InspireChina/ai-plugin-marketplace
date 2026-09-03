# Delivery 编译合同

Delivery 编译只读取已验证的完整 Scope、当前受影响切片和权威 SOW 模板目录，生成完整 `DeliveryBundle`。它不得反向修改 Scope，也不得在 Task 估算阶段改写 Story 或 AC。

编写前按阶段读取[Delivery 编写导航](delivery-authoring.md)中的对应参考。层级、拆解、技术分类、交付工作与 Effective Start 的细则分别由专门页面维护；它们不替代当前项目来源或模板目录。任何示例只用于判断层级与标题风格，不能作为当前项目范围、技术选型或估算证据。

## Story 与验收

- Story 以单一、可交付、可验收、可结算的结果命名，并通过唯一 `featureId` 归属一个 Feature；不得把多个 Feature 名称拼成一个 Story 的范围。标题采用自然、看板友好的 `[模块/接口] 角色或对象＋动作` 风格，不以“完成”或“实现”开头。Design 工作放在实施 Story 下的 `DESIGN` Task，不创建笼统的 Design Story。
- 每个需交付的 `IN_SCOPE` Feature 至少由一个 Story 覆盖；每个 Story 至少有两条独立、可观察、可判定的 AC，通常为 2–4 条，且最多包含四个 Task。超过四个基础单元实例时，必须按可独立验收和结算的结果拆分 Story。
- AC 至少覆盖正常结果，并按当前来源覆盖适用的校验、状态、异常、边界与 NFR；每条 AC 必须保存精确、最小充分的 `sourceRefs`。不得从参考示例发明 API、消息、产品或阈值；详细规则见[Acceptance Criteria](acceptance-criteria.md)。
- 可靠性、可观测、质量验证、发布切换或运维移交等跨业务 Feature 的工作，先在 Scope 中形成有来源的技术 Feature，再拆成相应 Story；不得创建横跨多个无关业务 Feature 的“共享治理”大 Story。
- 每条 AC 必须由同一 Story 的至少一个 Task 覆盖。Task 不能引用其他 Story 的 AC。
- AC 的显示和评审顺序就是 `acceptanceCriteria` 的列表顺序，不复制 `sequence` 或解释性 `rationale`。
- Story 稳定数据只保留 `storyId / featureId / name / uatRelevant`，不保存 `description` 或 `As / I want to / So that`。Story 行备注由工作簿从 Scope 中与 Feature 关联的已批准假设、风险、估算边界和变化触发条件确定性投影。

Epic、Feature、Story 按交付结果而非工种拆分。全局 DoD、常规 SIT/UAT 支持和未知未来缺陷不机械创建 Story；业务功能测试通常是业务 Story 下的 Task，只有有独立成果、AC、证据和估算对象的 Enabler、Spike、基础设施或专项保障才形成 Technical Story。

## Task 与模板目录

- 一条 Task 对应模板中的一个基础单元实例，只选择 `新建 / 调整 / 接入复用` 和 `S / M / L`。
- Task 名称使用“动作＋业务或技术对象＋单一交付物”，必须让评审者能直接回答本行计数的唯一对象。`业务服务与接口` 的接口 Task 一行只对应一个可独立开发、测试和估算的接口；属于该接口内部的校验、事务、权限和异常处理进入同一 Task 及其 AC，只有形成独立调用契约时才另建 Task。内部业务操作没有独立接口时，名称必须点明一个操作及其结果，不得使用“开发某某服务”代替交付物。静态写法、回退及目录权威见[Task 编写](task-authoring.md)。
- `read_template_catalog` 读取基础单元、任务族、计数口径、包含/排除、允许工作模式、复杂度标准和拆分条件；人天单元格只用于确认组合存在，不进入 JSON，也不由 Python 计算。
- `调整` 和 `接入复用` 必须通过 `workModeEvidence.effectiveStartItemId` 精确引用唯一 Effective Start；名称从 Scope 按 ID 解析，不复制到 Delivery。接入复用还要明确本项目侧注册、配置、封装、映射、适配、认证、租户、权限或专项验证工作。
- S/L 必须说明偏离 M 的事实；命中 X/拆分条件时必须拆分、澄清或形成有边界的设计/调研 Task，不能把 X 写入稳定 Delivery。
- 一个标题出现多个并列接口或多个可独立验收的业务操作时必须拆成多个 Task；拆分后超过同 Story 四个 Task 时继续拆 Story，不能靠合并名称绕过粒度门禁。

## Design、Integration 与专项工作

- 每个 `DESIGN_REQUIRED` Integration/NFR 必须由实现 Story 下的 Design Task 负责；跨 Story 的同一设计问题只计一次，并通过依赖把后续实现连接起来。
- 每个需要交付的 Integration 恰好由一个内部或外部系统对接 Task 负责，不重复计算例行接口设计。
- 数据迁移、发布切换、问题诊断与整改、用户培训和运维移交按各自基础单元拆分。禁止“其他支持”“持续支持”“不限次数”等开放式 Task；是否属于本项目交付范围按[交付工作分类](delivery-work-classification.md)判断。
- 顶层 `dependencies` 是唯一 Task 依赖表达；依赖必须连接两个不同的已知 Task 且无环，Task 内不再复制前置 ID 列表。

## ID 与切片替换

ID ledger 与 Scope 使用相同语义：`UNCHANGED` 完全一致，`CLARIFIED` 只改变说明性文字，实质变化必须使用新 ID，新增对象使用 `NEW`。`replacesFeatureIds` 只列基线中被替换的旧 Feature ID，不能混入候选新 ID；初次完整编译必须为空。替换切片时按 Story 的唯一 `featureId` 删除受影响 Feature 的全部旧 Story、AC、Task 及相连依赖；未受影响对象保持规范字节不变。

稳定 Delivery 不保存 Story `storyType/description`、AC `sequence/rationale`、Task `dependsOnTaskIds/matchedEffectiveStartItemId` 或 Effective Start 名称副本；这些值均可由固定合同、列表顺序、顶层依赖或 Scope ID 引用唯一得出。
