# 依任務複雜度建立 Dispatch Alias 清單

- [x] 讀取 CLAUDE.md，了解專案架構與技術棧
- [x] 讀取 專案任務清單.md，列出所有 Phase 0~4 任務（同步讀取兩份 superpowers/plans 計畫文件）
- [x] 依複雜度分類：haiku（單步驟環境設定/驗收）、sonnet（中等：腳本開發/n8n 節點）、opus（高複雜：跨系統整合/安全設計）
- [x] 為每個可獨立派遣的任務群組撰寫 alias（名稱、model、prompt 說明）
- [x] 將 alias YAML 片段寫入 .dispatch/tasks/build-alias-list/output.md，可直接複製貼入 ~/.dispatch/config.yaml
