import subprocess
import threading
import time
from pathlib import Path
import pytest
from engine import watcher
from tests.engine.test_repoident import make_repo, _git


def test_ignored_dirs_fast_path(tmp_path):
    repo = make_repo(tmp_path)
    assert watcher.should_ignore(repo, "node_modules/x/y.js")
    assert watcher.should_ignore(repo, "__pycache__/m.pyc")
    assert not watcher.should_ignore(repo, "src/app.py")


def test_git_ignored_batch_single_subprocess(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    (repo / ".gitignore").write_text("*.log\n")
    _git("add", ".gitignore", cwd=repo)
    calls = []
    orig = subprocess.run
    def counting_run(*a, **k):
        calls.append(a)
        return orig(*a, **k)
    monkeypatch.setattr(watcher.subprocess, "run", counting_run)
    ignored = watcher.git_ignored_batch(repo, ["a.log", "b.log", "src.py"])
    assert ignored == {"a.log", "b.log"}
    assert len(calls) == 1  # ONE check-ignore --stdin call for the batch


def test_index_queue_coalesces():
    q = watcher.IndexQueue()
    ran = []
    gate = threading.Event()
    def slow():
        gate.wait(5)
        ran.append("slow")
    def fast():
        ran.append("fast")
    q.submit("r1", slow)
    time.sleep(0.1)          # worker picks up slow, blocks on gate
    q.submit("r1", fast)     # queued
    q.submit("r1", fast)     # coalesced away
    gate.set()
    q.stop()
    assert ran == ["slow", "fast"]


def test_repo_watch_triggers_on_change(tmp_path):
    repo = make_repo(tmp_path)
    fired = threading.Event()
    w = watcher.RepoWatch(repo, on_change=fired.set)
    try:
        time.sleep(0.3)
        (repo / "new.py").write_text("y = 2\n")
        assert fired.wait(5.0)
    finally:
        w.stop()


def test_repo_watch_ignores_noise(tmp_path):
    repo = make_repo(tmp_path)
    fired = threading.Event()
    w = watcher.RepoWatch(repo, on_change=fired.set)
    try:
        time.sleep(0.3)
        nm = repo / "node_modules" / "p"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("x\n")
        assert not fired.wait(2.0)
    finally:
        w.stop()
