import sys
import chromadb
from chromadb.utils import embedding_functions

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "project_code"


def merge_chunks(results):
    """Group results by file and merge overlapping line ranges."""
    items = []
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        text = results["documents"][0][i]
        items.append((meta["path"], meta["start_line"], meta["end_line"], text))

    items.sort(key=lambda x: (x[0], x[1]))

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


def search(query, n_results=5):
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    emb_fn = embedding_functions.DefaultEmbeddingFunction()
    try:
        collection = client.get_collection(
            name=COLLECTION_NAME, embedding_function=emb_fn
        )
    except Exception:
        print(
            "Error: no index found. Run 'python3 index_project.py' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    count = collection.count()
    if count == 0:
        print("No results found.")
        sys.exit(2)

    results = collection.query(
        query_texts=[query], n_results=min(n_results, count)
    )

    merged = merge_chunks(results)
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
    args = parser.parse_args()
    search(" ".join(args.query), n_results=args.top)
