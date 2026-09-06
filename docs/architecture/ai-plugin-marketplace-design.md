# AI Plugin Marketplace 设计规格

- 日期：2026-09-02
- 当前 Beta：`0.1.0-beta.2`
- 目标稳定版本：`0.1.0`
- SOW 标准：`1.3`

## 目标与发布身份

本仓库发布可审查、可独立安装的 Codex 与 Claude Code 插件。Marketplace ID 为
`ai-plugin-marketplace`，展示名为 `AI Plugin Marketplace`，Publisher 为 `Inspire`。首个插件 ID、
目录名和 manifest 名称均为 `ai-sow`；其唯一公开 Skill 是 `ai-sow:generate`。

两份 marketplace 目录都把 `ai-sow` 指向 `./plugins/ai-sow`，安装策略为 `AVAILABLE`，鉴权策略为
`ON_INSTALL`，分类为 `Productivity`。插件 manifest 的名称、版本和描述必须一致。

## 仓库边界

```text
ai-plugin-marketplace/
├── .agents/plugins/marketplace.json
├── .claude-plugin/marketplace.json
├── .github/
├── docs/architecture/
├── plugins/
│   └── ai-sow/
│       ├── .codex-plugin/plugin.json
│       ├── .claude-plugin/plugin.json
│       ├── skills/generate/
│       ├── runtime/
│       ├── docs/
│       ├── references/
│       ├── tests/
│       ├── pyproject.toml
│       └── uv.lock
├── scripts/
├── tests/
└── README.md
```

Marketplace 根目录只负责目录发现、治理、CI 和多插件发布。每个 `plugins/<name>/` 都是可单独复制、
安装、验证和运行的完整单元；运行时不得读取 marketplace 根目录或其他插件。AI SOW 的依赖、合同、
模板、脚本、测试和参考资料全部位于 `plugins/ai-sow/`。

插件级 `runtime/` 只保存不拥有业务稳定数据的通用诊断与安全项目 I/O。所有 AI SOW 业务合同、编译器、
渲染器和模板由 `skills/generate/` 自己拥有。

## AI SOW 单入口架构

`ai-sow:generate` 是一个深 Skill，内部 Module 是可测试 seam，不是用户命令：

```text
orchestrator
  -> intake
  -> scope_compiler
  -> delivery_compiler
  -> task_compiler
  -> final_review
  -> package_renderer
  -> generation_store
```

- `intake` 完成 cheap gate，固化来源 block、模板和不可变 input revision；
- `scope_compiler` 拥有 Stage 1 的 InputItem、Scope Closure、Epic/Feature 与 Design/NFR/Policy；
- `delivery_compiler` 拥有 Stage 2 的 Story/AC，不能反向修改 Scope；
- `task_compiler` 拥有 Stage 3 的 Task、Dependency、Effective Start Match 与 Estimation Annotation；
- `final_review` 在各阶段完整验证后执行 fresh Review、条件 Owner IR Repair 和 PASS checkpoint；
- `package_renderer` 只读取 reviewed SOW Model 与 revision 模板，确定性生成 Package；
- `generation_store` 独立复核 artifact、approval 和 generation proof closure，再原子切换 current。

内部模块不能演化为新的公开 Skill，也不能把用户重新暴露给内部模式、批次或中间批准步骤。

## 输入与原型分析

PRD 和 HLD 只接受 UTF-8 Markdown（`.md`）；往期 SOW 只接受 `.xlsx`；补充材料接受 UTF-8 纯文本
（默认 Markdown）、HTML、TypeScript、TSX 或 `.xlsx`。PDF、Word、PowerPoint 和其他需要专用解析器
的格式不受支持，不提供对应输入解析路径；pypdf 仅复读本流程产生的 Office PDF renders。

Greenfield 不要求往期 SOW。Brownfield 未提供适用往期 SOW 时记录 `NOT_PROVIDED` 并建立新基线，
不能虚构历史承诺；若缺口实质改变范围或估算，则返回 `REQUEST_INPUT` 或安全终态。
HTML/TypeScript/TSX 原型既是源码输入，也是功能与交互证据：编译器提取入口、页面、
用户动作、触发、状态变化、校验、权限、异常和可观察结果。源码不足且 Demo 可运行时，宿主可按需
使用 Playwright 或 Computer Use 验证交互，结论必须追溯到原型来源且不能静默覆盖 PRD/HLD。

## 输入、稳定数据与发布事务

插件维护不可变 input revision、一份 reviewed `SOW Model`、三个 stage checkpoint、各阶段 fresh Review
decision、artifact approval 与 generation manifest。Package 只投影这些证明闭合的数据，不拥有新事实。

```text
.ai-sow/
├── current.json
├── inputs/revisions/<revision>/
├── generations/<generation>/
│   ├── manifest.json
│   ├── data/sow-model.json
│   └── output/{sow.xlsx,sow-notes.md}
└── work/runs/<run>/{actions,groups,candidates,checkpoints,reviews,artifacts}
```

input revision、action result/record、checkpoint 和 generation 都不可变。候选、独立评审、Office 复读与
用户批准先在 `work/` 完成；发布存储层再次验 hash 后发布 generation，最后原子替换 `current.json`。
失败、等待或阻断不会修改当前指针，因此上一份有效 SOW 始终可用。

每个新 run 都是 `FULL_COMPILE`，只根据本次完整 request 明列的来源和冻结政策编译，不读取旧 generation
或隐藏 work 决定业务内容。Brownfield 只消费显式 `PRIOR_SOW` 与本次 `declaredChangeContext`；同一未完成
run 只恢复自己的 StagePlan、Attempt 和 checkpoint。业务变化使用 abandon/start，稳定身份由受控规则生成。
工作簿和说明完整渲染，不对 OOXML 做局部 patch。

## 工作簿计算权威

`skills/generate/assets/sow-template.xlsx` 是任务目录、基础人天、复杂度、SIT、UAT、风险、公式和取整
的唯一计算权威。Python 和 JSON 不复制这些计算口径，也不执行 Excel 公式。生成器保留命名 Table、
公式原型、样式、行高、自动筛选、数据验证和跨 Sheet 引用，并在发布前复读结构与公式。

普通文本以 `= / + / - / @` 开头时按文本安全写入。任何改变工作簿确定性投影的实现都必须更新
`generation-renderer-v12` 与由 `package_renderer.py`、`workbook.py`、`office_engine.py`、
`story_notes.py` 组成的 fingerprint baseline。

## 安装后运行模型

Codex 或 Claude Code 安装插件后，Skill 从已加载 `skills/generate/SKILL.md` 解析绝对
`<plugin-root>`。平台 bootstrap 位于：

- macOS/Linux：`skills/generate/scripts/bootstrap.sh`
- Windows：`skills/generate/scripts/bootstrap.ps1`

普通插件用户无需预装 uv、Python 或 Python 依赖。bootstrap 在插件安装副本内固定准备 uv 0.11.7、
managed Python 3.12、锁定依赖和 `.venv`，再调用唯一 orchestrator。后续执行复用
`<plugin-root>/.venv/bin/python` 或 `<plugin-root>/.venv/Scripts/python.exe`，不依赖 shell profile、
PATH 中的 uv、手工激活环境或仓库相对路径。

Codex 与 Claude Code 只负责安装 Skill 和承载模型 worker。运行时不调用 `codex`、Claude Code CLI 或
其他代理产品命令；宿主通过同一 Python `NextAction`/文件协议推进。每个模型 worker 都是
`FRESH_NO_HISTORY`，跨 action 状态只通过 Schema 有效、hash-bound 项目文件传递。

Windows bootstrap 在任何项目写入前检查路径预算。启用机器级长路径策略需要用户明确同意；插件不得
静默修改系统策略或绕过 UAC。

## 隐私与安全

`.ai-sow/` 可能保存客户原文和衍生数据，默认应被用户项目版本控制忽略。稳定数据、公共仓库、日志和
测试 fixture 不保存凭据、客户 SOW 原文、私有源码、完整工具输出或本机绝对路径。项目输入、输出和
来源引用使用受管项目相对路径；路径越界和符号链接穿越必须 fail closed。

Git 只用于普通协作。插件不 clone、fetch、pull、reset、commit、push 或发布版本。

## 验证与发布边界

最终验证包含以下门禁；每 Task 只执行变更相关的 unit 和直接边界 integration：

1. 根测试检查 marketplace、manifest、文档链接、Schema/template hash 和单 Skill 发布面；
2. generate 测试覆盖显式输入、范围/交付完整编译、本轮冻结恢复、fresh Review、发布和工作簿；
3. 仓库验证器检查自包含边界、版本身份、renderer fingerprint 和公开文本；
4. 锁定输入的 validation campaign fail-fast，并从精确失败 checkpoint 恢复；
5. copy smoke 只复制 `plugins/ai-sow/`，直接用 Python API 运行 Greenfield、Brownfield、abandon/start，
   并验证相同输入、模板字节变化和业务变化时的三次新 run 完整编译与独立三阶段 fresh Review。

copy smoke 还验证 fresh context、生成目录精确文件集合、manifest hash 闭包、工作簿 Table/公式和说明
文档，并用读取守卫阻止运行时访问复制插件与测试项目之外的路径。失败收据、worker stdout/stderr 和
项目内临时文件在分类前保留，测试 harness 不删除失败现场。

CI 使用 Python 3.12 和 uv 0.11.7，覆盖 Ubuntu、macOS 和 Windows。该矩阵证明自动化测试运行于三种
GitHub-hosted runner，不等同于物理 Windows 11、Codex Desktop 或 Excel Desktop 的实机认证。

## 开源治理

仓库与插件使用 Apache License 2.0。插件目录保留独立 `LICENSE` 和 `NOTICE`，保证单独分发仍携带
授权信息。发布版本必须同步两个 manifest、Python PEP 440 版本、`uv.lock`、fixture、README、验证器
和 `CHANGELOG.md`；未经明确要求不创建 tag、不推送、不发布。
