import hashlib
import os
import subprocess
import sys
from pathlib import Path
from collections import Counter

import chromadb
from chromadb.utils.embedding_functions import EmbeddingFunction
from transformers import AutoTokenizer, AutoModel
import torch

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "project_code"
CHUNK_TARGET = 60
CHUNK_OVERLAP = 10
CHUNK_MAX = 120
CHROMA_MAX_BATCH = 5000

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


def detect_languages(files):
    langs = []
    for f in files:
        ext = Path(f).suffix.lower()
        if ext in LANG_MAP:
            langs.append(LANG_MAP[ext])
    return Counter(langs)


def choose_model(lang_counts):
    if not lang_counts:
        return "microsoft/graphcodebert-base"

    langs = set(lang_counts.keys())

    gcb_langs = {"python", "javascript", "java", "go", "php", "ruby"}
    systems_langs = {"rust", "cpp", "c", "csharp", "swift", "kotlin"}
    web_langs = {"javascript", "typescript", "html", "css", "scss", "svelte", "vue"}
    infra_langs = {"yaml", "json", "toml", "ini", "terraform", "docker", "kubernetes"}

    if langs.issubset(infra_langs):
        return "microsoft/codebert-base"

    return "microsoft/graphcodebert-base"


# --- HF embedding function with caching ---

class HFCodeEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name, device=None):
        self.model_name = model_name

        if model_name in _EMB_MODEL_CACHE:
            self.tokenizer, self.model, self.device = _EMB_MODEL_CACHE[model_name]
            return

        print(f"Loading model: {model_name}")
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name)

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        model.to(device)
        model.eval()

        self.tokenizer = tokenizer
        self.model = model
        self.device = device

        _EMB_MODEL_CACHE[model_name] = (tokenizer, model, device)

    def _choose_safe_batch_size(self, max_batch=170, safety_margin_gb=2.0):
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        avail = int(line.split()[1]) / 1_000_000
                        break
            else:
                avail = 4.0
        except Exception:
            avail = 4.0

        batch = max_batch
        while batch > 1:
            needed = 1.2 + batch * 0.18
            if needed + safety_margin_gb < avail:
                return batch
            batch //= 2
        return 1

    def embed(self, texts):
        """Embed all texts in memory-aware batches with unified progress display."""
        import time
        if isinstance(texts, str):
            texts = [texts]

        batch_size = self._choose_safe_batch_size()
        total = len(texts)
        batches_total = (total + batch_size - 1) // batch_size
        all_embeddings = []
        ema = None
        alpha = 0.2

        for batch_index, i in enumerate(range(0, total, batch_size), start=1):
            batch = texts[i:i + batch_size]
            start_time = time.time()

            encoded = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt"
            ).to(self.device)

            with torch.no_grad():
                outputs = self.model(**encoded)
                emb = outputs.last_hidden_state.mean(dim=1)

            all_embeddings.append(emb.cpu())

            batch_time = time.time() - start_time
            ema = batch_time if ema is None else alpha * batch_time + (1 - alpha) * ema
            batches_left = batches_total - batch_index
            eta_seconds = ema * batches_left
            mins, secs = int(eta_seconds // 60), int(eta_seconds % 60)
            _status(f"Embedding chunks... {batch_index}/{batches_total} batches | ETA {mins}m {secs}s")

        return torch.cat(all_embeddings, dim=0).numpy()

    def __call__(self, texts):
        """Called by ChromaDB for query-time embedding."""
        return self.embed(texts)


def index_files():
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    tracked_files = git_indexable_files()

    lang_counts = detect_languages(tracked_files)
    top_langs = ", ".join(lang for lang, _ in lang_counts.most_common(5)) or "none detected"
    model_name = choose_model(lang_counts)
    print(f"Languages: {top_langs}")
    print(f"Embedding model: {model_name}")

    emb_fn = HFCodeEmbeddingFunction(model_name)

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

    print()  # end scanning line

    if skipped_files:
        print(f"Skipped {len(skipped_files)} file(s) (not indexable):")
        for path, reason in skipped_files:
            print(f"  {path} ({reason})")

    embeddings = emb_fn.embed(docs_to_upsert) if docs_to_upsert else None
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
