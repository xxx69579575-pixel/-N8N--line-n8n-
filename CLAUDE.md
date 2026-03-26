# AI 企業問答助理 — 快速安裝主控指南

> **此分支（快速安裝）專為在新電腦上快速部署而設計。**
> 詳細安裝步驟請讀取 `快速安裝指南/CLAUDE.md`，以下為快速入口。

---

## Claude Code 請立即執行

1. 讀取 `快速安裝指南/CLAUDE.md` — 取得完整安裝流程
2. 依序執行：偵測 OS → 環境檢查 → 收集用戶資訊 → 安裝 → 驗證

---

<!-- 以下為開發參考（安裝時不需閱讀）-->
## 專案定位

本地 AI 企業問答助理，採 RAG 架構。兩條主要 n8n 工作流：

1. **文件匯入流程**：掃描本地資料夾 → 抽文字/OCR → 切片 → Embedding → 寫入 PostgreSQL + pgvector
2. **問答流程**：LINE 提問 → Embedding → pgvector 檢索 → Qwen2.5 生成回答 → LINE 回覆

核心技術棧：n8n（流程引擎）、Ollama + Qwen2.5（本地 LLM）、PostgreSQL + pgvector（向量知識庫）、LINE Messaging API（使用者入口）

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

## 已知關鍵衝突

**向量維度不一致**：`docker_postgreSQL/init.sql` 寫 `VECTOR(768)`，`n8n自動存入資料庫/02_postgresql_schema.sql` 寫 `VECTOR(1024)`。實際部署前必須先確認使用哪個 embedding 模型，統一後再執行 schema。

| 模型 | 維度 |
|------|------|
| nomic-embed-text | 768 |
| bge-m3 | 1024 |

---

## 資料庫 Schema 結構

五張核心表（定義在 `n8n自動存入資料庫/02_postgresql_schema.sql`）：

- `documents`：文件主檔，含 hash_sha256 去重、ingest_status、department、confidential_level
- `document_contents`：全文與解析結果，含 ocr_used、parse_status
- `document_chunks`：切片內容 + `embedding VECTOR(1024)` + page_no/sheet_name/section_title
- `document_permissions`：部門與角色層級的存取控制
- `processing_logs`：每一步驟的處理紀錄與錯誤追蹤

向量索引使用 `ivfflat`（cosine），`lists = 100`。所有表有 `updated_at` trigger 自動維護。

**Schema 尚缺**（需補建）：
- `qa_logs`：問答日誌（user_id、question、retrieved_chunk_ids、answer、confidence、created_at）
- `conversation_sessions`：對話記憶（line_user_id、turns JSONB、updated_at）

---

## 環境變數

整合自兩份規格書，建立 `.env.example` 時需涵蓋以下所有變數：

```
# 資料夾路徑
INGEST_INBOX_DIR=
INGEST_PROCESSING_DIR=
INGEST_PROCESSED_DIR=
INGEST_ERROR_DIR=

# PostgreSQL
POSTGRES_HOST=
POSTGRES_PORT=65432
POSTGRES_DB=vectordb
POSTGRES_USER=testuser
POSTGRES_PASSWORD=testpwd

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=qwen2.5
OLLAMA_EMBED_MODEL=nomic-embed-text

# 文件匯入
EMBEDDING_API_URL=
OCR_API_URL=
DEFAULT_DEPARTMENT=
DEFAULT_ACCESS_LEVEL=view

# LINE
LINE_CHANNEL_ACCESS_TOKEN=
LINE_CHANNEL_SECRET=

# 問答參數
QA_TOP_K=5
QA_MIN_SIMILARITY=0.7
DEFAULT_NO_ANSWER_MESSAGE=
```

---

## 工作流模組拆分

**文件匯入流程**（8 個子模組）：
檔案掃描 → metadata + hash → 文件解析（Word/PDF/Excel） → OCR → 文字切片 → embedding → PostgreSQL 寫入 → 錯誤處理

**問答流程**（8 個子模組）：
LINE ingress → 簽章驗證 + auth → embedding → vector search → prompt builder → LLM → LINE reply → QA logging

---

## 重要實作限制

- **去重必須用 SHA-256**，不可只靠檔名
- **LINE Webhook 必須驗證簽章**（`X-Line-Signature` header + `LINE_CHANNEL_SECRET`）
- **LINE Webhook 需公開 HTTPS URL**（本機 n8n 需透過 ngrok 或 Cloudflare Tunnel 暴露）
- **單一檔案失敗不可中斷整批**，每個錯誤分支都需寫 processing_logs 並移檔至 error 資料夾
- **RAG 硬性要求**：Qwen2.5 必須根據檢索到的 chunk 回答，查無資料時明確告知，不得自行補充未驗證資訊

---

## 參考文件

| 檔案 | 用途 |
|------|------|
| `n8n自動存入資料庫/01_n8n工作流規劃.md` | 文件匯入流程詳細設計（含 Mermaid 流程圖） |
| `n8n自動存入資料庫/03_ClaudeCode開發規格書.md` | 文件匯入流程驗收標準與交付物清單 |
| `企業問答助理line+n8n+向量庫/01_企業問答助理_n8n工作流設計.md` | 問答流程詳細設計 |
| `企業問答助理line+n8n+向量庫/02_ClaudeCode開發規格書_企業問答助理.md` | 問答流程驗收標準 |
| `專案任務清單.md` | 完整任務清單（含 Phase 0~4 + 未規劃的建議功能） |
