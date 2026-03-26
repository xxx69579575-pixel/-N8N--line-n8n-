# AI 企業問答助理 — 快速安裝主控指南

本文件供 Claude Code CLI 自動讀取並引導安裝流程。

當用戶在新電腦上 clone 此 repo 並執行 `claude` 後，請依照以下步驟順序引導整個安裝過程。

---

## 安裝流程（Claude Code 請依序執行）

### Step 1：偵測作業系統

執行 shell 命令偵測目前作業系統（Windows / macOS / Linux），明確告知用戶偵測結果，並載入對應的安裝指南：

- **Windows** → 讀取 `03_WINDOWS安裝指南.md`
- **macOS** → 讀取 `05_MAC安裝指南.md`
- **Linux / VPS** → 讀取 `04_VPS_Linux安裝指南.md`

```bash
# 偵測 OS 的方式（選其一）
uname -s          # macOS 回傳 Darwin，Linux 回傳 Linux
echo $OSTYPE      # Windows Git Bash 回傳 msys 或 cygwin
```

> 若為 Windows 環境且無 `uname`，PowerShell 可使用：
> ```powershell
> [System.Environment]::OSVersion.Platform
> ```

---

### Step 2：環境檢查

讀取 `01_環境檢查.md`，逐項執行文件中的驗證指令，列出**所有缺少或版本不符的工具**，並協助用戶逐一安裝。

**注意**：環境檢查完成後，Ollama 模型（qwen2.5 + bge-m3）的下載時間較長（合計約 5~6GB），請提醒用戶預留時間。

---

### Step 3：收集用戶資訊

讀取 `02_準備資訊清單.md`，**逐一詢問**用戶所有必要的設定值（API Token、帳密、路徑等）。

詢問格式請參考本文件末尾「詢問用戶時的格式」。

收集完畢後，將所有值寫入 `config/.env`（依照 `02_準備資訊清單.md` 中的範本格式）。

---

### Step 4：執行安裝

依照 Step 1 偵測到的作業系統，執行對應安裝指南中的所有步驟：

1. 啟動 Docker 服務（n8n + PostgreSQL）
2. 初始化資料庫 Schema
3. 啟動 Ollama 並確認模型載入
4. 啟動 Python API Server
5. 設定並啟動 ngrok tunnel
6. 匯入 n8n Workflow
7. 設定 LINE Webhook URL

---

### Step 5：安裝後驗證

讀取 `06_安裝後驗證與測試.md`，逐項驗證各服務是否正常運作。

驗證項目包含：
- PostgreSQL 連線測試
- pgvector 擴充功能確認
- Ollama API 回應測試
- Python API Server 健康檢查
- ngrok tunnel 連通測試
- LINE Webhook 驗證

---

### Step 6：完成報告

安裝完成後，輸出以下格式的服務狀態報告：

```
===== 安裝完成 =====

服務狀態：
  PostgreSQL     http://localhost:65432      [正常]
  pgAdmin        http://localhost:5050       [正常]
  n8n            http://localhost:5681       [正常]
  Ollama         http://localhost:11434      [正常]
  API Server     http://localhost:8765       [正常]
  ngrok tunnel   https://<your-domain>       [正常]

LINE Webhook URL：
  https://<your-domain>/webhook/line
  （請確認已在 LINE Developers Console 設定此 URL）

下一步：
  1. 在瀏覽器開啟 http://localhost:5681 完成 n8n 帳號設定
  2. 匯入 workflows/qa_workflow.json
  3. 在 LINE Developers Console 完成 Webhook 設定
  4. 傳送測試訊息給 LINE Bot 驗證全流程
```

---

## 重要說明

- 所有 API Token / 密碼類資訊請寫入 `config/.env`（**絕對不要 commit 此檔案**，.gitignore 已排除）
- n8n Workflow 需從 `workflows/qa_workflow.json` 匯入
- 資料庫 Schema 需執行 `n8n自動存入資料庫/02_postgresql_schema.sql`
- LINE Webhook URL 格式：`https://<ngrok-domain>/webhook/line`
- Python API Server 是 n8n 與 PostgreSQL / Ollama 的中間橋接層，**必須在 n8n Workflow 啟動前先運行**

---

## 詢問用戶時的格式

每次詢問用戶輸入設定值時，請遵循以下格式：

```
[設定項目名稱]
  用途：說明這個值的用途
  取得方式：說明在哪個網站/頁面/命令可以取得
  範例值：（如有範例則提供）

請輸入您的 <設定項目名稱>：
```

等待用戶輸入後，確認格式正確再繼續下一個項目。若用戶輸入有誤，指出問題並請其重新輸入。

---

## 目錄結構參考

```
本地AI企業問答助理/
├── 快速安裝指南/
│   ├── CLAUDE.md                   ← 本文件（AI 主控指南）
│   ├── 01_環境檢查.md
│   ├── 02_準備資訊清單.md
│   ├── 03_WINDOWS安裝指南.md
│   ├── 04_VPS_Linux安裝指南.md
│   ├── 05_MAC安裝指南.md
│   └── 06_安裝後驗證與測試.md
├── config/
│   └── .env                        ← 用戶填入的設定值（不 commit）
├── workflows/
│   └── qa_workflow.json            ← n8n 問答流程匯入檔
├── docker_n8n/
│   └── docker-compose.yml
├── docker_postgreSQL/
│   └── docker-compose.yml
├── scripts/
│   └── api_server.py               ← Python API Server（port 8765）
└── n8n自動存入資料庫/
    └── 02_postgresql_schema.sql    ← 完整資料庫 Schema
```
