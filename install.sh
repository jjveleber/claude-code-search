#!/usr/bin/env bash
set -euo pipefail

# Auto-detected install source (set during release via GitHub Actions)
# Empty = main branch, "v1.0.0" = release version
INSTALL_VERSION=""

# Determine installation source with priority: env var > embedded > default
if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    # Explicit version override
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    # Explicit branch override
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    # Embedded version from release
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    # Default to main
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

REPO_OWNER="${CODE_SEARCH_OWNER:-jjveleber}"

# Version format validation
if [ "$SOURCE_TYPE" = "version" ] && [[ ! "$SOURCE_VALUE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Invalid version '$SOURCE_VALUE' (expected format: v1.0.0)" >&2
    exit 1
fi

# Construct BASE_URL based on source type
BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/claude-code-search/${SOURCE_VALUE}"

# Test URL reachability before proceeding (skip if using local files)
if [ -z "${CODE_SEARCH_LOCAL:-}" ]; then
    if ! curl -fsSL --head "$BASE_URL/search_code.py" >/dev/null 2>&1; then
        echo "Error: Cannot access $SOURCE_TYPE '$SOURCE_VALUE'" >&2
        echo "  URL: $BASE_URL" >&2
        echo "  Check that the $SOURCE_TYPE exists and is accessible" >&2
        exit 1
    fi
fi

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

# Step 3: Detect or create isolated venv for code-search
# Uses .venv-code-search to avoid conflicts with project's .venv
# VIRTUAL_ENV is intentionally ignored — using a foreign venv would make
# the .venv-code-search/bin/activate instructions in .claude/CLAUDE.md incorrect.
VENV_EXISTED=false
if [ -d ".venv-code-search" ]; then
    VENV_PATH="$(pwd)/.venv-code-search"
    VENV_EXISTED=true
else
    echo "Creating .venv-code-search..."
    python3 -m venv .venv-code-search
    VENV_PATH="$(pwd)/.venv-code-search"
fi
echo "Using venv: $VENV_PATH"

# Save a reference file for mtime restoration when reusing an existing venv.
# pip may create new subdirs in .venv-code-search/ (e.g. share/) which would change its mtime
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

# Step 3b: WSL2 AMD GPU — install ROCm if /dev/dxg is present and ROCm not yet set up
_ROCM_VERSION="7.2"
_ROCM_BUILD="70200-1"
_ROCM_TORCH=false
if [ -e /dev/dxg ]; then
    echo ""
    echo "AMD GPU detected (WSL2 with /dev/dxg). Checking ROCm..."

    # Under pipefail, use `|| true` on rocminfo so grep controls the exit status
    if { HSA_ENABLE_DXG_DETECTION=1 rocminfo 2>/dev/null || true; } | grep -q "gfx"; then
        echo "  ROCm already installed and GPU detected. Skipping ROCm setup."
        _ROCM_TORCH=true
    elif ! command -v sudo &>/dev/null; then
        echo "  sudo not available — skipping ROCm install. Falling back to CPU."
    else
        echo "  ROCm not found. Installing ROCm ${_ROCM_VERSION}.x (requires sudo, ~2-3 GB download)..."
        echo "  You may be prompted for your password."
        echo ""

        _UBUNTU_CODENAME=$(. /etc/os-release 2>/dev/null && echo "${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}") || true
        case "$_UBUNTU_CODENAME" in
            noble) _ROCM_DEB="https://repo.radeon.com/amdgpu-install/${_ROCM_VERSION}/ubuntu/noble/amdgpu-install_${_ROCM_VERSION}.${_ROCM_BUILD}_all.deb" ;;
            jammy) _ROCM_DEB="https://repo.radeon.com/amdgpu-install/${_ROCM_VERSION}/ubuntu/jammy/amdgpu-install_${_ROCM_VERSION}.${_ROCM_BUILD}_all.deb" ;;
            *)
                echo "  Unsupported distro '$_UBUNTU_CODENAME' — skipping ROCm install."
                echo "  See: https://rocm.docs.amd.com/projects/install-on-linux/en/latest/"
                _UBUNTU_CODENAME=""
                ;;
        esac

        if [ -n "${_UBUNTU_CODENAME:-}" ]; then
            curl -fsSL "$_ROCM_DEB" -o /tmp/amdgpu-install.deb
            sudo apt install -y /tmp/amdgpu-install.deb
            sudo amdgpu-install --usecase=rocm --no-dkms -y
            sudo usermod -a -G render,video "$USER"
            rm -f /tmp/amdgpu-install.deb

            # Note: usermod group changes require a WSL2 restart to take effect.
            # The GPU check below may false-negative in the same session; if so,
            # re-run install.sh after: wsl --shutdown (from PowerShell).
            # The PyTorch ROCm wheel (below) is also skipped until the second run
            # after restart, when the GPU becomes visible to rocminfo.
            if { HSA_ENABLE_DXG_DETECTION=1 rocminfo 2>/dev/null || true; } | grep -q "gfx"; then
                echo "  ROCm installed successfully. GPU detected."
                _ROCM_TORCH=true
            else
                echo "  ROCm installed. GPU not yet visible (WSL2 restart may be needed)."
                echo "  From PowerShell: wsl --shutdown — then re-run install.sh."
            fi
        fi
    fi

    # Only persist the env var when GPU was confirmed working
    if [ "$_ROCM_TORCH" = true ]; then
        if ! grep -q "HSA_ENABLE_DXG_DETECTION" ~/.bashrc 2>/dev/null; then
            echo 'export HSA_ENABLE_DXG_DETECTION=1' >> ~/.bashrc
            echo "  Added HSA_ENABLE_DXG_DETECTION=1 to ~/.bashrc"
        fi
    fi
fi

# Step 4: Install chromadb
"$VENV_PATH/bin/python3" -m pip install --upgrade pip

# Install ROCm PyTorch before sentence-transformers so pip's resolver keeps it
if [ "$_ROCM_TORCH" = true ]; then
    echo "Installing PyTorch ROCm build..."
    if ! "$VENV_PATH/bin/python3" -c "import torch; assert 'rocm' in torch.__version__" 2>/dev/null; then
        "$VENV_PATH/bin/pip" install torch --index-url "https://download.pytorch.org/whl/rocm${_ROCM_VERSION}"
        echo "  PyTorch ROCm installed."
    else
        echo "  PyTorch ROCm already installed."
    fi
fi

"$VENV_PATH/bin/pip" install \
  "chromadb>=1.0" \
  "watchdog>=3.0" \
  "sentence-transformers>=3.0" \
  "einops>=0.7" \
  "psutil>=5.9" \
  "tree-sitter<0.22" \
  "tree-sitter-languages>=1.10" \
  "rank_bm25>=0.2.2"

# Restore venv directory mtime to signal reuse (not recreation)
if [ "$VENV_EXISTED" = true ] && [ -n "${_VENV_MTIME_REF:-}" ]; then
    touch -m -r "$_VENV_MTIME_REF" "$VENV_PATH" 2>/dev/null || true
    rm -f "$_VENV_MTIME_REF"
fi

# Step 4b: Create logs directory for search usage tracking
mkdir -p logs
touch logs/.gitkeep
echo "Created logs/ directory"

# Step 5: Download files (always overwrite — install acts as update)
# Downloads to temp files first; moves into place only after all succeed,
# so a partial failure (e.g. network error) leaves existing files untouched.
# CODE_SEARCH_LOCAL: if set, copy from that directory instead of curling (used for testing)
_CS_FILES=(index_project.py search_code.py watch_index.py chunker.py search_server.py)
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

# Step 5b: Install hook scripts
mkdir -p hooks
for HOOK in post_search_code.sh pre_read_grep_glob.sh; do
    if [ -n "${CODE_SEARCH_LOCAL:-}" ]; then
        cp "${CODE_SEARCH_LOCAL}/hooks/$HOOK" "hooks/$HOOK"
    else
        curl -fsSL "$BASE_URL/hooks/$HOOK" -o "hooks/$HOOK"
    fi
    chmod +x "hooks/$HOOK"
    if [ -f "hooks/$HOOK" ]; then
        echo "Installed hooks/$HOOK"
    fi
done

# Step 6: Update .gitignore
if [ ! -f ".gitignore" ]; then
    printf ".venv-code-search/\n.venv/\n__pycache__/\nchroma_db/\n.watch_index.log\n.watch_index.pid\n.search_server.pid\n.code-search-version\n.claude/settings.local.json\n.claude/CLAUDE.md\n" > .gitignore
    echo "Created .gitignore"
else
    if ! grep -qxF "chroma_db/" .gitignore; then
        printf "\nchroma_db/\n" >> .gitignore
        echo "Added chroma_db/ to .gitignore"
    else
        echo "chroma_db/ already in .gitignore"
    fi
    for WATCH_IGNORE in ".venv-code-search/" ".venv/" "__pycache__/" ".watch_index.log" ".watch_index.pid" ".search_server.pid" ".code-search-version" ".claude/settings.local.json" ".claude/CLAUDE.md"; do
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

**Rule:** Before using \`Read\`, \`Grep\`, or \`Glob\` — if the exact file path was not given to you in the current task, run \`.venv-code-search/bin/python3 search_code.py \"<query>\"\` first.

1. **File path given in task?**
   - **Yes** → go to step 2
   - **No** → run \`.venv-code-search/bin/python3 search_code.py \"<query>\"\`, then go to step 2
2. **Grep** the exact location, then **Read** to confirm context.
3. If wrong spot, refine and repeat from step 2.
4. **Edit** only after verified.

**Never use \`search_code.py\` when the file is already known — that is what \`Grep\` is for.**

**Search scope:** By default, \`search_code.py\` searches production and test code — documentation and generated files are excluded. Each result includes a \`[prod]\`, \`[test]\`, \`[doc]\`, or \`[generated]\` label.
- If results are all \`[test]\` files but you need implementation code, refine the query (\"find the implementation of X\") and note the mismatch to the user
- If the user's task is explicitly about tests, say so in the query (\"find the test for X\")
- Use \`--all\` to include documentation and generated files when explicitly needed

**Environment:** Always activate the virtual environment via \`source .venv-code-search/bin/activate\` before running project scripts.
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
    'if [ -f "watch_index.py" ] && [ -f ".venv-code-search/bin/python3" ]; then '
    '  .venv-code-search/bin/python3 index_project.py >> .watch_index.log 2>&1 & '
    '  .venv-code-search/bin/python3 watch_index.py >> .watch_index.log 2>&1 & '
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

prompt_hooks = local_settings.setdefault("UserPromptSubmit", [])

already_present = any(
    h.get("command") == hook_cmd
    for group in prompt_hooks
    for h in group.get("hooks", [])
)

# Migrate: remove legacy PostToolUse hook from settings.local.json (check both old and new locations)
for hook_path in [("hooks", "PostToolUse"), ("PostToolUse",)]:
    if len(hook_path) == 2:
        post_hooks = local_settings.get(hook_path[0], {}).get(hook_path[1], [])
    else:
        post_hooks = local_settings.get(hook_path[0], [])

    filtered_post = [
        g for g in post_hooks
        if not any("index_project.py" in h.get("command", "") for h in g.get("hooks", []))
    ]

    if len(filtered_post) < len(post_hooks):
        if len(hook_path) == 2:
            if "hooks" not in local_settings:
                local_settings["hooks"] = {}
            local_settings["hooks"]["PostToolUse"] = filtered_post
            if not local_settings["hooks"]["PostToolUse"]:
                del local_settings["hooks"]["PostToolUse"]
            if not local_settings.get("hooks"):
                del local_settings["hooks"]
        else:
            local_settings["PostToolUse"] = filtered_post
            if not local_settings["PostToolUse"]:
                del local_settings["PostToolUse"]
        print("Removed legacy PostToolUse hook from .claude/settings.local.json")

if not already_present:
    prompt_hooks.append({"hooks": [{"type": "command", "command": hook_cmd}]})
    print("Configured auto-watcher hook in .claude/settings.local.json")
else:
    print("Auto-watcher hook already configured")

local_p.write_text(json.dumps(local_settings, indent=2) + "\n")
PYEOF

# Step 9: Build or rebuild index
# Rebuilds automatically when the embedding model has changed (upgrade path).
# Old installs have no chroma_db/model.txt; new installs write "nomic-ai/CodeRankEmbed".
_EXPECTED_MODEL="nomic-ai/CodeRankEmbed"
if [ "$IS_GIT_REPO" = true ]; then
    if [ ! -d "chroma_db" ]; then
        echo "Building initial index..."
        "$VENV_PATH/bin/python3" index_project.py
    else
        _INSTALLED_MODEL=""
        if [ -f "chroma_db/model.txt" ]; then
            _INSTALLED_MODEL=$(cat "chroma_db/model.txt")
        fi
        if [ "$_INSTALLED_MODEL" != "$_EXPECTED_MODEL" ]; then
            echo "Embedding model changed ('${_INSTALLED_MODEL:-none}' → '${_EXPECTED_MODEL}') — rebuilding index..."
            rm -rf chroma_db
            "$VENV_PATH/bin/python3" index_project.py
        else
            echo "Index is up to date (model: ${_EXPECTED_MODEL})"
        fi
    fi
fi

# Step 10: Install search usage tracking hooks to .claude/settings.local.json
echo "Installing search usage tracking hooks..."

SETTINGS_FILE=".claude/settings.local.json"
HOOKS_DIR="$(pwd)/hooks"

# Create directory if needed
mkdir -p .claude

# Create settings file if it doesn't exist
if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo '{}' > "$SETTINGS_FILE"
fi

# Update settings.local.json with hooks (use Python for JSON manipulation)
HOOKS_DIR="$(pwd)/hooks" python3 - <<'PYTHON_EOF'
import json
import os
from pathlib import Path

settings_file = Path(".claude/settings.local.json")
settings = json.loads(settings_file.read_text())

hooks_dir = os.environ.get("HOOKS_DIR", "")

# Post-tool hook for search_code.py
post_tool = settings.get("PostToolUse", [])
search_hook_cmd = f"if [[ \"$TOOL_COMMAND\" == *search_code.py* ]]; then source {hooks_dir}/post_search_code.sh; fi"
# Check if hook already exists by comparing command
already_exists = any(
    hook.get("command") == search_hook_cmd
    for group in post_tool
    for hook in group.get("hooks", [])
)
if not already_exists:
    post_tool.append({"hooks": [{"type": "command", "command": search_hook_cmd}]})
settings["PostToolUse"] = post_tool

# Pre-tool hook for Read/Grep/Glob
pre_tool = settings.get("PreToolUse", [])
rgg_hook_cmd = f"if [[ \"$TOOL_NAME\" == Read ]] || [[ \"$TOOL_NAME\" == Grep ]] || [[ \"$TOOL_NAME\" == Glob ]]; then source {hooks_dir}/pre_read_grep_glob.sh; fi"
# Check if hook already exists by comparing command
already_exists = any(
    hook.get("command") == rgg_hook_cmd
    for group in pre_tool
    for hook in group.get("hooks", [])
)
if not already_exists:
    pre_tool.append({"hooks": [{"type": "command", "command": rgg_hook_cmd}]})
settings["PreToolUse"] = pre_tool

# Set default config
if "searchUsageTracking" not in settings:
    settings["searchUsageTracking"] = {
        "warningsVisible": False,
        "warningsBlocking": False,
        "searchStateTTL": 300,
        "recentPathTTL": 600
    }

settings_file.write_text(json.dumps(settings, indent=2))
print("Hooks installed successfully")
PYTHON_EOF

echo "Hooks installed. Run 'python3 tools/analyze_search_usage.py' to view analytics."

# Step 11: Record installation version/branch
cat > .code-search-version <<EOF
SOURCE_TYPE=$SOURCE_TYPE
SOURCE_VALUE=$SOURCE_VALUE
INSTALL_DATE=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
EOF


echo ""
echo "code-search installed successfully"
echo "  Venv:     $VENV_PATH"
echo "  Re-index: .venv-code-search/bin/python3 index_project.py"
echo "  Watch:    .venv-code-search/bin/python3 watch_index.py >> .watch_index.log 2>&1 &"
echo "  Server:   .venv-code-search/bin/python3 search_server.py &   # optional: warm model for fast search"
echo "  Search:   .venv-code-search/bin/python3 search_code.py \"<query>\""
