# macOS 安裝指南

> 適用環境：macOS 12.0 Monterey 以上
> 支援：Apple Silicon（M1 / M2 / M3）及 Intel 晶片

---

## 前置需求確認

開啟「終端機（Terminal）」，執行以下快速檢查：

```bash
# 確認 Homebrew
brew --version

# 確認 Docker
docker --version

# 確認 Python
python3 --version

# 確認 Git
git --version

# 確認 Ollama
ollama --version

# 確認 ngrok
ngrok --version
```

---

## Step 1：安裝 Homebrew（若尚未安裝）

Homebrew 是 macOS 最常用的套件管理工具，後續大多數工具都透過它安裝。

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**Apple Silicon（M1/M2/M3）額外設定：**

安裝完成後，Homebrew 會提示需要將路徑加入 shell 設定。依照終端機提示執行（通常是以下兩行）：

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

**驗證安裝：**

```bash
brew --version
```

---

## Step 2：安裝 Docker Desktop for Mac

1. 前往 https://www.docker.com/products/docker-desktop/ 下載 Mac 版
2. **Apple Silicon（M1/M2/M3）**：選擇 **Apple Chip** 版本
3. **Intel Mac**：選擇 **Intel Chip** 版本
4. 開啟下載的 `.dmg`，拖曳 Docker 到「應用程式」資料夾
5. 開啟 Docker Desktop，等待選單列出現 Docker 圖示且狀態顯示 Running

**驗證安裝：**

```bash
docker run hello-world
docker compose version
```

> macOS 12.0 (Monterey) 以下版本不受支援，請先升級系統。

---

## Step 3：安裝 Python 和依賴

```bash
# 使用 Homebrew 安裝 Python 3.11
brew install python@3.11

# 安裝 Python 依賴
pip3 install psycopg2-binary
```

**驗證安裝：**

```bash
python3 --version
pip3 show psycopg2-binary
```

> 注意：macOS 預裝的 Python 通常是 2.7，請確認使用的是 python3 指令。

---

## Step 4：安裝 Ollama for Mac

```bash
# 使用 Homebrew 安裝
brew install ollama

# 在背景啟動 Ollama（測試用）
ollama serve &

# 下載所需模型
ollama pull qwen2.5:7b-instruct-q4_0
ollama pull bge-m3
```

**設定 Ollama 開機自動啟動（使用 brew services）：**

```bash
brew services start ollama
```

**確認 Ollama 服務狀態：**

```bash
brew services list | grep ollama
curl http://localhost:11434/api/tags
```

> **Apple Silicon 優勢**：Ollama 在 M1/M2/M3 上有 Metal GPU 加速，推理速度遠優於 CPU 模式，qwen2.5:7b 可達到流暢回應速度。

---

## Step 5：安裝 ngrok for Mac

```bash
# 使用 Homebrew 安裝
brew install ngrok/ngrok/ngrok

# 確認版本
ngrok --version
```

**設定 authtoken（先至 https://dashboard.ngrok.com 取得 token）：**

```bash
ngrok config add-authtoken <YOUR_NGROK_TOKEN>
```

**設定靜態 domain tunnel（路徑：`~/.config/ngrok/ngrok.yml`）：**

```bash
nano ~/.config/ngrok/ngrok.yml
```

填入以下內容：

```yaml
version: "2"
authtoken: <YOUR_NGROK_TOKEN>
tunnels:
  api-server:
    proto: http
    addr: 8765
    domain: <YOUR_NGROK_DOMAIN>
```

> `<YOUR_NGROK_DOMAIN>` 可在 ngrok 後台的 Domains 頁面取得或建立靜態網域。

**驗證 ngrok 設定：**

```bash
ngrok start api-server
```

成功後按 `Ctrl+C` 停止。

> **首次執行 ngrok 可能遇到安全性警告**：前往「系統偏好設定（或系統設定）→ 安全性與隱私權」，點擊「仍要開啟」允許 ngrok 執行。

---

## Step 6：Clone 專案並設定

```bash
# Clone 專案
git clone https://github.com/xxx69579575-pixel/-N8N-.git
cd -N8N-

# 複製環境變數範本並填入值
cp config/.env.example config/.env
nano config/.env
# 或使用文字編輯器：open -e config/.env
```

**config/.env 關鍵設定：**

```env
# PostgreSQL（從 n8n Docker 容器訪問 host）
POSTGRES_HOST=host.docker.internal
POSTGRES_PORT=65432
POSTGRES_DB=vectordb
POSTGRES_USER=testuser
POSTGRES_PASSWORD=testpwd

# Ollama（從 n8n Docker 容器訪問 host）
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_CHAT_MODEL=qwen2.5:7b-instruct-q4_0
OLLAMA_EMBED_MODEL=bge-m3

# LINE
LINE_CHANNEL_ACCESS_TOKEN=你的token
LINE_CHANNEL_SECRET=你的secret
```

**修改 n8n Docker Compose volumes 路徑：**

```bash
nano docker_n8n/docker-compose.yml
```

找到 volumes 設定，將路徑改為你在 macOS 上的實際路徑：

```yaml
volumes:
  - n8n_data:/home/node/.n8n
  - /Users/你的用戶名/-N8N-:/workspace
```

例如（用戶名為 `john`）：

```yaml
  - /Users/john/-N8N-:/workspace
```

> 若不確定用戶名，在終端機執行 `echo $USER` 或 `whoami`。

---

## Step 7：啟動 PostgreSQL + pgvector

```bash
cd ~/‐N8N-/docker_postgreSQL
docker compose up -d

# 等待資料庫初始化
sleep 10

# 確認容器狀態
docker ps
```

確認 `pg_container` 狀態為 `Up` 後，執行 Schema 建立：

**方式 A：使用 Docker exec（推薦，不需另裝 psql）**

```bash
docker exec -i pg_container psql -U testuser -d vectordb < ../n8n自動存入資料庫/02_postgresql_schema.sql
```

**方式 B：使用 Homebrew 安裝 psql**

```bash
brew install postgresql
psql -h localhost -p 65432 -U testuser -d vectordb -f ../n8n自動存入資料庫/02_postgresql_schema.sql
```

**驗證 Schema：**

```bash
docker exec -it pg_container psql -U testuser -d vectordb -c "\dt"
```

應顯示 5 張表：`documents`、`document_contents`、`document_chunks`、`document_permissions`、`processing_logs`。

---

## Step 8：啟動 n8n

```bash
cd ~/‐N8N-/docker_n8n
docker compose up -d

# 確認容器狀態
docker ps
```

確認 `ai-qa-n8n` 狀態為 `Up` 後，開啟瀏覽器：

```
http://localhost:5681
```

首次開啟完成 n8n 初始設定（建立 Owner 帳號）。

---

## Step 9：匯入 n8n Workflow

1. 登入 n8n 後台（http://localhost:5681）
2. 點選左側選單 → **Workflows** → **Import Workflow**
3. 選擇專案中的 `workflows/qa_workflow.json`，點擊匯入

**設定 LINE Credentials：**

1. 點擊 LINE 相關節點 → Credentials → **Create New**
2. 填入：
   - Channel Access Token：LINE Developers Console 的 token
   - Channel Secret：LINE Developers Console 的 secret

**啟用 Workflow：**

點選 Workflow 右上角的開關，切換為 **Active**。

---

## Step 10：啟動 Python API Server

```bash
cd ~/‐N8N-
python3 scripts/api_server.py
```

**驗證 API Server：**

```bash
curl http://localhost:8765/health
```

應回傳：`{"status":"ok"}`

---

## Step 11：啟動 ngrok

```bash
ngrok start api-server
```

成功後終端機會顯示：

```
Forwarding   https://<你的ngrok域名> -> http://localhost:8765
```

---

## Step 12：設定 LINE Webhook

1. 前往 [LINE Developers Console](https://developers.line.biz/)
2. Messaging API → **Webhook settings**
3. Webhook URL：`https://<你的ngrok域名>/webhook/line`
4. 點擊 **Verify** 確認連線成功

---

## macOS 開機自動啟動設定

使用 macOS 的 **LaunchAgent** 機制讓 API Server 和 ngrok 開機自動啟動。

### API Server LaunchAgent

建立 plist 檔：

```bash
nano ~/Library/LaunchAgents/com.local.api_server.plist
```

填入以下內容（修改路徑和用戶名）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.api_server</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/你的用戶名/-N8N-/scripts/api_server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/你的用戶名/-N8N-</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/api_server.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/api_server_error.log</string>
</dict>
</plist>
```

> Apple Silicon 用戶：python3 路徑可能是 `/opt/homebrew/bin/python3`，用 `which python3` 確認。

### ngrok LaunchAgent

建立 plist 檔：

```bash
nano ~/Library/LaunchAgents/com.local.ngrok.plist
```

填入以下內容：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.ngrok</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/ngrok</string>
        <string>start</string>
        <string>api-server</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/ngrok.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/ngrok_error.log</string>
</dict>
</plist>
```

> Intel Mac 的 ngrok 路徑為 `/usr/local/bin/ngrok`，Apple Silicon 為 `/opt/homebrew/bin/ngrok`。用 `which ngrok` 確認。

### 載入 LaunchAgent

```bash
# 載入兩個服務
launchctl load ~/Library/LaunchAgents/com.local.api_server.plist
launchctl load ~/Library/LaunchAgents/com.local.ngrok.plist

# 確認已載入
launchctl list | grep com.local
```

**其他元件開機設定：**

- **Ollama**：已透過 `brew services start ollama` 設定開機啟動
- **Docker Desktop**：開啟 Docker Desktop → Settings → General → 勾選「Start Docker Desktop when you log in」

---

## Apple Silicon（M1/M2/M3）特別注意事項

### Metal GPU 加速

Ollama 在 Apple Silicon 上會自動使用 Metal GPU 加速，qwen2.5:7b 首次載入後回應速度相當流暢。可透過以下指令確認 GPU 使用情況：

```bash
# 確認 Ollama 使用 Metal
ollama run qwen2.5:7b-instruct-q4_0 "你好"
# 觀察 Activity Monitor → GPU History
```

### Docker 映像檔架構

確認 Docker 使用 arm64 原生映像（不透過 Rosetta 模擬）：

```bash
# 確認 PostgreSQL 映像架構
docker inspect pg_container | grep Architecture
# 應顯示 "arm64"
```

若出現 Rosetta 相關警告或 pgvector 運算問題，在 Docker Desktop 設定中：
- 前往 **Settings → General**
- **取消勾選**「Use Rosetta for x86/amd64 emulation on Apple Silicon」（pgvector 的 SIMD 加速需要原生 arm64）

### Homebrew 路徑差異

Apple Silicon 的 Homebrew 安裝路徑為 `/opt/homebrew/`，Intel Mac 為 `/usr/local/`。若遇到指令找不到的問題，確認 PATH 設定：

```bash
echo $PATH | tr ':' '\n' | grep homebrew
```

---

## 常見問題排解（macOS）

| 問題 | 解決方法 |
|------|----------|
| Docker Desktop 無法啟動 | 確認 macOS 版本 12.0+，或嘗試重新安裝 Docker Desktop |
| Port 65432 被佔用 | 修改 `docker_postgreSQL/docker-compose.yml` 的外部 port |
| Port 5681 被佔用 | 修改 `docker_n8n/docker-compose.yml` 的外部 port |
| ngrok 首次執行被系統封鎖 | 前往「系統設定 → 隱私權與安全性」→ 點擊「仍要開啟」 |
| psycopg2 安裝失敗 | 確認使用 `pip3 install psycopg2-binary`（含二進位）|
| LaunchAgent 未載入 | 確認 plist 路徑正確，用 `launchctl list \| grep com.local` 確認 |
| API Server 起動後 /health 無回應 | 確認 port 8765 未被佔用：`lsof -i :8765` |
| n8n 連不到 Ollama | 確認 docker-compose.yml 設定 `OLLAMA_BASE_URL=http://host.docker.internal:11434` |
| Docker volumes 路徑錯誤 | 確認路徑使用 `/Users/用戶名/...` 格式，不要用 `~` |

---

## 完整啟動順序確認清單

每次重新開機後（若未設定自動啟動），依序執行：

```bash
# 確認 Docker Desktop 已啟動（等待選單列圖示顯示 Running）

# 確認容器
docker ps

# 確認 Ollama
curl http://localhost:11434/api/tags

# 啟動 API Server（若未設 LaunchAgent）
cd ~/‐N8N- && python3 scripts/api_server.py &

# 啟動 ngrok（若未設 LaunchAgent）
ngrok start api-server &

# 確認 API Server
curl http://localhost:8765/health
```

- [ ] Docker Desktop 運行中
- [ ] `pg_container` 容器已啟動
- [ ] `ai-qa-n8n` 容器已啟動
- [ ] Ollama 服務運行中
- [ ] Python API Server 已啟動（http://localhost:8765/health）
- [ ] ngrok tunnel 已建立
- [ ] n8n Workflow 狀態為 Active（http://localhost:5681）
