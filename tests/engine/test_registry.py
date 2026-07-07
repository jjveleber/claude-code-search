import subprocess
from pathlib import Path
import pytest
from engine import registry, repoident
from tests.engine.test_repoident import make_repo, _git


@pytest.fixture(autouse=True)
def csh(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))


def test_resolve_unknown_repo(tmp_path):
    repo = make_repo(tmp_path)
    r = registry.resolve(repo)
    assert not r.registered and not r.family_enabled
    assert r.repo_id == repoident.repo_id(repo)


def test_enable_registers_main_worktree(tmp_path):
    repo = make_repo(tmp_path)
    r = registry.enable(repo)
    assert r.registered and r.family_enabled
    assert r.main_path == str(repo.resolve())
    r2 = registry.resolve(repo)
    assert r2.registered


def test_enable_from_worktree_registers_family_and_worktree(tmp_path):
    repo = make_repo(tmp_path)
    wt = tmp_path / "wt"
    _git("worktree", "add", str(wt), "-b", "feat", cwd=repo)
    r = registry.enable(wt)
    assert r.family_enabled and r.registered
    assert r.main_path == str(repo.resolve())
    # main worktree not yet registered, but family enabled
    rm = registry.resolve(repo)
    assert rm.family_enabled and not rm.registered


def test_register_worktree_inherits_enablement(tmp_path):
    repo = make_repo(tmp_path)
    registry.enable(repo)
    wt = tmp_path / "wt"
    _git("worktree", "add", str(wt), "-b", "feat", cwd=repo)
    r0 = registry.resolve(wt)
    assert r0.family_enabled and not r0.registered
    r = registry.register_worktree(wt)
    assert r.registered
    assert registry.resolve(wt).registered


def test_register_worktree_rejects_disabled_family(tmp_path):
    repo = make_repo(tmp_path)
    with pytest.raises(registry.NotEnabledError):
        registry.register_worktree(repo)


def test_disable_returns_repo_ids(tmp_path):
    repo = make_repo(tmp_path)
    registry.enable(repo)
    ids = registry.disable(repo)
    assert ids == [repoident.repo_id(repo)]
    assert not registry.resolve(repo).family_enabled


def test_gc_reaps_dead_paths(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    registry.enable(repo)
    rid = repoident.repo_id(repo)
    reg = registry.load()
    # simulate: path deleted and marked dead 8 days ago
    fam = next(iter(reg["repos"].values()))
    fam["worktrees"][rid]["path"] = str(tmp_path / "gone")
    fam["worktrees"][rid]["dead_since"] = "2026-06-01T00:00:00+00:00"
    registry.save(reg)
    reaped = registry.gc(days=7)
    assert reaped == [rid]
