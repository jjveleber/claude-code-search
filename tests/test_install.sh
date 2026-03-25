#!/usr/bin/env bash
# Integration tests for install.sh
# Usage: bash tests/test_install.sh
# Uses CODE_SEARCH_LOCAL env var to bypass curl (set automatically by this script)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
PASS=0
FAIL=0

assert() {
    local desc="$1"
    local condition="$2"
    if eval "$condition" > /dev/null 2>&1; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        FAIL=$((FAIL + 1))
    fi
}

setup() {
    TEST_DIR="$(mktemp -d)"
    cd "$TEST_DIR"
    unset VIRTUAL_ENV
    git config --global user.email "test@test.com" 2>/dev/null || true
    git config --global user.name "Test" 2>/dev/null || true
}

teardown() {
    cd "$REPO_ROOT"
    [ -n "${TEST_DIR:-}" ] && rm -rf "$TEST_DIR"
}

echo "=== Test 1: Fresh install into new git repo ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "index_project.py installed"   "[ -f index_project.py ]"
assert "search_code.py installed"     "[ -f search_code.py ]"
assert ".gitignore created"           "[ -f .gitignore ]"
assert "chroma_db/ in .gitignore"     "grep -qxF 'chroma_db/' .gitignore"
assert "CLAUDE.md created"            "[ -f CLAUDE.md ]"
assert "Precision Protocol in CLAUDE.md" "grep -q 'code-search:start' CLAUDE.md"
assert "venv created"                 "[ -d .venv ]"
assert "chroma_db index built"        "[ -d chroma_db ]"
assert "CLAUDE.md search command uses .venv/bin/python3 (not 'source')"  "grep -q '.venv/bin/python3 search_code.py' CLAUDE.md"
assert "CLAUDE.md does not start with blank line" "[ \"\$(head -c1 CLAUDE.md)\" != $'\n' ]"
assert "watch_index.py installed"              "[ -f watch_index.py ]"
assert ".watch_index.log in .gitignore"        "grep -qxF '.watch_index.log' .gitignore"
assert ".watch_index.pid in .gitignore"        "grep -qxF '.watch_index.pid' .gitignore"
assert "Session Startup in CLAUDE.md"          "grep -q 'Session Startup' CLAUDE.md"
assert "watch_index.py command in CLAUDE.md"   "grep -q 'watch_index.py' CLAUDE.md"
teardown

echo ""
echo "=== Test 2: Idempotency — running twice produces no duplicates ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
SENTINEL_COUNT=$(grep -c "code-search:start" CLAUDE.md)
assert "Precision Protocol appears exactly once" "[ '$SENTINEL_COUNT' = '1' ]"
GITIGNORE_COUNT=$(grep -c "chroma_db/" .gitignore)
assert "chroma_db/ appears exactly once in .gitignore" "[ '$GITIGNORE_COUNT' = '1' ]"
teardown

echo ""
echo "=== Test 3: Existing CLAUDE.md is appended, not overwritten ==="
setup
git init -q
git commit -q --allow-empty -m "init"
printf "# My Project\n\nSome existing content.\n" > CLAUDE.md
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "Original heading preserved"   "grep -q 'My Project' CLAUDE.md"
assert "Precision Protocol appended"  "grep -q 'code-search:start' CLAUDE.md"
teardown

echo ""
echo "=== Test 4: Non-git-repo skips index, still installs files ==="
setup
# No git init — plain directory
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh" || true
assert "index_project.py still installed" "[ -f index_project.py ]"
assert "CLAUDE.md still created"          "[ -f CLAUDE.md ]"
assert "chroma_db NOT created"            "[ ! -d chroma_db ]"
teardown

echo ""
echo "=== Test 5: Existing .venv is reused (not recreated) ==="
setup
git init -q
git commit -q --allow-empty -m "init"
python3 -m venv .venv
VENV_MTIME=$(stat -c %Y .venv 2>/dev/null || stat -f %m .venv)
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
VENV_MTIME2=$(stat -c %Y .venv 2>/dev/null || stat -f %m .venv)
assert "Existing .venv reused (mtime unchanged)" "[ '$VENV_MTIME' = '$VENV_MTIME2' ]"
teardown

echo ""
echo "=== Test 6: VIRTUAL_ENV set but .venv exists — installer uses .venv ==="
setup
git init -q
git commit -q --allow-empty -m "init"
# Create a fake foreign venv to act as the active VIRTUAL_ENV
FAKE_VENV="$(mktemp -d)"
python3 -m venv "$FAKE_VENV" 2>/dev/null || python3 -m venv "$FAKE_VENV"
VIRTUAL_ENV="$FAKE_VENV"
export VIRTUAL_ENV
# Create .venv before running install.sh
python3 -m venv .venv 2>/dev/null || python3 -m venv .venv
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "chromadb installed in .venv (not foreign venv)" "[ -d .venv/lib ] && .venv/bin/python3 -c 'import chromadb' 2>/dev/null"
assert "CLAUDE.md uses .venv not foreign path"         "! grep -q '$FAKE_VENV' CLAUDE.md"
unset VIRTUAL_ENV
rm -rf "$FAKE_VENV"
teardown

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

echo ""
echo "=== Test 9: CLAUDE.md Precision Protocol uses correct search command ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "CLAUDE.md search command uses .venv/bin/python3" \
    "grep -q '.venv/bin/python3 search_code.py' CLAUDE.md"
assert "CLAUDE.md search command does not misuse 'source' as a path prefix" \
    "! grep -q 'source .venv/bin/python3' CLAUDE.md"
teardown

echo ""
echo "=== Test 11: Re-install does not duplicate Session Startup in CLAUDE.md ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
COUNT1=$(grep -c "Session Startup" CLAUDE.md)
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh" 2>&1
COUNT2=$(grep -c "Session Startup" CLAUDE.md)
assert "Session Startup not duplicated on re-install" "[ \"$COUNT1\" = \"$COUNT2\" ]"
teardown

echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "All $PASS tests passed."
else
    echo "$PASS passed, $FAIL FAILED."
    exit 1
fi
