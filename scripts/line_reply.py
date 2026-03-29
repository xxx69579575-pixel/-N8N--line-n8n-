#!/usr/bin/env python3
"""
line_reply.py — LINE Bot 回覆工具，自動處理 reply token 過期問題

功能：
  1. 嘗試使用 replyToken 呼叫 Reply API
  2. 若 reply token 過期（HTTP 400, property=replyToken），自動 fallback 到 Push API
  3. 從 stdin 讀取 JSON，輸出執行結果至 stdout
  4. 提供 build_flex_bubble() 建構含圖片的 Flex Message，避免排版跑版

stdin JSON 格式：
{
  "reply_token": "<replyToken from webhook event>",
  "user_id": "<userId, optional, for push fallback>",
  "messages": [{"type": "text", "text": "..."}]
}

環境變數（可從 config/.env 載入）：
  LINE_CHANNEL_ACCESS_TOKEN — LINE Channel Access Token
"""

import sys
import json
import os
import urllib.request
import urllib.error
from pathlib import Path


LINE_REPLY_API = "https://api.line.me/v2/bot/message/reply"
LINE_PUSH_API  = "https://api.line.me/v2/bot/message/push"


def load_env_file(env_path: str) -> None:
    """從 .env 檔案載入環境變數（若尚未設定）"""
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass


def get_access_token() -> str:
    """取得 LINE_CHANNEL_ACCESS_TOKEN，優先環境變數，其次 config/.env"""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        env_path = Path(__file__).parent.parent / "config" / ".env"
        load_env_file(str(env_path))
        token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN not set")
    return token


def _post_json(url: str, payload: dict, token: str) -> dict:
    """對 LINE API 發送 POST JSON，回傳 {status, body, error?}"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return {"status": resp.status, "body": json.loads(body) if body else {}}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            err_body = json.loads(raw)
        except json.JSONDecodeError:
            err_body = {"raw": raw}
        return {"status": e.code, "body": err_body, "error": True}


def is_token_expired(response: dict) -> bool:
    """
    判斷是否為 reply token 過期錯誤。
    LINE API 在 token 過期時回傳 HTTP 400，
    details 陣列內含 {"property": "replyToken"}。
    """
    if response.get("status") != 400:
        return False
    body = response.get("body", {})
    details = body.get("details", [])
    if any(d.get("property") == "replyToken" for d in details):
        return True
    return False


def build_flex_bubble(
    alt_text: str,
    image_url: str,
    title: str = "",
    body_text: str = "",
    aspect_ratio: str = "20:13",
    aspect_mode: str = "cover",
) -> dict:
    """
    建構一個標準 Flex Message bubble，含頂部圖片。

    參數：
      alt_text    — 無法顯示 Flex 時的替代文字（必填）
      image_url   — 圖片 URL（HTTPS）
      title       — hero 下方標題文字（可選）
      body_text   — 內文說明（可選）
      aspect_ratio — 圖片寬高比，預設 "20:13"（約 16:9 的橫幅）
      aspect_mode  — "cover" 填滿裁切 / "fit" 完整顯示，預設 cover

    注意：
      - aspectRatio 與 aspectMode 是避免圖片跑版的關鍵設定
      - 圖片 URL 必須為 HTTPS，否則 LINE 會拒絕顯示
    """
    hero = {
        "type": "image",
        "url": image_url,
        "size": "full",
        "aspectRatio": aspect_ratio,
        "aspectMode": aspect_mode,
    }

    contents: dict = {"type": "bubble", "hero": hero}

    body_components = []
    if title:
        body_components.append(
            {
                "type": "text",
                "text": title,
                "weight": "bold",
                "size": "xl",
                "wrap": True,
            }
        )
    if body_text:
        body_components.append(
            {
                "type": "text",
                "text": body_text,
                "size": "sm",
                "color": "#555555",
                "wrap": True,
            }
        )

    if body_components:
        contents["body"] = {"type": "box", "layout": "vertical", "contents": body_components}

    return {
        "type": "flex",
        "altText": alt_text,
        "contents": contents,
    }


def send_reply(reply_token: str, messages: list, token: str) -> dict:
    """呼叫 Reply API；回傳 API 回應 dict。"""
    payload = {"replyToken": reply_token, "messages": messages}
    return _post_json(LINE_REPLY_API, payload, token)


def send_push(user_id: str, messages: list, token: str) -> dict:
    """呼叫 Push API；回傳 API 回應 dict。"""
    payload = {"to": user_id, "messages": messages}
    return _post_json(LINE_PUSH_API, payload, token)


def main() -> None:
    try:
        access_token = get_access_token()
    except ValueError as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)

    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    reply_token = payload.get("reply_token", "")
    user_id = payload.get("user_id", "")
    messages = payload.get("messages", [])

    if not messages:
        print(json.dumps({"success": False, "error": "messages is empty"}))
        sys.exit(1)

    # 1. 嘗試 Reply API
    if reply_token:
        result = send_reply(reply_token, messages, access_token)
        if not result.get("error"):
            print(json.dumps({"success": True, "method": "reply", "response": result}))
            return

        # reply token 過期 → fallback 到 Push API
        if is_token_expired(result) and user_id:
            push_result = send_push(user_id, messages, access_token)
            if not push_result.get("error"):
                print(json.dumps({"success": True, "method": "push_fallback", "response": push_result}))
                return
            print(json.dumps({"success": False, "method": "push_fallback", "response": push_result}))
            sys.exit(1)

        print(json.dumps({"success": False, "method": "reply", "response": result}))
        sys.exit(1)

    # 2. 無 reply_token，直接走 Push API
    if user_id:
        push_result = send_push(user_id, messages, access_token)
        ok = not push_result.get("error")
        print(json.dumps({"success": ok, "method": "push", "response": push_result}))
        sys.exit(0 if ok else 1)

    print(json.dumps({"success": False, "error": "Neither reply_token nor user_id provided"}))
    sys.exit(1)


if __name__ == "__main__":
    main()
