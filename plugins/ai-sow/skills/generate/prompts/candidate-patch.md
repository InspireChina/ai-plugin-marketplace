# 当前候选的受限增量修复

使用 `FRESH_NO_HISTORY`。只处理 packet 中当前原子组的 issues 与 slots，依据本组冻结证据形成业务判断。
返回 `PatchResult`：`repairPlanSha256`、`baseCandidateSha256`、`groupId`、`operations`。
每个 operation 只提供已发行的 `slotId` 与适用的 `value`；删除操作不提供 value。A patch must include every non-alternative slot and exactly one slot from each alternative set.
不返回完整候选、未授权集合、旧对象替代值、新权限或通过证明。未返回部分由程序原样继承。
引用值必须在槽位授权内，不能用已有证据替代缺失证据。读取不足时只 hydrate 本组给出的精确引用。
语义证据不足时报告真实缺口，不编造答案，不自行扩大槽位。只有 Reviewer 责任的 Action 可以修复 Review 格式，仍须独立判断全部当前评审义务。
原失败、已成功组和累计预算保持有效；槽位不能满足问题时说明具体原因，不能重写其它对象规避。
