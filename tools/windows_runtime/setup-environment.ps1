# 为指定实验创建独立环境，共享经过哈希校验的视频运行库，不修改硬件项目环境。
param(
    [Parameter(Mandatory = $true)][string]$ProjectDir,
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$PreviousCache = $env:UV_CACHE_DIR
Push-Location -LiteralPath $ProjectDir
try {
    $env:UV_CACHE_DIR = Join-Path $Repo ".cache/uv"
    uv sync --locked --python $Python
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
    uv pip check --python .venv/Scripts/python.exe
    if ($LASTEXITCODE -ne 0) { throw "Dependency validation failed" }
    $Manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "ffmpeg-source.json") | ConvertFrom-Json
    $Cache = Join-Path $Repo ".cache/ffmpeg"
    New-Item -ItemType Directory -Force $Cache | Out-Null
    $Archive = Join-Path $Cache "ffmpeg.zip"
    $Valid = (Test-Path -LiteralPath $Archive -PathType Leaf) -and
        ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Manifest.sha256)
    if (!$Valid) {
        # 校验成功后才替换缓存；中断或错误哈希不能污染已保存的归档。
        $Partial = Join-Path $Cache ("ffmpeg-" + [guid]::NewGuid().ToString("N") + ".partial")
        try {
            Invoke-WebRequest $Manifest.url -OutFile $Partial -UseBasicParsing
            if ((Get-FileHash -LiteralPath $Partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Manifest.sha256) {
                throw "FFmpeg downloaded archive checksum mismatch. Verify the pinned source."
            }
            Move-Item -LiteralPath $Partial -Destination $Archive -Force
        } finally {
            if (Test-Path -LiteralPath $Partial -PathType Leaf) { Remove-Item -LiteralPath $Partial -Force }
        }
    }
    Expand-Archive -LiteralPath $Archive -DestinationPath (Join-Path $Cache "runtime") -Force
} finally {
    $env:UV_CACHE_DIR = $PreviousCache
    Pop-Location
}
