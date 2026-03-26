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
