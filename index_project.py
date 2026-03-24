import hashlib
import subprocess
import sys
import chromadb
from chromadb.utils import embedding_functions

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "project_code"
CHUNK_TARGET = 60
CHUNK_OVERLAP = 10
CHUNK_MAX = 120


def git_tracked_files():
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    return [f for f in result.stdout.splitlines() if f.strip()]


def chunk_lines(lines):
    """Yield (start_line_1indexed, end_line_1indexed, text) tuples."""
    chunks = []
    i = 0
    overlap_lines = []
    while i < len(lines):
        chunk = overlap_lines + []
        start = i - len(overlap_lines)
        # accumulate up to target
        while i < len(lines) and (i - start) < CHUNK_TARGET:
            chunk.append(lines[i])
            i += 1
        # extend to next blank line, up to hard max
        while i < len(lines) and (i - start) < CHUNK_MAX:
            if lines[i].strip() == "":
                chunk.append(lines[i])
                i += 1
                break
            chunk.append(lines[i])
            i += 1
        if not chunk:
            break
        # 1-indexed line numbers
        chunk_start = start + 1
        chunk_end = start + len(chunk)
        chunks.append((chunk_start, chunk_end, "".join(chunk)))
        # overlap: last CHUNK_OVERLAP lines become prefix of next chunk
        overlap_lines = lines[max(0, i - CHUNK_OVERLAP):i]
    return chunks


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def index_files():
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    emb_fn = embedding_functions.DefaultEmbeddingFunction()
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME, embedding_function=emb_fn
    )

    # Load existing chunks from ChromaDB
    existing = collection.get(include=["metadatas"])
    existing_hashes = {}
    for chunk_id, meta in zip(existing["ids"], existing["metadatas"]):
        existing_hashes[chunk_id] = meta.get("hash", "")

    tracked_files = git_tracked_files()
    tracked_set = set(tracked_files)

    # Find chunk IDs that belong to files no longer tracked
    to_delete = [
        cid for cid in existing_hashes
        if cid.split("::")[0] not in tracked_set
    ]

    docs_to_upsert = []
    metas_to_upsert = []
    ids_to_upsert = []
    files_scanned = 0

    for filepath in tracked_files:
        files_scanned += 1
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except (UnicodeDecodeError, OSError) as e:
            print(f"  Warning: skipping {filepath} ({type(e).__name__})", file=sys.stderr)
            continue

        if not lines:
            continue

        chunks = chunk_lines(lines)
        for idx, (start, end, text) in enumerate(chunks):
            chunk_id = f"{filepath}::{idx}"
            h = sha256(text)
            if existing_hashes.get(chunk_id) == h:
                continue  # unchanged, skip
            docs_to_upsert.append(text)
            metas_to_upsert.append({
                "path": filepath,
                "start_line": start,
                "end_line": end,
                "hash": h,
            })
            ids_to_upsert.append(chunk_id)

    if ids_to_upsert:
        collection.upsert(
            documents=docs_to_upsert,
            metadatas=metas_to_upsert,
            ids=ids_to_upsert,
        )

    if to_delete:
        collection.delete(ids=to_delete)

    print(
        f"Files scanned: {files_scanned} | "
        f"Chunks upserted: {len(ids_to_upsert)} | "
        f"Chunks deleted: {len(to_delete)}"
    )


if __name__ == "__main__":
    index_files()
