"""Central registry of enabled repos/worktrees. Stdlib only."""
import contextlib
import fcntl
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

from engine import paths, repoident


class NotEnabledError(Exception):
    pass


@dataclass
class Resolved:
    family_id: str | None
    repo_id: str | None
    registered: bool
    family_enabled: bool
    main_path: str | None
    bm25: bool
    main_repo_id: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load() -> dict:
    p = paths.registry_path()
    if not p.exists():
        return {"repos": {}}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {"repos": {}}


@contextlib.contextmanager
def _locked():
    """Hold the registry file lock for a full read-modify-write transaction."""
    paths.ensure_home()
    lock = paths.registry_lock_path()
    with open(lock, "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _write(reg: dict) -> None:
    """Write reg to disk. Caller must already hold the lock via _locked()."""
    tmp = paths.registry_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=2))
    os.replace(tmp, paths.registry_path())


def save(reg: dict) -> None:
    with _locked():
        _write(reg)


def resolve(worktree_root: Path) -> Resolved:
    root = repoident.repo_root(Path(worktree_root))
    if root is None:
        return Resolved(None, None, False, False, None, False, None)
    fam_root = repoident.family_root(root)
    fam_id = repoident.repo_id(fam_root)
    rid = repoident.repo_id(root)
    reg = load()
    fam = reg["repos"].get(fam_id)
    if fam is None:
        return Resolved(fam_id, rid, False, False, None, False, None)
    return Resolved(
        family_id=fam_id,
        repo_id=rid,
        registered=rid in fam["worktrees"],
        family_enabled=True,
        main_path=fam["main_path"],
        bm25=fam.get("bm25", False),
        main_repo_id=repoident.repo_id(Path(fam["main_path"])),
    )


def enable(worktree_root: Path, bm25: bool = False) -> Resolved:
    root = repoident.repo_root(Path(worktree_root))
    if root is None:
        raise NotEnabledError(f"not a git repository: {worktree_root}")
    fam_root = repoident.family_root(root)
    fam_id = repoident.repo_id(fam_root)
    rid = repoident.repo_id(root)
    with _locked():
        reg = load()
        existed = fam_id in reg["repos"]
        fam = reg["repos"].setdefault(fam_id, {
            "main_path": str(fam_root),
            "enabled_at": _now(),
            "bm25": bm25,
            "worktrees": {},
        })
        if existed:
            # bm25 is sticky-on: re-enabling with --bm25 must upgrade an
            # already-enabled family, never silently downgrade it.
            fam["bm25"] = fam.get("bm25", False) or bm25
        fam["worktrees"].setdefault(rid, {
            "path": str(root), "last_indexed": None,
            "auto_registered": False, "dead_since": None,
        })
        _write(reg)
    return resolve(root)


def register_worktree(worktree_root: Path) -> Resolved:
    r = resolve(worktree_root)
    if not r.family_enabled:
        raise NotEnabledError(f"family not enabled for {worktree_root}")
    if r.registered:
        return r
    root = repoident.repo_root(Path(worktree_root))
    with _locked():
        reg = load()
        reg["repos"][r.family_id]["worktrees"][r.repo_id] = {
            "path": str(root), "last_indexed": None,
            "auto_registered": True, "dead_since": None,
        }
        _write(reg)
    return resolve(root)


def disable(worktree_root: Path) -> list[str]:
    r = resolve(worktree_root)
    if not r.family_enabled:
        return []
    with _locked():
        reg = load()
        fam = reg["repos"].pop(r.family_id, None)
        if fam is None:
            return []
        _write(reg)
    return list(fam["worktrees"].keys())


def gc(days: int = 7) -> list[str]:
    reaped = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with _locked():
        reg = load()
        for fam_id in list(reg["repos"]):
            fam = reg["repos"][fam_id]
            for rid in list(fam["worktrees"]):
                wt = fam["worktrees"][rid]
                if Path(wt["path"]).exists():
                    wt["dead_since"] = None
                    continue
                if wt["dead_since"] is None:
                    wt["dead_since"] = _now()
                elif datetime.fromisoformat(wt["dead_since"]) < cutoff:
                    del fam["worktrees"][rid]
                    reaped.append(rid)
            if not fam["worktrees"]:
                del reg["repos"][fam_id]
        _write(reg)
    return reaped
