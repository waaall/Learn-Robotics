# 安装本离线推理项目的锁定环境，不同步训练或机械臂项目。
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "../../tools/windows_runtime/setup-environment.ps1") -ProjectDir $PSScriptRoot -Python $Python
