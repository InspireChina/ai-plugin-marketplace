# Delivery 动态拆解与回退

静态对象定义见[Delivery 编写导航](delivery-authoring.md)。本页说明如何从证据逐层拆解，并在边界不成立时回退，而不是用层级数量包装工作。

## 正向拆解

```text
来源与 Scope
  -> Epic：完整价值流或长期能力
  -> Feature：可感知、可归责能力
  -> Story：可独立关闭结果
  -> AC：有精确来源的可观察证明
  -> Task：满足全部 AC 的独立实施单元
```

1. 先从来源确认价值目标、责任和范围，建立 Epic 与 Feature；不要按文档标题、系统、页面或工种分层。
2. 对每个 Feature 枚举触发者、对象、动作、状态、下游结果和责任，以一个可独立关闭结果形成 Story；同时排除项目级 SIT/UAT、通用 DoD 和没有独立成果的支持活动。
3. 在工作上下文建立一次性来源义务清单：把段落中的并列指标、阈值、责任、禁止项和变化触发拆成原子义务，保留全部判断条件和限定词，标明每项义务的实际触发与适用 Feature/Story。先提取成功结果，再仅在明确适用时补充校验、状态、异常、Integration 或 NFR 约束；每条 AC 绑定最小充分 `sourceRefs`，重复支持同一判断的锚点不进入集合。
4. 在进入 Task 前做一次双向 Story/AC 闭包检查：从每个 Story 正查 AC 是否与其触发和结果一致；从每条来源义务反查全部适用对象是否都有 AC 落点或明确排除。每个 `IN_SCOPE` Feature 的来源结果、跨 Feature 规则、会影响验收的 Integration/NFR 均须关闭，且每条 AC 来源可解析。发现遗漏时只回到 Epic/Feature/Story/AC 修正，不用 Task 填洞。
5. 闭包成立后，对 Story 的全部 AC 一起识别所需交付物，再与 Design、Integration、NFR、Effective Start 和当前模板目录共同推导 Task。AC 与 Task 是多对多，不按“一条 AC 一个 Task”机械生成，也不反向改写已经成立的 Story/AC 语义。

## 反向回退

| 发现 | 回退动作 |
| --- | --- |
| Epic 只有一个孤立能力 | 回看是否应降为 Feature，或是否遗漏同一价值流的来源范围。 |
| Feature 只有一个很小的结果 | 下调为 Story，或与相邻能力合并。 |
| Story 出现并列触发、对象、状态闭环或多个可独立结果 | 拆成多个 Story。 |
| Technical Story 混合容量、性能、可用性、驻留、权限等独立目标族 | 按可独立验证的目标族拆 Story，并回看是否需要调整 Technical Feature 归属。 |
| AC 只能靠示例或惯例补齐 | 回到来源；合并或澄清 Story，不杜撰 AC。 |
| Task 需要多个独立交付物或隐藏多个接口 | 拆 Task；若由此暴露多个结果，回退拆 Story。 |
| 无法确认起点、模板匹配或边界 | 形成精确问题、假设或有边界的设计/调研工作；不能猜测估算。 |

## 跨层复核

从任一 Task 反查到 Story、AC、Feature、Epic 与来源；从任一来源反查到至少一个受影响对象或明确排除理由。某项只能由范围外组织承担时，应保留责任边界而非进入 Delivery。
