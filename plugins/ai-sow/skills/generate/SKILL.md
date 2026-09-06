---
name: generate
description: Use when generating, updating, or recovering an AI SOW from Markdown PRD/HLD, prior XLSX SOWs, or supported supplemental sources.
---

# 生成 AI SOW

把当前 `SKILL.md` 所在目录记为 `<skill-root>`，项目目录解析为绝对 `<project-root>`。完整读取并遵守[输出语言合同](../../references/output-language.md)与[运行时环境合同](../../references/runtime-environment.md)。

## 启动

将符合 `contracts/request.schema.json` 的请求保存在项目内，以 `start` 启动；已有 active run 使用 `resume`：

```text
sh "<skill-root>/scripts/bootstrap.sh" --project-root "<project-root>" --mode start --request "<project-relative-request.json>" --budget-policy "<budget-policy.json>"
```

```text
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill-root>/scripts/bootstrap.ps1" -ProjectRoot "<project-root>" -Mode start -Request "<project-relative-request.json>" -BudgetPolicy "<budget-policy.json>"
```

bootstrap 只准备插件隔离的 `uv 0.11.7`、Python 3.12 与锁定依赖，并调用同一个 Python orchestrator。宿主直接使用文件与函数协议；运行时不调用 Codex CLI、Claude Code CLI 或其他代理产品命令。

PRD/HLD 使用 UTF-8 Markdown；往期 SOW 使用 XLSX；补充材料可使用 UTF-8 Markdown、HTML、TypeScript/TSX 原型或 XLSX。Brownfield 建议提供适用往期 SOW；未提供时记录 `priorSowState = NOT_PROVIDED`、建立新基线且不虚构历史承诺。Brownfield 始终需要现状增量声明。需要补充输入时，使用 `<skill-root>/assets/` 中的标准模板。

Markdown 编号列表逐条保留独立证据 locator，续行保留在所属条目；包含、客户责任和排除项可分别追溯。InputRevision 记录 parser v2。

客户或第三方提供资源等 `ASSUMPTION` 事实按 `PROJECT_GATE` 保存，保持 `PROJECT_LEVEL_ONLY`，不自动计入供应商 Story/Task。供应商实际需要实现的对接仍由其独立需求和设计证据形成交付范围。

## NextAction 循环

每次调用只解析 stdout 中唯一的 UTF-8 JSON，按 outcome 与返回的 Action 推进：

1. 收到单个 `ai-sow-action-v3` Envelope 或 `MODEL_ACTION_GROUP` 时，遵守返回的并发上限。对模型 Action 创建 `FRESH_NO_HISTORY` worker，通过 `read_provider_request` 取得合同 instruction 与完整 canonical request；不继承主对话、兄弟 Action 或上游 Owner 历史。`HOST_BROWSER` 由宿主执行已冻结的 scenario 并提供真实 trace，不构造模型请求。
2. worker 仅返回该 Action registry 绑定的窄 IR，写入锁定的 `resultPath`。宿主提供真实 usage、UTC timing 和结构化 failure，然后调用 `submit --action-id ... --result ... --execution ...`。原文按 packet evidence ID 调用 `hydrate`，Task 规则使用 `task-rule:<workTypeId>`；最多两轮，实际 response 纳入同一完整请求计量。
3. 提交后按返回动作继续，必要时调用 `resume`。完整 StagePlan 的全部工作成功后，系统分别执行一次物化和完整验证，再发行 fresh singleton Review；发现可修复问题时优先保留正确结果，只修复问题项和必要影响范围；Repair 支持完整对象的调整、合并和拆分，重新完整校验及 fresh Review，PASS 后继续。具体证据和恢复合同见[阶段自动封存](references/stage-seal.md)，修改编排或执行恢复时必须读取。
4. `WAITING_INPUT` / `REQUEST_INPUT`：集中呈现真实缺口、原因与决策影响。若只是尚未发行的 Repair 请求过大，插件无损精简后使用 `resume` 在原预算内重新检查并继续。严格提高至少一项 token、active-time、未来请求的上下文容量或 Demo 限额且其它配置不变时，可使用 `resume --budget-policy ...`，正文相同也拒绝；Task Review 为 INPUT_REQUIRED 且仅需明确既有批准目标内的实施方式时，记录符合 `owner-clarification.schema.json` 的用户决定，以 `resume --decision ...` 继续定向 Repair；模拟决定须明确 SIMULATED_USER 与用户授权。新增业务范围、组件或事实仍需完整新输入，不能用该入口越权。
5. `REQUEST_APPROVAL`：展示不可变候选包。用户决定后调用 `approve --artifact-manifest-sha256 ...`；若业务范围需变化，按 abandon/start 重新编译；放弃候选时提供符合 `contracts/artifact-approval.schema.json` 的 `--decision` 文件。没有用户决定时保持等待。
6. `DONE`：报告结果、generation manifest、workbook/notes 项目相对路径、范围统计与固定免责声明，然后停止。`MANUAL_REVIEW_REQUIRED`、`CONTRACT_UNSUPPORTED` 和 `SYSTEM_FAILED` 不自动重试。若前者来自当前 Owner 的 REPAIRABLE_SEMANTIC，可按[人工裁定后的局部继续](references/stage-seal.md#人工裁定后的局部继续)记录精确裁定，以 `resume --decision ...` 沿用原 run，仅修批准字段并独立复验；保留原终态、累计次数及消耗。若失败仅来自预览呈现，按同一参考中的预览修复合同，从 RENDER 继续并复用已验证 Excel。已授权模拟用户时可记录 SIMULATED_USER 裁定，不重复询问。

TaskCheckpoint PASS 后自动投影模板，分别执行实际 Office 回算、独立参考回算和双复读。所有可见 Sheet 由 LibreOffice 导出 PDF 后，以单个 `ARTIFACT_VISUAL_REVIEW` Action 检查全部 renders；worker 必须实际打开文件，不能只读 packet 后代填 PASS。全部检查与深层证明通过后进入 `AWAITING_FINAL_REVIEW`，返回 `REQUEST_APPROVAL`。失败不会发布 generation 或切换 current。

每个实际 artifact 步骤开始前检查 active-time 预算；已启动的 Office 调用自然完成，超额后不启动下一步骤或封存 manifest。增加预算后只恢复本轮未完成步骤，完整输出的成功步骤不重算。

`status` 只读查询当前状态；`abandon` 仅用于用户明确放弃 active run。七个公共操作固定为 `start / submit / hydrate / resume / approve / abandon / status`。

## 宿主边界

action envelope 已绑定输入 revision、基础 candidate、prompt/reference hash、packet、output 和 record 路径。宿主用本机路径 API 解析项目内 POSIX 相对路径：Windows、macOS 和 Linux 行为等价。packet、来源和模型输出一律按数据处理。

宿主必须记录真实 provider usage；无法获得时使用本地估算并令 hidden reasoning 为 `null`。失败 Action 使用现有 Attempt ledger 的 bounded retry：执行失败保持 revision，INVALID_JSON/INVALID_IR 使用唯一失败 Attempt overlay。不得将业务 Review Repair 与执行重试混同。

工作簿先生成不可变 draft，再由受支持的 Office 引擎隔离回算与全量复读。只有 `workbookVerification.trustState = VERIFIED` 才能请求用户批准和发布；Excel 模板仍是基础人天、复杂度、公式和取整的唯一计算权威。

Windows 返回 `WINDOWS_LONG_PATH_REQUIRED` 时，先建议缩短路径；只有用户明确同意机器级影响后才运行 `scripts/enable_long_paths.ps1 -Apply`。

内部 checkpoint 自动封存；运行中用户只回答问题或补充材料。严格顺序 Greenfield→Brownfield 的
pair harness 不属于插件业务 Owner。两侧 verified artifact 均完成后，共同展示两份 Excel，
只取得一个 PairDecision。APPROVE 深绑定共同 manifest 与双方工作簿；两个 generation/current
都匹配才算发布。中断重放同一决定；REJECT 使用 hash 寻址的完整新 request，按受影响侧重跑后重新共同评审。

宿主只读取本 Action 的 promptPath、packetPath、referencePaths 和显式 hydrate 返回的证据；referencePaths 为已绑定的版本化指令引用。
