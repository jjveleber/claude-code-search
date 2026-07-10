import json
import shutil
import subprocess
from pathlib import Path
import pytest
from engine import migrate, paths
from tests.engine.test_repoident import make_repo, _git


@pytest.fixture(autouse=True)
def csh(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_SEARCH_HOME", str(tmp_path / "csh"))
    paths.ensure_home()


def old_install(repo: Path):
    """Simulate an old per-repo install (all artifacts untracked)."""
    for f in ["index_project.py", "search_code.py", "watch_index.py",
              "chunker.py", "search_server.py"]:
        (repo / f).write_text("# installed copy\n")
    (repo / "hooks").mkdir(exist_ok=True)
    (repo / "hooks" / "post_search_code.sh").write_text("#!/bin/bash\n")
    (repo / "hooks" / "pre_read_grep_glob.sh").write_text("#!/bin/bash\n")
    (repo / "chroma_db").mkdir()
    (repo / "chroma_db" / "model.txt").write_text("nomic-ai/CodeRankEmbed")
    (repo / ".code-search-version").write_text("v1.2.0")
    (repo / ".gitignore").write_text(
        "chroma_db/\n.venv-code-search/\n.venv/\n__pycache__/\n"
        ".watch_index.log\n.claude/settings.local.json\n.claude/CLAUDE.md\n")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "CLAUDE.md").write_text(
        "## Precision Protocol\n\n**Rule:** Before using `Read`...\n\nstuff\n")
    (repo / ".claude" / "settings.local.json").write_text(json.dumps({
        "hooks": {"UserPromptSubmit": [{"hooks": [
            {"type": "command",
             "command": "/abs/path/.venv-code-search/bin/python3 watch_index.py"}]}]},
        "searchUsageTracking": {"warningsVisible": False},
        "permissions": {"allow": ["Bash(ls:*)"]},
    }))


def test_no_evidence_touches_nothing(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "chroma_db").mkdir()          # user's own chroma app, no model.txt
    (repo / "chroma_db" / "data.bin").write_text("theirs")
    report = migrate.migrate(repo)
    assert not report["evidence"]
    assert (repo / "chroma_db" / "data.bin").exists()


def test_full_migration(tmp_path):
    repo = make_repo(tmp_path)
    old_install(repo)
    report = migrate.migrate(repo)
    assert report["evidence"]
    assert not (repo / "search_code.py").exists()
    assert not (repo / "chroma_db").exists()
    assert not (repo / "hooks").exists()          # emptied then removed
    # trashed, not destroyed
    trash = paths.trash_dir()
    assert any(trash.rglob("search_code.py"))
    # gitignore: tool lines gone, generic lines kept
    gi = (repo / ".gitignore").read_text()
    assert "chroma_db/" not in gi and ".venv-code-search/" not in gi
    assert ".venv/" in gi and "__pycache__/" in gi
    assert ".claude/settings.local.json" in gi
    # settings: our hooks gone, user's permissions kept
    settings = json.loads((repo / ".claude" / "settings.local.json").read_text())
    assert "searchUsageTracking" not in settings
    assert settings["permissions"]["allow"] == ["Bash(ls:*)"]
    assert not settings.get("hooks", {}).get("UserPromptSubmit")
    # CLAUDE.md protocol block gone (file deleted since nothing else in it)
    assert not (repo / ".claude" / "CLAUDE.md").exists()


def test_tracked_files_skipped(tmp_path):
    repo = make_repo(tmp_path)
    old_install(repo)
    _git("add", "search_code.py", cwd=repo)
    _git("-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-m", "committed the script", cwd=repo)
    report = migrate.migrate(repo)
    assert "search_code.py" in report["skipped_tracked"]
    assert (repo / "search_code.py").exists()
    assert not (repo / "watch_index.py").exists()  # untracked ones still go


def test_dry_run_changes_nothing(tmp_path):
    repo = make_repo(tmp_path)
    old_install(repo)
    report = migrate.migrate(repo, dry_run=True)
    assert report["evidence"] and report["trashed"]
    assert (repo / "search_code.py").exists()
    assert (repo / "chroma_db").exists()


def test_git_error_fails_closed(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    old_install(repo)

    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "-C"] and "ls-files" in cmd:
            return subprocess.CompletedProcess(cmd, returncode=128,
                                                stdout="", stderr="fatal: error")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(migrate.subprocess, "run", fake_run)
    migrate.migrate(repo)
    # git status couldn't be determined -> treated as tracked -> never trashed
    assert (repo / "search_code.py").exists()


def test_trash_collision_preserves_prior_trash(tmp_path):
    repo = make_repo(tmp_path)
    old_install(repo)
    migrate.migrate(repo)
    trash = paths.trash_dir()
    first = list(trash.rglob("search_code.py"))
    assert len(first) == 1

    shutil.rmtree(repo / ".claude", ignore_errors=True)
    old_install(repo)
    migrate.migrate(repo)
    second = list(trash.rglob("search_code.py*"))
    # original trashed copy still present, plus a new non-colliding copy
    assert first[0].exists()
    assert len(second) == 2


def test_dead_pid_does_not_crash_migrate(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    old_install(repo)
    pid = 424242
    (repo / ".watch_index.pid").write_text(str(pid))

    # simulate a cmdline read that succeeds (process existed at read time)
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"python3 watch_index.py")

    def fake_kill(p, sig):
        # simulate the process having exited between the cmdline read and kill
        raise ProcessLookupError()

    monkeypatch.setattr(migrate.os, "kill", fake_kill)

    report = migrate.migrate(repo)  # must not raise
    assert report["evidence"]
    assert pid not in report["killed"]


def test_venv_deleted_not_trashed(tmp_path):
    """Issue #39: .venv-code-search should be deleted, not moved to trash."""
    repo = make_repo(tmp_path)
    old_install(repo)
    # Create a .venv-code-search directory (untracked)
    venv_path = repo / ".venv-code-search"
    venv_path.mkdir()
    (venv_path / "pyvenv.cfg").write_text("home = /usr/bin\n")

    report = migrate.migrate(repo)

    # Venv should be deleted, not trashed
    assert ".venv-code-search" in report["deleted"]
    assert ".venv-code-search" not in report["trashed"]
    assert not venv_path.exists()

    # Verify it's not in the trash directory either
    trash = paths.trash_dir()
    assert not any(trash.rglob(".venv-code-search"))


def test_mixed_hooks_in_matcher_block(tmp_path):
    """Issue #34: filter individual hooks, not whole matcher-block."""
    repo = make_repo(tmp_path)
    old_install(repo)

    # Override settings.local.json with a block containing both our hook and user's hook
    (repo / ".claude" / "settings.local.json").write_text(json.dumps({
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": {"type": "tools", "tools": ["Bash"]},
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/usr/local/bin/watch_index.py pre-tool"
                        },
                        {
                            "type": "command",
                            "command": "/my/own/hook.sh"
                        }
                    ]
                }
            ]
        }
    }))

    report = migrate.migrate(repo)

    # Settings should be cleaned
    assert report["settings_cleaned"]

    # Read the cleaned settings
    settings = json.loads((repo / ".claude" / "settings.local.json").read_text())

    # The block should still exist because user's hook remains
    assert "PreToolUse" in settings["hooks"]

    # The block should have only the user's hook
    block = settings["hooks"]["PreToolUse"][0]
    assert len(block["hooks"]) == 1
    assert block["hooks"][0]["command"] == "/my/own/hook.sh"
