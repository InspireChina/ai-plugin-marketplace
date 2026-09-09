# 基线 BOM 兼容夹具

这些 inputs 文件由 `dd1e5b3` 的真实 Lite 公共 CLI `ingest/sources` 生成，原样保存。材料是合成 `legacy-bom.md`，内容为 UTF-8 BOM、`# PRD`、`Query orders.`，使用 CRLF。

开发生成时，临时副本的 inputs.py、validation.py、artifacts.schema.json、protocol.schema.json 使用该提交的精确字节，脚本、模板与未变运行时沿用同一基线。执行成功后仅保留 inputs，未保存原始请求、绝对路径、遥测或其他环境输出。临时副本已清理。

原登记 encoding 为 `utf-8`，reading adapter_version 为 `lite-text-v1`，原件与摘录均包含 BOM。测试把这些真实登记字节放入隔离项目，再经当前 CLI 重用、查询及登记来源依据，要求旧摘要和读取含义保持有效。测试不加载旧运行时、不访问 Git，也不对旧数据实施迁移；新登记的 `utf-8-sig` 行为由另一个用例分别验证。
