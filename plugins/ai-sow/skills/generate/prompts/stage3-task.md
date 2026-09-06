# Stage 3 Task Author

只返回 TaskDecisionIR 的 `tasks`。每项精确为 `localKey / storyLocalKey / acceptanceCriterionKeys / workTypeId / technicalTarget / deliverableBoundary / workModeDecision / complexityDecision / evidenceIds`。

packet 唯一包含 `workItems` 与三字段 wrapper 的 `contextRefs`。`storyLocalKey`、AC keys 和 `technicalTarget` 必须选择当前 sealed checkpoint 投影给出的句柄，不继承上一模型 localKey。阅读该 Story 的全部 AC、适用设计、Integration、NFR、政策、来源与本轮模板目录规则。每项只对应一个技术对象和独立计量边界；不得扩大上游范围。

`workTypeId` 从本轮 Task catalog 选择，通过 `hydrate-task-standard` 读取所选、相邻和 challenger 的完整本轮规则（最多两轮），再按该行计数口径、模式规则、S/M/L 标准、拆分条件、相邻类型和不建 Task 规则判断。`workModeDecision` 只为 `新建 / 调整 / 接入复用`，`complexityDecision` 只为 `S / M / L`。`deliverableBoundary` 用中文说明一个计量对象的具体交付边界。目录没有适用类型或证据不足时走合同 uncertainty exit，不发明类型或参数。

每个 Story 的全部 AC 必须由同 Story Task 关闭，最多四项；同一对象/证据的重复计价不合法。选择当前 packet 中支持技术对象与判断的 evidenceIds。调整/接入复用必须有该对象可验证的 Effective Start 证据；名称相似和 Demo 不能证明现状。Demo 可证明 UI 交互，但不能单独决定后端、数据、集成、认证、部署 Task 的技术对象、工作类型、模式或复杂度。每个已批准 Integration 只由一项合格集成 Task 负责。

SIT/UAT 自动化政策必须交付可执行的自动化测试代码或脚本，不能只用联调方案、人工执行记录或常规支持关闭。上线工程化应包含来源支持的版本化脚本、配置或发布工程产物；同一应用、环境与批次不能因覆盖多个功能而重复计量，独立发布对象必须有独立来源依据。范围、类型与计量单位仍以本轮完整模板规则为准。

每项 Task 声明的业务事务和技术交付必须由它自己引用的 AC 与 evidenceIds 支持，不能只依靠同 Story 的另一项 Task 代为覆盖。逐项对照完整模板包含/排除和验收结果，再检查跨工作类型的重叠：工程资产的形成与正式执行可以是不同交付物，但分别计价时必须写清来源支持、互不重叠的产物和验收边界。不能把同一次部署执行同时装入环境接入与发布执行，也不能凭空添加环境、批次或资产来制造区别。仅共同使用同一设计/来源不代表重复，仍按实际交付物判断。

不输出最终 ID、SourceRef、row hash、replacementSet、节点、checkpoint、基础人天、倍率、公式、SIT/UAT 参数或取整值。模板仍为唯一计算权威。无法关闭的义务必须修正或取得上游依据，不能以自由文本声明免费而静默省略。
