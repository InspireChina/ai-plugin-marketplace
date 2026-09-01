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
- 只有模板变化：保留 Scope/Delivery，只完整重渲染 Package；
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
崩溃或阻断均保留上一份有效结果。generation manifest 绑定输入 revision、Bundle、模板和输出 hash。

`sow-notes.md` 固定披露输入版本、As-Is 证据边界、关键推断、估算假设、待设计事项、各方责任、排除
范围、冲突处置、未决 NFR、风险和变更触发条件。`PASS_WITH_NOTES` 事项不能只留在内部日志。

成功摘要只报告审核结果、本次 Feature 新增/更新/删除数、重算 Story/Task 数和两个输出路径。自动生成
不代表客户已经签署、接受或赋予 SOW 法律效力。

## 工作簿规则

[SOW 模板](skills/generate/assets/sow-template.xlsx)是基础单元、任务规则、基础人天、复杂度、SIT、UAT、
风险、公式和取整的唯一计算权威。生成器只投影已经通过终审的稳定数据，保留命名 Table、公式原型、
样式、行高、自动筛选、数据验证和跨 Sheet 引用，并在发布前复读。

任务模型、37 项基础单元和 13 个任务族见
[SOW 任务分类与开发交付人天标准](docs/reference/SOW任务分类与开发交付人天标准_v1.3.md)。示例工作簿见
[SOW 估算与生成示例](docs/reference/SOW估算与生成示例_v1.3.xlsx)。

## 运行时

普通用户无需预装 Python 或 uv。macOS/Linux 使用 `bootstrap.sh`，Windows 使用 `bootstrap.ps1`；
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
