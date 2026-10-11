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
    $archiveValid = (Test-Path -LiteralPath $archive -PathType Leaf) -and
        ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -eq $manifest.sha256)
    if (!$archiveValid) {
        # A failed download must never become the reusable cache entry.
        $partialArchive = Join-Path $ffmpegCache ("ffmpeg-" + [guid]::NewGuid().ToString("N") + ".partial")
        try {
            Invoke-WebRequest $manifest.url -OutFile $partialArchive -UseBasicParsing
            if ((Get-FileHash -LiteralPath $partialArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.sha256) {
                throw "FFmpeg downloaded archive checksum mismatch. Verify the pinned source; the existing cache was not replaced."
            }
            Move-Item -LiteralPath $partialArchive -Destination $archive -Force
        } finally {
            if (Test-Path -LiteralPath $partialArchive -PathType Leaf) {
                Remove-Item -LiteralPath $partialArchive -Force
            }
        }
    }
    $runtime = Join-Path $ffmpegCache "runtime"
    Expand-Archive -LiteralPath $archive -DestinationPath $runtime -Force
} finally {
    Pop-Location
}
