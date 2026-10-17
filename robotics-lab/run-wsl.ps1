param([int]$Port = 8000, [string]$Distribution = 'Ubuntu')
$ErrorActionPreference = 'Stop'
wsl.exe -d $Distribution --cd $PSScriptRoot -- bash ./run-linux.sh $Port
if ($LASTEXITCODE -ne 0) { throw 'WSL 平台启动失败，请按 README 检查 Linux 虚拟环境与端口。' }
