# Eval Experiment Runner Design

**Date:** 2026-03-26
**Status:** Approved
**Branch:** `feature/eval-framework`

## Overview

A set of shell scripts that automate setup, state management, guided execution, and result reporting for the claude-code-search eval experiments. The experiments run against `~/code-search-sandbox/llvm-project` (or any path set via `LLVM_DIR`) and measure the impact of claude-code-search on Claude's code navigation behavior.

## Goals

- Let experiments run on any machine with minimal configuration
- Guide the user through each prompt one at a time, with each prompt copied to the clipboard
- Ensure llvm-project is always in a known, validated state before a session
- Collect and organize session data automatically
- Post results directly to GitHub issues

## Non-Goals

- Automating the Claude Code sessions themselves (those remain manual)
- Supporting repos other than llvm-project without modification
- Linux support — scripts use `pbcopy` and target macOS only

## Prerequisites / Known Fixes Required

Before the scripts can be implemented, one bug in `eval.py` must be fixed:

**`eval.py compare` early-returns when modes differ.** `cmd_compare` currently prints a warning and exits when `mode_a != mode_b`. But baseline-vs-run is exactly the comparison we need for `report.sh`. The early return must be removed for the `{"baseline", "run"}` case so the `_compute_edit_hit_rate` path at line 221 is reachable. This fix is part of the implementation work for this spec.

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
| `CODE_SEARCH_LOCAL` | (not set) | When set, `setup.sh` passes it to `install.sh` to use local scripts instead of downloading from GitHub. Set to the path of your local claude-code-search clone. |

All scripts compute `EVAL_DIR` from their own location (`$(cd "$(dirname "$0")/../.." && pwd)`) so they work correctly on any machine regardless of where the repo is cloned.

## Relationship to `eval.py prepare` / `repo.py`

`eval.py prepare` (backed by `repo.py`) was designed to manage state for running evals **against the claude-code-search repo itself** — it resets the source repo, re-indexes it, and configures hooks for that repo. It is not used here.

`reset.sh` manages state for an **external target repo** (`$LLVM_DIR`). It implements its own `.bak` file scheme to toggle the llvm-project between baseline and run states. It calls `repo.py`'s `clear_session_state()` to reset session tracking state stored in `EVAL_DIR`.

## State Management

All file paths in this section are relative to `$LLVM_DIR` unless otherwise noted.

Two named states, managed by `reset.sh`:

### `baseline` state
Claude has no knowledge of or access to the search tool.

| File (relative to `$LLVM_DIR`) | Action |
|---|---|
| `.claude/CLAUDE.md` | moved to `.claude/CLAUDE.md.bak` |
| `.claude/settings.local.json` | moved to `.claude/settings.local.json.bak`; capture-only replacement written |
| `chroma_db/` | present but inaccessible (Claude has no instructions to use it) |

The capture-only `settings.local.json` is written fresh by `reset.sh` using the absolute path to `capture_session.py` in the eval-framework worktree (computed from `EVAL_DIR`). This ensures correct paths on any machine.

### `run` state
Claude has full access to the search tool.

| File (relative to `$LLVM_DIR`) | Action |
|---|---|
| `.claude/CLAUDE.md.bak` | restored to `.claude/CLAUDE.md` |
| `.claude/settings.local.json.bak` | restored to `.claude/settings.local.json` |
| `chroma_db/` | re-indexed before session starts |

### State detection

`validate.sh` uses `.bak` file presence to confirm state:

- `validate.sh baseline`: `.bak` files exist, `CLAUDE.md` absent, settings.local.json contains capture-only hooks (no indexer command)
- `validate.sh run`: originals present, no `.bak` files, `chroma_db/` exists with count > 0, git working tree is clean
- `validate.sh` (no mode): basic health — `LLVM_DIR` exists, is a git repo, git working tree is clean

`reset.sh` refuses to overwrite an existing `.bak` file to prevent double-moves. Run `validate.sh` first to confirm current state before running `reset.sh`.

## Data Flow

```
$LLVM_DIR/.claude/settings.local.json
  └─ hooks fire on each Claude Code tool call
       └─ $EVAL_DIR/eval/hooks/capture_session.py  ← absolute path written by reset.sh
            └─ $EVAL_DIR/eval/results/session-<timestamp>.log

eval.py analyze <mode>
  └─ $EVAL_DIR/eval/results/<timestamp>-<mode>.json

report.sh <baseline.json> <run.json>
  └─ eval.py compare → formatted output
       └─ gh issue create → github.com/$GH_REPO/issues
```

Session logs and reports are always stored in `$EVAL_DIR/eval/results/`, regardless of which machine the experiment runs on. `capture_session.py` derives its results directory from its own `__file__` path, so the absolute path written into `settings.local.json` by `reset.sh` is what determines where logs land.

## Script Details

### `setup.sh`

One-time setup. Safe to re-run (index rebuild is the only side effect on repeat runs).

1. Verify `LLVM_DIR` exists and is a git repo
2. Verify `gh` CLI is installed and authenticated (`gh auth status`)
3. Verify `EVAL_DIR/.venv` exists (venv must be set up in eval-framework repo first)
4. Run `install.sh` against `LLVM_DIR`; if `CODE_SEARCH_LOCAL` is set, pass it through so local scripts are used instead of downloaded ones
5. Run `$EVAL_DIR/.venv/bin/python3 $EVAL_DIR/index_project.py` with `cwd=$LLVM_DIR`
6. Verify `$LLVM_DIR/chroma_db/` exists and is non-empty (via chromadb Python check)
7. Print: "Setup complete. llvm-project is in run state. Run `validate.sh run` to confirm."

Post-setup state is `run`: `install.sh` writes the production `settings.local.json` (which contains the indexer hook and satisfies the `index_project.py` fingerprint check), and `CLAUDE.md` is present with the search protocol. No `.bak` files exist.

### `validate.sh [mode]`

Exits 0 if state matches, 1 with a specific message per failed check.

**No mode:** checks `LLVM_DIR` exists, is a git repo, git working tree is clean.

**`baseline`:**
- `$LLVM_DIR/.claude/CLAUDE.md` is absent
- `$LLVM_DIR/.claude/CLAUDE.md.bak` exists
- `$LLVM_DIR/.claude/settings.local.json` exists and does NOT contain the string `index_project.py` (used as the indexer-command fingerprint)
- `$LLVM_DIR/.claude/settings.local.json.bak` exists

**`run`:**
- `$LLVM_DIR/.claude/CLAUDE.md` exists
- `$LLVM_DIR/.claude/CLAUDE.md.bak` is absent
- `$LLVM_DIR/.claude/settings.local.json.bak` is absent
- `$LLVM_DIR/.claude/settings.local.json` exists and contains the string `index_project.py`
- `$LLVM_DIR/chroma_db/` exists and is non-empty (via `python3 -c "import chromadb; c = chromadb.PersistentClient('$LLVM_DIR/chroma_db'); print(c.get_collection('project_code').count())"`)
- `$LLVM_DIR` git working tree is clean

### `reset.sh [baseline|run]`

Transitions llvm-project to the named state. Fails fast if already in target state.

**`reset.sh baseline`:**
1. Abort if `$LLVM_DIR/.claude/CLAUDE.md.bak` already exists (already in baseline state)
2. `mv $LLVM_DIR/.claude/CLAUDE.md $LLVM_DIR/.claude/CLAUDE.md.bak`
3. `mv $LLVM_DIR/.claude/settings.local.json $LLVM_DIR/.claude/settings.local.json.bak`
4. Write capture-only `$LLVM_DIR/.claude/settings.local.json`:
   ```json
   {
     "hooks": {
       "UserPromptSubmit": [{"command": "<abs-path>/capture_session.py prompt"}],
       "PostToolUse":      [{"command": "<abs-path>/capture_session.py post"}],
       "Stop":             [{"command": "<abs-path>/capture_session.py stop"}]
     }
   }
   ```
   where `<abs-path>` = `$EVAL_DIR/eval/hooks/capture_session.py`
5. Run `cd $EVAL_DIR && $EVAL_DIR/.venv/bin/python3 -c "from eval.repo import clear_session_state; clear_session_state()"` — `cd $EVAL_DIR` is required so the module import resolves correctly
6. Print: "Ready for baseline. Run `validate.sh baseline` to confirm, then `run-experiment.sh baseline`."

**`reset.sh run`:**
1. Abort if `$LLVM_DIR/.claude/CLAUDE.md` already exists (already in run state, not in baseline)
2. `mv $LLVM_DIR/.claude/CLAUDE.md.bak $LLVM_DIR/.claude/CLAUDE.md`
3. `mv $LLVM_DIR/.claude/settings.local.json.bak $LLVM_DIR/.claude/settings.local.json`
4. Re-index: run `index_project.py` with `cwd=$LLVM_DIR`
5. Run `cd $EVAL_DIR && $EVAL_DIR/.venv/bin/python3 -c "from eval.repo import clear_session_state; clear_session_state()"`
6. Print: "Ready for run. Run `validate.sh run` to confirm, then `run-experiment.sh run`."

### `run-experiment.sh [baseline|run]`

Guided runner for macOS. Walks through every prompt in `eval/benchmarks/llvm.json` one at a time, copying each to the clipboard.

**Warning:** Re-running this script clears all session state. Do not re-run mid-session.

`validate.sh <mode>` is called only in step 2 (before sessions begin). The git-clean check it includes is intentional — it only applies pre-session, not after Claude Code edits files during the session.

1. Require mode argument; print usage if missing
2. Run `validate.sh <mode>`; print specific failure message and abort if it fails
3. Call `cd $EVAL_DIR && $EVAL_DIR/.venv/bin/python3 -c "from eval.repo import clear_session_state; clear_session_state()"` to start fresh
4. Loop — call `eval.py next-task` repeatedly; terminate when output contains the literal string `"All tasks complete."`:
   - `eval.py next-task` output format per iteration:
     ```
     Task {N} of {total}
     Task ID: {id}
     Prompt:  {prompt text}
     ```
   - Extract prompt text as everything after `"Prompt:  "` on that line
   - Print task number and ID
   - Copy prompt text to clipboard: `printf '%s' "<prompt>" | pbcopy`
   - Print: `"Prompt copied to clipboard. Open Claude Code in $LLVM_DIR, paste and run it. Press Enter when done."`
   - `read` to wait for Enter
5. Run `eval.py analyze <mode>`; capture the report path printed on the `"Report saved to"` line
6. For baseline runs: write report path to `$EVAL_DIR/.eval_last_baseline` (always overwrite, never append). This file is not deleted by `clear_session_state()` — it persists until a new baseline is run.
7. Print next step:
   - baseline: `"Baseline complete. Report: <path>\nNext: reset.sh run && run-experiment.sh run"`
   - run: `"Run complete. Report: <path>\nNext: report.sh $(cat $EVAL_DIR/.eval_last_baseline) <path>"`

### `report.sh <baseline.json> <run.json>`

Compares two reports and creates a GitHub issue. Uses metadata from the `run` report's git block for the issue title.

1. Verify both file arguments are provided and exist
2. Verify `gh` is installed and authenticated (`gh auth status`)
3. Validate that `<baseline.json>` has `"mode": "baseline"` and `<run.json>` has `"mode": "run"`; abort with a clear message if not
4. Run `eval.py compare <baseline.json> <run.json>`; capture output
5. Extract from `<run.json>`: `branch`, `commit` (short), `timestamp`
6. Build issue title: `"Eval results: baseline vs run — <branch> @ <commit>"`
7. Build issue body. Extract from each JSON file: top-level `timestamp` field and `git.commit`, `git.branch` fields:
   ```
   ## Comparison

   <eval.py compare output>

   ## Metadata

   | | Baseline | Run |
   |---|---|---|
   | Timestamp | <baseline[timestamp]> | <run[timestamp]> |
   | Commit | <baseline[git.commit]> | <run[git.commit]> |
   | Branch | <baseline[git.branch]> | <run[git.branch]> |

   **Machine:** <hostname>
   **Date:** <date>
   ```
8. Run `gh issue create --repo $GH_REPO --title "..." --body "..."`
9. Print the new issue URL

## Error Handling

- All scripts: print usage and exit 1 if required arguments are missing
- `setup.sh`: fails if `LLVM_DIR` not found, `gh` not installed/authenticated, venv missing, or index produces 0 documents
- `validate.sh`: exit 1 with a specific message per failed check
- `reset.sh`: refuses to overwrite `.bak` files; refuses to restore if originals still present
- `run-experiment.sh`: aborts before clearing session state if `validate.sh` fails; warns clearly that re-running destroys session state
- `report.sh`: aborts if either JSON file is missing, modes are wrong, or `gh` is not authenticated

## Testing

- `validate.sh`: test by manually toggling `.bak` files and confirming exit codes and messages
- `reset.sh`: `reset.sh baseline` followed by `reset.sh run` returns to original state; verify with `validate.sh run`
- `setup.sh`: safe to re-run; second run is faster (index rebuild only)
- `run-experiment.sh`: test with a small 1-entry benchmark file to verify prompt display, clipboard copy, and analyze step
- `report.sh`: test with two pre-existing JSON files in `eval/results/` (one baseline, one run) before running a real experiment
