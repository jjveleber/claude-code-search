"""One-off migration: add file_type metadata to existing ChromaDB chunks.

Classifies each chunk's file path as prod/test/doc/generated using
path-based heuristics and updates the metadata in-place.
Embeddings and documents are not modified — no re-indexing required.

Usage:
    python3 migrate_add_file_type.py           # apply changes
    python3 migrate_add_file_type.py --dry-run # preview breakdown only
"""
import argparse
import sys

import chromadb
from index_project import CHROMA_PATH, COLLECTION_NAME, classify_file

BATCH_SIZE = 5000


def run(dry_run=False):
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception as e:
        print(f"Error: could not open collection. Run index_project.py first. ({e})")
        sys.exit(1)

    total = collection.count()
    print(f"Collection: {total:,} chunks")

    counts: dict[str, int] = {}
    already_done = 0
    to_update_ids = []
    to_update_metas = []

    offset = 0
    processed = 0

    print("Scanning...")
    while True:
        batch = collection.get(
            limit=BATCH_SIZE,
            offset=offset,
            include=["metadatas"],
        )
        if not batch["ids"]:
            break

        for chunk_id, meta in zip(batch["ids"], batch["metadatas"]):
            if "file_type" in meta:
                already_done += 1
                ft = meta["file_type"]
            else:
                ft = classify_file(meta["path"])
                to_update_ids.append(chunk_id)
                to_update_metas.append({**meta, "file_type": ft})

            counts[ft] = counts.get(ft, 0) + 1

        processed += len(batch["ids"])
        print(f"\r  {processed:,} / {total:,}", end="", flush=True)
        offset += BATCH_SIZE

        if len(batch["ids"]) < BATCH_SIZE:
            break

    print()

    print("\nClassification breakdown:")
    for ft in ("prod", "test", "doc", "generated"):
        n = counts.get(ft, 0)
        pct = n / total * 100 if total else 0
        print(f"  {ft:12} {n:>8,}  ({pct:.1f}%)")
    other = {k: v for k, v in counts.items() if k not in ("prod", "test", "doc", "generated")}
    for ft, n in other.items():
        print(f"  {ft:12} {n:>8,}")
    if already_done:
        print(f"\n  {already_done:,} chunks already classified (counted above, skipped in update)")

    if not to_update_ids:
        print("\nNothing to update — all chunks already have file_type.")
        return

    print(f"\n{len(to_update_ids):,} chunks to update.")

    if dry_run:
        print("Dry run — no changes written.")
        return

    print("Writing...")
    total_update = len(to_update_ids)
    for i in range(0, total_update, BATCH_SIZE):
        batch_ids = to_update_ids[i:i + BATCH_SIZE]
        batch_metas = to_update_metas[i:i + BATCH_SIZE]
        collection.update(ids=batch_ids, metadatas=batch_metas)
        done = min(i + BATCH_SIZE, total_update)
        print(f"\r  {done:,} / {total_update:,}", end="", flush=True)
    print()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show classification breakdown without writing changes",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)
