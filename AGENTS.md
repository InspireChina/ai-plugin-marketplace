# AI Plugin Marketplace 项目指南

## 适用范围

本文件适用于整个仓库。仓库用于发布可审查、可独立安装的 Codex 插件；当前插件是 `plugins/ai-sow/`。

- 开始修改前先阅读根目录 `README.md` 和 `CONTRIBUTING.md`，并检查工作区状态和最近提交。
- 修改 marketplace 布局、安装方式或发布边界时，读取 `docs/architecture/ai-plugin-marketplace-design.md`。
- 修改 AI SOW 领域合同、阶段边界或数据语义时，读取 `plugins/ai-sow/docs/AI_SOW_PLUGIN_DESIGN.md` 和 `plugins/ai-sow/docs/CONTEXT.md`。
- 修改某个 Skill 时，完整读取该 Skill 的 `SKILL.md`；其合同、脚本、夹具和测试由该 Skill 自己维护。
- 修改用户可见语言或机器 token 时，读取 `plugins/ai-sow/references/output-language.md`。

## 修改原则

1. 先确定变更归属、权威来源和兼容边界，再修改最小必要范围。
2. 行为变更由测试证明；文档、合同、实现和发布元数据保持同步。
3. 保留用户已有的未提交修改，避免覆盖无关文件。
4. 临时文件只用于当前验证，完成后清理；可复用能力进入现有 Python 脚本或测试支持代码。
5. 未经用户明确要求，不创建提交、不推送、不发布版本。

## 插件与运行边界

- 每个插件必须自包含于 `plugins/<plugin-name>/`，运行时不得读取 marketplace 根目录或其他插件的文件。
- 插件的依赖、资产、运行时代码、文档和测试都放在插件目录内；独立复制后的插件必须仍可运行。
- marketplace 条目、插件目录名和 `.codex-plugin/plugin.json` 中的名称保持一致。
- AI SOW 脚本默认不跨 Skill import，也不读取其他 Skill 的 schema、fixture、test、asset 或 script。只有必须统一的 HLD/Go-live 门禁语义使用 `plugins/ai-sow/runtime/review_gates.py`。
- Skill 命令从已加载 `SKILL.md` 的位置解析插件路径，不依赖源码 checkout 的绝对路径。

## AI SOW 工作流与数据所有权

权威阶段顺序为：

```text
setup
  -> analyze-requirement
  -> analyze-as-is
  -> generate-design
  -> generate-story
  -> generate-task
  -> generate-sow
```

- Owner Skill 先完成专业工作并形成可读评审材料；用户明确批准后，才编译、验证和发布稳定 JSON。结构化草稿不能代替评审。
- 六份稳定交接数据各有唯一 Owner。下游只读 `.ai-sow/data/...`，发现上游事实需要变化时退回 Owner 修改。
- BUSINESS requirements 只由 `analyze-requirement` 维护；TECHNICAL requirements 只由 `generate-design` 维护。联合视图只存在于内存，不创建第三份 merged requirements。
- `.ai-sow/reviews/generate-design.md` 是 HLD/Go-live 批准合同，不是第七份稳定 JSON；Story、Task 和最终生成必须使用相同门禁语义复核。
- `setup` 只维护项目身份、目录和模板，`generate-sow` 只投影已批准数据；两者不承担业务分析。
- ID 在语义不变时保持稳定；实质含义变化时创建新 ID，不复用旧 ID 指代新对象。

## 工作簿与估算

对于 `plugins/ai-sow` 下的工作簿任务，仓库的 Python 生成器是实现权威。

- 当结构化输入和项目模板可以复现目标 XLSX 时，修改并测试 `plugins/ai-sow/skills/generate-sow/scripts/generate_sow.py` 或 `plugins/ai-sow/skills/generate-sow/scripts/workbook.py`，再重新生成工作簿。
- 直接修改已提交的 XLSX 前，先判断它是否来自模板、fixture 或稳定 AI SOW JSON；可复现的问题优先修复上游并再生文件。
- `.ai-sow/templates/sow-template.xlsx` 是任务规则、基础人天、复杂度、SIT、UAT、风险、公式和取整的唯一计算权威。Python 和 JSON 不复制计算口径，也不执行 Excel 公式。
- 公式只来自模板。填表逻辑必须保留命名 Table、公式原型、样式、行高、自动筛选和跨 Sheet 引用，并通过复读验证。
- `@oai/artifact-tool` 和 `.mjs` 只用于视觉检查、渲染或无法由结构化输入复现的一次性修复。一次任务只保留一个临时 `.mjs`，验证完成后删除；可复用生成能力使用 Python 实现。
- 普通 XLSX 文本按文本安全写入；不得把以 `=`、`+`、`-` 或 `@` 开头的普通内容解释为公式。

## 语言与隐私

- 面向用户的说明、评审材料和业务自由文本默认使用简体中文。
- 命令、路径、文件名、JSON 属性、Schema 字段、枚举、ID、哈希、Sheet 名、Table 名和公式保持合同原值，不做翻译或规范化改写。
- 稳定数据和公共仓库不保存凭据、客户 SOW 原文、私有源码、完整工具输出、本机绝对路径或其他敏感信息。
- `.ai-sow/` 可能包含客户衍生数据；生成工作簿和项目输入默认不视为可公开内容，提交前检查项目的忽略与共享策略。

## 测试与验证

先运行与修改范围最接近的测试。涉及插件行为、合同、模板、生成器或发布面时，在交付、提交、推送或发布前运行完整检查：

```text
uv sync --project plugins/ai-sow --locked
uv run --project plugins/ai-sow --locked python -m unittest discover -s tests -v
uv run --project plugins/ai-sow --locked python scripts/validate_repository.py
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow/skills -q
uv run --project plugins/ai-sow --locked python plugins/ai-sow/tests/support/smoke_plugin.py --copy-plugin
```

- 纯文档修改至少运行根测试、仓库验证器和 `git diff --check`；若文档中的命令、路径、版本、合同或安装流程变化，运行完整检查。
- 工作簿变更同时验证结构、公式、引用和关键样式；涉及可见布局时增加渲染或 Excel 视觉检查。
- 真实平台支持只能由对应实机证据声明。CI 和合成测试不能替代 Windows 11 实机或桌面 Excel 验收。

## 文档与发布同步

- 用户可见行为变化时更新相关 README、设计/合同文档和 `CHANGELOG.md`。
- 发布版本必须同步插件 manifest、`pyproject.toml` 的 PEP 440 版本、`uv.lock`、验证器常量、项目 fixture、README 和变更日志。
- 修改 SOW 标准或模板时，保持说明文档、原始资产、fixture、副本哈希和生成测试一致。
- 公共文档使用项目相对链接；新增或修改链接后运行仓库根测试验证目标存在。

## 代码审查规则

- **独立安装：** 标记任何读取插件目录之外运行时文件的实现。安全路径是把依赖移入插件目录，并用 `smoke_plugin.py --copy-plugin` 验证独立副本。
- **数据所有权：** 标记下游 Skill 修改上游稳定数据或复制上游 Schema/业务逻辑的实现。安全路径是由 Owner 修改并让下游只读稳定路径。
- **评审门禁：** 标记在用户批准前发布稳定 JSON，或绕过 HLD/Go-live、Uncertainty、引用完整性检查的流程。
- **计算权威：** 标记在 Python/JSON 中硬编码基础人天、倍率、公式或取整规则的实现。安全路径是复读模板并投影数据。
- **合同兼容：** 标记未同步测试、fixture、文档和版本面的 Schema 或枚举变更；兼容性影响必须明确记录。
- **隐私：** 标记公共文件中的客户内容、凭据、私有仓库信息、本机路径或可反推出这些信息的完整工具输出。

## 完成条件

变更只有在范围内行为已验证、文档与合同已同步、临时产物已清理、工作区中无意外文件，并且交付说明准确列出修改与验证结果后才算完成。
