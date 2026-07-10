# Central Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert claude-code-search from per-repo installation to a single central install packaged as a Claude Code plugin, per the approved spec `docs/superpowers/specs/2026-07-07-central-install-design.md`.

**Architecture:** A python package `engine/` provides a `RepoIndex(root, index_dir)` abstraction (no cwd dependence), a multiplexed Unix-socket daemon serving all enabled repos, and a stdlib-only layer (paths/identity/registry/client/migration) usable by hooks without the heavy venv. A plugin manifest registers SessionStart/SessionEnd hooks and a `/code-search` slash command that delegates to a deterministic CLI.

**Tech Stack:** Python 3.12, chromadb, sentence-transformers, watchdog, rank_bm25, pytest. Bash for hooks/launcher.

## Global Constraints

- Python 3.12; venv lives at `$CODE_SEARCH_HOME/venv` (default `~/.code-search`).
- **Stdlib-only rule:** `engine/paths.py`, `engine/repoident.py`, `engine/registry.py`, `engine/client.py`, `engine/migrate.py`, `engine/setup_venv.py`, `engine/cli_light.py` must import ONLY the Python standard library. Hooks and `setup` run before/without the venv. Heavy imports (chromadb, torch, watchdog) are allowed only in `engine/repo_index.py`, `engine/embedding.py`, `engine/daemon.py`, `engine/watcher.py`.
- **No `os.chdir()` anywhere in `engine/`.** All git/file operations take explicit `cwd=`/absolute paths.
- Every test uses a tmpdir with `CODE_SEARCH_HOME` set via monkeypatch — never the real `~/.code-search`.
- `repo_id = hashlib.sha256(str(Path(p).resolve()).encode()).hexdigest()[:16]` — exact formula, used consistently.
- Registry/watch-table writes: write to `<file>.tmp` then `os.replace()`, under `fcntl.flock` on `<file>.lock`.
- Socket protocol: one JSON object per line (newline-delimited), UTF-8. Responses: `{"ok": true, ...}` or `{"ok": false, "error": "..."}` or `{"ok": false, "status": "warming"}`.
- Work happens on a new branch `feature/central-install` cut from `main` (the spec commits on `feature/search-usage-tracking` should be cherry-picked or the branch based off it — executor: run `git checkout -b feature/central-install` from the current branch so the spec/plan ride along).
- Commit messages: conventional commits, ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Run tests with: `.venv-code-search/bin/python3 -m pytest tests/engine/<file> -v` (this repo's dev venv has pytest; see `requirements-dev.txt`).

---

### Task 0: Branch + package scaffold + `engine/paths.py`

**Files:**
- Create: `engine/__init__.py` (empty)
- Create: `engine/paths.py`
- Create: `tests/engine/__init__.py` (empty)
- Create: `tests/engine/test_paths.py`

**Interfaces:**
- Produces: `paths.home() -> Path`, `paths.ensure_home() -> Path`, and path helpers `registry_path()`, `registry_lock_path()`, `indexes_dir()`, `index_dir(repo_id) -> Path`, `socket_path()`, `pid_path()`, `watches_path()`, `state_dir()`, `logs_dir()`, `trash_dir()`, `venv_dir()`, `venv_python()`, `venv_ok_path()` — all `Path`, all derived from `home()`.

- [ ] **Step 1: Create branch**

```bash
git checkout -b feature/central-install
```

- [ ] **Step 2: Write the failing test**

```python
# tests/engine/test_paths.py
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine'` (pytest.ini may need `pythonpath = .` — check `pytest.ini`; if rootdir already on sys.path via conftest, error will be missing `paths`).

- [ ] **Step 4: Write implementation**

```python
# engine/paths.py
"""Central data-dir layout. Stdlib only — imported by hooks without the venv."""
import os
from pathlib import Path


def home() -> Path:
    env = os.environ.get("CODE_SEARCH_HOME")
    return Path(env) if env else Path.home() / ".code-search"


def ensure_home() -> Path:
    h = home()
    for sub in ("indexes", "state", "logs", "trash"):
        (h / sub).mkdir(parents=True, exist_ok=True)
    return h


def registry_path() -> Path: return home() / "registry.json"
def registry_lock_path() -> Path: return home() / "registry.lock"
def indexes_dir() -> Path: return home() / "indexes"
def index_dir(repo_id: str) -> Path: return home() / "indexes" / repo_id
def socket_path() -> Path: return home() / "daemon.sock"
def pid_path() -> Path: return home() / "daemon.pid"
def watches_path() -> Path: return home() / "state" / "watches.json"
def state_dir() -> Path: return home() / "state"
def logs_dir() -> Path: return home() / "logs"
def trash_dir() -> Path: return home() / "trash"
def config_path() -> Path: return home() / "config.json"
def venv_dir() -> Path: return home() / "venv"
def venv_python() -> Path: return home() / "venv" / "bin" / "python3"
def venv_ok_path() -> Path: return home() / "venv.ok"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_paths.py -v`
Expected: PASS (4 tests). If import fails, add `pythonpath = .` under `[pytest]` in `pytest.ini`.

- [ ] **Step 6: Commit**

```bash
git add engine/ tests/engine/ pytest.ini
git commit -m "feat: engine package scaffold with central path layout"
```

---

### Task 1: Repo identity (`engine/repoident.py`)

**Files:**
- Create: `engine/repoident.py`
- Create: `tests/engine/test_repoident.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `repo_root(start: Path) -> Path | None` (worktree top-level, resolved), `family_root(start: Path) -> Path | None` (main repo root shared by worktrees, resolved), `repo_id(path: Path) -> str` (16-hex).

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_repoident.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_repoident.py -v`
Expected: FAIL with `No module named 'engine.repoident'`

- [ ] **Step 3: Write implementation**

```python
# engine/repoident.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_repoident.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/repoident.py tests/engine/test_repoident.py
git commit -m "feat: repo/worktree identity resolution"
```

---

### Task 2: Registry (`engine/registry.py`)

**Files:**
- Create: `engine/registry.py`
- Create: `tests/engine/test_registry.py`

**Interfaces:**
- Consumes: `engine.paths`, `engine.repoident`.
- Produces:
  - `@dataclass Resolved: family_id: str|None; repo_id: str|None; registered: bool; family_enabled: bool; main_path: str|None; bm25: bool; main_repo_id: str|None`
  - `load() -> dict` / `save(reg: dict) -> None` (atomic+flock)
  - `enable(worktree_root: Path, bm25: bool = False) -> Resolved`
  - `disable(worktree_root: Path) -> list[str]` (repo_ids whose indexes may be purged)
  - `resolve(worktree_root: Path) -> Resolved`
  - `register_worktree(worktree_root: Path) -> Resolved` (requires family enabled)
  - `gc(days: int = 7) -> list[str]` (reaped repo_ids; marks dead paths, reaps entries dead > days)

Registry JSON schema (exact):

```json
{
  "repos": {
    "<family_id>": {
      "main_path": "/abs/path",
      "enabled_at": "2026-07-07T00:00:00+00:00",
      "bm25": false,
      "worktrees": {
        "<repo_id>": {
          "path": "/abs/path",
          "last_indexed": null,
          "auto_registered": false,
          "dead_since": null
        }
      }
    }
  }
}
```

The main worktree is itself an entry in `worktrees` (its `repo_id` = `repo_id(main_path)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_registry.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_registry.py -v`
Expected: FAIL with `No module named 'engine.registry'`

- [ ] **Step 3: Write implementation**

```python
# engine/registry.py
"""Central registry of enabled repos/worktrees. Stdlib only."""
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


def save(reg: dict) -> None:
    paths.ensure_home()
    lock = paths.registry_lock_path()
    with open(lock, "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        tmp = paths.registry_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(reg, indent=2))
        os.replace(tmp, paths.registry_path())


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
    reg = load()
    fam = reg["repos"].setdefault(fam_id, {
        "main_path": str(fam_root),
        "enabled_at": _now(),
        "bm25": bm25,
        "worktrees": {},
    })
    fam["worktrees"].setdefault(rid, {
        "path": str(root), "last_indexed": None,
        "auto_registered": False, "dead_since": None,
    })
    save(reg)
    return resolve(root)


def register_worktree(worktree_root: Path) -> Resolved:
    r = resolve(worktree_root)
    if not r.family_enabled:
        raise NotEnabledError(f"family not enabled for {worktree_root}")
    if r.registered:
        return r
    reg = load()
    root = repoident.repo_root(Path(worktree_root))
    reg["repos"][r.family_id]["worktrees"][r.repo_id] = {
        "path": str(root), "last_indexed": None,
        "auto_registered": True, "dead_since": None,
    }
    save(reg)
    return resolve(root)


def disable(worktree_root: Path) -> list[str]:
    r = resolve(worktree_root)
    if not r.family_enabled:
        return []
    reg = load()
    fam = reg["repos"].pop(r.family_id)
    save(reg)
    return list(fam["worktrees"].keys())


def gc(days: int = 7) -> list[str]:
    reg = load()
    reaped = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
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
    save(reg)
    return reaped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_registry.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/registry.py tests/engine/test_registry.py
git commit -m "feat: central registry with family/worktree model and GC"
```

---

### Task 3: `RepoIndex` — root-parameterized indexing and search

This is the cwd-relativity refactor the spec calls out. It moves logic from `index_project.py` and `search_code.py` into `engine/` with explicit roots. **Copy code, don't rewrite it** — the plan below states exactly which functions move where and what changes.

**Files:**
- Create: `engine/chunker.py` — byte-for-byte copy of existing `chunker.py` (no changes; it already takes `(filepath, lines)`).
- Create: `engine/embedding.py` — move from `index_project.py`: `_maybe_enable_amd_wsl2_gpu()` (call at import), `_EMB_MODEL_CACHE`, `_CODERANK_QUERY_PREFIX`, class `HFCodeEmbeddingFunction` (lines 270–319), unchanged.
- Create: `engine/classify.py` — move from `index_project.py`: `LANG_MAP`, `_TEST_DIRS`, `_DOC_DIRS`, `_GEN_DIRS`, `_DOC_EXTS`, `classify_file`, `detect_languages`, `choose_model`, unchanged.
- Create: `engine/repo_index.py` — the parameterized core (new code below).
- Create: `tests/engine/test_repo_index.py`
- Note: existing `tests/test_chunker.py` keeps passing against old root `chunker.py` until Task 10 removes old files and repoints imports.

**Interfaces:**
- Consumes: `engine.chunker.chunk_file(filepath, lines) -> list[(start, end, text)]`, `engine.embedding.HFCodeEmbeddingFunction`, `engine.classify`.
- Produces:
  - `class RepoIndex(root: Path, index_dir: Path)`
  - `.index(use_bm25: bool = False) -> dict` — returns `{"files_scanned": int, "upserted": int, "deleted": int}`; also updates `index_dir/model.txt`, `langs.json`, optional `bm25_corpus.json`.
  - `.search(query: str, n_results=5, all_files=False, use_bm25=False) -> list[list]` — merged results `[path, start, end, text, file_type]`, paths repo-relative.
  - `.invalidate_caches() -> None` — drops cached BM25 corpus + file_type probe (called by daemon after each index pass).
  - `.count() -> int`.
  - Module fn: `clone_index(src: Path, dst: Path) -> None` (shutil.copytree; caller serializes writes).

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_repo_index.py
import pytest
from pathlib import Path
from tests.engine.test_repoident import make_repo, _git

pytestmark = pytest.mark.slow  # loads the embedding model once per session

from engine.repo_index import RepoIndex, clone_index


@pytest.fixture(scope="module")
def indexed(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ri")
    repo = make_repo(tmp)
    (repo / "auth.py").write_text(
        "def authenticate(user, password):\n    return user == 'admin'\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_auth.py").write_text(
        "def test_authenticate():\n    assert True\n")
    _git("add", ".", cwd=repo)
    idx_dir = tmp / "idx"
    ri = RepoIndex(repo, idx_dir)
    stats = ri.index()
    return repo, idx_dir, ri, stats


def test_index_reports_stats(indexed):
    _, _, _, stats = indexed
    assert stats["upserted"] > 0 and stats["deleted"] == 0


def test_search_finds_auth_with_relative_path(indexed):
    _, _, ri, _ = indexed
    results = ri.search("user authentication check")
    assert results, "expected at least one result"
    paths = [r[0] for r in results]
    assert "auth.py" in paths
    assert all(not Path(p).is_absolute() for p in paths)


def test_search_labels_file_type(indexed):
    _, _, ri, _ = indexed
    results = ri.search("test authenticate", all_files=False)
    types = {r[0]: r[4] for r in results}
    if "tests/test_auth.py" in types:
        assert types["tests/test_auth.py"] == "test"


def test_incremental_reindex_skips_unchanged(indexed):
    _, _, ri, _ = indexed
    stats2 = ri.index()
    assert stats2["upserted"] == 0 and stats2["deleted"] == 0


def test_index_never_depends_on_cwd(indexed, tmp_path, monkeypatch):
    repo, idx_dir, _, _ = indexed
    monkeypatch.chdir(tmp_path)  # anywhere but the repo
    ri = RepoIndex(repo, idx_dir)
    assert ri.search("authentication")  # works from foreign cwd


def test_clone_index_then_catch_up(indexed, tmp_path_factory):
    repo, idx_dir, _, _ = indexed
    tmp = tmp_path_factory.mktemp("clone")
    dst = tmp / "idx2"
    clone_index(idx_dir, dst)
    ri2 = RepoIndex(repo, dst)
    stats = ri2.index()  # catch-up on identical tree: nothing to do
    assert stats["upserted"] == 0 and stats["deleted"] == 0
    assert ri2.search("authentication")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_repo_index.py -v`
Expected: FAIL with `No module named 'engine.repo_index'`

- [ ] **Step 3: Create the moved modules**

Copy verbatim as listed in **Files** above:

```bash
cp chunker.py engine/chunker.py
```

`engine/embedding.py`: copy from `index_project.py` lines 10–15 (`_maybe_enable_amd_wsl2_gpu` + module-level call), line 28 (`_CODERANK_QUERY_PREFIX`), line 31 (`_EMB_MODEL_CACHE`), lines 270–319 (`HFCodeEmbeddingFunction` including `_choose_safe_batch_size`, `embed`, `__call__`). Keep the `import psutil` and `from chromadb.utils.embedding_functions import EmbeddingFunction` imports it needs.

`engine/classify.py`: copy from `index_project.py` lines 106–265 (`LANG_MAP` through `choose_model`), plus `from pathlib import Path` and `from collections import Counter`.

- [ ] **Step 4: Write `engine/repo_index.py`**

This is `index_files()` and `search()` from the old scripts with three systematic changes: (1) `CHROMA_PATH` → `self.index_dir`; (2) `git ls-files`/`open(filepath)` → `cwd=self.root` / `self.root / filepath`; (3) module-level caches → instance attrs with `invalidate_caches()`.

```python
# engine/repo_index.py
"""Root-parameterized index + search. Heavy imports allowed here."""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import chromadb

from engine.chunker import chunk_file
from engine.classify import LANG_MAP, classify_file, detect_languages, choose_model
from engine.embedding import HFCodeEmbeddingFunction

COLLECTION_NAME = "project_code"
CHROMA_MAX_BATCH = 5000
_DOC_LANGS = frozenset({"restructuredtext", "markdown"})


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokenize_for_bm25(text):
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = re.sub(r'[_\-./\\:;,|#@!?(){}\[\]<>"\'+*&^%$=~`]', ' ', text)
    return [t for t in text.lower().split() if len(t) > 1]


def _rrf_merge(semantic_ids, bm25_ids, k=60):
    scores = {}
    for rank, cid in enumerate(semantic_ids, 1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    for rank, cid in enumerate(bm25_ids, 1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda c: scores[c], reverse=True)


def merge_chunks(items):
    # copy body verbatim from search_code.py merge_chunks (lines 156-177)
    ...


def clone_index(src: Path, dst: Path) -> None:
    """Seed a new worktree index by copying an existing one. Caller must
    ensure no writer is active on src."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


class RepoIndex:
    def __init__(self, root: Path, index_dir: Path):
        self.root = Path(root).resolve()
        self.index_dir = Path(index_dir)
        self._client = None
        self._bm25 = None          # (BM25Okapi, id_list) or None
        self._bm25_loaded = False

    # -- plumbing -------------------------------------------------------
    def _chroma(self):
        if self._client is None:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.index_dir))
        return self._client

    def invalidate_caches(self):
        self._bm25 = None
        self._bm25_loaded = False

    def close(self):
        self._client = None
        self.invalidate_caches()

    def _git_files(self) -> list[str]:
        # git_indexable_files from index_project.py lines 76-97, with
        # cwd=self.root on both subprocess.run calls and no chroma_dir
        # exclusion (the index no longer lives in the repo).
        ...

    def _emb_fn(self):
        model_file = self.index_dir / "model.txt"
        name = model_file.read_text().strip() if model_file.exists() \
            else "nomic-ai/CodeRankEmbed"
        return HFCodeEmbeddingFunction(name)

    # -- index ----------------------------------------------------------
    def index(self, use_bm25: bool = False) -> dict:
        # Body is index_files() from index_project.py lines 322-460 with:
        #   CHROMA_PATH            -> self.index_dir
        #   BM25_CORPUS_PATH       -> self.index_dir / "bm25_corpus.json"
        #   git_indexable_files()  -> self._git_files()
        #   open(filepath, ...)    -> open(self.root / filepath, ...)
        #   emb_fn                 -> self._emb_fn() after writing model.txt
        #   final prints           -> return {"files_scanned": ...,
        #                                     "upserted": len(ids_to_upsert),
        #                                     "deleted": len(to_delete)}
        # _status()/_batch_upsert()/_batch_delete() copy over as module
        # functions (lines 42-73), printing to stdout is fine (daemon logs it).
        # End with: self.invalidate_caches()
        ...

    def count(self) -> int:
        try:
            return self._chroma().get_collection(COLLECTION_NAME).count()
        except Exception:
            return 0

    # -- search ---------------------------------------------------------
    def _load_bm25(self):
        if not self._bm25_loaded:
            self._bm25_loaded = True
            corpus_path = self.index_dir / "bm25_corpus.json"
            self._bm25 = None
            if corpus_path.exists():
                try:
                    from rank_bm25 import BM25Okapi
                    corpus = json.loads(corpus_path.read_text())
                    ids = list(corpus.keys())
                    self._bm25 = (BM25Okapi(
                        [_tokenize_for_bm25(corpus[c]) for c in ids]), ids)
                except Exception:
                    self._bm25 = None
        return self._bm25

    def search(self, query, n_results=5, all_files=False, use_bm25=False):
        # Body is search() from search_code.py lines 180-269 with:
        #   CHROMA_PATH -> self.index_dir; client -> self._chroma()
        #   _load_embedding_fn() -> self._emb_fn()
        #   _load_source_langs() -> inline, reading self.index_dir/"langs.json"
        #   _load_bm25() -> self._load_bm25()
        #   sys.exit(1) on missing collection -> raise IndexMissingError
        #   drop _log_search_event (daemon logs centrally, Task 4)
        # Returns merge_chunks(items) — paths are already repo-relative
        # because the indexer stores them relative.
        ...


class IndexMissingError(Exception):
    pass
```

The `...` bodies are verbatim copies from the named line ranges with the listed substitutions — the executor performs the mechanical move, not a reimplementation. `merge_chunks` copies exactly.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_repo_index.py -v`
Expected: PASS (6 tests; slow — model download on first run)

- [ ] **Step 6: Commit**

```bash
git add engine/ tests/engine/test_repo_index.py
git commit -m "feat: RepoIndex - root-parameterized index and search"
```

---

### Task 4: Watch manager + index job queue (`engine/watcher.py`)

**Files:**
- Create: `engine/watcher.py`
- Create: `tests/engine/test_watcher.py`

**Interfaces:**
- Consumes: `RepoIndex` (Task 3).
- Produces:
  - `class IndexQueue` — single worker thread; `submit(repo_id, fn)` coalesces: at most one queued job per repo_id (a submit while queued is a no-op; a submit while *running* queues one more). `stop()` joins.
  - `class RepoWatch(root: Path, on_change: Callable[[], None])` — starts a watchdog observer on `root`; debounce 1.0s; batched ignore checks; `stop()`. Chooses `PollingObserver` when `root` is on a non-inotify filesystem.
  - `should_ignore(root: Path, rel_path: str) -> bool` and `git_ignored_batch(root: Path, rel_paths: list[str]) -> set[str]`.
  - `IGNORED_DIRS = {"node_modules", "dist", "build", "target", ".git", "__pycache__", "chroma_db", ".venv", ".venv-code-search", ".tox", ".mypy_cache", ".pytest_cache"}`

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_watcher.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_watcher.py -v`
Expected: FAIL with `No module named 'engine.watcher'`

- [ ] **Step 3: Write implementation**

```python
# engine/watcher.py
"""Per-repo fs watching + single-worker index queue."""
import os
import queue
import subprocess
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

DEBOUNCE_SECONDS = 1.0
IGNORED_DIRS = {"node_modules", "dist", "build", "target", ".git",
                "__pycache__", "chroma_db", ".venv", ".venv-code-search",
                ".tox", ".mypy_cache", ".pytest_cache"}


def should_ignore(root: Path, rel_path: str) -> bool:
    return any(part in IGNORED_DIRS for part in Path(rel_path).parts)


def git_ignored_batch(root: Path, rel_paths: list[str]) -> set[str]:
    """One `git check-ignore --stdin` call for the whole batch."""
    if not rel_paths:
        return set()
    try:
        r = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            input="\n".join(rel_paths), capture_output=True,
            text=True, cwd=root, timeout=10)
        return set(r.stdout.splitlines())
    except (OSError, subprocess.TimeoutExpired):
        return set()


def _needs_polling(root: Path) -> bool:
    """True for filesystems where inotify is silent (WSL2 drvfs/9p)."""
    try:
        with open("/proc/mounts") as f:
            mounts = [line.split() for line in f]
    except OSError:
        return False
    best = ("", "")
    for parts in mounts:
        if len(parts) >= 3 and str(root).startswith(parts[1]) \
                and len(parts[1]) > len(best[0]):
            best = (parts[1], parts[2])
    return best[1] in ("9p", "drvfs", "cifs", "nfs", "fuse.drvfs")


class IndexQueue:
    """Single worker; per-repo coalescing so N repos can't starve search."""

    def __init__(self):
        self._q = queue.Queue()
        self._pending = set()
        self._lock = threading.Lock()
        self._stop = object()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, repo_id: str, fn):
        with self._lock:
            if repo_id in self._pending:
                return
            self._pending.add(repo_id)
        self._q.put((repo_id, fn))

    def _run(self):
        while True:
            item = self._q.get()
            if item is self._stop:
                return
            repo_id, fn = item
            with self._lock:
                self._pending.discard(repo_id)
            try:
                fn()
            except Exception as e:
                print(f"[index-queue] {repo_id}: {type(e).__name__}: {e}",
                      flush=True)

    def stop(self):
        self._q.put(self._stop)
        self._worker.join(timeout=10)


class _Handler(FileSystemEventHandler):
    def __init__(self, watch):
        self._w = watch

    def on_any_event(self, event):
        if event.is_directory or event.event_type in ("opened", "closed_no_write"):
            return
        try:
            rel = str(Path(event.src_path).resolve()
                      .relative_to(self._w.root))
        except ValueError:
            return
        if should_ignore(self._w.root, rel):
            return
        self._w._enqueue(rel)


class RepoWatch:
    def __init__(self, root: Path, on_change):
        self.root = Path(root).resolve()
        self._on_change = on_change
        self._batch: list[str] = []
        self._timer = None
        self._lock = threading.Lock()
        cls = PollingObserver if _needs_polling(self.root) else Observer
        self._observer = cls()
        self._observer.schedule(_Handler(self), path=str(self.root),
                                recursive=True)
        self._observer.start()

    def _enqueue(self, rel_path: str):
        with self._lock:
            self._batch.append(rel_path)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self):
        with self._lock:
            batch, self._batch = self._batch, []
        ignored = git_ignored_batch(self.root, batch)
        if any(p not in ignored for p in batch):
            self._on_change()

    def stop(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
        self._observer.stop()
        self._observer.join(timeout=5)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_watcher.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/watcher.py tests/engine/test_watcher.py
git commit -m "feat: repo watcher with batched ignore checks and index queue"
```

---

### Task 5: Daemon (`engine/daemon.py`)

**Files:**
- Create: `engine/daemon.py`
- Create: `tests/engine/test_daemon.py`

**Interfaces:**
- Consumes: `paths`, `registry`, `repoident`, `RepoIndex`/`clone_index`/`IndexMissingError`, `IndexQueue`, `RepoWatch`.
- Produces: `python3 -m engine.daemon` entrypoint. Socket protocol (newline-delimited JSON):
  - `{"cmd": "ping"}` → `{"ok": true, "pid": <int>}`
  - `{"cmd": "watch", "repo": "/abs/path", "session_pid": <int>}` → `{"ok": true, "repo_id": "..."}` — resolves/auto-registers worktree (via `registry.register_worktree`), seeds index from main worktree's index if absent and main's exists (`clone_index`), queues catch-up index, starts `RepoWatch`, refcounts by `(repo_id, session_pid)`. Unknown/not-enabled repo → `{"ok": false, "error": "not enabled"}`.
  - `{"cmd": "unwatch", "repo": "/abs/path", "session_pid": <int>}` → `{"ok": true}`
  - `{"cmd": "search", "repo": "/abs/path", "query": "...", "n_results": 5, "all_files": false, "use_bm25": false}` → `{"ok": true, "results": [[path, start, end, text, file_type], ...]}`; while the embedding model is loading in another thread → `{"ok": false, "status": "warming"}`; no index yet → also `warming` (catch-up queued).
  - `{"cmd": "reindex", "repo": "/abs/path"}` → `{"ok": true}` (queued)
  - `{"cmd": "status"}` → `{"ok": true, "watched": {...}, "uptime_s": ..., "queue_pending": [...]}`
  - `{"cmd": "shutdown"}` → `{"ok": true}` then clean exit (used by tests).
- Lifecycle produced for later tasks: flock singleton on `paths.pid_path()` (reuse pattern of `watch_index.acquire_pid_lock` — copy that function into `engine/daemon.py`), socket bound at temp path then `os.rename` onto `paths.socket_path()`, watch table persisted to `paths.watches_path()` on every change and restored on start (dead pids skipped, catch-up queued for restored), dead-session pruning every 60s, idle exit after `IDLE_EXIT_SECONDS = 600` with no watches, search-usage JSONL logging to `paths.logs_dir()/"search_usage.jsonl"` with `repo_id` and rotation at 10 MB (rename to `.1`).

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_daemon.py
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import pytest
from engine import paths
from tests.engine.test_repoident import make_repo, _git

pytestmark = pytest.mark.slow


def _req(payload, timeout=120.0):
    """Send one request; retry through 'warming' responses."""
    deadline = time.time() + timeout
    while True:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(paths.socket_path()))
            s.sendall(json.dumps(payload).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        resp = json.loads(buf.split(b"\n")[0])
        if resp.get("status") == "warming" and time.time() < deadline:
            time.sleep(1.0)
            continue
        return resp


@pytest.fixture
def daemon(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    env = dict(os.environ, CODE_SEARCH_HOME=str(tmp_path / "csh"),
               PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    proc = subprocess.Popen([sys.executable, "-m", "engine.daemon"], env=env)
    deadline = time.time() + 30
    while not paths.socket_path().exists():
        assert time.time() < deadline, "daemon socket never appeared"
        assert proc.poll() is None, "daemon died on startup"
        time.sleep(0.2)
    yield proc
    try:
        _req({"cmd": "shutdown"}, timeout=10)
    except OSError:
        pass
    proc.wait(timeout=15)


def test_ping(daemon):
    assert _req({"cmd": "ping"})["ok"]


def test_watch_requires_enabled_repo(daemon, tmp_path):
    repo = make_repo(tmp_path)
    r = _req({"cmd": "watch", "repo": str(repo), "session_pid": os.getpid()})
    assert not r["ok"] and "not enabled" in r["error"]


def test_watch_index_search_unwatch(daemon, tmp_path):
    from engine import registry
    repo = make_repo(tmp_path)
    (repo / "auth.py").write_text("def authenticate(u, p):\n    return True\n")
    _git("add", ".", cwd=repo)
    registry.enable(repo)
    r = _req({"cmd": "watch", "repo": str(repo), "session_pid": os.getpid()})
    assert r["ok"]
    res = _req({"cmd": "search", "repo": str(repo),
                "query": "authentication", "n_results": 5})
    assert res["ok"] and any("auth.py" in row[0] for row in res["results"])
    st = _req({"cmd": "status"})
    assert st["ok"] and len(st["watched"]) == 1
    assert _req({"cmd": "unwatch", "repo": str(repo),
                 "session_pid": os.getpid()})["ok"]


def test_watch_table_persisted(daemon, tmp_path):
    from engine import registry
    repo = make_repo(tmp_path)
    registry.enable(repo)
    _req({"cmd": "watch", "repo": str(repo), "session_pid": os.getpid()})
    table = json.loads(paths.watches_path().read_text())
    assert any(w["path"] == str(repo.resolve()) for w in table["watches"])


def test_singleton_second_daemon_exits(daemon, tmp_path):
    env = dict(os.environ, CODE_SEARCH_HOME=os.environ["CODE_SEARCH_HOME"],
               PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    p2 = subprocess.Popen([sys.executable, "-m", "engine.daemon"], env=env)
    assert p2.wait(timeout=15) == 0  # loser exits cleanly, does NOT touch socket
    assert _req({"cmd": "ping"})["ok"]  # original still serving
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_daemon.py -v`
Expected: FAIL (`No module named engine.daemon` when subprocess starts → socket never appears)

- [ ] **Step 3: Write implementation**

```python
# engine/daemon.py
"""Multiplexed search daemon. One per CODE_SEARCH_HOME."""
import fcntl
import json
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from engine import paths, registry, repoident
from engine.repo_index import RepoIndex, clone_index, IndexMissingError
from engine.watcher import IndexQueue, RepoWatch

IDLE_EXIT_SECONDS = 600
PRUNE_INTERVAL = 60
LOG_ROTATE_BYTES = 10 * 1024 * 1024


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_pid_lock(pid_file: Path):
    """flock singleton — copied pattern from watch_index.py."""
    try:
        fh = open(pid_file, "a")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.seek(0); fh.truncate(); fh.write(str(os.getpid())); fh.flush()
        return fh
    except OSError:
        try:
            fh.close()
        except Exception:
            pass
        return None


class Daemon:
    def __init__(self):
        self.started = time.time()
        self.lock = threading.Lock()          # guards watches/indexes dicts
        self.watches = {}    # repo_id -> {"path", "sessions": set[int], "watch": RepoWatch}
        self.indexes = {}    # repo_id -> RepoIndex
        self.queue = IndexQueue()
        self.model_ready = threading.Event()
        self.model_loading = False
        self.shutting_down = threading.Event()

    # ---- model warmup ------------------------------------------------
    def _ensure_model_async(self):
        with self.lock:
            if self.model_ready.is_set() or self.model_loading:
                return
            self.model_loading = True

        def load():
            from engine.embedding import HFCodeEmbeddingFunction
            HFCodeEmbeddingFunction("nomic-ai/CodeRankEmbed")
            self.model_ready.set()
        threading.Thread(target=load, daemon=True).start()

    # ---- watch table persistence --------------------------------------
    def _persist_watches(self):
        data = {"watches": [
            {"repo_id": rid, "path": w["path"],
             "sessions": sorted(w["sessions"])}
            for rid, w in self.watches.items()]}
        tmp = paths.watches_path().with_suffix(".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data))
        os.replace(tmp, paths.watches_path())

    def restore_watches(self):
        try:
            data = json.loads(paths.watches_path().read_text())
        except (OSError, json.JSONDecodeError):
            return
        for w in data.get("watches", []):
            live = [p for p in w["sessions"] if _pid_alive(p)]
            if live and Path(w["path"]).exists():
                for pid in live:
                    self._watch(w["path"], pid)

    # ---- repo helpers --------------------------------------------------
    def _repo_index(self, rid: str, root: Path) -> RepoIndex:
        if rid not in self.indexes:
            self.indexes[rid] = RepoIndex(root, paths.index_dir(rid))
        return self.indexes[rid]

    def _queue_index(self, rid: str, root: Path, bm25: bool):
        ri = self._repo_index(rid, root)
        def job():
            self.model_ready.wait()
            ri.index(use_bm25=bm25)
            ri.invalidate_caches()
        self.queue.submit(rid, job)

    # ---- commands -------------------------------------------------------
    def cmd_watch(self, req):
        root = Path(req["repo"])
        r = registry.resolve(root)
        if not r.family_enabled:
            return {"ok": False, "error": "not enabled"}
        if not r.registered:
            r = registry.register_worktree(root)
            # seed from main worktree's index if it exists
            main_idx = paths.index_dir(r.main_repo_id)
            my_idx = paths.index_dir(r.repo_id)
            if r.main_repo_id != r.repo_id and main_idx.exists() \
                    and not my_idx.exists():
                clone_index(main_idx, my_idx)
        self._ensure_model_async()
        pid = int(req["session_pid"])
        resolved_root = repoident.repo_root(root)
        with self.lock:
            w = self.watches.get(r.repo_id)
            if w is None:
                watch = RepoWatch(resolved_root, on_change=lambda rid=r.repo_id,
                                  rr=resolved_root, b=r.bm25:
                                  self._queue_index(rid, rr, b))
                w = {"path": str(resolved_root), "sessions": set(),
                     "watch": watch}
                self.watches[r.repo_id] = w
            w["sessions"].add(pid)
            self._persist_watches()
        self._queue_index(r.repo_id, resolved_root, r.bm25)  # catch-up
        return {"ok": True, "repo_id": r.repo_id}

    def cmd_unwatch(self, req):
        root = Path(req["repo"])
        rid = repoident.repo_id(repoident.repo_root(root) or root)
        pid = int(req["session_pid"])
        with self.lock:
            w = self.watches.get(rid)
            if w:
                w["sessions"].discard(pid)
                if not w["sessions"]:
                    w["watch"].stop()
                    del self.watches[rid]
                    ri = self.indexes.pop(rid, None)
                    if ri:
                        ri.close()
                self._persist_watches()
        return {"ok": True}

    def cmd_search(self, req):
        root = Path(req["repo"])
        r = registry.resolve(root)
        if not r.family_enabled or not r.registered:
            return {"ok": False, "error": "not enabled"}
        self._ensure_model_async()
        if not self.model_ready.is_set():
            return {"ok": False, "status": "warming"}
        ri = self._repo_index(r.repo_id, repoident.repo_root(root))
        t0 = time.time()
        try:
            results = ri.search(
                req["query"], n_results=req.get("n_results", 5),
                all_files=req.get("all_files", False),
                use_bm25=req.get("use_bm25", False))
        except IndexMissingError:
            return {"ok": False, "status": "warming"}
        self._log_search(r.repo_id, req, results, time.time() - t0)
        return {"ok": True, "results": results}

    def cmd_reindex(self, req):
        root = Path(req["repo"])
        r = registry.resolve(root)
        if not r.registered:
            return {"ok": False, "error": "not enabled"}
        self._ensure_model_async()
        self._queue_index(r.repo_id, repoident.repo_root(root), r.bm25)
        return {"ok": True}

    def cmd_status(self, req):
        with self.lock:
            watched = {rid: {"path": w["path"],
                             "sessions": sorted(w["sessions"])}
                       for rid, w in self.watches.items()}
        return {"ok": True, "watched": watched,
                "uptime_s": int(time.time() - self.started)}

    # ---- logging --------------------------------------------------------
    def _log_search(self, rid, req, results, secs):
        log = paths.logs_dir() / "search_usage.jsonl"
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            if log.exists() and log.stat().st_size > LOG_ROTATE_BYTES:
                os.replace(log, log.with_suffix(".jsonl.1"))
            event = {"timestamp": datetime.now(timezone.utc).isoformat(),
                     "event_type": "search", "repo_id": rid,
                     "query": req["query"],
                     "result_count": len(results),
                     "latency_ms": int(secs * 1000),
                     "use_bm25": req.get("use_bm25", False),
                     "session_id": req.get("session_id", "unknown")}
            with log.open("a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            pass

    # ---- housekeeping -----------------------------------------------------
    def prune_loop(self):
        idle_since = time.time()
        while not self.shutting_down.wait(PRUNE_INTERVAL):
            with self.lock:
                for rid in list(self.watches):
                    w = self.watches[rid]
                    w["sessions"] = {p for p in w["sessions"] if _pid_alive(p)}
                    if not w["sessions"]:
                        w["watch"].stop()
                        del self.watches[rid]
                        ri = self.indexes.pop(rid, None)
                        if ri:
                            ri.close()
                self._persist_watches()
                empty = not self.watches
            if empty:
                if time.time() - idle_since > IDLE_EXIT_SECONDS:
                    self.shutting_down.set()
            else:
                idle_since = time.time()

    # ---- request dispatch --------------------------------------------------
    def handle(self, req: dict) -> dict:
        cmd = req.get("cmd")
        fn = getattr(self, f"cmd_{cmd}", None)
        if cmd == "shutdown":
            self.shutting_down.set()
            return {"ok": True}
        if fn is None:
            return {"ok": False, "error": f"unknown cmd: {cmd}"}
        try:
            return fn(req)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _serve(daemon: Daemon, srv: socket.socket):
    srv.settimeout(1.0)
    while not daemon.shutting_down.is_set():
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        threading.Thread(target=_handle_conn, args=(daemon, conn),
                         daemon=True).start()


def _handle_conn(daemon, conn):
    with conn:
        conn.settimeout(30.0)
        buf = b""
        try:
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
            req = json.loads(buf.split(b"\n")[0])
            resp = daemon.handle(req)
            conn.sendall(json.dumps(resp).encode() + b"\n")
        except (OSError, json.JSONDecodeError):
            pass


def main():
    paths.ensure_home()
    lock_fh = acquire_pid_lock(paths.pid_path())
    if lock_fh is None:
        sys.exit(0)   # another daemon holds the lock; never touch its socket

    daemon = Daemon()
    sock_final = paths.socket_path()
    sock_tmp = sock_final.with_suffix(f".tmp{os.getpid()}")
    for p in (sock_tmp,):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock_tmp))
    srv.listen(64)
    os.rename(sock_tmp, sock_final)   # atomic claim — no unlink-before-bind race

    def _term(signum=None, frame=None):
        daemon.shutting_down.set()
    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)

    daemon.restore_watches()
    pruner = threading.Thread(target=daemon.prune_loop, daemon=True)
    pruner.start()

    _serve(daemon, srv)

    # shutdown order: unlink socket -> stop watches -> persist -> release lock
    try:
        os.unlink(sock_final)
    except FileNotFoundError:
        pass
    with daemon.lock:
        for w in daemon.watches.values():
            w["watch"].stop()
        daemon._persist_watches()
    daemon.queue.stop()
    lock_fh.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_daemon.py -v`
Expected: PASS (5 tests; slow)

- [ ] **Step 5: Commit**

```bash
git add engine/daemon.py tests/engine/test_daemon.py
git commit -m "feat: multiplexed daemon with flock singleton and persisted watches"
```

---

### Task 6: Client (`engine/client.py`)

**Files:**
- Create: `engine/client.py`
- Create: `tests/engine/test_client.py`

**Interfaces:**
- Consumes: `paths`, daemon protocol (Task 5). **Stdlib only** (hooks import it).
- Produces:
  - `request(payload: dict, timeout: float = 30.0) -> dict` — one socket round-trip; raises `DaemonUnavailable` on connect failure.
  - `ensure_daemon() -> bool` — ping; on failure spawn `paths.venv_python() -m engine.daemon` detached (`start_new_session=True`, stdout/stderr to `paths.logs_dir()/"daemon.log"`, env `PYTHONPATH` = plugin root = `Path(__file__).resolve().parents[1]`), then ping-retry up to 15s. Returns False if venv python missing.
  - `search(repo: str, query: str, n_results=5, all_files=False, use_bm25=False, session_id="unknown", warm_deadline=300.0) -> dict` — ensure_daemon, then request; on `warming` sleep 2s and retry until deadline; on `DaemonUnavailable` re-ensure and retry (max 3 spawns). **No in-process fallback.**
  - `watch(repo: str, session_pid: int) -> dict`, `unwatch(...)`, `status()` — thin wrappers with `ensure_daemon()` for `watch`/`status` (`unwatch` best-effort: swallow `DaemonUnavailable`, never spawns).
  - `class DaemonUnavailable(Exception)`

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_client.py
import json
import os
import socket
import threading
import pytest
from engine import client, paths


@pytest.fixture(autouse=True)
def csh(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    paths.ensure_home()


def fake_daemon(responses):
    """Serve canned responses on the real socket path; returns stop()."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(paths.socket_path()))
    srv.listen(8)
    srv.settimeout(5)
    stop_flag = threading.Event()

    def run():
        i = 0
        while not stop_flag.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            with conn:
                conn.recv(65536)
                resp = responses[min(i, len(responses) - 1)]
                i += 1
                conn.sendall(json.dumps(resp).encode() + b"\n")
    t = threading.Thread(target=run, daemon=True)
    t.start()

    def stop():
        stop_flag.set()
        srv.close()
    return stop


def test_request_round_trip():
    stop = fake_daemon([{"ok": True, "pid": 1}])
    try:
        assert client.request({"cmd": "ping"})["ok"]
    finally:
        stop()


def test_request_raises_when_no_daemon():
    with pytest.raises(client.DaemonUnavailable):
        client.request({"cmd": "ping"})


def test_search_retries_through_warming(monkeypatch):
    monkeypatch.setattr(client, "ensure_daemon", lambda: True)
    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    stop = fake_daemon([
        {"ok": False, "status": "warming"},
        {"ok": False, "status": "warming"},
        {"ok": True, "results": [["a.py", 1, 2, "x", "prod"]]},
    ])
    try:
        r = client.search("/repo", "query")
        assert r["ok"] and r["results"][0][0] == "a.py"
    finally:
        stop()


def test_ensure_daemon_false_without_venv():
    # venv_python() does not exist in the tmp CODE_SEARCH_HOME
    assert client.ensure_daemon() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_client.py -v`
Expected: FAIL with `No module named 'engine.client'`

- [ ] **Step 3: Write implementation**

```python
# engine/client.py
"""Socket client for the daemon. Stdlib only — used by hooks."""
import json
import os
import socket
import subprocess
import time
from pathlib import Path

from engine import paths

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


class DaemonUnavailable(Exception):
    pass


def request(payload: dict, timeout: float = 30.0) -> dict:
    sp = paths.socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(sp))
            s.sendall(json.dumps(payload).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.split(b"\n")[0])
    except (OSError, json.JSONDecodeError) as e:
        raise DaemonUnavailable(str(e))


def ensure_daemon() -> bool:
    try:
        if request({"cmd": "ping"}, timeout=3.0).get("ok"):
            return True
    except DaemonUnavailable:
        pass
    py = paths.venv_python()
    if not py.exists():
        return False
    paths.ensure_home()
    log = open(paths.logs_dir() / "daemon.log", "a")
    env = dict(os.environ, PYTHONPATH=str(PLUGIN_ROOT))
    subprocess.Popen([str(py), "-m", "engine.daemon"], env=env,
                     stdout=log, stderr=subprocess.STDOUT,
                     start_new_session=True)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if request({"cmd": "ping"}, timeout=2.0).get("ok"):
                return True
        except DaemonUnavailable:
            time.sleep(0.3)
    return False


def search(repo, query, n_results=5, all_files=False, use_bm25=False,
           session_id="unknown", warm_deadline=300.0):
    payload = {"cmd": "search", "repo": str(repo), "query": query,
               "n_results": n_results, "all_files": all_files,
               "use_bm25": use_bm25, "session_id": session_id}
    spawns = 0
    deadline = time.time() + warm_deadline
    while True:
        try:
            resp = request(payload, timeout=60.0)
        except DaemonUnavailable:
            spawns += 1
            if spawns > 3 or not ensure_daemon():
                raise
            continue
        if resp.get("status") == "warming" and time.time() < deadline:
            time.sleep(2.0)
            continue
        return resp


def watch(repo, session_pid):
    if not ensure_daemon():
        raise DaemonUnavailable("venv missing — run: code-search setup")
    return request({"cmd": "watch", "repo": str(repo),
                    "session_pid": session_pid}, timeout=30.0)


def unwatch(repo, session_pid):
    try:
        return request({"cmd": "unwatch", "repo": str(repo),
                        "session_pid": session_pid}, timeout=5.0)
    except DaemonUnavailable:
        return {"ok": False, "error": "daemon not running"}


def status():
    if not ensure_daemon():
        raise DaemonUnavailable("venv missing — run: code-search setup")
    return request({"cmd": "status"}, timeout=10.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_client.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/client.py tests/engine/test_client.py
git commit -m "feat: stdlib daemon client with warming retry, no in-process fallback"
```

---

### Task 7: Migration (`engine/migrate.py`)

**Files:**
- Create: `engine/migrate.py`
- Create: `tests/engine/test_migrate.py`

**Interfaces:**
- Consumes: `paths` (trash dir), `repoident` (repo_id for trash subdir). **Stdlib only.**
- Produces:
  - `detect_old_install(repo: Path) -> bool` — positive evidence only: `.code-search-version` exists, OR `chroma_db/model.txt` exists (installer-created index marker).
  - `migrate(repo: Path, dry_run: bool = False) -> dict` — report `{"evidence": bool, "trashed": [...], "skipped_tracked": [...], "settings_cleaned": bool, "claude_md_cleaned": bool, "gitignore_cleaned": [...], "killed": [...]}`. No evidence → all-empty report, touches nothing.

Exact behavior (from spec):
- `OLD_FILES = ["index_project.py", "search_code.py", "watch_index.py", "chunker.py", "search_server.py", "migrate_add_file_type.py", "hooks/post_search_code.sh", "hooks/pre_read_grep_glob.sh", ".venv-code-search", "chroma_db", ".watch_index.log", ".watch_index.pid", ".search_server.pid", ".code-search-version"]`
- A path is trashed only if `git -C repo ls-files --error-unmatch <path>` FAILS (untracked). Tracked → `skipped_tracked`. Directories: check every tracked file under them (`git ls-files <dir>` non-empty → skip whole dir).
- Trash = `shutil.move` to `paths.trash_dir()/<repo_id>/<name>`; `hooks/` dir removed only if empty after.
- Kill: read `.watch_index.pid` / `.search_server.pid`; verify `/proc/<pid>/cmdline` contains the script name before `os.kill(pid, signal.SIGTERM)`.
- `.claude/CLAUDE.md`: remove text between `## Precision Protocol` header and next `##` header (or EOF); the sentinel line is `**Rule:** Before using` (present in both installed variants). Delete file if only whitespace remains.
- `.claude/settings.local.json`: remove any hook entry (both shapes: top-level event keys and nested under `"hooks"`) whose command contains one of `search_code.py`, `watch_index.py`, `pre_read_grep_glob`, `post_search_code`; delete `searchUsageTracking` key; delete file if `{}` remains.
- `.gitignore`: remove ONLY lines exactly matching (after strip): `chroma_db/`, `.venv-code-search/`, `.watch_index.log`, `.watch_index.pid`, `.search_server.pid`, `.code-search-version`. Never touch `.venv/`, `__pycache__/`, `.claude/settings.local.json`, `.claude/CLAUDE.md`.
- `dry_run=True`: full report, zero filesystem changes.

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_migrate.py
import json
from pathlib import Path
import pytest
from engine import migrate, paths
from tests.engine.test_repoident import make_repo, _git


@pytest.fixture(autouse=True)
def csh(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    paths.ensure_home()


def old_install(repo: Path):
    """Simulate an old per-repo install (all artifacts untracked)."""
    for f in ["index_project.py", "search_code.py", "watch_index.py",
              "chunker.py", "search_server.py"]:
        (repo / f).write_text("# installed copy\n")
    (repo / "hooks").mkdir(exist_ok=True)
    (repo / "hooks" / "post_search_code.sh").write_text("#!/bin/bash\n")
    (repo / "hooks" / "pre_read_grep_glob.sh").write_text("#!/bin/bash\n")
    (repo / "chroma_db").mkdir()
    (repo / "chroma_db" / "model.txt").write_text("nomic-ai/CodeRankEmbed")
    (repo / ".code-search-version").write_text("v1.2.0")
    (repo / ".gitignore").write_text(
        "chroma_db/\n.venv-code-search/\n.venv/\n__pycache__/\n"
        ".watch_index.log\n.claude/settings.local.json\n.claude/CLAUDE.md\n")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "CLAUDE.md").write_text(
        "## Precision Protocol\n\n**Rule:** Before using `Read`...\n\nstuff\n")
    (repo / ".claude" / "settings.local.json").write_text(json.dumps({
        "hooks": {"UserPromptSubmit": [{"hooks": [
            {"type": "command",
             "command": "/abs/path/.venv-code-search/bin/python3 watch_index.py"}]}]},
        "searchUsageTracking": {"warningsVisible": False},
        "permissions": {"allow": ["Bash(ls:*)"]},
    }))


def test_no_evidence_touches_nothing(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "chroma_db").mkdir()          # user's own chroma app, no model.txt
    (repo / "chroma_db" / "data.bin").write_text("theirs")
    report = migrate.migrate(repo)
    assert not report["evidence"]
    assert (repo / "chroma_db" / "data.bin").exists()


def test_full_migration(tmp_path):
    repo = make_repo(tmp_path)
    old_install(repo)
    report = migrate.migrate(repo)
    assert report["evidence"]
    assert not (repo / "search_code.py").exists()
    assert not (repo / "chroma_db").exists()
    assert not (repo / "hooks").exists()          # emptied then removed
    # trashed, not destroyed
    trash = paths.trash_dir()
    assert any(trash.rglob("search_code.py"))
    # gitignore: tool lines gone, generic lines kept
    gi = (repo / ".gitignore").read_text()
    assert "chroma_db/" not in gi and ".venv-code-search/" not in gi
    assert ".venv/" in gi and "__pycache__/" in gi
    assert ".claude/settings.local.json" in gi
    # settings: our hooks gone, user's permissions kept
    settings = json.loads((repo / ".claude" / "settings.local.json").read_text())
    assert "searchUsageTracking" not in settings
    assert settings["permissions"]["allow"] == ["Bash(ls:*)"]
    assert not settings.get("hooks", {}).get("UserPromptSubmit")
    # CLAUDE.md protocol block gone (file deleted since nothing else in it)
    assert not (repo / ".claude" / "CLAUDE.md").exists()


def test_tracked_files_skipped(tmp_path):
    repo = make_repo(tmp_path)
    old_install(repo)
    _git("add", "search_code.py", cwd=repo)
    _git("-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-m", "committed the script", cwd=repo)
    report = migrate.migrate(repo)
    assert "search_code.py" in report["skipped_tracked"]
    assert (repo / "search_code.py").exists()
    assert not (repo / "watch_index.py").exists()  # untracked ones still go


def test_dry_run_changes_nothing(tmp_path):
    repo = make_repo(tmp_path)
    old_install(repo)
    report = migrate.migrate(repo, dry_run=True)
    assert report["evidence"] and report["trashed"]
    assert (repo / "search_code.py").exists()
    assert (repo / "chroma_db").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_migrate.py -v`
Expected: FAIL with `No module named 'engine.migrate'`

- [ ] **Step 3: Write implementation**

Write `engine/migrate.py` implementing exactly the behavior specified in **Interfaces** above. Structure:

```python
# engine/migrate.py
"""Old per-repo install cleanup. Stdlib only. Every removal is a move to trash."""
import json
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path

from engine import paths, repoident

OLD_FILES = [
    "index_project.py", "search_code.py", "watch_index.py", "chunker.py",
    "search_server.py", "migrate_add_file_type.py",
    "hooks/post_search_code.sh", "hooks/pre_read_grep_glob.sh",
    ".venv-code-search", "chroma_db", ".watch_index.log",
    ".watch_index.pid", ".search_server.pid", ".code-search-version",
]
GITIGNORE_TOOL_LINES = {
    "chroma_db/", ".venv-code-search/", ".watch_index.log",
    ".watch_index.pid", ".search_server.pid", ".code-search-version",
}
HOOK_MARKERS = ("search_code.py", "watch_index.py",
                "pre_read_grep_glob", "post_search_code")
PID_FILES = {".watch_index.pid": "watch_index.py",
             ".search_server.pid": "search_server.py"}


def detect_old_install(repo: Path) -> bool:
    return (repo / ".code-search-version").exists() or \
           (repo / "chroma_db" / "model.txt").exists()


def _is_tracked(repo: Path, rel: str) -> bool:
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "--", rel],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


def _kill_old_processes(repo: Path, dry_run: bool) -> list[int]:
    killed = []
    for pidfile, script in PID_FILES.items():
        p = repo / pidfile
        if not p.exists():
            continue
        try:
            pid = int(p.read_text().strip())
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(
                errors="replace")
        except (ValueError, OSError):
            continue
        if script in cmdline:
            if not dry_run:
                os.kill(pid, signal.SIGTERM)
            killed.append(pid)
    return killed


def _clean_claude_md(repo: Path, dry_run: bool) -> bool:
    p = repo / ".claude" / "CLAUDE.md"
    if not p.exists():
        return False
    text = p.read_text()
    if "**Rule:** Before using" not in text:
        return False
    # drop from '## Precision Protocol' up to the next '## ' or EOF
    new = re.sub(r"## Precision Protocol.*?(?=\n## |\Z)", "", text,
                 flags=re.DOTALL)
    if dry_run:
        return True
    if new.strip():
        p.write_text(new)
    else:
        p.unlink()
    return True


def _clean_settings(repo: Path, dry_run: bool) -> bool:
    p = repo / ".claude" / "settings.local.json"
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return False

    def is_ours(entry) -> bool:
        return any(m in json.dumps(entry) for m in HOOK_MARKERS)

    changed = data.pop("searchUsageTracking", None) is not None
    for container in (data, data.get("hooks", {})):
        for event in list(container):
            if event in ("UserPromptSubmit", "PreToolUse", "PostToolUse"):
                kept = [e for e in container[event] if not is_ours(e)]
                if len(kept) != len(container[event]):
                    changed = True
                if kept:
                    container[event] = kept
                else:
                    del container[event]
    if data.get("hooks") == {}:
        del data["hooks"]
    if not changed:
        return False
    if not dry_run:
        if data:
            p.write_text(json.dumps(data, indent=2))
        else:
            p.unlink()
    return True


def _clean_gitignore(repo: Path, dry_run: bool) -> list[str]:
    p = repo / ".gitignore"
    if not p.exists():
        return []
    lines = p.read_text().splitlines()
    kept = [l for l in lines if l.strip() not in GITIGNORE_TOOL_LINES]
    removed = [l.strip() for l in lines if l.strip() in GITIGNORE_TOOL_LINES]
    if removed and not dry_run:
        p.write_text("\n".join(kept) + ("\n" if kept else ""))
    return removed


def migrate(repo: Path, dry_run: bool = False) -> dict:
    repo = Path(repo).resolve()
    report = {"evidence": False, "trashed": [], "skipped_tracked": [],
              "settings_cleaned": False, "claude_md_cleaned": False,
              "gitignore_cleaned": [], "killed": []}
    if not detect_old_install(repo):
        return report
    report["evidence"] = True
    report["killed"] = _kill_old_processes(repo, dry_run)

    trash = paths.trash_dir() / repoident.repo_id(repo)
    for rel in OLD_FILES:
        target = repo / rel
        if not target.exists():
            continue
        if _is_tracked(repo, rel):
            report["skipped_tracked"].append(rel)
            continue
        report["trashed"].append(rel)
        if not dry_run:
            dest = trash / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
            shutil.move(str(target), str(dest))
    hooks_dir = repo / "hooks"
    if not dry_run and hooks_dir.is_dir() and not any(hooks_dir.iterdir()):
        hooks_dir.rmdir()

    report["claude_md_cleaned"] = _clean_claude_md(repo, dry_run)
    report["settings_cleaned"] = _clean_settings(repo, dry_run)
    report["gitignore_cleaned"] = _clean_gitignore(repo, dry_run)
    return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_migrate.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/migrate.py tests/engine/test_migrate.py
git commit -m "feat: evidence-gated, git-aware, trash-based migration"
```

---

### Task 8: Venv setup + CLI (`engine/setup_venv.py`, `engine/cli.py`, `bin/code-search`)

**Files:**
- Create: `engine/setup_venv.py`
- Create: `engine/cli.py`
- Create: `engine/requirements.txt`
- Create: `bin/code-search` (mode 755)
- Create: `tests/engine/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `engine/requirements.txt` — copy the runtime dep pins currently listed in `install.sh`'s pip install step (chromadb, sentence-transformers, watchdog, rank_bm25, psutil, `tree-sitter<0.22` if present — executor: read `install.sh` lines ~90–120 and copy the exact pin set).
  - `setup_venv.main()` — stdlib only, runs under ANY python3: flock on `$CODE_SEARCH_HOME/setup.lock`; `python3 -m venv venv` if missing; `venv/bin/pip install -r engine/requirements.txt`; on success write `venv.ok` containing `sha256(requirements.txt bytes)`; on failure exit non-zero, no `venv.ok`. `venv_ok() -> bool` helper checks marker matches current requirements hash.
  - `cli.main(argv)` — subcommands:
    - `search <query...> [--top N] [--bm25] [--all]` — repo root from cwd via `repoident.repo_root`; `client.search`; print results in the exact current format (`MATCH i: path [type] (lines a-b)` — copy `format_results` from `search_code.py` lines 272–285); exit 2 on no results, exit 1 with actionable message on `DaemonUnavailable`/not-enabled.
    - `enable [--bm25] [--dry-run]` — `setup` if `venv.ok` stale → `migrate.migrate(root, dry_run)` (print report) → `registry.enable` → `client.watch` (triggers first index) → print summary.
    - `disable [--purge]` — `registry.disable`; unwatch; `--purge` deletes each returned repo_id's index dir.
    - `status` — registry entries with dead-path flags + `client.status()` daemon info (tolerate daemon down).
    - `reindex` — `client.request({"cmd": "reindex", ...})`.
    - `gc` — `registry.gc()` + delete reaped index dirs + prune trash >30 days.
    - `setup` — invoke `setup_venv.main()`.
  - `bin/code-search` — bash launcher.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_cli.py -v`
Expected: FAIL with `No module named 'engine.cli'`

- [ ] **Step 3: Write `engine/setup_venv.py`**

```python
# engine/setup_venv.py
"""Bootstrap the central venv. Stdlib only; runs under any python3."""
import fcntl
import hashlib
import subprocess
import sys
from pathlib import Path

from engine import paths

REQUIREMENTS = Path(__file__).with_name("requirements.txt")


def _req_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def venv_ok() -> bool:
    try:
        return paths.venv_ok_path().read_text().strip() == _req_hash()
    except OSError:
        return False


def main() -> int:
    paths.ensure_home()
    with open(paths.home() / "setup.lock", "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        if venv_ok():
            print("venv already up to date")
            return 0
        vdir = paths.venv_dir()
        if not paths.venv_python().exists():
            print(f"Creating venv at {vdir} ...")
            subprocess.run([sys.executable, "-m", "venv", str(vdir)],
                           check=True)
        print("Installing dependencies (this downloads torch — several GB "
              "on first run) ...")
        r = subprocess.run([str(vdir / "bin" / "pip"), "install", "-r",
                            str(REQUIREMENTS)])
        if r.returncode != 0:
            print("pip install failed — venv left without venv.ok marker",
                  file=sys.stderr)
            return r.returncode
        paths.venv_ok_path().write_text(_req_hash())
        print("Setup complete.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write `engine/cli.py`**

```python
# engine/cli.py
"""Deterministic CLI — all state-changing logic lives here, not in slash
command prose. Stdlib only (search results come from the daemon)."""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from engine import client, migrate, paths, registry, repoident, setup_venv


def _ensure_setup() -> bool:
    if setup_venv.venv_ok():
        return True
    return setup_venv.main() == 0


def _root() -> Path | None:
    return repoident.repo_root(Path.cwd())


def format_results(results) -> None:
    # exact output format copied from search_code.py format_results
    for i, (path, start, end, text, file_type) in enumerate(results, 1):
        label = f" [{file_type}]" if file_type else ""
        print(f"MATCH {i}: {path}{label} (lines {start}-{end})")
        print("-" * 40)
        print(text)
        if not text.endswith("\n"):
            print()
        print()


def cmd_search(args) -> int:
    root = _root()
    if root is None:
        print("not a git repository", file=sys.stderr)
        return 1
    r = registry.resolve(root)
    if not r.family_enabled:
        print(f"code-search is not enabled for this repo.\n"
              f"Run: code-search enable", file=sys.stderr)
        return 1
    try:
        resp = client.search(root, " ".join(args.query),
                             n_results=args.top, all_files=args.all,
                             use_bm25=args.bm25,
                             session_id=os.environ.get("CLAUDE_SESSION_ID",
                                                       "unknown"))
    except client.DaemonUnavailable as e:
        print(f"search daemon unavailable: {e}\n"
              f"Run: code-search setup   (then retry)", file=sys.stderr)
        return 1
    if not resp.get("ok"):
        print(resp.get("error", "search failed"), file=sys.stderr)
        return 1
    if not resp["results"]:
        print("No results found.")
        return 2
    format_results(resp["results"])
    return 0


def cmd_enable(args) -> int:
    root = _root()
    if root is None:
        print("not a git repository — run from inside the repo you want "
              "to enable", file=sys.stderr)
        return 1
    if not args.dry_run and not _ensure_setup():
        print("setup failed; not enabling", file=sys.stderr)
        return 1
    report = migrate.migrate(root, dry_run=args.dry_run)
    if report["evidence"]:
        print("Old per-repo install detected:")
        for k in ("trashed", "skipped_tracked", "gitignore_cleaned", "killed"):
            if report[k]:
                print(f"  {k}: {report[k]}")
        if report["skipped_tracked"]:
            print("  NOTE: tracked files were left in place — remove them "
                  "with git rm when ready.")
        print(f"  backup: {paths.trash_dir()}")
    if args.dry_run:
        print("(dry run — nothing changed)")
        return 0
    r = registry.enable(root, bm25=args.bm25)
    try:
        client.watch(root, os.getpid())     # spawns daemon, queues first index
        print(f"enabled: {r.main_path} (repo_id {r.repo_id}); "
              f"first index queued")
    except client.DaemonUnavailable as e:
        print(f"enabled, but daemon failed to start: {e}", file=sys.stderr)
    return 0


def cmd_disable(args) -> int:
    root = _root()
    if root is None:
        print("not a git repository", file=sys.stderr)
        return 1
    ids = registry.disable(root)
    client.unwatch(root, os.getpid())
    if args.purge:
        for rid in ids:
            shutil.rmtree(paths.index_dir(rid), ignore_errors=True)
    print(f"disabled ({len(ids)} worktree index(es)"
          f"{' purged' if args.purge else ' kept'})")
    return 0


def cmd_status(args) -> int:
    reg = registry.load()
    for fam_id, fam in reg["repos"].items():
        print(f"{fam['main_path']}  (family {fam_id}, "
              f"bm25={fam.get('bm25', False)})")
        for rid, wt in fam["worktrees"].items():
            dead = "" if Path(wt["path"]).exists() else "  [DEAD PATH]"
            print(f"  {rid}  {wt['path']}{dead}")
    try:
        st = client.status()
        print(f"daemon: up {st['uptime_s']}s, "
              f"watching {len(st['watched'])} repo(s)")
    except client.DaemonUnavailable:
        print("daemon: not running")
    return 0


def cmd_reindex(args) -> int:
    root = _root()
    if root is None:
        print("not a git repository", file=sys.stderr)
        return 1
    try:
        client.watch(root, os.getpid())
        resp = client.request({"cmd": "reindex", "repo": str(root)})
    except client.DaemonUnavailable as e:
        print(str(e), file=sys.stderr)
        return 1
    print("reindex queued" if resp.get("ok") else resp.get("error"))
    return 0 if resp.get("ok") else 1


def cmd_gc(args) -> int:
    reaped = registry.gc()
    for rid in reaped:
        shutil.rmtree(paths.index_dir(rid), ignore_errors=True)
    cutoff = time.time() - 30 * 86400
    for entry in paths.trash_dir().glob("*"):
        if entry.stat().st_mtime < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
    print(f"gc: reaped {len(reaped)} index(es)")
    return 0


def cmd_setup(args) -> int:
    return setup_venv.main()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="code-search")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search")
    sp.add_argument("query", nargs="+")
    sp.add_argument("--top", type=int, default=5)
    sp.add_argument("--bm25", action="store_true")
    sp.add_argument("--all", action="store_true")

    ep = sub.add_parser("enable")
    ep.add_argument("--bm25", action="store_true")
    ep.add_argument("--dry-run", action="store_true")

    dp = sub.add_parser("disable")
    dp.add_argument("--purge", action="store_true")

    sub.add_parser("status")
    sub.add_parser("reindex")
    sub.add_parser("gc")
    sub.add_parser("setup")

    args = p.parse_args(argv)
    return {"search": cmd_search, "enable": cmd_enable,
            "disable": cmd_disable, "status": cmd_status,
            "reindex": cmd_reindex, "gc": cmd_gc,
            "setup": cmd_setup}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Write `bin/code-search`**

```bash
#!/usr/bin/env bash
# Launcher: stdlib CLI runs under any python3; only the daemon needs the venv.
set -euo pipefail
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${PLUGIN_ROOT}${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m engine.cli "$@"
```

```bash
chmod +x bin/code-search
```

(The CLI itself is stdlib-only; heavy work happens in the daemon, which `engine.client.ensure_daemon` launches with `paths.venv_python()`. So the launcher does not need the venv at all.)

- [ ] **Step 6: Create `engine/requirements.txt`**

Read the pip install line(s) in `install.sh` (search for `pip install`) and copy the exact package pins into `engine/requirements.txt`, one per line.

- [ ] **Step 7: Run test to verify it passes**

Run: `.venv-code-search/bin/python3 -m pytest tests/engine/test_cli.py -v`
Expected: PASS (5 tests)

- [ ] **Step 8: Commit**

```bash
git add engine/setup_venv.py engine/cli.py engine/requirements.txt bin/code-search tests/engine/test_cli.py
git commit -m "feat: deterministic CLI, venv bootstrap, launcher"
```

---

### Task 9: Hooks + plugin manifest + slash command

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `hooks/hooks.json`
- Create: `hooks/session_start.sh` (mode 755)
- Create: `hooks/session_end.sh` (mode 755)
- Create: `commands/code-search.md`
- Create: `tests/engine/test_hooks.sh` (mode 755)
- Note: old `hooks/post_search_code.sh` and `hooks/pre_read_grep_glob.sh` are deleted in Task 10.

**Interfaces:**
- Consumes: `engine.registry`, `engine.client` (stdlib-only guarantee matters here).
- Produces: plugin-registered SessionStart/SessionEnd hooks; `additionalContext` protocol injection.

**IMPORTANT — verify against current plugin docs before writing** (they change): plugin manifest schema and hook-config schema at https://docs.claude.com/en/docs/claude-code/plugins and https://docs.claude.com/en/docs/claude-code/hooks. The shapes below are correct as of 2026-07; adjust field names if docs differ, and note any deviation in the commit message.

- [ ] **Step 1: Write hook test (bash, no Claude needed)**

```bash
#!/usr/bin/env bash
# tests/engine/test_hooks.sh — hook contract tests with stdin JSON fixtures.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CODE_SEARCH_HOME="$TMP/csh"

fail() { echo "FAIL: $1"; exit 1; }

# fixture repo
REPO="$TMP/repo"
mkdir -p "$REPO" && cd "$REPO"
git init -q && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m i

# Test 1: unregistered repo -> exit 0, empty stdout
OUT=$(echo "{\"session_id\":\"s1\",\"cwd\":\"$REPO\"}" \
      | "$ROOT/hooks/session_start.sh") || fail "hook exited non-zero"
[ -z "$OUT" ] || fail "expected no output for unregistered repo, got: $OUT"

# Test 2: registered repo, no venv -> stderr warning, still exit 0, no context
PYTHONPATH="$ROOT" python3 -c "
from pathlib import Path
from engine import registry
registry.enable(Path('$REPO'))
"
ERR=$(echo "{\"session_id\":\"s1\",\"cwd\":\"$REPO\"}" \
      | "$ROOT/hooks/session_start.sh" 2>&1 >/dev/null) || fail "hook non-zero"
echo "$ERR" | grep -q "code-search setup" || fail "expected setup warning"

# Test 3: registered repo, venv.ok faked -> emits additionalContext JSON
mkdir -p "$CODE_SEARCH_HOME"
python3 - <<EOF
import hashlib, pathlib
req = pathlib.Path("$ROOT/engine/requirements.txt").read_bytes()
pathlib.Path("$CODE_SEARCH_HOME/venv.ok").write_text(
    hashlib.sha256(req).hexdigest())
EOF
OUT=$(echo "{\"session_id\":\"s1\",\"cwd\":\"$REPO\"}" \
      | CODE_SEARCH_SKIP_DAEMON=1 "$ROOT/hooks/session_start.sh")
echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
ctx = d['hookSpecificOutput']['additionalContext']
assert 'Precision Protocol' in ctx and 'code-search search' in ctx
assert d['hookSpecificOutput']['hookEventName'] == 'SessionStart'
" || fail "additionalContext malformed"

# Test 4: session_end on unregistered repo -> silent success
echo "{\"session_id\":\"s1\",\"cwd\":\"$TMP\"}" \
    | "$ROOT/hooks/session_end.sh" || fail "session_end non-zero"

echo "ALL HOOK TESTS PASSED"
```

- [ ] **Step 2: Run to verify it fails**

Run: `tests/engine/test_hooks.sh`
Expected: FAIL (`session_start.sh: No such file or directory`)

- [ ] **Step 3: Write `hooks/session_start.sh`**

```bash
#!/usr/bin/env bash
# SessionStart: gate on registry, ensure daemon+watch, inject Precision Protocol.
set -uo pipefail
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${PLUGIN_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

python3 - <<'PYEOF'
import json
import os
import sys
from pathlib import Path

from engine import registry, setup_venv

payload = json.load(sys.stdin)
cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
session_id = payload.get("session_id", "unknown")

r = registry.resolve(Path(cwd))
if not r.family_enabled:
    sys.exit(0)                     # silent for unregistered repos

if not r.registered:
    # inherited enablement: auto-register this worktree
    r = registry.register_worktree(Path(cwd))

if not setup_venv.venv_ok():
    print("code-search: central venv missing or stale — run: code-search setup",
          file=sys.stderr)
    sys.exit(0)                     # session proceeds without search

if not os.environ.get("CODE_SEARCH_SKIP_DAEMON"):   # test escape hatch
    from engine import client
    try:
        resp = client.watch(cwd, os.getppid())
        if not resp.get("ok"):
            print(f"code-search: watch failed: {resp.get('error')}",
                  file=sys.stderr)
            sys.exit(0)
    except client.DaemonUnavailable as e:
        print(f"code-search: daemon unavailable: {e}", file=sys.stderr)
        sys.exit(0)

protocol = """## Precision Protocol

**Rule:** Before using `Read`, `Grep`, or `Glob` — if the exact file path was \
not given to you in the current task, run `code-search search "<query>"` first.

1. **File path given in task?**
   - **Yes** -> go to step 2
   - **No** -> run `code-search search "<query>"`, then go to step 2
2. **Grep** the exact location, then **Read** to confirm context.
3. If wrong spot, refine and repeat from step 2.
4. **Edit** only after verified.

**Never use `code-search` when the file is already known — that is what \
`Grep` is for.**

**Search scope:** Production and test code by default; results are labeled \
`[prod]`, `[test]`, `[doc]`, or `[generated]`. Use `--all` to include docs \
and generated files. Use `--top N` for more results."""

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": protocol,
}}))
PYEOF
```

- [ ] **Step 4: Write `hooks/session_end.sh`**

```bash
#!/usr/bin/env bash
# SessionEnd: best-effort unwatch. Daemon pid-pruning is the backstop.
set -uo pipefail
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${PLUGIN_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

python3 - <<'PYEOF'
import json
import os
import sys
from pathlib import Path

from engine import registry

payload = json.load(sys.stdin)
cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
r = registry.resolve(Path(cwd))
if not r.registered:
    sys.exit(0)
from engine import client
client.unwatch(cwd, os.getppid())   # swallows DaemonUnavailable internally
PYEOF
exit 0
```

- [ ] **Step 5: Write plugin manifest and hook config**

```json
// .claude-plugin/plugin.json
{
  "name": "code-search",
  "version": "2.0.0",
  "description": "Semantic code search for Claude Code: central daemon, per-repo opt-in, zero files in your repos."
}
```

```json
// hooks/hooks.json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/session_start.sh"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/session_end.sh"
          }
        ]
      }
    ]
  }
}
```

(Verify against docs whether `plugin.json` needs a `"hooks": "./hooks/hooks.json"` pointer; add it if so.)

- [ ] **Step 6: Write `commands/code-search.md`**

```markdown
---
description: Enable, disable, or inspect semantic code search for this repo
argument-hint: enable | disable [--purge] | status | reindex | gc | setup
---

Run the deterministic CLI and report its output. Do not perform any
enable/disable/migration steps yourself — the CLI does everything.

1. Run via Bash: `code-search $ARGUMENTS`
   (If `$ARGUMENTS` is empty, run `code-search status`.)
2. Show the user the command output verbatim.
3. If the output mentions tracked files that were skipped, tell the user
   they can remove them with `git rm` when ready.
4. If the command fails with a message about `code-search setup`, offer to
   run `code-search setup` (it downloads several GB on first run — warn
   the user before running it).
```

- [ ] **Step 7: Run hook tests, make executable**

```bash
chmod +x hooks/session_start.sh hooks/session_end.sh tests/engine/test_hooks.sh
tests/engine/test_hooks.sh
```

Expected: `ALL HOOK TESTS PASSED`

- [ ] **Step 8: Commit**

```bash
git add .claude-plugin/ hooks/hooks.json hooks/session_start.sh hooks/session_end.sh commands/ tests/engine/test_hooks.sh
git commit -m "feat: plugin manifest, session hooks, slash command"
```

---

### Task 10: Remove old per-repo machinery + repoint remaining tests

**Files:**
- Delete: `install.sh`, `index_project.py`, `search_code.py`, `watch_index.py`, `search_server.py`, `chunker.py`, `migrate_add_file_type.py`, `hooks/post_search_code.sh`, `hooks/pre_read_grep_glob.sh`, `tools/analyze_search_usage.py`
- Delete: `tests/test_install.sh`, `tests/test_e2e.sh`, `tests/test_search_usage_tracking.sh`, `tests/test_search_server.py`, `tests/test_watch_index.py`, `tests/test_index_project.py`, `tests/test_search_code.py`
- Modify: `tests/test_chunker.py` (repoint import to `engine.chunker`)
- Modify: `.github/workflows/*` if any release workflow references `install.sh` (check `ls .github/workflows/`)
- Modify: `CLAUDE.md`, `.claude/CLAUDE.md` (this repo's own Precision Protocol references `.venv-code-search/bin/python3 search_code.py` — dev instructions need updating to the new client or removal)

**Interfaces:** none new. The old `tools/analyze_search_usage.py` is deleted because the spec moves analytics to a future `code-search analytics` subcommand and the old hook-env-var data model never produced real data (spec: Future-feature adaptation A).

- [ ] **Step 1: Repoint chunker test**

In `tests/test_chunker.py` change `from chunker import ...` to `from engine.chunker import ...` (check the exact import line first).

- [ ] **Step 2: Check eval/ references**

```bash
grep -rn "search_code\|index_project\|watch_index\|search_server" eval/ conftest.py pytest.ini .github/ 2>/dev/null
```

For each hit in `eval/`: repoint to `engine` equivalents where trivial (imports of `merge_chunks`, `classify_file`); where eval drives the old CLI scripts, update the command to `code-search search`. If an eval change is non-trivial, leave a `# BROKEN by central-install: <what>` comment listing it in the commit message rather than half-fixing silently.

- [ ] **Step 3: Delete old files**

```bash
git rm install.sh index_project.py search_code.py watch_index.py search_server.py chunker.py migrate_add_file_type.py
git rm hooks/post_search_code.sh hooks/pre_read_grep_glob.sh
git rm tools/analyze_search_usage.py
git rm tests/test_install.sh tests/test_e2e.sh tests/test_search_usage_tracking.sh
git rm tests/test_search_server.py tests/test_watch_index.py tests/test_index_project.py tests/test_search_code.py
```

- [ ] **Step 4: Update this repo's own dev instructions**

`CLAUDE.md` and `.claude/CLAUDE.md` in this repo tell Claude to run `.venv-code-search/bin/python3 search_code.py` — replace those command references with `code-search search "<query>"` (keep the Precision Protocol structure; only the command changes). Also update `conftest.py` if it references deleted modules.

- [ ] **Step 5: Run the full remaining suite**

Run: `.venv-code-search/bin/python3 -m pytest tests/ -v`
Expected: PASS (engine tests + repointed chunker test). No import errors from deleted modules.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat!: remove per-repo install machinery

BREAKING CHANGE: install.sh and per-repo scripts are gone; install as a
Claude Code plugin and run 'code-search enable' per repo."
```

---

### Task 11: End-to-end test

**Files:**
- Create: `tests/engine/test_e2e_central.sh` (mode 755)

**Interfaces:** consumes everything; proves the full loop without Claude.

- [ ] **Step 1: Write the e2e script**

```bash
#!/usr/bin/env bash
# End-to-end: old install -> enable (migrate) -> daemon search -> worktree
# auto-register -> disable --purge. Requires the central venv deps; run
# with: CODE_SEARCH_E2E_VENV=/path/to/venv tests/engine/test_e2e_central.sh
# (CI/dev: point it at this repo's .venv-code-search)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP=$(mktemp -d)
trap 'PYTHONPATH="$ROOT" CODE_SEARCH_HOME="$TMP/csh" python3 -c "
from engine import client
client.request({\"cmd\": \"shutdown\"}, timeout=5)
" 2>/dev/null || true; rm -rf "$TMP"' EXIT
export CODE_SEARCH_HOME="$TMP/csh"
VENV="${CODE_SEARCH_E2E_VENV:?set CODE_SEARCH_E2E_VENV to a venv with chromadb}"

fail() { echo "FAIL: $1"; exit 1; }

# Wire the central home to reuse the provided venv (skips the GB download)
mkdir -p "$CODE_SEARCH_HOME"
ln -s "$VENV" "$CODE_SEARCH_HOME/venv"
python3 - <<EOF
import hashlib, pathlib
req = pathlib.Path("$ROOT/engine/requirements.txt").read_bytes()
pathlib.Path("$CODE_SEARCH_HOME/venv.ok").write_text(
    hashlib.sha256(req).hexdigest())
EOF

# Fixture repo with a fake old install
REPO="$TMP/proj"
mkdir -p "$REPO" && cd "$REPO"
git init -q
echo 'def authenticate(user): return True' > auth.py
echo 'chroma_db/' > .gitignore
echo '.venv/' >> .gitignore
mkdir -p chroma_db && echo "nomic-ai/CodeRankEmbed" > chroma_db/model.txt
echo "v1.2.0" > .code-search-version
touch search_code.py watch_index.py
git add auth.py .gitignore
git -c user.email=t@t -c user.name=t commit -qm init

# 1. enable: migrates + registers + first index
"$ROOT/bin/code-search" enable | tee "$TMP/enable.out"
grep -q "enabled:" "$TMP/enable.out" || fail "enable did not report success"
[ ! -f search_code.py ] || fail "old script not migrated"
[ ! -d chroma_db ] || fail "old index not migrated"
grep -q '^\.venv/$' .gitignore || fail "generic gitignore line was removed"

# 2. search works (warming retry inside the client)
"$ROOT/bin/code-search" search "user authentication" > "$TMP/search.out"
grep -q "MATCH 1:" "$TMP/search.out" || fail "no search results"
grep -q "auth.py" "$TMP/search.out" || fail "auth.py not found"

# 3. worktree: auto-registration + seeded index
git worktree add "$TMP/wt" -b feat -q
cd "$TMP/wt"
"$ROOT/bin/code-search" reindex >/dev/null   # triggers watch/auto-register
"$ROOT/bin/code-search" search "user authentication" > "$TMP/wt.out"
grep -q "auth.py" "$TMP/wt.out" || fail "worktree search failed"

# 4. status shows both worktrees
"$ROOT/bin/code-search" status | tee "$TMP/status.out"
[ "$(grep -c "$TMP" "$TMP/status.out")" -ge 2 ] || fail "status missing worktrees"

# 5. disable --purge removes indexes
cd "$REPO"
"$ROOT/bin/code-search" disable --purge
[ -z "$(ls -A "$CODE_SEARCH_HOME/indexes" 2>/dev/null)" ] \
    || fail "indexes not purged"

echo "ALL E2E TESTS PASSED"
```

- [ ] **Step 2: Run it**

```bash
chmod +x tests/engine/test_e2e_central.sh
CODE_SEARCH_E2E_VENV="$PWD/.venv-code-search" tests/engine/test_e2e_central.sh
```

Expected: `ALL E2E TESTS PASSED` (slow — daemon loads the model). Debug failures via `$CODE_SEARCH_HOME/logs/daemon.log`.

- [ ] **Step 3: Commit**

```bash
git add tests/engine/test_e2e_central.sh
git commit -m "test: end-to-end central install flow"
```

---

### Task 12: README rewrite + spec cross-check

**Files:**
- Modify: `README.md` (full rewrite of install/usage sections)
- Modify: `docs/superpowers/specs/2026-07-07-central-install-design.md` (only if implementation deviated — record deviations, don't silently drift)

- [ ] **Step 1: Rewrite README**

Replace the Install / Re-index / Search / Persistent Search Server / Search Usage Tracking / What Gets Installed / Upgrade / Uninstall sections with the new model:

- **Install:** add the plugin (marketplace or `claude plugin install` from this repo — check current plugin-install syntax in docs and write the real command), then `code-search setup` (or let first `enable` run it), then per repo: `/code-search enable`.
- **Usage:** `code-search search "<query>"` table of flags (`--top`, `--bm25`, `--all`); note hooks auto-start watching per session; worktrees auto-enable with seeded indexes.
- **Data:** everything under `~/.code-search` (`CODE_SEARCH_HOME` override); repos stay untouched; dotfile-sync exclusion warning.
- **Migrating from v1:** `/code-search enable` in each old repo; what migration does (trash backup path, tracked-file skips).
- **Uninstall:** `code-search disable` per repo (or `--purge`), remove plugin, `rm -rf ~/.code-search`.
- Keep: How It Works (chunking/embedding/incremental hashing unchanged), Eval section, Releases section (retag to v2.0.0 flow; the release workflow may need updating since `install.sh` is gone — check `.github/workflows/` and either update or delete the release-asset step).

- [ ] **Step 2: Spec deviation check**

Read the spec top to bottom; for each section confirm the implementation matches. Where it doesn't, either fix the code (preferred if small) or update the spec with a `**Deviation (2026-07-07):**` note explaining why.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/
git commit -m "docs: README for central install model"
```

---

## Verification (after all tasks)

1. `.venv-code-search/bin/python3 -m pytest tests/ -v` — full suite green.
2. `tests/engine/test_hooks.sh` — hook contract green.
3. `CODE_SEARCH_E2E_VENV="$PWD/.venv-code-search" tests/engine/test_e2e_central.sh` — e2e green.
4. Manual smoke (real Claude): install plugin locally (`claude plugin` dev-install of this repo per current docs), `code-search enable` in a scratch repo, open a Claude session there, confirm: Precision Protocol appears in context, `code-search search` returns results, `~/.code-search/logs/search_usage.jsonl` gets an event, second session in a worktree searches instantly.
5. Use superpowers:finishing-a-development-branch to merge/PR.
```
