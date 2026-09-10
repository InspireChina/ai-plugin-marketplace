# Clarify 语义验收输入

每例的 `feedback.md` 是新会话能看到的用户原话；已有项目来自真实 I1 交付，包含已采用输入与有效版本。被测者只能读取插件运行面、该项目和反馈，不读取原 generate 聊天、本目录中的期待或测试支持代码。

`expectations.json` 留在评估侧。评估者先核对实际展示的具体方案，才发送真实确认；不能预先把“用户已确认”写入项目。未确认时比较 current 和全部旧版字节，确认后比较实际差异与未涉及对象。记录具体文件和 hash；案例存在不代表通过。

`answer-complexity-S` 与 `answer-complexity-M` 复用包含迁移复杂度默认 M 待确认项的真实交付副本。后者首次采用形成问题/依据/决定的新版本，之后已采用的相同答复才是无变化。

`correct-source-reading` 使用测试明确植入误读、再由真实 I1 通道生成的错误基线：PRD 仍明确迟到响应不覆盖新查询，已交付 AC 被误写为覆盖。结构合法不代表业务正确；本例验证局部语义修正，不将故障归咎于原始生成。

候选悬空引用使用 I3.1 机械故障测试；不向真实语义会话泄露答案或额外制造一场无意义的 ID 讨论。

## I4 复杂变化

`shared-periodic-production/feedback.md`在同一真实I1交付基线提出A/B/C三组；方案形成后才给实际选择，不预制业务补丁。

`independent-sync/prd.md`和`hld.md`先用于真实Generate；`feedback.md`只在首版交付后提供给Clarify。初版执行者不提前读取后续意见；现版实时集成与新增独立周期同步分别判断。

实际专业结果、失败和未覆盖面见包内docs/archive/validation/I4-inputs-and-changes.md；这些输入的存在不证明语义通过。
