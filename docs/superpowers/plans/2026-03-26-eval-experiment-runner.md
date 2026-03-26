# Eval Experiment Runner Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build five shell scripts (`setup.sh`, `validate.sh`, `reset.sh`, `run-experiment.sh`, `report.sh`) plus an updated benchmark JSON that let experiments run on any machine, guide the user through prompts with clipboard copy, and post results to GitHub issues.

**Architecture:** Shell scripts in `eval/scripts/` operate on an external llvm-project repo (`$LLVM_DIR`). State is managed by toggling `.bak` files in `$LLVM_DIR/.claude/`. Session capture hooks are written with absolute paths derived from `EVAL_DIR` (computed from the script's own location). All results land in `eval/results/` inside the eval-framework worktree.

**Tech Stack:** bash, Python 3 (chromadb for index validation, eval.py for task/analyze/compare), gh CLI for GitHub issues, pbcopy (macOS).

**Spec:** `docs/superpowers/specs/2026-03-26-eval-experiment-runner-design.md`

---

## Files

| File | Action | Purpose |
|---|---|---|
| `eval/benchmarks/llvm.json` | Modify | Replace 3 stubs with 18 full benchmark prompts |
| `eval/scripts/validate.sh` | Create | Confirm llvm-project is in a named state |
| `eval/scripts/reset.sh` | Create | Transition llvm-project between baseline and run states |
| `eval/scripts/setup.sh` | Create | One-time setup: install + index llvm-project |
| `eval/scripts/run-experiment.sh` | Create | Guided runner: validate → walk prompts → analyze |
| `eval/scripts/report.sh` | Create | Compare two reports + create GitHub issue |

---

## Chunk 1: Update benchmark JSON

### Task 1: Replace llvm.json with 18 full prompts

**Files:**
- Modify: `eval/benchmarks/llvm.json`

The existing file has 3 stubs with empty `expected_files`. Replace with 18 prompts across 9 task types. `expected_files` and `acceptable_files` remain empty — they get populated after the first baseline run via `eval.py promote`.

- [ ] **Step 1: Overwrite `eval/benchmarks/llvm.json`**

```json
[
  {
    "id": "llvm-nav-001",
    "prompt": "Where is the Value class defined and what other classes inherit from it? I need to understand the base hierarchy of LLVM IR values.",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Navigation — find class definition and inheritance hierarchy"
  },
  {
    "id": "llvm-nav-002",
    "prompt": "I need to understand how the Global Value Numbering pass is implemented. Where does it live and what are the main methods?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Navigation — find a major compiler pass and its entry points"
  },
  {
    "id": "llvm-understand-001",
    "prompt": "Explain how LoopVectorizePass uses results from other analyses like DominatorTree, ScalarEvolution, and TargetTransformInfo to drive vectorization decisions.",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Understanding — cross-file data flow between a pass and multiple analyses"
  },
  {
    "id": "llvm-understand-002",
    "prompt": "I need to understand how CodeGenFunction manages code generation for a function, particularly how it coordinates with IRBuilder, debug info, and PGO instrumentation.",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Understanding — complex object composition across multiple systems"
  },
  {
    "id": "llvm-modify-001",
    "prompt": "I want to extend the ExpandMemCmp pass to track which loads participate in size-dependent optimizations. What changes would I need to make to the LoadEntry structure and the code that uses it?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Modification — data structure change with ripple effects across methods"
  },
  {
    "id": "llvm-modify-002",
    "prompt": "SimplifyCFG has several command-line flags like HoistCommon and PHINodeFoldingThreshold. I want to add a new option --simplifycfg-aggressive-inlining that affects how it folds basic blocks. What would need to be changed?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Modification — add CLI option touching infrastructure and implementation"
  },
  {
    "id": "llvm-debug-001",
    "prompt": "I have code where GVN isn't eliminating what looks like a redundant load. GVN mentions MemorySSA and MemoryDependenceAnalysis. Why might it not eliminate the load? What conditions prevent it?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Debugging — trace conditional logic across multiple analyses"
  },
  {
    "id": "llvm-debug-002",
    "prompt": "I notice ExpandMemCmp creates blocks for comparing 33 bytes as 2x16-byte loads and 1x1-byte load. How does it decide this decomposition? What determines MaxLoadSize and how does it compute LoadSequence?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Debugging — understand algorithmic decision-making and data structures"
  },
  {
    "id": "llvm-deps-001",
    "prompt": "I need to understand the impact of modifying SimplifyRecursivelyDeleted in SimplifyCFG. What are all the call sites, and what does it depend on internally?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Dependency tracing — forward and backward call chain analysis"
  },
  {
    "id": "llvm-deps-002",
    "prompt": "I want to understand the dependency analysis pipeline. Who calls DependenceAnalysis::depends() and what does it call internally?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Dependency tracing — complex analysis with many helpers and diverse callers"
  },
  {
    "id": "llvm-xcut-001",
    "prompt": "I need to audit all places where replaceAllUsesWith is called across the LLVM codebase. Are there any pattern variations I should know about?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Cross-cutting search — common pattern with variations across many files"
  },
  {
    "id": "llvm-xcut-002",
    "prompt": "Where are all the LLVM intrinsics defined (like x86_sse2_* functions), and what is the pattern for adding a new one? Show me how many different places use intrinsic IDs.",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Cross-cutting search — spans TableGen, headers, and implementations"
  },
  {
    "id": "llvm-api-001",
    "prompt": "I'm writing a pass that needs to insert a new instruction between two existing instructions in a basic block. What's the recommended API? Show me how it's done in existing passes.",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "API discovery — idiomatic instruction insertion pattern"
  },
  {
    "id": "llvm-api-002",
    "prompt": "I'm implementing a CFG transformation that merges basic blocks. How do I correctly update the dominance tree? Are there helpers to do this automatically?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "API discovery — non-obvious DomTreeUpdater helper exists"
  },
  {
    "id": "llvm-compare-001",
    "prompt": "LLVM has both DominatorTree and PostDominatorTree analyses. What's the conceptual difference, and can you show me examples where each is used in different passes?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Comparison — subtle algorithmic differences with diverse usage examples"
  },
  {
    "id": "llvm-compare-002",
    "prompt": "GVN supports both MemorySSA and MemoryDependenceAnalysis. What's the difference between them, and which does GVN prefer?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Comparison — different approaches to same problem, conditional logic"
  },
  {
    "id": "llvm-refactor-001",
    "prompt": "Suppose we want to change IRBuilder::CreateLoad to require an explicit alignment parameter (removing the default). What are all the places that would break, and how would we fix them systematically?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Refactoring — broad-impact change requiring all call site discovery"
  },
  {
    "id": "llvm-refactor-002",
    "prompt": "The Value class is the base of the LLVM IR hierarchy. If we add a new required field to its constructor, what would break? How many subclasses and initialization sites would need changes?",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Refactoring — fundamental infrastructure change, inheritance hierarchy impact"
  }
]
```

- [ ] **Step 2: Verify JSON is valid**

```bash
cd .worktrees/eval-framework
source .venv/bin/activate
python3 -c "import json; entries = json.load(open('eval/benchmarks/llvm.json')); print(f'{len(entries)} entries loaded'); assert len(entries) == 18"
```

Expected: `18 entries loaded`

- [ ] **Step 3: Verify eval.py next-task can read all entries**

```bash
cd .worktrees/eval-framework
source .venv/bin/activate
python3 eval/eval.py next-task --benchmark eval/benchmarks/llvm.json
```

Expected: prints `Task 1 of 18` with `llvm-nav-001` prompt. (Then reset the task index: `rm -f .eval_task_index .eval_current_task`)

```bash
rm -f .eval_task_index .eval_current_task
```

- [ ] **Step 4: Commit**

```bash
git add eval/benchmarks/llvm.json
git commit -m "feat: expand llvm benchmark to 18 prompts across 9 task types"
```

---

## Chunk 2: State management scripts (`validate.sh` + `reset.sh`)

These two scripts are written together because `reset.sh`'s correctness is verified entirely through `validate.sh`.

### Task 2: Write `validate.sh`

**Files:**
- Create: `eval/scripts/validate.sh`

- [ ] **Step 1: Create `eval/scripts/` directory and write `validate.sh`**

Key implementation notes:
- Use `$PYTHON` (`$EVAL_DIR/.venv/bin/python3`) for the chromadb count check — not bare `python3`, which may lack chromadb
- `run` mode must call `check_base()` which includes the git-clean check
- `baseline` mode must also call `check_base()` for the git-clean check

```bash
mkdir -p eval/scripts
```

Create `eval/scripts/validate.sh`:

```bash
#!/usr/bin/env bash
# validate.sh [baseline|run]
# Exits 0 if llvm-project is in the expected state, 1 with a message if not.
set -euo pipefail

EVAL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LLVM_DIR="${LLVM_DIR:-$HOME/code-search-sandbox/llvm-project}"
PYTHON="$EVAL_DIR/.venv/bin/python3"
MODE="${1:-}"

fail() { echo "ERROR: $1" >&2; exit 1; }
ok()   { echo "OK: $1"; }

check_base() {
    [ -d "$LLVM_DIR" ]                                           || fail "LLVM_DIR not found: $LLVM_DIR"
    git -C "$LLVM_DIR" rev-parse --git-dir >/dev/null 2>&1      || fail "$LLVM_DIR is not a git repo"
    [ -z "$(git -C "$LLVM_DIR" status --porcelain)" ]           || fail "$LLVM_DIR has uncommitted changes"
}

check_baseline() {
    check_base
    [ ! -f "$LLVM_DIR/.claude/CLAUDE.md" ]                      || fail ".claude/CLAUDE.md exists — not in baseline state"
    [ -f "$LLVM_DIR/.claude/CLAUDE.md.bak" ]                    || fail ".claude/CLAUDE.md.bak missing"
    [ -f "$LLVM_DIR/.claude/settings.local.json" ]              || fail ".claude/settings.local.json missing"
    ! grep -q "index_project.py" "$LLVM_DIR/.claude/settings.local.json" \
                                                                 || fail ".claude/settings.local.json contains indexer command (not capture-only)"
    [ -f "$LLVM_DIR/.claude/settings.local.json.bak" ]          || fail ".claude/settings.local.json.bak missing"
    ok "llvm-project is in baseline state"
}

check_run() {
    check_base
    [ -f "$LLVM_DIR/.claude/CLAUDE.md" ]                        || fail ".claude/CLAUDE.md missing"
    [ ! -f "$LLVM_DIR/.claude/CLAUDE.md.bak" ]                  || fail ".claude/CLAUDE.md.bak exists — still in baseline state"
    [ ! -f "$LLVM_DIR/.claude/settings.local.json.bak" ]        || fail ".claude/settings.local.json.bak exists — still in baseline state"
    [ -f "$LLVM_DIR/.claude/settings.local.json" ]              || fail ".claude/settings.local.json missing"
    grep -q "index_project.py" "$LLVM_DIR/.claude/settings.local.json" \
                                                                 || fail ".claude/settings.local.json missing indexer command"
    [ -d "$LLVM_DIR/chroma_db" ]                                || fail "chroma_db/ not found in $LLVM_DIR"
    COUNT="$("$PYTHON" -c "
import chromadb, sys
try:
    c = chromadb.PersistentClient(path='$LLVM_DIR/chroma_db')
    print(c.get_collection('project_code').count())
except Exception as e:
    print(0)
" 2>/dev/null)"
    [ "${COUNT:-0}" -gt 0 ] 2>/dev/null                         || fail "chroma_db is empty or unreadable (count=${COUNT:-0})"
    ok "llvm-project is in run state (index count: $COUNT)"
}

case "$MODE" in
    baseline) check_baseline ;;
    run)      check_run ;;
    "")       check_base; ok "basic health checks passed" ;;
    *)        echo "Usage: validate.sh [baseline|run]" >&2; exit 1 ;;
esac
```

- [ ] **Step 2: Make executable**

```bash
chmod +x eval/scripts/validate.sh
```

- [ ] **Step 3: Test — no mode (basic health)**

```bash
cd .worktrees/eval-framework
bash eval/scripts/validate.sh
```

Expected: `OK: basic health checks passed` (assuming `$LLVM_DIR` exists and is clean)

- [ ] **Step 4: Test — run mode against current llvm-project state**

```bash
bash eval/scripts/validate.sh run
```

Expected: `OK: llvm-project is in run state (index count: N)` where N > 0.
If the index doesn't exist yet, this will fail with a clear message — that's correct.

- [ ] **Step 5: Test — baseline mode fails correctly when not in baseline state**

```bash
bash eval/scripts/validate.sh baseline
echo "Exit code: $?"
```

Expected: prints `ERROR: .claude/CLAUDE.md exists — not in baseline state` and exits 1.

- [ ] **Step 6: Commit**

```bash
git add eval/scripts/validate.sh
git commit -m "feat: add validate.sh for llvm-project state checking"
```

---

### Task 3: Write `reset.sh`

**Files:**
- Create: `eval/scripts/reset.sh`

- [ ] **Step 1: Write `eval/scripts/reset.sh`**

Key implementation notes:
- `clear_session_state()` must `cd "$EVAL_DIR"` before the Python import — the `eval` package is rooted at `EVAL_DIR` and won't resolve from any other directory
- `CODE_SEARCH_LOCAL` is passed to `install.sh` as an environment variable (not a positional arg): `CODE_SEARCH_LOCAL="$CODE_SEARCH_LOCAL" bash install.sh`

```bash
#!/usr/bin/env bash
# reset.sh [baseline|run]
# Transitions llvm-project to the named state.
set -euo pipefail

EVAL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LLVM_DIR="${LLVM_DIR:-$HOME/code-search-sandbox/llvm-project}"
PYTHON="$EVAL_DIR/.venv/bin/python3"
CAPTURE_HOOK="$EVAL_DIR/eval/hooks/capture_session.py"
MODE="${1:-}"

fail() { echo "ERROR: $1" >&2; exit 1; }

clear_session_state() {
    cd "$EVAL_DIR" && "$PYTHON" -c "from eval.repo import clear_session_state; clear_session_state()"
    echo "Session state cleared."
}

case "$MODE" in
    baseline)
        [ ! -f "$LLVM_DIR/.claude/CLAUDE.md.bak" ] \
            || fail ".claude/CLAUDE.md.bak already exists — already in baseline state. Run validate.sh to check current state."
        [ -f "$LLVM_DIR/.claude/CLAUDE.md" ] \
            || fail ".claude/CLAUDE.md not found. Is llvm-project set up? Run setup.sh first."
        [ -f "$LLVM_DIR/.claude/settings.local.json" ] \
            || fail ".claude/settings.local.json not found. Run setup.sh first."

        echo "Transitioning to baseline state..."
        mv "$LLVM_DIR/.claude/CLAUDE.md" "$LLVM_DIR/.claude/CLAUDE.md.bak"
        mv "$LLVM_DIR/.claude/settings.local.json" "$LLVM_DIR/.claude/settings.local.json.bak"

        cat > "$LLVM_DIR/.claude/settings.local.json" <<EOF
{
  "hooks": {
    "UserPromptSubmit": [{"command": "$CAPTURE_HOOK prompt"}],
    "PostToolUse":      [{"command": "$CAPTURE_HOOK post"}],
    "Stop":             [{"command": "$CAPTURE_HOOK stop"}]
  }
}
EOF
        clear_session_state
        echo ""
        echo "Ready for baseline."
        echo "Next: bash eval/scripts/validate.sh baseline && bash eval/scripts/run-experiment.sh baseline"
        ;;

    run)
        [ ! -f "$LLVM_DIR/.claude/CLAUDE.md" ] \
            || fail ".claude/CLAUDE.md already exists — already in run state. Run validate.sh to check current state."
        [ -f "$LLVM_DIR/.claude/CLAUDE.md.bak" ] \
            || fail ".claude/CLAUDE.md.bak not found — not in baseline state. Run reset.sh baseline first."

        echo "Transitioning to run state..."
        mv "$LLVM_DIR/.claude/CLAUDE.md.bak" "$LLVM_DIR/.claude/CLAUDE.md"
        mv "$LLVM_DIR/.claude/settings.local.json.bak" "$LLVM_DIR/.claude/settings.local.json"

        echo "Re-indexing $LLVM_DIR..."
        (cd "$LLVM_DIR" && "$PYTHON" "$EVAL_DIR/index_project.py")
        echo "Re-index complete."

        clear_session_state
        echo ""
        echo "Ready for run."
        echo "Next: bash eval/scripts/validate.sh run && bash eval/scripts/run-experiment.sh run"
        ;;

    *)
        echo "Usage: reset.sh [baseline|run]" >&2
        exit 1
        ;;
esac
```

- [ ] **Step 2: Make executable**

```bash
chmod +x eval/scripts/reset.sh
```

- [ ] **Step 3: Test — reset to baseline**

```bash
cd .worktrees/eval-framework
bash eval/scripts/reset.sh baseline
```

Expected: prints "Transitioning to baseline state...", "Session state cleared.", "Ready for baseline."
Verify files moved: `.claude/CLAUDE.md.bak` exists, `.claude/CLAUDE.md` absent, `.claude/settings.local.json` is capture-only (no `index_project.py`).

```bash
bash eval/scripts/validate.sh baseline
```

Expected: `OK: llvm-project is in baseline state`

- [ ] **Step 4: Test — double-reset baseline fails cleanly**

```bash
bash eval/scripts/reset.sh baseline
echo "Exit: $?"
```

Expected: `ERROR: .claude/CLAUDE.md.bak already exists — already in baseline state.` and exit 1.

- [ ] **Step 5: Test — reset back to run**

```bash
bash eval/scripts/reset.sh run
```

Expected: transitions back, re-indexes, prints "Ready for run."

```bash
bash eval/scripts/validate.sh run
```

Expected: `OK: llvm-project is in run state (index count: N)`

- [ ] **Step 5b: Test — double-reset run fails cleanly**

```bash
bash eval/scripts/reset.sh run
echo "Exit: $?"
```

Expected: `ERROR: .claude/CLAUDE.md already exists — already in run state.` and exit 1.

- [ ] **Step 6: Commit**

```bash
git add eval/scripts/reset.sh
git commit -m "feat: add reset.sh for llvm-project state transitions"
```

---

## Chunk 3: `setup.sh`

### Task 4: Write `setup.sh`

**Files:**
- Create: `eval/scripts/setup.sh`

`setup.sh` is the one-time setup script. It is safe to re-run; the index will be rebuilt but nothing else changes.

- [ ] **Step 1: Write `eval/scripts/setup.sh`**

Key implementation notes:
- Use `$EVAL_DIR/.venv/bin/python3` for the chromadb count check — not bare `python3`
- Pass `CODE_SEARCH_LOCAL` as an environment variable to `install.sh` (e.g., `CODE_SEARCH_LOCAL="$CODE_SEARCH_LOCAL" bash install.sh`), not as a positional argument

```bash
#!/usr/bin/env bash
# setup.sh
# One-time setup: verify llvm-project, run install.sh, initial index.
# Safe to re-run — index rebuild is the only side effect.
set -euo pipefail

EVAL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LLVM_DIR="${LLVM_DIR:-$HOME/code-search-sandbox/llvm-project}"
PYTHON="$EVAL_DIR/.venv/bin/python3"

fail() { echo "ERROR: $1" >&2; exit 1; }

echo "=== claude-code-search eval setup ==="
echo "EVAL_DIR: $EVAL_DIR"
echo "LLVM_DIR: $LLVM_DIR"
echo ""

# 1. Verify LLVM_DIR
[ -d "$LLVM_DIR" ]                                          || fail "LLVM_DIR not found: $LLVM_DIR. Clone llvm-project first."
git -C "$LLVM_DIR" rev-parse --git-dir >/dev/null 2>&1     || fail "$LLVM_DIR is not a git repo"
echo "✓ llvm-project found"

# 2. Verify gh
command -v gh >/dev/null 2>&1                              || fail "'gh' CLI not found. Install from https://cli.github.com/"
gh auth status >/dev/null 2>&1                             || fail "'gh' is not authenticated. Run: gh auth login"
echo "✓ gh CLI authenticated"

# 3. Verify venv
[ -x "$PYTHON" ]                                           || fail "Python venv not found at $EVAL_DIR/.venv. Run: cd $EVAL_DIR && python3 -m venv .venv && .venv/bin/pip install -e ."
echo "✓ Python venv found"

# 4. Run install.sh
echo ""
echo "Installing claude-code-search into $LLVM_DIR..."
if [ -n "${CODE_SEARCH_LOCAL:-}" ]; then
    echo "  Using local scripts from: $CODE_SEARCH_LOCAL"
    (cd "$LLVM_DIR" && CODE_SEARCH_LOCAL="$CODE_SEARCH_LOCAL" bash "$EVAL_DIR/install.sh")
else
    (cd "$LLVM_DIR" && bash "$EVAL_DIR/install.sh")
fi
echo "✓ install.sh complete"

# 5. Build index
echo ""
echo "Indexing $LLVM_DIR (this may take several minutes for llvm-project)..."
(cd "$LLVM_DIR" && "$PYTHON" "$EVAL_DIR/index_project.py")
echo "✓ Indexing complete"

# 6. Verify index is non-empty
echo ""
echo "Verifying index..."
COUNT="$("$PYTHON" -c "
import chromadb
c = chromadb.PersistentClient(path='$LLVM_DIR/chroma_db')
print(c.get_collection('project_code').count())
" 2>/dev/null || echo 0)"
[ "${COUNT:-0}" -gt 0 ]                                    || fail "Index appears empty after setup (count=${COUNT:-0}). Check index_project.py output above."
echo "✓ Index non-empty (count: $COUNT)"

echo ""
echo "=== Setup complete ==="
echo "llvm-project is in run state."
echo "Next: bash eval/scripts/validate.sh run"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x eval/scripts/setup.sh
```

- [ ] **Step 3: Verify script is syntactically valid**

```bash
bash -n eval/scripts/setup.sh
```

Expected: no output (no syntax errors).

- [ ] **Step 4: Dry-run test — missing LLVM_DIR**

```bash
LLVM_DIR=/nonexistent bash eval/scripts/setup.sh
echo "Exit: $?"
```

Expected: `ERROR: LLVM_DIR not found: /nonexistent.` and exit 1.

- [ ] **Step 4b: Dry-run test — unauthenticated gh**

```bash
# Temporarily test by passing a fake GH_TOKEN or checking output
# If gh is authenticated, this verifies the auth check runs
gh auth status
```

Expected: `gh` is authenticated. If it is not, running `setup.sh` should print `ERROR: 'gh' is not authenticated. Run: gh auth login` and exit 1. Confirm this by reading the auth check in the script (`gh auth status >/dev/null 2>&1 || fail ...`).

- [ ] **Step 5: Commit**

```bash
git add eval/scripts/setup.sh
git commit -m "feat: add setup.sh for one-time llvm-project installation"
```

---

## Chunk 4: `run-experiment.sh`

### Task 5: Write `run-experiment.sh`

**Files:**
- Create: `eval/scripts/run-experiment.sh`

- [ ] **Step 1: Write `eval/scripts/run-experiment.sh`**

```bash
#!/usr/bin/env bash
# run-experiment.sh [baseline|run]
# Guided runner for macOS. Walks through every prompt one at a time,
# copying each to the clipboard, then analyzes the session.
#
# WARNING: Re-running this script clears all session state.
# Do not re-run mid-session.
set -euo pipefail

EVAL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LLVM_DIR="${LLVM_DIR:-$HOME/code-search-sandbox/llvm-project}"
PYTHON="$EVAL_DIR/.venv/bin/python3"
LAST_BASELINE_FILE="$EVAL_DIR/.eval_last_baseline"
MODE="${1:-}"

fail() { echo "ERROR: $1" >&2; exit 1; }

# Validate argument
[[ "$MODE" == "baseline" || "$MODE" == "run" ]] \
    || { echo "Usage: run-experiment.sh [baseline|run]" >&2; exit 1; }

echo "=== claude-code-search eval: $MODE session ==="
echo "WARNING: Re-running this script clears all session state."
echo ""

# Step 2: Validate state
echo "Validating state..."
bash "$(dirname "$0")/validate.sh" "$MODE" \
    || fail "State validation failed. Run 'bash eval/scripts/reset.sh $MODE' first."
echo ""

# Step 3: Clear session state
cd "$EVAL_DIR" && "$PYTHON" -c "from eval.repo import clear_session_state; clear_session_state()"
echo "Session state cleared. Starting prompt walk."
echo ""
echo "Open Claude Code in: $LLVM_DIR"
echo "-----------------------------------------------"
echo ""

# Step 4: Walk prompts one at a time
while true; do
    TASK_OUTPUT="$(cd "$EVAL_DIR" && "$PYTHON" eval/eval.py next-task 2>&1)"

    # Termination check
    if echo "$TASK_OUTPUT" | grep -q "All tasks complete"; then
        echo "All tasks complete."
        echo ""
        break
    fi

    TASK_NUM="$(echo "$TASK_OUTPUT" | grep "^Task [0-9]" | head -1)"
    TASK_ID="$(echo "$TASK_OUTPUT"  | grep "^Task ID:" | sed 's/^Task ID: //')"
    PROMPT="$( echo "$TASK_OUTPUT"  | grep "^Prompt:  " | sed 's/^Prompt:  //')"

    echo "--- $TASK_NUM ---"
    echo "ID: $TASK_ID"
    echo ""

    # Copy prompt to clipboard
    printf '%s' "$PROMPT" | pbcopy
    echo "Prompt (copied to clipboard):"
    echo "  $PROMPT"
    echo ""
    echo "Paste into Claude Code at $LLVM_DIR and run it."
    printf "Press Enter when the session is complete... "
    read -r
    echo ""
done

# Step 5: Analyze session
echo "Analyzing session..."
ANALYZE_OUTPUT="$(cd "$EVAL_DIR" && "$PYTHON" eval/eval.py analyze "$MODE" 2>&1)"
echo "$ANALYZE_OUTPUT"

REPORT_PATH="$(echo "$ANALYZE_OUTPUT" | grep "Report saved to" | sed 's/^Report saved to //')"

# Step 6: Save baseline path for later use by report.sh
if [ "$MODE" = "baseline" ]; then
    printf '%s' "$REPORT_PATH" > "$LAST_BASELINE_FILE"
    echo ""
    echo "=== Baseline complete ==="
    echo "Report: $REPORT_PATH"
    echo ""
    echo "Next steps:"
    echo "  1. bash eval/scripts/reset.sh run"
    echo "  2. bash eval/scripts/validate.sh run"
    echo "  3. bash eval/scripts/run-experiment.sh run"
else
    echo ""
    echo "=== Run complete ==="
    echo "Report: $REPORT_PATH"
    echo ""
    if [ -f "$LAST_BASELINE_FILE" ]; then
        BASELINE_PATH="$(cat "$LAST_BASELINE_FILE")"
        echo "Next step:"
        echo "  bash eval/scripts/report.sh \"$BASELINE_PATH\" \"$REPORT_PATH\""
    else
        echo "Next step:"
        echo "  bash eval/scripts/report.sh <baseline-report.json> \"$REPORT_PATH\""
        echo "  (No .eval_last_baseline found — supply the baseline path manually)"
    fi
fi
```

- [ ] **Step 2: Make executable**

```bash
chmod +x eval/scripts/run-experiment.sh
```

- [ ] **Step 3: Test — missing argument**

```bash
bash eval/scripts/run-experiment.sh
echo "Exit: $?"
```

Expected: `Usage: run-experiment.sh [baseline|run]` and exit 1.

- [ ] **Step 4: Test — validate failure is caught cleanly**

Make sure llvm-project is in run state, then test that baseline mode fails before touching session state:

```bash
bash eval/scripts/validate.sh run   # confirm run state
bash eval/scripts/run-experiment.sh baseline
echo "Exit: $?"
```

Expected: `ERROR: State validation failed. Run 'bash eval/scripts/reset.sh baseline' first.` and exit 1. Session state files should be untouched.

- [ ] **Step 5: Syntax check**

```bash
bash -n eval/scripts/run-experiment.sh
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add eval/scripts/run-experiment.sh
git commit -m "feat: add run-experiment.sh guided prompt runner with clipboard copy"
```

---

## Chunk 5: `report.sh`

### Task 6: Write `report.sh`

**Files:**
- Create: `eval/scripts/report.sh`

- [ ] **Step 1: Write `eval/scripts/report.sh`**

```bash
#!/usr/bin/env bash
# report.sh <baseline.json> <run.json>
# Compares two eval reports and creates a GitHub issue with the results.
set -euo pipefail

EVAL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$EVAL_DIR/.venv/bin/python3"
GH_REPO="${GH_REPO:-jjveleber/claude-code-search}"

BASELINE_JSON="${1:-}"
RUN_JSON="${2:-}"

fail() { echo "ERROR: $1" >&2; exit 1; }

# Validate args
[ -n "$BASELINE_JSON" ] && [ -n "$RUN_JSON" ] \
    || { echo "Usage: report.sh <baseline.json> <run.json>" >&2; exit 1; }
[ -f "$BASELINE_JSON" ] || fail "Baseline report not found: $BASELINE_JSON"
[ -f "$RUN_JSON" ]      || fail "Run report not found: $RUN_JSON"

# Validate gh
command -v gh >/dev/null 2>&1  || fail "'gh' CLI not found. Install from https://cli.github.com/"
gh auth status >/dev/null 2>&1 || fail "'gh' is not authenticated. Run: gh auth login"

# Validate modes
BASELINE_MODE="$("$PYTHON" -c "import json; print(json.load(open('$BASELINE_JSON')).get('mode',''))" 2>/dev/null)"
RUN_MODE="$(     "$PYTHON" -c "import json; print(json.load(open('$RUN_JSON')).get('mode',''))"      2>/dev/null)"
[ "$BASELINE_MODE" = "baseline" ] || fail "First file must have mode=baseline, got: $BASELINE_MODE"
[ "$RUN_MODE"      = "run"      ] || fail "Second file must have mode=run, got: $RUN_MODE"

# Run compare
echo "Comparing reports..."
COMPARE_OUTPUT="$(cd "$EVAL_DIR" && "$PYTHON" eval/eval.py compare "$BASELINE_JSON" "$RUN_JSON" 2>&1)"
echo "$COMPARE_OUTPUT"
echo ""

# Extract metadata via Python (handles missing keys gracefully)
extract() {
    "$PYTHON" -c "import json; d=json.load(open('$1')); print($2)" 2>/dev/null || echo "unknown"
}

BASELINE_TS="$(    extract "$BASELINE_JSON" "d.get('timestamp','unknown')")"
BASELINE_COMMIT="$(extract "$BASELINE_JSON" "d.get('git',{}).get('commit','unknown')")"
BASELINE_BRANCH="$(extract "$BASELINE_JSON" "d.get('git',{}).get('branch','unknown')")"

RUN_TS="$(    extract "$RUN_JSON" "d.get('timestamp','unknown')")"
RUN_COMMIT="$(extract "$RUN_JSON" "d.get('git',{}).get('commit','unknown')")"
RUN_BRANCH="$(extract "$RUN_JSON" "d.get('git',{}).get('branch','unknown')")"

SHORT_COMMIT="${RUN_COMMIT:0:8}"
ISSUE_TITLE="Eval results: baseline vs run — ${RUN_BRANCH} @ ${SHORT_COMMIT}"

ISSUE_BODY="$(cat <<EOF
## Comparison

\`\`\`
${COMPARE_OUTPUT}
\`\`\`

## Metadata

| | Baseline | Run |
|---|---|---|
| Timestamp | ${BASELINE_TS} | ${RUN_TS} |
| Commit | ${BASELINE_COMMIT} | ${RUN_COMMIT} |
| Branch | ${BASELINE_BRANCH} | ${RUN_BRANCH} |

**Machine:** $(hostname)
**Date:** $(date)
EOF
)"

echo "Creating GitHub issue on $GH_REPO..."
ISSUE_URL="$(gh issue create --repo "$GH_REPO" --title "$ISSUE_TITLE" --body "$ISSUE_BODY")"
echo ""
echo "Issue created: $ISSUE_URL"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x eval/scripts/report.sh
```

- [ ] **Step 3: Test — missing arguments**

```bash
bash eval/scripts/report.sh
echo "Exit: $?"
```

Expected: `Usage: report.sh <baseline.json> <run.json>` and exit 1.

- [ ] **Step 4: Test — wrong mode files**

```bash
# Pass the same file twice (both would be same mode)
SOME_REPORT="$(ls eval/results/*.json 2>/dev/null | head -1)"
if [ -n "$SOME_REPORT" ]; then
    bash eval/scripts/report.sh "$SOME_REPORT" "$SOME_REPORT"
    echo "Exit: $?"
fi
```

Expected: `ERROR: First file must have mode=baseline, got: ...` or similar mode mismatch error.

- [ ] **Step 5: Syntax check**

```bash
bash -n eval/scripts/report.sh
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add eval/scripts/report.sh
git commit -m "feat: add report.sh to compare reports and create GitHub issue"
```

---

## Chunk 6: Final wiring + smoke test

### Task 7: Push and update working document

- [ ] **Step 1: Verify all scripts are present and executable**

```bash
ls -la eval/scripts/
```

Expected: all five scripts present with execute bit set.

- [ ] **Step 2: Syntax-check all scripts at once**

```bash
for f in eval/scripts/*.sh; do
    bash -n "$f" && echo "OK: $f" || echo "FAIL: $f"
done
```

Expected: `OK: eval/scripts/report.sh` etc. for all five.

- [ ] **Step 3: Verify end-to-end state round-trip**

```bash
bash eval/scripts/validate.sh run       # confirm starting in run state
bash eval/scripts/reset.sh baseline     # transition to baseline
bash eval/scripts/validate.sh baseline  # confirm
bash eval/scripts/reset.sh run          # transition back (re-indexes)
bash eval/scripts/validate.sh run       # confirm back in run state
```

Expected: each validate prints `OK: ...` with no errors.

- [ ] **Step 4: Smoke test run-experiment.sh with 1-entry benchmark**

Create a minimal benchmark file:

```bash
cat > /tmp/test-benchmark.json <<'EOF'
[
  {
    "id": "smoke-001",
    "prompt": "Find the main function in any LLVM tool.",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Smoke test prompt"
  }
]
EOF
```

Reset to baseline (capture-only hooks), then run with the test benchmark:

```bash
bash eval/scripts/reset.sh baseline
bash eval/scripts/run-experiment.sh baseline
# When the prompt appears and is copied to clipboard, press Enter without running Claude Code.
# This tests: clipboard copy, prompt display, loop termination, analyze call, .eval_last_baseline creation.
```

Expected:
- `smoke-001` prompt text appears and is copied to clipboard (verify with `pbpaste`)
- After pressing Enter, "All tasks complete." is printed
- `eval.py analyze baseline` runs; report saved to `eval/results/`
- `.eval_last_baseline` file created with the report path
- "Next steps" printed pointing to `reset.sh run`

```bash
cat .eval_last_baseline       # should contain a path to a .json file
ls eval/results/*.json        # should contain a new baseline report
```

Reset back to run state afterward:
```bash
bash eval/scripts/reset.sh run
```

- [ ] **Step 5: Smoke test report.sh with paired JSON files**

After step 4, you have a baseline report. Create a minimal run report to pair it with:

```bash
BASELINE_JSON="$(cat .eval_last_baseline)"
# Create a fake run report by copying the baseline and changing the mode field
python3 -c "
import json, sys
d = json.load(open('$BASELINE_JSON'))
d['mode'] = 'run'
import time; d['timestamp'] = time.strftime('%Y-%m-%dT%H:%M:%S')
fname = '$BASELINE_JSON'.replace('baseline','run-smoke')
json.dump(d, open(fname, 'w'), indent=2)
print(fname)
" > /tmp/run_report_path.txt
RUN_JSON="$(cat /tmp/run_report_path.txt)"
```

Run report.sh in dry-run mode (no actual issue creation) by temporarily overriding GH_REPO to confirm the script reaches the `gh issue create` step:

```bash
GH_REPO=jjveleber/claude-code-search bash eval/scripts/report.sh "$BASELINE_JSON" "$RUN_JSON"
```

Expected: comparison output printed, issue created, URL printed. Verify the issue appears at https://github.com/jjveleber/claude-code-search/issues.

Clean up the fake run report:
```bash
rm "$RUN_JSON"
```

- [ ] **Step 6: Update working document with final status**

Edit `docs/eval-experiments-working-doc.md` — change the "Open Questions" section to mark both questions as resolved:

```markdown
## Open Questions (decide before implementing)

- [x] Use all 18 prompts (2 per type) — **decided: all 18**
- [x] Replace the existing 3 prompts in `llvm.json` or fold them in? — **decided: replaced**
```

- [ ] **Step 7: Push everything**

```bash
git push
```

Expected: branch pushed to remote, PR #16 updated.
