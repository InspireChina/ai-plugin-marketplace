# Owner 上下文纪律

该条款由五个专业 Owner 共用，目标是减少携带税和重复读取。

1. 先读取 Owner-local `context/manifest.json`；manifest 固定记录 fragment 顺序、canonical hash、
   每页 hash、`pageByteBudget: 32768`、`pageTokenBudget: 8192` 与 token estimator。
2. 严格按 `fragments[].pages[].order` 读取，每页且只读取一次。完整 fragment 文件只供机械校验，
   Stage/Reviewer 不绕过分页合同直接加载大文件。
3. 不预先加载完整上游 artifact、完整仓库、完整来源或完整工具输出。
4. 后续回合不使用 `jq`、`sed`、`rg` 或其他命令重新筛选、摘要或复读 fragment；需要的新事实只按 claim anchor 定向读取。
5. Reviewer 只获得当前任务必需的 claim、anchor、patch diff、影响闭包或完备性清单，不继承 Stage 的完整聊天历史。

任何被工具截断的 page 都视为 `NOT_READ`，不是部分完成。恢复时使用同一 manifest，从第一个未完成
page 继续；不重读已完成 page，也不临时改变预算或重新切页。如 manifest、fragment、page 或 anchor
hash 变化，重新生成闭包；不复用旧摘要。
