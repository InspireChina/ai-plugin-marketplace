# AI SOW 跨层终审合同

终审者必须在全新上下文中工作，只读取本文件、精确的 `review-packet.json`，以及 packet 的 `sourceRefInventory` 指向的 pending 来源快照。不得读取对话历史、Git 历史、旧 Owner 评审、未引用项目文件或其他客户材料。

## 输入与输出

- 输入 packet 已绑定 InputManifest、完整 Scope、完整 Delivery、ID 决定、ImpactPlan、模板哈希和机械校验结果。
- `acceptanceCriterionSources` 按 AC 给出所属 `storyId`、精确 `sourceRefs` 及可解析结论，是来源 → Story → AC 逐项复核表；不得用只看 Story 标题或抽样 AC 代替全量检查。
- 来源快照只用于核对已列出的 SourceRef。不得把来源全文复制到评审结果。
- packet 的 `allowedSubjects` 按 note category 给出唯一允许的 subject ID 清单。Reviewer 只能原样复制对应清单中的 ID，不得猜测、拼接或自由创建 ID。
- 输出只能是一个符合 `final-review.schema.json` 的 JSON 对象，不得创建用户批准 sidecar。
- `PASS` 不带 notes/questions；`PASS_WITH_NOTES` 的每条 note 必须绑定真实固定边界；`BLOCKED` 必须给出最少、去重、可由用户回答的问题。
- 接受终审时会从 packet 内 Scope/Delivery 重新计算同一清单；清单缺失或被改写时以 `FINAL_REVIEW_SUBJECT_INVENTORY_MISMATCH` 阻断。
- 准备终审会同时生成可读的 `review-material.md`。该材料依次说明项目名称、Epic/Feature/Story/AC/Task 数量、自然语言结论、包含范围、不包含范围、重要假设、风险和下一步；它不显示 packet 哈希、内部对象 ID 或阶段 token。
- 面向使用者的问题必须逐项展示“问题、为什么要问、答案决定什么、未回答后果”，不假设任何采购、甲方或乙方身份。

### 自包含输出合同

不得用 `status`、`outcome`、顶层 `summary`、单数 `subjectId` 或自由文本 question 代替合同字段。输出必须严格使用以下形状，且不得增加属性：

```json
{
  "contract": "ai-sow-final-review-v1",
  "runId": "<packet.runId>",
  "inputRevisionId": "<packet.inputRevisionId>",
  "scopeSha256": "<packet.artifacts.scope.sha256>",
  "deliverySha256": "<packet.artifacts.delivery.sha256>",
  "packetSha256": "<review-packet.json 原始字节的 SHA-256>",
  "decision": "PASS | PASS_WITH_NOTES | BLOCKED",
  "notes": [
    {
      "noteId": "<唯一 lower-kebab-case ID>",
      "category": "ASSUMPTION | RESPONSIBILITY | EXCLUSION | DESIGN_TASK | ESTIMATE_BOUNDARY | CHANGE_TRIGGER",
      "subjectIds": ["<从 packet.allowedSubjects[category] 原样选择>"],
      "summary": "<简短评审结论>",
      "sowNotesText": "<可进入 SOW 说明的固定边界文本>"
    }
  ],
  "questions": [
    {
      "questionId": "<唯一 lower-kebab-case ID>",
      "subjectIds": ["<真实受影响对象 ID>"],
      "question": "<用户可明确回答的一个问题>",
      "reason": "<缺失事实及其影响>",
      "decisionImpact": "<答案将如何改变范围、责任或估算>",
      "unansweredEffect": "<未回答时为什么不能继续>"
    }
  ]
}
```

`scopeSha256` 与 `deliverySha256` 分别直接复制 `packet.artifacts.scope.sha256` 和 `packet.artifacts.delivery.sha256`；`packetSha256` 对读取到的 `review-packet.json` 原始字节计算 SHA-256，不对 JSON 重排后再算。`PASS` 时两个数组都为空；`PASS_WITH_NOTES` 时 `notes` 至少一项且 `questions` 为空；`BLOCKED` 时 `questions` 至少一项。

## 必查清单

1. 来源忠实度：业务结果服从 PRD，目标实现机制服从 HLD；二者冲突不得静默调和。
2. Brownfield 起点：往期承诺已经逐项处置，Effective Start 有来源、适用边界和复用依据。
3. Scope 完整性：Feature、Design、Integration、NFR、假设、责任和排除项彼此一致；所有 `IN_SCOPE` 结果均有可交付落点。
4. Delivery 追踪与粒度：Epic 是完整业务线、业务域或长期技术能力域，Feature 是用户可感知且可归责的模块；两者名称应是稳定领域中的名词或名词短语。只有一个 Feature 的 Epic、只有一个 Story 的 Feature、机械一一对应、用抽象词连接异质能力的 Epic，或把业务能力塞入无共同投入理由的技术主题桶，都必须复核。每个 Story 恰属一个 Feature、至少两条 AC；标题应自然表达单一角色或对象的动作，并命名一个可独立移交和关闭的具体结果。准入共同核验具体交付物或能力、负责方或消费者、独立验收边界、独立关闭或发布边界；不可把某个阈值可验收误作独立边界。Technical Story 还必须有来源或已批准设计明确支持的可独立运行或消费机制、配置、证据包或运营能力；控制归组、验收活动、证据收集或指定验收人不能创造该结果，标题不得只是复核、测量、取证或合规确认。逐项检查 `acceptanceCriterionSources`：每条 AC 必须可观察、忠实覆盖来源要求的正常结果及适用异常/边界/NFR，且来源中每个会改变范围的用户动作、展示结果、状态变化、校验、权限和异常路径都已落入恰当 Story/AC 或明确排除。每个原子目标或控制必须先落到它约束的每个具体 Story 的来源可追溯 AC；授权、状态或政策控制若只在提交、审批、查询等已有业务触发中执行，必须落到每个受影响业务 Story 的 AC，跨切面不是共享控制 Story 的理由。项目级且没有 Story 特定行为时留在 NFR、DoD 或质量门禁。测量、报告阈值或符合陈述本身，以及目标、指标、质量属性、政策类别或异质控制集合，不是独立 Story。阈值必须保留在每个适用 Story 的 AC 或项目级质量/NFR 门禁，报表或测量 Story 不能关闭阈值满足义务。自动化、性能、安全或合规测试只可在已成立的 Story/AC 下成为 Task，不能反向证明 Story 准入。只有残余工作是一个由来源或已批准设计明确支持、可独立运行或消费的机制、配置、证据包或运营能力，并共同具备自己的交付、责任或消费者、验收、关闭或发布边界时才可成为 Technical Story；拆开不相关残余结果，不能用数据治理或服务水平兜底 Story 汇总。来源义务逐项闭包不能被解释为一项义务一个 Story。Story 的 1–5 个工作日只作经验参考；不得根据工作簿中的 Story 人天阻断评审，拆分判断只依据来源、Epic、Feature、Story 与 AC 的语义、边界和可独立验收性。
5. Task 流程边界：确认 Owner 先完成 Story/AC 来源闭包，再从这些 Story/AC 进入 Task 拆分；每条 AC 仍须由同 Story Task 覆盖，Task 不得反向改写 Story/AC。本轮不对 Task 最终拆成哪些基础单元、实例数量、名称、工作方式或复杂度作语义判优，也不从模板示例发明能力；这些字段只接受现有机械合同和模板成员校验。
6. 设计与集成：需要设计的 Integration/NFR 有 DESIGN Task；每个需实现 Integration 恰好有一个 Integration Task；常规设计工作不得重复计价。
7. 增量连续性：受影响切片被完整替换；未受影响对象与 ID 保留；实质变化对象使用新 ID；删除对象不再被引用。
8. 责任与排除：供应商、客户、第三方的输入、环境、验收和依赖责任清楚；排除内容不能以笼统“支持”任务回流。
9. 隐私与呈现：不包含凭据、本机绝对路径、私有仓库信息、完整工具输出或无关客户原文；用户摘要中的 Feature/Story/Task 数量与 packet 一致。
10. 技术工作分类：全局 DoD、常规 SIT/UAT、未知未来缺陷和按工种拆分的工作不得伪装成独立 Story；Enabler、Spike、测试基础设施、迁移、发布或专项保障只有在有独立成果、AC 和证据时才可单列。结合 packet 的 `storyNoteProjection` 复核备注候选：Story 备注只承载当前对象特有、需要评审者关注的风险、假设、例外、依赖、边界或不确定性，不复读标题、AC 或 Task；跨 Feature 通用假设和多个 Feature 复制的同质文案只能进入 `sow-notes.md`，不得逐行投影。

终审是前述 `accept-delivery` 前内存语义收敛审计的独立复核，不替代该门禁。若 packet 显示原子义务、双向 NFR 适用性、Brownfield 承诺、Design Task、Story/AC 来源支持或 Task 引用仍未收敛，必须 return to Owner；不得将机械有效 candidate 直接当作可接受范围。

## 对 claims 的复核与处置

packet 的 `claims` 是机械层可确定的层级复核提示，不是自动拒绝或自动接受。`epicGrain` 的一个 Feature Epic、`featureGrain` 的一个 Story Feature 都必须由 Reviewer 结合来源和边界判断：如果该项目输入明确只授权一个独立、可关闭的范围切片，且该子项本身没有被人为包装为父层，**一个子项可以接受**；不得为了凑数量强行拆分。否则退回 Owner 合并、下调或拆分。机械层不得根据业务自由文本关键词推断额外 claim。

## 逐层问题

按每个对象逐项回答，并在 review 结论中记录不能由 packet 支持的最小问题或固定边界：

1. Epic：来源支持什么完整价值流、长期能力或明确范围切片？名称指向什么稳定领域能力，为什么当前 Feature 集合共享同一投入理由而不是被抽象主题词拼在一起？
2. Feature：谁可感知并归责该能力？名称指向什么稳定能力，为什么这些 Story 共同形成能力，而不是按工种、页面、实现机制或质量属性分组？
3. Story：它可独立移交和关闭的单一具体结果是什么？具体交付物或能力、责任或消费者、独立验收、独立关闭或发布边界如何共同成立？它是否只是目标、指标、质量属性、政策类别、控制集合、测量、阈值报告或合规陈述？每条 AC 如何通过可观察事实判定，且为何只引用当前项目的精确来源？
4. Task：是否只在 Story/AC 来源闭包完成后开始拆分，是否覆盖同 Story AC 且不跨 Story，是否没有反向扩大或改写上游语义？本轮不判断最终基础单元拆法、实例数量、名称、工作方式或复杂度优劣。

以下情形必须退回 Owner，而不是提交 `accept-review` JSON：Story 的唯一结果是目标、指标、质量属性、政策类别或合规陈述；Technical Story 没有来源或已批准设计支持的独立可运行/消费能力，却以控制归组、验收活动、证据收集或指定验收人凑成结果，或标题只写复核、测量、取证、合规确认；不相关控制因宽泛主题而被聚合；只在既有业务触发执行的授权、状态或政策控制被挪到共享控制 Story，或横切义务只挂在兜底 Story、却实际约束多个具体 Story；阈值仅被仪表盘、报表或测量 Story 记录，未保留在全部适用 AC 或项目级质量/NFR 门禁；或用测试/Task 证明 Story，而不是先建立有效 Story/AC 边界。

示例不具有证据效力：不得从示例、惯例或 Reviewer 自身经验发明 API、消息、技术选型、用户选择或性能阈值。发现来源不足时，退回 Owner：层级、AC 或来源归 Scope/Delivery Owner；模板实例、任务类型、工作方式或复杂度归 Delivery Owner；缺失且会改变范围、验收或估算的可回答事实才形成最小 `BLOCKED` 问题。Reviewer 只给出接受、固定边界 note 或最小问题的处置，不代替 Owner 补写业务或技术方案。

## BLOCKED 判定

只有同时满足以下三项才允许 `BLOCKED`：缺失事实会改变范围、验收或估算；无法由已有来源或固定边界推导；问题可以由用户给出一个明确答案。不得要求详细 API 字段、低层设计或额外用户批准，只要可以用 Design Task、estimate boundary 和 change trigger 固定风险。

## 已知可修正缺陷的返回路径

如果已有 packet 已能证明候选的层级、AC、Task、引用或模板匹配错误，且 Owner 能仅凭现有来源和 packet 修正、无需用户回答，Reviewer **不得提交 `accept-review` JSON**。这不是 FinalReview 的 decision enum：`PASS` 或 `PASS_WITH_NOTES` 会错误接受缺陷，而 `BLOCKED` 不能替代没有用户问题的 Owner 返工。应 return to Owner，并附上证据定位和最小修正反馈；由 Owner 重新编译候选、重建 review packet，然后以新的 fresh-context review 重新终审。

`BLOCKED JSON` 只保留给上述三项均成立、用户可以明确回答的缺失事实；不得用它表达已知且可由 Owner 在现有证据内修正的缺陷。
