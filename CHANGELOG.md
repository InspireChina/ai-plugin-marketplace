# 变更日志

所有重要的用户可见变更都记录在此。

## 未发布

### AI SOW Lite

- **Windows 平台修复：** 项目相对引用统一为 POSIX 分隔符，修复 Windows 上 generate/clarify 因自身安全检查被拒（PATH_UNSAFE）；LibreOffice 私有 profile 移出项目树，避免深路径下引擎崩溃；复读接受整表一致的平台列宽换算与已验证的字体回退，单列变化或不一致缩放仍判为篡改；引擎发现支持 Windows 控制台入口 soffice.com 与默认安装目录。
- **引导：** uv 改为直接下载锁定版本压缩包并用 .NET ZipFile 解压，不再依赖 Get-ExecutionPolicy；bootstrap.sh 在 Windows shell 下直接指向 bootstrap.ps1。
- **可恢复性：** analysis 登记先绑定来源再写主题记录，索引一次性提交；索引丢失时仅由写入操作在逐字节重证出处后重建，查询保持只读。期望观察集合完全由不可变登记独立推导，不取用待验证记录自身的 observations，删除观察的记录不能再取得新索引。
- **存储：** Windows 上 os.replace 遇到瞬时文件锁时有界重试，消除偶发 INPUT_UNAVAILABLE。
- **来源隔离与验证：** 无关观察登记中断或损坏不再阻断健康主题；所需观察缺失仍拒绝。复制审计移除 POSIX 专用常量假设，验证工具统一 UTF-8 JSON 输出。
- **可选引擎准备：** 新增 `scripts/lite.py --provision-office`，在插件目录内解包锁定版本 LibreOffice；免管理员、不注册到系统、不自动触发，用户自有安装始终优先。

## AI SOW Lite 0.1.0-alpha.1 - 2026-09-11

- 新增独立 Lite 插件：从 PRD/HLD、往期 SOW 和可选原型生成四表 SOW Excel，通过 clarify 讨论并应用有限修改。
- 覆盖业务、技术及交付范围；简明 AC 与影响估算的待确认直接写入对应行，计算使用模板。
- 发布首个 Alpha 试用版，可从远端 marketplace 安装；已完成本地 Codex 安装、生成与改稿验证，支持范围以 macOS 本地目录及可用 LibreOffice 为基础。
- [Lite 版本说明](plugins/ai-sow-lite/CHANGELOG.md)汇总能力，[支持说明](plugins/ai-sow-lite/docs/support.md)记录限制；阶段记录归档，发布入口不再混入开发日记。

## AI SOW 0.1.0-beta.1 - 2026-09-11

首个 Beta 预发布，配套 SOW 标准 `1.3`。可从 Codex 与 Claude Code 的远端 marketplace 安装；[发布记录](https://github.com/InspireChina/ai-plugin-marketplace/releases/tag/ai-sow-v0.1.0-beta.1)包含安装方式与验证结果。

- **安装与平台：** 插件独立交付，setup 自动准备隔离的 uv、Python 和锁定依赖；支持 macOS、Linux、Windows 11 x64，并处理 Windows 路径长度、PowerShell 与 UTF-8 编码问题。
- **完整工作流：** 七个主线阶段覆盖需求、现状、设计、Story/AC、Task 和 Excel；五个专业阶段先生成候选、机械校验和独立评审，再按用户批准的精确内容发布六份稳定 JSON。
- **范围与依据：** 分开维护业务与技术需求，关联原始材料、现状、往期承诺和有效起点；对范围缺口、责任、上线前提及影响估算的未知执行一致性检查。
- **拆分与估算：** 按 Epic → Feature → Story → Task 组织交付，AC 与实施工作分别表达；37 个基础工作项按新建、调整、接入复用和复杂度分类，核对实例及共享边界，避免重复计量。
- **评审与修正：** 提供分页上下文、判断缓存、机械检查前置和有限字段修复；候选、评审和批准保持同版绑定。`reconcile` 支持在一次整体评审中处理固定影响后缀，包括连续尚未首次生成的下游阶段。
- **Excel 交付：** 从已批准数据生成包含阶段数据、批准评审、收据及模板的自包含交付包；统一中文展示、下拉与编辑权限，修复长文本裁切和 Excel 2016/2019 的 AC/Task 汇总兼容问题。
- **可靠性：** 修复跨阶段来源定位、引用闭包、评审名称与数量投影、重复提交及跨平台工作簿字节一致性；强化独立安装和回归检查。

人天、SIT/UAT、风险和取整仍以项目模板为唯一计算依据，插件不执行 Excel 公式。当前采用 As-Is `0.2`、Delivery `0.4`、Owner receipt `0.3` 和生成器 `receipt-only-v3`；不提供首次公开预发布前内部原型数据的迁移。Beta 仍需逐阶段人工评审，尚无速度或 token 达标承诺。详细使用方式见 [AI SOW README](plugins/ai-sow/README.md)。
