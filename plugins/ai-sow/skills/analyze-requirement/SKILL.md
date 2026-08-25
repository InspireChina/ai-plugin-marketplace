---
name: analyze-requirement
description: 当 AI SOW 项目需要从业务简报、招标文件、研讨会记录或利益相关方陈述中确认业务范围、目标、规则、优先级或验收意图时使用。
---

# 分析业务需求

本 Skill 是 BUSINESS requirements 的唯一 Owner。它形成来源、归一化条目、Epic 和 Feature；技术要求与设计问题保留在已登记来源中，由 `generate-design` 处理。

执行前完整读取并遵守[输出语言合同](../../references/output-language.md)。业务自由文本使用简体中文，合同 token、ID、路径与 hash 保持原值。

## 当前任务与 Reviewer

- 当前 Stage Agent 就是当前 Codex task，也是本 Skill 的唯一用户接口：直接与用户协作，完成来源登记、业务分析、问卷关闭、candidate、确定性 review 投影、机械校验和最多一次整体修复。不要为 Stage 工作另派 Agent。
- 只有 candidate 通过机械校验并形成 hash-bound `review-packet.json` 后，才创建一个 fresh Reviewer Agent。Reviewer 不继承当前完整聊天，只读取 packet、其中绑定的 candidate、context、review、risk summary 和项目内来源；它只返回 `PASS` 或带证据 findings，不修改文件。
- 同一次调用最多创建一个 Reviewer。第一次有 findings 时，Stage 进行一次整体修复：重新检查全部来源、业务范围、关系、问卷处置和稳定 ID，而不是只改被点名字段；随后重建 context、review 与 packet，并交给同一 Reviewer 完整复审。第二次仍有 findings 时返回 `BLOCKED` 并停止。
- 确定性脚本是机械门禁，不是 Agent。原样报告 outcome、diagnostics、hash 与 receipt，不解释或放宽失败。

Reviewer 不可用、packet 无法稳定绑定，或需要的用户事实仍缺失时返回 `BLOCKED`。不得让 Stage 自审，也不得创建第二个 Reviewer 规避 findings。

## 路径与生成前合同

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`，将用户项目根目录解析为 `<project-root>`；执行前把命令占位符替换为绝对路径。

Stage 开始完整分析前必须读取：

- `contracts/source-requirements.schema.json`；
- `fixtures/requirements.valid.json`；
- `references/review-template.md`；
- 需要澄清时的 `references/requirement-clarification-questionnaire.md`。

先向用户说明：本阶段会形成的 BUSINESS 结论与稳定输出、已登记来源、当前充分输入、会改变业务范围/目标/规则/优先级/验收意图的缺口、需要用户回答的问题，以及必须保持 `BLOCKED` 的事项。

## 专业分析与问卷门禁

1. 只在 `.ai-sow/inputs/analyze-requirement/` 登记用户提供的来源，保存稳定 `sourceDocumentId`、项目相对路径、原文件名和 SHA-256；稳定数据不保存来源原文。
2. 只分析业务结果、参与者、范围、规则、优先级、验收意图、冲突和未知项。明确技术内容保留在来源中，不产出 TECHNICAL Epic/Feature。
3. 信息缺口会改变业务结论时，按问卷参考维护 `.ai-sow/reviews/analyze-requirement-questionnaire.md`。`Blocking: YES` 必须在创建 Reviewer 前成为 `CLOSED`；非阻塞默认只有用户明确接受后才可为字段完整的 `APPROVED_DEFAULT` 与 `ASSUMPTION_CANDIDATE`。
4. 用户答案改变业务结论时，先更新完整 BUSINESS candidate；不要把开放问题、猜测或技术答案包装成稳定业务结论。

critical questionnaire 未关闭时，不运行 `prepare_context.py`，不创建 Reviewer，也不写任何正式 review、data 或 validation 路径。

## Candidate-first 评审

Stage 在 work-only 路径形成完整候选：

```text
.ai-sow/work/analyze-requirement/requirements.candidate.json
```

然后依次运行：

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/prepare_context.py" \
  --project-root "<project-root>"

uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/render_review.py" \
  --project-root "<project-root>"

uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode review \
  --review-path .ai-sow/work/analyze-requirement/review.candidate.md
```

`prepare_context.py` 固化当前项目、已登记来源和问卷终态的 Owner-local closure。`render_review.py` 从 candidate 确定性投影专业评审材料。`--mode review` 重新校验 Schema、来源字节、BUSINESS Owner-local ID/关系、问卷终态和 review 声明，写入：

```text
.ai-sow/work/analyze-requirement/context/manifest.json
.ai-sow/work/analyze-requirement/review.candidate.md
.ai-sow/work/analyze-requirement/risk-summary.md
.ai-sow/work/analyze-requirement/review-packet.json
```

`review-packet.json` 的固定算法 token 为 `ai-sow-owner-review-packet-v1`；它是本 Owner 的审批合同，不进入公共 runtime。

Reviewer 必须检查来源与证据、业务范围遗漏、Epic→Feature 关系、冲突、未经批准猜测、问卷处置、验收意图和稳定 ID，并核对 candidate 与 review 的编译忠实度。`PASS` 后 Stage 写 canonical sidecar：

```json
{"algorithm":"ai-sow-owner-reviewer-v1","decision":"PASS","owner":"analyze-requirement","packetSha256":"<packet-sha256>"}
```

路径固定为 `.ai-sow/work/analyze-requirement/reviewer.json`。在用户批准前，以下正式路径必须保持原字节或不存在：

```text
.ai-sow/reviews/analyze-requirement.md
.ai-sow/data/analyze-requirement/requirements.json
.ai-sow/validation/analyze-requirement.json
```

## Hash-bound 批准与发布

向用户提交完整 `review.candidate.md`、风险摘要和 packet SHA-256。用户必须明确批准当前 `analyze-requirement` packet 的精确 hash；泛化的“继续”或旧版本批准不能复用。批准后写：

```json
{"algorithm":"ai-sow-owner-approval-v1","decision":"APPROVED","owner":"analyze-requirement","packetSha256":"<packet-sha256>"}
```

路径固定为 `.ai-sow/work/analyze-requirement/approval.json`。随后只运行：

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode publish-approved \
  --review-path .ai-sow/work/analyze-requirement/review.candidate.md
```

`publish-approved` 重新计算并核对 context、input、candidate、review、risk summary、Reviewer 与 approval 的全部 hash。任一字节漂移都必须重新 review 和批准；失败不写正式路径。通过后把 candidate 与 review 原字节发布到正式路径，并发布 validator contract `0.3` receipt。

## 上游影响复核

项目元数据、正式 review 或问卷证据变化但 BUSINESS requirements 原字节不变时，可使用现行 `NO_CHANGE` 流程；来源字节的 SHA-256 是稳定 requirements 的权威字段，因此来源字节变化始终是 `CHANGED`，必须回到完整 candidate-first review 与精确 packet 批准。

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" \
  --project-root "<project-root>" --mode rebind
```

`rebind` 必须证明稳定 requirements 与上一成功 receipt 完全一致，只更新当前 inputs/review 绑定。

## Reconciliation Adapter

仅当用户显式调用 `ai-sow:reconcile` 且提供 `Reconciliation Run ID`、整体 review SHA-256 与项目内 staging root 时，本 Skill 作为 Requirement Owner Adapter 运行。它继续独占 BUSINESS rules、candidate 编译、`check/publish/rebind` 与写集合，但复用 reconciliation 的外层当前 Stage、一个 Reviewer 和一次 hash-bound 用户批准；确定性 Owner 命令由外层当前 Stage 直接调用。Owner 输出写入 staging view，并把影响说明、机械检查原始结果和候选忠实度返回外层当前 Stage；此内部模式不在本阶段 STOP，也不调用下游。

候选机械检查可用 `--review-path <project-relative-posix-path>` 读取 work-only Owner review；该 override 允许 `check/review/publish-approved`，legacy `publish/rebind` 继续只绑定正式 review。`check/publish/rebind` 是 reconciliation/兼容 adapter，不得替代普通调用的 candidate-first 授权链。

## 完成与停止

receipt 发布后，报告稳定输出与 validation 的项目相对路径，只推荐用户显式调用 `analyze-as-is` 及其所需输入，然后 STOP。不得自动调用下一 Skill，也不得修改其他 Owner 的稳定数据、合同或已安装插件文件。
