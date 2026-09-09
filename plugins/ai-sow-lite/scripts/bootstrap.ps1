param([Parameter(Mandatory = $true)][string]$Request)
# Mechanical bootstrap adapted from ai-sow 2fc8588, with a single request file.
$ErrorActionPreference = "Stop"
$UvVersion = "0.11.7"
$PluginRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ToolsRoot = Join-Path $PluginRoot ".ai-sow-tools"
$ToolsBin = Join-Path $ToolsRoot "bin"
$LocalUv = Join-Path $ToolsBin "uv.exe"
$Installer = Join-Path $ToolsRoot "install-uv.ps1"
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $OutputEncoding
$env:PYTHONUTF8 = "1"
$env:UV_NO_MODIFY_PATH = "1"
$env:UV_CACHE_DIR = Join-Path $ToolsRoot "cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $ToolsRoot "python"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $PluginRoot ".venv"
function Stop-Bootstrap([string]$Code, [string]$Summary) {
    [ordered]@{
        ok = $false; request_id = $null; operation = $null; result = @{}
        diagnostics = @([ordered]@{
            code = $Code; target = @{path=$null; object_id=$null; field=$null}
            message = $Summary; preserved_paths = @()
        })
    } | ConvertTo-Json -Compress -Depth 6
    exit 3
}
function Invoke-Native {
    param([string]$FilePath, [string[]]$Arguments = @())
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $text = (& $FilePath @Arguments 2>&1 | Out-String).Trim()
        return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Text = $text }
    } catch {
        return [pscustomobject]@{ ExitCode = -1; Text = "" }
    } finally { $ErrorActionPreference = $previous }
}
function Test-UvVersion([string]$VersionText) {
    return $VersionText -match ("^uv " + [regex]::Escape($UvVersion) + "(?:\s|$)")
}
try {
    New-Item -ItemType Directory -Force -Path $ToolsBin, $env:UV_CACHE_DIR | Out-Null
} catch { Stop-Bootstrap "BOOTSTRAP_DIRECTORY_FAILED" "无法创建插件隔离环境目录。" }
$UvBin = $null
if (Test-Path -LiteralPath $LocalUv -PathType Leaf) {
    $Probe = Invoke-Native $LocalUv @("--version")
    if ($Probe.ExitCode -eq 0 -and (Test-UvVersion $Probe.Text)) { $UvBin = $LocalUv }
}
if ($null -eq $UvBin) {
    $Command = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $Command) {
        $Probe = Invoke-Native $Command.Source @("--version")
        if ($Probe.ExitCode -eq 0 -and (Test-UvVersion $Probe.Text)) { $UvBin = $Command.Source }
    }
}
if ($null -eq $UvBin) {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/0.11.7/install.ps1" -OutFile $Installer
        $env:UV_UNMANAGED_INSTALL = $ToolsBin
        & $Installer *> $null
    } catch { Stop-Bootstrap "UV_INSTALL_FAILED" "uv 官方安装失败。" }
    finally { Remove-Item -LiteralPath $Installer -Force -ErrorAction SilentlyContinue }
    if (-not (Test-Path -LiteralPath $LocalUv -PathType Leaf)) { Stop-Bootstrap "UV_INSTALL_INVALID" "uv 安装后仍无法执行。" }
    $UvBin = $LocalUv
}
$Probe = Invoke-Native $UvBin @("--version")
if ($Probe.ExitCode -ne 0) { Stop-Bootstrap "UV_CHECK_FAILED" "uv 版本检查失败。" }
if (-not (Test-UvVersion $Probe.Text)) { Stop-Bootstrap "UV_VERSION_INVALID" "uv 不是锁定版本。" }
if ((Invoke-Native $UvBin @("python", "find", "3.12")).ExitCode -ne 0) {
    if ((Invoke-Native $UvBin @("python", "install", "3.12")).ExitCode -ne 0) {
        Stop-Bootstrap "PYTHON_INSTALL_FAILED" "Python 3.12 自动安装失败。"
    }
}
if ((Invoke-Native $UvBin @("sync", "--project", $PluginRoot, "--locked", "--python", "3.12")).ExitCode -ne 0) {
    Stop-Bootstrap "DEPENDENCY_SYNC_FAILED" "插件锁定依赖同步失败。"
}
$PythonBin = Join-Path $PluginRoot ".venv/Scripts/python.exe"
if ([IO.Path]::DirectorySeparatorChar -eq '/') { $PythonBin = Join-Path $PluginRoot ".venv/bin/python" }
if (-not (Test-Path -LiteralPath $PythonBin -PathType Leaf)) { Stop-Bootstrap "VENV_MISSING" "插件隔离环境未创建。" }
$Probe = Invoke-Native $PythonBin @("--version")
if ($Probe.ExitCode -ne 0) { Stop-Bootstrap "PYTHON_CHECK_FAILED" "隔离 Python 无法执行。" }
if (-not $Probe.Text.StartsWith("Python 3.12.")) { Stop-Bootstrap "PYTHON_VERSION_INVALID" "隔离 Python 不是 3.12。" }
if ((Invoke-Native $PythonBin @("-c", "import jsonschema, openpyxl")).ExitCode -ne 0) {
    Stop-Bootstrap "DEPENDENCY_IMPORT_FAILED" "隔离依赖复核失败。"
}
& $PythonBin (Join-Path $PluginRoot "scripts/lite.py") --request $Request
exit $LASTEXITCODE
