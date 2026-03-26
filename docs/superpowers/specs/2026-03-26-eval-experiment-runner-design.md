# Eval Experiment Runner Design

**Date:** 2026-03-26
**Status:** Approved
**Branch:** `feature/eval-framework`

## Overview

A set of shell scripts that automate setup, state management, guided execution, and result reporting for the claude-code-search eval experiments. The experiments run against `~/code-search-sandbox/llvm-project` (or any path set via `LLVM_DIR`) and measure the impact of claude-code-search on Claude's code navigation behavior.

## Goals

- Let experiments run on any machine with minimal configuration
- Guide the user through each prompt one at a time with clear instructions
- Ensure llvm-project is always in a known, validated state before a session
- Collect and organize session data automatically
- Post results directly to GitHub issues

## Non-Goals

- Automating the Claude Code sessions themselves (those remain manual)
- Supporting repos other than llvm-project without modification
- Modifying the existing `eval.py` CLI

## Scripts

```
eval/scripts/
  setup.sh                           ← one-time: verify llvm-project, run install.sh, initial index
  validate.sh [baseline|run]         ← confirm llvm-project is in expected state
  reset.sh [baseline|run]            ← transition llvm-project between states
  run-experiment.sh [baseline|run]   ← guided runner: validate → walk prompts → analyze
  report.sh <baseline.json> <run.json>  ← compare two reports + create GitHub issue
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `LLVM_DIR` | `~/code-search-sandbox/llvm-project` | Path to the target repo |
| `GH_REPO` | `jjveleber/claude-code-search` | GitHub repo for issue creation |
| `EVAL_DIR` | derived from script location | Path to eval-framework root (auto-computed) |

All scripts compute `EVAL_DIR` from their own location (`$(cd "$(dirname "$0")/../.." && pwd)`) so they work correctly on any machine regardless of where the repo is cloned.

## State Management

Two named states, managed by `reset.sh`:

### `baseline` state
Claude has no knowledge of or access to the search tool.

| File | Action |
|---|---|
| `.claude/CLAUDE.md` | moved to `.claude/CLAUDE.md.bak` |
| `.claude/settings.local.json` | moved to `.claude/settings.local.json.bak`; capture-only replacement written |
| `chroma_db/` | present but inaccessible (Claude has no instructions to use it) |

The capture-only `settings.local.json` is written fresh by `reset.sh` with paths computed for the current machine, pointing to `capture_session.py` in the eval-framework worktree.

### `run` state
Claude has full access to the search tool.

| File | Action |
|---|---|
| `.claude/CLAUDE.md.bak` | restored to `.claude/CLAUDE.md` |
| `.claude/settings.local.json.bak` | restored to `.claude/settings.local.json` |
| `chroma_db/` | re-indexed before session starts |

### State detection

`validate.sh` uses `.bak` file presence to confirm state:

- `validate.sh baseline`: `.bak` files exist, `CLAUDE.md` absent, capture-only hooks present
- `validate.sh run`: originals present, no `.bak` files, `chroma_db/` exists with count > 0
- `validate.sh` (no mode): basic health — `LLVM_DIR` exists, git repo, git clean

`reset.sh` refuses to overwrite an existing `.bak` file to prevent double-moves. Run `validate.sh` first to confirm current state.

## Data Flow

```
$LLVM_DIR/.claude/settings.local.json
  └─ hooks fire on each Claude Code tool call
       └─ capture_session.py (path written dynamically by reset.sh)
            └─ $EVAL_DIR/eval/results/session-<timestamp>.log

eval.py analyze <mode>
  └─ $EVAL_DIR/eval/results/<timestamp>-<mode>.json

report.sh <baseline.json> <run.json>
  └─ eval.py compare → formatted output
       └─ gh issue create → github.com/$GH_REPO/issues
```

Session logs and reports are always stored in `eval/results/` inside the eval-framework worktree, regardless of which machine the experiment runs on.

## Script Details

### `setup.sh`

One-time setup. Safe to re-run (idempotent for the index, skips install if already present).

1. Verify `LLVM_DIR` exists and is a git repo
2. Verify `gh` CLI is installed
3. Run `install.sh` against `LLVM_DIR` using `CODE_SEARCH_LOCAL` to use local scripts
4. Run `index_project.py` against `LLVM_DIR`
5. Confirm `chroma_db/` exists with count > 0
6. Print: "Setup complete. Run `validate.sh run` to confirm state."

### `validate.sh [mode]`

Exits 0 if state matches, 1 with explanation if not.

**No mode:** checks `LLVM_DIR` exists, is a git repo, git working tree is clean.

**`baseline`:**
- `.claude/CLAUDE.md` is absent (moved to `.bak`)
- `.claude/CLAUDE.md.bak` exists
- `.claude/settings.local.json` exists and contains capture-only hooks (no indexer command)
- `.claude/settings.local.json.bak` exists

**`run`:**
- `.claude/CLAUDE.md` exists
- No `.bak` files present
- `.claude/settings.local.json` exists and contains search hooks
- `chroma_db/` exists and is non-empty (via `python3 -c "import chromadb; ..."`)
- Git working tree is clean

### `reset.sh [baseline|run]`

Transitions llvm-project to the named state. Fails fast if already in target state (`.bak` file conflict).

**`reset.sh baseline`:**
1. Abort if `.claude/CLAUDE.md.bak` already exists
2. `mv .claude/CLAUDE.md .claude/CLAUDE.md.bak`
3. `mv .claude/settings.local.json .claude/settings.local.json.bak`
4. Write capture-only `settings.local.json` with current-machine paths to `capture_session.py`
5. Clear session state (`.eval_current_task`, `.eval_task_index`, `.eval_session_log`, old `session-*.log` files)
6. Print: "Ready for baseline. Run `validate.sh baseline` to confirm, then `run-experiment.sh baseline`."

**`reset.sh run`:**
1. Abort if `.claude/CLAUDE.md` already exists (not in baseline state)
2. `mv .claude/CLAUDE.md.bak .claude/CLAUDE.md`
3. `mv .claude/settings.local.json.bak .claude/settings.local.json`
4. Re-index: `python3 index_project.py` in `LLVM_DIR`
5. Clear session state
6. Print: "Ready for run. Run `validate.sh run` to confirm, then `run-experiment.sh run`."

### `run-experiment.sh [baseline|run]`

Guided runner. Walks through every prompt in `llvm.json`, pausing for the user to run each in Claude Code.

1. Require mode argument; print usage if missing
2. Run `validate.sh <mode>`; abort with instructions if it fails
3. Clear session state
4. For each prompt (via `eval.py next-task` loop):
   - Print task number, ID, and prompt text
   - Print: `"Open Claude Code in $LLVM_DIR and run the above prompt. Press Enter when done."`
   - `read` to wait
5. Run `eval.py analyze <mode>`; print report path
6. Print next step:
   - baseline: `"Now run: reset.sh run && run-experiment.sh run"`
   - run: `"Now run: report.sh eval/results/<baseline>.json eval/results/<run>.json"`

### `report.sh <baseline.json> <run.json>`

Compares two reports and creates a GitHub issue.

1. Verify both files exist and `gh` is installed
2. Run `eval.py compare <a> <b>`; capture output
3. Extract metadata (timestamps, commits, branch) from both JSON files
4. Build issue title: `"Eval results: baseline vs run — <branch> @ <commit>"`
5. Build issue body: comparison table + metadata block + machine info (`hostname`, `date`)
6. Run `gh issue create --repo $GH_REPO --title "..." --body "..."`
7. Print the new issue URL

## Error Handling

- All scripts: print usage and exit 1 if required arguments are missing
- `setup.sh`: fails if `LLVM_DIR` not found, `gh` not installed, or index produces 0 documents
- `validate.sh`: exit 1 with a specific message per failed check (not a generic failure)
- `reset.sh`: refuses to overwrite `.bak` files; refuses to restore if originals still present
- `run-experiment.sh`: aborts before touching session state if `validate.sh` fails
- `report.sh`: aborts if either JSON file is missing or `gh` is not authenticated

## Testing

- `validate.sh` can be tested by manually toggling `.bak` files and confirming exit codes
- `reset.sh` is idempotent in the sense that `reset.sh baseline` followed by `reset.sh run` returns to the original state
- `setup.sh` is safe to re-run; second run should complete faster (index already built)
