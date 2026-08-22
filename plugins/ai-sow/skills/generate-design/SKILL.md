---
name: generate-design
description: 当 AI SOW 项目需要基于已批准的业务需求、原始来源和现状证据明确目标方案、架构变化、范围决策或技术要求时使用。
---

# 生成解决方案设计

本 Skill 独占全部 TECHNICAL Epic 与 Feature：既包括来源明示技术输入，也包括设计决策产生的技术工作。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。方案、决策、理由和技术需求使用简体中文；合同 token 保持原值。

## 路径

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。保持项目根目录为当前工作目录，并在执行前把命令中的路径占位符替换为绝对路径。

## 工作流

1. 读取已登记的原始来源、已批准的 `.ai-sow/data/analyze-requirement/requirements.json` 和 `.ai-sow/data/analyze-as-is/asis.json`。读取全部 Topic、Evidence、Uncertainty、Commitment、Effective Start 和 BUSINESS Feature Coverage。
2. 相对于 Effective Start 形成目标方案、Design Item 和 Architecture Delta。`CARRY_FORWARD` Commitment 是待交付工作；未解决的重要 Uncertainty 必须形成带理由的设计决策、prerequisite、定向 evidence request 或 scope boundary。
3. 为每个 BUSINESS 和 TECHNICAL Feature 恰好给出一个 `IN_SCOPE`、`FULLY_COVERED` 或 `OUT_OF_SCOPE` Scope Decision。`IN_SCOPE` 必须引用至少一个 Design Item；`FULLY_COVERED` 可以不引用 Design Item，但必须引用经 Evidence 支持的 Effective Start，并用具体理由说明现状已覆盖完整目标。BUSINESS `FULLY_COVERED` 还必须有一条引用同组 Effective Start 的 `COMPLETE` Coverage；TECHNICAL Feature 不要求 BUSINESS Coverage。
4. 识别来源明示并经设计确认的技术要求，将其编译为 `TECHNICAL` Epic/Feature，provenance 使用 `SOURCE_INPUT`，直接追溯到已登记 `sourceDocumentId` 和具体 `sourceReferences`。
5. 识别设计决策新增的技术要求，将其编译为 `TECHNICAL` Epic/Feature，provenance 使用 `DESIGN_DERIVED`。编译前读取并严格遵守[派生理由合同](references/derived-rationale.md)；每个派生 Feature 的单个 `rationale` 字符串必须按顺序给出设计决策、产生原因和具体不交付影响，且不得复用仅替换实体名称的模板。
6. 每个 Design Decision 必须同时关联至少一个 Design Item 和一个 Feature；非 `NEW` Architecture Delta 必须引用 Effective Start。孤立 Design Item、`CARRY_FORWARD` 被标成 `FULLY_COVERED`，或 `affectsEstimate = true` 的 Uncertainty 都会阻止门禁通过。
7. 在 `.ai-sow/work/generate-design/` 保存分析，并在 `.ai-sow/reviews/generate-design.md` 写入两个固定门禁：

   - `## 高阶设计覆盖门禁` 与精确声明 `HLD Coverage: PASSED`；
   - `## 上线范围门禁` 与精确声明 `Go-live Assessment: PASSED`；
   - 紧随上线门禁使用固定七列矩阵：`Concern | Disposition | Feature IDs | Effective Start IDs | Evidence IDs | 责任边界 | 依据`。

   矩阵必须恰好列出 `PRODUCTION_SCOPE`、`ENVIRONMENT_CONFIGURATION`、`DEPLOYMENT_CUTOVER_ROLLBACK`、`DATA_MIGRATION`、`PRODUCTION_VALIDATION`、`OBSERVABILITY`、`OPERATIONS_HANDOVER`、`POST_GO_LIVE_SUPPORT`、`USER_ENABLEMENT`、`LEGACY_RETIREMENT` 十项 Concern。每项只能选择 `IN_SCOPE / FULLY_COVERED / OUT_OF_SCOPE / NOT_APPLICABLE`，并给出责任边界和依据。`IN_SCOPE` 必须关联 TECHNICAL Feature；`FULLY_COVERED` 必须关联有 Evidence 的 Effective Start；`PRODUCTION_SCOPE` 不得为 `NOT_APPLICABLE` 且必须关联 TECHNICAL Feature。数据迁移与生产发布范围必须使用不同 Feature。
8. 对门禁中 `IN_SCOPE` 的上线 Concern，新增或复用职责单一的 TECHNICAL Feature 并完成设计覆盖；对 `FULLY_COVERED` 项记录证据；对 `OUT_OF_SCOPE / NOT_APPLICABLE` 项明确责任和依据。上线后值守、待命容量或泛化支持不得在没有明确购买范围时生成 Feature。若合同明确购买专职驻场、固定班次、待命容量或 24×7 支持，当前 Task 模型不能估算：必须生成 `affectsEstimate = true` 的 Uncertainty，转入独立服务容量模型或单独支持 SOW，并保持 `BLOCKED`，直至责任方带回获批的容量估算或明确排除决定。
9. 获得用户批准后，一起编译并原子发布：
   - `.ai-sow/data/generate-design/design.json`
   - `.ai-sow/data/generate-design/requirements.json`
10. 运行：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" --project-root .
   ```

## 字段质量

Epic 与 Feature 的 `description` 只描述技术背景、范围和能力。`involvedSystemsData`、`targetOutcome`、`commonConstraintsOutOfScope` 和 `constraintsNfr` 仅在分析有具体价值时生成；无证据时省略，不填空泛占位。

## 完成条件

目标设计与所有 TECHNICAL 需求已获批准，两个输出同时验证通过。下游完整需求仅是在内存中联合 BUSINESS requirements 与 TECHNICAL requirements；本 Skill 不修改业务需求，也不创建第三份合并 JSON。
