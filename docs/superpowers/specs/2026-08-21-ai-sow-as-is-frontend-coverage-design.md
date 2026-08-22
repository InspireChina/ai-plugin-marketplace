# AI SOW As-Is 前端覆盖设计

状态：方案已确认，等待文档复核

日期：2026-08-21

目标插件版本：0.1.0-beta.1

目标 SOW 标准版本：v1.3

## 1. 背景与结论

现有 As-Is 固定评估九个 Topic，但前端只能隐含在 `APPLICATION`、`OPERATIONS_QUALITY` 等通用结论中。当前合同没有要求显式判断前端是否适用，也不能稳定表达已有界面、交互状态组和通用界面组件。只分析服务端代码仍可能得到一份形式完整的 As-Is，导致目标设计和 Task 估算无法可靠判断前端工作是新建、调整还是接入复用。

本设计在 0.1.0-beta.1 中一次性增加前端现状模型、代码优先的调查规则、证据门槛、Effective Start 表达和下游消费约束。它不新增第十个 Topic，也不把问卷作为前端调查的默认步骤。

前端调查遵循以下顺序：

1. 源码、配置、测试和仓库文档；
2. CI/CD、IaC、部署配置、制品和运行手册；
3. 静态证据不足且问题会实质影响设计时，执行范围收窄的构建、测试或探针；
4. 部署记录、监控、仪表板和其他外部运行证据；
5. 以上仍不能回答的重要问题，才进入定向问卷。

如果直接证据已经完整，前端 As-Is 可以在不生成任何问卷的情况下完成。

## 2. 与其他 0.1.0-beta.1 方案的关系

本设计与以下方案同属一次 0.1.0-beta.1 / SOW v1.3 合同升级：

- [AI SOW v1.3 领域模型、Skill 与工作簿设计](../../architecture/ai-sow-v1.3-contract-design.md)定义总体领域层级、Skill 所有权和发布策略；
- [AI SOW Task 估算模型设计](2026-08-21-ai-sow-task-estimation-model-design.md)定义 Task、任务族、基础单元、工作模式和复杂度。

本设计只拥有 As-Is 前端覆盖及其下游消费接口，不重新定义 Task 模型。Task 继续通过 `matchedEffectiveStartItemIds` 使用现状基线；本设计不向 Task 增加 `architectureDeltaIds`、前端专用字段或新的工作模式。

本设计发生于首次公开预发布之前，因此不为内部原型提供旧格式兼容、自动迁移或新旧合同并行读取。

## 3. 目标

1. 每次 As-Is 都明确判断前端现状是已评估、不适用还是证据不足。
2. 当前界面、交互状态组和通用界面组件能够进入稳定 As-Is 与 Effective Start。
3. 前端代码存在时，不能只靠服务端证据完成 `APPLICATION` 评估。
4. 代码可以证明的事实直接从代码、配置和测试编译，不再重复向用户提问。
5. 代码存在、运行验证通过和生产部署分别使用不同 Evidence，不相互替代。
6. 前端调整或接入复用 Task 能追溯到准确的前端 Effective Start。
7. 最终工作簿能够展示前端现状、证据、未决问题和有效起点。

## 4. 本次不处理的事项

- 不把 `FRONTEND` 增加为第十个 As-Is Topic。
- 不要求启动目标应用、浏览器、数据库或容器完成常规调查。
- 不用问卷重新确认代码已经可以证明的页面、路由、状态或组件事实。
- 不把 Figma、截图或设计稿当作当前代码已经实现的证明。
- 不在稳定数据中保存源码、完整工具输出、截图二进制、凭据或生产数据。
- 不修改 Task 的任务族、基础单元、复杂度标准或计算公式。
- 不要求每个 Feature 都包含前端工作。

## 5. 领域术语

### 5.1 Client Assessment

`Client Assessment` 是一次 As-Is 对当前人机交互前端现状的总判断。每次分析恰好有一条，状态沿用：

- `ASSESSED`：直接证据足以形成可供设计使用的结论；结论可以是“存在当前前端基线”，也可以是“已确认当前没有前端基线”。
- `NOT_APPLICABLE`：证据证明范围内没有人机交互前端，也没有需要评估的现有客户端资产。
- `INSUFFICIENT_EVIDENCE`：完成直接调查和针对性提问后，仍有会改变设计或估算的重要缺口。

`NOT_APPLICABLE` 不是“没有找到前端代码”的同义词。它必须有可核验的排除证据。

### 5.2 Client Surface

`Client Surface` 是当前存在的人机交互载体，例如 Web 应用、移动应用、桌面应用或嵌入式界面。它用于聚合入口、当前界面、通用界面组件、代码仓库和有效起点，不等同于单个页面。

允许的 `kind`：

- `WEB`
- `MOBILE`
- `DESKTOP`
- `EMBEDDED`

### 5.3 INTERFACE

`INTERFACE` 是 As-Is Item 或 Effective Start Item 的一种类型，表示一个具有明确用户目标和主要状态集合的界面与交互实例。它可以是页面、视图、流程步骤或不以 URL 表达的交互状态组。

加载、空白、错误、权限、条件联动等状态属于同一交互实例的行为，不应机械拆成多个 Item。具有不同用户目标、独立交付边界或独立计数口径的界面应拆分。

### 5.4 UI_COMPONENT

`UI_COMPONENT` 是 As-Is Item 或 Effective Start Item 的一种类型，表示可跨界面复用的通用界面组件或组件集合，例如设计系统控件、组合组件或共享交互模块。只服务一个具体界面的局部实现不单独编译为 `UI_COMPONENT`。

### 5.5 前端 Task

“前端”继续是 Task 估算模型中的任务族：

- `INTERFACE` 对应“界面与交互”基础单元；
- `UI_COMPONENT` 对应“通用界面组件”基础单元。

领域对象与估算基础单元保持对应，但由各自 Owner Skill 分别负责。

## 6. 输入登记与调查范围

按照 0.1.0-beta.1 总体设计，setup 不接收 mode、Repo 或往期 SOW。`analyze-as-is` 在调查开始时登记代码库、往期 SOW、配置、部署材料和其他现状证据。

每个已登记 Repo 在 As-Is 调查台账中保存一个或多个角色：

- `CLIENT_APP`
- `CLIENT_LIBRARY`
- `SERVER`
- `DATA`
- `PLATFORM`
- `AUTOMATION`
- `SHARED`

Repo 角色由仓库结构、清单文件、构建配置和负责人提供的可核验证据确定。单仓可以同时具有多个角色。

角色只表示调查范围，不表示 Task 任务族。`CLIENT_APP` 表示仓库包含可运行的人机交互应用；`CLIENT_LIBRARY` 表示仓库包含共享前端资产但不一定独立运行。

缺少代码库是合法情况。此时仍需调查现有外部系统、部署材料、运行手册、业务流程和可访问的运行证据，并明确 Client Assessment。

## 7. 代码优先的前端调查

### 7.1 静态调查

对每个 `CLIENT_APP` 或 `CLIENT_LIBRARY` Repo，先按 As-Is CodeGraph 策略完成探测，再调查以下内容：

- 应用入口、路由、页面、视图和导航；
- 组件层次、设计系统、主题和共享组件；
- 状态管理、表单校验、加载、空白、错误和权限状态；
- API、BFF、事件、第三方 SDK、认证和会话处理；
- 浏览器存储、缓存、离线行为和敏感信息处理；
- 响应式断点、设备适配、国际化和无障碍实现；
- 构建工具、bundle、依赖、feature flag 和环境配置；
- 单元、组件、E2E、视觉回归、兼容性和无障碍测试；
- 客户端日志、错误采集、RUM、Web Vitals 和埋点；
- CI/CD、制品、静态托管、CDN 和发布配置。

CodeGraph 不能可靠解释 generated route、framework dispatch、动态 import、模板编译、CSS 构建或运行时配置时，使用范围收窄的直接源码、配置和语言工具佐证。未佐证的推断形成 Uncertainty，不能直接编译为当前事实。

### 7.2 运行验证

AI SOW 默认进行静态调查。只有同时满足以下条件时才执行前端构建、测试或探针：

1. 静态证据不足；
2. 缺口会实质改变设计、复用判断或估算；
3. 仓库已有的范围收窄命令能够回答该问题；
4. 已完成仓库原生前置条件检查。

本地 build 成功只证明该 revision 在指定前置条件下可以构建。组件测试或 E2E 测试成功只证明被覆盖的行为。两者都不证明某版本已部署到生产。

### 7.3 Evidence 含义

- `CODE`：证明实现、配置引用或静态结构存在。
- `CONFIGURATION`：证明构建、环境、路由、开关或客户端配置的当前仓库定义。
- `CONTRACT`：证明 API、事件、组件属性或外部交互契约。
- `RUNTIME`：证明指定 build、test 或探针实际执行及其结果。
- `DEPLOYMENT`：证明指定版本或制品部署到指定环境。
- `DOCUMENT`：证明规范、运行手册、支持矩阵或其他受控文档事实。
- `QUESTIONNAIRE`：证明负责人确认且带证据引用和生效日期的仓库外事实。

同一结论需要跨越代码、部署或运行边界时，使用多条 Evidence。不能用 `CODE` 推断 live deployment，也不能用部署记录推断未被部署证据覆盖的页面行为。

## 8. 九个 Topic 的前端调查视角

| Topic | 代码与直接证据优先调查 | 只有直接证据不足时才询问 |
|---|---|---|
| `SYSTEM_CONTEXT` | 应用入口、路由、角色判断、外部跳转和仓库归属 | 实际用户群、业务负责人、外部人工流程和组织责任 |
| `CAPABILITY` | 可达用户旅程、状态转换、权限分支和自动化场景 | 未编码的人工步骤、当前实际使用方式和业务例外 |
| `APPLICATION` | 框架、渲染方式、页面、组件、状态管理和生命周期标记 | 代码是否已停用、未登记客户端、正式退役计划 |
| `INTEGRATION` | API/BFF、认证、SDK、埋点、feature flag 和失败处理 | 外部 SLA、生产 endpoint、未入库凭据责任和供应商限制 |
| `DATA` | 客户端存储、缓存、离线数据、字段使用和清理逻辑 | 数据驻留、保留政策、同意规则和生产数据量 |
| `PLATFORM` | 静态托管、容器、CDN、环境配置、IaC 和发布清单 | 实际环境拓扑、域名、流量路由、账户和区域 |
| `SECURITY_COMPLIANCE` | CSP、XSS/CSRF 防护、Cookie、Token、依赖扫描和安全测试 | 合规义务、正式例外、访问评审和控制负责人 |
| `OPERATIONS_QUALITY` | 客户端 telemetry、测试、性能预算和错误采集实现 | 生产 Web Vitals、错误率、SLO、支持矩阵和审计结果 |
| `DELIVERY_CONSTRAINTS` | 构建流水线、质量门禁、制品、发布脚本和回滚配置 | 发布窗口、审批责任、支持时间和跨团队依赖 |

每个 Topic 的前端结论进入原 Topic assessment，不建立平行的九项前端 Topic。

## 9. 问卷触发规则

前端问卷不是固定产物。只有完成代码、配置、测试、部署材料和必要运行验证后，仍存在影响设计或估算的证据缺口时，才生成 `.ai-sow/work/analyze-as-is/questionnaire.md`。

每次只选择能够关闭具体缺口的问题，不发送完整前端问题目录。问题至少保留：

```text
Question ID:
Answer: <已知值 | UNKNOWN | NOT_APPLICABLE>
Owner:
Evidence reference:
Effective date:
```

以下内容通常适合定向提问：

- 哪个 revision 或制品实际部署在哪个环境；
- 某代码路径是否仍有生产流量或已成为死代码；
- 浏览器、设备和辅助技术的正式支持政策；
- 生产 Web Vitals、错误率、容量和 SLO；
- 无障碍、隐私、安全和监管义务；
- 发布、回滚、值班和组件所有权；
- 未入库的 CDN、域名、租户、代理或第三方平台配置。

已确认回答只有在 Owner、Evidence reference 和 Effective date 完整且不存在冲突证据时，才编译为 `QUESTIONNAIRE` Evidence。空白、`UNKNOWN`、未回答或冲突回答只形成 Uncertainty。

如果没有选中问题，不创建问卷文件；评审第 7 节明确写明“直接证据调查后无剩余问卷记录”。

## 10. 稳定 As-Is 合同

### 10.1 顶层集合

0.1.0-beta.1 的 `asis.json` 在总体 As-Is 合同中增加：

```text
clientAssessment
clientSurfaces
```

其他 As-Is 集合继续保存 Topic、Item、Commitment、Effective Start、Feature Coverage、Uncertainty 和 Evidence。

`analysisScope.repositorySnapshots` 的每条 Repo snapshot 增加必填 `roles`，使用第 6 节定义的 Repo role。稳定数据只保存 `repoId`、revision 和 role，不保存绝对路径、远程地址或凭据。

### 10.2 clientAssessment

```json
{
  "status": "ASSESSED",
  "summary": "当前 Web 客户端代码、入口和可复用界面基线已完成评估。",
  "evidenceIds": ["evidence-client-entry"],
  "uncertaintyIds": []
}
```

规则：

- `ASSESSED` 和 `NOT_APPLICABLE` 至少引用一条 Evidence；
- `INSUFFICIENT_EVIDENCE` 至少引用一项 Uncertainty；
- `NOT_APPLICABLE` 时 `clientSurfaces` 必须为空；
- 存在 `CLIENT_APP` 或 `CLIENT_LIBRARY` Repo 时不得使用 `NOT_APPLICABLE`；
- `ASSESSED` 允许 `clientSurfaces` 为空，但必须由证据证明当前确实没有现成客户端基线。

### 10.3 clientSurfaces

```json
{
  "clientSurfaceId": "client-surface-customer-web",
  "kind": "WEB",
  "name": "客户门户 Web 客户端",
  "summary": "提供客户档案查看和维护入口。",
  "lifecycleStatus": "ACTIVE",
  "entryPoints": ["/customers"],
  "repositoryIds": ["customer-web"],
  "currentItemIds": ["asis-interface-customer-profile"],
  "effectiveStartItemIds": ["effective-start-interface-customer-profile"],
  "uncertaintyIds": []
}
```

`lifecycleStatus` 允许：

- `ACTIVE`
- `INACTIVE`
- `DEPRECATED`
- `UNVERIFIED`

`UNVERIFIED` 表示代码或文档能够证明该 Surface 存在，但缺乏足够证据判断当前运行状态。它必须在 `uncertaintyIds` 中关联相关 Uncertainty，不能被描述为已部署或活跃。

每个 Client Surface 至少有一条 Evidence 直接支持其 ID。`ACTIVE` Surface 至少有一个入口和一个当前 Item，并且必须有 `DEPLOYMENT` Evidence 证明当前部署；`CODE`、`CONFIGURATION`、本地 `RUNTIME` 或问卷陈述不能单独证明活跃状态。外部系统没有本地 Repo 时，`repositoryIds` 可以为空，但仍需要文档、部署或问卷 Evidence。

### 10.4 Item 和 Effective Start

As-Is Item 与 Effective Start Item 的 `itemType` 增加：

- `INTERFACE`
- `UI_COMPONENT`

`INTERFACE` 必须引用一个 `clientSurfaceId`，名称和摘要应说明用户目标、主要状态、角色或关键交互特点。`UI_COMPONENT` 可以关联一个或多个 Client Surface；跨应用共享但尚未确认消费者时允许为空，并以 Repo 和 Evidence 证明其当前存在。

代码存在但部署状态未知时，可以创建有 `CODE` Evidence 支持的当前 Item，但不能把它描述为生产活跃。它是否进入 Effective Start，取决于该代码资产能否在工作开始时作为可用基线，而不是取决于是否已上线。

### 10.5 Topic Evidence

每条 Topic assessment 增加 `evidenceIds`。规则如下：

- `ASSESSED` 和 `NOT_APPLICABLE` 至少引用一条能够支持其结论的 Evidence；
- `INSUFFICIENT_EVIDENCE` 至少引用一项 Uncertainty，并可引用已经确认的部分 Evidence；
- 不能只用非空 summary 通过 Topic 校验。

### 10.6 Feature Coverage

0.1.0-beta.1 的 Feature Coverage 增加 `clientSurfaceIds`，表示与该 BUSINESS Feature 相关的当前交互载体。它不表示 Feature 已经实现；实现程度仍由 Effective Start、Commitment、Uncertainty 和 Coverage status 共同判断。

现有 Client Surface 但没有相关界面能力时，Feature 仍可以是 `MISSING`；此时 `clientSurfaceIds` 表示可复用载体，`effectiveStartItemIds` 为空。若现有应用壳、导航或共享组件能够构成有效基线，应将其编译为对应 Effective Start，并把 Coverage 设为 `PARTIAL`。

## 11. 语义校验

校验器至少执行以下规则：

1. `clientAssessment` 必须存在且符合状态条件。
2. 每个 `CLIENT_APP` Repo 必须被至少一个 Client Surface 引用。
3. 每个 `CLIENT_LIBRARY` Repo 必须被至少一个 `UI_COMPONENT` Item 或 Client Surface 引用。
4. 每个已登记 Repo 必须具有与其调查结论相关的直接 Evidence，不能只有 revision snapshot。
5. 每个 Client Surface ID、Repo ID、Item ID、Effective Start ID、Evidence ID 和 Uncertainty ID 必须存在。
6. 每个 `INTERFACE` Item 必须属于一个 Client Surface。
7. 每个 `INTERFACE` 或 `UI_COMPONENT` 当前 Item 必须有直接 Evidence。
8. Client Surface 的 Effective Start 必须引用 `INTERFACE`、`UI_COMPONENT` 或明确属于该 Surface 的其他有效基线 Item。
9. `ACTIVE` Surface 必须有 `DEPLOYMENT` Evidence；代码、配置、本地运行检查或问卷不能单独证明当前部署。
10. `NOT_APPLICABLE` Client Assessment 必须有排除 Evidence，且不能存在 Client Surface 或 Client Repo role。
11. `INSUFFICIENT_EVIDENCE` Client Assessment 必须关联 Uncertainty。
12. 每条 Feature Coverage 引用的 Client Surface 必须存在。
13. Topic assessment 的 Evidence 和 Uncertainty 引用必须存在并符合状态条件。
14. 未回答或 `UNKNOWN` 问卷记录不得成为 `QUESTIONNAIRE` Evidence。

校验器验证稳定数据和已登记输入，不通过关键词扫描业务自由文本来猜测是否存在前端。

## 12. 评审投影

As-Is 评审继续保持总体设计规定的八个章节，不新增独立章节：

1. 在调查范围中列出 Repo role、Client Repo revision 和排除范围。
2. 在整体现状摘要中给出 Client Assessment。
3. 在九个 Topic 中分别呈现适用的前端结论和 Evidence。
4. 在往期承诺中核对界面、组件、设计系统和前端质量承诺。
5. 在 Effective Start 中单独列出 `INTERFACE` 和 `UI_COMPONENT`。
6. 在 Feature Coverage 中列出 `clientSurfaceIds` 和前端有效起点。
7. 只在存在剩余缺口时列出问卷记录；否则明确无问卷。
8. 在 Evidence 索引中区分代码、运行和部署证明。

评审必须能够回答：

- 当前有哪些 Client Surface；
- 每个 Surface 有哪些现成界面和通用组件；
- 哪些内容能进入 Effective Start；
- 哪些结论只证明代码存在，哪些证明实际运行或部署；
- 哪些前端事实仍会改变设计或估算。

## 13. 下游消费接口

### 13.1 generate-design

`generate-design` 必须读取 Client Assessment、Client Surface、Feature Coverage 以及 `INTERFACE/UI_COMPONENT` Effective Start。目标设计相对于这些基线形成 Architecture Delta，不能把代码存在、生产部署和预期开始前可用混为同一状态。

目标 Design Item 应能表达界面与交互或通用界面组件，并通过 Architecture Delta 的 `effectiveStartItemIds` 追溯当前基线。新建前端允许没有 Effective Start；调整、采用、替换或退役必须引用相关现状。

### 13.2 generate-story

`generate-story` 根据批准的目标设计形成 Story 和 Acceptance Criteria。UI 相关验收结果应覆盖适用的正常、加载、空白、错误、权限、响应式、兼容性和无障碍行为，但不要求为每种状态创建独立 Story。

本设计不向 Story 合同增加前端专用类型或字段。

### 13.3 generate-task

`generate-task` 继续使用 Task 估算模型规定的基础单元：

- “界面与交互”调整或接入复用 Task，应匹配 `INTERFACE` Effective Start；
- “通用界面组件”调整或接入复用 Task，应匹配 `UI_COMPONENT` Effective Start；
- 新建 Task 通常允许 `matchedEffectiveStartItemIds` 为空；
- 兼容性、无障碍或自动化验证构成独立交付对象时，使用 Task 估算模型已有的质量验证基础单元。

Task schema 不新增 `architectureDeltaIds` 或前端专用字段。

## 14. 工作簿投影

`90-系统现状` 继续作为唯一 As-Is Sheet，并增加以下记录类型：

- `CLIENT_ASSESSMENT`
- `CLIENT_SURFACE`
- `CURRENT_FACT` 中的 `INTERFACE / UI_COMPONENT`
- `EFFECTIVE_START` 中的 `INTERFACE / UI_COMPONENT`

Client Surface 行至少展示 kind、lifecycle status、入口、Repo 和关联 Item/Effective Start。Topic 表仍保持九行。

`05-任务明细` 不新增 As-Is 前端专用列。现有“系统现状匹配”继续写入 `matchedEffectiveStartItemIds`，并与 `90-系统现状` 中相同的前端 Effective Start ID 形成可验证引用。

## 15. 测试策略

### 15.1 Schema 和语义测试

- 接受证据完整的 Web Client As-Is。
- 接受证据支持的无当前前端基线结论。
- 拒绝缺少 Client Assessment。
- 拒绝没有排除证据的 `NOT_APPLICABLE`。
- 拒绝 `CLIENT_APP` Repo 没有 Client Surface。
- 拒绝 `CLIENT_LIBRARY` Repo 没有 `UI_COMPONENT`。
- 拒绝没有 Evidence 的 Client Surface、`INTERFACE` 或 `UI_COMPONENT`。
- 拒绝未知 Repo、Item、Effective Start、Evidence、Feature 或 Uncertainty 引用。
- 拒绝用未回答问卷生成 Evidence。
- 拒绝没有 `DEPLOYMENT` Evidence 的 `ACTIVE` Surface。

### 15.2 调查行为测试

- Fixture 中代码足以回答时不生成问卷。
- 部署状态未知时保留代码事实，并只为部署缺口生成 Uncertainty。
- CodeGraph 不覆盖前端动态边界时使用直接证据，而不是直接提问。
- 静态证据充分时不启动应用或浏览器。
- 必要运行验证只证明被执行的命令和覆盖行为。

### 15.3 下游和工作簿测试

- `generate-design` 能读取前端 Client Surface 和 Effective Start。
- “界面与交互”调整 Task 能匹配 `INTERFACE` Effective Start。
- “通用界面组件”调整 Task 能匹配 `UI_COMPONENT` Effective Start。
- 工作簿投影 Client Assessment、Client Surface 和前端有效起点。
- Task 的“系统现状匹配”能够定位到 `90-系统现状` 的前端 Effective Start 行。
- 插件端到端 smoke 在没有问卷的代码完整项目和存在部署缺口的项目上都通过。

插件合同测试不启动真实服务、浏览器、数据库或容器。

## 16. 实现影响范围

本设计实施时至少影响：

- `analyze-as-is` 的 Skill、CodeGraph/运行验证参考、问卷目录、Schema、validator、Fixture 和测试；
- `generate-design` 对前端 Effective Start 的读取、设计规则、Schema/validator 和测试；
- `generate-task` 对前端基础单元与 Effective Start 类型的匹配校验和测试；
- `generate-sow` 的 As-Is 投影、跨文件验证、工作簿模板和测试；
- 0.1.0-beta.1 领域词汇、总体设计引用、README、版本说明和插件 smoke Fixture。

Task 估算模型设计本身不因本方案增加字段或改变计算规则。

## 17. 采用和未采用的方案

采用显式 Client Assessment、Client Surface、`INTERFACE` 和 `UI_COMPONENT`，因为它们能够在不增加 Topic 的情况下形成稳定、可验证、可被 Effective Start 和 Task 消费的前端基线。

未采用：

- 新增 `FRONTEND` Topic：会把平台、安全、运维和交付等跨 Topic 问题压入一个浅层汇总。
- 只扩充问卷：代码已经能够证明的大量事实会被重复询问，且回答无法替代代码证据。
- 只补 Skill 文案：没有稳定对象和校验门槛，服务端单边分析仍可能通过。
- 从自由文本关键词自动判断前端适用性：误判不可控，无法作为确定性合同。
- 把每个 UI 状态编译为独立 Item：会破坏“界面与交互”基础单元的自然边界并放大数据量。
- 修改 Task 数据模型：前端现状可以通过已有 `matchedEffectiveStartItemIds` 接口被消费，无需扩大 Task 接口。

## 18. 验收标准

1. 每份 As-Is 都有且只有一个 Client Assessment。
2. 直接代码证据充分时不生成前端问卷。
3. 每个 `CLIENT_APP` Repo 都被一个或多个 Client Surface 覆盖。
4. 每个当前界面和通用界面组件都有稳定 Item、直接 Evidence 和可核验 Client Surface 关系。
5. 代码存在、运行检查和实际部署在 Evidence 中保持不同语义。
6. 部署未知不会抹去代码事实，而是形成范围收窄的 Uncertainty。
7. 前端 Effective Start 可以区分 `INTERFACE` 与 `UI_COMPONENT`。
8. Feature Coverage 能表达已有交互载体与实际能力覆盖之间的差异。
9. 前端调整或接入复用 Task 能通过 `matchedEffectiveStartItemIds` 追溯准确基线。
10. `90-系统现状` 完整展示 Client Assessment、Client Surface、前端事实、有效起点和 Evidence。
11. 九个 Topic、八个评审章节和 Task 估算模型保持原有所有权。
12. 全部 Schema、validator、Fixture、工作簿、插件 smoke 和仓库验证通过。
