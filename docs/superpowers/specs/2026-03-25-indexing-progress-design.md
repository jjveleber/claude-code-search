# Indexing Progress Display

**Date:** 2026-03-25
**Status:** Approved

## Overview

Add in-place terminal progress output to `index_project.py` across all three phases of indexing: loading, scanning, and upserting. No new dependencies.

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

### Phase 1: Loading

```
Loading index...
```

Printed before `collection.get()`. No per-item progress is available from the ChromaDB API, so this is a single static message that remains until the call returns, then ends with a newline.

### Phase 2: Scanning

```
Scanning files... 142 / 4,231
```

Updated on every file in the `for filepath in tracked_files` loop. Uses the length of `tracked_files` (known upfront) as the total.

### Phase 3: Upserting

```
Upserting... batch 2 / 9 (10,000 / 45,033 chunks)
```

Updated at the start of each batch in `_batch_upsert`. The helper receives the current batch index, total batches, current chunk count, and total chunk count so the message is fully informative.

If there are no chunks to upsert, prints `Nothing to upsert.` (with newline, no `\r` needed).

Same pattern applied to `_batch_delete` if there are deletions, showing:

```
Deleting... batch 1 / 2 (5,000 / 7,203 chunks)
```

### Summary Line

The existing summary line is unchanged:

```
Files scanned: 4,231 | Chunks upserted: 45,033 | Chunks deleted: 7,203
```

## Changes

- `index_project.py`: add `_status()` helper; add progress calls in `index_files()`, `_batch_upsert()`, and `_batch_delete()`
- `tests/test_index_project.py`: patch `sys.stdout` or capture output to verify `_status` is called at appropriate points; ensure `\033[K` is present in output

## Non-Goals

- No external dependencies (no `tqdm`, no `rich`)
- No ETA or throughput calculation
- No color or spinner
