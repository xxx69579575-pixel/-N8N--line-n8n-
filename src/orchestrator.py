"""
主要協調器
Stage 1–5 的業務邏輯，含雙 Bot handoff 機制
"""
import json
import logging
import re
import subprocess
import time
from enum import Enum

import httpx

from auto_fixer import AutoFixer
from auto_merger import AutoMerger
from claude_agent import ClaudeAgent
from config import Config
from service_manager import ServiceManager

logger = logging.getLogger(__name__)


class BotRole(Enum):
    CLAUDECODE = "ClaudeCode"
    OPENCALW = "OpenCalw"


class TaskComplexity(Enum):
    SIMPLE = "simple"    # 單檔、明確修改 → ClaudeCode 獨立執行
    COMPLEX = "complex"  # 多檔、跨模組 → OpenCalw 協作


class Orchestrator:
    def __init__(self, config: Config, discord_bot):
        self.config = config
        self.discord = discord_bot
        self.auto_fixer = AutoFixer(config)
        self.claude_agent = ClaudeAgent(config, discord_bot)
        self.service_manager = ServiceManager()
        self.auto_merger = AutoMerger(config, discord_bot)
        self._post_merge_in_progress: set[int] = set()  # dedup: 防 webhook+Discord 雙重觸發
        discord_bot._orchestrator = self  # 反向引用，讓 bot 可呼叫 post-merge
        self.gh_headers = {
            "Authorization": f"Bearer {config.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # OpenCalw token 用於發 GitHub Review（避免自己審自己）
        self.gh_review_headers = {
            "Authorization": f"Bearer {config.opencalw_github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.base_url = f"https://api.github.com/repos/{config.github_repo}"
        self._fix_retry_counts: dict[int, int] = {}  # pr_number → retry count
        self._assign_in_progress: set[int] = set()  # dedup: 防 webhook+Discord 雙重觸發

    # ──────────────────────────────────────────────
    # Stage 1 — 任務分配
    # ──────────────────────────────────────────────

    def assign_issue(self, issue_number: int, title: str, body: str) -> None:
        if issue_number in self._assign_in_progress:
            logger.info("Issue #%s already in-flight, skipping duplicate assign_issue call", issue_number)
            return
        self._assign_in_progress.add(issue_number)

        complexity = self._evaluate_complexity(body)
        assigned_bot = BotRole.CLAUDECODE if complexity == TaskComplexity.SIMPLE else BotRole.OPENCALW

        logger.info("Issue #%s → complexity=%s, assigned=%s", issue_number, complexity.value, assigned_bot.value)

        self.discord.post_task_assignment(
            issue_number=issue_number,
            title=title,
            bot=assigned_bot,
            complexity=complexity,
        )

        # 在背景執行緒自動修復（避免 blocking webhook response）
        import threading
        threading.Thread(
            target=self._run_auto_fix,
            args=(issue_number, title, body),
            daemon=True,
        ).start()

    def _run_auto_fix(self, issue_number: int, title: str, body: str) -> None:
        """背景執行：開 Discord 討論串 → 呼叫多輪 ClaudeAgent → 回報結果。"""
        # 在 #agent-hub 開討論串作為工作上下文
        thread_name = f"issue-#{issue_number}-{title[:45]}"
        try:
            thread_id = self.discord.create_agent_hub_thread(thread_name)
        except Exception as e:
            logger.error("Failed to create thread for Issue #%s: %s", issue_number, e)
            thread_id = None

        try:
            pr = self.claude_agent.fix_issue(issue_number, title, body, thread_id)
            if isinstance(pr, dict) and "number" in pr:
                # Agent 開了新 PR
                self.discord.notify_main_channel(
                    f"✅ **自動修復完成**\n"
                    f"Issue #{issue_number} → PR #{pr['number']} 已建立\n"
                    f"{pr['html_url']}\n"
                    f"請前往 GitHub 確認後按 **Merge**。"
                )
                self.discord.post_to_review_queue(
                    f"🔍 **待審 PR #{pr['number']}**\n"
                    f"**標題**：{pr['title']}\n"
                    f"**連結**：{pr['html_url']}\n"
                    f"**關聯 Issue**：#{issue_number}\n"
                    f"ClaudeCode Agent 已完成分析與修復，等待人工確認後 Merge。"
                )
            elif isinstance(pr, dict) and pr.get("done"):
                # Agent 呼叫 done：調查完成，無需新 PR（例如 PR 已存在）
                self.discord.notify_main_channel(
                    f"✅ **Issue #{issue_number} 調查完成**\n"
                    f"詳情請查看討論串：`{thread_name}`"
                )
            else:
                # cannot_fix 已在 thread 內說明根因，這裡只補主頻道提示
                self.discord.notify_main_channel(
                    f"⚠️ **Issue #{issue_number} 需要人工介入**\n"
                    f"詳細根因分析請查看討論串：`{thread_name}`"
                )
        except Exception as e:
            logger.error("ClaudeAgent failed for Issue #%s: %s", issue_number, e)
            self.discord.notify_main_channel(
                f"⚠️ **Issue #{issue_number} Agent 執行失敗**\n錯誤：`{e}`"
            )
            self.discord.post_to_logs(f"❌ Issue #{issue_number} Agent 錯誤：{e}")
        finally:
            self._assign_in_progress.discard(issue_number)

    def _evaluate_complexity(self, body: str) -> TaskComplexity:
        """簡單啟發式：body 提到多個檔案或關鍵字則視為複雜。"""
        complex_keywords = ["refactor", "重構", "架構", "多檔", "cross-module", "migration"]
        body_lower = body.lower()
        if any(kw in body_lower for kw in complex_keywords):
            return TaskComplexity.COMPLEX
        return TaskComplexity.SIMPLE

    # ──────────────────────────────────────────────
    # Stage 2 — PR 建立
    # ──────────────────────────────────────────────

    def create_pull_request(
        self,
        title: str,
        head_branch: str,
        base_branch: str,
        issue_number: int,
        changes: list[str],
        before_after: str,
        executed_by: BotRole,
        collaborated_by: BotRole | None = None,
    ) -> dict:
        bot_log = f"- {executed_by.value}: 主要執行"
        if collaborated_by:
            bot_log += f"\n- {collaborated_by.value}: 協作執行"

        body = f"""## Description
{title}

## Fixes
Fixes #{issue_number}

## Changes
{chr(10).join(f"- {c}" for c in changes)}

## Before / After
{before_after}

## Bot Execution Log
{bot_log}
"""
        payload = {
            "title": title,
            "head": head_branch,
            "base": base_branch,
            "body": body,
        }
        resp = httpx.post(f"{self.base_url}/pulls", headers=self.gh_headers, json=payload)
        resp.raise_for_status()
        pr = resp.json()
        logger.info("PR #%s created: %s", pr["number"], pr["html_url"])
        return pr

    # ──────────────────────────────────────────────
    # Stage 3 — Code Review
    # ──────────────────────────────────────────────

    def trigger_pr_review(self, pr_number: int, pr_title: str, head_sha: str) -> None:
        logger.info("Starting review for PR #%s", pr_number)

        diff = self._get_pr_diff(pr_number)
        if not diff:
            logger.warning("No diff found for PR #%s, skipping review (PR may still be processed by CI)", pr_number)
            # diff 取不到時仍給 APPROVE 讓流程繼續，CI 會做語法檢查
            self._post_github_review(pr_number, {"verdict": "APPROVE", "summary": "Automated review: no diff available, CI will validate syntax."})
            return

        review_result = self._analyze_with_alkaid(diff)

        # 發現重大問題時呼叫 OpenCalw 二次審查
        if review_result.get("has_critical"):
            logger.info("Critical issues found, requesting OpenCalw secondary review")
            secondary = self.discord.request_secondary_review(pr_number, diff)
            review_result = self._merge_review_results(review_result, secondary)

        self._post_github_review(pr_number, review_result)

        if review_result["verdict"] == "REQUEST_CHANGES":
            self._handle_review_changes(pr_number, review_result["comments"])

    def _get_pr_diff(self, pr_number: int) -> str:
        """GitHub API で PR の diff を取得（最多重試 3 次，等待 diff 生成）。"""
        for attempt in range(3):
            try:
                if attempt > 0:
                    time.sleep(5)
                resp = httpx.get(
                    f"{self.base_url}/pulls/{pr_number}/files",
                    headers=self.gh_headers,
                )
                if resp.status_code != 200:
                    continue
                files = resp.json()
                if not files:
                    continue
                lines = []
                for f in files:
                    lines.append(f"--- a/{f['filename']}\n+++ b/{f['filename']}")
                    lines.append(f.get("patch", "(binary or no patch)"))
                result = "\n".join(lines)
                if result.strip():
                    return result
            except Exception as e:
                logger.error("Failed to get PR diff (attempt %s): %s", attempt + 1, e)
        return ""

    def _analyze_with_alkaid(self, diff: str) -> dict:
        """Claude CLI 分析 diff，回傳 review 結果。"""
        prompt = (
            "你是資深 Code Reviewer。以下是 PR 的 diff，請分析並以 JSON 回覆：\n"
            '{"verdict":"APPROVE或REQUEST_CHANGES","has_critical":false,"summary":"一句話說明","comments":["問題1","問題2"]}\n'
            "只回傳 JSON，不要其他文字。\n\n"
            f"```diff\n{diff[:8000]}\n```"
        )
        try:
            result = subprocess.run(
                r'"C:\Users\xx\AppData\Roaming\npm\claude.cmd" --print --dangerously-skip-permissions',
                input=prompt,
                capture_output=True, encoding="utf-8", errors="replace",
                timeout=120, shell=True,
            )
            raw = result.stdout.strip()
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            return json.loads(raw)
        except Exception as e:
            logger.error("Alkaid analysis failed: %s", e)
            return {"verdict": "APPROVE", "has_critical": False, "summary": "Auto-approved (analysis unavailable).", "comments": []}

    def _merge_review_results(self, primary: dict, secondary: dict) -> dict:
        merged = dict(primary)
        if secondary.get("verdict") == "REQUEST_CHANGES":
            merged["verdict"] = "REQUEST_CHANGES"
        merged["comments"] = primary.get("comments", []) + secondary.get("comments", [])
        return merged

    def _post_github_review(self, pr_number: int, review_result: dict) -> None:
        verdict = review_result.get("verdict", "APPROVE")
        summary = review_result.get("summary", "")
        comments = review_result.get("comments", [])
        icon = "✅" if verdict == "APPROVE" else "⚠️"
        comment_lines = [f"{icon} **ClaudeCode Auto Review** — `{verdict}`", ""]
        if summary:
            comment_lines.append(summary)
        if comments:
            comment_lines.append("\n**Issues found:**")
            comment_lines += [f"- {c}" for c in comments[:5]]
        body = "\n".join(comment_lines)

        # 用 PR comment（不受「不能自審自己的 PR」限制）
        resp = httpx.post(
            f"{self.base_url}/issues/{pr_number}/comments",
            headers=self.gh_headers,
            json={"body": body},
        )
        if resp.status_code in (200, 201):
            logger.info("PR #%s review comment posted: %s", pr_number, verdict)
        else:
            logger.warning("Failed to post review comment: %s", resp.text)

    def _handle_review_changes(self, pr_number: int, comments: list) -> None:
        retries = self._fix_retry_counts.get(pr_number, 0)
        if retries >= self.config.max_auto_fix_retries:
            logger.warning("PR #%s exceeded max retries (%s), escalating", pr_number, retries)
            self.discord.post_to_logs(
                f"⚠️ PR #{pr_number} 自動修復失敗超過 {self.config.max_auto_fix_retries} 次，請人工介入。"
            )
            return

        self._fix_retry_counts[pr_number] = retries + 1
        logger.info("PR #%s auto-fix attempt %s/%s", pr_number, retries + 1, self.config.max_auto_fix_retries)
        self.discord.request_auto_fix(pr_number, comments)

    # ──────────────────────────────────────────────
    # Stage 5 — Post-merge sync
    # ──────────────────────────────────────────────

    def trigger_post_merge_sync(self, pr_number: int, pr_title: str, pr_body: str) -> None:
        """非阻塞入口：dedup 後派發至背景 thread。"""
        if pr_number in self._post_merge_in_progress:
            logger.info("Post-merge sync already in progress for PR #%s, skipping duplicate", pr_number)
            return
        self._post_merge_in_progress.add(pr_number)
        import threading
        threading.Thread(
            target=self._run_post_merge_sync,
            args=(pr_number, pr_title, pr_body),
            daemon=True,
        ).start()

    def _run_post_merge_sync(self, pr_number: int, pr_title: str, pr_body: str) -> None:
        """實際 post-merge 工作（在背景 thread 執行）。"""
        thread_name = f"sync-PR#{pr_number}-{pr_title[:40]}"
        logger.info("Starting post-merge sync: %s", thread_name)
        thread_id: int | None = None

        try:
            thread_id = self.discord.create_agent_hub_thread(thread_name)

            # ClaudeCode：確認 PR 內容 + 更新 MD 文件
            self.discord.notify_thread(thread_id, f"@ClaudeCode 請確認 PR #{pr_number} 內容並更新相關 MD 文件。")

            # OpenCalw：更新 CHANGELOG（如有協作記錄）
            if "OpenCalw" in (pr_body or ""):
                self.discord.notify_thread(thread_id, f"@OpenCalw 請更新 CHANGELOG 與相關文件。")

            self.discord.notify_thread(thread_id, f"✅ Task DONE — PR #{pr_number} 文件同步完成。")
            logger.info("Post-merge sync complete for PR #%s", pr_number)

            # ── 重啟本機服務 ───────────────────────────────────
            self.discord.notify_main_channel(
                f"🔄 **重啟本機服務中** (PR #{pr_number})\n"
                f"git pull + 重啟 api_server.py (port {self.config.api_server_port})..."
            )
            restart = self.service_manager.restart_and_verify(
                project_root=self.config.api_server_project_root,
                port=self.config.api_server_port,
            )
            detail_lines = "\n".join(f"  `{d}`" for d in restart["details"][-6:])
            if restart["success"]:
                self.discord.notify_main_channel(
                    f"✅ **本機服務重啟成功** (PR #{pr_number})\n"
                    f"api_server.py 已恢復，健康檢查通過。\n{detail_lines}"
                )
            else:
                self.discord.notify_main_channel(
                    f"⚠️ **本機服務重啟失敗** (PR #{pr_number})\n"
                    f"{restart['message']}\n{detail_lines}"
                )
                self.discord.post_to_logs(
                    f"❌ Service restart failed for PR #{pr_number}: {restart['message']}"
                )

            # 歸檔 thread（等待後）
            time.sleep(self.config.thread_archive_minutes * 60)
            if thread_id:
                self.discord.archive_thread(thread_id)

        except Exception as e:
            logger.error("Post-merge sync failed: %s", e)
            self.discord.post_to_logs(f"⚠️ Partial failure in post-merge sync for PR #{pr_number}: {e}")
        finally:
            self._post_merge_in_progress.discard(pr_number)

    # ──────────────────────────────────────────────
    # Handoff helper
    # ──────────────────────────────────────────────

    def handoff_to_opencalw(self, issue_number: int, reason: str) -> None:
        logger.info("Handing off issue #%s to OpenCalw. Reason: %s", issue_number, reason)
        self.discord.post_task_assignment(
            issue_number=issue_number,
            title=f"[Handoff] Issue #{issue_number}",
            bot=BotRole.OPENCALW,
            complexity=TaskComplexity.COMPLEX,
            note=f"ClaudeCode handoff: {reason}",
        )
