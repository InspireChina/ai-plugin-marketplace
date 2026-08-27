param(
    [string]$ProjectRoot,
    [string]$ProjectId,
    [string]$Name
)

$ErrorActionPreference = "Stop"
$UvVersion = "0.11.7"
$PluginRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$ToolsRoot = Join-Path $PluginRoot ".ai-sow-tools"
$ToolsBin = Join-Path $ToolsRoot "bin"
$LocalUv = Join-Path $ToolsBin "uv.exe"
$Installer = Join-Path $ToolsRoot "install-uv.ps1"

# Windows 控制台默认使用本地代码页（如 cp936），会把中文诊断写成非 UTF-8 字节。
# 调用方按 UTF-8 读取 stdout，这里显式固定编码，并让下游 Python 使用同一编码。
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $OutputEncoding
$env:PYTHONUTF8 = "1"

# 从 PowerShell 7 启动的会话会把 7.x 模块目录排在继承来的 PSModulePath 前面，
# 使 Windows PowerShell 5.1 加载到不兼容的内置模块。让本进程自己的模块目录优先。
$env:PSModulePath = (Join-Path $PSHOME "Modules") + [IO.Path]::PathSeparator + $env:PSModulePath

function Stop-Bootstrap([string]$Code, [string]$Summary) {
    [ordered]@{
        outcome = "BLOCKED"
        summary = $Summary
        diagnostics = @([ordered]@{code = $Code; message = $Summary})
        nextStep = "当前 Agent 需要获得一次必要的联网或文件写入权限后自动重试；用户无需手工安装或执行命令。"
    } | ConvertTo-Json -Compress -Depth 4
    exit 2
}

function Test-UvVersion([string]$VersionText) {
    return $VersionText -match ("^uv " + [regex]::Escape($UvVersion) + "(?:\s|$)")
}

# 原生命令的启动失败和写入 stderr 都会在 $ErrorActionPreference = "Stop" 下抛出终止错误，
# 使脚本绕过 Stop-Bootstrap 输出非 JSON 文本。这里隔离执行，把两者都还原成退出码。
function Invoke-Native {
    param([string]$FilePath, [string[]]$Arguments = @())

    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $text = (& $FilePath @Arguments 2>&1 | Out-String).Trim()
        return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Text = $text }
    } catch {
        return [pscustomobject]@{ ExitCode = -1; Text = $_.Exception.Message }
    } finally {
        $ErrorActionPreference = $previous
    }
}

try {
    New-Item -ItemType Directory -Force -Path $ToolsBin, (Join-Path $ToolsRoot "cache") | Out-Null
} catch {
    Stop-Bootstrap "BOOTSTRAP_DIRECTORY_FAILED" "无法创建插件隔离环境目录"
}
if ([string]::IsNullOrWhiteSpace($env:UV_CACHE_DIR)) {
    $env:UV_CACHE_DIR = Join-Path $ToolsRoot "cache"
}
$env:UV_NO_MODIFY_PATH = "1"

$UvBin = $null
$UvSource = $null
if (Test-Path -LiteralPath $LocalUv -PathType Leaf) {
    $LocalProbe = Invoke-Native $LocalUv @("--version")
    if ($LocalProbe.ExitCode -eq 0 -and (Test-UvVersion $LocalProbe.Text)) {
        $UvBin = $LocalUv
        $UvSource = "PLUGIN_LOCAL"
    }
}
if ($null -eq $UvBin) {
    $UvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $UvCommand) {
        $PathProbe = Invoke-Native $UvCommand.Source @("--version")
        if ($PathProbe.ExitCode -eq 0 -and (Test-UvVersion $PathProbe.Text)) {
            $UvBin = $UvCommand.Source
            $UvSource = "PATH"
        }
    }
}
if ($null -eq $UvBin) {
    try {
        [Net.ServicePointManager]::SecurityProtocol = `
            [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/0.11.7/install.ps1" -OutFile $Installer
    } catch {
        Stop-Bootstrap "UV_INSTALL_DOWNLOAD_FAILED" "无法下载 uv 官方安装器"
    }
    try {
        $env:UV_UNMANAGED_INSTALL = $ToolsBin
        & $Installer
    } catch {
        Stop-Bootstrap "UV_INSTALL_FAILED" "uv 官方安装器执行失败"
    } finally {
        Remove-Item -LiteralPath $Installer -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath $LocalUv -PathType Leaf)) {
        Stop-Bootstrap "UV_INSTALL_INVALID" "uv 自动安装完成后仍无法执行"
    }
    $UvBin = $LocalUv
    $UvSource = "PLUGIN_LOCAL"
}

$UvProbe = Invoke-Native $UvBin @("--version")
if ($UvProbe.ExitCode -ne 0) { Stop-Bootstrap "UV_CHECK_FAILED" "uv 版本检查失败" }
$UvVersionText = $UvProbe.Text
if (-not (Test-UvVersion $UvVersionText)) { Stop-Bootstrap "UV_VERSION_INVALID" "插件运行时 uv 版本不是固定的 $UvVersion" }

if ((Invoke-Native $UvBin @("python", "find", "3.12")).ExitCode -ne 0) {
    if ((Invoke-Native $UvBin @("python", "install", "3.12")).ExitCode -ne 0) {
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $ToolsRoot "python"
        if ((Invoke-Native $UvBin @("python", "install", "3.12")).ExitCode -ne 0) {
            Stop-Bootstrap "PYTHON_INSTALL_FAILED" "Python 3.12 自动安装失败"
        }
    }
}

$Sync = Invoke-Native $UvBin @("sync", "--project", $PluginRoot, "--locked", "--python", "3.12")
if ($Sync.ExitCode -ne 0) { Stop-Bootstrap "DEPENDENCY_SYNC_FAILED" "插件锁定依赖同步失败" }

$PythonBin = Join-Path $PluginRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonBin -PathType Leaf)) { Stop-Bootstrap "VENV_MISSING" "插件隔离 .venv 未创建" }
$PythonProbe = Invoke-Native $PythonBin @("--version")
if ($PythonProbe.ExitCode -ne 0) { Stop-Bootstrap "PYTHON_CHECK_FAILED" "插件隔离 Python 无法执行" }
$PythonVersion = $PythonProbe.Text
if (-not $PythonVersion.StartsWith("Python 3.12.")) { Stop-Bootstrap "PYTHON_VERSION_INVALID" "插件隔离 Python 不是 3.12" }
if ((Invoke-Native $PythonBin @("-c", "import jsonschema, openpyxl")).ExitCode -ne 0) {
    Stop-Bootstrap "DEPENDENCY_IMPORT_FAILED" "插件隔离依赖复核失败"
}

$HasSetupArgs = -not [string]::IsNullOrWhiteSpace($ProjectRoot) -or -not [string]::IsNullOrWhiteSpace($ProjectId) -or -not [string]::IsNullOrWhiteSpace($Name)
if ($HasSetupArgs) {
    if ([string]::IsNullOrWhiteSpace($ProjectRoot) -or [string]::IsNullOrWhiteSpace($ProjectId) -or [string]::IsNullOrWhiteSpace($Name)) {
        Stop-Bootstrap "SETUP_ARGUMENTS_INCOMPLETE" "setup 的项目根目录、项目 ID 和名称必须同时提供"
    }
    # 值同时含空格和结尾分隔符时，PowerShell 原生参数引用会把结尾反斜杠当成转义符并吞掉右引号。
    # 这里先去掉结尾分隔符，但保留 `C:\` 这类驱动器根。
    $SafeProjectRoot = $ProjectRoot
    while ($SafeProjectRoot.Length -gt 3 -and ($SafeProjectRoot.EndsWith('\') -or $SafeProjectRoot.EndsWith('/'))) {
        $SafeProjectRoot = $SafeProjectRoot.Substring(0, $SafeProjectRoot.Length - 1)
    }
    & $PythonBin (Join-Path $PSScriptRoot "setup.py") `
        --project-root $SafeProjectRoot --project-id $ProjectId --name $Name
    exit $LASTEXITCODE
}

[ordered]@{
    outcome = "OK"
    summary = "AI SOW 插件隔离环境已就绪"
    uvVersion = $UvVersionText
    uvSource = $UvSource
    pythonVersion = $PythonVersion
    venv = ".venv"
} | ConvertTo-Json -Compress
