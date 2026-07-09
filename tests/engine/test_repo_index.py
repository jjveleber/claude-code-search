import json
import threading
import time
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


def test_concurrent_load_bm25_no_torn_read(tmp_path, monkeypatch):
    """#36: _bm25_loaded must be set AFTER the corpus is built, under a lock,
    so a concurrent caller never observes loaded=True with _bm25 still None
    (a transient degrade to semantic-only)."""
    idx = tmp_path / "idx"
    idx.mkdir()
    (idx / "bm25_corpus.json").write_text(json.dumps({"c1": "hello world"}))
    ri = RepoIndex(tmp_path, idx)

    entered = threading.Event()
    release = threading.Event()
    import rank_bm25
    real = rank_bm25.BM25Okapi

    def slow(*a, **k):
        entered.set()
        release.wait(5)
        return real(*a, **k)

    monkeypatch.setattr(rank_bm25, "BM25Okapi", slow)

    a_result = {}
    b_result = {}
    ta = threading.Thread(target=lambda: a_result.__setitem__("v", ri._load_bm25()))
    ta.start()
    assert entered.wait(5), "builder thread never entered corpus build"
    # Concurrent caller while the builder is still constructing the corpus:
    tb = threading.Thread(target=lambda: b_result.__setitem__("v", ri._load_bm25()))
    tb.start()
    time.sleep(0.1)
    release.set()
    ta.join(5)
    tb.join(5)
    assert a_result["v"] is not None
    assert b_result["v"] is not None, \
        "concurrent search saw a torn semantic-only state"
