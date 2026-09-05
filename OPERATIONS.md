# OPERATIONS.md

本專案的「運行手冊 + 變更紀錄」。每次系統有功能新增、bug 修正、或架構調整，**追加**到「變更紀錄」最上方並更新「系統架構」相關章節。

最後更新：2026-06-30

---

## 系統架構（最新運行狀態）

### 元件總覽

| 元件 | 角色 | 啟動方式 |
|---|---|---|
| Docker Desktop | 容器執行環境 | Windows 開機自動啟動 |
| `pg_container` | PostgreSQL 65432，DB `vectordb` | docker-compose（`unless-stopped`） |
| `ai-qa-n8n` | n8n 5681，LINE QA Assistant workflow | docker-compose（`unless-stopped`） |
| Ollama | 本地 LLM `qwen2.5:7b-instruct-q4_0` + bge-m3 embedding | Windows 開機服務 |
| `api_server.py` | 8765，n8n 與本地腳本的 REST 橋接 | `start_all.bat` |
| ngrok（**穩定**子網域） | `quadruplication-satisfyingly-corrina.ngrok-free.dev` → n8n:5681 | `start_all.bat` |
| cloudflared（**動態** URL） | 隨機 `*.trycloudflare.com` → api_server:8765；URL 由腳本自動寫進 `.env` | `start_all.bat` |
| Task Scheduler `AI-QA-Assistant-Startup` | 登入時觸發 `start_all.bat` | 已註冊（一次性） |

### 對外 URL

| 用途 | URL |
|---|---|
| LINE Webhook | `https://quadruplication-satisfyingly-corrina.ngrok-free.dev/webhook/line-qa` ← **永久不變** |
| 檔案下載 / api_server 公開 | 動態（每次開機由 `start_all.ps1` 寫進 `config/.env` 的 `API_SERVER_BASE_URL`） |

### 文件收件匣資料夾

```
D:\智能助理資料庫自動備份\
├── PDF\        WORD\        EXCEL\        JPG\         ← inbox（按檔案類型分桶；不分部門）
├── processed\  ← 匯入成功後自動移來
└── error\      ← 匯入失敗後自動移來
```

所有檔案 `department` 一律標 `general`。

### 支援的副檔名（白名單）

| 桶 | 副檔名 |
|---|---|
| PDF | `.pdf` |
| WORD | `.doc` `.docx` |
| EXCEL | `.xls` `.xlsx` |
| JPG | `.jpg` `.jpeg` `.png` |
| ZIP | `.zip`（**只轉寄 mail、不入庫**） |

其他副檔名的檔案會在 `/line-download-content` 被回 415 拒絕，不入庫。

`.zip` 屬「不解析入庫」類型（`api_server.NON_INGEST_EXTS`）：照常下載 + 轉寄 mail，但 `/ingest-file` 會 graceful skip（回 `skipped:true`），檔案移至 `processed/ZIP/`，LINE 回覆顯示「📦 壓縮檔已轉寄，未加入知識庫」。

### LINE 訊息流程

**文字訊息**（QA / 找檔案 / 問檔案 …）→ 既有 5 條分支處理（vector_search → Ollama 生成 / search_files / 檔案類型選單 / 關鍵字輸入 / file_qa）。

**檔案/圖片訊息**（PDF / Word / Excel / JPG / JPEG / PNG / ZIP）：

1. LINE Webhook → 簽章驗證 → Parse Message（**每筆 event 各一個 item**，支援一次多檔）
2. Intent Router 判 `file_upload` → `Route File Upload` (IF) → file_upload 鏈
3. **per-item**：`/line-download-content` 把檔下載進 `inbox/<BUCKET>/`
4. **batch**：`Aggregate Paths` 收齊所有 file_path → `/forward-mail`（**單次 API 呼叫，多附件一封信**）→ `Distribute Mail Result` 再分回 N items
5. **per-item**：`/ingest-file`（extract → chunk → embed → DB → 移到 `processed/`）
6. **per-item**：`Build Upload Reply` → `LINE Reply: Upload`（**每份檔案各一條 LINE 回覆**）

---

## 變更紀錄

### 2026-09-05 — LINE 檔案上傳全數失敗：Python 不信任 LINE 新憑證鏈（`CERTIFICATE_VERIFY_FAILED`）
- **觸發**：n8n 執行 **#4373**（`.docx`）與 **#4375**（`.pdf`）於 `11:11` 同時失敗，`Execute: line_download_content` 回 502：
  `LINE Content API failed: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate>`
- **根本原因**：
  - `api-data.line.me` 的憑證於 `2026-08-14` 換發，簽發鏈改為 `GlobalSign GCC R46 OV TLS CA 2025 → GlobalSign Root R46`。
  - Windows 上的 Python `ssl` 只信任**已在本機 Windows 憑證存放區**的根憑證，且**不會**觸發 Windows 的「按需下載根憑證」機制；本機 ROOT 存放區沒有任何 GlobalSign 根憑證，所以驗證失敗。
  - `api.line.me`（Reply API，DigiCert 鏈）不受影響，因此只有「上傳檔案」壞、問答正常。9/1 仍成功是因為 LINE 端逐步切換節點。
  - 驗證：`openssl s_client` 對同一主機回 `Verify return code: 0`（伺服器有送完整鏈），改用 certifi 的 CA bundle 驗證亦 OK → 純粹是本機信任庫缺根憑證。
- **改動**（`scripts/api_server.py`）：
  - 新增 `_https_ssl_context()`：以系統存放區為基底，再疊上 `certifi` 的 Mozilla CA bundle；certifi 不可用時退回系統存放區並印警告。
  - `/line-download-content` 的 `urlopen` 改帶此 context；`/notify`、`/forward-mail` 兩處 SMTP STARTTLS 也改用同一 helper（Gmail 目前沒問題，預防性統一）。
- **補救**：修復並重啟 api_server 後，手動以原 `message_id` 重跑三步（下載 → `/forward-mail` 兩檔合寄 → `/ingest-file` 各自入庫），兩份《台灣奇蹟股份有限公司_董事會決議錄_1150905》均已寄出並入庫（各 1 chunk）。**LINE 端未收到回覆**（reply token 已過期），需人工告知使用者。
- **排查**：若日後再見同類錯誤，先用下列指令判斷是「伺服器鏈不完整」還是「本機缺根憑證」：
  ```powershell
  openssl s_client -connect api-data.line.me:443 -servername api-data.line.me -showcerts   # 看 Verify return code 與鏈
  python -c "import ssl,socket,certifi;ctx=ssl.create_default_context(cafile=certifi.where());ctx.wrap_socket(socket.create_connection(('api-data.line.me',443)),server_hostname='api-data.line.me');print('certifi OK')"
  ```

### 2026-09-01 — Ollama 模型遭刪除（系統壞了 25 小時無人察覺）+ Docker port-forward 衝突連帶修復
- **觸發**：LINE 上傳 `在建工程明細表20260422.xlsx` 後回覆「✉ 已轉寄成功，⚠️ 知識庫匯入失敗」，錯誤為 `Ollama HTTP 404: model "bge-m3" not found, try pulling it first`。

#### 問題一：Ollama 模型全數遭刪除
- **實況比回報更嚴重**：`/api/tags` 回傳 **0 個模型** —— 不只 `bge-m3`，連 `qwen2.5:7b-instruct-q4_0` 也不見了，等於**問答與匯入雙雙失效**。`~/.ollama/models/blobs` 與 `manifests` 皆空，整個目錄只剩 12K，mtime 停在 **2026-08-31 08:51**。
- **根本原因（決定性證據）**：`%LOCALAPPDATA%\Ollama\server.log` 記錄
  ```
  2026/08/31 - 08:51:19 | 200 | DELETE "/api/delete"   ← 127.0.0.1
  2026/08/31 - 08:51:19 | 200 | DELETE "/api/delete"
  2026/08/31 - 08:51:20 | 200 | DELETE "/api/delete"
  2026/08/31 - 08:51:20 | 200 | DELETE "/api/delete"
  ```
  一秒內 4 次來自本機的**明確刪除呼叫**（`ollama rm` 打的就是這個端點），全部回 200。**不是**崩潰、磁碟清理或自動更新：磁碟 C 尚餘 260GB；`app.log` 顯示 08:41／09:41 只有例行更新檢查（v0.33.2 已下載但未安裝），08:51 沒有 Ollama 自身活動。
- **無法確定執行者**：專案內 grep 不到任何 `ollama rm` / `api/delete` 的程式碼；PowerShell 歷史只有一筆舊的 `ollama pull bge-m3`。刪除可能來自其他 shell（cmd／Git Bash／WSL 不寫入 PSReadline 歷史）或 Ollama GUI。**能確定「是什麼」，不能確定「是誰」。**
- **順帶解開 8/31 09:00 的懸案**：該次 `GET: List Inbox Files` 卡 12.9 秒而逾時（見上方該筆），時間點正好落在 08:51 刪除約 6GB 模型檔之後 —— 大量刪除 I/O 拖慢了磁碟，這是先前查不出來源的那 12.9 秒最合理的解釋。
- **修復**：`ollama pull bge-m3`（1.16GB）、`ollama pull qwen2.5:7b-instruct-q4_0`（4.43GB）。

#### 問題二：Windows → PostgreSQL 的 port-forward 壞掉（補模型後才浮現）
- **現象**：模型補回後重跑匯入，extract／chunk／embed 全過，卻卡在 `write_to_db failed`。從 Windows 連 PG **三種寫法全失敗**：`localhost`（解析為 `::1`）、`::1`、`127.0.0.1`，錯誤為 `could not receive data from server: Software caused connection abort (10053)` 與 `server closed the connection unexpectedly` —— TCP 建得起來，但協定握手就被斷。
- **PostgreSQL 本身完全健康**：容器內 `psql` 與同 docker 網路的臨時容器都查得到 215 筆 documents。
- **根本原因（PID 級證據）**：`netstat` 顯示 **兩個程序同時綁 65432**
  | PID | 程序 | 綁定 | 啟動時間 |
  |-----|------|------|----------|
  | 52464 | `com.docker.backend` | `0.0.0.0:65432` + `[::]:65432` | **8/27 16:43** |
  | 43656 | `wslrelay.exe` (`--vm-id {3433a8a9-…}`) | `[::1]:65432` | **8/31 11:31:16** |
  `8/31 11:31` WSL VM 重啟後新起的 `wslrelay` 搶綁了 IPv6 loopback，而 Docker 的 forwarder 仍是 8/27 的舊程序、沒跟著 VM 重啟 → 兩者打架，轉發失效。（vm-id `3433a8a9` 正是當初在 Hyper-V VmSwitch 事件中看到的那個 NIC。）
- **這同時就是 n8n `Connection terminated unexpectedly` 的源頭**，時間完全吻合；先前把 n8n 改為直連 docker 內部網路（見上一筆），正好繞開了這個衝突，所以那條路徑修完即穩。
- **修復**：`docker restart pg_container` —— 讓 Docker 重建該 port 的 forwarding。重啟後 `127.0.0.1` 與 `localhost` 立即恢復正常。**注意**：`wslrelay` 仍綁著 `[::1]:65432`，衝突的結構還在，**下次 WSL VM 重啟後可能重演**（判斷方式見下方「排查」）。
- **api_server 為何不能比照 n8n 直連**：它跑在 Windows 上、不是容器，走不了 docker 內部網路，只能經由 port mapping，因此仍暴露在這個衝突下。

#### 驗證（全綠）
- 模型：`/api/tags` 回 `bge-m3:latest` 1.16GB + `qwen2.5:7b-instruct-q4_0` 4.43GB；`bge-m3` 實測輸出 **1024 維**（與 schema `VECTOR(1024)` 相符）；`qwen2.5` 生成正常（以 UTF-8 送中文 prompt 回答正確）。
- 檔案重跑：`在建工程明細表20260422.xlsx` 由 `error/EXCEL/` 移回 inbox 後重新 ingest → `success=True, chunk_count=3`；DB 確認 `ingest_status=done`、3 chunks、`dims=1024`。
- 端到端：`POST /vector-search`（此路徑正好經過剛修好的 `localhost:65432`）以「在建工程明細表的內容是什麼？」檢索 → 命中 3 筆，最高相似度 **0.6949**，Top-1 即該檔。
- **error 資料夾盤點**：共 37 個檔案，其中**只有 1 個是今天的**（即本次 xlsx），其餘 36 個為 4～7 月的舊失敗，與本次事故無關，未一併處理。

#### 監控缺口（尚未處理，建議補）
- 模型自 `8/31 08:51` 消失，直到 `9/1 09:41` 使用者上傳檔案才被發現 —— **系統壞了約 25 小時，零告警**。
- 現有 `watchdog_api.ps1` 只檢查 8765 是否 listening，**不檢查 Ollama 模型是否存在、也不檢查 api_server 能否連上 PG**。這兩者任一失效都會讓系統靜默失能。
- 建議在 watchdog 增加：① `GET /api/tags` 確認 `bge-m3` 與 `qwen2.5:7b-instruct-q4_0` 都在；② 從 Windows 實際連一次 PG。任一失敗即透過既有 `/notify` 告警。

#### 排查：疑似又是 port-forward 衝突時
```powershell
netstat -ano | findstr ":65432"        # 若有兩個不同 PID 在綁，即為此問題
Get-Process -Id <PID> | Select ProcessName,StartTime
docker restart pg_container            # 修法：讓 Docker 重建 forwarding
```

### 2026-09-01 — 修復「掉訊息偵測」watchdog：部署第一天起就沒運作過（失效 64 天）
- **發現經過**：追查 8/31 ingest 告警時，順手確認「為什麼 8/28、8/30、8/31 連三次 n8n crash 都沒告警」，才發現這支 watchdog 早已死亡。
- **證據**：
  - `logs/watchdog_n8n.state` 停在 `2026-06-29T02:47:02Z`，**兩個月未更新**（檔案 mtime 也停在 6/29）。
  - `logs/watchdog_n8n.log`：**OK 0 筆 / ERROR 8630 筆** —— 每 5 分鐘失敗一次，連續失敗到 9/1，8630 行全是同一則假錯誤。
- **根本原因（PowerShell 5.1 的原生 exe stderr 陷阱）**：
  - 腳本開頭 `$ErrorActionPreference = 'Stop'`，而取日誌那行用 `& docker logs ... 2>&1`。
  - PS 5.1 對**原生 exe** 用 `2>&1` 時，stderr 每一行都會被包成 `ErrorRecord`；配上 EAP=Stop 就成為終止錯誤，直接跳進最外層 `catch`。
  - **n8n 的日誌全部走 stderr**（連 `DEP0040 punycode` warning 也是），所以第一行就炸 → 永遠執行不到結尾的 `Set-Content $stateFile`。
  - 檢查點因此永遠卡在 6/29，每次 `docker logs --since` 都從 6/29 撈起，第一行 stderr 又立刻炸 —— 形成自我維持的死迴圈。
- **第二層盲點：排程的 `LastResult` 不可信**。`AI-QA-n8n-LogWatchdog` 執行的是 `wscript.exe watchdog_n8n_launch.vbs`，而 vbs 用 `shell.Run cmd, 0, False`（**非同步、不等待**），wscript 立刻結束回 0。所以 Task Scheduler 的 `LastResult` **恆為 0**，與 ps1 實際成敗無關 —— 這是連續失敗兩個月卻無人察覺的直接原因。
  - **判斷 watchdog 健康請一律看 `logs/watchdog_n8n.log` 是否持續出現 `OK`，不要看排程面板的 LastResult。**
- **改動**（`scripts/watchdog_n8n_log.ps1`）：
  - 新增 `Get-ContainerLogLines`：只在該呼叫內把 EAP 降為 `Continue`，把 `ErrorRecord` 攤平回字串，真正的失敗改用 `$LASTEXITCODE` 判斷（容器不存在／Docker 未啟動）。
  - 新增檢查點過舊保護：`$since` 若無法解析或早於 60 分鐘前，記 `WARN` 並截斷為回看 60 分鐘 —— 避免 watchdog 曾長期失效後，一次掃進數週日誌並對早已過期的事件洗版告警。
  - 舊的 8630 行垃圾日誌歸檔為 `logs/watchdog_n8n.log.broken-2026-06-29_2026-09-01`（保留證據）。
- **驗證**（四段全綠）：
  1. 手動執行 → `exit 0`（先前恆為 1）；log 出現兩個月來第一筆 `OK`，且正確印出 `WARN 檢查點過舊 → 截斷 60 分鐘`。
  2. 再執行一次 → 無 WARN，區間 `01:22:52 ~ 01:23:05` 精確銜接前次檢查點，無縫也無重疊。
  3. **告警路徑乾跑**：複製一份改 `$pattern` 為 `Initializing n8n process`（容器內確定存在）、`Send-Alert` 改為輸出不寄信 → 成功命中 1 筆並完整組出告警內容（主旨、掃描區間、原始日誌行、排查指令）。證明「偵測 → 組裝 → 告警」整條路徑可用，不只是「不再報錯」。
  4. **端到端**：等排程於 `09:27:01` 自動觸發 → log 寫入 `OK`，state 由 `01:23:05` 銜接至 `01:27:01`。
- **未動**：`watchdog_n8n_launch.vbs` 維持非同步啟動（改同步會有排程重疊風險，且當初就是為了消除命令視窗閃爍，見 2026-06-30 該筆）。

### 2026-09-01 — 修復文件匯入流程偶發告警：`GET: List Inbox Files` timeout 太短且無重試
- **症狀**：收到告警 `Enterprise Doc Ingest v2 / 執行ID 4238 / 最後節點 GET: List Inbox Files / The connection was aborted, perhaps the server is offline`。
- **排查結果：api_server 從頭到尾都活著，不是「server offline」**。
  - `logs/watchdog.log` 顯示 `pid=6492` 在 08:46 與 09:16 兩次心跳皆 `OK 8765 listening`，中間沒重啟過；`logs/api_server.err.log` 也沒有任何 traceback。
  - n8n event log（`/home/node/.n8n/n8nEventLog*.log`）顯示執行 4238 於 `2026-08-31T09:00:24` 開始、`09:00:37` 失敗 —— **卡了 12.9 秒**。
- **已排除「Docker 被重整/暫停」**（曾懷疑此因，實際查證後不成立）：
  - Hyper-V VmSwitch 事件顯示 WSL VM 的 NIC delete→create（= Docker VM 整個重啟）只發生在 **8/30 13:11** 與 **8/31 11:31**，兩次都對應 n8n 的 `Last session crashed`。事故（8/31 09:00）落在兩次之間，該區段 VmSwitch **完全沒有事件**，網路層連續穩定。
  - Windows 事件記錄無任何 Kernel-Power 41/42/107 → 電腦沒睡眠、沒當機、沒重開機。
  - 結論：8/31 11:31 的 Docker 重啟發生在事故**之後 2.5 小時**，是後續現象而非成因。
- **根本原因**：`GET: List Inbox Files` 節點 `options.timeout` 設 **10000ms**，該次呼叫實際耗時超過 10 秒（確切來源日誌未留痕跡，無法定位） → n8n 主動中斷連線，並把 timeout 一律回報成 "The connection was aborted, perhaps the server is offline"（誤導性訊息）。節點又**沒有任何重試**，單次瞬斷就讓整條流程失敗並發告警。
- **改動**（`workflows/ingest_workflow_v2.json` 的 `GET: List Inbox Files`）：
  - `options.timeout`：`10000` → `60000`（掃本機資料夾給足餘裕）
  - 新增 `retryOnFail: true`、`maxTries: 3`、`waitBetweenTries: 5000`（純讀取、冪等，重試安全）
  - **未動 `POST: Ingest File`**：該節點有寫 DB／移檔副作用，不加自動重試；且它失敗已由 `IF: Success?` 分支處理，不會中斷整批。
- **驗證**：改檔前先 `n8n export:workflow` 比對線上版與 repo 版（10 個節點、參數 0 差異）才覆蓋。匯入後 `export` 回讀確認 `active=True`、`timeout=60000`、`retryOnFail=True`、`maxTries=3`；容器內 `wget http://host.docker.internal:8765/list-inbox` 正常回 200。
- **頻率佐證**：event log 全歷史中，ingest 流程僅 6/23（當時 api_server 未啟動那批）與這次 8/31 失敗過，屬偶發瞬斷，非持續故障。
- **注意（踩過的坑）**：`n8n import:workflow` 會**自動把該 workflow 停用**（`Deactivating workflow ... Remember to activate later`），必須接著 `n8n update:workflow --id=<id> --active=true` **並重啟容器**才生效（CLI 會提示 `Changes will not take effect if n8n is running`）。

### 2026-09-01 — 根治 `Connection terminated unexpectedly`：n8n 改為直連 PostgreSQL 的 docker 內部網路
- **症狀**：`LINE QA Assistant` 在最前端的 `Query Session Early` 失敗，錯誤 `Connection terminated unexpectedly` —— **使用者提問被靜默丟棄**。執行 4265（09:05）、4267（09:21）連兩次。
- **關鍵事實：這是全新問題**。翻遍 n8n 全部 event log，此錯誤**歷史上從未出現過**，只有 9/1 早上這兩筆。
- **排除 PostgreSQL 端**（完全無辜）：
  - `idle_session_timeout` / `idle_in_transaction_session_timeout` / `statement_timeout` / `tcp_keepalives_idle` **全為 0（停用）** → PG 不會主動斷線，也不發 keepalive。
  - 連線數 6 / max_connections 100，毫無壓力；`docker logs pg_container --since 12h` **一行輸出都沒有**。
- **根本原因：連線繞了一大圈，中間層回收閒置 TCP**。
  - n8n 與 PostgreSQL 分屬**兩個不同的 compose project、兩個不同的 docker 網路**：
    - `ai-qa-n8n` → `docker_n8n_default`（172.22.0.2）
    - `pg_container` → `docker_postgresql_default`（172.21.0.2）
  - 因此 n8n 只能靠 credential 裡的 `host.docker.internal:65432` 連線 —— 路徑是「n8n 容器 → Docker NAT → Windows host port-forward → Docker NAT → pg 容器」。
  - **該 port-forward 層當時是壞的**（後續在排查 Ollama 事故時才查出精確機制，見下一筆）：`8/31 11:31` WSL VM 重啟後新起的 `wslrelay.exe`（PID 43656，vm-id `{3433a8a9-…}`）搶綁了 `[::1]:65432`，而 Docker 的 `com.docker.backend`（PID 52464）仍是 `8/27 16:43` 啟動的舊程序、沒跟著 VM 重啟 —— 兩個 forwarder 同時綁同一個 port，轉發行為變得不確定，連線在協定握手階段被斷。
  - 因此 n8n 的 pg pool 取用連線時拿到已被中間層斷掉的死連線 → `Connection terminated unexpectedly`。時間也完全吻合（wslrelay 起於 8/31 11:31，首次故障 9/1 09:05）。
- **修法：讓兩者直連，整段中間層直接消失**。
  1. `docker_n8n/docker-compose.yml`：加入 external network `docker_postgresql_default`（`networks: [default, pgnet]`），使網路連接由 compose 管理而非臨時 `docker network connect`（後者容器一重建就沒了）。
  2. n8n credential `PostgreSQL vectordb`：`host.docker.internal:65432` → **`db:5432`**（`db` 是 pg_container 的 compose service name / hostname alias）。以 `n8n export:credentials --decrypted` → 改 → `import:credentials` 完成，全程在容器內操作，避免其他憑證外流。
  3. compose 的 `POSTGRES_HOST` / `POSTGRES_PORT` 環境變數同步改為 `db` / `5432`。
  4. **第二層保險**：`qa_workflow.json` 的兩個唯讀節點 `Query Session Early`、`Query allowed_users` 加上 `retryOnFail: true / maxTries: 3 / waitBetweenTries: 3000`。
- **刻意不動**：`Insert qa_logs`、`Log Error` 是純 `INSERT`，自動重試會產生重複列，不加。（`conversation_sessions` 那幾個雖是 `ON CONFLICT` upsert、本身冪等，但根因已除、retry 只是保險，故一併維持原狀。）
- **不影響的部分**：`api_server.py` 跑在 Windows 上，仍走 `localhost:65432`（compose 的 `65432:5432` port mapping 保留）；n8n 對 api_server（8765）與 Ollama（11434）仍走 `host.docker.internal`，因為那兩者不是容器。
- **驗證**（逐層，全綠）：
  1. 先用 `docker network connect` 臨時接上測試 → `db:5432` / `pg_container:5432` TCP 皆通。
  2. `pg_hba.conf` 為 `host all all all trust`、`listen_addresses = *` → 新來源會被接受。
  3. **協定層**：從該網路起一個臨時 `ankane/pgvector` 容器 `psql -h db` → 認證成功，查得 `conversation_sessions`。
  4. 改 compose 後 `docker compose up -d` 重建 → 容器確實同時掛在兩個網路（172.22.0.2 + 172.21.0.4），證明設定已持久化。
  5. 回讀確認 credential 為 `db:5432`、workflow `active=True` 且兩節點 retry 已生效。
  6. **端到端**：自行以 `LINE_CHANNEL_SECRET` 計算 HMAC-SHA256 簽章，送一筆**未授權 user id** 的合法 webhook（`Check Auth` 對未授權者是 `return null`，流程正常結束、不觸發告警；對 LINE 的請求帶無效 replyToken 必被拒且被 `catch` 吞掉，**不會有訊息送給任何人**）→ webhook 回 **HTTP 200**；執行 4269 的 `Query Session Early` **23ms 內完成**；`pg_stat_activity.client_addr` 顯示 **172.21.0.4**（n8n 在 pg 網路的 IP），**證明連線確實走內部網路直連，不再經過 host.docker.internal**。
- **注意**：`import:workflow` 一樣會自動停用 workflow，需 `update:workflow --active=true` 並重啟；本次與 compose 重建合併為一次生效。

### 2026-06-30 — 清理重複的開機排程（消除重開機後殘留的錯誤視窗）
- **症狀**：重開機後桌面留下兩個沒自動關的命令視窗報錯 —— ① ngrok 視窗 `ERROR: Tunnel 'api-server' is not defined in the config files`；② api_server 視窗顯示 `'CLAUDE' 不是內部或外部命令`。但所有服務其實都正常運行。
- **根本原因**：登入時有**三個**排程同時觸發，其中兩個是改用 `start_all.ps1` + watchdog 架構之前的**舊版殘留**，現已與新架構重複且部分失效：
  1. `AI_Ngrok`（LastResult=1）→ `start_ngrok_bg.bat` / `start_ngrok.bat` 仍跑 `ngrok start api-server`，但 api_server 早已改走 cloudflared、`ngrok.yml` 只剩 `n8n` tunnel → 報 "tunnel not defined"。
  2. `AI_ApiServer`（LastResult=1）→ `start_api_server_bg.bat` 想再起第二個 api_server，8765 已被佔用 → 失敗。
  - 真正在運作的是 `AI-QA-Assistant-Startup`（→ `start_all.ps1`，LastResult=0）+ `AI_ApiServer_Watchdog` + `AI-QA-n8n-LogWatchdog`。
- **改動**：
  - 以系統管理員權限 `schtasks /Change /DISABLE` 停用 `AI_ApiServer`、`AI_Ngrok`（**只停用、未刪除**，可隨時還原）。
  - 刪除已無用途的殘留腳本：`start_ngrok.bat`、`start_ngrok_bg.bat`、`start_api_server_bg.bat`。
- **驗證**：停用後全鏈路重測皆綠 —— api_server `/health` 200、n8n `/healthz` 200、Ollama 200、cloudflared 對外 `/health` 200、ngrok LINE webhook 200；watchdog.log 心跳正常（每 30 分 `OK 8765 listening`）；ngrok 程序僅一個跑 `start n8n`（正確）。
- **備註**：開機自動化與自癒一律交由 `AI-QA-Assistant-Startup` + 兩支 watchdog 負責，不再有重複任務或殘留錯誤視窗。

### 2026-06-23 — 修復 PDF OCR 在 `pythonw.exe` 下卡死（multiprocessing 死鎖）
- **症狀**：整台電腦持續轉圈圈變鈍。查出 `api_server.py`（PID 1920）對同一個 `金泳公司章程.pdf` 在 16:32 / 17:03 / 18:03 重複觸發 3 次文字擷取，每次都卡死沒結束（各跑 46 分～2 小時17分、CPU 只耗 123～384 秒＝**阻塞而非運算**），每棵各自又開了 multiprocessing 子程序在背景空轉吃 CPU。
- **根本原因（三層）**：
  1. `api_server.py` 跑在 `pythonw.exe`（無 console），`extract_pdf_ocr` 開的 `multiprocessing.Pool` 子程序繼承 `pythonw.exe` → 子程序 `stdin/stdout` 為 `None`，spawn 啟動程序**永久死鎖**（commit `1a22b47` 改並行 OCR 後引入）。
  2. `run_script` 的 `subprocess.run` **沒設 timeout** → api_server 請求執行緒永遠等下去。
  3. 沒有防重入機制 → 每小時匯入 cron 重掃到仍在 inbox 的同一檔，又生一棵新的卡死程序樹。
- **改動**：
  - `scripts/extract_text.py`：multiprocessing 子程序改用 console `python.exe`（`_console_python()`，偵測到 `sys.executable` 是 pythonw 時切換）；新增 `freeze_support()`；pool 加 `map_async(...).get(timeout=max(180, 頁數×60))`，逾時/錯誤時 `terminate()` 並 fallback 到**循序 OCR**（`_ocr_pdf_sequential`，不開子程序、不會死鎖）。
  - `scripts/api_server.py`：`run_script` 改 `Popen + communicate(timeout=...)`，逾時時 `taskkill /F /T /PID` **整棵程序樹一起砍**（含 MP worker 與 poppler 的 `pdftoppm` 孫程序）；各步驟逾時 `EXTRACT_TIMEOUT_SECS=600 / CHUNK=180 / EMBED=1800 / DB=180`（皆可用環境變數覆寫）；`/ingest-file` 新增 `_INGEST_INPROGRESS` 單檔處理中鎖（`threading.Lock`），cron 重疊時回 `{skipped:true, reason:"已在處理中"}`。
- **部署**：`Stop-Process 1920` → `watchdog_api.ps1` 重起（新 pid 140568、`/health` ok）。
- **驗證**：① 在 `pythonw.exe` 下以 PIPE+timeout 擷取該 PDF → **4.2 秒**完成（原本卡 2 小時以上）、`returncode=0`、OCR 2 頁、1793 字；② 把檔從 `error/PDF/` 移回 inbox 後打 `/ingest-file` → **16.3 秒**完成、`success:true`、3 chunks 寫入 DB（`document_id d708401d…`）、檔案移至 `processed/PDF/`；③ 殘留卡死程序 0。

### 2026-06-23 — LINE 上傳 `.zip` 也能轉寄 mail
- **背景**：使用者在 LINE 上傳 `.zip`（如「114年第四梯次初級AI應用規劃師…公告.zip」10.1MB）後完全沒收到回覆。原因：`.zip` 不在 `api_server.EXT_TO_BUCKET` 白名單，`/line-download-content` 回 415，file_upload 鏈中斷。
- **需求**：`.zip` 也要能下載 + 轉寄 mail（壓縮檔無法解析，**不需入庫**）。
- **改動**：
  - `scripts/api_server.py`：`EXT_TO_BUCKET` 新增 `.zip → ZIP` 桶 + zip MIME（`application/zip`、`application/x-zip-compressed`）；新增 `NON_INGEST_EXTS = {".zip"}`；`/ingest-file` 開頭判斷副檔名，屬不解析類型則直接移到 `processed/` 並回 `{success:true, skipped:true}`（不跑 extract/chunk/embed）。
  - `workflows/qa_workflow.json`（**Build Upload Reply**）：新增 `ingestSkipped` 判斷，skip 時 LINE 回覆顯示「📦 壓縮檔已轉寄，未加入知識庫」，不再誤報「知識庫匯入失敗」。
- **後續修正（同日）— 大附件轉寄 timeout**：第一次實測 10.1MB zip 下載+跳過入庫都正常，但 mail 回「⚠️ 轉寄郵件失敗」。查 `api_server.err.log`：`smtplib` 的 socket `timeout=30` 在上傳 base64 膨脹後（~13.7MB）的附件途中逾時 → `TimeoutError: write operation timed out` → `SMTPServerDisconnected`。小檔（docx）沒事，大檔必爆。
  - `scripts/api_server.py`：`_handle_forward_mail` 的 SMTP timeout 改為**依附件大小動態計算**：`min(280, max(60, 45 + 編碼後bytes // (80*1024)))`，可用 `SMTP_TIMEOUT` 環境變數覆寫。
  - `workflows/qa_workflow.json`（**Execute: forward_mail**）：node timeout `60000 → 300000`（原本 60s 會比 api_server 先放棄）。
  - **Build Upload Reply**：skip 訊息由「📦 壓縮檔已轉寄，未加入知識庫」改為「📦 壓縮檔不加入知識庫」——避免在 mail 失敗時還顯示「已轉寄」自相矛盾（轉寄狀態由第二行 `已轉寄至 / 轉寄郵件失敗` 負責）。
  - **驗證**：直接打 `/forward-mail` 送 10MB 合法 zip 到自己信箱 → 60s 完成、`success:true`。（註：Gmail 對「非合法壓縮檔／含可執行內容的 zip」會回 `552 security block`，正常 exam zip 不受影響。）
- **部署**：重啟 `api_server.py`（watchdog 重起 pid）；`docker cp` + `n8n import:workflow` 進 `ai-qa-n8n` → `docker restart ai-qa-n8n`。驗證：`/health` ok、workflow 仍 active、deployed jsCode 含 `ingestSkipped`×2、forward_mail timeout=300000、dummy zip 打 `/ingest-file` 回 `skipped:true` 並移至 `processed/ZIP/`。

### 2026-04-27（下午）— 新增白名單使用者 Ariel
- **背景**：新使用者 LINE userId `Ue9634f3484e21a92495c35b05ce7fd3f` 上傳檔案後沒收到任何回覆，也沒寄出 mail。查 n8n 執行紀錄發現停在 `Check Auth` → `authorized: false`。原因是該 LINE userId 不在 `allowed_users` 白名單。
- **動作**：
  ```sql
  INSERT INTO allowed_users (line_user_id, display_name, department)
  VALUES ('Ue9634f3484e21a92495c35b05ce7fd3f', 'Ariel', 'general');
  ```
- **結果**：之後 Ariel 重傳，系統正常下載 → 寄信 → 入庫 → LINE 回覆。
- **重要**：未授權時的訊息**無法事後補處理** — workflow 在 Check Auth 就 return null，連 `/line-download-content` 都沒呼叫，LINE messageId 沒被任何節點記錄下來。授權後請使用者**重傳**才行。
- **觀察**：同一使用者**用 LINE 連續傳 2 張圖**（拍一張傳一張）會被 LINE 拆成 2 個獨立 webhook → 各自一封信，**不會**被「合併寄信」邏輯合併。要合併成 1 封必須在 LINE app 內**同時選多個檔案**一次發送。

### 2026-04-27 — LINE 檔案轉寄 + 多檔合併寄信 + 開機自動化

**功能**
- LINE 收到 PDF/Word/Excel/JPG → 自動下載 → 寄信給 `ArielHsu@chailease.com.tw` → 加入知識庫
- 一次傳多份：合併成**一封 mail（多附件）**，但**每份檔案各回一條 LINE 訊息**
- 完整保留既有的問答 / 找檔案功能
- 開機自動啟動所有 tunnel + 服務；LINE Webhook URL 永久不變

**程式碼變更**
- `scripts/api_server.py`
  - 新增 `POST /line-download-content`：呼叫 LINE Content API 下載檔案 → 存到 `inbox/<BUCKET>/`
  - 新增 `POST /forward-mail`：透過 Gmail SMTP 寄信，支援 `file_path`（單檔）或 `file_paths`（多附件）
  - 修正 `GET /list-inbox`：所有檔案的 `department` 一律標 `general`（先前會用第一層子資料夾名，導致 `PDF/WORD/...` 被誤當部門名）
- `scripts/line_verify.py`：（無 net 變更，期間有臨時 debug log，已移除）
- `workflows/qa_workflow.json`
  - `Parse Message` 改成 `runOnceForAllItems`，支援多 events 一個 webhook 進來
  - 新增 `Route File Upload` (IF) 在 `Intent Switch` 之前分流（n8n switch v3 最多 5 outputs）
  - 新增 file_upload 鏈：`Execute: line_download_content` → `Aggregate Paths` → `Execute: forward_mail` → `Distribute Mail Result` → `Execute: ingest_file_upload` → `Build Upload Reply` → `LINE Reply: Upload`
  - `Intent Router` / `Check Auth` / `Build Upload Reply` 改用 `$('NodeName').itemMatching($itemIndex)` 配對 items（不再用 `.first()` 抓第一筆）
  - 修正 `settings.errorWorkflow`：`line-qa-assistant-v1`（過期 ID）→ `hAz6zL8XtCTWyQ1D`（正確的 Error Workflow）
- `config/.env`：新增 `SMTP_HOST/PORT/USER/PASSWORD/FORWARD_MAIL_TO`（Gmail App Password）
- `config/.env.example`：同步 SMTP 範本

**基礎設施變更**
- 新增 `start_all.bat` + `scripts/start_all.ps1`（PowerShell 5.1 用，UTF-8 BOM）
  - 等 n8n ready → 啟動 ngrok（n8n tunnel）→ 啟動 cloudflared（api_server tunnel）→ 寫 cloudflared URL 到 `.env` → 重啟 api_server → smoke test
- 註冊 Windows Task Scheduler `AI-QA-Assistant-Startup`（登入時觸發）
- `~\AppData\Local\ngrok\ngrok.yml`：tunnel 從 `api-server` (port 8765) 改指 `n8n` (port 5681)，繼續用同一個穩定子網域
- `docker_n8n/docker-compose.yml`：`WEBHOOK_URL` 改為 ngrok 穩定網址

**資料庫變更**
- TRUNCATE：`documents` / `document_contents` / `document_chunks` / `document_permissions` / `processing_logs` / `qa_logs` / `conversation_sessions`
- 保留：`allowed_users`（LINE Bot 授權白名單）

**資料夾變更**
- 清空舊 `D:\智能助理資料庫自動備份\` 內容（含舊 `.sql` 備份、`建設公司/`、`個人/`）
- 重建為 `PDF/ WORD/ EXCEL/ JPG/ processed/ error/`（不再分部門）

**已知限制**
- n8n switch v3 最多 5 outputs；多一個 intent 要拆 IF
- LINE 檔案大小上限由 LINE 規定（300MB）；Gmail SMTP 寄信附件約 25MB，過大會在 SMTP 階段失敗（`/forward-mail` 回 502）

---

## 操作指南

### 開機後

什麼都不用做。Task Scheduler 會自動跑 `start_all.bat`。如果不放心，看：

```powershell
Get-Content "$env:LOCALAPPDATA\ai-qa-startup\start_all.log" -Tail 30
```

### 手動重啟整套服務

```powershell
& "D:\n8n\CLAUDE 實做\本地AI企業問答助理\start_all.bat"
```

### 更新 n8n workflow（不需要 API key）

```powershell
docker cp "D:\n8n\CLAUDE 實做\本地AI企業問答助理\workflows\qa_workflow.json" ai-qa-n8n:/tmp/qa_workflow.json
docker exec ai-qa-n8n n8n import:workflow --input=/tmp/qa_workflow.json
docker exec ai-qa-n8n n8n update:workflow --id=ANf96ECpcq8gTuPC --active=true
docker restart ai-qa-n8n
```

> 注意：`import:workflow` 用 JSON 內的 `id` 欄位匹配。改檔案前確認 `"id": "ANf96ECpcq8gTuPC"`，否則會建立重複的 workflow。

### 重新申請 n8n API key（之前的已過期）

n8n CLI 已經夠用，發新 key 是「之後想用 REST API 自動化推送」才需要。

1. 瀏覽器開 `http://localhost:5681`
2. 左下角頭像 → **Settings**
3. 左欄 → **n8n API**
4. **Create an API key**
5. 命名建議：`claude-code-push-YYYY-Q#`（例：`claude-code-push-2026-q3`）
6. **Expires in** 建議選 **90 days**（過短常忘記、過長有安全顧慮）
7. **Save** → 立刻**複製 token**（離開頁面就看不到了）
8. 把 token 寫進 `~/.claude/projects/D--n8n-CLAUDE------AI------/memory/reference_n8n_api.md`：
   ```markdown
   ## API Key (claude-code-push-YYYY-Q#) — Expires YYYY-MM-DD
   <貼上 token>
   ```
9. 用 PowerShell 推送 workflow 的範例：
   ```powershell
   $key = "<貼上新 key>"
   $wf = Get-Content "workflows\qa_workflow.json" -Raw -Encoding UTF8
   Invoke-WebRequest -Uri "http://localhost:5681/api/v1/workflows/ANf96ECpcq8gTuPC" `
       -Method PUT -Body $wf -ContentType "application/json" `
       -Headers @{"X-N8N-API-KEY"=$key} -UseBasicParsing
   ```

### 排查：PDF 上傳後沒收到 LINE 回覆

依序檢查：

1. **ngrok 在跑嗎？** `Get-Process ngrok`（沒在跑就 `& start_all.bat`）
2. **cloudflared 在跑嗎？** `Get-Process cloudflared`
3. **api_server 在跑嗎？** `Invoke-WebRequest http://localhost:8765/health`
4. **n8n 在跑嗎？** `Invoke-WebRequest http://localhost:5681/healthz`
5. **webhook 從外面通嗎？**
   ```powershell
   Invoke-WebRequest "https://quadruplication-satisfyingly-corrina.ngrok-free.dev/webhook/line-qa" `
       -Method POST -Body '{"events":[]}' -ContentType 'application/json' -UseBasicParsing
   ```
   應回 200。
6. **看 n8n 執行紀錄**：瀏覽器開 `http://localhost:5681` → 左欄 **Executions** → 找 `LINE QA Assistant` 最近的執行 → 點開看哪個 node 紅了
7. **看 api_server stderr**：`Get-Content "$env:LOCALAPPDATA\ai-qa-startup\api_server.log" -Tail 50`
8. **看 LINE Developers Console** → 你的 Bot → Messaging API → Webhook URL 還是不是那串穩定網址？按 **Verify** 應回 Success
9. **webhook intake 層級掉訊息（Executions 看不到、執行紀錄為零）**：
   - 症狀：LINE 有送進來但 n8n 沒有對應 execution、使用者也沒收到回覆。
   - 確認：`docker logs ai-qa-n8n | Select-String "Error in handling webhook request"`，
     或看 ngrok 側錄 `http://localhost:4040/api/requests/http`，LINE 那筆 upstream 狀態若為 `0` 即是。
   - 成因：n8n 在「啟動執行」最前端瞬間失敗（多為主機 I/O/CPU 卡頓時 sqlite 寫入失敗）。
     此類失敗**不會觸發 errorTrigger、不存 execution、不回覆**，且 **LINE 不重送 → 檔案/提問遺失**。
   - 補救：請對方**重傳**（LINE 端內容有下載期限，逾期就拿不回）。
   - 偵測：已由排程任務 `AI-QA-n8n-LogWatchdog`（每 5 分鐘）掃 log，命中即寄告警到 `ALERT_MAIL_TO`。

---

## 變更紀錄：掉訊息偵測 + 錯誤通知修復（2026-06-29）

**背景**：2026-06-29 10:02 一則 LINE 檔案上傳因 n8n intake 層級瞬間失敗被靜默丟棄（全 log 史上僅此 1 次），
使用者毫無感知。基礎設施全程健康，根因為一次性瞬斷 + 兩條告警鏈本來就是斷的。

**修正項目**：
1. **新增 `/notify` 端點**（`scripts/api_server.py`）：寄純文字告警信，收件人 `ALERT_MAIL_TO`（未設則 fallback `FORWARD_MAIL_TO`）。
2. **新增掉訊息 watchdog**（`scripts/watchdog_n8n_log.ps1` + `watchdog_n8n_launch.vbs`）：
   排程任務 `AI-QA-n8n-LogWatchdog` 每 5 分鐘掃 `docker logs ai-qa-n8n` 的
   `Error in handling webhook request`，命中即 POST `/notify` 告警。冪等（state 檔記檢查點，不重複告警）。
3. **修 Error Workflow 通知目標**（n8n `hAz6zL8XtCTWyQ1D`）：
   HTTP 節點原本 POST 到 `host.docker.internal:8080/webhook/n8n-error`（**該 port 無人聽，通知進黑洞**），
   改為 `host.docker.internal:8765/notify`；body 改用正確 errorTrigger 欄位
   （`$json.workflow.name`、`$json.execution.error.message`、`$json.execution.id`、`$json.execution.lastNodeExecuted`），
   並加 `onError=continueRegularOutput` 防止告警自身失敗時連鎖。
4. **新增 `.env`：`ALERT_MAIL_TO`**（系統告警收件人，預設管理者本人）。

**兩條告警鏈的分工**：
- 排程 watchdog → 抓 **intake 層級**靜默掉訊息（不觸發 errorTrigger 的那種）。
- Error Workflow → 抓 **節點層級**錯誤（會觸發 errorTrigger、有存 execution 的那種）。

**待辦（未做，需決策）**：
- n8n DB 由 sqlite 遷移到 PostgreSQL（降低 intake 寫入失敗機率；屬有停機與資料風險的變更）。
- 主機 `Group Policy Client (gpsvc)` 服務每 5 分鐘啟動逾時（每天 ~125 次）— Windows OS 層問題，需管理員權限修復。
