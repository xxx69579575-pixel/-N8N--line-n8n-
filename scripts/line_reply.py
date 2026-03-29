#!/usr/bin/env python3
"""
line_reply.py — LINE Bot 回覆工具，自動處理 reply token 過期問題

功能：
  1. 嘗試使用 replyToken 呼叫 Reply API
  2. 若 reply token 過期（HTTP 400, property=replyToken），自動 fallback 到 Push API
  3. 從 stdin 讀取 JSON，輸出執行結果至 stdout
  4. 發送前驗證訊息格式，避免 unsupported message type 錯誤

stdin JSON 格式：
{
  "reply_token": "<replyToken from webhook event>",
  "user_id": "<userId, optional, for push fallback>",
  "messages": [
    {"type": "text", "text": "..."},
    {
      "type": "image",
      "originalContentUrl": "https://example.com/image.jpg",
      "previewImageUrl": "https://example.com/preview.jpg"
    }
  ]
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

# 各訊息類型的必要欄位
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "text":     ["text"],
    "image":    ["originalContentUrl", "previewImageUrl"],
    "video":    ["originalContentUrl", "previewImageUrl"],
    "audio":    ["originalContentUrl", "duration"],
    "location": ["title", "address", "latitude", "longitude"],
    "sticker":  ["packageId", "stickerId"],
    "flex":     ["altText", "contents"],
    "template": ["altText", "template"],
}


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


def validate_messages(messages: list) -> list[str]:
    """
    驗證訊息清單中每則訊息的格式。
    回傳錯誤訊息列表；若為空則代表驗證通過。
    """
    errors: list[str] = []
    if not isinstance(messages, list) or len(messages) == 0:
        return ["messages 必須是非空陣列"]

    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            errors.append(f"messages[{idx}] 必須是物件")
            continue

        msg_type = msg.get("type")
        if not msg_type:
            errors.append(f"messages[{idx}] 缺少 type 欄位")
            continue

        required = _REQUIRED_FIELDS.get(msg_type)
        if required is None:
            errors.append(
                f"messages[{idx}] 不支援的訊息類型: '{msg_type}'，"
                f"支援類型: {', '.join(_REQUIRED_FIELDS.keys())}"
            )
            continue

        for field in required:
            if field not in msg or msg[field] is None:
                errors.append(
                    f"messages[{idx}] (type={msg_type}) 缺少必要欄位: '{field}'"
                )

    return errors


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
    # 部分舊版 API 以 message 欄位回傳過期訊息
    message = body.get("message", "")
    return "replyToken" in message and "expired" in message.lower()


def reply_or_push(reply_token: str, user_id: str, messages: list, token: str) -> dict:
    """
    嘗試 Reply API；若 token 過期且有 user_id，fallback 到 Push API。
    回傳最終 API 結果。
    """
    result = _post_json(
        LINE_REPLY_API,
        {"replyToken": reply_token, "messages": messages},
        token,
    )

    if is_token_expired(result):
        if not user_id:
            result["fallback_skipped"] = True
            result["fallback_reason"] = "user_id not provided"
            return result
        result["fallback"] = True
        push_result = _post_json(
            LINE_PUSH_API,
            {"to": user_id, "messages": messages},
            token,
        )
        push_result["used_push_fallback"] = True
        return push_result

    return result


def main() -> None:
    # 1. 取得 access token
    try:
        token = get_access_token()
    except ValueError as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)

    # 2. 從 stdin 讀取 JSON
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    reply_token = payload.get("reply_token", "")
    user_id     = payload.get("user_id", "")
    messages    = payload.get("messages", [])

    # 3. 驗證訊息格式（防止 unsupported message type）
    errors = validate_messages(messages)
    if errors:
        print(json.dumps({"success": False, "validation_errors": errors}))
        sys.exit(1)

    if not reply_token and not user_id:
        print(json.dumps({"success": False, "error": "reply_token or user_id required"}))
        sys.exit(1)

    # 4. 發送訊息
    if reply_token:
        result = reply_or_push(reply_token, user_id, messages, token)
    else:
        result = _post_json(
            LINE_PUSH_API,
            {"to": user_id, "messages": messages},
            token,
        )

    success = result.get("status", 0) in (200, 204) and not result.get("error")
    print(json.dumps({"success": success, **result}))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
