# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的结构。当前版本尚未公开发布。

## 0.1.0-beta.1 - 未发布

### 新增

- 新增唯一公开入口 `ai-sow:generate`，一次完成 Greenfield/Brownfield 首次生成、增量更新和阻断恢复。
- 新增 PRD、HLD、Greenfield 最小问卷和 SOW 标准模板；PRD/HLD 只接受 UTF-8 Markdown，往期 SOW
  只接受 XLSX，补充材料支持纯文本、HTML、TypeScript、TSX 和 XLSX。
- 新增原型功能与交互分析合同；源码不足且 Demo 可运行时，可使用 Playwright 或 Computer Use 核验。
- 新增 `InputManifest`、`ScopeBundle`、`DeliveryBundle` 三类稳定合同，以及来源锚点和稳定 ID 决策。
- 新增按 Feature 引用闭包执行的切片更新；无变化输入复用结果，仅 renderer 合同变化时重渲染 Package。
- 新增 `PASS / PASS_WITH_NOTES / BLOCKED` 自动终审与固定估算边界。
- 新增不可变 input revision、generation、原子 `current.json` 指针和 last-known-good 恢复模型。
- 新增确定性 `sow.xlsx` 与 `sow-notes.md` 输出，manifest 绑定输入、Bundle、模板和输出 hash。
- 新增 macOS/Linux 与 Windows bootstrap，在插件安装副本内准备 uv 0.11.7、managed Python 3.12、
  锁定依赖和隔离 `.venv`。
- 新增 Greenfield、Brownfield、缺失往期 SOW 阻断/恢复与相同输入复用的独立复制 E2E。

### 变更

- 问题统一为自包含合同，逐项展示问题、为什么要问、答案决定什么和未回答后果；fresh-context 终审
  自动执行，只有确实需要用户输入或确认时才使用自然语言结论与可读评审文件，内部 hash 不作为用户
  确认正文。
- 每个通过完整问题包 hash 校验的答案现在形成稳定 `QUESTION_ANSWER` 语义锚点，Scope、AC、终审与
  增量影响分析统一使用精确 SourceRef；只改答案时保留锚点 identity 并记录 `MODIFIED`，未回答或无效
  绑定不形成证据；重复 `questionId` 或文档 sourceId 与问答 sourceId 冲突时在写入 pending 前阻断。
- 每轮开始固定项目 XLSX 模板的本轮专用副本，Delivery 编译、终审、渲染与 LibreOffice 复读共用
  同一份快照；新一轮模板变化时完整重新编译 Delivery，成功 generation 保留自身的模板副本。
- 将 Epic、Feature、Story、AC、Task、技术/交付工作、Effective Start 和问题编写规则拆分为安装包内
  可按阶段加载的 reference；Task 具体目录、人天、S/M/L 复杂度与 X/拆分条件只从 `90-估算标准` 读取。
- 收紧 Task 编写与评审指引：接口 Task 一行只表达一个可独立交付对象，内部校验归入接口 AC；语义质量由当前来源、模板和 Reviewer 判断，机械编译器不再用中文标题关键词猜测业务含义。
- Delivery 编写固定为同一候选内的两遍流程：先完成并复核 Epic/Feature/Story/AC 的层级与来源闭包，再从已成立的 Story/AC 进入 Task 拆分；终审 packet 逐条提供 AC 所属 Story、精确来源和可解析状态，机械层不再用中文业务关键词猜测语义。
- Delivery 第一遍增加一次性原子来源义务闭包清单：逐项保留并列指标、阈值、责任、禁止项、变化触发和实际触发，覆盖跨 Feature 规则及适用 Integration/NFR；`sourceRefs` 只保留各自贡献必要判断的最小集合，Technical Story 按可独立验证的目标族拆分，并禁止把常规 SIT/UAT 与独立移交成果拼成 Story。
- SOW 模板简化为需求故事、任务清单、工作量汇总、估算标准四个 Sheet，继续作为当前任务目录、基础人天、
  复杂度、SIT、UAT、公式和取整的唯一计算权威。
- 生成器先产生候选件，再用 LibreOffice 隔离回算并完整复读模板公式、Table 计算列、数据验证、保护
  与缓存结果；打印布局保持一页宽但允许纵向分页，避免长任务清单被压缩为不可读的单页；发布存储层
  独立复审暂存件，只有精确匹配 manifest 的 `VERIFIED` 证据才允许发布，失败时保留 last-known-good。
- Delivery 移除可推导的 Story 类型与 `description`、AC 序号/理由、Task 重复依赖及 Effective Start 名称副本；保留所有
  判断、计算、评审和追踪所需字段。
- Epic、Feature、Story 增加层级、自然标题和技术工作分类规范；Story 改为通过唯一 `featureId` 归属一个 Feature，并增加至少两条 AC、拒绝“完成/实现”式标题和最多四个 Task 的编译门禁；跨业务
  Feature 的可靠性、质量验证、发布和移交先形成技术 Feature，避免拼接式“子需求”和超大 Story。
- `01-需求故事` 简化为九列并移除内部“故事路径”，Task 直接引用唯一 Story 名称；AC 与任务列表使用逐行可扫视格式，对象特异备注只出现一次，跨 Feature 通用事项集中进入配套说明。
- 新增锚点按候选 Scope 对象引用的 `(sourceId, anchorId, sha256)` 精确身份定位基线 Feature，替换集合
  只使用旧 ID且初次完整编译为空；发布统计统一为
  `affected / recomputed / reused / deleted / final`。
- Scope 提前阻断待决定承诺和无法建立固定边界的假设；具备责任方、处理方式、估算边界和变化触发条件的待确认假设由 `PASS_WITH_NOTES` 承接。`IN_SCOPE` Feature 必须具有供应商责任边界，避免把纯客户或第三方工作计入供应商估算；终审 packet 明示各 note 类别允许绑定的 subject ID。
- Marketplace、插件 manifest、README、架构、领域术语、安全说明和贡献流程统一为单 Skill 发布面。
- 项目直接开发人天改为直接汇总 Task 人天，UAT 也基于适用 Story 下的原始 Task 人天计算；Story 展示取整不再因拆分粒度形成额外人天。
- 项目模板仍是已知内置版本、且未自行修改时，后续 `prepare` 会安全采用新版内置模板；检测到项目侧模板改动（包括首次发布前的定制）时继续保留项目版本。
- `generation-renderer-v7` 由 `package_renderer.py`、`workbook.py`、`office_engine.py` 与 `story_notes.py` 的 fingerprint baseline 锁定；Story 验收条件统一使用符号点，任务列表显示任务类型/工作方式/复杂度，跨 Feature 通用假设不再重复进入 Story 备注；Scope 和
  Delivery 编译合同分别为 v2 和 v5，稳定 Delivery Bundle/Slice 为 v3。

### 移除

- 移除预发布原型中的八个阶段/维护 Skill、多阶段稳定 JSON、人工中间批准、独立影响协调协议及相关
  Schema、fixture、命令和测试。
- 移除 PDF、Word、PowerPoint 和其他专用文档解析路径；当前除 XLSX 外只处理 UTF-8 文本来源。
- 不提供旧命令别名、旧业务数据迁移、候选 Schema 双轨、功能开关或兼容执行路径；历史 generation manifest 的旧合同 token 只作为只读证据触发当前合同完整重编译或重渲染，不允许生成旧格式结果。

### 安全与隐私

- `.ai-sow/` 保存客户原文和衍生数据，默认应被用户项目版本控制忽略。
- 路径越界、符号链接穿越、损坏输入、无可信 Brownfield 起点和发布 hash 不一致均 fail closed。
- 自动生成结果仅用于评审、估算和签署准备，不代表客户签署、验收完成或产生法律效力。

## 已取代的预发布历史

在 `0.1.0-beta.1` 发布前曾实现过多阶段专业分工、逐包确认和独立修正流程。该实现从未形成公开兼容
承诺，已由上述单入口架构整体取代；本版本不维护迁移或兼容行为。
