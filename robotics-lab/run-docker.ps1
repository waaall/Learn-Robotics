param([ValidateSet('up', 'build', 'load', 'stop', 'logs', 'status')][string]$Action = 'up')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw '请先安装并启动 Docker Desktop，使用 Linux 容器。' }
    $engine = docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0) { throw 'Docker 引擎不可用，请启动 Docker Desktop。' }
    if ($engine -ne 'linux') { throw '请将 Docker Desktop 切换为 Linux 容器。' }
    $composeArgs = @('-f', 'compose.yaml')
    if (Test-Path -LiteralPath 'compose.build.yaml') { $composeArgs += @('-f', 'compose.build.yaml') }
    switch ($Action) {
        'up' { docker compose @composeArgs up -d --wait --wait-timeout 120 }
        'build' { docker compose @composeArgs build }
        'load' { docker image load -i images.tar }
        'stop' { docker compose @composeArgs down }
        'logs' { docker compose @composeArgs logs --tail 100 -f }
        'status' { docker compose @composeArgs ps }
    }
    if ($LASTEXITCODE -ne 0) { throw "Docker 操作失败: $Action" }
    if ($Action -eq 'up') {
        $address = docker compose @composeArgs port web 8080
        if ($LASTEXITCODE -ne 0) { throw '无法读取 Web 端口。' }
        Write-Host "Robotics Lab: http://$address"
    }
} finally {
    Pop-Location
}
