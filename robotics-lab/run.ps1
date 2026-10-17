param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $PSScriptRoot '.venv'
    $env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.cache/uv-windows'
    uv run --locked --offline python -m robotics_lab serve --port $Port
    if ($LASTEXITCODE -ne 0) { throw '平台启动失败' }
} finally {
    Pop-Location
}
