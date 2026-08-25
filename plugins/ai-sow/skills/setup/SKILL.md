---
name: setup
description: 当需要首次初始化 AI SOW 项目，或验证现有项目外壳、Python、uv、锁定依赖和 XLSX 模板是否可用时使用。
---

# 设置 AI SOW 项目

本 Skill 只准备运行环境和最小项目外壳，不进行业务分析、专业评审、稳定业务数据发布或版本迁移。
执行前完整读取并遵守[输出语言合同](../../references/output-language.md)。

## 执行边界

当前 Stage Agent 是本 Skill 的唯一用户接口，直接完成环境检查、项目身份确认和确定性初始化；不派发
叶子 Agent。setup 不形成新的专业结论或评审材料，也不创建模型审查。确定性脚本已经在一次调用内
完成写入、Project Schema 校验和模板 round-trip 复读，Stage 原样报告它的 outcome 与 diagnostics，
不为重复同一检查再运行第二次命令。

## 路径与环境

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`；将用户指定的项目根目录解析为 `<project-root>`。执行前把命令占位符替换为绝对路径。

当前 Stage Agent 按顺序完成：

1. 确认 AI SOW 插件已安装并加载；setup 不安装、升级或重新安装 Codex 插件。
2. 检查 uv 0.11.7 或兼容版本；缺失或不兼容时按当前操作系统的受支持方式进行用户级安装并复核。平台、网络或权限阻止安装时报告确切 blocker。
3. 检查 Python 3.12；缺失或不兼容时通过 uv 安装并复核，不要求管理员权限。
4. 确认 `<plugin-root>/uv.lock` 存在，运行 `uv sync --project "<plugin-root>" --locked`，准备或复用插件自己的隔离依赖环境；不向用户项目写入依赖，不修改 lockfile。
5. 获取并向用户回显稳定 `projectId` 与正式项目名称。

## 初始化与验证

当前 Stage Agent 在 `<project-root>` 直接运行：

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/setup.py" \
  --project-root "<project-root>" --project-id <stable-id> --name <name>
```

脚本只维护：

- 仅含 `projectId`、`name`、`pluginVersion`、`sowStandardVersion` 的 `.ai-sow/project.json`；
- `.ai-sow/templates/sow-template.xlsx`；
- `inputs`、`work`、`reviews`、`data`、`validation`、`outputs` 受管父目录；
- Project Schema 校验和 bundled template 的 XLSX 打开、保存、重新读取。

脚本成功返回前已经复读刚写入或已存在的项目。现有项目只有在身份、四字段元数据、全部受管目录和当前项目模板的必要 Table/XLSX round-trip 均有效时才返回 `OK`，且不修改任何文件。项目模板可以是用户已授权的合法项目级定制，不要求与 bundled template 字节相同。目标存在不完整、损坏或身份冲突的受管内容时返回 `BLOCKED`；setup 不提供 repair、不补目录、不覆盖模板，也不自动迁移 beta.1 项目。

项目模板初始化后是项目级计算输入。以后只有用户明确授权时，`generate-sow` 才能调整该项目副本；不得反向修改 bundled template。

## 完成与停止

脚本返回 `OK` 后，当前 Stage Agent 报告结构化结果和项目相对输出路径，推荐用户显式调用 `analyze-requirement` 并立即停止。代码库、往期 SOW、项目模式和其他现状证据留给 `analyze-as-is` 按需登记；setup 不接收、获取或分析这些资料，也不写业务数据或安装专用调查工具。
