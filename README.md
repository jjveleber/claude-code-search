# code-search

Semantic code search for Claude Code. Install once as a plugin — Claude can then find relevant code by natural language query instead of grep/glob, in any repo you enable.

## Prerequisites

- Python 3.12
- A git repository (the indexer uses `git ls-files`)

## Install

Install the plugin (loads it for the current Claude Code session):

```bash
claude --plugin-dir /path/to/claude-code-search
```

This works today from a local clone. A marketplace listing (`/plugin marketplace add ...` + `/plugin install code-search@...`) is the intended distribution route once this repo publishes a `.claude-plugin/marketplace.json` catalog — not yet available.

Once the plugin is loaded, bootstrap the central venv:

```bash
code-search setup
```

This installs the shared dependencies (chromadb, sentence-transformers/torch, watchdog, etc.) into `~/.code-search/venv` — several GB on first run, so expect it to take a few minutes. You can skip this step and let the first `code-search enable` run it for you instead.

Then, per repo you want indexed:

```bash
/code-search enable
```

This registers the repo centrally and queues the first index build. Nothing is written into the repo itself.

## Usage

```bash
code-search search "database connection"
```

Returns the top 5 most relevant code chunks with file paths and line numbers.

| Flag | Description |
|---|---|
| `--top N` | Return top N results (default: 5) |
| `--bm25` | Enable BM25 hybrid ranking (requires the repo enabled with `--bm25`) |
| `--all` | Include documentation and generated files in results (default: prod and test only) |

A `SessionStart` hook handles the rest automatically: it registers/watches the current repo with the central daemon, triggers a catch-up incremental index if files changed since last session, and injects the Precision Protocol (the "search before grep" rule) into context. There is nothing to start or stop manually.

**Git worktrees** are auto-enabled: the first search or session in a worktree of an already-enabled repo registers that worktree with its own index, seeded by cloning the main worktree's index and then catch-up indexing — so it's ready in seconds instead of a full rebuild.

**BM25 hybrid search** is opt-in per repo. Enable it at registration time:

```bash
/code-search enable --bm25
```

Then pass `--bm25` at query time to use Reciprocal Rank Fusion to merge semantic and keyword results.

## Data

Everything the tool owns lives under `~/.code-search` (override with `CODE_SEARCH_HOME`): the shared venv, the repo registry, per-repo/per-worktree indexes, daemon state, and logs. Enabled repos are otherwise untouched — no files, no `.gitignore` edits, no local settings.

> **Dotfile sync warning:** if you sync your home directory (chezmoi, a dotfiles repo, etc.), exclude `~/.code-search` — it holds multi-gigabyte venvs and machine-local indexes/sockets that should not travel between machines.

## Migrating from v1

The old per-repo install (five scripts copied into the repo root, a local `.venv-code-search`, hook entries in `.claude/settings.local.json`) is gone. To migrate each old repo, just run:

```bash
/code-search enable
```

`enable` detects the old install, kills any leftover watcher/server processes, and cleans up:
- Untracked old artifacts (`index_project.py`, `chroma_db/`, `.venv-code-search/`, pid/log files, etc.) are moved — not deleted — to `~/.code-search/trash/<repo_id>/` as a backup.
- Git-tracked copies of the old scripts are **skipped**, not touched; `enable` prints them so you can `git rm` them yourself.
- The Precision Protocol block is stripped from `.claude/CLAUDE.md`, the old hook entries are removed from `.claude/settings.local.json`, and the tool-specific lines are removed from `.gitignore`.

The repo is then registered centrally and a fresh index is built.

## Uninstall

Per repo:

```bash
code-search disable          # stop watching, keep the index
code-search disable --purge  # stop watching and delete the index
```

Then remove the plugin (drop the `--plugin-dir` flag / remove the marketplace install), and if you want to reclaim disk space entirely:

```bash
rm -rf ~/.code-search
```

## Releases

Releases are tagged as `vX.Y.Z` (e.g., `v2.0.0`). As of v2.0.0 the tool is distributed as a Claude Code plugin rather than a downloadable `install.sh` — see Install above. The release workflow (`.github/workflows/release.yml`) still packages and publishes the old `install.sh` asset and is currently broken for that reason; it needs to be redesigned around plugin/marketplace publishing before the next tag push.

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
