# SOP：Discord 回報 → Issue → PR → Merge → 自動重啟

> **主 Bot：ClaudeCode#6623**（Discord ID `1484454025893253162`）
> Stage 1–5 全程自動化，唯一需要人工的是 Stage 4（Merge）。

---

## 流程總覽

```
用戶 @ClaudeCode → Issue 建立 → 開 Discord 討論串
  → Multi-turn Agent（最多 25 輪）→ PR 建立
  → CI Lint → Bot Code Review → 用戶 Merge
  → 刪 branch → 關 Issue → git pull → 重啟服務
```

---

## 系統架構

```
src/
├── main.py              啟動入口（Flask + Discord Bot）
├── config.py            環境變數
├── discord_bot.py       Discord 事件監聽 + GitHub Issue 建立 + 討論串管理
├── orchestrator.py      Stage 1–5 業務流程協調
├── claude_agent.py      ★ Multi-turn Agent（claude --print 迴圈 + 8 種工具）
├── auto_fixer.py        舊版單次 fixer（保留供 fallback）
├── github_webhook.py    GitHub Webhook 接收（Flask, port 8080）
└── service_manager.py   git pull + kill PID + 重啟 + health check
```

---

## Stage 1 — 用戶回報問題（Discord → GitHub Issue）

### 觸發方式

在 `#agent-hub`（ID: `1487718765717098526`）@ClaudeCode：

```
@ClaudeCode LINE 按找檔案沒有回應
@ClaudeCode /vector-search 回傳空陣列，log 顯示 KeyError: 'similarity'
```

> ⚠️ Bot 為純文字模式，**無法讀取截圖**。請直接貼錯誤文字。

### Bot 自動執行

| 步驟 | 程式位置 | 說明 |
|------|---------|------|
| 1 | `discord_bot._handle_message` | dedup 確認（5 層防護）、驗證 @mention + 頻道 |
| 2 | `discord_bot._create_github_issue` | GitHub Search API 確認無重複後建立 Issue |
| 3 | Discord 回報 | `✅ Issue #N 已建立，ClaudeCode 正在分析...` |
| 4 | `github_webhook._handle_issue_opened` | Webhook 收到 → 呼叫 `orchestrator.assign_issue()` |
| 5 | `orchestrator._run_auto_fix` | 在 `#agent-hub` 開討論串 → 啟動 ClaudeAgent |

### 防重複機制（5 層）

1. **message dedup**：`processed_messages.json` 持久化
2. **in-memory 競態**：`_creating_issues` set
3. **檔案 cooldown**：`issue_cooldown.json`，同標題 60 秒內只建一次
4. **GitHub Search API**：建立前搜尋標題前 20 字
5. **建立後驗證**：2 秒後再搜，自動關閉競態重複 Issue

---

## Stage 2 — Multi-turn Agent 自動修復

### ClaudeAgent 工作方式

每個 Issue 在 `1487728782902296656` 自動開討論串（`issue-#N-{title}`），Agent 在串中逐步推理回報。

**`claude_agent.fix_issue()` 多輪迴圈（最多 25 輪）：**

```
每輪流程：
  claude --print（附完整對話歷史）
    → 輸出 <tool_call>{"tool": "...", "input": {...}}</tool_call>
    → Python 執行工具
    → 工具結果加入對話
    → 進行下一輪
```

**8 種工具：**

| 工具 | 功能 |
|------|------|
| `list_repo_files` | 列出 repo 檔案結構 |
| `read_file` | 讀取任何程式碼檔案（完整內容） |
| `fetch_url` | 抓取外部 URL（n8n API、文件等） |
| `create_branch` | 建立 `fix/issue-N-yyyymmddHHMMSS` |
| `commit_patch` | old_string→new_string 精準 patch |
| `open_pr` | 建立 PR，body 含 Fixes #N |
| `post_to_thread` | 在討論串回報每步進度 |
| `cannot_fix` | 超出範圍時說明根因 + 人工建議 |

**修復成功時的 PR body 格式：**
```markdown
## Description
## Fixes
Fixes #N
## Changes
## Before / After
## Bot Execution Log
```

**修復失敗處理：**
- `cannot_fix` 工具 → 討論串詳細說明根因 → `#logs` 通知
- 達到 25 輪上限 → 主頻道警告
- 工具執行錯誤 → 錯誤訊息餵回 Claude，讓 Agent 自行調整

---

## Stage 3 — CI + Code Review（全自動）

**GitHub Actions**（`.github/workflows/lint.yml`，觸發於 PR opened/synchronize）：
- `ruff check`（rules E, F, I；ignore E501, E402）
- `ast.parse` syntax check（所有 .py 檔）

**ClaudeCode Code Review**（`orchestrator.trigger_pr_review()`）：
```
1. GitHub API 取 PR diff（最多重試 3 次）
2. Claude CLI 分析 → verdict: APPROVE / REQUEST_CHANGES
3. 發 GitHub PR comment
4. REQUEST_CHANGES → 自動修復循環（最多 3 次）→ 超過 → #logs
```

---

## Stage 4 — 用戶手動 Merge（唯一需要人工的步驟）

1. 收到 Discord 通知 + `#review-queue` 提示
2. 點 PR 連結 → GitHub 審查 diff
3. CI ✅ + Code Review ✅ → 點 **Merge pull request**
4. 回到 Discord 輸入（可選備援）：
   ```
   @ClaudeCode 已Merge PR #N
   ```

> **也可不輸入**：GitHub Webhook 自動觸發 Stage 5。

---

## Stage 5 — Post-Merge 全自動

### 觸發（擇一，dedup 防重複）

- GitHub Webhook：`pull_request closed + merged`
- Discord 訊息：`@ClaudeCode 已Merge PR #N`

### 執行序列

```
github_webhook._handle_pr_merged()
├── DELETE /git/refs/heads/fix/issue-N-...   ← 刪 fix branch
└── PATCH /issues/N { state: closed }        ← 關 Issue

orchestrator._run_post_merge_sync()          ← background thread
├── 建 Discord Thread: sync-PR#N-title
├── service_manager.restart_and_verify()
│   ├── netstat -ano → 找 port 8765 PID
│   ├── taskkill /F /PID <old_pid>
│   ├── git -C "D:/n8n/CLAUDE 實做/本地AI企業問答助理" pull
│   ├── python scripts/api_server.py --port 8765 &
│   └── curl /health（重試 8 次）
│           ↓ 成功 → ✅ 本機服務重啟成功
│           ↓ 失敗 → ⚠️ 重啟失敗 + #logs
└── sleep(600) → archive thread
```

---

## 錯誤升級策略

| Level | 條件 | 動作 |
|-------|------|------|
| 1 | 第一次失敗 | Agent 自動調整（最多 25 輪） |
| 2 | `cannot_fix` 呼叫 | 討論串說明 + #logs 通知 |
| 3 | 達到 25 輪上限 | 主頻道警告，等待人工 |
| 4 | 用戶 4 小時未回應 | Issue 標記 🚨 ESCALATED |

---

## Discord 頻道分工

| 頻道 | ID | 用途 |
|------|----|------|
| `#agent-hub`（主頻） | `1487718765717098526` | 用戶回報、Issue 建立回覆 |
| `#agent-hub`（討論串） | `1487728782902296656` | 每個 Issue 的 Agent 工作空間 |
| `#logs` | 見 .env | 錯誤、失敗、升級通知 |
| `#review-queue` | 見 .env | 待審 PR 列表 |

---

## 啟動方式

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 填入環境變數
cp .env.example .env

# 3. 啟動（同時啟動 Flask webhook server + Discord bot）
cd "D:/n8n/CLAUDE 實做/claude agent遠端自動修復工作流"
python src/main.py
# 輸出：Listening on http://0.0.0.0:8080
#       Discord bot ready: ClaudeCode#6623

# 4. ngrok 將 port 8080 轉發至外網
# GitHub repo → Settings → Webhooks → Payload URL: https://xxx.ngrok.io/webhook
```

---

## 環境變數（`.env`）

```env
# GitHub
GITHUB_TOKEN=ghp_xxxx
GITHUB_WEBHOOK_SECRET=your_secret
GITHUB_REPO=xxx69579575-pixel/-N8N--line-n8n-
OPENCALW_GITHUB_TOKEN=ghp_yyyy   # 不同帳號，用於 PR review comment

# Discord
DISCORD_BOT_TOKEN=your_bot_token
OPENCALW_BOT_TOKEN=your_opencalw_token
DISCORD_CHANNEL_ID=1487718765717098526      # 用戶回報頻道
DISCORD_AGENT_HUB_ID=1487728782902296656    # Agent 討論串頻道
DISCORD_LOGS_CHANNEL_ID=
DISCORD_REVIEW_QUEUE_ID=

# Bot IDs
CLAUDECODE_BOT_ID=1484454025893253162
OPENCALW_BOT_ID=1484367437402210344

# 本機服務重啟目標
API_SERVER_PROJECT_ROOT=D:/n8n/CLAUDE 實做/本地AI企業問答助理
API_SERVER_PORT=8765

# Webhook server
PORT=8080
MAX_AUTO_FIX_RETRIES=3
THREAD_ARCHIVE_MINUTES=10
```

> ⚠️ 不需要 `ANTHROPIC_API_KEY`，ClaudeAgent 使用 Claude Pro 訂閱的 `claude --print` CLI。

---

## 常見問題

| 問題 | 原因 | 解法 |
|------|------|------|
| Bot 不回應 | 沒有 @mention 或不在 `1487718765717098526` | 確認頻道 + @ClaudeCode |
| 討論串沒開 | `DISCORD_AGENT_HUB_ID` 設錯或 Bot 無頻道權限 | 確認 .env + Bot 在頻道的權限 |
| Agent 卡在某輪 | Claude CLI 無回應或工具失敗 | 查看討論串最後訊息，補充問題描述 |
| PR 建立但 CI 失敗 | ruff 或 syntax 錯誤 | 等 Bot 自動修復（3 次），或人工修改 |
| Post-merge 重啟失敗 | api_server.py 啟動錯誤或 port 衝突 | 查 #logs，手動 `taskkill` 舊 PID |
| Webhook 沒收到 | ngrok 掉線 | 重啟 ngrok，更新 GitHub Webhook URL |
| `cannot_fix` 觸發 | 問題在 n8n/資料庫/非程式碼層 | 看討論串根因說明，人工處理 |

---

## 完整檢核清單

```
Stage 1-3（Bot 自動）
[ ] Discord @mention 觸發，Bot 回應「正在分析...」
[ ] GitHub Issue 建立成功
[ ] Discord 討論串在 1487728782902296656 自動建立
[ ] Agent 在討論串逐步回報進度（list_repo_files → read_file → ...）
[ ] fix branch 建立：fix/issue-N-yyyymmddHHMMSS
[ ] PR body 含 Fixes #N、Description、Changes、Before/After
[ ] CI lint 通過（綠燈）
[ ] Code Review comment 顯示 APPROVE

Stage 4（用戶手動）
[ ] 確認 PR diff 無異常
[ ] 點 Merge pull request
[ ] （可選）Discord 輸入「已Merge PR #N」

Stage 5（Bot 自動）
[ ] fix branch 已刪除
[ ] Issue 狀態 CLOSED
[ ] Discord Thread sync-PR#N 建立
[ ] git pull 完成
[ ] 舊 PID 已 kill
[ ] api_server.py 重新啟動
[ ] /health 回傳 {"status": "ok"}
[ ] Discord 回報 ✅ 重啟成功
[ ] Thread 歸檔（10 分鐘後）
```
