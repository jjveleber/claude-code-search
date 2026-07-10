#!/usr/bin/env bash
# SessionEnd: best-effort unwatch. Daemon pid-pruning is the backstop.
set -uo pipefail
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${PLUGIN_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

# $PPID = the long-lived Claude process that launched this hook (matches the
# pid session_start.sh registered the watch under). python's own
# os.getppid() would instead see this transient bash shell's pid — see
# session_start.sh for the full explanation. Using the wrong pid here makes
# unwatch a silent no-op against a pid that was never registered.
export CODE_SEARCH_SESSION_PID="$PPID"

python3 <(cat <<'PYEOF'
import json
import os
import sys
from pathlib import Path

from engine import registry

payload = json.load(sys.stdin)
cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
r = registry.resolve(Path(cwd))
if not r.registered:
    sys.exit(0)
session_pid = int(os.environ["CODE_SEARCH_SESSION_PID"])

if not os.environ.get("CODE_SEARCH_SKIP_DAEMON"):   # test escape hatch
    from engine import client
    client.unwatch(cwd, session_pid)   # swallows DaemonUnavailable internally
else:
    # test-only debug line: exposes the pid that WOULD have been unwatched,
    # so test_hooks.sh can assert it's the long-lived caller pid and not
    # python's transient getppid().
    print(f"code-search: [skip-daemon] session_pid={session_pid}",
          file=sys.stderr)
PYEOF
)
exit 0
