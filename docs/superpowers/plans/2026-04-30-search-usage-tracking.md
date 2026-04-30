# Search Usage Tracking Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track semantic search usage and violations to enable data-driven adoption decisions.

**Architecture:** Three-layer system with instrumented search logging, hook-based session state tracking, and compliance monitoring. Start in observation mode (warnings hidden from Claude), escalate to visible warnings when false positive rate is low.

**Tech Stack:** Python 3.11+, Bash hooks, JSONL logging, pandas for analytics

---

## File Structure

**Created:**
- `logs/` — Log output directory
- `logs/.gitkeep` — Keep logs/ in git
- `hooks/post_search_code.sh` — Sets LAST_SEARCH_* env vars after search
- `hooks/pre_read_grep_glob.sh` — Checks for violations before Read/Grep/Glob
- `tools/analyze_search_usage.py` — CLI analytics tool

**Modified:**
- `search_code.py` — Add _log_search_event() function
- `test_install.sh` — Install hooks, create logs/ dir, set config
- `.gitignore` — Exclude log files
- `classify_file.py` — (Optional) Add logs/ to generated patterns

**Design decisions:**
- Each hook is a standalone bash script (can be tested independently)
- Logging is append-only JSONL (no file locking needed)
- Analytics tool reads entire log into memory (acceptable for <100K events)
- Path-from-output tracking deferred to future enhancement (too complex for v1)

---

## Chunk 1: Core Logging Infrastructure

### Task 1: Add logging to search_code.py

**Files:**
- Modify: `search_code.py` (add _log_search_event function, call from __main__)

- [ ] **Step 1: Read current search_code.py structure**

```bash
source .venv/bin/activate
python3 search_code.py --help
```

Verify: Understand current CLI args and execution flow

- [ ] **Step 2: Add logging imports and helper**

Add after existing imports (line ~8):

```python
import os
import time
from datetime import datetime, timezone
```

Add after _load_source_langs() function (line ~115):

```python
def _log_search_event(query, n_results, result_count, latency_ms, 
                      search_mode, use_bm25):
    """Log search event to logs/search_usage.jsonl (JSONL format)."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "search_usage.jsonl"
    
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "search",
        "query": query,
        "n_results": n_results,
        "result_count": result_count,
        "latency_ms": latency_ms,
        "search_mode": search_mode,
        "use_bm25": use_bm25,
        "session_id": os.getenv("LAST_SEARCH_SESSION", "unknown"),
        "model": os.getenv("CLAUDE_MODEL", "unknown"),
        "skill_name": os.getenv("CLAUDE_SKILL", "unknown"),
        "agent_id": os.getenv("CLAUDE_AGENT_ID", "main"),
        "agent_depth": int(os.getenv("CLAUDE_AGENT_DEPTH", "0")),
    }
    
    try:
        with log_file.open("a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass  # Silent failure — don't break search if logging fails
```

- [ ] **Step 3: Instrument search() function**

Replace search() function (line ~147) to capture timing:

```python
def search(query, n_results=5, all_files=False, use_bm25=False):
    """Return merged search results as a list of (path, start, end, text, file_type) tuples.

    Returns an empty list when the index has no documents.
    Exits with code 1 if no index exists.
    """
    start_time = time.time()
    
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception as e:
        print(
            f"Error: no index found. Run 'python3 index_project.py' first. ({e})",
            file=sys.stderr,
        )
        sys.exit(1)

    count = collection.count()
    if count == 0:
        return []

    emb_fn = _load_embedding_fn()
    query_embedding = emb_fn([query])[0]

    where = None
    use_file_type = False
    source_langs: set = set()
    if not all_files:
        if _has_file_type_metadata(collection):
            where = {"file_type": {"$in": ["prod", "test"]}}
            use_file_type = True
        else:
            source_langs = _load_source_langs()
            where = {"lang": {"$in": list(source_langs)}} if source_langs else None

    n_candidates = min(n_results * 4, count)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_candidates,
        **({"where": where} if where else {}),
        include=["metadatas", "documents"],
    )

    semantic_ids = results["ids"][0]

    meta_cache = {}
    for i, cid in enumerate(semantic_ids):
        m = results["metadatas"][0][i]
        meta_cache[cid] = (m["path"], m["start_line"], m["end_line"],
                           results["documents"][0][i], m.get("file_type", ""))

    bm25, id_list = _load_bm25() if use_bm25 else (None, [])
    if bm25 is not None and id_list:
        tokenized_query = _tokenize_for_bm25(query)
        bm25_scores = bm25.get_scores(tokenized_query)
        top_indices = sorted(range(len(bm25_scores)),
                             key=lambda i: bm25_scores[i], reverse=True)[:n_candidates]
        bm25_ids = [id_list[i] for i in top_indices]
        merged_ids = _rrf_merge(semantic_ids, bm25_ids)
    else:
        merged_ids = semantic_ids

    missing = [cid for cid in merged_ids if cid not in meta_cache]
    if missing:
        extra = collection.get(ids=missing, include=["metadatas", "documents"])
        for i, cid in enumerate(extra["ids"]):
            m = extra["metadatas"][i]
            ft = m.get("file_type", "")
            if use_file_type and ft not in ("prod", "test"):
                continue
            if source_langs and m.get("lang") not in source_langs:
                continue
            meta_cache[cid] = (m["path"], m["start_line"], m["end_line"],
                               extra["documents"][i], ft)

    items = []
    seen_ids = set()
    for cid in merged_ids:
        if cid in meta_cache and cid not in seen_ids:
            seen_ids.add(cid)
            items.append(meta_cache[cid])
        if len(items) >= n_results:
            break

    latency_ms = int((time.time() - start_time) * 1000)
    _log_search_event(query, n_results, len(items), latency_ms, 
                      "direct", use_bm25)
    
    return merge_chunks(items)
```

- [ ] **Step 4: Instrument server search path**

Modify __main__ block (line ~270) to log server searches:

Replace:
```python
    server_results = _try_server_search(q, n_results=args.top,
                                        all_files=args.all_files, use_bm25=args.bm25)
    if server_results is not None:
        format_results(server_results)
```

With:
```python
    start_time = time.time()
    server_results = _try_server_search(q, n_results=args.top,
                                        all_files=args.all_files, use_bm25=args.bm25)
    if server_results is not None:
        latency_ms = int((time.time() - start_time) * 1000)
        _log_search_event(q, args.top, len(server_results), latency_ms,
                          "server", args.bm25)
        format_results(server_results)
```

- [ ] **Step 5: Test logging manually**

```bash
source .venv/bin/activate
rm -f logs/search_usage.jsonl  # clean slate
python3 search_code.py "authentication test" --top 3
cat logs/search_usage.jsonl | python3 -m json.tool
```

Expected: Valid JSON with all fields populated (session_id/model/skill will be "unknown" without hooks)

- [ ] **Step 6: Test server mode logging**

```bash
# Start server in background
python3 search_server.py &
SERVER_PID=$!
sleep 2

# Run search via server
python3 search_code.py "authentication test" --top 3

# Check logs
cat logs/search_usage.jsonl | tail -1 | python3 -m json.tool

# Cleanup
kill $SERVER_PID
```

Expected: `"search_mode": "server"` in latest log entry

- [ ] **Step 7: Commit logging changes**

```bash
git add search_code.py logs/.gitkeep
git commit -m "feat: add JSONL logging to search_code.py

Track search events with timestamp, query, results, latency, mode.
Logs to logs/search_usage.jsonl for analytics.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 2: Create post-search hook

**Files:**
- Create: `hooks/post_search_code.sh`

- [ ] **Step 1: Write post-search hook script**

```bash
cat > hooks/post_search_code.sh << 'EOF'
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
EOF

chmod +x hooks/post_search_code.sh
```

- [ ] **Step 2: Test post-search hook in isolation**

```bash
# Simulate hook environment
export TOOL_COMMAND='python3 search_code.py "authentication bug" --top 5'
export TOOL_OUTPUT='MATCH 1: src/auth.py [prod] (lines 45-67)'

source hooks/post_search_code.sh

# Verify env vars set
echo "LAST_SEARCH_TIME: $LAST_SEARCH_TIME"
echo "LAST_SEARCH_QUERY: $LAST_SEARCH_QUERY"
echo "LAST_SEARCH_SESSION: $LAST_SEARCH_SESSION"

[[ -n "$LAST_SEARCH_TIME" ]] || echo "ERROR: LAST_SEARCH_TIME not set"
[[ "$LAST_SEARCH_QUERY" == "authentication bug" ]] || echo "ERROR: Query mismatch"
[[ -n "$LAST_SEARCH_SESSION" ]] || echo "ERROR: Session ID not set"
```

Expected: All vars set correctly

- [ ] **Step 3: Test with edge cases**

```bash
# Test: query with spaces and special chars
export TOOL_COMMAND='python3 search_code.py "login & session handling" --bm25'
source hooks/post_search_code.sh
[[ "$LAST_SEARCH_QUERY" == "login & session handling" ]] || echo "ERROR: Special chars"

# Test: single-word query (no quotes)
export TOOL_COMMAND='python3 search_code.py authentication --top 3'
source hooks/post_search_code.sh
[[ "$LAST_SEARCH_QUERY" == "authentication" ]] || echo "ERROR: Unquoted query"

# Test: session ID persistence
FIRST_SESSION=$LAST_SEARCH_SESSION
export TOOL_COMMAND='python3 search_code.py "second query"'
source hooks/post_search_code.sh
[[ "$LAST_SEARCH_SESSION" == "$FIRST_SESSION" ]] || echo "ERROR: Session ID changed"
```

Expected: All assertions pass

- [ ] **Step 4: Commit post-search hook**

```bash
git add hooks/post_search_code.sh
git commit -m "feat: add post-search hook for state tracking

Sets LAST_SEARCH_TIME, LAST_SEARCH_QUERY, LAST_SEARCH_SESSION env vars.
State propagates to subsequent tools for violation detection.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 3: Create pre-Read/Grep/Glob hook

**Files:**
- Create: `hooks/pre_read_grep_glob.sh`

- [ ] **Step 1: Write pre-hook with exemption logic**

```bash
cat > hooks/pre_read_grep_glob.sh << 'EOF'
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
EOF

chmod +x hooks/pre_read_grep_glob.sh
```

- [ ] **Step 2: Test exemption logic**

```bash
mkdir -p logs

# Test: Config file exemption
export TOOL_NAME="Read"
export TOOL_PARAMS='file_path=".gitignore"'
bash hooks/pre_read_grep_glob.sh
[[ ! -f logs/search_warnings.log ]] || echo "ERROR: Config file not exempted"

# Test: Small file exemption
echo -e "line1\nline2\nline3" > /tmp/small.txt
export TOOL_PARAMS='file_path="/tmp/small.txt"'
bash hooks/pre_read_grep_glob.sh
grep -q "/tmp/small.txt" logs/search_warnings.log && echo "ERROR: Small file not exempted" || true

# Test: Recent search exemption
export LAST_SEARCH_TIME=$(date +%s)
export TOOL_PARAMS='file_path="src/auth.py"'
bash hooks/pre_read_grep_glob.sh
grep -q "src/auth.py" logs/search_warnings.log && echo "ERROR: Recent search not exempted" || true

# Test: Violation logged when no exemptions apply
unset LAST_SEARCH_TIME
export TOOL_PARAMS='file_path="src/some_file.py"'
bash hooks/pre_read_grep_glob.sh
grep -q "src/some_file.py" logs/search_warnings.log || echo "ERROR: Violation not logged"
```

Expected: Only last test logs violation

- [ ] **Step 3: Test duplicate read suppression**

```bash
rm -f logs/search_warnings.log

# First read: logs violation
export TOOL_PARAMS='file_path="src/new_file.py"'
unset RECENT_READS
unset LAST_SEARCH_TIME
bash hooks/pre_read_grep_glob.sh
FIRST_COUNT=$(wc -l < logs/search_warnings.log)

# Second read: should not log again (RECENT_READS set)
bash hooks/pre_read_grep_glob.sh
SECOND_COUNT=$(wc -l < logs/search_warnings.log)

[[ $FIRST_COUNT -eq $SECOND_COUNT ]] || echo "ERROR: Duplicate violation logged"
```

Expected: Same line count (no duplicate)

- [ ] **Step 4: Commit pre-hook**

```bash
git add hooks/pre_read_grep_glob.sh
git commit -m "feat: add pre-tool hook for violation detection

Checks Precision Protocol compliance before Read/Grep/Glob.
Logs violations to logs/search_warnings.log with generous exemptions.
Phase 1 (observation): warnings hidden from Claude, non-blocking.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Chunk 2: Analytics and Installation

### Task 4: Create analytics CLI tool

**Files:**
- Create: `tools/analyze_search_usage.py`

- [ ] **Step 1: Write analytics script**

```python
cat > tools/analyze_search_usage.py << 'EOF'
#!/usr/bin/env python3
"""
Analyze search usage from logs/search_usage.jsonl and logs/search_warnings.log

Usage:
    python3 tools/analyze_search_usage.py                # Full report
    python3 tools/analyze_search_usage.py --period 7     # Last 7 days
    python3 tools/analyze_search_usage.py --skill debugging  # Filter by skill
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
import argparse


def load_search_events(log_file, days=None):
    """Load search events from JSONL, optionally filtered by recency."""
    if not log_file.exists():
        return []
    
    events = []
    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    for line in log_file.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if cutoff:
                ts = datetime.fromisoformat(event["timestamp"])
                if ts < cutoff:
                    continue
            events.append(event)
        except (json.JSONDecodeError, KeyError):
            continue
    
    return events


def load_violations(log_file, days=None):
    """Load violations from pipe-delimited log."""
    if not log_file.exists():
        return []
    
    violations = []
    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    for line in log_file.read_text().splitlines():
        if not line.strip() or "VIOLATION" not in line:
            continue
        
        parts = line.split(" | ")
        if len(parts) < 4:
            continue
        
        ts_str = parts[0]
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if cutoff and ts < cutoff:
                continue
        except ValueError:
            continue
        
        violation = {"timestamp": ts_str}
        for part in parts[2:]:
            if "=" in part:
                key, val = part.split("=", 1)
                violation[key.strip()] = val.strip()
        
        violations.append(violation)
    
    return violations


def calculate_compliance_rate(searches, violations):
    """Compliance = searches / (searches + violations)."""
    total = len(searches) + len(violations)
    if total == 0:
        return 0.0
    return (len(searches) / total) * 100


def weekly_trends(events, violations):
    """Group by week and calculate compliance."""
    weeks = defaultdict(lambda: {"searches": 0, "violations": 0})
    
    for event in events:
        ts = datetime.fromisoformat(event["timestamp"])
        week = ts.strftime("%Y-W%U")
        weeks[week]["searches"] += 1
    
    for v in violations:
        ts = datetime.fromisoformat(v["timestamp"].replace("Z", "+00:00"))
        week = ts.strftime("%Y-W%U")
        weeks[week]["violations"] += 1
    
    trends = []
    for week in sorted(weeks.keys()):
        data = weeks[week]
        total = data["searches"] + data["violations"]
        compliance = (data["searches"] / total * 100) if total > 0 else 0.0
        trends.append((week, compliance, data["searches"], data["violations"]))
    
    return trends


def breakdown_by_field(events, violations, field):
    """Group by field (skill_name, model, etc) and calculate compliance."""
    stats = defaultdict(lambda: {"searches": 0, "violations": 0})
    
    for event in events:
        key = event.get(field, "unknown")
        stats[key]["searches"] += 1
    
    for v in violations:
        key = v.get(field, "unknown")
        stats[key]["violations"] += 1
    
    results = []
    for key in sorted(stats.keys()):
        data = stats[key]
        total = data["searches"] + data["violations"]
        compliance = (data["searches"] / total * 100) if total > 0 else 0.0
        results.append((key, compliance, data["searches"], data["violations"]))
    
    return results


def search_mode_distribution(events):
    """Count server vs direct searches."""
    modes = Counter(e["search_mode"] for e in events if "search_mode" in e)
    return modes


def bm25_usage_rate(events):
    """Percent of searches using BM25."""
    total = len(events)
    if total == 0:
        return 0.0
    bm25_count = sum(1 for e in events if e.get("use_bm25", False))
    return (bm25_count / total) * 100


def avg_latency_by_mode(events):
    """Average latency for server vs direct."""
    by_mode = defaultdict(list)
    for e in events:
        if "latency_ms" in e and "search_mode" in e:
            by_mode[e["search_mode"]].append(e["latency_ms"])
    
    return {mode: sum(vals) / len(vals) if vals else 0.0 
            for mode, vals in by_mode.items()}


def print_report(searches, violations, args):
    """Print formatted analytics report."""
    print("Search Usage Report")
    print("=" * 60)
    
    period_desc = f"Last {args.period} days" if args.period else "All time"
    print(f"Period: {period_desc}")
    if args.skill:
        print(f"Filtered by skill: {args.skill}")
    if args.model:
        print(f"Filtered by model: {args.model}")
    print()
    
    # Overall compliance
    compliance = calculate_compliance_rate(searches, violations)
    total_accesses = len(searches) + len(violations)
    print(f"Compliance Rate: {compliance:.1f}% ({len(searches)} searches / {total_accesses} file accesses)")
    print()
    
    # Trends
    if not args.skill and not args.model:  # Only show trends for full dataset
        trends = weekly_trends(searches, violations)
        if trends:
            print("Weekly Trends:")
            for week, comp, s, v in trends[-4:]:  # Last 4 weeks
                print(f"  {week}: {comp:.1f}% ({s} searches / {s + v} accesses)")
            print()
    
    # By skill
    if not args.skill:
        skill_stats = breakdown_by_field(searches, violations, "skill_name")
        if skill_stats:
            print("By Skill:")
            for skill, comp, s, v in skill_stats[:5]:  # Top 5
                if skill == "unknown":
                    continue
                print(f"  {skill}: {comp:.1f}% ({s}/{s + v})")
            print()
    
    # By model
    if not args.model:
        model_stats = breakdown_by_field(searches, violations, "model")
        if model_stats:
            print("By Model:")
            for model, comp, s, v in model_stats:
                if model == "unknown":
                    continue
                print(f"  {model}: {comp:.1f}% ({s}/{s + v})")
            print()
    
    # Search mode
    modes = search_mode_distribution(searches)
    if modes:
        total_searches = sum(modes.values())
        print("Search Mode:")
        for mode, count in modes.most_common():
            pct = (count / total_searches * 100) if total_searches else 0
            print(f"  {mode}: {pct:.1f}% ({count})")
        print()
    
    # BM25
    bm25_pct = bm25_usage_rate(searches)
    print(f"BM25 Usage: {bm25_pct:.1f}% of searches")
    print()
    
    # Latency
    latencies = avg_latency_by_mode(searches)
    if latencies:
        print("Avg Latency:")
        for mode, avg in sorted(latencies.items()):
            print(f"  {mode}: {avg:.0f}ms")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze search usage and compliance"
    )
    parser.add_argument(
        "--period", type=int, metavar="DAYS",
        help="Analyze last N days only"
    )
    parser.add_argument(
        "--skill", type=str,
        help="Filter by skill name"
    )
    parser.add_argument(
        "--model", type=str,
        help="Filter by model"
    )
    args = parser.parse_args()
    
    log_dir = Path("logs")
    searches = load_search_events(log_dir / "search_usage.jsonl", args.period)
    violations = load_violations(log_dir / "search_warnings.log", args.period)
    
    # Apply filters
    if args.skill:
        searches = [s for s in searches if s.get("skill_name") == args.skill]
        violations = [v for v in violations if v.get("skill") == args.skill]
    
    if args.model:
        searches = [s for s in searches if s.get("model") == args.model]
        violations = [v for v in violations if v.get("model") == args.model]
    
    if not searches and not violations:
        print("No data found matching filters.")
        sys.exit(0)
    
    print_report(searches, violations, args)


if __name__ == "__main__":
    main()
EOF

chmod +x tools/analyze_search_usage.py
```

- [ ] **Step 2: Test analytics with sample data**

```bash
source .venv/bin/activate

# Create sample search events
cat > logs/search_usage.jsonl << 'SAMPLE'
{"timestamp": "2026-04-25T10:00:00Z", "event_type": "search", "query": "test1", "n_results": 5, "result_count": 3, "latency_ms": 150, "search_mode": "server", "use_bm25": true, "session_id": "s1", "model": "claude-sonnet-4-5", "skill_name": "debugging", "agent_id": "main", "agent_depth": 0}
{"timestamp": "2026-04-26T11:00:00Z", "event_type": "search", "query": "test2", "n_results": 5, "result_count": 2, "latency_ms": 1800, "search_mode": "direct", "use_bm25": false, "session_id": "s2", "model": "claude-opus-4", "skill_name": "frontend-design", "agent_id": "main", "agent_depth": 0}
SAMPLE

# Create sample violations
cat > logs/search_warnings.log << 'SAMPLE'
2026-04-25T10:30:00Z | VIOLATION | tool=Read | path=src/auth.py | session=s1 | model=claude-sonnet-4-5 | skill=debugging | agent_depth=0
2026-04-26T12:00:00Z | VIOLATION | tool=Grep | path=src/utils.py | session=s3 | model=claude-opus-4 | skill=frontend-design | agent_depth=1
SAMPLE

python3 tools/analyze_search_usage.py
```

Expected: Report shows 50% compliance (2 searches, 2 violations), breakdown by skill/model

- [ ] **Step 3: Test filtering options**

```bash
# Filter by skill
python3 tools/analyze_search_usage.py --skill debugging

# Filter by model
python3 tools/analyze_search_usage.py --model claude-sonnet-4-5

# Filter by period
python3 tools/analyze_search_usage.py --period 1
```

Expected: Filtered results match expectations

- [ ] **Step 4: Clean up test data**

```bash
# Remove test data before committing
rm -f logs/search_usage.jsonl logs/search_warnings.log
```

Expected: Test logs cleaned

- [ ] **Step 5: Commit analytics tool**

```bash
git add tools/analyze_search_usage.py
git commit -m "feat: add search usage analytics CLI

Analyzes logs/search_usage.jsonl and logs/search_warnings.log.
Reports compliance rate, trends, by-skill, by-model, mode, BM25, latency.
Supports filtering by period, skill, model.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 5: Update installation script

**Files:**
- Modify: `test_install.sh` (add hook installation, create logs/ dir, set config)

- [ ] **Step 1: Read current test_install.sh**

```bash
cat test_install.sh | head -50
```

Verify: Understand current install flow

- [ ] **Step 2: Add logs directory creation**

Add after virtual environment setup (before index creation):

```bash
# Create logs directory for search usage tracking
mkdir -p logs
touch logs/.gitkeep
echo "Created logs/ directory"
```

- [ ] **Step 3: Add hook installation**

Add after all installations complete (before final success message):

```bash
# Install search usage tracking hooks
echo "Installing search usage tracking hooks..."

SETTINGS_FILE="$HOME/.claude/settings.json"
HOOKS_DIR="$(pwd)/hooks"

# Backup existing settings
if [[ -f "$SETTINGS_FILE" ]]; then
    cp "$SETTINGS_FILE" "$SETTINGS_FILE.backup-$(date +%s)"
fi

# Create settings file if it doesn't exist
mkdir -p "$(dirname "$SETTINGS_FILE")"
if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo '{}' > "$SETTINGS_FILE"
fi

# Update settings.json with hooks (use Python for JSON manipulation)
python3 << 'PYTHON_EOF'
import json
import sys
from pathlib import Path

settings_file = Path.home() / ".claude" / "settings.json"
settings = json.loads(settings_file.read_text())

# Add hooks
if "hooks" not in settings:
    settings["hooks"] = {}

# Post-tool hook for search_code.py
post_tool = settings["hooks"].get("post_tool", [])
search_hook = f"if [[ \"$TOOL_COMMAND\" == *search_code.py* ]]; then source {sys.argv[1]}/post_search_code.sh; fi"
if search_hook not in post_tool:
    post_tool.append(search_hook)
settings["hooks"]["post_tool"] = post_tool

# Pre-tool hook for Read/Grep/Glob
pre_tool = settings["hooks"].get("pre_tool", [])
rgg_hook = f"if [[ \"$TOOL_NAME\" == Read ]] || [[ \"$TOOL_NAME\" == Grep ]] || [[ \"$TOOL_NAME\" == Glob ]]; then source {sys.argv[1]}/pre_read_grep_glob.sh; fi"
if rgg_hook not in pre_tool:
    pre_tool.append(rgg_hook)
settings["hooks"]["pre_tool"] = pre_tool

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
PYTHON_EOF python3 "$HOOKS_DIR"

echo "Hooks installed. Run 'python3 tools/analyze_search_usage.py' to view analytics."
```

- [ ] **Step 4: Test install script**

```bash
# Backup current settings
cp ~/.claude/settings.json ~/.claude/settings.json.test-backup

# Run install script
bash test_install.sh

# Verify hooks installed
cat ~/.claude/settings.json | grep -A5 '"hooks"'

# Restore backup
mv ~/.claude/settings.json.test-backup ~/.claude/settings.json
```

Expected: Hooks present in settings.json, logs/ dir created

- [ ] **Step 5: Commit install script changes**

```bash
git add test_install.sh logs/.gitkeep
git commit -m "feat: install search usage tracking hooks

Update test_install.sh to:
- Create logs/ directory
- Install post-search and pre-tool hooks
- Set default config in ~/.claude/settings.json
- Preserve existing hooks and settings

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 6: Update ignore files

**Files:**
- Modify: `.gitignore`
- Optional: Modify: `classify_file.py`

- [ ] **Step 1: Add log files to .gitignore**

```bash
cat >> .gitignore << 'EOF'

# Search usage tracking logs
logs/search_usage.jsonl
logs/search_warnings.log
EOF
```

- [ ] **Step 2: Verify .gitignore**

```bash
git status
# Should NOT show logs/*.jsonl or logs/*.log as untracked
```

Expected: Log files ignored

- [ ] **Step 3: (Optional) Update classify_file.py**

If logs/ should be excluded from semantic index:

```python
# Add to classify_file.py GENERATED_PATTERNS list (around line 20)
    "logs/**",  # Search usage tracking logs
```

- [ ] **Step 4: Commit ignore changes**

```bash
git add .gitignore
git commit -m "chore: ignore search usage tracking logs

Add logs/search_usage.jsonl and logs/search_warnings.log to .gitignore.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Chunk 3: Testing and Documentation

### Task 7: End-to-end integration test

**Files:**
- Create: `tests/test_search_usage_tracking.sh`

- [ ] **Step 1: Write integration test script**

```bash
cat > tests/test_search_usage_tracking.sh << 'EOF'
#!/usr/bin/env bash
# Integration test for search usage tracking system

set -e

TEST_DIR=$(mktemp -d)
ORIGINAL_DIR=$(pwd)

echo "=== Integration Test: Search Usage Tracking ==="

# Setup: copy project files
cp -r "$ORIGINAL_DIR"/* "$TEST_DIR"/
cd "$TEST_DIR"

# Ensure clean state
rm -rf logs
mkdir -p logs

source .venv/bin/activate

# Test 1: Search logging
echo "Test 1: Search creates log entry..."
python3 search_code.py "authentication" --top 3 > /dev/null 2>&1 || true
[[ -f logs/search_usage.jsonl ]] || { echo "FAIL: No log file created"; exit 1; }
grep -q '"event_type": "search"' logs/search_usage.jsonl || { echo "FAIL: No search event logged"; exit 1; }
echo "PASS"

# Test 2: Post-hook sets env vars
echo "Test 2: Post-hook sets environment..."
export TOOL_COMMAND='python3 search_code.py "test query" --top 5'
export TOOL_OUTPUT='MATCH 1: src/test.py'
source hooks/post_search_code.sh
[[ -n "$LAST_SEARCH_TIME" ]] || { echo "FAIL: LAST_SEARCH_TIME not set"; exit 1; }
[[ "$LAST_SEARCH_QUERY" == "test query" ]] || { echo "FAIL: Query mismatch"; exit 1; }
echo "PASS"

# Test 3: Pre-hook exempts recent search
echo "Test 3: Pre-hook exempts after recent search..."
export LAST_SEARCH_TIME=$(date +%s)
export TOOL_NAME="Read"
export TOOL_PARAMS='file_path="src/auth.py"'
bash hooks/pre_read_grep_glob.sh
grep -q "src/auth.py" logs/search_warnings.log && { echo "FAIL: Recent search not exempted"; exit 1; } || true
echo "PASS"

# Test 4: Pre-hook logs violation when no search
echo "Test 4: Pre-hook logs violation without search..."
unset LAST_SEARCH_TIME
export TOOL_PARAMS='file_path="src/violation.py"'
bash hooks/pre_read_grep_glob.sh
grep -q "src/violation.py" logs/search_warnings.log || { echo "FAIL: Violation not logged"; exit 1; }
echo "PASS"

# Test 5: Analytics tool runs
echo "Test 5: Analytics tool produces report..."
python3 tools/analyze_search_usage.py > /tmp/analytics_output.txt
grep -q "Compliance Rate" /tmp/analytics_output.txt || { echo "FAIL: Analytics incomplete"; exit 1; }
echo "PASS"

echo ""
echo "=== All Tests Passed ==="
echo "Cleaning up $TEST_DIR"
rm -rf "$TEST_DIR"
EOF

chmod +x tests/test_search_usage_tracking.sh
```

- [ ] **Step 2: Run integration test**

```bash
bash tests/test_search_usage_tracking.sh
```

Expected: All tests pass

- [ ] **Step 3: Fix any failures**

If tests fail, debug and fix the underlying issue before committing.

- [ ] **Step 4: Commit integration test**

```bash
git add tests/test_search_usage_tracking.sh
git commit -m "test: add end-to-end integration test

Verifies search logging, hooks, violation detection, analytics.
Tests complete workflow from search to reporting.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 8: Update documentation

**Files:**
- Modify: `README.md` (add usage tracking section)

- [ ] **Step 1: Add usage tracking section to README**

Add after the "Persistent Search Server" section (after line ~79, before "## What Gets Installed"):

```markdown
## Search Usage Tracking

**Goal:** Understand when and why semantic search is used (or should have been used) in superpowers workflows.

### How It Works

1. **Logging:** `search_code.py` logs every invocation to `logs/search_usage.jsonl`
2. **State Tracking:** Post-search hook sets `LAST_SEARCH_TIME` env var
3. **Compliance Monitoring:** Pre-tool hook detects violations of Precision Protocol
4. **Analytics:** `tools/analyze_search_usage.py` reports compliance rates, trends, breakdowns

### Viewing Analytics

```bash
# Full report
python3 tools/analyze_search_usage.py

# Last 7 days only
python3 tools/analyze_search_usage.py --period 7

# Filter by skill
python3 tools/analyze_search_usage.py --skill debugging

# Filter by model
python3 tools/analyze_search_usage.py --model claude-sonnet-4-5
```

### Configuration

Set in `~/.claude/settings.json`:

```json
{
  "searchUsageTracking": {
    "warningsVisible": false,      // Show warnings to Claude (Phase 2)
    "warningsBlocking": false,     // Block non-compliant tools (Phase 3)
    "searchStateTTL": 300,         // Search state expires after 5 min
    "recentPathTTL": 600           // Path tracking expires after 10 min
  }
}
```

**Phase 1 (current):** Observation mode — violations logged, hidden from Claude  
**Phase 2 (manual):** Set `warningsVisible: true` to show warnings  
**Phase 3 (future):** Set `warningsBlocking: true` to enforce compliance

### Log Files

- `logs/search_usage.jsonl` — Search events (JSONL format)
- `logs/search_warnings.log` — Precision Protocol violations (pipe-delimited)

Both files are gitignored and safe for ad-hoc analysis with pandas/jq.
```

- [ ] **Step 2: Verify README renders correctly**

```bash
# Preview README (use CLI markdown viewer or check on GitHub)
glow README.md  # if glow installed, otherwise skip
```

Expected: Section renders clearly

- [ ] **Step 3: Commit README update**

```bash
git add README.md
git commit -m "docs: add search usage tracking section to README

Explains logging, analytics, configuration, phased approach.
Documents CLI usage for analyze_search_usage.py tool.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 9: Final verification

**Files:**
- All modified/created files

- [ ] **Step 1: Run full test suite**

```bash
source .venv/bin/activate
pytest tests/ -v
```

Expected: All tests pass (including new integration test)

- [ ] **Step 2: Verify hooks installed**

```bash
cat ~/.claude/settings.json | python3 -m json.tool | grep -A10 '"hooks"'
```

Expected: post_search_code.sh and pre_read_grep_glob.sh hooks present

- [ ] **Step 3: Test real workflow**

```bash
# Clean logs
rm -f logs/search_usage.jsonl logs/search_warnings.log

# Simulate compliant workflow
export TOOL_COMMAND='python3 search_code.py "authentication bug" --top 5'
export TOOL_OUTPUT='MATCH 1: src/auth.py'
source hooks/post_search_code.sh

# This should NOT log violation (recent search)
export TOOL_NAME="Read"
export TOOL_PARAMS='file_path="src/auth.py"'
source hooks/pre_read_grep_glob.sh

# Check logs
wc -l logs/search_usage.jsonl  # Should be 0 (search not actually run, just hook tested)
wc -l logs/search_warnings.log  # Should be 0 (exempted)

# Simulate violation
unset LAST_SEARCH_TIME
export TOOL_PARAMS='file_path="src/other.py"'
source hooks/pre_read_grep_glob.sh

wc -l logs/search_warnings.log  # Should be 1 (violation logged)
```

Expected: Workflow behaves as designed

- [ ] **Step 4: Review all changes**

```bash
git log --oneline --graph --all -10
git diff HEAD~8 HEAD --stat
```

Expected: 8 commits covering all components

- [ ] **Step 5: Final commit (if any cleanup needed)**

```bash
# If any minor fixes needed, stage and commit
git add -A
git commit -m "chore: final cleanup for search usage tracking

Minor fixes after integration testing.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Completion Checklist

- [ ] All tasks completed
- [ ] Integration test passes
- [ ] Hooks installed in ~/.claude/settings.json
- [ ] Logs directory created with .gitkeep
- [ ] README updated with usage instructions
- [ ] All commits follow conventional commit format
- [ ] No failing tests

**Next steps:**
1. User runs `bash test_install.sh` to install hooks
2. Use Claude Code with superpowers skills
3. Run `python3 tools/analyze_search_usage.py` weekly to track compliance
4. When false positive rate < 5%, escalate to Phase 2 (`warningsVisible: true`)
5. When compliance rate > 90%, consider Phase 3 (`warningsBlocking: true`)
