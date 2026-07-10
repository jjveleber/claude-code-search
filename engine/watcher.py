"""Per-repo fs watching + single-worker index queue."""
import os
import queue
import subprocess
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

DEBOUNCE_SECONDS = 1.0
IGNORED_DIRS = {"node_modules", "dist", "build", "target", ".git",
                "__pycache__", "chroma_db", ".venv", ".venv-code-search",
                ".tox", ".mypy_cache", ".pytest_cache"}


def should_ignore(root: Path, rel_path: str) -> bool:
    return any(part in IGNORED_DIRS for part in Path(rel_path).parts)


def git_ignored_batch(root: Path, rel_paths: list[str]) -> set[str]:
    """One `git check-ignore --stdin` call for the whole batch."""
    if not rel_paths:
        return set()
    try:
        r = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            input="\n".join(rel_paths), capture_output=True,
            text=True, cwd=root, timeout=10)
        return set(r.stdout.splitlines())
    except (OSError, subprocess.TimeoutExpired):
        return set()


def _needs_polling(root: Path) -> bool:
    """True for filesystems where inotify is silent (WSL2 drvfs/9p)."""
    try:
        with open("/proc/mounts") as f:
            mounts = [line.split() for line in f]
    except OSError:
        return False
    best = ("", "")
    for parts in mounts:
        if len(parts) >= 3 and str(root).startswith(parts[1]) \
                and len(parts[1]) > len(best[0]):
            best = (parts[1], parts[2])
    return best[1] in ("9p", "drvfs", "cifs", "nfs", "fuse.drvfs")


class IndexQueue:
    """Single worker; per-repo coalescing so N repos can't starve search."""

    def __init__(self):
        self._q = queue.Queue()
        self._pending = set()
        self._active_repo = None   # repo_id the worker is currently indexing
        self._failed = {}          # repo_id -> error string, last index failed
        self._lock = threading.Lock()
        self._stop = object()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, repo_id: str, fn):
        with self._lock:
            if repo_id in self._pending:
                return
            self._pending.add(repo_id)
        self._q.put((repo_id, fn))

    def _run(self):
        while True:
            item = self._q.get()
            if item is self._stop:
                return
            repo_id, fn = item
            with self._lock:
                self._pending.discard(repo_id)
                self._active_repo = repo_id
            try:
                fn()
            except Exception as e:
                print(f"[index-queue] {repo_id}: {type(e).__name__}: {e}",
                      flush=True)
                # Record the failure in the SAME locked section that clears
                # active_repo, so a search racing this can never observe
                # "not active, not pending, not failed" (false "empty").
                with self._lock:
                    self._failed[repo_id] = f"{type(e).__name__}: {e}"
                    self._active_repo = None
            else:
                with self._lock:
                    self._failed.pop(repo_id, None)
                    self._active_repo = None

    def stop(self):
        self._q.put(self._stop)
        self._worker.join(timeout=10)

    def pending(self):
        with self._lock:
            return sorted(self._pending)

    def active(self):
        with self._lock:
            return self._active_repo is not None

    def active_repo(self):
        """repo_id the worker is currently indexing, or None. Unlike active(),
        this lets a caller ask about a SPECIFIC repo rather than "any job"."""
        with self._lock:
            return self._active_repo

    def failed(self, repo_id):
        """Error string from repo_id's last index run, or None if its last
        run (if any) succeeded."""
        with self._lock:
            return self._failed.get(repo_id)


class _Handler(FileSystemEventHandler):
    def __init__(self, watch):
        self._w = watch

    def on_any_event(self, event):
        if event.is_directory or event.event_type in ("opened", "closed_no_write"):
            return
        try:
            rel = str(Path(event.src_path).resolve()
                      .relative_to(self._w.root))
        except ValueError:
            return
        if should_ignore(self._w.root, rel):
            return
        self._w._enqueue(rel)


class RepoWatch:
    def __init__(self, root: Path, on_change):
        self.root = Path(root).resolve()
        self._on_change = on_change
        self._batch: list[str] = []
        self._timer = None
        self._stopped = False
        self._lock = threading.Lock()
        cls = PollingObserver if _needs_polling(self.root) else Observer
        self._observer = cls()
        self._observer.schedule(_Handler(self), path=str(self.root),
                                recursive=True)
        self._observer.start()

    def _enqueue(self, rel_path: str):
        with self._lock:
            self._batch.append(rel_path)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self):
        with self._lock:
            if self._stopped:
                return   # Timer.cancel() is a no-op once _flush has started
            batch, self._batch = self._batch, []
        ignored = git_ignored_batch(self.root, batch)
        if any(p not in ignored for p in batch):
            self._on_change()

    def stop(self):
        with self._lock:
            self._stopped = True
            if self._timer is not None:
                self._timer.cancel()
        self._observer.stop()
        self._observer.join(timeout=5)
