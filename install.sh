#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${CODE_SEARCH_OWNER:-jjveleber}"
BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/claude-code-search/main"

# Step 1: Check Python version
# TODO: determine the full supported range (floor and ceiling) for torch/transformers compatibility.
#       Known: 3.12 works. 3.14 does not. Using strict 3.12 until range is confirmed.
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_MAJOR" -ne 3 ] || [ "$PYTHON_MINOR" -ne 12 ]; then
    echo "Error: Python 3.12 required (found $(python3 --version))"
    exit 1
fi

# Step 2: Check git repo
IS_GIT_REPO=true
if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    IS_GIT_REPO=false
    echo "Warning: Not a git repo — skipping index build. Run 'python3 index_project.py' manually after initializing git."
fi

# Step 3: Detect or create venv
# Priority: project .venv > create new .venv
# VIRTUAL_ENV is intentionally ignored — using a foreign venv would make
# the .venv/bin/activate instructions in .claude/CLAUDE.md incorrect.
VENV_EXISTED=false
if [ -d ".venv" ]; then
    VENV_PATH="$(pwd)/.venv"
    VENV_EXISTED=true
else
    echo "Creating .venv..."
    python3 -m venv .venv
    VENV_PATH="$(pwd)/.venv"
fi
echo "Using venv: $VENV_PATH"

# Save a reference file for mtime restoration when reusing an existing venv.
# pip may create new subdirs in .venv/ (e.g. share/) which would change its mtime
# even though the venv was not recreated. touch -r is POSIX-portable (GNU + BSD).
_VENV_MTIME_REF=""
_CS_TMPFILES=()
_CS_CLEANUP() {
    [ -n "${_VENV_MTIME_REF:-}" ] && rm -f "$_VENV_MTIME_REF"
    for _f in "${_CS_TMPFILES[@]+"${_CS_TMPFILES[@]}"}"; do
        rm -f "$_f"
    done
}
trap '_CS_CLEANUP' EXIT

if [ "$VENV_EXISTED" = true ]; then
    _VENV_MTIME_REF=$(mktemp)
    touch -r "$VENV_PATH" "$_VENV_MTIME_REF"
fi

# Step 4: Install chromadb
"$VENV_PATH/bin/python3" -m pip install --upgrade pip

"$VENV_PATH/bin/pip" install \
  "chromadb>=1.0" \
  "watchdog>=3.0" \
  "transformers==4.46.3" \
  "sentencepiece==0.2.0" \
  "psutil>=5.9" \
  "torch==2.11.0" \
  "rank_bm25>=0.2.2"

# Restore venv directory mtime to signal reuse (not recreation)
if [ "$VENV_EXISTED" = true ] && [ -n "${_VENV_MTIME_REF:-}" ]; then
    touch -m -r "$_VENV_MTIME_REF" "$VENV_PATH" 2>/dev/null || true
    rm -f "$_VENV_MTIME_REF"
fi

# Step 5: Download files (always overwrite — install acts as update)
# Downloads to temp files first; moves into place only after all succeed,
# so a partial failure (e.g. network error) leaves existing files untouched.
# CODE_SEARCH_LOCAL: if set, copy from that directory instead of curling (used for testing)
_CS_FILES=(index_project.py search_code.py watch_index.py)
_CS_FILE_EXISTED=()

# Phase 1: record pre-existence and download to temp files
for FILE in "${_CS_FILES[@]}"; do
    if [ -f "$FILE" ]; then
        _CS_FILE_EXISTED+=(true)
    else
        _CS_FILE_EXISTED+=(false)
    fi

    TMPFILE=$(mktemp "${FILE}.XXXXXX")
    _CS_TMPFILES+=("$TMPFILE")

    if [ -n "${CODE_SEARCH_LOCAL:-}" ]; then
        cp "${CODE_SEARCH_LOCAL}/$FILE" "$TMPFILE"
    else
        curl -fsSL "$BASE_URL/$FILE" -o "$TMPFILE"
    fi
done

# Phase 2: all downloads succeeded — move into place and report
for i in "${!_CS_FILES[@]}"; do
    FILE="${_CS_FILES[$i]}"
    mv "${_CS_TMPFILES[$i]}" "$FILE"
    if [ "${_CS_FILE_EXISTED[$i]}" = true ]; then
        echo "Updated $FILE"
    else
        echo "Installed $FILE"
    fi
done

# Step 6: Update .gitignore
if [ ! -f ".gitignore" ]; then
    printf "chroma_db/\n.watch_index.log\n.watch_index.pid\n.claude/settings.local.json\n.claude/CLAUDE.md\n" > .gitignore
    echo "Created .gitignore"
else
    if ! grep -qxF "chroma_db/" .gitignore; then
        printf "\nchroma_db/\n" >> .gitignore
        echo "Added chroma_db/ to .gitignore"
    else
        echo "chroma_db/ already in .gitignore"
    fi
    for WATCH_IGNORE in ".watch_index.log" ".watch_index.pid" ".claude/settings.local.json" ".claude/CLAUDE.md"; do
        if ! grep -qxF "$WATCH_IGNORE" .gitignore; then
            printf "\n%s\n" "$WATCH_IGNORE" >> .gitignore
            echo "Added $WATCH_IGNORE to .gitignore"
        else
            echo "$WATCH_IGNORE already in .gitignore"
        fi
    done
fi

# Step 7: Write Precision Protocol to .claude/CLAUDE.md (local-only, not committed)
mkdir -p .claude
SENTINEL="<!-- code-search:start -->"
CLAUDE_BLOCK="<!-- code-search:start -->
## Precision Protocol

**Rule:** Before using \`Read\`, \`Grep\`, or \`Glob\` — if the exact file path was not given to you in the current task, run \`.venv/bin/python3 search_code.py \"<query>\"\` first.

1. **File path given in task?**
   - **Yes** → go to step 2
   - **No** → run \`.venv/bin/python3 search_code.py \"<query>\"\`, then go to step 2
2. **Grep** the exact location, then **Read** to confirm context.
3. If wrong spot, refine and repeat from step 2.
4. **Edit** only after verified.

**Never use \`search_code.py\` when the file is already known — that is what \`Grep\` is for.**

**Environment:** Always activate the virtual environment via \`source .venv/bin/activate\` before running project scripts.
<!-- code-search:end -->"

if [ ! -f ".claude/CLAUDE.md" ]; then
    printf "%s\n" "$CLAUDE_BLOCK" > .claude/CLAUDE.md
    echo "Created .claude/CLAUDE.md with Precision Protocol"
elif ! grep -qF "$SENTINEL" .claude/CLAUDE.md; then
    printf "\n%s\n" "$CLAUDE_BLOCK" >> .claude/CLAUDE.md
    echo "Appended Precision Protocol to .claude/CLAUDE.md"
else
    CLAUDE_BLOCK="$CLAUDE_BLOCK" python3 - <<'PYEOF'
import re, pathlib, os
p = pathlib.Path(".claude/CLAUDE.md")
content = p.read_text()
new_block = os.environ["CLAUDE_BLOCK"]
updated = re.sub(r"<!-- code-search:start -->.*?<!-- code-search:end -->", new_block, content, flags=re.DOTALL)
p.write_text(updated)
PYEOF
    echo "Updated Precision Protocol in .claude/CLAUDE.md"
fi

# Step 7b: Remove legacy blocks from CLAUDE.md (migrates old installs)
if [ -f "CLAUDE.md" ]; then
    python3 - <<'PYEOF'
import re, pathlib
p = pathlib.Path("CLAUDE.md")
content = p.read_text()
original = content
# Remove legacy Session Startup block
content = re.sub(r"\n?<!-- code-search-watch:start -->.*?<!-- code-search-watch:end -->\n?", "", content, flags=re.DOTALL)
# Migrate Precision Protocol block out of CLAUDE.md (now lives in .claude/CLAUDE.md)
content = re.sub(r"\n?<!-- code-search:start -->.*?<!-- code-search:end -->\n?", "", content, flags=re.DOTALL)
if content != original:
    p.write_text(content)
    print("Removed legacy code-search blocks from CLAUDE.md")
PYEOF
fi

# Step 8: Configure per-project Claude hook to auto-start watcher (local-only, not committed)
# Uses settings.local.json so the hook only applies to the installing user.
python3 - <<'PYEOF'
import json, pathlib

hook_cmd = (
    'if [ -f "watch_index.py" ] && [ -f ".venv/bin/python3" ]; then '
    '  .venv/bin/python3 index_project.py >> .watch_index.log 2>&1 & '
    '  .venv/bin/python3 watch_index.py >> .watch_index.log 2>&1 & '
    'fi'
)

# Migrate: remove hook from settings.json if placed there by an older install
shared_p = pathlib.Path(".claude/settings.json")
if shared_p.exists():
    try:
        shared = json.loads(shared_p.read_text())
        prompt_hooks = shared.get("hooks", {}).get("UserPromptSubmit", [])
        filtered = [
            g for g in prompt_hooks
            if not any(h.get("command") == hook_cmd for h in g.get("hooks", []))
        ]
        if len(filtered) < len(prompt_hooks):
            shared["hooks"]["UserPromptSubmit"] = filtered
            if not shared["hooks"]["UserPromptSubmit"]:
                del shared["hooks"]["UserPromptSubmit"]
            if not shared.get("hooks"):
                del shared["hooks"]
            if not shared:
                shared_p.unlink()
            else:
                shared_p.write_text(json.dumps(shared, indent=2) + "\n")
            print("Migrated hook out of .claude/settings.json")
    except (json.JSONDecodeError, KeyError, AttributeError, TypeError):
        pass

# Write hook to settings.local.json (gitignored, per-user)
local_p = pathlib.Path(".claude/settings.local.json")
local_settings = json.loads(local_p.read_text()) if local_p.exists() else {}

hooks = local_settings.setdefault("hooks", {})
prompt_hooks = hooks.setdefault("UserPromptSubmit", [])

already_present = any(
    h.get("command") == hook_cmd
    for group in prompt_hooks
    for h in group.get("hooks", [])
)

# Migrate: remove legacy PostToolUse hook from settings.local.json
post_hooks = local_settings.get("hooks", {}).get("PostToolUse", [])
filtered_post = [
    g for g in post_hooks
    if not any("index_project.py" in h.get("command", "") for h in g.get("hooks", []))
]
if len(filtered_post) < len(post_hooks):
    local_settings["hooks"]["PostToolUse"] = filtered_post
    if not local_settings["hooks"]["PostToolUse"]:
        del local_settings["hooks"]["PostToolUse"]
    print("Removed legacy PostToolUse hook from .claude/settings.local.json")

if not already_present:
    prompt_hooks.append({"hooks": [{"type": "command", "command": hook_cmd}]})
    print("Configured auto-watcher hook in .claude/settings.local.json")
else:
    print("Auto-watcher hook already configured")

local_p.write_text(json.dumps(local_settings, indent=2) + "\n")
PYEOF

# Step 9: Run first index (skip if index already exists)
if [ "$IS_GIT_REPO" = true ] && [ ! -d "chroma_db" ]; then
    echo "Building initial index..."
    "$VENV_PATH/bin/python3" index_project.py
elif [ "$IS_GIT_REPO" = true ]; then
    echo "chroma_db index already exists, skipping"
fi

echo ""
echo "code-search installed successfully"
echo "  Venv:     $VENV_PATH"
echo "  Re-index: .venv/bin/python3 index_project.py"
echo "  Watch:    .venv/bin/python3 watch_index.py >> .watch_index.log 2>&1 &"
echo "  Search:   .venv/bin/python3 search_code.py \"<query>\""
