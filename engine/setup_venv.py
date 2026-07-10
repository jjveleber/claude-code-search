# engine/setup_venv.py
"""Bootstrap the central venv. Stdlib only; runs under any python3."""
import fcntl
import hashlib
import subprocess
import sys
from pathlib import Path

from engine import paths

REQUIREMENTS = Path(__file__).with_name("requirements.txt")


def _req_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def venv_ok() -> bool:
    # The marker alone is not enough: if the venv dir is deleted (to reclaim
    # the multi-GB torch install) or its interpreter is broken by an OS python
    # upgrade, a stale venv.ok would make setup report "already up to date"
    # while the daemon can't start — an unrecoverable loop. Require both.
    if not paths.venv_python().exists():
        return False
    try:
        return paths.venv_ok_path().read_text().strip() == _req_hash()
    except OSError:
        return False


def main() -> int:
    paths.ensure_home()
    with open(paths.home() / "setup.lock", "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        if venv_ok():
            print("venv already up to date")
            return 0
        vdir = paths.venv_dir()
        if not paths.venv_python().exists():
            print(f"Creating venv at {vdir} ...")
            subprocess.run([sys.executable, "-m", "venv", str(vdir)],
                           check=True)
        print("Installing dependencies (this downloads torch — several GB "
              "on first run) ...")
        r = subprocess.run([str(vdir / "bin" / "pip"), "install", "-r",
                            str(REQUIREMENTS)])
        if r.returncode != 0:
            print("pip install failed — venv left without venv.ok marker",
                  file=sys.stderr)
            return r.returncode
        paths.venv_ok_path().write_text(_req_hash())
        print("Setup complete.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
