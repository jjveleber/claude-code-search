#!/usr/bin/env python3
"""
Analyze search usage from logs/search_usage.jsonl and logs/search_warnings.log

Usage:
    python3 tools/analyze_search_usage.py                # Full report
    python3 tools/analyze_search_usage.py --period 7     # Last 7 days
    python3 tools/analyze_search_usage.py --skill debugging  # Filter by skill
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
import argparse


def load_search_events(log_file, days=None):
    """Load search events from JSONL, optionally filtered by recency."""
    if not log_file.exists():
        return []

    events = []
    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for line in log_file.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if cutoff:
                ts = datetime.fromisoformat(event["timestamp"])
                if ts < cutoff:
                    continue
            events.append(event)
        except (json.JSONDecodeError, KeyError):
            continue

    return events


def load_violations(log_file, days=None):
    """Load violations from pipe-delimited log."""
    if not log_file.exists():
        return []

    violations = []
    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for line in log_file.read_text().splitlines():
        if not line.strip() or "VIOLATION" not in line:
            continue

        parts = line.split(" | ")
        if len(parts) < 4:
            continue

        ts_str = parts[0]
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if cutoff and ts < cutoff:
                continue
        except ValueError:
            continue

        violation = {"timestamp": ts_str}
        for part in parts[2:]:
            if "=" in part:
                key, val = part.split("=", 1)
                violation[key.strip()] = val.strip()

        violations.append(violation)

    return violations


def calculate_compliance_rate(searches, violations):
    """Compliance = searches / (searches + violations)."""
    total = len(searches) + len(violations)
    if total == 0:
        return 0.0
    return (len(searches) / total) * 100


def weekly_trends(events, violations):
    """Group by week and calculate compliance."""
    weeks = defaultdict(lambda: {"searches": 0, "violations": 0})

    for event in events:
        ts = datetime.fromisoformat(event["timestamp"])
        week = ts.strftime("%Y-W%U")
        weeks[week]["searches"] += 1

    for v in violations:
        ts = datetime.fromisoformat(v["timestamp"].replace("Z", "+00:00"))
        week = ts.strftime("%Y-W%U")
        weeks[week]["violations"] += 1

    trends = []
    for week in sorted(weeks.keys()):
        data = weeks[week]
        total = data["searches"] + data["violations"]
        compliance = (data["searches"] / total * 100) if total > 0 else 0.0
        trends.append((week, compliance, data["searches"], data["violations"]))

    return trends


def breakdown_by_field(events, violations, field):
    """Group by field (skill_name, model, etc) and calculate compliance."""
    stats = defaultdict(lambda: {"searches": 0, "violations": 0})

    for event in events:
        key = event.get(field, "unknown")
        stats[key]["searches"] += 1

    for v in violations:
        key = v.get(field, "unknown")
        stats[key]["violations"] += 1

    results = []
    for key in sorted(stats.keys()):
        data = stats[key]
        total = data["searches"] + data["violations"]
        compliance = (data["searches"] / total * 100) if total > 0 else 0.0
        results.append((key, compliance, data["searches"], data["violations"]))

    return results


def search_mode_distribution(events):
    """Count server vs direct searches."""
    modes = Counter(e["search_mode"] for e in events if "search_mode" in e)
    return modes


def bm25_usage_rate(events):
    """Percent of searches using BM25."""
    total = len(events)
    if total == 0:
        return 0.0
    bm25_count = sum(1 for e in events if e.get("use_bm25", False))
    return (bm25_count / total) * 100


def avg_latency_by_mode(events):
    """Average latency for server vs direct."""
    by_mode = defaultdict(list)
    for e in events:
        if "latency_ms" in e and "search_mode" in e:
            by_mode[e["search_mode"]].append(e["latency_ms"])

    return {mode: sum(vals) / len(vals) if vals else 0.0
            for mode, vals in by_mode.items()}


def print_report(searches, violations, args):
    """Print formatted analytics report."""
    print("Search Usage Report")
    print("=" * 60)

    period_desc = f"Last {args.period} days" if args.period else "All time"
    print(f"Period: {period_desc}")
    if args.skill:
        print(f"Filtered by skill: {args.skill}")
    if args.model:
        print(f"Filtered by model: {args.model}")
    print()

    # Overall compliance
    compliance = calculate_compliance_rate(searches, violations)
    total_accesses = len(searches) + len(violations)
    print(f"Compliance Rate: {compliance:.1f}% ({len(searches)} searches / {total_accesses} file accesses)")
    print()

    # Trends
    if not args.skill and not args.model:  # Only show trends for full dataset
        trends = weekly_trends(searches, violations)
        if trends:
            print("Weekly Trends:")
            for week, comp, s, v in trends[-4:]:  # Last 4 weeks
                print(f"  {week}: {comp:.1f}% ({s} searches / {s + v} accesses)")
            print()

    # By skill
    if not args.skill:
        skill_stats = breakdown_by_field(searches, violations, "skill_name")
        if skill_stats:
            print("By Skill:")
            for skill, comp, s, v in skill_stats[:5]:  # Top 5
                if skill == "unknown":
                    continue
                print(f"  {skill}: {comp:.1f}% ({s}/{s + v})")
            print()

    # By model
    if not args.model:
        model_stats = breakdown_by_field(searches, violations, "model")
        if model_stats:
            print("By Model:")
            for model, comp, s, v in model_stats:
                if model == "unknown":
                    continue
                print(f"  {model}: {comp:.1f}% ({s}/{s + v})")
            print()

    # Search mode
    modes = search_mode_distribution(searches)
    if modes:
        total_searches = sum(modes.values())
        print("Search Mode:")
        for mode, count in modes.most_common():
            pct = (count / total_searches * 100) if total_searches else 0
            print(f"  {mode}: {pct:.1f}% ({count})")
        print()

    # BM25
    bm25_pct = bm25_usage_rate(searches)
    print(f"BM25 Usage: {bm25_pct:.1f}% of searches")
    print()

    # Latency
    latencies = avg_latency_by_mode(searches)
    if latencies:
        print("Avg Latency:")
        for mode, avg in sorted(latencies.items()):
            print(f"  {mode}: {avg:.0f}ms")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze search usage and compliance"
    )
    parser.add_argument(
        "--period", type=int, metavar="DAYS",
        help="Analyze last N days only"
    )
    parser.add_argument(
        "--skill", type=str,
        help="Filter by skill name"
    )
    parser.add_argument(
        "--model", type=str,
        help="Filter by model"
    )
    args = parser.parse_args()

    log_dir = Path("logs")
    searches = load_search_events(log_dir / "search_usage.jsonl", args.period)
    violations = load_violations(log_dir / "search_warnings.log", args.period)

    # Apply filters
    if args.skill:
        searches = [s for s in searches if s.get("skill_name") == args.skill]
        violations = [v for v in violations if v.get("skill") == args.skill]

    if args.model:
        searches = [s for s in searches if s.get("model") == args.model]
        violations = [v for v in violations if v.get("model") == args.model]

    if not searches and not violations:
        print("No data found matching filters.")
        sys.exit(0)

    print_report(searches, violations, args)


if __name__ == "__main__":
    main()
