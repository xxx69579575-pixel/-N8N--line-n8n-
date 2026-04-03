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


def chunk_pre_split(text: str) -> list[dict]:
    """將以 \\n\\n 分隔的預切段落各自成一個 chunk（不滑動視窗）。
    用於 extract_text.py 已結構化輸出（如面積計算表每戶一行）的情境。
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return [
        {
            "chunk_index": i,
            "chunk_text": p,
            "char_count": len(p),
            "token_estimate": len(p) // 3,
        }
        for i, p in enumerate(paragraphs)
    ]


def main():
    parser = argparse.ArgumentParser(description="Split text into overlapping chunks.")
    parser.add_argument("--text", required=True, help="Input text to chunk")
    parser.add_argument("--chunk-size", type=int, default=800, help="Characters per chunk (default: 800)")
    parser.add_argument("--overlap", type=int, default=150, help="Overlap characters between chunks (default: 150)")
    parser.add_argument("--pre-chunked", action="store_true",
                        help="Text is already split by \\n\\n; output one chunk per paragraph")
    args = parser.parse_args()

    if args.pre_chunked or "\n\n" in args.text:
        # 若文字含段落分隔，優先用段落切片（面積表等結構化輸出）
        paragraphs = [p.strip() for p in args.text.split("\n\n") if p.strip()]
        if len(paragraphs) >= 2:
            chunks = chunk_pre_split(args.text)
        else:
            chunks = chunk_text(args.text, args.chunk_size, args.overlap)
    else:
        chunks = chunk_text(args.text, args.chunk_size, args.overlap)

    output = json.dumps(chunks, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
