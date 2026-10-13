# 安装本训练项目的锁定环境，不同步推理或机械臂项目。
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "../../tools/windows_runtime/setup-environment.ps1") -ProjectDir $PSScriptRoot -Python $Python
