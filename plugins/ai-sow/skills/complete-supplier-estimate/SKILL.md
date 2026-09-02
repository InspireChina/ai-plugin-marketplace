---
name: complete-supplier-estimate
description: 当供应商已按 AI SOW 简易估算模板填写范围和任务，需要严格校验并补全为新的正式估算工作簿时使用；不用于任意自制表格、业务分析或人天计算。
---

# 补全供应商估算工作簿

本 Skill 校验受支持版本的供应商简易模板，并从插件正式模板原型生成一份新的正式工作簿。执行前完整读取并遵守[输出语言合同](../../references/output-language.md)；运行路径和插件隔离规则以[插件运行时环境合同](../../references/runtime-environment.md)为准。

## 边界

本 Skill 不是六份稳定业务数据的 Owner，不创建或修改稳定 JSON、评审、receipt 或七阶段成果，也不推断缺失关系、修复供应商内容或计算人天。业务公式、标准和结果只来自插件级正式 XLSX 模板及 Excel 重算。

只接受本 Skill `assets/supplier-estimate-input.xlsx` 派生的 `.xlsx`。输出必须是不存在的新 `.xlsx`，不得覆盖输入或既有文件。出现合同、安全、结构或业务 diagnostics 时，不做部分转换，不创建输出。

## 执行

将包含本文件的目录解析为 `<skill-root>`，上两级目录解析为 `<plugin-root>`，并把输入、输出替换为绝对路径。macOS 或 Linux 运行：

```text
"<plugin-root>/.venv/bin/python" "<skill-root>/scripts/complete_supplier_estimate.py" \
  --input "<supplier.xlsx>" --output "<new-formal.xlsx>"
```

Windows 运行：

```text
"<plugin-root>/.venv/Scripts/python.exe" "<skill-root>/scripts/complete_supplier_estimate.py" \
  --input "<supplier.xlsx>" --output "<new-formal.xlsx>"
```

脚本只执行一次。`outcome: OK` 时报告输入、输出、输入哈希及 Story/Task 数量；`outcome: BLOCKED` 时逐项原样报告 `sheet / row / field / code / message`，停止并让用户修正原供应商副本后另存为新文件再重试。不得猜测、忽略或自动改写任何失败项。
