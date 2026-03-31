#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api_server.py — Local HTTP API server for n8n workflow integration.

Wraps line_verify.py, vector_search.py, prompt_builder.py as REST endpoints
so n8n HTTP Request nodes can call them (replacing executeCommand nodes which
are not available in n8n 2.12+).

Usage:
    python scripts/api_server.py
    python scripts/api_server.py --port 8765 --host 127.0.0.1

Endpoints:
    GET  /health
    GET  /list-inbox
    GET  /files/<name>
    POST /line-verify      {body, signature}                         -> {valid: bool}
    POST /vector-search    {question, top_k?, min_sim?, department?} -> [{chunk_id,...}]
    POST /search-files     {keyword, file_type?}                     -> {results, count}
    POST /prompt-builder   {question, chunks, history}               -> {system, prompt}
    POST /ingest-file      {file_path, department?}                  -> {success, ...}
    POST /backup-db        {backup_dir?, keep?}                      -> {success, ...}
"""

import sys
import json
import os
import argparse
import subprocess
import traceback
import mimetypes
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _SCRIPT_DIR.parent


def _load_dotenv(path: str) -> None:
    """Minimal .env loader — sets os.environ for keys not already set."""
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


_load_dotenv(str(_PROJECT_ROOT / "config" / ".env"))

FILES_BASE_DIR = os.environ.get("FILES_BASE_DIR", "D:/職安")


class APIHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):  # noqa: A002
        sys.stderr.write(f"[api_server] {self.address_string()} {format % args}\n")
        sys.stderr.flush()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def send_json(self, status: int, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8-sig"))

    def run_script(self, args_list, stdin_data: bytes = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return subprocess.run(
            args_list,
            input=stdin_data,
            capture_output=True,
            cwd=str(_PROJECT_ROOT),
            env=env,
        )

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
        elif self.path == "/list-inbox":
            self._handle_list_inbox()
        elif self.path.startswith("/files/"):
            filename = self.path[7:]  # strip "/files/"
            self._handle_file_download(filename)
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        try:
            data = self.read_json_body()
        except Exception as e:
            self.send_json(400, {"error": f"Invalid JSON body: {e}"})
            return

        try:
            if self.path == "/line-verify":
                self._handle_line_verify(data)
            elif self.path == "/vector-search":
                self._handle_vector_search(data)
            elif self.path == "/prompt-builder":
                self._handle_prompt_builder(data)
            elif self.path == "/search-files":
                self._handle_search_files(data)
            elif self.path == "/ingest-file":
                self._handle_ingest_file(data)
            elif self.path == "/backup-db":
                self._handle_backup_db(data)
            else:
                self.send_json(404, {"error": "Not found"})
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            self.send_json(500, {"error": str(e)})

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _handle_line_verify(self, data: dict):
        """POST /line-verify  {body, signature} -> {valid: bool}"""
        stdin_payload = json.dumps({
            "body": data.get("body", ""),
            "signature": data.get("signature", ""),
        }).encode("utf-8")

        result = self.run_script(
            [sys.executable, str(_SCRIPT_DIR / "line_verify.py")],
            stdin_data=stdin_payload,
        )

        if result.returncode != 0 and not result.stdout.strip():
            self.send_json(500, {"valid": False, "error": result.stderr.decode("utf-8", errors="replace")})
            return

        try:
            out = json.loads(result.stdout.decode("utf-8"))
            self.send_json(200, out)
        except json.JSONDecodeError:
            self.send_json(500, {"valid": False, "error": "line_verify.py returned non-JSON"})

    def _handle_vector_search(self, data: dict):
        """POST /vector-search  {question, top_k?, min_sim?, department?, file_name?} -> {chunks, count}

        Supports optional file_name filter to narrow search to a specific document.
        Default min_sim lowered to 0.3 to reduce false negatives for Chinese embeddings.
        """
        question = data.get("question", "")
        if not question:
            self.send_json(400, {"error": "Missing required field: question"})
            return

        top_k = str(int(data.get("top_k", 5)))
        min_sim = str(float(data.get("min_sim", 0.3)))  # lowered from 0.5: Chinese embeddings typically score lower
        department = str(data.get("department", ""))
        file_name = str(data.get("file_name", ""))

        args = [
            sys.executable, str(_SCRIPT_DIR / "vector_search.py"),
            "--question", question,
            "--top-k", top_k,
            "--min-sim", min_sim,
        ]
        if department:
            args += ["--department", department]
        if file_name:
            args += ["--file", file_name]

        result = self.run_script(args)

        if result.returncode != 0:
            sys.stderr.write(f"[api_server] vector_search error: {result.stderr.decode('utf-8', errors='replace')}\n")
            self.send_json(200, {"chunks": [], "count": 0})
            return

        try:
            chunks = json.loads(result.stdout.decode("utf-8"))
            if not isinstance(chunks, list):
                chunks = []
            self.send_json(200, {"chunks": chunks, "count": len(chunks)})
        except json.JSONDecodeError:
            self.send_json(200, {"chunks": [], "count": 0})

    def _handle_file_download(self, filename: str):
        """GET /files/<filename> — lookup file_path from DB, serve with path-traversal protection."""
        try:
            filename = urllib.parse.unquote(filename, encoding="utf-8")
        except Exception:
            self.send_json(400, {"error": "Invalid URL encoding"})
            return

        if not filename or ".." in filename or "\x00" in filename:
            self.send_json(400, {"error": "Invalid filename"})
            return

        target = None
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=os.environ.get("POSTGRES_HOST", "localhost"),
                port=int(os.environ.get("POSTGRES_PORT", "65432")),
                dbname=os.environ.get("POSTGRES_DB", "vectordb"),
                user=os.environ.get("POSTGRES_USER", "testuser"),
                password=os.environ.get("POSTGRES_PASSWORD", "testpwd"),
            )
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT file_path FROM documents WHERE file_name = %s AND file_path IS NOT NULL LIMIT 1",
                        (filename,),
                    )
                    row = cur.fetchone()
                    if row:
                        target = row[0]
            finally:
                conn.close()
        except Exception as e:
            sys.stderr.write(f"[api_server] DB lookup error: {e}\n")

        if not target:
            base_dir = os.path.abspath(FILES_BASE_DIR)
            candidate = os.path.abspath(os.path.join(base_dir, os.path.basename(filename)))
            if candidate.startswith(base_dir + os.sep) and os.path.isfile(candidate):
                target = candidate

        if target and not os.path.isfile(target):
            inbox_dir = os.environ.get("INGEST_INBOX_DIR", "")
            if inbox_dir:
                processed_root = os.path.join(inbox_dir, "processed")
                search_name = os.path.basename(target)
                for dirpath, _, filenames in os.walk(processed_root):
                    if search_name in filenames:
                        target = os.path.join(dirpath, search_name)
                        break

        if not target or not os.path.isfile(target):
            self.send_json(404, {"error": f"File not found: {filename}"})
            return

        try:
            with open(target, "rb") as f:
                content = f.read()
            encoded_name = urllib.parse.quote(os.path.basename(target), safe="")
            ext = os.path.splitext(target)[1].lower()
            mime_map = {
                ".pdf":  ("application/pdf",  "inline"),
                ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "attachment"),
                ".doc":  ("application/msword", "attachment"),
                ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "attachment"),
                ".xls":  ("application/vnd.ms-excel", "attachment"),
                ".jpg":  ("image/jpeg", "inline"),
                ".jpeg": ("image/jpeg", "inline"),
                ".png":  ("image/png",  "inline"),
            }
            content_type, disposition = mime_map.get(ext, ("application/octet-stream", "attachment"))
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{encoded_name}")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            self.send_json(500, {"error": str(e)})

    def _handle_search_files(self, data: dict):
        """POST /search-files  {keyword, file_type?} -> {results: [{file_name, file_path, download_url}], count}"""
        keyword = data.get("keyword", "")
        if not keyword:
            self.send_json(400, {"error": "Missing required field: keyword"})
            return

        file_type = str(data.get("file_type", "")).lower().strip()
        ext_map = {
            "pdf":  [".pdf"],
            "docx": [".doc", ".docx"],
            "xlsx": [".xls", ".xlsx"],
            "jpg":  [".jpg", ".jpeg"],
        }
        ext_list = ext_map.get(file_type, [])

        try:
            import psycopg2
        except ImportError:
            self.send_json(500, {"error": "psycopg2 not installed"})
            return

        try:
            conn = psycopg2.connect(
                host=os.environ.get("POSTGRES_HOST", "localhost"),
                port=int(os.environ.get("POSTGRES_PORT", "65432")),
                dbname=os.environ.get("POSTGRES_DB", "vectordb"),
                user=os.environ.get("POSTGRES_USER", "testuser"),
                password=os.environ.get("POSTGRES_PASSWORD", "testpwd"),
            )
            try:
                with conn.cursor() as cur:
                    kw_nospace = f"%{keyword.replace(' ', '')}%"
                    if ext_list:
                        ext_clauses = " OR ".join(
                            [f"LOWER(file_name) LIKE %s" for _ in ext_list]
                        )
                        sql = (
                            f"SELECT file_name, file_path FROM documents "
                            f"WHERE replace(file_name, ' ', '') ILIKE %s AND ({ext_clauses}) "
                            f"ORDER BY file_name LIMIT 50"
                        )
                        params = [kw_nospace] + [f"%{ext}" for ext in ext_list]
                        cur.execute(sql, params)
                    else:
                        cur.execute(
                            "SELECT file_name, file_path FROM documents "
                            "WHERE replace(file_name, ' ', '') ILIKE %s "
                            "ORDER BY file_name LIMIT 50",
                            (kw_nospace,),
                        )
                    rows = cur.fetchall()
            finally:
                conn.close()

            _base_url = os.environ.get("API_SERVER_BASE_URL", "").rstrip("/")
            results = [
                {
                    "file_name": row[0],
                    "file_path": row[1],
                    "download_url": f"{_base_url}/files/{urllib.parse.quote(row[0], safe='')}",
                }
                for row in rows
            ]
            self.send_json(200, {"results": results, "count": len(results)})
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            self.send_json(500, {"error": str(e)})

    def _handle_list_inbox(self):
        """GET /list-inbox — scan INGEST_INBOX_DIR (including subfolders as department)."""
        inbox_dir = os.environ.get("INGEST_INBOX_DIR", "")
        if not inbox_dir or not os.path.isdir(inbox_dir):
            self.send_json(200, {"files": [], "count": 0, "inbox_dir": inbox_dir, "warning": "INGEST_INBOX_DIR not set or not found"})
            return

        supported = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".jpg", ".jpeg", ".png"}
        skip_dirs = {"processed", "error"}
        files = []

        for root, dirs, fnames in os.walk(inbox_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

            rel = os.path.relpath(root, inbox_dir)
            if rel == ".":
                department = "general"
            else:
                department = rel.split(os.sep)[0]

            for fname in fnames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in supported:
                    continue
                fpath = os.path.join(root, fname)
                files.append({
                    "file_name": fname,
                    "file_path": fpath,
                    "file_ext": ext,
                    "file_size": os.path.getsize(fpath),
                    "department": department,
                })

        self.send_json(200, {"files": files, "count": len(files), "inbox_dir": inbox_dir})

    def _handle_ingest_file(self, data: dict):
        """POST /ingest-file  {file_path, department?} -> {success, file_name, chunk_count, error?}"""
        import shutil

        file_path = data.get("file_path", "").strip()
        if not file_path:
            self.send_json(400, {"error": "Missing required field: file_path"})
            return
        if not os.path.isfile(file_path):
            self.send_json(404, {"error": f"File not found: {file_path}"})
            return

        department = str(data.get("department", "general"))
        file_name = os.path.basename(file_path)
        inbox_root = os.path.abspath(os.environ.get("INGEST_INBOX_DIR", os.path.join(os.path.dirname(file_path), "..")))
        processed_root = os.path.abspath(os.environ.get("INGEST_PROCESSED_DIR", os.path.join(inbox_root, "processed")))
        error_root = os.path.abspath(os.environ.get("INGEST_ERROR_DIR", os.path.join(inbox_root, "error")))

        try:
            rel_path = os.path.relpath(os.path.abspath(file_path), inbox_root)
        except ValueError:
            rel_path = file_name

        def move_file(dest_root: str):
            try:
                dest_path = os.path.join(dest_root, rel_path)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.move(file_path, dest_path)
            except Exception as mv_err:
                sys.stderr.write(f"[api_server] move error: {mv_err}\n")

        try:
            r1 = self.run_script([sys.executable, str(_SCRIPT_DIR / "extract_text.py"), file_path])
            if r1.returncode != 0:
                raise RuntimeError(f"extract_text failed: {r1.stderr.decode('utf-8', errors='replace')[:300]}")
            extracted = json.loads(r1.stdout.decode("utf-8"))
            if "error" in extracted:
                raise RuntimeError(f"extract_text error: {extracted['error']}")
            text = extracted.get("text", "").strip()
            if not text:
                raise RuntimeError("無法取得文字內容（空白或純圖片 PDF）")
            extracted["metadata"]["department"] = department

            r2 = self.run_script(
                [sys.executable, str(_SCRIPT_DIR / "chunk_text.py"), "--text", text],
            )
            if r2.returncode != 0:
                raise RuntimeError(f"chunk_text failed: {r2.stderr.decode('utf-8', errors='replace')[:300]}")
            chunks = json.loads(r2.stdout.decode("utf-8"))
            if not isinstance(chunks, list) or len(chunks) == 0:
                raise RuntimeError("切片結果為空")

            chunks_bytes = json.dumps(chunks, ensure_ascii=False).encode("utf-8")
            r3 = self.run_script([sys.executable, str(_SCRIPT_DIR / "embed_chunks.py")], stdin_data=chunks_bytes)
            if r3.returncode != 0:
                raise RuntimeError(f"embed_chunks failed: {r3.stderr.decode('utf-8', errors='replace')[:300]}")
            embedded_chunks = json.loads(r3.stdout.decode("utf-8"))

            db_payload = json.dumps({
                "text": text,
                "metadata": extracted["metadata"],
                "ocr_used": extracted.get("ocr_used", False),
                "page_count": extracted.get("page_count", 1),
                "chunks": embedded_chunks,
            }, ensure_ascii=False).encode("utf-8")
            r4 = self.run_script([sys.executable, str(_SCRIPT_DIR / "write_to_db.py")], stdin_data=db_payload)
            if r4.returncode != 0:
                raise RuntimeError(f"write_to_db failed: {r4.stderr.decode('utf-8', errors='replace')[:300]}")
            db_result = json.loads(r4.stdout.decode("utf-8"))

            move_file(processed_root)
            self.send_json(200, {
                "success": True,
                "file_name": file_name,
                "chunk_count": len(embedded_chunks),
                "db_result": db_result,
            })

        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            move_file(error_root)
            self.send_json(200, {
                "success": False,
                "file_name": file_name,
                "error": str(e),
            })

    def _handle_backup_db(self, data: dict):
        """POST /backup-db  {backup_dir?, keep?} -> {success, backup_file, file_size_mb, deleted_old}"""
        backup_dir = str(data.get("backup_dir", "") or os.environ.get("BACKUP_DIR", "D:/智能助理資料庫自動備份"))
        keep = int(data.get("keep", os.environ.get("BACKUP_KEEP", 7)))

        args = [
            sys.executable, str(_SCRIPT_DIR / "backup_db.py"),
            "--backup-dir", backup_dir,
            "--keep", str(keep),
        ]
        result = self.run_script(args)

        try:
            out = json.loads(result.stdout.decode("utf-8"))
            self.send_json(200, out)
        except json.JSONDecodeError:
            self.send_json(500, {
                "success": False,
                "error": result.stderr.decode("utf-8", errors="replace"),
            })

    def _handle_prompt_builder(self, data: dict):
        """POST /prompt-builder  {question, chunks, history} -> {system, prompt}"""
        question = data.get("question", "")
        if not question:
            self.send_json(400, {"error": "Missing required field: question"})
            return

        stdin_payload = json.dumps({
            "question": question,
            "chunks": data.get("chunks", []),
            "history": data.get("history", []),
        }, ensure_ascii=False).encode("utf-8")

        result = self.run_script(
            [sys.executable, str(_SCRIPT_DIR / "prompt_builder.py")],
            stdin_data=stdin_payload,
        )

        if result.returncode != 0 and not result.stdout.strip():
            self.send_json(500, {"error": result.stderr.decode("utf-8", errors="replace")})
            return

        try:
            out = json.loads(result.stdout.decode("utf-8"))
            self.send_json(200, out)
        except json.JSONDecodeError:
            self.send_json(500, {"error": "prompt_builder.py returned non-JSON"})


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Local API server for n8n workflow (replaces executeCommand nodes)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), APIHandler)
    sys.stderr.write(f"[api_server] Listening on http://{args.host}:{args.port}\n")
    sys.stderr.write(f"[api_server] Endpoints: GET /health /list-inbox /files/<name>  POST /line-verify /vector-search /prompt-builder /search-files /ingest-file /backup-db\n")
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[api_server] Shutting down.\n")


if __name__ == "__main__":
    main()
