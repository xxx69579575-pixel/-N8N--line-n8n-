# watchdog_api.ps1 — 確保後端 api_server.py 持續在 127.0.0.1:8765 運行。
# 每次由排程器叫起：檢查 8765，未監聽就用 pythonw 脫離啟動，並寫入日誌。
# 設計為「冪等」：已在跑就只記一行 heartbeat，不會重複啟動。

$ErrorActionPreference = 'Stop'

$root    = 'D:\n8n\CLAUDE 實做\本地AI企業問答助理'
$pythonw = 'C:\Users\xx\AppData\Local\Programs\Python\Python312\pythonw.exe'
$script  = Join-Path $root 'scripts\api_server.py'
$logDir  = Join-Path $root 'logs'
$log     = Join-Path $logDir 'watchdog.log'
$outLog  = Join-Path $logDir 'api_server.out.log'
$errLog  = Join-Path $logDir 'api_server.err.log'

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-Log($msg) {
    $ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    Add-Content -Path $log -Value "$ts  $msg" -Encoding utf8
    # 控制日誌大小：超過 2MB 截半
    if ((Test-Path $log) -and ((Get-Item $log).Length -gt 2MB)) {
        $keep = Get-Content $log -Tail 2000
        Set-Content -Path $log -Value $keep -Encoding utf8
    }
}

try {
    $listening = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
    if ($listening) {
        Write-Log ("OK    8765 listening pid=" + $listening.OwningProcess)
        exit 0
    }

    if (-not (Test-Path $pythonw)) { Write-Log "FATAL pythonw not found: $pythonw"; exit 1 }
    if (-not (Test-Path $script))  { Write-Log "FATAL api_server.py not found: $script"; exit 1 }

    Write-Log "DOWN  8765 not listening — starting api_server.py ..."
    Start-Process -FilePath $pythonw -ArgumentList "`"$script`"" -WorkingDirectory $root `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog -WindowStyle Hidden

    Start-Sleep -Seconds 5
    $now = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
    if ($now) { Write-Log ("STARTED 8765 listening pid=" + $now.OwningProcess) }
    else      { Write-Log "FAIL  started process but 8765 still not listening (see api_server.err.log)" }
}
catch {
    Write-Log ("ERROR " + $_.Exception.Message)
    exit 1
}

