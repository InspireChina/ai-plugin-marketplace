# AI SOW generate-task 性能 A/B 记录

日期：2026-08-25

状态：流程隔离 A/B 与自然专业拆分认证均通过；Owner 推广、E2E 与 release certification 待执行。

关联设计：[AI SOW 性能优化设计修正](2026-08-25-ai-sow-performance-optimization-design.md)

## 1. 评测问题

本次评测只回答：当 Task 专业决策保持不变时，candidate-first、Owner-local context、确定性
review renderer、单 Reviewer 和 hash-bound 批准是否减少 generate-task 的 Agent 编排成本，同时
保持发布质量。

它不回答模型对任意项目从零形成 Task 专业决策的准确率，也不代替完整主线 E2E、reconciliation
E2E、Windows 或 Excel Desktop 认证。

## 2. 控制变量

- Codex CLI：`0.149.0`；
- 模型：`gpt-5.6-terra`；
- reasoning effort：`medium`；
- 两个全新、无历史聊天的 session 并行启动；
- 两边均忽略用户配置与项目 rules，显式启用 multi-agent；
- 两边使用相同 warm `.venv` 状态和项目内 `uv` cache 策略；
- 项目输入树 SHA-256：`49e7ab25d7646b91772b876cf126333a48549dac4ee66a05901ccde887143c1b`；
- 同一份冻结 Task 决策作为项目输入，避免专业拆分随机性污染流程比较；
- 两边都经历“准备到批准点”和“明确批准后发布”两个 turn；
- 两边都必须通过本版本 validator 的独立发布后 `check`。

唯一处理变量是 generate-task Skill 与其实现：

- baseline Skill SHA-256：`4af0142d88473eee036bc27b06d8c89c945d5cac3ce714b24e78951e0116039e`；
- optimized Skill SHA-256：`ae26f0c247a6d255c3cfbf9ca3d521590f12cb37047695ebd4d8e5bea7aa11a0`。

token 数据取自 [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
所述 `codex exec --json` 的 `turn.completed.usage`；该接口把非交互执行输出为 JSONL，并报告
input、cached input、output 与 reasoning token。

## 3. 结果

| 指标 | Baseline | Optimized | 变化 |
|---|---:|---:|---:|
| 总 input tokens | 1,269,533 | 586,036 | -53.8% |
| cached input tokens | 1,203,712 | 527,360 | -56.2% |
| uncached input tokens | 65,821 | 58,676 | -10.9% |
| output tokens | 9,726 | 5,123 | -47.3% |
| reasoning output tokens | 2,003 | 597 | -70.2% |
| 总墙钟 | 277.797s | 155.051s | -44.2% |
| 批准后墙钟 | 100.647s | 24.245s | -75.9% |
| command executions | 26 | 16 | -38.5% |
| collaboration tool calls | 12 | 2 | -83.3% |

optimized 达到设计设定的“总 input token 至少降低 50%、端到端 wall time 至少降低 40%”流程
目标。uncached input 只下降 10.9%，说明本样本的主要收益来自删除重复的高缓存上下文和 Agent
roundtrip，而不只是缩短首次输入。

## 4. 正确性结果

两边均满足：

- 用户批准前没有稳定 Estimate 或 validation receipt；
- 用户批准后稳定 Estimate 存在；
- 两边稳定 Estimate SHA-256 相同：
  `3fa35832a66668f0477b9409ccd47e8f6d8fe55205f91c20c354ab168bdd60d8`；
- 两边稳定 Estimate 与冻结 Task 决策 JSON 语义完全相同；
- receipt `passed=true`；
- `validatorContractVersion=0.3`；
- 独立发布后 validator `check` exit code 均为 `0`；
- optimized 在批准前存在 candidate、review packet 和 `reviewer.json`，不存在正式 review、稳定
  Estimate 或 receipt；批准后只运行薄发布路径。

稳定 Estimate 与冻结输入的字节 hash 不同，但两版发布字节彼此相同、JSON 语义相同；差异只来自
模型采用的 JSON 格式化。Owner 仍按各自 candidate 原字节发布。

## 5. 排除样本与发现

在有效配对前运行的探索样本不进入上述百分比：

1. 首次续跑没有继承临时项目 cwd，导致两边均无法找到批准对象；这是评测器缺陷；
2. optimized packet 未绑定 context fragments，fresh-context Reviewer 无法取得允许证据；现已让
   packet 绑定 context manifest 和五个 fragment；
3. Stage 修复 candidate 后手工 review 遗漏 Effective Start；现已由 deterministic renderer 从
   candidate 和模板整体重投影；
4. 合成输入的 `L` 理由缺少两类环境证据，且 review 未展开 Base Unit count/include/exclude 边界；
   Reviewer 正确阻塞，评测输入与 renderer 均已修正；
5. 第一轮自然样本在一次修复后仍遗漏 Delivery 中三项开放风险，Reviewer 正确 fail closed；因此
   `review` 模式现把开放 Delivery 风险确定性投影到 hash-bound risk summary；
6. 第二轮自然样本在一次修复后仍把跨系统观测链路标为 `M`，Reviewer 再次 fail closed；因此 Skill
   明确一次整体修复必须重新检查全部新增和变化 Task，不能只修 finding 点名字段；
7. 上述阻塞样本均未产生正式 Estimate、review、validation receipt 或 approval，不计入有效发布样本。

## 6. 自然专业拆分认证

自然样本不提供冻结 Task 决策。两个有效发布样本复用同一冻结输入树
`a4df7f91258ffeeece5a202d46bfefa43832e4f594de30f4791fb11da1bb9588`、同一 Skill 字节、模型、
reasoning effort、warm cache 和干净 session；第一 turn 自然拆分并停在 `REVIEW_REQUIRED`，批准
turn 只绑定精确 packet 并运行 `publish-approved`。

| 指标 | 自然样本 1 | 自然样本 2 |
|---|---:|---:|
| Task / Story / AC / Integration | 27 / 23 / 31 / 4 | 30 / 23 / 31 / 4 |
| Reviewer Agent | 1 | 1 |
| 整体修复与同 Reviewer 复审 | 1 | 1 |
| 总 input tokens | 1,465,449 | 1,522,738 |
| cached input tokens | 1,359,360 | 1,428,224 |
| uncached input tokens | 106,089 | 94,514 |
| output tokens | 14,901 | 14,650 |
| reasoning output tokens | 2,206 | 2,031 |
| 总墙钟 | 421.31s | 约 445.7s |
| packet SHA-256 | `ec1335f5...c9d5` | `e6a046b7...bf236` |
| Estimate SHA-256 | `6af3b325...791c` | `60269df2...b531` |
| 发布后独立 `check` | `OK` | `OK` |

两个样本都满足：Reviewer `PASS` 前零正式写入；Reviewer 与 approval 精确绑定同一 packet；candidate
与正式 Estimate 原字节一致；receipt contract 为 `0.3`；未调用 `generate-sow`。自然拆分存在合理
输出波动，但没有改变合同完整性、模板权威或 fail-closed 语义。

另以第二个有效候选构造机械合法的预埋遗漏：删除安全与隐私专项验证 Task，但保留其他 Task 对
`ac-test-automation` 的机械覆盖。确定性 `review` 返回 `REVIEW_REQUIRED`；fresh-context Reviewer
随后根据 TECHNICAL requirement、Delivery 和模板中的 `BU-SECURITY-PRIVACY-TESTING` 精确定位遗漏
并返回 `BLOCKED`。该样本未写 `reviewer.json`、`approval.json` 或任何正式文件，证明机械 validator
与专业 Reviewer 的职责边界有效。

## 7. 结论与剩余门禁

`generate-task` 的流程架构优化方向成立，自然拆分、重复样本、专业遗漏检出和精确发布均已通过，
可以冻结为 candidate-first 生命周期参考合同并推广到其他专业 Owner。

后续仍需：

1. 把同一生命周期按 Owner-local Adapter 推广到其余四个专业 Owner；
2. 简化 `setup`、`generate-sow` 并适配 reconciliation 审批前完整闭包；
3. 刷新已安装插件缓存后，再运行普通主线 happy-path、reconciliation/sad-path E2E；
4. 最后执行完整 release certification。
