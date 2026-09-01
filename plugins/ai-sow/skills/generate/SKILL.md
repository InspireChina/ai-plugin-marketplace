---
name: generate
description: 当需要从 Markdown PRD/HLD、XLSX 往期 SOW 或文本/原型补充材料一次生成、增量更新或恢复 AI SOW 时使用。
---

# 生成 AI SOW

在一次连续调用中完成输入固化、Scope/Delivery 编译、独立终审、工作簿渲染和不可变发布。执行前完整读取并遵守[输出语言合同](../../references/output-language.md)与[运行时环境合同](../../references/runtime-environment.md)。

## 入口

从当前 `SKILL.md` 得到绝对 `<skill-root>`，其上两级为 `<plugin-root>`；把项目目录解析为绝对 `<project-root>`。所有内部模式均通过同一平台入口调用 `skills/generate/scripts/orchestrator.py`：

```text
sh "<skill-root>/scripts/bootstrap.sh" --project-root "<project-root>" --mode <mode> ...
```

```text
powershell -NoProfile -ExecutionPolicy Bypass -File "<skill-root>/scripts/bootstrap.ps1" -ProjectRoot "<project-root>" -Mode <mode> ...
```

bootstrap 固定准备 `uv 0.11.7`、managed Python 3.12、锁定的插件 `.venv`，之后只把本次参数传给 orchestrator。用户不需要安装工具、执行内部命令或了解模式名。

## 输入

一次收集完整标准请求并保存为项目内 JSON，再以 `prepare --request <path>` 启动。PRD 与 HLD 只接受 UTF-8 Markdown；往期 SOW 只接受 XLSX；补充材料接受 UTF-8 纯文本（默认 Markdown）、HTML、TypeScript/TSX 原型源码或 XLSX。其他需要专用解析器的格式当前不受支持。

若关键语义缺失，直接给出以下绝对安装路径，便于用户补全，不让用户寻找脚本：

- `<skill-root>/assets/prd-template.md`
- `<skill-root>/assets/hld-template.md`
- `<skill-root>/assets/greenfield-questionnaire.md`
- `<skill-root>/assets/sow-template.xlsx`

原型补充材料需要按界面、功能、用户动作、触发条件、状态变化、校验、权限、异常与可观察结果提取语义。源码不足且 Demo 可运行时，在本机启动后使用 Playwright 或 Computer Use 核验交互，再编写 Scope；把核验结论写入候选数据，不把工具输出或完整源码写入稳定产物。

## 连续推进

按 orchestrator 的 `outcome` 继续，直到形成终态：

1. `READY_FOR_SCOPE`：读取 pending anchors 和 [Scope 编译合同](references/scope-compilation.md)，完成全部受影响 Feature、引用和 ID decisions；以 `accept-scope --candidate <path> --ids <path>` 接受。
2. `READY_FOR_DELIVERY`：读取 [Delivery 编译合同](references/delivery-compilation.md)，基于当前 Scope 完成受影响 Story、AC、Task、依赖、集成与设计任务及 ID decisions；以 `accept-delivery --candidate <path> --ids <path>` 接受。
3. `REVIEW_REQUIRED`：先运行 `prepare-review`，再把 review packet 与 [终审合同](references/final-review.md)交给恰好一名 fresh-context Reviewer。Reviewer 必须复核跨层追踪、完整性、估算边界和阻塞问题；将结果以 `accept-review --review <path>` 接受。
4. `READY_TO_RENDER`：直接运行 `publish`。该分支复用已有 Scope/Delivery 和有效终审，不重新编写语义产物。
5. `REUSED`：立即返回当前 workbook/notes 项目相对路径，不创建 revision 或 generation。
6. `PUBLISHED`：只报告 decision、Feature 新增/更新/删除数、重算 Story/Task 数、当前 workbook/notes 项目相对路径，以及结果中的固定免责声明，然后停止。

每次模式调用都解析唯一 UTF-8 JSON 结果；仅在前一结果明确给出下一分支后继续。Module 名与内部模式不作为用户命令暴露。

## 阻塞与恢复

`BLOCKED` 时只呈现返回的去重问题，并说明上一份有效 SOW 保持不变，然后停止。后续再次调用时，把用户的新答案合并进 pending 标准请求，重新运行 `prepare` 并按 outcome 续接；保留稳定 ID，除非语义实质变化。

Windows 返回 `WINDOWS_LONG_PATH_REQUIRED` 时，提供缩短项目路径或启用机器级长路径策略两种选择。只有用户明确同意机器级影响后，才可运行 `enable_long_paths.ps1 -Apply`；不带 `-Apply` 只读检查。
