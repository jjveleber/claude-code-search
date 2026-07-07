# Central Install Design

**Date:** 2026-07-07
**Status:** Approved design
**Supersedes:** per-repo `install.sh` installation model

## Problem

Today every repo gets its own full installation: five Python scripts copied into the repo root, a multi-gigabyte `.venv-code-search` (torch + chromadb), a `chroma_db/` index, two hook scripts, a Precision Protocol block in `.claude/CLAUDE.md`, and hook entries in `.claude/settings.local.json`. N repos means N venvs, N copies of the code, N embedding models in RAM when sessions overlap, and N places to upgrade. The tool is intended only for Claude Code, so the per-repo generality buys nothing.

## Goal

Install once, globally, as a Claude Code plugin. Enable or disable per repo. Enabled repos remain 100% untouched — no files, no gitignore edits, no local settings. All code, data, and state live centrally.

## Decisions (settled during brainstorming)

1. **Packaging:** Claude Code plugin — hooks, slash command, and engine ship together; versioned upgrades via plugin update.
2. **Enable model:** opt-in via central registry. `/code-search enable` records the repo's realpath in `~/.code-search/registry.json`. No marker files in the repo. Hooks check the registry and exit silently for unregistered repos.
3. **Process model:** one daemon serves all enabled repos. It loads the embedding model once and watches a repo's filesystem only while a Claude session is active there. On session start it runs a catch-up incremental index (covering changes made while unwatched — git pull, editor edits) and then watches continuously, re-indexing on every change regardless of source.
4. **Migration:** per-repo mode is removed entirely. `/code-search enable` detects an old per-repo install and cleans it up automatically. Old indexes are discarded and rebuilt centrally.

## Architecture

### Plugin repo layout (this repo, restructured)

```
claude-code-search/
├── .claude-plugin/plugin.json     # name, version, hooks config
├── hooks/
│   ├── session_start.sh           # registry gate, venv/daemon boot, watch, inject protocol
│   └── session_end.sh             # unwatch
├── commands/
│   └── code-search.md             # /code-search enable|disable|status|reindex
├── bin/
│   └── code-search                # thin client: socket call, direct fallback
└── engine/                        # python package: chunker, indexer, daemon, search
```

Existing `chunker.py`, indexing, and search logic move into `engine/` — reused, not rewritten. `search_server.py` and `watch_index.py` merge into the daemon.

### Central data dir

```
~/.code-search/
├── venv/                          # single venv: torch, chromadb, watchdog
├── registry.json                  # {repo_id: {path, enabled_at, last_indexed}}
├── config.json                    # plugin-owned config (tracking phases, TTLs)
├── indexes/<repo_id>/chroma_db/   # per-repo vector index
├── logs/                          # daemon log, search_usage.jsonl, warnings
├── state/<session_id>             # per-session tracking state
├── daemon.sock
└── daemon.pid
```

The plugin directory is replaced on plugin update, so nothing mutable lives there. `CODE_SEARCH_HOME` env var overrides `~/.code-search` (used by tests).

**Repo identity:** `repo_id = sha256(realpath(repo))[:16]`. The readable path is stored alongside it in the registry.

## Components

### 1. Daemon (`engine/daemon.py`)

Single process, JSON-over-Unix-socket protocol on `~/.code-search/daemon.sock`. Merges today's `search_server.py` (hot model) and `watch_index.py` (fs watching), multiplexed across repos.

Commands:

| Command | Behavior |
|---|---|
| `watch {repo, session_pid}` | catch-up incremental index, then start watchdog observer for repo; refcounted per session |
| `unwatch {repo, session_pid}` | drop this session's ref; observer stops at zero refs |
| `search {repo, query, top, bm25, all}` | embed query (model hot), query repo's chroma collection, merge overlapping chunks, label `[prod]/[test]/[doc]/[generated]` |
| `reindex {repo}` | force full incremental pass |
| `status` | watched repos, index stats, uptime |

- Embedding model loaded lazily on first index/search.
- Per-repo watchdog observer with debounced incremental re-index (same hash-diff logic as today).
- Watch entries carry the session pid; the daemon periodically prunes entries whose pid is dead (SessionEnd hook is not guaranteed to fire).
- No watched repos for 10 minutes → daemon exits.

### 2. Hooks (plugin-registered, global)

**SessionStart:**
1. `realpath($CLAUDE_PROJECT_DIR)` in registry? No → exit 0 (silent, near-zero cost).
2. Venv missing or requirements changed since last sync → bootstrap into `~/.code-search/venv` (one-time; failure prints a one-line stderr warning and the session proceeds without search).
3. Daemon not running (stale sock/pid detected via connect-fail + dead pid) → clean up, spawn detached.
4. Send `watch`.
5. Emit Precision Protocol as `additionalContext` — the protocol text references `code-search search "<query>"`. This replaces the per-repo `.claude/CLAUDE.md` block.

**SessionEnd:** send `unwatch`. Best-effort; pid pruning is the backstop.

### 3. Client (`bin/code-search`)

What Claude invokes per the Precision Protocol: `code-search search "<query>"`. Resolves repo from cwd, connects to the socket. If the daemon is dead: performs a direct in-process search (cold, slow path) and respawns the daemon in the background.

### 4. Slash command (`/code-search`)

- `enable` — realpath → registry (atomic write: tmp + rename, flock), auto-migrate old install if present, trigger first index, report.
- `disable` — remove from registry, unwatch. Index kept by default (re-enable is cheap); `disable --purge` also deletes `indexes/<repo_id>/`.
- `status` — registry entries, dead paths flagged, daemon state, index freshness.
- `reindex` — force pass.

## Data flow

**Session start:** hook gates on registry → venv/daemon ensured → `watch` → catch-up index + fs observer → protocol injected into context.

**Search:** `code-search search "q"` → socket → daemon embeds + queries repo collection → merged, labeled results on stdout. Daemon dead → direct fallback + background respawn.

**During session:** fs events → debounced incremental re-index.

**Session end:** `unwatch`; last watched repo + 10 min grace → daemon exits.

**Concurrency:** same repo, two sessions → refcounted watch. Different repos → same daemon, separate collections and observers.

## Migration (inside `/code-search enable`)

Detect and remove, in the target repo only (surgical — only known installed names, sentinel-checked blocks):

1. Kill that repo's `watch_index.py` / `search_server.py` processes.
2. Delete: `index_project.py`, `search_code.py`, `watch_index.py`, `chunker.py`, `search_server.py`, `migrate_add_file_type.py`, `hooks/post_search_code.sh`, `hooks/pre_read_grep_glob.sh` (and `hooks/` if empty), `.venv-code-search/`, `chroma_db/`, `.watch_index.log`, `.watch_index.pid`, `.search_server.pid`, `.code-search-version`.
3. Strip the sentinel-marked Precision Protocol block from `.claude/CLAUDE.md`; delete the file if empty after.
4. Strip the watcher `UserPromptSubmit` and tracking hook entries from `.claude/settings.local.json`.
5. Remove the `.gitignore` lines the old installer added.
6. Register centrally and build a fresh index.

## Error handling

- **Stale socket/pid:** connect-fail + dead-pid check → clean + respawn (logic carried over from `search_server.py`).
- **Venv bootstrap failure** (no python3.12, disk full): hook warns once on stderr, session proceeds without search; `enable` fails loudly.
- **Repo moved/renamed:** realpath no longer matches → hooks stay silent; `status` flags dead entries; `enable` at the new path re-registers (fresh index).
- **Daemon crash mid-session:** next search takes the direct fallback path, respawns daemon, hook-registered watches restored on reconnect (`watch` re-sent by client after respawn).
- **Registry writes:** atomic tmp + rename under flock.

## Testing

- **Unit (pytest):** registry ops, repo-id derivation, socket protocol encode/decode, migration file-detection logic.
- **Daemon integration:** spawn daemon against a fixture repo in a tmpdir with `CODE_SEARCH_HOME` pointing at a fake home; assert watch → index → search → unwatch → idle-exit.
- **E2E (adapt current bash suite):** construct a fake old per-repo install → `enable` → assert complete cleanup + working central search. Hook scripts exercised with mocked `CLAUDE_PROJECT_DIR`.
- Existing chunker/indexer/search tests carry over into `engine/`.

## Future-feature adaptation

These features are NOT built in this project, but the design guarantees they fit. When picked up, follow this mapping — do not resurrect the per-repo patterns.

### A. Search usage tracking (existing `feature/search-usage-tracking` work, reworked)

| Old (per-repo) | New (central) |
|---|---|
| `search_code.py` appends `logs/search_usage.jsonl` in the repo | Daemon logs every search to `~/.code-search/logs/search_usage.jsonl`; each event carries `repo_id` and `session_id` |
| `hooks/post_search_code.sh` sets last-search state per repo | Plugin `PostToolUse` hook (global, registry-gated) writes `~/.code-search/state/<session_id>` |
| `hooks/pre_read_grep_glob.sh` detects Precision Protocol violations | Plugin `PreToolUse` hook, same registry gate — unregistered repos get zero noise |
| `tools/analyze_search_usage.py` standalone script | `code-search analytics [--repo] [--period] [--skill] [--model]` subcommand reading the central log; cross-repo comparison comes free |
| Config under `searchUsageTracking` in `~/.claude/settings.json` | `~/.code-search/config.json`; phase semantics unchanged (Phase 1 observe → Phase 2 `warningsVisible` → Phase 3 `warningsBlocking`) |

### B. RuVector self-learning (see `docs/ruvector-self-learning-integration.md`)

- The learning layer lives **in the daemon**. The daemon already sees query → results, and (via the tracking state above) which file Claude read next — that is the click-through signal.
- Per-repo learning state persists at `~/.code-search/indexes/<repo_id>/learning/`.
- The daemon's persistence makes online learning viable: model and Q-state stay hot across searches, which the old cold-start-per-query CLI could never support.
- The re-rank step inserts between the chroma query and chunk-merge inside the daemon's search path — a single, well-defined insertion point.
- The usage log from (A) is the training-signal source; **A is a prerequisite for B**.

## Out of scope

- Usage tracking and self-learning implementation (documented above for adaptation only).
- Non-Claude-Code consumers (tool is Claude Code only by decision).
- Windows-native support (WSL2 and macOS are the targets, as today).
