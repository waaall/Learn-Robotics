param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    # Keep downloads in the repository cache, outside the tracked environment files.
    $env:UV_CACHE_DIR = Join-Path (Resolve-Path "../..") ".cache/uv"
    uv sync --locked --python $Python
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
    uv pip check --python .venv/Scripts/python.exe
    if ($LASTEXITCODE -ne 0) { throw "Dependency validation failed" }
    $manifest = Get-Content ffmpeg-source.json | ConvertFrom-Json
    $ffmpegCache = Join-Path (Resolve-Path "../..") ".cache/ffmpeg"
    New-Item -ItemType Directory -Force $ffmpegCache | Out-Null
    $archive = Join-Path $ffmpegCache "ffmpeg.zip"
    if (!(Test-Path $archive)) {
        Invoke-WebRequest $manifest.url -OutFile $archive
    }
    if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLower() -ne $manifest.sha256) {
        throw "FFmpeg archive checksum mismatch. Upstream latest may have changed; inspect before updating the manifest."
    }
    $runtime = Join-Path $ffmpegCache "runtime"
    Expand-Archive -LiteralPath $archive -DestinationPath $runtime -Force
} finally {
    Pop-Location
}
