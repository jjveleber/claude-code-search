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
    monkeypatch.setattr(cli.client, "unwatch", lambda *a: {"ok": True})
    assert cli.main(["disable", "--purge"]) == 0
    assert not idx.exists()
