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
- Detect or create a `.venv-code-search` in your project and install `chromadb` and `watchdog` into it
- Copy `index_project.py`, `search_code.py`, `watch_index.py`, `chunker.py`, and `search_server.py` into your project root
- Add `chroma_db/`, `.watch_index.log`, `.watch_index.pid`, `.search_server.pid`, `.claude/settings.local.json`, and `.claude/CLAUDE.md` to your `.gitignore`
- Write the Precision Protocol block to `.claude/CLAUDE.md` (local-only, not committed)
- Write a `UserPromptSubmit` hook to `.claude/settings.local.json` (local-only, not committed) that auto-starts the watcher at the beginning of each Claude session
- Build the initial search index

Only the five Python scripts and the `.gitignore` additions are committed. The Precision Protocol and hook are local to each developer who runs the installer — teammates who pull the repo are not affected until they run it themselves.

The first index run is proportional to repo size and may take a minute or more on large repos.

## Re-index

The watcher (`watch_index.py`) runs in the background during Claude sessions and re-indexes automatically whenever files change. To re-index manually:

```bash
.venv-code-search/bin/python3 index_project.py
```

The indexer is incremental — only changed chunks are re-embedded, so re-runs are fast.

**BM25 hybrid search** is opt-in at both index and query time. Pass `--bm25` to build a keyword corpus alongside the vector index:

```bash
.venv-code-search/bin/python3 index_project.py --bm25
```

Then pass `--bm25` at query time to use Reciprocal Rank Fusion to merge semantic and keyword results:

```bash
.venv-code-search/bin/python3 search_code.py --bm25 "database connection"
```

To remove the BM25 corpus and revert to semantic-only: `index_project.py --disable-bm25`.

## Search

```bash
.venv-code-search/bin/python3 search_code.py "database connection"
```

Returns the top 5 most relevant code chunks with file paths and line numbers.

| Flag | Description |
|---|---|
| `--top N` | Return top N results (default: 5) |
| `--bm25` | Enable BM25 hybrid ranking (requires index built with `--bm25`) |
| `--all` | Include documentation and generated files in results (default: prod and test only) |

## Persistent Search Server

`search_server.py` is an optional background process that loads the embedding model once and serves search requests over a Unix socket. This eliminates the 3–7s cold-load penalty on every `search_code.py` call.

```bash
.venv-code-search/bin/python3 search_server.py &
```

`search_code.py` auto-detects the server socket and routes to it when available, falling back to direct execution silently. The server uses a project-specific socket in `/tmp/` and a `.search_server.pid` lock file in the project root (gitignored).

> **Note:** Unix sockets require a native Linux filesystem. On WSL2 with the project under `/mnt/c/`, the socket still works because it lives in `/tmp/`.

## Search Usage Tracking

**Goal:** Understand when and why semantic search is used (or should have been used) in superpowers workflows.

### How It Works

1. **Logging:** `search_code.py` logs every invocation to `logs/search_usage.jsonl`
2. **State Tracking:** Post-search hook sets `LAST_SEARCH_TIME` env var
3. **Compliance Monitoring:** Pre-tool hook detects violations of Precision Protocol
4. **Analytics:** `tools/analyze_search_usage.py` reports compliance rates, trends, breakdowns

### Viewing Analytics

```bash
# Full report
python3 tools/analyze_search_usage.py

# Last 7 days only
python3 tools/analyze_search_usage.py --period 7

# Filter by skill
python3 tools/analyze_search_usage.py --skill debugging

# Filter by model
python3 tools/analyze_search_usage.py --model claude-sonnet-4-5
```

### Configuration

Set in `~/.claude/settings.json`:

```json
{
  "searchUsageTracking": {
    "warningsVisible": false,      // Show warnings to Claude (Phase 2)
    "warningsBlocking": false,     // Block non-compliant tools (Phase 3)
    "searchStateTTL": 300,         // Search state expires after 5 min
    "recentPathTTL": 600           // Path tracking expires after 10 min
  }
}
```

**Phase 1 (current):** Observation mode — violations logged, hidden from Claude  
**Phase 2 (manual):** Set `warningsVisible: true` to show warnings  
**Phase 3 (future):** Set `warningsBlocking: true` to enforce compliance

### Log Files

- `logs/search_usage.jsonl` — Search events (JSONL format)
- `logs/search_warnings.log` — Precision Protocol violations (pipe-delimited)

Both files are gitignored and safe for ad-hoc analysis with pandas/jq.

## What Gets Installed

| Item | Location | Committed? |
|---|---|---|
| `index_project.py` | project root | yes |
| `search_code.py` | project root | yes |
| `watch_index.py` | project root | yes |
| `chunker.py` | project root | yes |
| `search_server.py` | project root | yes |
| `chroma_db/` | project root (created on first index) | no (gitignored) |
| Precision Protocol block | `.claude/CLAUDE.md` | no (gitignored) |
| `chroma_db/`, `.watch_index.log`, `.watch_index.pid`, `.search_server.pid`, `.claude/settings.local.json`, `.claude/CLAUDE.md` entries | `.gitignore` | yes |
| Auto-watcher `UserPromptSubmit` hook | `.claude/settings.local.json` | no (gitignored) |

## Upgrade

Re-running the installer does not overwrite existing files (local edits are preserved). To upgrade:

```bash
rm index_project.py search_code.py watch_index.py chunker.py search_server.py
curl -fsSL https://raw.githubusercontent.com/jjveleber/claude-code-search/main/install.sh | bash
```

## Uninstall

```bash
pkill -f watch_index.py || true
pkill -f search_server.py || true
rm -rf index_project.py search_code.py watch_index.py chunker.py search_server.py chroma_db/ .venv-code-search/ .watch_index.pid .watch_index.log .search_server.pid
```

> **Note:** Omit `.venv-code-search/` if it predated this installation (i.e. you brought your own virtual environment).

Then:
- Remove `.claude/CLAUDE.md`
- Remove the `chroma_db/`, `.watch_index.log`, `.watch_index.pid`, `.search_server.pid`, `.claude/settings.local.json`, and `.claude/CLAUDE.md` lines from `.gitignore`
- Remove `.claude/settings.local.json` (or just the `UserPromptSubmit` hook entry with `watch_index.py` if you have other settings there)

## Environment Variables

| Variable | Purpose |
|---|---|
| `CODE_SEARCH_OWNER` | Override the GitHub username used to build the raw download URL. Useful if you fork this repo. Default: `jjveleber`. Example: `CODE_SEARCH_OWNER=myname bash install.sh` |
| `CODE_SEARCH_LOCAL` | Copy scripts from a local directory instead of downloading via curl. Used by the integration test suite and for local development. Example: `CODE_SEARCH_LOCAL="." bash install.sh` |

## How It Works

1. `git ls-files` enumerates all tracked files (respects `.gitignore` automatically)
2. Each file is split into ~60-line chunks with 10-line overlap, breaking at blank lines to keep functions intact
3. Chunks are embedded using a model chosen by language: UniXcoder for systems languages (C/C++/Rust/Go/…), GraphCodeBERT for web/scripting, CodeBERT for config-only repos — no API key required, runs fully offline. Uses Apple MPS or AMD ROCm (auto-detected via `/dev/dxg` on WSL2) when available; otherwise CPU.
4. On re-index, only chunks whose content has changed (SHA-256 hash comparison) are re-embedded
5. `search_code.py` queries the vector DB (and BM25 corpus if present) and merges overlapping result chunks before printing

## Eval

An evaluation framework in `eval/` measures search quality at two levels:

- **Unit eval** — scores search results against known expected files, no Claude needed
- **Integration eval** — compares Claude Code sessions with and without search enabled, measuring navigation behavior

See [`eval/README.md`](eval/README.md) for usage details.
