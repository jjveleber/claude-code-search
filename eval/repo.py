import json
import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(ROOT_DIR, ".claude", "settings.local.json")
INDEX_SCRIPT = os.path.join(ROOT_DIR, "index_project.py")
CAPTURE_HOOK = os.path.join(ROOT_DIR, "eval", "hooks", "capture_session.py")
PRODUCTION_WATCHER = os.path.join(ROOT_DIR, "watch_index.py")
PYTHON = os.path.join(ROOT_DIR, ".venv", "bin", "python3")


def is_dirty():
    """Return True if the repo has uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=ROOT_DIR
    )
    return bool(result.stdout.strip())


def reset_repo():
    """Restore tracked files and remove untracked files (excluding eval/)."""
    subprocess.run(["git", "checkout", "."], cwd=ROOT_DIR, check=True)
    subprocess.run(
        ["git", "clean", "-fd", "--exclude=eval/"],
        cwd=ROOT_DIR, check=True
    )


def run_reindex():
    """Run incremental re-index."""
    print("Re-indexing...")
    subprocess.run([PYTHON, INDEX_SCRIPT], cwd=ROOT_DIR, check=True)
    print("Re-index complete.")


def _load_settings():
    if not os.path.exists(SETTINGS_PATH):
        return {}
    with open(SETTINGS_PATH) as f:
        return json.load(f)


def _save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def configure_hooks(mode):
    """
    mode='baseline': disable search hook, enable capture hook only
    mode='run': enable search hook + capture hook
    mode='restore': restore original production hooks, remove capture hook
    """
    settings = _load_settings()
    hooks = settings.setdefault("hooks", {})

    # Base UserPromptSubmit hook: starts watcher + indexer (production)
    production_prompt_cmd = (
        f"{PYTHON} {INDEX_SCRIPT} & {PYTHON} {PRODUCTION_WATCHER} &"
    )
    # Capture hook command (appended to UserPromptSubmit)
    capture_prompt_cmd = f"{PYTHON} {CAPTURE_HOOK} prompt"
    capture_post_cmd = f"{PYTHON} {CAPTURE_HOOK} post"
    capture_stop_cmd = f"{PYTHON} {CAPTURE_HOOK} stop"

    if mode == "restore":
        hooks["UserPromptSubmit"] = [{"command": production_prompt_cmd}]
        hooks.pop("PostToolUse", None)
        hooks.pop("Stop", None)
    elif mode == "baseline":
        # No search hook, capture only
        hooks["UserPromptSubmit"] = [
            {"command": capture_prompt_cmd},
        ]
        hooks["PostToolUse"] = [{"command": capture_post_cmd}]
        hooks["Stop"] = [{"command": capture_stop_cmd}]
    elif mode == "run":
        # Search hook + capture
        hooks["UserPromptSubmit"] = [
            {"command": production_prompt_cmd},
            {"command": capture_prompt_cmd},
        ]
        hooks["PostToolUse"] = [{"command": capture_post_cmd}]
        hooks["Stop"] = [{"command": capture_stop_cmd}]
    else:
        raise ValueError(f"Unknown mode: {mode}")

    _save_settings(settings)
    print(f"Hooks configured for mode: {mode}")


def clear_session_state():
    """Delete old session logs, task index, and current task file to start fresh."""
    import glob
    results_dir = os.path.join(ROOT_DIR, "eval", "results")
    for f in glob.glob(os.path.join(results_dir, "session-*.log")):
        os.remove(f)
    for f in [os.path.join(ROOT_DIR, ".eval_current_task"),
              os.path.join(ROOT_DIR, ".eval_task_index"),
              os.path.join(ROOT_DIR, ".eval_session_log")]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass


def prepare(mode):
    """Full prepare sequence: dirty check, reset, re-index, configure hooks."""
    if is_dirty():
        print("Error: repo has uncommitted changes. Commit or stash before running eval.")
        sys.exit(1)

    print(f"Preparing for {mode} session...")
    clear_session_state()
    reset_repo()
    run_reindex()
    configure_hooks(mode)
    print(f"Ready. Run your task prompts in Claude Code, then: eval.py analyze {mode}")
