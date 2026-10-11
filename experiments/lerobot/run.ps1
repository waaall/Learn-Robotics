param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Command,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$CommandArgs
)
$ErrorActionPreference = "Stop"
$previousPath = $env:PATH
Push-Location $PSScriptRoot
try {
    $manifest = Get-Content ffmpeg-source.json | ConvertFrom-Json
    $ffmpegBin = Join-Path (Resolve-Path "../../.cache/ffmpeg/runtime") ($manifest.directory + "/bin")
    $env:PATH = "$ffmpegBin;$(Join-Path $PSScriptRoot '.venv/Scripts');$previousPath"
    $executable = Join-Path $PSScriptRoot (".venv/Scripts/" + $Command + ".exe")
    if (!(Test-Path $executable)) { throw "Missing environment command: $executable" }
    & $executable @CommandArgs
    $commandExitCode = $LASTEXITCODE
} finally {
    $env:PATH = $previousPath
    Pop-Location
}
exit $commandExitCode
