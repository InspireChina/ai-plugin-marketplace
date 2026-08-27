---
name: setup
description: 当需要首次初始化或只读验证 AI SOW 项目，并自动准备插件隔离的 uv、Python、锁定依赖和 XLSX 模板时使用。
---

# 设置 AI SOW 项目

本 Skill 只准备运行环境和最小项目外壳，不进行业务分析、专业评审、稳定业务数据发布或版本迁移。
执行前完整读取并遵守[输出语言合同](../../references/output-language.md)。
运行时产物与后续 Skill 的解释方式以[插件运行时环境合同](../../references/runtime-environment.md)为准。

## 执行边界

当前 Stage Agent 是本 Skill 的唯一用户接口，直接完成环境自举、项目身份确认和确定性初始化；不派发
叶子 Agent。setup 不形成新的专业结论或评审材料，也不创建模型审查。bootstrap 与 setup Module 已在
一次公开命令内完成运行时准备、写入、Project Schema 校验和模板 round-trip 复读，Stage 原样报告最终
outcome 与 diagnostics，不拆成多条模型驱动的环境命令，也不为重复同一检查再运行第二次命令。

## 路径与环境

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`；将用户指定的项目根目录解析为 `<project-root>`。执行前把命令占位符替换为绝对路径。

当前 Stage Agent 先获取并向用户回显稳定 `projectId` 与正式项目名称，再只运行当前平台的一条 bootstrap 命令。bootstrap 负责：

1. 只复用精确 `uv 0.11.7`；不存在或版本不同时，通过 Astral 官方固定版本 standalone installer 自动安装到插件安装副本的 `.ai-sow-tools/`，不修改 shell profile、不要求管理员权限；
2. 复用 Python 3.12；不存在时由 uv 自动安装 managed Python 3.12；
3. 以锁定文件创建或复用 `<plugin-root>/.venv`，复核 Python 版本以及 `jsonschema`、`openpyxl` import；
4. 环境有效后立即调用同目录 `setup.py` 完成项目初始化与复读。

用户无需手工安装 Python、uv 或依赖，也无需复制、理解或执行命令。缺少联网或插件缓存写权限时，Stage 说明一次必要权限的目的并使用 Codex 的权限机制自动重试同一 bootstrap；不得要求 BA、PM 打开终端处理。联网或平台能力确实不可用时，原样返回 bootstrap 的 `BLOCKED` diagnostics，且不得先创建 `.ai-sow`。

## 初始化与验证

macOS 或 Linux 直接运行：

```text
sh "<skill-root>/scripts/bootstrap.sh" \
  --project-root "<project-root>" --project-id <stable-id> --name <name>
```

Windows PowerShell 直接运行：

```text
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill-root>/scripts/bootstrap.ps1" \
  -ProjectRoot "<project-root>" -ProjectId <stable-id> -Name <name>
```

两条命令都是 setup 的实际平台入口。macOS 已完成实机验证；Windows PowerShell 路径在
[插件运行时环境合同](../../references/runtime-environment.md)列出的实机验收完成前保持
`Provisional`，不得把 CI 或合成测试描述成 Windows 实机认证。

bootstrap 在锁定同步与依赖复核后，直接使用刚建立的插件 `.venv` Python 执行
`"<skill-root>/scripts/setup.py"`；Stage 不再单独执行或复读这些内部步骤。

脚本只维护：

- 仅含 `projectId`、`name`、`pluginVersion`、`sowStandardVersion` 的 `.ai-sow/project.json`；
- `.ai-sow/templates/sow-template.xlsx`；
- `inputs`、`work`、`reviews`、`data`、`validation`、`outputs` 受管父目录；
- Project Schema 校验和 bundled template 的 XLSX 打开、保存、重新读取。

模板的业务 Sheet 只使用唯一、非空的名称展示、下拉和跨表引用，可翻译的选项使用中文；稳定
ID 保留在结构化数据中。任务明细以基础单元名称提供下拉并由公式匹配目录；项目参数代码、
任务族 ID 和基础单元 ID 仅因模板读取或计算需要保留并默认隐藏。公式仍是基础人天、SIT、UAT、
风险、取整和总计的唯一计算依据。`90-系统现状` 不启用工作表保护，只保留一张包含主题、现状条目
名称、现状描述和起点可用性的明细表；主题与起点可用性提供下拉，名称与描述可自由填写。任务明细
直接从该可见名称列选择“关联现状条目”，不使用隐藏辅助名单。这些修改不回写稳定 JSON、评审或 manifest。

脚本成功返回前已经复读刚写入或已存在的项目。现有项目只有在身份、四字段元数据、全部受管目录和当前项目模板的必要 Table/XLSX round-trip 均有效时才返回 `OK`，且不修改任何文件。项目模板可以是用户已授权的合法项目级定制，不要求与 bundled template 字节相同。目标存在不完整、损坏、身份或版本冲突的受管内容时返回 `BLOCKED`；setup 不提供 repair、不补目录也不覆盖模板。

项目模板初始化后是项目级计算输入。以后只有用户明确授权时，`generate-sow` 才能调整该项目副本；不得反向修改 bundled template。

## 完成与停止

脚本返回 `OK` 后，当前 Stage Agent 报告结构化结果和项目相对输出路径，推荐用户显式调用 `analyze-requirement` 并立即停止。代码库、往期 SOW、项目模式和其他现状证据留给 `analyze-as-is` 按需登记；setup 不接收、获取或分析这些资料，也不写业务数据或安装专用调查工具。
