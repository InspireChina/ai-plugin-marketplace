# TASK 语义修复 v1

根据 reviewDecision 修复现有结果，使用原 task-decision IR。只返回 authorizedRootKeys 范围的完整替换对象，其余 ownerIR 由程序原样保留。允许：原位调整；将多个授权 roots 合并为一个并保留其中一个 localKey；将授权 root 拆成 root:repair:<有意义的后缀>。拆分后缀只使用 localKey Schema 允许的字符。合并或拆分时，返回受影响子图的全部保留对象；原授权范围中未返回的 roots 会移除，所有事实、限定条件、设计、政策、AC 和引用义务仍须完整关闭。修复目的只限本次 findings 及其必要影响范围。

保留已经正确的内容。先核对来源和模板，修正最小必要边界，再检查完整结果。不得重写整个 Owner、修改上游 checkpoint、制造计价对象或提交 patch/value、最终 ID。局部修复会生成一个新候选，完整机械校验和独立 fresh Review 均通过才封存；仍有问题时报告真实缺口，不能靠重试碰运气。
ownerPacket 可能采用 ai-sow-task-repair-context-v1：packet 中 storyRef 指向 stories 字典，视为完整 Story 正文；程序展开后核对原 packetSha256。所有 work items、来源与模板目录仍完整保留。

重复计量修复先确定实际可交付的资产/实施对象，不能只删同名行或把重复新建改成收费复用。只有源证据支持独立脚本、环境、对象或验收边界时才保留多份资产。一个共享资产保留一个主 storyLocalKey，acceptanceCriterionKeys 合并其实际覆盖的全部既有 AC；technicalTarget 选择主 Story 的合法目标，evidenceIds 保留各部分的授权证据。TASK_REPAIR_AUTHORIZATION 限定可共享的原 roots；共享须处于同一批准目标或明确 Feature 范围。程序据此绑定各被覆盖 Story 的政策/设计引用，保留全部 Story 和 AC，只计算一个 Task。模式、类型、计量单位、复杂度和交付边界须一起复核。

TASK_EFFECTIVE_START 的 CURRENT_RESPONSIBILITY_COMMITMENT 只是对端可使用的明确责任承诺候选，原文和全部条件见 commitment。它不证明供应商侧集成已实现，不授权调整对端。按本轮权威模板的完整 modeRules 区分新建集成契约、现有对端保持不变的项目侧接入复用、以及已有对象调整；仅凭 EXTERNAL 或服务名称不能选择复用。接入复用确实适用时，将准确目标的候选 evidenceId 纳入该 Task。证据仍不足时如实保留疑点供 fresh Review 判断。
