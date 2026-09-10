---
name: generate
description: 当用户要根据 PRD、HLD 和旧项目的往期 SOW 生成本期首版 SOW 工作簿，或续接尚未完成的首次生成时使用。
---

# 生成本期 SOW

一个主 session 从输入形成 Epic → Feature → Story（AC / Task），交付可直接 review 的 Excel。Agent 负责语义判断；工具负责读取、引用检查、模板投影和版本保存。初稿无需审批或定稿，不启动 subagent、模型 SDK 或自行选择模型。

## 1. 接收输入

复用用户已给信息，只核对新/旧项目和必要材料：PRD、HLD；旧项目另需往期 SOW；目录原型可选。非原型材料支持可读 UTF-8 文本和 XLSX。缺必需材料时列具体缺件，保存接收结论并结束本次推进；Epic/Feature 草稿或 tech note 不能替代。

资料齐备后，从当前已加载的 `skills/generate/SKILL.md` 定位包含 `scripts/lite.py` 的本插件根目录，按 [启动与登记](../../references/generate-authoring.md#启动与请求身份) 准备本插件隔离环境。项目使用用户目录。一个逻辑请求沿用一个 request_id；已有请求先查看 current/checkpoint，恢复其结果及已耗次数。已有有效 SOW 的修改转用 clarify。

## 2. 分析并澄清输入

读取 [输入分析](../../references/input-analysis.md)，登记原件后覆盖业务、技术/NFR、交付义务，形成有来源的 to-be、稀疏 as-is 和本期 gap。目录原型出现时才读 [原型输入](../../references/prototype-inputs.md)。

在 work 保存分析、输入 review 和问题去向。只有影响目标、基础方案或责任的输入问题才合批询问；基础充分后的局部未知随稿待确认。按输入参考的有限次数处理实际答复，基础仍不足则列补料清单退出。

完成条件：每个本期义务有依据或明确缺口；材料提及但未取得的验收规则已按实际影响记录，不能当作已明确的约定。

## 3. 骨架与片内生成

读取 [联合生成](../../references/generate-slices.md)。从有效 gap 按目标、责任及公共建设/消费关系形成骨架和片索引；顺序处理有关联的有限片，每片联合形成 Story、简明 AC、Task、分类和待确认。

标准按片合批读取并复用。复杂度不明立即 M+待确认；相关历史实例不明按新建+具体问题。骨架、片索引和跨片暂存关系留 work，文件形状见 [候选编写](../../references/generate-authoring.md#工作索引候选和准确绑定)。下一片只带必要引用和摘要。

完成条件：本片义务已有成果或具体缺口，规则缺口绑定实际 Story/AC，公共建设与消费工作不重复计量；slice 检查通过。

## 4. 合并与交付

做一次语义整合，核对义务覆盖、公共归属、跨片关系和输入问题去向，只修实际冲突范围，形成完整候选。只有有据确认全部本期 gap 为空才交付空范围结论。

按 [有效交付](../../references/generate-authoring.md#有效交付) 执行 full check → render → apply。模板独占人天、金额、公式及 SIT/UAT 计算；业务内容通过模型投影，不直接修改正式 Excel/current。机械失败保留候选和实际诊断，沿 [有界返修和恢复](../../references/generate-slices.md#有界返修和恢复) 退出或窄修。

成功返回有效版本、Excel、摘要与关键未决事项，不在聊天重复整份 SOW；未生效则说明具体保留位置和原因。

## 执行约定

- 参考按当前阶段/操作读取，不一次展开目录或全部工具合同。连续机械调用用 [Python 助手](../../references/python-client.md)，只输出必要结果及引用。
- 在开始工作时加载 [检查点与活动观察](../../references/generate-authoring.md#检查点与活动观察)，实际记录处理、等待和交付边界；资源未知如实保留，观测失败不重做业务。
- 续接保存活动、候选与已耗次数；换片、压缩或重启不刷新额度，计数不可恢复时停止。
- 用户说明及业务自由文本用简体中文，机器字段与标准名保持原值；客户资料及衍生文件留项目内。
