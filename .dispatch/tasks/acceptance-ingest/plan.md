# Task 6: 文件匯入流程驗收

- [x] 驗收案例 1 — Word 文件：複製 test_data/sample.docx 至 D:/AI_KB/inbox/，執行完整 pipeline（extract → chunk → embed → write），確認 documents 表有記錄、document_chunks 有切片且 embedding 非空
  - PASS: doc_id=04db511e, 1 chunk, 768-dim embedding, ingest_status=done
  - 注意: nomic-embed-text(768-dim)，schema 已修改為 VECTOR(768)（原 VECTOR(1024) 與可用模型不符）
- [x] 驗收案例 2 — Excel 文件：用 openpyxl 建立 test_data/sample.xlsx（含 Sheet1 數行資料），複製至 inbox，執行完整 pipeline，確認寫入成功
  - PASS: doc_id=1bc48865, 1 chunk, Sheet1 表格資料正確抽取（部門/員工/薪資）
- [x] 驗收案例 3 — 損毀檔案：建立 test_data/corrupt.docx（內容為亂碼），複製至 inbox，確認移至 D:/AI_KB/error/ 且 processing_logs 有 status='error' 記錄
  - PASS: extract_text.py 正確回傳 error JSON + exit code 1；processing_logs 有 log_level='error' 記錄（step_name='extract'）；檔案已複製至 D:/AI_KB/error/
- [x] 驗收案例 4 — 去重測試：重新執行 sample.docx（已在案例 1 寫入），確認 processing_logs 有 step_name='dedup', status='skipped' 記錄，documents 表無重複記錄
  - PASS: write_to_db.py 回傳 {"status":"skipped"}；processing_logs 有 dedup/skipped 記錄；documents 只有 1 筆 sample.docx
- [x] 驗收案例 5 — PDF 文件（有文字）：用 fpdf2 建立 test_data/sample.pdf（含一行中英文），執行 pipeline，確認寫入成功
  - PASS: doc_id=5f8d1656, pypdf 抽取文字成功（ocr_used=false），1 chunk, ingest_status=done
- [x] 整理驗收結果，回報各案例 pass/fail 及數據
  - 全部 5 案例 PASS；output.md 已寫入；已知問題：embedding 維度不一致需部署前確認、Windows 需 PYTHONIOENCODING=utf-8
