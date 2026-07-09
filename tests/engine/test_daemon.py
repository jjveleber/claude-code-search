# tests/engine/test_daemon.py
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
import pytest
from engine import paths
from tests.engine.test_repoident import make_repo, _git

pytestmark = pytest.mark.slow


def _req(payload, timeout=120.0):
    """Send one request; retry through 'warming' responses."""
    deadline = time.time() + timeout
    while True:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(paths.socket_path()))
            s.sendall(json.dumps(payload).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        resp = json.loads(buf.split(b"\n")[0])
        if resp.get("status") == "warming" and time.time() < deadline:
            time.sleep(1.0)
            continue
        return resp


@pytest.fixture
def daemon(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    env = dict(os.environ, CODE_SEARCH_HOME=str(tmp_path / "csh"),
               PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    proc = subprocess.Popen([sys.executable, "-m", "engine.daemon"], env=env)
    deadline = time.time() + 30
    while not paths.socket_path().exists():
        assert time.time() < deadline, "daemon socket never appeared"
        assert proc.poll() is None, "daemon died on startup"
        time.sleep(0.2)
    yield proc
    try:
        _req({"cmd": "shutdown"}, timeout=10)
    except OSError:
        pass
    proc.wait(timeout=15)


def test_ping(daemon):
    assert _req({"cmd": "ping"})["ok"]


def test_watch_requires_enabled_repo(daemon, tmp_path):
    repo = make_repo(tmp_path)
    r = _req({"cmd": "watch", "repo": str(repo), "session_pid": os.getpid()})
    assert not r["ok"] and "not enabled" in r["error"]


def test_watch_index_search_unwatch(daemon, tmp_path):
    from engine import registry
    repo = make_repo(tmp_path)
    (repo / "auth.py").write_text("def authenticate(u, p):\n    return True\n")
    _git("add", ".", cwd=repo)
    registry.enable(repo)
    r = _req({"cmd": "watch", "repo": str(repo), "session_pid": os.getpid()})
    assert r["ok"]
    res = _req({"cmd": "search", "repo": str(repo),
                "query": "authentication", "n_results": 5})
    assert res["ok"] and any("auth.py" in row[0] for row in res["results"])
    st = _req({"cmd": "status"})
    assert st["ok"] and len(st["watched"]) == 1
    assert _req({"cmd": "unwatch", "repo": str(repo),
                 "session_pid": os.getpid()})["ok"]


def test_watch_table_persisted(daemon, tmp_path):
    from engine import registry
    repo = make_repo(tmp_path)
    registry.enable(repo)
    _req({"cmd": "watch", "repo": str(repo), "session_pid": os.getpid()})
    table = json.loads(paths.watches_path().read_text())
    assert any(w["path"] == str(repo.resolve()) for w in table["watches"])


def test_singleton_second_daemon_exits(daemon, tmp_path):
    env = dict(os.environ, CODE_SEARCH_HOME=os.environ["CODE_SEARCH_HOME"],
               PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    p2 = subprocess.Popen([sys.executable, "-m", "engine.daemon"], env=env)
    assert p2.wait(timeout=15) == 0  # loser exits cleanly, does NOT touch socket
    assert _req({"cmd": "ping"})["ok"]  # original still serving


def test_prune_loop_waits_for_active_queue_job(monkeypatch, tmp_path):
    """Idle-exit must not fire while an index job is queued/running, even
    with zero watches — killing RepoIndex.index() mid-job loses all
    computed embeddings and the respawned daemon restarts from zero."""
    from engine import daemon as daemon_mod
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    monkeypatch.setattr(daemon_mod, "IDLE_EXIT_SECONDS", 0.3)
    monkeypatch.setattr(daemon_mod, "PRUNE_INTERVAL", 0.1)

    d = daemon_mod.Daemon()
    started = threading.Event()
    gate = threading.Event()
    def slow_job():
        started.set()
        gate.wait(5)
    d.queue.submit("r1", slow_job)
    assert started.wait(5)

    t = threading.Thread(target=d.prune_loop, daemon=True)
    t.start()
    try:
        time.sleep(1.0)   # several prune cycles, well past IDLE_EXIT_SECONDS
        assert not d.shutting_down.is_set(), \
            "daemon idle-exited while an index job was still active"
    finally:
        gate.set()
        d.shutting_down.set()
        t.join(timeout=5)
        d.queue.stop()


def test_prune_loop_idle_exits_once_queue_and_watches_are_empty(monkeypatch, tmp_path):
    from engine import daemon as daemon_mod
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    monkeypatch.setattr(daemon_mod, "IDLE_EXIT_SECONDS", 0.2)
    monkeypatch.setattr(daemon_mod, "PRUNE_INTERVAL", 0.05)

    d = daemon_mod.Daemon()
    t = threading.Thread(target=d.prune_loop, daemon=True)
    t.start()
    try:
        assert d.shutting_down.wait(5), \
            "daemon never idle-exited with an empty queue and no watches"
    finally:
        t.join(timeout=5)
        d.queue.stop()


def test_unwatch_all_removes_watch_and_stops_it(monkeypatch, tmp_path):
    """`disable` uses unwatch_all (not the pid-based unwatch) because the
    CLI's own pid was never registered as a session."""
    from engine import daemon as daemon_mod, registry
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    repo = make_repo(tmp_path)
    reg = registry.enable(repo)

    d = daemon_mod.Daemon()
    r = d.cmd_watch({"repo": str(repo), "session_pid": os.getpid()})
    assert r["ok"]
    watch = d.watches[reg.repo_id]["watch"]

    resp = d.cmd_unwatch_all({"repo": str(repo)})
    assert resp["ok"]
    assert reg.repo_id not in d.watches
    assert watch._stopped is True

    st = d.cmd_status({})
    assert st["watched"] == {}


def test_unwatch_stops_watch_outside_lock(monkeypatch, tmp_path):
    """RepoWatch.stop() joins the observer thread (up to 5s) — it must never
    be called while daemon.lock is held, or all daemon commands stall on
    WSL2 (issue #35)."""
    from engine import daemon as daemon_mod, registry
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    repo = make_repo(tmp_path)
    reg = registry.enable(repo)

    d = daemon_mod.Daemon()
    r = d.cmd_watch({"repo": str(repo), "session_pid": os.getpid()})
    assert r["ok"]

    watch = d.watches[reg.repo_id]["watch"]
    real_stop = watch.stop
    stop_calls = []

    def fake_stop():
        acquired = d.lock.acquire(blocking=False)
        assert acquired, "watch.stop() was called while daemon.lock was held"
        d.lock.release()
        stop_calls.append(True)
        real_stop()

    monkeypatch.setattr(watch, "stop", fake_stop)

    resp = d.cmd_unwatch({"repo": str(repo), "session_pid": os.getpid()})
    assert resp["ok"]
    assert stop_calls == [True]


def test_search_returns_empty_for_genuinely_empty_repo(monkeypatch, tmp_path):
    """A repo whose index has been built with zero chunks must report a
    distinct 'empty' status; a repo whose first index is still
    queued/running must keep reporting 'warming' (issue #29)."""
    from engine import daemon as daemon_mod, registry
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    repo = make_repo(tmp_path)
    reg = registry.enable(repo)

    d = daemon_mod.Daemon()
    d.model_ready.set()

    class FakeRI:
        def count(self):
            return 0

    d.indexes[reg.repo_id] = FakeRI()

    resp = d.cmd_search({"repo": str(repo), "query": "x"})
    assert resp == {"ok": False, "status": "empty"}

    d.queue._pending.add(reg.repo_id)
    try:
        resp = d.cmd_search({"repo": str(repo), "query": "x"})
        assert resp == {"ok": False, "status": "warming"}
    finally:
        d.queue._pending.discard(reg.repo_id)

    # A DIFFERENT repo actively indexing must NOT flip this empty repo to
    # 'warming' — the active-repo check is per-repo, not global.
    d.queue._active_repo = "some-other-repo"
    try:
        resp = d.cmd_search({"repo": str(repo), "query": "x"})
        assert resp == {"ok": False, "status": "empty"}
    finally:
        d.queue._active_repo = None

    # This repo's own first index actively running -> 'warming'.
    d.queue._active_repo = reg.repo_id
    try:
        resp = d.cmd_search({"repo": str(repo), "query": "x"})
        assert resp == {"ok": False, "status": "warming"}
    finally:
        d.queue._active_repo = None
    d.queue.stop()


def test_unwatch_all_drains_active_index_job_before_closing(monkeypatch, tmp_path):
    """A job that already passed the start-of-job disabled-check and is
    mid-write when disable lands must finish before cmd_unwatch_all closes
    the RepoIndex — otherwise the CLI's rmtree (which runs right after
    unwatch_all returns) can race a live write. Wires watch/index state
    directly rather than going through cmd_watch, whose real catch-up job
    would block forever on model_ready (never set in this test) — same
    trick as test_queued_index_job_skipped_for_disabled_repo below."""
    from engine import daemon as daemon_mod, registry
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    repo = make_repo(tmp_path)
    reg = registry.enable(repo)

    d = daemon_mod.Daemon()

    class FakeWatch:
        def __init__(self):
            self.stopped = False
        def stop(self):
            self.stopped = True

    class FakeRI:
        def __init__(self):
            self.closed_at = None
        def close(self):
            self.closed_at = time.time()

    fake_watch = FakeWatch()
    fake_ri = FakeRI()
    with d.lock:
        d.watches[reg.repo_id] = {"path": str(repo), "sessions": {os.getpid()},
                                   "watch": fake_watch}
        d.indexes[reg.repo_id] = fake_ri

    started = threading.Event()
    gate = threading.Event()
    finished_at = {}

    def slow_job():
        started.set()
        gate.wait(5)
        finished_at["t"] = time.time()

    d.queue.submit(reg.repo_id, slow_job)  # simulates a job already in-flight
    assert started.wait(5)

    result = {}
    def call_unwatch_all():
        result["resp"] = d.cmd_unwatch_all({"repo": str(repo)})

    t = threading.Thread(target=call_unwatch_all)
    t.start()
    try:
        time.sleep(0.3)
        assert t.is_alive(), \
            "unwatch_all returned before the active index job finished"
        assert fake_ri.closed_at is None, \
            "RepoIndex was closed while an index job was still writing to it"
    finally:
        gate.set()
        t.join(timeout=5)

    assert not t.is_alive()
    assert result["resp"]["ok"]
    assert fake_watch.stopped is True
    assert not d.queue.active() and not d.queue.pending()
    assert fake_ri.closed_at is not None
    assert fake_ri.closed_at >= finished_at["t"], \
        "RepoIndex was closed before the in-flight job actually finished"

    d.queue.stop()


def test_queued_index_job_skipped_for_disabled_repo(monkeypatch, tmp_path):
    """A job queued for a repo that is no longer registered (disable raced
    a stale on_change / catch-up index) must not recreate the just-purged
    index directory."""
    from engine import daemon as daemon_mod, registry, repoident
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    repo = make_repo(tmp_path)
    (repo / "auth.py").write_text("def f(): pass\n")
    _git("add", ".", cwd=repo)
    r = registry.enable(repo)
    registry.disable(repo)   # repo no longer registered

    d = daemon_mod.Daemon()
    d._queue_index(r.repo_id, repoident.repo_root(repo), r.bm25)
    d.queue.stop()   # drains synchronously; job must skip immediately

    idx_dir = paths.index_dir(r.repo_id)
    assert not idx_dir.exists(), \
        "index job ran against a disabled repo and recreated its index dir"


def test_restore_watches_on_startup(monkeypatch, tmp_path):
    """A pre-existing watches.json with a live pid must be restored, not crash
    the daemon (regression: restore_watches used to call a nonexistent
    self._watch(path, pid))."""
    from engine import registry

    home = tmp_path / "csh"
    monkeypatch.setenv("CODE_SEARCH_HOME", str(home))
    repo = make_repo(tmp_path)
    r = registry.enable(repo)

    watches_file = paths.watches_path()
    watches_file.parent.mkdir(parents=True, exist_ok=True)
    watches_file.write_text(json.dumps({"watches": [
        {"repo_id": r.repo_id, "path": str(repo.resolve()),
         "sessions": [os.getpid()]}]}))

    env = dict(os.environ, CODE_SEARCH_HOME=str(home),
               PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    proc = subprocess.Popen([sys.executable, "-m", "engine.daemon"], env=env)
    try:
        deadline = time.time() + 30
        while not paths.socket_path().exists():
            assert time.time() < deadline, "daemon socket never appeared"
            assert proc.poll() is None, "daemon died on startup"
            time.sleep(0.2)

        st = _req({"cmd": "status"})
        assert st["ok"]
        assert r.repo_id in st["watched"]
        assert st["watched"][r.repo_id]["path"] == str(repo.resolve())
    finally:
        try:
            _req({"cmd": "shutdown"}, timeout=10)
        except OSError:
            pass
        proc.wait(timeout=15)
