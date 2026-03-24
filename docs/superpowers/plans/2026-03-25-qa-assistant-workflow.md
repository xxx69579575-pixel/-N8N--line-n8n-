# QA Assistant Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 LINE + n8n + Qwen2.5 的 RAG 企業問答助理，使用者透過 LINE 提問，系統從 pgvector 檢索最相關 chunk 後由 Qwen2.5 生成回答，回傳至 LINE。

**Architecture:** n8n 作為流程引擎，接收 LINE Webhook 後依序：驗證簽章 → 查使用者權限 → 取對話記憶 → query embedding → pgvector 檢索 → Prompt 組裝 → Qwen2.5 生成 → LINE 回覆 → 寫 QA log。本計畫依賴 Document Ingest Pipeline 計畫已完成（知識庫已有資料）。

**Tech Stack:** n8n, LINE Messaging API, Ollama (Qwen2.5 + embedding model), PostgreSQL + pgvector, Python (輔助腳本), ngrok (本地 webhook 暴露)

**前置條件:** `2026-03-25-document-ingest-pipeline.md` 已完成，`sql/01_schema.sql` 已執行（含 qa_logs 與 conversation_sessions 表）

---

## File Structure

```
本地AI企業問答助理/
├── scripts/
│   ├── line_verify.py          # LINE 簽章驗證
│   ├── vector_search.py        # pgvector 相似度查詢
│   └── prompt_builder.py       # Prompt 組裝
├── workflows/
│   └── qa_workflow.json        # n8n 問答工作流匯出
└── docs/
    └── line_setup.md           # LINE Developer Console 設定說明
```

---

## Task 0: LINE Developer Console 設定與 Webhook 暴露

- [ ] **Step 0-1: 啟動 ngrok 暴露本地 n8n**

```bash
# 安裝 ngrok（若尚未安裝）
winget install Ngrok.Ngrok

# 啟動（n8n 預設跑在 5678）
ngrok http 5678
```

記下輸出的 `https://xxxxx.ngrok-free.app` URL。

- [ ] **Step 0-2: 設定 LINE Webhook URL**

前往 [LINE Developers Console](https://developers.line.biz/)：
1. 選擇或新建 Provider > Messaging API Channel
2. 進入 Messaging API 頁籤
3. Webhook URL 填入：`https://xxxxx.ngrok-free.app/webhook/line-qa`
4. 開啟「Use webhook」
5. 記下 Channel Access Token 與 Channel Secret

- [ ] **Step 0-3: 將 LINE 憑證存入 config/.env**

```bash
echo "LINE_CHANNEL_ACCESS_TOKEN=your_token_here" >> config/.env
echo "LINE_CHANNEL_SECRET=your_secret_here" >> config/.env
```

---

## Task 1: LINE 簽章驗證腳本

**Files:**
- Create: `scripts/line_verify.py`

- [ ] **Step 1-1: 建立 line_verify.py**

```python
#!/usr/bin/env python3
"""
LINE Webhook 簽章驗證
用法: echo '{"body":"...","signature":"..."}' | python line_verify.py
輸出: {"valid": true} 或 {"valid": false}
"""
import sys
import json
import hmac
import hashlib
import base64
import os

def verify_signature(body: str, signature: str, secret: str) -> bool:
    hash_bytes = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    expected = base64.b64encode(hash_bytes).decode("utf-8")
    return hmac.compare_digest(expected, signature)

def main():
    data = json.loads(sys.stdin.read())
    secret = os.getenv("LINE_CHANNEL_SECRET", "")
    valid = verify_signature(data["body"], data["signature"], secret)
    print(json.dumps({"valid": valid}))

if __name__ == "__main__":
    main()
```

- [ ] **Step 1-2: 驗證簽章邏輯**

```bash
# 產生一個正確簽章測試
python -c "
import hmac, hashlib, base64, json
secret = 'test_secret'
body = 'test_body'
sig = base64.b64encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()).decode()
print(json.dumps({'body': body, 'signature': sig}))
" | LINE_CHANNEL_SECRET=test_secret python scripts/line_verify.py
```

預期：`{"valid": true}`

- [ ] **Step 1-3: 測試錯誤簽章被拒絕**

```bash
echo '{"body":"test_body","signature":"wrong_sig"}' | LINE_CHANNEL_SECRET=test_secret python scripts/line_verify.py
```

預期：`{"valid": false}`

- [ ] **Step 1-4: Commit**

```bash
git add scripts/line_verify.py
git commit -m "feat: add LINE webhook signature verification script"
```

---

## Task 2: pgvector 相似度查詢腳本

**Files:**
- Create: `scripts/vector_search.py`

- [ ] **Step 2-1: 建立 vector_search.py**

```python
#!/usr/bin/env python3
"""
pgvector 相似度查詢
用法: python vector_search.py --question "公司請假流程" --top-k 5 --min-sim 0.7
輸出: JSON array of matching chunks with similarity score
"""
import sys
import json
import os
import argparse
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "65432")),
        dbname=os.getenv("POSTGRES_DB", "vectordb"),
        user=os.getenv("POSTGRES_USER", "testuser"),
        password=os.getenv("POSTGRES_PASSWORD", "testpwd")
    )

def embed_query(text: str) -> list:
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": text},
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]

def search(question: str, top_k: int = 5, min_similarity: float = 0.7,
           department: str = None) -> list:
    query_vec = embed_query(question)
    vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"

    dept_filter = "AND d.department = %(department)s" if department else ""

    sql = f"""
        SELECT
            dc.id::text AS chunk_id,
            dc.chunk_text,
            dc.chunk_index,
            dc.page_no,
            dc.section_title,
            d.file_name,
            d.department,
            1 - (dc.embedding <=> %(vec)s::vector) AS similarity
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE d.ingest_status = 'done'
        {dept_filter}
        AND 1 - (dc.embedding <=> %(vec)s::vector) >= %(min_sim)s
        ORDER BY dc.embedding <=> %(vec)s::vector
        LIMIT %(top_k)s
    """

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, {"vec": vec_str, "min_sim": min_similarity,
                              "top_k": top_k, "department": department})
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-sim", type=float, default=0.7)
    parser.add_argument("--department", default=None)
    args = parser.parse_args()

    results = search(args.question, args.top_k, args.min_sim, args.department)
    print(json.dumps(results, ensure_ascii=False, default=str))

if __name__ == "__main__":
    main()
```

- [ ] **Step 2-2: 驗證查詢（需知識庫已有資料）**

```bash
# 先確認 document_chunks 有資料
psql -h localhost -p 65432 -U testuser -d vectordb -c "SELECT count(*) FROM document_chunks WHERE embedding IS NOT NULL;"

# 執行查詢
python scripts/vector_search.py --question "測試文件" --top-k 3 --min-sim 0.5
```

預期：輸出包含 chunk_text 與 similarity 的 JSON array

- [ ] **Step 2-3: 測試查無資料情境**

```bash
python scripts/vector_search.py --question "完全不相關的外星語zxqwerty123" --top-k 3 --min-sim 0.9
```

預期：輸出空陣列 `[]`

- [ ] **Step 2-4: Commit**

```bash
git add scripts/vector_search.py
git commit -m "feat: add pgvector similarity search script with permission filter"
```

---

## Task 3: Prompt 組裝腳本

**Files:**
- Create: `scripts/prompt_builder.py`

- [ ] **Step 3-1: 建立 prompt_builder.py**

```python
#!/usr/bin/env python3
"""
組裝 RAG Prompt
用法: python prompt_builder.py --question "..." --chunks '[...]' --history '[...]'
輸出: JSON { "prompt": "...", "system": "..." }
"""
import sys
import json
import argparse

SYSTEM_PROMPT = """你是一個企業內部知識問答助理。
規則：
1. 只能根據以下提供的參考內容回答，不得自行補充未在內容中出現的資訊。
2. 若參考內容不足以回答問題，必須明確說明「目前知識庫沒有足夠資訊」。
3. 不得捏造任何公司政策、條款或數字。
4. 回答需簡潔，優先條列重點。
5. 若有多個參考來源，可在答案末標示來源文件名稱。"""

def build_prompt(question: str, chunks: list, history: list) -> dict:
    context_parts = []
    for i, chunk in enumerate(chunks):
        source = chunk.get("file_name", "未知文件")
        context_parts.append(f"[參考{i+1} 來源:{source}]\n{chunk['chunk_text']}")

    context = "\n\n".join(context_parts) if context_parts else "（無相關內容）"

    history_text = ""
    if history:
        turns = []
        for turn in history[-3:]:  # 最多帶 3 輪
            turns.append(f"使用者：{turn.get('question','')}")
            turns.append(f"助理：{turn.get('answer','')}")
        history_text = "\n".join(turns) + "\n\n"

    user_prompt = f"""{history_text}參考內容：
{context}

使用者問題：{question}

請根據以上參考內容回答："""

    return {"system": SYSTEM_PROMPT, "prompt": user_prompt}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    parser.add_argument("--chunks", required=True)
    parser.add_argument("--history", default="[]")
    args = parser.parse_args()

    chunks = json.loads(args.chunks)
    history = json.loads(args.history)
    result = build_prompt(args.question, chunks, history)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

- [ ] **Step 3-2: 驗證 Prompt 組裝**

```bash
python scripts/prompt_builder.py \
  --question "公司請假規定是什麼" \
  --chunks '[{"chunk_text":"員工每年享有15天特休假","file_name":"員工手冊.xlsx"}]' \
  --history '[]'
```

預期：輸出包含 SYSTEM_PROMPT 規則與參考內容的 JSON

- [ ] **Step 3-3: 驗證多輪對話帶入**

```bash
python scripts/prompt_builder.py \
  --question "那加班費怎麼算" \
  --chunks '[{"chunk_text":"加班費依勞基法計算","file_name":"薪資規定.docx"}]' \
  --history '[{"question":"請假規定","answer":"每年15天特休"}]'
```

預期：prompt 中出現上一輪的對話記錄

- [ ] **Step 3-4: Commit**

```bash
git add scripts/prompt_builder.py
git commit -m "feat: add RAG prompt builder with conversation history support"
```

---

## Task 4: n8n 問答工作流

**Files:**
- Create: `workflows/qa_workflow.json`

- [ ] **Step 4-1: 在 n8n 中建立 Webhook 節點**

新建 Workflow，命名為 `LINE QA Assistant`。

新增 Webhook 節點：
- HTTP Method: POST
- Path: `line-qa`
- Response Mode: Last Node

- [ ] **Step 4-2: 新增簽章驗證節點**

新增 Execute Command 節點：

```bash
echo '{"body":"{{ $json.rawBody }}","signature":"{{ $json.headers["x-line-signature"] }}"}' | python scripts/line_verify.py
```

新增 IF 節點，若 `valid` = false 則停止（回傳 200 空回應，不給 LINE 報錯）。

- [ ] **Step 4-3: 新增訊息解析節點（Code）**

```javascript
const events = $input.all()[0].json.body.events || [];
const textEvent = events.find(e => e.type === 'message' && e.message.type === 'text');
if (!textEvent) return [{ json: { skip: true } }];
return [{
  json: {
    userId: textEvent.source.userId,
    replyToken: textEvent.replyToken,
    question: textEvent.message.text,
    timestamp: textEvent.timestamp
  }
}];
```

- [ ] **Step 4-4: 建立 allowed_users 表並新增使用者驗證節點**

先在 PostgreSQL 建立白名單表（執行一次即可）：

```sql
CREATE TABLE IF NOT EXISTS allowed_users (
    line_user_id TEXT PRIMARY KEY,
    display_name TEXT,
    department TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- 測試時先插入自己的 LINE userId（從 n8n webhook log 取得）
INSERT INTO allowed_users (line_user_id, display_name) VALUES ('Uxxxxxxxxxxxxxxxx', 'test_user');
```

在 n8n 新增 PostgreSQL 節點，查詢白名單：

```sql
SELECT line_user_id FROM allowed_users WHERE line_user_id = '{{ $json.userId }}'
```

新增 IF 節點：若查無結果，直接使用 LINE Reply API 回覆 `您尚未獲授權使用此服務，請洽管理者。` 並停止流程。若有結果則繼續。

- [ ] **Step 4-5: 新增對話記憶查詢節點（PostgreSQL）**

```sql
SELECT turns FROM conversation_sessions WHERE line_user_id = '{{ $json.userId }}'
```

若無記錄則 turns 為空陣列。

- [ ] **Step 4-6: 新增向量查詢節點（Execute Command）**

```bash
python scripts/vector_search.py --question "{{ $json.question }}" --top-k {{ $env.QA_TOP_K }} --min-sim {{ $env.QA_MIN_SIMILARITY }}
```

新增 IF 節點：若回傳空陣列，導向「查無資料」回覆分支。

- [ ] **Step 4-7: 新增 Prompt 組裝節點（Execute Command）**

```bash
python scripts/prompt_builder.py \
  --question "{{ $json.question }}" \
  --chunks '{{ $json.chunks_json }}' \
  --history '{{ $json.history_json }}'
```

- [ ] **Step 4-8: 新增 Qwen2.5 生成節點（HTTP Request）**

```
POST http://localhost:11434/api/chat
Body:
{
  "model": "{{ $env.OLLAMA_CHAT_MODEL }}",
  "messages": [
    {"role": "system", "content": "{{ $json.system }}"},
    {"role": "user", "content": "{{ $json.prompt }}"}
  ],
  "stream": false
}
```

- [ ] **Step 4-9: 新增 LINE 回覆節點（HTTP Request）**

```
POST https://api.line.me/v2/bot/message/reply
Headers: Authorization: Bearer {{ $env.LINE_CHANNEL_ACCESS_TOKEN }}
Body:
{
  "replyToken": "{{ $json.replyToken }}",
  "messages": [{"type": "text", "text": "{{ $json.answer }}"}]
}
```

若答案超過 5000 字元，在 Code 節點截斷並加 `...（內容過長，請至管理者查詢完整資訊）`

- [ ] **Step 4-10: 新增對話記憶更新節點（PostgreSQL）**

```sql
INSERT INTO conversation_sessions (line_user_id, turns)
VALUES ('{{ $json.userId }}', '{{ $json.new_turns }}'::jsonb)
ON CONFLICT (line_user_id) DO UPDATE
SET turns = EXCLUDED.turns, updated_at = NOW()
```

turns 最多保留最近 3 輪，在 Code 節點中截斷。

- [ ] **Step 4-11: 新增 QA Log 節點（Code + PostgreSQL）**

先在 Code 節點將 chunk_ids 陣列格式化為 PostgreSQL 合法的 uuid[] 字串：

```javascript
// Code 節點：格式化 chunk IDs 為 PostgreSQL array literal
const chunks = JSON.parse($json.chunks_json || '[]');
const ids = chunks.map(c => c.chunk_id).filter(Boolean);
// 產生 '{uuid1,uuid2}' 格式
const pgArray = ids.length ? `{${ids.join(',')}}` : '{}';
return [{ json: { ...$json, chunk_ids_pg: pgArray } }];
```

再接 PostgreSQL 節點：

```sql
INSERT INTO qa_logs (user_id, question, retrieved_chunk_ids, answer, confidence)
VALUES (
  '{{ $json.userId }}',
  '{{ $json.question }}',
  '{{ $json.chunk_ids_pg }}'::uuid[],
  '{{ $json.answer }}',
  NULL
)
```

- [ ] **Step 4-12: 新增錯誤處理節點**

在任何節點失敗時觸發，使用 LINE Reply API 回覆保底訊息：
`系統暫時無法回應，請稍後再試或洽管理者。`

- [ ] **Step 4-13: 整體測試**

在 LINE 對話中發送「測試文件的內容是什麼」，確認：
1. n8n 工作流被觸發
2. 向量查詢回傳 chunk
3. Qwen2.5 根據 chunk 生成回答
4. LINE 顯示回覆
5. qa_logs 表有新記錄

- [ ] **Step 4-14: 測試查無資料**

發送「外星語 zxqwerty123 是什麼意思」，確認回覆為預設「無足夠資訊」訊息而非胡亂生成。

- [ ] **Step 4-15: 匯出工作流並 Commit**

```bash
# 匯出 workflow JSON 後
git add workflows/qa_workflow.json
git commit -m "feat: add LINE QA assistant n8n workflow with RAG and conversation memory"
```

---

## Task 5: 驗收測試清單

- [ ] **5-1**: LINE 傳入問題 → n8n 成功接收（ngrok log 顯示 200）
- [ ] **5-2**: 簽章錯誤的請求被靜默拒絕（不報 LINE 錯誤）
- [ ] **5-3**: 有資料的問題 → 正確引用 chunk → Qwen2.5 生成回答 → LINE 顯示
- [ ] **5-4**: 查無資料的問題 → 回覆標準「無足夠資訊」訊息
- [ ] **5-5**: 追問（多輪）→ 第二問帶入第一問的對話記憶
- [ ] **5-6**: qa_logs 每次問答都有記錄
- [ ] **5-7**: conversation_sessions 正確保留最近 3 輪、截斷舊輪次

- [ ] **Step 5-8: 建立 docs/line_setup.md**

建立 `docs/line_setup.md`，內容包含：
1. LINE Developer Console 建立 Messaging API Channel 步驟
2. Webhook URL 設定方式（ngrok URL 填入位置截圖說明）
3. Channel Access Token 與 Channel Secret 取得位置
4. ngrok 每次重啟需更新 Webhook URL 的注意事項
5. 如何取得自己的 LINE userId（從 n8n webhook log 讀取）
6. 將 userId 新增至 allowed_users 表的 SQL 指令

- [ ] **Step 5-9: 最終 Commit**

```bash
git add docs/line_setup.md workflows/qa_workflow.json
git commit -m "docs: add LINE setup guide and QA workflow deployment notes"
```

---

## 注意事項

- **ngrok 每次重啟 URL 會變**：每次重啟 ngrok 必須到 LINE Developer Console 更新 Webhook URL
- **Ollama 需先跑起來**：`ollama serve` 後再啟動 n8n
- **LINE 簽章驗證是安全關卡**：若繞過此步，任何人都能偽造 LINE 訊息呼叫工作流
- **qa_logs 的 retrieved_chunk_ids 欄位**：PostgreSQL `uuid[]` 型別，寫入前需確認 chunk ID 為 UUID 格式
