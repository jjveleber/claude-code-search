import sys
import os
import subprocess
import shutil
import chromadb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from search_code import merge_chunks


def make_results(items):
    """Helper: items = list of (path, start, end, text) or (path, start, end, text, file_type).
    Returns a flat list of 5-tuples as expected by merge_chunks."""
    return [(item[0], item[1], item[2], item[3], item[4] if len(item) > 4 else "prod")
            for item in items]


def test_merge_chunks_no_overlap():
    """Two chunks from different files — no merge."""
    results = make_results([
        ("a.py", 1, 5, "a\nb\nc\nd\ne\n"),
        ("b.py", 1, 3, "x\ny\nz\n"),
    ])
    merged = merge_chunks(results)
    assert len(merged) == 2
    assert merged[0][0] == "a.py"
    assert merged[1][0] == "b.py"


def test_merge_chunks_deduplicates_overlap():
    """Two overlapping chunks from the same file — overlap lines must not repeat."""
    # Chunk A: lines 1-12, Chunk B: lines 3-15 (lines 3-12 overlap)
    chunk_a = "".join(f"line{i}\n" for i in range(1, 13))   # lines 1-12
    chunk_b = "".join(f"line{i}\n" for i in range(3, 16))   # lines 3-15
    results = make_results([
        ("f.py", 1, 12, chunk_a),
        ("f.py", 3, 15, chunk_b),
    ])
    merged = merge_chunks(results)
    assert len(merged) == 1
    merged_text = merged[0][3]
    # Each line should appear exactly once
    for i in range(1, 16):
        assert merged_text.count(f"line{i}\n") == 1, f"line{i} duplicated in merged output"
    assert merged[0][1] == 1
    assert merged[0][2] == 15


def test_merge_chunks_adjacent_no_gap():
    """Adjacent chunks (B starts right after A ends) — no lines duplicated."""
    chunk_a = "".join(f"line{i}\n" for i in range(1, 6))   # lines 1-5
    chunk_b = "".join(f"line{i}\n" for i in range(6, 11))  # lines 6-10
    results = make_results([
        ("f.py", 1, 5, chunk_a),
        ("f.py", 6, 10, chunk_b),
    ])
    merged = merge_chunks(results)
    assert len(merged) == 1
    merged_text = merged[0][3]
    for i in range(1, 11):
        assert merged_text.count(f"line{i}\n") == 1


def test_merge_chunks_consistent_types():
    """All entries in the merged list should be the same mutable type (list)."""
    chunk_a = "a\nb\nc\n"
    chunk_b = "b\nc\nd\n"
    results = make_results([
        ("f.py", 1, 3, chunk_a),
        ("f.py", 2, 4, chunk_b),
    ])
    merged = merge_chunks(results)
    for entry in merged:
        assert isinstance(entry, list), f"Expected list, got {type(entry)}"


def run_search(args, cwd=None):
    """Run search_code.py as a subprocess, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, "search_code.py"] + args,
        capture_output=True, text=True, cwd=cwd or os.getcwd(),
    )
    return result.returncode, result.stdout, result.stderr


def copy_search_scripts(tmp_path):
    """Copy search_code.py and its dependencies to tmp_path."""
    shutil.copy("search_code.py", tmp_path / "search_code.py")
    shutil.copy("index_project.py", tmp_path / "index_project.py")
    shutil.copy("chunker.py", tmp_path / "chunker.py")


def test_missing_index_exits_1(tmp_path):
    """search_code.py exits 1 with a clear message when chroma_db doesn't exist."""
    copy_search_scripts(tmp_path)
    rc, stdout, stderr = run_search(["any query"], cwd=str(tmp_path))
    assert rc == 1
    assert "index" in (stdout + stderr).lower()


def test_no_results_exits_2(tmp_path):
    """search_code.py exits 2 with 'No results found.' when index is empty."""
    copy_search_scripts(tmp_path)
    # Create an empty chroma_db
    chromadb.PersistentClient(path=str(tmp_path / "chroma_db")).get_or_create_collection("project_code")
    rc, stdout, stderr = run_search(["any query"], cwd=str(tmp_path))
    assert rc == 2
    assert "no results" in (stdout + stderr).lower()


def test_top_flag_accepted(tmp_path):
    """--top N flag is accepted without error (even on missing index, the arg is parsed first)."""
    copy_search_scripts(tmp_path)
    rc, stdout, stderr = run_search(["--top", "10", "some query"], cwd=str(tmp_path))
    # Exit 1 expected (no index), but NOT exit 2 (arg parse error)
    assert rc != 2, f"argparse failed: {stderr}"


def test_usage_message_on_no_args():
    """Running with no args prints usage and exits non-zero."""
    rc, stdout, stderr = run_search([])
    assert rc != 0
    assert "usage" in (stdout + stderr).lower()


def test_merge_chunks_overlap_exceeds_lines():
    """When overlap count exceeds chunk B's actual line count, content must not be silently dropped."""
    # Chunk A: metadata says lines 1-20, but text only has 5 lines (metadata/text mismatch)
    chunk_a = "".join(f"lineA{i}\n" for i in range(1, 6))   # 5 lines
    # Chunk B: starts at line 3, overlaps with A (prev_end=20, start=3 → overlap=18 > len(chunk_b)=3)
    chunk_b = "".join(f"lineB{i}\n" for i in range(1, 4))   # 3 lines
    results = make_results([
        ("f.py", 1, 20, chunk_a),
        ("f.py", 3, 22, chunk_b),
    ])
    merged = merge_chunks(results)
    assert len(merged) == 1
    assert "lineB1\n" in merged[0][3], "chunk B content was silently dropped"


def test_search_error_includes_original_exception(tmp_path):
    """When get_collection fails, the error message includes the original exception detail."""
    copy_search_scripts(tmp_path)
    # Create chroma_db with a different collection name (not "project_code"),
    # so get_collection("project_code") raises a "collection not found" exception.
    chromadb.PersistentClient(path=str(tmp_path / "chroma_db")).get_or_create_collection("other")
    rc, stdout, stderr = run_search(["any query"], cwd=str(tmp_path))
    assert rc == 1
    output = stdout + stderr
    assert "index" in output.lower()
    # ChromaDB's exception for missing collection includes the collection name.
    # The fixed message should include it; the original static message does not.
    assert "project_code" in output, (
        f"Expected original exception detail in output, got: {output!r}"
    )


def test_index_reflects_edits(tmp_path):
    """After editing a tracked file and re-indexing, the new content appears in the chroma store."""
    import subprocess as _subprocess
    shutil.copy("index_project.py", tmp_path / "index_project.py")
    shutil.copy("chunker.py", tmp_path / "chunker.py")
    _subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    _subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(tmp_path), check=True)
    _subprocess.run(["git", "config", "user.name", "T"], cwd=str(tmp_path), check=True)

    (tmp_path / ".gitignore").write_text("chroma_db/\n")
    source_file = tmp_path / "hello.py"
    source_file.write_text("def greet():\n    return 'hello'\n")
    _subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True)
    _subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(tmp_path), check=True)
    _subprocess.run([sys.executable, "index_project.py"], cwd=str(tmp_path), check=True)

    # Edit the file with a unique marker and re-commit so git tracks the change
    source_file.write_text("def greet():\n    # UNIQUE_EDIT_MARKER_7X3Q\n    return 'hello'\n")
    _subprocess.run(["git", "add", "hello.py"], cwd=str(tmp_path), check=True)
    _subprocess.run(["git", "commit", "-q", "-m", "add marker"], cwd=str(tmp_path), check=True)

    result = _subprocess.run(
        [sys.executable, "index_project.py"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert "upserted: 1" in result.stdout, f"Expected 1 chunk upserted, got: {result.stdout!r}"

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma_db"))
    col = client.get_collection("project_code")
    docs = col.get(where={"path": "hello.py"}, include=["documents"])["documents"]
    assert any("UNIQUE_EDIT_MARKER_7X3Q" in doc for doc in docs), (
        "Edit was not reflected in the index after re-indexing"
    )


def test_index_warns_on_unreadable_file(tmp_path):
    """index_project.py prints a warning to stderr when a file cannot be decoded."""
    import subprocess as _subprocess
    shutil.copy("index_project.py", tmp_path / "index_project.py")
    shutil.copy("chunker.py", tmp_path / "chunker.py")
    # Set up a minimal git repo with one binary (non-UTF-8) file
    _subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    _subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(tmp_path), check=True)
    _subprocess.run(["git", "config", "user.name", "T"], cwd=str(tmp_path), check=True)
    binary_file = tmp_path / "binary.bin"
    binary_file.write_bytes(bytes(range(256)))
    _subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True)
    _subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(tmp_path), check=True)
    result = _subprocess.run(
        [sys.executable, "index_project.py"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "binary.bin" in output, f"Expected skipped-file warning mentioning binary.bin, got: {output!r}"
    assert any(word in output.lower() for word in ("warning", "skipping", "skipped")), (
        f"Expected 'warning', 'skipping', or 'skipped' in output, got: {output!r}"
    )


# ── Chunk 1: search() returns data, format_results() prints ──────────────────

from search_code import format_results


def test_search_returns_list_not_none(tmp_path, monkeypatch):
    """search() returns a list rather than printing and returning None."""
    import chromadb
    from unittest.mock import patch, MagicMock

    monkeypatch.chdir(tmp_path)
    shutil.copy(os.path.join(os.path.dirname(__file__), "..", "search_code.py"), tmp_path / "search_code.py")
    shutil.copy(os.path.join(os.path.dirname(__file__), "..", "index_project.py"), tmp_path / "index_project.py")
    shutil.copy(os.path.join(os.path.dirname(__file__), "..", "chunker.py"), tmp_path / "chunker.py")

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma_db"))
    col = client.get_or_create_collection("project_code")
    col.add(
        ids=["chunk1"],
        documents=["def hello(): pass"],
        embeddings=[[0.1] * 768],
        metadatas=[{"path": "hello.py", "start_line": 1, "end_line": 1,
                    "lang": "python", "file_type": "prod"}],
    )
    (tmp_path / "chroma_db" / "model.txt").write_text("nomic-ai/CodeRankEmbed")

    sys.path.insert(0, str(tmp_path))
    try:
        import importlib
        import search_code as sc
        importlib.reload(sc)
        mock_fn = MagicMock(return_value=[[0.1] * 768])
        with patch.object(sc, '_load_embedding_fn', return_value=mock_fn):
            results = sc.search("hello", n_results=1)
        assert results is not None
        assert isinstance(results, list)
    finally:
        sys.path.pop(0)


def test_format_results_exits_2_on_empty(capsys):
    """format_results([]) exits with code 2 and prints 'No results found.'"""
    with pytest.raises(SystemExit) as exc:
        format_results([])
    assert exc.value.code == 2
    assert "no results" in capsys.readouterr().out.lower()


def test_format_results_prints_match(capsys):
    """format_results prints MATCH header with path, lines, and file_type label."""
    results = [["hello.py", 1, 3, "def hello(): pass\n", "prod"]]
    format_results(results)
    out = capsys.readouterr().out
    assert "MATCH 1" in out
    assert "hello.py" in out
    assert "[prod]" in out


# ── Chunk 2: socket path helper and client routing ────────────────────────────

import json
import socket as _socket
import threading

from search_code import _server_socket_path, _try_server_search


def test_server_socket_path_is_in_tmp():
    """`_server_socket_path()` returns a path under /tmp."""
    p = _server_socket_path("/some/project/chroma_db")
    assert str(p).startswith("/tmp/")


def test_server_socket_path_is_project_specific():
    """`_server_socket_path()` returns different paths for different chroma_db roots."""
    p1 = _server_socket_path("/project/a/chroma_db")
    p2 = _server_socket_path("/project/b/chroma_db")
    assert p1 != p2


def test_server_socket_path_same_project_same_path():
    """Same chroma_db path always produces the same socket path."""
    assert _server_socket_path("/x/chroma_db") == _server_socket_path("/x/chroma_db")


def test_try_server_search_returns_none_when_no_socket(tmp_path):
    """`_try_server_search()` returns None when the socket file doesn't exist."""
    result = _try_server_search("hello", n_results=5, all_files=False, use_bm25=False,
                                socket_path=str(tmp_path / "nonexistent.sock"))
    assert result is None


def test_try_server_search_returns_none_on_connection_refused(tmp_path):
    """`_try_server_search()` returns None when socket file exists but no server listens."""
    sock_path = tmp_path / "dead.sock"
    sock_path.touch()
    result = _try_server_search("hello", n_results=5, all_files=False, use_bm25=False,
                                socket_path=str(sock_path))
    assert result is None


def test_try_server_search_returns_results_from_live_server(tmp_path):
    """`_try_server_search()` returns parsed results when a server responds correctly."""
    sock_path = str(tmp_path / "test.sock")
    expected = [["hello.py", 1, 5, "def hello(): pass", "prod"]]

    def fake_server():
        srv = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)
        conn, _ = srv.accept()
        conn.recv(4096)  # consume the request
        conn.sendall(json.dumps({"results": expected}).encode() + b"\n")
        conn.close()
        srv.close()

    t = threading.Thread(target=fake_server, daemon=True)
    t.start()
    import time; time.sleep(0.05)

    result = _try_server_search("hello", n_results=5, all_files=False, use_bm25=False,
                                socket_path=sock_path)
    assert result == expected


def test_try_server_search_returns_none_on_error_response(tmp_path):
    """`_try_server_search()` returns None when the server responds with an error key."""
    sock_path = str(tmp_path / "err.sock")

    def fake_server():
        srv = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)
        conn, _ = srv.accept()
        conn.recv(4096)
        conn.sendall(json.dumps({"error": "index missing"}).encode() + b"\n")
        conn.close()
        srv.close()

    t = threading.Thread(target=fake_server, daemon=True)
    t.start()
    import time; time.sleep(0.05)

    result = _try_server_search("hello", n_results=5, all_files=False, use_bm25=False,
                                socket_path=sock_path)
    assert result is None
