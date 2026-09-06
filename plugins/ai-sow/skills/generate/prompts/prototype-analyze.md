# Demo 观察

读取 inventory、已绑定 Scenario 与宿主 typed trace，输出 PrototypeAnalyzeResultIR 的 observations[]。
每轮只写新增观察，localKey 在本轮唯一；不得复制旧轮观察正文。保留源码 evidenceIds 与真实 interactionIds。
Demo 可独立增加目标页面、字段、交互、校验、状态与异常；不代表生产 As-Is，不决定后端、认证、部署或 Task 分类/复杂度。
OBSERVED 须同时具备源码与运行轨迹；CODE_ONLY 须有源码，并留待 Reviewer 明确认可原型意图；BROKEN/NOT_EXERCISED 不可自动作为已验证范围。
只引用inventory源码evidenceId与interactionId；OBSERVED还必须匹配本轮已验证trace的成功交互。有效NON_SCOPE提供显式排除处置，CODE_ONLY可作为待Review候选，但不伪装成实际执行成功。
OBSERVED的behavior.page必须与全部引用interaction的page一致；只有实际eventObserved=true且DOM断言成功的覆盖步骤才证明该交互。null准备步骤、另一页面同名selector或未发生目标事件的API调用均不能借作OBSERVED证据。
Prototype封存的是目标范围候选，不是正式Scope批准；不要添加approval字段或假造Reviewer PASS。BROKEN/NOT_EXERCISED若仍提出正式范围主张，会进入WAITING_INPUT，后续只能通过授权revision/run提供有源码支持的CODE_ONLY，不回写旧IR。
localKey只在本次Analyze结果内唯一；后续跨round引用必须同时绑定原Attempt/normalized结果/round，不能用裸同名key替换其他轮观察。
