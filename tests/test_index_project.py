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


def test_chroma_db_excluded_from_tracked():
    """chroma_db/ must never be indexed even if tracked by git."""
    with patch("index_project.subprocess.run", side_effect=_fake_run(
        ["main.py", "chroma_db/chroma.sqlite3", "chroma_db/uuid/data_level0.bin"], []
    )):
        files = git_indexable_files()
    assert not any(f.startswith("chroma_db") for f in files)


def test_chroma_db_excluded_from_untracked():
    """chroma_db/ must never be indexed even if untracked and not gitignored."""
    with patch("index_project.subprocess.run", side_effect=_fake_run(
        ["main.py"], ["chroma_db/chroma.sqlite3", "SUMMARY.md"]
    )):
        files = git_indexable_files()
    assert not any(f.startswith("chroma_db") for f in files)
    assert "SUMMARY.md" in files


def test_chroma_db_exclusion_tracks_chroma_path():
    """Exclusion must use CHROMA_PATH so a rename stays consistent."""
    import index_project as _ip
    original = _ip.CHROMA_PATH
    try:
        _ip.CHROMA_PATH = "./my_index"
        with patch("index_project.subprocess.run", side_effect=_fake_run(
            ["main.py", "my_index/chroma.sqlite3"], []
        )):
            files = _ip.git_indexable_files()
        assert not any(f.startswith("my_index") for f in files)
        assert "main.py" in files
    finally:
        _ip.CHROMA_PATH = original


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
