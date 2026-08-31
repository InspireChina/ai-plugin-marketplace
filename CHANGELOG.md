# 变更日志

所有重要的用户可见变更都记录在此。

## 0.1.0-beta.1 - 未发布

- `reconcile` 支持在修正影响后缀的连续未发布末端使用 `PENDING`：首次发布可在一次整体评审中完成，
  而中间 Owner 缺失但更下游已发布时仍以非法后缀阻塞；稳定数据继续由各 Owner 的正常发布路径写入。
- 明确确定性脚本成功且无 diagnostics 即为最终可信结果，Stage 不再重复 hash、复读、枚举或调用等价
  检查；`generate-design` 与 `generate-task` 的执行合同统一引用该共享规则。
- `generate-sow` 新增生成器静态指纹基线，仓库验证器会检查 `generate_sow.py` 与 `workbook.py` 的
  SHA-256；生成语义变化必须同步提升 `generatorContract` 并刷新基线，避免合同漏升版。
- 新增 work-only 结构化 Finding 路由合同，以 `LOCAL / UPSTREAM / DECISION / MECHANICAL` 分类替代
  跨 Owner 自由文本交接；容量、驻场、待命、固定班次和 SLA 等商业承诺问题必须进入用户决策路径。
- `generate-task` 新增基础单元实例碰撞归一化：区分同一实例、不同交付对象和消费方接入，Renderer
  显式投影潜在碰撞组；同一 API 下的业务操作与读模型可按 API/数据模型基础单元分别保留。轻量
  diff-review 发现 patch 引入的 Task-local 误选时允许一次受限纠错与最终轻量复审；无法保留独立
  Task 的 Story 返回 Story Owner 删除或合并，不再用人工测试或空壳 Task 填充。
- 五个 Owner 的 context compiler 新增确定性分页合同：manifest 绑定页序、页 hash、32 KiB/8K
  预算及截断恢复协议；输入 fragments 与 candidate-derived review claims 分离，不再在 candidate
  尚未形成时发布空 claims。Claim 新增机器校验的 `FACT_VERIFIER_LOW / JUDGMENT_REVIEWER_DEEP`
  路由与按路由剩余项指标。
- diff-review 收敛为变更字段前后值、一跳直接闭包和相关 AC→Story→Feature 映射，设置 65536-byte
  硬预算并在超限时原子拒绝。五个 renderer 新增 Schema 顶层集合→评审区段发布认证，generate-sow
  增加长文本换行与行高持久化夹具。
- Requirement patch 支持白名单约束的多候选事务；同一 finding 跨 requirements 与来源处置时一次
  写入、一次 post-check、一次 packet 旋转，任一文档失败则整体回滚且不消耗修复轮次。
- Design patch 同步把 `design.candidate.json` 与 `requirements.candidate.json` 纳入 Owner 白名单；
  同一 Reviewer finding 跨目标设计和技术需求时可在一次 staging 事务中修复、复核并旋转 packet，
  避免只能修改其中一份候选而留下跨文档不一致。
- 把最终 E2E 暴露的三个下游返工点前移为审批前门禁：As-Is 在 packet 前阻断仍影响估算的
  Uncertainty；Design 确定性投影 BUSINESS/TECHNICAL Feature 边界配对矩阵并拒绝双重
  `END_TO_END` Owner；Story 在进入 Task 前要求 `OPERATIONAL_THRESHOLD` 具备量化阈值、明确
  结果责任方及逐 Feature AC 映射。
- 字段 patch 改为 candidate、audit、context、review projection、Owner post-check 和新 diff packet 的
  staging 事务；失败不改当前工作集且不消耗修复轮次。五个 Owner 生成不同的新 packet 时会原子归档
  旧 packet/reviewer/approval 到按旧 packet hash 命名的目录，并撤销当前路径上的旧授权 sidecar。
- 确定性 package 指纹升级为 `receipt-only-v2`，manifest 显式记录 `generatorContract`，reconcile 强制
  使用同一合同。generate-sow 成功 stdout 直接返回 workbook、manifest、package tree SHA-256 与
  文件数，供 Stage 信任内建复读结果而不再扩展全量 hash 检查。
- 按 Windows 全流程 E2E 的 26 条真实 findings 落地评审降本方案：新增 premises、确定性 repo facts、
  claims 分片与 hash 缓存、数量/绝对化/隐私门禁、唯一事实源、字段级 patch 与引用闭包、机械内循环、
  diff-review 以及逐 Owner 成本控制。保留原 Claude Haiku 4.5 / Sonnet 5 / Opus 路由，并增加 Codex
  `gpt-5.6-luna` / `gpt-5.6-terra` / `gpt-5.6-sol` 映射与 10% 假阴性抽检升级规则。
- Delivery 合同升级为 0.4，移除中间 Gap 实体：Story 直接引用 Feature，AC 保存相对 Effective Start
  的 `gapRationale` 与逐条 `carryForwardCommitmentIds`；Task 新增 Story→AC→Feature 可达性门禁，
  Story 新增跨 Feature 同名 AC 的 `FEATURE_OVERLAP_SUSPECTED` 回流诊断，工作簿保持直接按
  Story.featureId 投影；当前自测版本不提供旧 Delivery 的兼容迁移。
- As-Is 合同升级为 0.2，把 Topic 结论拆为已调查、证据不足、边界声明和不适用四态，并绑定对应
  Uncertainty/估算影响规则；新增九类按需仓库事实预投影与 26 条 Windows E2E 黄金回归夹具。
- 插件作为单一安装包共享 Owner-agnostic review runtime；各 Skill 继续独占稳定业务 Schema、专业
  renderer 与数据所有权，独立复制插件的 smoke 边界不变。

- 修复生成工作簿中长文本被固定 prototype 行高裁切的问题：所有动态业务表现在按最终可见换行文本
  与模板列宽确定性扩大数据行；`03-SOW主表` 的公式汇总列使用同一稳定输入中的 AC/Task 名称作为
  布局提示，不执行公式。新增长文本回归测试并同步确定性参考工作簿；生成指纹合同提升为
  `receipt-only-v2`，避免修复前后不同包树发生不可变 `packageId` 碰撞。

- 修复 Excel 2016/2019 打开生成工作簿时 `03-SOW主表` 的“验收条件”和“任务明细”为空：
  两列改用兼容旧版 Excel 的 `TEXTJOIN + IF` CSE 数组公式，并统一为每条内容添加项目符号。
  五张受保护业务表继续锁定公式与关系派生单元格及单元格格式，但允许用户编辑白色输入单元格、
  调整列宽和行高，并使用表头筛选与排序；生成器复读同时拒绝动态工作表函数前缀，并校验数组
  公式及保护权限没有退化。
- 修复 `90-系统现状` 的开工基线投影：`现状描述` 现在直接使用 Effective Start 自身的 `summary`，
  不再拼接调查截止日期的 Item 与开工前 Commitment 摘要，避免“当前不存在”与“预计开工前具备”
  在同一行互相矛盾，并阻止稳定 ID 经来源摘要泄漏到业务 Sheet。
- 收紧 Owner 生成前合同：`SCOPE_BOUNDARY` 的 Schema 与 validator 统一只接受 BUSINESS
  Epic/Feature；需求问卷 diagnostics 给出 `YES：<理由> / NO：<理由>` 精确格式；As-Is 新增
  Uncertainty→Topic 反向关联、Coverage 理由引用、枚举数词、Evidence 数量漂移和可见摘要 ID
  检查，把可确定的问题从高成本 Reviewer 前移到机械门禁。
- `analyze-as-is` 评审模板采用合同 finding 严重度下限，并规定 Topic 不复制 Evidence/工作记录的
  计数与清单；CodeGraph CLI 1.5.0 的 `files` 示例改用 `--path`。文档同时公开仓库快照必须位于
  项目根内的当前约束和项目内只读快照做法。
- 修复 Story Integration 的跨 Owner 无解状态：没有类型化 Design Decision 的纯实现集成允许空
  `decisionIds`，但必须提供结构化 `decisionRationale`；存在决策时继续要求它关联当前 Story
  Feature。Design review renderer 另要求共享相同或包含 Design Item 集合的 `IN_SCOPE`
  TECHNICAL Feature 逐对说明可独立验收的非重叠边界。
- 修复 Story 离线评审的 Integration 表遗漏：renderer 现在逐行投影 `deliveryBoundary` 与
  `targetKind`，让 Reviewer 无需回读 candidate 即可核对 `END_TO_END / PORT_ONLY` 及目标类型；
  新增回归测试锁定表头和实际字段值。
- 修复字段级 patch 的引用闭包误扩散：当前 Owner 不拥有的 Feature、Decision、Commitment 等
  外部 ID 不再作为遍历枢纽把无关对象串入 `syncSuspects`。`PATCH_CLOSURE_UNSYNCED` 现在明确返回
  候选未写入、精确确认字段、允许重试且不消耗成功 patch 轮次；共享合同规定逐项确认格式与一次
  原子拒绝后的修正重试，避免 Stage 在实际未应用修复时提前 `BLOCKED`。
- 冻结 Reviewer 对同一 packet 的第一次 `PASS/BLOCKED` 判断：五个 Owner 新增内容寻址
  `review-judgments/<packet-sha256>.json`，无新 packet 时拒绝结论翻转；validator 同时输出
  candidate-derived `artifactMetrics`，阶段摘要不再由 Agent 手算 Story、AC、Evidence 或 Task 数量。
- 修复 As-Is 离线评审的身份投影缺口：Commitment、Uncertainty 和 Evidence 表现在同时显示稳定
  ID 与 `name`；validator 按 candidate 逐条核对该映射，任何缺名或错名都会以
  `REVIEW_NAME_PROJECTION_MISSING` 阻塞，不再把关键名称留给 Reviewer 回读 JSON 发现。
- 发布者标识统一为 `Inspire`：Codex manifest 的 `author.name` 与 `interface.developerName`、
  Claude manifest 的 `author.name`、Claude marketplace 的 `owner.name`，以及根目录和插件目录
  `NOTICE` 的版权声明。`scripts/validate_repository.py` 新增 `validate_publisher_identity`
  强制这四个宿主可见字段一致，插件 manifest 的 `author` 也纳入双 manifest 一致性检查。

- `setup` 新增 Windows 长路径前置检查与经用户同意的补救路径。未启用长路径支持时 Windows 把
  路径限制在 260 字符内，而最深的受管路径需要 162 字符，项目根目录必须短于 97 字符。setup
  现在在写入任何文件前计算预算，不足时返回 `WINDOWS_LONG_PATH_REQUIRED` 并且不创建
  `.ai-sow`；`runtime/project_io.py` 另把写入期的 `ERROR_FILENAME_EXCED_RANGE` 转换成
  `PROJECT_PATH_TOO_LONG`。新增 `skills/setup/scripts/enable_long_paths.ps1`：不带 `-Apply`
  只报告状态，带 `-Apply` 时必须已提权才会写入 `LongPathsEnabled`。该脚本修改机器级系统
  策略，`SKILL.md` 要求 Stage 先说明影响并取得用户明确同意，不得静默执行或绕过 UAC。

- 新增 Claude Code 作为第二个宿主：仓库发布 `.claude-plugin/marketplace.json`，插件发布
  `plugins/ai-sow/.claude-plugin/plugin.json`，与既有 Codex manifest 并存并指向同一份
  `skills/`。两套 manifest 的插件集合、来源路径、`name`、`version` 和 `description` 由
  `scripts/validate_repository.py` 强制保持一致；README 同时给出两个宿主的安装、更新和
  卸载命令。
- 修复 Windows 结构化输出乱码：所有写 stdout 的 Skill 脚本在输出前把 stdout/stderr 固定为
  UTF-8，`bootstrap.ps1` 固定 `[Console]::OutputEncoding` 并置 `PYTHONUTF8=1`。此前在
  cp936 等非 UTF-8 代码页上，`OK`/`BLOCKED` JSON 中的中文会以本地代码页字节送出，调用方
  按 UTF-8 解码后得到乱码，阻塞诊断实际不可读。
- 修复 `bootstrap.ps1` 在 Windows PowerShell 5.1 下无法解析：该文件含中文但未带 UTF-8 BOM，
  5.1 会按 ANSI 代码页解码，在中文 Windows 上直接产生语法错误，Windows setup 入口无法启动。
  现以 UTF-8 带 BOM 保存，并加回归测试锁定该编码与实际解析结果。
- 加固 `bootstrap.ps1` 与 `bootstrap.sh` 的诊断对等：补齐 `BOOTSTRAP_DIRECTORY_FAILED` 和
  `PYTHON_CHECK_FAILED`，把原生命令的启动失败和 stderr 输出隔离成退出码，避免在
  `$ErrorActionPreference = "Stop"` 下抛出未捕获异常、绕过结构化 `BLOCKED` 契约；
  下载官方安装器时显式启用 TLS 1.2，并把本进程 `$PSHOME\Modules` 前置到 `PSModulePath`，
  以免从 PowerShell 7 会话继承的模块路径让 5.1 加载到不兼容内置模块。
- 修复测试套件的 Windows 可移植性：补齐 56 处 `read_text`/`write_text` 的显式 UTF-8 编码，
  29 处 `subprocess` 调用固定按 UTF-8 解码子进程输出，仓库验证器的路径诊断改用 POSIX 分隔符，
  独立副本冒烟检查按运行时合同优先解析插件私有 `uv` 而不是要求它位于 PATH。
  `.gitignore` 新增 `.ai-sow-tools/`，避免 bootstrap 下载的工具链留在工作区。
- 新增 `.gitattributes` 统一以 LF 检出。Git for Windows 默认 `core.autocrlf=true`，此前在
  Windows 上克隆会把整棵树转成 CRLF，使 `bootstrap.sh` 变成无法执行的 CRLF 脚本，并改变
  schema 与 canonical JSON 的字节，导致已提交的 SHA-256 断言和 packet 绑定失效。
- 修复 XLSX 生成在不同操作系统间不可复现：`normalize_xlsx` 此前沿用原始 ZIP 条目的
  `create_system` 和 Unix 权限位，这两个字段由运行平台而非输入决定，使同一份已批准数据在
  Windows 和 macOS 上产生不同的 `sow.xlsx` 字节，破坏 package 复用与 manifest 绑定。现固定
  为 Unix 宿主标记和 `0o600` 权限位；macOS 输出字节不变，Windows 结果与之对齐。
- `analyze-requirement` 测试改用 `write_bytes` 写 reviewer/approval sidecar，与其他四个 Owner
  一致；此前的 `write_text` 在 Windows 上会把结尾 `\n` 翻译成 `\r\n`，破坏 canonical JSON 绑定。
- 依赖 POSIX shell 或符号链接创建权限的测试改为按能力跳过，使 Windows 上缺失的平台能力
  显式可见，而不是表现为失败。

- 优化 SOW Excel 可用性：业务 Sheet 只展示唯一、非空的名称，稳定 ID 继续保存在 JSON；可翻译
  的枚举和下拉统一使用中文，层级列按需求、子需求、故事、验收条件、任务及其他信息排列。
- `04-验收条件` 隐藏结构化顺序；`05-任务明细` 以基础单元名称和“关联现状条目”选择任务依据，
  不再展示集成点；`06-集成点` 只在故事名称后展示唯一关联的集成任务名称；`07-假设清单`
  改为由 Story 单选引用的独立条目；`90-系统现状` 不再展示证据引用。
- 统一工作簿视觉与编辑权限：文字垂直居中，短值居中、长文本左对齐；公式和关系派生列浅灰、
  锁定并启用工作表保护，可填写列保持白色；`90-系统现状` 删除九类汇总和混合记录台账，只保留
  “主题名称 / 现状条目名称 / 现状描述 / 起点可用性”四列明细，主题与起点可用性为浅黄色下拉，
  任务下拉直接引用可见名称列；该页不启用保护。修复项目汇总浅绿色状态单元格的文字对比度。
- `generate-sow` 严格复核当前模板表头、公式原型、样式、名称引用、保护和输入哈希，示例工作簿
  与权威模板同步；不提供尚未发布的旧项目模板迁移。
- `setup` 新增 macOS/Linux 与 Windows 的确定性环境 bootstrap：在插件安装副本内自动准备 uv、
  managed Python 3.12、锁定依赖和 `.venv`，再执行项目初始化；BA/PM 无需管理员权限或终端
  安装步骤，网络/权限不足时在写项目之前 fail closed 并由 Codex 自动重试。
- setup 后的七个 Owner/生成/维护入口统一直接使用插件 `.venv` 的跨平台 Python 路径，不再依赖
  PATH 中的 uv；根 README、插件 README、架构、领域上下文、安全支持版本与运行时合同同步区分
  普通用户和仓库贡献者的工具链。
- setup bootstrap 接受 `uv 0.11.7` 后的合法平台/安装来源后缀，避免 Homebrew 等发行形式被误判；
  文档明确 macOS/Linux 的 shell 入口与 Windows PowerShell 入口。
- `analyze-requirement` 新增 work-only 来源处置闭包：完整来源中的决策相关陈述必须分类为
  `BUSINESS / DESIGN_INPUT / SCOPE_BOUNDARY / EXCLUDED`，由确定性 context、review 与 packet
  绑定；技术输入不会污染 BUSINESS 稳定 JSON，跨域边界必须映射全部受影响的 Epic/Feature。
  同时固定 Skill 资产按 `<skill-root>` 直接解析，避免无关目录搜索和 Git 探测；五个专业
  Owner 把确定性脚本作为公开命令黑盒执行，不再为预测 diagnostics 复读实现源码。
- 五个专业 Owner 新增确定性 Reviewer/批准绑定：fresh-context Reviewer 只返回 `PASS` 或 findings，
  `PASS` 后 Stage 调用 Owner-local `write-reviewer` 写 canonical reviewer sidecar；新 session 已提供
  Owner 与完整 packet SHA-256 时，依次调用 `write-approval` 与一次 `publish-approved`。两个写命令
  只校验固定路径和 hash 参数，发布命令仍是唯一总复核；Stage 不再手写 reviewer/approval JSON，
  也不再枚举/预读 artifact、运行 `--help`、closure、renderer 或额外 `check`。
- `analyze-as-is` 新增只读 `upstream-check` 输入门禁，在 candidate 尚不存在时先匹配 Requirement
  receipt；不再误用 `review` 产生 `CANDIDATE_UNREADABLE`，且门禁不写任何 As-Is artifact。
  同时修正仓库内 `DOCUMENT` Evidence 的 attestation：`<repoId>:<anchor>` 会按已登记
  repository snapshot path 解析和绑定，不再被误当成项目根目录下的字面文件名；Commitment
  与 `PRIOR_SOW` Evidence 统一强制使用 `prior-sow:<priorSowId>#<anchor>`，防止来源字段与逻辑
  anchor 指向不同往期 SOW。Skill 同时公开既有 `implementationStatus → treatment` 完整矩阵，
  Stage 无需读取脚本或先消耗一次机械失败才能正确编制承诺。
- `generate-design` 修正 As-Is handoff 的仓库 `DOCUMENT` Evidence 重建：下游按登记 repoId 解析
  `<repoId>:<anchor>`，与 As-Is receipt 的真实项目路径保持一致，不再把逻辑引用误当字面路径。
  Design 的第一条项目命令固定为 `prepare_context.py`，Stage 不再预先枚举 `.ai-sow` 或探测 Git，
  成功后只读取 manifest 点名的闭包和必要 source anchor；closure 为每条可读 Evidence 提供项目
  相对 `resolvedPath` 及 repository/prior SOW snapshot，模型无需猜测逻辑引用的磁盘位置；Skill
  同时公布两份 candidate Schema 的精确路径，避免探测插件目录或猜测不存在的 `schemas/`。Design
  closure 删除 fragment 间重复的 source document、normalized item 与 Evidence，真实 E2E 输入下
  fragment bytes 从 37,385 降为 29,457（-21.2%）。
- `generate-design` review renderer 新增 candidate 驱动的唯一 `Structure Counts` 声明，并拒绝
  review-source 自由文本重复手写 Design/TECHNICAL 对象数量；一次专业整体修正新增或删除对象后，
  评审计数会随 candidate 自动更新，不再因旧摘要计数漂移而消耗第二次 Reviewer 失败。
- `generate-story` 公开 candidate 合同的精确路径 `contracts/delivery.schema.json`，Stage 在 closure
  后直接读取一次，不再通过 `ls`、glob、`rg`、fixture 或 test 枚举猜测 Schema。
- `generate-story` 修正 As-Is handoff 的仓库 `DOCUMENT` Evidence 重建：逻辑
  `<repoId>:<anchor>` 现在按 `repositorySnapshots` 解析为 receipt 绑定的项目相对路径，与
  `generate-design` 的既有 handoff 语义保持一致。
- `generate-story` context closure 新增已选 Feature 相关的 Design Decision 投影，避免 Stage 为
  AC/Integration 猜测批准 ID；Skill 和评审模板同时明确每个非 `NONE` 集成边界 Story 都要有
  边界一致的顶级 Integration，不能只挂到共享使能 Story。
- `generate-story` 新增横切技术范围的非重复门禁：带 `relatedBusinessFeatureIds` 的 TECHNICAL Story
  只能交付独立共享适配器/控制边界，不得聚合两个或更多相关 BUSINESS Story 已登记的提供方 target，
  也不得再次声明这些业务调用的映射、幂等、重试、异常处置和核对；机械 review 以
  `INTEGRATION_SCOPE_OVERLAP` 在进入 Task 前阻塞可证明的重复计价。
- 将 candidate-first 生命周期推广到五个专业 Owner：各 Owner-local context closure 只投影本阶段
  所需引用，独立 Reviewer 使用 fresh context；候选、机械校验、风险摘要和 hash-bound review
  packet 全部前置到用户批准之前，批准后只执行精确 `publish-approved` 原字节发布。现有 receipt
  `0.3`、稳定路径、模板计算权威和 reconciliation Adapter 保持兼容。
- 五个 Owner 的 legacy `publish/rebind` 现在只允许 reconciliation 携带合法 `--staging-root` 调用；
  普通发布只走 packet-bound `publish-approved`，缺少 staging 的 legacy 写命令在任何写入前阻塞。
- 普通 Owner 的 `NO_CHANGE` 进入完整 packet-bound 授权路径：至少一项 receipt 输入必须变化，candidate
  必须与稳定输出原字节一致，批准后只更新正式 review 与 receipt；语义变化仍必须走 `CHANGED`。
- 收紧 `generate-task` 性能试点：review packet 绑定 context manifest 与五个证据 fragment，
  Delivery 无完备 Story→Effective Start 映射时保守保留全部 Effective Start；新增确定性 review
  renderer，从 candidate 与模板投影逐 Task 计数、包含、排除和非重复计价边界，避免修复后的
  review 漂移。
- `generate-task` 公开 candidate 合同的固定路径 `contracts/estimate.schema.json`，closure 后只读
  一次，不再通过目录枚举或 test 猜测 Schema。
- `generate-task` 修正 As-Is handoff 的仓库 `DOCUMENT` Evidence 重建：逻辑
  `<repoId>:<anchor>` 按 `repositorySnapshots` 解析为 receipt 绑定的项目相对路径，与 Design、
  Story 消费同一交接语义，不再因把逻辑引用当成文件名而阻塞 Task context closure。
- `generate-task` 公开接入复用 `workModeRationale` 的精确 canonical 公式，并明确只有 Effective Start
  点名当前基础单元的既有资产时才使用“调整”；质量验证门禁同步识别 As-Is 的“回归资产”和
  “恢复演练”原词，失败 diagnostics 直接返回期望的 canonical rationale，Stage 无需读取 validator
  源码或消耗额外 session 才能遵守工作模式合同。复用既有 CI/CD 执行本项目新切换仍明确归为
  “新建”发布切换；首次机械 review 只含 candidate 可修复项时允许一次整体修正，第二次失败才停止，
  且不占用后续 Reviewer 的一次专业修复额度。
- `generate-task` 普通 candidate 流程在 manifest 后用一个工具回合各读取五个 context fragment 一次，
  禁止随后再次筛选或复读；Schema 明确映射到
  `<plugin-root>/skills/generate-task/contracts/estimate.schema.json`，template catalog 成为唯一正常运行
  目录投影，不再重复运行 `read_template.py`、读取项目 XLSX 或 Skill-local fixture。由此减少大段模板/
  As-Is 内容在后续模型回合中的重复累计。
- `generate-task` 同时固定输出语言合同为 `<plugin-root>/references/output-language.md`，禁止误探测
  不存在的 `<plugin-root>/skills/references/` 路径。
- `generate-sow` 修正最终 receipt matcher 的仓库 `DOCUMENT` Evidence 重建：逻辑
  `<repoId>:<anchor>` 按 `repositorySnapshots` 解析为 receipt 绑定的项目相对路径，普通项目文档路径
  保持原值，不再在最终 XLSX 生成时把仓库逻辑 anchor 当成项目根目录文件名。
- 简化确定性阶段拓扑：`setup` 与普通 `generate-sow` 均由当前 Stage 直接调用一次现有 Module，
  不再为环境/Schema 复读或 receipt/工作簿/package 机械检查创建 Worker、Validator 或默认 Reviewer
  叶子 Agent；既有 fail-closed、模板权威、复读和内容寻址发布语义保持不变。
- 新增七阶段之外的 `ai-sow:reconcile` 维护 Skill：已有完整产物后的上游修正可在一个 session
  内完成固定影响后缀；全部 Owner candidate/projection、staged validation、SOW package、canonical
  redo/diff/risk 都在批准前由完整 packet 绑定，一个 Reviewer 与一次批准绑定同一 packet SHA-256，
  批准后只做确定性 check/publish 和可恢复批量发布。未新增稳定业务 JSON、DAG、通用 Owner runner
  或 revision store。
- `reconcile` 公开五个 Owner Adapter 的 stable/candidate/review/receipt 精确路径、统一
  `--staging-root` 命令和 `NO_CHANGE` before/current receipt 取值规则；禁止预读未创建 work 文件、
  复制 ProjectView 可回退读取的 base 成果，或在失败 receipt 已占用 staging 后原地试错。真实 E2E
  暴露的路径猜测、参数拼写和两级 rebind 声明返工由此转为一次性确定性调度。新增只读
  `reconcile.py --mode inspect` 一次输出固定后缀的 baseline hash、validation inputs 与 ID 声明，避免
  平台相关 hash 命令和完整 `NO_CHANGE` artifact 进入 Stage 上下文；新增 `--mode stage-owner`
  确定性投影 review 与 `NO_CHANGE` 原 output，消除手工复制造成的双层 `.ai-sow` 和 base review
  回退；新增 reconciliation-only `--mode prepare-no-change`，从 base/staged receipts 自动投影完整
  Stable ID/hash binding。Owner validator 仍由 Stage 直接调用，且每个 Adapter/Owner 动作必须作为
  独立 fail-fast tool call；命令统一使用插件 `.venv` Python 与绝对脚本路径，避免遗漏 ID、失败后
  继续物化、PATH uv、shell 临时变量展开错误和重复 cache path 拼写；Adapter/Owner 强制绝对
  project root，直接 Python 调用保持项目 cwd。
- `reconcile` 新增只读 `inspect-work` 与机械 `prepare-changed`：任何 staging 前先固定 CHANGED
  candidate hashes、冻结整体 review，再把精确 run/review hash 绑定到 Owner work review；禁止先
  发布 Owner 再补整体批准闭包。
- 修正 `reconcile --mode check` 的进度报告：`before == after` 的 `NO_CHANGE` 原字节复用路径现在
  也计入 `completedOperations`，完整发布后的幂等复查会准确报告 `completedOperations ==
  totalOperations`，不再把内部 changed-prefix 计数误报为未完成。
- 修正 `generate-task` 的 AC 追溯语义：Story/AC 在批准后保持只读，Task 与同 Story AC
  允许多对多映射；每条 AC 仍须至少有一个 Task 覆盖，但多个基础单元 Task 可共同满足同一
  业务验收条件。
- 固化 Task→Design 反馈边界：实现机制缺口优先细化既有 TECHNICAL Feature；未改变用户批准
  的交付结果时，`generate-story` 只做 packet-bound `NO_CHANGE` 发布，不得用新增技术 Feature 反向改写
  已批准的 Story/AC。
- 将五个 Owner handoff 统一为 validator contract `0.3` receipt；下游只匹配当前 input、批准
  review 和 stable output 字节，不再重放上游业务 validator 或 HLD/Go-live 门禁。
- `generate-sow` 现在生成内容寻址且逐字节确定的自包含包，包含六份稳定 JSON、五份批准
  review、五份 receipt 和权威模板；相同包复用，不同内容 fail closed。
- 将首个稳定发布合同面统一到 `0.1.0` / SOW `1.3`；内部原型未对外发布，
  因此不保留旧数据迁移器或多版兼容层。
- 将 v1.3 XLSX 示例升级为面向 PMO 与财务评审的仿真 Brownfield 项目，使用 6 个 Epic、
  18 个 Feature、23 个 Story、46 个原子 Task、4 个集成点和 6 条假设/风险，完整展示
  需求追溯、现状证据、范围决策、验收、工作模式、复杂度、SIT、UAT、风险与项目取整。
- 在 `90-系统现状` 中为 Feature 覆盖记录显示“Feature覆盖”主题标签，避免连续空白被误解为
  数据遗漏，同时保持跨主题覆盖关系和稳定数据合同不变。
