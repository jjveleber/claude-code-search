#!/usr/bin/env bash
# Pre-tool hook: detect Precision Protocol violations
# Triggered before Read/Grep/Glob

# Config (override via env)
SEARCH_STATE_TTL=${SEARCH_STATE_TTL:-300}        # 5 minutes
RECENT_PATH_TTL=${RECENT_PATH_TTL:-600}          # 10 minutes
SEARCH_WARNINGS_VISIBLE=${SEARCH_WARNINGS_VISIBLE:-false}

# Extract file path from tool invocation
FILE_PATH=""
if [[ "$TOOL_NAME" == "Read" ]]; then
    # Read(file_path="/path/to/file")
    if [[ "$TOOL_PARAMS" =~ file_path=\"([^\"]+)\" ]]; then
        FILE_PATH="${BASH_REMATCH[1]}"
    fi
elif [[ "$TOOL_NAME" == "Grep" ]]; then
    # Grep(pattern="...", path="/path/to/dir")
    if [[ "$TOOL_PARAMS" =~ path=\"([^\"]+)\" ]]; then
        FILE_PATH="${BASH_REMATCH[1]}"
    fi
elif [[ "$TOOL_NAME" == "Glob" ]]; then
    # Glob(pattern="*.py", path="/path/to/dir")
    if [[ "$TOOL_PARAMS" =~ path=\"([^\"]+)\" ]]; then
        FILE_PATH="${BASH_REMATCH[1]}"
    fi
fi

[[ -z "$FILE_PATH" ]] && exit 0  # Can't determine path, skip

# Exemption 1: Config files (never require search)
CONFIG_PATTERNS=(
    ".gitignore" "pyproject.toml" "requirements.txt" "setup.py" "setup.cfg"
    "Makefile" "Dockerfile" ".env" "*.json" "*.yaml" "*.yml" "*.toml"
    "CLAUDE.md" "README.md" "LICENSE" ".flake8" ".pylintrc"
)

for pattern in "${CONFIG_PATTERNS[@]}"; do
    if [[ "$FILE_PATH" == $pattern ]] || [[ "$(basename "$FILE_PATH")" == $pattern ]]; then
        exit 0  # Exempted
    fi
done

# Exemption 2: Small files (user knows they want whole file)
if [[ -f "$FILE_PATH" ]] && [[ "$TOOL_NAME" == "Read" ]]; then
    LINE_COUNT=$(wc -l < "$FILE_PATH" 2>/dev/null || echo 999)
    if [[ $LINE_COUNT -lt 100 ]]; then
        exit 0  # Small file, exempted
    fi
fi

# Exemption 3: Recent search exists (within TTL)
if [[ -n "$LAST_SEARCH_TIME" ]]; then
    NOW=$(date +%s)
    AGE=$((NOW - LAST_SEARCH_TIME))
    if [[ $AGE -lt $SEARCH_STATE_TTL ]]; then
        exit 0  # Recent search, compliant
    fi
fi

# Exemption 4: File already read recently (avoid duplicate violations)
if [[ -n "$RECENT_READS" ]]; then
    NOW=$(date +%s)
    while IFS=: read -r timestamp path; do
        AGE=$((NOW - timestamp))
        if [[ $AGE -lt 600 ]] && [[ "$FILE_PATH" == "$path" ]]; then
            exit 0  # Already read recently, skip
        fi
    done <<< "$RECENT_READS"
fi

# VIOLATION DETECTED — log it
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/search_warnings.log"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
SESSION=${LAST_SEARCH_SESSION:-unknown}
MODEL=${CLAUDE_MODEL:-unknown}
SKILL=${CLAUDE_SKILL:-unknown}
AGENT_ID=${CLAUDE_AGENT_ID:-main}
AGENT_DEPTH=${CLAUDE_AGENT_DEPTH:-0}

echo "$TIMESTAMP | VIOLATION | tool=$TOOL_NAME | path=$FILE_PATH | session=$SESSION | model=$MODEL | skill=$SKILL | agent_depth=$AGENT_DEPTH" >> "$LOG_FILE"

# Track this read to avoid duplicate violations
export RECENT_READS="${RECENT_READS}${RECENT_READS:+$'\n'}$(date +%s):$FILE_PATH"

# Show warning to user (not Claude) if visible
if [[ "$SEARCH_WARNINGS_VISIBLE" == "true" ]]; then
    echo "⚠️  Precision Protocol: Consider running search_code.py before $TOOL_NAME" >&2
fi

# Phase 1 (observation): don't block
# Phase 3 (enforcement): uncomment to block
# if [[ "$SEARCH_WARNINGS_BLOCKING" == "true" ]]; then
#     echo "Error: Precision Protocol requires search_code.py before $TOOL_NAME $FILE_PATH" >&2
#     exit 1
# fi

exit 0
