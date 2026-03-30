---
name: token_estimation_bug
description: avg_estimated_tokens/task reports 0 in baseline report — needs fixing in session analyzer
type: project
---

`avg_estimated_tokens/task` reported as 0 in the baseline report (2026-03-27T22-53-11-baseline.json) and 2345 in the run report (2026-03-27T23-27-32-run.json). Baseline value of 0 is wrong — the token estimation logic in the session analyzer is broken for baseline mode.

**Why:** Not yet investigated. Deferred until after the search-enabled run completed.

**How to apply:** Fix before drawing conclusions about token cost tradeoff. The token question is the core open issue — search reduces tool calls but may increase token usage due to injected search results. Accurate numbers needed to evaluate this tradeoff.

Session logs to re-analyze after fix:
- /Users/jjveleber/projects/experiments/claude-code-search/.worktrees/eval-framework/eval/results/session-2026-03-27T21-24-41.log (baseline)
- /Users/jjveleber/projects/experiments/claude-code-search/.worktrees/eval-framework/eval/results/session-2026-03-27T23-06-30.log (run)
