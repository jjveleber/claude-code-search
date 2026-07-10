# tests/engine/test_setup_venv.py
import subprocess

import pytest

from engine import paths, setup_venv


@pytest.fixture(autouse=True)
def csh(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    paths.ensure_home()


# --- venv_ok(): marker must match sha256 of requirements.txt (no mocks) ---

def test_venv_ok_true_when_marker_matches_hash():
    paths.venv_ok_path().write_text(setup_venv._req_hash())
    assert setup_venv.venv_ok() is True


def test_venv_ok_false_when_marker_missing():
    assert setup_venv.venv_ok() is False


def test_venv_ok_false_when_marker_stale():
    paths.venv_ok_path().write_text("not-the-hash")
    assert setup_venv.venv_ok() is False


def test_venv_ok_ignores_surrounding_whitespace():
    paths.venv_ok_path().write_text(f"  {setup_venv._req_hash()}\n")
    assert setup_venv.venv_ok() is True


# --- main(): success-only venv.ok invariant ---

class _Completed:
    def __init__(self, returncode):
        self.returncode = returncode


def _fake_run(returncode_for_pip):
    """Return a subprocess.run stub: venv-create succeeds, pip gets the given rc."""
    def run(cmd, *a, **k):
        if "pip" in " ".join(str(c) for c in cmd):
            return _Completed(returncode_for_pip)
        return _Completed(0)   # `python -m venv` (check=True) must succeed
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
    paths.venv_ok_path().write_text(setup_venv._req_hash())

    def boom(*a, **k):
        raise AssertionError("subprocess.run must not be called when venv is ok")

    monkeypatch.setattr(subprocess, "run", boom)
    assert setup_venv.main() == 0
    assert "already up to date" in capsys.readouterr().out
