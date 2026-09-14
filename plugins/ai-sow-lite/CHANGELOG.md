# 版本说明

## 未发布

### Windows 支持

- generate 全链路（ingest → check → render → apply）与 clarify 有限修改已在 Windows 11 验证。
- 启动入口为 `scripts/bootstrap.ps1`；Windows PowerShell 5.1 与 PowerShell 7 均已验证。在 Git Bash 等 Windows shell 下运行 `bootstrap.sh` 会直接返回 BOOTSTRAP_HOST_UNSUPPORTED 并指向 ps1。
- Excel 重算自动使用 Windows 控制台入口 `soffice.com` 并探测默认安装目录；未安装时可执行 `scripts/lite.py --provision-office` 在插件目录内准备（免管理员、不注册到系统、不自动触发）。
- 原型目录输入依赖 POSIX 目录 fd 能力，Windows 不支持，返回 OPERATION_UNSUPPORTED。

### 可靠性

- analysis 登记中断后可用同一请求重放补完；索引丢失只由写入操作在逐字节重证出处后重建，查询保持只读。
- 主题记录的期望观察集合改为完全从不可变登记独立推导，不再取用待验证记录自身的 observations：删除观察的记录不能再通过重证而取得新索引。
- Windows 上原子替换遇到瞬时文件锁时有界重试。

## 0.1.0-alpha.1 — 2026-09-11

首个 AI SOW Lite 试用版。Lite 独立安装，提供 `generate` 与 `clarify` 两个入口。可从远端 marketplace 安装；发布与安装验证记录见 [GitHub Release](https://github.com/InspireChina/ai-plugin-marketplace/releases/tag/ai-sow-lite-v0.1.0-alpha.1)。

### 主要能力

- 从 PRD、高阶设计和旧项目往期 SOW 识别本期业务、技术与交付范围，生成 Epic、Feature、Story、AC 和 Task。
- 支持 UTF-8 Markdown、文本、XLSX 和可选的 HTML/JS/CSS 原型目录。
- 先收集项目类型及必要材料，再就影响推进的输入合批澄清；资料不足明确退出，局部未知随初稿交付。
- 只保留影响工作量估算的待确认；复杂度未知默认 M，有相关历史候选但实例适用未明时默认新建并留确认项。
- 输出四表自包含 Excel：完整 AC 位于验收条件列，必要说明和待确认位于目标行备注；人天、金额、SIT/UAT 由模板计算。
- Clarify 讨论具体修改方案，确认后在有限范围内更新；支持部分答复、明确采用默认档位和重复意见复用。
- 原始输入、依据与历史版本保存在项目文件中，支持新会话接续和中断恢复；资源记录与业务交付独立。

### 支持范围与已知限制

- 已验证 macOS 普通本地目录、Codex 和 LibreOffice 的安装、生成与改稿流程；具体环境见 [支持说明](docs/support.md)。
- Claude Code 仅完成入口发现与 manifest 检查；Windows/Linux、同步盘和网络盘尚无完整业务验证。
- 不支持 PDF/DOCX/OCR。缺少 LibreOffice 时保留候选，不能完成 Excel 导出。
- 生成与改稿仍可能需要数分钟；逐活动 token 精确归属尚不完整。当前没有速度达标承诺。
- 首稿需用户核对，过长文本可能触发 Excel 可见高度限制，需针对相关行作有限调整。

验证范围见 [验证摘要](docs/validation/README.md)。开发轮次、旧方案及原始指标集中在 [历史档案](docs/archive/README.md)，不作为当前使用步骤。
