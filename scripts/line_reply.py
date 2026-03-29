#!/usr/bin/env python3
"""
line_reply.py — LINE Bot 回覆工具，自動處理 reply token 過期問題

功能：
  1. 嘗試使用 replyToken 呼叫 Reply API
  2. 若 reply token 過期（HTTP 400, property=replyToken），自動 fallback 到 Push API
  3. 從 stdin 讀取 JSON，輸出執行結果至 stdout

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


def send_reply(reply_token: str, user_id: str, messages: list, token: str) -> dict:
    """
    嘗試 Reply API；若 reply token 過期則 fallback 到 Push API。
    回傳 {"method": "reply"|"push"|"failed", "status": int, "body": dict}
    """
    # 1. 嘗試 Reply API
    reply_payload = {"replyToken": reply_token, "messages": messages}
    resp = _post_json(LINE_REPLY_API, reply_payload, token)

    if not resp.get("error"):
        return {"method": "reply", "status": resp["status"], "body": resp["body"]}

    # 2. Reply token 過期 → fallback 到 Push API
    if is_token_expired(resp):
        if not user_id:
            return {
                "method": "failed",
                "status": resp["status"],
                "body": resp["body"],
                "error": "reply token expired and user_id not provided for push fallback",
            }
        push_payload = {"to": user_id, "messages": messages}
        push_resp = _post_json(LINE_PUSH_API, push_payload, token)
        result = {"method": "push", "status": push_resp["status"], "body": push_resp["body"]}
        if push_resp.get("error"):
            result["error"] = True
        return result

    # 3. 其他錯誤（非 token 過期）
    return {
        "method": "failed",
        "status": resp["status"],
        "body": resp["body"],
        "error": True,
    }


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    reply_token = payload.get("reply_token", "")
    user_id = payload.get("user_id", "")
    messages = payload.get("messages", [])

    if not reply_token:
        print(json.dumps({"success": False, "error": "Missing reply_token"}))
        sys.exit(1)

    if not messages:
        print(json.dumps({"success": False, "error": "Missing messages"}))
        sys.exit(1)

    try:
        token = get_access_token()
    except ValueError as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)

    result = send_reply(reply_token, user_id, messages, token)
    success = not result.get("error") and result.get("method") != "failed"
    print(json.dumps({"success": success, **result}))

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
