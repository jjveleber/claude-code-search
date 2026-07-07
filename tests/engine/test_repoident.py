import subprocess
from pathlib import Path
from engine import repoident


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def make_repo(tmp_path, name="main") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git("init", cwd=repo)
    (repo / "a.py").write_text("x = 1\n")
    _git("add", ".", cwd=repo)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init", cwd=repo)
    return repo


def test_repo_root_from_subdir(tmp_path):
    repo = make_repo(tmp_path)
    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)
    assert repoident.repo_root(sub) == repo.resolve()


def test_repo_root_outside_git(tmp_path):
    assert repoident.repo_root(tmp_path) is None


def test_family_root_of_worktree_is_main(tmp_path):
    repo = make_repo(tmp_path)
    wt = tmp_path / "wt"
    _git("worktree", "add", str(wt), "-b", "feat", cwd=repo)
    assert repoident.repo_root(wt) == wt.resolve()
    assert repoident.family_root(wt) == repo.resolve()
    assert repoident.family_root(repo) == repo.resolve()


def test_repo_id_stable_16_hex(tmp_path):
    repo = make_repo(tmp_path)
    rid = repoident.repo_id(repo)
    assert len(rid) == 16 and all(c in "0123456789abcdef" for c in rid)
    assert rid == repoident.repo_id(repo / "src" / "..")  # resolves first
