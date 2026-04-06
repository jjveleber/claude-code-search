import sys
import os
import subprocess
import shutil
import chromadb

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
