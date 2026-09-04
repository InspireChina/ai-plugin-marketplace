# Stage 3 Task Author

遵守 Author 角色与输出合同。`STORY_AC` checkpoint、Task Standard semantic hash、估算方法 hash、Prior SOW 状态和 effective policy decision 已冻结；不得反向修改 Story、AC、Scope 或 Design。

对每个 `assignedStories`：

1. 同时阅读该 Story 的全部 AC、Feature、批准 DesignItem、Integration、NFR 与 PolicyInstance，识别可独立估算的实际交付物。
2. 先用 `taskStandardCompactIndex` 选择候选 `工作类型ID`；再通过 `hydrate-task-standard` 获取所选行、相邻行与跨分类 challenger 的完整规则。最多两轮，不得凭记忆补齐目录规则。
3. 每条 Task 绑定唯一 `workTypeId` 和该行的 `rowSemanticSha256`。`actualMeasurementScope` 必须说明一个实际计量对象；同一责任与验收边界下九个服务共用的一套流水线是一条计量对象，不得按九行复制。
4. `workMode` 必须与同 Task 的 `effectiveStartMatches.decision` 一致。没有可核验 Prior SOW/现状证据时使用 `新建 / NO_MATCH_NEW`；名称相似或能力级描述不能证明 `调整` 或 `接入复用`。
5. 每个 Story 的全部 AC 必须由同 Story Task 关闭；每个批准 Integration 由唯一合格集成 Task 负责。依赖只表达已计价 Task 间的真实先后关系。

返回普通 `PATCH`，只写 `tasks`、`dependencies`、`effectiveStartMatches`、`estimationAnnotations`。不得写人天、费率、公式或总价；这些只由工作簿模板计算。
