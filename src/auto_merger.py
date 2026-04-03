"""
AutoMerger — 低風險 PR 自動 Merge。

觸發條件（全部滿足）：
  1. config.auto_merge_enabled = True
  2. PR 變更的所有檔案路徑符合 auto_merge_safe_paths
  3. 由外部在 CI 通過後呼叫（github_webhook check_suite handler）
"""
import logging

import httpx

logger = logging.getLogger(__name__)


class AutoMerger:

    def __init__(self, config, discord_bot):
        self.config = config
        self.discord = discord_bot
        self._gh_headers = {
            "Authorization": f"Bearer {config.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._base = f"https://api.github.com/repos/{config.github_repo}"

    def try_auto_merge(self, pr_number: int, head_sha: str) -> bool:
        """
        檢查 PR 是否符合自動 Merge 條件，符合則 Merge。
        回傳 True = 已 Merge，False = 跳過。
        """
        if not self.config.auto_merge_enabled:
            return False

        files = self._get_pr_files(pr_number)
        if not files:
            logger.info("AutoMerger: PR #%s has no changed files, skipping", pr_number)
            return False

        if not self._is_safe_change(files):
            logger.info(
                "AutoMerger: PR #%s has risky files %s, skipping",
                pr_number, [f for f in files if not self._file_is_safe(f)],
            )
            return False

        logger.info("AutoMerger: PR #%s qualifies for auto-merge", pr_number)
        return self._merge_pr(pr_number, head_sha)

    def _is_safe_change(self, files: list[str]) -> bool:
        if not files:
            return False
        return all(self._file_is_safe(f) for f in files)

    def _file_is_safe(self, path: str) -> bool:
        return any(path.startswith(p) or path.endswith(p) for p in self.config.auto_merge_safe_paths)

    def _get_pr_files(self, pr_number: int) -> list[str]:
        try:
            resp = httpx.get(
                f"{self._base}/pulls/{pr_number}/files",
                headers=self._gh_headers,
                timeout=15,
            )
            if resp.status_code == 200:
                return [f["filename"] for f in resp.json()]
        except Exception as e:
            logger.error("AutoMerger _get_pr_files error: %s", e)
        return []

    def _merge_pr(self, pr_number: int, head_sha: str) -> bool:
        try:
            resp = httpx.put(
                f"{self._base}/pulls/{pr_number}/merge",
                headers=self._gh_headers,
                json={
                    "commit_title": f"Auto-merge PR #{pr_number} (low-risk, CI passed)",
                    "sha": head_sha,
                    "merge_method": "squash",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                logger.info("AutoMerger: PR #%s merged successfully", pr_number)
                self.discord.notify_main_channel(
                    f"🤖 **Auto-Merge** PR #{pr_number} 已自動合併\n（低風險變更 + CI 通過）"
                )
                return True
            elif resp.status_code == 405:
                logger.info("AutoMerger: PR #%s not yet mergeable (CI pending or review required)", pr_number)
                return False
            elif resp.status_code == 409:
                logger.warning("AutoMerger: PR #%s has merge conflicts, skipping", pr_number)
                return False
            else:
                logger.warning("AutoMerger merge failed for PR #%s: %s", pr_number, resp.text)
                return False
        except Exception as e:
            logger.error("AutoMerger _merge_pr error: %s", e)
            return False
