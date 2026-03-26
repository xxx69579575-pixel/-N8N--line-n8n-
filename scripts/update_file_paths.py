#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_file_paths.py — 掃描指定資料夾，比對 documents.file_name，
                        更新 file_path 與 file_size_bytes 欄位。

Usage:
    python scripts/update_file_paths.py --dir "D:/職安"
    python scripts/update_file_paths.py --dir "D:/職安" --dry-run
"""
import argparse
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _SCRIPT_DIR.parent


def load_dotenv(path: str) -> None:
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

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "65432"))
POSTGRES_DB = os.environ.get("POSTGRES_DB", "vectordb")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "testuser")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "testpwd")


def main():
    parser = argparse.ArgumentParser(description="Update file_path in documents table")
    parser.add_argument("--dir", required=True, help="資料夾路徑（掃描所有檔案）")
    parser.add_argument("--dry-run", action="store_true", help="只顯示比對結果，不實際更新")
    args = parser.parse_args()

    folder = Path(args.dir)
    if not folder.exists():
        print(f"資料夾不存在: {folder}")
        sys.exit(1)

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 is required. pip install psycopg2-binary")
        sys.exit(1)

    # 建立資料夾內的檔名 → 完整路徑對應表
    file_map = {}
    for f in folder.rglob("*"):
        if f.is_file():
            file_map[f.name] = f

    print(f"資料夾共找到 {len(file_map)} 個檔案")

    conn = psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        dbname=POSTGRES_DB, user=POSTGRES_USER, password=POSTGRES_PASSWORD,
    )

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, file_name FROM documents")
            rows = cur.fetchall()
            print(f"資料庫共有 {len(rows)} 筆文件記錄")

            updated = 0
            not_found = 0

            for doc_id, file_name in rows:
                matched = file_map.get(file_name)
                if matched:
                    file_path = str(matched).replace("\\", "/")
                    file_size = matched.stat().st_size
                    if args.dry_run:
                        print(f"  [DRY] {file_name} → {file_path} ({file_size} bytes)")
                    else:
                        cur.execute(
                            "UPDATE documents SET file_path = %s, file_size_bytes = %s WHERE id = %s",
                            (file_path, file_size, doc_id)
                        )
                    updated += 1
                else:
                    print(f"  [未找到] {file_name}")
                    not_found += 1

            if not args.dry_run:
                conn.commit()
                print(f"\n完成：{updated} 筆更新，{not_found} 筆未找到對應檔案")
            else:
                print(f"\n[DRY RUN] 預計更新 {updated} 筆，{not_found} 筆未找到")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
