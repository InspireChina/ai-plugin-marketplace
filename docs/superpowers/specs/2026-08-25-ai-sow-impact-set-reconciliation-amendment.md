# AI SOW 影响集整体协调设计修正

状态：用户于 2026-08-25 明确批准本方向；本修正取代原 Owner handoff 设计中“上游修正后由用户逐阶段显式调用”的产品合同。性能优化实施已进一步把 candidate/staging/package/redo 全部移到批准前，现行顺序以[性能优化设计修正](2026-08-25-ai-sow-performance-optimization-design.md)和 `reconcile/SKILL.md` 为准。

适用版本：`0.1.0-beta.2`

## 1. 问题与目标

原设计把稳定数据 Owner 责任、独立 session 和逐阶段用户调用绑定在一起。即使下游专业结论没有变化，也要重复启动 Orchestrator、Worker、Reviewer、Validator，重新读入同一项目并逐个签发 receipt。该流程可解释，但不是最小用户模型，真实修正会产生大量重复上下文、等待和审查成本。

本修正把两件事分开：

- **Owner** 继续定义专业语义、稳定路径、Validator 和写入权限；
- **Reconciliation** 在一次用户调用中读取完整影响后缀，形成一份整体评审，调用各 Owner 的既有合同完成验证和 receipt 更新。

目标用户模型是：

```text
用户提交一项修正
→ 一次读取相关上游与全部下游稳定产物
→ 当前 Stage 形成整体评审、全部 candidate 与 Owner review projection
→ 各 Owner 确定性脚本在同一 staging view 中依固定顺序验证
→ 在 staging view 中生成并验证 SOW package
→ 确定性 assemble redo/diff/risk 和完整 review packet
→ 一个 fresh-context Reviewer 审查 packet
→ 一次用户批准精确 packet SHA-256
→ 先发布不可变 package，再执行一次可恢复的 Owner 批量发布
→ STOP
```

## 2. Module 与 Interface

新增七阶段之外的维护 Skill `ai-sow:reconcile`。它不是第八个业务阶段，不拥有稳定业务 JSON，也不解释 Owner 业务规则。

外部 Interface 只有一个用户操作：提交修正及可选证据；Module 返回 `REVIEW_REQUIRED`、`PUBLISHED` 或 `BLOCKED`。同一调用在 `REVIEW_REQUIRED` 后等待一次整体批准，再继续发布。

固定业务顺序保持：

```text
analyze-requirement
→ analyze-as-is
→ generate-design
→ generate-story
→ generate-task
→ generate-sow
```

修正 Owner 确定后，影响范围只能是从该 Owner 到 `generate-sow` 的连续后缀。不得配置节点、边、拓扑排序、字段依赖图或可插拔 Owner registry。

普通首次生成仍可使用原七阶段 Skill；`reconcile` 只处理已经存在有效下游产物后的修正与影响复核。

## 3. 整体评审与角色

当前 Stage 是唯一用户接口，直接读取受影响 Owner 的完整 Skill 合同、当前稳定 JSON、review、receipt
与修正证据，分别形成 Owner-local 影响结论，并调用确定性命令完成批准前 staged closure。不存在
Worker 或 Validator 叶子 Agent。完整 packet 只创建一个 fresh-context Reviewer，它审查专业合理性、
跨阶段一致性、覆盖、遗漏、Story/AC 冻结、candidate/projection 忠实度和 package/发布风险，但不
修改成果。Owner 是数据与规则的责任，不等于独立 Agent 或独立 session。

整体评审保存在 `.ai-sow/work/reconcile/<run-id>/review.md`，至少包含：

- 修正事实、证据和唯一 Owner；
- 固定影响后缀；
- 每个 Owner 的 `CHANGED` 或 `NO_CHANGE`；
- 新旧 output hash、受影响稳定 ID 和理由；
- Story/AC 精确差异；
- Task 与估算影响；
- package、redo/diff/risk 与 packet 技术摘要。

该文件是 work artifact，不是第七份稳定业务 JSON。确定性 assemble 生成的 packet 绑定 review、
全部 staged Owner artifact、receipt inputs、package tree、redo/diff/risk；Reviewer 与用户批准分别
保存在同目录 work-only sidecar，并绑定相同的 `run-id + packet SHA-256`。各受影响 Owner review
继续携带同一 `run-id` 与 review SHA-256，Owner receipt 仍绑定自己的 review/output/input。
Story/AC 业务结果变化声明和精确 diff 必须在同一 packet 中，由同一次批准覆盖。

## 4. 影响规则

每个受影响 Owner 只能返回：

- `NO_CHANGE`：该 Owner 的所有稳定 output 必须原字节复用，只允许更新批准 review 与 receipt 绑定；
- `CHANGED`：只允许修改该 Owner 的 review、candidate、稳定 output 和 receipt，无关对象与语义未变的 ID 保持稳定；
- `BLOCKED`：事实归属不唯一、证据不足、Owner-local Validator 失败，或修正需要回到当前影响起点之前。

Story/AC 是已批准业务交付合同：

- 技术设计、实现机制、基础单元、工作模式、复杂度或 Task 边界变化，默认不得改变 Story/AC；
- `generate-story` 对上述变化使用 `NO_CHANGE` 并保持 Delivery 原字节；
- 只有修正本身改变业务交付结果，且整体评审明确列出 Story/AC 差异和业务结果变化声明时，Story Owner 才能 `CHANGED`；该声明由同一次整体批准覆盖；
- Task 永远不能反向要求 Story/AC 与 Task 一一对应，也不能为了容纳实现拆分修改业务合同。

HLD/Go-live 仍只由 `generate-design` 判断；其他 Owner 与 `reconcile` 只匹配 Design receipt。

修正证据、来源、问卷或 prior SOW 必须在 reconciliation 建立 baseline 前已经存在于正式项目路径。
staging view 不注册或发布新的 Owner input；任何 staged receipt 绑定了只存在于 staging 的 input
时整批阻塞。用户输入继续由对应 Owner 的既有 input 合同管理，批量发布只处理已批准 Owner
成果。

## 5. Staging view 与发布

`runtime/project_io.py` 提供纯技术 staging view：读取时先查 staging root，普通缺失项回退到固定
base root；显式 tombstone 的路径必须表现为不存在，不能让旧问卷或旧输入从 base“复活”。所有
写入只进入 staging root。它不知道 Owner 名称、阶段顺序、Story、AC 或任何业务字段。

staging root 固定为项目内短路径 `.ai-sow/.stage-<12hex>/`，必须与正式 `.ai-sow` 位于同一文件
系统，且拒绝 symlink/reparse。Windows 路径与目录替换能力在实机验收前保持 `Provisional`。

批准前按固定顺序在同一 staging view 中运行：

```text
CHANGED → Owner candidate/check/publish to staging
NO_CHANGE → Owner rebind to staging
→ match current staged receipt
→ next Owner
→ generate-sow against completed staging view
```

全部通过前，正式稳定路径不变。

当前 Stage 先编译所有 `CHANGED` output candidate 和各 Owner 的 work-only review 投影，再在同一
staging view 中按固定 Owner 顺序执行一次前向 pass：
`CHANGED` Owner 通过仅限 `check` 的 `--review-path` Adapter 校验候选与投影，并读取已经在该 view
中发布、匹配的上游 staged receipt/output，通过后 stage review 并 `publish`；`NO_CHANGE` 没有
candidate，不运行 check mode，而是 stage 已完成 fidelity review 的固定 review，直接执行 Owner-local
`rebind` 并把原 output 原字节物化到 staging closure。两类 Owner 都在 staged receipt 匹配后才进入
下一 Owner。这样下游得到完整候选 handoff，而不是回退读取正式 baseline。最后生成并复读 package，
由 `reconcile.py --mode assemble` 生成完整 packet，一个 Reviewer 审查后用户批准。整个 pass 只写
staging；批准后只允许运行 publisher check/publish。`publish/rebind` 不允许 review-path override；
任一 staged byte 变化都必须形成新 packet 并重新复审、批准。

发布脚本只理解 work-only canonical redo manifest 中的 `WRITE/DELETE`、项目相对路径、before
状态和 staged/after 状态；它不调用 Owner 脚本、不解释业务语义。manifest 同时覆盖最终五份
receipt 的完整 `FILE` hash closure：项目外 repository evidence 只复核 baseline，不由发布器写入；
任何 staged-only receipt input 都阻塞。发布前一次性验证正式路径仍处于 before 状态。之后按固定
Owner 顺序写 review/output，并让每个 receipt 最后写入。任一中断后重跑时，当前状态必须属于
`{before, after}` 才可安全前向恢复；第三种状态立即阻塞。

这里不声明全局文件系统原子快照。单写者模型下，发布中的某个新 Owner 前缀可能单独有效，但
`generate-sow` 在 Task receipt 最后写入前不能接受完整五 receipt 集；中断时最终生成链 fail-closed
并可前向恢复。Reconciliation 运行期间不得在同一项目并发运行其他写 Skill。设计不增加项目锁、
不可变 revision store、活动指针、rollback journal、inode 协议或 cross-filesystem transaction。

SOW package 在 staging view 中通过生成、复读和 tree 校验后，先作为内容寻址目录发布；相同内容
复用，不同内容 fail closed。package 发布失败时 Owner 正式路径完全不变；package 成功而随后
Owner 批量发布中断时，尚未被完整 handoff 引用的内容寻址 package 只是可复用的不可变产物，
下一次前向恢复继续使用它。

可恢复发布以单一受支持写入者为运行前提。同一项目上的并发同权限写入不在保证范围；任一路径
出现既非 before hash 也非 staged hash 的第三种字节时，发布立即阻塞并要求人工核对，不猜测或
覆盖。

## 6. 技术边界

允许：

- `reconcile` Skill 的 Agent 读取受影响 Owner `SKILL.md` 与项目 artifact；
- 五个 Owner `SKILL.md` 显式声明可由 `reconcile` 作为内部 Adapter 调用；普通独立调用、Owner-local
  语义、写集合和 STOP 行为保持不变；
- 五个 Owner Validator 与 `generate_sow.py` 通过同名可选 staging-root 参数使用同一技术 view；
- `generate-sow/SKILL.md` 显式声明可作为 Reconciliation 的最终投影 Adapter；普通调用与
  receipt-only 投影职责保持不变；
- `project_io.py` 提供 overlay 与可恢复批量写入；
- `handoff.py` 保持现有 receipt/match/publish/rebind 语义。

禁止：

- runtime 硬编码 Owner 名称或阶段图；
- 跨 Skill Python import、共享业务 Schema、共享业务 validator 或通用 Owner runner；
- JSON Patch 直接改写稳定数据；
- 新增 reconciliation 稳定 JSON、自动批准或字段级依赖图；
- 为强原子性迁移全部 `.ai-sow` 物理路径。

本修正明确取代基础设计中以下“逐个显式调用/每步 STOP”条款：4.3 的顺序影响复核产品流程、
14.3 的跨 session 返回链认证、17 节相关 E2E 要求，以及完成标准 16、21、26 中要求用户逐个
调用下游的部分。原文关于唯一 Owner、Owner-local Validator、审批前不发布、固定阶段顺序、
`NO_CHANGE` byte identity、HLD/Go-live 所有权和 generate-sow receipt-only 投影的条款继续有效。

## 7. 成功条件

至少证明：

1. Design `CHANGED` → Story `NO_CHANGE` → Task `CHANGED` 在一个 session 内完成，Delivery 原字节不变；
2. As-Is 修正从 As-Is 到 SOW 的连续后缀整体完成，不跳 receipt；
3. Task 尝试修改 Delivery 时整批阻塞且正式路径不变；
4. 任一 Owner Validator 或 package 验证失败时，发布不开始；
5. package 发布失败时 Owner 路径全部保持 baseline；
6. holistic review hash、approval、Owner review 投影或 manifest 任一不一致时阻塞；
7. staged-only receipt input、baseline 漂移或第三种 hash 时发布阻塞；
8. 发布中断可从 before/staged hash 前向恢复，完整链在最终 receipt 前始终 fail-closed；
9. 普通七阶段流程、独立复制插件和现有 receipt matcher 保持兼容。
10. `generate-sow` 在 staging view 中生成的 package hash 来自 staged Owner artifacts，而不是 base。
