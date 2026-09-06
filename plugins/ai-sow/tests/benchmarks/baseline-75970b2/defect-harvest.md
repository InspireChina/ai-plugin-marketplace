# 75970b2 部分基线缺陷收集

- 基线提交：`75970b2cadd6c298443b1d6016f99b34c8e3b25a`
- 状态：`PARTIAL_BASELINE_CHECKPOINT`
- 已完成样本：12
- 未计入样本：1（fresh Reviewer 未创建即进入空目标等待，宿主在确认无进展后终止）
- 隐私：只保留聚合计数、稳定错误码和匿名样本身份；不保存来源正文、完整工具输出或本机路径。

## 聚合观测

| 指标 | 观测值 |
| --- | ---: |
| 总墙钟 | 19,606,627 ms |
| `inputTokens` | 90,864,877 |
| `cachedInputTokens` | 88,910,720 |
| `outputTokens` | 720,700 |
| `reasoningTokens` | 144,264 |
| tool attempts | 1,042 |
| failures | 59 |
| repair waves | 23 |
| rereviews | 21 |

12 个已完成样本全部不可用于候选性能结论：5 个为 `FINAL_REVIEW_CONFLICT`，2 个为
`STORY_AC_RECEIPT_MISSING`，5 个虽完成语义发布但因工具失败或重复工作被判
`MODEL_EFFICIENCY_FAILED`。第 13 个样本没有 provider 完成收据，因此不混入上述统计。

## 缺陷簇与根因

### D1 — 长上下文中的自由文件与 shell 编排

旧流程让同一个 Owner worker 连续承担 Scope、Story/AC、Task、Repair 和发布，并让它自行选择文件编辑、
模板读取和 shell 工具。阶段结果、工具输出和返修历史因此持续占用同一上下文。样本中出现 `sed`/`jq`
引用错误、试探缺失工具、逐行解析 OOXML、错误解释工作目录和插件虚拟环境路径等重复失败。

根因不是某个 shell 命令写错，而是接口过浅：调用方需要知道阶段状态、候选路径、序列化方式、模板内部
结构和宿主工具。系统修复是 fresh no-history `ActionEnvelope`、path-locked submit、受控 hydration 和
插件内确定性工具；不把某个 POSIX 命令写进提示词作为修复。

### D2 — 破坏式下游清理与 checkpoint 生命周期不闭合

`accept-delivery` 在确认 Story/AC checkpoint 后又删除该收据。终审要求 Task-only Owner 返修时，合法的
再次 `accept-delivery` 因此返回 `STORY_AC_RECEIPT_MISSING`。Scope 返修还会清除下游 compiled candidate，
促使 worker 猜测不存在的 `delivery.candidate.json` 作为恢复来源。

短期修复保留仍与当前 foundation hash 匹配的 Story/AC 收据；目标架构使用顺序不可变 candidate、Owner
projection checkpoint 和最小后缀失效，不能通过删除整个下游目录表达失效。

### D3 — 终审输入与受管输出路径别名

Reviewer 可以把结果直接写到 `.ai-sow/work/final-review.json`，而 `record_review` 又把该路径视为已存在的
受管结果。pretty JSON 与 canonical JSON 的字节差异被误报为 `FINAL_REVIEW_CONFLICT`。

短期修复先完整校验输入，再按 canonical 语义比较；目标架构为每个 action 分配不同的 result/record 路径，
并绑定 `actionId + envelope + input revision + base candidate + resultPath`。

### D4 — fresh Reviewer 只有自然语言约定

第 13 个样本在声明要交给 fresh Reviewer 后，没有创建 Reviewer，直接进入空目标等待。旧公开流程没有
机器可执行的 Reviewer action、expected action ID 或超时后可恢复状态，所以宿主只能把该运行作为未完成
样本剔除。

系统修复是 `MODEL_ACTION` / `MODEL_ACTION_GROUP` 判别联合、expected action ID、deadline/attempt 和
stale-result 拒绝。Codex 与 Claude Code 都只作为这个宿主中立协议的 Adapter；插件运行时不依赖任一 CLI。

### D5 — Task 模板目录缺少稳定 Interface

模型只能从 XLSX 自行发现 88 行目录，因而试探 `xlsx2csv`、`ssconvert`、`xmlstarlet`、`xmllint`、`unzip`
或宿主相对 `.venv/bin/python`。这些路径既不跨平台，也把大量 XML/表格内容带回上下文。

系统修复是插件内 `TaskStandardCatalog` Module：一次解析冻结模板，返回内容寻址的紧凑索引，并只允许按
候选行 ID hydration 完整行。Windows 与 POSIX 共用 Python 实现和项目相对路径。

## 修复顺序

1. 先锁住 D2、D3 的最小回归并修复，避免合法返修和终审继续失败。
2. 按已批准计划建立 next contracts、正交 Run State、不可变 candidate 和 typed Action 生命周期，关闭 D1、D4。
3. 建立 `TaskStandardCatalog` 与受控 hydration，关闭 D5。
4. 完成跨平台纯测试和独立安装 smoke 后，以相同输入、模型、reasoning 与 cache protocol 重新运行配对 E2E。

本 checkpoint 不能代替完整五次冷/暖、三种规模和两个阻断场景的最终基线；它只证明继续运行同一旧流程
会重复消耗成本，足以支持先完成上述系统修复再恢复配对采样。
