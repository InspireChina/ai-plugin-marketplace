# AI SOW

AI SOW `0.1.0-beta.1` 通过唯一公开 Skill `ai-sow:generate`，把 PRD、HLD、适用的往期 SOW 与补充材料
自动编译为可追溯的 `sow.xlsx` 和 `sow-notes.md`。当前 SOW 标准 1.3。

## 一次调用完成什么

```text
不可变 Input Revision
  -> Stage 1：InputItem / Scope Closure / Epic / Feature / Design
  -> R1 Source Audit + Scope Join
  -> Stage 2：Story / AC
  -> Stage 3：Task / Dependency / Effective Start / Estimation
  -> R2/R3 并行独立评审 + Theme Join + 必要的 Adjudication
  -> 工作簿与说明渲染 + Office 真实回算复读
  -> REQUEST_APPROVAL
  -> 用户批准后不可变发布
```

用户不需要依次运行内部模块，也不需要批准中间 hash。宿主按公开 `NextAction` 协议推进：

- `MODEL_ACTION_GROUP`：运行一个或多个 hash-bound 模型 action；
- `REQUEST_INPUT`：集中询问会改变范围、责任或估算的最少问题；
- `REQUEST_APPROVAL`：展示已通过评审和 Office 验证的不可变候选包；
- `DONE`：报告 `PUBLISHED`、`REUSED` 或安全终态并停止。

用户补充资料后以新 request 调用 `resume`，系统先校验新输入，再关闭旧 run、创建新的不可变 revision，
并从最低安全阶段继续。无效的新 request 不会破坏 active run；上一份有效 SOW 也不会被覆盖。

每个模型 action 都强制 `FRESH_NO_HISTORY`，只接收本 action 的 prompt、packet、reference 和按需
hydrate 的证据。同一 action 的工具往返可复用自身上下文，但主对话、兄弟 action、前序阶段和后续
阶段不会继承它的历史，因此长 E2E 不会把所有过程持续塞进一个模型上下文窗口。

所有问题都在同一次展示中逐项给出问题、为什么要问、答案决定什么和未回答后果。范围或终审确认
使用自然语言结论；内容较长时提供可打开的 Markdown 或 Excel 评审文件。hash、内部 ID、Schema 名和
阶段 token 只用于后台精确绑定，不要求使用者据此判断正在确认什么。

## 输入合同

| 来源角色 | 支持格式 | 规则 |
|---|---|---|
| PRD | UTF-8 `.md` | 所有项目必需 |
| HLD | UTF-8 `.md` | 所有项目必需 |
| 往期 SOW | `.xlsx` | Brownfield 建议提供；未提供时记录 `NOT_PROVIDED` 并建立新基线 |
| 补充材料 | UTF-8 纯文本、`.md`、`.html`、`.htm`、`.ts`、`.tsx`、`.xlsx` | 默认按 Markdown 语义处理文本 |

PDF、Word、PowerPoint 和其他需要专用解析器的文件暂不支持。文档标题可以不同，但必须表达最低业务
和技术语义；空白模板、只有占位符的文件或无关样例不构成有效输入。

所有请求还应提供项目 ID、项目名称、计划生效日期，以及客户、供应商和第三方的高层责任边界。
Brownfield 还必须说明自往期 SOW 生效后是否存在已知的范围、架构、集成或部署变化。

可直接使用插件内模板：

- [PRD 模板](skills/generate/assets/prd-template.md)
- [HLD 模板](skills/generate/assets/hld-template.md)
- [Greenfield 最小问卷](skills/generate/assets/greenfield-questionnaire.md)
- [SOW 模板](skills/generate/assets/sow-template.xlsx)

## 原型 Demo

HTML、TypeScript 和 TSX 原型作为 `SUPPLEMENT` 输入时，不只做附件归档。Scope 编译会识别：

- 页面、路由和入口；
- 用户角色、动作与触发条件；
- 状态变化、表单校验与权限；
- 空白、加载、成功和异常路径；
- 可观察的业务结果及其与 PRD/HLD 的关系。

源码不足且 Demo 可以运行时，宿主可以本地启动它，并按需使用 Playwright 或 Computer Use 核验实际
交互。核验结论必须追溯到原型来源；原型与 PRD/HLD 冲突时不能静默覆盖，而是形成边界说明或在确实
影响范围和估算时阻断。

## Greenfield 与 Brownfield

Greenfield 以“本期新建、不继承既有合同能力”为默认 Effective Start，只使用 PRD、HLD 和最小问卷，
不会强制开展完整现状调查。

Brownfield 在提供往期 SOW 时用它建立合同 As-Is、历史承诺与 Effective Start，但往期合同不自动证明
当前生产状态。未提供适用往期 SOW 时以 `priorSowState = NOT_PROVIDED` 建立新基线，不虚构历史承诺；
若缺口会实质改变范围、责任或估算，则通过 `REQUEST_INPUT` 或安全终态显式处理。

## 增量更新

后续仍调用 `ai-sow:generate`。工作流把新 request 对应的不可变 input revision 与最近一次成功
generation 的证明闭包比较：

- 全部语义与 renderer 指纹未变化：`REUSE`，不创建模型 action；
- 只有 renderer 或非语义模板字节变化：`RENDER_ONLY`，复用 SOW Model、检查点和评审决定，不启动 Reviewer；
- 语义输入、Delivery Policy、任务目录或阶段检查点变化：`DELTA_COMPILE`，以上一份 SOW Model 为基线重编译；
- 首次生成、缺少可信闭包或核心合同变化：`FULL_COMPILE`。

模型提交 typed replacement set，并绑定被修改节点的 expected hash；编译器在组内结果全部封存后一次
应用，不做未校验字段 patch。未受影响对象保持规范 JSON 原字节和 ID；语义变化的对象使用新 ID；
共享 Design、Integration、NFR、Policy 或 Task 会扩大影响闭包。所有非复用路线都完整重渲染 Package。

## 输出与可追溯性

```text
.ai-sow/
├── current.json
├── inputs/
│   └── revisions/<revision>/
│       ├── manifest.json
│       ├── sow-template.xlsx
│       └── sources/
├── generations/<generation>/
│   ├── manifest.json
│   ├── data/
│   │   └── sow-model.json
│   └── output/
│       ├── sow.xlsx
│       └── sow-notes.md
└── work/
    ├── active-run.json
    └── runs/<run>/
```

revision 与 generation 发布后不可变。候选、分阶段 checkpoint、独立评审、渲染和用户批准全部完成后
才原子更新 `current.json`；失败、崩溃、输入等待或批准等待均保留上一份有效结果。generation manifest
绑定 input revision、SOW Model、三个 stage checkpoint、评审决定、artifact manifest、用户批准、模板、
renderer 指纹、输出 hash，以及真实办公软件回算后的工作簿验证证据。

`sow-notes.md` 固定披露输入版本、As-Is 证据边界、关键推断、估算假设、待设计事项、各方责任、排除
范围、冲突处置、未决 NFR、风险和变更触发条件；这些事项不能只留在内部日志。成功摘要报告发布或
复用结果、generation manifest 以及两个输出路径。自动生成不代表客户已经签署、接受或赋予 SOW
法律效力。

## 工作簿规则

[SOW 模板](skills/generate/assets/sow-template.xlsx)是基础单元、任务规则、基础人天、复杂度、SIT、UAT、
公式和取整的唯一计算权威。正式工作簿固定为 `01-需求故事`、`02-任务清单`、`03-工作量汇总`、
`90-估算标准` 四个 Sheet。生成器先写候选件，再用 LibreOffice 在隔离目录中重算；只有 5 个命名
Table、全部输入行、公式缓存、校验结果、参数/目录、汇总和一页宽/纵向分页设置均复读通过，才以
`VERIFIED` 发布。公式和人天不会在 Python 或稳定 JSON 中重算。

当前只支持 XLSX 模板。intake 在创建 input revision 时把项目模板保存为 revision 内的
`sow-template.xlsx` 本轮专用副本；Task 编译、评审、渲染和复读只使用该副本。运行期间改动项目模板
不影响当前轮次。下一轮会区分非语义 renderer 变化与任务目录语义变化：前者 `RENDER_ONLY`，后者
重新编译 Delivery 并重新评审。generation manifest 同时绑定 `templateSha256` 与 `rendererSha256`。

Epic 和 Feature 使用稳定领域能力的名词或名词短语，并以共同投入理由维持同质边界，不能用“平台”“闭环”“保障”等抽象词把无关主题装入同一层级。Story 使用自然的
`[模块/接口] 角色或对象＋动作` 标题，只归属一个 Feature、至少包含两条 AC 且最多包含四个 Task。
Stage 1 先建立 InputItem、Scope Closure、Epic/Feature 和 Design/NFR/Policy；R1 对来源覆盖与全局
Scope 做独立复核，发现问题时只允许一次 hash-bound Stage 1 repair，并在进入 Stage 2 前再次独立
复核。Stage 2 只形成 Story/AC checkpoint，Stage 3 才读取模板目录拆分 Task；下游不得反向补造上游
范围。每个阶段都写入同一受管 SOW Model candidate，静态字段、ID、checkpoint 和 expected node hash
由固定实现维护，模型只提交 Schema 约束的 typed replacement set。
来源中的每个原子目标、指标、阈值或控制先逐项进入全部适用具体 Story 的来源可追溯 AC，同一语义义务可
以不同 AC ID 出现在多个 Story；项目级且没有 Story 特定行为的义务留在 NFR、DoD 或质量门禁。Story 必须
命名一个可独立移交并关闭的具体结果，并共同具备具体交付物或能力、责任方或消费者、独立验收、独立关闭
或发布边界；可分别测试或可验收的 NFR、质量属性、政策类别或合规陈述不会自动膨胀为 Story。自动化、性能、
安全或合规测试只在已成立 Story/AC 下成为 Task。只有一个具体机制、配置、证据包或运营能力同时拥有上述
边界、且由来源或已批准设计明确支持为可独立运行或消费的能力时才可成为 Technical Story，不能由控制归组、
验收活动或指定验收人制造，也不能用数据治理或服务水平等兜底 Story 汇总无关控制。授权、状态或政策控制若
只在提交、审批、查询等已有业务触发执行，先写入每个受影响业务 Story 的 AC；规则跨切面不形成共享控制
Story。来源规定的阈值必须保留在每个适用 AC 或项目级质量/NFR 门禁，报表或仪表盘只能交付显示/测量，
不能关闭阈值满足义务。
Stage 2 与 Stage 3 后分别运行多 shard 的 `STORY_DESIGN` 和 `TASK_ESTIMATION` 独立评审。一个主题
跨多个物理 shard 时必须由 Theme Join 绑定所有 leaf result hash 并保留全部 finding；同一 subject 的
冲突 finding 必须交给新的 `FRESH_NO_HISTORY` Adjudicator 明确选择，不能由编排器静默覆盖。
Story 稳定数据不保存描述；九列需求故事表不再保存内部故事路径，Task 直接引用唯一 Story 名称。每条
AC 以 `• ` 开头并独占一行，任务列表逐行显示 `[任务类型/工作方式/复杂度] 任务名称`。备注只显示对象
特有的特殊情况、不确定性、风险、例外、依赖或评审边界；跨 Feature 的项目级通用事项只进入
`sow-notes.md`，不在 Story 行重复。Story 人天仅保留为结果展示和后续基准校准输入，不作为拆分正确性或评审通过门禁；需求、子需求、Story、AC 与 Task 的语义边界和可独立验收性才是粒度判断依据。项目直接开发和
UAT 由模板基于 Task 人天汇总，因此相同 Task 不会因 Story 拆分或合并改变项目总人天。

Task 名称必须点明一个与模板任务类型匹配的计数对象。接口 Task 一行只对应一个可独立开发、测试和
估算的接口；属于该接口的校验、事务、权限和异常处理写入同一 Task 及其 AC，形成独立调用契约时才
另建 Task。泛化名称或并列多个接口由编写与终审结合来源和模板语义判断，机械编译器不通过中文标题
关键词推断业务含义。

模板中标记为 `待样本校准` 的参数会按原状态进入 `sow-notes.md`，不会被误写为固定规则。空 Story 或
空 Task 不能生成形式上成功的工作簿。

当前任务目录、计数口径、包含/排除项、可用工作方式与 S/M/L/X 标准只以本轮模板的
`90-估算标准` 为准。概念、判定方法与字段说明见
[SOW 任务分类与开发交付人天标准](docs/reference/SOW任务分类与开发交付人天标准_v1.3.md)。示例工作簿见
[SOW 估算与生成示例](docs/reference/SOW估算与生成示例_v1.3.xlsx)。

## 运行时

普通用户无需预装 Python 或 uv。正式发布还需要可执行的 LibreOffice（可通过 `AI_SOW_OFFICE_BIN`
指定，或由 `soffice/libreoffice` PATH 发现）；缺失时安全阻断并保留 last-known-good。macOS/Linux 使用 `bootstrap.sh`，Windows 使用 `bootstrap.ps1`；
bootstrap 在插件安装副本内准备固定 uv、managed Python、锁定依赖和 `.venv`。后续执行不要求 uv 位于 PATH，
也不需要激活虚拟环境。运行时不调用 Codex CLI、Claude Code CLI 或其他代理产品命令；Codex、Claude
Code、CI 或自定义宿主都通过同一个 Python `NextAction`/文件协议推进。完整约束见
[运行时环境合同](references/runtime-environment.md)。

Windows 未启用长路径支持时，项目根路径必须短于 97 个字符。启用机器级长路径策略需要管理员权限和
用户明确同意，插件不会静默修改。

## 隐私与安全

`.ai-sow/` 包含输入原文和客户衍生数据，默认应加入项目 `.gitignore`。分享或提交前必须单独确认该目录
以及生成工作簿的授权范围。插件不会把凭据、私有源码、完整工具输出或本机绝对路径写入稳定 SOW Model。
action record 只保存结果相对路径与 SHA-256；完整 submission 和按需证据不复制进公共执行日志。

路径只能位于项目受管范围内；符号链接穿越和目录越界会被拒绝。Git 只用于普通协作，插件不会执行
clone、fetch、pull、reset、commit 或 push。

## 开发验证

```text
uv sync --project plugins/ai-sow --locked
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow/skills -q
uv run --project plugins/ai-sow --locked python plugins/ai-sow/tests/support/smoke_plugin.py --copy-plugin
```

copy smoke 在独立复制的插件和临时项目中直接通过 Python API 运行，不要求安装 Codex 或 Claude Code
CLI。它覆盖 Greenfield、Brownfield、输入恢复、无变化复用、无 Reviewer 的 `RENDER_ONLY`、保留未受
影响节点的 `DELTA_COMPILE`，并验证 `FRESH_NO_HISTORY`、输出文件、manifest hash 闭包、工作簿 Table/
公式、项目边界和 marketplace 零读取。worker 的 stdout/stderr、临时文件及失败收据都保留在项目或
精确 smoke work-dir 内，失败现场不会被测试清理掉。
