#!/usr/bin/env python3
"""
embed_chunks.py — Add Ollama embeddings to a JSON array of chunks.

Usage:
    cat chunks.json | python scripts/embed_chunks.py
    echo '[{"chunk_index":0,"chunk_text":"..."}]' | python scripts/embed_chunks.py

Reads JSON array from stdin, calls Ollama /api/embed for each chunk,
adds an "embedding" field, and writes the updated array to stdout.

Environment variables:
    OLLAMA_BASE_URL    (default: http://localhost:11434)
    OLLAMA_EMBED_MODEL (default: nomic-embed-text)
"""
import json
import os
import sys
import urllib.request
import urllib.error


OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")


def embed_text(text: str) -> list[float]:
    # Ollama ≥0.1.x uses /api/embeddings with {"model":..., "prompt":...}
    # Response: {"embedding": [...]}
    url = f"{OLLAMA_BASE_URL}/api/embeddings"
    payload = json.dumps({"model": OLLAMA_EMBED_MODEL, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"ERROR: Cannot reach Ollama at {url}: {e}", file=sys.stderr)
        sys.exit(1)

    embedding = result.get("embedding")
    if not embedding:
        print(f"ERROR: Unexpected Ollama response: {result}", file=sys.stderr)
        sys.exit(1)
    return embedding


def main():
    raw = sys.stdin.buffer.read()
    try:
        chunks = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(chunks, list):
        print("ERROR: Input must be a JSON array of chunk objects", file=sys.stderr)
        sys.exit(1)

    for i, chunk in enumerate(chunks):
        text = chunk.get("chunk_text", "")
        print(f"Embedding chunk {i} ({len(text)} chars)…", file=sys.stderr)
        chunk["embedding"] = embed_text(text)

    output = json.dumps(chunks, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
