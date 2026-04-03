# 本地AI企業問答助理 — Dispatch Alias 清單

> 複製以下 YAML 貼入 `~/.dispatch/config.yaml` 的 `aliases:` 區塊

---

## 複雜度分類邏輯

| 模型 | 適用場景 |
|------|---------|
| **haiku** | 單步驟：環境設定、SQL 執行、config 建立、驗收測試確認 |
| **sonnet** | 中等：Python 腳本開發、n8n 節點設定、多步驟串接任務 |
| **opus** | 高複雜：跨系統安全設計、Hybrid Search 架構、Embedding 遷移策略 |

---

## YAML Aliases

```yaml
aliases:

  # ── Phase 0：基礎環境 ─────────────────────────────────────────

  db-schema:
    model: haiku
    prompt: |
      執行：確認 embedding 維度 → 修正 sql/01_schema.sql VECTOR() → psql 執行 schema → 確認 7 張表存在。
      參考 CLAUDE.md Schema 說明。

  env-setup:
    model: haiku
    prompt: |
      執行：cp config/.env.example config/.env → 建立 D:/AI_KB/inbox|processing|processed|error 資料夾 → 確認 .env 在 .gitignore。
      參考 docs/superpowers/plans/2026-03-25-document-ingest-pipeline.md Task 1。

  # ── Phase 1：文件匯入腳本 ────────────────────────────────────

  ingest-extract:
    model: sonnet
    prompt: |
      建立 scripts/extract_text.py，支援 .docx/.pdf/.xlsx/.xls/.jpg/.jpeg/.png。
      掃描 PDF 需用 pdf2image + pytesseract（poppler 已安裝）。
      同步更新 requirements.txt（含 pdf2image==1.17.0, fpdf2==2.7.9）。
      輸出：JSON {text, metadata{file_name,file_ext,file_path,file_size,hash_sha256}, ocr_used, page_count}。
      參考 docs/superpowers/plans/2026-03-25-document-ingest-pipeline.md Task 2。

  ingest-chunk-embed:
    model: sonnet
    prompt: |
      建立 scripts/chunk_text.py（chunk-size=800, overlap=150）與 scripts/embed_chunks.py（呼叫 Ollama /api/embed）。
      embed_chunks.py 從 stdin 讀 chunks JSON，每個 chunk 加入 embedding 欄位。
      使用環境變數 OLLAMA_BASE_URL、OLLAMA_EMBED_MODEL。
      參考 docs/superpowers/plans/2026-03-25-document-ingest-pipeline.md Task 3。

  ingest-db-write:
    model: sonnet
    prompt: |
      建立 scripts/write_to_db.py，依序寫入：documents（含 hash 去重 + skip log）→ document_contents → document_chunks → document_permissions（DEFAULT_DEPARTMENT/ACCESS_LEVEL）→ processing_logs。
      去重時呼叫 log_processing_no_doc 寫入 skip 記錄再返回。
      參考 docs/superpowers/plans/2026-03-25-document-ingest-pipeline.md Task 4。

  ingest-workflow:
    model: sonnet
    prompt: |
      在 n8n 建立 Enterprise Doc Ingest 工作流（排程1分鐘）：
      Schedule → List → Filter → Move-to-Processing → Extract → Parse → Chunk → Embed → Write-to-DB → Move-to-Processed/Error。
      去重在 write_to_db.py 內，n8n 不設 Check Duplicate 節點。
      匯出為 workflows/ingest_workflow.json。
      參考 docs/superpowers/plans/2026-03-25-document-ingest-pipeline.md Task 5。

  ingest-acceptance:
    model: haiku
    prompt: |
      執行驗收：Word/PDF/Excel/損毀檔/去重 五個測試案例，回報 pass/fail。
      去重驗收需確認 processing_logs 有 step_name='dedup' 記錄。
      參考 docs/superpowers/plans/2026-03-25-document-ingest-pipeline.md Task 6。

  # ── Phase 2：問答流程 ─────────────────────────────────────────

  qa-line-verify:
    model: haiku
    prompt: |
      建立 scripts/line_verify.py：stdin 讀 {body,signature}，用 LINE_CHANNEL_SECRET 驗 HMAC-SHA256，輸出 {"valid":bool}。
      參考 docs/superpowers/plans/2026-03-25-qa-assistant-workflow.md Task 1。

  qa-vector-search:
    model: sonnet
    prompt: |
      建立 scripts/vector_search.py：呼叫 Ollama embedding → pgvector 相似度查詢 → 輸出 JSON array（含 chunk_id, chunk_text, file_name, similarity）。
      支援 --question, --top-k, --min-sim, --department 參數。
      參考 docs/superpowers/plans/2026-03-25-qa-assistant-workflow.md Task 2。

  qa-prompt-builder:
    model: sonnet
    prompt: |
      建立 scripts/prompt_builder.py：組裝 SYSTEM_PROMPT（不得捏造、不足時明說）+ user prompt（含最近3輪對話歷史、參考內容）。
      輸出 JSON {system, prompt}。
      參考 docs/superpowers/plans/2026-03-25-qa-assistant-workflow.md Task 3。

  qa-workflow:
    model: sonnet
    prompt: |
      在 n8n 建立 LINE QA Assistant 工作流：
      Webhook → 簽章驗證 → 訊息解析 → allowed_users 白名單查詢（無權限回覆並停止）→ 對話記憶查詢 → 向量查詢 → Prompt 組裝 → Qwen2.5 → LINE 回覆 → 對話記憶更新 → QA Log（chunk_ids 先在 Code 節點格式化為 {uuid1,uuid2} PostgreSQL array 字串）→ 錯誤保底回覆。
      匯出為 workflows/qa_workflow.json。
      參考 docs/superpowers/plans/2026-03-25-qa-assistant-workflow.md Task 4。

  qa-acceptance:
    model: haiku
    prompt: |
      執行 7 項驗收：webhook接收/簽章拒絕/無權限/正常問答/無資料回覆/多輪記憶/qa_logs記錄，回報 pass/fail。
      參考 docs/superpowers/plans/2026-03-25-qa-assistant-workflow.md Task 5。

  # ── Phase 3：進階功能（按需） ─────────────────────────────────

  hybrid-search:
    model: opus
    prompt: |
      為 vector_search.py 新增 Hybrid Search：PostgreSQL tsvector + pgvector 結合 RRF 重排。
      需更新 sql/01_schema.sql（tsvector 欄位 + GIN 索引）並新增 --mode hybrid/vector/text 參數。
      參考 専案任務清單.md Phase 3 任務 3-1。

  doc-versioning:
    model: opus
    prompt: |
      設計文件版本控制：同名文件新版進入時，標記舊版 chunks metadata {"archived":true}，vector_search.py 只查未 archived 的 chunk。
      需修改 schema、write_to_db.py 與 vector_search.py。
      參考 專案任務清單.md Phase 3 任務 3-4。

  embed-migration-plan:
    model: opus
    prompt: |
      設計 Embedding 模型遷移策略（零停機）：
      當 embedding 模型從 768 維換至 1024 維時，需批次重新 embed 所有 document_chunks。
      設計：新增 embedding_v2 欄位 → 批次回填 → 切換查詢欄位 → 清除舊欄位。
      包含回滾計畫與進度追蹤機制。
      參考 專案任務清單.md Phase 3 任務 3-6。

  flex-message:
    model: sonnet
    prompt: |
      將 LINE 問答回覆從純文字升級為 Flex Message：
      卡片包含：答案區塊 + 來源文件名稱標籤 + 「換句話問」快速回覆按鈕 + 「回報問題」按鈕。
      修改 qa-workflow 中的 LINE 回覆節點，使用 LINE Flex Message JSON 格式。
      參考 專案任務清單.md Phase 3 任務 3-2。

  user-feedback:
    model: sonnet
    prompt: |
      新增使用者回饋機制：
      1. 在 sql/01_schema.sql 補建 qa_feedback 表（qa_log_id, user_id, rating BOOLEAN, created_at）
      2. 在 Flex Message 回覆後附上讚/倒讚按鈕（postback action）
      3. 在 n8n 新增 postback handler webhook，將 rating 寫入 qa_feedback 表
      參考 專案任務清單.md Phase 3 任務 3-3。

  doc-expiry:
    model: haiku
    prompt: |
      新增文件到期機制：
      1. 在 sql/01_schema.sql 的 documents 表新增 expires_at TIMESTAMPTZ 欄位
      2. 更新 scripts/vector_search.py 查詢加入 AND (d.expires_at IS NULL OR d.expires_at > NOW())
      3. 在 scripts/write_to_db.py 的 insert_document 支援傳入可選的 expires_at 參數
      參考 專案任務清單.md Phase 3 任務 3-5。

  knowledge-gap-report:
    model: sonnet
    prompt: |
      建立知識缺口分析腳本 scripts/knowledge_gap_report.py：
      查詢 qa_logs 表中無對應 retrieved_chunk_ids（或 similarity 低於門檻）的問題，
      按問題類型聚合，輸出 Markdown 報告至 docs/knowledge_gap_YYYYMMDD.md。
      可設定排程每週自動執行。
      參考 專案任務清單.md Phase 3 任務 3-7。

  workflow-backup:
    model: haiku
    prompt: |
      建立 n8n Workflow 自動備份機制：
      1. 撰寫 scripts/backup_n8n_workflows.sh，呼叫 n8n CLI 或 API 匯出所有 workflow JSON
      2. 存至 workflows/backups/YYYYMMDD/ 目錄
      3. 加入 git add + commit 步驟確保備份進版本控制
      參考 專案任務清單.md Phase 3 任務 3-8。
```
