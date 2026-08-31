# AI SOW Findings 驱动的在途协调优化方案

- 状态：方向提案，尚未实施
- 日期：2026-08-31
- 适用范围：AI SOW 首次生成中的跨 Owner findings、候选收敛、自动 handoff 与批准边界
- 相关背景：[多 Session E2E 最终分析](final-analysis.md)
- 相关目标设计：[决策驱动工作流重构设计](ai-sow-workflow-refactor-design.md)

## 1. 结论

本方案不新增 `converge-solution` Skill。现有 `reconcile` 扩展为两个协调模式：

```text
reconcile
├── IN_FLIGHT     首次生成中的候选收敛
└── POST_PUBLISH  已发布稳定产物后的修正
```

两个模式复用同一套 finding handoff、影响集、packet 与批准绑定，但保持不同的进入条件和发布语义。
`reconcile` 仍是薄协调层，只负责 finding 验证、Owner 路由、影响闭包、staging、整体 packet 和批准后
发布；Requirement、As-Is、Design、Story 和 Task 的专业判断继续由各自 Owner 独占。

`IN_FLIGHT` 不消除依赖拓扑。受影响 Owner 仍按上游到下游顺序执行，但正式批准和发布边界后移到
候选收敛之后，并只重新处理实际受影响的 Owner 或 subject。它解决的是重复 session、逐阶段重新
批准、稳定产物反复发布和人工判断回退路径的问题，而不是把有依赖的专业判断改成无序并行。

## 2. 问题描述

当前 AI SOW 主线按以下顺序推进：

```text
analyze-requirement
→ analyze-as-is
→ generate-design
→ generate-story
→ generate-task
→ generate-sow
```

该顺序提供了明确的数据所有权和批准链，但现有返工机制存在六个问题。

### 2.1 每个阶段都可能产生 findings

Findings 不是 `generate-task` 独有：

- Requirement Reviewer 可能发现来源遗漏或商业边界不明确；
- As-Is 调查可能发现证据不足、Effective Start 不成立或估算未知未关闭；
- Design Reviewer 可能发现职责、集成、上线或技术需求边界冲突；
- Story Reviewer 可能发现交付结果不可独立验收或 Integration 归属错误；
- Task 试拆分可能发现实现机制缺失、Story 不可估算或基础单元重复计价；
- SOW 生成可能发现 receipt 漂移、投影错误或生成器缺陷。

只设计 `Task → Design` 的特殊回退会把同类问题分散为多套临时流程。

### 2.2 当前阶段过早形成正式提交点

在下游可实施性尚未验证前，Design、Story 或 Task 可能已经分别评审、批准和发布。下游 finding
因此不只是修改 candidate，还会引发正式产物、review、receipt 和批准链的重新建立。

### 2.3 当前 reconcile 进入条件过晚

现有 `reconcile` 要求完整稳定下游链已经存在，适合 SOW 包生成后的维护修正，却不能处理首次生成
过程中“Design 和 Story 已发布、Task 尚未发布，但 Task finding 指向 Design”的状态。

### 2.4 自然语言 handoff 不可靠

如果 Owner 只返回“请回到 Design”之类自由文本，当前 Stage 需要自行猜测 correction Owner、影响
范围、是否需要用户决策以及应复用哪些成果。不同 session 可能得到不同路由结果，也难以机械防止
finding 循环。

### 2.5 自动串联不等于减少返工

简单自动执行 `Design → Story → Task → SOW` 只能减少人工点击和 session 切换。如果每次仍重做完整
Owner 后缀、重新读取全部 context 并逐阶段批准，主要分析成本没有消失。

### 2.6 联合收敛容易演化为巨型 Skill

如果协调器开始解释 BUSINESS、现状事实、HLD、Story/AC 或 Task 基础单元，它会复制五个 Owner 的
Schema 和业务规则，形成共享业务编译器或通用 Owner runner，破坏现有数据所有权和独立验证边界。

## 3. 目标与非目标

### 3.1 目标

1. 所有专业 Owner 使用统一、机器可读的 finding handoff。
2. 本地 finding 留在当前 Owner；明确的上游 finding 自动进入 `IN_FLIGHT`。
3. 候选收敛期间不提前发布新的正式业务数据。
4. 只重开 finding 实际影响的 Owner 和 subject，并复用闭包外 context、review 和 claim verification。
5. 收敛后由一个完整 Reviewer 和一次精确 packet 批准覆盖整体变化。
6. 保留 Owner 写集合、HLD/Go-live 所有权、Story/AC 保护和模板计算权威。
7. 同一 finding 无法无限自动重试，Owner 不明确或需要商业决策时 fail closed。

### 3.2 非目标

- 不新增 `converge-solution` 或其他用户可见流程 Skill；
- 不把五个 Owner 合并为一个共享业务 Skill；
- 不让 Task、Planning 或 SOW 生成器直接修改上游业务数据；
- 不建设配置驱动业务引擎、任意 DAG、不可变 revision store 或自动审批系统；
- 不取消最终用户批准，也不通过自动 handoff 推定商业授权；
- 不把 Schema、renderer 或生成器缺陷伪装成业务 finding 修复。

## 4. Finding 分类与统一合同

每条 finding 必须具有唯一 ID、发现 Owner、修正 Owner、受影响 subject、证据、失效声明和决策
要求。自由文本只解释问题，不参与机械路由。

建议的最小语义如下：

```json
{
  "findingId": "finding-audit-query-api",
  "discoveredBy": "generate-task",
  "correctionOwner": "generate-design",
  "category": "UPSTREAM",
  "subjectIds": ["story-audit-query"],
  "evidenceRefs": ["packet://<origin-packet-sha256>#finding-audit-query-api"],
  "invalidates": ["generate-design", "generate-task"],
  "requiresUserDecision": false,
  "summary": "审计查询结果缺少可实施的查询 API 设计。"
}
```

Finding 只允许四类：

| Category | 含义 | 默认处理 |
|---|---|---|
| `LOCAL` | 当前 Owner 可在自身写集合内修复 | Owner-local 字段 patch，不启动 reconciliation |
| `UPSTREAM` | 修正归属于明确的其他 Owner | 进入 `reconcile(IN_FLIGHT)` |
| `DECISION` | 需要新增或改变范围、责任、验收结果或商业承诺 | 请求用户决策，不自动修复 |
| `MECHANICAL` | Schema、renderer、validator、receipt 或 XLSX 投影缺陷 | 修复工具或合同，不改业务数据 |

`correctionOwner` 必须是现有五个 Owner 之一。Reviewer 可以提出 Owner，但 Owner-local validator 或
协调 preflight 必须验证它与固定 Owner 写集合兼容；无法唯一确定时把 finding 升级为 `DECISION`。

## 5. 自动触发与 handoff

自动触发不是后台扫描、定时任务或一个 Skill 直接调用另一个 Skill。发现 finding 的当前 Stage 先让
Owner-local validator 形成 canonical work-only handoff，再依据其中的 `nextAction` 进入协调模式。

建议 handoff 同时写入结构化 stdout 和内容寻址的 work-only sidecar，供当前 session 立即消费，也供
新 session 从 packet hash 恢复：

```json
{
  "algorithm": "ai-sow-finding-handoff-v1",
  "outcome": "NEEDS_RECONCILIATION",
  "originOwner": "generate-task",
  "originPacketSha256": "<sha256>",
  "findings": ["finding-audit-query-api"],
  "nextAction": {
    "skill": "reconcile",
    "mode": "IN_FLIGHT",
    "startOwner": "generate-design"
  }
}
```

只有同时满足以下条件才允许自动 handoff：

1. 至少一条 finding 为 `UPSTREAM`，且当前 Owner 无法在自身写集合内修复；
2. 每条 finding 均绑定当前不可变 packet 和实际证据；
3. `correctionOwner` 唯一，或多个 findings 可以机械收敛到最早的共同 Owner；
4. `requiresUserDecision = false`；
5. 当前项目不存在冲突的 reconciliation run 或第三种正式 hash；
6. 同一 finding 尚未在同一语义输入上完成一次失败的 in-flight 修复。

不满足时保持显式停止：Owner 不明确或涉及商业结果时请求用户决策；工具缺陷进入机械修复；同一
finding 再次出现时返回 `BLOCKED`，防止无限循环。

## 6. reconcile 的两个模式

### 6.1 IN_FLIGHT

用于首次生成过程中、最终 SOW 尚未形成时的候选返工。它允许影响集同时包含：

- 已有稳定输出且需要修正的 Owner：`CHANGED`；
- 已有稳定输出但专业结论不变的 Owner：`NO_CHANGE`；
- 尚未正式发布、将在本次闭包中首次形成输出的 Owner：`NEW`。

`NEW` 只表示协调运行中的发布状态，不成为稳定业务数据字段。一个 Owner 的正式 review、全部稳定
output 和 receipt 必须要么完整存在，要么完整缺失；不得接受半发布状态。当前合同下，已发布 Owner
形成前缀，未发布 Owner 形成连续后缀。

固定流程为：

```text
finding handoff
→ reconciliation preflight
→ correction Owner candidate patch
→ 受影响 Owner 前向复核
→ Trial Task / readiness 检查
→ staged package
→ holistic packet
→ fresh-context Reviewer
→ 用户批准精确 packet
→ package 与 Owner 产物前向发布
```

批准前所有新字节只存在于 Owner work 和单一 reconciliation staging view。任一 finding、candidate、
review、receipt、context 或 package 变化都生成新 packet；旧 Reviewer 与批准不得复用。

### 6.2 POST_PUBLISH

保留现有完整稳定链修正语义。所有受影响 Owner 均已有正式基线，只允许 `CHANGED / NO_CHANGE`，并
继续使用内容寻址 package、canonical redo manifest、单写者前向发布和中断恢复。

两个模式不得共用模糊的自动推断：baseline inspection 必须明确返回当前模式、Owner 状态和首个未
发布 Owner。正式基线完整时默认 `POST_PUBLISH`；存在合法未发布后缀且 handoff 绑定有效 upstream
finding 时才允许 `IN_FLIGHT`。

## 7. 影响闭包与执行顺序

### 7.1 第一阶段：Owner 级保守闭包

首版使用现有 Owner 顺序形成安全闭包：从 `correctionOwner` 开始，覆盖当前已发布前缀中的受影响
Owner、未发布后缀和最终 SOW package。每个 Owner 仍可判断 `NO_CHANGE`，避免伪造业务变化。

该阶段主要消除逐阶段 session、批准和正式发布成本，执行本身仍按上游到下游排序。

### 7.2 第二阶段：Subject 级依赖闭包

在 finding、candidate 和 receipt 已能稳定携带 `subjectIds` 后，影响范围从固定 Owner 后缀收窄为
类型化引用闭包：只失效实际依赖被修改 subject 的 Decision、Story、AC、Integration、Task、review
和 claims。闭包外产物保持原字节，并复用未变化的 context fragment 与 verified claim。

协调层只处理 ID、引用、hash 和 Owner 声明，不解释字段业务语义。某个 Owner 内哪些 subject 受影响
仍由该 Owner 的公开 validator 或 projector 给出，避免协调器演化为共享业务编译器。

## 8. 防止 reconcile 演化为巨型 Skill

`reconcile` 主入口只保留模式选择、公共不变量和批准边界；模式特有的长流程使用按条件读取的独立
reference。Finding Schema 放在插件级共享合同中，专业 Schema、renderer 和 validator 保持
Skill-local。

| 能力 | 唯一 Owner |
|---|---|
| BUSINESS requirements 与商业范围 | `analyze-requirement` |
| 当前事实、Evidence、Effective Start 与 Uncertainty | `analyze-as-is` |
| TECHNICAL requirements、HLD 与 Go-live | `generate-design` |
| Story、AC、Integration 与交付结果 | `generate-story` |
| Task、基础单元、工作模式与复杂度 | `generate-task` |
| Finding 路由、影响闭包、packet 与技术发布 | `reconcile` |
| XLSX 与 package 确定性投影 | `generate-sow` |

`reconcile` Python 不跨 Skill import，不读取其他 Skill Schema，不调用 Owner 脚本，也不形成配置驱动
runner。当前 Stage 按协调合同直接调用受影响 Owner 的公开 Adapter；Owner 只能写自己的 candidate、
review、output 和 receipt。

## 9. Findings 处理示例

### 9.1 重复手工测试 Task

- `discoveredBy`: `generate-task`
- `category`: `LOCAL`
- `correctionOwner`: `generate-task`
- 处理：Owner-local patch 删除与模板 SIT/UAT 重复计价的 Task；不触发 reconciliation。

### 9.2 缺少审计查询 API

- `discoveredBy`: `generate-task`
- `category`: `UPSTREAM`
- `correctionOwner`: `generate-design`
- 处理：自动进入 `IN_FLIGHT`；Design 补充现有交付结果内的实现机制。若 Story/AC 结果不变，Story
  使用 `NO_CHANGE`；Task 重新拆分并在整体 packet 中批准。

### 9.3 两周上线后支持窗口

- `discoveredBy`: `generate-task`
- `category`: `DECISION`
- 原因：固定支持容量、驻场、班次或待命窗口可能改变商业范围和服务责任，且不能用按实际问题计数的
  Task 基础单元代替。
- 处理：请求用户确认是排除支持容量、形成独立支持 SOW，还是提供可估算的具体交付对象；不得自动
  写入 Task。

### 9.4 generate-sow 投影缺陷

- `discoveredBy`: `generate-sow`
- `category`: `MECHANICAL`
- 处理：修复生成器、模板投影或合同并提升必要的 generator contract；不得通过改写 Story 或 Task
  绕过投影问题。

## 10. 失败、安全与恢复

1. 同一 packet 的 Reviewer 首次判断不可覆盖；修复必须产生新 packet。
2. 同一 finding 在相同语义输入上完成一次 in-flight 修复后再次出现，立即 `BLOCKED`。
3. 协调过程中出现指向更早 Owner 的新 finding 时，废弃当前 staging，使用新 run ID 从更早 Owner
   重建闭包，不在污染的 staging 内原地扩边。
4. 任一 Owner Adapter 失败即停止后续调用；失败 receipt 不得作为下游 handoff。
5. Task 只能提交 finding 和修改 Estimate candidate，不能修改 Delivery、Story 或 AC。
6. Scope、责任、验收结果或商业承诺变化必须由用户明确批准，不得因 `requiresUserDecision` 漏填而
   自动通过。
7. 正式发布继续采用单写者、before/after hash、package 先行和 receipt 最后写入；第三种 hash 转人工
   核对。
8. Finding sidecar、packet 和 staging 均为 work-only 协调状态，不新增稳定业务 JSON。

## 11. 分阶段实施建议

### Phase 1：Finding 合同与可观察路由

- 定义 canonical finding handoff、四类 category 和 `nextAction`；
- 五个 Owner 统一输出 finding ID、correction Owner、subject 和用户决策要求；
- 当前 Stage 展示建议路由，仍由人工确认是否进入 reconciliation；
- 记录本地 finding、上游 finding、误路由和重复 finding 指标。

### Phase 2：Owner 级 IN_FLIGHT

- 扩展 baseline inspection，识别稳定前缀和未发布后缀；
- 支持 `CHANGED / NO_CHANGE / NEW` staged closure；
- 自动消费符合条件的 `nextAction`；
- 一个整体 packet 覆盖 Owner 输出、receipts 和 SOW package；
- 保留固定 Owner 顺序作为第一版安全边界。

### Phase 3：Subject 级闭包与复用

- Finding 和 Owner receipt 发布可验证的 subject 依赖；
- 只重开依赖实际变化 subject 的 review、claims、context 和下游对象；
- 闭包外产物、verified claims 和 context fragments 原字节复用；
- 用 E2E 指标证明重跑对象数和 Reviewer 输入规模下降。

## 12. 验收条件

1. 任一 Owner 都能产生统一 finding handoff，不需要自然语言猜测下一阶段。
2. `LOCAL` finding 不启动 reconciliation；`DECISION` 和 `MECHANICAL` 不被错误自动修复。
3. 明确的 Task → Design finding 无需用户手工输入 `reconcile` 即可进入 `IN_FLIGHT` preflight。
4. `IN_FLIGHT` 中每个 Owner 只能修改自己的 candidate、review、output 和 receipt。
5. 未发布 Owner 使用 `NEW`，已有稳定 Owner 使用 `CHANGED / NO_CHANGE`；半发布 Owner fail closed。
6. 批准前正式数据保持原字节，收敛后只请求一次整体 packet 批准。
7. Story/AC 结果不变时能够证明 `NO_CHANGE` 并复用原字节；结果变化时 packet 列出精确 diff。
8. 同一 finding 再次出现时不会形成无限自动循环。
9. generate-sow 的机械缺陷不会通过修改业务数据规避。
10. 不新增用户可见 Skill，不引入共享业务 Schema、通用 Owner runner 或跨 Owner Python import。
11. E2E 能报告每次运行的重算 Owner 数、重算 subject 数、context/claim 复用数、Reviewer 次数、批准
    次数和 finding 循环次数。

## 13. 预期收益与限制

Phase 2 可直接减少人工回退、session 重启、逐阶段批准和重复正式发布，但 Owner 级执行仍是保守顺序。
只有 Phase 3 的 subject 级依赖闭包能够实质减少未受影响专业内容的重算和复审。因此实现验收不能只
统计“是否自动完成”，还必须比较重算对象、Reviewer 输入和批准次数，避免把流程自动串联误报为
分析成本下降。
