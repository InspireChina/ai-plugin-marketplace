# AI Plugin Marketplace

一个面向实用、可审查 AI 工作流的开源插件市场，同时发布 Codex 与 Claude Code 安装入口。
首个插件 AI SOW 通过唯一入口 `ai-sow:generate`，把 PRD、HLD、适用的往期 SOW 和补充材料
自动转换为可追溯的 SOW 工作簿及配套说明。

## 插件

| 插件 | 版本 | 用途 |
|---|---|---|
| [AI SOW](plugins/ai-sow/README.md) | 0.1.0-beta.2 | 按显式输入完整编译或恢复本轮 SOW，并保留不可变输入与输出历史。 |

## 支持平台

支持 macOS、Linux 和 Windows 11 x64。普通插件用户无需预装 Git、Python、
[uv](https://docs.astral.sh/uv/) 或 Python 依赖；`ai-sow:generate` 的平台 bootstrap 会在插件
安装副本内准备 uv 0.11.7、managed Python 3.12、锁定依赖和隔离 `.venv`。Windows 未启用长路径
支持时，项目根路径需短于 97 个字符。

Codex 与 Claude Code 只负责安装 Skill 和承载模型 worker。AI SOW 运行时使用同一套 Python
`NextAction`/文件协议，不调用 `codex`、Claude Code CLI 或其他代理产品命令；Windows 使用
`bootstrap.ps1` 与 `.venv/Scripts/python.exe`，macOS/Linux 使用 `bootstrap.sh` 与
`.venv/bin/python`。

## 安装

### Codex

```text
codex plugin marketplace add InspireChina/ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
codex plugin list
```

本地开发时可注册本地 checkout：

```text
git clone https://github.com/InspireChina/ai-plugin-marketplace.git
codex plugin marketplace add /absolute/path/to/ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
```

### Claude Code

```text
/plugin marketplace add InspireChina/ai-plugin-marketplace
/plugin install ai-sow@ai-plugin-marketplace
```

本地开发时使用同样的仓库 checkout：

```text
git clone https://github.com/InspireChina/ai-plugin-marketplace.git
/plugin marketplace add /absolute/path/to/ai-plugin-marketplace
/plugin install ai-sow@ai-plugin-marketplace
```

安装后只出现 `ai-sow:generate`。用户用自然语言给出项目资料和目标即可，不需要了解内部模式或
分阶段命令。

## 使用 AI SOW

每次调用都提供或更新一份标准请求：

- PRD：UTF-8 Markdown（`.md`）；
- HLD：UTF-8 Markdown（`.md`）；
- 往期 SOW：仅 Excel（`.xlsx`）；Brownfield 建议提供，未提供时明确记录 `NOT_PROVIDED` 并建立新基线；
- 补充材料：UTF-8 纯文本（默认 Markdown）、HTML、TypeScript、TSX 或 `.xlsx`；
- 项目标识、名称、生效日期，以及客户、供应商和第三方的高层责任边界。

PDF、Word、PowerPoint 和其他需要专用解析器的格式当前不支持。HTML/TypeScript/TSX 原型会被
作为功能与交互证据分析；源码不足且 Demo 可运行时，可以启动后用浏览器自动化或 Computer Use
核验页面、动作、状态、校验、权限、异常和可观察结果。

示例请求：

```text
使用 ai-sow:generate，根据 PRD、HLD 和 Greenfield 问卷生成本项目 SOW。
```

```text
使用 ai-sow:generate，根据 PRD、HLD、往期 SOW 和现状变化说明增量更新 SOW。
```

工作流会自动完成不可变输入归档、三阶段 SOW Model 编译、每阶段完整验证、fresh 独立评审、条件语义 Repair、工作簿渲染和 Office 复读。每个模型 action 都使用 `FRESH_NO_HISTORY`：只接收当前
action 的 prompt、packet、reference 和按需 hydrate 的证据，不继承主对话、兄弟 action 或前序阶段
历史，因此 E2E 主流程不会持续侵占模型上下文窗口。

资料不足时集中返回 `REQUEST_INPUT`；候选包、Office 双复读和全部可见 Sheet 的一次视觉评审都闭合后返回 `REQUEST_APPROVAL`，只有用户
批准精确 artifact manifest 后才原子发布。补充答案或修改范围时，先 abandon 当前 run，再用完整新
request start，创建新 run 并完整编译；上一份有效 SOW 始终不被覆盖。

每个问题都会逐项说明“问题、为什么要问、答案决定什么、未回答后果”。确认时展示自然语言结论；
内容较长时同时提供可打开的 Markdown 或 Excel 文件，内部 ID、hash 和阶段 token 不作为确认正文。

当前只支持 XLSX SOW 模板。每个 input revision 都保存模板的本轮专用副本；运行期间外部模板变化
不会改变已开始的本轮。相同输入、模板字节变化或业务变化都通过新 run 完整编译，并重新执行逐阶段评审。
同一未完成 run 的 resume 只恢复本轮冻结计划、Attempt 和 checkpoint。

正式工作簿采用四 Sheet 简化模板：`01-需求故事`、`02-任务清单`、`03-工作量汇总`、`90-估算标准`。
需求故事表固定九列且不暴露内部故事路径；Story 采用自然的角色/对象动作标题、至少两条可验收 AC，
每条 AC 以 `• ` 开头并独占一行。Task 直接引用唯一 Story 名称，Story 任务列表逐行显示
`[任务类型/工作方式/复杂度] 任务名称`。备注只显示对象特有的特殊情况、不确定性、风险、例外、依赖或
评审边界；跨 Feature 通用事项只进入配套说明，不在 Story 行重复。
发布前必须由 LibreOffice 实际回算并复读全部公式缓存、目录、参数、行级校验和汇总；缺少计算引擎或
验证失败时不会用候选文件覆盖上一份有效 SOW。

成功输出位于当前 generation：

```text
.ai-sow/generations/<generation>/output/sow.xlsx
.ai-sow/generations/<generation>/output/sow-notes.md
```

`.ai-sow/current.json` 始终指向最近一次成功结果。每个新 run 都是 `FULL_COMPILE`，只读取本次完整
request 明列的来源与政策；旧 generation 和隐藏 work 不参与业务输入。Brownfield 的往期 SOW 必须显式
列为 `PRIOR_SOW`，本次 `declaredChangeContext` 只约束本轮。

同 run 唯一允许的输入更新是 `resume --budget-policy ...`：至少增加一项 planned token、active-time 或
Demo 限额，其余配置保持原值。正文相同、限额降低、model/estimator/reserves/concurrency 变化均拒绝；
政策替换不创建业务 input revision，也不改写旧计划、Attempt 或 checkpoint。

自动生成结果用于评审和估算，不代表客户已经签署、接受或赋予 SOW 法律效力。

## 数据与隐私

`.ai-sow/` 包含客户原文、输入快照和衍生数据，应默认加入用户项目的 `.gitignore`，除非团队已经
明确批准其存储和共享策略。公共仓库、Issue、日志和测试 fixture 不得包含客户 SOW、凭据、私有源码
或完整敏感工具输出。

## 更新与卸载

Codex：

```text
codex plugin marketplace upgrade ai-plugin-marketplace
codex plugin remove ai-sow@ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
```

```text
codex plugin remove ai-sow@ai-plugin-marketplace
codex plugin marketplace remove ai-plugin-marketplace
```

Claude Code：

```text
/plugin marketplace update ai-plugin-marketplace
/plugin uninstall ai-sow@ai-plugin-marketplace
/plugin install ai-sow@ai-plugin-marketplace
```

```text
/plugin uninstall ai-sow@ai-plugin-marketplace
/plugin marketplace remove ai-plugin-marketplace
```

## 仓库与开发

```text
.agents/plugins/marketplace.json    Codex marketplace 目录
.claude-plugin/marketplace.json     Claude Code marketplace 目录
plugins/ai-sow/                     自包含插件包
scripts/                            仓库验证器
tests/                              Marketplace 级测试
.github/                            贡献模板与 CI
```

插件运行时不读取 marketplace 根目录或其他插件。架构和发布边界见
[Marketplace 设计规格](docs/architecture/ai-plugin-marketplace-design.md)。

以下命令仅面向贡献者；贡献者需要 Git、Python 3.12 和 uv 0.11.7：

```text
uv sync --project plugins/ai-sow --locked
uv run --project plugins/ai-sow --locked python -m unittest discover -s tests -v
uv run --project plugins/ai-sow --locked python scripts/validate_repository.py
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow/skills -q
uv run --project plugins/ai-sow --locked python plugins/ai-sow/tests/support/smoke_plugin.py --copy-plugin
```

完整要求见[贡献指南](CONTRIBUTING.md)。

## 添加其他插件

1. 创建 `plugins/<stable-plugin-name>/.codex-plugin/plugin.json` 和
   `plugins/<stable-plugin-name>/.claude-plugin/plugin.json`，保持名称、版本和描述一致。
2. 将运行时代码、依赖、资产、文档和测试全部放在插件目录内。
3. 在两份 marketplace 目录中添加指向同一插件目录的本地来源。
4. 扩展仓库验证器、测试、文档和发布说明。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。项目自行编写的模板、示例和文档采用同一许可证；
依赖项仍适用各自许可证。详见 [NOTICE](NOTICE)。

工作簿验证使用 `generation-renderer-v12`：现有汇总 Sheet 显示实体 ID 与公开 SourceRef；全部可见 Sheet 的 Office PDF renders 经一次独立视觉评审通过后，才向用户请求批准。每一步实际生成、Office 与复读都受 active-time 预算约束；预算增加后的恢复保留已完成输出。

内部 checkpoint 自动封存；运行中用户只回答问题或补充材料。严格顺序 Greenfield→Brownfield 的
pair harness 不属于插件业务 Owner。两侧 verified artifact 均完成后，共同展示两份 Excel，
只取得一个 PairDecision。APPROVE 深绑定共同 manifest 与双方工作簿；两个 generation/current
都匹配才算发布。中断重放同一决定；REJECT 使用 hash 寻址的完整新 request，按受影响侧重跑后重新共同评审。

生成后的 Scope、Story/AC 和 Task 优先按 findings 及影响范围局部修复，保留正确结果；普通 Repair 可调整、合并或拆分授权对象；共享测试资产保留独立 Story/AC，只计量一次，工作簿展示覆盖与费用归属。自动停止后，`resume --decision` 可绑定原终态与失败 Review，按明确用户裁定仅修允许字段、追加一个候选并 fresh Review，完整保留累计次数与消耗。具体合同见 [阶段自动封存](plugins/ai-sow/skills/generate/references/stage-seal.md)。

往期 Excel 大表按完整证据行分组，保留全部单元格、位置、哈希与表头，避免整张 Sheet 超出单次请求容量。阶段尚未发行计划工作便因容量等待时，修复分组后可从原 run 恢复，复用已完成的原型观察和检查点，不提高模型容量或重置消耗。
