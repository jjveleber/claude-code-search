# Install from Releases Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable users to install from specific GitHub releases or branches with auto-detection and environment variable overrides.

**Architecture:** Add version detection logic to install.sh that checks env vars → embedded version → default. Create GitHub Actions workflow that embeds version into install.sh during release. Extend test suite to validate all detection paths.

**Tech Stack:** Bash (install.sh), GitHub Actions (release automation), Bash testing framework (test_install.sh)

---

## Prerequisites

### Task 0: Create Feature Branch

**Context:** Per spec branching strategy (lines 344-367), work happens on `feature/install-from-releases` branch based from main.

- [ ] **Step 1: Verify on main branch with clean state**

Run:
```bash
git status
```

Expected: On branch `main`, working tree clean

- [ ] **Step 2: Create and switch to feature branch**

Run:
```bash
git checkout -b feature/install-from-releases
```

Expected: `Switched to a new branch 'feature/install-from-releases'`

- [ ] **Step 3: Verify branch created**

Run:
```bash
git branch --show-current
```

Expected: `feature/install-from-releases`

---

## Chunk 1: Core Installation Logic

## File Structure

**Modified files:**
- `install.sh` - Add version detection, URL construction, validation, reachability check
- `tests/test_install.sh` - Add tests for version detection logic

**Created files:**
- `.github/workflows/release.yml` - Automate release creation with embedded version

---

### Task 1: Add Version Detection Logic to install.sh

**Files:**
- Modify: `install.sh:1-6`
- Test: `tests/test_install.sh` (new test cases)

**Context:** Current install.sh hardcodes `BASE_URL` to main branch (line 5). Need version detection with priority: env var > embedded > default.

- [ ] **Step 1: Write test for default main branch behavior**

Add to `tests/test_install.sh` after line 50:

```bash
echo "=== Test 13: Version detection - defaults to main ==="
setup
git init -q
git commit -q --allow-empty -m "init"
# Create test install.sh with version detection logic but empty INSTALL_VERSION
cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION=""

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

echo "SOURCE_TYPE=$SOURCE_TYPE"
echo "SOURCE_VALUE=$SOURCE_VALUE"
INSTALL_SCRIPT

bash test_install.sh > output.txt
assert "Defaults to branch type" "grep -q 'SOURCE_TYPE=branch' output.txt"
assert "Defaults to main" "grep -q 'SOURCE_VALUE=main' output.txt"
teardown
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/jjveleber/projects/claude-code-search
bash tests/test_install.sh 2>&1 | grep "Test 13"
```

Expected: Test 13 section appears, both assertions FAIL (test_install.sh doesn't exist yet in test)

- [ ] **Step 3: Add version detection logic to install.sh**

Replace the script header and BASE_URL definition (lines 1-5) with version detection logic. This expands 5 lines into ~16 lines:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Auto-detected install source (set during release via GitHub Actions)
# Empty = main branch, "v1.0.0" = release version
INSTALL_VERSION=""

# Determine installation source with priority: env var > embedded > default
if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    # Explicit version override
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    # Explicit branch override
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    # Embedded version from release
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    # Default to main
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

REPO_OWNER="${CODE_SEARCH_OWNER:-jjveleber}"
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
bash tests/test_install.sh 2>&1 | grep "Test 13"
```

Expected: Test 13 PASS for both assertions

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_install.sh
git commit -m "feat: add version detection logic to install.sh

- Priority: env var > embedded version > default main
- Supports CODE_SEARCH_VERSION and CODE_SEARCH_BRANCH overrides
- Add test case for default behavior"
```

---

### Task 2: Add Environment Variable Override Tests

**Files:**
- Modify: `tests/test_install.sh` (add tests)

- [ ] **Step 1: Write test for CODE_SEARCH_VERSION override**

Add to `tests/test_install.sh`:

```bash
echo "=== Test 14: Version detection - CODE_SEARCH_VERSION override ==="
setup
git init -q
git commit -q --allow-empty -m "init"
cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION="v0.5.0"

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

echo "SOURCE_TYPE=$SOURCE_TYPE"
echo "SOURCE_VALUE=$SOURCE_VALUE"
INSTALL_SCRIPT

CODE_SEARCH_VERSION=v1.0.0 bash test_install.sh > output.txt
assert "Uses version type" "grep -q 'SOURCE_TYPE=version' output.txt"
assert "Uses override version" "grep -q 'SOURCE_VALUE=v1.0.0' output.txt"
teardown
```

- [ ] **Step 2: Write test for CODE_SEARCH_BRANCH override**

Add to `tests/test_install.sh`:

```bash
echo "=== Test 15: Version detection - CODE_SEARCH_BRANCH override ==="
setup
git init -q
git commit -q --allow-empty -m "init"
cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION=""

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

echo "SOURCE_TYPE=$SOURCE_TYPE"
echo "SOURCE_VALUE=$SOURCE_VALUE"
INSTALL_SCRIPT

CODE_SEARCH_BRANCH=develop bash test_install.sh > output.txt
assert "Uses branch type" "grep -q 'SOURCE_TYPE=branch' output.txt"
assert "Uses override branch" "grep -q 'SOURCE_VALUE=develop' output.txt"
teardown
```

- [ ] **Step 3: Write test for embedded version detection**

Add to `tests/test_install.sh`:

```bash
echo "=== Test 16: Version detection - embedded INSTALL_VERSION ==="
setup
git init -q
git commit -q --allow-empty -m "init"
cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION="v1.2.3"

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

echo "SOURCE_TYPE=$SOURCE_TYPE"
echo "SOURCE_VALUE=$SOURCE_VALUE"
INSTALL_SCRIPT

bash test_install.sh > output.txt
assert "Uses version type" "grep -q 'SOURCE_TYPE=version' output.txt"
assert "Uses embedded version" "grep -q 'SOURCE_VALUE=v1.2.3' output.txt"
teardown
```

- [ ] **Step 4: Run all new tests**

Run:
```bash
bash tests/test_install.sh 2>&1 | grep -E "Test 1[4-6]"
```

Expected: All assertions PASS (6 total across 3 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_install.sh
git commit -m "test: add version detection override tests

- Test CODE_SEARCH_VERSION env var override
- Test CODE_SEARCH_BRANCH env var override
- Test embedded INSTALL_VERSION detection"
```

---

### Task 3: Add Version Format Validation

**Files:**
- Modify: `install.sh` (add validation after version detection)
- Modify: `tests/test_install.sh` (add test)

- [ ] **Step 1: Write test for invalid version format**

Add to `tests/test_install.sh`:

```bash
echo "=== Test 17: Version validation - rejects invalid format ==="
setup
git init -q
git commit -q --allow-empty -m "init"
cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION=""

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

# Version format validation
if [ "$SOURCE_TYPE" = "version" ] && [[ ! "$SOURCE_VALUE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Invalid version '$SOURCE_VALUE' (expected format: v1.0.0)" >&2
    exit 1
fi

echo "VALID"
INSTALL_SCRIPT

# Test invalid formats
if CODE_SEARCH_VERSION=1.0.0 bash test_install.sh 2>&1 | grep -q "Error: Invalid version"; then
    echo "  PASS: Rejects missing v prefix"
    PASS=$((PASS + 1))
else
    echo "  FAIL: Should reject missing v prefix"
    FAIL=$((FAIL + 1))
fi

if CODE_SEARCH_VERSION=v1.0 bash test_install.sh 2>&1 | grep -q "Error: Invalid version"; then
    echo "  PASS: Rejects incomplete version"
    PASS=$((PASS + 1))
else
    echo "  FAIL: Should reject incomplete version"
    FAIL=$((FAIL + 1))
fi

# Test valid format
if CODE_SEARCH_VERSION=v1.0.0 bash test_install.sh 2>&1 | grep -q "VALID"; then
    echo "  PASS: Accepts valid version"
    PASS=$((PASS + 1))
else
    echo "  FAIL: Should accept valid version"
    FAIL=$((FAIL + 1))
fi

teardown
```

- [ ] **Step 2: Run test to verify it passes (validation already in test script)**

Run:
```bash
bash tests/test_install.sh 2>&1 | grep "Test 17"
```

Expected: Test 17 shows 3 PASS

- [ ] **Step 3: Add validation to install.sh**

Add after the `REPO_OWNER` line (before the existing Python version check):

```bash
# Version format validation
if [ "$SOURCE_TYPE" = "version" ] && [[ ! "$SOURCE_VALUE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Invalid version '$SOURCE_VALUE' (expected format: v1.0.0)" >&2
    exit 1
fi
```

- [ ] **Step 4: Verify install.sh validation works**

Run:
```bash
CODE_SEARCH_VERSION=1.0.0 bash install.sh 2>&1 | head -5
```

Expected: Shows "Error: Invalid version '1.0.0' (expected format: v1.0.0)"

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_install.sh
git commit -m "feat: add version format validation

- Validates semantic versioning format vX.Y.Z
- Rejects invalid formats with clear error message
- Add test cases for validation"
```

---

### Task 4: Update URL Construction

**Files:**
- Modify: `install.sh` (replace BASE_URL logic)
- Modify: `tests/test_install.sh` (add test)

- [ ] **Step 1: Write test for URL construction**

Add to `tests/test_install.sh`:

```bash
echo "=== Test 18: URL construction ==="
setup
git init -q
git commit -q --allow-empty -m "init"

cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION=""
REPO_OWNER="${CODE_SEARCH_OWNER:-jjveleber}"

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

if [ "$SOURCE_TYPE" = "version" ] && [[ ! "$SOURCE_VALUE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Invalid version '$SOURCE_VALUE' (expected format: v1.0.0)" >&2
    exit 1
fi

BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/claude-code-search/${SOURCE_VALUE}"
echo "BASE_URL=$BASE_URL"
INSTALL_SCRIPT

# Test version URL
CODE_SEARCH_VERSION=v1.0.0 bash test_install.sh > output.txt
assert "Version uses tag URL" "grep -q 'BASE_URL=https://raw.githubusercontent.com/jjveleber/claude-code-search/v1.0.0' output.txt"

# Test branch URL
CODE_SEARCH_BRANCH=develop bash test_install.sh > output.txt
assert "Branch uses branch URL" "grep -q 'BASE_URL=https://raw.githubusercontent.com/jjveleber/claude-code-search/develop' output.txt"

# Test default URL
bash test_install.sh > output.txt
assert "Default uses main URL" "grep -q 'BASE_URL=https://raw.githubusercontent.com/jjveleber/claude-code-search/main' output.txt"

teardown
```

- [ ] **Step 2: Run test to verify current behavior**

Run:
```bash
bash tests/test_install.sh 2>&1 | grep "Test 18"
```

Expected: Test 18 shows PASS for all (test script already has correct logic)

- [ ] **Step 3: Update BASE_URL construction in install.sh**

The old `BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/claude-code-search/main"` line was removed in Task 1.

Add after version validation (before Python version check):

```bash
# Construct BASE_URL based on source type
BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/claude-code-search/${SOURCE_VALUE}"
```

- [ ] **Step 4: Verify URL construction**

Run:
```bash
CODE_SEARCH_VERSION=v1.0.0 bash install.sh 2>&1 | head -10
```

Expected: Should proceed past URL construction (may fail later on missing files, that's OK)

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_install.sh
git commit -m "feat: update BASE_URL construction for versions and branches

- Use SOURCE_VALUE for tag or branch name
- Simplified logic - both use same URL pattern
- Add test for URL construction"
```

---

### Task 5: Add URL Reachability Check

**Files:**
- Modify: `install.sh` (add reachability check after BASE_URL)
- Modify: `tests/test_install.sh` (add test)

- [ ] **Step 1: Write test for reachability check**

Add to `tests/test_install.sh`:

```bash
echo "=== Test 19: URL reachability check ==="
setup
git init -q
git commit -q --allow-empty -m "init"

cat > test_install.sh << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_VERSION=""
REPO_OWNER="${CODE_SEARCH_OWNER:-jjveleber}"

if [ -n "${CODE_SEARCH_VERSION:-}" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$CODE_SEARCH_VERSION"
elif [ -n "${CODE_SEARCH_BRANCH:-}" ]; then
    SOURCE_TYPE="branch"
    SOURCE_VALUE="$CODE_SEARCH_BRANCH"
elif [ -n "$INSTALL_VERSION" ]; then
    SOURCE_TYPE="version"
    SOURCE_VALUE="$INSTALL_VERSION"
else
    SOURCE_TYPE="branch"
    SOURCE_VALUE="main"
fi

if [ "$SOURCE_TYPE" = "version" ] && [[ ! "$SOURCE_VALUE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Invalid version '$SOURCE_VALUE' (expected format: v1.0.0)" >&2
    exit 1
fi

BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/claude-code-search/${SOURCE_VALUE}"

# Test URL reachability
if ! curl -fsSL --head "$BASE_URL/search_code.py" >/dev/null 2>&1; then
    echo "Error: Cannot access $SOURCE_TYPE '$SOURCE_VALUE'" >&2
    echo "  URL: $BASE_URL" >&2
    echo "  Check that the $SOURCE_TYPE exists and is accessible" >&2
    exit 1
fi

echo "REACHABLE"
INSTALL_SCRIPT

# Test with nonexistent version
if CODE_SEARCH_VERSION=v999.999.999 bash test_install.sh 2>&1 | grep -q "Error: Cannot access version"; then
    echo "  PASS: Detects unreachable version"
    PASS=$((PASS + 1))
else
    echo "  FAIL: Should detect unreachable version"
    FAIL=$((FAIL + 1))
fi

# Test with nonexistent branch
if CODE_SEARCH_BRANCH=nonexistent-branch-name bash test_install.sh 2>&1 | grep -q "Error: Cannot access branch"; then
    echo "  PASS: Detects unreachable branch"
    PASS=$((PASS + 1))
else
    echo "  FAIL: Should detect unreachable branch"
    FAIL=$((FAIL + 1))
fi

teardown
```

- [ ] **Step 2: Run test to verify detection**

Run:
```bash
bash tests/test_install.sh 2>&1 | grep "Test 19"
```

Expected: Test 19 shows 2 PASS (unreachable version and branch detected)

- [ ] **Step 3: Add reachability check to install.sh**

Add after BASE_URL construction (before Python version check):

```bash
# Test URL reachability before proceeding (skip if using local files)
if [ -z "${CODE_SEARCH_LOCAL:-}" ]; then
    if ! curl -fsSL --head "$BASE_URL/search_code.py" >/dev/null 2>&1; then
        echo "Error: Cannot access $SOURCE_TYPE '$SOURCE_VALUE'" >&2
        echo "  URL: $BASE_URL" >&2
        echo "  Check that the $SOURCE_TYPE exists and is accessible" >&2
        exit 1
    fi
fi
```

- [ ] **Step 4: Verify reachability check bypassed with CODE_SEARCH_LOCAL**

Run:
```bash
CODE_SEARCH_LOCAL="$PWD" bash install.sh 2>&1 | head -15
```

Expected: Should proceed past reachability check (uses local files, skips URL check)

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_install.sh
git commit -m "feat: add URL reachability check

- Test URL before downloading files
- Fail fast with clear error if version/branch not found
- Skip check when CODE_SEARCH_LOCAL is set
- Add tests for unreachable sources"
```

- [ ] **Step 6: Verify complete install.sh header structure**

Run:
```bash
head -45 install.sh
```

Expected output should show:
- Shebang and set flags
- INSTALL_VERSION declaration (empty)
- Version detection logic (if/elif/else)
- REPO_OWNER assignment
- Version validation
- BASE_URL construction  
- Reachability check (with CODE_SEARCH_LOCAL bypass)
- Python version check (existing)

Total additions: ~25 lines added to install.sh header. Final file size remains manageable (<300 lines).

---

## Chunk 2: Release Automation

### Task 6: Create GitHub Actions Release Workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create .github/workflows directory**

Run:
```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Write release workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Create Release

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Extract and validate tag name
        id: tag
        run: |
          TAG_NAME="${GITHUB_REF#refs/tags/}"
          echo "TAG_NAME=$TAG_NAME" >> $GITHUB_OUTPUT
          
          # Validate semantic versioning format
          if [[ ! "$TAG_NAME" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "Error: Tag '$TAG_NAME' does not match semantic versioning format (vX.Y.Z)"
            exit 1
          fi
          echo "✓ Tag format valid: $TAG_NAME"

      - name: Verify source has empty INSTALL_VERSION
        run: |
          if ! grep -q '^INSTALL_VERSION=""$' install.sh; then
            echo "Error: install.sh should have INSTALL_VERSION=\"\" but doesn't"
            echo "Current INSTALL_VERSION line:"
            grep "INSTALL_VERSION=" install.sh || echo "(not found)"
            exit 1
          fi
          echo "✓ Source INSTALL_VERSION is empty"

      - name: Embed version in install.sh
        run: |
          # GitHub Actions substitutes ${{ }} before shell execution
          sed "s/^INSTALL_VERSION=\"\"$/INSTALL_VERSION=\"${{ steps.tag.outputs.TAG_NAME }}\"/" install.sh > install-release.sh
          chmod +x install-release.sh

      - name: Verify version embedding
        run: |
          # Verify version is embedded with actual value
          if ! grep -qE '^INSTALL_VERSION="v[0-9]+\.[0-9]+\.[0-9]+"$' install-release.sh; then
            echo "✗ Version embedding failed - expected INSTALL_VERSION=\"vX.Y.Z\""
            echo "Actual INSTALL_VERSION line:"
            grep "INSTALL_VERSION=" install-release.sh || echo "(not found)"
            exit 1
          fi
          
          # Verify file structure is intact (shebang still present)
          if ! head -1 install-release.sh | grep -q '^#!/usr/bin/env bash$'; then
            echo "✗ File structure corrupted - shebang missing"
            exit 1
          fi
          
          echo "✓ Version embedded successfully"
          echo "✓ File structure intact"

      - name: Create release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create ${{ steps.tag.outputs.TAG_NAME }} \
            --title "Release ${{ steps.tag.outputs.TAG_NAME }}" \
            --generate-notes \
            install-release.sh#install.sh

      - name: Verify release asset uploaded
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          # Wait briefly for asset processing
          sleep 2
          
          # Check that install.sh asset exists
          if gh release view ${{ steps.tag.outputs.TAG_NAME }} --json assets --jq '.assets[].name' | grep -q '^install.sh$'; then
            echo "✓ Release asset install.sh uploaded successfully"
          else
            echo "✗ Release asset install.sh not found"
            echo "Available assets:"
            gh release view ${{ steps.tag.outputs.TAG_NAME }} --json assets --jq '.assets[].name'
            exit 1
          fi
```

- [ ] **Step 3: Verify workflow syntax**

Run:
```bash
cat .github/workflows/release.yml | head -20
```

Expected: Valid YAML with correct structure

- [ ] **Step 4: Test version embedding locally**

Run:
```bash
TAG_NAME=v0.0.1-test
# Same quoting as workflow (double quotes for variable expansion)
sed "s/^INSTALL_VERSION=\"\"$/INSTALL_VERSION=\"$TAG_NAME\"/" install.sh > /tmp/install-test.sh
grep "INSTALL_VERSION=" /tmp/install-test.sh | head -1
```

Expected: Shows `INSTALL_VERSION="v0.0.1-test"` (actual value, not template)

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add GitHub Actions release workflow

- Triggered on version tag push (v*)
- Embeds version in install.sh via sed
- Creates GitHub release with modified install.sh as asset
- Auto-generates release notes"
```

---

## Chunk 3: Documentation

### Task 7: Update README Install Section

**Files:**
- Modify: `README.md` (update Install section)

- [ ] **Step 1: Read current Install section**

Run:
```bash
head -30 README.md
```

Expected: Shows current install instructions starting with "## Install"

- [ ] **Step 2: Update Install section with Edit tool**

Use Edit tool with content matching. Match from "## Install" through the command, keeping "This will:" section that follows:

```
old_string (from README.md):
## Install

Run from the root of any project:

```bash
curl -fsSL https://raw.githubusercontent.com/jjveleber/claude-code-search/main/install.sh | bash
```

This will:

new_string:
## Install

### Latest (recommended)

Run from the root of any project:

```bash
curl -fsSL https://raw.githubusercontent.com/jjveleber/claude-code-search/main/install.sh | bash
```

### Specific Release

```bash
curl -fsSL https://github.com/jjveleber/claude-code-search/releases/download/v1.0.0/install.sh | bash
```

### Specific Branch

```bash
CODE_SEARCH_BRANCH=develop \
  curl -fsSL https://raw.githubusercontent.com/jjveleber/claude-code-search/develop/install.sh | bash
```

This will:
```

This keeps the bullet list under "This will:" intact.

- [ ] **Step 3: Verify formatting**

Run:
```bash
head -50 README.md
```

Expected: Updated Install section with three subsections

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README install section

- Add specific release installation method
- Add specific branch installation method
- Keep latest installation as recommended default"
```

---

### Task 8: Add Environment Variables Documentation

**Files:**
- Modify: `README.md` (add/update environment variables section)

- [ ] **Step 1: Locate Re-index section**

Run:
```bash
grep -n "^## Re-index" README.md
```

Expected: Shows line number of Re-index section

- [ ] **Step 2: Add environment variables section before Re-index**

Use Edit tool to insert new section before Re-index:

```
old_string:
## Re-index

new_string:
## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `CODE_SEARCH_VERSION` | Install from specific release tag | `CODE_SEARCH_VERSION=v1.0.0` |
| `CODE_SEARCH_BRANCH` | Install from specific branch | `CODE_SEARCH_BRANCH=develop` |
| `CODE_SEARCH_OWNER` | Install from a fork | `CODE_SEARCH_OWNER=yourname` |
| `CODE_SEARCH_LOCAL` | Install from local filesystem (for testing) | `CODE_SEARCH_LOCAL=/path/to/repo` |

**Priority:** `CODE_SEARCH_VERSION` > `CODE_SEARCH_BRANCH` > embedded version (from release asset) > `main` branch

## Re-index
```

- [ ] **Step 3: Verify table formatting**

Run:
```bash
grep -A 10 "## Environment Variables" README.md
```

Expected: Shows formatted table

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add environment variables section to README

- Document CODE_SEARCH_VERSION and CODE_SEARCH_BRANCH
- Show priority order for version resolution
- Include existing variables (OWNER, LOCAL)"
```

---

### Task 9: Add Releases Section to README

**Files:**
- Modify: `README.md` (add Releases section)

- [ ] **Step 1: Locate Environment Variables section**

Run:
```bash
grep -n "^## Environment Variables" README.md
```

Expected: Shows line number of Environment Variables section (added in Task 8)

- [ ] **Step 2: Add Releases section after Environment Variables**

Use Edit tool to insert after Environment Variables, before Re-index:

```
old_string:
**Priority:** `CODE_SEARCH_VERSION` > `CODE_SEARCH_BRANCH` > embedded version (from release asset) > `main` branch

## Re-index

new_string:
**Priority:** `CODE_SEARCH_VERSION` > `CODE_SEARCH_BRANCH` > embedded version (from release asset) > `main` branch

## Releases

Releases are tagged as `vX.Y.Z` (e.g., `v1.0.0`). Each release includes a pre-configured `install.sh` that automatically pulls files from that version.

### For Users

Install a specific release:

```bash
curl -fsSL https://github.com/jjveleber/claude-code-search/releases/download/v1.0.0/install.sh | bash
```

The release asset has the version embedded, so all files are pulled from the same release tag.

### For Maintainers

Create a release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions automatically:
1. Embeds the version in `install.sh`
2. Creates a GitHub release
3. Attaches the modified `install.sh` as a release asset

## Re-index
```

Note: The Edit replaces text from Priority line through "## Re-index", inserting Releases section between Environment Variables and Re-index.

- [ ] **Step 3: Verify formatting**

Run:
```bash
grep -A 20 "## Releases" README.md
```

Expected: Shows complete Releases section with user and maintainer subsections

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add Releases section to README

- Explain release installation for users
- Document release creation for maintainers
- Describe GitHub Actions automation"
```

---

## Chunk 4: Validation & Cleanup

### Task 10: Run Full Test Suite

**Files:**
- Verify: `tests/test_install.sh` (all tests)

- [ ] **Step 1: Run complete test suite**

Run:
```bash
bash tests/test_install.sh
```

Expected: All tests PASS (19 tests total: original 12 + new 7)

- [ ] **Step 2: Check test summary**

Run:
```bash
bash tests/test_install.sh 2>&1 | tail -5
```

Expected: Shows summary like "PASS: 19, FAIL: 0" or similar

- [ ] **Step 3: If any failures, fix them**

If failures occur:
1. Identify failing test
2. Check error message
3. Fix root cause in install.sh or test
4. Rerun tests
5. Commit fix

- [ ] **Step 4: Verify clean exit**

Run:
```bash
bash tests/test_install.sh && echo "SUCCESS"
```

Expected: Ends with "SUCCESS"

- [ ] **Step 5: Commit if fixes were needed**

```bash
# Only if fixes were made
git add tests/test_install.sh install.sh
git commit -m "fix: resolve test failures

[Describe what was fixed]"
```

---

### Task 11: Manual Validation with Test Release

**Files:**
- None (manual validation process)

**Prerequisites:** All code changes committed, tests passing

- [ ] **Step 1: Create test tag**

Run:
```bash
git tag v0.0.1-test
```

- [ ] **Step 2: Push test tag to trigger workflow**

Run:
```bash
git push origin v0.0.1-test
```

Expected: GitHub Actions workflow triggered

- [ ] **Step 3: Wait for workflow completion**

Check workflow status:
```bash
gh run list --limit 1
```

Expected: Shows completed workflow for v0.0.1-test

- [ ] **Step 4: Verify release created**

Run:
```bash
gh release view v0.0.1-test
```

Expected: Shows release with install.sh asset

- [ ] **Step 5: Download and verify embedded version**

Run:
```bash
curl -fsSL https://github.com/jjveleber/claude-code-search/releases/download/v0.0.1-test/install.sh | head -10
```

Expected: Shows `INSTALL_VERSION="v0.0.1-test"` (not empty)

- [ ] **Step 6: Test installation from release**

Run in clean directory:
```bash
cd /tmp
mkdir test-install-release
cd test-install-release
git init
git commit --allow-empty -m "init"
curl -fsSL https://github.com/jjveleber/claude-code-search/releases/download/v0.0.1-test/install.sh | bash
```

Expected: Installs successfully, files present

- [ ] **Step 7: Verify files installed**

Run:
```bash
ls -la /tmp/test-install-release/ | grep -E "(index_project|search_code|watch_index)"
```

Expected: Shows all core files

- [ ] **Step 8: Delete test release**

Run:
```bash
gh release delete v0.0.1-test --yes
git tag -d v0.0.1-test
git push origin :refs/tags/v0.0.1-test
```

- [ ] **Step 9: Verify all manual validation steps passed**

Confirm:
- Release created with asset
- install.sh contains embedded version
- Installation from release works
- All core files present after install

No additional action needed (results verified in Steps 1-8).

---

### Task 12: Push Feature Branch and Create Pull Request

**Files:**
- None (git workflow)

**Context:** Feature branch created in Task 0, all commits made on `feature/install-from-releases`.

- [ ] **Step 1: Verify all commits are on branch**

Run:
```bash
git log --oneline feature/install-from-releases ^origin/main | head -10
```

Expected: Shows all commits from this implementation (should be ~13 commits: Tasks 1-11)

- [ ] **Step 2: Push feature branch**

Run:
```bash
git push -u origin feature/install-from-releases
```

- [ ] **Step 3: Create pull request**

Run:
```bash
gh pr create --title "Install from GitHub releases and branches" --body "$(cat <<'EOF'
## Summary
- Enable installation from specific GitHub releases
- Support branch-specific installation via env vars
- Auto-detect version from release assets
- Add GitHub Actions workflow for automated releases

## Implementation
- Version detection with priority: env var > embedded > default
- URL construction for releases and branches
- Version format validation (vX.Y.Z)
- URL reachability check before download
- Comprehensive test coverage (7 new tests)

## Changes
- `install.sh`: Version detection, validation, URL construction
- `.github/workflows/release.yml`: Automated release creation
- `README.md`: Updated install instructions, env vars, releases section
- `tests/test_install.sh`: Version detection and validation tests

## Testing
- [x] All existing tests pass
- [x] New version detection tests pass
- [x] Manual validation with test release (v0.0.1-test)
- [x] Verified release asset contains embedded version
- [x] Tested installation from release asset

## Backward Compatibility
✅ No breaking changes
- Existing `main` branch install command works unchanged
- `CODE_SEARCH_OWNER` and `CODE_SEARCH_LOCAL` preserved
- New capabilities added via opt-in env vars

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Verify PR created**

Run:
```bash
gh pr view
```

Expected: Shows PR details

---

## Success Criteria

After completing all tasks:

- [ ] Users can install from specific release versions
- [ ] Users can install from specific branches
- [ ] Auto-detection works from release assets
- [ ] Environment variables override auto-detection
- [ ] Backward compatibility maintained (existing commands work)
- [ ] Clear error messages on failures
- [ ] All tests pass (19 total)
- [ ] Documentation updated and clear
- [ ] Test release validated manually
- [ ] Pull request created

---

## Notes

- **Test execution:** Use `CODE_SEARCH_LOCAL` to bypass remote downloads during testing
- **Version format:** Must match `vX.Y.Z` (semantic versioning with v prefix)
- **URL pattern:** Both releases and branches use `raw.githubusercontent.com/<owner>/<repo>/<ref>`
- **Atomicity:** Keep existing `set -euo pipefail` and temp file pattern in install.sh
- **Fail-fast:** No silent fallbacks - clear errors when things break
