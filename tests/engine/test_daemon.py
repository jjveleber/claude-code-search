# tests/engine/test_daemon.py
import json
import os
import socket
import subprocess
import sys
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
