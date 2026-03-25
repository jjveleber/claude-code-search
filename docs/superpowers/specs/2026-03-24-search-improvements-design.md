# search_code.py Improvements Design

**Date:** 2026-03-24
**Status:** Approved

## Overview

Four targeted improvements to `search_code.py` to reduce token waste and improve result signal. All changes are confined to `search_code.py`. Motivation came from a PrivateBin repo session where unrelated files (e.g., `PurgeLimiter.php`) were surfacing for queries like "Controller".

## Changes

### 1. `--file` flag (file-scoped search)

Add `--file TEXT` CLI argument. When provided, filter results to chunks whose `path` metadata contains `TEXT` as a substring (case-sensitive). Example:

```
search_code.py "rate limiting" --file Controller.php
```

**Implementation:** ChromaDB 1.5.5 does not support `$contains` on metadata fields (only `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte` are valid). The filter is applied client-side:

1. Fetch `min(n_results * 10, collection.count())` candidates from ChromaDB
2. Before merging, discard any result whose `path` does not contain `file_filter` as a substring
3. Merge and return the top results as normal

The `n_results * 10` multiplier ensures enough candidates are available even when the target file represents a small fraction of the index.

### 2. Lower default `--top` from 5 to 3

Change the `argparse` default for `--top` from `5` to `3`. Users can still override with `--top N`. This reduces token waste in the common case.

### 3. `--scores` flag (relevance scores)

Add `--scores` boolean flag (off by default). When enabled, the match header includes the raw ChromaDB L2 distance score:

```
MATCH 1: path/to/file.php (lines 10-45)  score: 0.82
```

Scores are raw L2 distances — lower means more similar. Values are unbounded (not normalized to 0-1). Helps callers identify noise matches.

### 4. `--truncate N` flag (chunk truncation)

Add `--truncate N` integer flag, default `50`. After merging, if a chunk has **more than** N lines (i.e., `line_count > N`), only the first N lines are printed followed by:

```
... (+23 more lines, use Read for full context)
```

Edge cases:
- A chunk with exactly N lines is **not** truncated.
- `--truncate 0` disables truncation entirely (no notice is printed regardless of chunk size).
- The `+N more lines` count is `total_lines - truncate_lines`.
- Lines are split with `str.splitlines(keepends=True)` consistent with the existing merge logic.

## Architecture

### `merge_chunks()` change

Signature is unchanged: `def merge_chunks(results)`. Distances are extracted inside the function from `results["distances"][0]` alongside the existing `results["ids"][0]`, `results["metadatas"][0]`, and `results["documents"][0]` — all parallel lists indexed by position `i`.

Each `items` entry gains a distance value during construction:
```python
items.append((meta["path"], meta["start_line"], meta["end_line"], text, dist))
```

During merging, when two chunks merge, the group score is `min(existing_score, incoming_score)` (lower L2 distance = better match). The merged list entries are 5-element **lists** (consistent with current code which uses mutable lists to update `merged[-1]` in-place).

Current return type: `[(path, start, end, text), ...]`
New return type: `[(path, start, end, text, score), ...]`

Updated signature:
```python
def merge_chunks(results):  # unchanged signature; distances extracted from results["distances"][0]
```

### New `print_match()` helper

```python
def print_match(i, path, start, end, text, score, *, show_scores, truncate_lines):
```

Handles:
- Header: `MATCH {i}: {path} (lines {start}-{end})` — appends `  score: {score:.2f}` if `show_scores`
- Truncation: split `text` with `splitlines(keepends=True)` to get `lines`. If `truncate_lines > 0` and `len(lines) > truncate_lines`, print `"".join(lines[:truncate_lines])` then the continuation notice. Blank lines count toward the total. A chunk with exactly `truncate_lines` lines is not truncated.
- Separator (`"-" * 40`) and trailing newline (unchanged from current behavior)

The main output loop in `search()` must be updated to unpack the 5-element result:
```python
for i, (path, start, end, text, score) in enumerate(merged[:n_results], 1):
    print_match(i, path, start, end, text, score, show_scores=show_scores, truncate_lines=truncate_lines)
```
Note `merged[:n_results]` — this slice replaces the current unsliced iteration and handles the file-filter case where merged may contain more groups than `n_results`. If merged has fewer than `n_results` entries, the slice returns all of them (not an error).

### `search()` signature change

```python
def search(query, n_results=3, file_filter=None, show_scores=False, truncate_lines=50):
```

When `file_filter` is set, `min(n_results * 10, collection.count())` candidates are fetched from ChromaDB, then individual chunks whose `path` does not contain `file_filter` are discarded before the merge step. If no chunks survive the filter, print "No results found." and exit(2). After merging, the result list is sliced to `merged[:n_results]` so the caller always sees at most `n_results` groups regardless of how many candidates were fetched. (Without a file filter, the existing behavior is preserved: ChromaDB returns exactly `n_results` chunks, so the merged list naturally has at most `n_results` groups.)

## CLI Interface Summary

```
search_code.py QUERY [--top N] [--file PATH_SUBSTRING] [--scores] [--truncate N]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--top N` | 3 | Number of results to return after filtering/merging |
| `--file TEXT` | None | Case-sensitive substring filter on file path |
| `--scores` | off | Show raw L2 distance scores in match header |
| `--truncate N` | 50 | Max lines per merged chunk (0 = off) |

## Out of Scope

- Keyword pre-filter (demoting results with no literal query overlap) — solved more cleanly by `--file`
- Score normalization — raw distances are sufficient for noise detection
- Changes to `index_project.py`
