"""
ServiceManager — 本地 api_server.py 重啟管理器

流程：找到舊 process → kill → git pull → 啟動新 process → health check
Windows-compatible（使用 netstat + taskkill）
"""
import logging
import subprocess
import sys
import time

import httpx

logger = logging.getLogger(__name__)


class ServiceManager:

    def restart_and_verify(self, project_root: str, port: int = 8765) -> dict:
        """
        完整重啟流程，永遠回傳 dict（不 raise）：
        {"success": bool, "message": str, "details": list[str]}
        """
        details: list[str] = []
        try:
            # 1. 找並殺舊 process
            pids = self._find_process_on_port(port)
            if pids:
                kill_logs = self._kill_processes(pids)
                details.extend(kill_logs)
            else:
                details.append(f"port {port} 無現有 process")

            # 2. git pull
            ok, msg = self._git_pull(project_root)
            details.append(f"git pull: {msg.strip()[:120]}")
            if not ok:
                details.append("⚠️ git pull 失敗，以現有代碼重啟")

            # 3. 啟動新 process
            proc = self._start_server(project_root, port)
            details.append(f"api_server.py 啟動中 (PID {proc.pid})")

            # 4. 健康檢查
            if self._health_check(port):
                details.append(f"健康檢查通過 http://127.0.0.1:{port}/health ✅")
                return {"success": True, "message": "服務重啟成功", "details": details}
            else:
                details.append("健康檢查失敗 — 服務未能正常回應")
                return {"success": False, "message": "健康檢查失敗", "details": details}

        except Exception as e:
            logger.exception("ServiceManager.restart_and_verify failed")
            details.append(f"例外錯誤: {e}")
            return {"success": False, "message": str(e), "details": details}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_process_on_port(self, port: int) -> list[int]:
        """回傳正在監聽 port 的 PID 列表（Windows netstat -ano）。"""
        pids: list[int] = []
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                # 只看 LISTENING 行，且包含目標 port
                if "LISTENING" not in line:
                    continue
                if f":{port}" not in line:
                    continue
                parts = line.split()
                if parts:
                    pid_str = parts[-1]
                    if pid_str.isdigit():
                        pid = int(pid_str)
                        if pid not in pids:
                            pids.append(pid)
        except Exception as e:
            logger.warning("_find_process_on_port error: %s", e)
        return pids

    def _kill_processes(self, pids: list[int]) -> list[str]:
        logs: list[str] = []
        for pid in pids:
            try:
                r = subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, text=True, timeout=10,
                )
                msg = r.stdout.strip() or r.stderr.strip()
                logs.append(f"killed PID {pid}: {msg[:80]}")
            except Exception as e:
                logs.append(f"kill PID {pid} failed: {e}")

        # 等待 port 釋放（最多 3 秒）
        for _ in range(6):
            time.sleep(0.5)
            if not self._find_process_on_port(pids[0] if pids else 0):
                break
        return logs

    def _git_pull(self, project_root: str) -> tuple[bool, str]:
        """在 project_root 執行 git pull，回傳 (success, message)。"""
        try:
            r = subprocess.run(
                ["git", "-C", project_root, "pull"],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=60,
            )
            if r.returncode == 0:
                return True, r.stdout or "Already up to date."
            return False, r.stderr or "git pull failed"
        except Exception as e:
            return False, str(e)

    def _start_server(self, project_root: str, port: int) -> subprocess.Popen:
        """背景啟動 api_server.py，不等待回傳。"""
        cmd = [
            sys.executable,
            "scripts/api_server.py",
            "--port", str(port),
            "--host", "0.0.0.0",
        ]
        kwargs = dict(
            cwd=project_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(cmd, **kwargs)

    def _health_check(self, port: int, retries: int = 8, delay: float = 1.5) -> bool:
        """輪詢 /health，最多等待 retries * delay 秒。"""
        url = f"http://127.0.0.1:{port}/health"
        for attempt in range(retries):
            time.sleep(delay)
            try:
                resp = httpx.get(url, timeout=3)
                if resp.status_code == 200 and resp.json().get("status") == "ok":
                    return True
            except Exception:
                pass
            logger.debug("Health check attempt %s/%s failed", attempt + 1, retries)
        return False
