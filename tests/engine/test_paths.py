import os
from pathlib import Path
from engine import paths


def test_home_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    assert paths.home() == tmp_path / "csh"


def test_home_defaults_to_dot_code_search(monkeypatch):
    monkeypatch.delenv("CODE_SEARCH_HOME", raising=False)
    assert paths.home() == Path.home() / ".code-search"


def test_ensure_home_creates_layout(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    home = paths.ensure_home()
    for sub in ("indexes", "state", "logs", "trash"):
        assert (home / sub).is_dir()


def test_derived_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    h = tmp_path / "csh"
    assert paths.registry_path() == h / "registry.json"
    assert paths.index_dir("abc123") == h / "indexes" / "abc123"
    assert paths.socket_path() == h / "daemon.sock"
    assert paths.pid_path() == h / "daemon.pid"
    assert paths.watches_path() == h / "state" / "watches.json"
    assert paths.venv_python() == h / "venv" / "bin" / "python3"
    assert paths.venv_ok_path() == h / "venv.ok"
