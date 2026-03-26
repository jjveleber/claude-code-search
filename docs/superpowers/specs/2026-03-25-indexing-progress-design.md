# Indexing Progress Display

**Date:** 2026-03-25
**Status:** Approved

## Overview

Add in-place terminal progress output to `index_project.py` across all four phases of indexing: loading, scanning, upserting, and deleting. No new dependencies.

## Problem

The indexer runs silently until it prints a single summary line at the end. On large repos this means the user sees nothing for potentially tens of seconds or longer, with no indication of which phase is running or how far along it is.

## Design

### Helper: `_status(msg)`

A small private helper that writes a progress line in-place:

```python
def _status(msg):
    print(f"\r\033[K{msg}", end="", flush=True)
```

- `\r` returns the cursor to the start of the line
- `\033[K` (ANSI erase-to-end-of-line) clears any leftover characters from a longer previous message
- `end=""` suppresses the newline so the line is overwritten on the next call
- `flush=True` ensures output appears immediately

Each phase ends with a plain `print()` to emit a newline and leave the final state visible on screen.

ANSI output is always emitted regardless of TTY; non-TTY handling is out of scope.

### Phase 1: Loading

```
Loading index...
```

Printed before `collection.get()`. No per-item progress is available from the ChromaDB API, so this is a single static message. The terminating `print()` is placed immediately after `collection.get()` returns — before `git_indexable_files()` is called — so Phase 1 represents only the ChromaDB fetch.

### Phase 2: Scanning

```
Scanning files... 142 / 4,231
```

Updated on every file in the `for filepath in tracked_files` loop. Uses `len(tracked_files)` (known upfront) as the total. Numbers are formatted with thousands separators using `f"{n:,}"`.

### Phase 3: Upserting

```
Upserting... batch 2 / 9 (10,000 / 45,033 chunks)
```

Updated at the start of each batch in `_batch_upsert`. The `_batch_upsert` and `_batch_delete` signatures do not change — all progress data (current offset, total items, batch size) is already available inside both functions from existing parameters (`ids`, `CHROMA_MAX_BATCH`). Numbers formatted with `f"{n:,}"`.

If there are no chunks to upsert, prints `Nothing to upsert.` (plain `print()`, no `\r` needed).

### Phase 4: Deleting

```
Deleting... batch 1 / 2 (5,000 / 7,203 chunks)
```

Same pattern as Phase 3, applied to `_batch_delete`. If there are no chunks to delete, the function returns silently (no output).

### Summary Line

The existing summary line is unchanged:

```
Files scanned: 4,231 | Chunks upserted: 45,033 | Chunks deleted: 7,203
```

## Changes

- `index_project.py`: add `_status()` helper; add progress calls in `index_files()`, `_batch_upsert()`, and `_batch_delete()`
- `tests/test_index_project.py`:
  - Test `_status()` directly (unit test, no mocking needed) to verify `\r\033[K` prefix and `flush=True`
  - Test progress call sites by mocking `chromadb.PersistentClient`, `DefaultEmbeddingFunction`, and `subprocess.run` — same pattern as existing tests — then assert `_status` is called with expected messages. Do not use integration-style tests that touch real ChromaDB.

## Non-Goals

- No external dependencies (no `tqdm`, no `rich`)
- No ETA or throughput calculation
- No color or spinner
- No TTY detection
