# Task QA-2: 向量檢索腳本

- [x] 建立 `scripts/vector_search.py`：
    - CLI 參數：--question（必填）、--top-k（預設 5）、--min-sim（預設 0.7）、--department（可選）
    - 呼叫 Ollama /api/embeddings 取得 question 的 embedding
    - 對 document_chunks 執行 pgvector cosine 相似度查詢，JOIN documents 取 file_name
    - 若有 --department 則加入 WHERE 條件（從 document_permissions JOIN）
    - 輸出 JSON array：[{chunk_id, chunk_text, file_name, similarity}]
- [x] 驗證：python scripts/vector_search.py --question "公司請假流程" --top-k 3，確認輸出 JSON 格式正確（即使無結果也輸出空 array）
    - 輸出：[] （embedding dim=768，nomic-embed-text，DB 目前無資料，正確輸出空 array）
- [x] git commit scripts/vector_search.py （be39bdd）
