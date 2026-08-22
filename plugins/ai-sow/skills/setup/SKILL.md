---
name: setup
description: 当需要首次初始化 AI SOW 项目、恢复缺失的项目目录或模板，或确认本地环境具备 XLSX 生成能力时使用。
---

# 设置 AI SOW 项目

创建最小、确定性的项目外壳。首次初始化只需要项目 ID 和名称；脚本写入由合同固定的插件版本和 SOW 标准版本。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。

## 路径

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。保持用户的项目根目录为当前工作目录，并在执行前把命令中的路径占位符替换为绝对路径。

## 初始化

在项目根目录运行：

```text
uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/setup.py" \
  --project-root . --project-id <stable-id> --name <name>
```

完成结果必须包括：

- `.ai-sow/project.json`，且仅有 `projectId`、`name`、`pluginVersion`、`sowStandardVersion` 四个字段；
- `.ai-sow/templates/sow-template.xlsx`；
- 后续 Skill 使用的 `inputs`、`work`、`reviews`、`data`、`validation` 和 `outputs` 父目录；
- Python、锁定依赖和模板内存 round-trip 检查通过。

模板内置 13 个任务族和 37 个基础单元。基础单元、计数口径、S/M/L 标准及“新建 / 调整 / 接入复用”三个工作模式的 M 档基础人天合并在一张配置表中，`❌` 表示不适用；复杂度系数位于项目参数表。模板公式是任务人天、SIT、UAT、风险、取整和总计的唯一计算依据。

依赖不足时提示用户运行 `uv sync --project "<plugin-root>" --locked`。本 Skill 不下载 Python 或 uv。

若 `.ai-sow/project.json` 已存在，只在用户要求恢复缺失目录或模板时增加 `--repair`。修复必须复用已登记的项目 ID 和名称；身份不一致、受管路径包含符号链接或目标内容冲突时返回 `BLOCKED`，并保留现有项目元数据。

## 完成条件

报告创建或恢复的确切路径以及下一项适用的 Skill。代码库、往期 SOW、项目模式和其他现状证据在 `analyze-as-is` 使用时按需登记；setup 不接收、获取或分析这些输入，也不写业务数据或安装专用调查工具。
