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


def _status(msg):
    print(f"\r\033[K{msg}", end="", flush=True)


def _batch_upsert(collection, docs, metas, ids, embeddings=None):
    if not ids:
        print("Nothing to upsert.")
        return
    total = len(ids)
    total_batches = (total + CHROMA_MAX_BATCH - 1) // CHROMA_MAX_BATCH
    for b, i in enumerate(range(0, total, CHROMA_MAX_BATCH), start=1):
        done = min(i + CHROMA_MAX_BATCH, total)
        _status(f"Upserting... batch {b} / {total_batches} ({done:,} / {total:,} chunks)")
        collection.upsert(
            documents=docs[i:i + CHROMA_MAX_BATCH],
            embeddings=embeddings[i:i + CHROMA_MAX_BATCH] if embeddings is not None else None,
            metadatas=metas[i:i + CHROMA_MAX_BATCH],
            ids=ids[i:i + CHROMA_MAX_BATCH],
        )
    print()  # end upsert line


def _batch_delete(collection, ids):
    if not ids:
        return
    total = len(ids)
    total_batches = (total + CHROMA_MAX_BATCH - 1) // CHROMA_MAX_BATCH
    for b, i in enumerate(range(0, total, CHROMA_MAX_BATCH), start=1):
        done = min(i + CHROMA_MAX_BATCH, total)
        _status(f"Deleting... batch {b} / {total_batches} ({done:,} / {total:,} chunks)")
        collection.delete(ids=ids[i:i + CHROMA_MAX_BATCH])
    print()  # end delete line


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
        """Return tracked files plus untracked non-ignored files."""
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=self.root,
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"], cwd=self.root,
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        seen = set()
        result = []
        for f in tracked + untracked:
            if f.strip() and f not in seen:
                seen.add(f)
                result.append(f)
        return result

    def _emb_fn(self):
        model_file = self.index_dir / "model.txt"
        name = model_file.read_text().strip() if model_file.exists() \
            else "nomic-ai/CodeRankEmbed"
        return HFCodeEmbeddingFunction(name)

    # -- index ----------------------------------------------------------
    def index(self, use_bm25: bool = False) -> dict:
        client = self._chroma()

        tracked_files = self._git_files()

        lang_counts = detect_languages(tracked_files)
        top_langs = ", ".join(lang for lang, _ in lang_counts.most_common(5)) or "none detected"
        model_name = choose_model(lang_counts)
        print(f"Languages: {top_langs}")
        print(f"Embedding model: {model_name}")

        # Write model name and language counts so search() can load the same
        # embedding function and apply the correct language filter.
        self.index_dir.mkdir(parents=True, exist_ok=True)
        (self.index_dir / "model.txt").write_text(model_name)
        (self.index_dir / "langs.json").write_text(json.dumps(dict(lang_counts)))

        emb_fn = self._emb_fn()

        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=emb_fn
        )

        _status("Loading index...")
        existing_hashes = {}
        _PAGE = 5000
        _offset = 0
        while True:
            batch = collection.get(include=["metadatas"], limit=_PAGE, offset=_offset)
            batch_ids = batch.get("ids", [])
            if not batch_ids:
                break
            for chunk_id, meta in zip(batch_ids, batch.get("metadatas", [])):
                existing_hashes[chunk_id] = meta.get("hash", "")
            if len(batch_ids) < _PAGE:
                break
            _offset += _PAGE
        print()  # end loading line

        tracked_set = set(tracked_files)

        to_delete = [
            cid for cid in existing_hashes
            if cid.split("::")[0] not in tracked_set
        ]

        docs_to_upsert = []
        metas_to_upsert = []
        ids_to_upsert = []
        skipped_files = []
        files_scanned = 0

        total_files = len(tracked_files)
        for filepath in tracked_files:
            files_scanned += 1
            _status(f"Scanning files... {files_scanned:,} / {total_files:,}")
            try:
                with open(self.root / filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except (UnicodeDecodeError, OSError) as e:
                skipped_files.append((filepath, type(e).__name__))
                continue

            if not lines:
                continue

            chunks = chunk_file(filepath, lines)
            file_type = classify_file(filepath)
            for idx, (start, end, text) in enumerate(chunks):
                chunk_id = f"{filepath}::{idx}"
                h = _sha256(text)
                if existing_hashes.get(chunk_id) == h:
                    continue  # unchanged, skip
                docs_to_upsert.append(text)
                metas_to_upsert.append({
                    "path": filepath,
                    "start_line": start,
                    "end_line": end,
                    "hash": h,
                    "lang": LANG_MAP.get(Path(filepath).suffix.lower(), "unknown"),
                    "file_type": file_type,
                })
                ids_to_upsert.append(chunk_id)

        print()  # end scanning line

        if skipped_files:
            print(f"Skipped {len(skipped_files)} file(s) (not indexable):")
            for path, reason in skipped_files:
                print(f"  {path} ({reason})")

        embeddings = emb_fn.embed(docs_to_upsert, show_progress=True) if docs_to_upsert else None
        if docs_to_upsert:
            print()  # end embedding line
        _batch_upsert(collection, docs_to_upsert, metas_to_upsert, ids_to_upsert, embeddings)
        _batch_delete(collection, to_delete)

        (self.index_dir / "langs.json").write_text(json.dumps(dict(lang_counts)))

        if use_bm25:
            # Update BM25 corpus (incremental: load existing, remove deleted, add/update upserted)
            bm25_corpus_path = self.index_dir / "bm25_corpus.json"
            try:
                bm25_corpus = json.loads(bm25_corpus_path.read_text()) if bm25_corpus_path.exists() else {}
            except Exception:
                bm25_corpus = {}
            for cid in to_delete:
                bm25_corpus.pop(cid, None)
            for cid, text in zip(ids_to_upsert, docs_to_upsert):
                bm25_corpus[cid] = text

            # Bootstrap: if corpus is still empty (first BM25 run on existing index), fetch all docs
            if not bm25_corpus and collection.count() > 0:
                _status("Bootstrapping BM25 corpus from index...")
                _page, _off = 5000, 0
                while True:
                    batch = collection.get(include=["documents"], limit=_page, offset=_off)
                    batch_ids = batch.get("ids", [])
                    if not batch_ids:
                        break
                    for cid, doc in zip(batch_ids, batch.get("documents", [])):
                        bm25_corpus[cid] = doc
                    if len(batch_ids) < _page:
                        break
                    _off += _page
                print()

            bm25_corpus_path.write_text(json.dumps(bm25_corpus))
            bm25_msg = f" | BM25 corpus: {len(bm25_corpus):,} chunks"
        else:
            bm25_msg = " | BM25: disabled"

        print(
            f"Files scanned: {files_scanned} | "
            f"Chunks upserted: {len(ids_to_upsert)} | "
            f"Chunks deleted: {len(to_delete)}"
            f"{bm25_msg}"
        )

        self.invalidate_caches()
        return {
            "files_scanned": files_scanned,
            "upserted": len(ids_to_upsert),
            "deleted": len(to_delete),
        }

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
        client = self._chroma()
        try:
            collection = client.get_collection(name=COLLECTION_NAME)
        except Exception as e:
            raise IndexMissingError(f"no index found at {self.index_dir} ({e})")

        count = collection.count()
        if count == 0:
            return []

        emb_fn = self._emb_fn()
        query_embedding = emb_fn([query])[0]

        where = None
        use_file_type = False
        source_langs: set = set()
        if not all_files:
            if _has_file_type_metadata(collection):
                where = {"file_type": {"$in": ["prod", "test"]}}
                use_file_type = True
            else:
                langs_file = self.index_dir / "langs.json"
                if langs_file.exists():
                    try:
                        lang_counts = json.loads(langs_file.read_text())
                        source_langs = {lang for lang in lang_counts if lang not in _DOC_LANGS}
                    except Exception:
                        source_langs = set()
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

        loaded = self._load_bm25() if use_bm25 else None
        bm25, id_list = loaded if loaded is not None else (None, [])
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

        return merge_chunks(items)


class IndexMissingError(Exception):
    pass
