# code-search

Semantic code search for any project. Install with one command — Claude can then find relevant code by natural language query instead of grep/glob.

## Prerequisites

- Python 3.12
- A git repository (the indexer uses `git ls-files`)

## Install

Run from the root of any project:

```bash
curl -fsSL https://raw.githubusercontent.com/jjveleber/claude-code-search/main/install.sh | bash
```

This will:
- Detect or create a `.venv` in your project and install `chromadb` and `watchdog` into it
- Copy `index_project.py`, `search_code.py`, and `watch_index.py` into your project root
- Add `chroma_db/`, `.watch_index.log`, `.watch_index.pid`, `.claude/settings.local.json`, and `.claude/CLAUDE.md` to your `.gitignore`
- Write the Precision Protocol block to `.claude/CLAUDE.md` (local-only, not committed)
- Write a `UserPromptSubmit` hook to `.claude/settings.local.json` (local-only, not committed) that auto-starts the watcher at the beginning of each Claude session
- Build the initial search index

Only the three Python scripts and the `.gitignore` additions are committed. The Precision Protocol and hook are local to each developer who runs the installer — teammates who pull the repo are not affected until they run it themselves.

The first index run is proportional to repo size and may take a minute or more on large repos.

## Re-index

The watcher (`watch_index.py`) runs in the background during Claude sessions and re-indexes automatically whenever files change. To re-index manually:

```bash
.venv/bin/python3 index_project.py
```

The indexer is incremental — only changed chunks are re-embedded, so re-runs are fast.

## Search

```bash
.venv/bin/python3 search_code.py "database connection"
```

Returns the top 5 most relevant code chunks with file paths and line numbers.

## What Gets Installed

| Item | Location | Committed? |
|---|---|---|
| `index_project.py` | project root | yes |
| `search_code.py` | project root | yes |
| `watch_index.py` | project root | yes |
| `chroma_db/` | project root (created on first index) | no (gitignored) |
| Precision Protocol block | `.claude/CLAUDE.md` | no (gitignored) |
| `chroma_db/`, `.watch_index.log`, `.watch_index.pid`, `.claude/settings.local.json`, `.claude/CLAUDE.md` entries | `.gitignore` | yes |
| Auto-watcher `UserPromptSubmit` hook | `.claude/settings.local.json` | no (gitignored) |

## Upgrade

Re-running the installer does not overwrite existing files (local edits are preserved). To upgrade:

```bash
rm index_project.py search_code.py watch_index.py
curl -fsSL https://raw.githubusercontent.com/jjveleber/claude-code-search/main/install.sh | bash
```

## Uninstall

```bash
pkill -f watch_index.py || true
rm -rf index_project.py search_code.py watch_index.py chroma_db/ .venv/ .watch_index.pid .watch_index.log
```

> **Note:** Omit `.venv/` if it predated this installation (i.e. you brought your own virtual environment).

Then:
- Remove `.claude/CLAUDE.md`
- Remove the `chroma_db/`, `.watch_index.log`, `.watch_index.pid`, `.claude/settings.local.json`, and `.claude/CLAUDE.md` lines from `.gitignore`
- Remove `.claude/settings.local.json` (or just the `UserPromptSubmit` hook entry with `watch_index.py` if you have other settings there)

## Environment Variables

| Variable | Purpose |
|---|---|
| `CODE_SEARCH_OWNER` | Override the GitHub username used to build the raw download URL. Useful if you fork this repo. Default: `jjveleber`. Example: `CODE_SEARCH_OWNER=myname bash install.sh` |
| `CODE_SEARCH_LOCAL` | Copy scripts from a local directory instead of downloading via curl. Used by the integration test suite and for local development. Example: `CODE_SEARCH_LOCAL="." bash install.sh` |

## How It Works

1. `git ls-files` enumerates all tracked files (respects `.gitignore` automatically)
2. Each file is split into ~60-line chunks with 10-line overlap, breaking at blank lines to keep functions intact
3. Chunks are embedded using ChromaDB's built-in local ONNX model (all-MiniLM-L6-v2) — no API key required, runs fully offline
4. On re-index, only chunks whose content has changed (SHA-256 hash comparison) are re-embedded
5. `search_code.py` queries the vector DB and merges overlapping result chunks before printing
