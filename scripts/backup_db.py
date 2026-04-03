#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backup_db.py — PostgreSQL 自動備份腳本

透過 docker exec 呼叫容器內的 pg_dump，輸出 .sql 壓縮備份至指定目錄。
保留最近 N 份備份，自動刪除過期舊檔。

Usage:
    python scripts/backup_db.py
    python scripts/backup_db.py --backup-dir "D:/智能助理資料庫自動備份" --keep 7

Output JSON (stdout):
    {
      "success": true,
      "backup_file": "D:/智能助理資料庫自動備份/vectordb_20260326_020000.sql",
      "file_size_mb": 12.3,
      "deleted_old": ["vectordb_20260319_020000.sql"],
      "message": "備份完成"
    }
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _SCRIPT_DIR.parent

DEFAULT_BACKUP_DIR = "D:/智能助理資料庫自動備份"
DEFAULT_KEEP = 7
CONTAINER_NAME = "pg_container"
DB_NAME = "vectordb"
DB_USER = "testuser"


def load_dotenv(path: str):
    try:
        with open(path, encoding="utf-8") as f:
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


load_dotenv(str(_PROJECT_ROOT / "config" / ".env"))


def run_backup(backup_dir: str, keep: int) -> dict:
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"vectordb_{timestamp}.sql")

    db_name = os.environ.get("POSTGRES_DB", DB_NAME)
    db_user = os.environ.get("POSTGRES_USER", DB_USER)
    container = os.environ.get("POSTGRES_CONTAINER", CONTAINER_NAME)

    # Execute pg_dump inside the Docker container
    cmd = [
        "docker", "exec", container,
        "pg_dump",
        "-U", db_user,
        "-d", db_name,
        "--no-password",
        "--format=plain",
        "--encoding=UTF8",
    ]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(cmd, capture_output=True, env=env)

    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"pg_dump 失敗（exit {result.returncode}）: {err[:500]}")

    sql_bytes = result.stdout
    if len(sql_bytes) < 100:
        raise RuntimeError("pg_dump 輸出異常（內容過短，可能備份失敗）")

    with open(backup_file, "wb") as f:
        f.write(sql_bytes)

    file_size_mb = round(os.path.getsize(backup_file) / (1024 * 1024), 2)

    # Rotate: keep only the latest N backups
    all_backups = sorted(
        [p for p in Path(backup_dir).glob("vectordb_*.sql")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    deleted_old = []
    for old_file in all_backups[keep:]:
        try:
            old_file.unlink()
            deleted_old.append(old_file.name)
        except Exception:
            pass

    return {
        "success": True,
        "backup_file": backup_file,
        "file_size_mb": file_size_mb,
        "deleted_old": deleted_old,
        "message": f"備份完成，保留最近 {keep} 份",
        "timestamp": timestamp,
        "total_backups": min(len(all_backups), keep),
    }


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL 自動備份")
    parser.add_argument("--backup-dir", default=os.environ.get("BACKUP_DIR", DEFAULT_BACKUP_DIR))
    parser.add_argument("--keep", type=int, default=int(os.environ.get("BACKUP_KEEP", DEFAULT_KEEP)),
                        help="保留備份份數（預設 7 份）")
    args = parser.parse_args()

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        result = run_backup(args.backup_dir, args.keep)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e),
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
