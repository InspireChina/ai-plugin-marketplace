# AI Plugin Marketplace 设计规格

- 日期：2026-09-02
- 当前 Beta：`0.1.0-beta.1`
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
  -> final_review
  -> package_renderer
```

- `intake` 固化请求、验证来源格式、生成语义锚点并比较最近成功输入；
- `scope_compiler` 生成 `ScopeBundle`，拥有 Feature、Effective Start、Design、Integration 和 NFR；
- `delivery_compiler` 生成 `DeliveryBundle`，拥有 Story、AC、Task、依赖和估算输入；
- `final_review` 只产生 `PASS / PASS_WITH_NOTES / BLOCKED`，检查跨层追踪、完整性和固定估算边界；
- `package_renderer` 只读取终审通过的 Bundle 与模板，确定性生成 `sow.xlsx` 和 `sow-notes.md`。

内部模块不能演化为新的公开 Skill，也不能把用户重新暴露给内部模式、批次或中间批准步骤。

## 输入与原型分析

PRD 和 HLD 只接受 UTF-8 Markdown（`.md`）；往期 SOW 只接受 `.xlsx`；补充材料接受 UTF-8 纯文本
（默认 Markdown）、HTML、TypeScript、TSX 或 `.xlsx`。PDF、Word、PowerPoint 和其他需要专用解析器
的格式不受支持，运行时依赖中不得引入对应解析器。

Greenfield 不要求往期 SOW。Brownfield 至少提供一份适用往期 SOW 和现状增量声明；缺失时返回
`BLOCKED`。HTML/TypeScript/TSX 原型既是源码输入，也是功能与交互证据：编译器提取入口、页面、
用户动作、触发、状态变化、校验、权限、异常和可观察结果。源码不足且 Demo 可运行时，宿主可按需
使用 Playwright 或 Computer Use 验证交互，结论必须追溯到原型来源且不能静默覆盖 PRD/HLD。

## 输入、稳定数据与发布事务

插件维护三类稳定数据：`InputManifest`、`ScopeBundle`、`DeliveryBundle`。它们和模板共同决定 Package；
Package 不拥有新的范围事实。

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

输入 revision 和 generation 都不可变。候选与终审先在 `work/` 完成，输入与输出目录发布并复读成功后，
最后原子替换 `current.json`。失败或阻断不会修改当前指针，因此上一份有效 SOW 始终可用。

语义未变化的对象保留 ID；含义变化时创建新 ID。输入变化从来源锚点定位受影响 Feature，扩展共享
Design、Integration、NFR、Assumption 或 Task 的引用闭包，完整替换受影响切片。未受影响切片原字节
保留；工作簿和说明始终完整重渲染，不对 OOXML 做局部 patch。

## 工作簿计算权威

`skills/generate/assets/sow-template.xlsx` 是任务目录、基础人天、复杂度、SIT、UAT、风险、公式和取整
的唯一计算权威。Python 和 JSON 不复制这些计算口径，也不执行 Excel 公式。生成器保留命名 Table、
公式原型、样式、行高、自动筛选、数据验证和跨 Sheet 引用，并在发布前复读结构与公式。

普通文本以 `= / + / - / @` 开头时按文本安全写入。任何改变工作簿确定性投影的实现都必须更新
renderer contract 与由 `package_renderer.py`、`workbook.py` 组成的 fingerprint baseline。

## 安装后运行模型

Codex 或 Claude Code 安装插件后，Skill 从已加载 `skills/generate/SKILL.md` 解析绝对
`<plugin-root>`。平台 bootstrap 位于：

- macOS/Linux：`skills/generate/scripts/bootstrap.sh`
- Windows：`skills/generate/scripts/bootstrap.ps1`

普通插件用户无需预装 uv、Python 或 Python 依赖。bootstrap 在插件安装副本内固定准备 uv 0.11.7、
managed Python 3.12、锁定依赖和 `.venv`，再调用唯一 orchestrator。后续执行复用
`<plugin-root>/.venv/bin/python` 或 `<plugin-root>/.venv/Scripts/python.exe`，不依赖 shell profile、
PATH 中的 uv、手工激活环境或仓库相对路径。

Windows bootstrap 在任何项目写入前检查路径预算。启用机器级长路径策略需要用户明确同意；插件不得
静默修改系统策略或绕过 UAC。

## 隐私与安全

`.ai-sow/` 可能保存客户原文和衍生数据，默认应被用户项目版本控制忽略。稳定数据、公共仓库、日志和
测试 fixture 不保存凭据、客户 SOW 原文、私有源码、完整工具输出或本机绝对路径。项目输入、输出和
来源引用使用受管项目相对路径；路径越界和符号链接穿越必须 fail closed。

Git 只用于普通协作。插件不 clone、fetch、pull、reset、commit、push 或发布版本。

## 验证与发布边界

验证分四层：

1. 根测试检查 marketplace、manifest、文档链接、Schema/template hash 和单 Skill 发布面；
2. generate 测试覆盖输入格式、范围/交付编译、增量闭包、终审、发布和工作簿；
3. 仓库验证器检查自包含边界、版本身份、renderer fingerprint 和公开文本；
4. copy smoke 只复制 `plugins/ai-sow/`，在独立项目中运行 Greenfield、Brownfield、阻断恢复和无变化复用。

copy smoke 还验证生成目录精确文件集合、manifest hash 闭包、工作簿 Table/公式和说明文档，并用读取
守卫阻止运行时访问复制插件与测试项目之外的路径。

CI 使用 Python 3.12 和 uv 0.11.7，覆盖 Ubuntu、macOS 和 Windows。该矩阵证明自动化测试运行于三种
GitHub-hosted runner，不等同于物理 Windows 11、Codex Desktop 或 Excel Desktop 的实机认证。

## 开源治理

仓库与插件使用 Apache License 2.0。插件目录保留独立 `LICENSE` 和 `NOTICE`，保证单独分发仍携带
授权信息。发布版本必须同步两个 manifest、Python PEP 440 版本、`uv.lock`、fixture、README、验证器
和 `CHANGELOG.md`；未经明确要求不创建 tag、不推送、不发布。
