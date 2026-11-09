<#
.SYNOPSIS
  Start, stop, restart, or check the local ResearchRelay service (Windows PowerShell).
.EXAMPLE
  .\scripts\researchrelay.ps1 restart
  .\scripts\researchrelay.ps1 stop -Port 8001
.NOTES
  Set $env:RESEARCHRELAY_ENV to use a mamba env other than "researchrelay".
#>
param(
  [Parameter(Mandatory = $true, Position = 0)]
  [ValidateSet('start', 'stop', 'restart', 'status', 'run')]
  [string]$Action,
  [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root '.runtime\serve.log'
$envName = if ($env:RESEARCHRELAY_ENV) { $env:RESEARCHRELAY_ENV } else { 'researchrelay' }

function Get-ServicePids {
  $ids = @()
  $ids += Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { $_.OwningProcess }
  $pattern = "researchrelay\s+serve.*--port\s+$Port(\s|$)"
  $ids += Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match $pattern } |
    ForEach-Object { $_.ProcessId }
  $ids | Where-Object { $_ -and $_ -ne $PID } | Sort-Object -Unique
}

function Stop-Service {
  $ids = @(Get-ServicePids)
  if (-not $ids) { Write-Host "ResearchRelay is not running on port $Port."; return }
  # Stop twice: the auto-reload supervisor may respawn a worker after the first pass.
  foreach ($pass in 1..2) {
    foreach ($id in @(Get-ServicePids)) {
      try { Stop-Process -Id $id -Force -ErrorAction Stop }
      catch { Write-Warning "Could not stop PID ${id}: $($_.Exception.Message)" }
    }
    Start-Sleep -Milliseconds 700
  }
  if (@(Get-ServicePids)) { throw "Could not stop all processes on port $Port." }
  Write-Host "Stopped ResearchRelay on port $Port."
}

function Start-Service {
  $existing = @(Get-ServicePids)
  if ($existing) { Write-Host "Already running on port $Port (PIDs: $($existing -join ', '))."; return }
  New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
  if (Get-Command mamba -ErrorAction SilentlyContinue) {
    $exe = 'mamba'; $argList = @('run', '-n', $envName, 'researchrelay', 'serve', '--port', $Port)
  } elseif (Get-Command researchrelay -ErrorAction SilentlyContinue) {
    $exe = 'researchrelay'; $argList = @('serve', '--port', $Port)
  } else {
    throw 'Neither mamba nor researchrelay found on PATH.'
  }
  Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err"
  foreach ($i in 1..30) {
    try {
      Invoke-WebRequest "http://127.0.0.1:$Port/workspace" -UseBasicParsing -TimeoutSec 2 | Out-Null
      Write-Host "ResearchRelay running at http://127.0.0.1:$Port/workspace (log: $log)"; return
    } catch { Start-Sleep -Seconds 1 }
  }
  throw "Did not become ready; see $log and $log.err"
}

function Run-Foreground {
  # Used by the VS Code task: kill any stale service, then serve in this terminal.
  # Closing the terminal/window ends the service; the finally block cleans up stragglers.
  Stop-Service
  Set-Location $root
  try {
    if (Get-Command mamba -ErrorAction SilentlyContinue) {
      & mamba run -n $envName researchrelay serve --port $Port
    } elseif (Get-Command researchrelay -ErrorAction SilentlyContinue) {
      & researchrelay serve --port $Port
    } else {
      throw 'Neither mamba nor researchrelay found on PATH.'
    }
  } finally {
    Stop-Service
  }
}

switch ($Action) {
  'run'     { Run-Foreground }
  'start'   { Start-Service }
  'stop'    { Stop-Service }
  'restart' { Stop-Service; Start-Service }
  'status'  {
    $ids = @(Get-ServicePids)
    if ($ids) { Write-Host "Running on port $Port (PIDs: $($ids -join ', '))." }
    else { Write-Host "Not running on port $Port." }
  }
}
