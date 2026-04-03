# Document Ingest Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立自動文件匯入流程，掃描本地資料夾中的 Word/PDF/Excel/圖片，抽取文字（含 OCR）、切片、向量化，寫入 PostgreSQL + pgvector。

**Architecture:** 以 n8n 為排程與流程引擎，透過 Execute Command 節點呼叫本地 Python/Node 輔助腳本處理文字抽取、切片、Embedding，再由 n8n PostgreSQL 節點寫入資料庫。原始檔留在檔案系統，PostgreSQL 只存 metadata、文字、向量。

**Tech Stack:** n8n, PostgreSQL 15 + pgvector, Docker, Python 3.x (docx2txt, pypdf2, openpyxl, pytesseract), Ollama Embedding API, SHA-256 hash

---

## File Structure

```
本地AI企業問答助理/
├── sql/
│   ├── 01_schema.sql           # 完整 schema（含 qa_logs、conversation_sessions）
│   └── 02_seed_test_data.sql   # 測試用初始資料
├── scripts/
│   ├── extract_text.py         # 文字抽取主程式（Word/PDF/Excel/Image）
│   ├── chunk_text.py           # 切片邏輯
│   ├── embed_chunks.py         # 呼叫 Ollama embedding API
│   └── requirements.txt        # Python 相依套件
├── config/
│   └── .env.example            # 所有環境變數範本
├── workflows/
│   └── ingest_workflow.json    # n8n 工作流匯出檔
├── test_data/
│   ├── sample.docx
│   ├── sample_text.pdf
│   ├── sample_scanned.pdf
│   ├── sample.xlsx
│   └── sample.png
└── docs/
    └── deployment.md           # 部署與操作說明
```

---

## Task 0: 確認並統一 Embedding 維度

**Files:**
- Create: `sql/01_schema.sql`
- Modify: `docker_postgreSQL/init.sql`

- [ ] **Step 0-1: 確認 Ollama embedding 模型維度**

```bash
curl http://localhost:11434/api/embed -d '{"model":"nomic-embed-text","input":"test"}' | python -c "import sys,json; d=json.load(sys.stdin); print(len(d['embeddings'][0]))"
```

預期輸出：`768`（nomic-embed-text）或 `1024`（bge-m3）

- [ ] **Step 0-2: 統一 schema 維度**

根據上一步確認的維度，將 `n8n自動存入資料庫/02_postgresql_schema.sql` 中 `embedding VECTOR(1024)` 改為實際維度。複製到 `sql/01_schema.sql`。

- [ ] **Step 0-3: 補建缺少的兩張表（新增至 sql/01_schema.sql 末尾）**

```sql
CREATE TABLE IF NOT EXISTS qa_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    question TEXT NOT NULL,
    retrieved_chunk_ids UUID[] DEFAULT '{}',
    answer TEXT,
    confidence NUMERIC(3,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    line_user_id TEXT NOT NULL UNIQUE,
    turns JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qa_logs_user_id ON qa_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_conversation_sessions_line_user_id ON conversation_sessions(line_user_id);
```

- [ ] **Step 0-4: 驗證 schema 能正常執行**

```bash
cd "D:/n8n/CLAUDE 實做/本地AI企業問答助理"
docker compose -f docker_postgreSQL/docker-compose.yml up -d
sleep 5
psql -h localhost -p 65432 -U testuser -d vectordb -f sql/01_schema.sql
psql -h localhost -p 65432 -U testuser -d vectordb -c "\dt"
```

預期輸出：列出 7 張表（documents, document_contents, document_chunks, document_permissions, processing_logs, qa_logs, conversation_sessions）

- [ ] **Step 0-5: Commit**

```bash
git add sql/01_schema.sql docker_postgreSQL/
git commit -m "feat: unify embedding dimension and add missing qa_logs/conversation_sessions tables"
```

---

## Task 1: 建立環境設定檔

**Files:**
- Create: `config/.env.example`

- [ ] **Step 1-1: 建立 .env.example**

```bash
cat > config/.env.example << 'EOF'
# 資料夾路徑（Windows 路徑用正斜線）
INGEST_INBOX_DIR=D:/AI_KB/inbox
INGEST_PROCESSING_DIR=D:/AI_KB/processing
INGEST_PROCESSED_DIR=D:/AI_KB/processed
INGEST_ERROR_DIR=D:/AI_KB/error

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=65432
POSTGRES_DB=vectordb
POSTGRES_USER=testuser
POSTGRES_PASSWORD=testpwd

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=qwen2.5
OLLAMA_EMBED_MODEL=nomic-embed-text
EMBEDDING_DIM=768

# 文件匯入
DEFAULT_DEPARTMENT=general
DEFAULT_ACCESS_LEVEL=view

# LINE（問答流程用）
LINE_CHANNEL_ACCESS_TOKEN=
LINE_CHANNEL_SECRET=

# 問答參數
QA_TOP_K=5
QA_MIN_SIMILARITY=0.7
DEFAULT_NO_ANSWER_MESSAGE=目前知識庫沒有足夠資訊，請換句話提問或洽管理者。
EOF
```

- [ ] **Step 1-2: 建立實際執行用的 .env（從 .env.example 複製，不 commit）**

```bash
cp config/.env.example config/.env
```

- [ ] **Step 1-3: 建立四個 inbox 資料夾**

```bash
mkdir -p "D:/AI_KB/inbox" "D:/AI_KB/processing" "D:/AI_KB/processed" "D:/AI_KB/error"
```

- [ ] **Step 1-4: Commit**

```bash
git add config/.env.example
echo "config/.env" >> .gitignore
git add .gitignore
git commit -m "feat: add env config template and inbox folder structure"
```

---

## Task 2: Python 文字抽取腳本

**Files:**
- Create: `scripts/requirements.txt`
- Create: `scripts/extract_text.py`

- [ ] **Step 2-1: 建立 requirements.txt**

```text
python-docx==1.1.2
pypdf==4.3.1
openpyxl==3.1.5
pytesseract==0.3.13
Pillow==10.4.0
pdf2image==1.17.0
python-dotenv==1.0.1
psycopg2-binary==2.9.9
requests==2.32.3
fpdf2==2.7.9
```

- [ ] **Step 2-2: 安裝前置工具（Tesseract + Poppler）**

```bash
# Tesseract OCR（含繁體中文語言包）
winget install UB-Mannheim.TesseractOCR
# 安裝後確認路徑（預設 C:\Program Files\Tesseract-OCR\tesseract.exe）
tesseract --version

# Poppler（pdf2image 的依賴，用於 PDF→圖片轉換）
winget install oschwartz10612.poppler
# 安裝後確認 PATH 包含 poppler bin 目錄（含 pdftoppm.exe）
pdftoppm -v
```

- [ ] **Step 2-3: 安裝 Python 套件**

```bash
cd scripts
pip install -r requirements.txt
```

預期：無錯誤安裝完成。

- [ ] **Step 2-3: 建立 extract_text.py**

```python
#!/usr/bin/env python3
"""
文字抽取主程式
用法: python extract_text.py <file_path>
輸出: JSON { "text": "...", "metadata": {...}, "ocr_used": bool }
"""
import sys
import json
import hashlib
import os
from pathlib import Path

def extract_word(file_path: str) -> dict:
    from docx import Document
    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    tables = []
    for table in doc.tables:
        for row in table.rows:
            tables.append(" | ".join(cell.text.strip() for cell in row.cells))
    text = "\n".join(paragraphs + tables)
    return {"text": text, "ocr_used": False, "page_count": None}

def extract_pdf(file_path: str) -> dict:
    from pypdf import PdfReader
    reader = PdfReader(file_path)
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    text = "\n".join(pages)
    if len(text.strip()) < 50:
        # 掃描型 PDF，走 OCR
        return extract_pdf_ocr(file_path, len(reader.pages))
    return {"text": text, "ocr_used": False, "page_count": len(reader.pages)}

def extract_pdf_ocr(file_path: str, page_count: int) -> dict:
    import pytesseract
    from pdf2image import convert_from_path
    images = convert_from_path(file_path, dpi=200)
    texts = []
    for img in images:
        text = pytesseract.image_to_string(img, lang="chi_tra+eng")
        texts.append(text)
    return {"text": "\n".join(texts), "ocr_used": True, "page_count": len(images)}

def extract_excel(file_path: str) -> dict:
    from openpyxl import load_workbook
    wb = load_workbook(file_path, read_only=True, data_only=True)
    parts = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(c.strip() for c in cells):
                rows.append(" | ".join(cells))
        if rows:
            parts.append(f"[工作表: {sheet_name}]\n" + "\n".join(rows))
    return {"text": "\n\n".join(parts), "ocr_used": False, "page_count": None,
            "sheet_names": wb.sheetnames}

def extract_image(file_path: str) -> dict:
    import pytesseract
    from PIL import Image
    img = Image.open(file_path)
    text = pytesseract.image_to_string(img, lang="chi_tra+eng")
    return {"text": text, "ocr_used": True, "page_count": None}

def calc_hash(file_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: extract_text.py <file_path>"}))
        sys.exit(1)

    file_path = sys.argv[1]
    ext = Path(file_path).suffix.lower()
    stat = os.stat(file_path)

    metadata = {
        "file_name": Path(file_path).name,
        "file_ext": ext,
        "file_path": file_path,
        "file_size": stat.st_size,
        "hash_sha256": calc_hash(file_path),
    }

    try:
        if ext == ".docx":
            result = extract_word(file_path)
        elif ext == ".pdf":
            result = extract_pdf(file_path)
        elif ext in (".xlsx", ".xls"):
            result = extract_excel(file_path)
        elif ext in (".jpg", ".jpeg", ".png"):
            result = extract_image(file_path)
        else:
            result = {"error": f"Unsupported file type: {ext}"}

        result["metadata"] = metadata
        print(json.dumps(result, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"error": str(e), "metadata": metadata}))
        sys.exit(1)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2-4: 驗證腳本可執行（放一份測試 docx 到 test_data/）**

```bash
# 先準備測試檔：建立最小 docx
python -c "
from docx import Document
doc = Document()
doc.add_heading('測試文件', 0)
doc.add_paragraph('這是一段測試文字，用來驗證文字抽取功能。')
doc.save('test_data/sample.docx')
print('test docx created')
"

python scripts/extract_text.py test_data/sample.docx
```

預期輸出：包含 `"text": "測試文件\n這是一段測試文字..."` 的 JSON

- [ ] **Step 2-5: Commit**

```bash
git add scripts/ test_data/sample.docx
git commit -m "feat: add text extraction script for Word/PDF/Excel/Image"
```

---

## Task 3: 切片與 Embedding 腳本

**Files:**
- Create: `scripts/chunk_text.py`
- Create: `scripts/embed_chunks.py`

- [ ] **Step 3-1: 建立 chunk_text.py**

```python
#!/usr/bin/env python3
"""
文字切片
用法: python chunk_text.py --text "..." --chunk-size 800 --overlap 150
輸出: JSON array of { "chunk_index": N, "chunk_text": "...", "char_count": N }
"""
import sys
import json
import argparse

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list:
    chunks = []
    start = 0
    idx = 0
    text = text.strip()
    if not text:
        return []
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({
                "chunk_index": idx,
                "chunk_text": chunk,
                "char_count": len(chunk),
                "token_estimate": len(chunk) // 2  # 中文粗估
            })
            idx += 1
        start += chunk_size - overlap
    return chunks

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--overlap", type=int, default=150)
    args = parser.parse_args()
    result = chunk_text(args.text, args.chunk_size, args.overlap)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

- [ ] **Step 3-2: 驗證切片**

```bash
python scripts/chunk_text.py --text "$(python -c "print('測試內容 ' * 200)")" --chunk-size 300 --overlap 50
```

預期：輸出多個 chunk 的 JSON array，每個 `char_count` 約 300

- [ ] **Step 3-3: 建立 embed_chunks.py**

```python
#!/usr/bin/env python3
"""
呼叫 Ollama embedding API，對每個 chunk 產生向量
用法: echo '[{"chunk_index":0,"chunk_text":"..."}]' | python embed_chunks.py
輸出: 同 input，每個 chunk 新增 "embedding": [float, ...]
"""
import sys
import json
import os
import requests

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

def embed_text(text: str) -> list:
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": text},
        timeout=60
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]

def main():
    chunks = json.loads(sys.stdin.read())
    results = []
    for chunk in chunks:
        try:
            embedding = embed_text(chunk["chunk_text"])
            chunk["embedding"] = embedding
        except Exception as e:
            chunk["embedding"] = None
            chunk["embed_error"] = str(e)
        results.append(chunk)
    print(json.dumps(results, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

- [ ] **Step 3-4: 驗證 Embedding**

```bash
echo '[{"chunk_index":0,"chunk_text":"公司請假流程"}]' | python scripts/embed_chunks.py
```

預期：輸出包含 `"embedding": [0.123, ...]` 的 JSON，向量長度與 Step 0-1 確認的維度一致

- [ ] **Step 3-5: Commit**

```bash
git add scripts/chunk_text.py scripts/embed_chunks.py
git commit -m "feat: add chunking and ollama embedding scripts"
```

---

## Task 4: PostgreSQL 寫入腳本

**Files:**
- Create: `scripts/write_to_db.py`

- [ ] **Step 4-1: 建立 write_to_db.py**

```python
#!/usr/bin/env python3
"""
將文件資料寫入 PostgreSQL
用法: python write_to_db.py --meta '{}' --content '{}' --chunks '[...]'
"""
import sys
import json
import os
import argparse
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "65432")),
        dbname=os.getenv("POSTGRES_DB", "vectordb"),
        user=os.getenv("POSTGRES_USER", "testuser"),
        password=os.getenv("POSTGRES_PASSWORD", "testpwd")
    )

def check_duplicate(conn, hash_sha256: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM documents WHERE hash_sha256 = %s", (hash_sha256,))
        return cur.fetchone() is not None

def insert_document(conn, meta: dict) -> str:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO documents
              (file_name, file_ext, file_path, storage_type, file_size, hash_sha256,
               department, confidential_level, uploaded_by, ingest_status, parse_status)
            VALUES (%s,%s,%s,'filesystem',%s,%s,%s,%s,'system','processing','pending')
            RETURNING id
        """, (
            meta["file_name"], meta["file_ext"], meta["file_path"],
            meta.get("file_size"), meta["hash_sha256"],
            os.getenv("DEFAULT_DEPARTMENT", "general"),
            "internal"
        ))
        return str(cur.fetchone()[0])

def insert_content(conn, doc_id: str, full_text: str, ocr_used: bool, page_count) -> str:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO document_contents
              (document_id, full_text, text_source, ocr_used, page_count, parse_status, parsed_at)
            VALUES (%s,%s,'extract',%s,%s,'done', NOW())
            RETURNING id
        """, (doc_id, full_text, ocr_used, page_count))
        return str(cur.fetchone()[0])

def insert_chunks(conn, doc_id: str, content_id: str, chunks: list):
    with conn.cursor() as cur:
        for chunk in chunks:
            if chunk.get("embedding") is None:
                continue
            embedding_str = "[" + ",".join(str(v) for v in chunk["embedding"]) + "]"
            cur.execute("""
                INSERT INTO document_chunks
                  (document_id, content_id, chunk_index, chunk_text, char_count,
                   token_estimate, embedding, metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s::vector,%s)
                ON CONFLICT (document_id, chunk_index) DO NOTHING
            """, (
                doc_id, content_id,
                chunk["chunk_index"], chunk["chunk_text"],
                chunk.get("char_count"), chunk.get("token_estimate"),
                embedding_str, json.dumps({})
            ))

def insert_permissions(conn, doc_id: str):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO document_permissions (document_id, department, role_name, access_level)
            VALUES (%s, %s, 'all', %s)
        """, (doc_id, os.getenv("DEFAULT_DEPARTMENT", "general"),
              os.getenv("DEFAULT_ACCESS_LEVEL", "view")))

def log_processing(conn, doc_id, step, level, message):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO processing_logs (document_id, step_name, log_level, message)
            VALUES (%s, %s, %s, %s)
        """, (doc_id, step, level, message))

def log_processing_no_doc(conn, file_name, step, level, message):
    """log without a doc_id (e.g., for skipped duplicates where we don't have a UUID)"""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO processing_logs (file_name, step_name, log_level, message)
            VALUES (%s, %s, %s, %s)
        """, (file_name, step, level, message))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta", required=True)
    parser.add_argument("--content", required=True)
    parser.add_argument("--chunks", required=True)
    args = parser.parse_args()

    meta = json.loads(args.meta)
    content = json.loads(args.content)
    chunks = json.loads(args.chunks)

    conn = get_conn()
    try:
        conn.autocommit = False

        if check_duplicate(conn, meta["hash_sha256"]):
            # 寫入 skip log（document_id 為 NULL，用 file_name 記錄）
            log_processing_no_doc(conn, meta["file_name"], "dedup", "info",
                                  f"Skipped duplicate: {meta['hash_sha256'][:12]}...")
            conn.commit()
            print(json.dumps({"status": "skipped", "reason": "duplicate hash"}))
            return

        doc_id = insert_document(conn, meta)
        content_id = insert_content(conn, doc_id, content["text"], content["ocr_used"], content.get("page_count"))
        insert_chunks(conn, doc_id, content_id, chunks)
        insert_permissions(conn, doc_id)

        # 更新 ingest_status
        with conn.cursor() as cur:
            cur.execute("UPDATE documents SET ingest_status='done', parse_status='done' WHERE id=%s", (doc_id,))

        log_processing(conn, doc_id, "ingest", "info", f"Ingested {len(chunks)} chunks")
        conn.commit()
        print(json.dumps({"status": "ok", "doc_id": doc_id, "chunks": len(chunks)}))

    except Exception as e:
        conn.rollback()
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
```

- [ ] **Step 4-2: 端對端測試（用 sample.docx）**

```bash
# 1. 抽文字
EXTRACT=$(python scripts/extract_text.py test_data/sample.docx)
TEXT=$(echo "$EXTRACT" | python -c "import sys,json; d=json.load(sys.stdin); print(d['text'])")
META=$(echo "$EXTRACT" | python -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d['metadata']))")

# 2. 切片
CHUNKS=$(echo "$TEXT" | python -c "import sys; import subprocess; print(subprocess.check_output(['python','scripts/chunk_text.py','--text',sys.stdin.read()]).decode())" 2>/dev/null || python scripts/chunk_text.py --text "$TEXT")

# 3. Embedding
CHUNKS_WITH_EMB=$(echo "$CHUNKS" | python scripts/embed_chunks.py)

# 4. 寫入 DB
CONTENT=$(echo "$EXTRACT" | python -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'text':d['text'],'ocr_used':d.get('ocr_used',False),'page_count':d.get('page_count')}))")
python scripts/write_to_db.py --meta "$META" --content "$CONTENT" --chunks "$CHUNKS_WITH_EMB"
```

預期輸出：`{"status": "ok", "doc_id": "...", "chunks": N}`

- [ ] **Step 4-3: 驗證資料庫內容**

```bash
psql -h localhost -p 65432 -U testuser -d vectordb -c "SELECT file_name, ingest_status, parse_status FROM documents;"
psql -h localhost -p 65432 -U testuser -d vectordb -c "SELECT count(*) FROM document_chunks;"
```

- [ ] **Step 4-4: 測試去重（重複執行同一檔案）**

再次執行 Step 4-2 的所有指令，預期 stdout 輸出：`{"status": "skipped", "reason": "duplicate hash"}`

並驗證 processing_logs 有記錄（document_id 為 NULL，file_name 有值）：

```bash
psql -h localhost -p 65432 -U testuser -d vectordb -c \
  "SELECT file_name, step_name, message FROM processing_logs WHERE step_name='dedup';"
```

預期：出現 `sample.docx` 的 skipped 記錄

- [ ] **Step 4-5: Commit**

```bash
git add scripts/write_to_db.py
git commit -m "feat: add postgresql write script with deduplication and transaction"
```

---

## Task 5: n8n 文件匯入工作流

**Files:**
- Create: `workflows/ingest_workflow.json`

- [ ] **Step 5-1: 在 n8n 中建立工作流，依以下模組順序新增節點**

進入 n8n UI（通常在 `http://localhost:5678`），新建 Workflow，命名為 `Enterprise Doc Ingest`。

依序新增以下節點：

| 節點名稱 | 類型 | 設定重點 |
|---------|------|---------|
| Schedule Trigger | Schedule Trigger | 每 1 分鐘 |
| List Inbox Files | Execute Command | `ls -1 "{{ $env.INGEST_INBOX_DIR }}"` |
| Filter Supported Types | Code | 過濾 .docx/.pdf/.xlsx/.xls/.jpg/.jpeg/.png |
| Move to Processing | Execute Command | `mv "{{ $json.file }}" "{{ $env.INGEST_PROCESSING_DIR }}"` |
| Extract Text | Execute Command | `python scripts/extract_text.py "{{ $json.file }}"` |
| Parse JSON Result | Code | `JSON.parse($input.all()[0].json.stdout)` |
| Chunk Text | Execute Command | `python scripts/chunk_text.py --text "{{ $json.text }}"` |
| Embed Chunks | Execute Command | `python scripts/embed_chunks.py` (stdin from prev) |
| Write to DB | Execute Command | `python scripts/write_to_db.py ...` （去重邏輯在此腳本內，hash 查詢與 skip log 均由 Python 處理，n8n 不需另設 Check Duplicate 節點）|
| Move to Processed | Execute Command | `mv ... processed/`（僅在 Write to DB stdout 含 `"status":"ok"` 時執行；含 `"status":"skipped"` 時同樣移至 processed；`"status":"error"` 則移至 error）|
| Error Handler | Code | 捕捉錯誤，移至 error/，寫 log |

- [ ] **Step 5-2: 設定環境變數至 n8n**

在 n8n Settings > Variables 中新增 `INGEST_INBOX_DIR` 等所有環境變數。

- [ ] **Step 5-3: 手動觸發測試**

將 `test_data/sample.docx` 複製到 inbox，手動執行工作流，確認：
- processed/ 中出現 sample.docx
- `documents` 表有新紀錄

- [ ] **Step 5-4: 匯出 workflow JSON**

在 n8n 中選 Export > Download JSON，存到 `workflows/ingest_workflow.json`。

- [ ] **Step 5-5: Commit**

```bash
git add workflows/ingest_workflow.json
git commit -m "feat: add n8n ingest workflow with schedule trigger and error handling"
```

---

## Task 6: 驗收測試

- [ ] **Step 6-1: Word 驗收**

放入 `test_data/sample.docx` → 確認 documents/document_contents/document_chunks 三張表有對應資料

- [ ] **Step 6-2: 文字型 PDF 驗收**

```bash
# 用 Python 建立測試 PDF
python -c "
from fpdf import FPDF
pdf = FPDF()
pdf.add_page()
pdf.set_font('Arial', size=12)
pdf.cell(200, 10, txt='Test PDF content for ingestion', ln=True)
pdf.output('test_data/sample_text.pdf')
"
```

放入 inbox，確認 ocr_used = false，chunk 正常產生

- [ ] **Step 6-3: Excel 驗收**

```bash
python -c "
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws.title = '員工手冊'
ws.append(['項目', '說明'])
ws.append(['請假天數', '每年15天'])
wb.save('test_data/sample.xlsx')
"
```

確認 sheet_name 被保留在 metadata JSONB 中

- [ ] **Step 6-4: 去重驗收**

重複放入同一個檔案，確認 documents 表不新增第二筆，processing_logs 有 "skipped" 記錄

- [ ] **Step 6-5: 錯誤隔離驗收**

放入一個損毀的 .docx（零位元組），確認：
- 檔案移至 error/
- processing_logs 有 error level 記錄
- 其他檔案處理不受影響

- [ ] **Step 6-6: Commit**

```bash
git add test_data/ docs/deployment.md
git commit -m "test: add acceptance test data and results"
```

---

## 部署說明

詳見 `docs/deployment.md`（需另建）。關鍵前置：
1. `docker compose up -d` 啟動 PostgreSQL
2. `psql ... -f sql/01_schema.sql` 建立 schema
3. `pip install -r scripts/requirements.txt`
4. 設定 n8n 環境變數
5. 匯入 `workflows/ingest_workflow.json`

> **注意**：Tesseract OCR 需獨立安裝：`winget install UB-Mannheim.TesseractOCR`，並確認繁體中文語言包 `chi_tra` 已下載。
