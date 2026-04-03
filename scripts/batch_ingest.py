#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_ingest.py — 批次匯入資料夾內所有文件至 PostgreSQL + pgvector

Usage:
    python scripts/batch_ingest.py --dir D:/職安 --department safety
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()

SUPPORTED_EXT = {".pdf", ".docx", ".xlsx", ".xls", ".jpg", ".jpeg", ".png"}

def run(args_list, stdin_bytes=None, label=""):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    r = subprocess.run(
        args_list,
        input=stdin_bytes,
        capture_output=True,
        cwd=str(_SCRIPT_DIR.parent),
        env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"{label} failed:\n{r.stderr.decode('utf-8', errors='replace')[:500]}")
    return r.stdout

def ingest_file(file_path: Path, department: str) -> dict:
    py = sys.executable

    # Step 1: extract text
    print(f"  [1/4] 抽取文字...")
    raw = run([py, str(_SCRIPT_DIR / "extract_text.py"), str(file_path)], label="extract_text")
    extracted = json.loads(raw.decode("utf-8"))
    if "error" in extracted:
        raise RuntimeError(f"extract_text error: {extracted['error']}")

    text = extracted.get("text", "")
    if not text.strip():
        raise RuntimeError("無法取得文字內容（可能為純圖片 PDF，需 OCR）")

    # Inject department into metadata
    extracted["metadata"]["department"] = department

    # Step 2: chunk text
    print(f"  [2/4] 切片 ({len(text)} 字)...")
    raw_chunks = run(
        [py, str(_SCRIPT_DIR / "chunk_text.py"), "--text", text, "--chunk-size", "800", "--overlap", "150"],
        label="chunk_text"
    )
    chunks = json.loads(raw_chunks.decode("utf-8"))
    print(f"         產生 {len(chunks)} 個 chunk")

    # Step 3: embed
    print(f"  [3/4] 產生 embedding ({len(chunks)} chunks)...")
    raw_embedded = run(
        [py, str(_SCRIPT_DIR / "embed_chunks.py")],
        stdin_bytes=raw_chunks,
        label="embed_chunks"
    )
    embedded_chunks = json.loads(raw_embedded.decode("utf-8"))

    # Step 4: write to DB
    print(f"  [4/4] 寫入資料庫...")
    payload = {
        "text": extracted.get("text", ""),
        "metadata": extracted.get("metadata", {}),
        "ocr_used": extracted.get("ocr_used", False),
        "page_count": extracted.get("page_count", 1),
        "chunks": embedded_chunks,
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    raw_result = run(
        [py, str(_SCRIPT_DIR / "write_to_db.py")],
        stdin_bytes=payload_bytes,
        label="write_to_db"
    )
    result = json.loads(raw_result.decode("utf-8"))
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="要匯入的資料夾路徑")
    parser.add_argument("--department", default="general", help="部門名稱標籤（預設 general）")
    args = parser.parse_args()

    folder = Path(args.dir)
    if not folder.exists():
        print(f"資料夾不存在: {folder}")
        sys.exit(1)

    files = sorted([f for f in folder.iterdir() if f.suffix.lower() in SUPPORTED_EXT])
    print(f"找到 {len(files)} 個檔案，開始匯入...\n")

    ok, skip, fail = [], [], []

    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {f.name}")
        try:
            result = ingest_file(f, args.department)
            status = result.get("status", "?")
            if status == "skipped":
                print(f"  => 略過（已存在，hash 相同）\n")
                skip.append(f.name)
            else:
                doc_id = result.get("document_id", "?")
                chunks = result.get("chunks_written", "?")
                print(f"  => OK | doc_id={doc_id} | chunks={chunks}\n")
                ok.append(f.name)
        except Exception as e:
            print(f"  => 失敗: {e}\n")
            fail.append((f.name, str(e)))

    print("=" * 60)
    print(f"完成: {len(ok)} 成功 | {len(skip)} 略過 | {len(fail)} 失敗")
    if fail:
        print("\n失敗清單:")
        for name, err in fail:
            print(f"  {name}: {err[:100]}")

if __name__ == "__main__":
    main()
