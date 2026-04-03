# Task 0+1: DB Schema 統一 + 環境設定

- [x] 確認 Ollama embedding 模型維度：用戶確認使用 bge-m3，VECTOR(1024)。nomic-embed-text 未安裝；bge-m3 將由用戶 `ollama pull bge-m3` 安裝。
- [x] 建立 `sql/` 目錄，複製 `n8n自動存入資料庫/02_postgresql_schema.sql` 為 `sql/01_schema.sql`；原始已是 VECTOR(1024)，無需修正。
- [x] 在 `sql/01_schema.sql` 末尾補建 qa_logs 與 conversation_sessions 兩張表（含索引）
- [x] 啟動 Docker：`docker compose -f docker_postgreSQL/docker-compose.yml up -d`，舊 documents 表（init.sql 版）先 DROP CASCADE，再 `docker exec -i pg_container psql ... < sql/01_schema.sql` 成功執行。
- [x] 驗證 7 張表全部存在：documents、document_contents、document_chunks、document_permissions、processing_logs、qa_logs、conversation_sessions ✓
- [x] 建立 `config/` 目錄，建立 `config/.env.example`（含所有環境變數，OLLAMA_EMBED_MODEL=bge-m3）
- [x] 建立 inbox 資料夾結構：D:/AI_KB/inbox、processing、processed、error ✓
- [x] 確認 `config/.env` 加入 `.gitignore`，git commit schema + env 變更（commit 8f1d1e0）
