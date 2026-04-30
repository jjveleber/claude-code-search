# Search Usage Tracking and Enforcement

**Date:** 2026-04-30  
**Status:** Approved  
**Goal:** Track when `search_code.py` is used and when it should have been used but wasn't, enabling data-driven decisions to improve adoption in superpowers workflows.

## Problem

When using superpowers skills with claude-code-search, we can't tell:
1. When and why semantic search IS used
2. When and why it's NOT used (but should have been per Precision Protocol)
3. Trends over time as the system evolves

Without this visibility, we can't make informed decisions about increasing adoption where appropriate or understand the impact of changes to claude-code-search.

## Solution Overview

**Approach:** Integrated logging + hook-based state tracking

Three-layer system:
1. **Instrumented search** — `search_code.py` logs every invocation with context
2. **Session state tracking** — Hooks propagate search state via environment variables
3. **Compliance monitoring** — Pre-tool hooks detect violations, log them separately from Claude's view

## Architecture

### Components

**Modified: `search_code.py`**
- Add `_log_search_event()` function
- Log to `logs/search_usage.jsonl` (JSONL format for pandas/jq)
- Capture: timestamp, query, n_results, result count, latency, search mode (server/direct), BM25 flag, session ID, model, skill, agent depth

**New: `hooks/post_search_code.sh`**
- Triggered after `search_code.py` runs
- Sets environment variables:
  - `LAST_SEARCH_QUERY` — query text
  - `LAST_SEARCH_TIME` — Unix timestamp
  - `LAST_SEARCH_SESSION` — session identifier
- State propagates to subsequent tool calls in same session

**New: `hooks/pre_read_grep_glob.sh`**
- Triggered before Read/Grep/Glob
- Checks for recent search (`LAST_SEARCH_TIME` within 5 minutes)
- If missing and file path not previously known:
  - Logs violation to `logs/search_warnings.log` (hidden from Claude)
  - Captures: tool name, file path, session, model, skill, agent depth
- Exemptions (no violation logged):
  - File path appeared in prior tool output (e.g., git status, ls, grep results)
  - Config files (`.gitignore`, `pyproject.toml`, etc.)
  - Small files under 100 lines (user specified whole-file read)
  - Files already read in last 10 minutes
  - Session has already run search (grace period)

**New: `tools/analyze_search_usage.py`**
- CLI analytics tool
- Reads `logs/search_usage.jsonl` and `logs/search_warnings.log`
- Reports:
  - Overall compliance rate (searches : violations)
  - Daily/weekly trends (time series)
  - Breakdown by skill (`skill_name` field)
  - Breakdown by model (`model` field)
  - Search mode distribution (server vs direct)
  - BM25 usage rate
  - Average latency by mode

**Modified: `test_install.sh`**
- Create `logs/` directory
- Install hooks via `~/.claude/settings.json` updates
- Add hook configuration:
  ```json
  "hooks": {
    "post_tool": [
      "if [[ \"$TOOL_NAME\" == *search_code.py ]]; then source hooks/post_search_code.sh; fi"
    ],
    "pre_tool": [
      "if [[ \"$TOOL_NAME\" == Read || \"$TOOL_NAME\" == Grep || \"$TOOL_NAME\" == Glob ]]; then source hooks/pre_read_grep_glob.sh; fi"
    ]
  }
  ```
- Set default config: `SEARCH_WARNINGS_VISIBLE=false`

**Modified: `.gitignore`**
- Add `logs/search_usage.jsonl`
- Add `logs/search_warnings.log`

**Optional: `classify_file.py`**
- Add `logs/` to generated file patterns (exclude from semantic index)

### Data Flow

**Scenario 1: Compliant workflow**
1. User: "Fix the authentication bug"
2. Claude: runs `search_code.py "authentication bug"`
3. Post-hook: sets `LAST_SEARCH_TIME`, `LAST_SEARCH_SESSION`
4. `search_code.py`: logs search event to JSONL
5. Claude: runs `Read src/auth.py`
6. Pre-hook: sees recent search, allows quietly

**Scenario 2: Violation**
1. User: "Fix the authentication bug"
2. Claude: runs `Read src/auth.py` (skipped search, file path not given)
3. Pre-hook: no `LAST_SEARCH_TIME`, logs violation to `logs/search_warnings.log`
4. Violation log hidden from Claude (observation mode)

**Scenario 3: Exemption (no violation)**
1. User: "Update the README"
2. Claude: runs `Read README.md`
3. Pre-hook: file is config/doc, exempted from search requirement
4. No violation logged

**Scenario 4: Path from prior output**
1. Claude: runs `git status` → sees `src/auth.py` modified
2. Claude: runs `Read src/auth.py`
3. Pre-hook: path appeared in prior output, exempted
4. No violation logged

### Log Schema

**`logs/search_usage.jsonl`** (one JSON object per line):
```json
{
  "timestamp": "2026-04-30T14:32:01Z",
  "event_type": "search",
  "query": "authentication bug",
  "n_results": 5,
  "result_count": 3,
  "latency_ms": 234,
  "search_mode": "server",
  "use_bm25": true,
  "session_id": "abc123",
  "model": "claude-sonnet-4-5",
  "skill_name": "debugging",
  "agent_id": "main",
  "agent_depth": 0
}
```

**`logs/search_warnings.log`** (structured text, hidden from Claude):
```
2026-04-30T14:35:12Z | VIOLATION | tool=Read | path=src/auth.py | session=abc123 | model=claude-sonnet-4-5 | skill=debugging | agent_depth=0
```

### Analytics Capabilities

**`tools/analyze_search_usage.py`** outputs:

```
Search Usage Report
===================
Period: 2026-04-01 to 2026-04-30

Compliance Rate: 78.3% (235 searches / 300 file accesses)

Trends:
  Week 1: 65.2%
  Week 2: 72.1%
  Week 3: 76.8%
  Week 4: 78.3%

By Skill:
  debugging: 92.1% (117/127)
  frontend-design: 68.4% (65/95)
  mcp-builder: 70.0% (53/78)

By Model:
  claude-sonnet-4-5: 80.2%
  claude-opus-4: 75.6%

Search Mode:
  server: 89.4% (warm model)
  direct: 10.6% (cold start)

BM25 Usage: 23.8% of searches

Avg Latency:
  server: 234ms
  direct: 1820ms
```

## Phased Warning Visibility

**Phase 1: Observation (default)**
- `SEARCH_WARNINGS_VISIBLE=false`
- Violations written to `logs/search_warnings.log` (hidden from Claude)
- User sees analytics, tunes exemptions
- Goal: reduce false positive rate below 5%

**Phase 2: Warning (manual escalation)**
- `SEARCH_WARNINGS_VISIBLE=true`
- Pre-hook writes warnings to stderr (visible to Claude)
- Claude sees: "Warning: Precision Protocol violation - consider running search_code.py first"
- Claude adjusts behavior, learns from warnings
- Goal: increase compliance rate above 90%

**Phase 3: Enforcement (future, optional)**
- `SEARCH_WARNINGS_BLOCKING=true`
- Pre-hook blocks Read/Grep/Glob, requires search first
- Exit code 1 with clear error message
- Only enable when compliance rate plateaus

## Configuration

**Environment Variables:**
- `SEARCH_WARNINGS_VISIBLE` (default: `false`) — show warnings to Claude
- `SEARCH_WARNINGS_BLOCKING` (default: `false`) — block non-compliant tool calls
- `SEARCH_STATE_TTL` (default: `300`) — seconds until `LAST_SEARCH_TIME` expires
- `RECENT_PATH_TTL` (default: `600`) — seconds to remember prior tool output paths

**Hook State (set by post-hook, read by pre-hook):**
- `LAST_SEARCH_QUERY` — most recent search query
- `LAST_SEARCH_TIME` — Unix timestamp of last search
- `LAST_SEARCH_SESSION` — session ID where search occurred

## Success Criteria

1. **Visibility:** Analytics show compliance rate, trends, per-skill breakdown
2. **Actionability:** Data enables clear decisions (e.g., "debugging skill has 92% compliance, frontend-design needs improvement")
3. **Balance:** False positive rate under 5% (exemptions catch legitimate non-search paths)
4. **Non-invasive:** Observation mode collects data without affecting Claude's workflow
5. **Scalability:** JSONL logs support pandas/jq for ad-hoc analysis

## Non-Goals

- Hard enforcement in Phase 1 (observation only)
- Real-time feedback to Claude (warnings start hidden)
- Backward compatibility with pre-hook repositories (requires install script update)

## Trade-offs

**Chosen:** Hook-based state tracking (Approach B)

**Rejected alternatives:**
- **Approach A:** Pure logging (no violation detection)
  - Pro: simpler, no hooks required
  - Con: can't detect when search SHOULD have been used but wasn't
  
- **Approach C:** LLM prompt analysis
  - Pro: understands intent without hooks
  - Con: expensive, complex, unreliable for real-time detection

**Why B:** Balances visibility (captures violations) with simplicity (env var state is cheap, reliable). Hooks already exist in the ecosystem (caveman statusline), so infrastructure is proven.

## Open Questions

None — design approved after iterative refinement.

## Implementation Plan

Handled by `writing-plans` skill (next step after spec review).
