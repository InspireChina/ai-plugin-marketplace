# Delivery 动态拆解与回退

各阶段对象定义分别见 Epic、Feature、Story、AC 与 Task 的专门规则。本页说明如何从证据逐层拆解，并在边界不成立时回退，而不是用层级数量包装工作。

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
2. 对每个 Feature 枚举触发者、对象、动作、状态、下游结果和责任。Story 必须命名一个可独立移交并关闭的具体结果，并把具体交付物或能力、负责方或消费者、独立验收边界、独立关闭或发布边界作为共同证据核验；不能因某个目标、指标、质量属性、政策类别或控制集合可测试或可验收就准入。Technical Story 还须由来源或已批准设计明确支持一个可独立运行或消费的机制、配置、证据包或运营能力；控制归组、验收活动或指定验收人不足以准入，标题不能只写复核、测量、取证或合规确认。排除项目级 SIT/UAT、通用 DoD 和没有独立成果的支持活动。
3. Stage 1 checkpoint 通过后，由 `delivery_compiler.derive_story_obligations` 从 `scopeClosure.deliveryDisposition=STORY_AC_REQUIRED` 和 effective policy decision 重算带 hash 的 obligation projection。它保留并列指标、阈值、责任、禁止项、变化触发、限定词、Feature 路由和覆盖对象；候选 Story/AC 引用不能成为义务来源。
4. Stage 2 按 Feature affinity 与 token 预算动态分批。每个 packet 携带紧凑的项目级 obligation routing，并只分配当前 shard 的完整义务与候选无关证据。所有 sibling action 成功后一次性应用 patch，再从 projection 双向重算 Story/AC 闭包；不按固定 Feature 数或固定对象数切分。
5. 闭包成立后，对 Story 的全部 AC 一起识别所需交付物，再与 Design、Integration、NFR、Effective Start 和当前模板目录共同推导 Task。AC 与 Task 是多对多，不按“一条 AC 一个 Task”机械生成，也不反向改写已经成立的 Story/AC 语义。

## 原子义务的落点顺序

对每个原子目标或控制，按以下顺序决定落点，不能用测试性跳过前两步：

1. 找出其约束的每个具体 Story，并向每个适用 Story 添加可追溯到来源的 AC；同一语义义务可因此在多个 Story 中出现不同的 AC ID。
2. 若它项目级适用且没有 Story 特定行为，则保留在 NFR、DoD 或质量门禁，不制造 Story。
3. 自动化、性能、安全或合规测试可以在之后成为受影响 Story 下的 Task 工作，但测试性不能制造目标或控制 Story。
4. 只有剩余工作是一个具体机制、配置、证据包或运营能力，且同时具备自己的交付、责任或消费者、验收和关闭或发布边界时，才可成为专项 Technical Story；拆开无关的剩余结果，绝不保留数据治理或服务水平的兜底 Story。

业务控制若只在已有业务触发（例如提交、审批或查询）中执行，先成为每个受影响业务 Story 的 AC；即使规则跨越多个 Story，也不能因此建立共享控制 Story。只有来源或已批准设计明确支持一个可独立运行或消费、可独立关闭的共享能力时才可保留该 Story。

来源规定阈值时，每个适用 Story 的 AC 或项目级质量/NFR 门禁必须保留该阈值。报表或仪表盘 Story 可以交付显示或测量能力，却不能以此关闭阈值满足义务。

## 反向回退

| 发现 | 回退动作 |
| --- | --- |
| Epic 只有一个孤立能力 | 回看是否应降为 Feature，或是否遗漏同一价值流的来源范围。 |
| Epic 名称只能靠“平台”“保障”“闭环”等抽象词容纳多个主题 | 检查 Feature 是否属于异质领域；按共同投入理由重新划分 Epic 或把 Feature 移回真正拥有它的业务域。 |
| Feature 只有一个很小的结果 | 下调为 Story，或与相邻能力合并。 |
| Story 出现并列触发、对象、状态闭环或多个可独立结果 | 拆成多个 Story。 |
| Story 的唯一结果是目标、指标、质量属性、政策类别或合规陈述 | 回到适用的具体 Story，把该义务作为来源可追溯的 AC；项目级且没有 Story 特定行为时放入 NFR、DoD 或质量门禁。测量、报告阈值或符合陈述本身不构成 Story。 |
| Shared control Story 只汇集在提交、审批、查询等已有触发中执行的控制 | 回到所有受影响业务 Story 的 AC；规则跨切面并不等于共享能力。只有来源或已批准设计明确支持、且可独立运行或消费并关闭的共享能力才可单列。 |
| 阈值只被写入测量、报表或仪表盘 Story | 把阈值写回全部适用 Story 的 AC 或项目级质量/NFR 门禁；显示或测量能力不关闭阈值满足义务。 |
| Technical Story 包含多个 NFR 目标族或不相关控制 | 指标可以分别测试并不自动产生多个 Story；只有每个候选结果同时具备具体交付物或能力、责任或消费者、独立验收、独立关闭或发布边界时才拆分，否则作为适用 Story 的 NFR/AC 或一个共同技术结果承载。 |
| AC 只能靠示例或惯例补齐 | 回到来源；合并或澄清 Story，不杜撰 AC。 |
| Task 需要多个独立交付物或隐藏多个接口 | 拆 Task；若由此暴露多个结果，回退拆 Story。 |
| 无法确认起点、模板匹配或边界 | 形成精确问题、假设或有边界的设计/调研工作；不能猜测估算。 |

## 跨层复核

从任一 Task 反查到 Story、AC、Feature、Epic 与已验证 InputItem；从每个 obligation 反查到至少一个受影响 Story/AC 或明确的项目级处置。某项只能由范围外组织承担时，应保留责任边界而非进入 Delivery。

## Story/AC 阶段收敛

Story/AC 收敛由持久化 ActionRecord 与随后生成的 `STORY_AC` checkpoint 证明，不依赖同一主对话的历史。审计逐项确认：obligation projection 的 hash 与 Scope checkpoint/effective policy decision 一致；全部 assigned obligation（含阈值、对象、禁止项、变化触发和限定词）已落到所有适用 Story/AC；同质重复对象保留在一个 Story 的 `coverageSet`，独立定制、责任、验收或发布边界已拆分；Technical Story 只使用来源或批准设计支持的结果。此阶段 `tasks` 与 `dependencies` 保持为空，不读取估算模板，不以 Task 填补来源、Story 或 AC 缺口。

审计发现上游范围缺陷时，必须按返回的最低恢复阶段发出新的 hash-bound 修复动作并重建受影响 checkpoint；不得在下游区域绕过或补丁上游。发现 Story/AC 缺陷时回到 Story/AC Owner。进入 Task 阶段后，才检查已成立 Story 下有界需设计项、Task 的 Design/Integration/NFR 引用、AC 覆盖和依赖；Task、模板或实现词汇始终不能弥补来源、Story 或 AC 缺口。
