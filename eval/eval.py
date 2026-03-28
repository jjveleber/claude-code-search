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
