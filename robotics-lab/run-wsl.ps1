param([int]$Port = 8000, [string]$Distribution = '')
$ErrorActionPreference = 'Stop'
$wslArgs = @('--cd', $PSScriptRoot, '--', 'bash', './run-linux.sh', "$Port")
if ($Distribution) {
    $wslArgs = @('-d', $Distribution) + $wslArgs
}
wsl.exe @wslArgs
if ($LASTEXITCODE -ne 0) { throw 'WSL 平台启动失败，请按 README 检查 Linux 虚拟环境与端口。' }
