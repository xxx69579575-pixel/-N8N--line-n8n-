# Task QA-4: n8n LINE QA Assistant 工作流

- [x] 建立 `workflows/qa_workflow.json`，節點順序：
  1. Webhook（POST /webhook/line-qa，接收 LINE 事件）
  2. Execute Command: line_verify（驗證簽章，pipe {body, signature} 進 line_verify.py）
  3. Code node: Parse Verify（解析 valid 結果，若 false → 回覆 200 空 body 後停止）
  4. Code node: Parse Message（取出 line_user_id、message text、replyToken）
  5. Execute Command: vector_search（呼叫 vector_search.py --question）
  6. Code node: Parse Chunks（解析 vector_search 輸出）
  7. PostgreSQL node: 查詢 conversation_sessions（取對話歷史 turns by line_user_id）
  8. Code node: 查詢 allowed_users 白名單（SQL 查詢，無權限則回覆「您無使用權限」並停止）
  9. Execute Command: prompt_builder（組裝 prompt，pipe 進 prompt_builder.py）
  10. Code node: Parse Prompt（解析 system/prompt）
  11. HTTP Request node: 呼叫 Ollama /api/chat（model=qwen2.5，stream=false）
  12. Code node: 取出 Ollama 回覆文字
  13. HTTP Request node: LINE Reply API（回覆使用者）
  14. PostgreSQL node: 更新 conversation_sessions（append 新一輪至 turns）
  15. Code node: 格式化 chunk_ids 為 {uuid1,uuid2} 字串
  16. PostgreSQL node: 寫入 qa_logs
  17. Error Handler（任何節點失敗→回覆「系統發生錯誤，請稍後再試」）
  <!-- 實作說明：
    - 節點 7 改拆為 2 個 Postgres nodes（conversation_sessions + allowed_users）共 19 個節點
    - 節點 14~16 合併為 Post-Reply Processing Code node + 2 個 Postgres nodes
    - Error Handler = Error Trigger + Log Error (Postgres)，無法回覆 LINE（replyToken 在 error context 不可用）
    - responseMode=onReceived，LINE 收到 HTTP 200 立即，非同步處理後續邏輯
  -->
- [x] 確認所有環境變數列在 JSON _comments 區塊（LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, OLLAMA_BASE_URL 等）
  <!-- PROJECT_ROOT, LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, POSTGRES_* 皆已列在 _comments.required_env_vars -->
- [x] 建立 allowed_users 表 DDL 並補入 sql/01_schema.sql
  <!-- DDL 追加至 sql/01_schema.sql 末尾；docker exec pg_container psql 建立實際資料表與 unique index 成功 -->
- [x] git commit workflows/qa_workflow.json, sql/01_schema.sql
  <!-- commit 97f470f: feat: add workflows/qa_workflow.json — LINE QA Assistant n8n workflow + allowed_users table -->
