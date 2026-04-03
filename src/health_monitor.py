"""
HealthMonitor — 定時健康檢查，偵測故障後自動建立 GitHub Issue。

檢查對象：
  - api_server.py（port 8765）：GET /health -> {"status":"ok"}
  - n8n（port 5678）：GET /healthz -> 200

觸發建 Issue 條件：連續 fail_threshold 次失敗（預設 2）
防重複：同服務 cooldown_seconds 內只建一次（預設 1800s = 30 min）
"""
import logging
import threading
import time

import httpx

logger = logging.getLogger(__name__)


class HealthMonitor:

    def __init__(self, config, discord_bot, fail_threshold: int = 2, cooldown_seconds: int = 1800):
        self.config = config
        self.discord = discord_bot
        self._fail_threshold = fail_threshold
        self._cooldown_seconds = cooldown_seconds
        self._fail_counts: dict[str, int] = {}
        self._last_issue_ts: dict[str, float] = {}
        self._timer: threading.Timer | None = None
        self._stopped = threading.Event()
        self._gh_headers = {
            "Authorization": f"Bearer {config.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # -- Public API -----------------------------------------------------------

    def start(self) -> None:
        """啟動定時檢查（非阻塞）。"""
        logger.info("HealthMonitor started (interval=%ss)", self.config.health_check_interval_seconds)
        self._schedule_next()

    def stop(self) -> None:
        self._stopped.set()
        if self._timer:
            self._timer.cancel()

    # -- Internal -------------------------------------------------------------

    def _schedule_next(self) -> None:
        if self._stopped.is_set():
            return
        self._timer = threading.Timer(
            self.config.health_check_interval_seconds,
            self._run_checks,
        )
        self._timer.daemon = True
        self._timer.start()

    def _run_checks(self) -> None:
        for port in self.config.health_check_ports:
            self._check_service(
                name=f"api_server (port {port})",
                url=f"http://127.0.0.1:{port}/health",
                cooldown_key=f"api_{port}",
                issue_body=(
                    f"## 自動偵測：api_server (port {port}) 健康檢查失敗\n\n"
                    f"HealthMonitor 連續 {self._fail_threshold} 次無法連線 "
                    f"`http://127.0.0.1:{port}/health`。\n\n"
                    "**請檢查：**\n"
                    "1. api_server.py 是否已停止\n"
                    "2. Port 是否被其他程序佔用\n"
                    "3. 使用 `start_api_server.bat` 手動重啟確認"
                ),
            )

        if self.config.n8n_health_url:
            self._check_service(
                name="n8n",
                url=self.config.n8n_health_url,
                cooldown_key="n8n",
                issue_body=(
                    "## 自動偵測：n8n 服務無回應\n\n"
                    f"HealthMonitor 連續 {self._fail_threshold} 次無法連線 "
                    f"`{self.config.n8n_health_url}`。\n\n"
                    "**請檢查：**\n"
                    "1. n8n Docker container 是否在執行（`docker ps`）\n"
                    "2. 執行 `docker start n8n` 重啟\n"
                    "3. 確認 port 5678 未被佔用"
                ),
            )

        self._schedule_next()

    def _check_service(self, name: str, url: str, cooldown_key: str, issue_body: str = "") -> None:
        ok = self._check_url(url)
        if ok:
            if self._fail_counts.get(cooldown_key, 0) > 0:
                logger.info("HealthMonitor: %s recovered", name)
            self._fail_counts[cooldown_key] = 0
            return

        self._fail_counts[cooldown_key] = self._fail_counts.get(cooldown_key, 0) + 1
        count = self._fail_counts[cooldown_key]
        logger.warning("HealthMonitor: %s check failed (%s/%s)", name, count, self._fail_threshold)

        if count < self._fail_threshold:
            return

        # Reached threshold — check cooldown
        last_ts = self._last_issue_ts.get(cooldown_key, 0)
        if time.time() - last_ts < self._cooldown_seconds:
            logger.info("HealthMonitor: %s issue cooldown active, skipping", name)
            return

        # Create Issue
        self._last_issue_ts[cooldown_key] = time.time()
        issue_title = f"[AutoDetect] {name} 健康檢查失敗"
        self._create_issue(issue_title, issue_body or f"{name} 連線失敗")
        self.discord.post_to_logs(f"🚨 **AutoDetect** {name} 故障，已自動建立 GitHub Issue。")

    def _check_url(self, url: str) -> bool:
        try:
            resp = httpx.get(url, timeout=5)
            return resp.status_code == 200
        except Exception as e:
            logger.debug("HealthMonitor check failed for %s: %s", url, e)
            return False

    def _create_issue(self, title: str, body: str) -> None:
        try:
            resp = httpx.post(
                f"https://api.github.com/repos/{self.config.github_repo}/issues",
                headers=self._gh_headers,
                json={"title": title, "body": body, "labels": ["auto-detected"]},
                timeout=15,
            )
            if resp.status_code == 201:
                issue = resp.json()
                logger.info("HealthMonitor created Issue #%s: %s", issue["number"], title)
            else:
                logger.error("Failed to create issue: %s", resp.text)
        except Exception as e:
            logger.error("HealthMonitor _create_issue error: %s", e)
