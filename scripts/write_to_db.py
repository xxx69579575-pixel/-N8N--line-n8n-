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
                (file_name, file_ext, file_path, file_size, file_size_bytes, hash_sha256,
                 storage_type, ingest_status, parse_status, department, confidential_level)
            VALUES (%s, %s, %s, %s, %s, %s, 'filesystem', 'processing', 'pending', %s, %s)
            RETURNING id
            """,
            (
                metadata.get("file_name", ""),
                metadata.get("file_ext", ""),
                metadata.get("file_path", ""),
                metadata.get("file_size"),
                metadata.get("file_size_bytes", metadata.get("file_size")),
                metadata["hash_sha256"],
                metadata.get("department", os.environ.get("DEFAULT_DEPARTMENT", "general")),
                metadata.get("confidential_level", "internal"),
            ),
        )
        doc_id = str(cur.fetchone()[0])
    conn.commit()
    return doc_id


def insert_content(
    conn, document_id: str, text: str, ocr_used: bool, page_count: int
) -> str:
    """Insert into document_contents and return new UUID as str."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document_contents
                (document_id, full_text, text_source, ocr_used, page_count, parse_status, parsed_at)
            VALUES (%s, %s, %s, %s, %s, 'done', NOW())
            RETURNING id
            """,
            (
                document_id,
                text,
                "ocr" if ocr_used else "parsed",
                ocr_used,
                page_count,
            ),
        )
        content_id = str(cur.fetchone()[0])
    conn.commit()
    return content_id


def insert_chunks(conn, document_id: str, content_id: str, chunks: list) -> None:
    """Batch-insert into document_chunks with VECTOR(1024) embeddings."""
    if not chunks:
        return

    rows = []
    for chunk in chunks:
        emb = chunk.get("embedding")
        # Format embedding list as pgvector literal string
        if isinstance(emb, list):
            emb_str = "[" + ",".join(str(v) for v in emb) + "]"
        else:
            emb_str = emb  # already a string

        rows.append(
            (
                document_id,
                content_id,
                chunk["chunk_index"],
                chunk["chunk_text"],
                chunk.get("char_count"),
                chunk.get("token_estimate"),
                chunk.get("page_no"),
                chunk.get("section_title"),
                emb_str,
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO document_chunks
                (document_id, content_id, chunk_index, chunk_text,
                 char_count, token_estimate, page_no, section_title, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
            ON CONFLICT (document_id, chunk_index) DO NOTHING
            """,
            rows,
        )
    conn.commit()


def insert_permissions(conn, document_id: str) -> None:
    """Insert default permission row using env vars."""
    department = os.environ.get("DEFAULT_DEPARTMENT", "general")
    access_level = os.environ.get("DEFAULT_ACCESS_LEVEL", "view")

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document_permissions (document_id, department, access_level)
            VALUES (%s, %s, %s)
            """,
            (document_id, department, access_level),
        )
    conn.commit()


def log_processing(
    conn, document_id: str, step: str, status: str, message: str
) -> None:
    """Write processing_logs entry with document_id."""
    log_level = "error" if status == "error" else "info"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO processing_logs
                (document_id, file_name, step_name, log_level, message)
            VALUES (%s, NULL, %s, %s, %s)
            """,
            (document_id, step, log_level, message),
        )
    conn.commit()


def main() -> None:
    raw = sys.stdin.read()
    data = json.loads(raw)

    text = data.get("text", "")
    metadata = data["metadata"]
    ocr_used = data.get("ocr_used", False)
    page_count = data.get("page_count", 0)
    chunks = data.get("chunks", [])
    file_name = metadata.get("file_name", "")
    hash_sha256 = metadata["hash_sha256"]

    conn = get_db_connection()
    try:
        # 1. Dedup check
        existing_id = document_exists(conn, hash_sha256)
        if existing_id:
            log_processing_no_doc(
                conn,
                file_name,
                "dedup",
                f"skipped: document already exists (id={existing_id})",
            )
            print(
                json.dumps({"status": "skipped", "document_id": existing_id}),
                flush=True,
            )
            return

        # 2. Insert document
        doc_id = insert_document(conn, metadata, ocr_used, page_count)

        # 3. Insert content
        content_id = insert_content(conn, doc_id, text, ocr_used, page_count)

        # 4. Insert chunks
        insert_chunks(conn, doc_id, content_id, chunks)

        # 5. Insert permissions
        insert_permissions(conn, doc_id)

        # 6. Mark ingest_status = 'done'
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET ingest_status='done', parse_status='done' WHERE id=%s",
                (doc_id,),
            )
        conn.commit()

        # 7. Log success
        log_processing(conn, doc_id, "ingest", "success", "Document ingested successfully")

        print(
            json.dumps({"status": "ok", "document_id": doc_id, "chunks": len(chunks)}),
            flush=True,
        )

    except Exception as exc:
        conn.rollback()
        log_processing_no_doc(conn, file_name, "ingest", f"error: {exc}")
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr, flush=True)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
