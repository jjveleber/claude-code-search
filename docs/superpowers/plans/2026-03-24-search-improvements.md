# search_code.py Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--file`, `--scores`, and `--truncate` flags to `search_code.py`, lower the default `--top` from 5 to 3, and refactor result printing into a `print_match()` helper.

**Architecture:** All changes are confined to `search_code.py` (85 lines). `merge_chunks()` gains distance tracking. A new `print_match()` helper centralises output formatting. `search()` gains a `file_filter` parameter implemented via client-side post-query filtering.

**Tech Stack:** Python 3, ChromaDB 1.5.5, pytest

---

## Chunk 1: Tests and implementation

### Task 1: Update `make_results()` helper and existing tests

`tests/test_search_code.py` already exists with a `make_results()` helper that does not include `"distances"`. After the `merge_chunks()` change, it will access `results["distances"][0]` and raise `KeyError`. Fix the helper first so existing tests still pass.

**Files:**
- Modify: `tests/test_search_code.py`

- [ ] **Step 1: Add `distances` to `make_results()` helper**

In `tests/test_search_code.py`, replace the existing `make_results` function (lines 12–18):

```python
def make_results(items, distances=None):
    """Helper: items = list of (path, start, end, text). distances defaults to 0.0 per item."""
    if distances is None:
        distances = [0.0] * len(items)
    return {
        "ids": [[f"{p}::{i}" for i, (p, _, _, _) in enumerate(items)]],
        "metadatas": [[{"path": p, "start_line": s, "end_line": e} for p, s, e, _ in items]],
        "documents": [[t for _, _, _, t in items]],
        "distances": [distances],
    }
```

No other existing tests change — they call `make_results(items)` without distances and will get `[0.0, ...]` defaults.

- [ ] **Step 2: Run existing tests — they should still pass**

```bash
cd /mnt/c/Users/jjvel/PycharmProjects/PythonProject/github/claude-code-search
source .venv/bin/activate && pytest tests/test_search_code.py -v
```

Expected: all existing tests PASS (they still access tuple indices 0–3 which are unchanged).

---

### Task 2: Write failing tests for `merge_chunks()` score support

**Files:**
- Modify: `tests/test_search_code.py` (append)

- [ ] **Step 1: Append score-related tests**

Append to the end of `tests/test_search_code.py`:

```python
# --- merge_chunks score tests ---

def test_merge_chunks_returns_score_as_fifth_element():
    results = make_results(
        [("a.py", 1, 10, "chunk1\n")],
        distances=[0.42],
    )
    merged = merge_chunks(results)
    assert len(merged) == 1
    path, start, end, text, score = merged[0]
    assert score == 0.42


def test_merge_chunks_adjacent_chunks_take_min_score():
    results = make_results(
        [("a.py", 1, 10, "".join(f"line{i}\n" for i in range(1, 11))),
         ("a.py", 11, 20, "".join(f"line{i}\n" for i in range(11, 21)))],
        distances=[0.80, 0.30],
    )
    merged = merge_chunks(results)
    assert len(merged) == 1
    _, _, _, _, score = merged[0]
    assert score == 0.30  # min(0.80, 0.30)


def test_merge_chunks_different_files_preserve_individual_scores():
    results = make_results(
        [("a.py", 1, 5, "chunk_a\n"),
         ("b.py", 1, 5, "chunk_b\n")],
        distances=[0.50, 0.60],
    )
    merged = merge_chunks(results)
    assert len(merged) == 2
    scores = {m[0]: m[4] for m in merged}
    assert scores["a.py"] == 0.50
    assert scores["b.py"] == 0.60


def test_merge_chunks_non_adjacent_same_file_not_merged_scores_preserved():
    results = make_results(
        [("a.py", 1, 5, "first\n"),
         ("a.py", 11, 15, "second\n")],
        distances=[0.10, 0.20],
    )
    merged = merge_chunks(results)
    assert len(merged) == 2
    assert merged[0][4] == 0.10
    assert merged[1][4] == 0.20
```

- [ ] **Step 2: Run tests to confirm new ones fail**

```bash
pytest tests/test_search_code.py -v -k "score"
```

Expected: 4 failures — `merge_chunks` returns 4-element entries, unpacking to 5 fails.

---

### Task 3: Update `merge_chunks()` to return scores

**Files:**
- Modify: `search_code.py:9-33`

- [ ] **Step 1: Replace the `merge_chunks` function**

In `search_code.py`, replace the entire `merge_chunks` function (lines 9–33):

```python
def merge_chunks(results):
    """Group results by file and merge overlapping line ranges, tracking best score."""
    items = []
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        text = results["documents"][0][i]
        dist = results["distances"][0][i]
        items.append((meta["path"], meta["start_line"], meta["end_line"], text, dist))

    items.sort(key=lambda x: (x[0], x[1]))

    merged = []
    for path, start, end, text, score in items:
        if merged and merged[-1][0] == path and start <= merged[-1][2] + 1:
            prev_path, prev_start, prev_end, prev_text, prev_score = merged[-1]
            overlap_line_count = max(0, prev_end - start + 1)
            text_lines = text.splitlines(keepends=True)
            if overlap_line_count > len(text_lines):
                overlap_line_count = 0
            new_text = prev_text + "".join(text_lines[overlap_line_count:])
            merged[-1] = [prev_path, prev_start, max(prev_end, end), new_text, min(prev_score, score)]
        else:
            merged.append([path, start, end, text, score])

    return merged
```

- [ ] **Step 2: Run all `merge_chunks` tests**

```bash
pytest tests/test_search_code.py -v -k "merge_chunks"
```

Expected: all 8 `merge_chunks` tests PASS (4 existing + 4 new).

---

### Task 4: Write failing tests for `print_match()`

**Files:**
- Modify: `tests/test_search_code.py` (append)

- [ ] **Step 1: Append `print_match` tests**

Append to the end of `tests/test_search_code.py`:

```python
# --- print_match tests ---

import io as _io

from search_code import print_match


def _capture(fn, *args, **kwargs):
    import sys
    buf = _io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn(*args, **kwargs)
    finally:
        sys.stdout = old
    return buf.getvalue()


def test_print_match_header_no_scores():
    out = _capture(print_match, 1, "foo.py", 10, 20, "line1\nline2\n", 0.5,
                   show_scores=False, truncate_lines=0)
    assert "MATCH 1: foo.py (lines 10-20)" in out
    assert "score" not in out


def test_print_match_header_with_scores():
    out = _capture(print_match, 1, "foo.py", 10, 20, "line1\nline2\n", 0.5,
                   show_scores=True, truncate_lines=0)
    assert "score: 0.50" in out


def test_print_match_no_truncation_when_at_limit():
    # Exactly 50 lines — must NOT truncate
    text = "".join(f"line{i}\n" for i in range(50))
    out = _capture(print_match, 1, "f.py", 1, 50, text,
                   0.1, show_scores=False, truncate_lines=50)
    assert "more lines" not in out
    assert "line49" in out


def test_print_match_truncates_when_over_limit():
    # 51 lines — must truncate
    text = "".join(f"line{i}\n" for i in range(51))
    out = _capture(print_match, 1, "f.py", 1, 51, text,
                   0.1, show_scores=False, truncate_lines=50)
    assert "+1 more lines" in out
    assert "line50" not in out


def test_print_match_truncate_zero_disables():
    text = "".join(f"line{i}\n" for i in range(100))
    out = _capture(print_match, 1, "f.py", 1, 100, text,
                   0.1, show_scores=False, truncate_lines=0)
    assert "more lines" not in out
    assert "line99" in out
```

- [ ] **Step 2: Run to confirm these tests fail**

```bash
pytest tests/test_search_code.py -v -k "print_match"
```

Expected: 5 failures — `print_match` not yet defined in `search_code.py`.

---

### Task 5: Implement `print_match()`

**Files:**
- Modify: `search_code.py` (insert after `merge_chunks`, before `search`)

- [ ] **Step 1: Add `print_match()` after the `merge_chunks` function**

Insert the following after the closing of `merge_chunks` and before `def search(`:

```python
def print_match(i, path, start, end, text, score, *, show_scores, truncate_lines):
    header = f"MATCH {i}: {path} (lines {start}-{end})"
    if show_scores:
        header += f"  score: {score:.2f}"
    print(header)
    print("-" * 40)

    lines = text.splitlines(keepends=True)
    if truncate_lines > 0 and len(lines) > truncate_lines:
        print("".join(lines[:truncate_lines]), end="")
        remaining = len(lines) - truncate_lines
        print(f"\n... (+{remaining} more lines, use Read for full context)")
    else:
        print(text, end="")
        if not text.endswith("\n"):
            print()

    print()
```

- [ ] **Step 2: Run `print_match` tests**

```bash
pytest tests/test_search_code.py -v -k "print_match"
```

Expected: all 5 PASS.

---

### Task 6: Update `search()` and CLI

**Files:**
- Modify: `search_code.py` (replace `search()` function and `__main__` block)

- [ ] **Step 1: Replace `search()` function and `__main__` block**

In `search_code.py`, replace everything from `def search(` to end of file with:

```python
def search(query, n_results=3, file_filter=None, show_scores=False, truncate_lines=50):
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    emb_fn = embedding_functions.DefaultEmbeddingFunction()
    try:
        collection = client.get_collection(
            name=COLLECTION_NAME, embedding_function=emb_fn
        )
    except Exception as e:
        print(
            f"Error: no index found. Run 'python3 index_project.py' first. ({e})",
            file=sys.stderr,
        )
        sys.exit(1)

    count = collection.count()
    if count == 0:
        print("No results found.")
        sys.exit(2)

    fetch_n = min(n_results * 10, count) if file_filter else min(n_results, count)
    results = collection.query(query_texts=[query], n_results=fetch_n)

    if file_filter:
        keep = [
            i for i, meta in enumerate(results["metadatas"][0])
            if file_filter in meta["path"]
        ]
        if not keep:
            print("No results found.")
            sys.exit(2)
        results = {
            "ids": [[results["ids"][0][i] for i in keep]],
            "metadatas": [[results["metadatas"][0][i] for i in keep]],
            "documents": [[results["documents"][0][i] for i in keep]],
            "distances": [[results["distances"][0][i] for i in keep]],
        }

    merged = merge_chunks(results)
    if not merged:
        print("No results found.")
        sys.exit(2)

    for i, (path, start, end, text, score) in enumerate(merged[:n_results], 1):
        print_match(i, path, start, end, text, score,
                    show_scores=show_scores, truncate_lines=truncate_lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Semantic code search against a ChromaDB index."
    )
    parser.add_argument("query", nargs="+", help="Search query (natural language)")
    parser.add_argument(
        "--top", type=int, default=3, metavar="N",
        help="Number of results to return (default: 3)"
    )
    parser.add_argument(
        "--file", dest="file_filter", default=None, metavar="TEXT",
        help="Case-sensitive substring filter on file path"
    )
    parser.add_argument(
        "--scores", action="store_true", default=False,
        help="Show relevance distance scores in match header"
    )
    parser.add_argument(
        "--truncate", type=int, default=50, metavar="N",
        help="Max lines per result (0 = off, default: 50)"
    )
    args = parser.parse_args()
    search(
        " ".join(args.query),
        n_results=args.top,
        file_filter=args.file_filter,
        show_scores=args.scores,
        truncate_lines=args.truncate,
    )
```

- [ ] **Step 2: Run the full test suite**

```bash
pytest tests/test_search_code.py -v
```

Expected: all tests PASS (existing + new).

- [ ] **Step 3: Commit**

```bash
git add search_code.py tests/test_search_code.py
git commit -m "feat: add --file, --scores, --truncate flags; lower --top default to 3"
```

---

### Task 7: Smoke test the CLI

- [ ] **Step 1: Verify help output**

```bash
source .venv/bin/activate && python3 search_code.py --help
```

Expected output contains all of:
```
--top N
--file TEXT
--scores
--truncate N
```

- [ ] **Step 2: Basic query with default settings**

```bash
python3 search_code.py "merge chunks"
```

Expected: results printed, no score in header, output capped at 50 lines per match.

- [ ] **Step 3: Test `--scores`**

```bash
python3 search_code.py "merge chunks" --scores
```

Expected: match headers contain `score: X.XX`.

- [ ] **Step 4: Test `--truncate 5`**

```bash
python3 search_code.py "merge chunks" --truncate 5
```

Expected: each match shows at most 5 lines, then `... (+N more lines, use Read for full context)` where the chunk exceeds 5 lines.

- [ ] **Step 5: Test `--file` excludes other files**

```bash
python3 search_code.py "results" --file search_code.py --scores
```

Expected: all match paths contain `search_code.py`; no other files appear.
