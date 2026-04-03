你是一位專業的 DevOps 工程師，請按照以下步驟幫助用戶將本地 React + Vite 專案部署到 GitHub Pages。請**依序執行每個步驟**，若有錯誤立即停止並向用戶報告。

---

## 第一階段：前置要求檢查

執行以下所有檢查，並以清單格式向用戶報告結果（✅ 或 ❌）：

1. 檢查 git 是否安裝：`git --version`
2. 檢查 GitHub CLI 是否安裝：`gh --version`
3. 檢查 GitHub CLI 是否已登入：`gh auth status`
4. 檢查 Node.js 是否安裝：`node --version`
5. 檢查 npm 是否安裝：`npm --version`
6. 讀取 `package.json`，確認 `scripts.build` 存在
7. 取得目前登入的 GitHub 用戶名稱：`gh api user --jq .login`，並記住此值為 `GITHUB_USERNAME`

若任何檢查失敗，停止並告知用戶如何修復後再繼續。

---

## 第二階段：建立專業的 README.md

讀取 `package.json`、`src/App.tsx`（如果存在）以及 `CLAUDE.md`（如果存在）來了解專案。

然後**覆寫** `README.md`，內容須包含：
- 專案名稱與一行描述
- 功能亮點（bullet points）
- 技術棧（Tech Stack）
- 本地開發步驟（`npm install` / `npm run dev`）
- 線上 Demo 連結（佔位符：`https://<GITHUB_USERNAME>.github.io/my-project/`，使用真實用戶名替換）
- 授權資訊（MIT）

---

## 第三階段：設定 Vite base path（GitHub Pages 必需）

讀取 `vite.config.ts`，將 `base` 設定為 `/my-project/`。

若 `defineConfig` 中已有 `base` 則更新它，否則新增它。確保最終結果類似：

```ts
export default defineConfig({
  base: '/my-project/',
  // ...其餘原有設定保持不變
})
```

---

## 第四階段：建立 GitHub Actions 自動部署工作流程

建立檔案 `.github/workflows/deploy.yml`，內容如下：

```yaml
name: Deploy to GitHub Pages

on:
  push:
    branches: [main]

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'

      - name: Install dependencies
        run: npm install

      - name: Build
        run: npm run build

      - name: Setup Pages
        uses: actions/configure-pages@v4

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: ./build

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

---

## 第五階段：本地建置驗證

執行 `npm run build`，確認建置成功（`build/` 目錄被建立）。若失敗，報告錯誤給用戶。

---

## 第六階段：初始化 Git 並提交所有變更

依序執行：

1. `git init`（若 `.git` 不存在）
2. 確認 `.gitignore` 存在且包含 `node_modules`。若不存在，建立一個包含以下內容的 `.gitignore`：
   ```
   node_modules/
   build/
   dist/
   .DS_Store
   *.local
   ```
3. `git add README.md vite.config.ts .github/ .gitignore package.json index.html src/`（明確列出重要檔案，避免提交 node_modules）
4. 確認暫存區（`git status`）
5. 執行 commit：
   ```
   git commit -m "feat: initial project setup with GitHub Pages deployment

   - Add React + TypeScript treasure box game
   - Configure Vite base path for GitHub Pages
   - Add GitHub Actions workflow for automated deployment
   - Add professional README with demo link"
   ```

---

## 第七階段：建立 GitHub 公有儲存庫並推送

1. 使用 GitHub CLI 建立公有儲存庫：
   ```bash
   gh repo create my-project --public --description "Interactive Treasure Box Game built with React + TypeScript" --source=. --remote=origin --push
   ```

   若報錯「remote origin already exists」，改用：
   ```bash
   gh repo create my-project --public --description "Interactive Treasure Box Game built with React + TypeScript"
   git remote set-url origin https://github.com/<GITHUB_USERNAME>/my-project.git
   git branch -M main
   git push -u origin main
   ```

2. 確認推送成功：`git log --oneline -3`

---

## 第八階段：啟用 GitHub Pages

執行以下命令啟用 GitHub Pages（使用 GitHub Actions 作為來源）：

```bash
gh api repos/<GITHUB_USERNAME>/my-project/pages \
  --method POST \
  --field build_type=workflow \
  --field source='{"branch":"main","path":"/"}' 2>/dev/null || echo "Pages may already be enabled or will auto-enable on first workflow run"
```

---

## 第九階段：完成報告

向用戶輸出以下資訊：

```
🎉 部署完成！

📦 GitHub 儲存庫：https://github.com/<GITHUB_USERNAME>/my-project
🌐 GitHub Pages URL：https://<GITHUB_USERNAME>.github.io/my-project/

⏳ 注意：GitHub Pages 首次部署需要 1-3 分鐘。
   請前往 https://github.com/<GITHUB_USERNAME>/my-project/actions 查看部署進度。

✅ 部署成功後即可在上方 URL 瀏覽您的專案！
```

所有 `<GITHUB_USERNAME>` 請替換為第一階段取得的真實用戶名稱。
