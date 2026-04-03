# 文件匯入 Pipeline 驗收結果

**執行日期**: 2026-03-25
**執行環境**: Windows 11 + Python + PostgreSQL（Docker, port 65432）
**Embedding 模型**: nomic-embed-text（768-dim）

---

## ⚠️ 重要前置說明：Embedding 維度不一致問題

- **原始 schema**: `document_chunks.embedding VECTOR(1024)`（為 bge-m3 設計）
- **實際可用模型**: 只有 `nomic-embed-text`（768-dim），bge-m3 未安裝
- **處置**: 驗收前已將 DB schema 修改為 `VECTOR(768)` 以配合可用模型
- **部署建議**: 正式部署前需決定使用哪個 embedding 模型，並統一 schema 維度

---

## 驗收結果總覽

| 案例 | 檔案 | 結果 | 說明 |
|------|------|------|------|
| TC1 | sample.docx | ✅ PASS | Word 文件完整 pipeline 通過 |
| TC2 | sample.xlsx | ✅ PASS | Excel 文件完整 pipeline 通過 |
| TC3 | corrupt.docx | ✅ PASS | 損毀檔案正確觸發錯誤處理 |
| TC4 | sample.docx（重複） | ✅ PASS | 去重機制正確跳過已存在文件 |
| TC5 | sample.pdf | ✅ PASS | PDF 文件完整 pipeline 通過 |

---

## 各案例詳細結果

### TC1 — Word 文件（sample.docx）

- **extract_text.py**: 成功抽取中文文字（21 chars）, ocr_used=false, page_count=1
- **chunk_text.py**: 1 chunk（文字短，單一切片）
- **embed_chunks.py**: 768-dim embedding 生成成功
- **write_to_db.py**: `{"status": "ok", "document_id": "04db511e-65a2-4e52-ad33-f82e7b983a91", "chunks": 1}`
- **DB 驗證**: documents 表有記錄（ingest_status=done），document_chunks 1 筆，embedding 非空
- **結果**: ✅ PASS

### TC2 — Excel 文件（sample.xlsx）

- **extract_text.py**: 成功抽取 Sheet1 表格資料（部門/員工/薪資，65 chars）
- **chunk_text.py**: 1 chunk
- **embed_chunks.py**: 768-dim embedding 生成成功
- **write_to_db.py**: `{"status": "ok", "document_id": "1bc48865-b075-4a7d-b39f-166dd9c3e897", "chunks": 1}`
- **DB 驗證**: 成功寫入，惟文字保留 Sheet 標題前綴 `[Sheet: Sheet1]`
- **結果**: ✅ PASS

### TC3 — 損毀檔案（corrupt.docx）

- **extract_text.py**: 正確偵測無效 ZIP/OOXML，輸出 `{"error": "Package not found at '...corrupt.docx'"}`，exit code=1
- **pipeline 中斷**: extract 失敗後 pipeline 停止，未進入 chunk/embed/write
- **error logging**: 手動模擬 n8n 錯誤處理，writing_logs 有 `(step_name='extract', log_level='error')` 記錄
- **檔案移送**: 成功複製至 `D:/AI_KB/error/corrupt.docx`
- **結果**: ✅ PASS

### TC4 — 去重測試（sample.docx 重複執行）

- **extract_text.py**: 同一檔案，hash_sha256 相同（8f3b34d4a0d0d094...）
- **write_to_db.py**: 偵測到 hash 已存在，輸出 `{"status": "skipped", "document_id": "04db511e-..."}`
- **processing_logs**: 有 `step_name='dedup', log_level='info', message='skipped: document already exists (id=04db511e-...)'`
- **documents 表**: sample.docx 只有 1 筆記錄（無重複）
- **結果**: ✅ PASS

### TC5 — PDF 文件（sample.pdf）

- **extract_text.py**: 成功用 pypdf 抽取文字（65 chars），ocr_used=false
- **chunk_text.py**: 1 chunk
- **embed_chunks.py**: 768-dim embedding 生成成功
- **write_to_db.py**: `{"status": "ok", "document_id": "5f8d1656-ae60-40c1-88ad-3a5d8fb19ef3", "chunks": 1}`
- **結果**: ✅ PASS

---

## 最終 DB 狀態

```
documents (3 rows):
  sample.docx  ingest_status=done  hash=8f3b34d4a0d0
  sample.xlsx  ingest_status=done  hash=2594bebc0ae1
  sample.pdf   ingest_status=done  hash=a292b8e14f46

document_chunks: 3 rows, all embeddings non-null (768-dim)

processing_logs:
  (ingest, info)  sample.docx 寫入成功
  (ingest, info)  sample.xlsx 寫入成功
  (extract, error) corrupt.docx 錯誤
  (dedup, info)   sample.docx 重複跳過
  (ingest, info)  sample.pdf 寫入成功
```

---

## 已知問題與建議

1. **Embedding 維度不一致（已於驗收前修復）**
   - bge-m3 未安裝，原始 VECTOR(1024) schema 無法與 nomic-embed-text(768-dim) 配合
   - 建議: 正式部署前安裝 bge-m3 並還原 VECTOR(1024)，或確認使用 nomic-embed-text 並保持 VECTOR(768)

2. **Windows 編碼問題**
   - 需設定 `PYTHONIOENCODING=utf-8` 才能正確處理中文，否則 Python 在 Windows cp950 環境下會拋出 UnicodeEncodeError
   - 建議: 在 n8n Execute Command node 中加入 `PYTHONIOENCODING=utf-8` 環境變數

3. **corrupt.docx 錯誤記錄機制**
   - extract_text.py 只輸出 JSON error，不自動寫入 processing_logs
   - n8n 工作流需在 extract 失敗後呼叫額外的 logging node 才能記錄至 DB
