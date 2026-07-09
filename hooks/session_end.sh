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
from engine import client
session_pid = int(os.environ["CODE_SEARCH_SESSION_PID"])
client.unwatch(cwd, session_pid)   # swallows DaemonUnavailable internally
PYEOF
)
exit 0
