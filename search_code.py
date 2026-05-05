import hashlib
import re
import sys
import json
import socket as _socket
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import chromadb
from index_project import HFCodeEmbeddingFunction

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "project_code"
_DEFAULT_MODEL = "nomic-ai/CodeRankEmbed"
_DOC_LANGS = frozenset({"restructuredtext", "markdown"})  # legacy fallback for pre-migration indices


def _server_socket_path(chroma_path=None):
    """Return the Unix socket path for the search server for this project.

    Socket lives in /tmp/ to ensure it is on the Linux filesystem (not DrvFs).
    Path is project-specific via a SHA-1 hash of the resolved chroma_db directory.
    """
    if chroma_path is None:
        chroma_path = str(Path(CHROMA_PATH).resolve())
    h = hashlib.sha1(chroma_path.encode()).hexdigest()[:12]
    return Path(f"/tmp/claude-code-search-{h}.sock")


def _try_server_search(query, n_results=5, all_files=False, use_bm25=False,
                       socket_path=None):
    """Attempt a search via the persistent server socket.

    Returns the results list on success, or None if the server is unavailable.
    Results are lists of [path, start, end, text, file_type] (JSON arrays).
    """
    if socket_path is None:
        socket_path = str(_server_socket_path())

    if not Path(socket_path).exists():
        return None

    try:
        with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as sock:
            sock.settimeout(10.0)
            sock.connect(socket_path)
            request = json.dumps({
                "query": query,
                "n_results": n_results,
                "all_files": all_files,
                "use_bm25": use_bm25,
            })
            sock.sendall(request.encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
            response = json.loads(buf.split(b"\n")[0])
            if "error" in response:
                return None
            return response["results"]
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _tokenize_for_bm25(text):
    """Code-aware tokenization for BM25: split camelCase/snake_case, lowercase, drop short tokens."""
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = re.sub(r'[_\-./\\:;,|#@!?(){}\[\]<>"\'+*&^%$=~`]', ' ', text)
    tokens = text.lower().split()
    return [t for t in tokens if len(t) > 1]


def _load_bm25():
    """Load BM25 corpus and build BM25Okapi. Returns (bm25, id_list) or (None, [])."""
    corpus_path = Path(CHROMA_PATH) / "bm25_corpus.json"
    if not corpus_path.exists():
        return None, []
    try:
        from rank_bm25 import BM25Okapi
        corpus = json.loads(corpus_path.read_text())
        id_list = list(corpus.keys())
        tokenized = [_tokenize_for_bm25(corpus[cid]) for cid in id_list]
        return BM25Okapi(tokenized), id_list
    except Exception:
        return None, []


def _rrf_merge(semantic_ids, bm25_ids, k=60):
    """Reciprocal Rank Fusion: merge two ranked lists into one by score = sum(1/(k+rank))."""
    scores = {}
    for rank, cid in enumerate(semantic_ids, 1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    for rank, cid in enumerate(bm25_ids, 1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda c: scores[c], reverse=True)


def _load_embedding_fn():
    model_file = Path(CHROMA_PATH) / "model.txt"
    model_name = model_file.read_text().strip() if model_file.exists() else _DEFAULT_MODEL
    return HFCodeEmbeddingFunction(model_name)


def _load_source_langs():
    """Legacy fallback: return non-doc languages for indices without file_type metadata."""
    langs_file = Path(CHROMA_PATH) / "langs.json"
    if not langs_file.exists():
        return set()
    try:
        lang_counts = json.loads(langs_file.read_text())
        return {lang for lang in lang_counts if lang not in _DOC_LANGS}
    except Exception:
        return set()


def _log_search_event(query, n_results, result_count, latency_ms,
                      search_mode, use_bm25):
    """Log search event to logs/search_usage.jsonl (JSONL format)."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "search_usage.jsonl"

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "search",
        "query": query,
        "n_results": n_results,
        "result_count": result_count,
        "latency_ms": latency_ms,
        "search_mode": search_mode,
        "use_bm25": use_bm25,
        "session_id": os.getenv("LAST_SEARCH_SESSION", "unknown"),
        "model": os.getenv("CLAUDE_MODEL", "unknown"),
        "skill_name": os.getenv("CLAUDE_SKILL", "unknown"),
        "agent_id": os.getenv("CLAUDE_AGENT_ID", "main"),
        "agent_depth": int(os.getenv("CLAUDE_AGENT_DEPTH", "0")),
    }

    try:
        with log_file.open("a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass  # Silent failure — don't break search if logging fails


def _has_file_type_metadata(collection):
    """Return True if the index has file_type metadata (requires migration or fresh index)."""
    sample = collection.get(limit=1, include=["metadatas"])
    return bool(sample["ids"]) and "file_type" in (sample["metadatas"][0] or {})


def merge_chunks(items):
    """Group results by file and merge overlapping line ranges.

    items: list of (path, start_line, end_line, text, file_type) tuples
    """
    items = sorted(items, key=lambda x: (x[0], x[1]))

    merged = []
    for path, start, end, text, file_type in items:
        if merged and merged[-1][0] == path and start <= merged[-1][2] + 1:
            # overlapping or adjacent — merge, trimming duplicated overlap lines
            prev_path, prev_start, prev_end, prev_text, prev_ft = merged[-1]
            overlap_line_count = max(0, prev_end - start + 1)
            text_lines = text.splitlines(keepends=True)
            if overlap_line_count > len(text_lines):
                overlap_line_count = 0
            new_text = prev_text + "".join(text_lines[overlap_line_count:])
            merged[-1] = [prev_path, prev_start, max(prev_end, end), new_text, prev_ft]
        else:
            merged.append([path, start, end, text, file_type])

    return merged


def search(query, n_results=5, all_files=False, use_bm25=False):
    """Return merged search results as a list of (path, start, end, text, file_type) tuples.

    Returns an empty list when the index has no documents.
    Exits with code 1 if no index exists.
    """
    start_time = time.time()

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception as e:
        print(
            f"Error: no index found. Run 'python3 index_project.py' first. ({e})",
            file=sys.stderr,
        )
        sys.exit(1)

    count = collection.count()
    if count == 0:
        return []

    emb_fn = _load_embedding_fn()
    query_embedding = emb_fn([query])[0]

    where = None
    use_file_type = False
    source_langs: set = set()
    if not all_files:
        if _has_file_type_metadata(collection):
            where = {"file_type": {"$in": ["prod", "test"]}}
            use_file_type = True
        else:
            source_langs = _load_source_langs()
            where = {"lang": {"$in": list(source_langs)}} if source_langs else None

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

    bm25, id_list = _load_bm25() if use_bm25 else (None, [])
    if bm25 is not None and id_list:
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

    latency_ms = int((time.time() - start_time) * 1000)
    _log_search_event(query, n_results, len(items), latency_ms,
                      "direct", use_bm25)

    return merge_chunks(items)


def format_results(merged):
    """Print merged search results to stdout. Exits with code 2 if empty."""
    if not merged:
        print("No results found.")
        sys.exit(2)

    for i, (path, start, end, text, file_type) in enumerate(merged, 1):
        label = f" [{file_type}]" if file_type else ""
        print(f"MATCH {i}: {path}{label} (lines {start}-{end})")
        print("-" * 40)
        print(text)
        if not text.endswith("\n"):
            print()
        print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Semantic code search against a ChromaDB index."
    )
    parser.add_argument("query", nargs="*", help="Search query (natural language)")
    parser.add_argument(
        "--top", type=int, default=5, metavar="N",
        help="Number of results to return (default: 5)",
    )
    parser.add_argument(
        "--all", action="store_true", dest="all_files",
        help="Search all files including docs and generated (default: prod and test only)",
    )
    parser.add_argument(
        "--bm25", action="store_true", dest="bm25",
        help="Enable BM25 hybrid ranking (requires index built with --bm25)",
    )
    parser.add_argument(
        "--version", action="store_true",
        help="Show installed version information",
    )
    args = parser.parse_args()

    # Handle --version flag
    if args.version:
        version_file = Path(".code-search-version")
        if version_file.exists():
            print(version_file.read_text().strip())
        else:
            print("Version info not found (install.sh not run or old installation)")
        sys.exit(0)

    if not args.query:
        parser.error("the following arguments are required: query")

    q = " ".join(args.query)

    start_time = time.time()
    server_results = _try_server_search(q, n_results=args.top,
                                        all_files=args.all_files, use_bm25=args.bm25)
    if server_results is not None:
        latency_ms = int((time.time() - start_time) * 1000)
        _log_search_event(q, args.top, len(server_results), latency_ms,
                          "server", args.bm25)
        format_results(server_results)
    else:
        format_results(search(q, n_results=args.top,
                              all_files=args.all_files, use_bm25=args.bm25))
