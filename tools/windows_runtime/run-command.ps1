# 只运行指定项目的虚拟环境程序，并为该次调用临时提供 FFmpeg DLL 搜索路径。
param(
    [Parameter(Mandatory = $true)][string]$ProjectDir,
    [Parameter(Mandatory = $true)][string]$Command,
    [string[]]$CommandArgs
)
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$PreviousPath = $env:PATH
$CommandExitCode = 1
Push-Location -LiteralPath $ProjectDir
try {
    $Manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "ffmpeg-source.json") | ConvertFrom-Json
    $FFmpegBin = Join-Path (Join-Path $Repo ".cache/ffmpeg/runtime") ($Manifest.directory + "/bin")
    if (!(Test-Path -LiteralPath $FFmpegBin -PathType Container)) { throw "Run setup.ps1 first: FFmpeg shared runtime missing" }
    if ($Command -notmatch '^[A-Za-z0-9_-]+$') { throw "Only environment command names are accepted" }
    $VenvBin = Join-Path $ProjectDir ".venv/Scripts"
    $Executable = Join-Path $VenvBin ($Command + ".exe")
    if (!(Test-Path -LiteralPath $Executable -PathType Leaf)) { throw "Missing environment command: $Executable" }
    $env:PATH = "$FFmpegBin;$VenvBin;$PreviousPath"
    & $Executable @CommandArgs
    $CommandExitCode = $LASTEXITCODE
} finally {
    $env:PATH = $PreviousPath
    Pop-Location
}
exit $CommandExitCode
