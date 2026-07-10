# tests/engine/test_setup_venv.py
import subprocess

import pytest

from engine import paths, setup_venv


@pytest.fixture(autouse=True)
def csh(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    paths.ensure_home()


def _fake_venv_python():
    """Create a fake venv interpreter so venv_ok()'s existence check passes."""
    py = paths.venv_python()
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("#!/bin/sh\n")


# --- venv_ok(): marker matches sha256 of requirements.txt AND venv exists ---

def test_venv_ok_true_when_marker_matches_and_venv_present():
    _fake_venv_python()
    paths.venv_ok_path().write_text(setup_venv._req_hash())
    assert setup_venv.venv_ok() is True


def test_venv_ok_false_when_marker_missing():
    _fake_venv_python()
    assert setup_venv.venv_ok() is False


def test_venv_ok_false_when_marker_stale():
    _fake_venv_python()
    paths.venv_ok_path().write_text("not-the-hash")
    assert setup_venv.venv_ok() is False


def test_venv_ok_false_when_venv_deleted_despite_marker():
    # Marker survives but the venv dir was removed — must NOT report ok, else
    # setup says "already up to date" while the daemon can't start.
    paths.venv_ok_path().write_text(setup_venv._req_hash())
    assert not paths.venv_python().exists()
    assert setup_venv.venv_ok() is False


def test_venv_ok_ignores_surrounding_whitespace():
    _fake_venv_python()
    paths.venv_ok_path().write_text(f"  {setup_venv._req_hash()}\n")
    assert setup_venv.venv_ok() is True


# --- main(): success-only venv.ok invariant ---

class _Completed:
    def __init__(self, returncode):
        self.returncode = returncode


def _fake_run(returncode_for_pip):
    """subprocess.run stub: `python -m venv` materializes the interpreter and
    succeeds; pip gets the given returncode. Match on the pip *executable*
    (cmd[0]), not a substring — the tmp_path can itself contain 'pip'."""
    def run(cmd, *a, **k):
        if str(cmd[0]).endswith("pip"):
            return _Completed(returncode_for_pip)
        _fake_venv_python()      # `python -m venv` (check=True) must succeed
        return _Completed(0)
    return run


def test_main_writes_marker_on_pip_success(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", _fake_run(0))
    assert setup_venv.main() == 0
    assert paths.venv_ok_path().read_text() == setup_venv._req_hash()
    assert setup_venv.venv_ok() is True


def test_main_leaves_no_marker_on_pip_failure(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", _fake_run(1))
    assert setup_venv.main() == 1
    assert not paths.venv_ok_path().exists()
    assert setup_venv.venv_ok() is False
    assert "without venv.ok marker" in capsys.readouterr().err


def test_main_skips_build_when_already_ok(monkeypatch, capsys):
    _fake_venv_python()
    paths.venv_ok_path().write_text(setup_venv._req_hash())

    def boom(*a, **k):
        raise AssertionError("subprocess.run must not be called when venv is ok")

    monkeypatch.setattr(subprocess, "run", boom)
    assert setup_venv.main() == 0
    assert "already up to date" in capsys.readouterr().out
