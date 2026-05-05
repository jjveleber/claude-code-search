# Install from GitHub Releases and Branches

**Date:** 2026-05-03  
**Status:** Approved  
**Author:** Human + Claude

## Problem

Current installation only supports downloading from the `main` branch. Users cannot:
- Install a specific stable release version
- Install from a development branch
- Pin their installation to a known-good version

## Solution

Enable context-aware installation that automatically detects its source (release vs branch) while allowing explicit overrides via environment variables.

## Architecture Overview

### Resolution Hierarchy

The install system determines its source using this priority order (highest to lowest):

1. **Environment variable override:** `CODE_SEARCH_VERSION` or `CODE_SEARCH_BRANCH`
2. **Embedded version:** `INSTALL_VERSION` variable in install.sh (set during release)
3. **Default fallback:** `main` branch

### File Sourcing by Mode

| Mode | install.sh source | Supporting files source |
|------|------------------|------------------------|
| Release | GitHub release asset | Git tag via raw.githubusercontent.com |
| Branch | raw.githubusercontent.com | Same branch via raw.githubusercontent.com |
| Local dev | Local filesystem | Local filesystem (existing `CODE_SEARCH_LOCAL`) |

**Key insight:** Only install.sh needs to be a release asset (with embedded version). Other files are accessed via immutable git tags, keeping releases lightweight and avoiding duplication.

## Version Detection Logic

### In install.sh

Add version detection at the top of the script:

```bash
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
```

### URL Construction

Replace the current `BASE_URL` logic (line 5) with:

```bash
REPO_OWNER="${CODE_SEARCH_OWNER:-jjveleber}"

if [ "$SOURCE_TYPE" = "version" ]; then
    # Release: use raw.githubusercontent.com with tag
    BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/claude-code-search/${SOURCE_VALUE}"
else
    # Branch: existing pattern
    BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/claude-code-search/${SOURCE_VALUE}"
fi
```

**Note:** Both use the same URL pattern (raw.githubusercontent.com) since git tags are accessible this way. The distinction between version and branch is semantic.

## GitHub Actions Workflow

### Workflow File

**Location:** `.github/workflows/release.yml`

**Trigger:** Push of version tags matching `v*` pattern

**Steps:**
1. Checkout code at the tag
2. Substitute `INSTALL_VERSION=""` with `INSTALL_VERSION="$TAG_NAME"` in install.sh
3. Create GitHub release
4. Upload modified install.sh as release asset

**Implementation details:**
- Tag name extracted from `GITHUB_REF` (e.g., `refs/tags/v1.0.0` → `v1.0.0`)
- Substitution uses `sed` (portable, no Python needed)
- Release created via `gh release create`
- Original install.sh in git remains unchanged (`INSTALL_VERSION=""`)

### Release Process for Maintainers

```bash
git tag v1.0.0
git push origin v1.0.0
# GitHub Actions automatically creates the release
```

**Result:**
- Release appears at `https://github.com/USER/repo/releases/tag/v1.0.0`
- Asset: `install.sh` (with embedded version `v1.0.0`)
- Users download via: `curl https://github.com/USER/repo/releases/download/v1.0.0/install.sh | bash`

## Backward Compatibility

### Existing Commands Continue Working

```bash
# Current command (still works, uses main)
curl -fsSL https://raw.githubusercontent.com/jjveleber/claude-code-search/main/install.sh | bash
```

### Existing Environment Variables Preserved

- `CODE_SEARCH_OWNER` - Fork support (unchanged)
- `CODE_SEARCH_LOCAL` - Local dev/testing (unchanged)

### New Capabilities Added

```bash
# Install specific release (auto-detects version from asset)
curl -fsSL https://github.com/jjveleber/claude-code-search/releases/download/v1.0.0/install.sh | bash

# Install from branch (explicit)
CODE_SEARCH_BRANCH=feature/test \
  curl -fsSL https://raw.githubusercontent.com/jjveleber/claude-code-search/feature/test/install.sh | bash

# Override detected version
CODE_SEARCH_VERSION=v0.9.0 \
  curl -fsSL https://github.com/jjveleber/claude-code-search/releases/download/v1.0.0/install.sh | bash
```

**No breaking changes** - only additions.

## Error Handling

### Fail Fast, No Silent Fallbacks

Install failures should be immediate and clear. No graceful degradation.

### Invalid Version Format

```bash
if [ "$SOURCE_TYPE" = "version" ] && [[ ! "$SOURCE_VALUE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Invalid version '$SOURCE_VALUE' (expected format: v1.0.0)"
    exit 1
fi
```

**Validation:** Semantic versioning format `vX.Y.Z` where X, Y, Z are one or more digits (no upper limit).

### Release/Branch Not Found

```bash
# Test URL before bulk download
if ! curl -fsSL --head "$BASE_URL/search_code.py" >/dev/null 2>&1; then
    echo "Error: Cannot access $SOURCE_TYPE '$SOURCE_VALUE'"
    echo "  URL: $BASE_URL"
    echo "  Check that the $SOURCE_TYPE exists and is accessible"
    exit 1
fi
```

### Download Failures

- Keep existing `set -euo pipefail` (fails on any error)
- Keep atomic temp file pattern (all-or-nothing, lines 158-187)
- Add clear error context when curl fails

**Philosophy:** If it breaks, stop immediately and tell the user exactly what's broken.

## Testing Strategy

### Extend Existing Test Suite

**Current:** `tests/test_install.sh` (uses `CODE_SEARCH_LOCAL`)

**Add:** Test version detection logic and URL construction

### New Test Cases

```bash
# Test 1: Default to main
unset CODE_SEARCH_VERSION CODE_SEARCH_BRANCH
# Run install logic, verify BASE_URL points to main

# Test 2: Version override
CODE_SEARCH_VERSION=v1.0.0
# Verify BASE_URL points to v1.0.0 tag

# Test 3: Branch override
CODE_SEARCH_BRANCH=develop
# Verify BASE_URL points to develop branch

# Test 4: Embedded version detection
# Mock install.sh with INSTALL_VERSION="v1.0.0"
# Verify it's detected correctly

# Test 5: Invalid version format
CODE_SEARCH_VERSION=1.0.0  # Missing 'v'
# Verify exits with error
```

### Manual Validation Before First Release

1. Create test tag `v0.0.1-test`
2. Push tag, trigger workflow
3. Verify release created with asset
4. Test install from release asset
5. Verify all files downloaded correctly
6. Delete test release

## Documentation Updates

### README.md Changes

#### Install Section (Update)

```markdown
## Install

### Latest (recommended)
\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/jjveleber/claude-code-search/main/install.sh | bash
\`\`\`

### Specific Release
\`\`\`bash
curl -fsSL https://github.com/jjveleber/claude-code-search/releases/download/v1.0.0/install.sh | bash
\`\`\`

### Specific Branch
\`\`\`bash
CODE_SEARCH_BRANCH=develop \
  curl -fsSL https://raw.githubusercontent.com/jjveleber/claude-code-search/develop/install.sh | bash
\`\`\`
```

#### Environment Variables Section (Update)

Add entries for new variables:
- `CODE_SEARCH_VERSION` - Install from specific release (e.g., `v1.0.0`)
- `CODE_SEARCH_BRANCH` - Install from specific branch (overrides default)

Keep existing:
- `CODE_SEARCH_OWNER` - Fork support
- `CODE_SEARCH_LOCAL` - Local dev

#### New Releases Section (Add)

```markdown
## Releases

Releases are tagged as `vX.Y.Z` (e.g., `v1.0.0`). Each release includes a pre-configured install.sh that automatically pulls files from that version.

To create a release (maintainers):
\`\`\`bash
git tag v1.0.0
git push origin v1.0.0
# GitHub Actions creates the release automatically
\`\`\`
```

## Implementation Checklist

- [ ] Update install.sh with version detection logic
- [ ] Add URL construction based on SOURCE_TYPE
- [ ] Add version format validation
- [ ] Add URL reachability check
- [ ] Create `.github/workflows/release.yml`
- [ ] Extend `tests/test_install.sh` with new test cases
- [ ] Update README.md install section
- [ ] Update README.md environment variables section
- [ ] Add README.md releases section
- [ ] Manual validation with test release
- [ ] Create first official release

## Files Changed

| File | Type | Description |
|------|------|-------------|
| `install.sh` | Modified | Add version detection and URL construction |
| `.github/workflows/release.yml` | New | Automated release creation workflow |
| `README.md` | Modified | Update install instructions and add releases section |
| `tests/test_install.sh` | Modified | Add version detection test cases |

## User Experience

### Install from Release (Auto-detected)

```bash
curl -fsSL https://github.com/jjveleber/claude-code-search/releases/download/v1.0.0/install.sh | bash
```

**What happens:**
1. User downloads install.sh from release asset
2. Script detects `INSTALL_VERSION="v1.0.0"` (embedded during release)
3. Downloads supporting files from tag `v1.0.0` via raw.githubusercontent.com
4. Installs complete version `v1.0.0` snapshot

### Install from Main (Default)

```bash
curl -fsSL https://raw.githubusercontent.com/jjveleber/claude-code-search/main/install.sh | bash
```

**What happens:**
1. User downloads install.sh from main branch
2. Script sees `INSTALL_VERSION=""` (empty)
3. Defaults to `main` branch
4. Downloads supporting files from main
5. Installs latest development version

### Override Detected Version

```bash
CODE_SEARCH_VERSION=v0.9.0 \
  curl -fsSL https://github.com/jjveleber/claude-code-search/releases/download/v1.0.0/install.sh | bash
```

**What happens:**
1. User downloads install.sh from v1.0.0 release
2. Script detects `INSTALL_VERSION="v1.0.0"` (embedded)
3. Env var `CODE_SEARCH_VERSION=v0.9.0` **overrides** detected version
4. Downloads supporting files from tag `v0.9.0`
5. Installs version `v0.9.0` (not v1.0.0)

## Branching Strategy for Implementation

**Current state:**
- On branch: `feature/search-usage-tracking`
- Work to preserve: Search usage tracking implementation

**Implementation workflow:**

1. **Create PR for current feature:**
   - `feature/search-usage-tracking` → `main`
   - Preserves search tracking work
   - Keeps it out of the way during release work

2. **Start release installation work:**
   - Base: `main` branch (not current feature branch)
   - New branch: `feature/install-from-releases`
   - Implement: Version detection + GitHub Actions workflow

3. **After release work merged to main:**
   - Merge `main` → `feature/search-usage-tracking`
   - Brings release functionality into the tracking feature
   - Allows tracking feature to benefit from release system

**Key point:** Release work happens independently on `main`, then gets merged into the feature branch later.

## Success Criteria

- [ ] Users can install from specific release versions
- [ ] Users can install from specific branches
- [ ] Auto-detection works from release assets
- [ ] Environment variables override auto-detection
- [ ] Backward compatibility maintained (existing commands work)
- [ ] Clear error messages on failures
- [ ] All tests pass
- [ ] Documentation updated and clear
- [ ] First release created and validated
