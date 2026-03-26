# Eval Framework Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-layer evaluation framework that measures whether claude-code-search improves Claude's navigation efficiency and reduces token usage, with no Claude API spend.

**Architecture:** A standalone `eval/` directory houses a CLI (`eval.py`) that drives two layers: a unit layer that scores `search_code.py` results against known expected files, and an integration layer that analyzes captured Claude Code session logs comparing baseline (no search) vs run (with search). Both layers share a JSON report format annotated with git metadata for traceability.

**Tech Stack:** Python 3.9+, pytest, subprocess (calls `search_code.py`), json, argparse, existing `.venv`

---

## File Map

| File | Role |
|---|---|
| `eval/eval.py` | CLI entry point — arg parsing and command dispatch |
| `eval/report.py` | Report read/write, git metadata capture, results listing |
| `eval/unit.py` | Unit eval runner — calls `search_code.py`, scores results |
| `eval/repo.py` | Git ops — dirty check, reset, re-index, hook configuration |
| `eval/session.py` | Session log parsing and integration metric computation |
| `eval/hooks/capture_session.py` | PostToolUse + UserPromptSubmit + Stop hooks |
| `eval/benchmarks/llvm.json` | Benchmark dataset (committed, initially empty tasks list) |
| `eval/README.md` | How to run, how to add benchmark entries |
| `tests/eval/test_report.py` | Report format and git metadata tests |
| `tests/eval/test_unit.py` | Unit scorer and runner tests |
| `tests/eval/test_session.py` | Session log parser and metric computation tests |

---

## Chunk 1: Foundation — Report Format and Benchmark

### Task 1: Benchmark dataset and results directory

**Files:**
- Create: `eval/benchmarks/llvm.json`
- Create: `eval/results/.gitkeep`

- [ ] **Step 1: Create the benchmarks directory and initial dataset**

```json
[
  {
    "id": "llvm-001",
    "prompt": "Find where SelectionDAG handles vector shuffle lowering and explain the approach",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Tests concept-level navigation in CodeGen"
  },
  {
    "id": "llvm-002",
    "prompt": "Find the inliner cost model and how it decides whether to inline a function",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Tests cost model navigation"
  },
  {
    "id": "llvm-003",
    "prompt": "Find where register allocation spilling is handled",
    "expected_files": [],
    "acceptable_files": [],
    "notes": "Tests register allocation navigation"
  }
]
```

Save to `eval/benchmarks/llvm.json`.

- [ ] **Step 2: Create results directory with gitkeep**

```bash
mkdir -p eval/results
touch eval/results/.gitkeep
```

- [ ] **Step 3: Update .gitignore**

Add to `.gitignore`:
```
eval/results/*.json
eval/results/*.log
.eval_current_task
.eval_task_index
.eval_session_log
```

Do NOT ignore `eval/results/.gitkeep`.

- [ ] **Step 4: Commit**

```bash
git add eval/benchmarks/llvm.json eval/results/.gitkeep .gitignore
git commit -m "feat: add eval benchmark dataset and results directory"
```

---

### Task 2: Report module

**Files:**
- Create: `eval/__init__.py`
- Create: `eval/report.py`
- Create: `tests/eval/__init__.py`
- Create: `tests/eval/test_report.py`

- [ ] **Step 1: Write failing tests**

Create `tests/eval/__init__.py` (empty).

Create `tests/eval/test_report.py`:

```python
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eval.report import write_report, read_report, list_reports, capture_git_metadata


def test_capture_git_metadata_returns_required_fields():
    meta = capture_git_metadata()
    assert "commit" in meta
    assert "message" in meta
    assert "branch" in meta
    assert "dirty" in meta
    assert isinstance(meta["dirty"], bool)


def test_write_and_read_report_roundtrip():
    report = {
        "timestamp": "2026-03-25T14:30:00",
        "mode": "unit",
        "git": {"commit": "abc123", "message": "test", "branch": "main", "dirty": False},
        "config": {"chunk_size": 60, "overlap": 10, "top": 5},
        "tasks": [],
        "summary": {}
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = write_report(report, results_dir=tmpdir)
        loaded = read_report(path)
    assert loaded["mode"] == "unit"
    assert loaded["git"]["commit"] == "abc123"


def test_write_report_filename_includes_timestamp():
    report = {
        "timestamp": "2026-03-25T14:30:00",
        "mode": "unit",
        "git": {}, "config": {}, "tasks": [], "summary": {}
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = write_report(report, results_dir=tmpdir)
        assert "2026-03-25" in Path(path).name


def test_list_reports_returns_sorted_by_time():
    report_a = {"timestamp": "2026-03-25T10:00:00", "mode": "unit",
                "git": {}, "config": {}, "tasks": [], "summary": {}}
    report_b = {"timestamp": "2026-03-25T12:00:00", "mode": "baseline",
                "git": {}, "config": {}, "tasks": [], "summary": {}}
    with tempfile.TemporaryDirectory() as tmpdir:
        write_report(report_a, results_dir=tmpdir)
        write_report(report_b, results_dir=tmpdir)
        reports = list_reports(results_dir=tmpdir)
    assert len(reports) == 2
    assert reports[0]["timestamp"] < reports[1]["timestamp"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/c/Users/jjvel/PycharmProjects/PythonProject/github/claude-code-search
source .venv/bin/activate && python -m pytest tests/eval/test_report.py -v 2>&1 | head -30
```

Expected: ImportError or ModuleNotFoundError for `eval.report`.

- [ ] **Step 3: Implement report.py**

Create `eval/__init__.py` (empty).

Create `eval/report.py`:

```python
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def capture_git_metadata():
    """Capture current git state for traceability."""
    def _run(cmd):
        try:
            return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        except subprocess.CalledProcessError:
            return ""

    commit = _run(["git", "rev-parse", "--short", "HEAD"])
    message = _run(["git", "log", "-1", "--pretty=%s"])
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    dirty_output = _run(["git", "status", "--porcelain"])
    dirty = bool(dirty_output)

    return {
        "commit": commit,
        "message": message,
        "branch": branch,
        "dirty": dirty,
    }


def write_report(report, results_dir=None):
    """Write a report to a timestamped JSON file. Returns the file path."""
    if results_dir is None:
        results_dir = RESULTS_DIR
    os.makedirs(results_dir, exist_ok=True)

    ts = report.get("timestamp", datetime.now().isoformat(timespec="seconds"))
    safe_ts = ts.replace(":", "-")
    mode = report.get("mode", "unknown")
    filename = f"{safe_ts}-{mode}.json"
    path = os.path.join(results_dir, filename)

    with open(path, "w") as f:
        json.dump(report, f, indent=2)

    return path


def read_report(path):
    """Load a report from a JSON file."""
    with open(path) as f:
        return json.load(f)


def list_reports(results_dir=None):
    """Return all reports sorted by timestamp ascending."""
    if results_dir is None:
        results_dir = RESULTS_DIR
    reports = []
    for p in Path(results_dir).glob("*.json"):
        try:
            report = read_report(str(p))
            report["_path"] = str(p)
            reports.append(report)
        except (json.JSONDecodeError, KeyError):
            continue
    return sorted(reports, key=lambda r: r.get("timestamp", ""))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && python -m pytest tests/eval/test_report.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add eval/__init__.py eval/report.py tests/eval/__init__.py tests/eval/test_report.py
git commit -m "feat: add report read/write module with git metadata"
```

---

## Chunk 2: Unit Eval Layer

### Task 3: Unit scorer

**Files:**
- Create: `eval/unit.py`
- Create: `tests/eval/test_unit.py`

- [ ] **Step 1: Write failing tests**

Create `tests/eval/test_unit.py`:

```python
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eval.unit import parse_search_output, score_entry, aggregate_unit_metrics


def test_parse_search_output_extracts_paths():
    output = (
        "MATCH 1: llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp (lines 120-180)\n"
        "----------------------------------------\n"
        "some code\n\n"
        "MATCH 2: llvm/lib/Target/X86/X86ISelLowering.cpp (lines 3200-3260)\n"
        "----------------------------------------\n"
        "more code\n\n"
    )
    paths = parse_search_output(output)
    assert paths == [
        "llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp",
        "llvm/lib/Target/X86/X86ISelLowering.cpp",
    ]


def test_parse_search_output_empty():
    assert parse_search_output("No results found.\n") == []
    assert parse_search_output("") == []


def test_score_entry_hit_at_rank_1():
    result = score_entry(
        results=["llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp", "other.cpp"],
        expected=["llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp"],
        acceptable=[],
        k=5,
    )
    assert result["hit"] is True
    assert result["recall_at_k"] == 1.0
    assert result["reciprocal_rank"] == 1.0
    assert result["precision_at_k"] == pytest.approx(1.0 / 5)


def test_score_entry_miss():
    result = score_entry(
        results=["other.cpp", "another.cpp"],
        expected=["llvm/lib/CodeGen/SelectionDAG/LegalizeVectorOps.cpp"],
        acceptable=[],
        k=5,
    )
    assert result["hit"] is False
    assert result["recall_at_k"] == 0.0
    assert result["reciprocal_rank"] == 0.0
    assert result["precision_at_k"] == 0.0


def test_score_entry_acceptable_partial_credit():
    result = score_entry(
        results=["acceptable.cpp"],
        expected=["expected.cpp"],
        acceptable=["acceptable.cpp"],
        k=5,
    )
    assert result["hit"] is False
    assert result["precision_at_k"] == pytest.approx(0.5 / 5)


def test_score_entry_hit_at_rank_3():
    result = score_entry(
        results=["a.cpp", "b.cpp", "llvm/target.cpp"],
        expected=["llvm/target.cpp"],
        acceptable=[],
        k=5,
    )
    assert result["hit"] is True
    assert result["reciprocal_rank"] == pytest.approx(1.0 / 3)


def test_aggregate_unit_metrics():
    task_results = [
        {"hit": True, "recall_at_k": 1.0, "reciprocal_rank": 1.0, "precision_at_k": 0.2},
        {"hit": False, "recall_at_k": 0.0, "reciprocal_rank": 0.0, "precision_at_k": 0.0},
    ]
    summary = aggregate_unit_metrics(task_results)
    assert summary["hit_rate"] == pytest.approx(0.5)
    assert summary["recall_at_k"] == pytest.approx(0.5)
    assert summary["MRR"] == pytest.approx(0.5)
    assert summary["precision_at_k"] == pytest.approx(0.1)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/eval/test_unit.py -v 2>&1 | head -20
```

Expected: ImportError for `eval.unit`.

- [ ] **Step 3: Implement unit.py**

Create `eval/unit.py`:

```python
import re
import subprocess
import sys
import os
import json
from datetime import datetime

from eval.report import capture_git_metadata, write_report

SEARCH_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "search_code.py")
BENCHMARK_DIR = os.path.join(os.path.dirname(__file__), "benchmarks")
PYTHON = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".venv", "bin", "python3")

_MATCH_RE = re.compile(r"^MATCH \d+: (.+?) \(lines \d+-\d+\)")


def parse_search_output(output):
    """Extract ranked file paths from search_code.py stdout."""
    paths = []
    for line in output.splitlines():
        m = _MATCH_RE.match(line)
        if m:
            paths.append(m.group(1))
    return paths


def score_entry(results, expected, acceptable, k):
    """Score a single benchmark entry against search results."""
    top_k = results[:k]

    # Recall: did any expected file appear in top-k?
    hit = any(f in top_k for f in expected)
    recall_at_k = 1.0 if hit else 0.0

    # MRR: reciprocal rank of first expected hit
    reciprocal_rank = 0.0
    for rank, path in enumerate(top_k, 1):
        if path in expected:
            reciprocal_rank = 1.0 / rank
            break

    # Precision: (expected hits + 0.5 * acceptable hits) / k
    expected_hits = sum(1 for p in top_k if p in expected)
    acceptable_hits = sum(1 for p in top_k if p in acceptable and p not in expected)
    precision_at_k = (expected_hits + 0.5 * acceptable_hits) / k if k > 0 else 0.0

    return {
        "hit": hit,
        "recall_at_k": recall_at_k,
        "reciprocal_rank": reciprocal_rank,
        "precision_at_k": precision_at_k,
    }


def aggregate_unit_metrics(task_results):
    """Aggregate per-task scores into summary metrics."""
    n = len(task_results)
    if n == 0:
        return {"hit_rate": 0.0, "recall_at_k": 0.0, "MRR": 0.0, "precision_at_k": 0.0}
    return {
        "hit_rate": sum(r["hit"] for r in task_results) / n,
        "recall_at_k": sum(r["recall_at_k"] for r in task_results) / n,
        "MRR": sum(r["reciprocal_rank"] for r in task_results) / n,
        "precision_at_k": sum(r["precision_at_k"] for r in task_results) / n,
    }


def load_benchmark(benchmark_file):
    with open(benchmark_file) as f:
        return json.load(f)


def run_unit_eval(benchmark_file, top=5, config=None):
    """Run unit eval against all benchmark entries. Returns a report dict."""
    entries = load_benchmark(benchmark_file)
    if config is None:
        config = {}

    # Read chunk_size and overlap from index_project.py defaults if not provided
    full_config = {"chunk_size": 60, "overlap": 10, "top": top}
    full_config.update(config)

    task_results = []
    for entry in entries:
        expected = entry.get("expected_files", [])
        acceptable = entry.get("acceptable_files", [])

        if not expected:
            print(f"  [skip] {entry['id']} — no expected_files yet", file=sys.stderr)
            continue

        result = subprocess.run(
            [PYTHON, SEARCH_SCRIPT, entry["prompt"], "--top", str(top)],
            capture_output=True, text=True
        )

        if result.returncode == 1:
            print(f"Error: index not found. Run index_project.py first.", file=sys.stderr)
            sys.exit(1)

        paths = parse_search_output(result.stdout)
        scores = score_entry(paths, expected, acceptable, k=top)

        task_result = {
            "id": entry["id"],
            "query": entry["prompt"],
            "results": [{"rank": i + 1, "path": p} for i, p in enumerate(paths)],
            **scores,
        }
        task_results.append(task_result)
        status = "✓" if scores["hit"] else "✗"
        print(f"  {status} {entry['id']}  MRR={scores['reciprocal_rank']:.2f}")

    summary = aggregate_unit_metrics(task_results)

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": "unit",
        "git": capture_git_metadata(),
        "config": full_config,
        "tasks": task_results,
        "summary": summary,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && python -m pytest tests/eval/test_unit.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add eval/unit.py tests/eval/test_unit.py
git commit -m "feat: add unit eval scorer and runner"
```

---

### Task 4: eval.py unit subcommand

**Files:**
- Create: `eval/eval.py`

- [ ] **Step 1: Create the CLI entry point with unit subcommand**

Create `eval/eval.py`:

```python
#!/usr/bin/env python3
"""Eval CLI for claude-code-search."""
import argparse
import os
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(EVAL_DIR)
sys.path.insert(0, ROOT_DIR)

DEFAULT_BENCHMARK = os.path.join(EVAL_DIR, "benchmarks", "llvm.json")
RESULTS_DIR = os.path.join(EVAL_DIR, "results")


def cmd_unit(args):
    from eval.unit import run_unit_eval
    from eval.report import write_report
    benchmark = args.benchmark or DEFAULT_BENCHMARK
    print(f"Running unit eval against {benchmark} (--top {args.top})")
    report = run_unit_eval(benchmark, top=args.top)
    path = write_report(report, results_dir=RESULTS_DIR)
    s = report["summary"]
    print(f"\nResults saved to {path}")
    print(f"  hit_rate:     {s['hit_rate']:.2f}")
    print(f"  recall@k:     {s['recall_at_k']:.2f}")
    print(f"  MRR:          {s['MRR']:.2f}")
    print(f"  precision@k:  {s['precision_at_k']:.2f}")


def cmd_results(args):
    from eval.report import list_reports
    reports = list_reports(results_dir=RESULTS_DIR)
    if not reports:
        print("No reports found.")
        return
    print(f"{'Timestamp':<25} {'Mode':<10} {'Commit':<10} {'Branch':<15} Dirty")
    print("-" * 70)
    for r in reports:
        g = r.get("git", {})
        print(f"{r.get('timestamp','?'):<25} {r.get('mode','?'):<10} "
              f"{g.get('commit','?'):<10} {g.get('branch','?'):<15} "
              f"{'yes' if g.get('dirty') else 'no'}")


def main():
    parser = argparse.ArgumentParser(description="claude-code-search eval framework")
    sub = parser.add_subparsers(dest="command", required=True)

    # unit
    p_unit = sub.add_parser("unit", help="Run unit eval (no Claude needed)")
    p_unit.add_argument("--top", type=int, default=5, help="Top-N results to score (default: 5)")
    p_unit.add_argument("--benchmark", help="Path to benchmark JSON (default: benchmarks/llvm.json)")
    p_unit.set_defaults(func=cmd_unit)

    # results
    p_results = sub.add_parser("results", help="List saved reports")
    p_results.set_defaults(func=cmd_results)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x eval/eval.py
```

- [ ] **Step 3: Smoke test**

```bash
source .venv/bin/activate && python eval/eval.py results
```

Expected: "No reports found." (results dir is empty).

- [ ] **Step 4: Commit**

```bash
git add eval/eval.py
git commit -m "feat: add eval CLI with unit and results subcommands"
```

---

## Chunk 3: Repo Operations and Prepare Command

### Task 5: Repo operations module

**Files:**
- Create: `eval/repo.py`

The `repo.py` module handles dirty checking, resetting the repo, re-indexing, and toggling hook configuration in `.claude/settings.local.json`.

- [ ] **Step 1: Implement repo.py**

Create `eval/repo.py`:

```python
import json
import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(ROOT_DIR, ".claude", "settings.local.json")
INDEX_SCRIPT = os.path.join(ROOT_DIR, "index_project.py")
CAPTURE_HOOK = os.path.join(ROOT_DIR, "eval", "hooks", "capture_session.py")
PRODUCTION_WATCHER = os.path.join(ROOT_DIR, "watch_index.py")
PYTHON = os.path.join(ROOT_DIR, ".venv", "bin", "python3")


def is_dirty():
    """Return True if the repo has uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=ROOT_DIR
    )
    return bool(result.stdout.strip())


def reset_repo():
    """Restore tracked files and remove untracked files (excluding eval/)."""
    subprocess.run(["git", "checkout", "."], cwd=ROOT_DIR, check=True)
    subprocess.run(
        ["git", "clean", "-fd", "--exclude=eval/"],
        cwd=ROOT_DIR, check=True
    )


def run_reindex():
    """Run incremental re-index."""
    print("Re-indexing...")
    subprocess.run([PYTHON, INDEX_SCRIPT], cwd=ROOT_DIR, check=True)
    print("Re-index complete.")


def _load_settings():
    if not os.path.exists(SETTINGS_PATH):
        return {}
    with open(SETTINGS_PATH) as f:
        return json.load(f)


def _save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def configure_hooks(mode):
    """
    mode='baseline': disable search hook, enable capture hook only
    mode='run': enable search hook + capture hook
    mode='restore': restore original production hooks, remove capture hook
    """
    settings = _load_settings()
    hooks = settings.setdefault("hooks", {})

    # Base UserPromptSubmit hook: starts watcher + indexer (production)
    production_prompt_cmd = (
        f"{PYTHON} {INDEX_SCRIPT} & {PYTHON} {PRODUCTION_WATCHER} &"
    )
    # Capture hook command (appended to UserPromptSubmit)
    capture_prompt_cmd = f"{PYTHON} {CAPTURE_HOOK} prompt"
    capture_post_cmd = f"{PYTHON} {CAPTURE_HOOK} post"
    capture_stop_cmd = f"{PYTHON} {CAPTURE_HOOK} stop"

    if mode == "restore":
        hooks["UserPromptSubmit"] = [{"command": production_prompt_cmd}]
        hooks.pop("PostToolUse", None)
        hooks.pop("Stop", None)
    elif mode == "baseline":
        # No search hook, capture only
        hooks["UserPromptSubmit"] = [
            {"command": capture_prompt_cmd},
        ]
        hooks["PostToolUse"] = [{"command": capture_post_cmd}]
        hooks["Stop"] = [{"command": capture_stop_cmd}]
    elif mode == "run":
        # Search hook + capture
        hooks["UserPromptSubmit"] = [
            {"command": production_prompt_cmd},
            {"command": capture_prompt_cmd},
        ]
        hooks["PostToolUse"] = [{"command": capture_post_cmd}]
        hooks["Stop"] = [{"command": capture_stop_cmd}]
    else:
        raise ValueError(f"Unknown mode: {mode}")

    _save_settings(settings)
    print(f"Hooks configured for mode: {mode}")


def clear_session_state():
    """Delete old session logs, task index, and current task file to start fresh."""
    import glob
    results_dir = os.path.join(ROOT_DIR, "eval", "results")
    for f in glob.glob(os.path.join(results_dir, "session-*.log")):
        os.remove(f)
    for f in [os.path.join(ROOT_DIR, ".eval_current_task"),
              os.path.join(ROOT_DIR, ".eval_task_index"),
              os.path.join(ROOT_DIR, ".eval_session_log")]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass


def prepare(mode):
    """Full prepare sequence: dirty check, reset, re-index, configure hooks."""
    if is_dirty():
        print("Error: repo has uncommitted changes. Commit or stash before running eval.")
        sys.exit(1)

    print(f"Preparing for {mode} session...")
    clear_session_state()
    reset_repo()
    run_reindex()
    configure_hooks(mode)
    print(f"Ready. Run your task prompts in Claude Code, then: eval.py analyze {mode}")
```

- [ ] **Step 2: Smoke test dirty check**

```bash
source .venv/bin/activate && python -c "
import sys; sys.path.insert(0, '.')
from eval.repo import is_dirty
print('dirty:', is_dirty())
"
```

Expected: `dirty: False` (assuming clean repo).

- [ ] **Step 3: Commit**

```bash
git add eval/repo.py
git commit -m "feat: add repo operations module for eval prepare"
```

---

### Task 6: prepare and next-task subcommands

**Files:**
- Modify: `eval/eval.py`
- Create: `eval/hooks/__init__.py`

- [ ] **Step 1: Add prepare, next-task subcommands to eval.py**

Add after `cmd_results` in `eval/eval.py`:

```python
def cmd_prepare(args):
    from eval.repo import prepare
    prepare(args.mode)
    print(f"\nTask list for {args.mode} session:")
    _print_task_list(args.benchmark or DEFAULT_BENCHMARK)


def cmd_next_task(args):
    import json
    _print_task_list(args.benchmark or DEFAULT_BENCHMARK, interactive=True)


def _print_task_list(benchmark_file, interactive=False):
    import json
    # .eval_current_task lives in the project root, not relative to benchmark
    current_task_file = os.path.join(ROOT_DIR, ".eval_current_task")
    task_index_file = os.path.join(ROOT_DIR, ".eval_task_index")

    with open(benchmark_file) as f:
        entries = json.load(f)

    if not interactive:
        print("\nTasks to run (in order):")
        for e in entries:
            print(f"  [{e['id']}] {e['prompt']}")
        return

    # Read current task index (default 0)
    try:
        with open(task_index_file) as f:
            idx = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        idx = 0

    if idx >= len(entries):
        print("All tasks complete. Run 'eval.py analyze <mode>' to process the session log.")
        # Clear index for next run
        try:
            os.remove(task_index_file)
        except FileNotFoundError:
            pass
        return

    e = entries[idx]
    print(f"Task {idx + 1} of {len(entries)}")
    print(f"Task ID: {e['id']}")
    print(f"Prompt:  {e['prompt']}")
    print()
    print("Run this prompt in Claude Code, then run 'eval.py next-task' for the next one.")

    # Write task ID to temp file for capture hook
    with open(current_task_file, "w") as f:
        f.write(e["id"])

    # Advance index
    with open(task_index_file, "w") as f:
        f.write(str(idx + 1))
```

Add to `main()` subparser section:

```python
    # prepare
    p_prepare = sub.add_parser("prepare", help="Reset repo, re-index, configure hooks")
    p_prepare.add_argument("mode", choices=["baseline", "run", "restore"])
    p_prepare.add_argument("--benchmark", help="Path to benchmark JSON")
    p_prepare.set_defaults(func=cmd_prepare)

    # next-task
    p_next = sub.add_parser("next-task", help="Print next task prompt and register task ID")
    p_next.add_argument("--benchmark", help="Path to benchmark JSON")
    p_next.set_defaults(func=cmd_next_task)
```

- [ ] **Step 2: Create hooks init**

```bash
mkdir -p eval/hooks
touch eval/hooks/__init__.py
```

- [ ] **Step 3: Verify CLI help**

```bash
source .venv/bin/activate && python eval/eval.py --help
source .venv/bin/activate && python eval/eval.py prepare --help
```

Expected: subcommands listed without errors.

- [ ] **Step 4: Commit**

```bash
git add eval/eval.py eval/hooks/__init__.py
git commit -m "feat: add prepare and next-task subcommands"
```

---

## Chunk 4: Session Capture Hook

### Task 7: capture_session.py hook

**Files:**
- Create: `eval/hooks/capture_session.py`

This script is invoked by Claude Code hooks in three modes:
- `capture_session.py prompt` — called by `UserPromptSubmit`, writes `task_start`
- `capture_session.py post` — called by `PostToolUse`, writes one tool call entry
- `capture_session.py stop` — called by `Stop`, writes `task_end` and clears task ID file

Claude Code passes hook data as JSON on stdin for `PostToolUse`. The `UserPromptSubmit` hook receives the user prompt on stdin.

- [ ] **Step 1: Implement capture_session.py**

Create `eval/hooks/capture_session.py`:

```python
#!/usr/bin/env python3
"""
Claude Code hook script for eval session capture.
Usage:
  capture_session.py prompt   (UserPromptSubmit hook)
  capture_session.py post     (PostToolUse hook)
  capture_session.py stop     (Stop hook)
"""
import json
import os
import re
import sys
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS_DIR = os.path.join(ROOT_DIR, "eval", "results")
TASK_FILE = os.path.join(ROOT_DIR, ".eval_current_task")

_MATCH_RE = re.compile(r"^MATCH \d+: (.+?) \(lines (\d+)-(\d+)\)")


def _current_task_id():
    try:
        with open(TASK_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


SESSION_LOG_NAME_FILE = os.path.join(ROOT_DIR, ".eval_session_log")


def _log_file():
    """Return path for this session's log. Name is fixed at first write and stored in a temp file."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    try:
        with open(SESSION_LOG_NAME_FILE) as f:
            name = f.read().strip()
        return os.path.join(RESULTS_DIR, name)
    except FileNotFoundError:
        pass
    # First call this session — mint a new name
    name = f"session-{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.log"
    with open(SESSION_LOG_NAME_FILE, "w") as f:
        f.write(name)
    return os.path.join(RESULTS_DIR, name)


def _append(entry):
    with open(_log_file(), "a") as f:
        f.write(json.dumps(entry) + "\n")


def _parse_search_results(stdout):
    """Parse search_code.py stdout into ranked result list."""
    results = []
    rank = 0
    for line in stdout.splitlines():
        m = _MATCH_RE.match(line)
        if m:
            rank += 1
            results.append({"rank": rank, "path": m.group(1), "lines": f"{m.group(2)}-{m.group(3)}"})
    return results


def handle_prompt():
    """UserPromptSubmit: mark task start."""
    task_id = _current_task_id()
    if not task_id:
        return
    _append({"type": "task_start", "task_id": task_id, "ts": datetime.now().isoformat(timespec="seconds")})


def handle_post():
    """PostToolUse: log the tool call."""
    task_id = _current_task_id()
    if not task_id:
        return

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_response", {})

    entry = {"type": "tool", "tool": tool, "task_id": task_id,
             "ts": datetime.now().isoformat(timespec="seconds")}

    if tool == "Bash":
        cmd = tool_input.get("command", "")
        entry["cmd"] = cmd
        if "search_code.py" in cmd:
            stdout = tool_result.get("stdout", "") if isinstance(tool_result, dict) else str(tool_result)
            entry["results"] = _parse_search_results(stdout)
            entry["search_result_bytes"] = len(stdout.encode())

    elif tool == "Read":
        path = tool_input.get("file_path", "")
        entry["file"] = path
        content = tool_result.get("content", "") if isinstance(tool_result, dict) else str(tool_result)
        entry["bytes"] = len(content.encode())

    elif tool == "Edit":
        entry["file"] = tool_input.get("file_path", "")

    elif tool == "Write":
        entry["file"] = tool_input.get("file_path", "")

    _append(entry)


def handle_stop():
    """Stop hook: mark task end."""
    task_id = _current_task_id()
    if task_id:
        _append({"type": "task_end", "task_id": task_id,
                 "ts": datetime.now().isoformat(timespec="seconds")})
    # Clear task file so next prompt starts fresh
    try:
        os.remove(TASK_FILE)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "prompt":
        handle_prompt()
    elif mode == "post":
        handle_post()
    elif mode == "stop":
        handle_stop()
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x eval/hooks/capture_session.py
```

- [ ] **Step 3: Smoke test prompt mode**

```bash
echo "llvm-001" > .eval_current_task
source .venv/bin/activate && python eval/hooks/capture_session.py prompt
cat eval/results/session-*.log
```

Expected: JSON line with `type: task_start`, `task_id: llvm-001`.

- [ ] **Step 4: Clean up**

```bash
rm -f .eval_current_task eval/results/session-*.log
```

- [ ] **Step 5: Commit**

```bash
git add eval/hooks/capture_session.py eval/hooks/__init__.py
git commit -m "feat: add session capture hook for eval integration layer"
```

---

## Chunk 5: Session Analysis

### Task 8: Session log parser and metric computation

**Files:**
- Create: `eval/session.py`
- Create: `tests/eval/test_session.py`

- [ ] **Step 1: Write failing tests**

Create `tests/eval/test_session.py`:

```python
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eval.session import parse_session_log, compute_task_metrics, compute_summary


def _write_log(lines, tmpdir):
    path = os.path.join(tmpdir, "session-test.log")
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return path


def test_parse_session_log_groups_by_task():
    with tempfile.TemporaryDirectory() as tmpdir:
        log = _write_log([
            {"type": "task_start", "task_id": "t1", "ts": "10:00:00"},
            {"type": "tool", "tool": "Read", "file": "a.cpp", "bytes": 100, "task_id": "t1", "ts": "10:00:01"},
            {"type": "task_end", "task_id": "t1", "ts": "10:00:05"},
        ], tmpdir)
        tasks = parse_session_log(log)
    assert "t1" in tasks
    assert len(tasks["t1"]) == 1  # one tool call (excludes delimiters)
    assert tasks["t1"][0]["tool"] == "Read"


def test_compute_task_metrics_edited_and_discarded():
    tool_calls = [
        {"tool": "Read", "file": "a.cpp", "bytes": 500, "ts": "10:00:01"},
        {"tool": "Read", "file": "b.cpp", "bytes": 300, "ts": "10:00:02"},
        {"tool": "Edit", "file": "a.cpp", "ts": "10:00:03"},
    ]
    metrics = compute_task_metrics("t1", tool_calls)
    assert metrics["edited_files"] == ["a.cpp"]
    assert metrics["discarded_reads"] == ["b.cpp"]
    assert metrics["total_tool_calls"] == 3
    assert metrics["search_calls"] == 0
    assert metrics["grep_fallbacks"] == 0


def test_compute_task_metrics_search_calls_counted():
    tool_calls = [
        {"tool": "Bash", "cmd": "search_code.py \"vector shuffle\"", "results": [], "ts": "10:00:01"},
        {"tool": "Read", "file": "a.cpp", "bytes": 200, "ts": "10:00:02"},
        {"tool": "Edit", "file": "a.cpp", "ts": "10:00:03"},
    ]
    metrics = compute_task_metrics("t1", tool_calls)
    assert metrics["search_calls"] == 1
    assert metrics["edited_files"] == ["a.cpp"]


def test_compute_task_metrics_grep_fallback_detected():
    tool_calls = [
        {"tool": "Bash", "cmd": "search_code.py \"something\"", "results": [], "ts": "10:00:01"},
        {"tool": "Bash", "cmd": "grep -r 'foo' llvm/", "ts": "10:00:02"},
        {"tool": "Edit", "file": "a.cpp", "ts": "10:00:03"},
    ]
    metrics = compute_task_metrics("t1", tool_calls)
    assert metrics["grep_fallbacks"] == 1


def test_compute_task_metrics_grep_fallback_not_triggered_without_search():
    tool_calls = [
        {"tool": "Bash", "cmd": "grep -r 'foo' llvm/", "ts": "10:00:01"},
        {"tool": "Edit", "file": "a.cpp", "ts": "10:00:02"},
    ]
    metrics = compute_task_metrics("t1", tool_calls)
    assert metrics["grep_fallbacks"] == 0


def test_compute_task_metrics_token_estimation():
    tool_calls = [
        {"tool": "Read", "file": "a.cpp", "bytes": 4000, "ts": "10:00:01"},
        {"tool": "Bash", "cmd": "search_code.py \"x\"", "search_result_bytes": 800, "results": [], "ts": "10:00:02"},
        {"tool": "Edit", "file": "a.cpp", "ts": "10:00:03"},
    ]
    metrics = compute_task_metrics("t1", tool_calls)
    assert metrics["tokens"]["files_read_bytes"] == 4000
    assert metrics["tokens"]["search_result_bytes"] == 800
    assert metrics["tokens"]["estimated_tokens"] == (4000 + 800) // 4


def test_compute_summary():
    tasks = [
        {"id": "t1", "edited_files": ["a.cpp"], "discarded_reads": ["b.cpp"],
         "search_calls": 1, "grep_fallbacks": 0, "total_tool_calls": 5,
         "tokens": {"estimated_tokens": 1000}},
        {"id": "t2", "edited_files": ["c.cpp"], "discarded_reads": [],
         "search_calls": 2, "grep_fallbacks": 1, "total_tool_calls": 3,
         "tokens": {"estimated_tokens": 500}},
    ]
    summary = compute_summary(tasks)
    assert summary["discarded_reads_total"] == 1
    assert summary["avg_tool_calls_per_task"] == 4.0
    assert summary["grep_fallback_rate"] == 0.5
    assert summary["avg_estimated_tokens_per_task"] == 750.0
    assert summary["edit_hit_rate"] is None  # computed at compare time
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/eval/test_session.py -v 2>&1 | head -20
```

Expected: ImportError for `eval.session`.

- [ ] **Step 3: Implement session.py**

Create `eval/session.py`:

```python
import json
import os
import re
import sys
from datetime import datetime

from eval.report import capture_git_metadata, write_report

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
BENCHMARK_DIR = os.path.join(os.path.dirname(__file__), "benchmarks")


def parse_session_log(log_path):
    """Parse session log into dict of task_id -> list of tool call entries."""
    tasks = {}
    current_task = None

    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") == "task_start":
                current_task = entry["task_id"]
                tasks.setdefault(current_task, [])
            elif entry.get("type") == "task_end":
                current_task = None
            elif entry.get("type") == "tool" and current_task:
                tasks[current_task].append(entry)

    return tasks


def compute_task_metrics(task_id, tool_calls):
    """Compute per-task integration metrics from a list of tool call entries."""
    edited = set()
    read_files = []
    search_calls = 0
    grep_fallbacks = 0
    total_tool_calls = len(tool_calls)
    files_read_bytes = 0
    search_result_bytes = 0
    search_seen = False

    for call in tool_calls:
        tool = call.get("tool", "")

        if tool == "Edit" or tool == "Write":
            edited.add(call.get("file", ""))

        elif tool == "Read":
            f = call.get("file", "")
            if f:
                read_files.append(f)
            files_read_bytes += call.get("bytes", 0)

        elif tool == "Bash":
            cmd = call.get("cmd", "")
            if "search_code.py" in cmd:
                search_calls += 1
                search_seen = True
                search_result_bytes += call.get("search_result_bytes", 0)
            elif search_seen and re.search(r'\b(?:grep|rg|find)\s', cmd):
                grep_fallbacks += 1

    discarded = [f for f in read_files if f not in edited]

    return {
        "id": task_id,
        "edited_files": sorted(edited),
        "discarded_reads": discarded,
        "search_calls": search_calls,
        "grep_fallbacks": grep_fallbacks,
        "total_tool_calls": total_tool_calls,
        "tokens": {
            "files_read_bytes": files_read_bytes,
            "search_result_bytes": search_result_bytes,
            "estimated_tokens": (files_read_bytes + search_result_bytes) // 4,
        },
    }


def compute_summary(task_metrics):
    """Aggregate per-task metrics into a summary dict."""
    n = len(task_metrics)
    if n == 0:
        return {}
    return {
        "discarded_reads_total": sum(len(t["discarded_reads"]) for t in task_metrics),
        "avg_tool_calls_per_task": sum(t["total_tool_calls"] for t in task_metrics) / n,
        "grep_fallback_rate": sum(1 for t in task_metrics if t["grep_fallbacks"] > 0) / n,
        "avg_estimated_tokens_per_task": sum(
            t["tokens"]["estimated_tokens"] for t in task_metrics
        ) / n,
        # edit_hit_rate requires cross-report comparison; set at compare time, stored as null here
        "edit_hit_rate": None,
    }


def analyze_session(log_path, mode, config=None):
    """Parse a session log and produce an integration run report."""
    if config is None:
        config = {"chunk_size": 60, "overlap": 10, "top": 5}

    tasks_by_id = parse_session_log(log_path)
    task_metrics = [
        compute_task_metrics(tid, calls)
        for tid, calls in tasks_by_id.items()
    ]
    summary = compute_summary(task_metrics)

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "git": capture_git_metadata(),
        "config": config,
        "tasks": task_metrics,
        "summary": summary,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && python -m pytest tests/eval/test_session.py -v
```

Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add eval/session.py tests/eval/test_session.py
git commit -m "feat: add session log parser and integration metric computation"
```

---

### Task 9: analyze and promote subcommands

**Files:**
- Modify: `eval/eval.py`

- [ ] **Step 1: Add analyze and promote to eval.py**

Add to `eval/eval.py` after `cmd_next_task`:

```python
def cmd_analyze(args):
    import glob
    from eval.session import analyze_session
    from eval.report import write_report

    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    logs = sorted(glob.glob(os.path.join(results_dir, "session-*.log")))
    if not logs:
        print("No session log found in eval/results/. Run a session with capture hooks active first.")
        sys.exit(1)
    log_path = logs[-1]
    print(f"Analyzing: {log_path}")

    report = analyze_session(log_path, mode=args.mode)
    path = write_report(report, results_dir=results_dir)

    s = report["summary"]
    print(f"\nReport saved to {path}")
    print(f"  discarded_reads_total:        {s.get('discarded_reads_total', 0)}")
    print(f"  avg_tool_calls_per_task:      {s.get('avg_tool_calls_per_task', 0):.1f}")
    print(f"  grep_fallback_rate:           {s.get('grep_fallback_rate', 0):.0%}")
    print(f"  avg_estimated_tokens/task:    {s.get('avg_estimated_tokens_per_task', 0):.0f}")


def cmd_promote(args):
    import json
    from eval.report import read_report

    report = read_report(args.report)
    if report.get("mode") != "baseline":
        print("Error: promote requires a baseline report.")
        sys.exit(1)

    benchmark_file = args.benchmark or DEFAULT_BENCHMARK
    with open(benchmark_file) as f:
        benchmark = json.load(f)

    task_map = {t["id"]: t for t in report.get("tasks", [])}
    updated = 0
    for entry in benchmark:
        tid = entry["id"]
        if tid not in task_map:
            continue
        new_files = task_map[tid].get("edited_files", [])
        existing = set(entry.get("expected_files", []))
        merged = sorted(existing | set(new_files))
        if merged != entry.get("expected_files", []):
            entry["expected_files"] = merged
            updated += 1

    with open(benchmark_file, "w") as f:
        json.dump(benchmark, f, indent=2)

    print(f"Promoted {updated} entries to {benchmark_file}")
```

Add to `main()` subparser section:

```python
    # analyze
    p_analyze = sub.add_parser("analyze", help="Parse session log, write integration report")
    p_analyze.add_argument("mode", choices=["baseline", "run"])
    p_analyze.set_defaults(func=cmd_analyze)

    # promote
    p_promote = sub.add_parser("promote", help="Populate expected_files from baseline report")
    p_promote.add_argument("report", help="Path to baseline report JSON")
    p_promote.add_argument("--benchmark", help="Path to benchmark JSON")
    p_promote.set_defaults(func=cmd_promote)
```

- [ ] **Step 2: Verify CLI help**

```bash
source .venv/bin/activate && python eval/eval.py analyze --help
source .venv/bin/activate && python eval/eval.py promote --help
```

Expected: both print usage without errors.

- [ ] **Step 3: Commit**

```bash
git add eval/eval.py
git commit -m "feat: add analyze and promote subcommands"
```

---

## Chunk 6: Compare and README

### Task 10: compare subcommand

**Files:**
- Modify: `eval/eval.py`

- [ ] **Step 1: Add compare to eval.py**

Add to `eval/eval.py` after `cmd_promote`:

```python
def cmd_compare(args):
    from eval.report import read_report

    a = read_report(args.a)
    b = read_report(args.b)

    def _git_label(r):
        g = r.get("git", {})
        dirty = " [dirty]" if g.get("dirty") else ""
        return f"{r.get('timestamp','?')}  commit {g.get('commit','?')}  \"{g.get('message','?')}\"{dirty}"

    print(f"A: {_git_label(a)}")
    print(f"B: {_git_label(b)}")
    print()

    mode_a = a.get("mode")
    mode_b = b.get("mode")
    if mode_a != mode_b:
        print(f"Warning: comparing {mode_a} vs {mode_b} — only shared metadata shown.\n")
        return

    def _row(label, val_a, val_b, fmt="{:.2f}", lower_is_better=True):
        try:
            va = fmt.format(val_a) if val_a is not None else "n/a"
            vb = fmt.format(val_b) if val_b is not None else "n/a"
        except (TypeError, ValueError):
            va, vb = str(val_a), str(val_b)
        delta = ""
        symbol = ""
        try:
            diff = val_b - val_a
            sign = "+" if diff > 0 else ""
            delta = f"({sign}{fmt.format(diff)})"
            if diff == 0:
                symbol = ""
            elif (lower_is_better and diff < 0) or (not lower_is_better and diff > 0):
                symbol = "✓ improvement"
            else:
                symbol = "✗ regression"
        except TypeError:
            pass
        print(f"  {label:<35} {va:>8}  →  {vb:<8} {delta:<12} {symbol}")

    sa = a.get("summary", {})
    sb = b.get("summary", {})

    if mode_a == "unit":
        print("Unit metrics:")
        _row("hit_rate",       sa.get("hit_rate"),       sb.get("hit_rate"),       lower_is_better=False)
        _row("recall@k",       sa.get("recall_at_k"),    sb.get("recall_at_k"),    lower_is_better=False)
        _row("MRR",            sa.get("MRR"),            sb.get("MRR"),            lower_is_better=False)
        _row("precision@k",    sa.get("precision_at_k"), sb.get("precision_at_k"), lower_is_better=False)
    else:
        # Integration metrics (baseline vs run)
        print("Integration metrics:")
        _row("discarded_reads_total",      sa.get("discarded_reads_total"),       sb.get("discarded_reads_total"),       fmt="{:.0f}")
        _row("avg_tool_calls_per_task",    sa.get("avg_tool_calls_per_task"),     sb.get("avg_tool_calls_per_task"),     fmt="{:.1f}")
        _row("grep_fallback_rate",         sa.get("grep_fallback_rate"),          sb.get("grep_fallback_rate"),          fmt="{:.0%}")
        _row("avg_estimated_tokens/task",  sa.get("avg_estimated_tokens_per_task"), sb.get("avg_estimated_tokens_per_task"), fmt="{:.0f}")

    # edit_hit_rate only meaningful when comparing baseline vs run
    if {mode_a, mode_b} == {"baseline", "run"}:
        baseline_report = a if mode_a == "baseline" else b
        run_report = b if mode_b == "run" else a
        hit_rate = _compute_edit_hit_rate(baseline_report, run_report)
        print(f"\n  {'edit_hit_rate':<35} {'n/a':>8}  →  {hit_rate:<8.2f}")


def _compute_edit_hit_rate(baseline, run):
    """edit_hit_rate = mean over tasks of |run ∩ baseline| / |baseline|."""
    b_tasks = {t["id"]: set(t.get("edited_files", [])) for t in baseline.get("tasks", [])}
    r_tasks = {t["id"]: set(t.get("edited_files", [])) for t in run.get("tasks", [])}
    rates = []
    for tid, b_files in b_tasks.items():
        if not b_files:
            continue
        r_files = r_tasks.get(tid, set())
        rates.append(len(b_files & r_files) / len(b_files))
    return sum(rates) / len(rates) if rates else 0.0
```

Add to `main()`:

```python
    # compare
    p_compare = sub.add_parser("compare", help="Diff two reports")
    p_compare.add_argument("a", help="Path to first report JSON")
    p_compare.add_argument("b", help="Path to second report JSON")
    p_compare.set_defaults(func=cmd_compare)
```

- [ ] **Step 2: Verify CLI help**

```bash
source .venv/bin/activate && python eval/eval.py compare --help
```

- [ ] **Step 3: Commit**

```bash
git add eval/eval.py
git commit -m "feat: add compare subcommand with improvement/regression flagging"
```

---

### Task 11: README

**Files:**
- Create: `eval/README.md`

- [ ] **Step 1: Write the README**

Create `eval/README.md`:

```markdown
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
```

- [ ] **Step 2: Run all eval tests**

```bash
source .venv/bin/activate && python -m pytest tests/eval/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Final commit**

```bash
git add eval/README.md
git commit -m "docs: add eval framework README"
```

---

## Running All Tests

After each chunk, verify the full test suite stays green:

```bash
source .venv/bin/activate && python -m pytest tests/ -v
```
