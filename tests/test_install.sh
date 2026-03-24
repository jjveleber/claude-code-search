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
    git config --global user.email "test@test.com" 2>/dev/null || true
    git config --global user.name "Test" 2>/dev/null || true
}

teardown() {
    cd "$REPO_ROOT"
    rm -rf "$TEST_DIR"
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
if [ "$FAIL" -eq 0 ]; then
    echo "All $PASS tests passed."
else
    echo "$PASS passed, $FAIL FAILED."
    exit 1
fi
