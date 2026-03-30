#!/usr/bin/env python3
"""
api_server.py — n8n REST API bridge (port 8765)

Endpoints:
  POST /vector-search    → runs vector_search.py --question ...
  POST /search-files     → keyword search in inbox/
  POST /prompt-builder   → runs prompt_builder.py via stdin
  POST /line-verify      → runs line_verify.py via stdin
  GET  /files/<name>     → download file from inbox/
  GET  /list-inbox       → list files in inbox/

Environment:
  PORT (default: 8765)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

app = Flask(__name__)

_script_dir = Path(__file__).parent
_project_root = _script_dir.parent
_inbox_dir = _project_root / "inbox"


def _run_script(script_name: str, stdin_data: str = None, args: list = None) -> dict:
    """Run a script in scripts/, capture stdout as JSON."""
    script_path = _script_dir / script_name
    cmd = [sys.executable, str(script_path)] + (args or [])
    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{script_name} exited with code {result.returncode}")
    return json.loads(result.stdout)


@app.post("/vector-search")
def vector_search():
    body = request.get_json(force=True)
    question = body.get("question", "")
    if not question:
        return jsonify({"error": "Missing required field: question"}), 400

    args = ["--question", question]
    if body.get("top_k"):
        args += ["--top-k", str(body["top_k"])]
    if body.get("min_sim"):
        args += ["--min-sim", str(body["min_sim"])]
    if body.get("department"):
        args += ["--department", body["department"]]

    try:
        result = _run_script("vector_search.py", args=args)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/search-files")
def search_files():
    body = request.get_json(force=True)
    keyword = body.get("keyword", "")
    if not keyword:
        return jsonify({"error": "Missing required field: keyword"}), 400

    _inbox_dir.mkdir(parents=True, exist_ok=True)
    matched = [
        f.name
        for f in sorted(_inbox_dir.iterdir())
        if f.is_file() and keyword.lower() in f.name.lower()
    ]
    return jsonify({"keyword": keyword, "results": matched})


@app.post("/prompt-builder")
def prompt_builder():
    body = request.get_json(force=True)
    stdin_data = json.dumps(body, ensure_ascii=False)
    try:
        result = _run_script("prompt_builder.py", stdin_data=stdin_data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/line-verify")
def line_verify():
    body = request.get_json(force=True)
    stdin_data = json.dumps(body, ensure_ascii=False)
    try:
        result = _run_script("line_verify.py", stdin_data=stdin_data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/files/<path:name>")
def download_file(name):
    _inbox_dir.mkdir(parents=True, exist_ok=True)
    file_path = _inbox_dir / name
    if not file_path.exists() or not file_path.is_file():
        abort(404)
    return send_from_directory(str(_inbox_dir), name, as_attachment=True)


@app.get("/list-inbox")
def list_inbox():
    _inbox_dir.mkdir(parents=True, exist_ok=True)
    files = [
        {"name": f.name, "size": f.stat().st_size}
        for f in sorted(_inbox_dir.iterdir())
        if f.is_file()
    ]
    return jsonify({"files": files})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    app.run(host="0.0.0.0", port=port, debug=False)
