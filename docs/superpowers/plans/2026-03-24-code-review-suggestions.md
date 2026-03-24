# Code Review Suggestions (Round 2 Follow-Up)

Minor suggestions from the round 2 code review that are not blocking. Document for future implementation.

---

## Suggestion 1: Clear `_VENV_MTIME_REF` after explicit cleanup in install.sh

**File:** `install.sh` (line after the explicit `rm -f "$_VENV_MTIME_REF"`)

**Issue:** After the explicit `rm -f "$_VENV_MTIME_REF"` on the success path, `_VENV_MTIME_REF` is not unset. When the script completes normally and the EXIT trap fires, it evaluates `[ -n "${_VENV_MTIME_REF:-}" ]` as true and calls `rm -f` on an already-deleted path. `rm -f` on a nonexistent file exits 0, so this is harmless — but it is a redundant operation.

**Fix:**
```bash
touch -m -r "$_VENV_MTIME_REF" "$VENV_PATH" 2>/dev/null || true
rm -f "$_VENV_MTIME_REF"
_VENV_MTIME_REF=""   # prevent trap from re-running rm -f on a gone file
```

---

## Suggestion 2: Add chromadb import assertion to Test 7 in tests/test_install.sh

**File:** `tests/test_install.sh` (Test 7)

**Issue:** Test 7 verifies that `.venv` is created and that `CLAUDE.md` does not reference the foreign venv path, but does not verify that `chromadb` was actually installed into the new `.venv`. Test 6 has this assertion; Test 7 should mirror it for symmetry and to catch regressions if venv selection logic changes.

**Fix:** Add to Test 7:
```bash
assert "chromadb installed in .venv" "[ -d .venv/lib ] && .venv/bin/python3 -c 'import chromadb' 2>/dev/null"
```

---

## Suggestion 3: Add comment explaining overlap_line_count=0 fallback in search_code.py

**File:** `search_code.py` (lines 26–27, inside `merge_chunks`)

**Issue:** The fallback `overlap_line_count = 0` when computed overlap exceeds actual line count is a non-obvious choice. Without a comment, a future reader might "fix" it back to `min(overlap, len)`, reintroducing the silent data loss bug.

**Fix:**
```python
if overlap_line_count > len(text_lines):
    # Metadata/text mismatch: computed overlap would drop all of chunk B.
    # Include all of B rather than silently losing its content.
    overlap_line_count = 0
```
