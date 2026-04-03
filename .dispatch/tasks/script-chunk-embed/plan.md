# Task 3: 切片與 Embedding 腳本

- [x] 建立 `scripts/chunk_text.py`：接收 --text, --chunk-size(預設800), --overlap(預設150)，輸出 JSON array of {chunk_index, chunk_text, char_count, token_estimate}
- [x] 驗證切片：`python scripts/chunk_text.py --text "$(python -c "print('測試內容 ' * 200)")" --chunk-size 300 --overlap 50` → 7 個 chunk，每個 char_count=300 ✓
- [x] 建立 `scripts/embed_chunks.py`：從 stdin 讀 chunks JSON，對每個 chunk 呼叫 Ollama /api/embeddings（使用 OLLAMA_BASE_URL, OLLAMA_EMBED_MODEL 環境變數），輸出帶 embedding 欄位的 JSON array。注意：Ollama 0.18.2 用 /api/embeddings + prompt 欄位（非 /api/embed + input）
- [x] 驗證 embedding：nomic-embed-text 輸出 embedding length=768 ✓
- [x] 確認 embedding 向量長度：nomic-embed-text = 768 維（與 init.sql VECTOR(768) 一致）；qwen2.5:7b = 3584 維
- [x] git commit scripts/chunk_text.py, scripts/embed_chunks.py → commit 245fb22
