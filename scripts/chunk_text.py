#!/usr/bin/env python3
"""
chunk_text.py — Split text into overlapping chunks.

Usage:
    python scripts/chunk_text.py --text "..." [--chunk-size 800] [--overlap 150]

Output: JSON array of {chunk_index, chunk_text, char_count, token_estimate}
"""
import argparse
import json
import sys


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[dict]:
    if chunk_size <= 0:
        raise ValueError("--chunk-size must be > 0")
    if overlap < 0:
        raise ValueError("--overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("--overlap must be < --chunk-size")

    chunks = []
    start = 0
    index = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append({
            "chunk_index": index,
            "chunk_text": chunk,
            "char_count": len(chunk),
            "token_estimate": len(chunk) // 3,
        })
        index += 1
        next_start = start + chunk_size - overlap
        if next_start <= start:
            break
        start = next_start

    return chunks


def chunk_pre_split(text: str, chunk_size: int = 800) -> list[dict]:
    """將以 \\n\\n 分隔的段落聚合成 chunks，每個 chunk 盡量逼近 chunk_size。

    用於 extract_text.py 已結構化輸出的情境（OCR 破碎短行、面積計算表等）。
    短段落會被連續聚合，避免破碎 OCR 產生過量小 chunks（如 27KB → 502 chunks
    的退化 case）。超過 chunk_size 的單一大段落獨立成 chunk，避免句子被切斷。
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    cur_text = ""
    cur_index = 0

    for p in paragraphs:
        # 加上這段會超過 chunk_size 且當前 chunk 已有內容 → flush
        if cur_text and len(cur_text) + len(p) + 2 > chunk_size:
            chunks.append({
                "chunk_index": cur_index,
                "chunk_text": cur_text,
                "char_count": len(cur_text),
                "token_estimate": len(cur_text) // 3,
            })
            cur_index += 1
            cur_text = ""
        cur_text = cur_text + "\n\n" + p if cur_text else p

    if cur_text:
        chunks.append({
            "chunk_index": cur_index,
            "chunk_text": cur_text,
            "char_count": len(cur_text),
            "token_estimate": len(cur_text) // 3,
        })

    return chunks


def main():
    parser = argparse.ArgumentParser(description="Split text into overlapping chunks.")
    parser.add_argument("--text", help="Input text to chunk (if omitted, read from stdin)")
    parser.add_argument("--chunk-size", type=int, default=800, help="Characters per chunk (default: 800)")
    parser.add_argument("--overlap", type=int, default=150, help="Overlap characters between chunks (default: 150)")
    parser.add_argument("--pre-chunked", action="store_true",
                        help="Text is already split by \\n\\n; aggregate paragraphs up to --chunk-size")
    args = parser.parse_args()

    # Read from stdin when --text omitted, to avoid Windows command-line length limit
    # (32,768 chars triggers [WinError 206] when caller has large extracted text).
    text = args.text if args.text is not None else sys.stdin.buffer.read().decode("utf-8")

    if args.pre_chunked or "\n\n" in text:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) >= 2:
            chunks = chunk_pre_split(text, args.chunk_size)
        else:
            chunks = chunk_text(text, args.chunk_size, args.overlap)
    else:
        chunks = chunk_text(text, args.chunk_size, args.overlap)

    output = json.dumps(chunks, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
