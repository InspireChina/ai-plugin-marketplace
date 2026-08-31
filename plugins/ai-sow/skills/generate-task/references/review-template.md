# Task 拆分评审

## Story → Task

逐个 Story 说明 Task 拆分，并证明每条 AC 至少由一个同 Story Task 覆盖。AC 与 Task 是多对多关系；多个 Task 可共同满足同一 AC，一条 Task 也可支持多条 AC，不得因 Task 计数口径反向修改 Story/AC。

Story Map: story-example=task-example
AC Map: ac-example=task-example
Stable IDs: task-example

## 基础单元

按项目模板的 37 项基础单元目录说明每个 Task 的单实例计数边界、包含内容和排除内容。

Base Units: BU-EXAMPLE

## 工作模式

逐项说明 `新建 / 调整 / 接入复用`；调整和接入复用必须点名 Effective Start，接入复用还要列出本项目侧可独立估算的交付承诺。

Work Modes: 新建

## 复杂度

按当前基础单元自己的 S/M/L 标准评审；S/L 写出实例相对 M 的具体偏离事实，命中 X 时先拆分或澄清。

Complexities: M

## 现状依据

列出 Task 实际引用的 Effective Start 稳定 ID；没有引用时使用 `NONE`。

Effective Start IDs: NONE

## Integration 一对一

每个顶层 Integration 恰好映射一个责任归属和 Story 一致的内部或外部系统对接 Task。

Integration Map: integration-example=task-example

## 遗漏 / 重叠 / 排除理由

说明没有遗漏 Story 或 AC；多个 Task 引用同一 AC 只表示共同满足该业务验收条件，不视为重复计价。另行证明没有重复计算基础单元、发布切换、诊断/整改或 Integration，并记录明确排除项。

Renderer 把“相同基础单元 + 相同 Effective Start”的 Task 组列为潜在实例碰撞，但不机械判定重复。Reviewer 必须按交付对象和计数口径把每组归为 `SAME_INSTANCE / DISTINCT_DELIVERY_OBJECTS / REUSE_CONSUMER`：同一实例只保留一个 producing Task；同一 API 下的外部业务操作与内部读模型等不同交付对象可保留，但应分别选择实际基础单元；消费方只有存在可独立估算的项目侧接入工作时才生成 `接入复用` Task。

Scope Review: PASSED
Potential Instance Collisions: <base-unit>@<effective-start>=task-example,task-example-two
Collision Classification: SAME_INSTANCE / DISTINCT_DELIVERY_OBJECTS / REUSE_CONSUMER

## 估算前提

记录本次实际使用的项目模板字节哈希；基础人天、复杂度倍率、SIT、UAT、风险、公式和取整仍只存在于模板。

Template SHA-256: <64-lowercase-hex>

## 审查与批准

Reviewer: PASS
User Approval: APPROVED

在普通 candidate-first 流程中，本模板先保存为
`.ai-sow/work/generate-task/review.candidate.md`。以上两行是拟发布的最终声明，只有
`reviewer.json` 与 `approval.json` 都绑定同一个 `review-packet.json` SHA-256 后才具有授权效力；
批准前不得把本文件写入正式 review 路径。Reconciliation Adapter 继续使用整体批准绑定。

上游变化且专业结论与 Estimate 稳定字节不变时增加以下 machine declarations；首次发布删除这些行：

```text
Impact: NO_CHANGE
Upstream: generate-story
Previous Receipt SHA-256: generate-story=<old-hash>
Current Receipt SHA-256: generate-story=<new-hash>
Impact Rationale: task-example 均确认不受影响。
```
