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
- If the file exists but the process is dead (stale PID), overwrite the file and start normally
- Otherwise write the current PID to `.watch_index.pid`
- On clean exit or signal (SIGINT, SIGTERM), delete `.watch_index.pid`

**Watcher:**
- `watchdog` Observer watching the project root recursively
- Event handler ignores:
  - Directories (by prefix): `chroma_db/`, `.venv/`, `__pycache__/`, `.git/` — matching the `CHROMA_PATH = "./chroma_db"` constant in `index_project.py`
  - Files (by exact name): `.watch_index.pid`, `.watch_index.log`
- Responds to file created, modified, moved, and deleted events

**Debounce:**
- Uses `threading.Timer` with a 1-second delay
- Each new event resets the timer
- When the timer fires, check if a previous `index_project.py` subprocess is still running; if so, skip this trigger (do not queue or kill)
- Otherwise run `.venv/bin/python3 index_project.py` as a subprocess
- Prevents thrashing during rapid multi-file saves

**Logging:**
- All output (stdout + stderr from `index_project.py`, watcher status messages) is appended to `.watch_index.log` in the project root
- This ensures output is not lost when running as a background process (`&`)
- Startup prints `Watching for changes. Log: .watch_index.log` to the terminal before forking to background

### `install.sh` (modified)

- Add `watchdog>=3.0` to the pip install command alongside `chromadb`
- Add `watch_index.py` to the file download loop using the same `BASE_URL` as `index_project.py` and `search_code.py`

### `CLAUDE.md` (modified)

Add a Session Startup section instructing Claude to run at session open. The watcher is started with `&` to background it and output redirected to its log file:

```markdown
## Session Startup
At the start of each session:
1. Run `.venv/bin/python3 index_project.py` to ensure the index is fresh
2. Run `.venv/bin/python3 watch_index.py >> .watch_index.log 2>&1 &` to start the watcher in the background
```

The PID guard in `watch_index.py` ensures a second watcher is never started if one is already running.

### `README.md` (modified)

Update the Uninstall section:

**Stop the watcher first:**
```bash
pkill -f watch_index.py
```

**rm command:**
```bash
rm -rf index_project.py search_code.py watch_index.py chroma_db/ .venv/ .watch_index.pid .watch_index.log
```

**Additional manual steps** (same pattern as existing hook/CLAUDE.md cleanup):
- Remove the Session Startup block from `CLAUDE.md`
- Remove the `PostToolUse` hook entry from `.claude/settings.local.json`

## Data Flow

```
File change on disk
  → watchdog detects event
  → event handler filters ignored paths
  → debounce timer resets (1s)
  → timer fires → check if index_project.py already running
    → if running: skip
    → if not running: subprocess .venv/bin/python3 index_project.py >> .watch_index.log 2>&1
  → index_project.py upserts only changed chunks
```

## Error Handling

- If `index_project.py` exits non-zero, the error is logged to `.watch_index.log` and the watcher continues (does not crash)
- Stale PID file (process dead): overwrite and start normally
- Signal handlers (SIGINT, SIGTERM) ensure `.watch_index.pid` is always cleaned up on exit

## Testing

Existing test suite (`tests/test_install.sh`) covers `install.sh`. New tests needed:

- `tests/test_watch_index.py`: unit tests for:
  - PID guard: stale PID (process dead), live PID (already running), no file
  - Debounce: rapid events collapse to single trigger
  - Ignored path filtering: `chroma_db/`, `.venv/`, `.watch_index.pid` are ignored; regular files are not
  - Subprocess overlap: if `index_project.py` is already running, trigger is skipped
  - Non-zero exit from `index_project.py`: watcher logs and continues without crashing
- Manual integration: start watcher, edit a tracked file, verify `.watch_index.log` shows a re-index within ~2 seconds

## Out of Scope

- Watching untracked files (indexer uses `git ls-files`, watcher follows the same scope)
- Auto-starting the watcher outside of Claude Code sessions (shell aliases, direnv, launchd/systemd are user's choice)
- Replacing the existing `PostToolUse` hook (it stays as-is; minor redundancy is harmless)
