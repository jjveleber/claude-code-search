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
        try:
            entry["bytes"] = os.path.getsize(path)
        except OSError:
            entry["bytes"] = 0

    elif tool == "Edit":
        entry["file"] = tool_input.get("file_path", "")

    elif tool == "Write":
        entry["file"] = tool_input.get("file_path", "")

    _append(entry)


def _read_last_usage(transcript_path):
    """Read the last assistant message's usage from the transcript JSONL."""
    try:
        last_usage = {}
        with open(transcript_path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    msg = entry.get("message", {})
                    if msg.get("role") == "assistant":
                        usage = msg.get("usage")
                        if usage:
                            last_usage = usage
                except json.JSONDecodeError:
                    continue
        return last_usage
    except OSError:
        return {}


def handle_stop():
    """Stop hook: mark task end. Reads actual token usage from transcript."""
    task_id = _current_task_id()

    try:
        data = json.load(sys.stdin)
        transcript_path = data.get("transcript_path", "")
    except (json.JSONDecodeError, EOFError):
        transcript_path = ""

    if task_id:
        entry = {"type": "task_end", "task_id": task_id,
                 "ts": datetime.now().isoformat(timespec="seconds")}
        if transcript_path:
            raw = _read_last_usage(transcript_path)
            if raw:
                entry["usage"] = {
                    "input_tokens": raw.get("input_tokens", 0),
                    "output_tokens": raw.get("output_tokens", 0),
                    "cache_creation_input_tokens": raw.get("cache_creation_input_tokens", 0),
                    "cache_read_input_tokens": raw.get("cache_read_input_tokens", 0),
                }
        _append(entry)

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
