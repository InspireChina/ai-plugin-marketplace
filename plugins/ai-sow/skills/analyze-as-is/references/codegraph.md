# CodeGraph 调查参考

对每个已登记代码库按同一顺序选择证据路径。已安装版本的 `codegraph help <command>` 是参数权威；工作记录保留版本、命令差异、失败原因和索引覆盖。

## 四级选择

### 1. 当前可调用的 MCP

先调用已暴露的 CodeGraph MCP，检查项目、索引状态和文件覆盖。索引可用时选择 `CODEGRAPH_MCP` 并先做范围收窄的结构查询。

### 2. 已有 CLI

MCP 不能为当前代码库提供可用图时，用 `command -v codegraph`（POSIX）或 `(Get-Command codegraph).Source`（PowerShell）解析已有 CLI 的绝对路径。始终用该绝对路径执行：

```text
"<existing-cli-absolute>" --version
"<existing-cli-absolute>" status "<repo-path>"
"<existing-cli-absolute>" files --path "<repo-path>"
```

PowerShell 使用调用运算符，例如 `& "<existing-cli-absolute>" status "<repo-path>"`。CodeGraph CLI 1.5.0 的 `files` 只接受 `-p/--path`，不接受仓库位置参数；其他版本以已安装 CLI 的 `help files` 为准。若代码库尚未初始化或索引不可用，先执行 `"<existing-cli-absolute>" init "<repo-path>"`（PowerShell：`& "<existing-cli-absolute>" init "<repo-path>"`），然后用同一绝对路径再次执行 `status` 和 `files --path`。现有 CLI 产生可用图时选择 `CODEGRAPH_CLI`；只有找不到 executable，或初始化/索引后仍没有可用图时，才进入项目局部安装。

### 3. 项目局部安装和索引

前两级不能为当前代码库提供可用图时，把 CLI 安装在项目工作区 `.ai-sow/work/analyze-as-is/tooling/`，不写智能体配置。

Node/npm 可用时，安装后始终使用平台对应的绝对入口，不依赖 `PATH`：

```text
npm install --prefix ".ai-sow/work/analyze-as-is/tooling" @colbymchenry/codegraph
"<tooling-absolute>/node_modules/.bin/codegraph" --version
"<tooling-absolute>/node_modules/.bin/codegraph" init "<repo-path>"
```

```powershell
npm install --prefix ".ai-sow\work\analyze-as-is\tooling" @colbymchenry/codegraph
& "<tooling-absolute>\node_modules\.bin\codegraph.cmd" --version
& "<tooling-absolute>\node_modules\.bin\codegraph.cmd" init "<repo-path>"
```

POSIX 无 npm 时，可以把官方独立安装器的安装目录和可执行目录都定向到 tooling：

```text
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh \
  -o ".ai-sow/work/analyze-as-is/tooling/install-codegraph.sh"
env CODEGRAPH_INSTALL_DIR="<tooling-absolute>/codegraph" \
  CODEGRAPH_BIN_DIR="<tooling-absolute>/bin" \
  sh ".ai-sow/work/analyze-as-is/tooling/install-codegraph.sh"
"<tooling-absolute>/bin/codegraph" --version
"<tooling-absolute>/bin/codegraph" init "<repo-path>"
```

Windows 无 npm 时，不执行官方 `install.ps1` 作为本轮局部安装路径，因为它会持久修改用户 `PATH`。记录局部安装无法安全完成及 npm 探测结果，然后进入 `STATIC_FALLBACK`；只有用户明确要求持久安装时才使用该安装器。

安装成功后使用同一个绝对 CLI 路径初始化本次调查需要的代码库索引，并运行 `<local-cli> status <repo-path>` 与 `<local-cli> files --path <repo-path>`。成功时选择 `CODEGRAPH_LOCAL`；安装、初始化和索引日志保存在 tooling 或相邻工作记录中。

### 4. 已记录静态回退

只有 MCP、已有 CLI、项目局部安装或索引均不能产生可用图时，才能选择 `STATIC_FALLBACK`。先保留失败命令、退出码、简明错误和已尝试的恢复动作，再使用范围收窄的 `rg`、语言原生工具、合同、配置和部署材料。回退不会降低 Evidence 和 Uncertainty 要求。

## 每个代码库的记录

在 `.ai-sow/work/analyze-as-is/codegraph-<repo-id>.md` 记录：

```text
Repo ID 与 revision：
MCP 结果：
已有 CLI 路径、版本与结果：
项目局部安装路径与结果：
初始化、状态与文件覆盖：
失败证据与恢复动作：
最终路径：CODEGRAPH_MCP | CODEGRAPH_CLI | CODEGRAPH_LOCAL | STATIC_FALLBACK
未索引边界：
```

## 查询与证据

- 用 `query` 定位符号，用 `node` 读取确切符号或文件，用 `explore` 检查指定流程。
- 用 `callers`、`callees`、`impact` 和 `affected` 追踪关系；把启发式边视为候选，直到直接证据确认。
- 每条稳定 Evidence 只保存一个项目相对 anchor，例如 `<repo-id>:src/file.py#L12-L20` 或 `#symbol=...`；多处证据拆成多条记录。
- `sync`、`index` 和 `unlock` 只在 `status` 证明需要时使用，并记录原因；不让索引指向用户主目录、文件系统根目录或调查范围外路径。

## 持久 MCP 安装

持久安装会修改客户端或用户配置，通常要重启或重新加载智能体。本轮调查不以它为前置条件。只有用户明确要求持久安装时，才执行官方 `codegraph install`、`npx @colbymchenry/codegraph` 或 Windows `install.ps1`，先说明配置目标、用户 `PATH` 影响和重启要求；本轮仍使用可立即调用的绝对 CLI 路径。
