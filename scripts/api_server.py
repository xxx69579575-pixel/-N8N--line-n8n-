#!/usr/bin/env python3
"""
api_server.py — LINE Webhook 接收與處理伺服器

修復：reply token 過期問題
- webhook 立即回傳 200 OK，避免 LINE 平台 retry
- 事件處理改為背景執行緒，不阻塞主執行緒
- reply 失敗時自動 fallback 至 push message API
"""

import hashlib
import hmac
import json
import logging
import os
import sys
import threading
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
import urllib.error
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

def _load_dotenv(path: str) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass


_project_root = Path(__file__).parent.parent
_env_path = _project_root / "config" / ".env"
_load_dotenv(str(_env_path))

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


# ---------------------------------------------------------------------------
# LINE API helpers
# ---------------------------------------------------------------------------

def verify_signature(body: bytes, signature: str) -> bool:
    """驗證 LINE Webhook HMAC-SHA256 簽章"""
    if not LINE_CHANNEL_SECRET:
        logger.warning("LINE_CHANNEL_SECRET not configured")
        return False
    key = LINE_CHANNEL_SECRET.encode("utf-8")
    digest = hmac.new(key, body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _line_api_request(url: str, payload: dict) -> dict:
    """呼叫 LINE Messaging API，回傳 response dict。失敗時 raise exception。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        # FIX: read body once into a variable to avoid consuming the stream twice
        body = resp.read()
        return json.loads(body.decode("utf-8")) if body else {}


def reply_message(reply_token: str, messages: list) -> bool:
    """
    使用 reply token 回覆訊息。
    回傳 True 表示成功，False 表示失敗（token 過期或網路錯誤）。
    """
    if not reply_token or not messages:
        return False
    payload = {
        "replyToken": reply_token,
        "messages": messages,
    }
    try:
        _line_api_request(LINE_REPLY_URL, payload)
        logger.info("reply_message: success (token=%s...)", reply_token[:8])
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.warning("reply_message: HTTP %s — %s", e.code, body)
        return False
    except Exception as exc:
        logger.warning("reply_message: failed — %s", exc)
        return False


def push_message(user_id: str, messages: list) -> bool:
    """
    使用 push API 主動傳送訊息（不需要 reply token）。
    用於 reply token 過期時的 fallback。
    """
    if not user_id or not messages:
        return False
    payload = {
        "to": user_id,
        "messages": messages,
    }
    try:
        _line_api_request(LINE_PUSH_URL, payload)
        logger.info("push_message: success (user=%s)", user_id)
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error("push_message: HTTP %s — %s", e.code, body)
        return False
    except Exception as exc:
        logger.error("push_message: failed — %s", exc)
        return False


def reply_or_push(reply_token: str, user_id: str, messages: list) -> bool:
    """先嘗試 reply；若失敗則 fallback 至 push。"""
    if reply_message(reply_token, messages):
        return True
    logger.info("reply failed, falling back to push for user=%s", user_id)
    return push_message(user_id, messages)


# ---------------------------------------------------------------------------
# Event processing (runs in background thread)
# ---------------------------------------------------------------------------

def _process_event(event: dict) -> None:
    """處理單一 LINE 事件（於背景執行緒中執行）。"""
    event_type = event.get("type")
    if event_type != "message":
        return

    message = event.get("message", {})
    if message.get("type") != "text":
        return

    text = message.get("text", "").strip()
    reply_token = event.get("replyToken", "")
    user_id = event.get("source", {}).get("userId", "")

    logger.info("Received message: %r from user=%s", text, user_id)

    response_messages = [
        {"type": "text", "text": f"已收到您的訊息：{text}"}
    ]
    reply_or_push(reply_token, user_id, response_messages)


def _handle_events_async(events: list) -> None:
    """在背景執行緒中處理所有事件，避免阻塞主執行緒（防止 LINE retry）。"""
    for event in events:
        try:
            _process_event(event)
        except Exception as exc:
            logger.error("Error processing event %s: %s", event.get("type"), exc)


# ---------------------------------------------------------------------------
# HTTP Request Handler
# ---------------------------------------------------------------------------

class WebhookHandler(BaseHTTPRequestHandler):
    """接收 LINE Webhook POST 請求的 HTTP Handler。"""

    def log_message(self, fmt, *args):  # suppress default access log spam
        logger.debug("HTTP %s", fmt % args)

    def do_GET(self):
        """健康檢查端點，讓 n8n HTTP Request 節點可確認服務存活。"""
        if self.path in ("/", "/health"):
            self._respond(200, {"status": "ok"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        """接收並驗證 LINE Webhook，立即回傳 200，背景處理事件。"""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            # 驗證簽章
            signature = self.headers.get("X-Line-Signature", "")
            if not verify_signature(body, signature):
                logger.warning("Invalid signature from %s", self.client_address)
                self._respond(400, {"error": "invalid signature"})
                return

            # 立即回傳 200 OK（防止 LINE 因逾時而 retry）
            self._respond(200, {"status": "ok"})

            # 背景執行緒處理事件
            payload = json.loads(body.decode("utf-8"))
            events = payload.get("events", [])
            if events:
                t = threading.Thread(
                    target=_handle_events_async,
                    args=(events,),
                    daemon=True,
                )
                t.start()

        except json.JSONDecodeError as exc:
            logger.error("JSON decode error: %s", exc)
            self._respond(400, {"error": "invalid JSON"})
        except Exception as exc:
            logger.exception("Unexpected error in do_POST: %s", exc)
            # 仍回傳 200 避免 LINE retry；錯誤已記錄
            self._respond(200, {"status": "error", "detail": str(exc)})

    def _respond(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    host = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("WEBHOOK_PORT", "8080"))

    if not LINE_CHANNEL_SECRET:
        logger.warning("LINE_CHANNEL_SECRET is not set — signature verification will fail")
    if not LINE_CHANNEL_ACCESS_TOKEN:
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN is not set — messaging will fail")

    server = HTTPServer((host, port), WebhookHandler)
    logger.info("Webhook server listening on %s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
