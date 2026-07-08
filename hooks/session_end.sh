#!/usr/bin/env bash
# SessionEnd: best-effort unwatch. Daemon pid-pruning is the backstop.
set -uo pipefail
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${PLUGIN_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

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
client.unwatch(cwd, os.getppid())   # swallows DaemonUnavailable internally
PYEOF
)
exit 0
