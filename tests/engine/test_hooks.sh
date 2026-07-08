#!/usr/bin/env bash
# tests/engine/test_hooks.sh — hook contract tests with stdin JSON fixtures.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CODE_SEARCH_HOME="$TMP/csh"

fail() { echo "FAIL: $1"; exit 1; }

# fixture repo
REPO="$TMP/repo"
mkdir -p "$REPO" && cd "$REPO"
git init -q && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m i

# Test 1: unregistered repo -> exit 0, empty stdout
OUT=$(echo "{\"session_id\":\"s1\",\"cwd\":\"$REPO\"}" \
      | "$ROOT/hooks/session_start.sh") || fail "hook exited non-zero"
[ -z "$OUT" ] || fail "expected no output for unregistered repo, got: $OUT"

# Test 2: registered repo, no venv -> stderr warning, still exit 0, no context
PYTHONPATH="$ROOT" python3 -c "
from pathlib import Path
from engine import registry
registry.enable(Path('$REPO'))
"
ERR=$(echo "{\"session_id\":\"s1\",\"cwd\":\"$REPO\"}" \
      | "$ROOT/hooks/session_start.sh" 2>&1 >/dev/null) || fail "hook non-zero"
echo "$ERR" | grep -q "code-search setup" || fail "expected setup warning"

# Test 3: registered repo, venv.ok faked -> emits additionalContext JSON
mkdir -p "$CODE_SEARCH_HOME"
python3 - <<EOF
import hashlib, pathlib
req = pathlib.Path("$ROOT/engine/requirements.txt").read_bytes()
pathlib.Path("$CODE_SEARCH_HOME/venv.ok").write_text(
    hashlib.sha256(req).hexdigest())
EOF
OUT=$(echo "{\"session_id\":\"s1\",\"cwd\":\"$REPO\"}" \
      | CODE_SEARCH_SKIP_DAEMON=1 "$ROOT/hooks/session_start.sh")
echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
ctx = d['hookSpecificOutput']['additionalContext']
assert 'Precision Protocol' in ctx and 'code-search search' in ctx
assert d['hookSpecificOutput']['hookEventName'] == 'SessionStart'
" || fail "additionalContext malformed"

# Test 4: session_end on unregistered repo -> silent success
echo "{\"session_id\":\"s1\",\"cwd\":\"$TMP\"}" \
    | "$ROOT/hooks/session_end.sh" || fail "session_end non-zero"

echo "ALL HOOK TESTS PASSED"
