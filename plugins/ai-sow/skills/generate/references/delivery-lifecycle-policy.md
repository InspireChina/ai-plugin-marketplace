# 交付生命周期政策

固定生命周期为 `DEVELOPMENT / SIT / UAT / GO_LIVE`。政策只能为已经成立的实施范围增加规定的交付义务，不能从模板目录或阶段名称创造业务/技术需求。

| policyId | inclusionPolicy | 处理 |
| --- | --- | --- |
| `policy-sit-automation` | `DEFAULT_INCLUDED` | 默认加入自动化集成测试代码或脚本；形成独立 Story/AC/Task，用户可在最终批准前明确删除。 |
| `policy-uat-automation` | `DEFAULT_INCLUDED` | 默认加入 API 串联或浏览器驱动的端到端自动化代码；具体技术方式必须由批准设计支持。 |
| `policy-go-live` | `REQUIRED` | 每个实施型 SOW 必须覆盖版本化上线脚本、配置、部署和发布工程化；纯人工动作不自动计价。 |
| `policy-data-migration` | `SOURCE_GATED` | 仅当 PRD、选入 Demo、批准 HLD/ADR 或补充来源明确提出迁移/持续同步时实例化。 |

SIT/UAT 自动化开发人天与模板计算的常规 SIT/UAT 支持人天是两类独立费用。删除自动化范围不得改变模板公式或支持人天。

复杂迁移能力或持续同步属于 `DEVELOPMENT`，即使在 `GO_LIVE` 激活；一次性切换动作与迁移开发产物分开表达。政策实例保存 `policyId`、落点、包含策略和来源引用，不复制模板参数、倍率、公式或取整规则。

政策义务可落入已有稳定 Feature，也可在确有独立交付/责任/验收边界时形成 Delivery/Technical Feature。不得为了让每个阶段都有一层节点而机械创建 Feature。
