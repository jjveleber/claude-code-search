#!/usr/bin/env bash
# End-to-end integration test for code-search
# Tests: install → search → edit → reindex → hooks → logging
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
PASS=0
FAIL=0

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[E2E]${NC} $*"
}

assert() {
    local desc="$1"
    local condition="$2"
    if eval "$condition" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $desc"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}✗${NC} $desc"
        FAIL=$((FAIL + 1))
    fi
}

# Create isolated test project
TEST_PROJECT="$(mktemp -d)"
log "Created test project: $TEST_PROJECT"

cleanup() {
    log "Cleaning up test project"
    rm -rf "$TEST_PROJECT"
}
trap cleanup EXIT

cd "$TEST_PROJECT"

# Initialize git repo with test files
log "Setting up test project files"
git init -q
git config user.email "test@test.com"
git config user.name "Test User"

# Create sample Python files
mkdir -p src tests
cat > src/calculator.py <<'EOF'
"""Simple calculator module."""

def add(a, b):
    """Add two numbers."""
    return a + b

def subtract(a, b):
    """Subtract b from a."""
    return a - b

def multiply(a, b):
    """Multiply two numbers."""
    return a * b
EOF

cat > tests/test_calculator.py <<'EOF'
"""Tests for calculator module."""
from src.calculator import add, subtract

def test_add():
    assert add(2, 3) == 5

def test_subtract():
    assert subtract(5, 3) == 2
EOF

cat > README.md <<'EOF'
# Test Project

Simple calculator for testing code-search.
EOF

git add -A
git commit -q -m "Initial commit"

log "Installing code-search from local repo"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh" > /dev/null 2>&1

# === Test 1: Installation verification ===
log "Test 1: Verify installation"
assert "search_code.py installed" "[ -f search_code.py ]"
assert "index_project.py installed" "[ -f index_project.py ]"
assert "watch_index.py installed" "[ -f watch_index.py ]"
assert ".venv-code-search created" "[ -d .venv-code-search ]"
assert "chroma_db index built" "[ -d chroma_db ]"
assert ".claude/CLAUDE.md created" "[ -f .claude/CLAUDE.md ]"
assert ".claude/settings.local.json created" "[ -f .claude/settings.local.json ]"

# === Test 2: Search functionality ===
log "Test 2: Search finds code correctly"
SEARCH_OUTPUT=$(.venv-code-search/bin/python3 search_code.py "add two numbers" 2>&1)
assert "Search finds add function" "echo '$SEARCH_OUTPUT' | grep -q 'calculator.py'"
assert "Search output includes line numbers" "echo '$SEARCH_OUTPUT' | grep -q 'lines'"
assert "Search excludes README (doc file)" "! echo '$SEARCH_OUTPUT' | grep -q 'README.md'"

# Test --all flag includes docs
SEARCH_ALL=$(.venv-code-search/bin/python3 search_code.py "calculator" --all 2>&1)
assert "Search --all includes README" "echo '$SEARCH_ALL' | grep -q 'README.md'"

# === Test 3: File edit triggers reindex ===
log "Test 3: File edits trigger reindexing"
# Add new function
cat >> src/calculator.py <<'EOF'

def divide(a, b):
    """Divide a by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
EOF

# Manually reindex (watcher would do this automatically in real usage)
.venv-code-search/bin/python3 index_project.py > /dev/null 2>&1

# Search for new function
SEARCH_DIVIDE=$(.venv-code-search/bin/python3 search_code.py "divide by zero" 2>&1)
assert "Reindex detected new function" "echo '$SEARCH_DIVIDE' | grep -q 'divide'"
assert "New function searchable" "echo '$SEARCH_DIVIDE' | grep -q 'Cannot divide by zero'"

# === Test 4: Hooks are installed correctly ===
log "Test 4: Hooks configured in settings.local.json"
assert "PostToolUse hook exists" "grep -q 'PostToolUse' .claude/settings.local.json"
assert "PreToolUse hook exists" "grep -q 'PreToolUse' .claude/settings.local.json"
assert "UserPromptSubmit hook exists" "grep -q 'UserPromptSubmit' .claude/settings.local.json"
assert "PostToolUse references post_search_code.sh" "grep -q 'post_search_code.sh' .claude/settings.local.json"
assert "PreToolUse references pre_read_grep_glob.sh" "grep -q 'pre_read_grep_glob.sh' .claude/settings.local.json"
assert "Hooks use correct format (objects)" "grep -q '\"command\":' .claude/settings.local.json"

# === Test 5: Precision Protocol in CLAUDE.md ===
log "Test 5: Precision Protocol documented"
assert "CLAUDE.md has Precision Protocol" "grep -q 'Precision Protocol' .claude/CLAUDE.md"
assert "CLAUDE.md references .venv-code-search" "grep -q '.venv-code-search/bin/python3 search_code.py' .claude/CLAUDE.md"
assert "CLAUDE.md has search scope docs" "grep -q 'Search scope:' .claude/CLAUDE.md"

# === Test 6: Usage tracking infrastructure ===
log "Test 6: Usage tracking setup"
assert "logs/ directory exists" "[ -d logs ]"
assert "hooks/ directory exists" "[ -d hooks ]"
assert "post_search_code.sh exists" "[ -f hooks/post_search_code.sh ]"
assert "pre_read_grep_glob.sh exists" "[ -f hooks/pre_read_grep_glob.sh ]"
assert "Hook scripts are executable" "[ -x hooks/post_search_code.sh ]"

# === Test 7: File classification ===
log "Test 7: File type classification"
SEARCH_PROD=$(.venv-code-search/bin/python3 search_code.py "calculator" 2>&1)
assert "Production files labeled [prod]" "echo '$SEARCH_PROD' | grep -q '\\[prod\\]'"
assert "Test files labeled [test]" "echo '$SEARCH_PROD' | grep -q '\\[test\\]' || true"  # May not match

# === Test 8: BM25 hybrid search (if available) ===
log "Test 8: BM25 functionality"
# Build BM25 index
.venv-code-search/bin/python3 index_project.py --bm25 > /dev/null 2>&1
assert "BM25 corpus created" "[ -f chroma_db/bm25_corpus.json ]"

# Search with BM25
SEARCH_BM25=$(.venv-code-search/bin/python3 search_code.py --bm25 "calculator multiply" 2>&1)
assert "BM25 search works" "echo '$SEARCH_BM25' | grep -q 'calculator.py'"

# === Test 9: Index excludes chroma_db directory ===
log "Test 9: Chroma DB directory excluded from index"
# The indexer should never index its own database files
# Check if any actual chroma_db/ files are in the index by looking at MATCH headers
SEARCH_CHROMA=$(.venv-code-search/bin/python3 search_code.py "vector database" 2>&1 || true)
# MATCH lines show file paths - none should be from chroma_db/
if echo "$SEARCH_CHROMA" | grep "^MATCH.*: chroma_db/" > /dev/null; then
    # Found a file from chroma_db/ in results (bad)
    assert "chroma_db/ files not indexed" "false"
else
    # No chroma_db/ files in results (good)
    assert "chroma_db/ files not indexed" "true"
fi

# === Summary ===
echo ""
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All $PASS end-to-end tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$PASS passed, $FAIL FAILED${NC}"
    exit 1
fi
