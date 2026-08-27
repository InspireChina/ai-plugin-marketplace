# 变更日志

所有重要的用户可见变更都记录在此。

## 0.1.0 - 未发布

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
  文档明确 macOS/Linux 的 shell 入口、Windows PowerShell 入口及 Windows `Provisional` 证据边界。
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
