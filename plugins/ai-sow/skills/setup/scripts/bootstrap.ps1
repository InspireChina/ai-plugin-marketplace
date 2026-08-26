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

function Stop-Bootstrap([string]$Code, [string]$Summary) {
    [ordered]@{
        outcome = "BLOCKED"
        summary = $Summary
        diagnostics = @([ordered]@{code = $Code; message = $Summary})
        nextStep = "Codex 需要获得一次必要的联网或文件写入权限后自动重试；用户无需手工安装或执行命令。"
    } | ConvertTo-Json -Compress -Depth 4
    exit 2
}

New-Item -ItemType Directory -Force -Path $ToolsBin, (Join-Path $ToolsRoot "cache") | Out-Null
if ([string]::IsNullOrWhiteSpace($env:UV_CACHE_DIR)) {
    $env:UV_CACHE_DIR = Join-Path $ToolsRoot "cache"
}
$env:UV_NO_MODIFY_PATH = "1"

$UvBin = $null
$UvSource = $null
if (Test-Path -LiteralPath $LocalUv -PathType Leaf) {
    $LocalVersion = (& $LocalUv --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -eq 0 -and $LocalVersion -eq "uv $UvVersion") {
        $UvBin = $LocalUv
        $UvSource = "PLUGIN_LOCAL"
    }
}
if ($null -eq $UvBin) {
    $UvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $UvCommand) {
        $PathVersion = (& $UvCommand.Source --version 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $PathVersion -eq "uv $UvVersion") {
            $UvBin = $UvCommand.Source
            $UvSource = "PATH"
        }
    }
}
if ($null -eq $UvBin) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/0.11.7/install.ps1" -OutFile $Installer
        $env:UV_UNMANAGED_INSTALL = $ToolsBin
        & $Installer
    } catch {
        Stop-Bootstrap "UV_INSTALL_FAILED" "uv 官方安装器下载或执行失败"
    } finally {
        Remove-Item -LiteralPath $Installer -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath $LocalUv -PathType Leaf)) {
        Stop-Bootstrap "UV_INSTALL_INVALID" "uv 自动安装完成后仍无法执行"
    }
    $UvBin = $LocalUv
    $UvSource = "PLUGIN_LOCAL"
}

$UvVersionText = (& $UvBin --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { Stop-Bootstrap "UV_CHECK_FAILED" "uv 版本检查失败" }
if ($UvVersionText -ne "uv $UvVersion") { Stop-Bootstrap "UV_VERSION_INVALID" "插件运行时 uv 版本不是固定的 $UvVersion" }

& $UvBin python find 3.12 *> $null
if ($LASTEXITCODE -ne 0) {
    & $UvBin python install 3.12
    if ($LASTEXITCODE -ne 0) {
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $ToolsRoot "python"
        & $UvBin python install 3.12
        if ($LASTEXITCODE -ne 0) { Stop-Bootstrap "PYTHON_INSTALL_FAILED" "Python 3.12 自动安装失败" }
    }
}

& $UvBin sync --project $PluginRoot --locked --python 3.12
if ($LASTEXITCODE -ne 0) { Stop-Bootstrap "DEPENDENCY_SYNC_FAILED" "插件锁定依赖同步失败" }

$PythonBin = Join-Path $PluginRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonBin -PathType Leaf)) { Stop-Bootstrap "VENV_MISSING" "插件隔离 .venv 未创建" }
$PythonVersion = (& $PythonBin --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $PythonVersion.StartsWith("Python 3.12.")) { Stop-Bootstrap "PYTHON_VERSION_INVALID" "插件隔离 Python 不是 3.12" }
& $PythonBin -c "import jsonschema, openpyxl"
if ($LASTEXITCODE -ne 0) { Stop-Bootstrap "DEPENDENCY_IMPORT_FAILED" "插件隔离依赖复核失败" }

$HasSetupArgs = -not [string]::IsNullOrWhiteSpace($ProjectRoot) -or -not [string]::IsNullOrWhiteSpace($ProjectId) -or -not [string]::IsNullOrWhiteSpace($Name)
if ($HasSetupArgs) {
    if ([string]::IsNullOrWhiteSpace($ProjectRoot) -or [string]::IsNullOrWhiteSpace($ProjectId) -or [string]::IsNullOrWhiteSpace($Name)) {
        Stop-Bootstrap "SETUP_ARGUMENTS_INCOMPLETE" "setup 的项目根目录、项目 ID 和名称必须同时提供"
    }
    & $PythonBin (Join-Path $PSScriptRoot "setup.py") --project-root $ProjectRoot --project-id $ProjectId --name $Name
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
