# Task 4: write_to_db.py — 寫入資料庫腳本

- [x] 建立 `scripts/write_to_db.py`，實作以下功能：
    - `get_db_connection()` → 從環境變數取得 PostgreSQL 連線（POSTGRES_HOST/PORT/DB/USER/PASSWORD）
    - `document_exists(conn, hash_sha256)` → 查詢 documents 表，依 hash_sha256 判斷是否已存在，回傳 document_id 或 None
    - `log_processing_no_doc(conn, file_name, step, message)` → 寫入 processing_logs（document_id=NULL，step_name=step，status='skipped'，error_message=message）
    - `insert_document(conn, metadata, ocr_used, page_count)` → 寫入 documents，回傳 document_id（UUID）
    - `insert_content(conn, document_id, text, ocr_used, page_count)` → 寫入 document_contents
    - `insert_chunks(conn, document_id, chunks_with_embeddings)` → 批次寫入 document_chunks（含 embedding）
    - `insert_permissions(conn, document_id)` → 寫入 document_permissions（使用 DEFAULT_DEPARTMENT / DEFAULT_ACCESS_LEVEL 環境變數）
    - `log_processing(conn, document_id, step, status, message)` → 寫入 processing_logs
    - `main()` → 從 stdin 讀取 JSON（含 metadata, text, chunks with embeddings, ocr_used, page_count），依序執行：hash 去重 → insert_document → insert_content → insert_chunks → insert_permissions → log_processing('complete','success')；去重時呼叫 log_processing_no_doc 後直接 return
- [x] 建立測試：手動組裝一筆小資料（text, metadata, 1 個帶 embedding 的 chunk），pipe 進 write_to_db.py，驗證資料庫確實寫入 — document_id=8b031036, chunk fbbc6d42 寫入成功
  - `PGPASSWORD=testpwd psql -h localhost -p 65432 -U testuser -d vectordb -c "SELECT id, file_name FROM documents LIMIT 5;"`
- [x] 測試去重：再次 pipe 同一筆資料，確認 processing_logs 有 step_name='dedup', status='skipped' 記錄 — log 已寫入，message='skipped: document already exists (id=8b031036...)'
- [x] git commit scripts/write_to_db.py — commit 2489b9d
