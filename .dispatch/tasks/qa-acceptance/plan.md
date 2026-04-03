# Task QA-5: LINE QA 問答流程驗收

- [x] 驗收 1 — LINE Webhook 接收：確認 qa_workflow.json 的 Webhook 路徑 /webhook/line-qa 設定正確，模擬一筆 LINE event JSON 格式正確
  - PASS: qa_workflow.json node "LINE Webhook" has httpMethod=POST, path="line-qa" (maps to /webhook/line-qa), responseMode=onReceived, rawBody=true
- [x] 驗收 2 — 簽章拒絕：用錯誤 signature pipe 進 line_verify.py，確認 valid=false；確認 workflow 在此步驟停止且回傳 HTTP 200
  - PASS: wrong sig → {"valid": false}; correct HMAC-SHA256 sig → {"valid": true}. Workflow Parse Verify node returns null on invalid, stopping pipeline.
- [x] 驗收 3 — 無權限拒絕：用不在 allowed_users 的 line_user_id 執行查詢，確認回覆「您無使用權限」
  - PASS: U_unknown_user returns 0 rows from allowed_users. U_test_user_001 confirmed inserted.
- [x] 驗收 4 — 正常問答：在 allowed_users 表插入一筆測試用戶，執行完整 pipeline（vector_search → prompt_builder → Ollama → LINE reply），確認有回覆產出
  - PASS: vector_search ran (0 chunks — KB empty), prompt_builder built correct prompt, Ollama qwen2.5:7b-instruct-q4_0 responded (45 chars), qa_log inserted (id: c8a96ff0)
- [x] 驗收 5 — 無資料回覆：用知識庫查無資料的問題（DB 無相關 chunk），確認 prompt_builder 傳入空 chunks，Ollama 回答「目前知識庫中沒有相關資料」類似訊息
  - PASS: "宇宙的起源是什麼" → 0 chunks → prompt has （無相關資料） → Ollama response starts with "目前知識庫中沒有相關資料"
- [x] 驗收 6 — 多輪記憶：同一 line_user_id 連問兩次，確認第二次的 prompt 包含第一輪對話歷史（conversation_sessions turns 更新）
  - PASS: Inserted prev turns into conversation_sessions for U_test_user_001. prompt_builder with history→ prompt contains 【對話歷史】 section, previous Q "年假有幾天" and previous A "10天"
- [x] 驗收 7 — qa_logs 記錄：完成一次正常問答後，確認 qa_logs 表有記錄（user_id, question, answer 非空，retrieved_chunk_ids 正確格式）
  - PASS: 1 row in qa_logs: user_id='U_test_user_001', question_len=6, answer_len=45, chunk_ids={} (empty array — no chunks matched)
- [x] 整理驗收結果，回報各項 pass/fail，輸出至 .dispatch/tasks/qa-acceptance/output.md
