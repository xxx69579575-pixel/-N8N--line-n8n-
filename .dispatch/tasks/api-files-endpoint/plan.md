# 任務二：api_server.py 加 /files 端點

- [ ] 讀取 scripts/api_server.py 了解現有架構（BaseHTTPRequestHandler, port 8765）
- [ ] 新增 GET /files/<filename> 路由：從設定的 FILES_BASE_DIR 讀取檔案回傳，Content-Disposition: attachment，限制路徑穿越攻擊（不允許 ../ 或絕對路徑）
- [ ] 新增 POST /search-files 路由：接收 {keyword}，查詢 documents 表的 file_name 與 file_path，回傳 [{file_name, file_path, download_url}]，download_url 格式為 /files/<file_name>
- [ ] 新增環境變數 FILES_BASE_DIR（預設 D:/職安），從 config/.env 載入
- [ ] 在 do_GET 加入 /files/ 路由分派，在 do_POST 加入 /search-files 路由分派
- [ ] 測試：curl http://localhost:8765/files/勞動法簡介.pdf 能下載，curl -X POST http://localhost:8765/search-files -d '{"keyword":"勞動法"}' 回傳 JSON
- [ ] 寫摘要至 .dispatch/tasks/api-files-endpoint/output.md
