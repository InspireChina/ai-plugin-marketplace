# Owner 上下文纪律

该条款由五个专业 Owner 共用，目标是减少携带税和重复读取。

1. 先读取 Owner-local `context/manifest.json`。
2. 在一个工具回合内把 manifest 点名的 fragment 各读取且只读取一次。
3. 不预先加载完整上游 artifact、完整仓库、完整来源或完整工具输出。
4. 后续回合不使用 `jq`、`sed`、`rg` 或其他命令重新筛选、摘要或复读 fragment；需要的新事实只按 claim anchor 定向读取。
5. Reviewer 只获得当前任务必需的 claim、anchor、patch diff、影响闭包或完备性清单，不继承 Stage 的完整聊天历史。

如 manifest、fragment 或 anchor hash 变化，重新生成闭包；不复用旧摘要。
