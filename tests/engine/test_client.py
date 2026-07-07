import json
import os
import socket
import threading
import pytest
from engine import client, paths


@pytest.fixture(autouse=True)
def csh(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    paths.ensure_home()


def fake_daemon(responses):
    """Serve canned responses on the real socket path; returns stop()."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(paths.socket_path()))
    srv.listen(8)
    srv.settimeout(5)
    stop_flag = threading.Event()

    def run():
        i = 0
        while not stop_flag.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            with conn:
                conn.recv(65536)
                resp = responses[min(i, len(responses) - 1)]
                i += 1
                conn.sendall(json.dumps(resp).encode() + b"\n")
    t = threading.Thread(target=run, daemon=True)
    t.start()

    def stop():
        stop_flag.set()
        srv.close()
    return stop


def test_request_round_trip():
    stop = fake_daemon([{"ok": True, "pid": 1}])
    try:
        assert client.request({"cmd": "ping"})["ok"]
    finally:
        stop()


def test_request_raises_when_no_daemon():
    with pytest.raises(client.DaemonUnavailable):
        client.request({"cmd": "ping"})


def test_search_retries_through_warming(monkeypatch):
    monkeypatch.setattr(client, "ensure_daemon", lambda: True)
    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    stop = fake_daemon([
        {"ok": False, "status": "warming"},
        {"ok": False, "status": "warming"},
        {"ok": True, "results": [["a.py", 1, 2, "x", "prod"]]},
    ])
    try:
        r = client.search("/repo", "query")
        assert r["ok"] and r["results"][0][0] == "a.py"
    finally:
        stop()


def test_ensure_daemon_false_without_venv():
    # venv_python() does not exist in the tmp CODE_SEARCH_HOME
    assert client.ensure_daemon() is False
