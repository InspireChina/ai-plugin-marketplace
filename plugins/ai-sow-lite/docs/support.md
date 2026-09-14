# 支持与限制

适用于首个 Alpha 试用版 `0.1.0-alpha.1`；以下区分已验证能力和未验证范围。远端发布与安装验证记录见 [GitHub Release](https://github.com/InspireChina/ai-plugin-marketplace/releases/tag/ai-sow-lite-v0.1.0-alpha.1)。

## 运行环境

| 项目 | 当前证据与要求 |
|---|---|
| 操作系统与文件位置 | 已验证 macOS 普通本地目录；Windows 11 已验证 generate 全链路（`ingest → check → render → apply`）与 clarify 有限修改。单人串行生成与修改 |
| Windows 启动入口 | 必须用 `scripts/bootstrap.ps1 -Request <file>`；Windows PowerShell 5.1 与 PowerShell 7 均已验证。Git Bash/MSYS 下 `bootstrap.sh` 会直接报 `BOOTSTRAP_HOST_UNSUPPORTED` 并指向 ps1，不做半途失败 |
| Codex | 已验证桌面随附 CLI 0.153.4 经本地 marketplace 安装、发现 generate/clarify 并完成业务执行；不等同于所有宿主版本支持 |
| Excel 计算 | 需要外部已有的 LibreOffice；已验证 26.8.0.3。插件保留模板公式并通过真实 Office 重算、复读。Windows 上 LibreOffice 不写 PATH，插件会自动探测默认安装目录并使用控制台入口 `soffice.com`（`soffice.exe` 在管道下不返回版本）；也可用 `AI_SOW_LITE_OFFICE_BIN` 指定。完全没有安装时，可执行 `scripts/lite.py --provision-office` 在插件目录内准备一份（约 1.5 GB，免管理员、不注册到系统）；用户自有安装始终优先 |
| Excel 查看 | Microsoft Excel 16.112.3 已有代表性文件打开和布局验证；不要求用户用它替代导出引擎 |
| Python 与依赖 | 首次入口自动准备插件内隔离环境，后续复用；下载失败或目录不可写时返回诊断。可预先把锁定版本的 `uv` 可执行文件放入 `.ai-sow-tools/bin/` 跳过下载 |
| Claude Code | 2.1.250 已通过 manifest 检查和入口发现；认证失败导致业务流程未完成，暂不承诺完整支持 |
| 其他 Claude 兼容宿主 | 从 Claude Code 用户级 marketplace 安装时，部分宿主默认不加载外部用户级插件来源，需显式开启后才能发现 generate/clarify（omp：在配置中加入 `enabledProviders: [claude-plugins]`） |
| 其他平台与磁盘 | Linux、同步盘和网络盘没有对应实跑保证 |

若系统里同时有旧版 CLI 和桌面随附版本，应使用与所选模型兼容的宿主；不能把不同版本的验证结果混用。安装与使用方法见 [README](../README.md)，逐项证据见 [验证摘要](validation/README.md)。

## 输入和修改边界

- 文本支持 UTF-8 `.md`、`.markdown`、`.txt`，Excel 支持 `.xlsx`；原型需明确的目录资源包。PDF/DOCX、扫描件、OCR、`.xls` 等暂不支持。
- 原型目录输入依赖 POSIX 的目录 fd / no-follow 安全读取能力，**Windows 不支持**，会返回 `OPERATION_UNSUPPORTED`；其余输入类型不受影响。
- 新项目需要 PRD/HLD，旧项目还需往期 SOW。原型和草稿是补充，不替代基础材料。
- 历史名称或类型相似不能证明同一实例可调整或复用；需要确认的适用性写入本次估算问题。
- 当前按单人串行使用设计；修改依赖当前版本。基线已变化时旧草稿停止应用，不自动套到新版本上。
- Clarify 需要完整项目共享文件，不能仅凭 Excel 附件或原聊天重建基线。

## 常见情况

| 情况 | 如何处理 |
|---|---|
| 找不到 Lite 入口 | 刷新 Git marketplace 快照，核对 Lite 是否已安装并启用；安装后在新会话使用入口。非 Claude Code 宿主还需确认已允许外部用户级插件来源（omp：`enabledProviders: [claude-plugins]`） |
| `BOOTSTRAP_HOST_UNSUPPORTED` | 在 Windows 上用了 `bootstrap.sh`；改用 `scripts/bootstrap.ps1 -Request <file>` |
| `UV_INSTALL_FAILED` / `UV_INSTALL_INVALID` | 无法下载或解压 uv；按诊断检查网络，或手动把锁定版本的 `uv.exe` 放入插件的 `.ai-sow-tools/bin/` 后重试 |
| `OPERATION_UNSUPPORTED`（原型） | Windows 不支持原型目录输入；改用文本或 XLSX 材料 |
| 首次依赖准备失败 | 按诊断检查网络和插件目录权限，修正后在原项目继续 |
| `BOOTSTRAP_PATH_UNSAFE` | 插件工具根目录为符号链接或重解析点；使用真实安装目录，不绕过目录保护 |
| 缺少 LibreOffice | 自行安装，或执行 `scripts/lite.py --provision-office` 由插件在自身目录内准备；候选会保留，缺引擎时没有可用的新 Excel |
| 必需资料缺失或内容过少 | 按具体补料清单提供可读材料；不会先编造范围和方案 |
| 有值但显示“待确认” | 例如复杂度暂用 M；有值不等于用户已采用，可通过 clarify 答复 |
| 文本超过 Excel 可见高度 | 根据对象和单元格诊断精简或合理拆分相关 Story，不修改模板计算口径 |
| 执行中断 | 在原项目继续并查询状态；已成功版本保留，不删除工作文件另起一遍 |

## 性能与资源记录

生成和改稿仍可能需要数分钟。历史固定案例曾记录生成约 14 分钟、改稿约 8 分 21 秒；它们包含工具等待与实际返修，不是普通用户 SLA，也不是最新规则的提速证明。

工具调用耗时和大活动起止可记录。请求级 token 仅在明确提供已验证格式的本次原生来源时核对；逐活动 token、纯模型耗时与峰值上下文仍存在缺口。未知保持未知，不按文本大小换算 token，也不影响业务交付。原始成本见 [性能档案](archive/validation/I10-reference-gaps-and-skills.md#耗时与-token)。

正确性优先于性能。机械检查不能保证所有专业判断都正确，用户应核对范围、估算分类和待确认；后续优化以同等质量、减少返工为前提。
