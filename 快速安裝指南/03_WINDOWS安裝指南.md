# Windows 安裝指南

> 適用環境：Windows 10 / Windows 11（64 位元）

---

## 前置需求確認

執行以下快速檢查，確認目前系統狀態：

```bat
:: 確認 Docker
docker --version

:: 確認 Python
python --version

:: 確認 Git
git --version

:: 確認 Ollama
ollama --version

:: 確認 ngrok
ngrok --version
```

---

## Step 1：安裝 Docker Desktop for Windows

1. 前往 https://www.docker.com/products/docker-desktop/ 下載 Windows 版安裝程式
2. 執行安裝程式，安裝過程中選擇 **Use WSL 2 instead of Hyper-V**
3. 安裝完成後重新開機
4. 啟動 Docker Desktop，等待系統列出現 Docker 圖示且狀態為 Running

**驗證安裝：**

```bat
docker run hello-world
```

出現 `Hello from Docker!` 表示安裝成功。

**若 Docker 無法啟動：**

確認 WSL2 已啟用：

```powershell
wsl --install
wsl --set-default-version 2
```

---

## Step 2：安裝 Python 3.10+

1. 前往 https://www.python.org/downloads/ 下載最新 Python 3.10 或以上版本
2. 執行安裝程式，**務必勾選「Add Python to PATH」**
3. 選擇「Customize installation」→ 確認勾選 pip

**安裝 Python 依賴：**

```bat
pip install psycopg2-binary
```

> 注意：必須安裝 `psycopg2-binary`（含編譯好的二進位），不要安裝 `psycopg2`（需要本地編譯環境）。

**驗證安裝：**

```bat
python --version
pip show psycopg2-binary
```

---

## Step 3：安裝 Ollama for Windows

1. 前往 https://ollama.ai/download 下載 Windows 版安裝程式
2. 執行安裝，完成後 Ollama 會在背景自動啟動
3. 下載所需模型（**注意：bge-m3 約 1.2GB，qwen2.5 約 4.7GB，請確保磁碟空間充足**）：

```bat
ollama pull qwen2.5:7b-instruct-q4_0
ollama pull bge-m3
```

**驗證 Ollama 運作：**

```bat
ollama list
curl http://localhost:11434/api/tags
```

> Ollama 安裝完成後預設隨系統啟動，port 為 11434。

---

## Step 4：安裝 ngrok for Windows

1. 前往 https://ngrok.com/download 下載 Windows 版 zip
2. 解壓縮，將 `ngrok.exe` 放到 `C:\ngrok\`
3. 將 `C:\ngrok\` 加入系統環境變數 PATH：
   - 右鍵「本機」→「內容」→「進階系統設定」→「環境變數」
   - 在「系統變數」中找到 `Path`，新增 `C:\ngrok`

4. 設定 authtoken（先至 https://dashboard.ngrok.com 取得 token）：

```bat
ngrok config add-authtoken <YOUR_NGROK_TOKEN>
```

5. 設定靜態 domain tunnel。編輯 ngrok 設定檔（路徑：`%APPDATA%\ngrok\ngrok.yml`）：

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

```bat
ngrok start api-server
```

成功後會顯示類似 `Forwarding https://xxxx.ngrok-free.app -> http://localhost:8765`。

---

## Step 5：Clone 專案並設定環境變數

```bat
git clone https://github.com/xxx69579575-pixel/-N8N-.git
cd -N8N-
```

複製環境變數範本並填入實際值：

```bat
copy config\.env.example config\.env
notepad config\.env
```

需填入的關鍵變數：

| 變數 | 說明 |
|------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developers Console 取得 |
| `LINE_CHANNEL_SECRET` | LINE Developers Console 取得 |
| `OLLAMA_BASE_URL` | Docker 內填 `http://host.docker.internal:11434` |
| `POSTGRES_HOST` | Docker 內填 `host.docker.internal` |

**修改 n8n Docker Compose 的 volumes 路徑：**

編輯 `docker_n8n\docker-compose.yml`，找到 volumes 設定，將專案路徑改為你實際的路徑：

```yaml
volumes:
  - n8n_data:/home/node/.n8n
  - D:/你的實際路徑/-N8N-:/workspace   # 改成你的路徑，注意使用正斜線
```

> Windows 路徑在 Docker compose 中使用正斜線（`/`），例如：`D:/projects/-N8N-:/workspace`

---

## Step 6：啟動 PostgreSQL + pgvector

```bat
cd docker_postgreSQL
docker compose up -d
```

等待約 10 秒讓資料庫完成初始化，確認容器正常運作：

```bat
docker ps
```

確認 `pg_container` 狀態為 `Up` 後，執行 Schema 建立：

**方式 A：使用 psql（需另行安裝 PostgreSQL client）**

```bat
psql -h localhost -p 65432 -U testuser -d vectordb -f n8n自動存入資料庫\02_postgresql_schema.sql
```

**方式 B：使用 Docker exec（不需要安裝 psql）**

```bat
docker exec -i pg_container psql -U testuser -d vectordb < n8n自動存入資料庫\02_postgresql_schema.sql
```

**方式 C：使用 pgAdmin**
- 開啟瀏覽器，前往 http://localhost:5050
- 帳號：`admin@admin.com`，密碼：`root`
- 連線 PostgreSQL：hostname 填 `db`，port `5432`，user `testuser`，password `testpwd`
- 在 Query Tool 中貼上 `02_postgresql_schema.sql` 內容執行

**驗證 Schema：**

```bat
docker exec -it pg_container psql -U testuser -d vectordb -c "\dt"
```

應顯示 5 張表：`documents`、`document_contents`、`document_chunks`、`document_permissions`、`processing_logs`。

---

## Step 7：啟動 n8n

```bat
cd ..\docker_n8n
docker compose up -d
```

確認容器啟動：

```bat
docker ps
```

確認 `ai-qa-n8n` 容器狀態為 `Up` 後，開啟瀏覽器：

```
http://localhost:5681
```

首次開啟需完成 n8n 初始設定：
1. 建立 Owner 帳號（輸入 Email 和密碼）
2. 完成歡迎設定精靈

---

## Step 8：匯入 n8n Workflow

1. 登入 n8n 後台（http://localhost:5681）
2. 點選左側選單 → **Workflows**
3. 點選右上角 **Import Workflow**（或 `...` 選單中的 Import）
4. 選擇專案中的 `workflows\qa_workflow.json`，點擊匯入

**設定 LINE Credentials：**

1. 在 Workflow 中找到 LINE 相關節點（LINE Webhook、LINE Reply）
2. 點擊節點 → Credentials → **Create New**
3. 填入：
   - Channel Access Token：LINE Developers Console 的 `Channel access token`
   - Channel Secret：LINE Developers Console 的 `Channel secret`

**啟用 Workflow：**

點選 Workflow 右上角的開關，將狀態切換為 **Active**。

---

## Step 9：啟動 Python API Server

使用專案根目錄的批次檔啟動：

```bat
start_api_server.bat
```

或手動啟動：

```bat
cd "D:\你的專案目錄"
python scripts\api_server.py
```

**驗證 API Server 正常運作：**

開啟瀏覽器或執行：

```bat
curl http://localhost:8765/health
```

應回傳：`{"status":"ok"}`

---

## Step 10：啟動 ngrok

使用專案根目錄的批次檔：

```bat
start_ngrok.bat
```

或手動啟動：

```bat
ngrok start api-server
```

成功後終端機會顯示：

```
Forwarding   https://<你的ngrok域名> -> http://localhost:8765
```

記下這個 HTTPS URL，下一步設定 LINE Webhook 時需要用到。

---

## Step 11：設定 LINE Webhook

1. 前往 [LINE Developers Console](https://developers.line.biz/)
2. 選擇你的 Bot Channel → **Messaging API** 分頁
3. 找到 **Webhook settings**
4. 在 Webhook URL 填入：`https://<你的ngrok域名>/webhook/line`
5. 點擊 **Verify** 按鈕確認連線

驗證成功後，用 LINE 掃描 Bot 的 QR Code 加為好友，即可傳送訊息測試。

---

## Windows 開機自動啟動設定

讓 API Server 和 ngrok 在 Windows 開機後自動啟動：

**建立 start_api_server.bat（若尚未存在）：**

```bat
@echo off
cd /d "D:\你的專案目錄"
python scripts\api_server.py
```

**建立 start_ngrok.bat（若尚未存在）：**

```bat
@echo off
ngrok start api-server
```

**加入開機啟動：**

1. 按 `Win + R`，輸入 `shell:startup`，開啟啟動資料夾
2. 在啟動資料夾中建立以下兩個捷徑：
   - `start_api_server.bat` 的捷徑
   - `start_ngrok.bat` 的捷徑

**其他元件開機設定：**

- **Ollama**：安裝後預設自動設定為開機啟動
- **Docker Desktop**：開啟 Docker Desktop → Settings → General → 勾選「Start Docker Desktop when you sign in to your computer」

---

## 常見問題排解（Windows）

| 問題 | 解決方法 |
|------|----------|
| Docker Desktop 無法啟動 | 確認已啟用 WSL2：在 PowerShell 執行 `wsl --install` |
| `psycopg2` 安裝失敗 | 確認使用 `pip install psycopg2-binary`，不是 `psycopg2` |
| Port 5681 被佔用 | 修改 `docker_n8n\docker-compose.yml` 的外部 port，例如改為 `5682:5678` |
| Port 65432 被佔用 | 修改 `docker_postgreSQL\docker-compose.yml` 的外部 port |
| ngrok tunnel 無法建立 | 確認 authtoken 正確，並確認網路可連線到 ngrok 服務 |
| n8n 容器無法連線 PostgreSQL | 確認 `docker-compose.yml` 中 `POSTGRES_HOST` 設為 `host.docker.internal` |
| API Server 啟動後 /health 無回應 | 確認 port 8765 未被其他程式佔用：`netstat -ano \| findstr :8765` |
| LINE Webhook Verify 失敗 | 確認 ngrok 正在運行且 API Server 已啟動，並確認 URL 格式正確 |

---

## 完整啟動順序確認清單

每次重新開機後，依序確認以下服務已啟動：

- [ ] Docker Desktop 已運行
- [ ] `pg_container` 容器已啟動（`docker ps`）
- [ ] `ai-qa-n8n` 容器已啟動（`docker ps`）
- [ ] Ollama 服務已運行（`curl http://localhost:11434/api/tags`）
- [ ] Python API Server 已啟動（`curl http://localhost:8765/health`）
- [ ] ngrok tunnel 已建立（終端機顯示 Forwarding URL）
- [ ] n8n Workflow 狀態為 Active（http://localhost:5681）
