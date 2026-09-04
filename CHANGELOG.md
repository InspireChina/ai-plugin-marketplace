# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的结构。当前版本尚未公开发布。

## 0.1.0-beta.1 - 未发布

### 新增

- 新增唯一公开入口 `ai-sow:generate`，支持 Greenfield/Brownfield 首次生成、输入恢复、结果复用、
  仅渲染与增量重编译。
- 新增宿主中立 Python `NextAction`/文件协议；公共操作固定为
  `start / submit / hydrate / resume / approve / abandon / status`，运行时不依赖 Codex CLI 或
  Claude Code CLI。
- 新增不可变 input revision、单 active run、typed action/group、execution receipt、Stage 1/2/3
  checkpoint、artifact approval、generation proof closure 与原子 `current.json`。
- 新增唯一 `ai-sow-model-v1`，统一保存 InputItem/Scope Closure、Epic/Feature、Design/Integration/NFR/
  Policy、Story/AC、Task/Dependency/Effective Start Match 和各 Owner annotation/decision。
- 新增 R1 Source Audit/Scope Join、R2 Story/Design 与 R3 Task/Estimation 独立评审、Theme Join、
  Adjudication 和最小影响 repair plan。R1 repair 后必须再次独立复核，不能带 finding 进入 Stage 2。
- 新增 `REUSE / RENDER_ONLY / DELTA_COMPILE / FULL_COMPILE` 路由；路由由完整 hash proof closure 与
  `lowestRecoveryStage` 决定。
- 新增用户对精确 artifact manifest 的批准门禁；只有 layered review、renderer 和 Office 验证全部
  闭合后才允许发布。
- 新增 PRD、HLD、Greenfield 问卷与 SOW 标准模板；来源支持 UTF-8 Markdown/文本、HTML、
  TypeScript/TSX 与 XLSX，往期 SOW 只接受 XLSX。
- 新增 macOS/Linux 与 Windows bootstrap，在插件安装副本内准备 uv 0.11.7、managed Python 3.12、
  锁定依赖和隔离 `.venv`。
- 新增可恢复 validation campaign、模型效率 benchmark 协议与独立复制插件 smoke。
- 将缺少逐样本收据的 `75970b2` 历史数据登记为不可用于数值比较的部分基线，并以完整 32 样本配对
  manifest 作为 70% 性能/Token 改善声明的硬门禁。

### 变更

- 每个模型 action 强制 `FRESH_NO_HISTORY`。worker 只读取本 action 的 prompt、packet、reference 与
  hydrate 证据；主对话、兄弟 action、前序阶段和后续阶段不继承其历史。
- action record 只保存项目相对 result path 和 SHA-256，不复制 submission、证据正文或完整工具输出；
  恢复时从不可变结果文件复读并验 hash。
- 新 request 的 `resume` 先做 cheap gate；无效 request 不影响 active run，有效 request 才关闭旧 run、
  创建新 revision 并从安全边界继续。
- Brownfield 未提供往期 SOW 时记录 `priorSowState = NOT_PROVIDED` 并建立新基线，不虚构历史承诺。
- 三阶段 Owner 写集合固定：Stage 1 维护 Scope/Design，Stage 2 维护 Story/AC，Stage 3 维护 Task/
  Estimation；下游不得反向修改上游。
- 模型输出改为绑定 expected node hash 的 typed replacement set。整组 sibling result 全部封存后才一次
  应用；未受影响增量节点保持 ID 和规范 JSON 不变。
- Theme Join 必须绑定全部 leaf result hash 并保留 findings；同一 subject 的冲突结论必须由新的
  Adjudicator 显式选择，编排器不得静默覆盖。
- 当前只支持 XLSX 模板。每个 input revision 保存模板本轮专用副本；任务目录语义变化会重新编译
  Delivery，纯 renderer/模板字节变化才允许 `RENDER_ONLY`。
- `generation-renderer-v8` 绑定 `package_renderer.py`、`workbook.py`、`office_engine.py` 与
  `story_notes.py` 的 fingerprint。generation manifest 同时保存 `rendererSha256`。
- 正式工作簿固定为 `01-需求故事`、`02-任务清单`、`03-工作量汇总`、`90-估算标准` 四个 Sheet 和
  五个命名 Table；LibreOffice 真实回算并复读公式、缓存、目录、参数和汇总后才能达到 `VERIFIED`。
- copy smoke 改为直接运行复制插件的 Python API，覆盖 Greenfield、Brownfield、输入恢复、`REUSE`、
  无 Reviewer 的 `RENDER_ONLY` 和保留未受影响下游节点的 `DELTA_COMPILE`。
- copy smoke 的临时文件、worker stdout/stderr 与失败收据保存在项目或精确 work-dir；失败时不删除
  现场。读取守卫验证运行时不访问 marketplace，也不写出插件/项目边界。
- 用户问题统一逐项说明问题、为什么要问、答案决定什么和未回答后果；批准展示自然语言摘要与可读
  Markdown/Excel，内部 hash 和阶段 token 不作为确认正文。
- 失败或迟到的模型 action 可由公共 `submit` 在固定两次预算内重发；run state 改为内容寻址快照，
  action plan/record 与 active marker 之间的中断可从不可变事实恢复。
- 默认自动化排除会哈希绑定原 artifact、失效精确下游 action group、重建 Stage 1 checkpoint 并立即
  从 Story/AC 重跑；批准页放弃和公共 `abandon` 都会写入 artifact-bound 终态决定并永久失效旧工件。
- Theme Join 与 Adjudication 逐字段保留原 finding，冲突按全部 subject 建索引；物理 shard 上限按
  单个逻辑主题计算，跨主题超过八个时由宿主分批发放；跨评审同 ID 同内容 finding 全局去重，同 ID
  异内容返回结构化冲突诊断。
- `REUSE` 前始终复核当前 renderer 与 generation proof closure；输入 revision 相同但 renderer 漂移时
  进入 `RENDER_ONLY`。
- 配对 benchmark 新增机械 `compare`：精确验证 32 样本矩阵、必需 ACTION/STAGE 覆盖、三种收据粒度、
  按 policy 重算全部收据 outcome、校验 ACTION→STAGE→RUN 聚合、签名/哈希、输入、环境、cache
  namespace、执行配置和完整 token/wall/review 成本；
  分类失败输出可审计 FAIL receipt，`SATISFIED` 必须由仓库验证器重新求值得到精确 PASS receipt。
- Input Revision、generation staging 与渲染/复读临时目录均移入项目 `.ai-sow/`；渲染临时目录按
  context 隔离，避免并发项目共享进程级临时目录；XLSX 来源使用只读流式加载，并限制文件、ZIP 解压、
  Sheet、声明维度、行列、单元格与文本总量。

### 移除

- 移除预发布的多 Skill Owner 工作流、`ScopeBundle`/`DeliveryBundle` 双稳定模型、旧 accept 命令、
  人工中间批准和旧 candidate/run-plan 合同。
- 移除 Codex/Claude CLI 运行时调用、字段级未校验 patch、Python 公式计算、旧业务数据写入兼容路径、
  PDF/Word/PowerPoint 解析与自动 Git 操作。

### 安全与隐私

- `.ai-sow/` 保存客户原文与衍生数据，默认应被用户项目版本控制忽略。
- 路径越界、符号链接穿越、损坏输入、action/Schema/hash 漂移和 Office 验证失败均 fail closed；
  last-known-good 不被覆盖。
- 自动生成结果只用于离线评审、估算和签署准备，不代表客户签署、验收或产生法律效力。
