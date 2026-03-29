#!/usr/bin/env python3
"""
vector_search.py — pgvector cosine similarity search for QA.

Usage:
    python scripts/vector_search.py --question "公司請假流程"
    python scripts/vector_search.py --question "..." --top-k 3 --min-sim 0.6 --department HR

Embeds the question via Ollama, queries document_chunks with pgvector cosine
similarity, and prints a JSON array of results.

Environment variables (loaded from config/.env if present):
    OLLAMA_BASE_URL    (default: http://localhost:11434)
    OLLAMA_EMBED_MODEL (default: nomic-embed-text)
    POSTGRES_HOST      (default: localhost)
    POSTGRES_PORT      (default: 65432)
    POSTGRES_DB        (default: vectordb)
    POSTGRES_USER      (default: testuser)
    POSTGRES_PASSWORD  (default: testpwd)
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error


# ---------------------------------------------------------------------------
# Config loader — manual .env parse (no external deps)
# ---------------------------------------------------------------------------

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


# Load config/.env relative to this script's project root
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
load_dotenv(os.path.join(_project_root, "config", ".env"))


OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3")
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "65432"))
POSTGRES_DB = os.environ.get("POSTGRES_DB", "vectordb")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "testuser")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "testpwd")


# ---------------------------------------------------------------------------
# Ollama embedding
# ---------------------------------------------------------------------------

def get_embedding(text: str) -> list:
    # Use /api/embed (new API) with "input" key — must match how embed_chunks.py stores vectors
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
            embeddings = result.get("embeddings")
            if embeddings and isinstance(embeddings, list):
                return embeddings[0]
            # fallback for older Ollama /api/embed response shape
            embedding = result.get("embedding")
            if embedding:
                return embedding
            raise ValueError(f"Unexpected Ollama response shape: {list(result.keys())}")
    except urllib.error.URLError as e:
        print(f"ERROR: Cannot reach Ollama at {OLLAMA_BASE_URL} — {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# pgvector search
# ---------------------------------------------------------------------------

def search(question: str, top_k: int = 5, min_sim: float = 0.5, department: str | None = None) -> list:
    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 is required. pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    embedding = get_embedding(question)
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"

    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )

    try:
        with conn.cursor() as cur:
            if department:
                cur.execute(
                    """
                    SELECT
                        dc.chunk_index,
                        dc.chunk_text,
                        d.file_name,
                        d.file_path,
                        1 - (dc.embedding <=> %s::vector) AS similarity
                    FROM document_chunks dc
                    JOIN documents d ON d.id = dc.document_id
                    WHERE d.department = %s
                      AND 1 - (dc.embedding <=> %s::vector) >= %s
                    ORDER BY dc.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vec_str, department, vec_str, min_sim, vec_str, top_k),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        dc.chunk_index,
                        dc.chunk_text,
                        d.file_name,
                        d.file_path,
                        1 - (dc.embedding <=> %s::vector) AS similarity
                    FROM document_chunks dc
                    JOIN documents d ON d.id = dc.document_id
                    WHERE 1 - (dc.embedding <=> %s::vector) >= %s
                    ORDER BY dc.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vec_str, vec_str, min_sim, vec_str, top_k),
                )
            rows = cur.fetchall()
    finally:
        conn.close()

    results = [
        {
            "chunk_index": row[0],
            "chunk_text": row[1],
            "file_name": row[2],
            "file_path": row[3],
            "similarity": float(row[4]),
        }
        for row in rows
    ]
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Vector similarity search")
    parser.add_argument("--question", required=True, help="查詢問題")
    parser.add_argument("--top-k", type=int, default=5, help="回傳前 N 筆結果 (default: 5)")
    parser.add_argument("--min-sim", type=float, default=0.5, help="最低相似度門檻 (default: 0.5)")
    parser.add_argument("--department", default=None, help="限定部門篩選")
    args = parser.parse_args()

    results = search(
        question=args.question,
        top_k=args.top_k,
        min_sim=args.min_sim,
        department=args.department,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
