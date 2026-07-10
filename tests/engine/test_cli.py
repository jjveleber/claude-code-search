# tests/engine/test_cli.py
import pytest
from engine import cli, paths, registry
from tests.engine.test_repoident import make_repo


@pytest.fixture(autouse=True)
def csh(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    paths.ensure_home()


def test_enable_registers_and_reports(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "_ensure_setup", lambda: True)
    monkeypatch.setattr(cli.client, "watch",
                        lambda r, p: {"ok": True, "repo_id": "x"})
    assert cli.main(["enable"]) == 0
    assert registry.resolve(repo).registered
    assert "enabled" in capsys.readouterr().out.lower()


def test_enable_outside_git_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["enable"]) == 1
    assert "not a git repo" in capsys.readouterr().err.lower()


def test_search_not_enabled_message(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    assert cli.main(["search", "anything"]) == 1
    assert "code-search enable" in capsys.readouterr().err


def test_search_prints_match_format(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    registry.enable(repo)
    monkeypatch.setattr(
        cli.client, "search",
        lambda *a, **k: {"ok": True,
                         "results": [["auth.py", 1, 2, "def f(): pass\n", "prod"]]})
    assert cli.main(["search", "auth"]) == 0
    out = capsys.readouterr().out
    assert "MATCH 1: auth.py [prod] (lines 1-2)" in out


def test_disable_purge_removes_index(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    r = registry.enable(repo)
    idx = paths.index_dir(r.repo_id)
    idx.mkdir(parents=True)
    (idx / "chroma.sqlite3").write_text("x")
    monkeypatch.setattr(cli.client, "unwatch_all", lambda *a: {"ok": True})
    assert cli.main(["disable", "--purge"]) == 0
    assert not idx.exists()


def _enabled_with_index(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    r = registry.enable(repo)
    idx = paths.index_dir(r.repo_id)
    idx.mkdir(parents=True)
    (idx / "chroma.sqlite3").write_text("x")
    return idx


def test_disable_purge_withheld_when_daemon_busy(tmp_path, monkeypatch, capsys):
    # Daemon still draining its index queue -> unwatch_all returns ok=False.
    # Purging now would rmtree an index the worker is still writing, so withhold.
    idx = _enabled_with_index(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.client, "unwatch_all",
                        lambda *a: {"ok": False, "error": "queue busy"})
    assert cli.main(["disable", "--purge"]) == 1
    assert idx.exists()
    assert "retry" in capsys.readouterr().err.lower()


def test_disable_purge_proceeds_when_daemon_down(tmp_path, monkeypatch):
    # No daemon => nothing can be writing the index => purge is safe.
    idx = _enabled_with_index(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.client, "unwatch_all",
                        lambda *a: {"ok": False, "error": "daemon not running"})
    assert cli.main(["disable", "--purge"]) == 0
    assert not idx.exists()


def _raise_unavail(*a, **k):
    raise cli.client.DaemonUnavailable("down")


# --- search-status message mapping ---

@pytest.mark.parametrize("status,needle", [
    ("warming", "warming up"),
    ("empty", "no indexable files"),
    ("timeout", "timed out"),
    ("index_error", "code-search reindex"),
])
def test_search_status_messages(tmp_path, monkeypatch, capsys, status, needle):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    registry.enable(repo)
    monkeypatch.setattr(cli.client, "search",
                        lambda *a, **k: {"ok": False, "status": status})
    assert cli.main(["search", "x"]) == 1
    assert needle in capsys.readouterr().err


def test_search_daemon_unavailable(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    registry.enable(repo)
    monkeypatch.setattr(cli.client, "search", _raise_unavail)
    assert cli.main(["search", "x"]) == 1
    assert "daemon unavailable" in capsys.readouterr().err


# --- enable --dry-run / daemon-unavailable ---

def test_enable_dry_run_changes_nothing(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    assert cli.main(["enable", "--dry-run"]) == 0
    assert not registry.resolve(repo).registered
    assert "dry run" in capsys.readouterr().out.lower()


def test_enable_daemon_unavailable_still_registers(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "_ensure_setup", lambda: True)
    monkeypatch.setattr(cli.client, "watch", _raise_unavail)
    assert cli.main(["enable"]) == 0
    assert registry.resolve(repo).registered
    assert "daemon failed to start" in capsys.readouterr().err


# --- status ---

def test_status_reports_daemon_up(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    registry.enable(repo)
    monkeypatch.setattr(cli.client, "status",
                        lambda: {"uptime_s": 7, "watched": ["a", "b"]})
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "daemon: up 7s, watching 2 repo(s)" in out


def test_status_reports_daemon_down(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    registry.enable(repo)
    monkeypatch.setattr(cli.client, "status", _raise_unavail)
    assert cli.main(["status"]) == 0
    assert "daemon: not running" in capsys.readouterr().out


# --- reindex ---

def test_reindex_queued(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli.client, "watch", lambda *a: {"ok": True})
    monkeypatch.setattr(cli.client, "request", lambda *a, **k: {"ok": True})
    assert cli.main(["reindex"]) == 0
    assert "reindex queued" in capsys.readouterr().out


def test_reindex_error(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli.client, "watch", lambda *a: {"ok": True})
    monkeypatch.setattr(cli.client, "request",
                        lambda *a, **k: {"ok": False, "error": "boom"})
    assert cli.main(["reindex"]) == 1
    assert "boom" in capsys.readouterr().out


def test_reindex_daemon_unavailable(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli.client, "watch", _raise_unavail)
    assert cli.main(["reindex"]) == 1
    assert "down" in capsys.readouterr().err


# --- gc / setup ---

def test_gc_reports_reaped_count(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["gc"]) == 0
    assert "gc: reaped 0 index(es)" in capsys.readouterr().out


def test_setup_delegates_to_setup_venv(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.setup_venv, "main", lambda: 0)
    assert cli.main(["setup"]) == 0
