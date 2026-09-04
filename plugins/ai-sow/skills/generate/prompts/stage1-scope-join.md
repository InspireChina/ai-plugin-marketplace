# Stage 1 Global Scope Join

遵守 Author 角色/输出合同，并读取全部已验证 InputItem、ScopeProposal、boundary summary、跨 shard affinity、全量 ID/计数和适用交付政策。

按来源权威处理 PRD 与选入 Demo 的需求并集；冲突不得静默覆盖。`BUSINESS / TECHNICAL / DELIVERY` 是工作性质而不是来源角色。只从批准 HLD/ADR 规范化 DesignItem、Integration 和 NFR，Demo 不得证明后端、数据、集成或部署设计。

全局唯一决定 Epic/Feature，并让每个 InputItem 恰有一个 `scopeClosure`：`SCOPE_NODE / PROJECT_GATE / OUT_OF_SCOPE / CONFLICT`，同时给出 delivery disposition、Feature 落点、限定词引用、跨 Feature 目标和设计覆盖状态。不得留下未处置 InputItem。

创建 Integration 时，`responsibilityBoundaryIds` 只能引用 packet 给出的同名清单；清单为空时不得虚构责任边界。

实例化 `policy-sit-automation`、`policy-uat-automation` 和 `policy-go-live`；`policy-data-migration` 仅在允许的来源明确命中时实例化。不要生成 Story、AC、Task，不要补写技术方案。

返回普通 `PATCH`，只写 Stage 1 区域；InputItem 已由 Source Scan 冻结，除非是同一语义的精确合并，否则不要重写。
