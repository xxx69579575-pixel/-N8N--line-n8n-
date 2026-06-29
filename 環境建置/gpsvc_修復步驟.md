# Group Policy Client (gpsvc) 服務逾時修復步驟

> **2026-06-29 實測結論與最終解法（優先看這段，不用重開機）**
>
> **症狀**：System 事件日誌每 5 分鐘出現 SCM 7000/7009（gpsvc 啟動逾時 30 秒），每天約 125 次。
> 本機為 **WORKGROUP（非網域）**，`gpsvc.dll` 完好（非檔案損壞）。
>
> **排查走過的彎路（記錄以免重蹈）**：
> 1. `sfc /scannow` + `DISM /RestoreHealth` → 沒解決（DLL 本來就沒壞）。
> 2. 一度以為是 SCM 失敗復原策略（`FAILURE_ACTIONS: RESTART, Delay 300000ms = 5 分鐘`），
>    用 SYSTEM 清空 FailureActions → **實測無效，11:16:28 照樣逾時**。代表 5 分鐘的驅動「不是」復原策略。
> 3. 真因：**某程序每 5 分鐘查 Group Policy → demand-start gpsvc（trigger-start 服務）→ 它啟動時 hang 滿 30 秒**。
>    Task Scheduler Operational 日誌被停用，無法低成本揪出該呼叫者（要 ProcMon/ETW 追 RPC）。
>
> **權限關鍵**：gpsvc 是受保護服務，SDDL 只給 `BA`(Administrators) 唯讀
> （`CCLCSWLOCRRC`，無 DC 改設定、無 RP 啟動），登錄檔 key 也是 Administrators 只有 ReadKey。
> **唯一能改的是 `SY`(NT AUTHORITY\SYSTEM)** → 即使 UAC 提權成 Admin 也會 Access Denied(error 5)。
>
> **✅ 最終生效解法（以 SYSTEM 身分停用服務；不重開機、可逆）**：
> 因 Admin 無權，需用「排程任務以 SYSTEM 執行」。一次性做法（提權 PowerShell）：
> ```powershell
> # 建一個以 SYSTEM 跑的一次性任務，把 gpsvc 設為 Disabled
> schtasks /Create /TN gpsvcdis /TR 'cmd /c sc config gpsvc start= disabled' /SC ONCE /ST 00:00 /RU SYSTEM /RL HIGHEST /F
> schtasks /Run /TN gpsvcdis
> Start-Sleep 5; schtasks /Delete /TN gpsvcdis /F
> sc.exe qc gpsvc        # 確認 START_TYPE = 4 DISABLED
> ```
> 停用後，每 5 分鐘的呼叫會立即收到「服務已停用(1058)」而非 hang 30 秒 → 7000/7009 與卡頓消失。
>
> **還原**（日後加入網域 / 需要 GP 時，同樣用 SYSTEM 任務）：
> ```powershell
> schtasks /Create /TN gpsvcen /TR 'cmd /c sc config gpsvc start= auto' /SC ONCE /ST 00:00 /RU SYSTEM /RL HIGHEST /F
> schtasks /Run /TN gpsvcen; Start-Sleep 5; schtasks /Delete /TN gpsvcen /F
> ```
> 若想徹底治本（讓 gpsvc 能正常啟動而非停用）：找出每 5 分鐘呼叫 GP 的程序並停掉它，或重開機。
>
> 以下為完整深入排查（需要時才做）。

---


> 症狀：System 事件日誌每 5 分鐘出現 SCM 7000/7009（「Group Policy Client 服務未在時限內回應」），
> 每天約 125 次。`gpsvc` 設為 Auto 但卡在 Stopped。屬 Windows OS 層問題，與 AI-QA 專案無關，
> 但代表主機 service 層不健康（會偶發 I/O/CPU 卡頓，2026-06-29 曾連帶讓 n8n 掉一則 LINE 訊息）。

**請全程用「系統管理員」開 PowerShell（Win+X → 終端機(系統管理員)）。由上往下做，每步看結果再決定下一步。**

---

## 步驟 0：先試手動啟動，看真正的錯誤

```powershell
Start-Service gpsvc -Verbose
Get-Service gpsvc
```

- 若 `Running` → 服務本身沒壞，問題在「啟動時機/逾時」，跳到 **步驟 3**。
- 若仍失敗並噴錯 → 記下錯誤碼，繼續 **步驟 1**。

## 步驟 1：檢查服務登錄與 svchost 群組設定

```powershell
# gpsvc 應為 svchost -k GPSvcGroup，ServiceDll 應指向 gpsvc.dll
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\gpsvc' |
  Select-Object ImagePath, ObjectName, Start, Type
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\gpsvc\Parameters' |
  Select-Object ServiceDll
# svchost 的 GPSvcGroup 群組裡應包含 gpsvc
(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Svchost').GPSvcGroup
# gpsvc.dll 檔案存在嗎
Test-Path C:\Windows\System32\gpsvc.dll
```

預期值：
- `ImagePath` = `%SystemRoot%\system32\svchost.exe -k GPSvcGroup`
- `ObjectName` = `LocalSystem`，`Start` = `2`(Auto)
- `ServiceDll` = `%SystemRoot%\System32\gpsvc.dll`
- `GPSvcGroup` 內含 `gpsvc`，且 `gpsvc.dll` 存在

任何一項缺/錯，多半是系統檔損壞 → 步驟 2 修復。

## 步驟 2：系統檔完整性修復（最關鍵）

```powershell
sfc /scannow
# sfc 跑完接著跑 DISM（修元件存放區，sfc 修不動時靠它）
DISM /Online /Cleanup-Image /RestoreHealth
```

兩者都跑完後 **重開機**，再觀察事件日誌是否還跳 7000/7009。

## 步驟 3：檢查「每 5 分鐘重試」從何而來

```powershell
# 看 SCM 對 gpsvc 的失敗復原設定（若被設成 Restart after 5 min 會造成重試風暴）
sc.exe qfailure gpsvc
# 看是否有排程任務在週期性刷新 GP / 啟動服務
Get-WinEvent -LogName 'Microsoft-Windows-GroupPolicy/Operational' -MaxEvents 20 |
  Select-Object TimeCreated, Id, Message | Format-Table -Wrap
```

若 `qfailure` 顯示 5 分鐘重啟，且根因短期無法解決，可暫時把復原動作設為「不動作」止血（治標）：

```powershell
sc.exe failure gpsvc reset= 0 actions= ""
```

> 注意：這只是停止日誌洗版，不是修好服務。根因仍應靠步驟 2。

## 步驟 4：重開機後驗證

```powershell
Get-Service gpsvc                       # 應為 Running
# 過 10 分鐘後確認不再有新的 7000/7009
Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Service Control Manager';Id=7000,7009;StartTime=(Get-Date).AddMinutes(-10)} -ErrorAction SilentlyContinue |
  Measure-Object | Select-Object -ExpandProperty Count   # 期望 0
```

---

## 為什麼值得修

`gpsvc` 反覆 30 秒逾時，代表主機 service 層在那些時刻是卡住的。雖然 AI-QA 的 watchdog（`AI-QA-n8n-LogWatchdog`）
已能在「intake 掉訊息」發生時寄信通知你，但**根治主機卡頓**能直接降低再次掉訊息的機率，
也是 n8n DB 是否需要遷移到 Postgres（待辦 #3）的前提判斷依據——若主機穩定了，sqlite 其實也夠用。
