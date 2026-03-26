# VPS / Linux 伺服器安裝指南

> 適用環境：Ubuntu 22.04 LTS / Debian 11+（amd64）

---

## VPS 建議規格

| 項目 | 最低需求 | 建議配置 |
|------|----------|----------|
| vCPU | 2 核 | 4 核以上（Ollama 推理需要） |
| RAM | 8 GB（勉強可運行） | 16 GB 以上 |
| 磁碟 | 20 GB | 40 GB 以上 SSD |
| OS | Ubuntu 20.04 | Ubuntu 22.04 LTS |
| 網路 | 固定 IP（或 ngrok tunnel） | 固定 IP + 固定 domain |

> 若 VPS 記憶體不足 16GB，Ollama 可能無法流暢運行 qwen2.5:7b。可嘗試更小的量化版本（如 `qwen2.5:3b-instruct-q4_0`）或僅使用 API 模式而不本地推理。

---

## Step 1：更新系統並安裝基礎工具

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget python3 python3-pip build-essential
```

安裝 Python 依賴：

```bash
pip3 install psycopg2-binary
```

確認安裝：

```bash
python3 --version
pip3 show psycopg2-binary
```

---

## Step 2：安裝 Docker Engine

```bash
# 使用官方一鍵安裝腳本
curl -fsSL https://get.docker.com | sh

# 將目前用戶加入 docker 群組（避免每次都需要 sudo）
sudo usermod -aG docker $USER

# 套用群組變更（或重新登入 SSH）
newgrp docker

# 確認版本
docker --version
docker compose version
```

**設定 Docker 開機啟動：**

```bash
sudo systemctl enable docker
sudo systemctl start docker
```

**驗證安裝：**

```bash
docker run hello-world
```

---

## Step 3：安裝 Ollama

```bash
# 官方安裝腳本
curl -fsSL https://ollama.ai/install.sh | sh
```

**設定 Ollama 為 systemd 服務（開機自動啟動）：**

建立 systemd unit 檔：

```bash
sudo nano /etc/systemd/system/ollama.service
```

填入以下內容：

```ini
[Unit]
Description=Ollama Local LLM Service
After=network-online.target

[Service]
ExecStart=/usr/local/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3
Environment="HOME=/usr/share/ollama"

[Install]
WantedBy=default.target
```

> 若 Ollama 安裝時已自動建立 systemd 服務，可跳過此步驟，直接執行 `sudo systemctl enable ollama`。

啟用並啟動服務：

```bash
sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl start ollama

# 確認狀態
sudo systemctl status ollama
```

**下載所需模型：**

```bash
# 等待 Ollama 啟動（約 5 秒）
sleep 5

ollama pull qwen2.5:7b-instruct-q4_0
ollama pull bge-m3
```

> 注意：bge-m3 約 1.2GB，qwen2.5:7b 約 4.7GB，請確保磁碟與記憶體充足。

**驗證 Ollama：**

```bash
curl http://localhost:11434/api/tags
```

---

## Step 4：安裝 ngrok

```bash
# 使用官方 apt 套件庫安裝
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok

# 確認版本
ngrok --version
```

**設定 authtoken（先至 https://dashboard.ngrok.com 取得 token）：**

```bash
ngrok config add-authtoken <YOUR_NGROK_TOKEN>
```

**設定 ngrok tunnel（路徑：`~/.config/ngrok/ngrok.yml`）：**

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

**驗證 ngrok 設定（測試模式）：**

```bash
ngrok start api-server
```

成功後按 `Ctrl+C` 停止，正式啟動改用 systemd 服務。

---

## Step 5：Clone 專案並設定

```bash
# Clone 專案到家目錄
cd ~
git clone https://github.com/xxx69579575-pixel/-N8N-.git
cd -N8N-

# 複製環境變數範本
cp config/.env.example config/.env
nano config/.env
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

找到 volumes 設定，將 Windows 路徑改為 Linux 路徑：

```yaml
volumes:
  - n8n_data:/home/node/.n8n
  - /home/你的用戶名/-N8N-:/workspace   # 改成你的實際路徑
```

例如（假設用戶名為 `ubuntu`）：

```yaml
  - /home/ubuntu/-N8N-:/workspace
```

---

## Step 6：啟動 PostgreSQL + pgvector

```bash
cd ~/‐N8N-/docker_postgreSQL
docker compose up -d

# 等待資料庫初始化
sleep 10

# 確認容器狀態
docker ps
```

確認 `pg_container` 狀態為 `Up` 後，執行 Schema 建立：

**方式 A：直接用 Docker exec 執行（推薦，不需另裝 psql）**

```bash
docker exec -i pg_container psql -U testuser -d vectordb < ../n8n自動存入資料庫/02_postgresql_schema.sql
```

**方式 B：安裝 psql client 後執行**

```bash
sudo apt install -y postgresql-client
psql -h localhost -p 65432 -U testuser -d vectordb -f ../n8n自動存入資料庫/02_postgresql_schema.sql
```

**驗證 Schema：**

```bash
docker exec -it pg_container psql -U testuser -d vectordb -c "\dt"
```

應顯示 5 張表：`documents`、`document_contents`、`document_chunks`、`document_permissions`、`processing_logs`。

---

## Step 7：啟動 n8n

```bash
cd ~/‐N8N-/docker_n8n
docker compose up -d

# 確認容器狀態
docker ps
```

**VPS 存取方式：**

- 透過 VPS 公網 IP：`http://<VPS_IP>:5681`
- 若設有反向代理（Nginx/Caddy），可設定子域名

> **安全提醒**：n8n 預設無 HTTPS，VPS 上建議設定 Nginx + Let's Encrypt 或使用 Cloudflare Tunnel 保護 n8n 管理介面。

首次開啟完成 n8n 初始設定（建立 Owner 帳號）。

---

## Step 8：設定 systemd 服務（開機自動啟動）

### 8.1 Python API Server 服務

```bash
sudo nano /etc/systemd/system/api_server.service
```

填入以下內容（注意修改路徑和用戶名）：

```ini
[Unit]
Description=Local AI QA API Server
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/-N8N-
ExecStart=/usr/bin/python3 /home/ubuntu/-N8N-/scripts/api_server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 8.2 ngrok Tunnel 服務

```bash
sudo nano /etc/systemd/system/ngrok.service
```

填入以下內容：

```ini
[Unit]
Description=ngrok Tunnel Service
After=network-online.target api_server.service
Wants=network-online.target
Requires=api_server.service

[Service]
Type=simple
User=ubuntu
ExecStart=/usr/bin/ngrok start api-server
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 8.3 啟用所有服務

```bash
sudo systemctl daemon-reload

# 啟用開機自動啟動
sudo systemctl enable api_server
sudo systemctl enable ngrok

# 立即啟動
sudo systemctl start api_server
sudo systemctl start ngrok

# 確認狀態
sudo systemctl status api_server
sudo systemctl status ngrok
```

**查看服務日誌：**

```bash
# API Server 日誌
sudo journalctl -u api_server -f

# ngrok 日誌
sudo journalctl -u ngrok -f
```

---

## Step 9：防火牆設定（ufw）

```bash
# 安裝 ufw（若尚未安裝）
sudo apt install -y ufw

# 允許 SSH（重要：先設定 SSH，避免鎖死）
sudo ufw allow 22/tcp

# 允許 n8n 管理介面（若需從外部存取）
sudo ufw allow 5681/tcp

# pgAdmin（視需求，建議只允許特定 IP）
# sudo ufw allow from <你的IP> to any port 5050

# 注意：port 8765 不需要對外開放，ngrok 會透過 tunnel 處理
# 注意：port 65432 不需要對外開放

# 啟用防火牆
sudo ufw enable

# 確認規則
sudo ufw status verbose
```

> **安全建議**：若 VPS 在公網，建議限制 n8n（5681）和 pgAdmin（5050）只允許你的 IP 存取，避免暴露管理介面。

---

## Step 10：匯入 n8n Workflow 並設定 LINE Webhook

### 匯入 Workflow

1. 登入 n8n 後台（`http://<VPS_IP>:5681`）
2. 點選左側選單 → **Workflows** → **Import Workflow**
3. 上傳 `workflows/qa_workflow.json`

### 設定 LINE Credentials

1. 點擊 LINE 相關節點 → Credentials → **Create New**
2. 填入 Channel Access Token 和 Channel Secret

### 啟用 Workflow

點選 Workflow 右上角開關，切換為 **Active**。

### 設定 LINE Webhook

1. 前往 [LINE Developers Console](https://developers.line.biz/)
2. Messaging API → **Webhook settings**
3. Webhook URL：`https://<你的ngrok域名>/webhook/line`
4. 點擊 **Verify** 確認

---

## 常見問題排解（VPS）

| 問題 | 解決方法 |
|------|----------|
| Ollama 記憶體不足 OOM | 改用更小量化模型：`ollama pull qwen2.5:3b-instruct-q4_0` |
| `docker: permission denied` | 確認用戶在 docker 群組：`sudo usermod -aG docker $USER`，然後重新登入 |
| n8n volumes 路徑錯誤 | 確認路徑存在且有讀寫權限：`ls -la /home/ubuntu/-N8N-` |
| psql 執行 schema 失敗 | 確認 pg_container 已完全啟動，可用 `docker logs pg_container` 查看 |
| ngrok service 啟動失敗 | 確認 `~/.config/ngrok/ngrok.yml` 設定正確，且 authtoken 有效 |
| API Server 無法連線 PostgreSQL | 確認環境變數 `POSTGRES_HOST=host.docker.internal`（Python 直接在 host 運行時用 `localhost`）|
| n8n 連不到 Ollama | 確認 n8n docker-compose 設定 `OLLAMA_BASE_URL=http://host.docker.internal:11434` |
| VPS 重開機後服務未啟動 | 確認所有服務都有 `systemctl enable`，並用 `systemctl status` 排查 |

---

## 完整啟動順序確認清單

每次重開機後，依序確認以下服務狀態：

```bash
# 一次查看所有服務狀態
sudo systemctl status docker ollama api_server ngrok
docker ps
```

- [ ] Docker Engine 運行中
- [ ] `pg_container` 容器已啟動
- [ ] `ai-qa-n8n` 容器已啟動
- [ ] Ollama 服務運行中（`curl http://localhost:11434/api/tags`）
- [ ] API Server 運行中（`curl http://localhost:8765/health`）
- [ ] ngrok tunnel 已建立（`sudo journalctl -u ngrok -n 20`）
- [ ] n8n Workflow 狀態為 Active
