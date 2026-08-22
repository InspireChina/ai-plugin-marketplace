# AI SOW

AI SOW 是一个 Codex 插件，用于将需求和当前系统现状转换为可评审、可追溯的
工作说明书（SOW）工作簿。它的脚本会校验 AI 编写的阶段交接数据，并确定性地
生成最终工作簿。

## 前置条件

- 支持本地 marketplace 的 Codex
- Python 3.12
- [uv](https://docs.astral.sh/uv/) 0.11.7 或兼容版本

Codex 会创建独立的已安装插件副本。首次调用脚本时，uv 会根据已锁定的
`pyproject.toml` 和 `uv.lock` 准备运行环境。更新插件不会修改用户项目。

## 工作流

按以下顺序使用各 Skill：

1. `setup`
2. `analyze-requirement`
3. `analyze-as-is`
4. `generate-design`
5. `generate-story`
6. `generate-task`
7. `generate-sow`

每个 Owner Skill 都会先产出可供人工评审的分析，再编译为稳定的 JSON 交接数据。
各 Skill 仅通过文档规定的 `.ai-sow/data/` 路径交换数据；它们不会导入彼此的代码、
schema、测试或资产。

## 运行时路径

命令必须从已加载的 `SKILL.md` 解析 `<plugin-root>`，不能从 marketplace checkout
解析。如果 `<skill-root>` 是包含已加载 `SKILL.md` 的绝对目录，则
`<plugin-root>` 为 `<skill-root>/../..`。当前工作目录必须保持为用户项目根目录。

例如，在用户项目中运行：

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/setup.py" --help
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" --project-root .
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/generate_sow.py" --project-root .
```

请将尖括号 token 替换为解析后的绝对路径，不要逐字运行这些示例。

## Contract 0.1 / SOW 1.3

Contract 0.1 / SOW 1.3 采用严格约束。BUSINESS Epic/Feature 由需求分析维护，
TECHNICAL Epic/Feature 由方案设计维护，下游只在内存中联合。As-Is 独立登记技术输入
与生效起点；Story 不保存类型，一行 Task 对应一个基础单元实例。Task 只保存基础单元、
工作模式、复杂度、理由和必要引用；任务族与人天由随附 v1.3 工作簿带出和计算。
设计评审中的 HLD Coverage 与 Go-live Assessment 是 Story、Task 和最终生成的强制批准门禁。
模板包含 13 个任务族、37 个基础单元；单张配置表直接维护“新建 / 调整 / 接入复用”
三个人天列，复杂度系数位于项目参数表。

完整边界请参阅[设计文档](docs/AI_SOW_PLUGIN_DESIGN.md)和
[领域上下文](docs/CONTEXT.md)。

## 生成数据与敏感数据

插件会在用户项目的 `.ai-sow/` 下写入项目元数据、复制的往期 SOW 输入、稳定 JSON
交接数据、评审、暂存文件和生成的工作簿。这些文件可能包含客户需求、仓库事实、
估算和机密源材料。

marketplace 仅对自身 fixture 忽略 `.ai-sow/runtime/`。在其他仓库中使用本插件前，
必须明确选择该项目的策略：忽略敏感的生成/输入路径，或仅对已批准的稳定 contract
文件进行版本控制。未经评审，绝不能发布 `.ai-sow/inputs/`、运行时暂存内容或生成的
客户交付物。

## 开发

在 marketplace 根目录运行：

```text
uv sync --project plugins/ai-sow --locked
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow/skills -q
```

AI SOW 不会安装 Python 或 uv，不会提交到 Git，不会执行电子表格公式，不提供事务
恢复，也不会将 XLSX 中的编辑反向导入。
