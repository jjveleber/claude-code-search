---
name: prepare_claude_md_toggle
description: repo.py prepare command should auto-enable/disable the target codebase's CLAUDE.md for baseline vs run modes
type: project
---

`prepare baseline` should rename `<target>/.claude/CLAUDE.md` → `CLAUDE.md.disabled` to prevent Claude from using search instructions during baseline. `prepare run` should rename it back. Currently done manually.

**Why:** Without this, the baseline session could still follow the Precision Protocol (use search_code.py first) if CLAUDE.md is active, contaminating the baseline signal.

**How to apply:** Add CLAUDE.md toggle logic to `repo.py` `configure_hooks()` or `prepare()`. The target codebase path needs to be known — check how `index_project.py` resolves it.
