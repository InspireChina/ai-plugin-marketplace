# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的结构。当前版本尚未公开发布。

## 0.1.0-beta.2 - 未发布

- 新增 Owner 授权的 `CANDIDATE_PATCH-v1`：机械失败与新发生的 `REPAIRABLE_SEMANTIC` 只修改精确槽位，绑定 RepairReceipt、CandidateResolution、Review/base/semantic source 与协议选择事件；原失败和已发行旧 Repair 保持冻结。补丁组、hydrate、内容/执行次数和用量累计恢复，无进展、输入、合同、Owner、执行与预算分别停止。
- 派生结果不再冒充 Attempt；dependency、Prototype、checkpoint 与 portable proof 区分物理 record 和 CandidateResolution，并重放 base、对象索引、语义来源、事件和完整 Patch 链。确定性缓存绑定实际输入、参数、相关实现和无绝对路径 Office 身份；旧无指纹成功不在新路径复用。
- 修复 `CANDIDATE_PATCH-v1` 在真实阶段接续中的集成缺口：Task 共享资产、实施澄清、人工裁定、Reviewer 格式修复、未发行容量恢复和 portable proof 统一保留 CandidateResolution、旧 Attempt、上游 checkpoint 与精确 Review 绑定；最终工件复核同时恢复实际 workbook bytes 解码。
- 真实宿主 E2E 使用宿主当前模型、全新 Controller Session 和逐 `MODEL_PROVIDER` Action 的 `FRESH_NO_HISTORY` worker；新增 test-only 内容寻址隔离报告与 `verify-host-invocations`。基准结果切换为 `ai-sow-benchmark-result-v2`，将严格 Functional Acceptance、必记 Timing Observation 与 `COMPLETE / PARTIAL / UNAVAILABLE` Token Observation 分离；缺少 provider usage 不再阻断功能，实际 token 不换算费用。
- 修复 Schema-invalid 候选含附加属性、缺失对象身份、条件字段联动或旧 `decision/reason` 无关处置时 Repair 无法收敛及 Action 放大的问题：诊断展开到精确属性路径，Owner 以无值 `REMOVE_FIELD` 槽位只删除 Schema 明确拒绝的现存字段，只允许 `SET_FIELD` 补齐尚不存在的身份字段，并以 `SET_FIELDS` 在同一对象内原子选择 discriminator 的封闭字段分支；已表达 `NO_RELEVANT_FACT` 的旧字段按现存值约束为 `disposition/facts/noRelevantReason`，不要求模型编造事实。同一 SOURCE_SCAN 候选中没有替代选择、字段 footprint 不重叠的 issues 合并为一个原子 Patch，同对象不同字段也可安全合并；已有身份仍不可改写，集合或实际重叠写入仍分开。Patch receipt 统一绑定规范化 Patch并可从模型原始非 canonical JSON 重放；预算等待恢复按同一 Owner lineage 的最新 `repairRound` 叶节点处理，不再受 Action ID 排序影响，也不会为等待前已发行的旧 Patch 写入伪 `WAITING_INPUT_EXITED`。Patch instruction 明确顶层只能包含四个 Schema 字段，删除“说明具体原因”与封闭 Schema 的矛盾，不再诱导模型添加 `contract` 或 `diagnostics`。旧失败 raw 仍保留，新运行使用更新后的 Patch 合同 hash。
- 收紧 SOW 阶段 Integration 粒度：稳定模型只保留参与系统与方向、高层 `method`、`purpose` 和责任边界，移除具体 `trigger` 与 `dataCategories`；Scope facet 改为 `DIRECTION / METHOD / PURPOSE`。具体触发时机、endpoint、payload、字段映射、token/claim、重试和错误处理延后到迭代开始时确认，不再形成 Scope 输入门禁；ScopeDecisionIR 同时移除可把正常 fresh Review 误报为输入缺口的自由文本 uncertainty。

- 修复 Action 容量门禁按全局 hydrate reserve 过量预留的问题：发放与独立校验使用该 Action 冻结的读取上限；原容量、总预算、输入与失败记录不变，未发行修复可从原等待处接续。

- 机械候选/执行次数耗尽改为保留进度的预算等待；候选、执行及确定性步骤三个可选次数限额默认 2，可显式增加至不超过 10，沿原逻辑工作接续。Scope/Story/Task、Prior、原型保留定位并保护无关对象；首版 Schema 不完整也保留有效对象，工件失败保存下一步并复用成功字节，非法中间输出不能清空保护基线；旧记录和冻结预算不回写。

- 修正 Task 来源权威门禁误拒绝 PRD 支持的 SIT/UAT 界面自动化：仅对无设计引用、逐 Story/AC/政策证据闭合的 `TEST-UI-E2E` 允许表达；保留后台、数据、集成、认证、部署及估算门禁，旧失败记录不追认。

- 新 Task/Repair v2 将完整规则读取上限提高到 65536，允许同 run 显式单调追加 hydrate reserve；旧 Action/retry、冻结计划、Repair 和离线证明保留原版本与额度。Task 身份碰撞在成功封存前返回精确 INVALID_IR，不改变身份算法或计量依据。
- 新计划以 `PRIOR_ANALYZE-v3` 固定已有无损表传输用于初始与修复请求，复用 v2 专业 prompt/schema/限额；旧 v1/v2 请求原字节保持，现有支持布局的旧计划按冻结合同重放分组、物化与证明，不新增业务 IR 或历史布局迁移。

- Scope 从真实有效 Analyze 结果补齐每个对象选中观察的原型来源，并让候选、稳定身份和独立评审索引使用同一证据集合；保留来源权威、排除门禁及原来完整枚举来源的合法输入兼容性。
- 保持既有 Scope Review v1 合同可复读；Prior v2 的新增提取核验随本轮评审义务绑定，不使已验证 Greenfield 候选失效。
- 大型 Prior 的完整位置索引单独计作上下文，行分组保留原目标；完整模型请求仍受原预算守卫，避免索引挤掉正常证据行。

- 修正非固定格式往期 XLSX 解析：Prior Analyze v2 区分项目交付与目录/示例/汇总，补齐按行覆盖说明、同来源跨 Sheet hydrate、全局限定和必要单元格身份；Scope Review 可读取被排除行原文。Consolidate v2 只返回新增关系，程序确定性保留全部成功依赖，并纳入原有 Attempt/raw 回放。v1 IR 保留原合同，旧 run 不自动迁移；未新增布局阶段、稳定分类模型或终态恢复。

- 修复 RENDER 完成事件与输出发布之间中断后的恢复：先持久保存真实 Office PDF，再记录成功事件；恢复复用事件绑定原字节并校验篡改，避免字体替代引起的重复导出漂移。已验证 renderer、工作簿和预览保持不变。

- 修复 XLSX 数组公式被转为含内存地址的 Python 对象字符串而导致证据块 ID 漂移的问题；按原公式文本读取，缺少公式或无原公式文本的数据表公式明确失败，不执行公式。已冻结的 revision 原字节保留，新 Prepare 得到确定性证据。

- 收紧连续 Task Repair 的本轮 AC 授权：在公开提交、物化与 proof 回放中拒绝借用历史无关 roots 的覆盖，保留已批准的共享资产结果。

- 修复 ABANDON 决定落盘后中断恢复继续读取已移除 active marker 的问题；工件取证从最终 Task checkpoint 和预览修复授权链恢复候选绑定，离线读取不再要求可变当前候选。
- Prior 行分区支持同 packet、同 source/Sheet 的授权实体引用；Attempt repair 提供 canonical packet hash 不变的无损表传输，尚未发行的 retry 可在原容量内恢复，保留原失败和全部消耗。宿主中断采用独立调用证据和有限等待，未知用量与本地估算分开披露。

- Task 独立评审补齐候选实际选中类型的完整冻结模板规则，并校验模板与行 hash；明确工程资产和正式执行的边界、逐 Task 的 AC/来源支持及跨类型重叠检查，保持原有修复次数和 PASS 门禁。

- 共享上线政策按实例保留完整跨功能覆盖，不再按 Feature 复制计价义务；Task 技术依据仅扩展到该政策明确覆盖的目标，保留独立应用/环境的来源边界。SIT/UAT 仍逐功能独立交付，Author/Review 明确自动化代码与普通联调、人工支持的区别。

- Story 校验恢复生命周期政策的独立边界，拒绝业务与政策、不同政策之间的错误合并；保留同 Feature 共享架构约束的合法合并，并在 Author 提示中明确边界与限定词检查。

- Story 义务按单个 Feature 展开时同步收敛边界 key，避免共享设计的原多 Feature 适用范围阻止其并入业务 Story；明确独立限定和跨 Feature 隔离仍有效。

- Task 增加仅由 Story 明确引用的批准技术设计形成的实现目标，使业务事务承接共享架构约束，避免为设计覆盖而按 Story 重复计量同一运行环境；UI、跨 Feature 来源隔离和独立语义评审保持有效。

- Task 政策目标按 Story 保留所属 Feature 的批准技术依据，拒绝跨 Feature 借用或 Demo 升格；Integration 责任 Story 优先匹配其上游事实和来源，避免仅按 ID 选中无关部署 Story。

- 预算恢复允许同模型/估算器下单调提高未来请求的上下文容量，保留原 Envelope、计划、输入、输出和 Attempt；修复大失败输出导致未发行 retry 在旧容量下阻止预算替换的问题。

- Story/AC 与 Task 统一遵循来源粒度：至少一条 AC 完整关闭全部义务，不再强制凑两条；保持来源身份冲突、限定词和覆盖闭包检查。客户/第三方提供物的扫描分类与 Scope 评审明确项目门禁边界。
- Markdown 编号条目使用独立证据块并保留续行，避免同一列表中的正式范围、客户责任和排除项共用 anchor；InputRevision parser 升至 v2。
- 配对验收准备支持已冻结旧请求的 `currentStateDelta`/来源 `status` 形态，按原始文件 hash 与路径无业务漂移迁移到 v3。
- Scope 将 `ASSUMPTION` 保留为项目级前提，不自动派生供应商 Story/Task；补清政策 ID、来源证据 ID 和交付阶段关系的边界，避免无效引用与生命周期冲突。
- 真实多次运行的配对复核读取内容寻址的放弃、人工复核、合同不支持和系统失败终态，保留失败记录，并校验终态正文 hash、Schema 与输入绑定。
- 窄 IR 的绑定错误可保留结构化诊断；Scope 引用/关系错误将具体 code、JSON path 和 root 带入原有 bounded retry；Task 预检定位到具体 Task/Story，并合并同一 Story 的重复覆盖诊断。
- 同步 v3 request/Action、28 份业务 Schema、renderer-v12 和独立安装合同；内部 checkpoint 自动封存，实际配对仅共同审阅两份 Excel 后取得一个 PairDecision。
- 移除旧 benchmark 执行协议，只保留明确标为已取代的历史比较分析。复制 smoke 使用逐 Action 新进程 fixture，明确区分进程隔离与真实 provider 认证。
- 真实模型、浏览器、B.a–B.p 及最终双工作簿验收尚未完成，不声明基准或性能改善。

## 0.1.0-beta.1 - 已取代的开发记录

### 确定性编译切换（未发布）

- `generation-renderer-v9` 接通最终 XLSX、Office 非敏感 identity、双复读与完整 ZIP/公式错误扫描；汇总 Sheet 的实体 ID/SourceRef 经只读 Prior adapter 往返。
- 每个 workbook 仅一个 ARTIFACT_VISUAL_REVIEW，实际 Office PDF renders 覆盖全部可见 Sheet；完整深层 ArtifactManifest 与 immutable workbook 校验后才请求批准。generation 携带完整离线证明。
- renderer、Office、reference Office、reopen、render 与最终验证分别记录实际 active-time 区间；超额后停止下游步骤，预算增加后不重复完整成功输出。

- 删除剩余跨 run 路由、proof/DTO、REUSE/RENDER_ONLY/DELTA_COMPILE 与默认自动化排除入口。每次新 run 仅依赖本次明确输入，Brownfield 现状声明进入冻结 Scope context。
- 补充业务材料使用 abandon/start；预算替换必须严格增加允许限额，正文相同也拒绝。APPROVE 精确发布重放和 ABANDON 终态恢复保留。

- 三个 Owner 使用完整冻结 StagePlan、真实 Attempt pre-seal 校验、分别计时的物化与完整验证，以及条件输入确定后才发行的 fresh Review/Repair；PASS 自动推进。
- StageCheckpoint 绑定实际 plan、所有 Attempt、候选 revisions、validator、Review/PASS、上游与可选 Prior snapshot；恢复不重复转换，status 只读验证。
- 移除旧动态分组、通用 PATCH、分层 Theme Join/Adjudication 编译路径。新 run 不复用旧 generation 业务内容。hydrate 使用本轮原文/冻结 Task 规则与唯一完整请求计量。
- 模板字节未改变；renderer 的上述 v9 输出语义取代旧 v8。下方旧 R1/层级评审与增量路线条目为已取代的开发历史；完整输出、Office/浏览器和发布验证仍在最终集成验收执行。

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

- 生成后定向 Repair：Scope、Story/AC、Task 支持授权对象调整、合并、拆分并保留正确结果；Task 共享验收覆盖及当前责任承诺起点带完整证明。Repair 请求无损字典化，可在同一预算内恢复未发行工作。renderer v10 展示共享覆盖和计量归属，保留原模板全部计价公式。

- Task 输入澄清可通过 `resume --decision` 绑定真实 INPUT_REQUIRED、既有目标与 USER/SIMULATED_USER 决定，追加一次定向修复；累计链、原 Review、完整校验和 fresh Review 保留，拒绝新增未批准目标。

- 生成后局部修复：支持 Scope、Story/AC、Task 的受控合并/拆分及逐字段保留；新增原终态绑定的人工裁定继续与累计离线证明，不清零自动次数。
- renderer v11：不同工作类型共享技术目标名称时，以模板工作类型名称区分显示；同类型重名仍拒绝，原计价公式和已 PASS 业务模型不变。

- renderer v12：Office 向量预览按原比例、完整重叠窗口分页；新增预览失败后的 RENDER 后缀修复，复用已验证 Excel/Office 前缀，保留旧工件与失败视觉证明。

- 往期 Excel 大 Sheet 改为完整证据行分区，去除重复单元格正文并保留全部来源绑定；首组发行前的容量等待可从原 run 恢复，完整验证已有 Prototype 与预算。
