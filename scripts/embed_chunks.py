#!/usr/bin/env python3
"""
embed_chunks.py — Add Ollama embeddings to a JSON array of chunks.

Usage:
    cat chunks.json | python scripts/embed_chunks.py
    echo '[{"chunk_index":0,"chunk_text":"..."}]' | python scripts/embed_chunks.py

Reads JSON array from stdin, calls Ollama /api/embed for each chunk,
adds an "embedding" field, and writes the updated array to stdout.

Resilience: chunks that Ollama refuses (HTTP error, empty embedding, NaN values)
are SKIPPED with a warning instead of aborting the entire batch. Output stdout
contains only chunks that successfully got an embedding.

Environment variables:
    OLLAMA_BASE_URL    (default: http://localhost:11434)
    OLLAMA_EMBED_MODEL (default: bge-m3)
"""
import json
import math
import os
import sys
import urllib.request
import urllib.error


OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3")


def embed_text(text: str):
    """Return an embedding list, or None if Ollama can't or won't embed it.

    Returns None for any per-chunk failure mode (HTTP 4xx/5xx, network error,
    empty result, NaN/Inf values). Caller decides how to handle.
    """
    url = f"{OLLAMA_BASE_URL}/api/embed"
    payload = json.dumps({"model": OLLAMA_EMBED_MODEL, "input": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        print(f"  WARN: Ollama HTTP {e.code} for chunk: {body}", file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        # Connection-level error — propagate so caller can fail fast
        # (no point continuing if Ollama is down).
        raise RuntimeError(f"Cannot reach Ollama at {url}: {e}") from e
    except Exception as e:
        print(f"  WARN: unexpected error embedding chunk: {type(e).__name__}: {e}", file=sys.stderr)
        return None

    embeddings = result.get("embeddings")
    if not embeddings or not embeddings[0]:
        print(f"  WARN: Ollama returned empty embeddings for chunk", file=sys.stderr)
        return None

    vec = embeddings[0]
    if any(not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) for v in vec):
        print(f"  WARN: Ollama returned NaN/Inf in embedding (likely corrupt input chunk)", file=sys.stderr)
        return None

    return vec


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

    out = []
    skipped = 0
    try:
        for i, chunk in enumerate(chunks):
            text = chunk.get("chunk_text", "")
            print(f"Embedding chunk {i} ({len(text)} chars)…", file=sys.stderr)
            vec = embed_text(text)
            if vec is None:
                skipped += 1
                continue
            chunk["embedding"] = vec
            out.append(chunk)
    except RuntimeError as e:
        # Connection-level failure: Ollama is unreachable. Fail fast.
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if skipped:
        print(f"Skipped {skipped}/{len(chunks)} chunks that Ollama refused to embed", file=sys.stderr)
    if not out:
        print("ERROR: No chunks successfully embedded", file=sys.stderr)
        sys.exit(1)

    output = json.dumps(out, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
