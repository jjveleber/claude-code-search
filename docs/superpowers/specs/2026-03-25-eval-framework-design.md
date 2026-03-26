# Eval Framework Design

**Date:** 2026-03-25
**Status:** Approved

## Problem

There is no empirical way to determine whether claude-code-search improves Claude's behavior, nor to detect regressions when the tool changes. Decisions about chunking, indexing, and configuration are made without data.

## Goals

- Measure whether code-search reduces wasted file exploration and token usage
- Produce comparable metrics across code changes so improvements and regressions are visible
- Keep eval infrastructure completely separate from production code
- Require no Claude API spend to run

## Non-Goals

- Evaluating Claude's task completion quality (only navigation efficiency)
- Real-time or continuous monitoring
- Automated CI/CD gating (phase 2)

---

## Architecture

Two independent eval layers that share the same real codebase and ChromaDB index:

```
eval/
  eval.py                        ← CLI entry point
  benchmarks/
    llvm.json                    ← committed: task prompts (integration) + expected files (unit)
  results/                       ← gitignored: session logs and run reports
  hooks/
    capture_session.py           ← opt-in PostToolUse hook, separate from production
  README.md
```

**Unit layer** — measures `search_code.py` result quality directly by running benchmark queries and scoring them against known expected files. No Claude involved. Fast, fully automated.

**Integration layer** — measures Claude's navigation behavior across two manually-run sessions: one without search (baseline) and one with search enabled. The baseline session's edit log defines ground truth. A developer runs each session; `eval.py` handles setup, teardown, and analysis.

Both layers produce reports in the same JSON format so `eval.py compare` works on both.

---

## Benchmark Dataset

**File:** `eval/benchmarks/llvm.json`

Each entry serves both layers. The `prompt` field drives integration sessions; the `expected_files` field drives unit eval. Unit expected files are populated by promoting entries from baseline session logs using `eval.py promote`.

```json
[
  {
    "id": "llvm-001",
    "prompt": "Find where SelectionDAG handles vector shuffle lowering and explain the approach",
    "expected_files": [
      "llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp"
    ],
    "acceptable_files": [
      "llvm/lib/CodeGen/SelectionDAG/SelectionDAGTargetInfo.cpp"
    ],
    "notes": "Tests concept-level navigation in CodeGen"
  }
]
```

- `expected_files` — must appear in search results for full credit
- `acceptable_files` — partial credit; relevant but secondary
- New entries start with empty `expected_files`; they are populated via `eval.py promote` after a baseline session

---

## Unit Layer

The unit layer calls `search_code.py` as a subprocess for each benchmark entry, parses stdout, and scores results. It does not involve Claude.

### Runner Behavior

The `--top` value defaults to 5 and is configurable via `eval.py unit --top N`. The value used is recorded in `config.top` of the report.

For each benchmark entry:
1. Run `.venv/bin/python3 search_code.py "<prompt>" --top <N>` as a subprocess
2. Parse the result lines (`MATCH N: <path> (lines X-Y)`) to extract ranked file paths
3. Score the result against `expected_files` and `acceptable_files`
4. Abort with a clear error if the ChromaDB index does not exist (exit code 1 from search_code.py)

### Unit Metrics

| Metric | Formula |
|---|---|
| `recall@k` | 1 if any `expected_files` entry appears in top-k results, else 0; averaged across entries |
| `MRR` | Mean of `1/rank` where rank is the position of the first `expected_files` hit; 0 if no hit |
| `precision@k` | `(expected hits + 0.5 × acceptable hits) / k`; averaged across entries |
| `hit_rate` | % of benchmark entries with at least one `expected_files` hit in top-k |

---

## Integration Layer

### How Sessions Are Run

Integration sessions require a developer to run Claude Code manually. `eval.py` does not launch Claude — it cannot without incurring API cost.

**Workflow:**

```
eval.py prepare baseline   # git reset + re-index, disable search hook, print task prompts
# developer runs each prompt in Claude Code
eval.py analyze baseline   # parse session log, write baseline report

eval.py prepare run        # git reset + re-index, enable search hook, print task prompts
# developer runs same prompts in Claude Code
eval.py analyze run        # parse session log, write run report
```

`eval.py prepare` configures `.claude/settings.local.json` to enable or disable the search hook and the capture hook. `eval.py analyze` processes the captured session log.

### Session Capture

`eval/hooks/capture_session.py` is a `PostToolUse` Claude Code hook, installed separately from the production hook. It appends one JSON line per tool call to `eval/results/session-TIMESTAMP.log`.

**Task ID binding:** Before running each prompt, the developer runs `eval.py next-task`, which prints the next task ID and prompt and writes the current task ID to `.eval_current_task` (a temp file in the project root, gitignored). The `UserPromptSubmit` hook reads this file to determine the task ID for the upcoming turn and writes a `task_start` delimiter. The `PostToolUse` hook reads the same file to tag each tool call. On `task_end` (written after the turn completes via the `Stop` hook), the file is cleared.

```json
{"type": "task_start", "task_id": "llvm-001", "ts": "14:30:00"}
{"type": "tool", "tool": "Bash", "cmd": "search_code.py \"vector shuffle lowering\"", "results": [{"rank": 1, "path": "llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp", "lines": "120-180"}, {"rank": 2, "path": "llvm/lib/Target/X86/X86ISelLowering.cpp", "lines": "3200-3260"}], "ts": "14:30:01"}
{"type": "tool", "tool": "Read", "file": "llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp", "bytes": 4200, "ts": "14:30:03"}
{"type": "tool", "tool": "Edit", "file": "llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp", "ts": "14:30:09"}
{"type": "task_end", "task_id": "llvm-001", "ts": "14:30:15"}
```

**Search result capture:** The `results` field is populated only for Bash tool calls where the command string contains `search_code.py`. For all other Bash calls, `results` is omitted. The capture hook detects search calls via substring match on `"search_code.py"` in the command. For Read calls, `bytes` records the file size (used for token estimation). Edit calls record only the file path.

### Ground Truth Derivation

The baseline session (search disabled) establishes ground truth:

- **Edited files** = target files for that task (definitive signal)
- **Read-then-not-edited files** = wasted exploration

No human confirmation is required. Ground truth is derived automatically by `eval.py analyze baseline`.

### Improvement / Regression Criteria

| Observation | Classification |
|---|---|
| Files discarded in baseline but not in run | Improvement |
| Files discarded in run but not in baseline | Regression |
| Edited files match between baseline and run | Targets found |
| Edited files in baseline missing from run | Regression |

### Grep Fallback Detection

A "grep fallback" occurs within a task when:
1. At least one `search_code.py` call has been made in the task, AND
2. A subsequent Bash tool call contains `grep`, `rg`, or `find` in the command string

`Glob` tool calls are excluded from fallback detection — they are used for structural exploration and do not indicate that search failed.

`grep_fallback_rate` = number of tasks with at least one fallback / total tasks.

### Reset and Re-index

Before each `eval.py prepare` run:

1. Check for dirty repo state — if uncommitted changes exist, print a warning and abort. The developer must commit or stash before running eval.
2. `git checkout .` — restore modified tracked files
3. `git clean -fd --exclude=eval/` — remove untracked files created during the previous session, preserving `eval/results/` and all eval infrastructure
4. `.venv/bin/python3 index_project.py` — incremental re-index (fast, only re-embeds changed chunks)

### Promoting Entries to Unit Benchmark

After `eval.py analyze baseline`, run `eval.py promote <baseline-report.json>` to populate `expected_files` in `benchmarks/llvm.json`. For each task, the baseline's `edited_files` are merged into `expected_files` — new files are added, existing entries are preserved. No entries are removed. No confirmation required.

---

## Data Model

### Run Report (`eval/results/TIMESTAMP.json`)

```json
{
  "timestamp": "2026-03-25T14:30:00",
  "mode": "baseline | run | unit",
  "git": {
    "commit": "2f571c5",
    "message": "fix: improve chunking overlap",
    "branch": "main",
    "dirty": false
  },
  "config": {
    "chunk_size": 60,
    "overlap": 10,
    "top": 5
  },
  "tasks": [
    {
      "id": "llvm-001",
      "edited_files": ["llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp"],
      "discarded_reads": ["llvm/lib/Target/X86/X86ISelLowering.cpp"],
      "search_calls": 2,
      "grep_fallbacks": 0,
      "total_tool_calls": 8,
      "tokens": {
        "files_read_bytes": 42800,
        "search_result_bytes": 3200,
        "estimated_tokens": 11500
      }
    }
  ],
  "summary": {
    "edit_hit_rate": 1.0,
    "discarded_reads_total": 3,
    "avg_tool_calls_per_task": 8,
    "grep_fallback_rate": 0.0,
    "avg_estimated_tokens_per_task": 11500
  }
}
```

### Unit Report (`eval/results/TIMESTAMP.json`, `mode: "unit"`)

```json
{
  "timestamp": "2026-03-25T14:30:00",
  "mode": "unit",
  "git": {
    "commit": "2f571c5",
    "message": "fix: improve chunking overlap",
    "branch": "main",
    "dirty": false
  },
  "config": {
    "chunk_size": 60,
    "overlap": 10,
    "top": 5
  },
  "tasks": [
    {
      "id": "llvm-001",
      "query": "Find where SelectionDAG handles vector shuffle lowering...",
      "results": [
        {"rank": 1, "path": "llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp"},
        {"rank": 2, "path": "llvm/lib/Target/X86/X86ISelLowering.cpp"}
      ],
      "recall_at_k": 1.0,
      "reciprocal_rank": 1.0,
      "precision_at_k": 0.8,
      "hit": true
    }
  ],
  "summary": {
    "recall_at_k": 0.90,
    "MRR": 0.82,
    "precision_at_k": 0.74,
    "hit_rate": 0.90
  }
}
```

`eval.py compare` works across both report types for fields that exist in both (`git`, `config`, `timestamp`). Metrics are compared only between reports of the same `mode`. Comparing a `unit` report against a `run` report prints a warning and shows only the shared metadata fields.

### Metric Definitions

**`edit_hit_rate`** (integration):
```
per task: |run.edited_files ∩ baseline.edited_files| / |baseline.edited_files|
summary:  mean across all tasks
```

**`estimated_tokens`** (integration):
```
(files_read_bytes + search_result_bytes) / 4
```

Exact token counts are preferred. The `Stop` hook will be investigated during implementation to determine whether Claude Code exposes session token usage. If unavailable, the proxy above is used. Relative comparisons between baseline and run remain valid under the proxy.

**`config.top`** matches the `--top` argument of `search_code.py`.

---

## CLI

```
eval.py prepare <baseline|run>   # dirty check, git reset, re-index, configure hooks, print task list
eval.py next-task                # print next task ID and prompt for the developer to run
eval.py analyze <baseline|run>   # parse session log, write timestamped report
eval.py promote <report.json>    # populate expected_files in benchmarks from a baseline report
eval.py unit                     # run unit eval against benchmark, write timestamped report
eval.py compare <a.json> <b.json># diff two reports, show improvements and regressions
eval.py results                  # list saved reports with git metadata
```

### Compare Output Format

```
Baseline: 2026-03-25T14:00  commit abc123  "before search"
Run:      2026-03-25T16:00  commit abc123  "with search enabled"

Edit hit rate:          1.0  → 1.0    (no change)
Discarded reads:         11  → 4      (-7)   ✓ improvement
Avg tool calls/task:     14  → 9      (-5)   ✓ improvement
Est. tokens/task:      2900  → 1840   (-37%) ✓ improvement
Search calls/task:        0  → 2      (search used)
Grep fallback rate:     0%   → 10%    (+10%) ✗ regression
```

Regressions are flagged with ✗. The git commit and dirty state of each run are shown so the cause of any change is traceable.

---

## Metrics Reference

| Metric | Layer | What it measures |
|---|---|---|
| `edit_hit_rate` | Integration | % of baseline-edited files also edited in run, per task |
| `discarded_reads_total` | Integration | Total files read but not edited across all tasks |
| `avg_tool_calls_per_task` | Integration | Navigation cost per task |
| `search_calls` | Integration | How often search_code.py was invoked |
| `grep_fallback_rate` | Integration | % of tasks where Claude fell back to grep/glob after searching |
| `estimated_tokens` | Integration | Proxy for input tokens consumed by navigation |
| `recall@k` | Unit | Did an expected file appear in top-k results |
| `MRR` | Unit | Mean reciprocal rank of first correct result |
| `precision@k` | Unit | Fraction of top-k results that are expected or acceptable |
| `hit_rate` | Unit | % of benchmark entries with at least one expected hit |

---

## File Layout

```
eval/
  eval.py
  benchmarks/
    llvm.json
  results/               ← gitignored
    session-*.log
    *.json
  hooks/
    capture_session.py
  README.md
```

`eval/results/` and `.eval_current_task` are added to `.gitignore`. All other files under `eval/` are committed.
