# 阶段自动封存

公开编译使用唯一的 `SCOPE → STORY_AC → TASK` 流程。每个 Owner 根据完整冻结输入生成一个 StagePlan；全部分组都由通用 scheduler 选择，组内工作数不得超过原规划政策的 `maxConcurrency`。不得截断 work 列表、动态补建旧 group plan 或改写已发行 Envelope。

每阶段顺序固定：全部必需工作取得有效成功 Attempt → 当前 sealed IR 物化一次 → 完整机械验证 → fresh singleton Review → 可选一次自动 singleton Repair → 新语义 revision 物化、验证和 fresh Review → PASS checkpoint。`MATERIALIZE` 与 `VALIDATE` 分别在真实调用前检查 active-time，真实计算结束后先写现有 `DETERMINISTIC_STEP_FINISHED`，成功 payload 另绑定 `stageKind / semanticRevision / outputSha256`，再发布该完整输出。MATERIALIZE hash 覆盖整个 Review input（候选、图、Prior、索引与义务），VALIDATE hash 覆盖完整 validator result。恢复要求同一步骤的成功事件 hash 全部一致，文件唯一且逐字节匹配；已发布完成输出不重复计算。对于 Owner 的 MATERIALIZE/VALIDATE，若完成事件已落盘而输出尚未发布，守卫预算后重算未发布输出，与原 hash 比较并记录恢复运算的真实新区间；失败事件不能授权输出。该扩展沿用唯一 RunEvent 类型族，不增加 receipt、start/reservation event 或预算计数存储。

Review 输入只含候选、来源引用、全部当前 Owner root localKey 到候选 ID/path 的索引（含 EXCLUDE/RETIRE 的 scopeAnnotations），以及必须逐项判断的 review obligations。恢复还从已封 Owner IR 与原来源独立推导精确 root 索引；Scope 复用唯一稳定 ID 规则（含 parent/Prior 身份），Story/Task 复用原 node bindings，同名节点不能交换映射。Reviewer 不继承 Author 历史。`ReviewDecisionIR` 只有 `decision` 和 `findings`；PASS 无 finding，其他决定至少一个 finding。决定为 `PASS / REPAIRABLE_SEMANTIC / INPUT_REQUIRED / CONTRACT_GAP / OWNER_BUG`。SYSTEM 属于 Attempt failure，不是模型 Review 决定。

`REPAIRABLE_SEMANTIC` 或下述经过明确实施澄清的 Task INPUT_REQUIRED 允许 Repair。每个 finding 的 subjectId 必须是当前 Owner root localKey；Repair 复用该 Owner 的同一窄 IR schema，定向提交受影响对象的完整 replacement decisions。指定 roots 可原位调整、合并为一个已有 localKey，或拆为 `root:repair:<suffix>`；删除的义务必须由保留对象完整承担。Scope 的 `authorizedRootKeys` 另含引用问题 roots 的传递影响闭包，未返回的闭包对象默认保留。程序逐字段保留其它 roots，保存旧 IR、候选和 Review。只有后继 PASS 才关闭触发 Repair 的全部 findings；第二次仍有未解决的语义 finding 时停止自动修复。Task 的 INPUT_REQUIRED 可在用户提供下述精确实施澄清后追加一次修复；三个 Owner 达到自动上限后，可按下述人工裁定逐次继续一个候选。

Review 的 identity 为 `{stageKind, actionKind:"REVIEW", candidateSha256, actionContractSha256}`；Repair 的 identity 为 `{stageKind, actionKind:"REPAIR", reviewDecisionSha256, actionContractSha256}`。二者均以 canonical identity 的 SHA-256 生成 `logical-` ID，再从 `{logicalWorkId}` 生成 `control-group-` ID。实际输入确定后才发行 singleton，不在 StagePlan 中预留未来工作。

StageCheckpoint 精确绑定 `stageKind / inputRevisionSha256 / upstreamCheckpointSha256s / stagePlanSha256 / effectiveAttemptRecordSha256s / candidateSha256 / validatorResultSha256 / reviewPacketSha256 / reviewDecisionSha256`。Scope 有 Prior 时另含 `priorStateSha256`；零 Prior 时省略。有效 Attempt 集包含实际计划工作、Review、已发生的 Repair 及其失败重试；Scope 还包含全部实际 Prototype preprocessing Attempt。

Prior 原工作簿仅在准备时提取一次。大 Sheet 按完整证据行确定性分区；单元格正文只保存在 evidence 中，保留原 ID、A1 位置、哈希和全部结构元数据，原始标题/表头作为只读上下文。分区不改变证据授权，不截断内容，也不将分区视作业务边界。唯一 Prior root 必须先通过业务验证，之后才可发行依赖它的 Scope 工作；合法冲突、unsupported、cycle、overlap 等可以成为成功执行事实，但不能产生 snapshot 或放行 Scope。Scope 恢复从冻结 inventory 与实际 Prior 根独立重建 snapshot，并从 sealed Scope decisions 与该 snapshot 独立投影 ChangeGraph 后逐字段比较；不以待验证 Review input 自身作为证明。Story/Task 只消费本轮授权的 immutable snapshot/ChangeGraph。Scope Reviewer 必须独立判断 visible-ID 保留与完整来源等价，部分重合不能机械推断为完整 DUPLICATE。

Demo 全部有序 Scenario/Browser/Analyze 轮次封存后才冻结 Scope StagePlan。必须保留早期独有观察与完整 Attempt chain。采用 CODE_ONLY 观察时，Review packet 枚举完整原始 ObservationIR 正文、result/Attempt hash、round 和候选证据；PASS 明确确认这些业务意图。缺少 obligation、意图未获认可或不相关 PASS 都不能关闭 Scope。

hydrate 只解析已发行 packet 授权的来源引用。返回 `{refId, canonicalContent, contentSha256}`，最多两轮，同一 evidence ID 不重复发行；原文来自本轮不可变来源，Prior 不重新打开工作簿。Task 可用 `task-rule:<workTypeId>` 请求冻结目录中该项、相邻项和 challenger 的当前规则。完整 provider request 包含这些 response，由同一 estimator 检查实际容量；同时遵守 Envelope hydrate 上限和本轮 active-time 门禁。

绑定校验的 `INVALID_IR` 沿现有 AttemptDiagnostic 保留具体 code、JSON path 和 root subjectIds，并进入原有 Attempt repair context；不增加重试轮数、异常字段或事后修改失败记录。缺少具体定位的旧校验仍使用通用 `INVALID_IR`。

每次新 Action 发行前检查实际已用、未完成预留和整个拟发行组的预算；实际 dependency/repair request 超容量进入 `WAITING_INPUT`，不重新分组。政策替换先完成已经物理发行的旧 Envelope 事务，既不改写原政策也不重复发行/计费。`status` 只读取并验证完整证据链。

阶段 PASS 自动继续，没有 stage/packet/预算批准。业务输入改变时 abandon 当前 run，以完整新 request 从头 start；新 run 不以旧 generation 或隐藏缓存决定业务内容。

新 run 的来源仅为本次完整 request 明列的原始文件；Brownfield 的 declaredChangeContext 随本轮 Scope context 冻结，往期 SOW 只来自明列的 PRIOR_SOW。预算替换必须严格增加至少一项 token、active-time、未来请求的上下文容量或 Demo 限额，正文相同也拒绝；如果发布事件已完成但返回中断，以不带 policy 的 resume 恢复。

Scope 的 DECLARED_CHANGE_CONTEXT obligation 绑定本轮 input revision 和原声明正文；fresh Review 必须对照候选判断。恢复从冻结 scope-context 重建义务，缺失或改变声明即拒绝，不以 Review input 自身证明。


## 最终工件后缀

三个 checkpoint 完整复读后，ARTIFACT 依次执行 MATERIALIZE（投影）、OFFICE、OFFICE_REFERENCE、VALIDATE（双复读和完整审计）、RENDER（真实 Office PDF 与全部可见 Sheet 分页）和视觉 PASS 后的 FINAL_VALIDATE。每次实际调用前复用同一 active-time guard，实际区间与完整输出 hash 写入同一 DETERMINISTIC_STEP_FINISHED；已开始的 Office 不受 active-time 强制中断。超额后不进入下一步骤或封存 manifest。恢复沿用内容寻址完整输出。RENDER 在写成功完成事件前，先用 ProjectFiles 的持久写入保存真实 Office 导出原字节；若事件已完成而正式步骤输出未发布，恢复在预算守卫后复读事件 hash 绑定的暂存，校验精确字节并记录本次恢复 I/O 区间，不重新导出 PDF。没有成功事件的孤儿暂存不能授权复用，篡改必须拒绝；旧运行没有暂存时仍执行重算和原 hash 精确比较。其它步骤保留原恢复重算规则。Office 字体替代可能令重复 PDF 导出字节不同，不能通过忽略差异或重新接受 hash 绕过绑定。

最终 XLSX 和 renders 通过 publish_new 冻结，之后发行唯一 ARTIFACT_VISUAL_REVIEW。identity 精确为 `{stageKind:"ARTIFACT",actionKind:"ARTIFACT_VISUAL_REVIEW",workbookSha256,orderedRenderSha256s,actionContractSha256}`；使用 REVIEW/MODEL_PROVIDER 和 revision 1，INVALID_IR/执行重试复用同一 Attempt ledger。VisualReviewDecisionIR 保留全部可见 Sheet 的顺序，无集合排序；只允许逐 Sheet checks/decision/findings 和 overallDecision。合法 FAIL 保留成功执行事实并进入 MANUAL_REVIEW_REQUIRED，不产生批准 manifest。

全部验证通过后才发布 ai-sow-artifact-manifest-v2 并进入 AWAITING_FINAL_REVIEW。ArtifactManifest 的 visualReview 只保存成功 attemptRecordSha256；portable proof bundle 复读实际完整 Attempt→Envelope→packet/result、三个 checkpoint、原候选及确定性完成事件。输出校验失败不产生正式 ArtifactManifest、GenerationManifest 或 current。批准只复制已冻结字节，generation 保存完整离线证明，不回写或重新回算 XLSX。

上下文容量只能在相同 modelProfileId/estimatorVersion 下单调增加，并由宿主核实实际模型容量。已发放 Envelope、原 policy、StagePlan、输入、输出与 Attempt 字节保持原值；未发放的 retry/Review 才绑定新 policy。若预算等待中的 retry 在旧容量下仍无法发行，先发布明确增加的 policy，再恢复该 retry；不清零用量或重试计数，不重做已封存阶段。输出/hydration reserve、并发与模型 profile/estimator 变化仍需要新 run。


## 生成后定向修复

大体正确的结果优先通过现有 Repair 收敛，覆盖 Scope、Story/AC 和 Task；不因某个下游问题重做已 PASS 的上游。Task Repair 可以让一个实际资产覆盖授权 roots 中多个既有 Story 的 AC，保留一个主 Story、全部 AC 和政策/设计关系，只计量一次。普通 Author 仍不得任意跨 Story 借用覆盖。每轮 replacement 只能重新分配本轮受影响 roots 已有的 AC；历史累计授权只保留已接受的共享覆盖，不扩大后续无关修复的范围。提交入口在封存成功 Attempt 前检查这条约束，越界按 INVALID_IR 正常重试；物化与 proof 回放重复核验。物化、提交、恢复和 checkpoint proof 都核对同一确定性授权上下文。

Task 修复上下文对重复 Story 正文使用 `ai-sow-task-repair-context-v1` 字典引用；展开后必须与绑定 packet SHA 完全相等，全部义务和证据仍保留。尚未发行的 Repair 超容量时，`resume` 可重建并重新守卫当前完整请求；在原 policy 内通过后才发行。既有 `WAITING_INPUT_EXITED` 使用 `FITTING_UNISSUED_REPAIR`，绑定等待期间真实发行的 actionId/envelopeSha256；中断恢复沿用该 Action。既有输入、StagePlan、Attempt、checkpoint 和使用量不修改。总预算不足或已有 Repair 的执行 retry 不借此绕过限制。

阶段尚未发行任何计划工作便因容量等待时，修复无损输入分组后可从原 run 公开 resume。已完成 Prototype 继续复用。完整计划和第一组请求重新通过现有预算守卫后，`FITTING_UNISSUED_PLAN` 绑定 stagePlanSha256/groupId 与等待期间的实际发行证明；发行前后中断均复用同一计划和 Action。已有计划工作、冻结计划、模型容量、总预算、历史使用量均不能借此重置或改写。

Prior 行分区中的实体可引用当前 packet 已授权、同一 source 和 Sheet 的其他行分区证据，且至少保留所属 localKey namespace 的一个 anchor。跨 Sheet、跨 source 或其他 Action 未分配的行不在授权范围；headerEvidence 只解释表头。越界使用 `PRIOR_ENTITY_PARTITION_BINDING_INVALID` 定位。

Prior Analyze 的行分区 Attempt repair 可采用 `ai-sow-lossless-tables-v1` 传输：同构对象数组改为 columns/rows/path，解码后的 canonical packet SHA 必须与原 packet 完全相同；重复 path、列、行宽或内容漂移均拒绝。原 packet、原失败输出和完整结果 IR 保留。该无损表示只减少本地请求估算，不证明实际 provider token 节省或输出上限。

INVALID_JSON/INVALID_IR 后尚未发行的 retry 若因输入容量等待，当前完整请求在原预算内变得可容纳时，可公开 resume。`FITTING_UNISSUED_RETRY` 绑定原失败 record、Envelope、packet 和合同以及实际新 Action；等待退出前后中断复用同一发行证明。失败记录、累计消耗、冻结计划和重试次数保持原值。

宿主为每次原生调用保存独立请求、输出、事件和结束记录，按 Action group deadline 设置有限等待。重入时先核实进程与已有证据；中断或超时作为 EXECUTION 提交，再沿正式 Attempt retry 继续。保留旧 bytes/hash；无 completion usage 或可靠退出码时明确 unknown，并把协议所需本地估算与真实 provider 用量分开。

已持久化的 ABANDON 决定恢复成 DONE 后即结束恢复后缀，移除 active marker 后不再进入容量恢复。artifact 取证从不可变 Task checkpoint 绑定候选，并从授权事件及原终态复读预览修复链；离线取证不依赖可变当前候选。


## 既有目标内的实施澄清

Task Review 的 INPUT_REQUIRED 若仅缺既有批准目标内的实施决定，可通过 `resume --decision <path>` 提交 `owner-clarification.schema.json`。该不可变决定绑定当前 candidate SHA、真实 Review decision SHA、当前问题 Task 的既有 technicalTargetKeys、明确决定与 USER/SIMULATED_USER 授权来源。它不修改原 HLD，不新增上游范围、组件、环境或当前状态事实。格式、目标或候选不匹配时拒绝。

决定保存于本 run 的 Task clarifications，既有 WAITING_INPUT_EXITED 以 OWNER_CLARIFICATION 绑定其 SHA 与原 Review SHA。Repair 和其后 fresh Review 都包含原决定；原 INPUT_REQUIRED 和全部失败记录保留。精确实施澄清最多追加一次候选；普通第二次 REPAIRABLE_SEMANTIC 不获得额外自动重试。累计修复上下文保留上一轮已修复的共享 AC、政策和起点证据，proof 从实际 Author IR 连续验证每次局部修复与后继候选，不能恢复已移除的重复计量。已记录决定和已发行 Action 在中断及重复提交时复用。


## 人工裁定后的局部继续

Scope、Story/AC 或 Task 因第二次及后续 REPAIRABLE_SEMANTIC 停在 MANUAL_REVIEW_REQUIRED 时，允许使用 `resume --decision <path>` 提交 `contracts/owner-repair-authorization.schema.json`，沿用原 run。用户可在本会话中提前授权代理模拟裁定；使用 SIMULATED_USER 并写明授权依据，无需重复请求同一授权。

决定精确绑定 runId、原 terminalStateSha256、当前 candidateSha256、失败 reviewDecisionSha256、完整 rootKeys 影响集与允许修改的 Owner 字段 allowedFields，additionalRevisions 固定为 1。只准调整既有字段，不能改 localKey、删除/拆分 root 或改其它字段；需要合并/拆分的普通 Repair 仍使用前述 root 变换。完整替换 IR 必须有实际变化，不能以相同候选重复碰运气。OWNER_BUG、CONTRACT_GAP、视觉 FAIL、已发布/放弃 run 和历史候选不能借此继续。另一个 run 已激活时拒绝旧 run 恢复。

不可变 OWNER_REPAIR_AUTHORIZED 事件绑定原终态、裁定、失败 Review 和累计 semanticRevision，先保存事件再接回 active 指针；中断后重放同一决定，不重发已有 Action。每条新裁定只授权一个后继候选；普通自动次数、全部 Attempt、tokens、时间和失败 Review 都不清零。没有新裁定仍保持停止。

同一 Owner 从原 Author IR 连续重放全部已发生 Repair，保留不受影响结果与上游 checkpoint。Repair 获得精确裁定，后继 fresh Review 同时携带仍生效的实施澄清及最新人工裁定，完整机械验证和独立 PASS 缺一不可。portable artifact proof 包含原终态、裁定正文及事件先后关系，离线重新验证候选、修改字段、累计次数和全部失败链；最终 Excel 只从新 PASS 模型投影。


## 已验证 Excel 的预览修复

视觉 FAIL 若来自预览呈现，可使用 `resume --decision <path>` 提交 `artifact-repair-authorization.schema.json`。决定绑定当前 run、原终态 SHA、同一 PASS 模型、真实失败视觉 Attempt SHA、已修 renderer SHA 与 `repairFromStep: RENDER`；USER/SIMULATED_USER 及授权依据必须明确。该入口只修显示，不能修改业务模型、Excel 或计价。XLSX 内容或计算问题不能冒充预览问题。

不可变 ARTIFACT_REPAIR_AUTHORIZED 事件建立连续 artifactRevision；新版本从 RENDER 继续，复用原 MATERIALIZE、OFFICE、OFFICE_REFERENCE 和 VALIDATE 的精确成功输出，不重新回算。旧工作簿、全部预览、失败视觉评审、事件和终态保留。新路径使用六位工件版本，Excel 逐字节复制，完整重新视觉检查全部 Sheet，再 FINAL_VALIDATE。重复提交同一决定复用当前动作，不重复执行。

Office 原始向量页面以不超过1200点的阅读窗口完整分页，相邻窗口重叠36点，保持原字号；长表和宽表按从上至下、每带从左至右浏览全部窗口。分页只是内部视觉检查的可读视图，完整 Excel 不改变；不是用户 PDF 输入路径。宿主必须把所有绑定页实际交给视觉 worker（例如原生图片附件），记录页号、SHA、完整清单和真实调用证据；仅给路径或依据行列数猜测不构成视觉验收。

portable proof 保留每次预览修复裁定、原终态、失败 Attempt，以及各步骤真正使用的 revision；复核最终 Excel 与全部先前已验证工作簿 SHA 相同。正式批准仍要求新视觉 PASS、全部深层证明和当前 artifact hash。
