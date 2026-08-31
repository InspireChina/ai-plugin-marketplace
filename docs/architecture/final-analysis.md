# AI SOW 多 Session 新版本 E2E 最终分析

## 1. 总结论

本轮 E2E 功能结果通过，性能结果失败。

七阶段主线从 clean project 完成到可复用的确定性 SOW 包；多人、多 session 交接成立，所有 Owner
都能仅凭项目内稳定数据、批准评审和 receipt 恢复上下文，没有依赖前一位 Agent 的聊天摘要。五位
Owner 的正式数据都经过 fresh-context Reviewer、精确 packet 批准和原字节发布，没有发生下游
越权修改上游稳定数据或未批准内容静默进入交付包。

但流程成本远超目标。可审计 session ledger 的最终累计为 78,455,416 gross token、4,607,352
uncached input + output token 和 17,194,924ms Agent 墙钟（286.6 分钟）；未重复计入协调任务等待
时间。协调任务自身截至最终归档前的可见计量另有 23,150,693 gross token、848,613 uncached
input + output。因此全流程已观测模型成本下限为 101,606,109 gross token 和 5,455,965 uncached
input + output；最终归档与答复产生的少量后续 token 不在该下限内。

## 2. 最终结果正确性

### 结构化交付

- Requirement、As-Is、Design、TECHNICAL requirements、Delivery、Estimate 六份稳定 JSON 均存在。
- 五份 Owner validation receipt 均为 `ai-sow-owner-v1`、validator contract `0.3` 且 `passed=true`。
- 稳定 JSON 与各自获批 candidate 原字节一致；正式 review 与获批 review candidate 原字节一致。
- 最终 Delivery 含 20 Stories、58 AC、4 Integrations、8 Assumptions/Risks。
- 最终 Estimate 含 25 Tasks，覆盖全部 20 Stories、58 AC 和 4 Integrations；Task ID 唯一。
- 工作模式为新建 23、调整 2、接入复用 0；两个调整任务均绑定精确 Effective Start。
- 复杂度 S/M/L 为 3/19/3；每个顶级 Integration 恰好映射一个 Task。
- 结构化 Estimate 不保存人天、倍率、SIT/UAT、风险、公式、取整或 quantity，计算权威仍在模板。

### 最终包与 XLSX

- 最终 package ID：`sow-sha256-8974dda457001a6e64a1b57f4eda7332f4f5f168e3d8380268c03c8aff3d97f7`。
- Workbook SHA-256：`40b8def37d8036ef3fc60edb23a772a7b5334b1b6335bfaf4357d46dbfb6f396`。
- Package tree SHA-256：`248463a57d749d21537c52676fded3e04ab782538528aa5580d1bc690cfbca63`；19 个文件。
- 新 session 首次生成返回 `CREATED`，另一新 session 返回 `REUSED`；复用前后包树、上游数据、
  review、receipt 与模板 hash 全部一致。
- 12/12 Sheet 独立渲染和人工检查通过；长文本检查 `clipped_rows=0`。
- 公式错误单元格匹配为 0；无 `_xlfn._xlws.`、`#REF!`、`#DIV/0!`；40 个 CSE 数组公式和 5 张
  受保护业务表保持正确。
- `20-项目汇总` 显示直接开发 53.5、SIT 3.0、UAT 1.0、待确认风险 0.0，最终开发交付估算
  57.5 人天。

技术包可离线评审和审计。商业签署就绪仍未证明：模板参数、商业条款、计费规则、签署信息、人员和
迭代计划没有结构化 PM readiness receipt，57.5 人天也明确排除非开发角色。

## 3. 多 session 与首次用户体验

交接机制本身是本轮最稳健的部分：

1. setup 冷启动自动建立插件隔离运行时，新用户不需要预装 Python、uv 或依赖。
2. 每个下游 Owner 都通过固定 receipt 恢复上游，不依赖聊天记忆。
3. 上游事实或边界错误只能退回唯一 Owner 修正；Story、Task 没有反向改写 Requirement、As-Is 或
   Design。
4. 用户批准绑定精确 packet SHA-256；批准后的快速路径只写 approval 和正式发布，不重跑专业判断。
5. 插件升级后 remove/add 重装、`.venv` 重建和项目只读复核都能恢复，新的 session 能使用新缓存。

首次用户的主要困难不是“不知道下一步”，而是工作目录中 stale packet/sidecar 可见、上下文输出
截断恢复规则不清、机械 diagnostics 暴露内部修复合同，以及一次完整阶段失败后必须从新 session
重建大上下文。这些问题会显著增加认知成本，即使最终安全门禁仍然有效。

## 4. 返工轨迹

专业 Owner 共 12 次 attempt，其中 5 次以 `BLOCKED*` 结束；另有 Requirement 初次问卷是预期的人类
决策停止点。五个失败 attempt 直接消耗 25,261,987 gross token，占 instrumented 总量 32.2%。

| 返工点 | 直接原因 | 根因层级 | 结果 |
| --- | --- | --- | --- |
| S2 → S2R2 Requirement | patch 后来源理由与 candidate 字节链仍不闭合 | patch 事务与来源处置 preflight 不完整 | 新 session 重建并批准发布 |
| S4 → S3R2 As-Is | 8 项 `affectsEstimate` 不确定性使 Design 无法估算 | As-Is 缺少下游 Design-readiness gate | 补充 8 项事实并重新批准 |
| S5 → S4R3 Design | BUSINESS 与共享 TECHNICAL Feature 重复拥有 `END_TO_END` | Design 只验单对象，未验成对边界所有权 | TECHNICAL 收敛为 `PORT_ONLY` |
| S5R2 Story | Reviewer patch 后仍有两项机械错误；Integration review 漏列 | patch 未先做 post-check；renderer 与模板字段合同漂移 | commit `6962337` 修复 renderer |
| S5R3 Story | 新 AC 被扩成 94 个 sync suspects，原子拒绝误算 patch 已消费 | closure 穿过外部 ID，retry 合同不明确 | commit `717165d` 修复闭包与重试 |
| S6 Task | 22 Tasks 经 Reviewer 修为 25，存在重复 API 计价、模式和性能边界问题 | 可机械判定的 Task 语义仍留给深审 | patch 后覆盖完整、diff Reviewer PASS |
| S8 XLSX | 62 行长文本被固定 prototype 行高裁切 | 动态表只复制固定高度，公式列缺少布局提示 | commit `ec35900` 修复并重跑 |
| S8 package identity | 修复生成器会让不同工作簿碰撞旧 package ID | 指纹包含固定 `receipt-only-v1`，但投影变更未升级 | 提升为 `receipt-only-v2` 并同步 reconcile |

本轮共在 `main` 产生并推送三次插件修复：`6962337`、`717165d`、`ec35900`。每次均运行完整根测试、
仓库验证、插件 pytest 和独立复制 smoke，再刷新 Git marketplace 与本地插件缓存。

## 5. 返工原因归纳

### 5.1 上游 readiness 不足

As-Is 到 Design、Design 到 Story、Story 到 Task 的“下游可启动条件”没有在上游批准前完整机械化。
因此估算事实、唯一交付边界和可估算任务语义只能由下一阶段用高成本 Reviewer 才发现。Owner 回退
方向是正确的，但发现时点太晚。

### 5.2 patch 是安全的，但不是低成本事务

hash-bound patch 能避免静默修改，但本轮多次出现“修复已应用，post-check 才失败”或“原子拒绝被
误解为额度耗尽”。一次 patch 应被定义为 candidate、review projection、机械 post-check 和 diff
packet 的整体事务；只有事务成功才消费修复额度。

### 5.3 renderer/生成器缺少展示层验收

Schema、稳定 JSON 和 receipt 全部正确，仍可能出现离线 review 漏列或 XLSX 长文本裁切。前者需要
renderer 字段覆盖契约，后者需要真实长文本 fixture 与 render-and-inspect 门禁。仅靠 openpyxl 结构
复读无法证明用户可见布局正确。

### 5.4 上下文与 Reviewer 过大

22 个 Reviewer Agent 共消耗 23,004,873 gross token，占 instrumented 总量 29.3%；其中 11 个 Judgment
Reviewer 为 18,766,890 token。fragment 聚合输出多次超过宿主上限；即使命中缓存，gross 上下文、
延迟和 Reviewer 认知负担仍未下降。

### 5.5 Agent 容易自行增加“安全但冗余”的检查

最终 `REUSED` session 的生成命令只耗时 0.52 秒，但 Agent 自行增加前置枚举、全量 hash 基线和后置
复核，使 session 达到 128.2 秒、289,003 gross token。生成器已经内建 receipt matcher、工作簿复读、
manifest 与包树验证；这些额外命令没有增加实质正确性，只增加耗时和输出截断风险。

## 6. 用时与 token

| 指标 | 目标 | Instrumented session | 判断 |
| --- | ---: | ---: | --- |
| Agent 墙钟 | 90–120 分钟 | 286.6 分钟 | FAIL，超过上限 2.39 倍 |
| Gross token | 1.4M–2.2M | 78.46M | FAIL，超过上限 35.7 倍 |
| Uncached input + output | 补充指标 | 4.61M | 仍为目标上限 2.09 倍 |
| Reviewer gross | ≤700K/深审；≤30K/diff | 合计 23.00M | 多数阶段超标 |
| 失败 Owner attempt gross | — | 25.26M | 占 32.2% |

协调任务 token 单列后，全流程已观测总量下限为 101.61M gross、5.46M uncached input + output。gross
与 uncached 相差约 18.6 倍，说明最大成本是长上下文反复携带；缓存降低新增输入量，但没有降低窗口、
延迟和 gross 指标。

确定性脚本本身并不慢：最终 generate-sow `CREATED` 命令约 0.34 秒，`REUSED` 约 0.52 秒。主要耗时
来自专业候选生成、完整 Reviewer、返工重跑、上下文传输和 Agent 自行扩展的只读验证。

## 7. 优化建议

### P0：消除整阶段返工

1. 在 As-Is 批准前生成 Design-readiness；所有 `affectsEstimate` 项必须有 owner、答案、证据和关闭条件。
2. 在 Design 批准前机械生成 BUSINESS/TECHNICAL Feature boundary pair matrix，同一外部结果只能有
   一个 `END_TO_END` Owner。
3. 在 Story 批准前增加 Task-readiness lint：结果所有权、性能阈值、固定上线支持边界和 Effective
   Start 推荐映射。
4. 把 patch 变为原子事务；拒绝或 closure acknowledgement retry 不消费成功修复轮次。
5. 新 packet 原子归档旧 packet/reviewer/approval，或维护唯一 `CURRENT` 状态摘要。

### P1：压缩 Reviewer 上下文

1. context compiler 按固定 byte/token 上限分页；manifest 记录顺序、hash 和预算，合同改为“每个分片
   一次读取”。
2. 工具明确返回 truncated recovery 协议；截断不计作已读取，可按相同 manifest 分页恢复。
3. `prepare_context` 分离输入上下文与 review claims，避免 candidate 尚不存在时固定生成空 claims。
4. FACTUAL/结构 claim 交给机械 validator 或低成本 verifier；Judgment Reviewer 只看真实判断字段。
5. diff packet 只含 changed path、直接引用闭包和受影响验收映射，并设置硬输入预算。

### P1：把展示层纳入发布认证

1. renderer 模板列与 Schema 字段做自动覆盖测试。
2. 工作簿测试加入真实长文本 fixture、公式可见文本布局提示和 12-Sheet 渲染抽查。
3. 任何会改变工作簿确定性字节的投影变更必须提升 generator contract；测试同时验证 reconcile 使用
   相同合同。
4. generate-sow 成功结果直接返回 workbook SHA、manifest SHA、package tree SHA 和文件数，避免
   Agent 再做全量 hash 前后检。

### P2：补齐 PM readiness

增加独立结构化 receipt，绑定模板参数、商业条款、计费规则、人员/迭代计划责任、签署状态和模板
hash；明确区分“技术包生成成功”“估算可评审”“商业可签署”三个状态。

## 8. 最终判断

当前版本证明了 AI SOW 的治理模型可以在多人、多 session、插件中途升级和真实返工下保持数据所有权、
批准链和不可变交付包安全；结果正确性是可信的。它还没有达到高效生产流程：主要瓶颈是迟到的
readiness 发现、全阶段重跑和 Reviewer/上下文规模，而不是确定性脚本执行。

建议以本轮三个插件缺陷和五个失败 Owner attempt 作为下一版回归基线，优先完成 P0 readiness 与
patch 事务化，再重新跑同一场景。若只优化模型或降低 reasoning effort，而不改变上述流程结构，
token 和墙钟不会接近目标。
