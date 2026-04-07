#!/usr/bin/env python3
"""search_server.py — persistent search server that keeps the embedding model warm.

Usage:
    python3 search_server.py          # start the server (foreground, manual lifecycle)

Lifecycle mirrors watch_index.py: acquire flock PID lock, install SIGINT/SIGTERM
handlers, block until killed.

Socket: /tmp/claude-code-search-<hash>.sock  (project-specific, always on Linux fs)
PID:    .search_server.pid                   (in project directory)

search_code.py auto-detects the socket and routes to the server when available,
falling back to direct execution silently.
"""

import json
import os
import signal
import socket
import sys
import threading
from pathlib import Path

import chromadb

from search_code import (
    CHROMA_PATH,
    COLLECTION_NAME,
    _has_file_type_metadata,
    _load_bm25,
    _load_embedding_fn,
    _load_source_langs,
    _rrf_merge,
    _server_socket_path,
    _tokenize_for_bm25,
    merge_chunks,
)
from watch_index import acquire_pid_lock, cleanup_pid

PID_FILE = ".search_server.pid"


# ── Request handling ───────────────────────────────────────────────────────────

def _handle_request(request, emb_fn, collection, source_langs, use_file_type, bm25, id_list):
    """Execute one search request and return the merged results list."""
    query = request["query"]
    n_results = request.get("n_results", 5)
    all_files = request.get("all_files", False)
    use_bm25 = request.get("use_bm25", False)

    count = collection.count()
    if count == 0:
        return []

    query_embedding = emb_fn([query])[0]

    where = None
    if not all_files:
        if use_file_type:
            where = {"file_type": {"$in": ["prod", "test"]}}
        elif source_langs:
            where = {"lang": {"$in": list(source_langs)}}

    n_candidates = min(n_results * 4, count)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_candidates,
        **({"where": where} if where else {}),
        include=["metadatas", "documents"],
    )

    semantic_ids = results["ids"][0]
    meta_cache = {}
    for i, cid in enumerate(semantic_ids):
        m = results["metadatas"][0][i]
        meta_cache[cid] = (m["path"], m["start_line"], m["end_line"],
                           results["documents"][0][i], m.get("file_type", ""))

    if use_bm25 and bm25 is not None and id_list:
        tokenized_query = _tokenize_for_bm25(query)
        bm25_scores = bm25.get_scores(tokenized_query)
        top_indices = sorted(range(len(bm25_scores)),
                             key=lambda i: bm25_scores[i], reverse=True)[:n_candidates]
        bm25_ids = [id_list[i] for i in top_indices]
        merged_ids = _rrf_merge(semantic_ids, bm25_ids)
    else:
        merged_ids = semantic_ids

    missing = [cid for cid in merged_ids if cid not in meta_cache]
    if missing:
        extra = collection.get(ids=missing, include=["metadatas", "documents"])
        for i, cid in enumerate(extra["ids"]):
            m = extra["metadatas"][i]
            ft = m.get("file_type", "")
            if use_file_type and ft not in ("prod", "test"):
                continue
            if source_langs and m.get("lang") not in source_langs:
                continue
            meta_cache[cid] = (m["path"], m["start_line"], m["end_line"],
                               extra["documents"][i], ft)

    items = []
    seen_ids = set()
    for cid in merged_ids:
        if cid in meta_cache and cid not in seen_ids:
            seen_ids.add(cid)
            items.append(meta_cache[cid])
        if len(items) >= n_results:
            break

    return merge_chunks(items)


def _handle_connection(conn, emb_fn, collection, source_langs, use_file_type, bm25, id_list):
    """Read one JSON request from conn, write one JSON response."""
    try:
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                return
            buf += chunk
        request = json.loads(buf.split(b"\n")[0])
        results = _handle_request(request, emb_fn, collection,
                                  source_langs, use_file_type, bm25, id_list)
        # merge_chunks returns lists/tuples — both serialize correctly to JSON arrays
        conn.sendall(json.dumps({"results": results}).encode() + b"\n")
    except Exception as e:
        try:
            conn.sendall(json.dumps({"error": str(e)}).encode() + b"\n")
        except Exception:
            pass
    finally:
        conn.close()


# ── Server lifecycle ───────────────────────────────────────────────────────────

def run_server(chroma_path=None, socket_path=None, stop_event=None):
    """Load warm objects and serve requests until stop_event is set (or process killed).

    Args:
        chroma_path: path to chroma_db directory (defaults to CHROMA_PATH)
        socket_path: Unix socket path (defaults to _server_socket_path())
        stop_event: threading.Event for clean shutdown in tests
    """
    if chroma_path is None:
        chroma_path = CHROMA_PATH
    if socket_path is None:
        socket_path = str(_server_socket_path(str(Path(chroma_path).resolve())))

    client = chromadb.PersistentClient(path=chroma_path)
    try:
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception as e:
        print(f"Error: no index found. Run 'python3 index_project.py' first. ({e})",
              file=sys.stderr)
        sys.exit(1)

    emb_fn = _load_embedding_fn()
    bm25, id_list = _load_bm25()

    use_file_type = False
    source_langs: set = set()
    if _has_file_type_metadata(collection):
        use_file_type = True
    else:
        source_langs = _load_source_langs()

    # Remove stale socket from a previous crashed run
    try:
        os.remove(socket_path)
    except FileNotFoundError:
        pass

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(socket_path)
        srv.listen(8)
        srv.settimeout(1.0)

        print(f"Search server ready. Socket: {socket_path}", flush=True)

        while stop_event is None or not stop_event.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(
                target=_handle_connection,
                args=(conn, emb_fn, collection, source_langs, use_file_type, bm25, id_list),
                daemon=True,
            )
            t.start()
    finally:
        srv.close()
        try:
            os.remove(socket_path)
        except FileNotFoundError:
            pass


def main():
    lock_fh = acquire_pid_lock(PID_FILE)
    if lock_fh is None:
        try:
            pid = Path(PID_FILE).read_text().strip()
        except FileNotFoundError:
            pid = "unknown"
        print(f"search server already running (PID: {pid})")
        sys.exit(0)

    socket_path = str(_server_socket_path(str(Path(CHROMA_PATH).resolve())))

    def _cleanup(signum=None, frame=None):
        lock_fh.close()
        cleanup_pid(PID_FILE)
        try:
            os.remove(socket_path)
        except FileNotFoundError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        run_server(socket_path=socket_path)
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
