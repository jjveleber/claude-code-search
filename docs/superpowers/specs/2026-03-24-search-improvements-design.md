# search_code.py Improvements Design

**Date:** 2026-03-24
**Status:** Approved

## Overview

Four targeted improvements to `search_code.py` to reduce token waste and improve result signal. All changes are confined to `search_code.py`. Motivation came from a PrivateBin repo session where unrelated files (e.g., `PurgeLimiter.php`) were surfacing for queries like "Controller".

## Changes

### 1. `--file` flag (file-scoped search)

Add `--file TEXT` CLI argument. When provided, it is passed to ChromaDB's `collection.query()` as a `where` filter:

```python
where={"path": {"$contains": file_filter}}
```

This scopes the vector query to chunks whose `path` metadata contains the given substring, evaluated by ChromaDB before scoring. Example usage:

```
search_code.py "rate limiting" --file Controller.php
```

### 2. Lower default `--top` from 5 to 3

Change the `argparse` default for `--top` from `5` to `3`. Users can still override with `--top N`. This reduces token waste in the common case.

### 3. `--scores` flag (relevance scores)

Add `--scores` boolean flag (off by default). When enabled, the match header includes the raw ChromaDB distance score:

```
MATCH 1: path/to/file.php (lines 10-45)  score: 0.82
```

Scores are raw L2 distances — lower means more similar. No normalization. Helps callers identify noise matches.

### 4. `--truncate N` flag (chunk truncation)

Add `--truncate N` integer flag, default `50`. After merging, if a chunk exceeds N lines, only the first N lines are printed followed by:

```
... (+23 more lines, use Read for full context)
```

Set `--truncate 0` to disable truncation entirely.

## Architecture

### `merge_chunks()` change

Current return type: `[(path, start, end, text), ...]`
New return type: `[(path, start, end, text, score), ...]`

The `score` is the minimum distance value among all ChromaDB chunks that merged into a given group (minimum = best match). ChromaDB returns distances in `results["distances"][0]`.

### New `print_match()` helper

```python
def print_match(i, path, start, end, text, score, *, show_scores, truncate_lines):
```

Handles:
- Header formatting (optionally appending score)
- Truncation logic (cap at `truncate_lines`, emit continuation notice)
- Separator and trailing newline

The main output loop in `search()` calls `print_match()` per result instead of inlining print logic.

### `search()` signature change

```python
def search(query, n_results=3, file_filter=None, show_scores=False, truncate_lines=50):
```

## CLI Interface Summary

```
search_code.py QUERY [--top N] [--file PATH_SUBSTRING] [--scores] [--truncate N]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--top N` | 3 | Number of ChromaDB results to fetch |
| `--file TEXT` | None | Substring filter on file path |
| `--scores` | off | Show relevance distance scores |
| `--truncate N` | 50 | Max lines per merged chunk (0 = off) |

## Out of Scope

- Keyword pre-filter (demoting results with no literal query overlap) — solved more cleanly by `--file`
- Score normalization — raw distances are sufficient for noise detection
- Changes to `index_project.py`
