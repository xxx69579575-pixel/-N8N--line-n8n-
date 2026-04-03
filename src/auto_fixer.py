"""
Issue → 自動修復 → PR
1. 讀取 GitHub repo 相關檔案
2. 呼叫 Claude API 分析並生成修復
3. 建立 branch → commit → PR
"""
import base64
import json
import logging
import re
import subprocess
import textwrap
from datetime import datetime

import httpx

from config import Config

logger = logging.getLogger(__name__)


class AutoFixer:
    def __init__(self, config: Config):
        self.config = config
        self.gh = httpx.Client(
            headers={
                "Authorization": f"Bearer {config.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        self.base = f"https://api.github.com/repos/{config.github_repo}"

    # ──────────────────────────────────────────────
    # 公開入口
    # ──────────────────────────────────────────────

    def fix_issue(self, issue_number: int, title: str, body: str) -> dict | None:
        """
        分析 Issue，自動修復並開 PR。
        回傳 PR dict，失敗回傳 None。
        失敗時自動在 Issue 留診斷問題留言，引導用戶補充技術細節。
        """
        logger.info("AutoFixer: starting fix for Issue #%s", issue_number)

        # 1. 讀取 repo 結構與相關檔案
        repo_context = self._build_repo_context(title, body)

        # 2. 請 Claude 分析並給出修復方案
        fix_plan = self._ask_claude(issue_number, title, body, repo_context)
        if not fix_plan:
            logger.warning("Claude returned no fix plan for Issue #%s", issue_number)
            self._post_diagnostic_comment(issue_number, reason="Claude 無法從現有描述判斷修改位置")
            return None

        # 3. 建立修復分支
        branch = f"fix/issue-{issue_number}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        default_branch = self._get_default_branch()
        if not self._create_branch(branch, default_branch):
            return None

        # 4. 提交修改（patch 模式：old_string→new_string；或 content 模式：完整內容）
        committed = []
        files_to_change = fix_plan.get("files", [])

        if not files_to_change:
            logger.warning(
                "Issue #%s: Claude returned empty files array. summary=%r",
                issue_number, fix_plan.get("summary", "")
            )
            self._post_diagnostic_comment(issue_number, reason="Claude 分析後無法確定需要修改哪個檔案")
            return None

        for file_change in files_to_change:
            if self._commit_file(branch, file_change, issue_number):
                committed.append(file_change["path"])

        if not committed:
            logger.warning(
                "Issue #%s: All %d file patch(es) failed to apply. Attempted: %s",
                issue_number,
                len(files_to_change),
                [f.get("path") for f in files_to_change],
            )
            self._post_diagnostic_comment(
                issue_number,
                reason=f"程式碼 patch 套用失敗（嘗試修改：{[f.get('path') for f in files_to_change]}）",
            )
            return None

        # 5. 開 PR
        pr = self._open_pr(
            branch=branch,
            base=default_branch,
            issue_number=issue_number,
            title=title,
            changes=committed,
            summary=fix_plan.get("summary", ""),
            before_after=fix_plan.get("before_after", ""),
        )
        logger.info("PR #%s created for Issue #%s", pr.get("number"), issue_number)
        return pr

    # ──────────────────────────────────────────────
    # Repo 脈絡蒐集
    # ──────────────────────────────────────────────

    # 每次都必須載入的核心檔案（不依賴關鍵字匹配）
    CORE_FILES = ["scripts/api_server.py"]

    def _build_repo_context(self, title: str, body: str) -> str:
        """讀取 repo 根目錄檔案列表與主要檔案內容。
        永遠優先載入 SYSTEM_CONTEXT.md 讓 Claude 理解完整架構。
        永遠載入 CORE_FILES（系統核心入口），不依賴關鍵字匹配。
        """
        lines = []

        # ── 1. 系統架構文件（最高優先）────────────────────
        system_ctx = self._read_file("SYSTEM_CONTEXT.md")
        if system_ctx:
            lines.append(f"## SYSTEM_CONTEXT.md（系統架構，必讀）\n{system_ctx[:5000]}")
        else:
            logger.warning("SYSTEM_CONTEXT.md not found in repo, analysis may be incomplete")

        # ── 2. 核心檔案（永遠載入，關鍵字選不到也必須看）──
        for core_path in self.CORE_FILES:
            content = self._read_file(core_path)
            if content:
                excerpt = self._extract_relevant_section(content, title + " " + body)
                lines.append(f"\n## {core_path}（核心入口，必讀）\n```python\n{excerpt}\n```")
                logger.debug("Loaded core file: %s", core_path)

        # ── 3. Repo 結構 ──────────────────────────────────
        lines.append("\n## Repo structure\n")
        try:
            resp = self.gh.get(f"{self.base}/git/trees/HEAD?recursive=1")
            if resp.status_code == 200:
                tree = resp.json().get("tree", [])
                py_files = [f["path"] for f in tree if f["path"].endswith(".py")][:15]
                lines.append("\n".join(py_files))

                # ── 4. 與 Issue 最相關的程式碼檔案（最多 3 個，排除已載入的核心檔案）──
                relevant = self._pick_relevant_files(py_files, title + " " + body)
                loaded = set(self.CORE_FILES)
                for path in relevant:
                    if path in loaded:
                        continue
                    content = self._read_file(path)
                    if content:
                        excerpt = self._extract_relevant_section(content, title + " " + body)
                        lines.append(f"\n## {path}\n```python\n{excerpt}\n```")
                        loaded.add(path)
                    if len(loaded) - len(self.CORE_FILES) >= 3:
                        break
        except Exception as e:
            logger.warning("Failed to build repo context: %s", e)
        return "\n".join(lines)

    def _extract_relevant_section(self, content: str, query: str, context_lines: int = 60) -> str:
        """從大型檔案中擷取與 query 最相關的段落（±context_lines 行），
        確保 Claude 看到正確的程式碼而不是前 N 字截斷。
        若找不到關鍵字則回傳前 3000 字。
        """
        keywords = [kw for kw in re.findall(r"\w{4,}", query.lower()) if kw not in {"fix", "issue", "error", "bug", "the", "and"}]
        file_lines = content.split("\n")

        best_line = 0
        best_score = 0
        for i, line in enumerate(file_lines):
            score = sum(1 for kw in keywords if kw in line.lower())
            if score > best_score:
                best_score = score
                best_line = i

        if best_score == 0:
            return content[:3000]

        start = max(0, best_line - context_lines)
        end = min(len(file_lines), best_line + context_lines)
        excerpt = "\n".join(file_lines[start:end])
        prefix = f"# ... (lines {start+1}-{end} of {len(file_lines)}) ...\n"
        return prefix + excerpt

    def _pick_relevant_files(self, files: list[str], query: str) -> list[str]:
        """簡單關鍵字比對選出最相關的檔案。"""
        keywords = re.findall(r"\w+", query.lower())
        scored = []
        for f in files:
            score = sum(1 for kw in keywords if kw in f.lower())
            scored.append((score, f))
        scored.sort(reverse=True)
        return [f for _, f in scored]

    def _read_file(self, path: str) -> str | None:
        resp = self.gh.get(f"{self.base}/contents/{path}")
        if resp.status_code == 200:
            try:
                return base64.b64decode(resp.json()["content"]).decode("utf-8", errors="replace")
            except Exception:
                pass
        return None

    # ──────────────────────────────────────────────
    # Claude 分析
    # ──────────────────────────────────────────────

    def _ask_claude(self, issue_number: int, title: str, body: str, repo_context: str) -> dict | None:
        """透過 Claude Code CLI（claude --print）分析 Issue 並回傳修復方案。
        使用 patch 模式（old_string/new_string）避免輸出完整大型檔案導致截斷。
        """
        prompt = textwrap.dedent(f"""
            你是一位資深工程師，負責修復 GitHub Issue。

            **Issue #{issue_number}：{title}**
            {body}

            {repo_context}

            請分析問題並給出修復方案。以 JSON 格式回覆（使用 patch 模式，不要輸出完整檔案）：
            {{
                "summary": "用一句話說明做了什麼修改",
                "before_after": "修改前後的對比說明",
                "files": [
                    {{
                        "path": "相對路徑（例如 scripts/api_server.py）",
                        "old_string": "要被替換的原始程式碼片段（必須與檔案中完全一致，包含縮排）",
                        "new_string": "替換後的新程式碼片段",
                        "reason": "為什麼這樣修"
                    }}
                ]
            }}

            重要規則：
            1. old_string 必須是檔案中確實存在的程式碼片段（從上方 repo_context 中複製）
            2. new_string 只包含需要改變的部分，保持相同縮排
            3. 一個檔案可以有多個修改，每個 old_string 要唯一可識別
            4. 如果無法確定修改位置，files 回傳空陣列
            5. 只回傳 JSON，不要其他文字
        """).strip()

        try:
            claude_path = r"C:\Users\xx\AppData\Roaming\npm\claude.cmd"
            result = subprocess.run(
                f'"{claude_path}" --print --dangerously-skip-permissions',
                input=prompt,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                shell=True,
            )
            raw = result.stdout.strip()
            if not raw:
                logger.error("Claude CLI returned empty response for Issue #%s: %s", issue_number, result.stderr[:500])
                return None
            # 移除可能的 markdown code block 包裝
            raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw)
            # 用 raw_decode 只解析第一個完整 JSON 物件（忽略後續文字）
            try:
                obj, _ = json.JSONDecoder().raw_decode(raw.lstrip())
                return obj
            except json.JSONDecodeError:
                # fallback：找第一個 { ... } 區塊
                match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
                raise
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out for Issue #%s (300s)", issue_number)
            return None
        except json.JSONDecodeError as e:
            logger.error("Claude CLI returned invalid JSON for Issue #%s: %s", issue_number, e)
            return None
        except Exception as e:
            logger.error("Claude CLI failed: %s", e)
            return None

    # ──────────────────────────────────────────────
    # GitHub 操作
    # ──────────────────────────────────────────────

    def _get_default_branch(self) -> str:
        resp = self.gh.get(self.base)
        return resp.json().get("default_branch", "master") if resp.status_code == 200 else "master"

    def _create_branch(self, branch: str, base: str) -> bool:
        # 取 base branch 的 SHA
        resp = self.gh.get(f"{self.base}/git/refs/heads/{base}")
        if resp.status_code != 200:
            logger.error("Cannot get base branch SHA: %s", resp.text)
            return False
        sha = resp.json()["object"]["sha"]

        resp = self.gh.post(
            f"{self.base}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        if resp.status_code in (200, 201):
            logger.info("Branch '%s' created.", branch)
            return True
        logger.error("Failed to create branch: %s", resp.text)
        return False

    def _commit_file(self, branch: str, file_change: dict, issue_number: int) -> bool:
        path = file_change["path"]

        # 取既有檔案內容（patch 模式需要；content 模式取 sha）
        existing = self.gh.get(f"{self.base}/contents/{path}?ref={branch}")
        if existing.status_code != 200:
            logger.error("Cannot read existing file %s: %s", path, existing.status_code)
            return False

        existing_data = existing.json()
        existing_sha = existing_data["sha"]
        existing_content = base64.b64decode(existing_data["content"]).decode("utf-8", errors="replace")

        # ── Patch 模式（優先）：用 old_string → new_string 替換 ──────────────
        if "old_string" in file_change and "new_string" in file_change:
            old_str = file_change["old_string"]
            new_str = file_change["new_string"]
            if old_str not in existing_content:
                logger.error("old_string not found in %s — patch aborted", path)
                logger.debug("old_string: %r", old_str[:200])
                return False
            count = existing_content.count(old_str)
            if count > 1:
                logger.warning("old_string appears %d times in %s, replacing first occurrence", count, path)
            new_content = existing_content.replace(old_str, new_str, 1)

        # ── Content 模式（fallback）：完整替換 ───────────────────────────────
        elif "content" in file_change:
            new_content = file_change["content"]
            # 安全檢查：新內容不能比原始內容短超過 50%（防止意外截斷）
            if len(new_content) < len(existing_content) * 0.5:
                logger.error(
                    "Content mode safety check failed for %s: new=%d chars vs old=%d chars (>50%% reduction). Aborting.",
                    path, len(new_content), len(existing_content),
                )
                return False
        else:
            logger.error("file_change for %s has neither old_string nor content", path)
            return False

        encoded = base64.b64encode(new_content.encode("utf-8")).decode()
        payload = {
            "message": f"fix: resolve issue #{issue_number} in {path}",
            "content": encoded,
            "branch": branch,
            "sha": existing_sha,
        }
        resp = self.gh.put(f"{self.base}/contents/{path}", json=payload)
        if resp.status_code in (200, 201):
            logger.info("Committed %s to branch %s", path, branch)
            return True
        logger.error("Failed to commit %s: %s", path, resp.text)
        return False

    def _post_diagnostic_comment(self, issue_number: int, reason: str = "") -> None:
        """修復失敗時在 Issue 留診斷留言，引導用戶補充技術細節。"""
        reason_line = f"\n> 失敗原因：{reason}\n" if reason else ""
        body = (
            f"## 🤖 自動修復需要更多資訊\n"
            f"{reason_line}\n"
            f"目前的描述不足以讓 Bot 定位問題程式碼，請補充以下任一項：\n\n"
            f"**1. 哪個 API 端點或功能出錯？**\n"
            f"例如：`/vector-search`、`/search-files`、LINE Webhook 驗證\n\n"
            f"**2. 完整的錯誤訊息是什麼？**\n"
            f"例如：`KeyError: 'similarity'`、`HTTP 404`、`psycopg2.OperationalError`\n\n"
            f"**3. api_server 或 n8n 的 log 顯示什麼？**\n"
            f"請直接貼上 log 文字（不要截圖，Bot 無法讀取圖片）\n\n"
            f"**4. 問題發生的步驟**\n"
            f"例如：「用戶傳『找面積計算式.pdf』→ n8n 呼叫 /vector-search → 回傳空陣列」\n\n"
            f"補充後 Bot 會自動重新嘗試修復。"
        )
        resp = self.gh.post(
            f"{self.base}/issues/{issue_number}/comments",
            json={"body": body},
        )
        if resp.status_code == 201:
            logger.info("Posted diagnostic comment on Issue #%s", issue_number)
        else:
            logger.warning("Failed to post diagnostic comment on Issue #%s: %s", issue_number, resp.status_code)

    def _open_pr(self, branch, base, issue_number, title, changes, summary, before_after) -> dict:
        changes_md = "\n".join(f"- `{c}`" for c in changes)
        body = (
            f"## Description\n{summary}\n\n"
            f"## Fixes\nFixes #{issue_number}\n\n"
            f"## Changes\n{changes_md}\n\n"
            f"## Before / After\n{before_after}\n\n"
            f"## Bot Execution Log\n- ClaudeCode: 自動分析並修復"
        )
        resp = self.gh.post(
            f"{self.base}/pulls",
            json={"title": f"fix: {title}", "head": branch, "base": base, "body": body},
        )
        resp.raise_for_status()
        return resp.json()
