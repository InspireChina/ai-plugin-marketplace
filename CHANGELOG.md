# 变更日志

所有重要的用户可见变更都记录在此。

## 未发布

- 将 candidate-first 生命周期推广到五个专业 Owner：各 Owner-local context closure 只投影本阶段
  所需引用，独立 Reviewer 使用 fresh context；候选、机械校验、风险摘要和 hash-bound review
  packet 全部前置到用户批准之前，批准后只执行精确 `publish-approved` 原字节发布。现有 receipt
  `0.3`、稳定路径、模板计算权威和 reconciliation Adapter 保持兼容。
- 收紧 `generate-task` 性能试点：review packet 绑定 context manifest 与五个证据 fragment，
  Delivery 无完备 Story→Effective Start 映射时保守保留全部 Effective Start；新增确定性 review
  renderer，从 candidate 与模板投影逐 Task 计数、包含、排除和非重复计价边界，避免修复后的
  review 漂移。
- 简化确定性阶段拓扑：`setup` 与普通 `generate-sow` 均由当前 Stage 直接调用一次现有 Module，
  不再为环境/Schema 复读或 receipt/工作簿/package 机械检查创建 Worker、Validator 或默认 Reviewer
  叶子 Agent；既有 fail-closed、模板权威、复读和内容寻址发布语义保持不变。
- 新增七阶段之外的 `ai-sow:reconcile` 维护 Skill：已有完整产物后的上游修正可在一个 session
  内完成固定影响后缀；全部 Owner candidate/projection、staged validation、SOW package、canonical
  redo/diff/risk 都在批准前由完整 packet 绑定，一个 Reviewer 与一次批准绑定同一 packet SHA-256，
  批准后只做确定性 check/publish 和可恢复批量发布。未新增稳定业务 JSON、DAG、通用 Owner runner
  或 revision store。
- 修正 `generate-task` 的 AC 追溯语义：Story/AC 在批准后保持只读，Task 与同 Story AC
  允许多对多映射；每条 AC 仍须至少有一个 Task 覆盖，但多个基础单元 Task 可共同满足同一
  业务验收条件。
- 固化 Task→Design 反馈边界：实现机制缺口优先细化既有 TECHNICAL Feature；未改变用户批准
  的交付结果时，`generate-story` 只做 `NO_CHANGE` rebind，不得用新增技术 Feature 反向改写
  已批准的 Story/AC。
- 将五个 Owner handoff 统一为 validator contract `0.3` receipt；下游只匹配当前 input、批准
  review 和 stable output 字节，不再重放上游业务 validator 或 HLD/Go-live 门禁。
- `generate-sow` 现在生成内容寻址且逐字节确定的自包含包，包含六份稳定 JSON、五份批准
  review、五份 receipt 和权威模板；相同包复用，不同内容 fail closed。
- 将插件发布面同步到 `0.1.0-beta.2`，并提供与正常 `setup` 分离、只修改四字段 project
  metadata 的显式 beta.1→beta.2 迁移及审计报告。
- 将 v1.3 XLSX 示例升级为面向 PMO 与财务评审的仿真 Brownfield 项目，使用 6 个 Epic、
  18 个 Feature、23 个 Story、46 个原子 Task、4 个集成点和 6 条假设/风险，完整展示
  需求追溯、现状证据、范围决策、验收、工作模式、复杂度、SIT、UAT、风险与项目取整。
- 在 `90-系统现状` 中为 Feature 覆盖记录显示“Feature覆盖”主题标签，避免连续空白被误解为
  数据遗漏，同时保持跨主题覆盖关系和稳定数据合同不变。

## 0.1.0-beta.1 - 2026-08-22

- 将 AI SOW 作为首个自包含 marketplace 插件的公开 beta 版本发布。
- 引入严格的 SOW 1.3 八实体合同和 Effective Start 模型。
- 分离 BUSINESS 与 TECHNICAL Epic/Feature 的数据所有权，将技术输入移至 As-Is，并按
  一行一个原子 Task 进行估算，不使用乘法数量字段。
- 用 12 个任务族、36 个基础单元的目录替代 Story 类型和旧版 Task 领域、活动、模式倍率。
  每个 Task 根据配置的基础单元、工作模式人天和逐单元 S/M/L 标准估算；SIT 由每个
  Integration 关联的唯一集成 Task 触发，UAT 由 Story 标志触发。
- 将基础单元目录及三个工作模式的人天合并到一个便于评审的工作表，并把 S/M/L 复杂度
  系数移入项目参数表。
- 发布可维护的 v1.3 Markdown 标准、生成的 XLSX 示例和字节完全一致的内置模板副本。
- 增加从已加载 `SKILL.md` 路径推导的安装安全 Skill 命令。
- 增加确定性的 setup、验证和工作簿生成测试覆盖。
- 面向用户的 Skill 指令和业务自由文本默认使用简体中文，同时保持机器合同、枚举、ID、
  路径、哈希和字节完全一致的 XLSX 模板不变。
- 将 macOS 标记为已验证平台，证据覆盖仓库测试、本地安装、独立插件副本和 Brownfield
  工作流；Windows 11 在公开实机清单具备证据前保持临时支持（`Provisional`）。Windows
  CI 和合成可移植性测试不作为真实 Windows 11 验收结果。
