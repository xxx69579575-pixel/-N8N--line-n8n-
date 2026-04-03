# SYSTEM_CONTEXT.md — 系統架構全覽（Claude Bot 分析 Issue 必讀）

> 每次分析 Issue 前請完整閱讀此文件，理解完整資料流後再診斷問題。

## 整體架構

```
LINE 用戶 (手機)
    │  發訊息
    ▼
LINE Messaging API (雲端)
    │  Webhook POST
    ▼
n8n (本機 localhost，透過 ngrok 公開)
    │  HTTP Request 呼叫
    ▼
api_server.py (localhost:8765)  ←── 重要：只有本機可存取，無公開 URL
    │  呼叫子腳本
    ├── scripts/vector_search.py   (語意搜尋)
    ├── scripts/search_files.py    (檔案搜尋)
    ├── scripts/line_verify.py     (簽名驗證)
    ├── scripts/line_reply.py      (發送回覆)
    └── scripts/prompt_builder.py  (Prompt 組裝)
    │  讀取/寫入
    ▼
PostgreSQL (localhost:65432, DB=vectordb)
    └── documents 表：file_name, file_path, chunk_text, embedding
```

## 重要環境設定

| 變數 | 值 | 說明 |
|------|-----|------|
|  | localhost | PostgreSQL |
|  | 65432 | PostgreSQL port |
|  | vectordb | 資料庫名稱 |
|  | D:/智能助理資料庫自動備份 | 檔案匯入目錄 |
|  | D:/智能助理資料庫自動備份/processed | 已處理檔案目錄 |
|  | 未設定（待加入）| api_server.py 的公開 URL 前綴 |
|  | 已設定 | LINE Bot token |

## ngrok 現況

| Port | 用途 | 公開 URL |
|------|------|---------|
| 8080 | GitHub Webhook（Flask） | https://quadruplication-satisfyingly-corrina.ngrok-free.dev |
| **8765** | **api_server.py** | **⚠️ 無公開 URL（問題根源）** |

## 關鍵已知問題：LINE 檔案連結 404

### 資料流（問題所在）

1. LINE 用戶傳訊息「找檔案 楊富段」
2. n8n 呼叫  → 本機正常
3. api_server.py 回傳：
   
4. ❌  是**相對路徑**，n8n 拼成 
5. ❌ LINE 用戶手機點擊 → 無法存取  → **404 或連線失敗**

### 根本原因

 的  產生相對路徑 ，
但  沒有公開 URL，LINE 用戶無法從手機存取。

### 正確修復方式

在  加入  環境變數支援：



 中設定：


## DB file_path 過期問題（次要）

DB 中  儲存舊路徑（如 ），
但檔案實際在 。

 已有 fallback 機制（搜尋 processed 目錄），**本機存取正常**，
但  欄位應更新以保持一致性。

## api_server.py 端點清單

| 方法 | 路徑 | 功能 |
|------|------|------|
| GET | /health | 健康檢查 |
| GET | /list-inbox | 列出待匯入檔案 |
| GET | /files/\<name\> | 下載檔案（需公開 URL 才能讓 LINE 用戶存取） |
| POST | /line-verify | 驗證 LINE Webhook 簽名 |
| POST | /vector-search | 語意搜尋 |
| POST | /search-files | 搜尋檔案名稱，回傳 download_url |
| POST | /prompt-builder | 組裝 Prompt |
| POST | /ingest-file | 匯入檔案至 DB |
| POST | /backup-db | 備份資料庫 |

## 腳本目錄結構



## 修改任何腳本前的必要檢查

1. **api_server.py 修改**：確認  端點回傳正常後才重啟
2. **vector_search.py 修改**：需確認  參數仍存在（PR #45 曾錯誤移除 ）
3. **line_reply.py 修改**： 含 4 個參數（PR #57 已修正）
4. **DB 操作**： 表欄位為 , , , ,

## Bot 修復範圍（重要）

### ✅ Bot 可以自動修復的範圍
目標 repo  下的檔案：
- （HTTP API server）
- 
- 
- 
- 
- 
- 

### ❌ Bot 無法自動修復的範圍（需人工）
| 項目 | 原因 |
|------|------|
| 以下是所有 `src/*.py` 的結構摘要：

---

## 專案架構概覽

### `main.py`
啟動入口。載入環境變數、初始化 `Config` → `DiscordBot` → `Orchestrator` → `GitHubWebhook`，然後以 Flask 啟動 Webhook 伺服器（預設 port 8765）。

---

### `config.py`
純 dataclass 設定，從環境變數讀取：
- GitHub token、repo、webhook secret
- Discord token（ClaudeCode bot + OpenCalw bot）、各頻道 ID
- 閾值：handoff timeout 300s、最大重試 3 次、48hr review timeout、10min thread archive
- 本機服務設定：`api_server_project_root`、port 8765

---

### `orchestrator.py` — 核心協調器（Stage 1–5）

| 方法 | 功能 |
|------|------|
| `assign_issue()` | 評估複雜度 → Discord 通知 → 背景 thread 呼叫 AutoFixer |
| `create_pull_request()` | 組裝標準 PR body，呼叫 GitHub API 建 PR |
| `trigger_pr_review()` | 取 diff → Claude CLI 分析 → 發 GitHub PR comment |
| `trigger_post_merge_sync()` | dedup 後派發背景 thread：Discord thread → 重啟本機服務 → archive |
| `handoff_to_opencalw()` | 轉派任務給 OpenCalw |

---

### `discord_bot.py` — Discord 整合

- `on_message`：監聽 mention → 自然語言轉 GitHub Issue（5 層防重複：dedup set、cooldown file、in-memory lock、GitHub Search API、建立後驗證）
- 偵測「已Merge PR #N」訊息 → 觸發 post-merge 流程
- Thread 建立/通知/archive、各頻道推送（`#agent-hub`、`#logs`、`#review-queue`）

---

### `github_webhook.py` — Webhook 伺服器

- HMAC-SHA256 簽名驗證
- 路由：
  - `issues.opened` → `orchestrator.assign_issue()`
  - `pull_request.opened/synchronize` → `orchestrator.trigger_pr_review()`
  - `pull_request.closed+merged` → 刪 branch → 關 Issue → `trigger_post_merge_sync()`
- `/files/<path>` 反向代理到 `api_server.py:8765`

---

### `auto_fixer.py` — Issue → PR 自動修復

1. 讀取 repo 結構（優先 `SYSTEM_CONTEXT.md`）+ 相關 `.py` 檔案
2. 用關鍵字擷取最相關段落（`_extract_relevant_section`）
3. 呼叫 Claude Code CLI（`claude --print --dangerously-skip-permissions`）返回 JSON 修復方案
4. **Patch 模式**（`old_string` → `new_string`）優先，fallback 為完整 content 模式（有 50% 縮減安全檢查）
5. 建 branch → commit → 開 PR

---

### `service_manager.py` — 本機服務重啟（Windows）

Post-merge 後自動執行：
1. `netstat -ano` 找 PID → `taskkill /F` 殺舊 process
2. `git pull` 同步最新代碼
3. `subprocess.Popen` 背景啟動 `scripts/api_server.py`
4. 輪詢 `/health` 做健康檢查（最多 8 × 1.5s）

---

有想討論的特定模組或想調整的功能嗎？（Bot 自身程式碼） | Chicken-and-egg：Bot 不能修自己 |
| 、 等環境設定檔 | 本機設定，不進版本控制 |
| n8n workflow 設定 | n8n 內部設定，非程式碼 |
| ngrok 設定 | 本機服務，非程式碼 |

### 檔案下載架構（已確認正確）


 設定於：
- 以下是 `.env` 的內容摘要：

**GitHub**
- `GITHUB_TOKEN` / `OPENCALW_GITHUB_TOKEN`：同一個 token（兩個 bot 共用同帳號，PR review 會 skip）
- `GITHUB_REPO`：`xxx69579575-pixel/-N8N--line-n8n-`
- `GITHUB_WEBHOOK_SECRET`：`n8nline`

**Discord Bot Tokens**
- `DISCORD_BOT_TOKEN`：ClaudeCode#6623
- `OPENCALW_BOT_TOKEN`：OpenCalw Astra

**Discord Channel IDs**
- `#agent-hub`：`1487718765717098526`
- `#logs`：`1487728849784406136`
- `#review-queue`：`1487728892709179462`

**Server**
- `PORT=8080`（Flask + ngrok）
- `API_SERVER_BASE_URL`：ngrok 公開網址

> **注意**：`OPENCALW_GITHUB_TOKEN` 和 `GITHUB_TOKEN` 是相同的 token，意味著 PR code review 無法用不同帳號審查，CI 仍會跑但 review 步驟會 skip。如需雙帳號審查功能，需要替換成不同 GitHub 帳號的 token。
- 
每次 ngrok 重啟需更新這兩個檔案。
