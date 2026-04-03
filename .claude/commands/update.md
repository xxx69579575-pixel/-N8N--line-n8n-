你是一位 DevOps 工程師，請自動將本專案的變更提交並推送到 GitHub，並同步部署到 Vercel。

## 執行步驟

**第一步：確認有變更**
執行 `git status` 確認有修改過的檔案。若沒有任何變更，直接告知用戶「目前沒有需要上傳的變更」並停止。

**第二步：分析變更內容**
執行 `git diff --stat HEAD` 查看哪些檔案被修改，根據變更內容自動產生合適的 commit message，格式如下：
- 新功能 → `feat: <描述>`
- 修 bug → `fix: <描述>`
- 樣式調整 → `style: <描述>`
- 重構 → `refactor: <描述>`
- 其他 → `chore: <描述>`

**第三步：提交並推送到 GitHub**
依序執行：
```bash
git add .
git commit -m "<自動產生的 commit message>"
git push
```

**第四步：部署到 Vercel**
執行：
```bash
vercel --prod --yes 2>&1
```
等待部署完成，擷取正式環境 URL。

**第五步：完成報告**
回報以下資訊：
- 哪些檔案被上傳
- commit message 是什麼
- GitHub Pages 會自動更新（透過 GitHub Actions）
- Vercel 正式網址
