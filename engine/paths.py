"""Central data-dir layout. Stdlib only — imported by hooks without the venv."""
import os
from pathlib import Path


def home() -> Path:
    env = os.environ.get("CODE_SEARCH_HOME")
    return Path(env) if env else Path.home() / ".code-search"


def ensure_home() -> Path:
    h = home()
    for sub in ("indexes", "state", "logs", "trash"):
        (h / sub).mkdir(parents=True, exist_ok=True)
    return h


def registry_path() -> Path: return home() / "registry.json"
def registry_lock_path() -> Path: return home() / "registry.lock"
def indexes_dir() -> Path: return home() / "indexes"
def index_dir(repo_id: str) -> Path: return home() / "indexes" / repo_id
def socket_path() -> Path: return home() / "daemon.sock"
def pid_path() -> Path: return home() / "daemon.pid"
def watches_path() -> Path: return home() / "state" / "watches.json"
def state_dir() -> Path: return home() / "state"
def logs_dir() -> Path: return home() / "logs"
def trash_dir() -> Path: return home() / "trash"
def config_path() -> Path: return home() / "config.json"
def venv_dir() -> Path: return home() / "venv"
def venv_python() -> Path: return home() / "venv" / "bin" / "python3"
def venv_ok_path() -> Path: return home() / "venv.ok"
