---
name: generate-task
description: 当已评审的交付 Story 需要按权威模板的基础单元目录拆成可独立估算、验收和结算的 Task，并判断工作模式、复杂度、现状依据或 Integration 引用时使用。
---

# 生成原子 Task

一条 Task 对应一个基础单元实例需要完成的全部工作。它是直接估算人天的最小明细，不是“设计”“编码”“测试”中的某一个固定步骤。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。Task 名称和理由使用简体中文；模板枚举按原值写入。

## 路径

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。保持项目根目录为当前工作目录，并在执行前把命令中的路径占位符替换为绝对路径。

## 工作流

1. 读取 `.ai-sow/data/generate-story/delivery.json`、As-Is Effective Start、目标设计和 `.ai-sow/templates/sow-template.xlsx`。Integration 是独立顶级实体，不从 Story 类型推断；设计门禁已由 `generate-story` 前置复核，并由 `generate-sow` 在最终投影前防御性复核。
2. 运行模板读取器，从单张基础单元配置表取得 37 项基础单元、13 个任务族、计数口径、包含/不包含内容、三个工作模式列的 M 档基础人天和逐单元复杂度标准，并从项目参数取得 S/M/L 系数。人天列中的正数表示组合可用，`❌` 表示不适用；复杂度系数必须为正数且状态为固定规则、已校准或已批准：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/read_template.py" --project-root .
   ```

3. 先按计数口径识别实例，再一实例一行拆分。Task 名称写清具体交付对象和范围；必要的设计、实现或配置、开发自测、单元级验证、说明和基本联调包含在同一基础单元内，不固定拆成“设计 + 实现”任务对。重复实例必须拆行，不能用数量或复杂度合并。
4. 只写 `baseUnit`，任务族由模板自动带出。不得保存 `professionalDomain`、`activity`、`quantity`、基础人天、倍率、Task 人天或 `sitEstimates`。
5. 工作模式只允许：

   - `新建`：创建原来不存在的基础单元实例；
   - `调整`：保留已有对象及主要范围，修改其行为、规则、结构、配置或内容；
   - `接入复用`：已有能力本身不改，只完成本项目一侧的接入、配置、映射、适配和必要验证。

   `调整 / 接入复用` 必须填写结构化 `workModeEvidence`：`effectiveStartItemId` 必须是 `matchedEffectiveStartItemIds` 中的一项，`effectiveStartItemName` 必须与该 Effective Start 名称完全一致且在 Task 名称或理由中明确出现，不能用宽泛关键词或无关现状凑引用。测试类调整所引用的 Effective Start 必须明确是既有测试方案、用例、脚本、框架或配置；数据迁移与发布切换的调整必须引用既有迁移或切换资产。数据迁移、系统功能下线、同一根因问题整改的新建 Task 也必须引用所作用的现状；发布切换涉及现有运行能力时同样如此。“接入复用”的 `projectSideWorkTypes` 必须列出本项目侧可独立估算的注册、配置、封装、映射、适配、认证、租户、权限或专项验证工作，并按枚举顺序生成 `projectSideWorkCommitment = 本项目负责并交付：<中文工作类型>`；`workModeRationale` 必须严格写成 `<effectiveStartItemName>保持不变；<projectSideWorkCommitment>。`。普通依赖引入、常规调用或直接按既有约定使用不单独生成 Task。
6. “替换”和“退役”不是 Task 工作模式。替换按实际范围拆成替代能力、数据迁移、发布切换和系统功能下线；只修改原对象内部实现时使用“调整”。
7. 按当前基础单元自己的标准判断 `S / M / L`。S/L 的 `complexityRationale` 必须写明当前实例偏离 M 的具体事实，不能照抄目录标准；M 省略该字段。命中 X 时不得进入正式 JSON，必须继续拆分、澄清，或先生成专题调研/架构方案设计 Task。
8. 内部或外部系统对接 Task 必须引用一个已登记的 `integrationId`，且责任归属、Story 和基础单元一致。一个 Integration 恰好由一个集成 Task 实现；其他 Task 不得填写 `integrationId`。发现未登记的交互时退回 `generate-story` 或 `generate-design` 补证据，不能临时编造 Integration。
9. 上线范围按目录拆解：发布计划和实际部署/切换合并为同一个“发布切换”Task，每个 Story 最多一个；数据迁移必须使用独立 Task。“问题诊断与恢复”只计算分诊、证据收集、诊断和恢复，“同一根因问题整改”只计算已确认根因的实现与验证，同一 Story 不得让两者重复计算诊断。只有 `USER_ENABLEMENT = IN_SCOPE` 时才按明确用户群体生成“用户培训与使用材料”；不得生成泛化的上线后支持、待命或容量 Task。
10. 为每条 Task 填写具体的 `workModeRationale` 和 `rationale`，并在 `.ai-sow/work/generate-task/` 保存分解；在 `.ai-sow/reviews/generate-task.md` 评审覆盖、重叠、单实例边界、工作模式、复杂度、Integration 一对一关系、上线 Concern 和现状证据。
11. 获得用户批准后编译 `.ai-sow/data/generate-task/estimate.json`，再运行：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" --project-root .
   ```

## 完成条件

每个 Story 至少有一条 Task；每条 Task 只对应一个基础单元实例，匹配模板允许的“基础单元 + 工作模式”，并满足理由、相关 Effective Start、调整资产、可估算复用工作和 Integration 规则。复杂度系数已经校准或批准；稳定 JSON 不保存计算结果。权威模板按 M 档基础人天与复杂度倍率计算 Task 人天，由集成 Task 触发 SIT，并继续计算 UAT、风险和取整。
