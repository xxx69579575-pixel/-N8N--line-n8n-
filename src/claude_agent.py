"""
Multi-turn Claude Agent（使用 claude --print CLI 迴圈，無需 API key）
每輪讓 Claude 呼叫一個工具，結果餵回下一輪，形成多步推理。
每個 Issue 在 Discord 討論串中持續回報進度。
"""
import base64
import json
import logging
import re
import subprocess
import textwrap
from typing import Any

import httpx

from config import Config

logger = logging.getLogger(__name__)

CLAUDE_CMD = r"C:\Users\xx\AppData\Roaming\npm\claude.cmd"

SYSTEM_PROMPT = """\
你是一位資深工程師，負責調查並修復 GitHub Issues。

每次回應只呼叫一個工具，格式如下（僅輸出此 JSON block，不加其他文字）：

<tool_call>
{"tool": "<工具名稱>", "input": {<參數>}}
</tool_call>

可用工具：
- list_repo_files      {"path_prefix": "scripts/"}  → 列出 repo 檔案
- read_file            {"path": "scripts/api_server.py"}  → 讀取檔案內容
- fetch_url            {"url": "https://..."}  → 取得任意 URL 內容
- create_branch        {"branch_name": "fix/issue-N-slug"}  → 建立 branch
- commit_patch         {"branch":"...", "path":"...", "old_string":"...", "new_string":"...", "commit_message":"..."}  → patch 程式碼
- open_pr              {"title":"...", "branch":"...", "body":"...（含 Fixes #N）"}  → 開 PR
- post_to_thread       {"message": "..."}  → 回報進度到 Discord 討論串
- cannot_fix           {"root_cause": "...", "recommendation": "..."}  → 說明超出範圍的根因
- done                 {}  → 任務完成，結束

規則：
1. 先 list_repo_files + read_file 調查，不要急著修改
2. commit_patch 的 old_string 必須先從 read_file 確認完全一致後才使用
3. 若問題在 n8n / 資料庫 / 非程式碼層，呼叫 cannot_fix 說明
4. 每個重要進度用 post_to_thread 告知用戶
5. PR 建立後呼叫 done
"""


class ClaudeAgent:
    """多輪 claude --print 迴圈 Agent，取代 AutoFixer 的單次呼叫。"""

    MAX_TURNS = 25

    def __init__(self, config: Config, discord_bot):
        self.config = config
        self.discord = discord_bot
        self.gh = httpx.Client(
            headers={
                "Authorization": f"Bearer {config.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        self.base = f"https://api.github.com/repos/{config.github_repo}"
        self._thread_id: int | None = None
        self._issue_number: int | None = None

    # ──────────────────────────────────────────────
    # 公開入口
    # ──────────────────────────────────────────────

    def fix_issue(self, issue_number: int, title: str, body: str, thread_id: int) -> dict | None:
        """
        多輪迴圈修復 Issue，在 Discord thread_id 持續回報。
        回傳 PR dict（成功）或 None（失敗/超出範圍）。
        """
        self._thread_id = thread_id
        self._issue_number = issue_number

        self._post(f"🔍 **開始調查 Issue #{issue_number}**\n> {title}")

        # 初始提示：告訴 Claude 要做什麼
        conversation = textwrap.dedent(f"""
            {SYSTEM_PROMPT}

            ---
            任務：修復 GitHub Issue #{issue_number}
            標題：{title}
            內容：{body or '（無詳細描述）'}
            目標 Repo：{self.config.github_repo}

            請先調查問題根因（list_repo_files → read_file），再動手修改。
            現在開始，呼叫第一個工具：
        """).strip()

        pr_result = None
        done_cleanly = False  # Agent 呼叫 done（完成，無需新 PR）

        for turn in range(self.MAX_TURNS):
            # 呼叫 claude --print
            raw_output = self._call_claude(conversation)
            if not raw_output:
                self._post("⚠️ Claude CLI 無回應，停止。")
                break

            # 偵測用量上限，等到重置後自動繼續
            if self._is_rate_limited(raw_output):
                wait_secs = self._wait_for_rate_limit_reset(raw_output)
                if wait_secs <= 0:
                    self._post("⏸️ Claude 用量已達上限，請稍後手動重新觸發。")
                    break
                continue  # 重試同一輪

            logger.info("[Agent turn %d] output: %s", turn + 1, raw_output[:200])

            # 解析工具呼叫
            tool_call = self._parse_tool_call(raw_output)
            if not tool_call:
                # Claude 沒有呼叫工具，可能是自然語言結論
                logger.info("No tool call found, agent may be done.")
                self._post(f"💬 {raw_output[:500]}")
                break

            tool_name = tool_call.get("tool", "")
            tool_input = tool_call.get("input", {})
            logger.info("Tool: %s  input=%s", tool_name, json.dumps(tool_input)[:120])

            # 執行工具
            try:
                result = self._run_tool(tool_name, tool_input)
                if tool_name == "open_pr" and isinstance(result, dict) and "number" in result:
                    pr_result = result
            except Exception as e:
                logger.error("Tool %s error: %s", tool_name, e)
                result = {"error": str(e)}

            # 若 done / cannot_fix → 結束
            if tool_name == "done":
                done_cleanly = True
                break
            if tool_name == "cannot_fix":
                break

            # 把工具結果加入對話，讓下輪繼續
            result_text = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
            conversation += (
                f"\n\n<tool_call>\n{json.dumps({'tool': tool_name, 'input': tool_input}, ensure_ascii=False)}\n</tool_call>"
                f"\n\n<tool_result>\n{result_text[:3000]}\n</tool_result>"
                f"\n\n根據以上結果，繼續下一步（呼叫下一個工具）："
            )

        else:
            logger.warning("Agent reached MAX_TURNS (%d) for Issue #%s", self.MAX_TURNS, issue_number)
            self._post(f"⚠️ 達到最大輪次（{self.MAX_TURNS}），請人工確認狀態。")

        # done_cleanly=True 表示 Agent 完成調查但無需新 PR（例如 PR 已存在）
        # 回傳 {"done": True} 讓 orchestrator 區分「成功完成」vs「cannot_fix」
        if done_cleanly and pr_result is None:
            return {"done": True}
        return pr_result

    # ──────────────────────────────────────────────
    # Claude CLI
    # ──────────────────────────────────────────────

    def _call_claude(self, prompt: str) -> str:
        try:
            result = subprocess.run(
                f'"{CLAUDE_CMD}" --print --dangerously-skip-permissions',
                input=prompt,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                shell=True,
            )
            logger.info("Claude CLI returncode=%d stdout_len=%d stderr=%s",
                        result.returncode, len(result.stdout), result.stderr[:200] if result.stderr else "")
            if not result.stdout.strip() and result.stderr:
                logger.error("Claude CLI stderr: %s", result.stderr[:500])
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out")
            return ""
        except Exception as e:
            logger.error("Claude CLI error: %s", e)
            return ""

    def _is_rate_limited(self, output: str) -> bool:
        return "hit your limit" in output.lower() or "you've hit your limit" in output.lower()

    def _wait_for_rate_limit_reset(self, output: str) -> int:
        """解析 reset 時間，等待並回報進度；回傳實際等待秒數（0 表示放棄）。"""
        import time
        from datetime import datetime, timezone, timedelta

        # 解析 "resets Xpm" 或 "resets HH:MM"
        reset_match = re.search(r'resets?\s+(\d+(?::\d{2})?\s*(?:am|pm)?)', output, re.IGNORECASE)
        wait_secs = 0
        reset_str = "soon"

        if reset_match:
            reset_str = reset_match.group(1).strip()
            try:
                # Asia/Taipei = UTC+8
                tz_offset = timezone(timedelta(hours=8))
                now = datetime.now(tz_offset)
                fmt = "%I%p" if re.search(r'am|pm', reset_str, re.I) else "%H:%M"
                reset_time = datetime.strptime(reset_str.lower().replace(" ", ""), fmt)
                reset_dt = now.replace(
                    hour=reset_time.hour, minute=reset_time.minute,
                    second=0, microsecond=0
                )
                if reset_dt <= now:
                    reset_dt += timedelta(days=1)
                wait_secs = int((reset_dt - now).total_seconds()) + 60  # 多等 1 分鐘緩衝
            except Exception:
                wait_secs = 0

        if wait_secs <= 0 or wait_secs > 7200:  # 超過 2 小時就放棄
            return 0

        self._post(
            f"⏸️ Claude 用量已達上限（resets {reset_str} Asia/Taipei）\n"
            f"Bot 將自動等待 {wait_secs // 60} 分鐘後繼續，請稍候..."
        )
        logger.info("Rate limit hit, waiting %d seconds until reset", wait_secs)

        # 每 10 分鐘回報一次進度
        elapsed = 0
        interval = 600
        while elapsed < wait_secs:
            sleep_chunk = min(interval, wait_secs - elapsed)
            time.sleep(sleep_chunk)
            elapsed += sleep_chunk
            remaining = (wait_secs - elapsed) // 60
            if remaining > 0:
                self._post(f"⏳ 還需等待約 {remaining} 分鐘...")

        self._post("▶️ 用量已重置，繼續執行修復...")
        return wait_secs

    def _parse_tool_call(self, text: str) -> dict | None:
        """從 Claude 輸出中解析 <tool_call>...</tool_call>。"""
        match = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            logger.warning("Failed to parse tool_call JSON: %s", match.group(1)[:200])
            return None

    # ──────────────────────────────────────────────
    # Tool dispatch
    # ──────────────────────────────────────────────

    def _run_tool(self, name: str, inputs: dict) -> Any:
        if name == "list_repo_files":
            return self._list_repo_files(inputs.get("path_prefix", ""))
        if name == "read_file":
            return self._read_file(inputs["path"])
        if name == "fetch_url":
            return self._fetch_url(inputs["url"])
        if name == "create_branch":
            return self._create_branch(inputs["branch_name"])
        if name == "commit_patch":
            return self._commit_patch(
                inputs["branch"], inputs["path"],
                inputs["old_string"], inputs["new_string"],
                inputs["commit_message"],
            )
        if name == "open_pr":
            return self._open_pr(inputs["title"], inputs["branch"], inputs["body"])
        if name == "post_to_thread":
            self._post(inputs["message"])
            return "posted"
        if name == "cannot_fix":
            self._post(
                f"⚠️ **無法自動修復 Issue #{self._issue_number}**\n\n"
                f"**根因：**\n{inputs['root_cause']}\n\n"
                f"**建議步驟：**\n{inputs['recommendation']}"
            )
            self.discord.post_to_logs(
                f"⚠️ Issue #{self._issue_number} 需人工介入：{inputs['root_cause'][:120]}"
            )
            return "acknowledged"
        if name == "done":
            return "done"
        return f"Unknown tool: {name}"

    # ──────────────────────────────────────────────
    # GitHub helpers
    # ──────────────────────────────────────────────

    def _list_repo_files(self, path_prefix: str = "") -> list[str]:
        resp = self.gh.get(f"{self.base}/git/trees/HEAD?recursive=1")
        if resp.status_code != 200:
            return [f"Error: {resp.status_code}"]
        files = [f["path"] for f in resp.json().get("tree", []) if f["type"] == "blob"]
        if path_prefix:
            files = [f for f in files if f.startswith(path_prefix)]
        return files[:60]

    def _read_file(self, path: str) -> str:
        resp = self.gh.get(f"{self.base}/contents/{path}")
        if resp.status_code == 200:
            try:
                return base64.b64decode(resp.json()["content"]).decode("utf-8", errors="replace")
            except Exception as e:
                return f"Decode error: {e}"
        return f"Not found: {path} (HTTP {resp.status_code})"

    def _fetch_url(self, url: str) -> str:
        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            return resp.text[:5000]
        except Exception as e:
            return f"Fetch error: {e}"

    def _create_branch(self, branch_name: str) -> dict:
        repo_resp = self.gh.get(self.base)
        default = repo_resp.json().get("default_branch", "master") if repo_resp.status_code == 200 else "master"
        ref_resp = self.gh.get(f"{self.base}/git/refs/heads/{default}")
        if ref_resp.status_code != 200:
            return {"error": "Cannot get base branch SHA"}
        sha = ref_resp.json()["object"]["sha"]
        resp = self.gh.post(f"{self.base}/git/refs", json={"ref": f"refs/heads/{branch_name}", "sha": sha})
        if resp.status_code in (200, 201):
            return {"success": True, "branch": branch_name}
        return {"error": resp.text[:200]}

    def _commit_patch(self, branch: str, path: str, old_string: str, new_string: str, commit_message: str) -> dict:
        existing = self.gh.get(f"{self.base}/contents/{path}?ref={branch}")
        if existing.status_code != 200:
            return {"error": f"Cannot read {path} on branch {branch}"}
        data = existing.json()
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        if old_string not in content:
            return {
                "error": f"old_string not found in {path}",
                "hint": f"File first 400 chars:\n{content[:400]}"
            }
        new_content = content.replace(old_string, new_string, 1)
        encoded = base64.b64encode(new_content.encode()).decode()
        resp = self.gh.put(
            f"{self.base}/contents/{path}",
            json={"message": commit_message, "content": encoded, "branch": branch, "sha": data["sha"]},
        )
        if resp.status_code in (200, 201):
            return {"success": True, "path": path, "branch": branch}
        return {"error": resp.text[:200]}

    def _open_pr(self, title: str, branch: str, body: str) -> dict:
        issue_number = self._issue_number
        if issue_number and f"#{issue_number}" not in body:
            body += f"\n\nFixes #{issue_number}"
        repo_resp = self.gh.get(self.base)
        base_branch = repo_resp.json().get("default_branch", "master") if repo_resp.status_code == 200 else "master"
        resp = self.gh.post(
            f"{self.base}/pulls",
            json={"title": title, "head": branch, "base": base_branch, "body": body},
        )
        if resp.status_code in (200, 201):
            pr = resp.json()
            self._post(
                f"✅ **PR #{pr['number']} 已建立**\n"
                f"{pr['html_url']}\n"
                f"請前往 GitHub 確認後按 **Merge pull request**。"
            )
            return {"number": pr["number"], "html_url": pr["html_url"], "title": pr["title"]}
        return {"error": resp.text[:200]}

    # ──────────────────────────────────────────────
    # Discord helper
    # ──────────────────────────────────────────────

    def _post(self, message: str) -> None:
        if self._thread_id:
            try:
                self.discord.notify_thread(self._thread_id, message)
            except Exception as e:
                logger.warning("Failed to post to thread %s: %s", self._thread_id, e)
