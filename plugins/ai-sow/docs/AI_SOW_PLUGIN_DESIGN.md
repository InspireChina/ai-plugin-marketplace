# AI SOW 插件方案

- 状态：当前正式合同
- 插件版本：`0.1.0-beta.1`
- SOW 标准：`1.3`
- 适用宿主：Codex 与 Claude Code
- 公开入口：`ai-sow:generate`
- 领域语义：[CONTEXT.md](CONTEXT.md)
- 计算权威：[sow-template.xlsx](../skills/generate/assets/sow-template.xlsx)
- 运行时合同：[插件运行时环境合同](../references/runtime-environment.md)

## 1. 设计目标

AI SOW 用一个公开 Skill 完成首次生成、增量更新和阻断恢复。用户一次提供项目资料，内部自动完成输入
固化、范围编译、交付分解、终审、渲染和发布。内部模块只形成可测试的深 seam，不成为额外命令，也
不要求用户理解候选目录、模式名或中间 hash。

核心原则：

1. PRD 决定业务结果，HLD 决定高层技术边界，往期 SOW 只提供 Brownfield 合同起点；
2. 插件维护 `InputManifest`、`ScopeBundle`、`DeliveryBundle` 三类稳定数据；
3. 输入变化按受影响 Feature 闭包整片重算，不做字段级 patch；
4. 能建立固定范围与估算边界时继续，并通过说明文档披露限制；
5. 失败或阻断不改变最近一次成功 generation；
6. Excel 模板是所有计算口径的唯一权威；
7. 自动生成不等于客户签署或接受。

## 2. 包结构与模块所有权

```text
plugins/ai-sow/
├── .codex-plugin/plugin.json
├── .claude-plugin/plugin.json
├── pyproject.toml
├── uv.lock
├── runtime/
│   ├── diagnostics.py
│   └── project_io.py
├── references/
├── docs/
├── tests/
└── skills/generate/
    ├── SKILL.md
    ├── assets/
    ├── contracts/
    ├── fixtures/
    ├── references/
    ├── scripts/
    └── tests/
```

`runtime/` 只提供业务无关的诊断和安全项目 I/O。`generate` 独占全部稳定业务 Schema、模板、编译器、
渲染器、fixture 和测试。运行时不得读取插件目录之外的实现文件，也不得依赖 marketplace 根目录。

五个内部 seam：

| Module | 所有权与边界 |
|---|---|
| `intake` | 校验请求与格式，固化输入，生成锚点，比较最近成功 revision |
| `scope_compiler` | 编译 Feature、Effective Start、Design、Integration、NFR 与范围边界 |
| `delivery_compiler` | 编译 Story、AC、Task、依赖、假设和估算输入 |
| `final_review` | 跨层检查完整性、追踪、责任和估算固定边界，只输出三种终态 |
| `package_renderer` | 从已通过终审的 Bundle 和模板确定性渲染 Package |

`orchestrator` 只选择全量生成、无变化复用、切片更新、仅渲染或阻断恢复，并按结果串联上述模块；它
不拥有业务规则。

## 3. 输入合同

所有项目必须提供 PRD、HLD、项目标识、名称、计划生效日期，以及客户、供应商和第三方高层责任边界。
未指定项目模板时使用插件内置模板。

| 输入角色 | 支持格式 |
|---|---|
| PRD | UTF-8 Markdown `.md` |
| HLD | UTF-8 Markdown `.md` |
| PRIOR_SOW | Excel `.xlsx` |
| SUPPLEMENT | UTF-8 纯文本、Markdown、HTML、TypeScript、TSX 或 `.xlsx` |

PDF、Word、PowerPoint 与其他需要专用解析器的格式不支持。校验关注必需语义，不按标题机械拒绝非标准
文档。空文件、只有占位符的模板、损坏或加密文件以及无关样例不是有效输入。

Greenfield 不要求往期 SOW，以“本期新建、不继承既有合同能力”为默认 Effective Start，只补充确实
影响范围、责任或估算的最小问卷。

Brownfield 至少需要一份适用往期 SOW，并回答自其生效后是否存在已知的范围、架构、集成或部署变化。
往期 SOW 建立合同口径 As-Is、历史承诺与 Effective Start，但不自动证明当前生产状态。缺少适用文件时
直接 `BLOCKED`。

### 3.1 原型证据

HTML、TypeScript 与 TSX 原型不能只按普通附件摘要。Scope 编译至少提取页面或入口、用户角色、动作、
触发、状态变化、校验、权限、异常路径和可观察业务结果。源码不足且 Demo 可运行时，可在本地启动后
用 Playwright 或 Computer Use 核验交互；只保存可追溯结论，不保存完整源码、截图或工具输出。原型不
覆盖 PRD/HLD 的明确声明，实质冲突按固定边界或 `BLOCKED` 规则处理。

## 4. 来源权威与稳定数据

- PRD：业务目标、范围、Feature、业务规则与验收意图；
- HLD：目标架构、跨系统设计、Integration、NFR 和上线约束；
- 往期 SOW：Brownfield 合同起点、历史承诺和延续范围；
- 用户答案与补充材料：本次责任、现状变化、明确决策及原型证据；
- SOW 模板：任务分类、人天、复杂度、SIT、UAT、风险、公式和取整。

PRD/HLD 实质矛盾不能按文件顺序覆盖。若假设、排除项、责任或 Design Task 可以建立固定边界，则以
`PASS_WITH_NOTES` 继续；若不同解释会改变 Feature、责任、验收或估算且无法限定，则 `BLOCKED`。

三类稳定数据：

- `InputManifest`：来源角色、文件 hash、语义锚点、问卷答案和变更来源；
- `ScopeBundle`：Epic/Feature、Effective Start、DesignItem、Integration、NFR、SourceRef；
- `DeliveryBundle`：Story、AcceptanceCriterion、Task、依赖、假设/风险和估算投影。

每个对象携带最小来源或上层引用。语义不变时沿用 ID；仅文字澄清且交付含义不变时也保留 ID；实质
含义变化时生成新 ID，不允许旧 ID 指代新对象。

通过 `questionSha256` 校验的每个答案还会在 intake 形成一个 `QUESTION_ANSWER` 语义锚点。其稳定
source/anchor ID 只从 `questionId` 推导，内容 hash 绑定 canonical 完整问题包和精确答案；未回答问题
不构成证据，绑定无效时不发布 pending。Scope、Delivery 与终审继续使用通用精确 SourceRef inventory，
不建立问卷专用证据模型。同一请求的 `questionId` 必须唯一，文档 sourceId 与生成的问答 sourceId
冲突时在 pending 写入前 fail closed，避免问答锚点被解析成文件来源。

## 5. Scope 与 Delivery 编译

`scope_compiler` 联合 PRD、HLD、往期 SOW 和补充来源，建立目标结果相对 Effective Start 的差值。
`FULLY_COVERED` 必须有合同或现状证据；需要新增交付的 Feature 进入 `IN_SCOPE`；不属于本期的范围
明确为 `OUT_OF_SCOPE`。Integration 必须有方向、触发、目的、数据类别和责任归属；适用 NFR 必须有
目标、待设计状态或不适用结论。由于这是供应商 SOW，`IN_SCOPE` Feature 必须至少连接一条 `VENDOR`
责任边界；只有客户或第三方责任的事项不能进入供应商计价范围。

`delivery_compiler` 在一个 Bundle 中共同形成 Story、AC 和 Task：

- 编写顺序固定为两遍：先完成并复核全部受影响 Story/AC 的层级、来源闭包和可观察结果，再从已成立的 Story/AC 读取当前模板进入 Task 拆分；两遍共享同一 candidate 和 ID decisions，不新增中间稳定数据或批准点；
- Story 是可独立交付、验收和结算的结果，通过唯一 `featureId` 归属一个 Feature，最多包含四个 Task；
- AC 是可观察、可独立判定的结果，不描述实现步骤；
- Task 一行对应一个基础单元实例，并追溯到 Story 与相关 Design/Integration/NFR；名称点明一个与任务类型匹配的计数对象，接口 Task 一行只包含一个可独立开发、测试和估算的接口，接口内部校验进入该接口 AC；
- 待设计事项默认成为实施 Story 下可独立估算的 Design Task；
- 跨业务 Feature 的可靠性、验证、发布或移交工作先形成技术 Feature，再由对应 Story 计价并通过依赖连接；
- 一个 Integration 对应一个需要交付的内部或外部系统对接 Task；
- 正式复杂度只允许 `S / M / L`，无法限定的 `X` 不进入发布数据。

Task 工作模式只允许 `新建 / 调整 / 接入复用`。`调整 / 接入复用` 必须引用匹配的 Effective Start；
接入复用还必须明确项目侧注册、配置、封装、映射、适配、认证、租户、权限或专项验证工作。替换与退役
通过替代能力、数据迁移、发布切换和系统功能下线等真实基础单元拆分。

## 6. 增量更新

每次请求先与最近成功输入 revision 比较：

```text
变更来源锚点
  -> 直接 Feature
  -> 共享对象引用闭包
  -> 整个受影响 Scope/Delivery 切片
  -> 完整 Package 重渲染
```

问答锚点遵循同一闭包：只改变答案或问题包内容时保持 source/anchor identity、更新内容 hash，并以
`MODIFIED` 定位所有引用它的 Feature；`questionId` 改变时按移除旧锚点和新增锚点处理。

闭包包括直接 Feature 及其 DesignItem、Integration、NFR、Story、AC、Task，并扩展到共享这些对象且会
改变交付或估算的其他 Feature。无法可靠定位唯一 Feature 时，影响范围按 Feature、系统/业务域、全部
Scope 逐级扩大。

替换切片时，新结果仍存在且语义不变的对象保留 ID；新增对象获得新 ID；旧切片中未再生成的对象删除。
跨切片引用和估算校验在替换后重新运行。输入、模板与渲染器合同都未变化时复用当前结果；只有渲染器
合同变化且语义输入与模板不变时才跳过语义编译并完整重渲染。模板变化始终开始新一轮，重新编译
Delivery 并重新终审。

## 7. 自动终审

终审在所有受影响切片完成后执行一次，检查：

- SourceRef 与 Feature/Design/Integration/NFR 的覆盖；
- Epic → Feature → Story → AC 的层级、来源完整性和可追溯性，以及 Story/AC 闭包完成后才进入 Task 拆分的流程；
- HLD、上线、数据、环境、安全与运维边界；
- 重复、遗漏、共享对象和依赖闭包；
- 任务目录、工作模式、复杂度理由与模板组合；
- 假设、责任、排除项和变更触发条件是否形成固定估算边界。

结果为 `PASS`、`PASS_WITH_NOTES` 或 `BLOCKED`。详细设计缺失、字段级接口未定、产品未选型或部署参数
待确认通常由 Design Task 和说明承接。待确认假设只有在责任方、处理方式、估算边界和变化触发条件都
已固定时才允许 `PASS_WITH_NOTES`；`NEEDS_DECISION` 承诺必须在 Scope 接受前解决。只有无法建立可信
范围/估算边界，且不同解释会实质改变交付时才允许阻断。阻断问题必须聚合、去重并只询问改变结果
所需的信息。

每个用户问题必须自包含问题、为什么要问、答案决定什么和未回答后果，并精确绑定受影响对象；批量
展示不能用一段通用说明代替单项解释。fresh-context 终审由系统自动执行；只有确实需要用户输入或
确认时，才展示自然语言结论，内容较长时提供可读文件，例如可打开的 Markdown 评审材料或 Excel
交付物。内部 ID、hash、Schema 名和阶段 token 仍用于精确绑定，但不作为使用者识别确认内容的正文。
review packet 的 `acceptanceCriterionSources` 逐条投影 AC 所属 Story、精确来源与可解析状态；`claims`
只包含可机械证明的层级提示，不根据业务自由文本关键词猜测语义。

## 8. 项目事务与不可变发布

```text
.ai-sow/
├── current.json
├── inputs/
│   ├── pending/
│   └── revisions/<revision>/
├── generations/<generation>/
│   ├── manifest.json
│   ├── data/{scope.json,delivery.json}
│   └── output/{sow.xlsx,sow-notes.md}
└── work/
```

pending 保存尚未成功的输入；revision 保存每次实际使用的不可变输入快照；generation 保存稳定 Bundle、
manifest 和输出；work 只保存本次候选与临时审计数据。

发布顺序固定为：完成候选与终审、生成工作簿候选、用 LibreOffice 隔离回算并完整复读、固化 input revision、固化 generation、最后
原子替换 `current.json`。指针切换前的新目录不视为有效。任何失败都不得覆盖上一份 generation；恢复
直接合并 pending 补充并重新规划受影响切片。

## 9. Package 与工作簿

每次成功 generation 包含：

```text
manifest.json
data/scope.json
data/delivery.json
output/sow.xlsx
output/sow-notes.md
```

`sow-notes.md` 固定说明输入 revision、As-Is 证据边界、关键推断、假设、待设计事项、各方责任、排除
范围、冲突处置、未决 NFR、风险和变更触发条件。

工作簿模板保存当前基础单元、任务族及全部计算规则。正式拓扑只有 `01-需求故事`、
`02-任务清单`、`03-工作量汇总`、`90-估算标准` 四个 Sheet 和五个命名 Table。生成器写入结构化文本
和名称关系，保留公式、样式、行高、筛选和保护；公式只来自模板，Python 不计算最终人天。候选件经
LibreOffice 真实回算后，必须同时复读公式和缓存值，并逐项核对模板公式、Table 计算列元数据、数据
验证、Sheet 保护、可见样式、行高、一页宽且不限制纵向页数的打印布局、全部 Story/Task、基础单元、
项目参数、公式错误与汇总恒等关系。发布存储层还要对
暂存工作簿独立执行同一审计，并精确匹配 manifest 的 `workbookVerification`；只有
`workbookVerification.trustState = VERIFIED` 才允许发布；缺少
引擎、空 Story/Task 或复读不完整均保留 last-known-good。以 `= / + / - / @` 开头的普通文本按文本写入，
防止公式注入。

当前只支持 XLSX 模板。项目模板副本只有同时满足“与上一份已发布 manifest 的模板哈希一致”和
“该哈希属于已知内置模板版本”时，`prepare` 才会安全采用新的内置模板；发布后改动或首次发布前
定制的项目模板都必须保留。每轮 `prepare` 立即将当时模板固定为 `.ai-sow/work/run-template.xlsx`，
Delivery 编译、终审、渲染和复读共用这份本轮副本。运行期间项目模板改动不影响已开始的本轮；
下一轮检测到模板与上一 generation 不同时，必须重新编译 Delivery 并重新终审，不允许只重渲染旧 Task。
成功 generation 在自身 `input/sow-template.xlsx` 保存原字节模板副本，manifest 记录路径与 SHA-256。

`generation-renderer-v7` 与 renderer fingerprint 绑定九列 Story 表、AC 符号点、带任务类型/工作方式/复杂度前缀的任务列表、对象特异备注投影、直接 Story 名称引用、Task 原子计价、真实回算引擎和验证代码。改变输出字节语义时必须提升
合同并同步 baseline、测试与文档。

`scope-compiler-v2` 和 `delivery-compiler-v5` 对应当前最小稳定模型：Story 只保存唯一 `featureId`、名称和 UAT 适用性，不保存类型常量或 `description`；每个 Story 至少两条 AC 且最多四个 Task，接口 Task 保持一个可独立估算接口，AC 不复制
顺序/理由，Task 不复制依赖或 Effective Start 名称。新增锚点必须用候选对象 `sourceRefs` 的
`(sourceId, anchorId, sha256)` 精确身份定位基线 Feature；替换集合只保存旧 ID，初次完整编译为空；
发布统计对四类对象统一使用 `affected / recomputed / reused / deleted / final`。

## 10. 运行时、安全与隐私

平台 bootstrap 在插件安装副本内准备 uv 0.11.7、managed Python 3.12、锁定依赖与 `.venv`，然后调用
唯一 orchestrator。普通用户无需预装 Python/uv，也无需手工激活环境。所有内部结果为 UTF-8 JSON。

项目受管路径禁止越界和符号链接穿越。稳定数据不保存凭据、客户无关原文、私有源码、完整工具输出或
本机绝对路径。`.ai-sow/` 默认应被版本控制忽略并按客户数据处理。插件不执行 Git 网络、历史改写、
提交、推送或发布操作。

## 11. 验证与非目标

Module、合同、增量和 E2E 测试分别覆盖格式矩阵、引用、ID、影响闭包、终审门槛、不可变 generation、
last-known-good、公式/Table/样式以及独立复制运行。copy smoke 必须在复制插件之外创建项目，并阻止
访问 marketplace 根目录。

本版本明确不提供：旧命令兼容、旧业务数据迁移、候选 Schema 双轨、字段 patch、复杂业务状态机、
Python 公式执行、XLSX 反向导入、PDF/Word/PPT 解析、自动 Git 操作或客户签署判断。generation manifest
对旧合同 token 的枚举仅用于把既有 generation 识别为只读证据并触发当前合同完整重编译或重渲染；
run plan、candidate、稳定 Bundle 和新 generation 始终只写当前合同，不形成旧格式兼容执行路径。
