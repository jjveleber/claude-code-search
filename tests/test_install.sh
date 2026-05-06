#!/usr/bin/env bash
# Integration tests for install.sh
# Usage: bash tests/test_install.sh
# Uses CODE_SEARCH_LOCAL env var to bypass curl (set automatically by this script)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Self-isolation: run tests from separate execution directory to avoid polluting main project
if [ -z "${TEST_ISOLATED:-}" ]; then
    TEST_EXEC_DIR="$(mktemp -d)"
    export TEST_ISOLATED=1
    trap "rm -rf '$TEST_EXEC_DIR'" EXIT
    cd "$TEST_EXEC_DIR"
    exec bash "$SCRIPT_DIR/$(basename "$0")"
fi

# Now running in isolated temp directory
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
    git config --local user.email "test@test.com" 2>/dev/null || true
    git config --local user.name "Test" 2>/dev/null || true
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
assert ".venv-code-search/ in .gitignore"                              "grep -qxF '.venv-code-search/' .gitignore"
assert ".venv/ in .gitignore"                              "grep -qxF '.venv/' .gitignore"
assert "__pycache__/ in .gitignore"                        "grep -qxF '__pycache__/' .gitignore"
assert "chroma_db/ in .gitignore"                          "grep -qxF 'chroma_db/' .gitignore"
assert ".watch_index.log in .gitignore"                    "grep -qxF '.watch_index.log' .gitignore"
assert ".watch_index.pid in .gitignore"                    "grep -qxF '.watch_index.pid' .gitignore"
assert ".claude/settings.local.json in .gitignore"         "grep -qxF '.claude/settings.local.json' .gitignore"
assert ".claude/CLAUDE.md in .gitignore"                   "grep -qxF '.claude/CLAUDE.md' .gitignore"
assert "venv created"                                      "[ -d .venv-code-search ]"
assert "chroma_db index built"                             "[ -d chroma_db ]"
assert ".claude/CLAUDE.md created"                         "[ -f .claude/CLAUDE.md ]"
assert "Precision Protocol in .claude/CLAUDE.md"           "grep -q 'code-search:start' .claude/CLAUDE.md"
assert ".claude/CLAUDE.md search command uses .venv-code-search/bin/python3" \
    "grep -q '.venv-code-search/bin/python3 search_code.py' .claude/CLAUDE.md"
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
VENV_COUNT=$(grep -c ".venv-code-search/" .gitignore)
assert ".venv-code-search/ appears exactly once in .gitignore" "[ '$VENV_COUNT' = '1' ]"
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
echo "=== Test 5: Existing .venv-code-search is reused (not recreated) ==="
setup
git init -q
git commit -q --allow-empty -m "init"
python3 -m venv .venv-code-search
VENV_MTIME=$(stat -c %Y .venv-code-search 2>/dev/null || stat -f %m .venv-code-search)
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
VENV_MTIME2=$(stat -c %Y .venv-code-search 2>/dev/null || stat -f %m .venv-code-search)
assert "Existing .venv-code-search reused (mtime unchanged)" "[ '$VENV_MTIME' = '$VENV_MTIME2' ]"
teardown

echo ""
echo "=== Test 6: VIRTUAL_ENV set but .venv-code-search exists — installer uses .venv-code-search ==="
setup
git init -q
git commit -q --allow-empty -m "init"
# Create a fake foreign venv to act as the active VIRTUAL_ENV
FAKE_VENV="$(mktemp -d)"
python3 -m venv "$FAKE_VENV" 2>/dev/null || python3 -m venv "$FAKE_VENV"
VIRTUAL_ENV="$FAKE_VENV"
export VIRTUAL_ENV
# Create .venv-code-search before running install.sh
python3 -m venv .venv-code-search 2>/dev/null || python3 -m venv .venv-code-search
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "chromadb installed in .venv-code-search (not foreign venv)" "[ -d .venv-code-search/lib ] && .venv-code-search/bin/python3 -c 'import chromadb' 2>/dev/null"
assert ".claude/CLAUDE.md uses .venv-code-search not foreign path"  "! grep -q '$FAKE_VENV' .claude/CLAUDE.md"
unset VIRTUAL_ENV
rm -rf "$FAKE_VENV"
teardown

echo ""
echo "=== Test 7: VIRTUAL_ENV set, no .venv-code-search — installer creates .venv-code-search (ignores VIRTUAL_ENV) ==="
setup
git init -q
git commit -q --allow-empty -m "init"
FAKE_VENV="$(mktemp -d)"
python3 -m venv "$FAKE_VENV" --without-pip 2>/dev/null || python3 -m venv "$FAKE_VENV"
VIRTUAL_ENV="$FAKE_VENV"
export VIRTUAL_ENV
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "project .venv-code-search created (VIRTUAL_ENV ignored)"     "[ -d .venv-code-search ]"
assert ".claude/CLAUDE.md uses .venv-code-search not VIRTUAL_ENV path" "! grep -q '$FAKE_VENV' .claude/CLAUDE.md"
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
assert ".claude/CLAUDE.md search command uses .venv-code-search/bin/python3" \
    "grep -q '.venv-code-search/bin/python3 search_code.py' .claude/CLAUDE.md"
assert ".claude/CLAUDE.md search command does not misuse 'source' as a path prefix" \
    "! grep -q 'source .venv-code-search/bin/python3' .claude/CLAUDE.md"
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
printf '{"hooks":{"PostToolUse":[{"matcher":"Edit","hooks":[{"type":"command","command":".venv-code-search/bin/python3 index_project.py"}]}]}}\n' > .claude/settings.local.json
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh"
assert "Legacy PostToolUse hook (matcher:Edit) removed"  "! grep -q 'matcher.*Edit' .claude/settings.local.json"
assert "Legacy PostToolUse hook (index_project.py) removed"  "! grep -q 'Edit.*index_project.py' .claude/settings.local.json"
assert "New PostToolUse hook (search tracking) added"    "grep -q 'search_code.py' .claude/settings.local.json"
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
hook = 'if [ -f \"watch_index.py\" ] && [ -f \".venv-code-search/bin/python3\" ]; then   .venv-code-search/bin/python3 index_project.py >> .watch_index.log 2>&1 &   .venv-code-search/bin/python3 watch_index.py >> .watch_index.log 2>&1 & fi'
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
printf '{"hooks":{"PostToolUse":[{"matcher":"Edit","hooks":[{"type":"command","command":".venv-code-search/bin/python3 index_project.py"}]}]}}\n' > .claude/settings.local.json
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
echo "=== Test 16: Version detection - defaults to main ==="
setup
git init -q
git commit -q --allow-empty -m "init"
# Create test install.sh with version detection logic but empty INSTALL_VERSION
cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION=""

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

echo "SOURCE_TYPE=$SOURCE_TYPE"
echo "SOURCE_VALUE=$SOURCE_VALUE"
INSTALL_SCRIPT

bash test_install.sh > output.txt
assert "Defaults to branch type" "grep -q 'SOURCE_TYPE=branch' output.txt"
assert "Defaults to main" "grep -q 'SOURCE_VALUE=main' output.txt"
teardown

echo ""
echo "=== Test 17: Version detection - CODE_SEARCH_VERSION override ==="
setup
git init -q
git commit -q --allow-empty -m "init"
cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION="v0.5.0"

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

echo "SOURCE_TYPE=$SOURCE_TYPE"
echo "SOURCE_VALUE=$SOURCE_VALUE"
INSTALL_SCRIPT

CODE_SEARCH_VERSION=v1.0.0 bash test_install.sh > output.txt
assert "Uses version type" "grep -q 'SOURCE_TYPE=version' output.txt"
assert "Uses override version" "grep -q 'SOURCE_VALUE=v1.0.0' output.txt"
teardown

echo ""
echo "=== Test 18: Version detection - CODE_SEARCH_BRANCH override ==="
setup
git init -q
git commit -q --allow-empty -m "init"
cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION=""

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

echo "SOURCE_TYPE=$SOURCE_TYPE"
echo "SOURCE_VALUE=$SOURCE_VALUE"
INSTALL_SCRIPT

CODE_SEARCH_BRANCH=develop bash test_install.sh > output.txt
assert "Uses branch type" "grep -q 'SOURCE_TYPE=branch' output.txt"
assert "Uses override branch" "grep -q 'SOURCE_VALUE=develop' output.txt"
teardown

echo ""
echo "=== Test 19: Version detection - embedded INSTALL_VERSION ==="
setup
git init -q
git commit -q --allow-empty -m "init"
cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION="v1.2.3"

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

echo "SOURCE_TYPE=$SOURCE_TYPE"
echo "SOURCE_VALUE=$SOURCE_VALUE"
INSTALL_SCRIPT

bash test_install.sh > output.txt
assert "Uses version type" "grep -q 'SOURCE_TYPE=version' output.txt"
assert "Uses embedded version" "grep -q 'SOURCE_VALUE=v1.2.3' output.txt"
teardown

echo ""
echo "=== Test 20: Version validation - rejects invalid format ==="
setup
git init -q
git commit -q --allow-empty -m "init"
cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION=""

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

# Version format validation
if [ "$SOURCE_TYPE" = "version" ] && [[ ! "$SOURCE_VALUE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Invalid version '$SOURCE_VALUE' (expected format: v1.0.0)" >&2
    exit 1
fi

echo "VALID"
INSTALL_SCRIPT

# Test invalid formats
output=$(CODE_SEARCH_VERSION=1.0.0 bash test_install.sh 2>&1 || true)
if echo "$output" | grep -q "Error: Invalid version"; then
    echo "  PASS: Rejects missing v prefix"
    PASS=$((PASS + 1))
else
    echo "  FAIL: Should reject missing v prefix"
    FAIL=$((FAIL + 1))
fi

output=$(CODE_SEARCH_VERSION=v1.0 bash test_install.sh 2>&1 || true)
if echo "$output" | grep -q "Error: Invalid version"; then
    echo "  PASS: Rejects incomplete version"
    PASS=$((PASS + 1))
else
    echo "  FAIL: Should reject incomplete version"
    FAIL=$((FAIL + 1))
fi

# Test valid format
if CODE_SEARCH_VERSION=v1.0.0 bash test_install.sh 2>&1 | grep -q "VALID"; then
    echo "  PASS: Accepts valid version"
    PASS=$((PASS + 1))
else
    echo "  FAIL: Should accept valid version"
    FAIL=$((FAIL + 1))
fi

teardown

echo ""
echo "=== Test 21: URL construction ==="
setup
git init -q
git commit -q --allow-empty -m "init"

cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION=""
REPO_OWNER="${CODE_SEARCH_OWNER:-jjveleber}"

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

if [ "$SOURCE_TYPE" = "version" ] && [[ ! "$SOURCE_VALUE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Invalid version '$SOURCE_VALUE' (expected format: v1.0.0)" >&2
    exit 1
fi

BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/claude-code-search/${SOURCE_VALUE}"
echo "BASE_URL=$BASE_URL"
INSTALL_SCRIPT

# Test version URL
CODE_SEARCH_VERSION=v1.0.0 bash test_install.sh > output.txt
assert "Version uses tag URL" "grep -q 'BASE_URL=https://raw.githubusercontent.com/jjveleber/claude-code-search/v1.0.0' output.txt"

# Test branch URL
CODE_SEARCH_BRANCH=develop bash test_install.sh > output.txt
assert "Branch uses branch URL" "grep -q 'BASE_URL=https://raw.githubusercontent.com/jjveleber/claude-code-search/develop' output.txt"

# Test default URL
bash test_install.sh > output.txt
assert "Default uses main URL" "grep -q 'BASE_URL=https://raw.githubusercontent.com/jjveleber/claude-code-search/main' output.txt"

teardown

echo ""
echo "=== Test 22: URL reachability check ==="
setup
git init -q
git commit -q --allow-empty -m "init"

cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION=""
REPO_OWNER="${CODE_SEARCH_OWNER:-jjveleber}"

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

if [ "$SOURCE_TYPE" = "version" ] && [[ ! "$SOURCE_VALUE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Invalid version '$SOURCE_VALUE' (expected format: v1.0.0)" >&2
    exit 1
fi

BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/claude-code-search/${SOURCE_VALUE}"

# Test URL reachability
if ! curl -fsSL --head "$BASE_URL/search_code.py" >/dev/null 2>&1; then
    echo "Error: Cannot access $SOURCE_TYPE '$SOURCE_VALUE'" >&2
    echo "  URL: $BASE_URL" >&2
    echo "  Check that the $SOURCE_TYPE exists and is accessible" >&2
    exit 1
fi

echo "REACHABLE"
INSTALL_SCRIPT

# Test with nonexistent version
output=$(CODE_SEARCH_VERSION=v999.999.999 bash test_install.sh 2>&1 || true)
if echo "$output" | grep -q "Error: Cannot access version"; then
    echo "  PASS: Detects unreachable version"
    PASS=$((PASS + 1))
else
    echo "  FAIL: Should detect unreachable version"
    FAIL=$((FAIL + 1))
fi

# Test with nonexistent branch
output=$(CODE_SEARCH_BRANCH=nonexistent-branch-name bash test_install.sh 2>&1 || true)
if echo "$output" | grep -q "Error: Cannot access branch"; then
    echo "  PASS: Detects unreachable branch"
    PASS=$((PASS + 1))
else
    echo "  FAIL: Should detect unreachable branch"
    FAIL=$((FAIL + 1))
fi

echo "=== Test 23: Version tracking file creation ==="
setup
git init -q
git commit -q --allow-empty -m "init"
CODE_SEARCH_LOCAL="$REPO_ROOT" bash "$REPO_ROOT/install.sh" >/dev/null 2>&1
assert ".code-search-version created"                      "[ -f .code-search-version ]"
assert ".code-search-version in .gitignore"                "grep -qxF '.code-search-version' .gitignore"
assert "Contains SOURCE_TYPE=branch"                       "grep -q 'SOURCE_TYPE=branch' .code-search-version"
assert "Contains SOURCE_VALUE=main"                        "grep -q 'SOURCE_VALUE=main' .code-search-version"
assert "Contains INSTALL_DATE"                             "grep -q 'INSTALL_DATE=' .code-search-version"
assert "search_code.py --version works"                    ".venv/bin/python3 search_code.py --version | grep -q 'SOURCE_TYPE=branch'"
teardown

echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "All $PASS tests passed."
else
    echo "$PASS passed, $FAIL FAILED."
    exit 1
fi
