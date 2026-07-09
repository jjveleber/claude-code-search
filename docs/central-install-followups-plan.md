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
- [ ] #30 cmd_watch clone outside lock → torn sqlite. Route clone through IndexQueue.
- [ ] #36 _load_bm25 flag-before-corpus, no lock (self-heals; set flag after corpus, under lock).
- [ ] #37 daemon shutdown kills handler threads mid-response (graceful drain; note spec deviation).

## Wave 4 — latent / degenerate today  ·  model: Haiku/Sonnet, opportunistic
Fold into related feature work, not standalone.
- [ ] #31 warmup hardcodes CodeRankEmbed — fix WITH multi-model support, not before.
- [ ] #34 migrate _clean_settings whole-block match — unreachable w/ real installer.
- [ ] #39 migrate cross-device venv move — delete (reproducible), don't move.

## Cross-cutting
- #32 test debt: **no standalone pass** — write the missing test as part of each wave (setup_venv, CLI paths, prune/idle-exit). Close #32 when the residue is empty or keep as tracking.

## Sequencing caveats
- **#30 + #35 both touch daemon locking** — do them lock-order-aware (same person, ideally adjacent) to avoid re-touching twice.
- Reviewer per wave: Sonnet 5; Opus 4.8 only for Wave 3 concurrency subtlety.
