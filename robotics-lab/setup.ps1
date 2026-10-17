$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.cache/uv-windows'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $PSScriptRoot '.venv'
    uv sync --locked --extra dev --python 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败' }
    npm.cmd ci --prefix frontend --cache .cache/npm --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
    npm.cmd run build --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
    Write-Host '构建完成。Windows 可运行数值实验；官方 WebViewer 请使用 Linux/WSL。'
} finally {
    Pop-Location
}
