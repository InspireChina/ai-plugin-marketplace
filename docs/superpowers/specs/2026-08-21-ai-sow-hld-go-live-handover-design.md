# AI SOW 高阶设计、上线与交付移交改进设计

状态：待文档评审（设计方向已确认）

日期：2026-08-21

目标插件版本：0.1.0-beta.1

目标 SOW 标准版本：v1.3（尚未发布，直接并入，不提供旧格式兼容）

## 1. 背景与结论

当前 v1.3 已用 `Epic → Feature → Story → Task` 表达需求、交付结果和原子估算，并提供发布切换、数据迁移、系统功能下线和运维交接等基础单元。现有模型仍有三项缺口：

1. 高阶设计已经生成 `DesignItem`、`DesignDecision`、`ArchitectureDelta` 和 `ScopeDecision`，但工作簿没有直接投影这些设计结果，也没有强制验证每个 `IN_SCOPE` Feature 已获得足够目标设计覆盖，或每个 `FULLY_COVERED` Feature 已具备完整的现状证明链。
2. UAT 后到生产上线的范围没有强制检查点，项目可能遗漏上线准备、发布切换、运维移交、上线后支持边界、培训或旧功能下线。
3. 现有 `技术支持事项` 按一个明确问题计数，而上线后支持通常按时长、覆盖时段、人员配置和实际事件量计量，不能作为同一种基础单元；`运维交接与操作手册` 面向运维人员，也不能表达最终用户培训与使用材料。

本设计采用以下结论：

1. 每个 SOW 都必须完成高阶设计覆盖门禁和上线范围门禁。门禁允许得出不在范围或不适用的结论，但不允许不分析、无依据或保持未决。
2. 保持正式层级及现有设计实体不变，不新增 Delivery Phase、Document Package、HLD Artifact 或 Story 类型。
3. 高阶设计以 Feature 为覆盖和评审粒度，以 `DesignItem` 与 `DesignDecision` 为实际设计粒度，以独立架构问题为 Task 估算粒度。
4. 上线计划与上线实施是同一个 `发布切换` 基础单元实例，不存在计划-only 基础单元，也不按编写、评审和实施步骤拆 Task。
5. 基础单元目录从 36 项扩展为 37 项，只新增 `用户培训与使用材料`；现有 `数据迁移与切换` 拆为 `数据迁移` 和 `发布与切换`，`问题整改` 与 `交付支持` 重组为 `问题处理` 和 `交付与移交`，任务族从 12 个调整为 13 个。
6. 文档是对应 Task 的交付物载体，不新增通用“编写文档”基础单元。
7. 不新增高阶设计工作表。HLD 是项目内交付物时通过 TECHNICAL Feature、Story、AC 和 `架构方案设计` Task 展示；只是估算前提时仅由设计覆盖门禁保证，不在工作簿重复投影。
8. 不新增 `上线稳定期保障` 基础单元。上线后支持是必须评估的合同或服务容量事项；可明确交付的生产验证、监控、交接、问题诊断和问题整改分别使用现有基础单元。

## 2. 目标

1. 让每个 SOW 都能证明高阶设计已覆盖全部 `IN_SCOPE` Feature、现状证据已覆盖全部 `FULLY_COVERED` Feature，并能追溯关键架构决策和相对 Effective Start 的变化。
2. 让每个 SOW 都明确生产上线和运营移交是 `IN_SCOPE`、`FULLY_COVERED`、`OUT_OF_SCOPE` 还是 `NOT_APPLICABLE`，并保存依据和责任边界。
3. 在上线属于范围时，完整覆盖上线准备、生产发布切换、生产验证、运维交接、用户培训和条件适用的数据迁移及旧功能下线；数据迁移与发布切换分别交付、验收和估算。
4. 让上线计划、上线实施及其文档只估算一次。
5. 为用户培训建立可复用、可审计、可校准的基础单元，并把上线后支持从问题处理和交付移交中明确分离。
6. 不扩大 Story 或 Task 的正式接口，不引入与 Feature、AC 或 Task 重复的交付物实体。

## 3. 不处理的事项

- 不把项目管理、日常会议、一般沟通或排期压力建成 Task。
- 不把生产上线默认判定为供应商范围；强制考虑不等于强制纳入。
- 不为未知数量的未来缺陷预先生成整改 Task。
- 不用 `问题诊断与恢复` 表达上线后值守、可用性承诺或持续运维。
- 不用 Task 的复杂度表达支持天数、覆盖时段、并发人员或未知事件量；专职驻场、固定班次和 24×7 支持需要独立服务容量模型或单独支持 SOW。
- 不建设长期 ITSM、培训平台、发布平台或运维平台；这些平台能力需要独立 Feature 和 Task。
- 不增加通用“上线阶段”“文档交接”“高阶设计”Story 类型。
- 不为首次公开预发布前的内部原型提供迁移器；SOW v1.3 随 `0.1.0-beta.1` 首次公开，本设计直接修改尚未发布的权威资产。

## 4. 领域模型与追溯

正式交付层级保持：

```text
Epic
  └── Feature
        └── Delivery Gap
              └── Story
                    └── Task
```

高阶设计使用现有实体形成多对多追溯：

```text
Feature ←── ScopeDecision ──→ DesignItem
   ↑              │               ↑
   │              └── effectiveStartItemIds ──→ Effective Start
   └──── relatedFeatureIds ── DesignDecision       ↑
                                  │                │
Effective Start ← ArchitectureDelta ──→ DesignItem │
                                                   │
                     As-Is Item / Evidence ─────────┘
```

各层职责如下：

- **Epic**：围绕同一业务结果或技术目标组织 Feature。
- **Feature**：可以独立纳入、排除、延期和评审的最小需求范围，也是高阶设计覆盖索引。
- **ScopeDecision**：记录 Feature 的 `IN_SCOPE / FULLY_COVERED / OUT_OF_SCOPE` 结论与理由；`IN_SCOPE` 通过 `designItemIds` 指向目标设计，`FULLY_COVERED` 通过 `effectiveStartItemIds` 指向现状证明起点。
- **DesignItem**：目标设计中的 `COMPONENT / FLOW / DATA / INTEGRATION / INFRASTRUCTURE / QUALITY` 对象。
- **DesignDecision**：对一个独立设计问题的选择、理由和影响；一个决策可以关联多个 Feature 和 DesignItem。
- **ArchitectureDelta**：一个 DesignItem 相对 Effective Start 的 `NEW / ADOPT / ADJUST / REPLACE / RETIRE` 变化。
- **Story**：相对 Effective Start 仍需交付、可独立验收和结算的结果。
- **Task**：一个基础单元实例的完整工作，不是设计、编写、评审、实施等活动步骤。

不要求 Feature 与 HLD、DesignItem 或架构设计 Task 一一对应。跨 Feature 的认证、数据、集成、部署或质量决策只保存一次，通过关系集合连接所有受影响 Feature。

## 5. 强制门禁

### 5.1 高阶设计覆盖门禁

`generate-design` 的评审必须包含固定标题 **高阶设计覆盖门禁**，并声明：

```text
HLD Coverage: PASSED
```

只有同时满足以下条件才能声明 `PASSED`：

1. 每个 BUSINESS 与 TECHNICAL Feature 恰有一个 `ScopeDecision`。
2. 每个 `IN_SCOPE` Feature 至少关联一个 DesignItem，其设计覆盖说明适用的组件、流程、数据、集成、基础设施或质量设计；不要求无关类型凑数。
3. 每个 `FULLY_COVERED` Feature 至少引用一个 Effective Start，并具有证明现状已完整满足目标要求的 Evidence 和具体判定理由；不得存在关联的 `CARRY_FORWARD` 工作或仍影响估算的未决问题。
4. BUSINESS Feature 判定为 `FULLY_COVERED` 时，其 As-Is Coverage 必须为 `COMPLETE`，且引用的 Effective Start 必须与 Coverage 一致。TECHNICAL Feature 不要求补造 BUSINESS Coverage，但必须满足同一 Effective Start 与 Evidence 证明链。
5. `FULLY_COVERED` Feature 的 DesignItem 关联为可选；仅当既有能力需要在目标架构中显式呈现或参与跨 Feature 设计决策时关联，不得为通过门禁而创建占位 DesignItem。
6. 每个 DesignDecision 至少关联一个 DesignItem 和一个 Feature。
7. 每个 DesignItem 至少被 ScopeDecision、DesignDecision 或 ArchitectureDelta 中的一处引用，不保存孤立设计项。
8. 每条 ArchitectureDelta 引用已知 DesignItem；非 `NEW` 变化引用适用的 Effective Start。
9. 任何仍会改变范围、责任、设计、交付对象、复杂度或人天的问题都形成 `affectsEstimate = true` 的 Uncertainty，并阻止门禁通过。

缺失固定声明、声明不是 `PASSED`、`IN_SCOPE` 设计引用不完整、`FULLY_COVERED` 证明链不完整或存在影响估算的未决问题时，`generate-design` validator 必须失败。`generate-story` 不接受未通过门禁的设计输入。

### 5.2 上线范围门禁

每个 SOW 都必须评估以下十项上线关注点：

| Concern | 必须判断的内容 |
|---|---|
| `PRODUCTION_SCOPE` | 交付目标是否包含生产可用、生产部署或业务切换 |
| `ENVIRONMENT_CONFIGURATION` | 生产环境、基础设施、访问、配置、证书、机密责任和功能开关 |
| `DEPLOYMENT_CUTOVER_ROLLBACK` | 发布窗口、上线计划、实际实施、Go/No-Go、回滚和批准责任 |
| `DATA_MIGRATION` | 数据或状态迁移、演练、核对、回滚和数据责任 |
| `PRODUCTION_VALIDATION` | 生产冒烟、健康检查、数据核对和上线确认 |
| `OBSERVABILITY` | 日志、指标、追踪、Dashboard、告警、SLO 和审计 |
| `OPERATIONS_HANDOVER` | 操作手册、值班、升级路径、知识转移和交接批准 |
| `POST_GO_LIVE_SUPPORT` | 上线后的质保或支持期限、覆盖时段、响应责任、投入上限、服务容量和退出条件 |
| `USER_ENABLEMENT` | 最终用户材料、培训、受众、场次和移交责任 |
| `LEGACY_RETIREMENT` | 旧系统、服务、任务、功能、权限、数据和资源是否下线 |

`generate-design` 的评审必须包含固定标题 **上线范围门禁** 和十行完整矩阵。每行只允许以下处置：

- `IN_SCOPE`：本项目仍需交付，必须关联至少一个 TECHNICAL Feature。
- `FULLY_COVERED`：相对 Effective Start 已完整具备，不产生 Delivery Gap，但必须给出 Evidence 和有效起点。
- `OUT_OF_SCOPE`：明确排除，必须写明责任方、范围边界和依据。
- `NOT_APPLICABLE`：对本项目确实不适用，必须说明原因。

矩阵必须记录 Concern、Disposition、Feature IDs、责任边界、依据或 Evidence。`PRODUCTION_SCOPE` 必须关联至少一个用于表达生产上线与运营移交范围的 TECHNICAL Feature；该 Feature 可以是 `IN_SCOPE`、`FULLY_COVERED` 或 `OUT_OF_SCOPE`，从而保证上线结论进入正式需求和 SOW，而不是只存在于评审文字中。

`PRODUCTION_SCOPE` 不允许使用 `NOT_APPLICABLE`：任何 SOW 都必须明确生产上线属于本项目范围、已由有效起点完整覆盖，还是明确排除。其余九项只有在与已确认的生产范围确实无关时才可使用 `NOT_APPLICABLE`。

`DATA_MIGRATION = IN_SCOPE` 时必须关联独立的数据迁移 TECHNICAL Feature，不能只关联 `PRODUCTION_SCOPE` 使用的生产上线 Feature。两类 Feature 可以同属一个 Epic，但必须能够分别纳入、排除、延期和评审。

`POST_GO_LIVE_SUPPORT` 必须给出合同处置，但不会自动产生 Task：

- 仅包含缺陷责任或质保边界时，写入范围条款、Assumption/Risk 和缺陷/变更判定标准。
- 包含计划性的生产检查、监控建设或运维交接时，分别使用 `人工测试`、`监控、追踪与审计` 或 `运维交接与操作手册`。
- 包含已明确问题时，使用 `问题诊断与恢复`；已确认根因并需要修改代码、配置或数据时，使用 `同一根因问题整改`。
- 包含专职驻场、固定班次、待命容量或 24×7 支持时，当前 Task 模型无法可靠计量，必须形成 `affectsEstimate = true` 的 Uncertainty，并转入独立服务容量模型或单独支持 SOW。

评审末尾必须声明：

```text
Go-live Assessment: PASSED
```

以下情况阻止门禁通过：

- 任一 Concern 缺失、重复、无处置或无理由；
- `IN_SCOPE` 没有 Feature，或 Feature 的 ScopeDecision 不是 `IN_SCOPE`；
- `FULLY_COVERED` 没有 Effective Start 与 Evidence；
- `OUT_OF_SCOPE` 没有责任边界或来源依据；
- 答案仍可能改变估算，却没有 `affectsEstimate = true` 的 Uncertainty；
- `PRODUCTION_SCOPE` 没有进入正式 TECHNICAL Feature；
- 声明缺失或不是 `PASSED`。

门禁确保每个 SOW 都考虑上线，但不会把上线自动归入供应商范围。

## 6. 上线 Feature 与 Story 分解

生产上线和运营移交以一个或多个 TECHNICAL Feature 表达。小型项目通常使用一个 Feature：

```text
生产上线与运营移交
```

多个系统、多个独立窗口或可分别纳入和延期的上线范围必须拆成多个 Feature，不能用复杂度合并。

当上线 Feature 为 `IN_SCOPE` 时，优先拆成三个核心结果型 Story：

1. **生产上线准备就绪**：生产环境、流水线、配置、监控、权限、版本和上线前置条件达到 Go/No-Go 标准。
2. **完成生产发布与业务切换**：在批准窗口完成上线计划、实际实施、生产检查、回滚判断和上线确认；不包含数据迁移执行或迁移核对。
3. **完成生产验证与运维移交**：完成约定的生产检查、运行资料、知识转移、遗留问题责任记录和交接确认；不包含按时段或待命容量计量的上线后支持。

条件适用时分别增加：

4. **完成旧系统或旧功能下线**：旧能力停流、停作业、数据归档、权限与配置清理、资源处置并完成可恢复性验证。

数据迁移适用时不挂在上述上线 Feature 下，而是按可独立纳入和延期的数据范围生成一个或多个 TECHNICAL Feature；每个 `IN_SCOPE` 数据迁移 Feature 形成“完成生产数据迁移与核对”等独立 Story，覆盖映射、转换、迁移执行、校验对账、异常处理和必要演练。

Story 按独立交付、验收和结算结果拆分，不按项目阶段名称机械生成。数据迁移不能并入发布切换 Story；一次上线可以没有数据迁移，也可以依赖一个或多个数据迁移 Feature/Story。小型项目只有在上线准备、发布切换、生产验证和运维交接确实使用同一验收和结算边界时才允许合并；评审必须说明不会隐藏交接、生产验证或切换工作。

上线 Story 通常设置 `uatRelevant = false`。它们接受的是发布、生产验证或运营交接验收，不再次触发业务 UAT 人天。UAT 完成和已批准的遗留问题清单是上线前提，不创建开放式“修完所有 UAT 问题” Story。

SOW 必须明确：

- 实现缺陷与变更请求的判定标准；
- 允许的复测轮次或支持时间窗口；
- 可带缺陷上线的严重等级和批准责任；
- 第三方问题、历史数据问题和范围外需求的处理方式；
- 生产访问、变更审批、业务代表和依赖团队的责任。

## 7. `发布切换` 基础单元补强

上线计划和上线实施属于一个基础单元实例，不存在只设计不实施的上线切换范围。

### 7.1 权威定义

- **计数口径**：一次具有统一窗口、统一责任范围和回滚方案的生产发布切换。
- **包含内容**：版本范围、前置条件、上线计划、窗口、执行顺序、依赖协调、RACI、Go/No-Go、演练、实际部署与切换、流量及数据检查、回滚条件与执行、上线确认和切换记录。
- **不包含内容**：替代功能实现、任何数据迁移执行或迁移核对、运行环境或流水线建设、上线后支持。发布切换只读取迁移完成状态和已批准核对结果作为 Go/No-Go 条件，不承担迁移工作。

推荐 Task 名称：

```text
制定并实施 XX 系统生产发布与切换
```

不得拆成“制定上线计划”“评审上线计划”“实施上线切换”等活动 Task。同一窗口只生成一个 `发布切换` Task。

### 7.2 工作模式

- `新建`：为本次交付新做一次上线计划并实施切换，即使目标系统是现有系统也使用新建。
- `调整`：仅在修改并继续使用已有切换方案、清单、脚本或发布资产时使用，必须精确引用该 Effective Start。
- `接入复用`：不适用。

现有建议 M 档人天保持：

| 新建 | 调整 | 接入复用 |
|---:|---:|---:|
| 2.5 | 1.5 | ❌ |

现有 S/M/L 判断保持，但“方案和实施同属一个实例”必须进入计数口径、具体工作内容、Skill 和评审规则。

## 8. 任务族调整与新增基础单元

目录从 12 个任务族调整为 13 个，从 36 项基础单元扩展为 37 项。

### 8.1 任务族拆分

现有 `数据迁移与切换` 拆成两个任务族：

| 任务族 | 基础单元 | 职责 |
|---|---|---|
| `数据迁移` | `数据迁移` | 数据映射、转换、迁移执行、校验对账、异常处理和迁移演练 |
| `发布与切换` | `发布切换`；`系统功能下线` | 生产发布实施、流量或业务切换、回滚判断，以及旧能力退出 |

同属一次上线不表示属于同一个 Task、Story 或时间窗口。数据迁移可以在上线前分批执行，也可以在切换窗口完成最终增量；发布切换只消费迁移完成状态，不承接迁移工作量。

### 8.2 问题处理与交付移交重组

现有 `问题整改` 与 `交付支持` 两个任务族重组为：

| 任务族 | 基础单元 | 职责 |
|---|---|---|
| `问题处理` | `问题诊断与恢复`；`同一根因问题整改` | 对明确问题形成诊断或恢复结论，或对已确认根因实施整改 |
| `交付与移交` | `运维交接与操作手册`；`用户培训与使用材料` | 向运维人员或最终业务用户交付资料、知识和责任 |

`技术支持事项` 重命名为 `问题诊断与恢复`，原建议 M 档人天保持 `新建 = 2.0`：

- **计数口径**：一个具有统一问题描述和处理结论的明确问题。
- **包含内容**：受理分诊、证据收集、诊断、恢复或建议及处理记录。
- **不包含内容**：上线后值守、待命容量、持续监控、另行批准的产品改造，以及对已确认根因的代码、配置或数据整改。

`同一根因问题整改` 继续负责已确认根因后的实际修改和针对性回归。不得为同一工作同时生成 `问题诊断与恢复` 和 `同一根因问题整改`：只有诊断和恢复结论可以独立验收时才保留前者；根因在估算前已经明确时直接使用后者。

`运维交接与操作手册` 面向运维团队；`用户培训与使用材料` 面向最终业务用户。两者以受众、内容和签收责任区分，不能因都包含知识转移而合并。

### 8.3 用户培训与使用材料

任务族：`交付与移交`

- **计数口径**：一个明确用户群体针对一项连贯能力的培训和材料交付。
- **包含内容**：培训需求确认、使用材料、演示或练习、培训实施、问答、出席记录及材料移交。
- **不包含内容**：运维交接、技术架构培训、业务内容翻译和长期培训运营。
- **工作模式**：`新建` 表示为本次交付形成材料并实施培训；`调整` 表示更新已有材料并按更新范围实施培训；`接入复用` 不适用。

建议 M 档基础人天：

| 新建 | 调整 | 接入复用 |
|---:|---:|---:|
| 1.5 | 1.0 | ❌ |

复杂度标准：

| S | M | L | X / 拆分条件 |
|---|---|---|---|
| 单一角色；标准流程；一次短时讲解；无专门练习环境 | 一个用户群体包含多个相关角色；需要演示、练习和问答 | 多语言、Train-the-Trainer、专门练习环境或正式能力考核 | 多个独立用户群体或多个无关产品，必须拆分 |

## 9. 文档与交接归属

文档是对应 Task 的交付物，不按文件数量生成 Task：

| 文档或记录 | 所属基础单元 |
|---|---|
| 上线计划、Go/No-Go、回滚方案、切换记录 | `发布切换` |
| 数据迁移方案、映射、演练和核对报告 | `数据迁移` |
| 生产冒烟方案和结果 | `人工测试` |
| 部署、启停、监控、故障、回滚、值班和升级路径 | `运维交接与操作手册` |
| 环境、访问和运行配置清单 | `运行环境`、`配置与功能开关` |
| Dashboard、指标、告警和审计清单 | `监控、追踪与审计` |
| HLD、候选方案、权衡、决策和影响 | `架构方案设计` |
| As-built 技术说明 | 随对应实现 Task 更新 |
| 最终用户手册、培训材料和出席记录 | `用户培训与使用材料` |

不新增通用“编写文档”基础单元。只有文档对应一个已经定义、可独立验收和估算的基础单元时才形成独立 Task；编写、评审、修订和移交是该 Task 的内部步骤。

上线后支持方案、响应承诺、投入上限和退出条件属于合同或服务容量约定，不因为形成一份方案、排班表或状态报告而生成 Task。方案中明确列出的生产验证、监控、交接、问题诊断或整改工作，分别归入其权威基础单元。

如果整体资料交接是合同里程碑，可以创建结果型 Story“完成生产资料与运营责任移交”，但其子 Task 仍按上表拆分，不能用一个泛化文档 Task覆盖全部对象。

## 10. 高阶设计交付与估算

### 10.1 SOW 前置设计

为确定范围、系统边界、主要流程、集成、数据、部署方式、质量目标和估算而必须完成的高阶设计，是 SOW 编制前提，不再作为项目交付 Task 重复计费。

只要未决设计问题仍会改变范围、工作量、责任或人天，就必须形成 `affectsEstimate = true` 的 Uncertainty，并在正式 SOW 前关闭。

### 10.2 项目内设计交付

如果 HLD 本身是合同交付物，需要客户正式评审和签署，则使用：

```text
TECHNICAL Feature
  → Story：完成高阶设计并获得批准
    → Task：架构方案设计
```

`架构方案设计` 按一个需要独立决策和评审的架构问题计数，不按 Feature 数、章节数或文档数计数。一个统一认证方案同时影响六个 Feature 时，只保存一条设计决策和一个基础单元实例，并关联全部 Feature。

常规模块设计、接口细节、配置说明、开发自测和基本联调继续包含在对应实现 Task 内，不另拆设计 Task。

## 11. 工作簿呈现

### 11.1 不新增高阶设计 Sheet

工作簿不直接投影 `DesignItem`、`ArchitectureDelta` 和 `DesignDecision`。这些对象用于设计覆盖、范围判断和估算门禁，权威数据继续保存在 `design.json` 并随输出包保留。

HLD 在工作簿中的呈现取决于其是否属于本项目交付范围：

- HLD 只是形成本 SOW 所需的估算前提时，不生成 Story 或 Task，也不在工作簿重复列示设计工作量。
- HLD 是需要客户评审和签署的项目交付物时，使用 TECHNICAL Feature、结果型 Story、AC 和 `架构方案设计` Task，并通过现有需求、Story、验收条件和任务 Sheet 展示。
- HLD 为 `FULLY_COVERED` 或 `OUT_OF_SCOPE` 时不产生 Story；其完整性或范围结论由高阶设计覆盖门禁和稳定设计数据保证，不能仅依赖 Story 检查。

### 11.2 现有 Sheet 调整

- `01-需求` 与 `02-子需求` 显示生产上线与运营移交 TECHNICAL Feature，但不新增范围结论或范围理由列。`IN_SCOPE` TECHNICAL Feature 的交付范围由 `03-SOW主表` 中关联的 Story 表达；`FULLY_COVERED` 或 `OUT_OF_SCOPE` 没有 Story，其 ScopeDecision 只保存在稳定 `design.json` 和门禁评审中。
- `03-SOW主表` 显示范围内的上线 Story，`uatRelevant = false` 不进入 UAT 分母。
- `04-验收条件` 显示上线准备、切换、生产验证和交接的可观察结果。
- `05-任务明细` 支持新增的 `用户培训与使用材料`，并继续通过公式计算任务族、基础人天、复杂度倍率和小计。
- `07-假设清单` 显示生产访问、审批、第三方、支持窗口和责任边界相关 Assumption/Risk。
- `92-基础人天` 从 36 行调整为 37 行，任务族从 12 个调整为 13 个，并反映任务族重组和基础单元重命名。

## 12. Skill 责任变化

### 12.1 `generate-design`

- 强制完成高阶设计覆盖门禁和上线范围门禁。
- 每个 SOW 至少生成一个表达 `PRODUCTION_SCOPE` 的 TECHNICAL Feature，并给出 ScopeDecision；上线可以不在范围，但不能没有结论。
- 对十个上线 Concern 逐项给出处置、依据和责任边界。
- `IN_SCOPE` 上线 Concern 必须映射到适当 Feature 和目标 DesignItem，并在适用时关联 DesignDecision 与 ArchitectureDelta；`FULLY_COVERED` 上线 Concern 必须映射到 Feature、Effective Start 和 Evidence，DesignItem 仅在需要显式呈现既有目标架构时关联。
- `DATA_MIGRATION = IN_SCOPE` 时生成独立于生产上线 Feature 的数据迁移 TECHNICAL Feature；两者只能通过明确依赖和验收前置条件关联，不能合并范围。
- 高阶设计不足或上线责任不清且会影响估算时生成 `affectsEstimate = true` 的 Uncertainty，并保持阻塞。

### 12.2 `generate-story`

- 开始前验证两个门禁均为 `PASSED`。
- 对 `IN_SCOPE` 上线 Feature 形成完整 Delivery Gap。
- 优先按上线准备、发布切换、生产验证与运维移交拆核心 Story；旧功能下线条件适用时单独生成 Story。
- 为每个 `IN_SCOPE` 数据迁移 Feature 单独生成 Gap 和迁移 Story，不允许把迁移 Story 归入生产上线 Feature。
- `POST_GO_LIVE_SUPPORT` 只形成合同边界、Assumption/Risk 或明确的可交付工作，不生成泛化上线后支持 Story。
- 上线 Story 通常设置 `uatRelevant = false`。
- UAT 缺陷责任、变更请求和支持边界进入 AC、Assumption/Risk，不生成开放式缺陷 Story。

### 12.3 `generate-task`

- 从模板读取 37 项基础单元。
- 把上线计划和实施作为一个 `发布切换` 实例，禁止按活动拆分。
- 数据迁移与发布切换必须使用不同基础单元；发布切换不得包含迁移执行或迁移核对。
- 使用新增的 `用户培训与使用材料`，以及重命名后的 `问题诊断与恢复`。
- 不生成 `上线稳定期保障` Task；把计划性的生产验证、监控、交接、问题诊断和问题整改分别映射到权威基础单元。
- 检查发布切换、数据迁移、生产验证、交接、培训和条件适用的下线是否重复或遗漏。
- 文档归入其权威基础单元，不生成泛化文档 Task。

### 12.4 `generate-sow`

- 防御性复核两个门禁、设计引用和 37 项目录。
- 在既有需求、Story、AC、Task、Assumption 和参数 Sheet 中投影上线范围。
- HLD 属于项目交付范围时，通过既有 TECHNICAL Feature、Story、AC 和 `架构方案设计` Task 投影；否则不在工作簿重复展示。
- 不新增设计人天公式；设计工作只在存在 `架构方案设计` Task 时进入估算。

### 12.5 `setup`

- 发布含 37 项基础单元的唯一权威模板，不增加高阶设计 Sheet。
- 继续确保公式、数据验证、命名范围、表结构和样式完整。

## 13. Schema 与校验

不新增正式顶层集合。`design.json`、TECHNICAL requirements、delivery 和 estimate 的总体形状保持不变。

`design.schema.json` 与 validator 需要加强以下约束：

1. DesignDecision 的 `designItemIds` 和 `relatedFeatureIds` 必须非空。
2. `IN_SCOPE` ScopeDecision 的 `designItemIds` 必须非空；`FULLY_COVERED` 的 `designItemIds` 可以为空。
3. ScopeDecision 新增 `effectiveStartItemIds` 引用集合；`FULLY_COVERED` 时必须非空，其他范围决定可以为空。
4. `FULLY_COVERED` 引用的 Effective Start 必须存在，并由 Evidence 直接支持，或由 Evidence 经其 `sourceItemIds` 指向的 As-Is Item 间接支持；`rationale` 必须具体说明目标要求为何已被现状完整满足。
5. BUSINESS Feature 为 `FULLY_COVERED` 时，对应 As-Is Coverage 必须为 `COMPLETE`，Coverage 与 ScopeDecision 的 `effectiveStartItemIds` 必须一致，且不得关联 `CARRY_FORWARD` Commitment 或仍影响估算的 Uncertainty。TECHNICAL Feature 不要求存在 BUSINESS Coverage，但适用相同的 Effective Start、Evidence、理由和未决问题约束。
6. 每个来源和技术 Feature 恰有一个 ScopeDecision。
7. DesignItem 不得孤立。
8. 非 `NEW` ArchitectureDelta 必须引用 Effective Start；`NEW` 可以为空。
9. 评审文件必须包含两个固定门禁声明和完整的十项上线矩阵。
10. 上线矩阵引用的 Feature、ScopeDecision、Effective Start 和 Evidence 必须与稳定 JSON 一致。
11. `PRODUCTION_SCOPE` 必须引用至少一个 TECHNICAL Feature。

模板读取器、`generate-task`、`generate-sow` 和资产测试中的固定目录数量从 36 改为 37，任务族数量从 12 改为 13。

语义规则不能可靠从自由文本推断时，由 Skill 评审 fail closed；能够通过稳定引用或固定门禁声明验证的规则进入 validator。不得通过上线、文档、交付、培训等关键词猜测范围。

## 14. 测试策略

### 14.1 `generate-design`

- 每个 `IN_SCOPE` Feature 有 DesignItem 覆盖时通过。
- `FULLY_COVERED` Feature 没有 DesignItem，但 Effective Start、Evidence、判定理由和适用的 `COMPLETE` Coverage 完整时通过。
- `FULLY_COVERED` Feature 缺少 Effective Start、Evidence 或完整现状覆盖，仍有关联的 `CARRY_FORWARD` 工作或影响估算的未决问题时失败。
- 缺少 HLD 门禁声明时失败。
- `IN_SCOPE` Feature 没有 DesignItem 时失败。
- DesignDecision 没有 Feature 或 DesignItem 时失败。
- DesignItem 孤立时失败。
- 上线十项矩阵完整且引用一致时通过。
- 缺少任一 Concern、Disposition、依据或责任边界时失败。
- `PRODUCTION_SCOPE` 没有 TECHNICAL Feature 时失败。
- 上线责任未决但未形成影响估算 Uncertainty 时失败。

### 14.2 `generate-story`

- 上线在范围时产生准备、切换、生产验证与交接的完整 Story/AC 示例。
- 数据迁移在范围时使用独立 TECHNICAL Feature、Gap 和 Story；上线没有迁移时不生成数据迁移范围。
- 上线明确范围外时不生成上线 Gap，但保留 TECHNICAL Feature 与范围结论。
- `POST_GO_LIVE_SUPPORT` 形成明确合同处置，但不生成泛化支持 Story。
- 未通过任一门禁时失败。
- 上线 Story 不错误进入 UAT 分母。

### 14.3 `generate-task`

- 模板恰有 37 项基础单元和 13 个任务族。
- 一个发布切换 Task 同时覆盖计划和实施。
- 数据迁移与发布切换分别生成 Story 和 Task；上线没有迁移时不生成数据迁移范围。
- 同一 Story 不生成重复的上线计划 Task。
- `技术支持事项` 已重命名为 `问题诊断与恢复`，并与 `同一根因问题整改` 满足互斥规则。
- 用户培训使用正确基础单元、工作模式和复杂度规则。
- 上线后值守、待命容量、24×7 支持或未定义投入上限不生成 Task，并在影响估算时保持阻塞。
- 多个独立用户群体必须拆 Task。

### 14.4 模板与生成

- setup、generate-task fixture、generate-sow fixture 和参考工作簿的目录、公式和表结构一致。
- 新增基础单元进入数据验证和公式查找范围。
- 生成器复读 37 项目录并正确投影一个新增基础单元、一个重命名基础单元和任务族重组。
- HLD 交付 Story 和 `架构方案设计` Task 使用现有 Sheet 正确投影；HLD 仅作为估算前提时不生成重复工作量。
- raw asset、中文投影、端到端 smoke 和跨文件引用测试全部更新。

## 15. 实施影响面

实施预计修改以下区域：

- `plugins/ai-sow/skills/generate-design/`
  - `SKILL.md`
  - `contracts/design.schema.json`
  - `scripts/validate.py`
  - fixtures 与 tests
- `plugins/ai-sow/skills/generate-story/`
  - `SKILL.md`
  - validator、fixtures 与 tests
- `plugins/ai-sow/skills/generate-task/`
  - `SKILL.md`
  - template reader/validator、fixtures 与 tests
- `plugins/ai-sow/skills/generate-sow/`
  - `SKILL.md`
  - generator/workbook projection、fixtures 与 tests
- `plugins/ai-sow/skills/setup/`
  - `SKILL.md`
  - 权威模板资产与 tests
- `plugins/ai-sow/docs/`
  - `CONTEXT.md`
  - `AI_SOW_PLUGIN_DESIGN.md`
  - `reference/SOW任务分类与开发交付人天标准_v1.3.md`
  - 参考 XLSX
- `plugins/ai-sow/tests/support/`
  - 全链路 fixtures 与 smoke

模板及其复制件必须从一个获批权威资产同步生成或进行字节身份校验，不能手工分别修改后留下不一致副本。

## 16. 验收标准

1. v1.3 仍只使用 `Epic → Feature → Story → Task`，不新增 Story 类型或顶层交付物实体。
2. 每个 SOW 的高阶设计覆盖门禁和上线范围门禁都得到 `PASSED`；缺失或未决时 validator 失败。
3. 每个 `IN_SCOPE` Feature 至少关联一个 DesignItem；`FULLY_COVERED` Feature 可以不关联 DesignItem，但必须具有完整且一致的 Effective Start、Evidence、判定理由和适用的 `COMPLETE` Coverage；每个 DesignDecision 至少关联一个 Feature 和 DesignItem。
4. 每个 SOW 都有表达 `PRODUCTION_SCOPE` 的 TECHNICAL Feature 和明确 ScopeDecision。
5. 上线在范围时，Gap、Story、AC 和 Task 覆盖上线准备、计划与实施、生产验证和运维移交，并覆盖条件适用的培训和旧功能下线；数据迁移使用独立 TECHNICAL Feature、Gap、Story 和 Task。
6. 上线计划与上线实施只形成一个 `发布切换` Task，同一窗口不重复估算。
7. `数据迁移` 与 `发布与切换` 是两个任务族；数据迁移与生产上线使用不同 Feature、Story、Task 和工作量，发布切换只把迁移结果作为前置条件。
8. `问题整改` 与 `交付支持` 已重组为 `问题处理` 和 `交付与移交`；`问题诊断与恢复`、`同一根因问题整改`、`运维交接与操作手册` 和 `用户培训与使用材料` 的计数对象与排除范围互不重叠。
9. 任务目录恰有 13 个任务族和 37 个基础单元。
10. 不存在 `上线稳定期保障` 基础单元；`POST_GO_LIVE_SUPPORT` 必须形成合同处置，专职驻场、待命容量或 24×7 支持不能进入当前 Task 估算。
11. `用户培训与使用材料` 具有明确计数口径、包含/不包含内容、工作模式、M 档人天和 S/M/L/X 标准。
12. 文档归入对应基础单元，不生成泛化“编写文档”Task。
13. HLD 以 Feature 为覆盖粒度，以 DesignItem/DesignDecision 为实际设计粒度，以独立架构问题为估算粒度。
14. 工作簿不新增高阶设计 Sheet；HLD 属于项目交付范围时通过现有 Feature、Story、AC 和 `架构方案设计` Task 展示，否则只作为门禁输入且不重复估算。
15. setup、三个模板副本、参考 XLSX、Markdown 标准、Skill、Schema、validator、fixtures 和 tests 对 13 个任务族及 37 项目录保持一致。
16. 全部 Skill 单测、资产测试、端到端 smoke 和仓库级验证通过。
