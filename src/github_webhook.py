"""
GitHub Webhook 接收伺服器
處理 issue、pull_request 事件
"""
import hashlib
import hmac
import json
import logging
import os
import re
from typing import Any

import httpx
from flask import Flask, abort, request, Response

from config import Config

logger = logging.getLogger(__name__)
app = Flask(__name__)


class GitHubWebhook:
    def __init__(self, config: Config, orchestrator: Any):
        self.config = config
        self.orchestrator = orchestrator
        self.headers = {
            "Authorization": f"Bearer {config.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.base_url = f"https://api.github.com/repos/{config.github_repo}"

    # ──────────────────────────────────────────────
    # Signature verification
    # ──────────────────────────────────────────────

    def _verify_signature(self, payload: bytes, signature: str) -> bool:
        expected = "sha256=" + hmac.new(
            self.config.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # ──────────────────────────────────────────────
    # Event routing
    # ──────────────────────────────────────────────

    def handle(self, event: str, payload: dict) -> None:
        if event == "issues" and payload.get("action") == "opened":
            self._handle_issue_opened(payload)
        elif event == "pull_request":
            action = payload.get("action")
            if action in ("opened", "synchronize"):
                self._handle_pr_opened(payload)
            elif action == "closed" and payload["pull_request"].get("merged"):
                self._handle_pr_merged(payload)
        elif event == "check_suite":
            action = payload.get("action")
            conclusion = payload.get("check_suite", {}).get("conclusion")
            if action == "completed" and conclusion == "success":
                self._handle_check_suite_success(payload)

    # ──────────────────────────────────────────────
    # Stage 1 — Issue opened
    # ──────────────────────────────────────────────

    def _handle_issue_opened(self, payload: dict) -> None:
        issue = payload["issue"]
        logger.info("Issue #%s opened: %s", issue["number"], issue["title"])
        self.orchestrator.assign_issue(
            issue_number=issue["number"],
            title=issue["title"],
            body=issue.get("body", ""),
        )

    # ──────────────────────────────────────────────
    # Stage 3 — PR opened / synchronize
    # ──────────────────────────────────────────────

    def _handle_pr_opened(self, payload: dict) -> None:
        pr = payload["pull_request"]
        logger.info("PR #%s opened/updated: %s", pr["number"], pr["title"])
        self.orchestrator.trigger_pr_review(
            pr_number=pr["number"],
            pr_title=pr["title"],
            head_sha=pr["head"]["sha"],
        )

    # ──────────────────────────────────────────────
    # Stage 5 — PR merged
    # ──────────────────────────────────────────────

    def _handle_pr_merged(self, payload: dict) -> None:
        pr = payload["pull_request"]
        pr_number = pr["number"]
        branch = pr["head"]["ref"]
        body = pr.get("body") or ""

        logger.info("PR #%s merged, branch=%s", pr_number, branch)

        # ① Delete source branch
        self._delete_branch(branch)

        # ② Close linked issues (Fixes #N)
        for issue_num in self._parse_fixes(body):
            self._close_issue(issue_num)

        # ③ Post-merge sync via orchestrator
        self.orchestrator.trigger_post_merge_sync(
            pr_number=pr_number,
            pr_title=pr["title"],
            pr_body=body,
        )

    def _delete_branch(self, branch: str) -> None:
        url = f"{self.base_url}/git/refs/heads/{branch}"
        resp = httpx.delete(url, headers=self.headers)
        if resp.status_code == 204:
            logger.info("Branch '%s' deleted.", branch)
        else:
            logger.warning("Failed to delete branch '%s': %s", branch, resp.text)

    def _close_issue(self, issue_number: int) -> None:
        url = f"{self.base_url}/issues/{issue_number}"
        resp = httpx.patch(url, headers=self.headers, json={"state": "closed"})
        if resp.status_code == 200:
            logger.info("Issue #%s closed.", issue_number)
        else:
            logger.warning("Failed to close issue #%s: %s", issue_number, resp.text)

    @staticmethod
    def _parse_fixes(body: str) -> list[int]:
        """Extract issue numbers from 'Fixes #N' patterns in PR body."""
        return [int(n) for n in re.findall(r"[Ff]ixes\s+#(\d+)", body)]

    def _handle_check_suite_success(self, payload: dict) -> None:
        """CI 全部通過 -> 嘗試 auto-merge 相關 PR。"""
        head_sha = payload.get("check_suite", {}).get("head_sha", "")
        resp = httpx.get(
            f"{self.base_url}/pulls",
            headers=self.headers,
            params={"state": "open", "per_page": 20},
            timeout=15,
        )
        if resp.status_code != 200:
            return
        for pr in resp.json():
            if pr["head"]["sha"] == head_sha and not pr.get("draft"):
                auto_merger = getattr(self.orchestrator, "auto_merger", None)
                if auto_merger:
                    auto_merger.try_auto_merge(pr["number"], head_sha)

    def handle_n8n_error(self, workflow_name: str, error_message: str, execution_id: str) -> None:
        """n8n 執行失敗 -> 自動建立 GitHub Issue。"""
        title = f"[n8n] {workflow_name} 執行失敗"
        body = (
            f"## n8n Workflow 執行錯誤（自動偵測）\n\n"
            f"**Workflow：** {workflow_name}\n"
            f"**Execution ID：** {execution_id or '未知'}\n\n"
            f"**錯誤訊息：**\n```\n{error_message[:1000]}\n```\n\n"
            f"**請檢查：**\n"
            f"1. n8n 介面查看 Execution 詳情（execution ID: {execution_id}）\n"
            f"2. 確認相關 HTTP Request 節點的 endpoint 是否正常\n"
            f"3. 若是 api_server 回傳錯誤，確認 port 8765 服務狀態"
        )
        resp = httpx.post(
            f"{self.base_url}/issues",
            headers=self.headers,
            json={"title": title, "body": body, "labels": ["n8n-error", "bot-reported"]},
            timeout=15,
        )
        if resp.status_code == 201:
            issue = resp.json()
            logger.info("n8n error Issue #%s created", issue["number"])
        else:
            logger.error("Failed to create n8n error issue: %s", resp.text)


# ──────────────────────────────────────────────
# Flask routes
# ──────────────────────────────────────────────

_webhook: GitHubWebhook | None = None


def init_webhook(config: Config, orchestrator: Any) -> None:
    global _webhook
    _webhook = GitHubWebhook(config, orchestrator)


@app.route("/webhook", methods=["POST"])
def webhook_endpoint():
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _webhook._verify_signature(request.data, signature):
        abort(403, "Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    payload = request.get_json(force=True)
    _webhook.handle(event, payload)
    return "", 200


@app.route("/webhook/line-qa", methods=["POST"])
def line_webhook_proxy():
    """Proxy /webhook/line-qa to n8n (port 5681, Docker instance with full 40-node workflow).
    LINE Messaging API → ngrok (port 8080) → n8n webhook (port 5681).
    """
    n8n_url = "http://127.0.0.1:5681/webhook/line-qa"
    try:
        resp = httpx.post(
            n8n_url,
            content=request.data,
            headers={k: v for k, v in request.headers if k.lower() not in ("host", "content-length")},
            timeout=30,
        )
        return Response(resp.content, status=resp.status_code,
                        content_type=resp.headers.get("content-type", "application/json"))
    except Exception as e:
        logger.error("LINE webhook proxy error: %s", e)
        return Response(json.dumps({"error": "n8n unavailable"}), status=503,
                        content_type="application/json")


@app.route("/files/<path:filename>", methods=["GET"])
def file_proxy(filename: str):
    """Proxy /files/<filename> to api_server.py (port 8765).
    讓 LINE 用戶透過 ngrok (port 8080) 存取 api_server.py 的檔案服務。
    """
    api_port = os.environ.get("API_SERVER_PORT", "8765")
    target_url = f"http://127.0.0.1:{api_port}/files/{filename}"
    try:
        resp = httpx.get(target_url, timeout=30, follow_redirects=True)
        return Response(
            resp.content,
            status=resp.status_code,
            headers={
                k: v for k, v in resp.headers.items()
                if k.lower() in ("content-type", "content-disposition", "content-length")
            },
        )
    except Exception as e:
        logger.error("File proxy error for %s: %s", filename, e)
        return Response(
            json.dumps({"error": "File service unavailable"}),
            status=503,
            content_type="application/json",
        )


@app.route("/webhook/n8n-error", methods=["POST"])
def n8n_error_webhook():
    """接收 n8n Error Workflow 推送的執行失敗事件。

    n8n Error Workflow 設定：
      HTTP Request node -> POST http://localhost:8080/webhook/n8n-error
      Body: {"workflow_name": "...", "error_message": "...", "execution_id": "..."}
    """
    raw_body = request.data.decode("utf-8", errors="replace")
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    workflow_name = data.get("workflow_name", "未知 Workflow")
    error_message = data.get("error_message", "（無詳細錯誤）")
    execution_id = data.get("execution_id", "")

    # Warn when required fields are missing so the n8n Error Workflow
    # misconfiguration is visible in logs (and included in the Issue body).
    missing_fields = [f for f, v in [
        ("workflow_name", workflow_name == "未知 Workflow"),
        ("error_message", error_message == "（無詳細錯誤）"),
        ("execution_id", not execution_id),
    ] if v]
    if missing_fields:
        logger.warning(
            "n8n-error webhook missing fields %s — raw body: %.500s",
            missing_fields, raw_body,
        )
        # Append raw body to error_message so the Issue contains diagnostic info
        error_message = f"{error_message}\n\n[診斷] 原始請求 body：\n```\n{raw_body[:800]}\n```"

    logger.info("n8n error received: workflow=%s execution=%s", workflow_name, execution_id)

    if _webhook:
        _webhook.handle_n8n_error(workflow_name, error_message, execution_id)

    return "", 200
