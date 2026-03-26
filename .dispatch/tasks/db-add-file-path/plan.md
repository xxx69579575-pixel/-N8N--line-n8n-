# 任務三：documents 表加 file_path 欄位

- [ ] 連接 PostgreSQL (localhost:65432, vectordb, testuser/testpwd)，執行 ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_path TEXT, ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT
- [ ] 建立 scripts/update_file_paths.py：掃描指定資料夾，比對 documents.file_name，UPDATE file_path 與 file_size_bytes
- [ ] 執行 update_file_paths.py --dir "D:/職安" 更新現有 36 筆資料
- [ ] 更新 scripts/write_to_db.py：匯入新文件時自動帶入 file_path 與 file_size_bytes
- [ ] 驗證：SELECT file_name, file_path, file_size_bytes FROM documents WHERE file_path IS NOT NULL LIMIT 10，確認欄位有值
- [ ] 寫摘要至 .dispatch/tasks/db-add-file-path/output.md
