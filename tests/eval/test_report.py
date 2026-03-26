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
