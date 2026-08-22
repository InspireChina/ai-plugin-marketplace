---
name: generate-story
description: 当已评审的业务需求、技术需求、现状和目标设计需要分解为可交付、可验收、可结算的 AI SOW 范围时使用。
---

# 生成交付 Story

把每个范围内 Feature 相对于 Effective Start 的差距分解为 Story、AC、Integration、Assumption 和 Risk。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。业务自由文本使用简体中文；合同 token 保持原值。

## 路径

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。保持项目根目录为当前工作目录，并在执行前把命令中的路径占位符替换为绝对路径。

## 工作流

1. 分别读取 BUSINESS requirements 与 TECHNICAL requirements，并在内存中联合；不写合并文件。同时读取 As-Is、design、`.ai-sow/reviews/generate-design.md` 和需求评审中的 `Questionnaire` 声明。只有 HLD Coverage 与 Go-live Assessment 均精确为 `PASSED`、固定上线矩阵完整且与 design/As-Is 一致时才继续；否则返回 `BLOCKED`。声明为正式路径时读取可选 `.ai-sow/reviews/analyze-requirement-questionnaire.md`；声明为 `NOT_REQUIRED` 时确认该文件不存在。声明缺失、声明与文件状态冲突或应有文件缺失时返回 `BLOCKED`。
2. 问卷存在时检查全部记录；出现 `OPEN`、`ANSWERED`、字段不完整或无法验证的处置时返回 `BLOCKED`。对每个同时具备 Question ID、用户 Answer、Decision date、Decision evidence、`Status: APPROVED_DEFAULT` 与 `Disposition: ASSUMPTION_CANDIDATE` 的记录恰好生成一个 Assumption 候选；其 `handling` 保留 `analyze-requirement-questionnaire#<Question-ID>` 来源锚点。`CLOSED / INCORPORATED_BUSINESS:<stable-id>` 必须能在获批 BUSINESS requirements 中找到对应 ID，并核对 Answer 已反映在该 Epic/Feature 中，且不再生成 Assumption；`CLOSED / NO_CHANGE` 也不生成。
3. 对每个 `IN_SCOPE` Feature，用目标结果减去其 Coverage 所连接的 Effective Start，形成 Delivery Gap。把相关 `CARRY_FORWARD` Commitment 纳入差距，不能当作基线。`FULLY_COVERED` Feature 不生成 Gap 或 Story；其完整性已由设计门禁中的 Effective Start、Evidence 和理由证明。
4. 对每个 `IN_SCOPE` 生产上线 TECHNICAL Feature 形成完整 Delivery Gap，并优先拆成“上线准备”“发布切换”“生产验证与运维移交”三个结果型核心 Story；旧功能下线条件适用时单独生成 Story，不与发布切换合并。每个上线 Story 通常设置 `uatRelevant = false`，只有确实属于业务 UAT 分母且获得评审确认时才能设为 `true`。
5. 对每个 `IN_SCOPE` 数据迁移 TECHNICAL Feature 单独生成 Gap 和迁移 Story。迁移 Feature、Gap 和 Story 不得归入生产上线 Feature；发布切换只能把已完成的迁移结果写成前置条件或 AC，不能吞并迁移交付范围。
6. `POST_GO_LIVE_SUPPORT` 只能形成明确的合同边界、Assumption/Risk，或已经批准且可验收的具体交付工作；不得生成泛化“上线后支持”、驻场、待命容量或 24×7 支持 Story。若输入明确购买专职驻场、固定班次、待命容量或 24×7 支持，停止 Story 分解并返回 `generate-design`：由其登记 `affectsEstimate = true` 的 Uncertainty，转入独立服务容量模型或单独支持 SOW，在责任方带回获批容量估算或明确排除决定前保持 `BLOCKED`。UAT 缺陷责任、变更请求和支持边界写入 AC、Assumption/Risk 与责任边界，不生成开放式缺陷 Story。
7. 将其余差距拆成结果明确、可独立交付、验收和结算的 Story。Story 不保存类型；前端、后端、数据、集成、测试、迁移、调研等工作性质由后续 Task 表达。重要 Uncertainty 需要交付工作解决时创建具有明确问题和结论的 Story；否则形成带 trigger、handling 和 responsibility boundary 的 Assumption 或 Risk。
8. 为每个 Story 编写有序 AC；每条 AC 是独立可观察、可通过或不通过的结果，不描述实现 Task。上线 AC 必须明确前置条件、成功判定、失败或回滚边界以及责任方；数据迁移 AC 与发布切换 AC 分开。
9. 把有证据支持的 Integration 作为顶级权威实体写入 `integrations`。每条 Integration 有唯一 `integrationId`，并明确 `storyId`、source、target、trigger、direction、purpose 和 owner。Integration 不依赖 Story 类型，登记关系也不表示已经决定生成集成 Task；是否需要交付内部或外部系统对接工作由 `generate-task` 判断。
10. 把每个 Assumption 或 Risk 作为 `assumptions` 中的一条独立记录。相同语义只保留一行，通过 `assumptionStories` 关联一个或多个 Story；不为每个 Story 复制同一假设。
11. 在 `.ai-sow/work/generate-story/` 保存分解，在 `.ai-sow/reviews/generate-story.md` 评审差距、Story 边界、AC 可测性、Integration 责任、Assumption/Risk 及约束证据。评审必须逐项记录十个上线 Concern 的合同处置及 `Concern -> Feature -> Gap -> Story/Assumption/Risk` 映射，并确认上线准备、发布切换、生产验证与运维移交、条件适用的下线、独立数据迁移、UAT 分母和支持边界无遗漏或重复；自由文本无法可靠证明时保持 fail closed。问卷存在时，评审还必须逐项列出 `Question ID -> assumptionId -> storyIds`；批准前每个 `APPROVED_DEFAULT` 恰好出现一次，不得遗漏或重复消费。
12. 获得用户批准后编译 `.ai-sow/data/generate-story/delivery.json`，再运行：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" --project-root .
   ```

## 完成条件

每个范围内 Feature 恰有可追溯 Gap，每个 Gap 至少关联一个 Story，每个 Story 至少有一条 AC；范围内生产上线完整覆盖上线准备、发布切换、生产验证与运维移交，适用时单列旧功能下线；数据迁移使用独立 Feature、Gap 和 Story；上线 Story 的 UAT 分母、上线后支持边界及 UAT 缺陷/变更责任均有明确评审结论。每条有依据的 Integration 都作为独立记录关联一个 Story；每个 Assumption/Risk 只保存一次并用关系集合连接 Story。存在问卷时，每个 `APPROVED_DEFAULT` 都完整映射到一个稳定 Assumption 和至少一个 Story，且 `handling` 保留 Question ID 锚点；问卷本身仍是人类评审状态，不成为第七份稳定 JSON。validator 以 exit code 0 结束。
