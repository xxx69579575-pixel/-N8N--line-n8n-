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
        return json.loads(resp.read().decode("utf-8")) if resp.read() else {}


def reply_message(reply_token: str, messages: list) -> bool:
    """
    使用 reply token 回覆訊息。
    回傳 True 表示成功，False 表示失敗（token 過期或其他錯誤）。
    """
    try:
        _line_api_request(LINE_REPLY_URL, {
            "replyToken": reply_token,
            "messages": messages,
        })
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.warning("reply_message failed (HTTP %s): %s", e.code, body)
        # 400 通常表示 token 過期或已使用
        return False
    except Exception as e:
        logger.warning("reply_message failed: %s", e)
        return False


def push_message(user_id: str, messages: list) -> bool:
    """
    使用 push API 傳送訊息（不需要 reply token）。
    用於 reply token 過期後的 fallback。
    """
    try:
        _line_api_request(LINE_PUSH_URL, {
            "to": user_id,
            "messages": messages,
        })
        logger.info("push_message sent to %s", user_id)
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error("push_message failed (HTTP %s): %s", e.code, body)
        return False
    except Exception as e:
        logger.error("push_message failed: %s", e)
        return False


def send_message_with_fallback(
    reply_token: str,
    user_id: str,
    messages: list,
) -> None:
    """
    先嘗試 reply API；若失敗（token 過期）自動 fallback 至 push API。

    Args:
        reply_token: 來自 webhook 事件的 replyToken
        user_id    : 事件的 source.userId，用於 push fallback
        messages   : LINE message objects 陣列
    """
    if not reply_message(reply_token, messages):
        logger.info(
            "reply token expired or invalid for user %s, falling back to push",
            user_id,
        )
        push_message(user_id, messages)


# ---------------------------------------------------------------------------
# 事件處理（在背景執行緒中執行）
# ---------------------------------------------------------------------------

def handle_message_event(event: dict) -> None:
    """處理 message 類型事件，回覆相同文字（echo bot 示例）。"""
    reply_token = event.get("replyToken", "")
    source = event.get("source", {})
    user_id = source.get("userId", "")
    message = event.get("message", {})
    text = message.get("text", "")

    if not reply_token or not user_id:
        logger.warning("Missing replyToken or userId in event: %s", event)
        return

    # 在此加入實際業務邏輯（例如 RAG 查詢、AI 回覆等）
    # 因為已在背景執行緒中，可安全進行耗時操作
    response_text = f"您說：{text}" if text else "（非文字訊息）"

    send_message_with_fallback(
        reply_token=reply_token,
        user_id=user_id,
        messages=[{"type": "text", "text": response_text}],
    )


def process_events(events: list) -> None:
    """在背景執行緒中逐一處理所有事件。"""
    for event in events:
        event_type = event.get("type", "")
        try:
            if event_type == "message":
                handle_message_event(event)
            else:
                logger.info("Unhandled event type: %s", event_type)
        except Exception as e:
            logger.exception("Error processing event %s: %s", event_type, e)


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------

class WebhookHandler(BaseHTTPRequestHandler):
    """LINE Webhook HTTP handler。"""

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/webhook":
            self._respond(404, b"Not Found")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # 1. 驗證簽章
        signature = self.headers.get("X-Line-Signature", "")
        if not verify_signature(body, signature):
            logger.warning("Invalid signature — request rejected")
            self._respond(400, b"Invalid signature")
            return

        # 2. 立即回傳 200 OK（必須在 30 秒內，否則 LINE 平台視為失敗並 retry）
        self._respond(200, b"OK")

        # 3. 解析事件並在背景執行緒中處理（不阻塞 HTTP response）
        try:
            payload = json.loads(body.decode("utf-8"))
            events = payload.get("events", [])
            if events:
                t = threading.Thread(
                    target=process_events,
                    args=(events,),
                    daemon=True,
                )
                t.start()
        except json.JSONDecodeError as e:
            logger.error("Failed to parse webhook body: %s", e)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._respond(200, b"OK")
        else:
            self._respond(404, b"Not Found")

    def _respond(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # noqa: ANN002
        logger.info(fmt, *args)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    logger.info("LINE Webhook server listening on port %d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
