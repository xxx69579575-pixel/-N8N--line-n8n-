# Task QA-3: Prompt 組裝腳本

- [x] 建立 `scripts/prompt_builder.py`：
    - 從 stdin 讀 JSON {question, chunks: [{chunk_text, file_name, similarity}], history: [{role, content}]}
    - history 只取最近 3 輪（最多 6 筆）
    - 組裝 system prompt：「你是企業內部知識問答助理，只能根據以下參考內容回答。若參考內容不足以回答，請明確告知，不得捏造或補充未驗證資訊。」
    - 組裝 user prompt：含對話歷史 + 參考內容（含 file_name）+ 問題
    - 輸出 JSON {system, prompt}
- [x] 驗證：echo 一筆測試 JSON（含 question + 2 個 chunks + 2 輪 history）pipe 進去，確認輸出 system 與 prompt 欄位非空且格式正確（輸出 valid UTF-8 JSON，所有 assertion 通過）
- [x] git commit scripts/prompt_builder.py（commit f9ca2c3）
