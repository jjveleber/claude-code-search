#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${CODE_SEARCH_OWNER:-jjveleber}"
BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/code-search/main"

# Step 1: Check Python version
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]; }; then
    echo "Error: Python 3.9+ required (found $(python3 --version))"
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
# the .venv/bin/activate instructions in CLAUDE.md incorrect.
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
if [ "$VENV_EXISTED" = true ]; then
    _VENV_MTIME_REF=$(mktemp)
    trap '[ -n "${_VENV_MTIME_REF:-}" ] && rm -f "$_VENV_MTIME_REF"' EXIT
    touch -r "$VENV_PATH" "$_VENV_MTIME_REF"
fi

# Step 4: Install chromadb
"$VENV_PATH/bin/pip" install "chromadb>=1.0" --quiet

# Restore venv directory mtime to signal reuse (not recreation)
if [ "$VENV_EXISTED" = true ] && [ -n "${_VENV_MTIME_REF:-}" ]; then
    touch -m -r "$_VENV_MTIME_REF" "$VENV_PATH" 2>/dev/null || true
    rm -f "$_VENV_MTIME_REF"
fi

# Step 5: Download files (skip if already present)
# CODE_SEARCH_LOCAL: if set, copy from that directory instead of curling (used for testing)
for FILE in index_project.py search_code.py; do
    if [ ! -f "$FILE" ]; then
        if [ -n "${CODE_SEARCH_LOCAL:-}" ]; then
            cp "${CODE_SEARCH_LOCAL}/$FILE" "./$FILE"
        else
            curl -fsSL "$BASE_URL/$FILE" -o "$FILE"
        fi
        echo "Installed $FILE"
    else
        echo "$FILE already exists, skipping"
    fi
done

# Step 6: Update .gitignore
if [ ! -f ".gitignore" ]; then
    printf "chroma_db/\n" > .gitignore
    echo "Created .gitignore"
elif ! grep -qxF "chroma_db/" .gitignore; then
    printf "\nchroma_db/\n" >> .gitignore
    echo "Added chroma_db/ to .gitignore"
else
    echo "chroma_db/ already in .gitignore"
fi

# Step 7: Update CLAUDE.md with Precision Protocol
SENTINEL="<!-- code-search:start -->"
CLAUDE_BLOCK="<!-- code-search:start -->
## Precision Protocol
1. **Search First:** Run \`source .venv/bin/activate && python3 search_code.py \"<query>\"\` to find relevant chunks.
2. **Verify:** Use the \`Read\` tool on the path from the search result.
3. **Validate:** If it's the wrong spot, refine the search query and repeat.
4. **Edit:** Only modify once the file content is verified.

**Environment:** Always activate the virtual environment via \`source .venv/bin/activate\` before running project scripts.
<!-- code-search:end -->"

if [ ! -f "CLAUDE.md" ]; then
    printf "%s\n" "$CLAUDE_BLOCK" > CLAUDE.md
    echo "Created CLAUDE.md with Precision Protocol"
elif ! grep -qF "$SENTINEL" CLAUDE.md; then
    printf "\n%s\n" "$CLAUDE_BLOCK" >> CLAUDE.md
    echo "Appended Precision Protocol to CLAUDE.md"
else
    echo "Precision Protocol already in CLAUDE.md"
fi

# Step 8: Run first index
if [ "$IS_GIT_REPO" = true ]; then
    echo "Building initial index..."
    "$VENV_PATH/bin/python3" index_project.py
fi

echo ""
echo "code-search installed successfully"
echo "  Venv:     $VENV_PATH"
echo "  Re-index: source .venv/bin/activate && python3 index_project.py"
echo "  Search:   source .venv/bin/activate && python3 search_code.py \"<query>\""
