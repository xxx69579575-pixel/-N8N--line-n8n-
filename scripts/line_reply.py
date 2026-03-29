#!/usr/bin/env python3
"""
line_reply.py — LINE Bot 回覆工具，自動處理 reply token 過期問題

功能：
  1. 嘗試使用 replyToken 呼叫 Reply API
  2. 若 reply token 過期（HTTP 400, property=replyToken），自動 fallback 到 Push API
  3. 支援 Flex Message（圖片 + 文字排版）
  4. 從 stdin 讀取 JSON，輸出執行結果至 stdout

stdin JSON 格式：
{
  "reply_token": "<replyToken from webhook event>",
  "user_id": "<userId, optional, for push fallback>",
  "messages": [{"type": "text", "text": "..."}]
}

或傳入 flex 訊息：
{
  "reply_token": "...",
  "user_id": "...",
  "flex": {
    "alt_text": "訊息預覽文字",
    "image_url": "https://example.com/image.jpg",
    "title": "標題",
    "body_text": "內文",
    "action_label": "查看詳情",
    "action_uri": "https://example.com"
  }
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


def build_flex_image_message(
    alt_text: str,
    image_url: str,
    title: str = "",
    body_text: str = "",
    action_label: str = "查看詳情",
    action_uri: str = "",
) -> dict:
    """
    建立符合 LINE Flex Message 規格的圖片訊息。

    修復要點：
    - hero image 必須設定 aspectRatio（預設 20:13）與 size="full"
    - hero image 的 action 必須是合法的 URIAction
    - body 使用 vertical layout，文字元件使用 wrap=True 避免截斷
    - altText 為必填欄位
    """
    hero: dict = {
        "type": "image",
        "url": image_url,
        "size": "full",
        "aspectRatio": "20:13",
        "aspectMode": "cover",
    }
    if action_uri:
        hero["action"] = {
            "type": "uri",
            "label": action_label,
            "uri": action_uri,
        }

    body_contents = []
    if title:
        body_contents.append({
            "type": "text",
            "text": title,
            "weight": "bold",
            "size": "xl",
            "wrap": True,
        })
    if body_text:
        body_contents.append({
            "type": "text",
            "text": body_text,
            "size": "sm",
            "color": "#666666",
            "wrap": True,
        })

    bubble: dict = {
        "type": "bubble",
        "hero": hero,
    }
    if body_contents:
        bubble["body"] = {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents,
            "paddingAll": "12px",
            "spacing": "sm",
        }
    if action_uri:
        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "action": {
                        "type": "uri",
                        "label": action_label,
                        "uri": action_uri,
                    },
                }
            ],
            "paddingAll": "12px",
        }

    return {
        "type": "flex",
        "altText": alt_text,
        "contents": bubble,
    }


def reply_or_push(reply_token: str, user_id: str, messages: list, token: str) -> dict:
    """嘗試 Reply API；若 token 過期則 fallback 到 Push API。"""
    payload = {"replyToken": reply_token, "messages": messages}
    result = _post_json(LINE_REPLY_API, payload, token)

    if is_token_expired(result):
        if not user_id:
            return {"ok": False, "error": "reply token expired and no user_id for push fallback", "detail": result}
        push_payload = {"to": user_id, "messages": messages}
        push_result = _post_json(LINE_PUSH_API, push_payload, token)
        push_result["fallback"] = "push"
        return push_result

    return result


def main() -> None:
    try:
        token = get_access_token()
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)

    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    reply_token = payload.get("reply_token", "")
    user_id = payload.get("user_id", "")

    # 支援 flex 快捷格式
    if "flex" in payload:
        f = payload["flex"]
        messages = [
            build_flex_image_message(
                alt_text=f.get("alt_text", "訊息"),
                image_url=f.get("image_url", ""),
                title=f.get("title", ""),
                body_text=f.get("body_text", ""),
                action_label=f.get("action_label", "查看詳情"),
                action_uri=f.get("action_uri", ""),
            )
        ]
    else:
        messages = payload.get("messages", [])

    if not messages:
        print(json.dumps({"ok": False, "error": "No messages provided"}))
        sys.exit(1)

    result = reply_or_push(reply_token, user_id, messages, token)
    ok = not result.get("error") and result.get("status", 0) in (200, 0)
    result["ok"] = ok
    print(json.dumps(result, ensure_ascii=False))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
