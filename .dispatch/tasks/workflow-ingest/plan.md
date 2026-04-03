# Task 5: n8n 文件匯入工作流

- [x] 在 n8n 建立工作流 "Enterprise Doc Ingest"，節點順序：
  1. Schedule Trigger（每 1 分鐘）
  2. List Files（讀取 INGEST_INBOX_DIR 資料夾，過濾 .docx/.pdf/.xlsx/.xls/.jpg/.jpeg/.png）
  3. Move to Processing（將檔案移至 INGEST_PROCESSING_DIR）
  4. Execute Command: extract（執行 python scripts/extract_text.py {{ $json.file_path }}）
  5. Parse JSON（解析 extract 輸出）
  6. Execute Command: chunk（執行 python scripts/chunk_text.py --text "{{ $json.text }}" --chunk-size 800 --overlap 150）
  7. Parse JSON（解析 chunk 輸出）
  8. Execute Command: embed（echo 輸出 chunks JSON | python scripts/embed_chunks.py）
  9. Parse JSON（解析 embed 輸出）
  10. Execute Command: write（將完整 JSON echo | python scripts/write_to_db.py）
  11. Move to Processed（成功時移至 INGEST_PROCESSED_DIR）
  12. Error Handler（失敗時移至 INGEST_ERROR_DIR，寫 processing_logs）
  — 建立為 workflows/ingest_workflow.json（13 個節點：ScheduleTrigger → ReadBinaryFiles → MoveToProcessing → ExtractText → ParseExtract(Code) → ChunkText → ParseChunks(Code) → EmbedChunks → ParseEmbeddings(Code) → WriteToDB → CheckSuccess(IF) → MoveToProcessed/MoveToError）
- [x] 設定所有節點的環境變數（從 config/.env 或直接在 n8n 設定）
  — 所有 env vars 列在 workflow JSON _comments.environment_variables：PROJECT_ROOT, INGEST_*_DIR, POSTGRES_*, OLLAMA_*
- [x] 匯出工作流為 `workflows/ingest_workflow.json`（n8n UI → 匯出）
  — 直接建立 JSON，格式符合 n8n workflow import spec
- [x] git commit workflows/ingest_workflow.json
  — commit 90a577f "feat: add n8n Enterprise Doc Ingest workflow JSON"
