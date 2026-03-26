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
    except urllib.error.URLError as e:
        print(f"ERROR: Cannot reach Ollama at {url}: {e}", file=sys.stderr)
        sys.exit(1)

    embeddings = result.get("embeddings")
    if not embeddings or not embeddings[0]:
        print(f"ERROR: Unexpected Ollama response: {result}", file=sys.stderr)
        sys.exit(1)
    return embeddings[0]


# ---------------------------------------------------------------------------
# pgvector search (pure-stdlib socket-based psycopg2 alternative)
# ---------------------------------------------------------------------------

def vector_search(embedding: list, top_k: int, min_sim: float, department: str, file_name: str = "") -> list:
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("ERROR: psycopg2 is required. Install with: pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    vec_literal = "[" + ",".join(str(v) for v in embedding) + "]"

    sql = f"""
SELECT
    dc.id        AS chunk_id,
    dc.chunk_text,
    d.file_name,
    1 - (dc.embedding <=> %s::vector) AS similarity
FROM document_chunks dc
JOIN documents d ON dc.document_id = d.id
JOIN document_permissions dp ON dc.document_id = dp.document_id
WHERE 1 - (dc.embedding <=> %s::vector) >= %s
  AND (%s = '' OR dp.department = %s)
  AND (%s = '' OR d.file_name = %s)
ORDER BY dc.embedding <=> %s::vector
LIMIT %s;
"""

    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
        )
    except Exception as e:
        print(f"ERROR: Cannot connect to PostgreSQL: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET ivfflat.probes = 50")
            cur.execute(sql, (
                vec_literal, vec_literal, min_sim,
                department, department,
                file_name, file_name,
                vec_literal, top_k,
            ))
            rows = cur.fetchall()
    except Exception as e:
        print(f"ERROR: Query failed: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)
    finally:
        conn.close()

    results = []
    for row in rows:
        results.append({
            "chunk_id": str(row["chunk_id"]),
            "chunk_text": row["chunk_text"],
            "file_name": row["file_name"],
            "similarity": float(row["similarity"]),
        })
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="pgvector similarity search via Ollama embedding")
    parser.add_argument("--question", required=True, help="Question text to embed and search")
    parser.add_argument("--top-k", type=int, default=5, dest="top_k", help="Number of results (default: 5)")
    parser.add_argument("--min-sim", type=float, default=0.7, dest="min_sim", help="Minimum similarity threshold (default: 0.7)")
    parser.add_argument("--department", default="", help="Filter by department (optional)")
    parser.add_argument("--file-name", default="", dest="file_name", help="Filter by exact file name (optional)")
    args = parser.parse_args()

    print(f"Embedding question with model '{OLLAMA_EMBED_MODEL}'…", file=sys.stderr)
    embedding = get_embedding(args.question)
    print(f"Embedding dimension: {len(embedding)}", file=sys.stderr)

    print(f"Searching top_k={args.top_k} min_sim={args.min_sim} department='{args.department}' file_name='{args.file_name}'…", file=sys.stderr)
    results = vector_search(embedding, args.top_k, args.min_sim, args.department, args.file_name)

    print(f"Found {len(results)} result(s).", file=sys.stderr)
    output = json.dumps(results, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
