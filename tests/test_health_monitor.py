# tests/test_health_monitor.py
import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from health_monitor import HealthMonitor

def make_monitor():
    config = MagicMock()
    config.health_check_interval_seconds = 60
    config.health_check_ports = [8765]
    config.n8n_health_url = "http://localhost:5678/healthz"
    config.github_token = "fake"
    config.github_repo = "owner/repo"
    discord = MagicMock()
    return HealthMonitor(config, discord)

def test_consecutive_fail_threshold():
    """連續 2 次失敗才建 Issue，第 1 次不建。"""
    m = make_monitor()
    with patch.object(m, '_check_url', return_value=False):
        with patch.object(m, '_create_issue') as mock_issue:
            m._check_service("api_server", "http://localhost:8765/health", cooldown_key="api_8765")
            mock_issue.assert_not_called()  # 第 1 次失敗，不建
            m._check_service("api_server", "http://localhost:8765/health", cooldown_key="api_8765")
            mock_issue.assert_called_once()  # 第 2 次，建 Issue

def test_cooldown_prevents_duplicate_issue():
    """cooldown 期間內不重複建 Issue。"""
    import time
    m = make_monitor()
    m._cooldown_seconds = 3600
    m._fail_counts["api_8765"] = 2
    m._last_issue_ts["api_8765"] = time.time()  # 剛建過
    with patch.object(m, '_check_url', return_value=False):
        with patch.object(m, '_create_issue') as mock_issue:
            m._check_service("api_server", "http://localhost:8765/health", cooldown_key="api_8765")
            mock_issue.assert_not_called()

def test_recovery_resets_fail_count():
    """服務恢復後 fail_count 歸零。"""
    m = make_monitor()
    m._fail_counts["api_8765"] = 2
    with patch.object(m, '_check_url', return_value=True):
        m._check_service("api_server", "http://localhost:8765/health", cooldown_key="api_8765")
    assert m._fail_counts["api_8765"] == 0
