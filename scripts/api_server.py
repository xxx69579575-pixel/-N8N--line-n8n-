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
    POST /line-verify      {body, signature}                         -> {valid: bool}
    POST /vector-search    {question, top_k?, min_sim?, department?} -> [{chunk_id,...}]
    POST /prompt-builder   {question, chunks, history}               -> {system, prompt}
"""

import sys
import json
import os
import argparse
import subprocess
import traceback
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
        """POST /vector-search  {question, top_k?, min_sim?, department?} -> [{...}]"""
        question = data.get("question", "")
        if not question:
            self.send_json(400, {"error": "Missing required field: question"})
            return

        top_k = str(int(data.get("top_k", 5)))
        min_sim = str(float(data.get("min_sim", 0.7)))
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
            args += ["--file-name", file_name]

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
        # URL-decode first
        try:
            filename = urllib.parse.unquote(filename, encoding="utf-8")
        except Exception:
            self.send_json(400, {"error": "Invalid URL encoding"})
            return

        # Block traversal sequences (after decode)
        if not filename or ".." in filename or "\x00" in filename:
            self.send_json(400, {"error": "Invalid filename"})
            return

        # Lookup actual file_path from DB
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

        # Fallback to FILES_BASE_DIR if not in DB
        if not target:
            base_dir = os.path.abspath(FILES_BASE_DIR)
            candidate = os.path.abspath(os.path.join(base_dir, os.path.basename(filename)))
            if candidate.startswith(base_dir + os.sep) and os.path.isfile(candidate):
                target = candidate

        if not target or not os.path.isfile(target):
            self.send_json(404, {"error": f"File not found: {filename}"})
            return

        try:
            with open(target, "rb") as f:
                content = f.read()
            encoded_name = urllib.parse.quote(os.path.basename(target), safe="")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded_name}")
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

        # Optional file type filter: pdf, docx, xlsx, jpg
        file_type = str(data.get("file_type", "")).lower().strip()
        ext_map = {
            "pdf":  [".pdf"],
            "docx": [".doc", ".docx"],
            "xlsx": [".xls", ".xlsx"],
            "jpg":  [".jpg", ".jpeg"],
        }
        ext_list = ext_map.get(file_type, [])

        try:
            import psycopg2  # type: ignore
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
                    # Strip spaces from both keyword and file_name before matching
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

            results = [
                {
                    "file_name": row[0],
                    "file_path": row[1],
                    "download_url": f"/files/{urllib.parse.quote(row[0], safe='')}",
                }
                for row in rows
            ]
            self.send_json(200, {"results": results, "count": len(results)})
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            self.send_json(500, {"error": str(e)})

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
    sys.stderr.write(f"[api_server] Endpoints: GET /health /files/<name>  POST /line-verify /vector-search /prompt-builder /search-files\n")
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[api_server] Shutting down.\n")


if __name__ == "__main__":
    main()
