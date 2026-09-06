<#
.SYNOPSIS
启用 Windows 长路径支持（LongPathsEnabled）。

.DESCRIPTION
这会修改 HKLM 下的机器级系统策略，影响本机所有程序，且需要管理员权限。
只有在向用户说明影响并取得明确同意后才可运行，且必须显式传入 -Apply。
不传 -Apply 时只报告当前状态，不做任何修改。
#>
param(
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$KeyPath = "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem"
$ValueName = "LongPathsEnabled"

$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $OutputEncoding
$env:PSModulePath = (Join-Path $PSHOME "Modules") + [IO.Path]::PathSeparator + $env:PSModulePath

function Write-Result([hashtable]$Payload) {
    [ordered]@{
        outcome = $Payload.outcome
        summary = $Payload.summary
        longPathsEnabled = $Payload.longPathsEnabled
        nextStep = $Payload.nextStep
    } | ConvertTo-Json -Compress -Depth 4
}

function Get-LongPathsEnabled {
    $current = Get-ItemProperty -Path $KeyPath -Name $ValueName -ErrorAction SilentlyContinue
    if ($null -eq $current) { return 0 }
    return [int]$current.$ValueName
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal $identity
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$enabled = Get-LongPathsEnabled

if ($enabled -eq 1) {
    Write-Result @{
        outcome = "OK"
        summary = "本机已启用 Windows 长路径支持"
        longPathsEnabled = $true
        nextStep = "重新调用 generate。"
    }
    exit 0
}

if (-not $Apply) {
    Write-Result @{
        outcome = "NEEDS_INPUT"
        summary = "本机未启用 Windows 长路径支持；本次为只读检查，未做任何修改"
        longPathsEnabled = $false
        nextStep = "向用户说明这会修改机器级系统策略并需要管理员权限；取得明确同意后，以管理员身份重新运行本脚本并加上 -Apply。"
    }
    exit 1
}

if (-not (Test-Administrator)) {
    Write-Result @{
        outcome = "BLOCKED"
        summary = "启用长路径支持需要管理员权限"
        longPathsEnabled = $false
        nextStep = "在取得用户同意后，以管理员身份重新运行本脚本并加上 -Apply；不要绕过 UAC 提示。"
    }
    exit 2
}

try {
    New-ItemProperty -Path $KeyPath -Name $ValueName -Value 1 -PropertyType DWord -Force | Out-Null
} catch {
    Write-Result @{
        outcome = "BLOCKED"
        summary = "写入 LongPathsEnabled 失败"
        longPathsEnabled = $false
        nextStep = "确认账户具有 HKLM 写入权限，或改为把项目移动到更短的路径。"
    }
    exit 2
}

if ((Get-LongPathsEnabled) -ne 1) {
    Write-Result @{
        outcome = "BLOCKED"
        summary = "写入后复读 LongPathsEnabled 仍不是 1"
        longPathsEnabled = $false
        nextStep = "检查是否有组策略覆盖该值；否则改为把项目移动到更短的路径。"
    }
    exit 2
}

Write-Result @{
    outcome = "OK"
    summary = "已启用 Windows 长路径支持"
    longPathsEnabled = $true
    nextStep = "新启动的进程立即生效；已在运行的 Codex/Claude Code 会话需要重启后重新调用 generate。"
}
exit 0
