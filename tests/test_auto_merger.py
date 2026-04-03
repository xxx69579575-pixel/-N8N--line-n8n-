# tests/test_auto_merger.py
import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_merger import AutoMerger

def make_merger():
    config = MagicMock()
    config.auto_merge_enabled = True
    config.auto_merge_safe_paths = ("workflows/", "config/", "docs/", ".md")
    config.github_token = "fake"
    config.github_repo = "owner/repo"
    discord = MagicMock()
    return AutoMerger(config, discord)

def test_safe_paths_all_safe():
    m = make_merger()
    files = ["workflows/qa_workflow.json", "docs/README.md"]
    assert m._is_safe_change(files) is True

def test_safe_paths_has_risky_file():
    m = make_merger()
    files = ["workflows/qa_workflow.json", "scripts/api_server.py"]
    assert m._is_safe_change(files) is False

def test_safe_paths_empty():
    m = make_merger()
    assert m._is_safe_change([]) is False

def test_auto_merge_disabled():
    m = make_merger()
    m.config.auto_merge_enabled = False
    with patch.object(m, '_merge_pr') as mock_merge:
        result = m.try_auto_merge(pr_number=1, head_sha="abc")
        mock_merge.assert_not_called()
    assert result is False

def test_auto_merge_risky_files_skips():
    m = make_merger()
    with patch.object(m, '_get_pr_files', return_value=["scripts/api_server.py"]):
        with patch.object(m, '_merge_pr') as mock_merge:
            result = m.try_auto_merge(pr_number=1, head_sha="abc")
            mock_merge.assert_not_called()
    assert result is False
