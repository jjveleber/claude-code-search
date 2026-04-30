#!/usr/bin/env bash
# Post-search hook: propagate search state to subsequent tools
# Triggered after search_code.py runs successfully

if [[ -z "$TOOL_OUTPUT" ]]; then
    exit 0
fi

# Extract query from tool invocation (assumes: python3 search_code.py "query" ...)
# Parse from TOOL_COMMAND env var if available, otherwise skip
if [[ -n "$TOOL_COMMAND" ]]; then
    # Extract quoted string after search_code.py
    if [[ "$TOOL_COMMAND" =~ search_code\.py[[:space:]]+\"([^\"]+)\" ]]; then
        export LAST_SEARCH_QUERY="${BASH_REMATCH[1]}"
    elif [[ "$TOOL_COMMAND" =~ search_code\.py[[:space:]]+([^[:space:]]+) ]]; then
        export LAST_SEARCH_QUERY="${BASH_REMATCH[1]}"
    fi
fi

export LAST_SEARCH_TIME=$(date +%s)

# Generate or reuse session ID
if [[ -z "$LAST_SEARCH_SESSION" ]]; then
    export LAST_SEARCH_SESSION=$(uuidgen 2>/dev/null || echo "session-$$-$RANDOM")
fi

# Debug: log state (remove after testing)
# echo "[DEBUG] post_search_code: LAST_SEARCH_TIME=$LAST_SEARCH_TIME LAST_SEARCH_QUERY=$LAST_SEARCH_QUERY LAST_SEARCH_SESSION=$LAST_SEARCH_SESSION" >> /tmp/hook-debug.log
