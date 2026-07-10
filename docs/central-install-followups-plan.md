# Central-install follow-ups — execution plan

Post-merge cleanup of PR #27 deferred items. Detail lives in the GitHub issues; this is sequencing + model routing only.

**Principle:** one PR per wave (one review cycle), work inline, tests land with their fix.

**Branch base:** PR #27 (`feature/central-install`) is NOT yet merged, and every wave's fixes depend on central-install code that lives only on that branch (not `main`). So each wave = its own sub-branch off `feature/central-install`, PR targeting `feature/central-install` (stacked on #27), not `main`. "Post-merge cleanup" in the title is aspirational — until #27 merges, base = `feature/central-install`. Re-target to `main` only once #27 has merged. Never commit wave fixes directly onto `feature/central-install`; keep the per-wave review cycle.

## Orchestration
- **Orchestrator (this controller): Opus 4.8.** Holds the plan, routes dispatches, adjudicates reviews, owns the Wave 3 lock-order judgment. Do NOT downgrade the controller — a weak orchestrator mis-adjudicates concurrency and mis-routes work. Fast mode OK (still Opus 4.8).
- **Subagents do the bulk edits on the cheap model named per wave.** Controller stays lean: dispatch → receive report → review → merge. Controller should not itself write Wave 1/4 mechanical edits when a Haiku subagent can.
- Every dispatch pins its model explicitly (implementer + reviewer).

## Context management (clear/compact)
Durable state = this file + the GitHub issues + PR/commit history. Conversation memory is NOT the handoff. So clearing is cheap — use it.
- **`/clear` at every wave boundary** (after a wave's PR is merged/approved). Fresh context per wave keeps controller input tokens small. Re-seed the new session by reading this plan + `gh issue view`.
- **`/compact` only mid-wave** if a single wave's context balloons (most likely Wave 3 concurrency debugging) and the task isn't done yet.
- **Never `/clear` or `/compact` with uncommitted work or an un-filed decision** — commit or record it in this file first.
- Wave 3 is the one wave likely to need a mid-wave compact; Waves 1/2/4 should each fit one context window → clear between, don't compact.

### Controller duty (so these fire, not just sit here)
A plan file prompts nothing. To get told when: the orchestrator MUST do this.
- **On every session start, first action: read this file.** It re-seeds the cleared session and reloads this duty.
- **When a wave's PR is approved/merged → STOP and tell the user: "Wave N done — run `/clear`, then re-read this plan to start Wave N+1."** Do not silently roll into the next wave.
- **Mid-wave, if you notice context growing large (long Wave 3 debug) → tell the user to `/compact`.** (Auto-compact is the backstop if you miss it.)
- Update the wave checkboxes above + commit before prompting a clear, so state survives the wipe.

## Wave 1 — docs / one-liners  ·  model: Haiku 4.5  ·  ✅ DONE (PR #41 merged, adversarial review clean)
Single PR. No concurrency reasoning.
- [x] #38 README: stale `search_code.py` ref + worktree first-search claim
- [x] #40 test_hooks.sh Test 6 comment (venv.ok inaccuracy)
- [x] #33 ensure_daemon daemon.log fd leak (close in parent)

## Wave 2 — WSL2 / UX correctness  ·  model: Sonnet 5  ·  ✅ DONE (PR #42 merged)
One PR. Real pain on this machine (WSL2).
- [x] #35 RepoWatch.stop() joins observer under daemon.lock → daemon stall. Collect under lock, stop/join after release. (4 sites: cmd_unwatch, cmd_unwatch_all, prune_loop, main() shutdown.)
- [x] #29 empty-repo permanent `warming` + client stale-warming: distinct `empty` (daemon) + `timeout` (client) statuses; cli maps warming/empty/timeout to messages.

**Adversarial review caught a real bug pre-merge:** the empty-vs-warming check first used the global `IndexQueue.active()` bool, so a genuinely-empty repo reported `warming` (→ client retries to `warm_deadline`, then `timeout`) whenever ANY other repo was indexing — the daemon's normal multi-repo state, defeating #29. Fixed: `IndexQueue` now tracks the active repo_id (`active_repo()`); `active()` keeps global-bool semantics for the drain/idle-exit callers.

**Known follow-up (NOT fixed — Wave 4 candidate):** if a repo's first index *raises* (disk/embed error), `count()` stays 0 and it now reports `empty` ("no indexable files") with no auto-retry — a false claim vs the pre-#29 permanent-`warming`. Needs an index-succeeded flag / error state; out of scope for #29's empty-vs-warming distinction.

## Wave 3 — concurrency hardening  ·  model: Opus 4.8  ·  reviewer escalate to Opus if subtle
Highest judgment. Each fix needs a real-daemon test. Aware of lock-order with #35.
- [x] #30 cmd_watch clone outside lock → torn sqlite. Route clone through IndexQueue (seed_from in _queue_index; runs on single worker → serialized behind active index, no double-clone).
- [x] #36 _load_bm25 flag-before-corpus, no lock. Double-checked lock; build into local, set flag LAST.
- [x] #37 daemon shutdown kills handler threads mid-response. Track handler threads; drain_handlers() bounded-join at shutdown before teardown.

## Wave 4 — latent / degenerate today  ·  model: Haiku/Sonnet, opportunistic  ·  ✅ DONE (PR #44 merged; adversarial review caught venv-rmtree false-report, fixed)
Fold into related feature work, not standalone.
- [ ] #31 warmup hardcodes CodeRankEmbed — **DEFERRED, kept open:** blocked on multi-model support (only CodeRankEmbed exists); fix WITH it, not before.
- [x] #34 migrate _clean_settings whole-block match — now filters per-hook-command; co-mingled user hook in same block survives. (Haiku)
- [x] #39 migrate cross-device venv move — `.venv-code-search` now `rmtree`'d (reproducible) not trashed; new `report["deleted"]`. (Haiku)
- [x] Wave 2 index-failure follow-up (plan line 41): first index raising reported false `empty`. IndexQueue now tracks `_failed`; cmd_search returns new `index_error` status; cli points at reindex. Race: failure recorded + active_repo cleared in one lock section. (Sonnet)

## Cross-cutting
- #32 test debt: **both live gaps closed (branch `test/issue-32-test-debt`, PR stacked on `feature/central-install`).**
  - ✅ `engine/setup_venv.py` — `tests/engine/test_setup_venv.py`: `venv_ok()` marker-vs-sha256 (no mocks) + `main()` success-only invariant (subprocess.run stub: pip-success writes `venv.ok`, pip-fail leaves no marker).
  - ✅ CLI paths — `tests/engine/test_cli.py` extended: `status`(up/down)/`gc`/`reindex`(queued/error/unavail)/`setup`/`enable --dry-run`, all 4 `except client.DaemonUnavailable` branches, and search-status mapping (`warming`/`empty`/`timeout`/`index_error`).
  - ✅ prune / idle-exit — already covered (`test_prune_loop_waits_for_active_queue_job`, `..._idle_exits_...`, Waves 2/3). Struck.
  - ⚪ log-rotation — no rotation feature exists (`daemon.log` is plain append). Moot until built. Struck.

## Remaining after Wave 4 (all 4 waves DONE)
1. ~~**#32 test debt** — write tests for the two live gaps above (setup_venv, CLI paths).~~ ✅ DONE (branch `test/issue-32-test-debt`; +9 setup_venv tests, +13 CLI tests; `tests/engine/` 92 green).
2. **#31** — deferred, blocked on multi-model support. Kept open.
3. **#27 (`feature/central-install`) → `main`** — the base branch is NOT yet merged; all 4 waves stack on it.
   - ✅ **Adversarial review of PR #27 done (3 Fable reviewers: concurrency / search-status / bootstrap-migrate-leak).** Caught a CRITICAL (`disable --purge` racing the index worker) + ~a dozen real findings. Prior-wave fixes (#29/#30/#34/#35/#36/#37) all re-verified holding. Scope chosen: fix ALL real bugs.
   - ✅ **Fixes in PR #46 (`fix/pr27-adversarial-review`), stacked on `feature/central-install`.** `tests/engine/` 99 green (+7). Covers: disable-purge torn-write, atomic bm25/model/langs writes, model-load-failure wedge, restart false-empty self-heal, swallowed-reindex warning, stale-flush resurrection, cmd_search auto-register, venv_ok existence check, migrate tracked-file skip + symlink venv + kill-wait, cmd_enable migrate guard, Popen fd leak, drain_handlers robustness.
   - **NEXT: merge #46 → `feature/central-install`; then merge #27 → `main`; then re-target/close deferred items (#31).**

## Sequencing caveats
- **#30 + #35 both touch daemon locking** — do them lock-order-aware (same person, ideally adjacent) to avoid re-touching twice.
- Reviewer per wave: Sonnet 5; Opus 4.8 only for Wave 3 concurrency subtlety.
