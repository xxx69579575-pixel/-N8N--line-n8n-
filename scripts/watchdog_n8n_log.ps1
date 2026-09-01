# watchdog_n8n_log.ps1 — 偵測 n8n「webhook intake 層級」靜默掉訊息並寄告警。
#
# 背景：LINE webhook 用 responseMode=onReceived。若 n8n 在「啟動執行」最前端失敗
# （log: "Error in handling webhook request ... There was a problem executing the workflow"），
# 則不會存 execution、不會觸發 errorTrigger、不會回覆使用者 —— 完全靜默，且 LINE 不重送。
# 2026-06-29 就因此掉了一個檔案。此 watchdog 補上「掉訊息 → 立刻寄信通知」這條偵測線。
#
# 設計：每次由排程器叫起，掃 docker logs 自上次檢查點之後的新行；命中就 POST /notify。
# 冪等：用 state 檔記住上次掃描時間，只對「新出現」的錯誤告警，不重複。

$ErrorActionPreference = 'Stop'

$root      = 'D:\n8n\CLAUDE 實做\本地AI企業問答助理'
$container = 'ai-qa-n8n'
$apiBase   = 'http://localhost:8765'
$logDir    = Join-Path $root 'logs'
$log       = Join-Path $logDir 'watchdog_n8n.log'
$stateFile = Join-Path $logDir 'watchdog_n8n.state'   # 存上次掃描的 UTC RFC3339 時間點

# 命中即視為「intake 層級掉訊息」的特徵字串
$pattern = 'Error in handling webhook request'

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-Log($msg) {
    $ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    Add-Content -Path $log -Value "$ts  $msg" -Encoding utf8
    if ((Test-Path $log) -and ((Get-Item $log).Length -gt 2MB)) {
        $keep = Get-Content $log -Tail 2000
        Set-Content -Path $log -Value $keep -Encoding utf8
    }
}

function Send-Alert($subject, $message) {
    $payload = @{ subject = $subject; message = $message } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    Invoke-RestMethod -Uri "$apiBase/notify" -Method Post -Body $bytes `
        -ContentType 'application/json; charset=utf-8' -TimeoutSec 35 | Out-Null
}

# PowerShell 5.1 對「原生 exe」用 2>&1 時，stderr 的每一行都會被包成 ErrorRecord。
# 本腳本開頭是 $ErrorActionPreference='Stop'，於是那些 ErrorRecord 變成終止錯誤，
# 直接跳進最外層 catch —— 而 n8n 的日誌「全部」走 stderr（連 DEP0040 warning 也是），
# 所以第一行就會炸掉，永遠走不到推進 state 檔那行。
# 2026-06-29 ~ 2026-09-01 期間本 watchdog 因此完全失效（log: OK 0 筆 / ERROR 8630 筆）。
# 修法：只在這個呼叫內把 EAP 降為 Continue，並把 ErrorRecord 攤平回字串；
# 真正的失敗改用 $LASTEXITCODE 判斷（容器不存在、docker 沒起來等）。
function Get-ContainerLogLines($since) {
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $raw = & docker logs --since $since -t $container 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEAP
    }
    if ($code -ne 0) { throw "docker logs 失敗 (exit $code)：容器 '$container' 可能不存在或 Docker 未啟動" }
    return @($raw | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { [string]$_ }
    })
}


try {
    # 掃描起點：上次檢查點；首次執行則回看 15 分鐘（避免漏掉剛發生的）
    $nowUtc = (Get-Date).ToUniversalTime()
    if (Test-Path $stateFile) {
        $since = (Get-Content $stateFile -Raw).Trim()
    } else {
        $since = $nowUtc.AddMinutes(-15).ToString('yyyy-MM-ddTHH:mm:ssZ')
    }

    # 防禦：檢查點若過舊（watchdog 曾長時間失效／機器關機多日），最多只回看 60 分鐘。
    # 否則一次掃進數週日誌，既慢又會對早已過期的事件洗版告警。
    $maxLookback = $nowUtc.AddMinutes(-60)
    $parsedSince = [datetime]::MinValue
    $sinceOk = [datetime]::TryParse($since, [ref]$parsedSince)
    if ((-not $sinceOk) -or ($parsedSince.ToUniversalTime() -lt $maxLookback)) {
        Write-Log "WARN  檢查點 '$since' 過舊或無法解析，截斷為回看 60 分鐘"
        $since = $maxLookback.ToString('yyyy-MM-ddTHH:mm:ssZ')
    }

    # docker logs --since 取自 $since 之後、含時間戳。n8n 日誌走 stderr，
    # 由 Get-ContainerLogLines 安全合併（見上方註解）。
    $lines = @(Get-ContainerLogLines $since | Select-String -Pattern $pattern -SimpleMatch)

    $checkpoint = $nowUtc.ToString('yyyy-MM-ddTHH:mm:ssZ')

    if ($lines -and $lines.Count -gt 0) {
        $count = $lines.Count
        $detail = ($lines | ForEach-Object { $_.Line }) -join "`n"
        $body = @"
n8n 偵測到 $count 筆 webhook intake 層級失敗（訊息被靜默丟棄，LINE 不會重送）。
使用者上傳的檔案/提問可能已遺失，請主動聯繫對方重傳。

掃描區間: $since ~ $checkpoint (UTC)
特徵: $pattern

原始日誌:
$detail

排查指令:
  docker logs --since $since -t $container | Select-String '$pattern'
"@
        Send-Alert "[AI-QA] ⚠️ 偵測到 $count 筆掉訊息（webhook intake 失敗）" $body
        Write-Log "ALERT sent: $count intake-failure(s) in [$since ~ $checkpoint]"
    } else {
        Write-Log "OK    no intake failures in [$since ~ $checkpoint]"
    }

    # 推進檢查點（即使這次失敗送信，下次也不重複告警同一批）
    Set-Content -Path $stateFile -Value $checkpoint -Encoding ascii
}
catch {
    Write-Log ("ERROR " + $_.Exception.Message)
    exit 1
}
