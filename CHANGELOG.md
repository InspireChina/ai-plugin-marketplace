# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的结构。当前版本尚未公开发布。

## 0.1.0-beta.1 - 未发布

### 新增

- 新增唯一公开入口 `ai-sow:generate`，一次完成 Greenfield/Brownfield 首次生成、增量更新和阻断恢复。
- 新增 PRD、HLD、Greenfield 最小问卷和 SOW 标准模板；PRD/HLD 只接受 UTF-8 Markdown，往期 SOW
  只接受 XLSX，补充材料支持纯文本、HTML、TypeScript、TSX 和 XLSX。
- 新增原型功能与交互分析合同；源码不足且 Demo 可运行时，可使用 Playwright 或 Computer Use 核验。
- 新增 `InputManifest`、`ScopeBundle`、`DeliveryBundle` 三类稳定合同，以及来源锚点和稳定 ID 决策。
- 新增按 Feature 引用闭包执行的切片更新；无变化输入复用结果，模板单独变化时只重渲染 Package。
- 新增 `PASS / PASS_WITH_NOTES / BLOCKED` 自动终审与固定估算边界。
- 新增不可变 input revision、generation、原子 `current.json` 指针和 last-known-good 恢复模型。
- 新增确定性 `sow.xlsx` 与 `sow-notes.md` 输出，manifest 绑定输入、Bundle、模板和输出 hash。
- 新增 macOS/Linux 与 Windows bootstrap，在插件安装副本内准备 uv 0.11.7、managed Python 3.12、
  锁定依赖和隔离 `.venv`。
- 新增 Greenfield、Brownfield、缺失往期 SOW 阻断/恢复与相同输入复用的独立复制 E2E。

### 变更

- SOW 模板继续作为 37 项基础单元、13 个任务族、基础人天、复杂度、SIT、UAT、风险、公式和取整的
  唯一计算权威；生成器只投影稳定数据并复读工作簿。
- Marketplace、插件 manifest、README、架构、领域术语、安全说明和贡献流程统一为单 Skill 发布面。
- renderer contract 由 `package_renderer.py` 与 `workbook.py` 的 fingerprint baseline 锁定。

### 移除

- 移除预发布原型中的八个阶段/维护 Skill、多阶段稳定 JSON、人工中间批准、独立影响协调协议及相关
  Schema、fixture、命令和测试。
- 移除 PDF、Word、PowerPoint 和其他专用文档解析路径；当前除 XLSX 外只处理 UTF-8 文本来源。
- 不提供旧命令别名、旧项目迁移、Schema 双轨、功能开关或兼容层。

### 安全与隐私

- `.ai-sow/` 保存客户原文和衍生数据，默认应被用户项目版本控制忽略。
- 路径越界、符号链接穿越、损坏输入、无可信 Brownfield 起点和发布 hash 不一致均 fail closed。
- 自动生成结果仅用于评审、估算和签署准备，不代表客户签署、验收完成或产生法律效力。

## 已取代的预发布历史

在 `0.1.0-beta.1` 发布前曾实现过多阶段专业分工、逐包确认和独立修正流程。该实现从未形成公开兼容
承诺，已由上述单入口架构整体取代；本版本不维护迁移或兼容行为。
