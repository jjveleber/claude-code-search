# Central Install Design

**Date:** 2026-07-07 (revised same day after adversarial review)
**Status:** Approved design, revised per adversarial review findings
**Supersedes:** per-repo `install.sh` installation model

## Problem

Today every repo gets its own full installation: five Python scripts copied into the repo root, a multi-gigabyte `.venv-code-search` (torch + chromadb), a `chroma_db/` index, two hook scripts, a Precision Protocol block in `.claude/CLAUDE.md`, and hook entries in `.claude/settings.local.json`. N repos means N venvs, N copies of the code, N embedding models in RAM when sessions overlap, and N places to upgrade. The tool is intended only for Claude Code, so the per-repo generality buys nothing.

## Goal

Install once, globally, as a Claude Code plugin. Enable or disable per repo. Enabled repos remain 100% untouched — no files, no gitignore edits, no local settings. All code, data, and state live centrally.

## Decisions (settled during brainstorming and review)

1. **Packaging:** Claude Code plugin — hooks, slash command, and engine ship together; versioned upgrades via plugin update. Plugin `bin/` is on the Bash tool PATH, so Claude invokes the client as bare `code-search`.
2. **Enable model:** opt-in via central registry. `code-search enable` records the repo in `~/.code-search/registry.json`. No marker files in the repo. Hooks check the registry and exit silently for unregistered repos.
3. **Process model:** one daemon serves all enabled repos. It loads the embedding model once and watches a repo's filesystem only while a Claude session is active there. On session start it runs a catch-up incremental index and then watches continuously.
4. **Migration:** per-repo mode is removed entirely. `code-search enable` detects an old per-repo install and cleans it up — with ownership verification and backup, never blind deletion (see Migration).
5. **Worktrees:** per-worktree index with inherited enablement. Enabling a repo enables all its worktrees; each worktree gets its own id and index, seeded by cloning the main index then catch-up indexing. Orphaned indexes are garbage-collected.
6. **All state-changing logic lives in the `code-search` CLI**, not in slash-command markdown. Slash commands are LLM-interpreted prompts and must not be trusted to perform destructive multi-step operations; `commands/code-search.md` simply instructs Claude to run `code-search <args>` and report the output.

## Architecture

### Plugin repo layout (this repo, restructured)

```
claude-code-search/
├── .claude-plugin/plugin.json     # name, version, hooks config
├── hooks/
│   ├── session_start.sh           # registry gate, daemon ensure, watch, inject protocol
│   └── session_end.sh             # unwatch (best-effort)
├── commands/
│   └── code-search.md             # thin wrapper: "run `code-search $ARGUMENTS`"
├── bin/
│   └── code-search                # client launcher (execs central venv python)
└── engine/                        # python package: chunker, indexer, daemon, search, cli
```

### Central data dir

```
~/.code-search/
├── venv/                          # single venv: torch, chromadb, watchdog
├── venv.ok                        # written on successful bootstrap; contains requirements hash
├── registry.json                  # repos + worktrees (see schema below)
├── config.json                    # plugin-owned config (tracking phases, TTLs, memory budget)
├── indexes/<repo_id>/chroma_db/   # per-worktree vector index (+ BM25 corpus if enabled)
├── state/watches.json             # daemon watch table, persisted for crash recovery
├── state/<session_id>.json        # per-session tracking state (future feature A)
├── trash/<repo_id>/               # migration backups (see Migration)
├── logs/                          # daemon log, search_usage.jsonl, warnings
├── daemon.sock
└── daemon.pid                     # flock-guarded
```

The plugin directory is replaced on plugin update, so nothing mutable lives there. `CODE_SEARCH_HOME` env var overrides `~/.code-search` (used by tests). `~/.code-search` must be excluded from dotfile sync — sockets, pids, and indexes are machine-local and registry paths differ per machine; the README documents this.

### Repo identity and registry schema

- **Repo root resolution:** `git rev-parse --show-toplevel` from the session/search directory — never raw cwd, since Claude routinely runs Bash from subdirectories.
- **Repo family:** `git rev-parse --git-common-dir` identifies the main repo shared by all its worktrees.
- **`repo_id` = `sha256(realpath(worktree_root))[:16]`** — one id and one index per worktree.

```json
{
  "repos": {
    "<family_id>": {
      "main_path": "/home/u/projects/foo",
      "enabled_at": "...",
      "bm25": false,
      "worktrees": {
        "<repo_id>": {"path": "...", "last_indexed": "...", "auto_registered": true}
      }
    }
  }
}
```

- **Inherited enablement:** SessionStart in an unregistered worktree resolves its family; if the family is enabled, the worktree is auto-registered with its own id and index. No manual enable per worktree.
- **Index seeding:** when a new worktree registers and the main worktree's index exists, the daemon pauses index writes for that family, copies `indexes/<main_id>/` to `indexes/<new_id>/`, then runs a normal incremental catch-up against the worktree (hash-diff re-embeds only branch-divergent chunks, prunes deleted files, rebuilds the BM25 corpus if enabled). First worktree index drops from minutes to seconds. Fresh build is the fallback when no main index exists.
- **GC:** on daemon start and on `code-search status`, registered paths that no longer exist are marked dead; entries dead for 7 days have their index and registry entry removed. `code-search gc` runs this on demand.
- **Known limitation (documented, not solved):** the same directory reachable via two absolute paths (WSL2 `/mnt/c/...` vs a bind mount) registers as two repos. Multi-uid use (`sudo claude`) sees a different `~` and therefore an empty registry.

## Components

### 1. Daemon (`engine/daemon.py`)

Single process, JSON-over-Unix-socket protocol on `~/.code-search/daemon.sock`.

**This is a refactor, not a lift-and-shift.** The existing engine is pervasively cwd-relative (`CHROMA_PATH = "./chroma_db"`, `git ls-files`/`git check-ignore` from cwd, relative log paths, `INDEX_CMD` referencing `.venv-code-search`). The implementation plan must budget for introducing a `RepoIndex(root, index_dir)` abstraction that parameterizes every index/search/watch operation by explicit repo root and index directory. `os.chdir()` is banned in the daemon (threads race). The chunker, hash-diff incremental indexing, chunk merge, and result labeling logic carry over conceptually but their entry points are rewritten. Existing tests that monkeypatch cwd/module globals need the same rework.

Commands:

| Command | Behavior |
|---|---|
| `watch {repo, session_pid}` | resolve/auto-register worktree, seed index if needed, catch-up incremental index (queued), start fs observer; refcounted per session |
| `unwatch {repo, session_pid}` | drop this session's ref; observer stops at zero refs |
| `search {repo, query, top, bm25, all}` | embed query, query repo's collection, merge overlapping chunks, label `[prod]/[test]/[doc]/[generated]` |
| `reindex {repo}` | force incremental pass (queued) |
| `status` | watched repos, index stats, queue depth, uptime |

**Lifecycle:**

- **Singleton:** the flock on `daemon.pid` (the `acquire_pid_lock` pattern from `watch_index.py`) is the *only* spawn gate. A process that fails to acquire the lock exits without touching the socket. Hooks and clients never "clean up" sockets or pid files they don't own.
- **Socket creation:** bind to a temp path, then `rename` over `daemon.sock` — no unlink-before-bind race.
- **Shutdown order:** unlink socket → drain in-flight requests → persist watch table → release lock → exit. A `watch` arriving during shutdown gets a connection error and the hook retries (respawning if needed) until it receives a positive `watch` ack.
- **Warming handshake:** the embedding model loads lazily. While loading, `search` replies `{"status": "warming"}`; the client waits and retries with a long deadline (model load is 30–60s warm, minutes on first HF download). **There is no in-process client fallback** — all chroma access stays in exactly one process (concurrent multi-process access to a chroma persist dir is unsupported and the old 10s-timeout fallback would fire spuriously on every cold start, double-loading the model).
- **Crash recovery:** the watch table (`repo_id`, `path`, `session_pid`) is persisted to `state/watches.json` on every change. On startup the daemon restores entries whose pid is still alive and queues catch-up for each — so a respawn after crash restores *all* sessions' watches, not just the repo whose search triggered the respawn.
- **Dead-session pruning:** SessionEnd is best-effort; the daemon periodically prunes watch entries whose session pid is dead.
- **Idle exit:** no watched repos for 10 minutes → clean shutdown.

**Indexing discipline:**

- Single-worker index job queue — embedding is CPU-heavy; concurrent catch-ups for several repos must not starve search. Search requests are served between jobs (model shared, queries cheap).
- Ignore checks are batched (`git check-ignore --stdin` or cached exclude rules) — never one subprocess per fs event (the `.venv` runaway-process incident multiplies by N repos in a central daemon). Built-in ignore set widened: `node_modules/`, build output dirs, `.venv*`, `__pycache__`, `chroma_db`.
- After every index pass, the repo's BM25 corpus and collection filter caches are invalidated and lazily reloaded (the current server loads BM25 once at startup and never reloads — a bug that a long-lived daemon would turn into permanently stale keyword results).
- **WSL2 `/mnt/c` repos:** inotify delivers no events on drvfs/9p mounts. The daemon detects the mount fs type and uses watchdog's `PollingObserver` for such paths.

**Memory:** per-repo chroma collection handles and BM25 corpora are LRU-closed after an idle TTL; `config.json` carries a memory budget. Watched-but-idle repos cost near zero.

### 2. Hooks (plugin-registered, global)

Hooks read their input as JSON on stdin (the real interface — see Future-feature adaptation for why this is called out).

**SessionStart:**
1. Resolve repo root and family; not enabled → exit 0 (silent, near-zero cost).
2. `venv.ok` missing or its requirements hash stale → print one-line stderr warning telling the user to run `code-search setup`; session proceeds without search. **No bootstrap in hooks** — a multi-GB torch install must not run inside session start (hook timeout kills it mid-pip, leaving a venv that exists but is broken).
3. Ensure daemon: try socket; on failure attempt spawn (flock decides the winner); require a positive `watch` ack with bounded retries.
4. Emit Precision Protocol as `additionalContext` — references `code-search search "<query>"`. Replaces the per-repo `.claude/CLAUDE.md` block. Cost: ~400 tokens, re-injected on resume/clear/compact; accepted deliberately.

**SessionEnd:** send `unwatch`. Best-effort; pid pruning is the backstop.

### 3. Client (`bin/code-search`)

A small launcher that execs `~/.code-search/venv/bin/python3 -m engine.cli` with the plugin's `engine/` on `sys.path` (the launcher knows its own location, so no reliance on `CLAUDE_PLUGIN_ROOT` at Bash-tool time). Subcommands:

- `search "<query>" [--top N] [--bm25] [--all]` — resolve repo via `git rev-parse --show-toplevel`, socket call, warming-aware retry. Daemon unreachable → attempt spawn, retry; still failing → one actionable error message. No in-process search.
- `enable [--bm25]` / `disable [--purge]` / `status` / `reindex` / `gc` / `setup` / `analytics` (future).
- `setup` — the venv bootstrap: flock-serialized, installs into `~/.code-search/venv`, writes `venv.ok` (requirements hash) only on success. Run by `enable` automatically (interactive, loud, user consented); never by hooks.

### 4. Slash command (`/code-search`)

`commands/code-search.md` contains no logic: "Run `code-search $ARGUMENTS` via Bash and report the output." All enable/disable/migration behavior is deterministic CLI code with `--dry-run` support.

## Data flow

**Session start:** hook gates on registry (family-aware) → daemon ensured (flock singleton) → `watch` ack required → catch-up queued + fs observer started → protocol injected.

**Search:** `code-search search "q"` → socket → warming-aware wait → daemon embeds + queries → merged, labeled results on stdout.

**During session:** fs events → debounced, queued incremental re-index → BM25/filter caches invalidated.

**Session end:** `unwatch`; dead-pid pruning as backstop; last repo + 10 min → daemon exits.

**Concurrency:** same repo, two sessions → refcounted watch. Two worktrees of one repo → independent ids, indexes, observers — no shared-index thrash.

## Migration (inside `code-search enable`)

**Gate:** migration runs only on positive evidence of an old install — `.code-search-version` file, or `chroma_db/` whose contents match the known layout (model marker + `project_code` collection). No evidence → no deletion of anything, even name-matches.

**Ownership rules:**
- A file/dir is removed only if it is **untracked in git** (`git ls-files --error-unmatch` fails). Tracked files (someone committed the old scripts — or the repo *is* this project) are left in place with a warning listing them. This also protects a user's own `chroma_db/` in a RAG project (no version marker → no gate → untouched) and a pre-existing `.venv-code-search` is only removed if the version marker proves the installer created content in it; otherwise warned.
- Removal is **move to `~/.code-search/trash/<repo_id>/`**, not `rm -rf`. Trash is GC'd after 30 days.

**Steps (deterministic CLI, `--dry-run` supported):**
1. Kill the repo's `watch_index.py` / `search_server.py` — pid from pidfiles, verified against `/proc/<pid>/cmdline` containing the script name before kill (pid reuse guard).
2. Trash (ownership-gated): `index_project.py`, `search_code.py`, `watch_index.py`, `chunker.py`, `search_server.py`, `migrate_add_file_type.py`, `hooks/post_search_code.sh`, `hooks/pre_read_grep_glob.sh` (remove `hooks/` only if empty after), `.venv-code-search/`, `chroma_db/`, `.watch_index.log`, `.watch_index.pid`, `.search_server.pid`, `.code-search-version`.
3. Strip the sentinel-marked Precision Protocol block from `.claude/CLAUDE.md`; delete the file if empty after.
4. `settings.local.json`: remove hook entries matched by **substring** (`search_code.py`, `watch_index.py`, `pre_read_grep_glob`, `post_search_code`) across both historical shapes (top-level keys and nested under `"hooks"`), plus the `searchUsageTracking` key. Exact-string matching is insufficient — installed variants embed differing absolute paths.
5. `.gitignore`: remove only tool-specific lines (`chroma_db/`, `.venv-code-search/`, `.watch_index.log`, `.watch_index.pid`, `.search_server.pid`, `.code-search-version`). **Never** remove generic lines the old installer also wrote (`.venv/`, `__pycache__/`, `.claude/settings.local.json`, `.claude/CLAUDE.md`) — the user may rely on them.
6. Register centrally, run `setup` if needed, build fresh index.
7. Print a full report of what was moved, what was skipped (tracked), and where the backup lives.

## Error handling

- **Stale socket/pid:** flock is authoritative. Lock held → daemon alive (socket connect retried); lock free → previous daemon dead, spawner cleans pid/socket *after* acquiring the lock.
- **Venv missing/broken:** hooks warn and continue; `enable`/`setup` fail loudly with the pip error. `venv.ok` hash marker distinguishes "broken/partial" from "present".
- **Repo moved/renamed:** realpath no longer matches → hooks silent; `status` flags dead entries; GC reaps them; `enable` at the new path re-registers.
- **Daemon crash mid-session:** next search (or next SessionStart) respawns; persisted watch table restores *all* live sessions' watches and queues catch-up for each.
- **Registry and watch-table writes:** atomic tmp + rename under flock.
- **Log/state growth:** `logs/search_usage.jsonl` rotated by size; `state/<session_id>.json` files GC'd by TTL on daemon start; trash GC'd after 30 days.

## Testing

- **Unit (pytest):** registry ops (family/worktree resolution), repo-id derivation, protocol encode/decode, migration gating (version-marker evidence, git-tracked skip, gitignore line whitelist), hook-entry substring matching against both historical settings shapes.
- **Daemon integration:** spawn against fixture repos in tmpdir with `CODE_SEARCH_HOME` override; assert watch → index → search → unwatch → idle-exit; crash → respawn → watch-table restore; worktree auto-register → index clone + catch-up; concurrent spawn race (two spawners, one winner via flock); warming handshake.
- **E2E (adapt current bash suite):** fake old per-repo install (including a git-tracked-scripts variant and a user-owned-chroma_db variant) → `enable` → assert correct migration, correct skips, working central search, clean `settings.local.json`. Hook scripts exercised with stdin JSON fixtures and mocked `CLAUDE_PROJECT_DIR`.
- Chunker/indexer/search logic tests carry over; cwd-dependent tests are reworked against `RepoIndex(root, index_dir)`.

## Future-feature adaptation

These features are NOT built in this project, but the design guarantees they fit. When picked up, follow this mapping — do not resurrect the per-repo patterns.

**⚠ The old tracking hooks are known-broken and must not be ported faithfully.** `hooks/pre_read_grep_glob.sh` and `hooks/post_search_code.sh` read `$TOOL_NAME`, `$TOOL_PARAMS`, `$TOOL_COMMAND`, `$TOOL_OUTPUT` environment variables that Claude Code has never set — hooks receive a JSON payload on **stdin** (`tool_name`, `tool_input`, `tool_response`, `session_id`, ...). The old scripts' guards therefore always exit early; they have never logged a violation. Likewise `export LAST_SEARCH_TIME` cannot persist across hook processes, and `$CLAUDE_MODEL`/`$CLAUDE_SKILL` don't exist, so the analytics `--skill`/`--model` dimensions have only ever recorded "unknown". Reimplement against the stdin-JSON interface with file-based state.

### A. Search usage tracking (existing `feature/search-usage-tracking` work, respecified)

| Concern | New (central) implementation |
|---|---|
| Search event logging | Daemon logs every search to `~/.code-search/logs/search_usage.jsonl`; each event carries `repo_id` and `session_id` (rotated by size) |
| Last-search state | Plugin `PostToolUse` hook (global, registry-gated): stdin JSON → if `tool_input.command` contains `code-search search`, write timestamp+query to `~/.code-search/state/<session_id>.json` |
| Violation detection | Plugin `PreToolUse` hook, same registry gate: stdin JSON `tool_name` ∈ {Read, Grep, Glob} → compare against session state file; unregistered repos get zero noise |
| Analytics | `code-search analytics [--repo] [--period]` reading the central log; cross-repo comparison comes free. `--skill`/`--model` only if those fields actually exist in hook input at implementation time — verify against current docs, do not assume |
| Config | `~/.code-search/config.json`; phase semantics unchanged (Phase 1 observe → Phase 2 warn → Phase 3 block) |

### B. RuVector self-learning (see `docs/ruvector-self-learning-integration.md`)

- The learning layer lives **in the daemon**. Click-through signal: the `PostToolUse` hook for **Read** (stdin JSON `tool_input.file_path`) correlated with the session's recent search results via `state/<session_id>.json` — not by parsing Bash stdout.
- Per-repo learning state persists at `~/.code-search/indexes/<repo_id>/learning/`.
- The daemon's persistence makes online learning viable: model and Q-state stay hot across searches, which the old cold-start-per-query CLI could never support.
- The re-rank step inserts between the chroma query and chunk-merge inside the daemon's search path — a single, well-defined insertion point.
- The usage log from (A) is the training-signal source; **A is a prerequisite for B**.

## Out of scope

- Usage tracking and self-learning implementation (documented above for adaptation only).
- Non-Claude-Code consumers (tool is Claude Code only by decision).
- Windows-native support (WSL2 and macOS are the targets; `/mnt/c` polling covered above).
- Dual-path (bind-mount) dedup and multi-uid support (documented limitations).
