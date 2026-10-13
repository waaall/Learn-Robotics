# 固定使用推理项目的虚拟环境与临时 DLL 路径。
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Command,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$CommandArgs
)
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "../../tools/windows_runtime/run-command.ps1") -ProjectDir $PSScriptRoot -Command $Command -CommandArgs $CommandArgs
exit $LASTEXITCODE
