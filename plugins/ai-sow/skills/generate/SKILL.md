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

1. `READY_FOR_SCOPE`：读取 pending anchors、[Scope 编译合同](references/scope-compilation.md)、[Epic 编写](references/epic-authoring.md)、[Feature 编写](references/feature-authoring.md)、[技术工作分类](references/technical-work-classification.md)与[Effective Start 匹配](references/effective-start-matching.md)。只编辑结果中 `scopeCandidatePath` 指向的插件管理 JSON，在现有骨架内填写 `newAnchorMappings` 与 Scope 业务集合，完成全部受影响 Feature、技术项分类、项目起点判断和引用；不得改写 contract、revision、impact、替换集合或责任边界。完成后直接运行 `accept-scope`；orchestrator 自动推导并校验 ID decisions。
2. `READY_FOR_DELIVERY`：只完成 Epic/Feature/Story/AC 阶段。读取[Delivery 编译合同](references/delivery-compilation.md)、[Delivery 编写导航](references/delivery-authoring.md)、[Story 编写](references/story-authoring.md)、[Acceptance Criteria](references/acceptance-criteria.md)与[动态拆解](references/delivery-decomposition.md)，基于当前 Scope 完成并复核全部受影响 Story 与 AC；此时 `tasks` 与 `dependencies` 保持为空，不读取 Task 编写或估算模板。Story 必须是可独立移交并关闭的具体结果；具体交付物或能力、负责方或消费者、独立验收边界、独立关闭或发布边界必须共同成立，不能因目标、指标、质量属性、政策类别或控制集合可测试或可验收而准入。Technical Story 另须由来源或已批准设计明确支持一个可独立运行或消费的机制、配置、证据包或运营能力，不能由控制归组、验收活动或指定验收人制造。在工作上下文建立一次性来源义务闭包清单，保留来源的全部条件、实际触发、跨 Feature 适用范围及 Integration/NFR 落点；每个原子目标或控制先作为来源可追溯 AC 放入全部适用的具体 Story，项目级且没有 Story 特定行为的义务保留在 NFR、DoD 或质量门禁，来源阈值不得被仪表盘或报表替代。运行 `accept-story-ac` 前仅在内存中完成零未解决行的双向闭包审计；Scope 缺陷回到 `prepare`/`accept-scope`，Story/AC 缺陷只修正受管 candidate。通过后运行 `accept-story-ac`，得到工作区收据和 `READY_FOR_TASK`；不发布稳定 Delivery，也不增加额外确认步骤。当前只验证 Story/AC 的 E2E 必须在这里停止。
3. `READY_FOR_TASK`：仅在后续明确进入 Task 阶段时，才读取[Task 编写](references/task-authoring.md)、[Effective Start 匹配](references/effective-start-matching.md)与[交付工作分类](references/delivery-work-classification.md)，在同一受管 candidate 中填写 Task 与 dependencies，不得改写已验收的 Story/AC；Story/AC 有任何变化都必须重新运行 `accept-story-ac`。Task 完成并通过自己的收敛检查后才运行 `accept-delivery`。
4. `REVIEW_REQUIRED`：读取[问题编写](references/question-authoring.md)、[非证据性示例](references/delivery-examples.md)和[终审合同](references/final-review.md)。逐项展示每个问题的“问题、为什么要问、答案决定什么、未回答后果”。先运行 `prepare-review`；当确认内容较长时，优先提供结果中的 `reviewMaterialPath`，而非要求使用内部哈希识别确认内容。将 review packet 交给恰好一名 fresh-context Reviewer。Reviewer 必须复核跨层追踪、完整性、估算边界和阻塞问题；将结果以 `accept-review --review <path>` 接受。
5. `READY_TO_RENDER`：直接运行 `publish`。该分支复用已有 Scope/Delivery 和有效终审，不重新编写语义产物。发布必须找到受支持的 LibreOffice，完成隔离回算和全量复读；缺少计算引擎时返回 `BLOCKED` 并保留上一份有效结果。
6. `REUSED`：立即返回当前 workbook/notes 项目相对路径，不创建 revision 或 generation。
7. `PUBLISHED`：只报告 decision、Feature/Story/AC/Task 的 `affected / recomputed / reused / deleted / final` 统计、当前 workbook/notes 项目相对路径，以及结果中的固定免责声明，然后停止。

每次模式调用都解析唯一 UTF-8 JSON 结果；仅在前一结果明确给出下一分支后继续。Module 名与内部模式不作为用户命令暴露。

候选编写始终是受 Schema 约束的数据编辑。运行中只创建请求、candidate、review 等数据文件，不为单次项目生成 Python、JavaScript、TypeScript、Shell、PowerShell 或其他辅助代码；动态业务内容由当前模型直接写入插件提供的 JSON 骨架，静态字段、hash、替换集合和 ID decisions 由固定实现负责。

工作簿先以 `CANDIDATE` 生成，再由 LibreOffice 重算为正式 `sow.xlsx`。只有 4 个 Sheet、5 个命名 Table、全部参数/目录、每行缓存结果、校验列和汇总恒等关系均复读通过，manifest 才记录 `workbookVerification.trustState = VERIFIED` 并允许发布；`待样本校准` 参数按模板原值披露在说明中，不能改写成固定规则。

## 阻塞与恢复

`BLOCKED` 时只呈现返回的去重问题，并说明上一份有效 SOW 保持不变，然后停止。每个问题都按“问题、为什么要问、答案决定什么、未回答后果”逐项展示；后续再次调用时，把用户的新答案合并进 pending 标准请求，重新运行 `prepare` 并按 outcome 续接；保留稳定 ID，除非语义实质变化。

Windows 返回 `WINDOWS_LONG_PATH_REQUIRED` 时，提供缩短项目路径或启用机器级长路径策略两种选择。只有用户明确同意机器级影响后，才可运行 `enable_long_paths.ps1 -Apply`；不带 `-Apply` 只读检查。
