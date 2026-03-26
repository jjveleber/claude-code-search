import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from index_project import git_indexable_files


def _fake_run(tracked, untracked):
    def _run(cmd, **kwargs):
        result = MagicMock()
        result.stdout = "\n".join(untracked if "--others" in cmd else tracked)
        if result.stdout:
            result.stdout += "\n"
        return result
    return _run


def test_includes_tracked_files():
    with patch("index_project.subprocess.run", side_effect=_fake_run(["main.py", "utils.py"], [])):
        files = git_indexable_files()
    assert "main.py" in files
    assert "utils.py" in files


def test_includes_untracked_non_ignored_files():
    """New files created by Claude Code (not yet staged) must appear in the index."""
    with patch("index_project.subprocess.run", side_effect=_fake_run(["main.py"], ["SUMMARY.md"])):
        files = git_indexable_files()
    assert "main.py" in files
    assert "SUMMARY.md" in files


def test_no_duplicates_when_file_in_both_lists():
    with patch("index_project.subprocess.run", side_effect=_fake_run(["main.py"], ["main.py"])):
        files = git_indexable_files()
    assert files.count("main.py") == 1


def test_empty_lines_excluded():
    with patch("index_project.subprocess.run", side_effect=_fake_run(["main.py", ""], ["", "new.py"])):
        files = git_indexable_files()
    assert "" not in files


def test_untracked_query_uses_exclude_standard():
    """--exclude-standard ensures gitignored files are not returned as untracked."""
    calls = []
    def capturing_run(cmd, **kwargs):
        calls.append(list(cmd))
        r = MagicMock()
        r.stdout = ""
        return r

    with patch("index_project.subprocess.run", side_effect=capturing_run):
        git_indexable_files()

    untracked_calls = [c for c in calls if "--others" in c]
    assert untracked_calls, "expected a call with --others"
    assert "--exclude-standard" in untracked_calls[0]
