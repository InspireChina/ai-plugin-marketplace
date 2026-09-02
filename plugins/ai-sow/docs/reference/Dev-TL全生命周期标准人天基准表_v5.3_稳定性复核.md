# Dev / TL 全生命周期标准人天基准表 v5.3 稳定性复核

- 复核对象：[v5.3 稳定候选稿](Dev-TL全生命周期标准人天基准表_v5.3_讨论稿.md)
- 样本批次：C（公开一手工程案例留出集）
- 日期：2026-09-02
- 复核目标：使用未参与 v5.3 形成过程的真实工程背景，检查是否仍产生新增类型、改名、边界或 PD 调整建议

公开案例只用于确认真实交付对象和边界。公开披露的团队规模、系统规模或项目历时不用于反推单条 PD；
大型工程必须先拆成多个基础工作单元，再按各自模式和复杂度估算。

## 案例 C1：GitHub.com 将 MySQL 生产集群升级到 8.0

一手来源：[Upgrading GitHub.com to MySQL 8.0](https://github.blog/engineering/infrastructure/upgrading-github-com-to-mysql-8-0/)。
公开案例包含兼容验证、渐进升级、拓扑调整、回滚能力、监控和旧版本清理等真实边界。

| 可识别 Task 实例 | v5.3 类型 ID | 模式 | 复核判断 |
|---|---|---|---|
| 分析字符集、权限、复制和查询兼容影响 | AN-IMPACT | 新增 | 可准确映射。 |
| 验证反向复制和关键查询未知问题 | AN-SPIKE | 新增 | 可准确映射。 |
| 设计滚动升级、主从拓扑、检查点和回滚方案 | AN-DESIGN | 新增 | 可准确映射。 |
| 调整数据库集群资源栈和复制拓扑 | ENG-INFRA-STACK | 修改 | 数据库平台基础设施发生改变，不需要新增“数据库升级”类型。 |
| 调整集群升级和编排自动化 | ENG-PLATFORM | 修改 | 可准确映射。 |
| 处理查询和复制性能瓶颈 | CO-PERF-RELIABILITY | 修改 | 可准确映射。 |
| 完成版本、字符集和查询兼容验证 | TEST-COMPAT-A11Y | 新增 | 可准确映射。 |
| 完成流量、复制延迟和稳定性验证 | TEST-PERF | 新增 | 可准确映射。 |
| 编制渐进发布与回滚方案 | REL-PLAN | 新增 | 可准确映射。 |
| 执行分阶段切换和回滚演练 | REL-REHEARSAL | 新增 | 可准确映射。 |
| 退役旧 MySQL 5.7 实例 | OPS-RETIREMENT | 新增 | 可准确映射。 |

结果：无新增建议。数据库引擎只是技术对象；应用依赖升级用 ENG-STACK-UPGRADE，数据库平台升级用
ENG-INFRA-STACK 或 ENG-PLATFORM，取决于实际交付对象。

## 案例 C2：Slack 建立桌面端自动化无障碍测试

一手来源：[Automated Accessibility Testing at Slack](https://slack.engineering/automated-accessibility-testing-at-slack/)。
公开案例明确区分无障碍标准、组件或功能建设、自动化测试以及人工辅助技术验证。

| 可识别 Task 实例 | v5.3 类型 ID | 模式 | 复核判断 |
|---|---|---|---|
| 建立桌面应用无障碍基础模式和工程约束 | CO-ACCESSIBILITY | 新增 | 可准确映射。 |
| 调整共享组件的语义、焦点和键盘行为 | FE-COMPONENT | 修改 | 可准确映射。 |
| 建立可复用无障碍测试支撑工具 | TEST-TOOL | 新增 | 可准确映射。 |
| 建立桌面端无障碍自动化流程 | TEST-UI-E2E | 新增 | 可准确映射。 |
| 完成读屏、键盘及标准符合性验证 | TEST-COMPAT-A11Y | 新增 | 可准确映射。 |
| 将无障碍检查接入质量门禁 | ENG-BOOTSTRAP | 修改 | 既有工程规范和门禁发生改变。 |

结果：无新增建议。自动化无障碍检查不需要独立类型；它由测试工具、端到端自动化和兼容性与无障碍验证共同表达。

## 案例 C3：Stripe 的 API 版本和发布机制

一手来源：[APIs as infrastructure: future-proofing Stripe with versioning](https://stripe.com/blog/api-versioning)、
[Introducing Stripe’s new API release process](https://stripe.com/blog/introducing-stripes-new-api-release-process) 和
[API upgrades](https://docs.stripe.com/upgrades)。这些来源描述版本固定、兼容演进、SDK 关联、升级指导、Webhook 测试和回滚窗口。

| 可识别 Task 实例 | v5.3 类型 ID | 模式 | 复核判断 |
|---|---|---|---|
| 设计 API 兼容、版本固定和升级策略 | AN-DESIGN | 新增 | 可准确映射。 |
| 记录滚动版本而非大版本路径的技术决策 | AN-ADR | 新增 | 可准确映射。 |
| 调整共享 API 数据契约 | DATA-CONTRACT | 修改 | 多接口共同使用并独立版本化时计量。 |
| 调整查询或操作 API 行为 | FE-QUERY-API / FE-COMMAND-API | 修改 | 按实际业务事务分别成行。 |
| 建立账户或请求级版本配置 | CO-CONFIG | 新增 | 可准确映射。 |
| 适配合作伙伴或 Webhook 消费者 | IN-INTEGRATION | 适配 | 只有存在独立映射和验证工作时计量。 |
| 建立跨版本接口契约测试 | TEST-CONTRACT | 新增 | 可准确映射。 |
| 形成升级、回滚和发布说明 | REL-PLAN | 修改 | API 发布同样适用通用发布类型。 |
| 退役不再支持的旧版本能力 | OPS-RETIREMENT | 新增 | 可准确映射。 |

结果：无新增建议。“API 版本管理”是设计、契约、配置、接口修改、测试和发布的组合，不是新的基础交付物类型。

## 案例 C4：Shopify 为大促扩展数据平台吞吐和可靠性

一手来源：[How to Reliably Scale Your Data Platform for High Volumes](https://shopify.engineering/reliably-scale-data-platform)。
案例描述真实高峰流量下的数据处理、扩容、可靠性、可观测和验证目标。

| 可识别 Task 实例 | v5.3 类型 ID | 模式 | 复核判断 |
|---|---|---|---|
| 分析吞吐、延迟、积压和故障影响 | AN-IMPACT | 新增 | 可准确映射。 |
| 调整高吞吐数据加工流程 | DATA-TRANSFORM | 修改 | 可准确映射。 |
| 调整数据同步和消费能力 | DATA-SYNC | 修改 | 可准确映射。 |
| 实施容量、并发和故障隔离改进 | CO-PERF-RELIABILITY | 修改 | 可准确映射。 |
| 调整平台资源和共享处理能力 | ENG-PLATFORM | 修改 | 可准确映射。 |
| 建立积压、延迟和失败率告警 | ENG-ALERT | 修改 | 可准确映射。 |
| 完成高峰容量和长期稳定性验证 | TEST-PERF | 新增 | 可准确映射。 |
| 更新大促运行与恢复手册 | HAND-RUNBOOK | 修改 | 可准确映射。 |

结果：无新增建议。“大促保障”是业务背景，不是工作类型；数据加工、同步、可靠性工程、平台、告警和验证已覆盖独立结果。

## 案例 C5：GitHub 建设新一代代码搜索

一手来源：[The technology behind GitHub’s new code search](https://github.blog/engineering/the-technology-behind-githubs-new-code-search/)。
公开案例包含专用搜索引擎决策、大规模索引、增量更新、查询体验、性能和基础设施等边界。

| 可识别 Task 实例 | v5.3 类型 ID | 模式 | 复核判断 |
|---|---|---|---|
| 验证通用搜索方案能否满足代码搜索目标 | AN-POC | 新增 | 可准确映射。 |
| 记录建设专用搜索引擎的技术决策 | AN-ADR | 新增 | 可准确映射。 |
| 建立搜索结果和代码浏览页面 | FE-VIEW | 新增 | 可准确映射。 |
| 建立代码搜索查询 API | FE-QUERY-API | 新增 | 可准确映射。 |
| 建立仓库内容增量索引同步 | DATA-SYNC | 新增 | 可准确映射。 |
| 建立全量重建和增量索引任务 | FE-BATCH | 新增 | 可准确映射。 |
| 建立索引数据加工和去重 | DATA-TRANSFORM | 新增 | 可准确映射。 |
| 实施查询延迟、索引吞吐和存储优化 | CO-PERF-RELIABILITY | 新增 | 可准确映射。 |
| 建设搜索集群资源栈 | ENG-INFRA-STACK | 新增 | 可准确映射。 |
| 完成查询性能、容量和稳定性验证 | TEST-PERF | 新增 | 可准确映射。 |

结果：无新增建议。即使自研搜索引擎，仍可按页面、查询、同步、调度、加工、性能工程和资源栈拆分；
“搜索引擎”本身不是比这些交付对象更稳定的计价 Key。

## 案例 C6：Cloudflare 故障恢复、复盘与韧性改进

一手来源：[Cloudflare control plane and analytics outage post-mortem](https://blog.cloudflare.com/post-mortem-on-cloudflare-control-plane-and-analytics-outage/)
和 [Code Orange: Fail Small](https://blog.cloudflare.com/code-orange-fail-small-complete/)。公开案例包含灾备切换、服务恢复、
根因分析、故障范围收敛、安全配置、紧急操作能力、监控和流程改进。

| 可识别 Task 实例 | v5.3 类型 ID | 模式 | 复核判断 |
|---|---|---|---|
| 诊断故障并恢复控制面和分析服务 | OPS-INCIDENT-RECOVERY | 新增 | 可准确映射。 |
| 形成故障时间线、根因和改进结论 | OPS-RCA | 新增 | 可准确映射。 |
| 建立或调整灾备切换与恢复能力 | CO-BCDR | 修改 | 可准确映射。 |
| 建立故障域隔离和可靠性改进 | CO-PERF-RELIABILITY | 修改 | 可准确映射。 |
| 建立更安全的配置变更控制 | CO-SECURITY-PRIVACY | 修改 | 可准确映射。 |
| 调整共享授权和应急工程平台能力 | ENG-PLATFORM | 修改 | 可准确映射。 |
| 建立关键服务和恢复路径告警 | ENG-ALERT | 修改 | 可准确映射。 |
| 完成灾备切换和恢复验证 | TEST-DR | 修改 | 可准确映射。 |
| 完成配置与授权安全验证 | TEST-SECURITY | 修改 | 可准确映射。 |
| 更新应急操作与恢复手册 | HAND-RUNBOOK | 修改 | 可准确映射。 |

结果：无新增建议。事故响应、RCA、具体整改、灾备能力和正式验证保持分离，可以避免把一次事故重复计量多次。

## 留出集改进建议审核

| Finding | 候选建议 | 审核决定 | 理由 |
|---|---|---|---|
| C-F01 | 增加“数据库引擎升级” | **不吸收** | 应用依赖升级、基础设施资源栈和共享平台已按实际所有权覆盖；数据库名称不是交付类型。 |
| C-F02 | 增加“自动化无障碍测试” | **不吸收** | TEST-TOOL、TEST-UI-E2E 和 TEST-COMPAT-A11Y 已覆盖不同交付对象。 |
| C-F03 | 增加“API 版本管理” | **不吸收** | 版本策略由设计、数据契约、配置、接口、契约测试和发布组成。 |
| C-F04 | 增加“大促保障” | **不吸收** | 大促是业务背景；性能工程、数据处理、平台、告警和验证已经覆盖。 |
| C-F05 | 增加“搜索引擎建设” | **不吸收** | 搜索引擎是技术实现；可验收结果已能拆到现有类型。 |
| C-F06 | 增加“事故整改专项” | **不吸收** | 故障恢复、RCA 和各类具体整改必须分开，泛化专项会造成重复计量。 |
| C-F07 | 根据公开项目历时提高基础 PD | **不吸收** | 公开案例由大量实例组成，规模应通过拆行和复杂度表达，不能把项目历时写回单个基础单元。 |
| C-F08 | 调整 v5.3 名称、边界或参数 | **无建议** | 六个真实案例均可形成唯一主类型和明确的独立附加交付物，没有发现新的重叠或空档。 |

## 累计覆盖与稳定性证据

下表把 v5.0、v5.1、v5.2 和本批次案例合并检查。每个 v5.3 工作类型 ID 至少在一个正向拆分场景中出现；
相邻易混类型还在各轮复核中完成过排重判断。

| 分类 | 已覆盖的 v5.3 工作类型 ID |
|---|---|
| 分析与设计 | AN-IMPACT、AN-DESIGN、AN-ADR、AN-SPIKE、AN-POC |
| 功能与接口 | FE-VIEW、FE-EDIT、FE-FLOW、FE-DASHBOARD、FE-COMPONENT、FE-QUERY-API、FE-COMMAND-API、FE-FILE-TRANSFER、FE-MESSAGE-FLOW、FE-COMPENSATION、FE-BATCH、IN-INTEGRATION、IN-IDENTITY |
| 应用共性能力 | CO-I18N、CO-CONFIG、CO-ACCESSIBILITY、CO-PERF-RELIABILITY、CO-BCDR、CO-SECURITY-PRIVACY、CO-MULTITENANCY |
| 集成与数据 | DATA-IMPORT、DATA-EXPORT、DATA-SYNC、DATA-TRANSFORM、DATA-CONTRACT、DATA-LIFECYCLE、DATA-MIGRATION、DATA-RECON、DATA-REPAIR、DATA-REPORT、DATA-DOCUMENT、DATA-METRIC |
| 身份安全与治理 | GOV-FUNCTION-ACCESS、GOV-DATA-ACCESS、GOV-DATA-SECURITY、GOV-AUDIT |
| 测试与验证 | TEST-API、TEST-UI-E2E、TEST-CONTRACT、TEST-TOOL、TEST-PERF、TEST-DR、TEST-SECURITY、TEST-COMPAT-A11Y、TEST-INTEGRATION |
| 工程化 | ENG-BOOTSTRAP、ENG-STACK-UPGRADE、ENG-REFACTOR、ENG-PIPELINE、ENG-IAC、ENG-INFRA-STACK、ENG-PLATFORM、ENG-RUNTIME、ENG-OBSERVABILITY、ENG-ALERT |
| 发布与生产 | REL-PLAN、REL-REHEARSAL、REL-MIGRATION-DRYRUN、REL-EXECUTION、REL-MIGRATION-EXECUTION、REL-REVIEW、OPS-INCIDENT-RECOVERY、OPS-RCA、OPS-RETIREMENT |
| 技术交接 | HAND-RUNBOOK、HAND-KT |

重点排重边界均已通过案例验证：

- 文件传输与数据导入、数据输出、业务文档生成；
- 单接口 Schema 与共享数据模型或契约；
- 批量调度与独立数据加工；
- 消息业务流程与跨系统集成；
- 应用安全工程、数据安全处理与安全验证；
- 性能可靠性工程与性能验证；
- 灾备能力建设与灾备验证；
- IaC 模块、资源栈、共享平台与应用运行环境接入；
- 发布方案、演练、执行与发布后复盘；
- 故障恢复、RCA、具体整改与系统退役。

## 稳定性结论

| 检查项 | 结果 |
|---|---|
| v5.3 工作类型数量 | 71 |
| 稳定工作类型 ID 数量 | 71，且无重复 |
| 本批次新类型建议 | 0 |
| 本批次改名建议 | 0 |
| 本批次边界调整建议 | 0 |
| 本批次 PD 调整建议 | 0 |
| 公开真实案例可拆分性 | 6 / 6 均能按独立交付对象映射 |

v5.3 在当前 Dev / TL 适用范围内达到结构稳定：继续增加行业名词、协议、产品、数据库、框架、漏洞或实现机制，
不会提升基础单元的互斥性和可复用性。后续只有真实项目回放数据出现持续、同方向偏差时，才调整 PD；
这属于统计校准，不再属于目录完整性修订。
