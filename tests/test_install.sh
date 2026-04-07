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
assert "index_project.py installed"                        "[ -f index_project.py ]"
assert "search_code.py installed"                          "[ -f search_code.py ]"
assert "watch_index.py installed"                          "[ -f watch_index.py ]"
assert ".gitignore created"                                "[ -f .gitignore ]"
assert ".venv/ in .gitignore"                              "grep -qxF '.venv/' .gitignore"
assert "__pycache__/ in .gitignore"                        "grep -qxF '__pycache__/' .gitignore"
assert "chroma_db/ in .gitignore"                          "grep -qxF 'chroma_db/' .gitignore"
assert ".watch_index.log in .gitignore"                    "grep -qxF '.watch_index.log' .gitignore"
assert ".watch_index.pid in .gitignore"                    "grep -qxF '.watch_index.pid' .gitignore"
assert ".claude/settings.local.json in .gitignore"         "grep -qxF '.claude/settings.local.json' .gitignore"
assert ".claude/CLAUDE.md in .gitignore"                   "grep -qxF '.claude/CLAUDE.md' .gitignore"
assert "venv created"                                      "[ -d .venv ]"
assert "chroma_db index built"                             "[ -d chroma_db ]"
assert ".claude/CLAUDE.md created"                         "[ -f .claude/CLAUDE.md ]"
assert "Precision Protocol in .claude/CLAUDE.md"           "grep -q 'code-search:start' .claude/CLAUDE.md"
assert ".claude/CLAUDE.md search command uses .venv/bin/python3" \
    "grep -q '.venv/bin/python3 search_code.py' .claude/CLAUDE.md"
assert ".claude/CLAUDE.md does not start with blank line"  "[ \"\$(head -c1 .claude/CLAUDE.md)\" != $'\n' ]"
assert "auto-watcher hook in .claude/settings.local.json"  "[ -f .claude/settings.local.json ] && grep -q 'watch_index.py' .claude/settings.local.json"
assert "hook NOT in .claude/settings.json"                 "! ([ -f .claude/settings.json ] && grep -q 'watch_index.py' .claude/settings.json)"
assert "Precision Protocol NOT in project CLAUDE.md"       "! ([ -f CLAUDE.md ] && grep -q 'code-search:start' CLAUDE.md)"
assert "Session Startup not in .claude/CLAUDE.md"          "! grep -q 'Session Startup' .claude/CLAUDE.md"
teardown

echo ""
echo "=== Test 2: Idempotency — running twice produces no duplicates ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
SENTINEL_COUNT=$(grep -c "code-search:start" .claude/CLAUDE.md)
assert "Precision Protocol appears exactly once in .claude/CLAUDE.md" "[ '$SENTINEL_COUNT' = '1' ]"
VENV_COUNT=$(grep -c ".venv/" .gitignore)
assert ".venv/ appears exactly once in .gitignore" "[ '$VENV_COUNT' = '1' ]"
PYCACHE_COUNT=$(grep -c "__pycache__/" .gitignore)
assert "__pycache__/ appears exactly once in .gitignore" "[ '$PYCACHE_COUNT' = '1' ]"
GITIGNORE_COUNT=$(grep -c "chroma_db/" .gitignore)
assert "chroma_db/ appears exactly once in .gitignore" "[ '$GITIGNORE_COUNT' = '1' ]"
LOG_COUNT=$(grep -c ".watch_index.log" .gitignore)
assert ".watch_index.log appears exactly once in .gitignore" "[ '$LOG_COUNT' = '1' ]"
PID_COUNT=$(grep -c ".watch_index.pid" .gitignore)
assert ".watch_index.pid appears exactly once in .gitignore" "[ '$PID_COUNT' = '1' ]"
LOCAL_JSON_COUNT=$(grep -c ".claude/settings.local.json" .gitignore)
assert ".claude/settings.local.json appears exactly once in .gitignore" "[ '$LOCAL_JSON_COUNT' = '1' ]"
LOCAL_MD_COUNT=$(grep -c ".claude/CLAUDE.md" .gitignore)
assert ".claude/CLAUDE.md appears exactly once in .gitignore" "[ '$LOCAL_MD_COUNT' = '1' ]"
HOOK_COUNT=$(grep -c "watch_index.py" .claude/settings.local.json)
assert "Hook appears exactly once in .claude/settings.local.json" "[ '$HOOK_COUNT' = '1' ]"
teardown

echo ""
echo "=== Test 3: Existing CLAUDE.md is not modified ==="
setup
git init -q
git commit -q --allow-empty -m "init"
printf "# My Project\n\nSome existing content.\n" > CLAUDE.md
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "Original heading preserved in CLAUDE.md"           "grep -q 'My Project' CLAUDE.md"
assert "Precision Protocol NOT appended to CLAUDE.md"      "! grep -q 'code-search:start' CLAUDE.md"
assert "Precision Protocol written to .claude/CLAUDE.md"   "grep -q 'code-search:start' .claude/CLAUDE.md"
teardown

echo ""
echo "=== Test 4: Non-git-repo skips index, still installs files ==="
setup
# No git init — plain directory
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh" || true
assert "index_project.py still installed"      "[ -f index_project.py ]"
assert ".claude/CLAUDE.md still created"       "[ -f .claude/CLAUDE.md ]"
assert "chroma_db NOT created"                 "[ ! -d chroma_db ]"
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
assert ".claude/CLAUDE.md uses .venv not foreign path"  "! grep -q '$FAKE_VENV' .claude/CLAUDE.md"
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
assert "project .venv created (VIRTUAL_ENV ignored)"     "[ -d .venv ]"
assert ".claude/CLAUDE.md uses .venv not VIRTUAL_ENV path" "! grep -q '$FAKE_VENV' .claude/CLAUDE.md"
unset VIRTUAL_ENV
rm -rf "$FAKE_VENV"
teardown

echo ""
echo "=== Test 8: Re-install updates python files but does not rebuild existing index ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
INDEX_MTIME=$(stat -c %Y chroma_db 2>/dev/null || stat -f %m chroma_db)
SECOND_OUTPUT=$(CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh" 2>&1)
INDEX_MTIME2=$(stat -c %Y chroma_db 2>/dev/null || stat -f %m chroma_db)
assert "chroma_db not rebuilt on re-install (mtime unchanged)" "[ '$INDEX_MTIME' = '$INDEX_MTIME2' ]"
assert "second run updates python files" "echo '$SECOND_OUTPUT' | grep -q 'Updated index_project.py'"
teardown

echo ""
echo "=== Test 9: .claude/CLAUDE.md Precision Protocol uses correct search command ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert ".claude/CLAUDE.md search command uses .venv/bin/python3" \
    "grep -q '.venv/bin/python3 search_code.py' .claude/CLAUDE.md"
assert ".claude/CLAUDE.md search command does not misuse 'source' as a path prefix" \
    "! grep -q 'source .venv/bin/python3' .claude/CLAUDE.md"
teardown

echo ""
echo "=== Test 10: Re-install does not duplicate hook in .claude/settings.local.json ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
COUNT1=$(grep -c "watch_index.py" .claude/settings.local.json)
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh" 2>&1
COUNT2=$(grep -c "watch_index.py" .claude/settings.local.json)
assert "Hook not duplicated on re-install" "[ \"$COUNT1\" = \"$COUNT2\" ]"
teardown

echo ""
echo "=== Test 11: Migrates legacy Session Startup section out of CLAUDE.md ==="
setup
git init -q
git commit -q --allow-empty -m "init"
# Simulate old install with Session Startup section in CLAUDE.md
printf "<!-- code-search:start -->\n## Precision Protocol\n<!-- code-search:end -->\n\n<!-- code-search-watch:start -->\n## Session Startup\nAt the start of each session:\n1. Run index_project.py\n<!-- code-search-watch:end -->\n" > CLAUDE.md
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "Session Startup removed from CLAUDE.md"          "! grep -q 'Session Startup' CLAUDE.md"
assert "Precision Protocol removed from CLAUDE.md"       "! grep -q 'code-search:start' CLAUDE.md"
assert "Precision Protocol present in .claude/CLAUDE.md" "grep -q 'code-search:start' .claude/CLAUDE.md"
teardown

echo ""
echo "=== Test 12: Migrates legacy PostToolUse hook out of .claude/settings.local.json ==="
setup
git init -q
git commit -q --allow-empty -m "init"
# Simulate old install with PostToolUse hook in settings.local.json
mkdir -p .claude
printf '{"hooks":{"PostToolUse":[{"matcher":"Edit","hooks":[{"type":"command","command":".venv/bin/python3 index_project.py"}]}]}}\n' > .claude/settings.local.json
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "PostToolUse hook removed from settings.local.json"  "! grep -q 'PostToolUse' .claude/settings.local.json"
assert "UserPromptSubmit hook added to settings.local.json" "grep -q 'watch_index.py' .claude/settings.local.json"
assert "hook NOT written to settings.json"                  "! ([ -f .claude/settings.json ] && grep -q 'watch_index.py' .claude/settings.json)"
teardown

echo ""
echo "=== Test 13: Migrates legacy UserPromptSubmit hook out of .claude/settings.json ==="
setup
git init -q
git commit -q --allow-empty -m "init"
# Simulate old install with hook in shared settings.json (use Python to produce valid JSON)
mkdir -p .claude
python3 -c "
import json, pathlib
hook = 'if [ -f \"watch_index.py\" ] && [ -f \".venv/bin/python3\" ]; then   .venv/bin/python3 index_project.py >> .watch_index.log 2>&1 &   .venv/bin/python3 watch_index.py >> .watch_index.log 2>&1 & fi'
pathlib.Path('.claude/settings.json').write_text(json.dumps({'hooks':{'UserPromptSubmit':[{'hooks':[{'type':'command','command':hook}]}]}}) + '\n')
"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "hook migrated out of .claude/settings.json"        "! grep -q 'watch_index.py' .claude/settings.json"
assert "hook present in .claude/settings.local.json"       "grep -q 'watch_index.py' .claude/settings.local.json"
teardown

echo ""
echo "=== Test 14: Migration is idempotent — running install.sh twice on an old install ==="
setup
git init -q
git commit -q --allow-empty -m "init"
# Simulate old install with Precision Protocol in CLAUDE.md and PostToolUse hook
printf "<!-- code-search:start -->\n## Precision Protocol\n<!-- code-search:end -->\n\n<!-- code-search-watch:start -->\n## Session Startup\n1. Run index_project.py\n<!-- code-search-watch:end -->\n" > CLAUDE.md
mkdir -p .claude
printf '{"hooks":{"PostToolUse":[{"matcher":"Edit","hooks":[{"type":"command","command":".venv/bin/python3 index_project.py"}]}]}}\n' > .claude/settings.local.json
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "Session Startup still absent after second run"             "! grep -q 'Session Startup' CLAUDE.md"
assert "Precision Protocol absent from CLAUDE.md after two runs"   "! grep -q 'code-search:start' CLAUDE.md"
assert "Precision Protocol in .claude/CLAUDE.md after two runs"    "grep -q 'code-search:start' .claude/CLAUDE.md"
assert "Hook not duplicated after two runs on old install" \
    "[ \"$(grep -c 'watch_index.py' .claude/settings.local.json)\" = '1' ]"
teardown

echo ""
echo "=== Test 15: ROCm setup is skipped on non-WSL2 systems ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh" > "$TEST_DIR/install_out.txt" 2>&1
_exit=$?
assert "install.sh exits 0 on non-WSL2" "[ $_exit -eq 0 ]"
assert "ROCm install not attempted on non-WSL2" \
    "! grep -q 'amdgpu-install' '$TEST_DIR/install_out.txt'"
assert "index_project.py installed" "[ -f index_project.py ]"
teardown

echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "All $PASS tests passed."
else
    echo "$PASS passed, $FAIL FAILED."
    exit 1
fi
