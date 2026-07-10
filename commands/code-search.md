---
description: Enable, disable, or inspect semantic code search for this repo
argument-hint: enable | disable [--purge] | status | reindex | gc | setup
---

Run the deterministic CLI and report its output. Do not perform any
enable/disable/migration steps yourself — the CLI does everything.

1. Run via Bash: `code-search $ARGUMENTS`
   (If `$ARGUMENTS` is empty, run `code-search status`.)
2. Show the user the command output verbatim.
3. If the output mentions tracked files that were skipped, tell the user
   they can remove them with `git rm` when ready.
4. If the command fails with a message about `code-search setup`, offer to
   run `code-search setup` (it downloads several GB on first run — warn
   the user before running it).
