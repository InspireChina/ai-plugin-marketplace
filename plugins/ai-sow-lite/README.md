# AI SOW Lite

从 PRD、高阶设计和往期 SOW 生成本期工作量估算，再根据反馈作局部修改。交付为可独立阅读的 Excel，覆盖业务、技术和交付工作。

当前版本：**0.1.0-alpha.1，首个 Alpha 试用版**（[发布记录](https://github.com/InspireChina/ai-plugin-marketplace/releases/tag/ai-sow-lite-v0.1.0-alpha.1)）。已验证 macOS 本地目录中的 Codex 使用流程；Excel 导出需要已安装的 LibreOffice。完整边界见 [支持与限制](docs/support.md)。

## 安装与准备

Lite 是独立插件，不需要安装 AI SOW。先准备：

- 支持插件安装的 Codex；已验证版本见支持说明。
- 可用的 LibreOffice，用于 Excel 公式重算；Microsoft Excel 可用于查看交付。
- 首次使用时允许访问工具链下载源。插件自动准备隔离的 Python 和依赖，用户无需手工配置 Python/uv。

从远端 marketplace 安装：

```text
codex plugin marketplace add InspireChina/ai-plugin-marketplace
codex plugin add ai-sow-lite@ai-plugin-marketplace
codex plugin list
```

已有同名 Git marketplace 时，先执行 `codex plugin marketplace upgrade ai-plugin-marketplace` 刷新快照，再安装 Lite，无需重复注册。本地开发可将注册命令的来源改为仓库 checkout 的绝对路径；已有同名 marketplace 指向其他来源时先核对注册。

更新 Git marketplace 时先执行 `codex plugin marketplace upgrade ai-plugin-marketplace`，再移除并重新添加 `ai-sow-lite@ai-plugin-marketplace`；本地来源先更新 checkout。卸载插件使用 `codex plugin remove ai-sow-lite@ai-plugin-marketplace`。

## 生成首稿

在保存项目材料的目录中调用 [generate](skills/generate/SKILL.md)，说明项目类型和实际文件路径：

```text
请用 ai-sow-lite 的 generate 生成本期 SOW。
这是新项目，PRD 是 inputs/prd.md，高阶设计是 inputs/hld.md。
```

| 项目 | 必需输入 | 可选输入 |
|---|---|---|
| 新项目 | PRD、高阶设计（HLD） | HTML/JS/CSS 原型目录、已有草稿和补充说明 |
| 旧项目 | PRD、高阶设计、往期 SOW | 同上 |

文档支持 UTF-8 Markdown、文本和 `.xlsx`；原型按目录资源包提供。暂不支持 PDF、DOCX、扫描件、OCR 或其他 Excel 格式。只有 Epic/Feature 标题和零散技术备注通常不足以生成可用估算。

插件先确认新旧项目、收集必要材料；已有信息不重复询问。分析后只就影响推进的业务、技术或交付输入合批澄清；资料严重不足则返回补料清单。往期 SOW 用来理解 as-is，其余项目材料描述 to-be，从两者差异识别本期工作。

信息足够后，Agent 建立 Epic/Feature 骨架，分片完成 Story、AC 和 Task，识别公共技术能力、业务接入、迁移和上线准备，合并后生成 Excel。初稿无需审批，也没有定稿步骤。

## 阅读 Excel

工作簿保留四张表：

| Sheet | 内容 |
|---|---|
| `01-需求故事` | Epic/Feature/Story、完整验收条件、必要备注、SIT/UAT 适用及故事人天 |
| `02-任务清单` | Task、工作类型、工作方式、复杂度、集成类型、判断原因与估算 |
| `03-工作量汇总` | 模板计算的工作量汇总 |
| `90-估算标准` | 工作类型、判定标准、标准人天及 SIT/UAT 适用规则 |

AC 用简短条目约定交付结果和关键边界。Story 备注通常为空，仅保留 AC 未表达的必要范围、责任或外部前提说明；Task 备注说明非新建方式、非 M 复杂度的判断原因。

待确认只保留会改变工作范围、Task 数量或分类、本方责任的未知，直接放到实际受影响行的备注中，该行校验显示“待确认”。不影响估算的字段明细、规范版本等不另列问题；Task 问题不自动上卷到 Story。

复杂度无法判断时先用 M 并留待确认。历史能力只有类型相似、实例适用不明确时，先按新建并留确认项；没有相关历史候选时默认新建。其余缺少依据的结论不编造。

Agent 只作定性分类，人天、金额和适用规则由模板计算。Story 只要含任意 SIT/UAT 适用的 Task，相应适用性即由公式自动计算，不可手改。

## 根据反馈改稿

在同一项目目录中调用 [clarify](skills/clarify/SKILL.md)，可另开会话，无需原生成聊天：

```text
请用 ai-sow-lite 的 clarify 调整当前 SOW。
资料迁移数量暂时拿不到，本次估算明确采用 M，其他范围保持。
```

也可以提出 AC、范围或责任方面的修改意见。插件先定位相关对象、讨论具体方案，确认后只更新约定范围并生成新版本；部分答复只处理已答部分。已采用的重复意见返回已有结果。用户要求时可先生成候选 Excel 预览。

Excel 可以单独分享；后续使用 clarify 需要保留项目的 `.ai-sow-lite/` 目录，只有 Excel 附件不足以恢复完整修改基线。手改 Excel 不会自动同步回插件。

## 保存与恢复

交付保存在项目 `.ai-sow-lite/versions/<version_id>/`，包括 `sow.xlsx`、同版结构化数据、摘要及待确认说明；最新有效版本由 `current.json` 指向。中断后在原项目续接，插件查询实际状态，保留已成功的版本和可恢复工作。

输入、项目文件和工作簿可能含客户资料，按项目权限共享，不要复制进插件源码。工具耗时和可取得的 token 记录独立保存，观测缺失不阻塞出稿。

## 更多说明

- [支持与限制](docs/support.md)：平台、依赖、性能和常见问题。
- [验证摘要](docs/validation/README.md)：已完成的验证及其实际范围。
- [开发维护](docs/development.md)：测试命令、文档职责和设计入口。
- [版本说明](CHANGELOG.md)：本版本的用户可见能力。
