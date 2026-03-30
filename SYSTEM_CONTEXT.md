# SYSTEM_CONTEXT.md — 系統架構全覽（Claude Bot 分析 Issue 必讀）

> 每次分析 Issue 前請完整閱讀此文件，理解完整資料流後再診斷問題。

## 整體架構

```
LINE 用戶 (手機)
    │  發訊息
    ▼
LINE Messaging API (雲端)
    │  Webhook POST
    ▼
n8n (本機 localhost，透過 ngrok 公開)
    │  HTTP Request 呼叫
    ▼
api_server.py (localhost:8765)  ←── 重要：只有本機可存取，無公開 URL
    │  呼叫子腳本
    ├── scripts/vector_search.py   (語意搜尋)
    ├── scripts/search_files.py    (檔案搜尋)
    ├── scripts/line_verify.py     (簽名驗證)
    ├── scripts/line_reply.py      (發送回覆)
    └── scripts/prompt_builder.py  (Prompt 組裝)
    │  讀取/寫入
    ▼
PostgreSQL (localhost:65432, DB=vectordb)
    └── documents 表：file_name, file_path, chunk_text, embedding
```

## 重要環境設定

| 變數 | 值 | 說明 |
|------|-----|------|
|  | localhost | PostgreSQL |
|  | 65432 | PostgreSQL port |
|  | vectordb | 資料庫名稱 |
|  | D:/智能助理資料庫自動備份 | 檔案匯入目錄 |
|  | D:/智能助理資料庫自動備份/processed | 已處理檔案目錄 |
|  | 未設定（待加入）| api_server.py 的公開 URL 前綴 |
|  | 已設定 | LINE Bot token |

## ngrok 現況

| Port | 用途 | 公開 URL |
|------|------|---------|
| 8080 | GitHub Webhook（Flask） | https://quadruplication-satisfyingly-corrina.ngrok-free.dev |
| **8765** | **api_server.py** | **⚠️ 無公開 URL（問題根源）** |

## 關鍵已知問題：LINE 檔案連結 404

### 資料流（問題所在）

1. LINE 用戶傳訊息「找檔案 楊富段」
2. n8n 呼叫  → 本機正常
3. api_server.py 回傳：
   
4. ❌  是**相對路徑**，n8n 拼成 
5. ❌ LINE 用戶手機點擊 → 無法存取  → **404 或連線失敗**

### 根本原因

 的  產生相對路徑 ，
但  沒有公開 URL，LINE 用戶無法從手機存取。

### 正確修復方式

在  加入  環境變數支援：



 中設定：


## DB file_path 過期問題（次要）

DB 中  儲存舊路徑（如 ），
但檔案實際在 。

 已有 fallback 機制（搜尋 processed 目錄），**本機存取正常**，
但  欄位應更新以保持一致性。

## api_server.py 端點清單

| 方法 | 路徑 | 功能 |
|------|------|------|
| GET | /health | 健康檢查 |
| GET | /list-inbox | 列出待匯入檔案 |
| GET | /files/\<name\> | 下載檔案（需公開 URL 才能讓 LINE 用戶存取） |
| POST | /line-verify | 驗證 LINE Webhook 簽名 |
| POST | /vector-search | 語意搜尋 |
| POST | /search-files | 搜尋檔案名稱，回傳 download_url |
| POST | /prompt-builder | 組裝 Prompt |
| POST | /ingest-file | 匯入檔案至 DB |
| POST | /backup-db | 備份資料庫 |

## 腳本目錄結構



## 修改任何腳本前的必要檢查

1. **api_server.py 修改**：確認  端點回傳正常後才重啟
2. **vector_search.py 修改**：需確認  參數仍存在（PR #45 曾錯誤移除 ）
3. **line_reply.py 修改**： 含 4 個參數（PR #57 已修正）
4. **DB 操作**： 表欄位為 , , , ,