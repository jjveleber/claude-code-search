"""Old per-repo install cleanup. Stdlib only. Venvs are deleted
(reproducible); every other removal is a move to trash."""
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

from engine import paths, repoident

OLD_FILES = [
    "index_project.py", "search_code.py", "watch_index.py", "chunker.py",
    "search_server.py", "migrate_add_file_type.py",
    "hooks/post_search_code.sh", "hooks/pre_read_grep_glob.sh",
    ".venv-code-search", "chroma_db", ".watch_index.log",
    ".watch_index.pid", ".search_server.pid", ".code-search-version",
]
GITIGNORE_TOOL_LINES = {
    "chroma_db/", ".venv-code-search/", ".watch_index.log",
    ".watch_index.pid", ".search_server.pid", ".code-search-version",
}
HOOK_MARKERS = ("search_code.py", "watch_index.py",
                "pre_read_grep_glob", "post_search_code")
PID_FILES = {".watch_index.pid": "watch_index.py",
             ".search_server.pid": "search_server.py"}


def detect_old_install(repo: Path) -> bool:
    return (repo / ".code-search-version").exists() or \
           (repo / "chroma_db" / "model.txt").exists()


def _is_tracked(repo: Path, rel: str) -> bool:
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "--", rel],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # Can't determine tracked status: fail closed, treat as tracked
        # so the caller skips it rather than trashing it.
        return True
    return bool(r.stdout.strip())


def _kill_old_processes(repo: Path, dry_run: bool) -> list[int]:
    killed = []
    for pidfile, script in PID_FILES.items():
        p = repo / pidfile
        if not p.exists():
            continue
        try:
            pid = int(p.read_text().strip())
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(
                errors="replace")
        except (ValueError, OSError):
            continue
        if script in cmdline:
            if not dry_run:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    continue
                # Wait (bounded) for it to actually exit before the caller
                # trashes its pid/log/chroma_db — a still-dying process can
                # recreate those files or write mid-move, leaving fresh litter
                # after "cleanup".
                for _ in range(30):
                    try:
                        os.kill(pid, 0)
                    except OSError:
                        break
                    time.sleep(0.1)
            killed.append(pid)
    return killed


def _clean_claude_md(repo: Path, dry_run: bool) -> bool:
    p = repo / ".claude" / "CLAUDE.md"
    if not p.exists():
        return False
    text = p.read_text()
    if "**Rule:** Before using" not in text:
        return False
    if _is_tracked(repo, ".claude/CLAUDE.md"):
        return False   # never modify/delete a tracked file (see OLD_FILES loop)
    # drop from '## Precision Protocol' up to the next '## ' or EOF
    new = re.sub(r"## Precision Protocol.*?(?=\n## |\Z)", "", text,
                 flags=re.DOTALL)
    if dry_run:
        return True
    if new.strip():
        p.write_text(new)
    else:
        p.unlink()
    return True


def _clean_settings(repo: Path, dry_run: bool) -> bool:
    p = repo / ".claude" / "settings.local.json"
    if not p.exists():
        return False
    if _is_tracked(repo, ".claude/settings.local.json"):
        return False   # never modify/delete a tracked file (see OLD_FILES loop)
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return False

    def is_ours(entry) -> bool:
        return any(m in json.dumps(entry) for m in HOOK_MARKERS)

    changed = data.pop("searchUsageTracking", None) is not None
    for container in (data, data.get("hooks", {})):
        for event in list(container):
            if event in ("UserPromptSubmit", "PreToolUse", "PostToolUse"):
                kept = []
                for e in container[event]:
                    # If entry has "hooks" key, filter at individual hook level
                    if "hooks" in e:
                        original_hooks = e.get("hooks", [])
                        filtered_hooks = [
                            hook for hook in original_hooks
                            if not any(m in json.dumps(hook) for m in HOOK_MARKERS)
                        ]
                        if filtered_hooks:
                            # Some hooks remain
                            if len(filtered_hooks) != len(original_hooks):
                                changed = True
                            e["hooks"] = filtered_hooks
                            kept.append(e)
                        else:
                            # All hooks removed; drop entry
                            changed = True
                    else:
                        # No "hooks" key; use old check
                        if not is_ours(e):
                            kept.append(e)
                        else:
                            changed = True

                if len(kept) != len(container[event]):
                    changed = True
                if kept:
                    container[event] = kept
                else:
                    del container[event]
    if data.get("hooks") == {}:
        del data["hooks"]
    if not changed:
        return False
    if not dry_run:
        if data:
            p.write_text(json.dumps(data, indent=2))
        else:
            p.unlink()
    return True


def _clean_gitignore(repo: Path, dry_run: bool) -> list[str]:
    p = repo / ".gitignore"
    if not p.exists():
        return []
    lines = p.read_text().splitlines()
    kept = [l for l in lines if l.strip() not in GITIGNORE_TOOL_LINES]
    removed = [l.strip() for l in lines if l.strip() in GITIGNORE_TOOL_LINES]
    if removed and not dry_run:
        p.write_text("\n".join(kept) + ("\n" if kept else ""))
    return removed


def migrate(repo: Path, dry_run: bool = False) -> dict:
    repo = Path(repo).resolve()
    report = {"evidence": False, "trashed": [], "skipped_tracked": [],
              "settings_cleaned": False, "claude_md_cleaned": False,
              "gitignore_cleaned": [], "deleted": [], "killed": []}
    if not detect_old_install(repo):
        return report
    report["evidence"] = True
    report["killed"] = _kill_old_processes(repo, dry_run)

    trash = paths.trash_dir() / repoident.repo_id(repo)
    for rel in OLD_FILES:
        target = repo / rel
        if not target.exists():
            continue
        if _is_tracked(repo, rel):
            report["skipped_tracked"].append(rel)
            continue
        if rel == ".venv-code-search":
            # No ignore_errors: a delete that fails must surface, like the
            # trash-move branch below — never report "deleted" for a venv
            # still on disk. A cross-device move can leave .venv-code-search
            # as a symlink, on which rmtree raises — unlink those instead.
            if not dry_run:
                if target.is_symlink():
                    target.unlink()
                else:
                    shutil.rmtree(target)
            report["deleted"].append(rel)
        else:
            report["trashed"].append(rel)
            if not dry_run:
                dest = trash / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    n = 1
                    while (candidate := dest.with_name(f"{dest.name}.{n}")).exists():
                        n += 1
                    dest = candidate
                shutil.move(str(target), str(dest))
    hooks_dir = repo / "hooks"
    if not dry_run and hooks_dir.is_dir() and not any(hooks_dir.iterdir()):
        hooks_dir.rmdir()

    report["claude_md_cleaned"] = _clean_claude_md(repo, dry_run)
    report["settings_cleaned"] = _clean_settings(repo, dry_run)
    report["gitignore_cleaned"] = _clean_gitignore(repo, dry_run)
    return report
