import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eval.session import parse_session_log, parse_task_usage, compute_task_metrics, compute_summary


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


def test_compute_task_metrics_with_actual_usage():
    tool_calls = [
        {"tool": "Read", "file": "a.cpp", "bytes": 4000, "ts": "10:00:01"},
        {"tool": "Edit", "file": "a.cpp", "ts": "10:00:02"},
    ]
    usage = {"input_tokens": 1500, "output_tokens": 200,
             "cache_creation_input_tokens": 100, "cache_read_input_tokens": 800}
    metrics = compute_task_metrics("t1", tool_calls, usage=usage)
    assert metrics["tokens"]["input_tokens"] == 1500
    assert metrics["tokens"]["output_tokens"] == 200
    assert metrics["tokens"]["cache_creation_input_tokens"] == 100
    assert metrics["tokens"]["cache_read_input_tokens"] == 800
    assert metrics["tokens"]["estimated_tokens"] == 4000 // 4  # still present


def test_parse_task_usage():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "session-test.log")
        lines = [
            {"type": "task_start", "task_id": "t1", "ts": "10:00:00"},
            {"type": "tool", "tool": "Read", "file": "a.cpp", "bytes": 100, "task_id": "t1", "ts": "10:00:01"},
            {"type": "task_end", "task_id": "t1", "ts": "10:00:05",
             "usage": {"input_tokens": 500, "output_tokens": 80,
                       "cache_creation_input_tokens": 50, "cache_read_input_tokens": 300}},
            {"type": "task_start", "task_id": "t2", "ts": "10:01:00"},
            {"type": "task_end", "task_id": "t2", "ts": "10:01:30"},
        ]
        with open(log_path, "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
        usage = parse_task_usage(log_path)
    assert "t1" in usage
    assert usage["t1"]["input_tokens"] == 500
    assert usage["t1"]["output_tokens"] == 80
    assert "t2" not in usage  # no usage in t2's task_end


def test_compute_summary_prefers_actual_tokens():
    tasks = [
        {"id": "t1", "edited_files": [], "discarded_reads": [],
         "search_calls": 0, "grep_fallbacks": 0, "total_tool_calls": 5,
         "tokens": {"estimated_tokens": 0, "input_tokens": 1000, "output_tokens": 200,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
        {"id": "t2", "edited_files": [], "discarded_reads": [],
         "search_calls": 0, "grep_fallbacks": 0, "total_tool_calls": 3,
         "tokens": {"estimated_tokens": 0, "input_tokens": 600, "output_tokens": 100,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
    ]
    summary = compute_summary(tasks)
    assert summary["avg_estimated_tokens_per_task"] == (1200 + 700) / 2  # input+output


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
