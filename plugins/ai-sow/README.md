# AI SOW

AI SOW `0.1.0-beta.2` 通过唯一公开 Skill `ai-sow:generate`，把 PRD、HLD、适用的往期 SOW 与补充材料
自动编译为可追溯的 `sow.xlsx` 和 `sow-notes.md`。当前 SOW 标准 1.3。

## 一次调用完成什么

```text
不可变 Input Revision 与原型预处理
  → Scope StagePlan → 物化/验证/fresh Review → checkpoint
  → Story/AC StagePlan → 物化/验证/fresh Review → checkpoint
  → Task StagePlan → 物化/验证/fresh Review → checkpoint
  → 工作簿与发布后缀
```

当前未发布重构已贯通三阶段自动封存；Office 与完整输出发布仍须最终集成验收。阶段控制与证据合同见[阶段自动封存](skills/generate/references/stage-seal.md)。

用户不需要依次运行内部模块，也不需要批准中间 hash。宿主按公开 `NextAction` 协议推进：

- `ai-sow-action-v3` / `MODEL_ACTION_GROUP`：运行一个或多个 hash-bound Action；
- `WAITING_INPUT`：集中询问会改变范围、责任或估算的最少问题；
- `REQUEST_APPROVAL`：展示已通过评审和 Office 验证的不可变候选包；
- `DONE`：报告 `PUBLISHED` 或安全终态并停止。

业务输入变化时先明确 abandon 当前 run，再以完整新 request start，创建新的不可变 revision 并完整编译。
同一 run 的 resume 只恢复已冻结的计划与执行事实，上一份有效 SOW 不会被覆盖。
往期工作簿的新分析请求使用无损编码，在相同预算内共同读取更多完整行；原证据和独立语义评审要求保持不变。旧计划保留其冻结版本。

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
| Demo | 静态 HTML/CSS/JavaScript bundle | 显式列出入口和全部文件，无需安装或构建 |
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

可执行 Demo 使用静态 HTML/CSS/JavaScript bundle。HTML、TypeScript 和 TSX 也可作为 `SUPPLEMENT`
提供静态来源，但可执行 Demo 必须显式声明 `demo.entrypoint` 与全部 `demo.files`。Scope 编译会识别：

- 页面、路由和入口；
- 用户角色、动作与触发条件；
- 状态变化、表单校验与权限；
- 空白、加载、成功和异常路径；
- 可观察的业务结果及其与 PRD/HLD 的关系。

声明 Demo 后，宿主按冻结的场景执行真实浏览器、typed trace 和有界重放，再由 Analyze 封存观察。
核验结论必须追溯到原型来源；原型与 PRD/HLD 冲突时不能静默覆盖，而是形成边界说明或在确实
影响范围和估算时阻断。

## Greenfield 与 Brownfield

Greenfield 以“本期新建、不继承既有合同能力”为默认 Effective Start，只使用 PRD、HLD 和最小问卷，
不会强制开展完整现状调查。

Brownfield 由 Scope 一次解释明确提供的往期 SOW，按本期计划生效日建立合同推定的生产 As-Is、
历史承诺与 Effective Start。重复来源保留审计，只投影 canonical 实体；已生效 FULL 替代排除前项。
未提供适用往期 SOW 时以 `priorSowState = NOT_PROVIDED` 建立新基线，不虚构历史承诺；
若缺口会实质改变范围、责任或估算，则通过 `REQUEST_INPUT` 或安全终态显式处理。

## 输入更新与恢复

后续仍调用 `ai-sow:generate`。每个新 run 完整编译当前输入；往期 SOW 必须作为显式输入，经过 Prior
核对形成授权 snapshot。旧 generation 不作为隐藏业务缓存。业务输入变化采用 abandon/start；同一
run 的 resume 沿用完整冻结 StagePlan、原始 Envelope、Attempt 与 checkpoint，不重复转换已封存 revision。
`declaredChangeContext` 进入本轮冻结的 Scope 上下文，不从旧 generation 注入。
预算替换须严格增加至少一项 token、active-time、未来请求的上下文容量、hydrate reserve 或 Demo 限额；正文相同、限额降低或其它配置变化均拒绝。
合法替换发布不可变 policy 与 RunEvent，不创建业务 revision，也不改写已冻结计划和执行记录。


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
范围、冲突处置、未决 NFR、风险和变更触发条件；这些事项不能只留在内部日志。成功摘要报告发布结果、generation manifest 以及两个输出路径。自动生成不代表客户已经签署、接受或赋予 SOW
法律效力。

## 工作簿规则

[SOW 模板](skills/generate/assets/sow-template.xlsx)是基础单元、任务规则、基础人天、复杂度、SIT、UAT、
公式和取整的唯一计算权威。正式工作簿固定为 `01-需求故事`、`02-任务清单`、`03-工作量汇总`、
`90-估算标准` 四个 Sheet。生成器先写候选件，再用 LibreOffice 在隔离目录中重算；只有 5 个命名
Table、全部输入行、公式缓存、校验结果、参数/目录、汇总和一页宽/纵向分页设置均复读通过，才以
`VERIFIED` 发布。公式和人天不会在 Python 或稳定 JSON 中重算。

默认模板正式采用 13 列 TaskTable，以工作类型名称下拉输入、隐藏公式匹配稳定 ID；删除 SIT
计费点 ID 列，以全表唯一的任务名称识别计费任务。“集成类型”仅供目录中具备
`PER_INTEGRATION` 资格的任务选择内部集成/外部集成，其他任务留空。生成器仍兼容原 14 列
ID 输入模板，并按所选模板原型保留输入列与计算列。生成前继续按 Integration 引用校验方向唯一
归属；SIT 费率、复杂度系数与汇总取整仍由模板公式决定。

空白模板预备 60 条故事、200 条任务输入行，名称输入格可编辑，公式格受保护。
`03-工作量汇总` 仅展示工作量和 8 项参数的受保护公式视图，不追加实体 ID、类型或来源台账；
原 ProjectParameterTable 留在 `90-估算标准` 隐藏区域。估算标准默认展示 10 列、右侧 6 列分组
细则，其余原始机器字段隐藏保留，只冻结前四行。

当前只支持 XLSX 模板。intake 在创建 input revision 时把项目模板保存为 revision 内的
`sow-template.xlsx` 本轮专用副本；Task 编译、评审、渲染和复读只使用该副本。运行期间改动项目模板
不影响当前轮次。下一轮使用新的模板快照完整编译并重新评审。generation manifest 同时绑定 `templateSha256` 与 `rendererSha256`。
项目已有 `.ai-sow/templates/sow-template.xlsx` 时优先使用该文件，更新插件默认资产不会覆盖项目
副本；采用新版模板后须创建新 run。

Epic 和 Feature 使用稳定领域能力的名词或名词短语，并以共同投入理由维持同质边界，不能用“平台”“闭环”“保障”等抽象词把无关主题装入同一层级。Story 使用自然的
`[模块/接口] 角色或对象＋动作` 标题，只归属一个 Feature、至少包含两条 AC 且最多包含四个 Task。
每个 Owner 的 StagePlan 形成有效结果后才物化候选，完整机械验证后发行 fresh Review。机械失败和新发生的语义 finding 使用受限 `CANDIDATE_PATCH-v1`；Owner 发放槽位，程序保留无关数据并重放 CandidateResolution。语义 Patch 绑定真实 Review 和程序侧 Owner IR base，不能写 PASS；修复后必须由 distinct fresh Review 通过。已发行旧 Repair 保留冻结语义。
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
Scope、Story/AC 与 Task 均使用 fresh singleton Review。PASS 自动进入下一阶段；不存在中间阶段批准或多层 Theme Join/Adjudication。
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
[SOW 估算与生成示例](docs/reference/SOW估算与生成示例_v1.3.xlsx)。当前 reference 示例为 mall
订单履约与售后升级，包含 22 条 Story、59 条 Task；直接开发 97.3、SIT 支持 3.5、UAT 支持 3.0，
合计 103.8 人天。其升级需求与企业资产均为示例假设，不是真实历史报价或已批准 SOW；
[配套说明与复现输入](docs/reference/mall订单履约与售后升级_示例说明.md)保留公开来源、适用边界与复现步骤。

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
CLI。最终集成需覆盖 Greenfield、Brownfield、新输入完整编译和同 run 恢复，并验证 `FRESH_NO_HISTORY`、输出文件、manifest hash 闭包、工作簿 Table/
公式、项目边界和 marketplace 零读取。worker 的 stdout/stderr、临时文件及失败收据都保留在项目或
精确 smoke work-dir 内，失败现场不会被测试清理掉。

工作簿验证使用 `generation-renderer-v13`：精简模板的汇总 Sheet 只显示工作量和模板参数，追溯信息保留在配套模型/证明中；原 14 列模板兼容可见追溯；全部可见 Sheet 的 Office PDF renders 经一次独立视觉评审通过后，才向用户请求批准。每一步实际生成、Office 与复读都受 active-time 预算约束；预算增加后的恢复保留已完成输出。

内部 checkpoint 自动封存；运行中用户只回答问题或补充材料。严格顺序 Greenfield→Brownfield 的
pair harness 不属于插件业务 Owner。两侧 verified artifact 均完成后，共同展示两份 Excel，
只取得一个 PairDecision。APPROVE 深绑定共同 manifest 与双方工作簿；两个 generation/current
都匹配才算发布。中断重放同一决定；REJECT 使用 hash 寻址的完整新 request，按受影响侧重跑后重新共同评审。

生成后的 Scope、Story/AC 和 Task 按 findings 使用受限 Patch：精确字段直接修改，宽 root 只处理 Owner 授权闭包；无关对象、上游 checkpoint、物理失败记录和累计使用量不变。自动停止后的 `resume --decision` 仍绑定原终态与失败 Review，并与 `allowedFields` 取交集。完整合同见 [阶段自动封存](skills/generate/references/stage-seal.md)。

往期 Excel 大表按完整证据行分组，保留全部单元格、位置、哈希与表头，避免整张 Sheet 超出单次请求容量。阶段尚未发行计划工作便因容量等待时，修复分组后可从原 run 恢复，复用已完成的原型观察和检查点，不提高模型容量或重置消耗。

往期资料的失败重试可通过无损表表示减少请求体，完整资料和原失败结果保持可复原；尚未发行的重试重新满足原容量后继续。网络中断保留原调用证据并按执行重试接续，未知 provider 用量单独披露。放弃决定在中断后可恢复为终态；工件取证从最终检查点恢复，不依赖可变当前候选。完整边界见[阶段自动封存](skills/generate/references/stage-seal.md)。

恢复会保留真实 Office PDF：导出原字节先持久暂存，再记录成功完成事件，避免中断后重复导出的字体差异；已完成结果和 renderer 不变。XLSX 数组公式按原公式文本取证，无原公式文本的数据表公式明确拒绝，读取不执行公式。

往期 XLSX 无需固定格式：同次分析理解表头、横纵布局与附注，区分本项目合同交付和通用目录/示例/重复汇总；未提取行保留理由，合同限定保留原文依据。小文件优先整本分析，必要时按行分组并补读同来源的跨 Sheet 条款；程序无损汇总，现有独立评审核对被排除原文。无法解释或容量不足时明确报告，不承诺任意工作簿自动成功。

Task 按所选模板目录读取完整规则；未来 Task 合同允许最多 65536 的累计规则读取额度，实际仍受本 run 的显式 hydrate reserve 与上下文容量约束。旧冻结 Action、计划、Repair 与证明不升级。

已批准的界面自动化测试可依据具体业务验收条件生成测试资产，无需虚构额外后台设计；系统仍核对每条测试的政策、来源、工作类型与独立交付边界。

机械候选默认最多 2 版、每版执行 2 次；达到次数上限后保留进度，显式增加有限预算可沿原工作继续。Scope、Story、Task、Prior 与原型候选保护无关对象，保留定位及失败原文；工件步骤失败也按有限次数接续并复用成功输出；详见[机械候选接续](skills/generate/references/stage-seal.md#机械候选的有限接续)。

Action 发放与 Envelope 复验按其冻结的 `maxHydrateTokens` 预留读取空间（不超过 run 的 hydrate reserve），避免为其他阶段较大的读取额度重复占用容量；阶段分组仍沿用原保守规划。原请求、预算、次数与完整 hydration 请求容量复核保持有效，尚未发行的修复满足原限额即可从同一 run 接续。
