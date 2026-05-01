#!/usr/bin/env python3
"""watch_index.py — re-index ChromaDB whenever project files change."""

import fcntl
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

PID_FILE = ".watch_index.pid"
LOG_FILE = ".watch_index.log"
IGNORED_DIRS = {"chroma_db", ".venv-code-search", "__pycache__", ".git"}
IGNORED_FILES = {".watch_index.pid", ".watch_index.log"}
DEBOUNCE_SECONDS = 1.0
INDEX_CMD = [".venv-code-search/bin/python3", "index_project.py"]


def is_already_running(pid_file=PID_FILE):
    """Return True if a live watcher process is recorded in pid_file."""
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it


def write_pid(pid_file=PID_FILE):
    """Write the current process PID to pid_file."""
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))


def acquire_pid_lock(pid_file=PID_FILE):
    """Atomically acquire exclusive PID lock.

    Returns an open file handle on success (caller must keep it open to hold
    the lock), or None if another process already holds it.  Using flock
    eliminates the TOCTOU race in the old is_already_running/write_pid pair.
    """
    try:
        fh = open(pid_file, "a")          # create if absent; never truncates
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        return fh
    except OSError:
        try:
            fh.close()
        except Exception:
            pass
        return None


def cleanup_pid(pid_file=PID_FILE):
    """Remove pid_file, silently ignore if missing."""
    try:
        os.remove(pid_file)
    except FileNotFoundError:
        pass


def is_git_ignored(path):
    """Return True if path is git-ignored (i.e. git check-ignore exits 0)."""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", path],
            capture_output=True,
        )
        return result.returncode == 0
    except OSError:
        return False


def should_ignore(path):
    """Return True if path is under an ignored directory or is an ignored filename."""
    p = Path(path)
    for part in p.parts:
        if part in IGNORED_DIRS:
            return True
    return p.name in IGNORED_FILES


class DebounceReindexer:
    """Collapses rapid file-change events into a single index_project.py run."""

    def __init__(self, delay=DEBOUNCE_SECONDS, cmd=None):
        self._delay = delay
        self._cmd = cmd if cmd is not None else INDEX_CMD
        self._timer = None
        self._lock = threading.Lock()
        self._proc = None

    def trigger(self):
        """Schedule a re-index, resetting any pending timer."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._run)
            self._timer.daemon = True
            self._timer.start()

    def _run(self):
        """Run index_project.py unless a previous run is still in progress."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                _log("index already running, skipping trigger")
                return
            _log("change detected, re-indexing...")
            with open(LOG_FILE, "a") as log_f:
                self._proc = subprocess.Popen(
                    self._cmd,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                )


class ReindexHandler(FileSystemEventHandler):
    """Watchdog event handler that forwards relevant events to DebounceReindexer."""

    def __init__(self, reindexer):
        self._reindexer = reindexer

    def on_any_event(self, event):
        if event.is_directory:
            return
        if event.event_type in ("opened", "closed_no_write"):
            return
        if should_ignore(event.src_path):
            return
        if is_git_ignored(event.src_path):
            return
        _log(f"triggered by: {event.src_path} ({event.event_type})")
        self._reindexer.trigger()


def _log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[watch_index] {msg}\n")


def main():
    lock_fh = acquire_pid_lock()
    if lock_fh is None:
        try:
            with open(PID_FILE) as f:
                pid = f.read().strip()
        except FileNotFoundError:
            pid = "unknown"
        print(f"watcher already running (PID: {pid})")
        sys.exit(0)

    def _cleanup(signum=None, frame=None):
        lock_fh.close()
        cleanup_pid()
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    reindexer = DebounceReindexer()
    handler = ReindexHandler(reindexer)
    observer = Observer()
    observer.schedule(handler, path=".", recursive=True)
    observer.start()

    print(f"Watching for changes. Log: {LOG_FILE}")

    try:
        observer.join()
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
