import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from search_code import merge_chunks


def make_results(items):
    """Helper: items = list of (path, start, end, text)."""
    return {
        "ids": [[f"{p}::{i}" for i, (p, _, _, _) in enumerate(items)]],
        "metadatas": [[{"path": p, "start_line": s, "end_line": e} for p, s, e, _ in items]],
        "documents": [[t for _, _, _, t in items]],
    }


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
