param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [Parameter(Mandatory = $true)]
    [ValidateSet("prepare", "accept-scope", "accept-delivery", "prepare-review", "accept-review", "publish", "status")]
    [string]$Mode,
    [string]$Request,
    [string]$Candidate,
    [string]$Ids,
    [string]$Review
)

$ErrorActionPreference = "Stop"
$UvVersion = "0.11.7"
$PluginRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$Orchestrator = Join-Path $PluginRoot "skills/generate/scripts/orchestrator.py"
$ToolsRoot = Join-Path $PluginRoot ".ai-sow-tools"
$ToolsBin = Join-Path $ToolsRoot "bin"
$LocalUv = Join-Path $ToolsBin "uv.exe"
$Installer = Join-Path $ToolsRoot "install-uv.ps1"

$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $OutputEncoding
$env:PYTHONUTF8 = "1"
$env:PSModulePath = (Join-Path $PSHOME "Modules") + [IO.Path]::PathSeparator + $env:PSModulePath

function Stop-Bootstrap([string]$Code, [string]$Summary, [string]$NextStep = "当前 Agent 需要获得一次必要的联网或文件写入权限后自动重试；用户无需手工安装或执行命令。") {
    [ordered]@{
        outcome = "BLOCKED"
        summary = $Summary
        diagnostics = @([ordered]@{code = $Code; message = $Summary})
        nextStep = $NextStep
    } | ConvertTo-Json -Compress -Depth 4
    exit 2
}

function Test-UvVersion([string]$VersionText) {
    return $VersionText -match ("^uv " + [regex]::Escape($UvVersion) + "(?:\s|$)")
}

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

function Test-LongPathsEnabled {
    $value = Get-ItemProperty `
        -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
        -Name "LongPathsEnabled" `
        -ErrorAction SilentlyContinue
    return $null -ne $value -and [int]$value.LongPathsEnabled -eq 1
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
if (Test-Path -LiteralPath $LocalUv -PathType Leaf) {
    $LocalProbe = Invoke-Native $LocalUv @("--version")
    if ($LocalProbe.ExitCode -eq 0 -and (Test-UvVersion $LocalProbe.Text)) {
        $UvBin = $LocalUv
    }
}
if ($null -eq $UvBin) {
    $UvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $UvCommand) {
        $PathProbe = Invoke-Native $UvCommand.Source @("--version")
        if ($PathProbe.ExitCode -eq 0 -and (Test-UvVersion $PathProbe.Text)) {
            $UvBin = $UvCommand.Source
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
}

$UvProbe = Invoke-Native $UvBin @("--version")
if ($UvProbe.ExitCode -ne 0) { Stop-Bootstrap "UV_CHECK_FAILED" "uv 版本检查失败" }
if (-not (Test-UvVersion $UvProbe.Text)) { Stop-Bootstrap "UV_VERSION_INVALID" "插件运行时 uv 版本不是固定的 $UvVersion" }

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
if (-not $PythonProbe.Text.StartsWith("Python 3.12.")) { Stop-Bootstrap "PYTHON_VERSION_INVALID" "插件隔离 Python 不是 3.12" }
if ((Invoke-Native $PythonBin @("-c", "import jsonschema, openpyxl")).ExitCode -ne 0) {
    Stop-Bootstrap "DEPENDENCY_IMPORT_FAILED" "插件隔离依赖复核失败"
}

$SafeProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
while ($SafeProjectRoot.Length -gt 3 -and ($SafeProjectRoot.EndsWith('\') -or $SafeProjectRoot.EndsWith('/'))) {
    $SafeProjectRoot = $SafeProjectRoot.Substring(0, $SafeProjectRoot.Length - 1)
}
if ($SafeProjectRoot.Length -ge 97 -and -not (Test-LongPathsEnabled)) {
    $Remedy = Join-Path $PSScriptRoot "enable_long_paths.ps1"
    Stop-Bootstrap `
        "WINDOWS_LONG_PATH_REQUIRED" `
        "项目路径过长且 Windows 长路径支持未启用；生成尚未写入项目。" `
        "缩短项目路径，或说明机器级策略影响并取得明确同意后运行 $Remedy -Apply。"
}

$OrchestratorArgs = @($Orchestrator, "--project-root", $SafeProjectRoot, "--mode", $Mode)
if (-not [string]::IsNullOrWhiteSpace($Request)) { $OrchestratorArgs += @("--request", $Request) }
if (-not [string]::IsNullOrWhiteSpace($Candidate)) { $OrchestratorArgs += @("--candidate", $Candidate) }
if (-not [string]::IsNullOrWhiteSpace($Ids)) { $OrchestratorArgs += @("--ids", $Ids) }
if (-not [string]::IsNullOrWhiteSpace($Review)) { $OrchestratorArgs += @("--review", $Review) }

& $PythonBin @OrchestratorArgs
exit $LASTEXITCODE
