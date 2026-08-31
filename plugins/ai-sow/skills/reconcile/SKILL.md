---
name: reconcile
description: 当已有 AI SOW Owner 稳定产物因一项上游修正需要在一次批准中整体复核连续影响后缀、更新 receipt 并重新生成 SOW 包时使用。
---

# 整体协调 AI SOW 影响集

在一个 session 中协调一次已登记修正及其完整下游影响。普通首次生成继续使用七阶段 Skill；本
Skill 不拥有稳定业务 JSON，也不解释或复制 Owner 业务规则。

执行前完整读取并遵守[输出语言合同](../../references/output-language.md)。整体评审使用简体中文；
Owner、路径、hash、枚举和其他 machine token 保持原值。
按[插件运行时环境合同](../../references/runtime-environment.md)从 `<plugin-root>` 解析当前平台的
`<python-bin>`；全部确定性命令直接使用 setup 已建立的插件 `.venv`。

## 当前任务与固定边界

当前 Stage Agent 是本 Skill 的唯一用户接口、专业协调者和确定性命令派发者；不创建 Worker 或
Validator 叶子 Agent。批准前只创建一个不继承当前完整聊天的 fresh-context Reviewer；同一次调用
最多使用该 Reviewer 完成一次完整审查，发现 findings 时允许 Stage 一次整体修复并重新机械闭环后，
交回同一 Reviewer 完整复审。第二次仍有 findings 时 `BLOCKED`。

固定顺序为：

```text
analyze-requirement
-> analyze-as-is
-> generate-design
-> generate-story
-> generate-task
-> generate-sow
```

影响集只能从唯一修正 Owner 开始，连续延伸至 `generate-sow`。整体 review 的 `Impact Suffix` 必须
显式包含最后的 `generate-sow`；Owner 影响矩阵和 redo `owners` 只列拥有稳定数据的 Owner，到
`generate-task` 为止，`generate-sow` 由 package 段表示。不得跳过中间 Owner、配置阶段图或建立
字段级依赖。修正证据、来源、问卷和 prior SOW 必须在建立 baseline 前已位于正式项目路径；staging
不登记或发布新的 Owner input。

每个受影响 Owner 使用 `CHANGED / NO_CHANGE / PENDING` 三态：

- `CHANGED`：只修改该 Owner 的 work-only review projection、candidate、staged output 和 receipt；
  语义未变的 ID 保持稳定。
- `NO_CHANGE`：不编译 candidate、不运行拒绝 `Impact: NO_CHANGE` 的 check；稳定 output 原字节复用，
  只把获批 review projection staged 后执行 Owner-local `rebind`。
- `PENDING`：该 Owner 位于影响后缀中但尚未首次发布；所有 `PENDING` 必须构成后缀的连续末端。
  它按 Owner 自己的普通 candidate、renderer、`check` 与 `publish` 路径首次发布，不读取不存在的
  baseline，也不使用 `rebind`。这次首次发布仍只占该 Owner 原本需要的一次批准，不增加批准轮次。
- 设计、实现机制、基础单元、工作模式、复杂度或 Task 边界变化默认保持 Story/AC 不变。只有修正
  本身改变业务交付结果，且整体评审包含 `Story/AC Outcome Change: CHANGED` 和精确差异时，
  `generate-story` 才能为 `CHANGED`。Task 不得修改 Delivery、Story 或 AC。

任一 Owner 归属不唯一、修正需要回到影响起点之前、Owner-local 门禁失败或同一项目存在并发写入时
返回 `BLOCKED`。

## 批准前完整闭包

为本次运行生成 12 位小写十六进制 `<run-id>`，只使用：

```text
.ai-sow/work/reconcile/<run-id>/review.md
.ai-sow/work/reconcile/<run-id>/diff.json
.ai-sow/work/reconcile/<run-id>/risk-summary.md
.ai-sow/work/reconcile/<run-id>/redo.json
.ai-sow/work/reconcile/<run-id>/review-packet.json
.ai-sow/work/reconcile/<run-id>/reviewer.json
.ai-sow/work/reconcile/<run-id>/approval.json
.ai-sow/.stage-<run-id>/
```

当前 Stage 先读取[整体评审模板](references/review-template.md)和受影响 Owner 的完整 `SKILL.md`、
Owner-local 必需 reference；随后用下方只读 `inspect` 取得固定路径、hash、receipt input 和 review
ID 声明。`inspect` 同时把未首次发布的连续末端标记为 `PENDING`；若中间 Owner 缺失而更下游已
发布，则立即 `BLOCKED`。Stage 只读取 `CHANGED` Owner 的专业工作所需稳定内容与修正证据；`PENDING`
没有 baseline 可读，直接从 staged upstream handoff 开展该 Owner 的首次专业工作；`NO_CHANGE` 不把完整
稳定 output/review 带入模型上下文，也不由模型创建 work review。然后只形成 `review.md`、全部
`CHANGED/PENDING` candidate 及其 work-only review；`NO_CHANGE` projection 由 Adapter 确定性生成。影响矩阵 Before/After 必须按
Owner receipt 的 named output 顺序使用 canonical `name=64-lowercase-hex`；多份 output 以 `; `
连接。`PENDING` 的 Before 使用 canonical `name=MISSING`，After 使用首次发布 hash；`NO_CHANGE` 的
Before/After hash 必须相同。

### 精确路径与 Adapter 命令

从已加载 Skill 路径解析一次 `<skill-root>`、`<plugin-root>` 与 `<python-bin>` 后，在整个 run 中原样
复用这些绝对路径；不得重新搜索、手工缩写或猜测 cache version。Owner 的固定路径如下，不得把 `requirements.json` 猜成
`technical-requirements.json`，也不得预读尚未创建的 candidate 或 projection：

Owner 合同读取后的第一条项目命令固定为只读 baseline inspection；不得用 `sha256sum`、`shasum`、
整文件 `sed` 或自行拼接 Python 代替，也不得在它之前读取任何项目 artifact：

```text
"<python-bin>" "<skill-root>/scripts/reconcile.py" \
  --project-root "<project-root>" \
  --start-owner "<correction-owner>" \
  --mode inspect
```

`inspect` 只返回固定 Owner 后缀的 stable output/review/receipt SHA-256、candidate/work review 路径、
base receipt 的 validation inputs 和 review 中已有的 ID 声明；它不写项目、不调用 Owner 脚本、
不读取其他 Skill Schema，也不解释业务字段。Stage 必须直接复用该结构化结果，不再自行哈希同一
baseline 或读取完整 `NO_CHANGE` review/output。
读取 `CHANGED` 内容时只访问 `inspect` 返回的精确路径和修正证据 anchor；`PENDING` 只访问其
上游 staged handoff、Owner 合同和本次 work candidate，不探测不存在的正式路径。禁止对 `.ai-sow` 递归
`rg/find`，禁止再次运行 Adapter `--help`，也不得重新哈希 `inspect` 已返回的 baseline。

| Owner | Stable output | Candidate | Work review | Formal review | Receipt |
|---|---|---|---|---|---|
| analyze-requirement | `.ai-sow/data/analyze-requirement/requirements.json` | `.ai-sow/work/analyze-requirement/requirements.candidate.json` | `.ai-sow/work/analyze-requirement/review.candidate.md` | `.ai-sow/reviews/analyze-requirement.md` | `.ai-sow/validation/analyze-requirement.json` |
| analyze-as-is | `.ai-sow/data/analyze-as-is/asis.json` | `.ai-sow/work/analyze-as-is/asis.candidate.json` | `.ai-sow/work/analyze-as-is/review.candidate.md` | `.ai-sow/reviews/analyze-as-is.md` | `.ai-sow/validation/analyze-as-is.json` |
| generate-design | `.ai-sow/data/generate-design/design.json`; `.ai-sow/data/generate-design/requirements.json` | `.ai-sow/work/generate-design/design.candidate.json`; `.ai-sow/work/generate-design/requirements.candidate.json` | `.ai-sow/work/generate-design/review.candidate.md` | `.ai-sow/reviews/generate-design.md` | `.ai-sow/validation/generate-design.json` |
| generate-story | `.ai-sow/data/generate-story/delivery.json` | `.ai-sow/work/generate-story/delivery.candidate.json` | `.ai-sow/work/generate-story/review.candidate.md` | `.ai-sow/reviews/generate-story.md` | `.ai-sow/validation/generate-story.json` |
| generate-task | `.ai-sow/data/generate-task/estimate.json` | `.ai-sow/work/generate-task/estimate.candidate.json` | `.ai-sow/work/generate-task/review.candidate.md` | `.ai-sow/reviews/generate-task.md` | `.ai-sow/validation/generate-task.json` |

任何 Owner staging 前必须先冻结整体专业 review，顺序不可交换：

1. 形成全部 `CHANGED/PENDING` candidate 及其 renderer 生成的 work review；
2. 对每个 `CHANGED/PENDING` Owner 单独运行只读 `inspect-work`，取得 candidate named hashes；
3. 用 baseline `inspect` 与 `inspect-work` 的精确 hashes 写完
   `.ai-sow/work/reconcile/<run-id>/review.md` 全文；不得留占位；
4. 对每个 `CHANGED/PENDING` Owner 单独运行 `prepare-changed`，把精确 run ID、整体 review hash 与
   baseline 决定的 `Impact: CHANGED` 或 `Impact: PENDING` 绑定到其 work review；
5. 只有上述步骤全部完成，才开始下方 Owner `check/stage/publish`。`prepare-no-change` 同样要求整体
   review 已存在，绝不能先发布 Design 再补整体 review。

`inspect-work` 与 `prepare-changed` 的独立命令分别为：

```text
"<python-bin>" "<skill-root>/scripts/reconcile.py" \
  --project-root "<project-root>" --owner "<owner>" --mode inspect-work
```

```text
"<python-bin>" "<skill-root>/scripts/reconcile.py" \
  --project-root "<project-root>" --run-id "<run-id>" --owner "<owner>" \
  --mode prepare-changed
```

Owner validator 仍由当前 Stage 直接调用，reconcile Python 不跨 Skill 执行脚本。每条下列命令必须
是一个独立 tool call：一个 shell command 中只能出现一次 `"<python-bin>"`，不得用换行、`;`、`&&`
或 `||` 串联后续动作。每条命令直接使用一个绝对脚本路径，不使用 shell 临时变量或重复 cache path；
所有 `--project-root` 必须是绝对路径，不得使用 `--stage-root`。直接调用插件 `.venv` Python 不改变
项目 cwd；读取或编辑项目 artifact 时继续保持项目 cwd，不得拼接临时 `python -c` 代替公开命令。

`CHANGED/PENDING` 固定执行三个独立调用：Owner `check`、`stage-owner review`、Owner `publish`。
`PENDING` 使用 Owner 的现有首次发布 candidate，不进入 `NO_CHANGE` 分支。Owner 命令
使用表中 validator/candidate/work review 精确路径及其 Skill 公布的 candidate flags：

```text
"<python-bin>" "<validator-path>" \
  --project-root "<project-root>" \
  --staging-root ".ai-sow/.stage-<run-id>" \
  --mode check \
  --review-path "<work-review>" \
  <Owner candidate flags>
```

```text
"<python-bin>" "<skill-root>/scripts/reconcile.py" \
  --project-root "<project-root>" --run-id "<run-id>" --owner "<owner>" \
  --artifact review --mode stage-owner
```

```text
"<python-bin>" "<validator-path>" \
  --project-root "<project-root>" \
  --staging-root ".ai-sow/.stage-<run-id>" \
  --mode publish \
  <Owner candidate flags>
```

`NO_CHANGE` 不编译 candidate，也不由模型读取/复制 base review。先单独运行 `prepare-no-change`；它读取
base formal review 中已有的 `Stable IDs`、`Design IDs`、`Technical IDs` 声明形成完整 Impact
Rationale，替换旧 reconciliation declarations，再比较当前 Owner receipt 的每个 `*Validation`
input：

- `Previous Receipt SHA-256`：base Owner receipt 中该 named input 已绑定的 hash；
- `Current Receipt SHA-256`：同一 upstream Owner 的 staged upstream receipt 原字节 hash；
- `Upstream`：只列上述两个 hash 不同的全部直接输入 Owner，保持 Owner validator 的固定顺序。一个
  Task receipt 可同时直接绑定 Design 与 Story，因此不得把“直接输入”误解为只有紧邻上一阶段。

```text
"<python-bin>" "<skill-root>/scripts/reconcile.py" \
  --project-root "<project-root>" --run-id "<run-id>" --owner "<owner>" \
  --mode prepare-no-change
```

成功后才分别执行 `stage-owner --artifact review`、Owner-local `rebind`、
`stage-owner --artifact unchanged-output`；每步仍是单独 tool call，前一步失败时绝不发起后一步。
Owner-local `rebind` 的独立命令为：

```text
"<python-bin>" "<validator-path>" \
  --project-root "<project-root>" \
  --staging-root ".ai-sow/.stage-<run-id>" \
  --mode rebind
```

`stage-owner` 接收逻辑 `.ai-sow/...` 路径并机械写到 flat staging 的 `reviews/...` 或 `data/...`，拒绝
不同字节覆盖，且禁止生成双层 `.ai-sow/.stage-*/.ai-sow/...`。Stage 不得手工 `mkdir/cp` staging
内容。任一 Owner closure 失败都立即停止
整个 run；不得在同一个 staging 中修补后重试，因为失败 receipt 会占用 staging validation 路径，
后续命令不能再把它当作有效的 base Owner receipt。修正插件或专业结论后必须删除这个隔离 run，使用
新 run ID 从该 reconciliation 步骤整体重跑。

flat staging view 会对未覆盖路径回退读取 base；因此 correction Owner 之前的 Owner output、review、
receipt 和模板不得复制进 staging。完整受影响后缀通过后，直接运行一次 staged generator；无需再次
读取 `generate-sow/SKILL.md`：

```text
"<python-bin>" "<plugin-root>/skills/generate-sow/scripts/generate_sow.py" \
  --project-root "<project-root>" \
  --staging-root ".ai-sow/.stage-<run-id>"
```

批准前在同一个 flat staging view 完成一次固定顺序的前向 pass：

1. `CHANGED/PENDING` Owner-local `check` 通过 `--review-path` 读取 work-only projection，再把
   projection 写入 staging 固定 review 路径并执行 `publish`；candidate After hash 必须等于整体
   review 的 named After hash。`PENDING` 的正式 review/output/receipt 在 baseline 中必须全部为
   `MISSING`，并由该次 `publish` 一次性首次形成。
2. `NO_CHANGE` 直接把 projection 写入 staging 固定 review 路径，执行 Owner-local `rebind`，并把
   原稳定 output 原字节物化到 staging closure。
3. 两类 Owner 都必须匹配刚生成的 staged receipt，才允许下游读取完整 staged handoff；
   `publish/rebind` 不允许 review-path override，HLD/Go-live 仍只由 `generate-design` 判断。
4. 当前 Stage 直接调用 `generate-sow` Reconciliation Adapter，从完整 staged receipt/output/review
   生成并复读内容寻址 package。manifest 与 workbook hash 必须来自 staged bytes，不得回退到 base。

以上步骤只写 work 与 `.ai-sow/.stage-<run-id>/`；正式 Owner 路径和正式 package baseline 保持原字节。
全部通过后，当前 Stage 运行确定性 assemble：

```text
"<python-bin>" "<skill-root>/scripts/reconcile.py" \
  --project-root "<project-root>" \
  --run-id "<run-id>" \
  --mode assemble
```

`assemble` 不调用 Owner 脚本，也不解释业务语义。它从 baseline、flat staging、固定 Owner 后缀和
已验证 package 确定性生成 contract `0.2` 的 canonical `redo.json`、技术 `diff.json`、风险摘要与
`ai-sow-reconciliation-review-packet-v1` packet。packet 精确绑定：整体 review、全部 staged Owner
review/output/receipt、receipt inputs、package tree、diff、risk summary 和 redo manifest。`redo.json`
只记录固定路径与顺序、`WRITE/DELETE`、before/after state、package tree、packet/Reviewer/approval
固定路径和 `writerMode: SINGLE_WRITER`；不得由 Agent 手工拼接。

批准前 `reviewer.json`、`approval.json` 不存在。Reviewer 只读取精确 packet 及其点名的闭包，审查
Owner-local 专业结论、跨阶段一致性、遗漏、Story/AC 冻结、candidate/projection 忠实度、完整 staged
package 与发布风险。`PASS` 后当前 Stage 写 canonical：

```json
{"algorithm":"ai-sow-reconciliation-reviewer-v1","decision":"PASS","packetSha256":"<packet-sha256>","runId":"<run-id>"}
```

Stage 向用户展示整份 `review.md`、risk summary、package ID、run ID 与 packet SHA-256。用户必须明确
批准该 `<run-id>` 和精确 packet SHA-256；随后写 canonical：

```json
{"algorithm":"ai-sow-reconciliation-approval-v1","decision":"APPROVED","packetSha256":"<packet-sha256>","runId":"<run-id>"}
```

任何 input、candidate、Owner projection、staged receipt、package、diff、risk、redo 或整体 review
字节变化都必须重新运行 assemble，形成新 packet，由同一 Reviewer 完整复审并重新取得用户批准。
不得只修 packet 中未点名的影子文件绕过批准。

## 批准后只运行确定性发布

批准后只运行以下两个命令；不得再编译 candidate、修复专业结论、修改 Owner projection、调用
Reviewer、执行 Owner validator/publish/rebind 或重新生成 package：

```text
"<python-bin>" "<skill-root>/scripts/reconcile.py" \
  --project-root "<project-root>" \
  --manifest ".ai-sow/work/reconcile/<run-id>/redo.json" \
  --mode check

"<python-bin>" "<skill-root>/scripts/reconcile.py" \
  --project-root "<project-root>" \
  --manifest ".ai-sow/work/reconcile/<run-id>/redo.json" \
  --mode publish
```

Publisher 先复算 contract `0.2` redo、packet、Reviewer、approval、全部 staged bytes、receipt closure 和
package tree；任一漂移都在正式发布前 `BLOCKED`。它先发布或复用已验证的不可变 package，再按 Owner
顺序写 review/output，并让每个 receipt 最后写入；`generate-task` receipt 是整批最后一个正式 Owner
写入。正式状态必须属于 manifest 的 before/after，已完成的 after 只能形成有序前缀；第三种 hash、
staged-only receipt input、批准漂移或并发写迹象都不得覆盖。

`check` 的 `completedOperations` 统计已经处于 after 状态的全部 manifest operation；`before == after`
的原字节复用路径天然视为完成。因此一次完整发布后的复查必须报告
`completedOperations == totalOperations`，不能只报告发生字节变化的 operation。

删除只允许 Requirement Owner 以显式 tombstone 删除已存在的可选 questionnaire review，不允许用
staging 新增 Owner input。Publisher 按 `ai-sow-package-v1` 与 `receipt-only-v2` 机械复算最终
`generationFingerprint`，绑定 project、六份 output、五份 review、五份 receipt 和正式模板原字节；
manifest 的 `generatorContract` 必须与 publisher 常量精确一致，否则返回
`PACKAGE_GENERATOR_CONTRACT_MISMATCH`。任何确定性投影变更必须同时提升 generate-sow 与 reconcile
中的合同并由跨路径测试锁定；这些检查只比较固定字段、路径和 hash，不重放 Owner 业务规则。

发布中断后复用同一个 run ID、packet、批准和 redo manifest 重跑 `publish`；只做幂等前向恢复，
不自动回滚、不创建 revision store、活动指针或项目锁。需要人工处理时报告具体 path、before/after/
current hash 和已发布 package；人工确认前不得生成新 redo 覆盖证据。contract `0.1` 仅由 publisher
保留读取兼容，当前流程不得新建该旧格式。

## 完成

只有 package 已发布、全部 Owner 路径达到 after、五份最终 receipt 的 `FILE` hash closure 完整且
Task receipt 已最后写入时返回 `PUBLISHED`。报告 run ID、packet SHA-256、整体 review、package、各
Owner impact、receipt 和是否发生前向恢复，然后 `STOP`；不得继续修改其他项目内容。
