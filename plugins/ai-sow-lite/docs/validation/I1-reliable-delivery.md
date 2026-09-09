# I1 可靠程序交付验证

I1.1 已完成实现、TDD 回归及独立审阅收口。I1 整体尚未完成，I1.2 输入登记/版本保存、I1.3 Excel 投影、I1.4 埋点运行时、I1.5 完整副本交付均未实现。

## 已实现与证据

以设计提交 `311fee2` 为起点，在当前分支新增 Lite 自有隔离环境、6份 JSON Schema、严格 JSON/摘要、只读候选校验和 `scripts/lite.py --request`。校验器负责真实来源/标准身份、分类和问题一致性、引用闭合、历史去向及路径边界；不会拆解业务、改专业字段或计算金额。

只有 check/candidate 可执行。ingest/inspect/render/apply/recover、check/edits 和计划检查明确返回 OPERATION_UNSUPPORTED。contract_case 是直接准备的真实字节单元夹具；未伪造 ingest 成功、current 或 Excel 交付。当前接口见 [工具合同](../../references/tools.md)。

| 验证 | 实际结果 |
|---|---|
| 测试先行 | 真实 fixture 准备后，核心实现不存在时63项失败、1跳过，无 fixture/收集错误；后续路径别名、显式 locator、内容摘要等修复分别保留失败再通过的证据 |
| 锁定依赖 | uv lock、uv sync --locked、uv lock --check 通过；Python3.12.13、jsonschema4.26.0、openpyxl3.1.5、pytest8.4.1 |
| Lite 全量 | 首轮95 passed、1 skipped；审阅返修后144 passed、1 skipped；唯一跳过为缺少 pwsh，未宣称 Windows 执行通过 |
| 隔离环境 | Bash 自举在含空格/中文路径的临时 Lite 副本真实重建并复用 .venv，实际转发 UTF-8 请求；从不同 cwd 调用不依赖仓库环境 |
| 平台与编码 | macOS26.5.2 arm64 实测，Bash 无 BOM、PowerShell UTF-8 BOM；路径样例283字符/387 UTF-8字节，不作为平台最大长度或 Windows 支持承诺 |
| 原模板 | assets SHA-256 保持 `6abc55d44bc66476a60c2251e18c0dfdb66709e07539c246dfdec3a0373f5332`；既有模板测试原字节不变，包含原 LibreOffice 回归 |
| 真实 Agent 候选 | 两轮生成后以独立运行时副本实际调用 check CLI，通过、1项 open、无业务改写；见下方探针记录 |
| 已保存样本复现 | 将下方合成样本复制到另一临时项目，补原模板，再用独立运行时副本校验：通过、1项 open，14份已有文件原字节不变、未创建 current |
| 仓库边界 | 根42项测试、仓库验证器、旧插件独立副本 smoke 通过；I1.1 初测曾有2项旧架构断言失败，后续专项修复后旧插件全目录539 passed、4 skipped |

复核命令：

```text
uv sync --project plugins/ai-sow-lite --locked
uv run --project plugins/ai-sow-lite --locked pytest plugins/ai-sow-lite/tests -q
sh -n plugins/ai-sow-lite/scripts/bootstrap.sh
```

严格摘要向量 `{"a":[1,true,null],"z":"中文"}` 对应 `json-v1:db6a0f2ebe94b34e63a8bbcc767de7852280476696e69e1152bdbb07a6f3cf32`；保留业务字符串空白、数组顺序和精确整数。运行时不接受外部 Schema 取回或复制旧领域规则。

旧插件全目录曾有两项既有失败：`test_runtime_is_plugin_shared_owner_agnostic_infrastructure` 的精确文件清单未包含已有 findings.py；`test_all_professional_owners_freeze_owner_local_candidate_first_interface` 的指定文字断言未匹配已有 generate-task 指引。I1.1 提交后按用户要求专项修复了过期清单与措辞断言，保留 Owner 边界、页序、已读页不重复读取和截断恢复检查；旧插件运行时与 Skill 原字节未改。先复现2 failed，再验证架构12 passed、全目录539 passed/4 skipped，根42项、仓库验证器与独立副本 smoke 均通过。

## 独立审阅与定点返修

独立审阅确认了6项机械反例：历史条目的实例依据/父链、重复主题版本、覆盖记录与输入集合矛盾、逆向历史替换链、尾随换行的 UUID，以及无关 Schema 错误遮蔽分类诊断。已逐项补失败与通过样例并修复。独立复核核对原反例、合法情形及最终文件身份后，Spec 和 Quality 均通过，6项问题均关闭；I1.1 已勾选完成。

测试先按合同定义预期，再运行旧实现观察失败，随后修复并回归。下表的失败数是各组新增反例在修复前的实际结果，不是人为注入 fail 标志；对应测试位于 [test_contracts.py](../../tests/test_contracts.py)。

| 预期来源 | 新增反例 | 修复前证据 |
|---|---|---|
| [D02](../design/detailed/D02-shared-data-and-evidence.md) 历史实例依据与显式父引用闭合 | 嵌套依据缺失、父项缺失、重复身份、父链循环；另有合法稀疏历史 | 4 failed、1 passed |
| D02 稳定主题版本身份 | 同一主题版本重复或冲突，保留合法共享情形 | 4 failed、1 passed |
| [D03](../design/detailed/D03-input-analysis-and-exploration.md) 输入与覆盖记录一致 | 未登记来源、非法定位顺序、主题输入与覆盖不符；保留合法未读区域 | 5 failed、1 passed |
| D02 历史替换去向与版本定位 | 逆向或缺乏后续关系的替换链；保留合法链与有据删除 | 4 failed、2 passed |
| [P00](../design/implementation/P00-contracts-and-fixtures.md) UUID/摘要精确编码 | 六份 Schema 与实际候选的尾随换行身份 | 7 failed |
| [I1.1](../design/implementation/P01-reliable-delivery.md) 按实际依赖合批诊断 | 无关文件格式错误遮蔽分类等诊断，非法文件不能冒充空集合 | 8 failed、2 passed |

修复后合同测试127项通过，聚焦环境/合同135项通过、1跳过，全量144项通过、1跳过。这证明已列机械预期与反例在当前实现上成立，不代表自然语言义务全部覆盖。真实 Agent 探针的专业缺口仍单独记录在 I2，不能以程序测试通过关闭。

另有同一 Schema 文件内重复定义的非阻断维护建议，已使用现有 $defs/$ref 做局部去重。重构前9项行为保护测试通过，重构后相关23项通过，再纳入全量测试；这些原本通过的保护测试不冒称 Red。没有引入生成框架或业务阶段。

## 前置探针与后续工作

[Generate 验证](I2-generate.md) 保留真实三类义务、默认 M、输入问答、可见约束及关系导航限制；[宿主验证](host-support.md) 保留生产者版本、真实 response/turn 计数、耗时与归属未知。原字节 [合成候选](samples/three-scope/README.md) 可用于复核。探针没有安装 Skill、调用模型 SDK 或修改宿主配置，不能替代 I2 端到端验收。

下一实施任务为 I1.2。先把直接合同夹具接到真正的输入登记及可靠文件保存；继续保留 Agent 专业自由、有限修改、原模板计算和诚实观测边界。
