param(
  [int]$Port = 38945,
  [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

$root = Invoke-WebRequest -Uri "http://localhost:$Port/" -UseBasicParsing -TimeoutSec 3
$html = [string]$root.Content

$token = ""
$nameFirst = [regex]::Match($html, '<meta[^>]+name=["'']yuizaki-control-token["''][^>]+content=["'']([^"'']+)["''][^>]*>', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
if ($nameFirst.Success) {
  $token = $nameFirst.Groups[1].Value.Trim()
} else {
  $contentFirst = [regex]::Match($html, '<meta[^>]+content=["'']([^"'']+)["''][^>]+name=["'']yuizaki-control-token["''][^>]*>', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
  if ($contentFirst.Success) {
    $token = $contentFirst.Groups[1].Value.Trim()
  }
}

$origin = ""
if ($token) {
  $headers = @{ Authorization = "Bearer $token" }
  $envCheck = Invoke-RestMethod -Uri "http://localhost:$Port/api/system/env-check" -Headers $headers -TimeoutSec 5
  if ($envCheck.pythonApiOrigin) {
    $origin = [string]$envCheck.pythonApiOrigin
  }
}

$hostName = ""
$portText = ""
if ($origin) {
  try {
    $uri = [Uri]$origin
    $hostName = $uri.Host
    $portText = [string]$uri.Port
  } catch {
    $hostName = ""
    $portText = ""
  }
}

$line = "$token|$hostName|$portText|$origin"
if ($OutputPath) {
  Set-Content -LiteralPath $OutputPath -Value $line -NoNewline
} else {
  Write-Output $line
}
