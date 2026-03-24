#!/usr/bin/env python3
"""watch_index.py — re-index ChromaDB whenever project files change."""

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
IGNORED_DIRS = {"chroma_db", ".venv", "__pycache__", ".git"}
IGNORED_FILES = {".watch_index.pid", ".watch_index.log"}
DEBOUNCE_SECONDS = 1.0
INDEX_CMD = [".venv/bin/python3", "index_project.py"]


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


def cleanup_pid(pid_file=PID_FILE):
    """Remove pid_file, silently ignore if missing."""
    try:
        os.remove(pid_file)
    except FileNotFoundError:
        pass


def should_ignore(path):
    """Return True if path is under an ignored directory or is an ignored filename."""
    raise NotImplementedError


class DebounceReindexer:
    pass


class ReindexHandler(FileSystemEventHandler):
    pass


def _log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[watch_index] {msg}\n")


def main():
    pass


if __name__ == "__main__":
    main()
