---
name: generate-design
description: 当 AI SOW 项目需要基于已批准的业务需求、原始来源和现状证据明确目标方案、架构变化、范围决策或技术要求时使用。
---

# 生成解决方案设计

本 Skill 独占全部 TECHNICAL Epic 与 Feature：既包括来源明示技术输入，也包括设计决策产生的技术工作。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。方案、决策、理由和技术需求使用简体中文；合同 token 保持原值。

## 精确批准快速路径

若本次新 session 的用户指令已经明确批准 Owner `generate-design` 和一个完整 packet SHA-256，本节优先于下方完整设计流程。从当前 turn 的 Available skills 条目直接取得本 `SKILL.md` 的绝对路径；不得使用 `rg`、`find` 或 `rg --files` 枚举或重新定位 Skill。Stage 不得手写 approval JSON，必须严格依次只运行以下两条确定性命令；第一条用 canonical bytes 写固定 `ai-sow-owner-approval-v1` sidecar，第二条执行唯一发布 preflight：

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode write-approval \
  --packet-sha256 "<用户明确批准的完整 packet SHA-256>"
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode publish-approved \
  --candidate .ai-sow/work/generate-design/design.candidate.json \
  --requirements-candidate .ai-sow/work/generate-design/requirements.candidate.json \
  --review-path .ai-sow/work/generate-design/review.candidate.md
```

`write-approval` 只校验 hash 格式并写固定 sidecar，不读取 packet 或专业成果；`publish-approved` 自己复算 packet、Reviewer、两份 candidate、context、input、review、risk summary 与 approval 的全部绑定，是正式写入前唯一需要的 preflight。

此快速路径不得重新读取上游数据、来源、Schema、reference、candidate、packet 或 Reviewer 内容，不得枚举项目或插件文件，不得运行 `--help` 或除上述两条以外的其他命令，不得运行 `prepare_context.py`、`render_review.py`、独立 `check`，也不得创建 Reviewer 或修改专业成果。任一命令返回 `BLOCKED` 时原样报告 diagnostics 并停止；不得探索实现或退回完整设计。

## 精确 Reviewer 绑定

fresh-context Reviewer 只返回 `PASS` 或 findings，不写项目文件。Reviewer 对当前 packet 返回 `PASS` 后，当前 Stage 不得手写 reviewer JSON，必须立即运行下列唯一绑定命令；它只校验完整 hash 格式并以 canonical bytes 原子写入固定 `ai-sow-owner-reviewer-v1` sidecar，不读取 packet、两份 candidate、上下文或来源：

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode write-reviewer \
  --packet-sha256 "<Reviewer 已独立审查并 PASS 的完整 packet SHA-256>"
```

该命令只能消费实际 Reviewer 的 `PASS`，不能替代独立评审。命令返回 `BLOCKED` 时原样报告并停止；任何 packet 字节变化都必须重新创建 packet、交回 Reviewer 完整复审，再重新绑定。

## 路径

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。保持项目根目录为当前工作目录，并在执行前把命令中的路径占位符替换为绝对路径。

确定性脚本是本 Skill 的公开命令实现。Stage 与 Reviewer 不得复读 `scripts/*.py` 实现，也不得为预测 diagnostics 扫描源码；Stage 只按本 Skill 公布的命令执行并原样消费结构化 stdout。仅当脚本实际异常且公开 diagnostics 不足以定位执行故障时，才允许最小化读取直接报错位置。

完整设计流程同样从当前 turn 的 Available skills 条目直接取得本 `SKILL.md` 路径，不搜索插件。
读取本合同及其直接要求的参考后，第一条项目命令必须是下方公开的 `prepare_context.py`；不得先用
`rg`、`rg --files`、`find`、`git status` 或其他命令枚举项目、`.ai-sow` 或插件，也不得先运行
`--help`。该命令本身是 Requirement 与 As-Is handoff 的唯一启动门禁；成功后 Stage 只读取其
`context/manifest.json` 点名的 fragment 和完成专业设计确需的原始 source anchor，不复读完整上游
artifact 或无关 work-only 目录。

`context/source-anchors.json` 同时保留证据的逻辑 `reference` 和可读取文件的项目相对
`resolvedPath`，并投影登记的 repository/prior SOW snapshot。Stage 读取证据原文时只使用
`resolvedPath`，不得从 `<repoId>:<anchor>` 猜测磁盘路径；逻辑 `reference` 继续用于追溯，不能被
`resolvedPath` 替换进稳定业务数据。

fragment 采用唯一事实投影：`business-requirements.json` 只含 BUSINESS Epic/Feature，
`effective-start.json` 只含 Effective Start/Item/Commitment；source document、normalized item、
Evidence、repository/prior SOW snapshot 只存在于 `source-anchors.json`。Stage 不跨 fragment 重复读取
同一集合，也不自行把这些集合复制到新的 work-only 文件。

两份 candidate 的 Owner-local 合同固定为 `<skill-root>/contracts/design.schema.json` 与
`<skill-root>/contracts/technical-requirements.schema.json`。closure 成功后 Stage 可按这两个精确路径
各读取一次；不得用 `ls`、glob、`rg` 或目录枚举寻找 Schema，不得读取 fixture/test 代替合同，也不
得先猜测插件级 `schemas/` 路径。

## 工作流

1. 当前 Stage 是本 Skill 的唯一用户接口，第一条项目命令直接运行 `prepare_context.py`，由它验证 Requirement 与 As-Is receipt。任一上游 handoff 为 missing、invalid、stale 或 unsupported 时，原样报告对应 Owner 并停止；不重跑上游 validator，不修改上游稳定数据。除第 11 步的一个 Reviewer 外，普通流程全部工作都由当前 Stage 直接完成。
2. `prepare_context.py` 把 BUSINESS Requirements、As-Is Coverage、Uncertainty、Effective Start 与 source anchor 收敛为 `.ai-sow/work/generate-design/context/` 的确定性闭包。当前 Stage 只读这个闭包和 manifest 点名的必要原始来源，在 `.ai-sow/work/generate-design/` 保存分析。
3. 相对于 Effective Start 形成目标方案、Design Item 和 Architecture Delta。`CARRY_FORWARD` Commitment 是待交付工作；重要 Uncertainty 必须形成设计决策、prerequisite、定向 evidence request 或 scope boundary。
4. 为每个 BUSINESS 和 TECHNICAL Feature 恰好给出一个 `IN_SCOPE`、`FULLY_COVERED` 或 `OUT_OF_SCOPE` Scope Decision。`IN_SCOPE` 引用 Design Item，并显式声明 `requiredIntegrationBoundary` 与 `requiredDecisionKinds`；每项类型化义务由关联 Design Decision 与 Evidence 履行。`FULLY_COVERED` 引用有 Evidence 的 Effective Start；BUSINESS Feature 还需同组 `COMPLETE` Coverage。
5. 来源明示的技术要求编译为 `SOURCE_INPUT` TECHNICAL Epic/Feature，并追溯到已登记 `sourceDocumentId` 与具体 `sourceReferences`。设计决策产生的技术要求使用 `DESIGN_DERIVED`，并严格遵守[派生理由合同](references/derived-rationale.md)。Task 可实施性反馈只细化已有 Design Decision、Design Item 或职责相同的 TECHNICAL Feature；不得仅因实现机制新增 Feature，也不得要求下游修改已批准的 Story/AC。只有用户明确批准新的独立交付结果时才新增 Feature 并交由 `generate-story` 评估。
6. 每个 Design Decision 同时关联 Design Item 与 Feature；非 `NEW` Architecture Delta 引用 Effective Start。孤立 Design Item、把 `CARRY_FORWARD` 标为 `FULLY_COVERED`，或 `affectsEstimate = true` 的 Uncertainty 均阻止门禁通过。
7. 当前 Stage 一次形成两份 work-only candidate：`.ai-sow/work/generate-design/design.candidate.json` 与 `.ai-sow/work/generate-design/requirements.candidate.json`。两份候选共同构成一个评审版本；任一份变化都使整个版本失效。
8. 当前 Stage 按[评审模板](references/review-template.md)形成 `.ai-sow/work/generate-design/review-source.json`，再运行 `render_review.py` 确定性生成 `.ai-sow/work/generate-design/review.candidate.md`。评审必须包含两个固定门禁：

   `targetDesign`、`architectureDeltaReview`、`designDecisionReview`、`scopeReview` 与
   `technicalRequirementsReview` 只总结专业结论，不得手写 Design Item、Architecture Delta、
   Design Decision、Scope Decision、TECHNICAL Epic/Feature 或 BUSINESS Feature 的对象数量。
   `render_review.py` 从当前两份 candidate 确定性投影唯一 `Structure Counts` 声明；候选修正后
   重新 renderer 即自动更新计数，避免 review-source 与 candidate 漂移。

   - `## 高阶设计覆盖门禁` 与精确声明 `HLD Coverage: PASSED`；
   - `## 上线范围门禁` 与精确声明 `Go-live Assessment: PASSED`；
   - 紧随上线门禁使用固定七列矩阵：`Concern | Disposition | Feature IDs | Effective Start IDs | Evidence IDs | 责任边界 | 依据`。

   矩阵必须恰好列出 `PRODUCTION_SCOPE`、`ENVIRONMENT_CONFIGURATION`、`DEPLOYMENT_CUTOVER_ROLLBACK`、`DATA_MIGRATION`、`PRODUCTION_VALIDATION`、`OBSERVABILITY`、`OPERATIONS_HANDOVER`、`POST_GO_LIVE_SUPPORT`、`USER_ENABLEMENT`、`LEGACY_RETIREMENT` 十项 Concern。每项只能选择 `IN_SCOPE / FULLY_COVERED / OUT_OF_SCOPE / NOT_APPLICABLE`，并给出责任边界和依据。`IN_SCOPE` 必须关联 TECHNICAL Feature；`FULLY_COVERED` 必须关联有 Evidence 的 Effective Start；`PRODUCTION_SCOPE` 不得为 `NOT_APPLICABLE` 且必须关联 TECHNICAL Feature。数据迁移与生产发布范围必须使用不同 Feature。
9. 对 `IN_SCOPE` 上线 Concern 新增或复用职责单一的 TECHNICAL Feature；对 `FULLY_COVERED` 记录证据；对 `OUT_OF_SCOPE / NOT_APPLICABLE` 明确责任和依据。若合同购买专职驻场、固定班次、待命容量或 24×7 支持，生成 `affectsEstimate = true` 的 Uncertainty，转入独立服务容量模型或单独支持 SOW，并保持 `BLOCKED`。
10. 当前 Stage 直接运行以下确定性脚本；`--mode review` 验证两份 candidate、HLD/Go-live、provenance、context 与 risk summary，并用固定算法 `ai-sow-owner-review-packet-v1` 写入 hash-bound `review-packet.json`。此时 `.ai-sow/reviews/generate-design.md`、两份稳定 JSON 和 validation receipt 必须都不存在或保持原值：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/prepare_context.py" --project-root .
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/render_review.py" --project-root .
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" --project-root . --mode review --review-path .ai-sow/work/generate-design/review.candidate.md
   ```
11. 当前 Stage 只启动一个不继承当前完整聊天的全新 Reviewer Agent。Reviewer 以当前 packet、评审、风险摘要、闭包和必要来源独立审查专业遗漏、HLD/Go-live、范围边界及两份候选忠实度。首次失败时，当前 Stage 只允许一次整体修复，并重新检查所有新增或变化对象后交回同一 Reviewer 完整复审；第二次仍失败则 `BLOCKED`。Reviewer PASS 后 Stage 只运行“精确 Reviewer 绑定”命令，用固定算法 `ai-sow-owner-reviewer-v1` 写 `reviewer.json`，绑定精确 packet SHA-256。
12. 将 Reviewer 已绑定的同一 packet 提交用户。用户明确批准 Owner 与精确 packet SHA-256 后，用固定算法 `ai-sow-owner-approval-v1` 写 `approval.json`；候选、上下文、review、risk 或 input 任一字节变化都必须重新生成 packet 并重新整体评审、批准。
13. 当前 Stage 只运行 `--mode publish-approved`。确定性脚本校验两个 sidecar 后，按 candidate 原字节同时发布 Design 与 TECHNICAL requirements、正式 review 与 0.3 receipt；不得在此阶段重做分析、改候选或启动 Reviewer：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" --project-root . --mode publish-approved --review-path .ai-sow/work/generate-design/review.candidate.md
   ```
14. 直接上游 receipt 变化而专业结论不变时，在正式 review 中记录 `Impact: NO_CHANGE`、旧/新 receipt hash、全部稳定 ID 的影响理由，并只运行 legacy `--mode rebind`。Reconciliation Adapter 继续使用 legacy `--mode check`、`--mode publish` 与 `--mode rebind`；rebind 必须证明两份稳定输出原字节均未变化。
15. receipt 发布后报告完成，推荐用户显式调用 `generate-story`，然后停止；不得自动启动下游 Skill。

## 字段质量

Epic 与 Feature 的 `description` 只描述技术背景、范围和能力。`involvedSystemsData`、`targetOutcome`、`commonConstraintsOutOfScope` 和 `constraintsNfr` 仅在分析有具体价值时生成；无证据时省略，不填空泛占位。

## 完成条件

目标设计与所有 TECHNICAL 需求已获批准，两个输出原字节同时发布且 receipt 成功签发。下游完整需求仅在内存中联合 BUSINESS requirements 与 TECHNICAL requirements；本 Skill 不修改业务需求，不创建第三份合并 JSON，也不自动推进下一 Skill。

## Reconciliation Adapter

仅当用户显式调用 `ai-sow:reconcile` 且提供 `Reconciliation Run ID`、整体 review SHA-256 与项目内
staging root 时，本 Skill 作为 Design Owner Adapter 运行。它继续独占 TECHNICAL requirements、
HLD/Go-live、两份候选的同时发布、`check/publish/rebind` 与写集合；reconciliation 不解释或重放
这些规则。它复用 reconciliation 的外层 Stage、一个 Reviewer 和一次 hash-bound 用户批准；外层
Stage 直接调用本 Owner 的确定性脚本，并收集 Owner 影响段、脚本原始结果与两份候选忠实度。本内部
模式不在本阶段 STOP，也不调用 Story；普通独立调用保持原合同。实现机制细化未改变业务交付结果时，必须明确
要求 Story Adapter 使用 `NO_CHANGE`，不得反向改写 Story/AC。

候选校验可在 `--mode check` 中用 `--review-path <project-relative-posix-path>` 读取本次 reconciliation
为 Design Owner 编译的 work-only review 投影；该路径同时作为 Design review 与 HLD/Go-live 门禁
诊断路径。上游 Owner review 仍使用各自固定路径。`publish` 与 `rebind` 禁止 review override，必须
回到固定 `REVIEW_PATH` 发布 Owner receipt。整体 review 本体只作为投影携带的批准 hash 绑定来源，
不直接传给 Owner-local `validate.py`。
