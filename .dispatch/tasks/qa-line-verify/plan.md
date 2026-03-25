# Task QA-1: LINE 簽章驗證腳本

- [x] 建立 `scripts/line_verify.py`：從 stdin 讀 JSON {body, signature}，用 LINE_CHANNEL_SECRET 計算 HMAC-SHA256，輸出 {"valid": true/false}
- [x] 驗證正確簽章：用 Python 手動計算正確 signature 後 pipe 進去，確認 valid=true
- [x] 驗證錯誤簽章：pipe 進錯誤 signature，確認 valid=false
- [x] git commit scripts/line_verify.py — commit 0877134
