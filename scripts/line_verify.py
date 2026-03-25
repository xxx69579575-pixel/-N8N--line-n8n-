#!/usr/bin/env python3
"""
LINE Webhook 簽章驗證腳本

stdin JSON 格式：{"body": "<request body string>", "signature": "<X-Line-Signature header value>"}
輸出：{"valid": true} 或 {"valid": false}

使用方式：
  echo '{"body": "...", "signature": "..."}' | LINE_CHANNEL_SECRET=xxx python scripts/line_verify.py
"""

import sys
import json
import hmac
import hashlib
import base64
import os
from pathlib import Path


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


def verify_signature(body: str, signature: str, secret: str) -> bool:
    """用 HMAC-SHA256 驗證 LINE Webhook 簽章"""
    key = secret.encode("utf-8")
    msg = body.encode("utf-8")
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def main() -> None:
    # 1. 嘗試從環境變數取得 LINE_CHANNEL_SECRET
    secret = os.environ.get("LINE_CHANNEL_SECRET")

    # 2. 若無，嘗試從 config/.env 載入
    if not secret:
        env_path = Path(__file__).parent.parent / "config" / ".env"
        load_env_file(str(env_path))
        secret = os.environ.get("LINE_CHANNEL_SECRET")

    if not secret:
        print(json.dumps({"valid": False, "error": "LINE_CHANNEL_SECRET not set"}))
        sys.exit(1)

    # 3. 從 stdin 讀取 JSON
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(json.dumps({"valid": False, "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    body = payload.get("body", "")
    signature = payload.get("signature", "")

    if not signature:
        print(json.dumps({"valid": False, "error": "Missing signature field"}))
        sys.exit(1)

    # 4. 驗證簽章
    result = verify_signature(body, signature, secret)
    print(json.dumps({"valid": result}))


if __name__ == "__main__":
    main()
