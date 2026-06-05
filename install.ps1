# VM Agent MCP - Windows installer.
#   irm https://raw.githubusercontent.com/CrazyMan28/vm-agent-mcp/main/install.ps1 | iex
#
# Installs uv + Tailscale (if missing), writes %USERPROFILE%\.vm-agent\config.yaml, and
# runs vm-agent as a Scheduled Task at logon with highest privileges so it has admin
# rights AND can see the interactive desktop (screenshots + mouse/keyboard work).
# Prints the one-liner to register this VM on your dev box.
#
# Optional env knobs (set before running):
#   $env:VM_AGENT_TOKEN   use this bearer token instead of generating one
#   $env:TS_AUTHKEY       bring Tailscale up unattended with this auth key
#   $env:VM_AGENT_PORT    listen port (default 8800)
#   $env:VM_AGENT_REF     git ref / branch (default main)

$ErrorActionPreference = 'Stop'
$Repo = 'https://github.com/CrazyMan28/vm-agent-mcp'
$Ref  = if ($env:VM_AGENT_REF) { $env:VM_AGENT_REF } else { 'main' }
$Port = if ($env:VM_AGENT_PORT) { $env:VM_AGENT_PORT } else { '8800' }
$AppDir = Join-Path $env:USERPROFILE '.vm-agent\app'
$CfgDir = Join-Path $env:USERPROFILE '.vm-agent'
$Cfg    = Join-Path $CfgDir 'config.yaml'

function Say($m)  { Write-Host "[vm-agent] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[vm-agent] $m" -ForegroundColor Yellow }

# ---- self-elevate -------------------------------------------------------------
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $admin) {
  Say 'Elevating to Administrator…'
  $self = $MyInvocation.MyCommand.Definition
  if ($self -and (Test-Path $self)) {
    Start-Process powershell "-NoProfile -ExecutionPolicy Bypass -File `"$self`"" -Verb RunAs
  } else {
    # piped from irm | iex: re-fetch elevated
    Start-Process powershell "-NoProfile -ExecutionPolicy Bypass -Command `"irm $Repo/raw/$Ref/install.ps1 | iex`"" -Verb RunAs
  }
  return
}

# ---- Tailscale ----------------------------------------------------------------
if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
  Say 'Installing Tailscale…'
  winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements
  $env:Path += ';C:\Program Files\Tailscale'
}
try { tailscale ip -4 2>$null | Out-Null } catch {}
if ($LASTEXITCODE -ne 0 -or -not (tailscale ip -4 2>$null)) {
  if ($env:TS_AUTHKEY) { Say 'Bringing Tailscale up with auth key…'; tailscale up --authkey $env:TS_AUTHKEY }
  else { Say 'Bringing Tailscale up (a browser will open to authenticate)…'; tailscale up }
}
$TsIp = (tailscale ip -4 2>$null | Select-Object -First 1)
if (-not $TsIp) { Warn 'Could not detect Tailscale IP yet — finish "tailscale up" and read it later.' }

# ---- uv -----------------------------------------------------------------------
$Uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (-not (Test-Path $Uv) -and -not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Say 'Installing uv…'
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
}
if (-not (Test-Path $Uv)) { $Uv = (Get-Command uv).Source }

# ---- fetch / update app -------------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Say 'Installing Git…'; winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
  $env:Path += ';C:\Program Files\Git\cmd'
}
if (Test-Path (Join-Path $AppDir '.git')) {
  Say 'Updating existing checkout…'
  git -C $AppDir fetch --depth 1 origin $Ref; git -C $AppDir reset --hard FETCH_HEAD
} else {
  Say "Cloning $Repo…"
  if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
  New-Item -ItemType Directory -Force -Path (Split-Path $AppDir) | Out-Null
  git clone --depth 1 --branch $Ref $Repo $AppDir
}
Say 'Resolving Python environment (uv sync)…'
Push-Location $AppDir; & $Uv sync; Pop-Location

# ---- token + config -----------------------------------------------------------
$Token = $env:VM_AGENT_TOKEN
if (-not $Token -and (Test-Path $Cfg)) {
  $Token = (Select-String -Path $Cfg -Pattern 'bearer_token:\s*(.+)').Matches.Groups[1].Value.Trim()
}
if (-not $Token) {
  $bytes = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $Token = -join ($bytes | ForEach-Object { $_.ToString('x2') })
}
New-Item -ItemType Directory -Force -Path $CfgDir | Out-Null
@"
bearer_token: $Token
mcp_host: 0.0.0.0
mcp_port: $Port
max_output_chars: 100000
"@ | Set-Content -Path $Cfg -Encoding ASCII
Say "Wrote $Cfg"

# ---- Scheduled Task (logon, elevated, interactive desktop) --------------------
Say 'Registering scheduled task…'
$action = New-ScheduledTaskAction -Execute $Uv -Argument 'run vm-agent-mcp' -WorkingDirectory $AppDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'vm-agent-mcp' -Action $action -Trigger $trigger `
              -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'vm-agent-mcp'

# ---- firewall -----------------------------------------------------------------
if (-not (Get-NetFirewallRule -DisplayName 'vm-agent-mcp' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName 'vm-agent-mcp' -Direction Inbound -LocalPort $Port -Protocol TCP -Action Allow | Out-Null
}

# ---- verify + print -----------------------------------------------------------
Start-Sleep -Seconds 5
try {
  Invoke-RestMethod -Headers @{Authorization = "Bearer $Token"} "http://127.0.0.1:$Port/health" | Out-Null
  Say 'Server is up and healthy.'
} catch { Warn "Health check failed — check Task Scheduler > vm-agent-mcp history." }

$Name = "vm-$($env:COMPUTERNAME.ToLower())"
$ipShown = if ($TsIp) { $TsIp } else { '<this-vm-tailscale-ip>' }
Write-Host ''
Say '=========================================================================='
Say ' VM Agent is installed. Run THIS on your dev box to connect to this VM:'
Write-Host ''
Write-Host "  curl -fsSL $Repo/raw/$Ref/client-setup.sh | bash -s -- \"
Write-Host "    --name $Name --url http://${ipShown}:$Port/mcp --token $Token"
Write-Host ''
Say '=========================================================================='
