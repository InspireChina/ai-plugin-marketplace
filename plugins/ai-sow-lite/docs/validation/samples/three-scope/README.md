# I1.1 实际 Agent 合成候选

本目录只含合成材料、真实 Agent 生成的候选及实际来源，不含客户数据。它来自隔离的输入分析和候选生成两轮；是开发验证样本，不是已应用项目，也不是预制答案喂给 Agent 的生成测试。

项目模板不重复保存。复核时将本目录复制到临时项目，把插件 assets/sow-template.xlsx 复制到该项目 `.ai-sow-lite/template/6abc55d44bc66476a60c2251e18c0dfdb66709e07539c246dfdec3a0373f5332/sow-template.xlsx`，保留其原字节，再用 scripts/lite.py 的 check/candidate（scope=full、plan_path=null）核对 `.ai-sow-lite/work/generate/95b424f4-8703-4c4d-9ace-298cd6421cab/candidate.json`。CLI 请求的 project_path 填临时项目；请求信封使用 protocol_version=1.0，request_id 用该候选目录中的请求 UUID；业务文件自身的 schema_version 保持1.0。

预期：检查通过、1项 open，未生成 Excel 或 current。所有业务模型、依据和输入按原字节保留；未改标题或 Task 数来匹配设计例。完整计量与限制见 [Generate 验证](../../I2-generate.md) 和 [宿主验证](../../host-support.md)。此目录是评估侧工件，不能提供给后续盲测 Agent。

- [候选](.ai-sow-lite/work/generate/95b424f4-8703-4c4d-9ace-298cd6421cab/candidate.json)
- [模型](.ai-sow-lite/work/generate/95b424f4-8703-4c4d-9ace-298cd6421cab/model.json)
- [待确认](.ai-sow-lite/work/generate/95b424f4-8703-4c4d-9ace-298cd6421cab/pending-items.json)
