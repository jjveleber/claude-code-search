# File Watcher Auto-Reindex Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `watch_index.py` — a background file watcher that re-indexes ChromaDB whenever project files change, covering edits from any source (user, IDE, Claude).

**Architecture:** A standalone Python script using `watchdog` for native OS events (FSEvents/inotify/ReadDirectoryChangesW). A PID file guards against duplicate instances. A 1-second debounce timer collapses rapid saves into a single `index_project.py` subprocess call. `install.sh` gains `watchdog` as a dependency, downloads `watch_index.py`, and injects a Session Startup section into the user's `CLAUDE.md`.

**Tech Stack:** Python 3.9+, watchdog≥3.0, threading.Timer, pytest.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `watch_index.py` | Create | PID guard, watchdog observer, debounce, subprocess launch |
| `tests/test_watch_index.py` | Create | Unit tests for all testable units in watch_index.py |
| `install.sh` | Modify | Add watchdog dep, download watch_index.py, update .gitignore, inject Session Startup into CLAUDE.md |
| `tests/test_install.sh` | Modify | Assert watch_index.py installed, .gitignore entries, Session Startup in CLAUDE.md, idempotency |
| `CLAUDE.md` (repo root) | Modify | Add Session Startup section for tool development use |
| `README.md` | Modify | Update Upgrade and Uninstall sections |
| `.gitignore` (repo root) | Modify | Add `.watch_index.log` and `.watch_index.pid` |

---

## Chunk 1: `watch_index.py` + `tests/test_watch_index.py`

### Task 1: PID guard — tests first

**Files:**
- Create: `tests/test_watch_index.py`

- [ ] **Step 1: Create test file with PID guard tests**

```python
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
```

- [ ] **Step 2: Run tests — verify they fail with ImportError**

```bash
source .venv/bin/activate && pytest tests/test_watch_index.py -v
```

Expected: `ModuleNotFoundError: No module named 'watch_index'`

---

### Task 2: PID guard — implement

**Files:**
- Create: `watch_index.py`

- [ ] **Step 3: Create `watch_index.py` with PID guard functions**

```python
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
```

- [ ] **Step 4: Run PID guard tests — verify they pass**

```bash
pytest tests/test_watch_index.py::test_is_already_running_no_file \
       tests/test_watch_index.py::test_is_already_running_stale_pid \
       tests/test_watch_index.py::test_is_already_running_live_pid \
       tests/test_watch_index.py::test_write_pid_creates_file_with_current_pid \
       tests/test_watch_index.py::test_cleanup_pid_removes_file \
       tests/test_watch_index.py::test_cleanup_pid_missing_file_does_not_raise -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add watch_index.py tests/test_watch_index.py
git commit -m "feat: add watch_index.py skeleton with PID guard"
```

---

### Task 3: Path filtering — tests first

**Files:**
- Modify: `tests/test_watch_index.py` (append)

- [ ] **Step 1: Append should_ignore tests**

```python
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
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
pytest tests/test_watch_index.py -k "should_ignore" -v
```

Expected: 8 failed with `NotImplementedError`

---

### Task 4: Path filtering — implement

**Files:**
- Modify: `watch_index.py` — replace `should_ignore` stub

- [ ] **Step 3: Replace `should_ignore` stub with implementation**

Replace:
```python
def should_ignore(path):
    """Return True if path is under an ignored directory or is an ignored filename."""
    raise NotImplementedError
```

With:
```python
def should_ignore(path):
    """Return True if path is under an ignored directory or is an ignored filename."""
    p = Path(path)
    for part in p.parts:
        if part in IGNORED_DIRS:
            return True
    return p.name in IGNORED_FILES
```

- [ ] **Step 4: Run should_ignore tests — verify they pass**

```bash
pytest tests/test_watch_index.py -k "should_ignore" -v
```

Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add watch_index.py tests/test_watch_index.py
git commit -m "feat: add should_ignore path filter to watch_index"
```

---

### Task 5: DebounceReindexer — tests first

**Files:**
- Modify: `tests/test_watch_index.py` (append)

- [ ] **Step 1: Append DebounceReindexer tests**

```python
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
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
pytest tests/test_watch_index.py -k "debounce or nonzero" -v
```

Expected: 4 failed (DebounceReindexer is a stub `pass` class)

---

### Task 6: DebounceReindexer — implement

**Files:**
- Modify: `watch_index.py` — replace `DebounceReindexer` stub

- [ ] **Step 3: Replace DebounceReindexer stub with implementation**

Replace:
```python
class DebounceReindexer:
    pass
```

With:
```python
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
```

- [ ] **Step 4: Run DebounceReindexer tests — verify they pass**

```bash
pytest tests/test_watch_index.py -k "debounce or nonzero" -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add watch_index.py tests/test_watch_index.py
git commit -m "feat: add DebounceReindexer to watch_index"
```

---

### Task 7: ReindexHandler + main — tests first, then implement

**Files:**
- Modify: `tests/test_watch_index.py` (append)
- Modify: `watch_index.py` — replace ReindexHandler stub and main

- [ ] **Step 1: Append ReindexHandler tests**

```python
# ── ReindexHandler ─────────────────────────────────────────────────────────────

def test_handler_ignores_directory_events():
    reindexer = MagicMock()
    handler = ReindexHandler(reindexer)
    event = MagicMock()
    event.is_directory = True
    event.src_path = "somedir"
    handler.on_any_event(event)
    reindexer.trigger.assert_not_called()


def test_handler_ignores_excluded_path():
    reindexer = MagicMock()
    handler = ReindexHandler(reindexer)
    event = MagicMock()
    event.is_directory = False
    event.src_path = "chroma_db/index/data.bin"
    handler.on_any_event(event)
    reindexer.trigger.assert_not_called()


def test_handler_triggers_for_regular_file():
    reindexer = MagicMock()
    handler = ReindexHandler(reindexer)
    event = MagicMock()
    event.is_directory = False
    event.src_path = "index_project.py"
    handler.on_any_event(event)
    reindexer.trigger.assert_called_once()
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
pytest tests/test_watch_index.py -k "handler" -v
```

Expected: 3 failed (ReindexHandler is a stub)

- [ ] **Step 3: Replace ReindexHandler stub with implementation**

Replace:
```python
class ReindexHandler(FileSystemEventHandler):
    pass
```

With:
```python
class ReindexHandler(FileSystemEventHandler):
    """Watchdog event handler that forwards relevant events to DebounceReindexer."""

    def __init__(self, reindexer):
        self._reindexer = reindexer

    def on_any_event(self, event):
        if event.is_directory:
            return
        if should_ignore(event.src_path):
            return
        self._reindexer.trigger()
```

- [ ] **Step 4: Replace main stub with implementation**

Replace:
```python
def main():
    pass
```

With:
```python
def main():
    if is_already_running():
        try:
            with open(PID_FILE) as f:
                pid = f.read().strip()
        except FileNotFoundError:
            pid = "unknown"
        print(f"watcher already running (PID: {pid})")
        sys.exit(0)

    write_pid()

    def _cleanup(signum=None, frame=None):
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
```

- [ ] **Step 5: Run all tests — verify they all pass**

```bash
pytest tests/test_watch_index.py -v
```

Expected: all tests pass (no failures)

- [ ] **Step 6: Commit**

```bash
git add watch_index.py tests/test_watch_index.py
git commit -m "feat: add ReindexHandler and main to watch_index"
```

---

## Chunk 2: `install.sh` + `tests/test_install.sh`

### Task 8: Update install.sh

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Add `watchdog>=3.0` to pip install (line 47)**

Change:
```bash
"$VENV_PATH/bin/pip" install "chromadb>=1.0"
```

To:
```bash
"$VENV_PATH/bin/pip" install "chromadb>=1.0" "watchdog>=3.0"
```

- [ ] **Step 2: Add `watch_index.py` to the file download loop (line 57)**

Change:
```bash
for FILE in index_project.py search_code.py; do
```

To:
```bash
for FILE in index_project.py search_code.py watch_index.py; do
```

- [ ] **Step 3: Update .gitignore step to also add `.watch_index.log` and `.watch_index.pid`**

Change the entire Step 6 block:
```bash
# Step 6: Update .gitignore
if [ ! -f ".gitignore" ]; then
    printf "chroma_db/\n" > .gitignore
    echo "Created .gitignore"
elif ! grep -qxF "chroma_db/" .gitignore; then
    printf "\nchroma_db/\n" >> .gitignore
    echo "Added chroma_db/ to .gitignore"
else
    echo "chroma_db/ already in .gitignore"
fi
```

To:
```bash
# Step 6: Update .gitignore
if [ ! -f ".gitignore" ]; then
    printf "chroma_db/\n.watch_index.log\n.watch_index.pid\n" > .gitignore
    echo "Created .gitignore"
else
    if ! grep -qxF "chroma_db/" .gitignore; then
        printf "\nchroma_db/\n" >> .gitignore
        echo "Added chroma_db/ to .gitignore"
    else
        echo "chroma_db/ already in .gitignore"
    fi
    for WATCH_IGNORE in ".watch_index.log" ".watch_index.pid"; do
        if ! grep -qxF "$WATCH_IGNORE" .gitignore; then
            printf "\n%s\n" "$WATCH_IGNORE" >> .gitignore
            echo "Added $WATCH_IGNORE to .gitignore"
        else
            echo "$WATCH_IGNORE already in .gitignore"
        fi
    done
fi
```

- [ ] **Step 4: Add Session Startup injection to CLAUDE.md (after Step 7 block)**

Insert the new Step 7b block immediately after the line `echo "Precision Protocol already in CLAUDE.md"` / `fi` and before the line `# Step 8: Install PostToolUse hook`. The exact anchor is:

```bash
else
    echo "Precision Protocol already in CLAUDE.md"
fi

# Step 8: Install PostToolUse hook into .claude/settings.local.json
```

Insert between the `fi` and `# Step 8:` line:

```bash
else
    echo "Precision Protocol already in CLAUDE.md"
fi

# Step 7b: Add Session Startup section to CLAUDE.md
WATCH_SENTINEL="<!-- code-search-watch:start -->"
WATCH_BLOCK="<!-- code-search-watch:start -->
## Session Startup
At the start of each session:
1. Run \`.venv/bin/python3 index_project.py\` to ensure the index is fresh
2. Run \`.venv/bin/python3 watch_index.py >> .watch_index.log 2>&1 &\` to start the watcher in the background
<!-- code-search-watch:end -->"

if ! grep -qF "$WATCH_SENTINEL" CLAUDE.md; then
    printf "\n%s\n" "$WATCH_BLOCK" >> CLAUDE.md
    echo "Appended Session Startup to CLAUDE.md"
else
    echo "Session Startup already in CLAUDE.md"
fi

# Step 8: Install PostToolUse hook into .claude/settings.local.json
```

- [ ] **Step 4b: Verify install.sh is syntactically valid**

```bash
bash -n install.sh
```

Expected: no output (exit 0)

- [ ] **Step 5: Update the final echo in install.sh to mention the watcher**

Change:
```bash
echo "  Re-index: .venv/bin/python3 index_project.py"
echo "  Search:   .venv/bin/python3 search_code.py \"<query>\""
```

To:
```bash
echo "  Re-index: .venv/bin/python3 index_project.py"
echo "  Watch:    .venv/bin/python3 watch_index.py >> .watch_index.log 2>&1 &"
echo "  Search:   .venv/bin/python3 search_code.py \"<query>\""
```

---

### Task 9: Update test_install.sh

**Files:**
- Modify: `tests/test_install.sh`

- [ ] **Step 1: Add assertions to Test 1 (fresh install)**

In Test 1, insert the following asserts immediately before the `teardown` call at the end of the Test 1 block:

```bash
assert "watch_index.py installed"              "[ -f watch_index.py ]"
assert ".watch_index.log in .gitignore"        "grep -qxF '.watch_index.log' .gitignore"
assert ".watch_index.pid in .gitignore"        "grep -qxF '.watch_index.pid' .gitignore"
assert "Session Startup in CLAUDE.md"          "grep -q 'Session Startup' CLAUDE.md"
assert "watch_index.py command in CLAUDE.md"   "grep -q 'watch_index.py' CLAUDE.md"
```

- [ ] **Step 2: Add a new test for Session Startup idempotency**

Before the final `if [ "$FAIL" -eq 0 ]` block, add:

```bash
echo ""
echo "=== Test 11: Re-install does not duplicate Session Startup in CLAUDE.md ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
COUNT1=$(grep -c "Session Startup" CLAUDE.md)
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh" 2>&1
COUNT2=$(grep -c "Session Startup" CLAUDE.md)
assert "Session Startup not duplicated on re-install" "[ \"$COUNT1\" = \"$COUNT2\" ]"
teardown
```

- [ ] **Step 3: Run the full test suite — verify all tests pass**

```bash
bash tests/test_install.sh
```

Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add install.sh tests/test_install.sh
git commit -m "feat: install.sh adds watchdog, watch_index.py, and Session Startup to CLAUDE.md"
```

---

## Chunk 3: Docs + repo config

### Task 10: Update repo's own CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (repo root)

- [ ] **Step 1: Append Session Startup section**

Append after the existing `<!-- code-search:end -->` block. The current file ends with:

```
<!-- code-search:end -->
```

Add after it:

```markdown

<!-- code-search-watch:start -->
## Session Startup
At the start of each session:
1. Run `.venv/bin/python3 index_project.py` to ensure the index is fresh
2. Run `.venv/bin/python3 watch_index.py >> .watch_index.log 2>&1 &` to start the watcher in the background
<!-- code-search-watch:end -->
```

- [ ] **Step 2: Verify the sentinel appears exactly once**

```bash
grep -c "code-search-watch:start" CLAUDE.md
```

Expected: `1`

---

### Task 11: Update README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update Upgrade section — add `watch_index.py` to the rm command**

Change:
```bash
rm index_project.py search_code.py
```

To:
```bash
rm index_project.py search_code.py watch_index.py
```

- [ ] **Step 2: Update Uninstall section — full replacement**

Change the Uninstall bash block:
```bash
rm -rf index_project.py search_code.py chroma_db/ .venv/
```

To:
```bash
pkill -f watch_index.py || true
rm -rf index_project.py search_code.py watch_index.py chroma_db/ .venv/ .watch_index.pid .watch_index.log
```

- [ ] **Step 3: Update the manual uninstall steps bullet list**

Change:
```
- Remove the block between `<!-- code-search:start -->` and `<!-- code-search:end -->` from `CLAUDE.md`
- Remove the `chroma_db/` line from `.gitignore`
- Remove the `PostToolUse` hook entry from `.claude/settings.local.json` (the entry with `"command": ".venv/bin/python3 index_project.py"`)
```

To:
```
- Remove the block between `<!-- code-search:start -->` and `<!-- code-search:end -->` from `CLAUDE.md`
- Remove the block between `<!-- code-search-watch:start -->` and `<!-- code-search-watch:end -->` from `CLAUDE.md`
- Remove the `chroma_db/`, `.watch_index.log`, and `.watch_index.pid` lines from `.gitignore`
- Remove the `PostToolUse` hook entry from `.claude/settings.local.json` (the entry with `"command": ".venv/bin/python3 index_project.py"`)
```

---

### Task 12: Update repo .gitignore and commit docs

**Files:**
- Modify: `.gitignore` (repo root)

- [ ] **Step 1: Add watch_index artifacts to repo .gitignore**

Check and append only if not already present:

```bash
for ENTRY in ".watch_index.log" ".watch_index.pid"; do
    if ! grep -qxF "$ENTRY" .gitignore; then
        printf "\n%s\n" "$ENTRY" >> .gitignore
        echo "Added $ENTRY"
    fi
done
```

- [ ] **Step 2: Commit all docs and config changes**

```bash
git add CLAUDE.md README.md .gitignore
git commit -m "docs: update CLAUDE.md, README uninstall, and .gitignore for watch_index"
```
