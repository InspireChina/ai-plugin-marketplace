# 变更日志

所有重要的用户可见变更都记录在此。

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
