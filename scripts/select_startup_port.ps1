param(
  [ValidateSet("backend", "control", "renderer", "stop-backend", "stop-control")]
  [string]$Mode,
  [int]$PreferredPort,
  [string]$FallbackPorts = "",
  [string]$ProjectRoot = ""
)

$ErrorActionPreference = "SilentlyContinue"

function Test-TcpPort([int]$Port) {
  foreach ($hostName in @("127.0.0.1", "::1")) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
      $connect = $client.BeginConnect($hostName, $Port, $null, $null)
      if (-not $connect.AsyncWaitHandle.WaitOne(250)) {
        continue
      }
      try {
        $client.EndConnect($connect)
        return $true
      } catch {
      }
    } finally {
      $client.Close()
    }
  }
  return $false
}

function Get-ListeningProcessIds([int]$Port) {
  $ids = @()
  $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
  try {
    $lines = & netstat -ano -p tcp 2>$null
    foreach ($line in $lines) {
      if ($line -match $pattern) {
        $id = [int]$Matches[1]
        if ($id -gt 0 -and -not $ids.Contains($id)) {
          $ids += $id
        }
      }
    }
  } catch {
  }
  return $ids
}

function Test-BackendPing([int]$Port) {
  try {
    $response = Invoke-WebRequest -Uri ("http://localhost:{0}/api/ping" -f $Port) -UseBasicParsing -TimeoutSec 3
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
  } catch {
    return $false
  }
}

function Get-ProcessCommandLine([int]$ProcessId) {
  try {
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $ProcessId)
    if ($process) {
      return [string]$process.CommandLine
    }
  } catch {
  }
  return ""
}

function Test-YuizakiBackendProcess([int]$ProcessId) {
  $needle = ($ProjectRoot -replace '/', '\').TrimEnd('\')
  $currentId = $ProcessId
  for ($depth = 0; $depth -lt 5 -and $currentId -gt 0; $depth++) {
    try {
      $process = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $currentId)
      if (-not $process) {
        return $false
      }

      $commandLine = [string]$process.CommandLine
      $normalized = $commandLine -replace '/', '\'
      $executablePath = ([string]$process.ExecutablePath) -replace '/', '\'
      if (
        $normalized -match 'uvicorn\s+app:app' -and
        ($normalized.Contains($needle) -or $executablePath.Contains("$needle\python\.venv\Scripts\python.exe"))
      ) {
        return $true
      }
      if ($normalized.Contains($needle) -or $normalized -match 'run_backend_dev\.bat') {
        return $true
      }
      $currentId = [int]$process.ParentProcessId
    } catch {
      return $false
    }
  }
  return $false
}

function Test-YuizakiElectronProcess([int]$ProcessId) {
  $needle = ($ProjectRoot -replace '/', '\').TrimEnd('\')
  $currentId = $ProcessId
  for ($depth = 0; $depth -lt 5 -and $currentId -gt 0; $depth++) {
    try {
      $process = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $currentId)
      if (-not $process) {
        return $false
      }

      $commandLine = ([string]$process.CommandLine) -replace '/', '\'
      if (
        $commandLine.Contains($needle) -and
        ($commandLine -match '\\electron\\node_modules\\electron\\dist\\electron\.exe' -or
          $commandLine -match '\\electron\\cli\.js' -or
          $commandLine -match 'run_electron_app\.bat')
      ) {
        return $true
      }
      $currentId = [int]$process.ParentProcessId
    } catch {
      return $false
    }
  }
  return $false
}

function Test-YuizakiRendererProcess([int]$ProcessId) {
  $needle = ($ProjectRoot -replace '/', '\').TrimEnd('\')
  $currentId = $ProcessId
  for ($depth = 0; $depth -lt 5 -and $currentId -gt 0; $depth++) {
    try {
      $process = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $currentId)
      if (-not $process) {
        return $false
      }

      $commandLine = ([string]$process.CommandLine) -replace '/', '\'
      if (
        $commandLine.Contains($needle) -and
        ($commandLine -match '\\vite\\bin\\vite\.js' -or
          $commandLine -match 'run_renderer_dev\.bat')
      ) {
        return $true
      }
      $currentId = [int]$process.ParentProcessId
    } catch {
      return $false
    }
  }
  return $false
}

function Stop-StaleYuizakiBackendOnPort([int]$Port) {
  $targets = @()
  foreach ($owner in (Get-ListeningProcessIds $Port)) {
    if ($owner -le 0) {
      continue
    }
    if (-not (Test-YuizakiBackendProcess $owner)) {
      continue
    }

    $currentId = $owner
    for ($depth = 0; $depth -lt 6 -and $currentId -gt 0; $depth++) {
      try {
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $currentId)
        if (-not $process) {
          break
        }

        $commandLine = ([string]$process.CommandLine) -replace '/', '\'
        $executablePath = ([string]$process.ExecutablePath) -replace '/', '\'
        if (
          $currentId -eq $owner -or
          $commandLine.Contains(($ProjectRoot -replace '/', '\').TrimEnd('\')) -or
          $commandLine -match 'run_backend_dev\.bat' -or
          $executablePath.Contains((($ProjectRoot -replace '/', '\').TrimEnd('\')) + '\python\.venv\Scripts\python.exe')
        ) {
          if (-not $targets.Contains($currentId)) {
            $targets += $currentId
          }
        }
        $currentId = [int]$process.ParentProcessId
      } catch {
        break
      }
    }
  }

  foreach ($target in ($targets | Sort-Object -Descending)) {
    try {
      Stop-Process -Id $target -Force
    } catch {
    }
  }

  $deadline = (Get-Date).AddSeconds(5)
  while ((Get-Date) -lt $deadline) {
    if (-not (Test-TcpPort $Port)) {
      return $true
    }
    Start-Sleep -Milliseconds 250
  }
  return -not (Test-TcpPort $Port)
}

function Stop-StaleYuizakiControlOnPort([int]$Port) {
  foreach ($owner in (Get-ListeningProcessIds $Port)) {
    if ($owner -le 0) {
      continue
    }
    if (-not (Test-YuizakiElectronProcess $owner)) {
      continue
    }
    try {
      Stop-Process -Id $owner -Force
    } catch {
    }
  }

  $deadline = (Get-Date).AddSeconds(8)
  while ((Get-Date) -lt $deadline) {
    if (-not (Test-TcpPort $Port)) {
      return $true
    }
    Start-Sleep -Milliseconds 250
  }
  return -not (Test-TcpPort $Port)
}

function Stop-StaleYuizakiRendererOnPort([int]$Port) {
  foreach ($owner in (Get-ListeningProcessIds $Port)) {
    if ($owner -le 0) {
      continue
    }
    if (-not (Test-YuizakiRendererProcess $owner)) {
      continue
    }
    try {
      Stop-Process -Id $owner -Force
    } catch {
    }
  }

  $deadline = (Get-Date).AddSeconds(5)
  while ((Get-Date) -lt $deadline) {
    if (-not (Test-TcpPort $Port)) {
      return $true
    }
    Start-Sleep -Milliseconds 250
  }
  return -not (Test-TcpPort $Port)
}

$ports = @($PreferredPort)
$ports += $FallbackPorts -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | ForEach-Object { [int]$_ }
$seen = @{}

if ($Mode -eq "stop-backend") {
  if (Stop-StaleYuizakiBackendOnPort $PreferredPort) {
    Write-Output ("{0}|stopped" -f $PreferredPort)
    exit 0
  }
  Write-Output ("{0}|blocked" -f $PreferredPort)
  exit 2
}

if ($Mode -eq "stop-control") {
  if (Stop-StaleYuizakiControlOnPort $PreferredPort) {
    Write-Output ("{0}|stopped" -f $PreferredPort)
    exit 0
  }
  Write-Output ("{0}|blocked" -f $PreferredPort)
  exit 2
}

foreach ($port in $ports) {
  if ($seen.ContainsKey($port)) {
    continue
  }
  $seen[$port] = $true

  if ($Mode -eq "backend" -and (Test-BackendPing $port)) {
    Write-Output ("{0}|healthy" -f $port)
    exit 0
  }

  if (-not (Test-TcpPort $port)) {
    if ($port -eq $PreferredPort) {
      Write-Output ("{0}|free" -f $port)
    } else {
      Write-Output ("{0}|fallback" -f $port)
    }
    exit 0
  }

  if ($Mode -eq "backend" -and (Stop-StaleYuizakiBackendOnPort $port)) {
    if ($port -eq $PreferredPort) {
      Write-Output ("{0}|freed" -f $port)
    } else {
      Write-Output ("{0}|fallback" -f $port)
    }
    exit 0
  }

  if ($Mode -eq "control" -and $port -eq $PreferredPort -and (Stop-StaleYuizakiControlOnPort $port)) {
    Write-Output ("{0}|freed" -f $port)
    exit 0
  }

  if ($Mode -eq "renderer" -and (Stop-StaleYuizakiRendererOnPort $port)) {
    if ($port -eq $PreferredPort) {
      Write-Output ("{0}|freed" -f $port)
    } else {
      Write-Output ("{0}|fallback" -f $port)
    }
    exit 0
  }
}

Write-Output ("{0}|blocked" -f $PreferredPort)
exit 2
