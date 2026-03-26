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
