#!/usr/bin/env python3
"""
vector_search.py — pgvector cosine similarity search for QA.

Usage:
    python scripts/vector_search.py --question "公司請假流程"
    python scripts/vector_search.py --question "..." --top-k 3 --min-sim 0.3 --department HR
    python scripts/vector_search.py --question "面積" --file "面積計算式.pdf" --min-sim 0.2

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
    """Call Ollama /api/embed and return the embedding vector."""
    url = f"{OLLAMA_BASE_URL}/api/embed"
    payload = json.dumps(
        {"model": OLLAMA_EMBED_MODEL, "input": text},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data["embeddings"][0]
    except urllib.error.URLError as e:
        print(f"ERROR: 無法連線至 Ollama ({OLLAMA_BASE_URL}): {e}", file=sys.stderr)
        sys.exit(1)
    except (KeyError, IndexError) as e:
        print(f"ERROR: Ollama 回應格式異常: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# pgvector search
# ---------------------------------------------------------------------------

def search(
    question: str,
    top_k: int = 5,
    min_sim: float = 0.0,
    department: str = None,
    file_name: str = None,
) -> list:
    """Query document_chunks via pgvector cosine similarity."""
    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 is required. pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    embedding = get_embedding(question)
    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )
    try:
        with conn.cursor() as cur:
            # Raise ivfflat probes so filtered queries (e.g. single file) don't miss
            # chunks that fall outside the default probe=1 cluster scan.
            cur.execute("SET LOCAL ivfflat.probes = 10")

            filters = []
            filter_params = []

            if department:
                filters.append("d.department = %s")
                filter_params.append(department)
            if file_name:
                filters.append("d.file_name = %s")
                filter_params.append(file_name)

            where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

            query = f"""
                SELECT
                    dc.chunk_index,
                    dc.chunk_text,
                    d.file_name,
                    d.file_path,
                    1 - (dc.embedding <=> %s::vector) AS similarity
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                {where_clause}
                ORDER BY dc.embedding <=> %s::vector
                LIMIT %s
            """
            params = [embedding_str] + filter_params + [embedding_str, top_k]
            cur.execute(query, params)
            rows = cur.fetchall()

        results = []
        for chunk_index, chunk_text, fname, fpath, similarity in rows:
            if float(similarity) < min_sim:
                continue
            results.append({
                "file_name": fname,
                "file_path": fpath,
                "chunk_index": chunk_index,
                "chunk_text": chunk_text,
                "similarity": round(float(similarity), 4),
            })
        return results
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Vector similarity search")
    parser.add_argument("--question", required=True, help="搜尋問題")
    parser.add_argument("--top-k", type=int, default=5, help="回傳筆數")
    parser.add_argument("--min-sim", type=float, default=0.0, help="最低相似度")
    parser.add_argument("--department", help="部門篩選")
    parser.add_argument("--file", dest="file_name", help="檔名篩選")
    args = parser.parse_args()

    results = search(
        question=args.question,
        top_k=args.top_k,
        min_sim=args.min_sim,
        department=args.department,
        file_name=args.file_name,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
