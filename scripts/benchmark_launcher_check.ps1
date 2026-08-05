param(
  [double]$MaxSeconds = 15
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $projectRoot 'YuizakiLauncher.exe'

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
  throw "Launcher not found: $launcher"
}

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
& $launcher --check --no-mcp --no-qdrant --no-open --no-show-pet
$exitCode = $LASTEXITCODE
$stopwatch.Stop()

$elapsed = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
Write-Host "Launcher preflight: ${elapsed}s (limit: ${MaxSeconds}s)"

if ($exitCode -ne 0) {
  throw "Launcher preflight failed with exit code $exitCode"
}
if ($stopwatch.Elapsed.TotalSeconds -gt $MaxSeconds) {
  throw "Launcher preflight exceeded ${MaxSeconds}s: ${elapsed}s"
}
