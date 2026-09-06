# 工作簿最终视觉评审

逐一打开 packet 中绑定的最终 XLSX 和全部可见 Sheet 的 PDF render，按 packet 的稳定 Sheet 顺序检查。
必须实际查看每份 render 的全部内容，包括长表末尾及汇总表追溯区；只读文本或文件名不足以证明通过。
逐 Sheet 判断 clipping（裁切）、readability（可读性）、unexpectedBlank（意外空白）、styleLoss（样式丢失）。
仅返回 VisualReviewDecisionIR：sheets 的顺序和 sheetKey 必须与 packet 一致，每项包含 checks、decision 和 findings，最后给出 overallDecision。
所有 checks 均通过且无 findings 才能给出该 Sheet PASS；所有 Sheet PASS 才能 overallDecision PASS。
若任何文件无法实际查看，返回 FAIL 并准确描述缺口，不得推测或代填 PASS。禁止修改工作簿或提交 run/file/hash。
