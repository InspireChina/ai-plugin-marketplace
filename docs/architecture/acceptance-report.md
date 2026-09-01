# 已取代：AI SOW 多 Session E2E 阶段汇总报告

> 历史说明：本报告记录 2026-08-30 至 2026-08-31 的预发布多阶段原型，不能作为当前命令、路径、
> 兼容承诺或验收状态使用。该原型已于 2026-09-02 被唯一入口 `ai-sow:generate`、三份稳定 Bundle、
> 自动终审和不可变 generation 架构整体取代。当前合同见
> [AI SOW 插件方案](../../plugins/ai-sow/docs/AI_SOW_PLUGIN_DESIGN.md)。

- 报告性质：中期验收报告
- Run ID：`2026-08-30-codex-v2`
- 统计截止：`2026-08-31T03:54:58+08:00`
- 当前状态：`BLOCKED`
- 当前阶段：`S5R2_STORY_BLOCKED`
- 权威指标来源：`metrics/session-ledger.jsonl`

## 1. 执行结论

本轮已经证明 hash-bound Owner 交接、独立 session 恢复、精确用户批准、稳定产物发布和上游退回机制可以工作；Requirement、As-Is 和更新后的 Design 均已正式发布，且每次发布的稳定 JSON、正式 review 与 `0.3` receipt 都可由批准 packet 追溯。

本轮尚未完成七阶段 E2E。`generate-story` 已运行两次：S5 正确发现真实的 Design Feature 边界重叠并退回 Design Owner；S4R3 修正并发布后，S5R2 又在唯一一次受控 patch 后留下两项 candidate-local 机械失败，因此按合同停止。当前没有可批准的 Story packet，也没有稳定 Delivery、Task 或 SOW package。

截至当前的验收判断：

| 维度 | 结论 | 说明 |
| --- | --- | --- |
| 多 session 正式交接 | `PASS` | 新 session 能仅依赖 receipt 与最小 context 恢复，并能识别 stale/changed 上游。 |
| Owner 数据所有权与批准门禁 | `PASS` | 下游没有修改上游稳定 JSON；稳定数据均在精确 packet 批准后发布。 |
| 机械门禁与专业 Reviewer | `PARTIAL_PASS` | 成功拦截真实问题，但 patch 后闭环、artifact 可见性和 Reviewer 成本仍有明显缺口。 |
| 首次用户可用性 | `PARTIAL_PASS` | setup 和 receipt 交接自然，但多次需要协调 session 解释机械内循环或 stale artifact。 |
| 七阶段完整 E2E | `INCOMPLETE` | 停在 Story，尚未进入 `generate-task`、`generate-sow` 和最终复核。 |
| 性能目标 | `FAIL` | 墙钟、gross token、深度 Reviewer token 和 diff-review token 均显著超标。 |
| 当前版本继续下游 | `HOLD` | 先完成 renderer 修复的完整验证与插件重装，再从全新 S5R3 重跑 Story。 |

## 2. 固定基线与测试范围

| 对象 | 固定值 |
| --- | --- |
| Marketplace commit | `6f778b6ffb6218b8a645fe5357458a189a8e2712` |
| Marketplace tree | `f50f555b4edb292029954fec009fb9062dcd7752` |
| 插件 | `ai-sow@0.1.0` |
| 插件内容指纹 | `34460b6f0ce90b570e2fe5560dc1c9acfd94d588059860df39aad3d139eb5453` |
| 样例仓库 | `explicit-architecture@a7228303cfbde62577466fd056540360d516ca54` |
| 业务输入 | `inputs/requirement-brief.md` |
| 往期 SOW | `inputs/prior-sow-phase1.md` |
| 补充事实包 | `inputs/s4-blocker-facts-v1.md`，SHA-256 `d0b899b1fb7949c95e9f71d666eec2ad66f878aa5876508bdb72e1ed50f6cb71` |
| 首次用户模式 | `INSTALLED_PLUGIN_CLEAN_PROJECT` |
| SOW 标准 | `1.3` |

测试采用独立 Codex task 模拟 BA、TL 等角色，不向新 Owner 传递上一 task 的聊天历史。正式交接只依赖项目内 stable data、review、receipt、packet 和由 Owner compiler 生成的最小 context fragments。

## 3. 阶段轨迹

墙钟均排除用户等待；gross token 包含 cached input。Owner attempt 行包含该轮 Reviewer token，publish 行为用户批准后的快速路径增量。

| Session | 阶段 | 结果 | 墙钟（分钟） | Gross token | 关键说明 |
| --- | --- | --- | ---: | ---: | --- |
| S1 | setup | `OK` | 0.8 | 118,504 | 冷建插件 `.venv`，Python 3.12.13；用户无需手装运行时。 |
| S2 | Requirement attempt 1 | `BLOCKED` | 35.8 | 11,685,772 | 8 项问卷完成后，评审/patch 仍未收敛。 |
| S2R2 | Requirement attempt 2 | `REVIEWER_PASS` | 18.1 | 5,852,194 | 新 session 重建并到达精确批准门禁。 |
| S2R2 | Requirement publish | `OK` | 0.6 | 512,809 | 快速路径正式发布。 |
| S3 | As-Is attempt 1 | `REVIEWER_PASS` | 40.4 | 10,459,162 | 单次仓库调查，9 topics、11 items；Evidence 超目标。 |
| S3 | As-Is publish | `OK` | 0.7 | 625,576 | 正式发布首版 As-Is。 |
| S4 | Design attempt 1 | `BLOCKED` | 13.1 | 1,670,126 | 8 项 `affectsEstimate` Uncertainty 被 HLD 门禁拦截，未启动 Reviewer。 |
| S3R2 | As-Is update | `REVIEWER_PASS` | 32.8 | 14,049,565 | 用户事实包消解估算阻塞，保持 8 个 Uncertainty ID。 |
| S3R2 | As-Is update publish | `OK` | 0.5 | 378,011 | 发布当前有效 As-Is。 |
| S4R2 | Design attempt 2 | `REVIEWER_PASS` | 18.8 | 3,787,426 | HLD/Go-live 均通过。 |
| S4R2 | Design publish | `OK` | 0.9 | 453,871 | 发布首版 Design 与 TECHNICAL requirements。 |
| S5 | Story attempt 1 | `BLOCKED_UPSTREAM` | 21.2 | 4,685,162 | Reviewer 发现 BUSINESS/TECHNICAL Feature 的 `END_TO_END` 重叠。 |
| S4R3 | Design boundary fix | `REVIEWER_PASS` | 20.2 | 4,229,663 | 两个共享 TECHNICAL Feature 收敛为 `PORT_ONLY`。 |
| S4R3 | Design boundary publish | `OK` | 0.7 | 551,541 | 发布当前有效 Design。 |
| S5R2 | Story attempt 2 | `BLOCKED_CANDIDATE_LOCAL` | 21.3 | 2,946,975 | 37/37 claims 深审；一次 patch 后仍有两项机械失败。 |

当前稳定主链为：

```text
setup
  -> Requirement PUBLISHED
  -> As-Is v2 PUBLISHED
  -> Design v2 PUBLISHED
  -> Story BLOCKED
  -> Task NOT_STARTED
  -> SOW NOT_STARTED
```

## 4. 批准与稳定产物链

| Owner / 版本 | 已批准 packet SHA-256 | 稳定数据 SHA-256 | Validation receipt SHA-256 | 状态 |
| --- | --- | --- | --- | --- |
| Requirement | `dc2036f9d5eeccb39921a23a057b6f920dae882e4b65e1a7fef14b757f6b2f8c` | Requirements `2aca1d03edf37f52f484d0652de3a68f0420bc12eaab90d4b91a66d880aad49b` | `30f10893e4b0d164c4939e902d9c7397783e6bbe967fe5d91981172cb7c29eb2` | 当前有效 |
| As-Is v1 | `3765252d4029ccd9668dea69ba1f0a6f175799ecb3fc8268a5ab717cf73760c3` | As-Is `b71ae50f1c5cde8182afa0d7bd9d45ebdba74deb5d41539ec7d58867c9008273` | `4fedd2422aa3c1b6c9bcdfad5733909b8bc54612409f9ca658e61f81bf49b9a4` | 已由 v2 取代 |
| As-Is v2 | `7155ca4fed788d9be009882b6f103d8531ac22cad9dbc051d3b93ac4c1d610d7` | As-Is `91e425b5b5ac9d99ca7f78dbff0064829e056f2e4a2243919fa9d0136cf78062` | `fe5c1bb62a59044971a5a776d178012bf5214f20ae98ab85e0251ea0aded33c6` | 当前有效 |
| Design v1 | `e01a6bbc7dcac8d249b90f07cdac69f5bd23a2034dbb42272714681a82db57df` | Design `46396f94a5d5512836c60e00bc6d2d089e743646c57cecb482b17ff358b5d0f3`；TECH requirements `1abbb417793c2e8a4fdbe83a24f9883dd2be138e1e2e559d8c116dcaea862e69` | `ec845c106a1bff9dc809da145e430d06cebfa5129e63fa677131647f10117574` | 已由 v2 取代 |
| Design v2 | `3769b4515c7015651c2678771765d9bf2eef4a8c8a51c9b6086fe658b84f64f1` | Design `adc9d270001e0ee418573b7b9563cc9d808b5822c831236068c0b87ed4837652`；TECH requirements `55caaa52c782e5755da15f8dca6fbcdbbd67ff2e4cf0232bec758333dda51325` | `01beab34f76f846006260f2100669f76a5dc23d2af8bc315b19722a1def21b19` | 当前有效 |
| Story | 无 | 无 | 无 | 阻塞，不得批准或进入 Task |

所有正式发布均使用用户精确批准的 packet SHA-256；快速路径只执行 approval sidecar 写入和 publish preflight，没有重新做专业分析或自动启动下游 Owner。

## 5. 多 Session 交接与首次用户观察

### 5.1 已验证有效的行为

1. Requirement、As-Is、Design 和 Story 的新 session 均能先验证上游 receipt，再生成最小 context；换 session 后没有依赖父聊天摘要恢复业务语义。
2. Design 首次阻塞时，系统没有让 Design Owner 修改 As-Is，而是收集 8 项事实并退回 As-Is Owner；更新后的稳定 As-Is 发布后再由新 Design session 重新闭合。
3. Story 首次发现真实 Feature overlap 后，系统正确退回 Design Owner；S4R3 保持 BUSINESS Feature 的 `END_TO_END` 所有权，同时把共享 TECHNICAL Feature 收敛为 `PORT_ONLY`。
4. 未通过 Reviewer 或用户批准的 candidate 均停留在 work 路径，没有污染稳定数据。
5. 用户批准均绑定完整 packet SHA-256；旧 packet、旧 receipt 或 candidate 字节变化不能被静默复用。

### 5.2 首次用户体验缺口

1. S5 在首轮机械 diagnostics 后错误地把可本地修复的问题当成终态，需要协调 session 再次强调“机械内循环直到 `REVIEW_REQUIRED`”。
2. S4R3 在工具输出截断后复读 `claims.json` 与 `source-anchors.json`，违反 fragment 各读取一次的上下文纪律。
3. work 目录会留下绑定旧 packet 的 approval/reviewer sidecar 或旧 `review-packet.json`。hash 门禁仍安全，但首次用户难以区分“文件存在”与“当前有效”。
4. Story Skill 禁止 Worker/Validator Agent，而共享降本合同又定义 Claim Verifier 路由；实际结果是 S5 的 66 claims 和 S5R2 的 37 claims 主要由 max Reviewer 整体承担。
5. S5R2 的字段级 patch 首次因 27 个引用闭包对象未显式处理而原子失败；公开合同没有给出 acknowledgement 字段格式，Owner 只能对闭包对象增加有业务意义的显式修改。
6. S5R2 最终摘要报告 41 AC，但磁盘 candidate 实际为 43 AC，产生用户可见的计数不一致。

## 6. generate-story 详细结果

### 6.1 S5：真实上游边界问题

S5 基于 Design v1 形成 21 Stories、59 AC、9 Integrations、9 Assumptions/Risks。Reviewer 在 66 claims 中返回 5 项 findings，其中一项为真实上游问题：

- `feature-address-validation-normalization` 和 `feature-address-change-email` 应独占外部提供方 `END_TO_END` 结果；
- `feature-technical-addresscheck-adapter` 和 `feature-technical-real-email-delivery` 不应再次拥有映射、重试、异常处置或 delivered 结果；
- 合法修复必须由 Design Owner 把两个共享技术边界改成 `PORT_ONLY`。

S4R3 完成并发布该修正，同时新增 `decision-addresscheck-port-boundary` 与 `decision-email-port-boundary`；HLD Coverage 与 Go-live Assessment 均为 `PASSED`。

### 6.2 S5R2：单次 patch 后候选仍阻塞

S5R2 在新 Design receipt 上从零重建，没有复用旧 Story candidate。首轮机械内循环在 Reviewer 前修复 16 项 candidate-local diagnostics，之后生成 packet：

- 初始 packet SHA-256：`1ecf1d40b41b81846c737ba32656bfd148de7597bfb18b0cb5468bb2faa5b237`
- Reviewer：37/37 claims 已深度核验，7 项 findings
- 当前 candidate SHA-256：`113e18277fa2c1185e2ae49f75184fe3332ec822c79f0170a12b593dab1b3817`
- 当前 review SHA-256：`a62f4ccd4e097d8b2f0c299059b73cf63d0f339a06171e497ca3c97c65e9ef17`
- 当前 risk summary SHA-256：`ffc46c99ec034266d7e2d00d5ac7bd148b9062ee5ced424a0e38a88b807e2f37`
- patch audit SHA-256：`971370e7876e7a1ef5968e22b64922202e98e2e510f7788d7ecb3fccf955afe0`

一次受控 patch 最终通过 `PATCH_FREEFORM_EDIT_DETECTED=0` 与 `PATCH_CLOSURE_UNSYNCED=0`，但重新渲染后的机械校验仍有两项失败：

1. `AC_GAP_RATIONALE_MISSING`：`ac-address-change-audit-query-retention` 必须明确 Coverage 为 `MISSING`，不存在有效的地址修改审计起点；邻接查询骨架不能作为基线。
2. `DECISION_FEATURE_MISMATCH`：`ac-technical-application-observability-alerts` 错误引用 `decision-addresscheck-threshold`，该 Decision 不关联其 TECHNICAL Feature。

当前磁盘 candidate 包含 20 Stories、43 AC、4 Integrations、6 Assumptions/Risks。唯一 patch round 已消费，因此按 Skill 合同没有启动 diff Reviewer；初始 packet 已与当前 candidate 脱绑，不能批准。

## 7. generate-story renderer 修复记录

### 7.1 缺陷

`generate-story` 评审模板要求 Integration 表逐行展示 `Delivery Boundary` 和 `Target Kind`。Schema 与 candidate 已保存 `deliveryBoundary`、`targetKind`，但 E2E 基线版本的 renderer 没有把这两个字段投影到 `review.candidate.md`，导致离线 Reviewer 无法直接核对：

- `END_TO_END` 与 `PORT_ONLY`；
- `PROVIDER`、`SYSTEM`、`ADAPTER` 与 `PORT`。

该问题由 S5R2 Judgment Reviewer 作为 `GST-JR-007` 报告。它不改变 Delivery 业务数据，但破坏评审模板的可审计性。

### 7.2 已提交修复

renderer 修复已提交到 marketplace `main`：

- Commit：`6962337b03c0e162a612272b25237dc28e3963ce`
- Subject：`fix(ai-sow): render story integration boundaries`
- 前一基线 commit：`6f778b6ffb6218b8a645fe5357458a189a8e2712`

该 commit 修改并同步记录以下文件：

- `plugins/ai-sow/skills/generate-story/scripts/render_review.py`
- `plugins/ai-sow/skills/generate-story/tests/test_validate.py`
- `plugins/ai-sow/README.md`
- `plugins/ai-sow/docs/AI_SOW_PLUGIN_DESIGN.md`
- `CHANGELOG.md`

实现改动：

1. Integration 表头增加 `Delivery Boundary` 与 `Target Kind`。
2. 每一行分别投影 `item.get("deliveryBoundary", "")` 与 `item.get("targetKind", "")`。
3. `NONE` 占位行同步扩展为 13 列，保持 Markdown 表格列数一致。
4. 新增回归测试 `test_integration_review_projection_includes_boundary_and_target_kind`，验证表头及 `END_TO_END / SYSTEM` 实际值。

最小回归验证：

```text
uv run --project plugins/ai-sow --locked pytest \
  -c plugins/ai-sow/pyproject.toml \
  plugins/ai-sow/skills/generate-story/tests/test_validate.py::test_integration_review_projection_includes_boundary_and_target_kind -q

1 passed in 0.10s
```

### 7.3 修复状态

| 检查项 | 状态 |
| --- | --- |
| 源码实现 | `COMMITTED`，commit `6962337b03c0e162a612272b25237dc28e3963ce` |
| 针对性回归测试 | `PASS` |
| generate-story 全测试 | `NOT_RUN` |
| 插件完整检查 | `NOT_RUN` |
| Git commit | `DONE` |
| 本地插件重新安装/cachebuster | `NOT_DONE` |
| S5R3 E2E 验证 | `NOT_RUN` |

因此 renderer 修复目前可以视为“源码已提交并通过最小测试”，但尚未经过本报告范围内的完整插件检查、开发安装或 S5R3 E2E 验收。原 E2E run 的固定基线仍是 `6f778b6`；恢复 S5R3 时必须把新 commit、tree 与插件内容指纹登记为新的执行基线，不能静默改写历史基线。

## 8. 性能与成本

### 8.1 累计结果

| 指标 | 目标 | 当前实际 | 结论 |
| --- | ---: | ---: | --- |
| Agent 墙钟，不含用户等待 | 90–120 分钟 | 225.8 分钟 | `FAIL`，为上限的 1.88 倍 |
| Gross total token | 1.4M–2.2M | 62,006,357 | `FAIL`，为上限的 28.18 倍 |
| Uncached input + output | 补充观察 | 3,510,613 | 即使排除 cached input 仍高于 2.2M |
| Reviewer agents | — | 18 个 | 6 Claim Verifier、8 Judgment Reviewer、4 diff Reviewer |
| Reviewer gross token | — | 18,016,168 | 占累计 gross token 约 29.1% |

### 8.2 Reviewer 路由结果

| Owner attempt | Deep review token | Deep review 墙钟 | Diff-review token | 对目标的判断 |
| --- | ---: | ---: | ---: | --- |
| Requirement S2 | 890,380 | — | 685,748 | deep 与 diff 均超标 |
| Requirement S2R2 | 1,342,239 | 10.54 分钟 | 211,820 | deep、墙钟、diff 均超标 |
| As-Is S3 | 2,547,372 | 13.59 分钟 | 372,166 | 全部超标 |
| As-Is S3R2 | 5,334,280 | 10.75 分钟 | 285,179 | 全部超标 |
| Design S4R2 | 926,152 | 7.11 分钟 | 0 | token 超标，墙钟达标 |
| Story S5 | 857,236 | 11.14 分钟 | 0 | token 与墙钟超标 |
| Design S4R3 | 1,073,939 | 8.14 分钟 | 0 | token 超标，墙钟达标 |
| Story S5R2 | 1,050,214 | 8.06 分钟 | 0 | token 超标，墙钟达标 |

`analyze-as-is` 的 11 Items 满足不高于 18 的目标，但 Evidence 从首版 40 增至更新版 65，超过不高于 25 的目标。正常调查本身只做了一次，但 S4 阻塞迫使 As-Is Owner 再运行一次更新评审。

性能超标的主要来源不是发布快速路径，而是：

1. Requirement 与 As-Is 的多轮完整 Reviewer 和高价 diff-review；
2. As-Is 更新时 65 条 Evidence 与大量 claims 进入深审；
3. Story 无法使用廉价 Claim Verifier 路由，全部 claims 进入 max Reviewer；
4. 上游事实与 Feature 边界在下游才被发现，导致 Owner 级回退和完整重跑；
5. cached context 携带量大，使 gross token 显著高于 uncached input + output。

## 9. 问题清单与优先级

| 优先级 | 问题 | 当前处置 |
| --- | --- | --- |
| P0 | renderer 缺少 Integration 边界/目标类型投影 | commit `6962337` 已修复且最小测试通过；待完整验证、重装和 S5R3。 |
| P0 | S5R2 patch 后仍有两项 candidate-local 机械失败 | 当前 packet 作废；只能在全新 Story Owner 中重建。 |
| P0 | 七阶段主流程未完成 | Story 发布前禁止启动 Task/SOW。 |
| P1 | Story Skill 与 Claim Verifier 路由存在执行冲突 | 需要统一合同：允许事实分片，或明确所有 Story claims 均由 Judgment Reviewer 处理并调整预算。 |
| P1 | Reviewer token 普遍超过 700k | 继续缩小 packet、claim、premise 与 Reviewer 输入；对缓存命中只抽检。 |
| P1 | patch closure acknowledgement 不可发现 | 在公开合同或 diagnostics 中给出 acknowledgement 结构，避免无意义字段改动。 |
| P1 | stale packet/sidecar 可见性误导 | 新 context/review 时原子归档或清理失效 work-only sidecar，并显示 stale 状态。 |
| P1 | Stage 摘要计数与磁盘 candidate 不一致 | 最终摘要应从确定性 validator 输出读取数量，不由模型手算。 |
| P2 | fragment 输出截断后发生复读 | context compiler 提供稳定的小型索引/claim query，避免整 fragment 重读。 |

## 10. 恢复执行建议

1. 保留当前 S5R2 作为失败证据，不覆盖其 candidate、review、risk summary、patch audit 和 ledger。
2. 对 renderer commit `6962337` 运行 generate-story 全测试及仓库要求的完整插件检查。
3. 通过插件开发安装/cachebuster 流程重新安装本地插件，并记录新 commit、tree 与插件内容指纹；不要继续沿用本报告的旧基线指纹。
4. 创建全新 S5R3 Story Owner。它必须重新运行 `prepare_context.py`，不得复用 S5/S5R2 candidate 或 packet。
5. 把本轮两项机械 blocker 作为已知质量检查：
   - `MISSING` Coverage 的 AC 必须明确不存在有效起点；
   - Decision 只能引用 `relatedFeatureIds` 包含当前 Story Feature 的 typed decision。
6. S5R3 必须重新达到 `REVIEW_REQUIRED`、完成 fresh Reviewer、生成新的 packet，并等待新的精确用户批准。
7. Delivery 正式发布后，才继续 `generate-task`、人员/迭代计划、`generate-sow`、最终 TL/BA/PM 复核和确定性 `REUSED` 复验。

## 11. 权威记录

- 测试计划：`../../e2e-test-plan-v2.md`
- Run manifest：`run-manifest.json`
- Session ledger：`metrics/session-ledger.jsonl`
- 首次用户观察：`observations/first-user.md`
- Session handoff：`observations/handoffs.md`
- S5R2 candidate：`.ai-sow/work/generate-story/delivery.candidate.json`
- S5R2 review：`.ai-sow/work/generate-story/review.candidate.md`
- S5R2 patch audit：`.ai-sow/work/generate-story/patch-audit.json`

本报告只汇总当前权威状态，不把 work-only candidate 或尚未安装、尚未经过 S5R3 的 renderer commit 表述为 E2E 已验收结果。
