# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fully automated GitHub workflow for `https://github.com/xxx69579575-pixel/-N8N--line-n8n-`, orchestrated via two Discord bots in channel `1487718765717098526`.

**Pipeline:** Issue → PR → CI/Code Review → User Approve/Merge → Post-Merge Sync

## Bot Roles

| Bot | Status | Role |
|-----|--------|------|
| ClaudeCode#6623 | ✅ Active | Primary orchestrator: issue detection, multi-turn agent fix, PR creation, code review, post-merge sync |
| OpenCalw Astra | ✅ Joined channel | Secondary executor: handoff target when ClaudeCode cannot complete |

**Handoff triggers (ClaudeCode → OpenCalw):** affected files > 3, cross-module refactor, execution timeout > 5 min, retry count > 2.

## Agent Architecture（核心設計）

### Multi-turn ClaudeAgent（取代舊版 AutoFixer）

每個 Issue 觸發時，`ClaudeAgent`（`src/claude_agent.py`）使用 `claude --print` CLI 進行**多輪工具呼叫迴圈**，不需要 Anthropic API key，使用 Claude Pro 訂閱即可。

**工具集（8 種）：**

| 工具 | 功能 |
|------|------|
| `list_repo_files` | 列出 repo 檔案結構 |
| `read_file` | 讀取任何程式碼檔案 |
| `fetch_url` | 抓取外部 URL（文件、n8n API 等） |
| `create_branch` | 建立 fix branch |
| `commit_patch` | old_string→new_string 精準 patch |
| `open_pr` | 建立 Pull Request |
| `post_to_thread` | 回報進度到 Discord 討論串 |
| `cannot_fix` | 說明超出範圍的根因 + 人工建議 |

**Discord 討論串：**
每個 Issue 自動在 `#agent-hub`（`1487728782902296656`）建立討論串（`issue-#N-{title}`），Agent 在串中逐步回報推理過程，問題解決後才關閉。

## Pipeline Stages

**Stage 1 — Issue Creation**
- ClaudeCode#6623 在 Discord `#agent-hub` 偵測 @mention → 建立 GitHub Issue
- GitHub Webhook → `orchestrator.assign_issue()` → 開 Discord 討論串 → 啟動 ClaudeAgent
- 複雜度路由：所有 Issue 統一走 ClaudeAgent；複雜任務由 Agent 自行呼叫 `cannot_fix` 後轉交 OpenCalw

**Stage 2 — Multi-turn Agent Fix**
- `ClaudeAgent.fix_issue()` 在背景 thread 執行，最多 25 輪
- 每輪：claude --print → 解析 `<tool_call>` → 執行工具 → 結果餵回下輪
- 修改完成 → `open_pr` → PR body 含 `Fixes #N`、Description、Changes、Before/After

**Stage 3 — CI + Code Review**
- GitHub Actions (`.github/workflows/lint.yml`) on `pull_request`:
  - `ruff check` rules E, F, I (ignore E501, E402)
  - `ast.parse` syntax check on all `.py` files
- ClaudeCode webhook on `pull_request opened`:
  - `orchestrator.trigger_pr_review()` → Claude CLI 分析 diff → 發 GitHub PR comment
  - 發現 critical issues → OpenCalw 二次審查（目前為 stub，自動 APPROVE）
  - Auto-fix loop: up to 3 retries before escalating to `#logs`

**Stage 4 — User Approve & Merge**
- Manual: user reviews on GitHub → approve → merge
- 48-hour inactivity → reminder posted to `#agent-hub`

**Stage 5 — Post-Merge** (`github_webhook._handle_pr_merged()`)
1. `DELETE /repos/{repo}/git/refs/heads/{branch}`
2. Parse `Fixes #N` → `PATCH /repos/{repo}/issues/{N}` (`state: closed`)
3. `orchestrator.trigger_post_merge_sync()` → Discord thread `sync-PR#N-{title}`:
   - git pull 本機 repo
   - kill 舊 PID → 重啟 `api_server.py --port 8765`
   - health check（重試 8 次）
   - All done → ✅ DONE, archive thread (10 min)

## Error Escalation

| Level | Condition | Action |
|-------|-----------|--------|
| 1 | First failure | Bot auto-retries (max 3×) |
| 2 | Still failing | Other bot takes over |
| 3 | Both bots fail | Notify user via `#logs` |
| 4 | No user response in 4h | Issue marked 🚨 ESCALATED |

**Agent 特殊升級：**
- Agent 呼叫 `cannot_fix` → 討論串說明根因 + #logs 通知 → 等待人工介入
- Agent 達到 25 輪上限 → 主頻道警告

## Discord Channels

| Channel | ID | Purpose |
|---------|----|---------|
| `#agent-hub` | `1487718765717098526` | 用戶回報問題（@mention ClaudeCode） |
| `#agent-hub`（討論串） | `1487728782902296656` | 每個 Issue 的 Agent 工作空間 |
| `#logs` | 見 .env | Errors, warnings, failures |
| `#review-queue` | 見 .env | PRs awaiting user approval |

## Implementation Phases

1. ✅ ClaudeCode single-bot full pipeline (Stage 1–5)
2. ✅ GitHub Actions CI (`lint.yml`)
3. ✅ Multi-turn ClaudeAgent with 8 tools + Discord thread per Issue
4. OpenCalw integration + handoff logic（進行中）
5. Auto-fix loop (REQUEST_CHANGES → bot auto-resubmits)
6. 48hr timeout reminder + thread archiving
