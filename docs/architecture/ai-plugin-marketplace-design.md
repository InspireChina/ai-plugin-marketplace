# AI Plugin Marketplace 设计规格

日期：2026-08-20

## 目标

发布 AI SOW `0.1.0` / SOW `1.3` 首个稳定合同，形成一个可公开发布、可继续添加插件、可由 Codex 本地安装并从已安装插件目录独立运行的 marketplace 仓库。

## 标识

- 仓库目录与未来建议仓库名：`ai-plugin-marketplace`
- Marketplace ID：`ai-plugin-marketplace`
- Marketplace 展示名：`AI Plugin Marketplace`
- 首个插件 ID 与目录名：`ai-sow`
- 插件展示名：`AI SOW`
- Publisher：`Yuan Li`
- 目标稳定版本：`0.1.0`；SOW 标准版本：`1.3`
- Marketplace 条目分类：`Productivity`
- 安装策略：`AVAILABLE`
- 鉴权策略：`ON_INSTALL`

插件名称、插件目录和 manifest 的 `name` 必须始终一致。Marketplace 的 `source.path` 固定为 `./plugins/ai-sow`。

## 选择的架构

采用单仓库、多插件、自包含插件包：

```text
ai-plugin-marketplace/
├── .agents/plugins/marketplace.json
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── pull_request_template.md
│   └── workflows/ci.yml
├── docs/
│   ├── architecture/
│   │   ├── ai-plugin-marketplace-design.md
│   │   └── ai-sow-chinese-output-design.md
│   └── windows-11-validation.md
├── plugins/
│   └── ai-sow/
│       ├── .codex-plugin/plugin.json
│       ├── skills/
│       ├── docs/
│       ├── pyproject.toml
│       ├── uv.lock
│       ├── README.md
│       ├── LICENSE
│       └── NOTICE
├── scripts/
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── LICENSE
├── NOTICE
├── README.md
└── SECURITY.md
```

Marketplace 根目录只承担目录发现、开源治理、CI 和多插件编排。每个 `plugins/<name>/` 都必须是可单独复制、验证和运行的完整发布单元，不得依赖仓库根目录的 Python 配置、锁文件、脚本、模板或业务文档。

暂不拆分 marketplace 与 plugin 到不同仓库。只有当插件出现独立维护者、独立发布节奏或不同许可证时，才将该插件拆分为 Git-backed source。

## AI SOW 插件边界

AI SOW 的领域实现与参考资料全部位于 `plugins/ai-sow/`：

- 领域上下文：`plugins/ai-sow/docs/CONTEXT.md`
- 插件设计：`plugins/ai-sow/docs/AI_SOW_PLUGIN_DESIGN.md`
- Word 规则文档和 Excel 示例：`plugins/ai-sow/docs/reference/`
- Python 项目与锁文件：`plugins/ai-sow/pyproject.toml`、`plugins/ai-sow/uv.lock`

内部实施计划、本机绝对路径、运行时生成文件和 `.DS_Store` 不进入仓库的正式源代码提交。

插件 manifest 名为 `ai-sow`，首个稳定版本为 `0.1.0`，配套 SOW 标准为 `1.3`，并提供 Apache-2.0、关键词和规范化的 install-surface 文案。未知的 GitHub URL、主页、隐私条款和服务条款不使用占位值；远程仓库建立后再增加真实 HTTPS 地址。`defaultPrompt` 使用最多三个短字符串组成的数组。

## 安装后运行模型

Codex 安装本地 marketplace 插件时会创建独立的插件目录。AI SOW 运行时不得假设用户当前目录中存在 `plugin/skills/...`，也不得读取 marketplace 根目录。

setup 与后续 Skill 按以下规则运行脚本：

1. 从当前已加载 `SKILL.md` 的绝对路径确定 `<plugin-root>`：`skills/<skill-name>/SKILL.md` 的上两级目录。
2. `setup` 先运行平台对应的 Skill-local bootstrap，在插件安装副本内准备 uv 0.11.7、managed Python
   3.12、锁定依赖和 `.venv`，再初始化或只读复核项目。
3. 后续 Skill 从用户项目根目录执行命令，不改变当前工作目录，并直接使用 setup 建立的插件
   `.venv`：

   ```text
   "<plugin-root>/.venv/bin/python" "<plugin-root>/skills/<skill-name>/scripts/<script>.py" --project-root .
   ```

   Windows 使用等价的 `<plugin-root>/.venv/Scripts/python.exe`。
4. 不依赖 `PLUGIN_ROOT`、shell profile、PATH 中的 uv、手工激活虚拟环境或仓库根目录相对路径。

普通插件用户无需预装 uv、Python 或 Python 依赖。插件自带 `pyproject.toml` 与 `uv.lock`；首次
`setup` 在插件安装副本内按固定官方来源准备工具链，后续阶段只复用插件 `.venv`，不会修改用户项目
的依赖文件。Git、Python 和 uv 仍是仓库贡献者执行开发与 CI 命令的工具链，不属于插件安装条件。

这套调用方式的设计目标是在 macOS、Linux 和 Windows 路径上可表达。文档示例使用引号包围所有绝对路径，不提供仅适用于 POSIX shell 的启动器。当前发布已在真实 macOS 环境完成本地验收；Windows 11 仍为临时支持（`Provisional`），不能用 macOS 上执行的 Windows 分支合成测试或 GitHub 托管 CI 代替真实 Windows 11 验收。公开状态与实机清单见 [Windows 11 验证状态](../windows-11-validation.md)。

## Marketplace 元数据

`.agents/plugins/marketplace.json` 包含：

- 顶层 `name: "ai-plugin-marketplace"`
- `interface.displayName: "AI Plugin Marketplace"`
- 一个 `ai-sow` 条目
- 本地 source：`./plugins/ai-sow`
- 完整的 installation、authentication 和 category 字段

条目顺序就是展示顺序。后续插件默认追加，不自动重排。`policy.products` 在没有明确产品限制时省略。

## 开源治理与许可证

仓库和 AI SOW 插件使用 Apache License 2.0。插件包内保留独立 `LICENSE` 与 `NOTICE`，保证插件目录单独分发时仍携带授权信息。版权声明使用 `Copyright 2026 Yuan Li`。

本发布将项目代码、项目原创说明、SOW 模板和示例视为同一项目的可发布资产。Python 依赖只在运行时解析，不 vendoring 到仓库；`NOTICE` 说明主要依赖及其许可证，不复制依赖源码。

根目录增加：

- `CONTRIBUTING.md`：开发环境、目录约束、测试和 PR 要求
- `CODE_OF_CONDUCT.md`：行为标准和报告渠道
- `SECURITY.md`：支持版本、私密报告方式和响应边界
- `CHANGELOG.md`：Keep a Changelog 风格的版本记录
- Issue 表单和 PR 模板

用户项目生成的 `.ai-sow/` 可能包含客户资料。文档必须给出显式、可选择的忽略策略，不能在 marketplace 仓库中假设所有用户都应提交或忽略这些文件。

## CI 与验证

GitHub Actions 使用 Python 3.12 和 uv 0.11.7。测试矩阵覆盖 Ubuntu、macOS 和 Windows。CI 不依赖开发者机器上的 Codex skill 目录。该矩阵证明自动化测试在 GitHub-hosted runner 上执行，不证明物理 Windows 11、Codex Desktop、NTFS reparse point 或 Excel Desktop 的端到端兼容性。

仓库内验证分四层：

### 1. 静态目录和元数据

- Marketplace JSON 可解析且字段完整。
- `source.path` 位于仓库根目录内并指向真实插件。
- Marketplace entry、插件目录和 manifest 名称一致。
- Manifest 使用严格 semver，引用的所有相对路径都存在且位于插件内。
- 正式跟踪文件不存在本机绝对路径、旧 `plugin/skills` 命令、占位词或内部实施计划。

### 2. 插件单元与合同测试

- 使用 `uv sync --project plugins/ai-sow --locked` 验证锁文件。
- 运行 AI SOW 全量 pytest。
- 运行 plugin validator、仓库 validator、Marketplace 根测试与插件全量 pytest。
- 三份 SOW 模板副本保持字节一致。
- `0.1.0` manifest、schema、fixture 和 setup 常量与 SOW `1.3` 一致。

### 3. 发布边界测试

只复制 `plugins/ai-sow/` 到临时目录，不复制 marketplace 根目录。随后从另一个空目录：

- 使用复制后的 `pyproject.toml` 与 `uv.lock` 建立运行环境。
- 直接使用复制插件 `.venv` 的 Python 执行 Greenfield setup，证明后续命令不依赖 PATH uv。
- 复核审核 fixture 中五位 Owner 的 0.3 receipts 和六份稳定数据；不在 smoke 中重放 Owner 业务门禁。
- 使用同一插件 `.venv` Python 从审核 fixture 生成 SOW 包。

这一层证明独立插件副本不依赖源码仓库布局。

### 4. 本地 Codex 安装与端到端冒烟测试

使用 CLI 注册新 marketplace 根目录并安装插件：

```text
codex plugin marketplace add <absolute-path-to-ai-plugin-marketplace>
codex plugin add ai-sow@ai-plugin-marketplace
```

验收包括：

- `codex plugin marketplace list` 能解析新 marketplace。
- `codex plugin list` 显示 `ai-sow` 已安装并启用。
- 已安装目录中的 plugin manifest、skills、锁文件和模板完整。
- 从已安装插件目录而非源码目录，在全新临时项目中完成 Greenfield setup。
- 独立 Owner E2E 运行五位 Owner validator；copy smoke 则复核已审核 fixture 的五份 0.3 receipt，
  并使用安装副本 `.venv` Python 生成确定性 SOW 包，避免下游重放 Owner 业务门禁。
- 用 Microsoft Excel 打开临时输出、完整重算并保存；缓存值中公式错误数为零。
- 检查 13 个工作表、动态 As-Is 表、Task → Effective Start 追溯和三份模板哈希。
- 用全新的 Codex 进程确认安装后的 skill 可以被发现；当前任务不假设热重载。

安装和测试只写入 marketplace、Codex 的 marketplace/plugin 配置与独立临时测试目录。

以上本地验收目前是 macOS 证据。Windows 11 只有 CI 和合成分支覆盖；在 [Windows 11 验证状态](../windows-11-validation.md) 的实机检查全部通过并归档证据前，不将其标记为已验证平台。

## 错误处理

- Marketplace 注册失败时，不手改 `~/.codex/config.toml`；使用 `codex plugin marketplace` 命令检查和修复。
- 插件安装失败时，先验证 marketplace source 和 manifest，再重试安装。
- 端到端测试只使用唯一临时目录，不覆盖用户项目。
- 若新安装影响现有 Codex 插件状态，可用 CLI 删除 `ai-sow` 或 `ai-plugin-marketplace`，但不得删除其他 marketplace。

## 完成标准

任务仅在以下条件全部满足时完成：

1. 公开仓库只包含预期发布文件。
2. schema、contract、枚举和 XLSX 模板由仓库测试锁定；公开验证不依赖私有工作区或本机路径。
3. Marketplace 与插件均通过静态和官方本地校验。
4. 全量 pytest 在已声明的本地验收平台通过，CI 配置覆盖三种操作系统；CI 覆盖不等同于 Windows 11 实机通过。
5. 只复制插件目录的发布边界测试通过。
6. 本地 Codex 安装成功，已安装插件从空项目完成端到端冒烟测试。
7. Excel 实际重算没有公式错误，SOW 结构与 SOW `1.3` 合同一致。
8. 新仓库工作区干净，并提供安装、更新、卸载和贡献说明。
