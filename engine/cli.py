# engine/cli.py
"""Deterministic CLI — all state-changing logic lives here, not in slash
command prose. Stdlib only (search results come from the daemon)."""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from engine import client, migrate, paths, registry, repoident, setup_venv


def _ensure_setup() -> bool:
    if setup_venv.venv_ok():
        return True
    return setup_venv.main() == 0


def _root() -> Path | None:
    return repoident.repo_root(Path.cwd())


def format_results(results) -> None:
    # exact output format copied from search_code.py format_results
    for i, (path, start, end, text, file_type) in enumerate(results, 1):
        label = f" [{file_type}]" if file_type else ""
        print(f"MATCH {i}: {path}{label} (lines {start}-{end})")
        print("-" * 40)
        print(text)
        if not text.endswith("\n"):
            print()
        print()


def cmd_search(args) -> int:
    root = _root()
    if root is None:
        print("not a git repository", file=sys.stderr)
        return 1
    r = registry.resolve(root)
    if not r.family_enabled:
        print(f"code-search is not enabled for this repo.\n"
              f"Run: code-search enable", file=sys.stderr)
        return 1
    try:
        resp = client.search(root, " ".join(args.query),
                             n_results=args.top, all_files=args.all,
                             use_bm25=args.bm25,
                             session_id=os.environ.get("CLAUDE_SESSION_ID",
                                                       "unknown"))
    except client.DaemonUnavailable as e:
        print(f"search daemon unavailable: {e}\n"
              f"Run: code-search setup   (then retry)", file=sys.stderr)
        return 1
    if not resp.get("ok"):
        status = resp.get("status")
        if status == "warming":
            print("index still warming up — try again shortly", file=sys.stderr)
        elif status == "empty":
            print("index is empty — no indexable files in this repo", file=sys.stderr)
        elif status == "timeout":
            print("timed out waiting for the index to warm up — try again shortly",
                  file=sys.stderr)
        else:
            print(resp.get("error", "search failed"), file=sys.stderr)
        return 1
    if not resp["results"]:
        print("No results found.")
        return 2
    format_results(resp["results"])
    return 0


def cmd_enable(args) -> int:
    root = _root()
    if root is None:
        print("not a git repository — run from inside the repo you want "
              "to enable", file=sys.stderr)
        return 1
    if not args.dry_run and not _ensure_setup():
        print("setup failed; not enabling", file=sys.stderr)
        return 1
    report = migrate.migrate(root, dry_run=args.dry_run)
    if report["evidence"]:
        print("Old per-repo install detected:")
        for k in ("trashed", "skipped_tracked", "gitignore_cleaned", "killed"):
            if report[k]:
                print(f"  {k}: {report[k]}")
        if report["skipped_tracked"]:
            print("  NOTE: tracked files were left in place — remove them "
                  "with git rm when ready.")
        print(f"  backup: {paths.trash_dir()}")
    if args.dry_run:
        print("(dry run — nothing changed)")
        return 0
    r = registry.enable(root, bm25=args.bm25)
    try:
        client.watch(root, os.getpid())     # spawns daemon, queues first index
        print(f"enabled: {r.main_path} (repo_id {r.repo_id}); "
              f"first index queued")
    except client.DaemonUnavailable as e:
        print(f"enabled, but daemon failed to start: {e}", file=sys.stderr)
    return 0


def cmd_disable(args) -> int:
    root = _root()
    if root is None:
        print("not a git repository", file=sys.stderr)
        return 1
    ids = registry.disable(root)
    client.unwatch_all(root)
    if args.purge:
        for rid in ids:
            shutil.rmtree(paths.index_dir(rid), ignore_errors=True)
    print(f"disabled ({len(ids)} worktree index(es)"
          f"{' purged' if args.purge else ' kept'})")
    return 0


def cmd_status(args) -> int:
    reg = registry.load()
    for fam_id, fam in reg["repos"].items():
        print(f"{fam['main_path']}  (family {fam_id}, "
              f"bm25={fam.get('bm25', False)})")
        for rid, wt in fam["worktrees"].items():
            dead = "" if Path(wt["path"]).exists() else "  [DEAD PATH]"
            print(f"  {rid}  {wt['path']}{dead}")
    try:
        st = client.status()
        print(f"daemon: up {st['uptime_s']}s, "
              f"watching {len(st['watched'])} repo(s)")
    except client.DaemonUnavailable:
        print("daemon: not running")
    return 0


def cmd_reindex(args) -> int:
    root = _root()
    if root is None:
        print("not a git repository", file=sys.stderr)
        return 1
    try:
        client.watch(root, os.getpid())
        resp = client.request({"cmd": "reindex", "repo": str(root)})
    except client.DaemonUnavailable as e:
        print(str(e), file=sys.stderr)
        return 1
    print("reindex queued" if resp.get("ok") else resp.get("error"))
    return 0 if resp.get("ok") else 1


def cmd_gc(args) -> int:
    reaped = registry.gc()
    for rid in reaped:
        shutil.rmtree(paths.index_dir(rid), ignore_errors=True)
    cutoff = time.time() - 30 * 86400
    for entry in paths.trash_dir().glob("*"):
        if entry.stat().st_mtime < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
    print(f"gc: reaped {len(reaped)} index(es)")
    return 0


def cmd_setup(args) -> int:
    return setup_venv.main()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="code-search")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search")
    sp.add_argument("query", nargs="+")
    sp.add_argument("--top", type=int, default=5)
    sp.add_argument("--bm25", action="store_true")
    sp.add_argument("--all", action="store_true")

    ep = sub.add_parser("enable")
    ep.add_argument("--bm25", action="store_true")
    ep.add_argument("--dry-run", action="store_true")

    dp = sub.add_parser("disable")
    dp.add_argument("--purge", action="store_true")

    sub.add_parser("status")
    sub.add_parser("reindex")
    sub.add_parser("gc")
    sub.add_parser("setup")

    args = p.parse_args(argv)
    return {"search": cmd_search, "enable": cmd_enable,
            "disable": cmd_disable, "status": cmd_status,
            "reindex": cmd_reindex, "gc": cmd_gc,
            "setup": cmd_setup}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
