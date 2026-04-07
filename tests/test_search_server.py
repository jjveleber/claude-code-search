# tests/test_search_server.py
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_server_module_imports():
    """search_server.py can be imported without side effects."""
    import search_server  # noqa: F401


def test_server_exposes_pid_file_constant():
    """PID_FILE constant is accessible."""
    import search_server
    assert hasattr(search_server, "PID_FILE")


def test_server_rejects_second_instance(tmp_path, monkeypatch):
    """main() prints 'already running' and exits 0 when PID lock is held."""
    monkeypatch.chdir(tmp_path)

    import search_server
    from watch_index import acquire_pid_lock

    pid_file = str(tmp_path / ".search_server.pid")
    fh = acquire_pid_lock(pid_file)
    assert fh is not None, "Could not acquire PID lock for test setup"
    try:
        # Patch acquire_pid_lock inside search_server to return None (lock held)
        with patch("search_server.acquire_pid_lock", return_value=None):
            with pytest.raises(SystemExit) as exc:
                search_server.main()
        assert exc.value.code == 0
    finally:
        fh.close()


def test_server_handles_query_and_returns_results(tmp_path):
    """Server accepts a JSON query over Unix socket and returns a JSON response."""
    import chromadb
    import search_server

    sock_path = str(tmp_path / "test.sock")
    chroma_path = str(tmp_path / "chroma_db")

    # Build a minimal index
    client = chromadb.PersistentClient(path=chroma_path)
    col = client.get_or_create_collection("project_code")
    col.add(
        ids=["c1"],
        documents=["def greet(): return 'hello'"],
        embeddings=[[0.1] * 768],
        metadatas=[{"path": "greet.py", "start_line": 1, "end_line": 1,
                    "lang": "python", "file_type": "prod"}],
    )
    (tmp_path / "chroma_db" / "model.txt").write_text("nomic-ai/CodeRankEmbed")

    stop_event = threading.Event()
    mock_emb_fn = MagicMock(return_value=[[0.1] * 768])

    with patch("search_server._load_embedding_fn", return_value=mock_emb_fn):
        server_thread = threading.Thread(
            target=search_server.run_server,
            kwargs={
                "chroma_path": chroma_path,
                "socket_path": sock_path,
                "stop_event": stop_event,
            },
            daemon=True,
        )
        server_thread.start()
        time.sleep(0.3)  # wait for socket to be ready

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect(sock_path)
                req = json.dumps({"query": "greet", "n_results": 1,
                                  "all_files": False, "use_bm25": False})
                s.sendall(req.encode() + b"\n")
                buf = b""
                while b"\n" not in buf:
                    buf += s.recv(4096)
            resp = json.loads(buf.split(b"\n")[0])
            assert "results" in resp
            assert isinstance(resp["results"], list)
        finally:
            stop_event.set()
            server_thread.join(timeout=3.0)


def test_server_cleans_up_socket_on_stop(tmp_path):
    """Socket file is removed when the server stops via stop_event."""
    import chromadb
    import search_server

    sock_path = str(tmp_path / "cleanup.sock")
    chroma_path = str(tmp_path / "chroma_db")

    client = chromadb.PersistentClient(path=chroma_path)
    col = client.get_or_create_collection("project_code")
    col.add(ids=["c1"], documents=["pass"],
            embeddings=[[0.1] * 768],
            metadatas=[{"path": "f.py", "start_line": 1, "end_line": 1,
                        "lang": "python", "file_type": "prod"}])

    stop_event = threading.Event()
    mock_emb_fn = MagicMock(return_value=[[0.1] * 768])

    with patch("search_server._load_embedding_fn", return_value=mock_emb_fn):
        t = threading.Thread(
            target=search_server.run_server,
            kwargs={"chroma_path": chroma_path, "socket_path": sock_path,
                    "stop_event": stop_event},
            daemon=True,
        )
        t.start()
        time.sleep(0.3)
        assert Path(sock_path).exists()
        stop_event.set()
        t.join(timeout=3.0)

    assert not Path(sock_path).exists(), "Socket file should be removed after server stops"
