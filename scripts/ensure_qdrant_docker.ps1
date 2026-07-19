param(
  [string]$ProjectRoot = "",
  [string]$SettingsPath = "",
  [string]$EnvPath = "",
  [int]$TimeoutSeconds = 120,
  [string]$DockerDesktopPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe",
  [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
  $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
if (-not $SettingsPath) {
  $SettingsPath = Join-Path $ProjectRoot "python\config\settings.json"
}
if (-not $EnvPath) {
  $EnvPath = Join-Path $ProjectRoot "python\.env"
}

function Write-Info([string]$Message) {
  Write-Host "[INFO]  $Message"
}

function Write-Warn([string]$Message) {
  Write-Host "[WARN]  $Message"
}

function Write-Err([string]$Message) {
  Write-Host "[ERROR] $Message"
}

function Read-DotEnv([string]$Path) {
  $values = @{}
  if (-not (Test-Path -LiteralPath $Path)) {
    return $values
  }

  foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) {
      continue
    }
    $idx = $trimmed.IndexOf("=")
    if ($idx -le 0) {
      continue
    }
    $key = $trimmed.Substring(0, $idx).Trim()
    $value = $trimmed.Substring($idx + 1).Trim()
    if ($value.Length -ge 2) {
      $first = $value.Substring(0, 1)
      $last = $value.Substring($value.Length - 1, 1)
      if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
        $value = $value.Substring(1, $value.Length - 2)
      }
    }
    $values[$key] = $value
  }
  return $values
}

function Convert-ToBool([object]$Value, [bool]$Default) {
  if ($null -eq $Value) {
    return $Default
  }
  if ($Value -is [bool]) {
    return [bool]$Value
  }
  $text = ([string]$Value).Trim().ToLowerInvariant()
  if ($text -in @("1", "true", "yes", "y", "on")) {
    return $true
  }
  if ($text -in @("0", "false", "no", "n", "off")) {
    return $false
  }
  return $Default
}

function Get-JsonProperty([object]$Object, [string]$Name) {
  if ($null -eq $Object) {
    return $null
  }
  $prop = $Object.PSObject.Properties[$Name]
  if ($null -eq $prop) {
    return $null
  }
  return $prop.Value
}

function Set-ConfigValue([hashtable]$Config, [string]$Key, [object]$Value) {
  if ($null -ne $Value) {
    $Config[$Key] = $Value
  }
}

function Get-EffectiveConfig {
  $config = @{
    backend = "inmemory"
    qdrant_url = "http://127.0.0.1:6333"
    qdrant_api_key = ""
    qdrant_auto_start = $true
    qdrant_docker_image = "qdrant/qdrant:v1.18.3"
    qdrant_docker_container = "yuizaki-qdrant"
    qdrant_docker_volume = "yuizaki-qdrant-storage"
  }

  $envValues = Read-DotEnv $EnvPath
  Set-ConfigValue $config "backend" $envValues["MEMORY_BACKEND"]
  Set-ConfigValue $config "qdrant_url" $envValues["QDRANT_URL"]
  Set-ConfigValue $config "qdrant_api_key" $envValues["QDRANT_API_KEY"]
  if ($envValues.ContainsKey("QDRANT_AUTO_START")) {
    $config["qdrant_auto_start"] = Convert-ToBool $envValues["QDRANT_AUTO_START"] $true
  }
  Set-ConfigValue $config "qdrant_docker_image" $envValues["QDRANT_DOCKER_IMAGE"]
  Set-ConfigValue $config "qdrant_docker_container" $envValues["QDRANT_DOCKER_CONTAINER"]
  Set-ConfigValue $config "qdrant_docker_volume" $envValues["QDRANT_DOCKER_VOLUME"]

  if (Test-Path -LiteralPath $SettingsPath) {
    try {
      $settings = Get-Content -LiteralPath $SettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
      $memory = Get-JsonProperty $settings "memory"
      if ($null -ne $memory) {
        Set-ConfigValue $config "backend" (Get-JsonProperty $memory "backend")
        Set-ConfigValue $config "qdrant_url" (Get-JsonProperty $memory "qdrant_url")
        Set-ConfigValue $config "qdrant_api_key" (Get-JsonProperty $memory "qdrant_api_key")
        $autoStart = Get-JsonProperty $memory "qdrant_auto_start"
        if ($null -ne $autoStart) {
          $config["qdrant_auto_start"] = Convert-ToBool $autoStart $true
        }
        Set-ConfigValue $config "qdrant_docker_image" (Get-JsonProperty $memory "qdrant_docker_image")
        Set-ConfigValue $config "qdrant_docker_container" (Get-JsonProperty $memory "qdrant_docker_container")
        Set-ConfigValue $config "qdrant_docker_volume" (Get-JsonProperty $memory "qdrant_docker_volume")
      }
    } catch {
      Write-Warn "Unable to read memory settings; falling back to .env/default Qdrant settings."
    }
  }

  foreach ($pair in @{
    MEMORY_BACKEND = "backend"
    QDRANT_URL = "qdrant_url"
    QDRANT_API_KEY = "qdrant_api_key"
    QDRANT_DOCKER_IMAGE = "qdrant_docker_image"
    QDRANT_DOCKER_CONTAINER = "qdrant_docker_container"
    QDRANT_DOCKER_VOLUME = "qdrant_docker_volume"
  }.GetEnumerator()) {
    $value = [Environment]::GetEnvironmentVariable($pair.Key, "Process")
    if ($null -ne $value -and $value -ne "") {
      $config[$pair.Value] = $value
    }
  }
  $envAutoStart = [Environment]::GetEnvironmentVariable("QDRANT_AUTO_START", "Process")
  if ($null -ne $envAutoStart -and $envAutoStart -ne "") {
    $config["qdrant_auto_start"] = Convert-ToBool $envAutoStart $true
  }

  $config["backend"] = ([string]$config["backend"]).Trim().ToLowerInvariant()
  $config["qdrant_url"] = ([string]$config["qdrant_url"]).Trim().TrimEnd("/")
  if (-not $config["qdrant_url"]) {
    $config["qdrant_url"] = "http://127.0.0.1:6333"
  }
  foreach ($key in @("qdrant_docker_image", "qdrant_docker_container", "qdrant_docker_volume")) {
    $config[$key] = ([string]$config[$key]).Trim()
  }
  if (-not $config["qdrant_docker_image"]) {
    $config["qdrant_docker_image"] = "qdrant/qdrant:v1.18.3"
  }
  if (-not $config["qdrant_docker_container"]) {
    $config["qdrant_docker_container"] = "yuizaki-qdrant"
  }
  if (-not $config["qdrant_docker_volume"]) {
    $config["qdrant_docker_volume"] = "yuizaki-qdrant-storage"
  }
  return $config
}

function Resolve-QdrantUri([string]$Url) {
  if ($Url -eq ":memory:") {
    return $null
  }
  $candidate = $Url
  if ($candidate -notmatch "^[a-zA-Z][a-zA-Z0-9+.-]*://") {
    $candidate = "http://$candidate"
  }
  return [Uri]$candidate
}

function Test-LocalQdrantHost([string]$HostName) {
  $cleanHost = $HostName.Trim().Trim("[", "]").ToLowerInvariant()
  return $cleanHost -in @("127.0.0.1", "localhost", "::1", "0.0.0.0")
}

function Test-QdrantReady([string]$BaseUrl, [string]$ApiKey) {
  $headers = @{}
  if ($ApiKey) {
    $headers["api-key"] = $ApiKey
  }
  try {
    $response = Invoke-WebRequest -Uri "$BaseUrl/collections" -Headers $headers -UseBasicParsing -TimeoutSec 5
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
  } catch {
    return $false
  }
}

function Test-DockerReady {
  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    & docker info > $null 2> $null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  } finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
}

function Ensure-DockerReady([int]$WaitSeconds) {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Err "Docker CLI is not available in PATH. Install Docker Desktop before using local Qdrant auto-start."
    return $false
  }
  if (Test-DockerReady) {
    return $true
  }
  if (Test-Path -LiteralPath $DockerDesktopPath) {
    Write-Info "Docker daemon is not ready; starting Docker Desktop."
    Start-Process -FilePath $DockerDesktopPath -WindowStyle Hidden
  } else {
    Write-Err "Docker daemon is not running and Docker Desktop was not found at $DockerDesktopPath."
    return $false
  }

  $deadline = (Get-Date).AddSeconds($WaitSeconds)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    if (Test-DockerReady) {
      return $true
    }
  }
  Write-Err "Docker daemon did not become ready within ${WaitSeconds}s."
  return $false
}

function Invoke-Docker {
  param([string[]]$DockerArgs)
  & docker @DockerArgs
  if ($LASTEXITCODE -ne 0) {
    throw "docker $($DockerArgs -join ' ') failed"
  }
}

try {
  $config = Get-EffectiveConfig
  if ($config["backend"] -ne "qdrant") {
    Write-Info "Qdrant Docker auto-start skipped: memory backend is '$($config["backend"])'."
    exit 0
  }
  if (-not [bool]$config["qdrant_auto_start"]) {
    Write-Info "Qdrant Docker auto-start skipped: qdrant_auto_start is disabled."
    exit 0
  }
  if ($config["qdrant_url"] -eq ":memory:") {
    Write-Info "Qdrant Docker auto-start skipped: in-process Qdrant memory mode is configured."
    exit 0
  }

  try {
    $uri = Resolve-QdrantUri ([string]$config["qdrant_url"])
  } catch {
    Write-Err "Qdrant URL is invalid: $($config["qdrant_url"])"
    exit 1
  }
  if ($null -eq $uri) {
    Write-Info "Qdrant Docker auto-start skipped: in-process Qdrant memory mode is configured."
    exit 0
  }
  if ($uri.Scheme -ne "http") {
    Write-Info "Qdrant Docker auto-start skipped: URL scheme '$($uri.Scheme)' is not a local Docker HTTP endpoint."
    exit 0
  }
  if (-not (Test-LocalQdrantHost $uri.Host)) {
    Write-Info "Qdrant Docker auto-start skipped: Qdrant URL points to remote host '$($uri.Host)'."
    exit 0
  }

  $port = if ($uri.IsDefaultPort) { 6333 } else { $uri.Port }
  $baseUrl = "http://127.0.0.1:$port"
  $apiKey = [string]$config["qdrant_api_key"]
  $image = [string]$config["qdrant_docker_image"]
  $container = [string]$config["qdrant_docker_container"]
  $volume = [string]$config["qdrant_docker_volume"]

  if ($CheckOnly) {
    Write-Info "Qdrant Docker config check passed for $baseUrl using container '$container'."
    exit 0
  }

  if (Test-QdrantReady $baseUrl $apiKey) {
    Write-Info "Qdrant is already reachable at $baseUrl."
    exit 0
  }

  if (-not (Ensure-DockerReady $TimeoutSeconds)) {
    exit 1
  }

  $filter = "name=^/$container$"
  $line = & docker ps -a --filter $filter --format "{{.ID}}|{{.State}}" 2>$null | Select-Object -First 1
  if ($line) {
    $parts = ([string]$line).Split("|", 2)
    $state = if ($parts.Count -gt 1) { $parts[1] } else { "" }
    if ($state -eq "running") {
      Write-Info "Qdrant container '$container' is running; waiting for readiness."
    } else {
      Write-Info "Starting existing Qdrant container '$container'."
      Invoke-Docker -DockerArgs @("start", $container)
    }
  } else {
    Write-Info "Creating Qdrant container '$container' from image '$image'."
    Invoke-Docker -DockerArgs @("volume", "create", $volume) | Out-Null
    $runArgs = @("run", "-d", "--name", $container, "-p", "${port}:6333", "-v", "${volume}:/qdrant/storage", $image)
    Invoke-Docker -DockerArgs $runArgs
  }

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-QdrantReady $baseUrl $apiKey) {
      Write-Info "Qdrant is ready at $baseUrl."
      exit 0
    }
    Start-Sleep -Seconds 2
  }
  Write-Err "Qdrant container '$container' did not become ready at $baseUrl within ${TimeoutSeconds}s."
  exit 1
} catch {
  Write-Err $_.Exception.Message
  exit 1
}
