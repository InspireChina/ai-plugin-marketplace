# Reviewer 输出

只返回 `contracts/next/review-repair.schema.json#/$defs/reviewResult` 接受的 JSON。所有 hash、review set、run、kind、coverage union 和检查 ID 必须与 packet 精确一致。

finding 必须包含稳定 `findingId`、分类 `type`、最早修复 `owner`、精确 `subjectIds/evidenceIds` 与简洁 `summary`。PASS 的 `findings` 必须为空；非 PASS 必须至少有一条与 decision 一致的 finding。
