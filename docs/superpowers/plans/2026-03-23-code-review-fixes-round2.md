# Code Review Fixes Round 2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 bugs identified in second code review — 3 in Python scripts (search_code.py, index_project.py) and 3 in install.sh.

**Architecture:** Two independent chunks: Python fixes first (TDD with pytest), then shell fixes (TDD with test_install.sh). Each chunk is fully tested and committed before the next begins.

**Tech Stack:** Python 3.9+, ChromaDB ≥ 1.0, bash, pytest.

---

## Files

| File | Action | Purpose |
|---|---|---|
| `search_code.py` | Modify | Clamp `overlap_line_count`; surface exception detail |
| `index_project.py` | Modify | Warn on skipped files |
| `install.sh` | Modify | Remove `VIRTUAL_ENV` fallback; add `trap`; guard index rebuild |
| `tests/test_search_code.py` | Modify | Tests for overlap clamp, exception message, index warnings |
| `tests/test_install.sh` | Modify | Update Test 6; add Test 7 (VIRTUAL_ENV ignored); add Test 8 (idempotent index) |

---

## Chunk 1: Python fixes (search_code.py + index_project.py)

### Task 1: Clamp overlap_line_count to prevent silent data loss (search_code.py)

**Issue:** `text_lines[overlap_line_count:]` silently returns empty when `overlap_line_count > len(text_lines)`, dropping chunk B's unique content with no error.

**Files:**
- Modify: `search_code.py` (lines 24–26 in `merge_chunks`)
- Modify: `tests/test_search_code.py` (append 1 test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_search_code.py`:

```python
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
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
.venv/bin/pytest tests/test_search_code.py::test_merge_chunks_overlap_exceeds_lines -v
```

Expected: FAIL — `overlap_line_count=18 > len(chunk_b)=3`, slice returns empty, assertion fails.

- [ ] **Step 3: Fix merge_chunks — add clamp after computing overlap**

In `search_code.py`, replace lines 24–26:

```python
            overlap_line_count = max(0, prev_end - start + 1)
            text_lines = text.splitlines(keepends=True)
            new_text = prev_text + "".join(text_lines[overlap_line_count:])
```

With:

```python
            overlap_line_count = max(0, prev_end - start + 1)
            text_lines = text.splitlines(keepends=True)
            overlap_line_count = min(overlap_line_count, len(text_lines))
            new_text = prev_text + "".join(text_lines[overlap_line_count:])
```

- [ ] **Step 4: Run all pytest tests — expect all pass**

```bash
.venv/bin/pytest tests/test_search_code.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add search_code.py tests/test_search_code.py
git commit -m "fix: clamp overlap_line_count to len(text_lines) to prevent silent data loss"
```

---

### Task 2: Surface original exception detail in search() error message (search_code.py)

**Issue:** `except Exception:` discards the original error. All failures — including permission errors, I/O errors, ChromaDB version mismatches — print the same static "no index found" message, misdiagnosing the real problem.

**Files:**
- Modify: `search_code.py` (lines 41–46 in `search()`)
- Modify: `tests/test_search_code.py` (append 1 test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_search_code.py`:

```python
def test_search_error_includes_original_exception(tmp_path):
    """When get_collection fails, the error message includes the original exception detail."""
    shutil.copy("search_code.py", tmp_path / "search_code.py")
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
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
.venv/bin/pytest tests/test_search_code.py::test_search_error_includes_original_exception -v
```

Expected: FAIL — current message is static and does not include "project_code".

- [ ] **Step 3: Fix search() — capture and append exception**

In `search_code.py`, replace lines 41–46:

```python
    except Exception:
        print(
            "Error: no index found. Run 'python3 index_project.py' first.",
            file=sys.stderr,
        )
        sys.exit(1)
```

With:

```python
    except Exception as e:
        print(
            f"Error: no index found. Run 'python3 index_project.py' first. ({e})",
            file=sys.stderr,
        )
        sys.exit(1)
```

- [ ] **Step 4: Run all pytest tests — expect all pass**

```bash
.venv/bin/pytest tests/test_search_code.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add search_code.py tests/test_search_code.py
git commit -m "fix: include original exception detail in missing-index error message"
```

---

### Task 3: Warn on unreadable files in index_project.py

**Issue:** `UnicodeDecodeError` and `OSError` are caught and silently `continue`d. The index is silently incomplete with no indication of which files were skipped.

**Files:**
- Modify: `index_project.py` (lines 87–88)
- Modify: `tests/test_search_code.py` (append 1 test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_search_code.py`:

```python
def test_index_warns_on_unreadable_file(tmp_path):
    """index_project.py prints a warning to stderr when a file cannot be decoded."""
    import subprocess as _subprocess
    shutil.copy("index_project.py", tmp_path / "index_project.py")
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
    assert "warning" in output.lower() or "skipping" in output.lower(), (
        f"Expected 'warning' or 'skipping' in output, got: {output!r}"
    )
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
.venv/bin/pytest tests/test_search_code.py::test_index_warns_on_unreadable_file -v
```

Expected: FAIL — no warning is currently printed for skipped files.

- [ ] **Step 3: Fix index_project.py — print warning on skip**

In `index_project.py`, replace lines 87–88:

```python
        except (UnicodeDecodeError, OSError):
            continue
```

With:

```python
        except (UnicodeDecodeError, OSError) as e:
            print(f"  Warning: skipping {filepath} ({type(e).__name__})", file=sys.stderr)
            continue
```

- [ ] **Step 4: Run all pytest tests — expect all pass**

```bash
.venv/bin/pytest tests/test_search_code.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add index_project.py tests/test_search_code.py
git commit -m "fix: warn on files skipped due to read errors in index_project.py"
```

---

## Chunk 2: install.sh fixes

### Task 4: Remove VIRTUAL_ENV fallback — always create .venv (install.sh)

**Issue:** When `VIRTUAL_ENV` is set but no `.venv` exists, the installer uses `$VIRTUAL_ENV` but writes `source .venv/bin/activate` to CLAUDE.md — an instruction that won't work because `.venv` doesn't exist. Fix: remove the fallback. If no `.venv`, always create one.

**Files:**
- Modify: `install.sh` (lines 22–38, the Step 3 block)
- Modify: `tests/test_install.sh` (add Test 7)

- [ ] **Step 1: Replace the venv detection block in install.sh**

Replace lines 22–38 (the full Step 3 block, from `# Step 3` through `echo "Using venv: $VENV_PATH"`):

```bash
# Step 3: Detect or create venv
# Priority: project .venv > create new .venv
# VIRTUAL_ENV is intentionally ignored — using a foreign venv would make
# the .venv/bin/activate instructions in CLAUDE.md incorrect.
VENV_EXISTED=false
if [ -d ".venv" ]; then
    VENV_PATH="$(pwd)/.venv"
    VENV_EXISTED=true
else
    echo "Creating .venv..."
    python3 -m venv .venv
    VENV_PATH="$(pwd)/.venv"
fi
echo "Using venv: $VENV_PATH"
```

- [ ] **Step 2: Add Test 7 to tests/test_install.sh**

Append after Test 6 (before the final `echo ""` and summary block):

```bash
echo ""
echo "=== Test 7: VIRTUAL_ENV set, no .venv — installer creates .venv (ignores VIRTUAL_ENV) ==="
setup
git init -q
git commit -q --allow-empty -m "init"
FAKE_VENV="$(mktemp -d)"
python3 -m venv "$FAKE_VENV" --without-pip 2>/dev/null || python3 -m venv "$FAKE_VENV"
VIRTUAL_ENV="$FAKE_VENV"
export VIRTUAL_ENV
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "project .venv created (VIRTUAL_ENV ignored)" "[ -d .venv ]"
assert "CLAUDE.md uses .venv not VIRTUAL_ENV path" "! grep -q '$FAKE_VENV' CLAUDE.md"
unset VIRTUAL_ENV
rm -rf "$FAKE_VENV"
teardown
```

- [ ] **Step 3: Run tests — expect all pass (now 22 tests)**

```bash
bash tests/test_install.sh
```

Expected: `All 22 tests passed.`

- [ ] **Step 4: Commit**

```bash
git add install.sh tests/test_install.sh
git commit -m "fix: remove VIRTUAL_ENV fallback — always create .venv if not present"
```

---

### Task 5: Add trap to clean up mtime tempfile on early exit (install.sh)

**Issue:** `_VENV_MTIME_REF=$(mktemp)` creates a tempfile that is only removed on the success path. With `set -euo pipefail`, a failed `pip install` exits before `rm -f`, leaking the file in `/tmp` indefinitely.

**Prerequisite:** Apply after Task 4. Task 4 changes the semantics of `VENV_EXISTED` (no longer set for VIRTUAL_ENV fallback), so the trap scope is correct only in the post-Task-4 state.

**Files:**
- Modify: `install.sh` (lines 43–46, the mtime save block)

No new integration test: the failure path (pip install abort) cannot be reliably simulated without a mock, and the existing Test 5 (mtime unchanged) already exercises the full save/restore cycle. Verify by code inspection.

- [ ] **Step 1: Add trap immediately after mktemp in install.sh**

Replace lines 43–46:

```bash
if [ "$VENV_EXISTED" = true ]; then
    _VENV_MTIME_REF=$(mktemp)
    touch -r "$VENV_PATH" "$_VENV_MTIME_REF"
fi
```

With:

```bash
if [ "$VENV_EXISTED" = true ]; then
    _VENV_MTIME_REF=$(mktemp)
    trap '[ -n "${_VENV_MTIME_REF:-}" ] && rm -f "$_VENV_MTIME_REF"' EXIT
    touch -r "$VENV_PATH" "$_VENV_MTIME_REF"
fi
```

The single-quoted trap expands `_VENV_MTIME_REF` at fire-time (not definition-time), so the path is always current. The `[ -n ... ]` guard prevents `rm -f ""` if the variable is somehow unset.

- [ ] **Step 2: Run tests — expect all pass**

```bash
bash tests/test_install.sh
```

Expected: `All 22 tests passed.` (Test 5 verifies mtime is still preserved correctly.)

- [ ] **Step 3: Commit**

```bash
git add install.sh
git commit -m "fix: add trap to clean up mtime reference tempfile on early exit"
```

---

### Task 6: Guard index rebuild for idempotency (install.sh)

**Issue:** Step 8 rebuilds the index every time the installer runs (when in a git repo). Every other step skips work already done; the index should too.

**Files:**
- Modify: `install.sh` (lines 105–109, Step 8)
- Modify: `tests/test_install.sh` (add Test 8)

- [ ] **Step 1: Add chroma_db existence guard to Step 8 in install.sh**

Replace lines 105–109:

```bash
# Step 8: Run first index
if [ "$IS_GIT_REPO" = true ]; then
    echo "Building initial index..."
    "$VENV_PATH/bin/python3" index_project.py
fi
```

With:

```bash
# Step 8: Run first index (skip if index already exists)
if [ "$IS_GIT_REPO" = true ] && [ ! -d "chroma_db" ]; then
    echo "Building initial index..."
    "$VENV_PATH/bin/python3" index_project.py
elif [ "$IS_GIT_REPO" = true ]; then
    echo "chroma_db index already exists, skipping"
fi
```

- [ ] **Step 2: Add Test 8 to tests/test_install.sh**

Append after Test 7 (before the final `echo ""` and summary block):

```bash
echo ""
echo "=== Test 8: Re-install does not rebuild existing index ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
INDEX_MTIME=$(stat -c %Y chroma_db 2>/dev/null || stat -f %m chroma_db)
SECOND_OUTPUT=$(CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh" 2>&1)
INDEX_MTIME2=$(stat -c %Y chroma_db 2>/dev/null || stat -f %m chroma_db)
assert "chroma_db not rebuilt on re-install (mtime unchanged)" "[ '$INDEX_MTIME' = '$INDEX_MTIME2' ]"
assert "second run reports index already exists" "echo '$SECOND_OUTPUT' | grep -q 'already exists'"
teardown
```

- [ ] **Step 3: Run tests — expect all pass (now 24 tests)**

```bash
bash tests/test_install.sh
```

Expected: `All 24 tests passed.`

- [ ] **Step 4: Commit**

```bash
git add install.sh tests/test_install.sh
git commit -m "fix: skip index rebuild on re-install if chroma_db already exists"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run all tests**

```bash
bash tests/test_install.sh && .venv/bin/pytest tests/test_search_code.py -v
```

Expected: `All 24 tests passed.` and all 11 pytest tests green.

- [ ] **Step 2: Verify git log**

```bash
git log --oneline -6
```

Expected commits (most recent first):
```
fix: skip index rebuild on re-install if chroma_db already exists
fix: add trap to clean up mtime reference tempfile on early exit
fix: remove VIRTUAL_ENV fallback — always create .venv if not present
fix: warn on files skipped due to read errors in index_project.py
fix: include original exception detail in missing-index error message
fix: clamp overlap_line_count to len(text_lines) to prevent silent data loss
```
