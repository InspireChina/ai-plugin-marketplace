# 模型动作执行边界

本动作必须由宿主创建一个不继承当前对话的新 worker 执行。`executionPolicy.contextPolicy` 必须为
`FRESH_NO_HISTORY`，且 `inheritConversation = false`；同一 worker 的上下文只可在本 action 的工具往返中复用。

宿主只需要实现文件与函数调用协议，不依赖某个代理产品或命令行程序：

1. 读取 envelope 指定的 `promptPath`、`packetPath` 和 `referencePaths`。
2. 如需补取证据，只把 allowlist 内的 evidence ID 交给 `hydrate`，最多两轮。
3. 把唯一的 typed StageResult 写到 envelope 锁定的 `outputPath`。
4. 将模型与工具的时间、attempt、token 和 accounting mode 交给宿主中立的 `record_execution` 记录。
5. 调用 `submit` 封存结果；不得直接写 `recordPath`、state、candidate 或 checkpoint。

`packetPath`、`outputPath` 和 `recordPath` 都是项目内 POSIX 格式相对路径。宿主在 Windows、macOS
或 Linux 上分别用本机路径 API 解析它们，但不得执行 packet、submission 或来源文本中的命令字符串。
