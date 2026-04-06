import io
import os
import sys
from unittest.mock import MagicMock, patch, mock_open

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import index_project as _ip_module
from index_project import git_indexable_files, CHROMA_MAX_BATCH


def _fake_run(tracked, untracked):
    def _run(cmd, **kwargs):
        result = MagicMock()
        result.stdout = "\n".join(untracked if "--others" in cmd else tracked)
        if result.stdout:
            result.stdout += "\n"
        return result
    return _run


def test_includes_tracked_files():
    with patch("index_project.subprocess.run", side_effect=_fake_run(["main.py", "utils.py"], [])):
        files = git_indexable_files()
    assert "main.py" in files
    assert "utils.py" in files


def test_includes_untracked_non_ignored_files():
    """New files created by Claude Code (not yet staged) must appear in the index."""
    with patch("index_project.subprocess.run", side_effect=_fake_run(["main.py"], ["SUMMARY.md"])):
        files = git_indexable_files()
    assert "main.py" in files
    assert "SUMMARY.md" in files


def test_no_duplicates_when_file_in_both_lists():
    with patch("index_project.subprocess.run", side_effect=_fake_run(["main.py"], ["main.py"])):
        files = git_indexable_files()
    assert files.count("main.py") == 1


def test_empty_lines_excluded():
    with patch("index_project.subprocess.run", side_effect=_fake_run(["main.py", ""], ["", "new.py"])):
        files = git_indexable_files()
    assert "" not in files


def test_chroma_db_excluded_from_tracked():
    """chroma_db/ must never be indexed even if tracked by git."""
    with patch("index_project.subprocess.run", side_effect=_fake_run(
        ["main.py", "chroma_db/chroma.sqlite3", "chroma_db/uuid/data_level0.bin"], []
    )):
        files = git_indexable_files()
    assert not any(f.startswith("chroma_db") for f in files)


def test_chroma_db_excluded_from_untracked():
    """chroma_db/ must never be indexed even if untracked and not gitignored."""
    with patch("index_project.subprocess.run", side_effect=_fake_run(
        ["main.py"], ["chroma_db/chroma.sqlite3", "SUMMARY.md"]
    )):
        files = git_indexable_files()
    assert not any(f.startswith("chroma_db") for f in files)
    assert "SUMMARY.md" in files


def test_chroma_db_exclusion_tracks_chroma_path():
    """Exclusion must use CHROMA_PATH so a rename stays consistent."""
    import index_project as _ip
    original = _ip.CHROMA_PATH
    try:
        _ip.CHROMA_PATH = "./my_index"
        with patch("index_project.subprocess.run", side_effect=_fake_run(
            ["main.py", "my_index/chroma.sqlite3"], []
        )):
            files = _ip.git_indexable_files()
        assert not any(f.startswith("my_index") for f in files)
        assert "main.py" in files
    finally:
        _ip.CHROMA_PATH = original


def test_chroma_db_exclusion_uses_forward_slashes():
    """Exclusion must work even when os.path.normpath returns backslash-separated paths (Windows)."""
    import index_project as _ip
    original = _ip.CHROMA_PATH
    try:
        _ip.CHROMA_PATH = "./data/chroma_db"
        with patch("index_project.os.path.normpath", return_value="data\\chroma_db"), \
             patch("index_project.subprocess.run", side_effect=_fake_run(
                 ["main.py", "data/chroma_db/chroma.sqlite3"], []
             )):
            files = _ip.git_indexable_files()
        assert not any(f.startswith("data/chroma_db") for f in files)
        assert "main.py" in files
    finally:
        _ip.CHROMA_PATH = original


def test_upsert_is_batched_when_exceeding_max_batch_size():
    """collection.upsert must be called in multiple batches when chunks exceed CHROMA_MAX_BATCH."""
    import index_project as _ip

    num_items = CHROMA_MAX_BATCH + 1
    ids = [f"file.py::{i}" for i in range(num_items)]
    docs = [f"chunk {i}" for i in range(num_items)]
    metas = [{"path": "file.py", "start_line": i, "end_line": i + 1, "hash": f"h{i}"} for i in range(num_items)]

    mock_collection = MagicMock()
    mock_collection.upsert = MagicMock()

    _ip._batch_upsert(mock_collection, docs, metas, ids)

    expected_calls = (num_items + CHROMA_MAX_BATCH - 1) // CHROMA_MAX_BATCH
    assert mock_collection.upsert.call_count == expected_calls

    first_call_ids = mock_collection.upsert.call_args_list[0][1]["ids"]
    assert len(first_call_ids) == CHROMA_MAX_BATCH

    last_call_ids = mock_collection.upsert.call_args_list[-1][1]["ids"]
    assert len(last_call_ids) == num_items % CHROMA_MAX_BATCH


def test_delete_is_batched_when_exceeding_max_batch_size():
    """collection.delete must be called in multiple batches when ids exceed CHROMA_MAX_BATCH."""
    import index_project as _ip

    num_items = CHROMA_MAX_BATCH + 1
    ids = [f"file.py::{i}" for i in range(num_items)]

    mock_collection = MagicMock()
    mock_collection.delete = MagicMock()

    _ip._batch_delete(mock_collection, ids)

    expected_calls = (num_items + CHROMA_MAX_BATCH - 1) // CHROMA_MAX_BATCH
    assert mock_collection.delete.call_count == expected_calls


def test_untracked_query_uses_exclude_standard():
    """--exclude-standard ensures gitignored files are not returned as untracked."""
    calls = []
    def capturing_run(cmd, **kwargs):
        calls.append(list(cmd))
        r = MagicMock()
        r.stdout = ""
        return r

    with patch("index_project.subprocess.run", side_effect=capturing_run):
        git_indexable_files()

    untracked_calls = [c for c in calls if "--others" in c]
    assert untracked_calls, "expected a call with --others"
    assert "--exclude-standard" in untracked_calls[0]


def test_status_writes_ansi_erase_and_message():
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        _ip_module._status("hello world")
    assert buf.getvalue() == "\r\033[Khello world"


def test_status_does_not_write_newline():
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        _ip_module._status("x")
    assert "\n" not in buf.getvalue()


def test_status_uses_flush():
    mock_stdout = MagicMock()
    with patch("sys.stdout", mock_stdout):
        _ip_module._status("msg")
    mock_stdout.write.assert_called()
    # print(..., flush=True) calls flush() on stdout
    mock_stdout.flush.assert_called()


def test_loading_phase_prints_status_before_collection_get():
    """_status('Loading index...') must be called before collection.get()."""
    call_order = []

    mock_collection = MagicMock()
    mock_collection.get.side_effect = lambda **kw: (call_order.append("get"), {"ids": [], "metadatas": []})[1]

    with patch("index_project._status", side_effect=lambda m: call_order.append(f"status:{m}")), \
         patch("index_project.chromadb.PersistentClient") as mock_client, \
         patch("index_project.HFCodeEmbeddingFunction"), \
         patch("index_project.git_indexable_files", return_value=[]):
        mock_client.return_value.get_or_create_collection.return_value = mock_collection
        _ip_module.index_files()

    assert call_order[0] == "status:Loading index..."
    assert call_order[1] == "get"


def test_scanning_phase_updates_per_file():
    """_status must be called once per file with correct counts."""
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "metadatas": []}

    status_calls = []
    with patch("index_project._status", side_effect=lambda m: status_calls.append(m)), \
         patch("index_project.chromadb.PersistentClient") as mock_client, \
         patch("index_project.HFCodeEmbeddingFunction"), \
         patch("index_project.git_indexable_files", return_value=["a.py", "b.py", "c.py"]), \
         patch("builtins.open", mock_open(read_data="line1\n")):
        mock_client.return_value.get_or_create_collection.return_value = mock_collection
        _ip_module.index_files()

    scanning_calls = [m for m in status_calls if m.startswith("Scanning")]
    assert scanning_calls == [
        "Scanning files... 1 / 3",
        "Scanning files... 2 / 3",
        "Scanning files... 3 / 3",
    ]


def test_batch_upsert_progress_messages():
    """_status must show batch and chunk counts for each batch."""
    mock_collection = MagicMock()
    status_calls = []

    # 2 items, batch size 1 → 2 batches
    with patch("index_project._status", side_effect=lambda m: status_calls.append(m)), \
         patch("index_project.CHROMA_MAX_BATCH", 1):
        _ip_module._batch_upsert(mock_collection, ["d1", "d2"], [{"a": 1}, {"a": 2}], ["id1", "id2"])

    assert status_calls == [
        "Upserting... batch 1 / 2 (1 / 2 chunks)",
        "Upserting... batch 2 / 2 (2 / 2 chunks)",
    ]
    assert mock_collection.upsert.call_count == 2


def test_batch_upsert_empty_prints_nothing_to_upsert():
    printed = []
    with patch("builtins.print", side_effect=lambda *a, **kw: printed.append(a)):
        _ip_module._batch_upsert(MagicMock(), [], [], [])
    assert any("Nothing to upsert" in str(p) for p in printed)


def test_batch_delete_progress_messages():
    """_status must show batch and chunk counts for each batch."""
    mock_collection = MagicMock()
    status_calls = []

    with patch("index_project._status", side_effect=lambda m: status_calls.append(m)), \
         patch("index_project.CHROMA_MAX_BATCH", 1):
        _ip_module._batch_delete(mock_collection, ["id1", "id2"])

    assert status_calls == [
        "Deleting... batch 1 / 2 (1 / 2 chunks)",
        "Deleting... batch 2 / 2 (2 / 2 chunks)",
    ]
    assert mock_collection.delete.call_count == 2


def test_batch_delete_empty_is_silent():
    printed = []
    status_calls = []
    with patch("builtins.print", side_effect=lambda *a, **kw: printed.append(a)), \
         patch("index_project._status", side_effect=lambda m: status_calls.append(m)):
        _ip_module._batch_delete(MagicMock(), [])
    assert printed == []
    assert status_calls == []


def test_batch_upsert_prints_newline_terminator_after_batches():
    """A bare print() must be called after the last batch to end the progress line."""
    bare_prints = []
    with patch("index_project._status"), \
         patch("builtins.print", side_effect=lambda *a, **kw: bare_prints.append(a) if not a else None):
        _ip_module._batch_upsert(MagicMock(), ["d"], [{"a": 1}], ["id1"])
    assert () in bare_prints


def test_batch_delete_prints_newline_terminator_after_batches():
    """A bare print() must be called after the last batch to end the progress line."""
    bare_prints = []
    with patch("index_project._status"), \
         patch("builtins.print", side_effect=lambda *a, **kw: bare_prints.append(a) if not a else None):
        _ip_module._batch_delete(MagicMock(), ["id1"])
    assert () in bare_prints
