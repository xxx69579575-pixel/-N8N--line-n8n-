# OPERATIONS.md

本專案的「運行手冊 + 變更紀錄」。每次系統有功能新增、bug 修正、或架構調整，**追加**到「變更紀錄」最上方並更新「系統架構」相關章節。

最後更新：2026-04-27

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

其他副檔名的檔案會在 `/line-download-content` 被回 415 拒絕，不入庫。

### LINE 訊息流程

**文字訊息**（QA / 找檔案 / 問檔案 …）→ 既有 5 條分支處理（vector_search → Ollama 生成 / search_files / 檔案類型選單 / 關鍵字輸入 / file_qa）。

**檔案/圖片訊息**（PDF / Word / Excel / JPG / JPEG / PNG）：

1. LINE Webhook → 簽章驗證 → Parse Message（**每筆 event 各一個 item**，支援一次多檔）
2. Intent Router 判 `file_upload` → `Route File Upload` (IF) → file_upload 鏈
3. **per-item**：`/line-download-content` 把檔下載進 `inbox/<BUCKET>/`
4. **batch**：`Aggregate Paths` 收齊所有 file_path → `/forward-mail`（**單次 API 呼叫，多附件一封信**）→ `Distribute Mail Result` 再分回 N items
5. **per-item**：`/ingest-file`（extract → chunk → embed → DB → 移到 `processed/`）
6. **per-item**：`Build Upload Reply` → `LINE Reply: Upload`（**每份檔案各一條 LINE 回覆**）

---

## 變更紀錄

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
