#!/usr/bin/env bash
# SessionStart: gate on registry, ensure daemon+watch, inject Precision Protocol.
set -uo pipefail
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${PLUGIN_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

# $PPID here is THIS script's parent — the long-lived Claude process that
# launched the hook. We must NOT use python's own os.getppid() below: since
# python runs as `python3 <(...)`, its parent is this transient bash shell,
# which exits as soon as the hook finishes. Registering the watch under that
# pid causes the daemon's prune_loop to reap it within one prune cycle
# (<=60s), even though the real session is still running.
export CODE_SEARCH_SESSION_PID="$PPID"

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

# The long-lived session pid, captured by the wrapping bash script as its
# own $PPID (see comment there for why python's os.getppid() is wrong).
session_pid = int(os.environ["CODE_SEARCH_SESSION_PID"])

if not os.environ.get("CODE_SEARCH_SKIP_DAEMON"):   # test escape hatch
    from engine import client
    try:
        resp = client.watch(cwd, session_pid)
        if not resp.get("ok"):
            print(f"code-search: watch failed: {resp.get('error')}",
                  file=sys.stderr)
            sys.exit(0)
    except client.DaemonUnavailable as e:
        print(f"code-search: daemon unavailable: {e}", file=sys.stderr)
        sys.exit(0)
else:
    # test-only debug line: exposes the pid that WOULD have been registered,
    # so test_hooks.sh can assert it's the long-lived caller pid and not
    # python's transient getppid().
    print(f"code-search: [skip-daemon] session_pid={session_pid}",
          file=sys.stderr)

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
