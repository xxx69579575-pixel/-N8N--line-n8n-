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
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            # /api/embed returns {"embeddings": [[...]]}
            embeddings = result.get("embeddings") or result.get("embedding")
            if not embeddings:
                print(f"ERROR: Ollama response missing embeddings key: {list(result.keys())}", file=sys.stderr)
                sys.exit(1)
            # embeddings may be [[...]] or [...]
            if isinstance(embeddings[0], list):
                return embeddings[0]
            return embeddings
    except urllib.error.URLError as e:
        print(f"ERROR: Cannot reach Ollama at {OLLAMA_BASE_URL}: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Vector search
# ---------------------------------------------------------------------------

def vector_search(
    question: str,
    top_k: int = 5,
    min_sim: float = 0.25,
    department: str | None = None,
    file_name: str | None = None,
) -> list[dict]:
    """Return top_k chunks most similar to question."""
    embedding = get_embedding(question)
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 is required. pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )

    try:
        with conn.cursor() as cur:
            # Build dynamic WHERE clause
            conditions = ["1 - (dc.embedding <=> %s::vector) >= %s"]
            params: list = [embedding_str, min_sim]

            if department:
                conditions.append("d.department = %s")
                params.append(department)

            if file_name:
                # Support partial match so user can pass just the filename
                conditions.append("d.file_name ILIKE %s")
                params.append(f"%{file_name}%")

            where_clause = " AND ".join(conditions)

            query = f"""
                SELECT
                    dc.chunk_index,
                    dc.chunk_text,
                    1 - (dc.embedding <=> %s::vector) AS similarity,
                    d.file_name,
                    d.file_path,
                    d.id AS document_id
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE {where_clause}
                ORDER BY dc.embedding <=> %s::vector
                LIMIT %s
            """
            # embedding_str used twice: once for similarity calc, once for ORDER BY
            cur.execute(query, [embedding_str] + params + [embedding_str, top_k])
            rows = cur.fetchall()

            results = []
            for chunk_index, chunk_text, similarity, fname, fpath, doc_id in rows:
                results.append({
                    "document_id": str(doc_id),
                    "file_name": fname,
                    "file_path": fpath,
                    "chunk_index": chunk_index,
                    "similarity": round(float(similarity), 4),
                    "chunk_text": chunk_text,
                })
            return results
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Vector similarity search")
    parser.add_argument("--question", required=True, help="搜尋問題")
    parser.add_argument("--top-k", type=int, default=5, help="回傳筆數 (default: 5)")
    parser.add_argument(
        "--min-sim",
        type=float,
        default=0.25,
        help="最低相似度門檻，0~1 (default: 0.25)。面積計算式 PDF 可嘗試 0.15",
    )
    parser.add_argument("--department", default=None, help="部門篩選")
    parser.add_argument(
        "--file",
        default=None,
        help="依檔名篩選，支援部分比對，例如 --file 面積計算式.pdf",
    )
    args = parser.parse_args()

    results = vector_search(
        question=args.question,
        top_k=args.top_k,
        min_sim=args.min_sim,
        department=args.department,
        file_name=args.file,
    )

    if not results:
        print(
            json.dumps(
                {
                    "message": "找不到符合條件的結果",
                    "hint": (
                        f"請確認：1) 檔案已透過 batch_ingest.py 匯入；"
                        f"2) 嘗試降低 --min-sim（目前 {args.min_sim}）；"
                        f"3) 若 PDF 為掃描圖片，請確認 OCR 已啟用"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
