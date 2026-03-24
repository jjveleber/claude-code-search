# File Watcher Auto-Reindex Design

**Date:** 2026-03-24
**Status:** Draft

## Goal

Automatically re-index the ChromaDB vector store whenever project files change — whether changed by the user, an editor, or Claude Code — eliminating the need to manually run `index_project.py`.

## Background

Currently, `index_project.py` is triggered only via a Claude Code `PostToolUse` hook, meaning edits made outside of Claude (e.g., from an IDE or terminal) do not update the index. A file watcher solves this by monitoring the filesystem and re-indexing on any change.

## Approach

A standalone script `watch_index.py` runs as a background process and uses the `watchdog` library (native OS events: FSEvents on macOS, inotify on Linux, ReadDirectoryChangesW on Windows) to detect file changes and trigger `index_project.py`.

The script is kept intentionally simple — it does not replicate indexing logic, it delegates entirely to `index_project.py`.

## Components

### `watch_index.py` (new)

**PID guard:**
- On startup, check `.watch_index.pid`
- If the file exists and the recorded PID is still alive, print "watcher already running (PID: X)" and exit
- Otherwise write the current PID to `.watch_index.pid`
- On clean exit or signal (SIGINT, SIGTERM), delete `.watch_index.pid`

**Watcher:**
- `watchdog` Observer watching the project root recursively
- Event handler ignores paths under: `chroma_db/`, `.venv/`, `__pycache__/`, `.git/`, and `.watch_index.pid`
- Responds to file created, modified, moved, and deleted events

**Debounce:**
- Uses `threading.Timer` with a 1-second delay
- Each new event resets the timer
- When the timer fires, runs `.venv/bin/python3 index_project.py` as a subprocess
- Prevents thrashing during rapid multi-file saves

### `install.sh` (modified)

- Add `watchdog>=3.0` to the pip install command alongside `chromadb`
- Add `watch_index.py` to the file download loop

### `CLAUDE.md` (modified)

Add a Session Startup section instructing Claude to run at session open:

```
## Session Startup
At the start of each session:
1. Run `.venv/bin/python3 index_project.py` to ensure the index is fresh
2. Start `.venv/bin/python3 watch_index.py` in the background to keep it updated
```

### `README.md` (modified)

Update the Uninstall section:

**rm command:**
```bash
rm -rf index_project.py search_code.py watch_index.py chroma_db/ .venv/ .watch_index.pid
```

**Additional uninstall steps:**
- Stop the watcher if running: `pkill -f watch_index.py`
- Remove the Session Startup block from `CLAUDE.md`

## Data Flow

```
File change on disk
  → watchdog detects event
  → event handler filters ignored paths
  → debounce timer resets (1s)
  → timer fires → subprocess: python3 index_project.py
  → index_project.py upserts only changed chunks
```

## Error Handling

- If `index_project.py` exits non-zero, the watcher logs the error to stderr and continues watching (does not crash)
- If `.watch_index.pid` exists but the process is dead (stale PID), the watcher overwrites it and starts normally
- Signal handlers ensure the PID file is always cleaned up on exit

## Testing

Existing test suite (`tests/test_install.sh`) covers `install.sh`. New tests needed:

- `tests/test_watch_index.py`: unit tests for PID guard logic (stale PID, live PID, no file), debounce timer reset, ignored path filtering
- Manual integration: start watcher, edit a tracked file, verify index updates within ~2 seconds

## Out of Scope

- Watching untracked files (indexer uses `git ls-files`, watcher follows the same scope)
- Auto-starting the watcher outside of Claude Code sessions (shell aliases, direnv, launchd/systemd are user's choice)
- Replacing the existing `PostToolUse` hook (it stays as-is; minor redundancy is harmless)
