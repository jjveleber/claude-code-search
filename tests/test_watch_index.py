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


# ── DebounceReindexer ──────────────────────────────────────────────────────────

def test_debounce_skips_if_subprocess_running(tmp_path, monkeypatch):
    """_run() does not launch a new process if one is still running."""
    monkeypatch.chdir(tmp_path)
    reindexer = DebounceReindexer(cmd=["echo", "test"])
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # still running
    reindexer._proc = mock_proc

    with patch("watch_index.subprocess.Popen") as mock_popen:
        reindexer._run()

    mock_popen.assert_not_called()


def test_debounce_launches_subprocess_when_idle(tmp_path, monkeypatch):
    """_run() launches the command when no prior process is running."""
    monkeypatch.chdir(tmp_path)
    reindexer = DebounceReindexer(cmd=["echo", "test"])
    assert reindexer._proc is None
    reindexer._run()
    assert reindexer._proc is not None


def test_nonzero_exit_does_not_crash(tmp_path, monkeypatch):
    """A failing index command does not crash the watcher."""
    monkeypatch.chdir(tmp_path)
    reindexer = DebounceReindexer(cmd=["python3", "-c", "import sys; sys.exit(1)"])
    reindexer._run()  # must not raise
    assert reindexer._proc is not None


def test_debounce_collapses_rapid_triggers():
    """Ten rapid trigger() calls result in exactly one _run() call."""
    run_count = {"n": 0}
    reindexer = DebounceReindexer(delay=0.05)

    def counting_run():
        run_count["n"] += 1

    reindexer._run = counting_run

    for _ in range(10):
        reindexer.trigger()

    time.sleep(0.2)
    assert run_count["n"] == 1
