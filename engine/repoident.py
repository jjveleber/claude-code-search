"""Repo/worktree identity. Stdlib only."""
import hashlib
import subprocess
from pathlib import Path


def _git_out(args, cwd) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def repo_root(start: Path) -> Path | None:
    """Top-level of the worktree containing `start` (resolved), or None."""
    out = _git_out(["rev-parse", "--show-toplevel"], cwd=start)
    return Path(out).resolve() if out else None


def family_root(start: Path) -> Path | None:
    """Main-repo root shared by all worktrees of the repo containing `start`."""
    common = _git_out(["rev-parse", "--path-format=absolute", "--git-common-dir"],
                      cwd=start)
    if not common:
        return None
    common_path = Path(common).resolve()
    if common_path.name == ".git":
        return common_path.parent
    return common_path  # bare repo: family root is the git dir itself


def repo_id(path: Path) -> str:
    return hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:16]
