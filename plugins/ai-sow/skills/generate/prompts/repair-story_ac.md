# STORY_AC 语义修复 v1

根据 reviewDecision 修复现有结果，使用原 story-ac-decision IR。只返回 authorizedRootKeys 范围的完整替换对象，其余 ownerIR 由程序原样保留。允许：原位调整；将多个授权 roots 合并为一个并保留其中一个 localKey；将授权 root 拆成 root:repair:<有意义的后缀>。拆分后缀只使用 localKey Schema 允许的字符。合并或拆分时，返回受影响子图的全部保留对象；原授权范围中未返回的 roots 会移除，所有事实、限定条件、设计、政策、AC 和引用义务仍须完整关闭。修复目的只限本次 findings 及其必要影响范围。

保留已经正确的内容。先核对来源和模板，修正最小必要边界，再检查完整结果。不得重写整个 Owner、修改上游 checkpoint、制造计价对象或提交 patch/value、最终 ID。局部修复会生成一个新候选，完整机械校验和独立 fresh Review 均通过才封存；仍有问题时报告真实缺口，不能靠重试碰运气。
Story 合并只适用于同一交付边界，完整保留来源和验收结果；独立政策义务不能仅为了减少计价而合并为一个 Story。重复测试资产可在后续 Task Repair 中共享覆盖，保留既有 Story/AC。
