#!/usr/bin/env python3
"""
line_reply.py — LINE Bot 回覆工具，自動處理 reply token 過期問題

功能：
  1. 嘗試使用 replyToken 呼叫 Reply API
  2. 若 reply token 過期（HTTP 400, property=replyToken），自動 fallback 到 Push API
  3. 從 stdin 讀取 JSON，輸出執行結果至 stdout
  4. 提供 build_flex_image_message() 輔助函式，確保 Flex Message 圖片欄位完整

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
    return any(d.get("property") == "replyToken" for d in details)


def build_flex_image_message(
    image_url: str,
    alt_text: str = "圖片訊息",
    aspect_ratio: str = "20:13",
    aspect_mode: str = "cover",
    size: str = "full",
    body_contents: list | None = None,
) -> dict:
    """
    建構包含圖片的 Flex Message。

    LINE Flex Message 圖片必須提供以下欄位，否則會排版跑版或圖片空白：
      - aspectRatio：圖片長寬比，例如 "20:13"、"1:1"、"3:4"
      - aspectMode："cover"（裁切填滿）或 "fit"（完整顯示）
      - size："full"、"5xl"、"4xl" 等，hero image 通常用 "full"

    Args:
        image_url:     圖片的 HTTPS URL
        alt_text:      Flex Message 替代文字（通知欄顯示）
        aspect_ratio:  圖片外框長寬比（預設 "20:13"）
        aspect_mode:   填充模式，"cover" 或 "fit"（預設 "cover"）
        size:          圖片尺寸關鍵字（預設 "full"）
        body_contents: bubble body 的額外 contents 清單（可選）

    Returns:
        符合 LINE Messaging API 格式的 Flex Message dict
    """
    hero_block = {
        "type": "image",
        "url": image_url,
        "size": size,
        "aspectRatio": aspect_ratio,
        "aspectMode": aspect_mode,
    }

    bubble: dict = {
        "type": "bubble",
        "hero": hero_block,
    }

    if body_contents:
        bubble["body"] = {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents,
        }

    return {
        "type": "flex",
        "altText": alt_text,
        "contents": bubble,
    }


def reply_or_push(reply_token: str, user_id: str, messages: list, token: str) -> dict:
    """嘗試 Reply API，若 token 過期則 fallback 到 Push API"""
    result = _post_json(
        LINE_REPLY_API,
        {"replyToken": reply_token, "messages": messages},
        token,
    )
    if is_token_expired(result):
        if not user_id:
            return {"success": False, "error": "reply token expired and no user_id for push fallback", "reply_response": result}
        push_result = _post_json(
            LINE_PUSH_API,
            {"to": user_id, "messages": messages},
            token,
        )
        return {"success": not push_result.get("error", False), "method": "push", "response": push_result}
    return {"success": not result.get("error", False), "method": "reply", "response": result}


def main() -> None:
    try:
        token = get_access_token()
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

    if not reply_token and not user_id:
        print(json.dumps({"success": False, "error": "reply_token or user_id required"}))
        sys.exit(1)

    if not messages:
        print(json.dumps({"success": False, "error": "messages array is empty"}))
        sys.exit(1)

    result = reply_or_push(reply_token, user_id, messages, token)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
