# AI SOW Lite 详细设计

[返回概要](../README.md) · [设计路线图](../11-detailed-design-roadmap.md)

详细设计按专题维护。当前已完成 R0 的交互与贯穿样例，形成 R1 的最小共享数据和工具/保存接口稿；R2 已展开 D03 输入分析/探索、D04/D04A 骨架与单 session 全景、D04B 环路控制，以及 D06 Excel 投影与 EX04 走读。R3 已形成 D05 Clarify 与 EX05 修改走读，D09 已分配全部场景的验证归属。D08/EX06 已形成观测与性能设计并记录有限宿主只读探针；先验证无 subagent 基线，再按实际开销决定优化。D09 已完成设计一致性收口，EX07 补工作缺口/初始化反例；[P00—P04](../implementation/README.md) 已把四个增量细化为14项实施任务，当前已按单人串行和原模板计算收口，见[统一 review](../REVIEW.md)，执行起点为 I1.1；再依次接真实 generate 与独立 clarify。这里不代表 Lite Skill 或运行时已经实现。

领域词义见 [CONTEXT](../CONTEXT.md)，历史条目、交付物类型、具体实例、复用候选和当前新建口径分别表达。

建议先读 [EX01 三类需求生成与新会话补值](examples/EX01-generate-clarify.md)，再看 D01 的用户边界、D02 的数据和 D07 的保存方式。样例覆盖公共建设单计、页面接入、迁移上线、复杂度默认 M 待确认及一次只改相关字段的 clarify，未实际生成 Excel 或测量性能。

| 专题 | 状态 |
|---|---|
| [D00 技术栈与运行形态](D00-technology-stack.md) | 已采用既有基础组合，完成源码/测试来源核对；Lite 适配、差异回归及新能力验证待开展 |
| [D01 交互与结果](D01-interaction-and-outcomes.md) | R0 设计完成；问答/退出决策、正常异常时序与 EX01 走读，待宿主执行验证 |
| [D02 共享数据与依据](D02-shared-data-and-evidence.md) | R1 最小合同稿；身份、来源、分类依据、空值、问题和应用决定，待更多输入/拆合实例验证 |
| [D03 输入分析与探索](D03-input-analysis-and-exploration.md) | R2 首稿；文本/XLSX 边界、as-is/to-be/gap、匹配依据、读取与覆盖、来源定位、原型自主探索、充分性与输入问题移交；[EX02](examples/EX02-input-analysis-and-exploration.md) 为合成走读，待适配/宿主验证 |
| [D04 Generate 与上下文](D04-generate-and-context.md) | R2 设计稿；骨架来源与语义分片；隔离/并发为待评估选项 |
| [D04A 单 session 输入输出全景](D04A-single-session-panorama.md) | D04 的分析基线；无 subagent 的逐步输入输出、历史累积、异常与优化顺序，待真实执行观测 |
| [EX03 As-is/to-be 与 gap](examples/EX03-as-is-to-be-gap.md) | 稀疏历史、API/事件候选、实例适用、有值待确认及有限修改的合成走读，待实际验证 |
| [D04B 批量处理与环路退出](D04B-bounded-loops.md) | 统一有限目标、共享追加/返修上限、无进展退出和恢复计数；默认参数待实测校准 |
| [D05 Clarify 与修改边界](D05-clarify-and-change-scope.md) | R3 详细设计稿；有限定位/候选/确认、部分答复与子集、拆合与历史引用、串行基线、有限编辑构造、原模板预览及退出；[EX05](examples/EX05-clarify-changes.md) 为合成走读，待运行验证 |
| [D06 Excel 投影与交付](D06-excel-projection-and-delivery.md) | R2 详细设计稿；逐列映射、安全别名、独立问题/全文、必要扩行及原模板重算；[EX04](examples/EX04-excel-projection.md) 为合成走读，未实现投影器 |
| [D07 工具、存储与恢复](D07-tools-storage-and-recovery.md) | 有限读写、确认、版本生效、幂等及取消边界已细化；P00 固定机械编码，I1/I3 负责故障验证 |
| [D08 观测与性能](D08-telemetry-and-performance.md) | R4 设计稿；实际时钟/usage 来源、去重/共享/未知、独立报告及性能实验；[EX06](examples/EX06-telemetry-accounting.md) 记录有限只读探针与合成账例，未实现采集器或性能实测 |
| [D09 设计收口与实现增量](D09-validation-and-implementation.md) | 设计衔接已收口；163 个场景明确主责/最早增量，I1—I4 列出文件职责、验收与限制，并接 P01—P04 具体任务；[EX07](examples/EX07-design-consistency.md) 为合同反例，未实现运行时 |
