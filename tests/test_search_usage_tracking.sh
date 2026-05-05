#!/usr/bin/env bash
# Integration test for search usage tracking system

set -e

TEST_DIR=$(mktemp -d)
ORIGINAL_DIR=$(pwd)

echo "=== Integration Test: Search Usage Tracking ==="

# Setup: initialize temp directory as git repo and install
cd "$TEST_DIR"
git init -q
git config --local user.email "test@test.com"
git config --local user.name "Test"
git commit -q --allow-empty -m "init"

# Install from local source
CODE_SEARCH_LOCAL="$ORIGINAL_DIR" bash "$ORIGINAL_DIR/install.sh" > /dev/null

# Copy hooks and tools from original directory
cp -r "$ORIGINAL_DIR/hooks" .
cp -r "$ORIGINAL_DIR/tools" .

# Ensure clean state
rm -rf logs
mkdir -p logs

source .venv/bin/activate

# Test 1: Search logging
echo "Test 1: Search creates log entry..."
python3 search_code.py "authentication" --top 3 > /dev/null 2>&1 || true
[[ -f logs/search_usage.jsonl ]] || { echo "FAIL: No log file created"; exit 1; }
grep -q '"event_type": "search"' logs/search_usage.jsonl || { echo "FAIL: No search event logged"; exit 1; }
echo "PASS"

# Test 2: Post-hook sets env vars
echo "Test 2: Post-hook sets environment..."
export TOOL_COMMAND='python3 search_code.py "test query" --top 5'
export TOOL_OUTPUT='MATCH 1: src/test.py'
source hooks/post_search_code.sh
[[ -n "$LAST_SEARCH_TIME" ]] || { echo "FAIL: LAST_SEARCH_TIME not set"; exit 1; }
[[ "$LAST_SEARCH_QUERY" == "test query" ]] || { echo "FAIL: Query mismatch"; exit 1; }
echo "PASS"

# Test 3: Pre-hook exempts recent search
echo "Test 3: Pre-hook exempts after recent search..."
export LAST_SEARCH_TIME=$(date +%s)
export TOOL_NAME="Read"
export TOOL_PARAMS='file_path="src/auth.py"'
bash hooks/pre_read_grep_glob.sh
grep -q "src/auth.py" logs/search_warnings.log && { echo "FAIL: Recent search not exempted"; exit 1; } || true
echo "PASS"

# Test 4: Pre-hook logs violation without search
echo "Test 4: Pre-hook logs violation without search..."
unset LAST_SEARCH_TIME
export TOOL_PARAMS='file_path="src/violation.py"'
bash hooks/pre_read_grep_glob.sh
grep -q "src/violation.py" logs/search_warnings.log || { echo "FAIL: Violation not logged"; exit 1; }
echo "PASS"

# Test 5: Analytics tool runs
echo "Test 5: Analytics tool produces report..."
python3 tools/analyze_search_usage.py > /tmp/analytics_output.txt
grep -q "Compliance Rate" /tmp/analytics_output.txt || { echo "FAIL: Analytics incomplete"; exit 1; }
echo "PASS"

echo ""
echo "=== All Tests Passed ==="
echo "Cleaning up $TEST_DIR"
rm -rf "$TEST_DIR"
