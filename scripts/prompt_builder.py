#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_builder.py — 組裝 RAG Prompt

stdin JSON:
{
  "question": "使用者的問題",
  "chunks": [{"chunk_text": "...", "file_name": "xxx.docx", "similarity": 0.85}],
  "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
}

stdout JSON:
{"system": "...", "prompt": "..."}
"""

import json
import sys

SYSTEM_PROMPT = """你是企業內部知識問答助理。請根據以下參考資料回答問題。
規則：
1. 只能使用提供的參考資料回答，不得捏造或補充未驗證資訊
2. 若參考資料不足以回答問題，請明確說明「目前知識庫中沒有相關資料」
3. 回答需引用來源文件名稱
4. 使用繁體中文回答"""


def build_prompt(question: str, chunks: list, history: list) -> str:
    parts = []

    # 對話歷史：只取最後 6 筆（3 輪）
    recent_history = history[-6:] if len(history) > 6 else history
    if recent_history:
        parts.append("【對話歷史】")
        for turn in recent_history:
            role_label = "使用者" if turn.get("role") == "user" else "助理"
            parts.append(f"{role_label}：{turn.get('content', '')}")
        parts.append("")

    # 參考資料
    if chunks:
        parts.append("【參考資料】")
        for i, chunk in enumerate(chunks, 1):
            file_name = chunk.get("file_name", "未知來源")
            chunk_text = chunk.get("chunk_text", "")
            parts.append(f"[來源: {file_name}]\n{chunk_text}")
            if i < len(chunks):
                parts.append("")
        parts.append("")
    else:
        parts.append("【參考資料】")
        parts.append("（無相關資料）")
        parts.append("")

    # 當前問題
    parts.append("【問題】")
    parts.append(question)

    return "\n".join(parts)


def main():
    raw = sys.stdin.buffer.read().decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stdout.buffer.write(json.dumps({"error": f"Invalid JSON input: {e}"}, ensure_ascii=False).encode("utf-8"))
        sys.exit(1)

    question = data.get("question", "")
    chunks = data.get("chunks", [])
    history = data.get("history", [])

    if not question:
        sys.stdout.buffer.write(json.dumps({"error": "Missing required field: question"}, ensure_ascii=False).encode("utf-8"))
        sys.exit(1)

    prompt = build_prompt(question, chunks, history)

    result = {
        "system": SYSTEM_PROMPT,
        "prompt": prompt,
    }
    output = json.dumps(result, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
