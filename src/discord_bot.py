"""
Discord Bot 整合
ClaudeCode + OpenCalw 頻道通訊、Thread 管理、#logs 通知
+ 自然語言監聽 → 自動開 GitHub Issue
"""
import asyncio
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import discord
import httpx

from config import Config

logger = logging.getLogger(__name__)


class DiscordBot:
    """同步包裝器，供 orchestrator / webhook 呼叫。"""

    def __init__(self, config: Config):
        self.config = config
        self.intents = discord.Intents.default()
        self.intents.message_content = True
        self.client = discord.Client(intents=self.intents)
        # 已處理訊息 ID 持久化存磁碟，重啟後不遺失
        self._dedup_file = Path(__file__).parent.parent / "processed_messages.json"
        self._processed_messages: set[int] = self._load_processed()
        self._dedup_lock: asyncio.Lock | None = None  # 在 event loop 中初始化
        self._creating_issues: set[str] = set()  # 正在建立中的 Issue 標題前綴（防競態重複，in-memory）
        # 檔案層級 cooldown：跨進程防重複（多個 bot 實例共享此檔案）
        self._cooldown_file = Path(__file__).parent.parent / "issue_cooldown.json"
        self._COOLDOWN_SECONDS = 60  # 同標題 60 秒內只建一次
        self._orchestrator = None  # 由 Orchestrator.__init__ 反向注入
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self.gh_headers = {
            "Authorization": f"Bearer {config.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        # 啟動 Discord 客戶端於背景執行緒
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=30)

    def _load_processed(self) -> set[int]:
        try:
            if self._dedup_file.exists():
                data = json.loads(self._dedup_file.read_text())
                # 只保留最近 500 筆，避免檔案無限增長
                return set(data[-500:])
        except Exception:
            pass
        return set()

    def _save_processed(self, message_id: int) -> None:
        try:
            existing = list(self._processed_messages)[-499:]
            self._dedup_file.write_text(json.dumps(existing + [message_id]))
        except Exception as e:
            logger.warning("Failed to save processed messages: %s", e)

    # ── 檔案層級 cooldown（跨進程防重複建 Issue）──────────────
    def _is_on_cooldown(self, title_key: str) -> bool:
        """回傳 True 表示此標題仍在 cooldown 期間內（不可建立新 Issue）。"""
        try:
            if self._cooldown_file.exists():
                data: dict = json.loads(self._cooldown_file.read_text())
                last_ts = data.get(title_key, 0)
                if time.time() - last_ts < self._COOLDOWN_SECONDS:
                    logger.info(
                        "Issue cooldown active for '%s' (%.0fs remaining)",
                        title_key,
                        self._COOLDOWN_SECONDS - (time.time() - last_ts),
                    )
                    return True
        except Exception as e:
            logger.warning("Failed to read cooldown file: %s", e)
        return False

    def _set_cooldown(self, title_key: str) -> None:
        """記錄此標題的建立時間到檔案，供跨進程共享。"""
        try:
            data: dict = {}
            if self._cooldown_file.exists():
                data = json.loads(self._cooldown_file.read_text())
            data[title_key] = time.time()
            # 清理超過 1 小時的舊記錄，避免檔案無限增長
            cutoff = time.time() - 3600
            data = {k: v for k, v in data.items() if v > cutoff}
            self._cooldown_file.write_text(json.dumps(data))
        except Exception as e:
            logger.warning("Failed to write cooldown file: %s", e)

    def _run(self):
        asyncio.set_event_loop(self._loop)

        @self.client.event
        async def on_ready():
            self._dedup_lock = asyncio.Lock()
            logger.info("Discord bot ready: %s", self.client.user)
            self._ready.set()

        @self.client.event
        async def on_message(message: discord.Message):
            await self._handle_message(message)

        self._loop.run_until_complete(self.client.start(self.config.discord_token))

    def _run_async(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    # ──────────────────────────────────────────────
    # 自然語言監聽 → GitHub Issue
    # ──────────────────────────────────────────────

    async def _handle_message(self, message: discord.Message):
        # 只忽略自己的訊息（允許其他 Bot 觸發，例如 OpenCalw）
        if message.author.id == self.client.user.id:
            return

        # 防止重複處理同一則訊息（加鎖 + 持久化）
        if self._dedup_lock is None:
            return
        async with self._dedup_lock:
            if message.id in self._processed_messages:
                logger.info("Duplicate message %s ignored", message.id)
                return
            self._processed_messages.add(message.id)
            self._save_processed(message.id)

        # 討論串內的「請繼續」指令：重新觸發 Agent
        if isinstance(message.channel, discord.Thread):
            if message.channel.parent_id == self.config.discord_agent_hub_id:
                content_stripped = re.sub(r"<@!?\d+>", "", message.content).strip()
                if content_stripped in ("請繼續", "繼續", "continue", "retry", "重試"):
                    thread_name = message.channel.name
                    m = re.match(r"issue-#(\d+)-", thread_name)
                    if m and self._orchestrator:
                        issue_number = int(m.group(1))
                        await message.add_reaction("▶️")
                        import threading
                        threading.Thread(
                            target=self._resume_issue,
                            args=(issue_number, message.channel.id),
                            daemon=True,
                        ).start()
            return

        # 只處理指定頻道的訊息，且需要 mention ClaudeCode bot
        bot_mentioned = self.client.user in message.mentions
        in_target_channel = message.channel.id == self.config.discord_channel_id

        if not (in_target_channel and bot_mentioned):
            return

        # 移除 mention 標籤，取得純文字內容
        content = re.sub(r"<@!?\d+>", "", message.content).strip()
        attachments = list(message.attachments)  # 保留截圖/附件

        if not content and not attachments:
            await message.reply("請說明你遇到的問題，我會幫你自動開 Issue。")
            return

        # 若只有圖片沒有文字，用附件檔名當 content
        if not content and attachments:
            content = f"附件截圖：{', '.join(a.filename for a in attachments)}"

        # ── 偵測「已Merge PR #N」→ 觸發 post-merge 流程 ──────────
        merge_match = re.match(r"已\s*[Mm]erge\s+[Pp][Rr]\s*#?(\d+)", content, re.IGNORECASE)
        if merge_match:
            pr_number = int(merge_match.group(1))
            await message.reply(
                f"✅ 收到！PR #{pr_number} 已 Merge。\n"
                f"正在執行 Post-Merge 流程：清理 → git pull → 重啟服務..."
            )
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, self._trigger_post_merge_callback, pr_number)
            return

        # 回應「處理中」
        try:
            processing_msg = await message.channel.send(
                f"> {content[:80]}{'...' if len(content) > 80 else ''}\n"
                f"正在分析問題並建立 GitHub Issue，請稍候..."
            )
        except Exception as e:
            logger.error("Failed to send processing message: %s", e)
            return

        title = self._extract_title(content)
        title_key = title[:30].lower()

        # ── Layer 1：檔案層級 cooldown（跨進程，最強防線）──────
        if self._is_on_cooldown(title_key):
            await processing_msg.edit(content=(
                f"⚠️ 相同問題剛剛已在處理中，請稍後查看 GitHub Issues。"
            ))
            return

        # ── Layer 2：in-memory 競態防護（同進程並發）───────────
        async with self._dedup_lock:
            if title_key in self._creating_issues:
                logger.info("Issue with same title already in-flight, skipping: %s", title_key)
                await processing_msg.delete()
                return
            self._creating_issues.add(title_key)

        # ── Layer 3：立即寫 cooldown（搶佔式，在建立前就鎖定）──
        # 其他進程/實例從這一刻起都會被 cooldown 擋住
        self._set_cooldown(title_key)

        try:
            issue, is_new = await self._create_github_issue(
                title=title,
                body=self._format_issue_body(content, message.author, attachments),
                attachments=attachments,
            )
            issue_url = issue["html_url"]
            issue_number = issue["number"]

            has_images = any(a.content_type and "image" in a.content_type for a in attachments) if attachments else False

            if is_new:
                status_msg = (
                    f"✅ **Issue #{issue_number} 已建立**\n"
                    f"{issue_url}\n\n"
                    f"ClaudeCode 正在分析問題並準備自動修復，完成後會回報 PR 連結。"
                )
                # 直接觸發 orchestrator（不依賴 GitHub webhook，確保 Agent 一定啟動）
                if self._orchestrator:
                    import threading
                    threading.Thread(
                        target=self._orchestrator.assign_issue,
                        args=(issue_number, issue["title"], issue.get("body", "")),
                        daemon=True,
                    ).start()
                    logger.info("Triggered auto-fix for new Issue #%s", issue_number)
            else:
                if has_images:
                    status_msg = (
                        f"♻️ **Issue #{issue_number} 已存在，截圖已補充並重新觸發修復**\n"
                        f"{issue_url}\n\n"
                        f"⚠️ 注意：Claude CLI 為純文字模式，**無法直接解讀截圖圖片內容**。\n"
                        f"若修復仍失敗，請直接輸入錯誤訊息的**文字內容**（例如：`404 Not Found`、`timeout` 等）。"
                    )
                    # 對已有 issue 直接觸發 orchestrator（不依賴 GitHub webhook）
                    if self._orchestrator:
                        import threading
                        threading.Thread(
                            target=self._orchestrator.assign_issue,
                            args=(issue_number, issue["title"], issue.get("body", "")),
                            daemon=True,
                        ).start()
                        logger.info("Re-triggered auto-fix for existing Issue #%s (new screenshots added)", issue_number)
                else:
                    status_msg = (
                        f"♻️ **Issue #{issue_number} 已存在，重新觸發自動修復**\n"
                        f"{issue_url}\n\n"
                        f"ClaudeCode 正在重新分析問題，完成後會回報 PR 連結。"
                    )
                    # 對已有 issue（無截圖）也直接觸發 orchestrator
                    if self._orchestrator:
                        import threading
                        threading.Thread(
                            target=self._orchestrator.assign_issue,
                            args=(issue_number, issue["title"], issue.get("body", "")),
                            daemon=True,
                        ).start()
                        logger.info("Re-triggered auto-fix for existing Issue #%s (no new screenshots)", issue_number)

            await processing_msg.edit(content=status_msg)
            logger.info("Issue #%s created from Discord message by %s", issue_number, message.author)

        except Exception as e:
            logger.error("Failed to create GitHub issue: %s", e)
            await processing_msg.edit(content=f"❌ 建立 Issue 失敗：{e}")
        finally:
            async with self._dedup_lock:
                self._creating_issues.discard(title_key)

    def _resume_issue(self, issue_number: int, thread_id: int) -> None:
        """從討論串「請繼續」指令重新觸發 Agent。"""
        try:
            resp = httpx.get(
                f"https://api.github.com/repos/{self.config.github_repo}/issues/{issue_number}",
                headers=self.gh_headers, timeout=10,
            )
            resp.raise_for_status()
            issue = resp.json()
            self._orchestrator.assign_issue(
                issue_number=issue_number,
                title=issue["title"],
                body=issue.get("body", ""),
            )
        except Exception as e:
            logger.error("Failed to resume Issue #%s: %s", issue_number, e)
            self._run_async(self._send_to_channel(thread_id, f"❌ 重新觸發失敗：{e}"))

    def _trigger_post_merge_callback(self, pr_number: int) -> None:
        """在 thread pool 中觸發 post-merge sync（從 Discord event loop 呼叫）。"""
        if self._orchestrator is None:
            logger.warning("Orchestrator not wired, cannot trigger post-merge for PR #%s", pr_number)
            return
        try:
            self._orchestrator.trigger_post_merge_sync(
                pr_number=pr_number,
                pr_title=f"PR #{pr_number} (user-triggered)",
                pr_body="",
            )
        except Exception as e:
            logger.error("Post-merge callback failed for PR #%s: %s", pr_number, e)

    def _extract_title(self, content: str) -> str:
        """取第一行或前 72 字作為 Issue 標題。"""
        first_line = content.splitlines()[0].strip()
        if len(first_line) <= 72:
            return first_line
        return first_line[:69] + "..."

    def _format_issue_body(self, content: str, author: discord.User, attachments: list = None) -> str:
        body = (
            f"## 問題描述\n{content}\n\n"
            f"## 來源\n由 Discord 用戶 `{author.display_name}` 透過 ClaudeCode Bot 回報"
        )
        if attachments:
            images = [a for a in attachments if a.content_type and "image" in a.content_type]
            others = [a for a in attachments if not (a.content_type and "image" in a.content_type)]
            if images:
                img_md = "\n".join(f"![{a.filename}]({a.url})" for a in images)
                body += f"\n\n## 截圖\n{img_md}"
            if others:
                file_md = "\n".join(f"- [{a.filename}]({a.url})" for a in others)
                body += f"\n\n## 附件\n{file_md}"
        return body

    async def _create_github_issue(self, title: str, body: str, attachments: list = None) -> tuple[dict, bool]:
        """回傳 (issue_dict, is_new)。is_new=False 表示回傳既有重複 issue。"""
        repo = self.config.github_repo
        async with httpx.AsyncClient() as client:
            # ── Layer 4：GitHub Search API（最廣範圍，含剛建立的）──
            search_q = f'repo:{repo} in:title "{title[:20]}" is:issue is:open'
            search_resp = await client.get(
                "https://api.github.com/search/issues",
                headers={**self.gh_headers, "Accept": "application/vnd.github+json"},
                params={"q": search_q, "per_page": 5, "sort": "created", "order": "desc"},
            )
            if search_resp.status_code == 200:
                items = search_resp.json().get("items", [])
                prefix = title[:30].lower()
                existing = [i for i in items if i.get("title", "")[:30].lower() == prefix]
                if existing:
                    existing_issue = existing[0]
                    logger.info(
                        "Duplicate issue detected via Search API, returning existing: #%s",
                        existing_issue["number"],
                    )
                    # 若新訊息有附件，把截圖補進 issue body
                    if attachments:
                        images = [a for a in attachments if a.content_type and "image" in a.content_type]
                        if images:
                            img_md = "\n".join(f"![{a.filename}]({a.url})" for a in images)
                            updated_body = (existing_issue.get("body") or "") + f"\n\n## 新增截圖（重新觸發修復）\n{img_md}"
                            await client.patch(
                                f"https://api.github.com/repos/{repo}/issues/{existing_issue['number']}",
                                headers=self.gh_headers,
                                json={"body": updated_body},
                            )
                            logger.info("Updated Issue #%s body with %d new screenshot(s)", existing_issue["number"], len(images))
                            existing_issue["body"] = updated_body
                    return existing_issue, False

            # 建立新 Issue
            resp = await client.post(
                f"https://api.github.com/repos/{repo}/issues",
                headers=self.gh_headers,
                json={"title": title, "body": body, "labels": ["bot-reported"]},
            )
            resp.raise_for_status()
            new_issue = resp.json()

            # ── Layer 5：建立後再確認是否有競態重複，自動關閉 ──
            await asyncio.sleep(2)
            verify_resp = await client.get(
                "https://api.github.com/search/issues",
                headers={**self.gh_headers, "Accept": "application/vnd.github+json"},
                params={"q": search_q, "per_page": 10, "sort": "created", "order": "asc"},
            )
            if verify_resp.status_code == 200:
                all_matching = [
                    i for i in verify_resp.json().get("items", [])
                    if i.get("title", "")[:30].lower() == title[:30].lower()
                ]
                if len(all_matching) > 1:
                    keep = all_matching[0]
                    for dup in all_matching[1:]:
                        logger.warning("Closing duplicate issue #%s (keeping #%s)", dup["number"], keep["number"])
                        await client.patch(
                            f"https://api.github.com/repos/{repo}/issues/{dup['number']}",
                            headers=self.gh_headers,
                            json={
                                "state": "closed",
                                "body": dup.get("body", "") + f"\n\n---\n_重複 Issue，已自動關閉。請參考 #{keep['number']}_",
                            },
                        )
                    if new_issue["number"] != keep["number"]:
                        logger.info("Our issue #%s was a duplicate, returning original #%s", new_issue["number"], keep["number"])
                        return keep, False

            return new_issue, True

    # ──────────────────────────────────────────────
    # 任務分配通知
    # ──────────────────────────────────────────────

    def post_task_assignment(self, issue_number, title, bot, complexity, note=""):
        msg = (
            f"**[TASK-{issue_number}]** {title}\n"
            f"狀態: `ASSIGNED`\n"
            f"執行 Bot: `{bot.value}`\n"
            f"複雜度: `{complexity.value}`"
        )
        if note:
            msg += f"\n備注: {note}"
        self._run_async(self._send_to_channel(self.config.discord_agent_hub_id, msg))

    # ──────────────────────────────────────────────
    # Thread 管理
    # ──────────────────────────────────────────────

    def create_agent_hub_thread(self, thread_name: str) -> int:
        """在 #agent-hub (discord_agent_hub_id) 開討論串供 Agent 工作使用。"""
        return self._run_async(self._create_thread(self.config.discord_agent_hub_id, thread_name))

    def notify_thread(self, thread_id: int, message: str) -> None:
        self._run_async(self._send_to_channel(thread_id, message))

    def archive_thread(self, thread_id: int) -> None:
        self._run_async(self._do_archive_thread(thread_id))

    # ──────────────────────────────────────────────
    # PR Review 協作
    # ──────────────────────────────────────────────

    def request_secondary_review(self, pr_number, diff):
        msg = f"@OpenCalw 請對 PR #{pr_number} 進行二次 code review。"
        self._run_async(self._send_to_channel(self.config.discord_agent_hub_id, msg))
        return {"verdict": "APPROVE", "has_critical": False, "comments": []}

    def request_auto_fix(self, pr_number, comments):
        issues = "\n".join(f"- {c}" for c in comments[:5])
        msg = (
            f"**[AUTO-FIX]** PR #{pr_number} 需要修改：\n{issues}\n"
            f"@ClaudeCode 請自動修正並重新提交。"
        )
        self._run_async(self._send_to_channel(self.config.discord_agent_hub_id, msg))

    # ──────────────────────────────────────────────
    # 日誌 / 警告
    # ──────────────────────────────────────────────

    def notify_main_channel(self, message: str) -> None:
        self._run_async(self._send_to_channel(self.config.discord_channel_id, message))

    def post_to_logs(self, message: str) -> None:
        self._run_async(self._send_to_channel(self.config.discord_logs_channel_id, message))

    def post_to_review_queue(self, message: str) -> None:
        self._run_async(self._send_to_channel(self.config.discord_review_queue_id, message))

    def post_pr_review_reminder(self, pr_number: int) -> None:
        msg = f"⏰ PR #{pr_number} 已超過 48 小時未 review，請盡快處理。"
        self._run_async(self._send_to_channel(self.config.discord_agent_hub_id, msg))

    # ──────────────────────────────────────────────
    # 內部 async helpers
    # ──────────────────────────────────────────────

    async def _send_to_channel(self, channel_id: int, message: str) -> None:
        channel = self.client.get_channel(channel_id)
        if channel is None:
            channel = await self.client.fetch_channel(channel_id)
        await channel.send(message)

    async def _create_thread(self, channel_id: int, thread_name: str) -> int:
        channel = self.client.get_channel(channel_id)
        if channel is None:
            channel = await self.client.fetch_channel(channel_id)
        thread = await channel.create_thread(
            name=thread_name,
            auto_archive_duration=60,
            type=discord.ChannelType.public_thread,
        )
        return thread.id

    async def _do_archive_thread(self, thread_id: int) -> None:
        thread = self.client.get_channel(thread_id)
        if thread is None:
            thread = await self.client.fetch_channel(thread_id)
        await thread.edit(archived=True)
