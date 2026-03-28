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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
