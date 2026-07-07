"""Socket client for the daemon. Stdlib only — used by hooks."""
import json
import os
import socket
import subprocess
import time
from pathlib import Path

from engine import paths

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


class DaemonUnavailable(Exception):
    pass


def request(payload: dict, timeout: float = 30.0) -> dict:
    sp = paths.socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(sp))
            s.sendall(json.dumps(payload).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.split(b"\n")[0])
    except (OSError, json.JSONDecodeError) as e:
        raise DaemonUnavailable(str(e))


def ensure_daemon() -> bool:
    try:
        if request({"cmd": "ping"}, timeout=3.0).get("ok"):
            return True
    except DaemonUnavailable:
        pass
    py = paths.venv_python()
    if not py.exists():
        return False
    paths.ensure_home()
    log = open(paths.logs_dir() / "daemon.log", "a")
    env = dict(os.environ, PYTHONPATH=str(PLUGIN_ROOT))
    subprocess.Popen([str(py), "-m", "engine.daemon"], env=env,
                     stdout=log, stderr=subprocess.STDOUT,
                     start_new_session=True)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if request({"cmd": "ping"}, timeout=2.0).get("ok"):
                return True
        except DaemonUnavailable:
            time.sleep(0.3)
    return False


def search(repo, query, n_results=5, all_files=False, use_bm25=False,
           session_id="unknown", warm_deadline=300.0):
    payload = {"cmd": "search", "repo": str(repo), "query": query,
               "n_results": n_results, "all_files": all_files,
               "use_bm25": use_bm25, "session_id": session_id}
    spawns = 0
    deadline = time.time() + warm_deadline
    while True:
        try:
            resp = request(payload, timeout=60.0)
        except DaemonUnavailable:
            spawns += 1
            if spawns > 3 or not ensure_daemon():
                raise
            continue
        if resp.get("status") == "warming" and time.time() < deadline:
            time.sleep(2.0)
            continue
        return resp


def watch(repo, session_pid):
    if not ensure_daemon():
        raise DaemonUnavailable("venv missing — run: code-search setup")
    return request({"cmd": "watch", "repo": str(repo),
                    "session_pid": session_pid}, timeout=30.0)


def unwatch(repo, session_pid):
    try:
        return request({"cmd": "unwatch", "repo": str(repo),
                        "session_pid": session_pid}, timeout=5.0)
    except DaemonUnavailable:
        return {"ok": False, "error": "daemon not running"}


def status():
    if not ensure_daemon():
        raise DaemonUnavailable("venv missing — run: code-search setup")
    return request({"cmd": "status"}, timeout=10.0)
