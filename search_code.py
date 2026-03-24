import sys
import chromadb
from chromadb.utils import embedding_functions

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "project_code"


def merge_chunks(results):
    """Group results by file and merge overlapping line ranges."""
    # Build list of (path, start, end, text) sorted by file then start
    items = []
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        text = results["documents"][0][i]
        items.append((meta["path"], meta["start_line"], meta["end_line"], text))

    items.sort(key=lambda x: (x[0], x[1]))

    merged = []
    for path, start, end, text in items:
        if merged and merged[-1][0] == path and start <= merged[-1][2] + 1:
            # overlapping or adjacent — merge
            prev_path, prev_start, prev_end, prev_text = merged[-1]
            new_end = max(prev_end, end)
            merged[-1] = (prev_path, prev_start, new_end, prev_text + text)
        else:
            merged.append([path, start, end, text])

    return merged


def search(query, n_results=5):
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    emb_fn = embedding_functions.DefaultEmbeddingFunction()
    collection = client.get_collection(
        name=COLLECTION_NAME, embedding_function=emb_fn
    )
    results = collection.query(query_texts=[query], n_results=n_results)

    merged = merge_chunks(results)
    for i, (path, start, end, text) in enumerate(merged, 1):
        print(f"MATCH {i}: {path} (lines {start}-{end})")
        print("-" * 40)
        print(text)
        if not text.endswith("\n"):
            print()
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 search_code.py '<query>'")
        sys.exit(1)
    search(" ".join(sys.argv[1:]))
