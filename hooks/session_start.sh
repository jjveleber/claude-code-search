#!/usr/bin/env bash
# SessionStart: gate on registry, ensure daemon+watch, inject Precision Protocol.
set -uo pipefail
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${PLUGIN_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

python3 <(cat <<'PYEOF'
import json
import os
import sys
from pathlib import Path

from engine import registry, setup_venv

payload = json.load(sys.stdin)
cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
session_id = payload.get("session_id", "unknown")

r = registry.resolve(Path(cwd))
if not r.family_enabled:
    sys.exit(0)                     # silent for unregistered repos

if not r.registered:
    # inherited enablement: auto-register this worktree
    r = registry.register_worktree(Path(cwd))

if not setup_venv.venv_ok():
    print("code-search: central venv missing or stale — run: code-search setup",
          file=sys.stderr)
    sys.exit(0)                     # session proceeds without search

if not os.environ.get("CODE_SEARCH_SKIP_DAEMON"):   # test escape hatch
    from engine import client
    try:
        resp = client.watch(cwd, os.getppid())
        if not resp.get("ok"):
            print(f"code-search: watch failed: {resp.get('error')}",
                  file=sys.stderr)
            sys.exit(0)
    except client.DaemonUnavailable as e:
        print(f"code-search: daemon unavailable: {e}", file=sys.stderr)
        sys.exit(0)

protocol = """## Precision Protocol

**Rule:** Before using `Read`, `Grep`, or `Glob` — if the exact file path was \
not given to you in the current task, run `code-search search "<query>"` first.

1. **File path given in task?**
   - **Yes** -> go to step 2
   - **No** -> run `code-search search "<query>"`, then go to step 2
2. **Grep** the exact location, then **Read** to confirm context.
3. If wrong spot, refine and repeat from step 2.
4. **Edit** only after verified.

**Never use `code-search` when the file is already known — that is what \
`Grep` is for.**

**Search scope:** Production and test code by default; results are labeled \
`[prod]`, `[test]`, `[doc]`, or `[generated]`. Use `--all` to include docs \
and generated files. Use `--top N` for more results."""

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": protocol,
}}))
PYEOF
)
