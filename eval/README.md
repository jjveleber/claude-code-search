# Eval Framework

Two-layer evaluation for `claude-code-search`.

## Quick Start

### Unit eval (no Claude needed)
Tests search quality against known expected files.

```bash
# First run unit eval to see baseline search quality
source .venv/bin/activate
python eval/eval.py unit
```

Results are saved to `eval/results/`. Add expected files to `eval/benchmarks/llvm.json` via `eval.py promote` (see Integration workflow below).

---

### Integration eval (requires Claude Code sessions)

Measures how search affects Claude's navigation behavior by comparing two sessions.

**Step 1: Run the baseline (no search)**
```bash
python eval/eval.py prepare baseline
# Follow the task prompts printed above — run each in Claude Code
# For each task, first run:
python eval/eval.py next-task
# Then paste the printed prompt into Claude Code and let it complete
# When all tasks are done:
python eval/eval.py analyze baseline
```

**Step 2: Run with search enabled**
```bash
python eval/eval.py prepare run
# Repeat the same prompts using next-task
python eval/eval.py analyze run
```

**Step 3: Compare**
```bash
python eval/eval.py compare eval/results/<baseline>.json eval/results/<run>.json
```

**Step 4: Promote baseline results to unit benchmark**
```bash
python eval/eval.py promote eval/results/<baseline>.json
```

---

## CLI Reference

| Command | Description |
|---|---|
| `eval.py unit [--top N] [--benchmark FILE]` | Run unit eval |
| `eval.py prepare <baseline\|run\|restore>` | Reset repo, re-index, configure hooks |
| `eval.py next-task [--benchmark FILE]` | Print next task prompt, register task ID |
| `eval.py analyze <baseline\|run>` | Parse session log, write report |
| `eval.py promote <report.json>` | Populate expected_files from baseline report |
| `eval.py compare <a.json> <b.json>` | Diff two reports |
| `eval.py results` | List saved reports |

---

## Adding Benchmark Entries

Edit `eval/benchmarks/llvm.json`. Add entries with `id`, `prompt`, and `notes`. Leave `expected_files` empty — they will be populated automatically after the first baseline session via `eval.py promote`.

## How Results Are Stored

Reports are saved as timestamped JSON files in `eval/results/` (gitignored). The `git` block in each report records the commit, branch, and dirty state so you can trace what code produced each result.
