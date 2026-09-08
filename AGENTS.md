# AI Plugin Marketplace 项目指南

## 适用范围

本文件适用于整个仓库。仓库发布可审查、可独立安装的 Codex 与 Claude Code 插件；当前插件是
`plugins/ai-sow/`。

- 开始修改前阅读根 `README.md`、`CONTRIBUTING.md`，检查工作区状态和最近提交。
- 修改 marketplace 布局、安装或发布边界时，读取 `docs/architecture/ai-plugin-marketplace-design.md`。
- 修改 AI SOW 领域合同、模块边界或数据语义时，读取
  `plugins/ai-sow/docs/AI_SOW_PLUGIN_DESIGN.md` 和 `plugins/ai-sow/docs/CONTEXT.md`。
- 修改 `ai-sow:generate` 时，完整读取 `plugins/ai-sow/skills/generate/SKILL.md`；合同、脚本、fixture、
  reference、asset 和测试由该 Skill 自己维护。
- 修改用户语言或 machine token 时，读取 `plugins/ai-sow/references/output-language.md`。

## 修改原则

1. 先确定变更归属、权威来源和兼容边界，再修改最小必要范围。
2. 行为变更由测试证明；文档、合同、实现和发布元数据保持同步。
3. 保留用户已有的未提交修改，不覆盖无关文件。
4. 临时文件只用于当前验证，完成后清理；可复用能力进入现有 Python 脚本或测试支持代码。
5. 未经用户明确要求，不创建提交、不推送、不发布版本。

## 插件与运行边界

- 每个插件自包含于 `plugins/<plugin-name>/`，运行时不得读取 marketplace 根目录或其他插件。
- marketplace 条目、插件目录和两份 plugin manifest 的名称、版本与描述保持一致。
- AI SOW 只公开 `ai-sow:generate`；内部 Module 不形成额外 Skill、别名或兼容入口。
- `skills/generate/` 拥有全部稳定业务 Schema、编译器、renderer、fixture、reference、asset 和测试。
- 插件级 `runtime/` 只复用不拥有业务稳定数据的诊断和安全项目 I/O，不得演化为共享业务编译器。
- Skill 从已加载 `SKILL.md` 解析插件根路径，不依赖源码 checkout 的绝对路径或 marketplace 布局。
- `smoke_plugin.py --copy-plugin` 必须证明复制插件不访问原仓库或测试项目之外的文件。

## AI SOW 工作流与数据所有权

唯一公开入口内部按以下顺序推进：

```text
ai-sow:generate
  -> intake
  -> scope_compiler
  -> 完整校验 / fresh Review / ScopeCheckpoint
  -> delivery_compiler / 完整校验 / fresh Review / StoryAcCheckpoint
  -> task_compiler / 完整校验 / fresh Review / TaskCheckpoint
  -> final_review
  -> package_renderer
  -> generation_store
```

- `orchestrator` 只维护公开 NextAction 状态机、本轮 FULL_COMPILE 与 checkpoint 恢复、action 发放和可恢复事务，
  不拥有业务规则。
- 唯一稳定业务真相是 `ai-sow-model-v1`。`scope_compiler` 独占 Stage 1 写集合，`delivery_compiler`
  独占 Stage 2 Story/AC 写集合，`task_compiler` 独占 Stage 3 Task/Estimation 写集合；各阶段以不可变
  checkpoint 关闭，后续 Owner 不得反向修改上游写集合。
- `intake` 独占不可变 input revision；`final_review` 独占 fresh Review、条件 Owner IR Repair 与
  StageCheckpoint 证明；`package_renderer` 只投影 reviewed SOW Model；`generation_store` 独占 artifact 批准绑定、
  不可变 generation 和原子 `current.json` 切换。后二者都不拥有新的范围事实。
- PRD/HLD 只接受 UTF-8 Markdown，往期 SOW 只接受 `.xlsx`；补充材料接受 UTF-8 纯文本、HTML、
  TypeScript、TSX 或 `.xlsx`。不得引入 PDF、Word、PowerPoint 等专用解析路径。
- 原型必须提取页面、功能、动作、触发、状态、校验、权限、异常和可观察结果；源码不足且 Demo 可运行
  时可用 Playwright 或 Computer Use 核验，结论必须追溯到原型来源。
- Greenfield 不要求往期 SOW；Brownfield 建议提供适用往期 SOW，未提供时记录
  `priorSowState = NOT_PROVIDED` 并建立新基线，不虚构历史承诺。
- 评审 decision 只允许 `PASS / REPAIRABLE_SEMANTIC / INPUT_REQUIRED / CONTRACT_GAP / OWNER_BUG`；
  Repairable finding 指定 roots 可定向替换、合并或拆分；同 Owner 引用影响闭包可同步调整，其余结果保留。普通自动修复最多两个语义 revisions；Task 的精确用户实施澄清可追加一次；达到自动上限后，明确人工裁定可逐次授权一个字段修复候选，原终态、累计次数、完整证明与 fresh Review 必须保留。
  阶段 PASS 自动继续。完整合同见 `skills/generate/references/stage-seal.md`（相对插件根）。
- 新 run 不从旧 generation/隐藏缓存恢复业务内容；业务输入变化 abandon/start，同一 run 只消费自己的
  冻结计划、Attempt 和 checkpoint。身份由 stable_ids 的受控表生成。
- input revision 与 generation 发布后不可变；候选和输出全部验证后最后切换 `current.json`。失败或阻断
  不得覆盖 last-known-good。

## 工作簿与估算

对于 `plugins/ai-sow` 下的工作簿任务，仓库 Python renderer 是实现权威，Excel 模板是计算权威。

- 可复现的输出问题优先修改并测试
  `plugins/ai-sow/skills/generate/scripts/package_renderer.py` 或
  `plugins/ai-sow/skills/generate/scripts/workbook.py`，再重新生成工作簿。
- 权威模板是 `plugins/ai-sow/skills/generate/assets/sow-template.xlsx`；项目副本位于
  `.ai-sow/templates/sow-template.xlsx`。
- 模板独占任务目录、基础人天、复杂度、SIT、UAT、公式和取整。Python/JSON 不复制计算口径，
  也不执行 Excel 公式。共享 Task 仅由 renderer 投影 Story 的任务列表与覆盖校验公式；全部计价、汇总与取整公式保持模板原值。
- renderer 保留命名 Table、公式原型、样式、行高、自动筛选、数据验证、保护和跨 Sheet 引用，并
  在发布前复读。
- 修改确定性输出语义时更新当前 renderer 合同版本及
  `contracts/renderer-fingerprint-baseline.json`，不得只刷新 hash 掩盖合同变化。
- `@oai/artifact-tool` 和 `.mjs` 只用于视觉检查或一次性修复；一次任务只保留一个临时 `.mjs`，完成后
  删除。可复用生成能力使用 Python。
- 普通 XLSX 文本按文本安全写入，不得把 `= / + / - / @` 开头的内容解释为公式。

## 语言与隐私

- 用户说明、评审、问题、风险和业务自由文本默认使用简体中文。
- 命令、路径、文件名、JSON 属性、Schema 字段、枚举、ID、hash、Sheet/Table 名和公式保持合同原值。
- 稳定数据和公共仓库不保存凭据、客户无关原文、私有源码、完整工具输出或本机绝对路径。
- `.ai-sow/` 包含客户输入和衍生数据；默认不视为可公开内容，提交或分享前检查忽略与授权策略。

## 测试与验证

每个 Task 只验收本次变更：新增/修复行为测试、直接受影响的契约与调用边界局部集成。
按实际风险选择测试 node ID 或过滤表达式；不把历史整文件列表、整插件/全仓或完整端到端当作每 Task
默认门禁。发现具体跨模块失败才扩大定位，并说明理由。

测试层级分别运行（可附加路径或 `-k` 选择当前改动）：

```text
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow -m unit -q
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow -m integration -q
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow -m e2e -q
```

unit 不得通过共享 fixture 或 helper 导入执行完整生成、Office/浏览器或批准发布流程。
保留关键失败/边界/缺陷回归；实际合并重复测试时记录行为由何处承接，禁止全局 skip/xfail 掩盖问题。
完整分层定义见 `plugins/ai-sow/tests/README.md`。

最终集成/交付验证仍执行锁定依赖同步、根 unittest、仓库验证器、插件全量 pytest、独立复制 smoke，
以及原计划规定的真实 Office/浏览器、严格顺序 Greenfield→Brownfield 和工作簿复读门禁。
这些最终门禁不自动前移至每个 Task；未运行项不得报告为通过。文档修改只验证实际受影响的链接/规则，
日常检查 `git diff --check`。工作簿可见布局修改仍需相应视觉验证。

## 文档与发布同步

- 用户行为变化时同步 README、设计/合同、manifest、marketplace 描述和 `CHANGELOG.md`。
- 发布版本同步 plugin manifest、`pyproject.toml` PEP 440 版本、`uv.lock`、验证器、fixture 和 README。
- 修改 SOW 标准或模板时同步说明文档、原始 asset、参考工作簿、fixture hash 和生成测试。
- 公共文档使用项目相对链接；新增或修改链接后运行根测试。
- 旧设计、验收报告或发布记录若必须保留，必须显式标记为“已取代”，不能表现为当前命令或状态。

## 代码审查规则

- **独立安装：** 标记任何运行时读取插件目录之外实现文件的代码。
- **数据所有权：** 标记 Owner 越过 Stage 写集合、下游修改上游 checkpoint、复制业务 Schema，或让
  orchestrator 拥有业务判断的实现。
- **评审门禁：** 标记绕过阶段完整验证、fresh Review/PASS、artifact hash 批准或 Office
  复读而发布 SOW Model/Package 的流程。
- **不可变发布：** 标记回写 revision/generation、先切 current 指针或失败时破坏 last-known-good 的实现。
- **计算权威：** 标记在 Python/JSON 中硬编码基础人天、倍率、公式或取整规则的实现。
- **合同兼容：** 当前预发布重构不提供旧流程兼容；标记任何未同步测试、fixture、文档和版本面的变更。
- **隐私：** 标记公共文件中的客户内容、凭据、私有仓库、本机路径或完整敏感工具输出。

## 完成条件

变更只有在范围行为已验证、文档与合同同步、临时产物清理、工作区没有意外文件，并且交付说明准确
列出修改和验证结果后才算完成。

Scope 独占 PriorStateSnapshot 与 ChangeGraph；三个 Owner 不跨写。
内部 checkpoint 自动封存；运行中用户只回答问题或补充材料。严格顺序 Greenfield→Brownfield 的
pair harness 不属于插件业务 Owner。两侧 verified artifact 均完成后，共同展示两份 Excel，
只取得一个 PairDecision。APPROVE 深绑定共同 manifest 与双方工作簿；两个 generation/current
都匹配才算发布。中断重放同一决定；REJECT 使用 hash 寻址的完整新 request，按受影响侧重跑后重新共同评审。

`pypdf` 仅用于读取本流程生成的 Office PDF renders，不接受用户 PDF 业务输入。
