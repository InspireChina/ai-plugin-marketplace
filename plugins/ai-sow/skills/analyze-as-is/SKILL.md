---
name: analyze-as-is
description: 当 AI SOW 在方案设计前需要独立调查代码、集成、数据、配置、部署、证据、往期承诺或有效起点时使用。
---

# 分析现状

先形成证据完整的人类可读评审，再编译稳定 As-Is 数据。没有代码库或往期 SOW 是合法情况；调查仍需明确覆盖边界和未知项。

执行前读取并遵守[输出语言合同](../../references/output-language.md)。中文用于结论、问卷、证据摘要和评审；合同 token 保持原值。

## 路径

将包含当前 `SKILL.md` 的目录解析为 `<skill-root>`，将其上两级目录解析为 `<plugin-root>`。保持项目根目录为当前工作目录，并在执行前把命令中的路径占位符替换为绝对路径。

## 工作流

1. **登记调查输入。** 读取四字段 `.ai-sow/project.json`。询问本次调查可用的本地代码库、往期 SOW、配置、部署材料和其他证据；仅登记用户提供或明确授权取得的输入。代码库记录稳定 `repoId`、项目相对路径、revision 与 dirty 状态；往期 SOW 复制到 `.ai-sow/inputs/analyze-as-is/prior-sows/` 并记录稳定 ID、原文件名和 SHA-256。根据证据确定 `GREENFIELD` 或 `BROWNFIELD`，写入 As-Is `analysisScope`，不回写项目元数据。
2. **固定覆盖范围。** 按顺序评估 `SYSTEM_CONTEXT`、`CAPABILITY`、`APPLICATION`、`INTEGRATION`、`DATA`、`PLATFORM`、`SECURITY_COMPLIANCE`、`OPERATIONS_QUALITY`、`DELIVERY_CONSTRAINTS`。每个 Topic 恰有一个 `ASSESSED`、`NOT_APPLICABLE` 或 `INSUFFICIENT_EVIDENCE`；最后一种状态至少关联一个 Uncertainty。
3. **静态调查优先。** 对每个代码库读取[CodeGraph 参考](references/codegraph.md)，严格按 MCP → 已有 CLI → 项目局部 CLI 安装和索引 → 已记录静态回退的顺序取证。CodeGraph 成功可用时先使用图查询；动态分派、生成代码、配置、部署和运行边界必须由直接证据佐证，或记录 Uncertainty。
4. **核对承诺与有效起点。** 从每份往期 SOW 逐项提取 Commitment，核对 `implementationStatus` 和 `treatment`。只有当前 Item 与 `EXPECTED_BEFORE_START` Commitment 可组成 Effective Start；`CARRY_FORWARD` 是待交付范围，不是现有能力。
5. **覆盖业务 Feature。** 为每个 BUSINESS Feature 建立一条 Coverage，连接有效起点、承诺、证据和缺口。没有对应现状时使用 `MISSING`，不编造事实。
6. **按需进行定向验证。** 默认不启动应用、数据库或容器。仅当静态证据无法解决会实质影响设计的重要不确定性，且最小定向运行能回答该问题时，读取[运行时验证参考](references/runtime-verification.md)，先说明原因，再执行目标仓库已有的最小测试或探针。
7. **询问剩余缺口。** 完成直接调查后，才读取[现状证据问卷](references/current-state-questionnaire.md)并生成 `.ai-sow/work/analyze-as-is/questionnaire.md`。确认回答可形成 `QUESTIONNAIRE` Evidence；空白、未知或冲突回答形成 Uncertainty。每条 Uncertainty 必须显式填写 `affectsEstimate`：只要答案可能改变范围、责任、设计、交付对象、工作量或人天就为 `true`；只有确认不影响正式估算时才可为 `false`。
8. **评审并编译。** 将范围、九个 Topic、承诺核对、Effective Start、Feature Coverage、Uncertainty、CodeGraph/运行验证记录和 Evidence 索引写入 `.ai-sow/reviews/analyze-as-is.md`。获得用户批准后编译 `.ai-sow/data/analyze-as-is/asis.json`，再运行：

   ```text
   uv run --project "<plugin-root>" --locked python "<skill-root>/scripts/validate.py" --project-root .
   ```

## 完成条件

九个 Topic、每份已登记输入和每个 BUSINESS Feature 均已处理；每条结论有项目相对 Evidence anchor 或明确 Uncertainty；validator 以 exit code 0 结束。稳定数据不包含源码、完整工具输出、凭据、绝对路径或工具安装文件，也不修改上游来源与其他 Skill 的文件。
