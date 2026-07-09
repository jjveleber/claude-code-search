# engine/daemon.py
"""Multiplexed search daemon. One per CODE_SEARCH_HOME."""
import fcntl
import json
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from engine import paths, registry, repoident
from engine.repo_index import RepoIndex, clone_index, IndexMissingError
from engine.watcher import IndexQueue, RepoWatch

IDLE_EXIT_SECONDS = 600
PRUNE_INTERVAL = 60
LOG_ROTATE_BYTES = 10 * 1024 * 1024
HANDLER_DRAIN_TIMEOUT = 5.0   # bounded wait for in-flight handlers at shutdown


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_pid_lock(pid_file: Path):
    """flock singleton — copied pattern from watch_index.py."""
    try:
        fh = open(pid_file, "a")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.seek(0); fh.truncate(); fh.write(str(os.getpid())); fh.flush()
        return fh
    except OSError:
        try:
            fh.close()
        except Exception:
            pass
        return None


class Daemon:
    def __init__(self):
        self.started = time.time()
        self.lock = threading.Lock()          # guards watches/indexes dicts
        self.watches = {}    # repo_id -> {"path", "sessions": set[int], "watch": RepoWatch}
        self.indexes = {}    # repo_id -> RepoIndex
        self.queue = IndexQueue()
        self.model_ready = threading.Event()
        self.model_loading = False
        self.shutting_down = threading.Event()
        self._handlers = set()                 # live request-handler threads
        self._handlers_lock = threading.Lock()

    # ---- model warmup ------------------------------------------------
    def _ensure_model_async(self):
        with self.lock:
            if self.model_ready.is_set() or self.model_loading:
                return
            self.model_loading = True

        def load():
            try:
                from engine.embedding import HFCodeEmbeddingFunction
                HFCodeEmbeddingFunction("nomic-ai/CodeRankEmbed")
                self.model_ready.set()
            except Exception as e:
                with self.lock:
                    self.model_loading = False
                print(f"[model-load] {type(e).__name__}: {e}", flush=True)
        threading.Thread(target=load, daemon=True).start()

    # ---- watch table persistence --------------------------------------
    def _persist_watches(self):
        data = {"watches": [
            {"repo_id": rid, "path": w["path"],
             "sessions": sorted(w["sessions"])}
            for rid, w in self.watches.items()]}
        tmp = paths.watches_path().with_suffix(".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data))
        os.replace(tmp, paths.watches_path())

    def restore_watches(self):
        try:
            data = json.loads(paths.watches_path().read_text())
        except (OSError, json.JSONDecodeError):
            return
        for w in data.get("watches", []):
            live = [p for p in w["sessions"] if _pid_alive(p)]
            if live and Path(w["path"]).exists():
                for pid in live:
                    try:
                        self.cmd_watch({"repo": w["path"], "session_pid": pid})
                    except Exception as e:
                        print(f"[restore_watches] {w['path']}: "
                              f"{type(e).__name__}: {e}", flush=True)

    def drain_handlers(self, deadline: float):
        """Wait (bounded by deadline) for in-flight request handlers to finish,
        so shutdown doesn't cut a response mid-send."""
        with self._handlers_lock:
            threads = list(self._handlers)
        for t in threads:
            remaining = deadline - time.time()
            if remaining > 0:
                t.join(timeout=remaining)

    # ---- repo helpers --------------------------------------------------
    def _repo_index(self, rid: str, root: Path) -> RepoIndex:
        with self.lock:
            if rid not in self.indexes:
                self.indexes[rid] = RepoIndex(root, paths.index_dir(rid))
            return self.indexes[rid]

    def _queue_index(self, rid: str, root: Path, bm25: bool, seed_from: Path = None):
        ri = self._repo_index(rid, root)
        def job():
            # Re-check at job start (not just at submit time): the repo may
            # have been disabled between when this job was queued/coalesced
            # and when the worker actually picks it up (e.g. disable racing
            # a stale on_change), which would otherwise resurrect an index
            # that was just purged.
            r = registry.resolve(root)
            if not (r.family_enabled and r.registered):
                return
            # Seed a fresh worktree from the main index here, on the single
            # queue worker, so the copy serializes behind any active reindex
            # (no torn sqlite) and two racing watches can't double-clone.
            my_idx = paths.index_dir(rid)
            if seed_from is not None and seed_from.exists() and not my_idx.exists():
                clone_index(seed_from, my_idx)
            self.model_ready.wait()
            ri.index(use_bm25=bm25)
            ri.invalidate_caches()
        self.queue.submit(rid, job)

    def _on_repo_change(self, rid: str, root: Path, bm25: bool):
        # Guard the fs-watch callback itself too: RepoWatch.stop() can race
        # a debounce flush already in flight (see RepoWatch._stopped), so a
        # stale on_change can still fire right after disable/unwatch_all.
        r = registry.resolve(root)
        if not (r.family_enabled and r.registered):
            return
        self._queue_index(rid, root, bm25)

    # ---- commands -------------------------------------------------------
    def cmd_ping(self, req):
        return {"ok": True, "pid": os.getpid()}

    def cmd_watch(self, req):
        root = Path(req["repo"])
        r = registry.resolve(root)
        if not r.family_enabled:
            return {"ok": False, "error": "not enabled"}
        seed_from = None
        if not r.registered:
            r = registry.register_worktree(root)
            # seed from main worktree's index if it exists — but do the copy
            # on the queue worker (see _queue_index), not inline here, so it
            # can't clone a torn sqlite mid-reindex.
            main_idx = paths.index_dir(r.main_repo_id)
            my_idx = paths.index_dir(r.repo_id)
            if r.main_repo_id != r.repo_id and main_idx.exists() \
                    and not my_idx.exists():
                seed_from = main_idx
        self._ensure_model_async()
        pid = int(req["session_pid"])
        resolved_root = repoident.repo_root(root)
        with self.lock:
            w = self.watches.get(r.repo_id)
            if w is None:
                watch = RepoWatch(resolved_root, on_change=lambda rid=r.repo_id,
                                  rr=resolved_root, b=r.bm25:
                                  self._on_repo_change(rid, rr, b))
                w = {"path": str(resolved_root), "sessions": set(),
                     "watch": watch}
                self.watches[r.repo_id] = w
            w["sessions"].add(pid)
            self._persist_watches()
        self._queue_index(r.repo_id, resolved_root, r.bm25,
                          seed_from=seed_from)  # seed (if new) + catch-up
        return {"ok": True, "repo_id": r.repo_id}

    def cmd_unwatch(self, req):
        root = Path(req["repo"])
        rid = repoident.repo_id(repoident.repo_root(root) or root)
        pid = int(req["session_pid"])
        to_stop = []
        with self.lock:
            w = self.watches.get(rid)
            if w:
                w["sessions"].discard(pid)
                if not w["sessions"]:
                    to_stop.append(w["watch"])
                    del self.watches[rid]
                    ri = self.indexes.pop(rid, None)
                    if ri:
                        ri.close()
                self._persist_watches()
        for w in to_stop:
            w.stop()
        return {"ok": True}

    def cmd_unwatch_all(self, req):
        """Unconditionally drop the watch for a repo, regardless of which
        session pids hold it. Used by `disable` — the CLI invocation is
        never itself a registered session pid, so the per-pid cmd_unwatch
        above can't remove the watch; leaving it live lets on_change keep
        queuing indexes after disable/purge."""
        root = Path(req["repo"])
        rid = repoident.repo_id(repoident.repo_root(root) or root)
        with self.lock:
            w = self.watches.pop(rid, None)
            self._persist_watches()
        if w:
            w["watch"].stop()
            # A job that already passed the start-of-job registry re-check
            # (see _queue_index) and is mid-ri.index() when disable lands is
            # not stopped by RepoWatch.stop() above — that only blocks NEW
            # jobs from being queued via on_change. If we closed the
            # RepoIndex (or let the CLI's rmtree run) while that job is
            # still writing through it, we'd get a torn write or a purged
            # dir that gets partially repopulated. So: wait for the queue to
            # go idle before closing.
            #
            # disable is rare and not latency-critical, so waiting for ANY
            # active/pending job (not strictly this rid) is an acceptable
            # simplification over threading an active-rid through
            # IndexQueue — it's a single global worker, so "queue idle" is
            # cheap to observe and still guarantees ri.close() below can
            # never race a live write for this repo. Bounded so a
            # genuinely stuck worker can't hang disable forever; generous
            # enough to cover a job parked in model_ready.wait(). Must NOT
            # hold daemon.lock while waiting — other commands (search,
            # status, other watches) need it in the meantime.
            deadline = time.time() + 120
            while (self.queue.active() or self.queue.pending()) \
                    and time.time() < deadline:
                time.sleep(0.1)
            if self.queue.active() or self.queue.pending():
                print("[unwatch_all] timed out waiting for index queue to "
                      "drain; proceeding anyway", flush=True)
            with self.lock:
                ri = self.indexes.pop(rid, None)
            if ri:
                ri.close()
        return {"ok": True}

    def cmd_search(self, req):
        root = Path(req["repo"])
        r = registry.resolve(root)
        if not r.family_enabled or not r.registered:
            return {"ok": False, "error": "not enabled"}
        self._ensure_model_async()
        if not self.model_ready.is_set():
            return {"ok": False, "status": "warming"}
        ri = self._repo_index(r.repo_id, repoident.repo_root(root))
        if ri.count() == 0:
            # "empty" only if THIS repo's first index has finished (or was
            # never queued) — a global active() check would mis-report a
            # genuinely-empty repo as "warming" whenever any OTHER repo is
            # indexing, which is the daemon's normal multi-repo state.
            if r.repo_id in self.queue.pending() \
                    or self.queue.active_repo() == r.repo_id:
                return {"ok": False, "status": "warming"}
            return {"ok": False, "status": "empty"}
        t0 = time.time()
        try:
            results = ri.search(
                req["query"], n_results=req.get("n_results", 5),
                all_files=req.get("all_files", False),
                use_bm25=req.get("use_bm25", False))
        except IndexMissingError:
            return {"ok": False, "status": "warming"}
        self._log_search(r.repo_id, req, results, time.time() - t0)
        return {"ok": True, "results": results}

    def cmd_reindex(self, req):
        root = Path(req["repo"])
        r = registry.resolve(root)
        if not r.registered:
            return {"ok": False, "error": "not enabled"}
        self._ensure_model_async()
        self._queue_index(r.repo_id, repoident.repo_root(root), r.bm25)
        return {"ok": True}

    def cmd_status(self, req):
        with self.lock:
            watched = {rid: {"path": w["path"],
                             "sessions": sorted(w["sessions"])}
                       for rid, w in self.watches.items()}
        return {"ok": True, "watched": watched,
                "uptime_s": int(time.time() - self.started),
                "queue_pending": self.queue.pending()}

    # ---- logging --------------------------------------------------------
    def _log_search(self, rid, req, results, secs):
        log = paths.logs_dir() / "search_usage.jsonl"
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            if log.exists() and log.stat().st_size > LOG_ROTATE_BYTES:
                os.replace(log, log.with_suffix(".jsonl.1"))
            event = {"timestamp": datetime.now(timezone.utc).isoformat(),
                     "event_type": "search", "repo_id": rid,
                     "query": req["query"],
                     "result_count": len(results),
                     "latency_ms": int(secs * 1000),
                     "use_bm25": req.get("use_bm25", False),
                     "session_id": req.get("session_id", "unknown")}
            with log.open("a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            pass

    # ---- housekeeping -----------------------------------------------------
    def prune_loop(self):
        idle_since = time.time()
        while not self.shutting_down.wait(PRUNE_INTERVAL):
            to_stop = []
            with self.lock:
                for rid in list(self.watches):
                    w = self.watches[rid]
                    w["sessions"] = {p for p in w["sessions"] if _pid_alive(p)}
                    if not w["sessions"]:
                        to_stop.append(w["watch"])
                        del self.watches[rid]
                        ri = self.indexes.pop(rid, None)
                        if ri:
                            ri.close()
                self._persist_watches()
                empty = not self.watches
            for w in to_stop:
                w.stop()
            # A pending/active index job must block idle-exit even with no
            # watches left: RepoIndex.index() computes all embeddings before
            # the first upsert, so killing it mid-job discards everything
            # and the respawned daemon restarts from zero.
            queue_busy = bool(self.queue.pending()) or self.queue.active()
            if empty and not queue_busy:
                if time.time() - idle_since > IDLE_EXIT_SECONDS:
                    self.shutting_down.set()
            else:
                idle_since = time.time()

    # ---- request dispatch --------------------------------------------------
    def handle(self, req: dict) -> dict:
        cmd = req.get("cmd")
        fn = getattr(self, f"cmd_{cmd}", None)
        if cmd == "shutdown":
            self.shutting_down.set()
            return {"ok": True}
        if fn is None:
            return {"ok": False, "error": f"unknown cmd: {cmd}"}
        try:
            return fn(req)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _serve(daemon: Daemon, srv: socket.socket):
    srv.settimeout(1.0)
    while not daemon.shutting_down.is_set():
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        t = threading.Thread(target=_handle_conn, args=(daemon, conn),
                             daemon=True)
        with daemon._handlers_lock:
            daemon._handlers.add(t)
        t.start()


def _handle_conn(daemon, conn):
    try:
        with conn:
            conn.settimeout(30.0)
            buf = b""
            try:
                while b"\n" not in buf:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    buf += chunk
                req = json.loads(buf.split(b"\n")[0])
                resp = daemon.handle(req)
                conn.sendall(json.dumps(resp).encode() + b"\n")
            except (OSError, json.JSONDecodeError):
                pass
    finally:
        with daemon._handlers_lock:
            daemon._handlers.discard(threading.current_thread())


def main():
    paths.ensure_home()
    lock_fh = acquire_pid_lock(paths.pid_path())
    if lock_fh is None:
        sys.exit(0)   # another daemon holds the lock; never touch its socket

    daemon = Daemon()
    sock_final = paths.socket_path()
    sock_tmp = sock_final.with_suffix(f".tmp{os.getpid()}")
    for p in (sock_tmp,):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock_tmp))
    srv.listen(64)
    os.rename(sock_tmp, sock_final)   # atomic claim — no unlink-before-bind race

    def _term(signum=None, frame=None):
        daemon.shutting_down.set()
    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)

    daemon.restore_watches()
    pruner = threading.Thread(target=daemon.prune_loop, daemon=True)
    pruner.start()

    _serve(daemon, srv)

    # shutdown order: unlink socket -> drain in-flight handlers -> stop
    # watches -> persist -> release lock
    try:
        os.unlink(sock_final)
    except FileNotFoundError:
        pass
    daemon.drain_handlers(time.time() + HANDLER_DRAIN_TIMEOUT)
    with daemon.lock:
        to_stop = [w["watch"] for w in daemon.watches.values()]
        daemon._persist_watches()
    for w in to_stop:
        w.stop()
    daemon.queue.stop()
    lock_fh.close()


if __name__ == "__main__":
    main()
