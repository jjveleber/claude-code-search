# code-search

Semantic code search for any project. Install with one command — Claude can then find relevant code by natural language query instead of grep/glob.

## Prerequisites

- Python 3.9+
- A git repository (the indexer uses `git ls-files`)

## Install

Run from the root of any project:

```bash
curl -fsSL https://raw.githubusercontent.com/jjveleber/code-search/main/install.sh | bash
```

This will:
- Detect or create a `.venv` in your project and install `chromadb` into it
- Copy `index_project.py` and `search_code.py` into your project root
- Add `chroma_db/` to your `.gitignore`
- Append the Precision Protocol block to your `CLAUDE.md` (creates it if missing)
- Build the initial search index

The first index run is proportional to repo size and may take a minute or more on large repos.

## Re-index

After significant code changes:

```bash
source .venv/bin/activate && python3 index_project.py
```

The indexer is incremental — only changed chunks are re-embedded, so re-runs are fast.

## Search

```bash
source .venv/bin/activate && python3 search_code.py "database connection"
```

Returns the top 5 most relevant code chunks with file paths and line numbers.

## What Gets Installed

| Item | Location |
|---|---|
| `index_project.py` | project root |
| `search_code.py` | project root |
| `chroma_db/` | project root (created on first index) |
| Precision Protocol block | appended to `CLAUDE.md` |
| `chroma_db/` entry | appended to `.gitignore` |

## Upgrade

Re-running the installer does not overwrite existing files (local edits are preserved). To upgrade:

```bash
rm index_project.py search_code.py
curl -fsSL https://raw.githubusercontent.com/jjveleber/code-search/main/install.sh | bash
```

## Uninstall

```bash
rm -rf index_project.py search_code.py chroma_db/
```

Then remove the block between `<!-- code-search:start -->` and `<!-- code-search:end -->` from `CLAUDE.md`, and remove the `chroma_db/` line from `.gitignore`.

## How It Works

1. `git ls-files` enumerates all tracked files (respects `.gitignore` automatically)
2. Each file is split into ~60-line chunks with 10-line overlap, breaking at blank lines to keep functions intact
3. Chunks are embedded using ChromaDB's built-in local ONNX model (all-MiniLM-L6-v2) — no API key required, runs fully offline
4. On re-index, only chunks whose content has changed (SHA-256 hash comparison) are re-embedded
5. `search_code.py` queries the vector DB and merges overlapping result chunks before printing
