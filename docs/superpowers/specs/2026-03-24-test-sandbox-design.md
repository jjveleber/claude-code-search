# Test Sandbox Design

**Date:** 2026-03-24
**Status:** Approved

## Overview

A sibling directory to `claude-code-search` that serves as an interactive testing sandbox. Used to clone real-world repositories and run the `install.sh` installer against them to surface issues.

## Goals

- Provide a clean, isolated place to clone test repos and run the installer manually
- Prevent confusion between test target repos and the source `claude-code-search` repo
- Make running the installer against a cloned repo require minimal typing

## Non-Goals

- Not a replacement for the automated test suite (`tests/test_install.sh`)
- No pre-seeded repos — repos are cloned on demand as issues arise
- Not a git repository itself

## Structure

```
code-search-sandbox/         ← sibling to claude-code-search/
  CLAUDE.md                  ← context note for Claude
  test-install.sh            ← installer wrapper script
  <cloned-repos>/            ← added on demand, not tracked
```

## Components

### `CLAUDE.md`

Tells Claude:
- This directory is a test sandbox for the `claude-code-search` installer
- Repos cloned here are test targets, not part of the source project
- The source repo is at `../claude-code-search/`
- Do not confuse these repos with the real one; do not index this directory as the project

### `test-install.sh`

A thin wrapper around `../claude-code-search/install.sh` that:
- Sets `CODE_SEARCH_LOCAL` to `../claude-code-search` (so scripts are copied locally, not downloaded via curl)
- Accepts an optional subdirectory argument — if provided, `cd`s into it before running the installer
- If no argument is given, runs the installer in the current working directory
- Resolves all paths relative to the script's own location so it works regardless of where it's called from

**Usage:**
```bash
# cd into a cloned repo and run:
cd some-cloned-repo
bash ../test-install.sh

# Or pass the repo as an argument from the sandbox root:
bash test-install.sh some-cloned-repo
```

## Workflow

1. Clone a repo into `code-search-sandbox/`
2. Run `bash test-install.sh <repo-name>` (or `cd` in and run `bash ../test-install.sh`)
3. Inspect results — check `CLAUDE.md`, `.gitignore`, `chroma_db/`, search output
4. Note any issues and investigate in the source repo

## Rationale

- **Sibling directory** keeps the sandbox fully outside the source repo — no risk of accidental commits or indexing
- **`CODE_SEARCH_LOCAL`** bypasses curl so the current local version of the scripts is tested, not the published GitHub version
- **No automation beyond the helper script** keeps the sandbox simple and low-maintenance
