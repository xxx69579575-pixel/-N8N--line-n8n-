# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **實作狀態：✅ 全部完成並驗收通過（2026-03-26）**
> **2026-04-27 新增：LINE 檔案上傳 → 自動轉寄 mail + 同步加入知識庫**（詳見 `OPERATIONS.md`）

## 專案定位

本地 AI 企業問答助理，採 RAG 架構。三條運行中的 n8n 工作流：

1. **文件匯入流程**（`ingest_workflow_v2.json`）：每小時掃描 `D:\智能助理資料庫自動備份` → 抽文字/OCR → 切片 → Embedding → 寫入 PostgreSQL + pgvector
2. **問答流程**（`qa_workflow.json`）：LINE 提問 → Embedding → pgvector 檢索 → Qwen2.5 生成回答 → LINE 回覆。同時負責 **LINE 檔案上傳分支**：PDF/Word/Excel/JPG → 下載 → 寄信 → 入庫
3. **自動備份**（`backup_workflow.json`）：每天凌晨 2:00 備份 PostgreSQL，保留最近 7 份

核心技術棧：n8n（流程引擎）、Ollama + Qwen2.5（本地 LLM）、bge-m3（Embedding）、PostgreSQL + pgvector（向量知識庫）、LINE Messaging API（使用者入口）、Python API Server（n8n 與本地腳本的橋接層）、Gmail SMTP（檔案轉寄）

---

## 啟動資料庫

```bash
cd docker_postgreSQL
docker compose up -d
```

- PostgreSQL：`localhost:65432`，DB `vectordb`，user `testuser`，password `testpwd`
- pgAdmin：`http://localhost:5050`，帳號 `admin@admin.com`，密碼 `root`
- 連接 pgAdmin 時，PostgreSQL hostname 填 `db`（docker 內部 hostname）

建立完整 Schema（5 張表 + trigger）：

```bash
psql -h localhost -p 65432 -U testuser -d vectordb -f n8n自動存入資料庫/02_postgresql_schema.sql
```

> `init.sql` 僅含基礎 `documents` 表（向量維度 768），完整 schema 請用 `02_postgresql_schema.sql`（向量維度 1024）。

---

## 系統啟動順序

**現在已自動化** — Windows 開機後 Task Scheduler `AI-QA-Assistant-Startup` 觸發 `start_all.bat`：等 n8n ready → 啟動 ngrok（n8n 穩定網域）→ 啟動 cloudflared（api_server 動態網址，自動寫進 `.env`）→ 重啟 api_server。詳見 `OPERATIONS.md`。

手動啟動：

```bash
# 1. Docker（PostgreSQL + n8n）
cd docker_postgreSQL && docker compose up -d
# n8n 網址：http://localhost:5681

# 2. Ollama（開機自動啟動）

# 3. 一鍵啟動所有對外 tunnel + api_server
start_all.bat
```

LINE Webhook URL（**穩定，不再變動**）：
```
https://quadruplication-satisfyingly-corrina.ngrok-free.dev/webhook/line-qa
```

---

## Python API Server（scripts/api_server.py，port 8765）

所有 n8n workflow 均透過 HTTP Request 節點呼叫，n8n 2.12+ 已封鎖 executeCommand。

| 端點 | 方法 | 功能 |
|------|------|------|
| `/health` | GET | 健康檢查 |
| `/list-inbox` | GET | 掃描文件收件匣（所有檔案 department 一律 `general`） |
| `/files/<name>` | GET | 下載原始檔案 |
| `/line-verify` | POST | LINE 簽章驗證 |
| `/vector-search` | POST | pgvector 相似度搜尋 |
| `/prompt-builder` | POST | 組裝 RAG Prompt |
| `/search-files` | POST | 按關鍵字搜尋檔案 |
| `/ingest-file` | POST | 單檔完整匯入 pipeline |
| `/backup-db` | POST | 觸發 PostgreSQL 備份 |
| `/line-download-content` | POST | **新** 從 LINE Content API 下載使用者上傳的檔案 |
| `/forward-mail` | POST | **新** 透過 Gmail SMTP 寄附件信，支援單檔 (`file_path`) 或多附件 (`file_paths`) |

---

## 向量維度說明

**已確認使用 bge-m3（1024 維）**。`docker_postgreSQL/init.sql` 為舊版（768 維），**請勿使用**，一律用 `02_postgresql_schema.sql`。

| 模型 | 維度 | 使用狀態 |
|------|------|----------|
| bge-m3 | 1024 | ✅ 目前使用 |
| nomic-embed-text | 768 | ❌ 舊版，已棄用 |

---

## 資料庫 Schema 結構

完整 Schema 定義在 `n8n自動存入資料庫/02_postgresql_schema.sql`。

**文件匯入相關（5 張表）**：
- `documents`：文件主檔，含 hash_sha256 去重、ingest_status、department、confidential_level
- `document_contents`：全文與解析結果，含 ocr_used、parse_status
- `document_chunks`：切片內容 + `embedding VECTOR(1024)` + page_no/sheet_name/section_title
- `document_permissions`：部門與角色層級的存取控制
- `processing_logs`：每一步驟的處理紀錄與錯誤追蹤

**問答流程相關（2 張表）**：
- `qa_logs`：問答日誌（user_id、question、retrieved_chunk_ids、answer、confidence、created_at）
- `allowed_users`：LINE Bot 授權白名單（`line_user_id`、`display_name`、`department`）

> **新增使用者**：`INSERT INTO allowed_users (line_user_id, display_name, department) VALUES ('U...', '顯示名', 'general');` — 未授權者上傳檔案會被 Check Auth 擋下。

向量索引使用 `ivfflat`（cosine），`lists = 100`。所有表有 `updated_at` trigger 自動維護。

---

## 環境變數

實際設定在 `config/.env`（gitignore），範本在 `config/.env.example`。

```
# 資料夾路徑
INGEST_INBOX_DIR=D:/智能助理資料庫自動備份
INGEST_PROCESSED_DIR=D:/智能助理資料庫自動備份/processed
INGEST_ERROR_DIR=D:/智能助理資料庫自動備份/error
BACKUP_DIR=D:/智能助理資料庫自動備份
BACKUP_KEEP=7

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=65432
POSTGRES_DB=vectordb
POSTGRES_USER=testuser
POSTGRES_PASSWORD=testpwd

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=qwen2.5:7b-instruct-q4_0
OLLAMA_EMBED_MODEL=bge-m3

# LINE
LINE_CHANNEL_ACCESS_TOKEN=（實際值存於 config/.env）
LINE_CHANNEL_SECRET=（實際值存於 config/.env）

# 問答參數
QA_TOP_K=5
QA_MIN_SIMILARITY=0.3
DEFAULT_NO_ANSWER_MESSAGE=目前知識庫中沒有相關資料

# API Server 對外 URL（cloudflared 動態，由 start_all.ps1 自動更新）
API_SERVER_BASE_URL=https://<random>.trycloudflare.com

# SMTP 寄信（LINE 使用者上傳檔案 → 自動轉寄）
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=（Gmail 帳號）
SMTP_PASSWORD=（Gmail App Password，16 字元）
FORWARD_MAIL_TO=（收件人 email）
```

---

## 文件收件匣資料夾結構（2026-04-27 重整）

```
D:\智能助理資料庫自動備份\        ← INGEST_INBOX_DIR
   PDF\          ← .pdf
   WORD\         ← .doc / .docx
   EXCEL\        ← .xls / .xlsx
   JPG\          ← .jpg / .jpeg / .png（含 LINE 上傳的圖片）
   processed\    ← 匯入成功後自動移來（保留子資料夾結構）
   error\        ← 匯入失敗後自動移來
```

**所有檔案 `department` 欄位一律標 `general`**（不再用第一層子資料夾名當部門）。要分部門請改 `_handle_list_inbox` 邏輯。

---

## 工作流模組拆分

**文件匯入流程**（每小時 cron）：
GET /list-inbox → Split 逐檔 → POST /ingest-file（extract→chunk→embed→write_to_db）→ 移至 processed/error

**問答流程**（單一 workflow，多分支）：

LINE Webhook → 簽章驗證 → Parse Message → Query Session Early → Intent Router → Query allowed_users → Check Auth → Route File Upload (IF)
- **TRUE 分支（檔案/圖片上傳）**：Execute: line_download_content → Aggregate Paths → Execute: forward_mail（一次寄多附件）→ Distribute Mail Result → Execute: ingest_file_upload → Build Upload Reply → LINE Reply: Upload
- **FALSE 分支（文字訊息）**：Intent Switch → 5 條子分支（QA / 找檔案執行 / 檔案類型選單 / 關鍵字輸入 / file_qa）

---

## 重要實作限制

- **去重必須用 SHA-256**，不可只靠檔名
- **LINE Webhook 必須驗證簽章**（`X-Line-Signature` header + `LINE_CHANNEL_SECRET`）
- **LINE Webhook 需公開 HTTPS URL**（用 ngrok 穩定子網域 → n8n:5681；URL 一次設好永久不動）
- **檔案下載 URL** 用 cloudflared 動態網址 → api_server:8765；URL 變了由 `start_all.ps1` 自動寫進 `.env`
- **單一檔案失敗不可中斷整批**，每個錯誤分支都需寫 processing_logs 並移檔至 error 資料夾
- **RAG 硬性要求**：Qwen2.5 必須根據檢索到的 chunk 回答，查無資料時明確告知，不得自行補充未驗證資訊
- **LINE 檔案上傳支援的副檔名**：`.pdf .doc .docx .xls .xlsx .jpg .jpeg .png`（白名單，其他類型 `/line-download-content` 回 415）
- **n8n switch v3 最多 5 outputs**：file_upload 改用獨立 IF (`Route File Upload`) 在 Intent Switch 之前分流

---

## 參考文件

| 檔案 | 用途 |
|------|------|
| `OPERATIONS.md` | **運行手冊 + 變更紀錄**（每次系統變動都記在這） |
| `n8n自動存入資料庫/01_n8n工作流規劃.md` | 文件匯入流程詳細設計（含實作完成記錄） |
| `n8n自動存入資料庫/03_ClaudeCode開發規格書.md` | 文件匯入驗收結果與交付物清單 |
| `企業問答助理line+n8n+向量庫/01_企業問答助理_n8n工作流設計.md` | 問答流程詳細設計（含 API 端點、備份說明） |
| `企業問答助理line+n8n+向量庫/02_ClaudeCode開發規格書_企業問答助理.md` | 問答流程驗收結果（含額外功能清單） |
| `n8n自動存入資料庫/02_postgresql_schema.sql` | 完整資料庫 Schema（7 張資料表 + trigger） |
| `快速安裝指南/CLAUDE.md` | 一鍵安裝控制文件（Windows/VPS/Mac） |
| `專案任務清單.md` | 完整任務清單（Phase 0~4 全部完成） |
