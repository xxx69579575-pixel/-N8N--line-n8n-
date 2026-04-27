#requires -Version 5.1
<#
start_all.ps1 — boot startup orchestrator for the AI QA assistant.

Order:
  1. Wait for Docker / n8n container (port 5681)
  2. Start ngrok (stable domain → n8n) if not running
  3. Start cloudflared (random URL → api_server:8765), capture URL
  4. Write API_SERVER_BASE_URL into config/.env
  5. Restart api_server.py (so it picks up the new env var)
  6. Smoke-test all reachable endpoints

LINE webhook URL is permanent (uses ngrok stable domain) — no manual update needed
after reboots.
#>

$ErrorActionPreference = "Stop"
$ProjectRoot   = "D:\n8n\CLAUDE 實做\本地AI企業問答助理"
$EnvFile       = Join-Path $ProjectRoot "config\.env"
$ApiPort       = 8765
$N8nPort       = 5681
$NgrokDomain   = "quadruplication-satisfyingly-corrina.ngrok-free.dev"
$LogDir        = Join-Path $env:LOCALAPPDATA "ai-qa-startup"
$LogFile       = Join-Path $LogDir       "start_all.log"
$CloudflaredLog = Join-Path $env:TEMP    "cloudflared_api.log"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts $msg" | Tee-Object -FilePath $LogFile -Append | Out-Host
}

Log "=== start_all begin ==="
Set-Location $ProjectRoot

# ---------------------------------------------------------------
# 1. Wait for n8n to be reachable
# ---------------------------------------------------------------
Log "[1/6] Waiting for n8n on localhost:$N8nPort ..."
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
    try {
        $r = Invoke-WebRequest "http://localhost:$N8nPort/healthz" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; Log "      n8n ready after $i sec"; break }
    } catch { Start-Sleep -Seconds 2 }
}
if (-not $ready) { Log "      WARN: n8n still not responding after 180s — continuing anyway" }

# ---------------------------------------------------------------
# 2. Start ngrok (n8n tunnel, stable domain)
# ---------------------------------------------------------------
$ngrok = Get-Process ngrok -ErrorAction SilentlyContinue
if ($ngrok) {
    Log "[2/6] ngrok already running (PID $($ngrok.Id -join ','))"
} else {
    Log "[2/6] Starting ngrok (n8n tunnel)..."
    Start-Process -FilePath "ngrok" -ArgumentList "start","n8n" -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 4
}

# ---------------------------------------------------------------
# 3. Start cloudflared (api_server tunnel, random URL)
# ---------------------------------------------------------------
$cf = Get-Process cloudflared -ErrorAction SilentlyContinue
if ($cf) {
    Log "[3/6] Stopping old cloudflared (PID $($cf.Id -join ',')) — needs fresh URL log"
    $cf | Stop-Process -Force
    Start-Sleep -Seconds 2
}
if (Test-Path $CloudflaredLog) { Remove-Item $CloudflaredLog -Force -ErrorAction SilentlyContinue }
Log "[3/6] Starting cloudflared (--url http://localhost:$ApiPort)..."
Start-Process -FilePath "cloudflared" `
    -ArgumentList "tunnel","--no-autoupdate","--url","http://localhost:$ApiPort","--logfile",$CloudflaredLog `
    -WindowStyle Hidden | Out-Null

$cfUrl = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $CloudflaredLog) {
        $m = Select-String -Path $CloudflaredLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue
        if ($m) { $cfUrl = $m.Matches[0].Value; break }
    }
}
if (-not $cfUrl) { Log "      ERROR: cloudflared URL not captured. See $CloudflaredLog"; exit 1 }
Log "      cloudflared URL: $cfUrl"

# ---------------------------------------------------------------
# 4. Update .env API_SERVER_BASE_URL (preserve UTF-8 BOM for PS5.1 read compat)
# ---------------------------------------------------------------
Log "[4/6] Updating API_SERVER_BASE_URL in $EnvFile"
$lines = Get-Content $EnvFile -Encoding UTF8
$updated = @()
$found = $false
foreach ($line in $lines) {
    if ($line -match '^API_SERVER_BASE_URL=') {
        $updated += "API_SERVER_BASE_URL=$cfUrl"
        $found = $true
    } else {
        $updated += $line
    }
}
if (-not $found) { $updated += "API_SERVER_BASE_URL=$cfUrl" }
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($EnvFile, ($updated -join "`r`n") + "`r`n", $utf8Bom)

# ---------------------------------------------------------------
# 5. Restart api_server (kill + relaunch so it reads new .env)
# ---------------------------------------------------------------
Log "[5/6] Restarting api_server.py..."
$conns = Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    $procIds = $conns | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique
    foreach ($procId in $procIds) {
        try { Stop-Process -Id $procId -Force -ErrorAction Stop; Log "      stopped existing PID $procId" } catch {}
    }
    Start-Sleep -Seconds 1
}
Start-Process -FilePath "python" `
    -ArgumentList "scripts\api_server.py" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden | Out-Null
Start-Sleep -Seconds 2

# ---------------------------------------------------------------
# 6. Smoke test
# ---------------------------------------------------------------
Log "[6/6] Smoke testing endpoints..."
$apiOk = $false
try {
    $r = Invoke-WebRequest "http://localhost:$ApiPort/health" -UseBasicParsing -TimeoutSec 5
    if ($r.StatusCode -eq 200) { $apiOk = $true }
} catch {}
Log "      api_server localhost: $(if ($apiOk) { 'OK' } else { 'FAILED' })"

$apiPubOk = $false
try {
    $r = Invoke-WebRequest "$cfUrl/health" -UseBasicParsing -TimeoutSec 8
    if ($r.StatusCode -eq 200) { $apiPubOk = $true }
} catch {}
Log "      api_server public:    $(if ($apiPubOk) { 'OK' } else { 'FAILED' }) ($cfUrl)"

$n8nPubOk = $false
try {
    $r = Invoke-WebRequest "https://$NgrokDomain/webhook/line-qa" -Method POST -Body '{"events":[]}' -ContentType 'application/json' -UseBasicParsing -TimeoutSec 8
    if ($r.StatusCode -eq 200) { $n8nPubOk = $true }
} catch {}
Log "      n8n webhook public:   $(if ($n8nPubOk) { 'OK' } else { 'FAILED' }) (https://$NgrokDomain/webhook/line-qa)"

Log "=== start_all done ==="
