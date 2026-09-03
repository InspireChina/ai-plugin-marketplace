# AI SOW

AI SOW `0.1.0-beta.1` 通过唯一公开 Skill `ai-sow:generate`，把 PRD、HLD、适用的往期 SOW 与补充材料
自动编译为可追溯的 `sow.xlsx` 和 `sow-notes.md`。当前 SOW 标准 1.3。

## 一次调用完成什么

```text
输入归档
  -> Scope 编译
  -> Delivery 编译
  -> 自动终审
  -> 工作簿与说明渲染
  -> 不可变发布
```

用户不需要依次运行内部模块，也不需要批准中间 hash。终审结果只有：

- `PASS`：直接发布；
- `PASS_WITH_NOTES`：在明确假设、责任、排除项和变更触发条件后发布；
- `BLOCKED`：无法形成可信范围或估算时停止，并一次汇总最少量问题。

被阻断的输入保留在 `pending/`。用户补充资料后再次调用 `ai-sow:generate`，会从同一 pending 请求
续跑；已经提供且仍有效的信息不会重复询问，上一份有效 SOW 也不会被覆盖。

所有问题都在同一次展示中逐项给出问题、为什么要问、答案决定什么和未回答后果。范围或终审确认
使用自然语言结论；内容较长时提供可打开的 Markdown 或 Excel 评审文件。hash、内部 ID、Schema 名和
阶段 token 只用于后台精确绑定，不要求使用者据此判断正在确认什么。

## 输入合同

| 来源角色 | 支持格式 | 规则 |
|---|---|---|
| PRD | UTF-8 `.md` | 所有项目必需 |
| HLD | UTF-8 `.md` | 所有项目必需 |
| 往期 SOW | `.xlsx` | Brownfield 至少一份；Greenfield 不需要 |
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

Brownfield 使用往期 SOW 建立合同 As-Is、历史承诺与 Effective Start，但往期合同不自动证明当前生产
状态。缺少适用往期 SOW 时稳定返回 `BLOCKED`；现状证据不足但仍能建立固定边界时以
`PASS_WITH_NOTES` 披露限制。

## 增量更新

后续仍调用 `ai-sow:generate`。工作流把当前 pending 输入与最近一次成功 revision 比较：

- 输入和规则都未变化：复用当前 generation；
- 只有 renderer 合同变化：保留 Scope/Delivery，只完整重渲染 Package；
- 项目模板相对上一份 generation 变化：完整重新编译 Scope 和 Delivery、重新终审并渲染；
- 语义输入变化：定位来源锚点，扩大至完整受影响 Feature 闭包，重算并替换该切片；
- 编译合同变化：重算受该合同影响的全部数据。

更新不产生字段级 patch。未受影响对象保持内容和 ID；语义变化的对象获得新 ID；受影响旧对象若不再
生成则从新切片消失。共享 Design、Integration、NFR、Assumption 或 Task 会自动扩大影响闭包。

## 输出与可追溯性

```text
.ai-sow/
├── current.json
├── inputs/
│   ├── pending/
│   └── revisions/<revision>/
├── generations/<generation>/
│   ├── manifest.json
│   ├── data/
│   │   ├── scope.json
│   │   └── delivery.json
│   └── output/
│       ├── sow.xlsx
│       └── sow-notes.md
└── work/
```

revision 与 generation 发布后不可变。候选、审核和渲染全部完成后才原子更新 `current.json`；失败、
崩溃或阻断均保留上一份有效结果。generation manifest 绑定输入 revision、Bundle、模板、输出 hash，
以及真实办公软件回算后的工作簿验证证据。

`sow-notes.md` 固定披露输入版本、As-Is 证据边界、关键推断、估算假设、待设计事项、各方责任、排除
范围、冲突处置、未决 NFR、风险和变更触发条件。`PASS_WITH_NOTES` 事项不能只留在内部日志。

成功摘要只报告审核结果、Feature/Story/AC/Task 的受影响、重算、复用、删除和最终数量，以及两个输出路径。自动生成
不代表客户已经签署、接受或赋予 SOW 法律效力。

## 工作簿规则

[SOW 模板](skills/generate/assets/sow-template.xlsx)是基础单元、任务规则、基础人天、复杂度、SIT、UAT、
公式和取整的唯一计算权威。正式工作簿固定为 `01-需求故事`、`02-任务清单`、`03-工作量汇总`、
`90-估算标准` 四个 Sheet。生成器先写候选件，再用 LibreOffice 在隔离目录中重算；只有 5 个命名
Table、全部输入行、公式缓存、校验结果、参数/目录、汇总和一页宽/纵向分页设置均复读通过，才以
`VERIFIED` 发布。公式和人天不会在 Python 或稳定 JSON 中重算。

当前只支持 XLSX 模板。每轮 `prepare` 读取当时的项目模板并保存 `.ai-sow/work/run-template.xlsx` 作为
本轮专用副本；Delivery 编译、终审、渲染和复读只使用该副本。运行期间改动项目模板不影响当前轮次；
下一轮检测到模板变化时重新编译 Delivery，而不是只用新模板重渲染旧 Task。成功 generation 还会在
自身的 `input/sow-template.xlsx` 保存本轮模板原字节并由 manifest hash 闭合。

Epic 表达完整业务线或长期技术能力域，Feature 表达用户可感知且可归责的模块；Story 使用自然的
`[模块/接口] 角色或对象＋动作` 标题，只归属一个 Feature、至少包含两条 AC 且最多包含四个 Task。
Delivery 先从来源完成并复核全部 Story/AC，再以这些已成立的 Story/AC 进入 Task 拆分；Task 不得反向
补造或改写上游范围。两遍仍写入同一候选，不增加用户批准步骤。
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
也不需要激活虚拟环境。完整约束见[运行时环境合同](references/runtime-environment.md)。

Windows 未启用长路径支持时，项目根路径必须短于 97 个字符。启用机器级长路径策略需要管理员权限和
用户明确同意，插件不会静默修改。

## 隐私与安全

`.ai-sow/` 包含输入原文和客户衍生数据，默认应加入项目 `.gitignore`。分享或提交前必须单独确认该目录
以及生成工作簿的授权范围。插件不会把凭据、私有源码、完整工具输出或本机绝对路径写入稳定 Bundle。

路径只能位于项目受管范围内；符号链接穿越和目录越界会被拒绝。Git 只用于普通协作，插件不会执行
clone、fetch、pull、reset、commit 或 push。

## 开发验证

```text
uv sync --project plugins/ai-sow --locked
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow/skills -q
uv run --project plugins/ai-sow --locked python plugins/ai-sow/tests/support/smoke_plugin.py --copy-plugin
```

copy smoke 在独立复制的插件和临时项目中覆盖 Greenfield、Brownfield、缺失往期 SOW 的阻断/恢复和
相同输入复用，并验证输出文件、manifest hash 闭包以及工作簿 Table 与公式。
