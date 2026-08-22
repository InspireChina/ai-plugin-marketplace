# 星云零售全渠道会员与订单服务平台升级（仿真需求简报）

> 本文件全部机构、系统、人员、交易量与时间窗口均为仿真数据，仅用于说明 AI SOW 从需求、现状、设计、Story、Task 到估算汇总的完整追溯方法。

## 项目背景

星云零售在全国经营约 600 家门店，并通过小程序、App 与直营网店提供线上服务。现有会员门户、订单服务与门店系统分阶段建设，会员等级、订单状态、退货退款和财务对账口径不一致。项目拟在不替换 ERP、支付网关与电子发票平台的前提下，升级全渠道会员与订单服务能力，并建立可审计、可切换、可运维的交付边界。

## 业务目标

- 会员档案、等级与权益规则在各渠道保持一致，个人信息处理保留可审计记录。
- 门店和线上订单使用统一的订单状态与库存预占机制，支持退货退款闭环。
- 支付对账、电子发票与经营报表形成可供财务复核的日结链路。
- 上线范围包含迁移、环境、切换、生产验证、监控、交接和培训；上线后驻场支持与旧系统退役不在本期范围。

## 需求清单

### 客户档案

用户可以创建、查看和维护客户档案；渠道侧只展示完成授权的数据字段。

### 会员等级

系统根据年度有效消费额计算会员等级，并在规则调整后保留生效版本与变更记录。

### 授权与隐私

沿用现有授权中心记录营销授权、撤回与查询日志，本项目不得复制授权主数据。

### 订单编排

系统接收门店与线上订单，校验价格、会员权益和履约方式，并以统一状态机驱动后续处理。

### 库存预占

订单确认前调用 ERP 库存接口完成预占或释放；接口超时不得产生重复预占。

### 退货退款

客服与门店可发起退货，系统核验可退数量并通过支付网关发起退款，退款结果回写订单。

### 门店接单

门店工作台展示待处理订单、缺货替代与交接信息，支持按门店权限操作。

### 订单可视

顾客和客服可以查看一致的订单状态、履约节点和异常原因。

### 客户通知

沿用现有消息中心发送订单节点通知，本项目仅消费已发布的标准事件。

### 支付对账

财务每日按支付渠道、门店和订单核对实收、退款与手续费差异，异常项可追溯到原交易。

### 电子发票

订单完成后按开票申请调用外部电子发票平台，并保存发票号码、状态与失败原因。

### 财务经营报表

财务可按日、区域、渠道查看销售、退款、优惠和未对账金额；指标定义须与对账规则一致。

## Technical platform

- Expose customer-profile operations through a stable API boundary.
- Reuse the registered ERP, payment-gateway and e-invoice connections; estimate project-side authentication, mapping, adaptation and verification separately.
- Keep data migration independent from production cutover and rollback.
- Include production readiness, observability, operations handover, user enablement and quality verification as explicit technical scope.
- Exclude post-go-live resident support and legacy retirement from this phase.
