# 详细设计

[返回设计目录](../README.md) · [当前验证摘要](../../validation/README.md)

按问题查阅下列专题。表格描述设计职责，不重复维护开发进度；合成样例用于理解合同，不作为真实运行结果。

| 专题 | 内容 |
|---|---|
| [D00 技术栈](D00-technology-stack.md) | 插件、隔离 Python 与 Office 的运行边界 |
| [D01 交互](D01-interaction-and-outcomes.md) | 输入问答、输出、确认和退出 |
| [D02 数据与依据](D02-shared-data-and-evidence.md) | 身份、来源、问题、分类依据和决定 |
| [D03 输入分析](D03-input-analysis-and-exploration.md) | 文本/XLSX/原型、as-is/to-be/gap 与充分性 |
| [D04 生成与上下文](D04-generate-and-context.md) | 骨架、语义分片和合并 |
| [D04A 单 session 全景](D04A-single-session-panorama.md) | 各步输入输出、上下文累积和优化顺序 |
| [D04B 有限环路](D04B-bounded-loops.md) | 批量、追加/返修上限和无进展退出 |
| [D05 局部修改](D05-clarify-and-change-scope.md) | 定位、计划、确认、部分答复及历史保护 |
| [D06 Excel](D06-excel-projection-and-delivery.md) | 逐列映射、完整正文、模板重算与复读 |
| [D07 工具与恢复](D07-tools-storage-and-recovery.md) | 有限接口、存储、版本、幂等与取消 |
| [D08 资源观测](D08-telemetry-and-performance.md) | 时钟、原生 usage、独立报告和性能比较 |
| [D09 场景与验证](D09-validation-and-implementation.md) | 163 个场景的主责及最早实现依赖 |

## 合成走读

- [EX01 生成与新会话修改](examples/EX01-generate-clarify.md)
- [EX02 输入分析](examples/EX02-input-analysis-and-exploration.md)
- [EX03 历史与本期 gap](examples/EX03-as-is-to-be-gap.md)
- [EX04 Excel 投影](examples/EX04-excel-projection.md)
- [EX05 有限修改](examples/EX05-clarify-changes.md)
- [EX06 资源记账](examples/EX06-telemetry-accounting.md)
- [EX07 合同反例](examples/EX07-design-consistency.md)

详细设计路线图、实现前审阅和 P00—P05 计划保留在 [历史档案](../../archive/README.md)。
