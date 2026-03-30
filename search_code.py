import re
import sys
import json
from pathlib import Path
import chromadb
from rank_bm25 import BM25Okapi
from index_project import HFCodeEmbeddingFunction

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "project_code"
_DEFAULT_MODEL = "microsoft/graphcodebert-base"
_DOC_LANGS = frozenset({"restructuredtext", "markdown"})


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
    """Return non-doc languages present in the index, or empty set if unavailable."""
    langs_file = Path(CHROMA_PATH) / "langs.json"
    if not langs_file.exists():
        return set()
    try:
        lang_counts = json.loads(langs_file.read_text())
        return {lang for lang in lang_counts if lang not in _DOC_LANGS}
    except Exception:
        return set()


def merge_chunks(items):
    """Group results by file and merge overlapping line ranges.

    items: list of (path, start_line, end_line, text) tuples
    """
    items = sorted(items, key=lambda x: (x[0], x[1]))

    merged = []
    for path, start, end, text in items:
        if merged and merged[-1][0] == path and start <= merged[-1][2] + 1:
            # overlapping or adjacent — merge, trimming duplicated overlap lines
            prev_path, prev_start, prev_end, prev_text = merged[-1]
            overlap_line_count = max(0, prev_end - start + 1)
            text_lines = text.splitlines(keepends=True)
            if overlap_line_count > len(text_lines):
                overlap_line_count = 0
            new_text = prev_text + "".join(text_lines[overlap_line_count:])
            merged[-1] = [prev_path, prev_start, max(prev_end, end), new_text]
        else:
            merged.append([path, start, end, text])

    return merged


def search(query, n_results=5, all_files=False, use_bm25=True):
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    emb_fn = _load_embedding_fn()
    try:
        collection = client.get_collection(
            name=COLLECTION_NAME, embedding_function=emb_fn
        )
    except Exception as e:
        print(
            f"Error: no index found. Run 'python3 index_project.py' first. ({e})",
            file=sys.stderr,
        )
        sys.exit(1)

    count = collection.count()
    if count == 0:
        print("No results found.")
        sys.exit(2)

    source_langs = set() if all_files else _load_source_langs()
    where = {"lang": {"$in": list(source_langs)}} if source_langs else None

    # Fetch more semantic candidates for RRF
    n_candidates = min(n_results * 4, count)
    results = collection.query(
        query_texts=[query],
        n_results=n_candidates,
        **({"where": where} if where else {}),
        include=["metadatas", "documents"],
    )

    semantic_ids = results["ids"][0]

    # Build metadata cache from semantic results
    meta_cache = {}
    for i, cid in enumerate(semantic_ids):
        m = results["metadatas"][0][i]
        meta_cache[cid] = (m["path"], m["start_line"], m["end_line"], results["documents"][0][i])

    # BM25 search + RRF merge
    bm25, id_list = _load_bm25() if use_bm25 else (None, [])
    if bm25 is not None and id_list:
        tokenized_query = _tokenize_for_bm25(query)
        bm25_scores = bm25.get_scores(tokenized_query)
        top_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:n_candidates]
        bm25_ids = [id_list[i] for i in top_indices]
        merged_ids = _rrf_merge(semantic_ids, bm25_ids)
    else:
        merged_ids = semantic_ids

    # Fetch metadata for any BM25-only IDs not already in cache
    missing = [cid for cid in merged_ids if cid not in meta_cache]
    if missing:
        extra = collection.get(ids=missing, include=["metadatas", "documents"])
        for i, cid in enumerate(extra["ids"]):
            m = extra["metadatas"][i]
            if source_langs and m.get("lang") not in source_langs:
                continue
            meta_cache[cid] = (m["path"], m["start_line"], m["end_line"], extra["documents"][i])

    # Build ordered items list up to n_results
    items = []
    seen_ids = set()
    for cid in merged_ids:
        if cid in meta_cache and cid not in seen_ids:
            seen_ids.add(cid)
            items.append(meta_cache[cid])
        if len(items) >= n_results:
            break

    merged = merge_chunks(items)
    if not merged:
        print("No results found.")
        sys.exit(2)

    for i, (path, start, end, text) in enumerate(merged, 1):
        print(f"MATCH {i}: {path} (lines {start}-{end})")
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
    parser.add_argument("query", nargs="+", help="Search query (natural language)")
    parser.add_argument(
        "--top", type=int, default=5, metavar="N",
        help="Number of results to return (default: 5)"
    )
    parser.add_argument(
        "--all", action="store_true", dest="all_files",
        help="Search all files including docs (default: source files only)",
    )
    parser.add_argument(
        "--no-bm25", action="store_true", dest="no_bm25",
        help="Use semantic search only, skip BM25 hybrid ranking",
    )
    args = parser.parse_args()
    search(" ".join(args.query), n_results=args.top, all_files=args.all_files, use_bm25=not args.no_bm25)
