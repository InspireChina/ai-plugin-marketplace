# mall 订单履约与售后升级：SOW 配套示例

这是基于真实开源电商项目 mall 的中等规模改造示例。项目及既有代码可公开核验；本次改造需求、企业已有资产、系统责任、数据规模、性能目标和估算均为示范假设，**不是 mall 作者的实际合同、报价或历史投入，也不是已批准 SOW**。

本案例已正式作为仓库 reference 示例，默认空白模板也已采用相同布局。

- [reference 工作簿](SOW估算与生成示例_v1.3.xlsx)
- [默认空白模板](../../skills/generate/assets/sow-template.xlsx)
- [复现输入 JSON](mall订单履约与售后升级_复现输入.json)

## 范围与结果

示例交付订单查询、拆包发货、物流轨迹、退货审核、退款恢复、对账、SSO 与审计，并纳入自动化测试、性能验证、环境接入、历史数据迁移、发布和技术交接。范围限于三个 mall 应用的项目侧；不承接 WMS、财务、物流或 IdP 对端建设。

| 规模 | 数量 |
| --- | ---: |
| 需求故事 / 验收条件 | 22 / 44 |
| Task / 工作类型 | 59 / 35 |
| 新建 / 调整 / 接入复用 | 33 / 10 / 16 |
| S / M / L | 8 / 47 / 4 |
| 单方向 Integration | 6（内部 5，外部 1） |
| UAT 适用 / 不适用故事 | 12 / 10 |

| 模板汇总项 | 人天 |
| --- | ---: |
| 直接开发人天 | 97.3 |
| SIT 支持人天 | 3.5 |
| UAT 支持人天 | 3.0 |
| 总开发人天 | **103.8** |

以上数值从办公软件重算后的公式缓存读取，未在 Python 中复制估算算法。“直接开发人天”沿用模板名称，包含本例选入的设计、测试、迁移、上线与交接 Task，并非仅编码时间。工作簿不是排期表；没有将人天直接换算为自然日，也没有加入报价、项目管理或许可费用。

## 建议阅读顺序

1. **03-工作量汇总**：先看汇总及第 11～22 行的 8 项参数。参数展示是受保护的公式视图，原始参数表继续保留在估算标准页隐藏区域。此页不展示实体 ID、类型或来源引用；公开来源与内部追溯保留在配套材料。
2. **01-需求故事**：看交付结果、验收条件、UAT 适用性及任务覆盖。共享交付会在业务故事备注中显示，人天归属只保留一处。
3. **02-任务清单**：直接从工作类型名称下拉选择，再确定模式和复杂度。工作类型 ID 由隐藏公式匹配，不需要人工填写。SIT 计费点列已删除；集成任务选择“内部集成/外部集成”，其他任务留空，任务名称全表唯一。备注保留计量范围与判档依据。任务按行顺序对应 TK-001～TK-059，即 Excel 行号减 4；逐项计量范围和判档依据保存在复现输入的 `projection.tasks[].actualMeasurementScope` 中。
4. **90-估算标准**：默认 10 列，右侧展开 6 列细则，再对照 Task 的实际范围。模式 PD 是 M 档基准，最终任务人天由模板计算。原始机器字段隐藏保留，只冻结前四行。

## 重点场景对照

| 要观察的规则 | 示例位置 | 判定要点 |
| --- | --- | --- |
| 存量能力调整 | TK-001、002、014、015 | 已有页面/API 有代码证据；只按本次变化和必要回归判断复杂度。 |
| 项目已有系统，仍有新建 Task | TK-005、007、018 | 新的包裹对象组、拆包事务和退款事务有独立交付结果，不能因项目是改造就全部选调整。 |
| 真正接入复用 | TK-019、025、039～050 中的复用项 | 明确假设已有可用平台或组件，公共资产不改，只交付项目适配、配置与验证；这些企业资产不是开源仓库事实。 |
| 外部接口简单也不直接选 S | TK-011 | 外部稳定物流方向 1 操作、16 字段，按目录的外部规则选 M。 |
| 双向业务拆方向 | TK-009/010、019/020 | WMS 下发/回传、财务提交查询/回传分别拥有 Integration。单次请求的协议响应不另算方向。 |
| L 的明确依据 | TK-003、018、031、036 | 分别体现页面状态恢复、退款并发写冲突、异步回调测试、量化性能目标。 |
| 流程内部页面不重复拆 | TK-013 | 退货四步流程作为一个结果交付，内部编辑控件不再单列 FE-EDIT。 |
| 普通实现细节不建 Task | ST-05、ST-14 备注 | 集成内部落库、普通重试/DLQ、单元测试、例行执行及缺陷复测包含在相应交付内。 |
| 共享资产只计一次 | TK-035，覆盖 ST-01/ST-07/ST-14 | 数据适配包在质量故事计费一次，订单与退货故事显示共享覆盖。 |
| SIT 与专项测试不同 | 6 个 Integration；TK-034 | SIT 支持按方向归属一次；契约测试独立交付持续版本兼容资产，不重复普通联调。 |
| UAT 支持与测试任务不同 | ST-01～12 / ST-13～22 | 业务交付适用 UAT；工程质量故事不套业务 UAT。未另建“UAT执行”任务重复收费。 |
| 按应用×环境 / 应用×批次拆分 | TK-042～047、054～056 | 六个运行实例与三个发布执行结果各有独立边界。 |
| 复用工具，执行仍是新建 | TK-029、054～056 | 新的一次生产迁移或发布结果，不能因为用了已有脚本、流水线就选接入复用。 |
| 迁移三个阶段有不同成果 | TK-027～029 | 脚本与核验资产、演练记录、生产执行记录分别交付；不重复算开发或复演。 |
| 对账与数据导出 | TK-022、024 | 财务人工提供既定快照，避免漏掉数据责任；CSV 交给程序消费，使用 DATA-EXPORT，非人工报表。 |

## 人工填写与 SIT 计算

空白模板已预留 60 条故事、200 条任务：先填唯一故事名称，再在任务表选择所属故事、工作类型名称、工作模式和复杂度。输入格可编辑，公式格受保护；无需生成器，也无需编写任何 ID。任务名称以业务对象、动作和集成方向区分，不能重名。

“集成类型”的下拉仅对目录中具备 SIT 支持资格的集成工作类型开放，选项为内部集成、外部集成；非集成任务留空。切换类型或粘贴导致的不合法组合会在校验结果中提示。复杂度系数与其他计算列使用相同底色，错误提示只出现在校验列。

以下仅解释本例绑定模板的计算结果。每方向支持标准、复杂度系数及内部/外部分别汇总后的取整都由模板公式和参数决定；非集成任务不计 SIT。调整参数或采用其他模板后，应重新通过 Office 回算，不能直接沿用本例结果。

本例内部 I01/I02/I05/I06 均为 M，各 `0.5`；I04 为 S，`0.3`，内部小计 `2.3` 向上取整为 `2.5`。外部 I03 为 M，`1.0`。最终 SIT 支持为 **3.5 人天**。

Excel 直接以唯一任务名称标识计费任务，没有单独的 SIT 计费点列。人工填写时，一个集成任务只描述一个方向；两个不同名称是否实际重复描述同一方向，需要对照计量范围复核。AI 生成时继续由底层 Integration 引用校验同方向多归属、无归属和单任务多方向，用户不负责创建这些内部标识。

## X / 拆分条件如何使用

本例没有把 X 当作可计费复杂度。以下原始大包应先退回拆分，再形成表中的 S/M/L Task：

- “打通 WMS”：包含独立下发和回传方向，拆为 I01、I02；并非因为字段多而随意均分。
- “接入全部环境”：三个应用乘 UAT/PROD 两个环境，拆为六个运行接入 Task。
- “上线三个应用”：共同方案和演练按一个 R01 批次交付；执行结果按应用分别计量。
- “订单与退货全部自动化”：独立业务流程分别交付回归资产，共享数据适配包只计一次。
- 如果实际 WMS 字段超过内部 L 上界、对端环境不可用，或本团队也要实现 WMS，应重新明确范围、拆分或补起点，不直接套本例 M 档。

AI 功能、多租户、跨区域灾备、专业安全认证、真实支付清算等不属于这次订单售后范围，没有为了覆盖目录而强行添加 Task。

## 真实事实与示例假设

F01～F09 是配套来源记录中核验的公开文件；链接锁定到具体 commit，不依赖默认分支。
它们只支持表中的既有能力事实，不证明本例升级需求、企业资产或估算已获项目方认可。
复现输入的 `publicSources` 保留文件路径、完整 commit、SHA-256 和核验日期；不复制源码或完整工具输出。

| 编号 | 既有能力依据 | 固定版本来源 |
| --- | --- | --- |
| F01 | 真实项目及模块架构 | [README.md](https://github.com/macrozheng/mall/blob/0504e86b1f1b6f1b8aa6a734d37a90fb67346be7/README.md) |
| F02 | 已有订单列表、详情、发货和收货信息变更接口 | [OmsOrderController.java](https://github.com/macrozheng/mall/blob/0504e86b1f1b6f1b8aa6a734d37a90fb67346be7/mall-admin/src/main/java/com/macro/mall/controller/OmsOrderController.java) |
| F03 | 已有退货列表、详情和状态更新接口 | [OmsOrderReturnApplyController.java](https://github.com/macrozheng/mall/blob/0504e86b1f1b6f1b8aa6a734d37a90fb67346be7/mall-admin/src/main/java/com/macro/mall/controller/OmsOrderReturnApplyController.java) |
| F04 | 已有消费者退货申请接口 | [OmsPortalOrderReturnApplyController.java](https://github.com/macrozheng/mall/blob/0504e86b1f1b6f1b8aa6a734d37a90fb67346be7/mall-portal/src/main/java/com/macro/mall/portal/controller/OmsPortalOrderReturnApplyController.java) |
| F05 | 已有管理员登录、令牌续期、角色查询 | [UmsAdminController.java](https://github.com/macrozheng/mall/blob/0504e86b1f1b6f1b8aa6a734d37a90fb67346be7/mall-admin/src/main/java/com/macro/mall/controller/UmsAdminController.java) |
| F06 | 已有角色资源分配接口 | [UmsRoleController.java](https://github.com/macrozheng/mall/blob/0504e86b1f1b6f1b8aa6a734d37a90fb67346be7/mall-admin/src/main/java/com/macro/mall/controller/UmsRoleController.java) |
| F07 | 已有后台订单列表页面 | [index.vue](https://github.com/macrozheng/mall-admin-web/blob/81fc17e5a19f452bd854b106a9d59fa1ed5c7eac/src/views/oms/order/index.vue) |
| F08 | 已有后台退货详情处理页面 | [applyDetail.vue](https://github.com/macrozheng/mall-admin-web/blob/81fc17e5a19f452bd854b106a9d59fa1ed5c7eac/src/views/oms/apply/applyDetail.vue) |
| F09 | 已有消费者订单生成、查询、收货确认接口 | [OmsPortalOrderController.java](https://github.com/macrozheng/mall/blob/0504e86b1f1b6f1b8aa6a734d37a90fb67346be7/mall-portal/src/main/java/com/macro/mall/portal/controller/OmsPortalOrderController.java) |

H01～H11 均为本例假设，不能当作开源仓库事实或历史报价依据：

- **H01**：示例企业已有经过验收的 OIDC 客户端及企业 IdP；本次只做项目映射、会话配置和验证，不改公共客户端。
- **H02**：示例企业已有财务退款提交/结果查询适配器；本次只配置项目凭据、8 个映射字段和幂等键，不改适配器；退款结果回传方向尚未建设。
- **H03**：示例企业已有流水线模板及容器平台；本次交付应用流水线实例、环境配置和运行验证，不建设平台。
- **H04**：示例企业已有遥测、告警和业务审计平台；本次只交付项目接入包，不修改平台。
- **H05**：示例企业已有测试数据工厂；本次交付可版本化的订单/退货项目适配包，不只是单次测试配置。
- **H06**：示例部署已沿用公开订单/退货页面、API 与 RBAC；未额外实现本例新增的拆包、WMS、物流查询、财务回调。
- **H07**：示例历史数据快照含订单、明细、退货三个对象共 90 万行、46 个迁移字段；质量基线为缺失必填字段 0.2%、重复业务键 0.05%，隔离后人工确认；允许维护窗口整体回滚。
- **H08**：示例订单查询压测基线为 200 RPS 下 p95=1.8 秒；目标 p95≤600 毫秒、错误率<0.1%，固定同一数据快照和硬件、测量60分钟；这些数值不是 mall 实测结果。
- **H09**：交付范围为 mall-admin、mall-portal、后台 Web 三个应用；已有 DEV/UAT/PROD 平台，纳入六个 UAT/PROD 应用环境接入；只交付一个发布批次。
- **H10**：WMS、财务、IdP 由示例企业内部其他团队维护，物流服务由外部供应商维护；本团队只实现 mall 一侧，接口稳定且联调环境正常可用。
- **H11**：财务每天提供截至次日02:00的退款单/退款明细CSV快照，由财务人工上传至约定目录；本次对账直接消费快照，不建设新的自动文件传输方向。

本例不保存真实个人、订单或支付数据，不包含生产凭据。JSON 中的接口路径是公开代码位置或案例说明，
“项目凭据”是待实施工作的描述，不是凭据值。Task 中的 F/H 编号分别对应上述事实来源和假设。
其余排除项保存在复现输入的 `exclusions`，不承诺对开源项目完成生产安全审计或部署验证。

## 复现输入与证据边界

[复现输入 JSON](mall订单履约与售后升级_复现输入.json)采用 `ILLUSTRATIVE_NOT_APPROVED` 状态，
包含公开来源、企业资产假设、排除范围、预期缓存结果及 renderer 所需的 `projection`。
它是示例投影数据，不是 `ai-sow-model-v1` 稳定交接文件，不可作为 `start` 请求、已封存 checkpoint
或发布审批证据使用。示例 ID 只用于故事、AC、任务、共享覆盖与 Integration 之间的确定性引用。

输入保留全部故事和 AC 文本、任务判定依据、模板标准行语义哈希以及故事备注；去掉临时路径、
未形成正式输入 revision 的哈希声明、悬空来源引用和空的工作流集合。公开来源与 H01～H11 假设
直接随输入保存；故事和任务投影与整理前的示例输入一致。汇总页不附来源台账，完整来源仍可在本说明和
JSON 中复核；只有精简 XLSX 时不能宣称已恢复稳定机器身份。

| 已采纳文件 | SHA-256 |
| --- | --- |
| 默认空白模板 | `470f0ef92dfc71c3a3516484721b58e284037f5ea32aae900d16abd3418b97a8` |
| reference 示例 | `b4b12f5250a5503b8fe938f1f19330e04d5a20955f16b2d1051d587f0711c3ed` |

正式采纳的示例采用 `generation-renderer-v13`、LibreOffice 26.8.0.3，回算并复读的结果为
22 条 Story、59 条 Task，直接开发 97.3、SIT 支持 3.5、UAT 支持 3.0，总计 103.8 人天。
同一示例输入从默认模板重新投影后，Office 独立参考重算的 audit 为 `VERIFIED`，五张命名 Table
的全部缓存值与原示例一致。四个 Sheet 的 PDF 完整通过，`03-工作量汇总` 标题中的“量”字显示
恢复正常；重新投影继承正确模板字体，不沿用旧预览中已被替换的字体。
上述哈希绑定已采纳文件；不同 Office 版本重新保存后的 ZIP 字节不要求相同，应检查投影、公式缓存、
结构和汇总。空白模板预备的 60/200 行用于人工录入，程序生成时按本例 22/59 行调整命名 Table。

案例材料没有完整的阶段 Review、人工批准、artifact manifest 或生产发布收据。正式采纳它作为
reference 不意味着通过真实项目的业务审批；工作簿计算和结构验证也不替代独立语义与视觉评审。
本说明保留可复现输入与必要来源，不搬入历史测试日志、渲染大文件或临时工作目录。

## 复现步骤

以下面向贡献者，在插件根目录运行，即仓库的 `plugins/ai-sow` 或独立插件副本；依赖按锁文件安装，
LibreOffice 须已可发现，或通过 `AI_SOW_OFFICE_BIN` 指定。命令使用 POSIX shell；Windows 可将其中
Python 片段交给同一插件环境的 Python 执行。输出新建于系统临时目录，不覆盖模板或 reference 资产。

```sh
uv sync --locked
uv run --locked python -B - <<'PYCODE'
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

plugin = Path.cwd()
skill = plugin / "skills/generate"
sys.path.insert(0, str(skill / "scripts"))
from office_engine import recalculate_workbook, require_office_engine
from package_renderer import RENDERER_CONTRACT
from workbook import audit_calculated_workbook, write_workbook

example = json.loads((plugin / "docs/reference/mall订单履约与售后升级_复现输入.json").read_text(encoding="utf-8"))
assert example["status"] == "ILLUSTRATIVE_NOT_APPROVED"
assert example["rendererContract"] == RENDERER_CONTRACT
template = plugin / example["template"]["path"]
assert hashlib.sha256(template.read_bytes()).hexdigest() == example["template"]["sha256"]
projection = example["projection"]
assert projection["project"]["templateSha256"] == example["template"]["sha256"]
output = Path(tempfile.mkdtemp(prefix="mall-sow-reference-"))
candidate = output / "candidate.xlsx"
calculated = output / "mall-sow-example.xlsx"
write_workbook(template, projection, candidate)
engine = require_office_engine()
recalculate_workbook(candidate, calculated, engine)
audit = audit_calculated_workbook(calculated, template, projection, engine)
assert audit.trust_state == "VERIFIED"
for field, expected in example["expectedResults"].items():
    assert math.isclose(getattr(audit, field), expected, abs_tol=1e-9), field
print(calculated)
PYCODE
```

这里调用现有 Python renderer 投影，由 LibreOffice 执行全部公式，再调用既有复读器校验；没有在
Python 中实现人天算法。该步骤只复现示例工作簿，不创建 run、审批或 generation。
模板或标准行语义哈希变化时应先重新评估输入和预期结果，不能通过直接刷新哈希掩盖变化。
