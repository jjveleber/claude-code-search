#!/usr/bin/env bash
# End-to-end: old install -> enable (migrate) -> daemon search -> worktree
# auto-register -> disable --purge. Requires the central venv deps; run
# with: CODE_SEARCH_E2E_VENV=/path/to/venv tests/engine/test_e2e_central.sh
# (CI/dev: point it at this repo's .venv)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP=$(mktemp -d)
trap 'PYTHONPATH="$ROOT" CODE_SEARCH_HOME="$TMP/csh" python3 -c "
from engine import client
client.request({\"cmd\": \"shutdown\"}, timeout=5)
" 2>/dev/null || true; rm -rf "$TMP"' EXIT
export CODE_SEARCH_HOME="$TMP/csh"
VENV="${CODE_SEARCH_E2E_VENV:?set CODE_SEARCH_E2E_VENV to a venv with chromadb}"

fail() { echo "FAIL: $1"; exit 1; }

# Wire the central home to reuse the provided venv (skips the GB download)
mkdir -p "$CODE_SEARCH_HOME"
ln -s "$VENV" "$CODE_SEARCH_HOME/venv"
python3 - <<EOF
import hashlib, pathlib
req = pathlib.Path("$ROOT/engine/requirements.txt").read_bytes()
pathlib.Path("$CODE_SEARCH_HOME/venv.ok").write_text(
    hashlib.sha256(req).hexdigest())
EOF

# Fixture repo with a fake old install
REPO="$TMP/proj"
mkdir -p "$REPO" && cd "$REPO"
git init -q
echo 'def authenticate(user): return True' > auth.py
echo 'chroma_db/' > .gitignore
echo '.venv/' >> .gitignore
mkdir -p chroma_db && echo "nomic-ai/CodeRankEmbed" > chroma_db/model.txt
echo "v1.2.0" > .code-search-version
touch search_code.py watch_index.py
git add auth.py .gitignore
git -c user.email=t@t -c user.name=t commit -qm init

# 1. enable: migrates + registers + first index
"$ROOT/bin/code-search" enable | tee "$TMP/enable.out"
grep -q "enabled:" "$TMP/enable.out" || fail "enable did not report success"
[ ! -f search_code.py ] || fail "old script not migrated"
[ ! -d chroma_db ] || fail "old index not migrated"
grep -q '^\.venv/$' .gitignore || fail "generic gitignore line was removed"

# 2. search works (warming retry inside the client)
"$ROOT/bin/code-search" search "user authentication" > "$TMP/search.out"
grep -q "MATCH 1:" "$TMP/search.out" || fail "no search results"
grep -q "auth.py" "$TMP/search.out" || fail "auth.py not found"

# 3. worktree: auto-registration + seeded index
git worktree add "$TMP/wt" -b feat -q
cd "$TMP/wt"
"$ROOT/bin/code-search" reindex >/dev/null   # triggers watch/auto-register
"$ROOT/bin/code-search" search "user authentication" > "$TMP/wt.out"
grep -q "auth.py" "$TMP/wt.out" || fail "worktree search failed"

# 4. status shows both worktrees
"$ROOT/bin/code-search" status | tee "$TMP/status.out"
[ "$(grep -c "$TMP" "$TMP/status.out")" -ge 2 ] || fail "status missing worktrees"

# 5. disable --purge removes indexes
cd "$REPO"
"$ROOT/bin/code-search" disable --purge
[ -z "$(ls -A "$CODE_SEARCH_HOME/indexes" 2>/dev/null)" ] \
    || fail "indexes not purged"

echo "ALL E2E TESTS PASSED"
