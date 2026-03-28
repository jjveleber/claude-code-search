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
