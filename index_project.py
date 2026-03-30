import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from collections import Counter

import psutil

import chromadb
from chunker import chunk_file
from chromadb.utils.embedding_functions import EmbeddingFunction

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "project_code"
CHROMA_MAX_BATCH = 5000

_CODERANK_QUERY_PREFIX = "Represent this query for searching relevant code: "

# Global cache for the embedding model
_EMB_MODEL_CACHE = {}


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


def git_indexable_files():
    """Return tracked files plus untracked non-ignored files."""
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    chroma_dir = os.path.normpath(CHROMA_PATH).replace("\\", "/")
    seen = set()
    result = []
    for f in tracked + untracked:
        if (
            f.strip()
            and f not in seen
            and not f.startswith(chroma_dir + "/")
            and f != chroma_dir
        ):
            seen.add(f)
            result.append(f)
    return result


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Language detection ---

LANG_MAP = {
    # --- Major languages ---
    ".py": "python", ".pyw": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala", ".go": "go", ".rs": "rust",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    ".cc": "cpp", ".cxx": "cpp", ".hh": "cpp",
    ".cs": "csharp", ".vb": "visualbasic",
    ".swift": "swift", ".m": "objective-c", ".mm": "objective-cpp",
    ".php": "php", ".rb": "ruby", ".rake": "ruby",
    ".pl": "perl", ".pm": "perl", ".lua": "lua",

    # --- Shell / scripting ---
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".fish": "shell", ".ps1": "powershell",
    ".psm1": "powershell", ".psd1": "powershell",
    ".bat": "batch", ".cmd": "batch",

    # --- Web / templating ---
    ".html": "html", ".htm": "html", ".css": "css",
    ".scss": "scss", ".sass": "sass", ".less": "less",
    ".vue": "vue", ".svelte": "svelte",
    ".ejs": "ejs", ".hbs": "handlebars",
    ".mustache": "mustache", ".jinja": "jinja",
    ".jinja2": "jinja", ".twig": "twig",

    # --- Data / config ---
    ".json": "json", ".jsonc": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".ini": "ini", ".cfg": "ini",
    ".conf": "config", ".env": "dotenv",
    ".properties": "properties",

    # --- Build systems ---
    ".gradle": "gradle", ".gradle.kts": "gradle",
    ".pom": "maven", ".xml": "xml",
    ".makefile": "make", ".mk": "make",
    ".cmake": "cmake", ".bazel": "bazel",
    ".bzl": "bazel", ".ninja": "ninja",

    # --- Infrastructure / DevOps ---
    ".tf": "terraform", ".tfvars": "terraform",
    ".dockerfile": "docker", ".dockerignore": "docker",
    ".compose": "docker-compose",
    ".helm": "helm", ".chart": "helm",
    ".k8s": "kubernetes",

    # --- SQL / DB ---
    ".sql": "sql", ".psql": "sql", ".mysql": "sql",
    ".sqlite": "sql",

    # --- Functional languages ---
    ".hs": "haskell", ".lhs": "haskell",
    ".ml": "ocaml", ".mli": "ocaml",
    ".elm": "elm", ".clj": "clojure",
    ".cljs": "clojure", ".cljc": "clojure",
    ".erl": "erlang", ".hrl": "erlang",
    ".ex": "elixir", ".exs": "elixir",

    # --- GPU / shader languages ---
    ".glsl": "glsl", ".vert": "glsl", ".frag": "glsl",
    ".hlsl": "hlsl", ".metal": "metal",

    # --- Misc scripting ---
    ".r": "r", ".rmd": "rmarkdown",
    ".jl": "julia", ".dart": "dart",
    ".nim": "nim", ".zig": "zig",
    ".vala": "vala",

    # --- DSLs / niche ---
    ".proto": "protobuf", ".thrift": "thrift",
    ".graphql": "graphql", ".gql": "graphql",
    ".asm": "assembly", ".s": "assembly",
    ".ahk": "autohotkey", ".tex": "latex",
    ".bib": "bibtex", ".md": "markdown",
    ".rst": "restructuredtext",
}


# --- File type classification ---

_TEST_DIRS = frozenset({
    "test", "tests", "__tests__", "spec", "specs",
    "e2e", "integration", "unit", "functional",
    "testdata", "test_data", "fixtures",
})
_DOC_DIRS = frozenset({
    "doc", "docs", "documentation", "Doc", "pydoc_data",
    "man", "_site", "site",
})
_GEN_DIRS = frozenset({
    "clinic", "generated", "__generated__", "gen", "auto-generated",
})
_DOC_EXTS = frozenset({".md", ".rst", ".adoc", ".txt"})


def classify_file(filepath):
    """Classify a file as prod/test/doc/generated based on path heuristics.

    Order: doc → generated → test → prod (prod is the default).
    Biased toward prod when uncertain — a prod file misclassified as test
    is excluded from default searches, which is worse than test noise.
    """
    p = Path(filepath)
    parts = p.parts
    name = p.name
    suffix = p.suffix.lower()

    # Doc: extension-based
    if suffix in _DOC_EXTS:
        return "doc"

    # Doc: directory-based
    if any(part in _DOC_DIRS for part in parts):
        return "doc"

    # Generated: directory-based
    if any(part in _GEN_DIRS for part in parts):
        return "generated"

    # Generated: file naming
    if name.endswith(("_pb2.py", "_pb2_grpc.py")):
        return "generated"
    if ".generated." in name or name.endswith(".generated"):
        return "generated"

    # Test: directory-based
    if any(part in _TEST_DIRS for part in parts):
        return "test"

    # Test: filename patterns
    if name.startswith("test_") or name.endswith((
        "_test.py", "_test.go", "_test.rb", "_test.rs",
        "_spec.rb", "_test.c", "_test.cpp",
    )):
        return "test"
    if any(name.endswith(ext) for ext in (
        ".test.ts", ".spec.ts", ".test.js", ".spec.js",
        ".test.tsx", ".spec.tsx", ".test.jsx", ".spec.jsx",
    )):
        return "test"
    if name.endswith(("Test.java", "Tests.java", "Spec.java", "IT.java")):
        return "test"

    return "prod"


def detect_languages(files):
    langs = []
    for f in files:
        ext = Path(f).suffix.lower()
        if ext in LANG_MAP:
            langs.append(LANG_MAP[ext])
    return Counter(langs)


def choose_model(lang_counts):
    """Return the embedding model to use."""
    return "nomic-ai/CodeRankEmbed"


# --- Embedding function ---

class HFCodeEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name, device=None):
        self.model_name = model_name

        if model_name in _EMB_MODEL_CACHE:
            self._st_model = _EMB_MODEL_CACHE[model_name]
            return

        print(f"Loading model: {model_name}")
        from sentence_transformers import SentenceTransformer
        st_model = SentenceTransformer(model_name, trust_remote_code=True, device=device)
        st_model.max_seq_length = 512
        self._st_model = st_model
        _EMB_MODEL_CACHE[model_name] = st_model

    def _choose_safe_batch_size(self, max_batch=64, safety_margin_gb=2.0):
        try:
            avail = psutil.virtual_memory().available / 1e9
        except Exception:
            avail = 4.0

        batch = max_batch
        while batch > 1:
            needed = 1.2 + batch * 0.18
            if needed + safety_margin_gb < avail:
                return batch
            batch //= 2
        return 1

    def embed(self, texts, show_progress=False):
        """Embed texts for indexing (no query prefix)."""
        if isinstance(texts, str):
            texts = [texts]

        batch_size = self._choose_safe_batch_size()
        print(f"Embedding batch size: {batch_size}")
        return self._st_model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
        )

    def __call__(self, texts):
        """Called by ChromaDB at query time — adds query prefix."""
        if isinstance(texts, str):
            texts = [texts]
        prefixed = [_CODERANK_QUERY_PREFIX + t for t in texts]
        return self._st_model.encode(prefixed, convert_to_numpy=True)


def index_files():
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    tracked_files = git_indexable_files()

    lang_counts = detect_languages(tracked_files)
    top_langs = ", ".join(lang for lang, _ in lang_counts.most_common(5)) or "none detected"
    model_name = choose_model(lang_counts)
    print(f"Languages: {top_langs}")
    print(f"Embedding model: {model_name}")

    emb_fn = HFCodeEmbeddingFunction(model_name)

    # Write model name and language counts so search_code.py can load the same
    # embedding function and apply the correct language filter.
    Path(CHROMA_PATH).mkdir(parents=True, exist_ok=True)
    Path(CHROMA_PATH, "model.txt").write_text(model_name)
    Path(CHROMA_PATH, "langs.json").write_text(json.dumps(dict(lang_counts)))

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=emb_fn
    )

    _status("Loading index...")
    existing = collection.get(include=["metadatas"])
    print()  # end loading line

    existing_hashes = {}
    for chunk_id, meta in zip(existing.get("ids", []), existing.get("metadatas", [])):
        existing_hashes[chunk_id] = meta.get("hash", "")

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
            with open(filepath, "r", encoding="utf-8") as f:
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
            h = sha256(text)
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

    print(
        f"Files scanned: {files_scanned} | "
        f"Chunks upserted: {len(ids_to_upsert)} | "
        f"Chunks deleted: {len(to_delete)}"
    )


if __name__ == "__main__":
    index_files()
