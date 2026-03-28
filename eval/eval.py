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

    # prepare
    p_prepare = sub.add_parser("prepare", help="Reset repo, re-index, configure hooks")
    p_prepare.add_argument("mode", choices=["baseline", "run", "restore"])
    p_prepare.add_argument("--benchmark", help="Path to benchmark JSON")
    p_prepare.set_defaults(func=cmd_prepare)

    # next-task
    p_next = sub.add_parser("next-task", help="Print next task prompt and register task ID")
    p_next.add_argument("--benchmark", help="Path to benchmark JSON")
    p_next.set_defaults(func=cmd_next_task)

    # analyze
    p_analyze = sub.add_parser("analyze", help="Parse session log, write integration report")
    p_analyze.add_argument("mode", choices=["baseline", "run"])
    p_analyze.set_defaults(func=cmd_analyze)

    # promote
    p_promote = sub.add_parser("promote", help="Populate expected_files from baseline report")
    p_promote.add_argument("report", help="Path to baseline report JSON")
    p_promote.add_argument("--benchmark", help="Path to benchmark JSON")
    p_promote.set_defaults(func=cmd_promote)

    # compare
    p_compare = sub.add_parser("compare", help="Diff two reports")
    p_compare.add_argument("a", help="Path to first report JSON")
    p_compare.add_argument("b", help="Path to second report JSON")
    p_compare.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
