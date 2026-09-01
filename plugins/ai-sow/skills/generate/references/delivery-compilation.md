# Delivery 编译合同

Delivery 编译只读取已验证的完整 Scope、当前受影响切片和权威 SOW 模板目录，生成完整 `DeliveryBundle`。它不得反向修改 Scope，也不得在 Task 估算阶段改写 Story 或 AC。

## Story 与验收

- Story 以可交付结果命名并显式连接 Feature；Design 工作放在实现 Story 下的 `DESIGN` Task，不创建笼统的 Design Story。
- 每个需交付的 `IN_SCOPE` Feature 至少由一个 Story 覆盖；每个 Story 至少有一条独立、可观察、可判定的 AC。
- 每条 AC 必须由同一 Story 的至少一个 Task 覆盖。Task 不能引用其他 Story 的 AC。

## Task 与模板目录

- 一条 Task 对应模板中的一个基础单元实例，只选择 `新建 / 调整 / 接入复用` 和 `S / M / L`。
- `read_template_catalog` 读取基础单元、任务族、计数口径、包含/排除、允许工作模式、复杂度标准和拆分条件；人天单元格只用于确认组合存在，不进入 JSON，也不由 Python 计算。
- `调整` 和 `接入复用` 必须精确引用 Effective Start。接入复用还要明确本项目侧注册、配置、封装、映射、适配、认证、租户、权限或专项验证工作。
- S/L 必须说明偏离 M 的事实；命中 X/拆分条件时必须拆分、澄清或形成有边界的设计/调研 Task，不能把 X 写入稳定 Delivery。

## Design、Integration 与专项工作

- 每个 `DESIGN_REQUIRED` Integration/NFR 必须由实现 Story 下的 Design Task 负责；跨 Story 的同一设计问题只计一次，并通过依赖把后续实现连接起来。
- 每个需要交付的 Integration 恰好由一个内部或外部系统对接 Task 负责，不重复计算例行接口设计。
- 数据迁移、发布切换、问题诊断与整改、用户培训和运维移交按各自基础单元拆分。禁止“其他支持”“持续支持”“不限次数”等开放式 Task。
- 依赖必须连接已知 Task、与 `dependsOnTaskIds` 完全一致且无环。

## ID 与切片替换

ID ledger 与 Scope 使用相同语义：`UNCHANGED` 完全一致，`CLARIFIED` 只改变说明性文字，实质变化必须使用新 ID，新增对象使用 `NEW`。替换切片时删除受影响 Feature 的全部旧 Story、AC、Task 及相连依赖；未受影响对象保持规范字节不变。共享 Story 跨越闭包时必须先扩大 ImpactPlan。
