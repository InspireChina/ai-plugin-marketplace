param([Parameter(Mandatory = $true)][string]$Request)
# Mechanical bootstrap adapted from ai-sow 2fc8588, with a single request file.
$ErrorActionPreference = "Stop"
$UvVersion = "0.11.7"
$PluginRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ToolsRoot = Join-Path $PluginRoot ".ai-sow-tools"
$ToolsBin = Join-Path $ToolsRoot "bin"
$LocalUv = Join-Path $ToolsBin "uv.exe"
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
# Check only owned write roots, including dangling links/junctions, before any writes.
# Managed version aliases below python remain valid.
foreach ($RuntimeRoot in @(".venv", ".ai-sow-tools", ".ai-sow-tools/bin", ".ai-sow-tools/cache", ".ai-sow-tools/python")) {
    try {
        $Attributes = [IO.File]::GetAttributes((Join-Path $PluginRoot $RuntimeRoot))
    } catch [IO.FileNotFoundException] { continue }
      catch [IO.DirectoryNotFoundException] { continue }
      catch { Stop-Bootstrap "BOOTSTRAP_PATH_UNSAFE" "无法安全检查插件运行时根目录 $RuntimeRoot。" }
    if (($Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Stop-Bootstrap "BOOTSTRAP_PATH_UNSAFE" "插件运行时根目录 $RuntimeRoot 不能是链接或重解析点；请使用本副本的真实目录。"
    }
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
    # Fetch the pinned archive directly. The official install.ps1 calls
    # Get-ExecutionPolicy, which fails outright when PSModulePath resolves
    # Microsoft.PowerShell.Security to a newer side-by-side PowerShell.
    $Archive = Join-Path $ToolsRoot "uv-$UvVersion.zip"
    $Staging = Join-Path $ToolsRoot "uv-$UvVersion-unpack"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $Platform = if ([Environment]::Is64BitOperatingSystem) { "x86_64" } else { "i686" }
        Invoke-WebRequest -UseBasicParsing -OutFile $Archive -Uri `
            "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-$Platform-pc-windows-msvc.zip"
        Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue
        # The ZipFile API needs no module lookup, unlike Expand-Archive.
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Staging)
        $Extracted = Get-ChildItem -LiteralPath $Staging -Filter "uv.exe" -Recurse -File | Select-Object -First 1
        if ($null -eq $Extracted) { throw "uv.exe missing from archive" }
        Move-Item -LiteralPath $Extracted.FullName -Destination $LocalUv -Force
    } catch { Stop-Bootstrap "UV_INSTALL_FAILED" "uv 下载或解压失败；可手动将 uv $UvVersion 的 uv.exe 放入 .ai-sow-tools/bin/ 后重试。" }
    finally {
        Remove-Item -LiteralPath $Archive -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath $LocalUv -PathType Leaf)) {
        Stop-Bootstrap "UV_INSTALL_INVALID" "uv 安装后仍无法执行；可手动将 uv $UvVersion 的 uv.exe 放入 .ai-sow-tools/bin/ 后重试。"
    }
    $UvBin = $LocalUv
}
$Probe = Invoke-Native $UvBin @("--version")
if ($Probe.ExitCode -ne 0) { Stop-Bootstrap "UV_CHECK_FAILED" "uv 版本检查失败。" }
if (-not (Test-UvVersion $Probe.Text)) { Stop-Bootstrap "UV_VERSION_INVALID" "uv 不是锁定版本。" }
# Reuse this copy's installation without registering user-bin/registry entries.
if ((Invoke-Native $UvBin @("python", "install", "3.12", "--no-bin", "--no-registry")).ExitCode -ne 0) {
    Stop-Bootstrap "PYTHON_INSTALL_FAILED" "Python 3.12 自动安装失败。"
}
$Probe = Invoke-Native $UvBin @("python", "find", "3.12", "--managed-python", "--no-project", "--system", "--resolve-links")
if ($Probe.ExitCode -ne 0) { Stop-Bootstrap "PYTHON_CHECK_FAILED" "无法定位本插件的 managed Python。" }
$ManagedPython = $Probe.Text
$OwnRootCheck = "import pathlib,sys; sys.exit(not pathlib.Path(sys.executable).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve() / '.ai-sow-tools' / 'python'))"
if ((Invoke-Native $ManagedPython @("-c", $OwnRootCheck, $PluginRoot)).ExitCode -ne 0) {
    Stop-Bootstrap "PYTHON_CHECK_FAILED" "managed Python 不属于本插件副本。"
}
$PythonBin = Join-Path $PluginRoot ".venv/Scripts/python.exe"
if ([IO.Path]::DirectorySeparatorChar -eq '/') { $PythonBin = Join-Path $PluginRoot ".venv/bin/python" }
$BaseProbe = "import os,sys; print(os.path.realpath(sys._base_executable))"
# Explicit --python alone does not replace a same-version foreign venv.
if (Test-Path -LiteralPath $env:UV_PROJECT_ENVIRONMENT -PathType Container) {
    $Probe = Invoke-Native $PythonBin @("-c", $BaseProbe)
    if ($Probe.ExitCode -ne 0 -or $Probe.Text -cne $ManagedPython) {
        if ((Invoke-Native $UvBin @("venv", "--no-project", "--clear", "--no-python-downloads", "--python", $ManagedPython, $env:UV_PROJECT_ENVIRONMENT)).ExitCode -ne 0) {
            Stop-Bootstrap "VENV_MISSING" "无法重建本插件隔离环境。"
        }
    }
}
if ((Invoke-Native $UvBin @("sync", "--project", $PluginRoot, "--locked", "--no-python-downloads", "--python", $ManagedPython)).ExitCode -ne 0) {
    Stop-Bootstrap "DEPENDENCY_SYNC_FAILED" "插件锁定依赖同步失败。"
}
if (-not (Test-Path -LiteralPath $PythonBin -PathType Leaf)) { Stop-Bootstrap "VENV_MISSING" "插件隔离环境未创建。" }
$Probe = Invoke-Native $PythonBin @("-c", $BaseProbe)
if ($Probe.ExitCode -ne 0 -or $Probe.Text -cne $ManagedPython) { Stop-Bootstrap "PYTHON_CHECK_FAILED" "隔离 Python 不属于本插件副本。" }
$Probe = Invoke-Native $PythonBin @("--version")
if ($Probe.ExitCode -ne 0) { Stop-Bootstrap "PYTHON_CHECK_FAILED" "隔离 Python 无法执行。" }
if (-not $Probe.Text.StartsWith("Python 3.12.")) { Stop-Bootstrap "PYTHON_VERSION_INVALID" "隔离 Python 不是 3.12。" }
if ((Invoke-Native $PythonBin @("-c", "import jsonschema, openpyxl")).ExitCode -ne 0) {
    Stop-Bootstrap "DEPENDENCY_IMPORT_FAILED" "隔离依赖复核失败。"
}
& $PythonBin (Join-Path $PluginRoot "scripts/lite.py") --request $Request
exit $LASTEXITCODE
