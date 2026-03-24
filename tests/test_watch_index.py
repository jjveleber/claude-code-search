# tests/test_watch_index.py
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watch_index import (
    DebounceReindexer,
    ReindexHandler,
    cleanup_pid,
    is_already_running,
    should_ignore,
    write_pid,
)


# ── PID guard ──────────────────────────────────────────────────────────────────

def test_is_already_running_no_file(tmp_path):
    """No PID file → not running."""
    assert not is_already_running(str(tmp_path / "test.pid"))


def test_is_already_running_stale_pid(tmp_path):
    """PID file exists but process is dead → not running."""
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("99999999")
    assert not is_already_running(str(pid_file))


def test_is_already_running_live_pid(tmp_path):
    """PID file contains own PID → running."""
    pid_file = tmp_path / "test.pid"
    pid_file.write_text(str(os.getpid()))
    assert is_already_running(str(pid_file))


def test_write_pid_creates_file_with_current_pid(tmp_path):
    pid_file = str(tmp_path / "test.pid")
    write_pid(pid_file)
    assert Path(pid_file).read_text().strip() == str(os.getpid())


def test_cleanup_pid_removes_file(tmp_path):
    pid_file = str(tmp_path / "test.pid")
    write_pid(pid_file)
    cleanup_pid(pid_file)
    assert not Path(pid_file).exists()


def test_cleanup_pid_missing_file_does_not_raise(tmp_path):
    cleanup_pid(str(tmp_path / "missing.pid"))  # must not raise


# ── Path filtering ─────────────────────────────────────────────────────────────

def test_should_ignore_chroma_db():
    assert should_ignore("chroma_db/index/data.bin")


def test_should_ignore_venv():
    assert should_ignore(".venv/lib/python3.11/site-packages/foo.py")


def test_should_ignore_git():
    assert should_ignore(".git/COMMIT_EDITMSG")


def test_should_ignore_pycache():
    assert should_ignore("__pycache__/foo.cpython-311.pyc")


def test_should_ignore_pid_file():
    assert should_ignore(".watch_index.pid")


def test_should_ignore_log_file():
    assert should_ignore(".watch_index.log")


def test_should_not_ignore_py_file():
    assert not should_ignore("index_project.py")


def test_should_not_ignore_nested_py_file():
    assert not should_ignore("src/utils/helpers.py")
