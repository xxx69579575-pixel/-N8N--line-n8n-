#!/usr/bin/env python3
"""
write_to_db.py — 將文件、切片、embedding 寫入 PostgreSQL

stdin JSON format:
{
  "text": "...",
  "metadata": {"file_name": "...", "file_ext": ".docx", "file_path": "...",
                "file_size": 1234, "hash_sha256": "abc..."},
  "ocr_used": false,
  "page_count": 1,
  "chunks": [{"chunk_index": 0, "chunk_text": "...", "char_count": 100,
               "token_estimate": 33, "embedding": [0.1, 0.2, ...]}]
}
"""

import json
import os
import sys
from pathlib import Path


def _load_dotenv(path: str) -> None:
    """Minimal .env loader — sets os.environ for keys not already set."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass


def _find_dotenv() -> str | None:
    """Look for config/.env relative to this script or cwd."""
    candidates = [
        Path(__file__).parent.parent / "config" / ".env",
        Path.cwd() / "config" / ".env",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


# Load .env on import
_env_path = _find_dotenv()
if _env_path:
    _load_dotenv(_env_path)


def get_db_connection():
    """Return a psycopg2 connection using POSTGRES_* env vars."""
    import psycopg2

    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "65432")),
        dbname=os.environ.get("POSTGRES_DB", "vectordb"),
        user=os.environ.get("POSTGRES_USER", "testuser"),
        password=os.environ.get("POSTGRES_PASSWORD", "testpwd"),
    )


def document_exists(conn, hash_sha256: str):
    """Return document_id (str) if hash already in documents, else None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM documents WHERE hash_sha256 = %s LIMIT 1",
            (hash_sha256,),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None


def log_processing_no_doc(conn, file_name: str, step: str, message: str) -> None:
    """Write processing_logs entry with document_id=NULL (e.g. dedup skipped)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO processing_logs (file_name, step_name, log_level, message)
            VALUES (%s, %s, %s, %s)
            """,
            (file_name, step, "info", message),
        )
    conn.commit()


def insert_document(conn, metadata: dict, ocr_used: bool, page_count: int) -> str:
    """Insert into documents and return new UUID as str."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents
                (file_name, file_ext, file_path, file_size_bytes, hash_sha256,
                 department, ingest_status, parse_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                metadata.get("file_name"),
                metadata.get("file_ext"),
                metadata.get("file_path"),
                metadata.get("file_size"),
                metadata.get("hash_sha256"),
                metadata.get("department", "general"),
                "done",
                "done",
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return str(row[0])


def insert_chunks(conn, document_id: str, chunks: list) -> None:
    """Bulk-insert chunks + embeddings into document_chunks."""
    with conn.cursor() as cur:
        for chunk in chunks:
            embedding = chunk.get("embedding")
            embedding_str = (
                "[" + ",".join(str(v) for v in embedding) + "]" if embedding else None
            )
            cur.execute(
                """
                INSERT INTO document_chunks
                    (document_id, chunk_index, chunk_text, char_count,
                     token_estimate, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector)
                """,
                (
                    document_id,
                    chunk.get("chunk_index"),
                    chunk.get("chunk_text"),
                    chunk.get("char_count"),
                    chunk.get("token_estimate"),
                    embedding_str,
                ),
            )
    conn.commit()


def log_processing(conn, document_id: str, file_name: str, step: str, message: str) -> None:
    """Write processing_logs entry linked to a document."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO processing_logs (document_id, file_name, step_name, log_level, message)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (document_id, file_name, step, "info", message),
        )
    conn.commit()


def main() -> None:
    try:
        import psycopg2  # noqa: F401 — ensure dependency present
    except ImportError:
        print("ERROR: psycopg2 is required. pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON from stdin: {exc}", file=sys.stderr)
        sys.exit(1)

    metadata = data.get("metadata", {})
    ocr_used = data.get("ocr_used", False)
    page_count = data.get("page_count", 1)
    chunks = data.get("chunks", [])
    file_name = metadata.get("file_name", "unknown")
    hash_sha256 = metadata.get("hash_sha256", "")

    conn = get_db_connection()
    try:
        existing_id = document_exists(conn, hash_sha256)
        if existing_id:
            log_processing_no_doc(
                conn,
                file_name,
                "dedup",
                f"Skipped duplicate document (existing id={existing_id})",
            )
            print(json.dumps({"status": "skipped", "document_id": existing_id}))
            return

        doc_id = insert_document(conn, metadata, ocr_used, page_count)
        insert_chunks(conn, doc_id, chunks)
        log_processing(conn, doc_id, file_name, "write_to_db", "Inserted successfully")
        print(json.dumps({"status": "ok", "document_id": doc_id, "chunks": len(chunks)}))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
