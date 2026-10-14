#!/usr/bin/env python3
"""Report and delete the rebuildable cache of Room run directories.

Usage:
  room-gc.py report [<path>...]
  room-gc.py clean <run-dir> [--entry NAME]... [--apply]

A run directory (RUN) is Lead's per-spec directory (`<spec folder>/.room` or
`~/.local/state/codex-room/runs/<slug>`). `RUN/cache/` holds only bytes that can
be rebuilt from a commit: verification instances, build outputs, database data,
copied dependencies. Everything else in RUN (baselines, manifests, logs, notes,
evidence) is kept. Processes are registered by run-procs.py under `RUN/procs/`.

report  Prints one RUN line per run directory: total bytes, cache bytes, other
        bytes, live process records, then one CACHE line per cache entry. A
        path that is not itself a run directory is searched (depth 3) for run
        directories. Default path: ~/.local/state/codex-room/runs. A RUN whose
        cache is empty but whose `other` bytes are large is a run directory
        written before the cache layout: inspect it by hand.
clean   Dry run unless --apply. Without --entry the whole `RUN/cache` is the
        target and any live record under `RUN/procs` refuses it. With --entry,
        each `RUN/cache/NAME` is a target and a live record refuses it when its
        cwd, log or any argument contains the entry's absolute path or equals
        NAME. A record is live when run-procs.py verifies its holder, when its
        process group still has members, or when it is still starting; an
        unreadable record or process table counts as live. Symlinked targets are
        refused. Ends with one SUMMARY line.

Exit codes: 0 done (or dry run); 1 anything refused; 2 usage error.

Limits: processes started outside run-procs.py (or with a registry outside
`RUN/procs`) are invisible here; stop them before cleaning.
"""
import argparse
import importlib.util
import os
import pathlib
import shutil
import sys

DEFAULT_ROOT = pathlib.Path.home() / ".local" / "state" / "codex-room" / "runs"
RUN_MARKERS = ("cache", "procs", "baseline.json")
SEARCH_DEPTH = 3
SKIP_DIRS = {".git", "node_modules"}


def load_run_procs():
    path = pathlib.Path(__file__).resolve().with_name("run-procs.py")
    spec = importlib.util.spec_from_file_location("run_procs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RP = load_run_procs()


def disk_bytes(path: pathlib.Path) -> int:
    """Allocated bytes under `path`, never following symlinks."""
    try:
        info = path.lstat()
    except OSError:
        return 0
    total = info.st_blocks * 512
    if path.is_symlink() or not path.is_dir():
        return total
    for root, dirs, files in os.walk(path, onerror=lambda _error: None):
        for name in dirs + files:
            try:
                total += os.lstat(os.path.join(root, name)).st_blocks * 512
            except OSError:
                pass
    return total


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "K", "M", "G"):
        if value < 1024:
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}T"


def is_run(path: pathlib.Path) -> bool:
    return any((path / marker).exists() for marker in RUN_MARKERS)


def find_runs(path: pathlib.Path, depth: int = 0) -> list[pathlib.Path]:
    if path.is_symlink() or not path.is_dir():
        return []
    if is_run(path):
        return [path]
    if depth >= SEARCH_DEPTH:
        return []
    found = []
    try:
        children = sorted(path.iterdir())
    except OSError:
        return []
    for child in children:
        if child.name not in SKIP_DIRS:
            found.extend(find_runs(child, depth + 1))
    return found


def live_records(run: pathlib.Path) -> list[tuple[dict, str]]:
    """(record, why) for every record under RUN/procs that may still have processes."""
    procs = run / "procs"
    if not procs.is_dir():
        return []
    live = []
    for path in sorted(procs.rglob("*.json")):
        try:
            record = RP.read_record(path)
        except RP.RecordError as error:
            live.append(({"name": path.stem, "command": [], "cwd": "", "log": None}, f"unreadable: {error}"))
            continue
        state = record.get("state")
        try:
            if state == "starting":
                live.append((record, "starting"))
            elif state == "running" and RP.verified(record):
                live.append((record, "running"))
            elif state == "running" and RP.group_members(record["pgid"]):
                live.append((record, "unverified group members"))
        except RP.PsUnavailable as error:
            live.append((record, f"process table unknown: {error}"))
    return live


def references(record: dict, entry: pathlib.Path) -> bool:
    if not record.get("command") and not record.get("cwd"):
        return True  # unreadable record: assume it uses everything
    absolute = str(entry)
    texts = [str(part) for part in record.get("command", [])] + [record.get("cwd") or "", record.get("log") or ""]
    return any(absolute in text or text == entry.name or text.endswith(f"={entry.name}") for text in texts)


def report(args: argparse.Namespace) -> int:
    paths = [pathlib.Path(p).expanduser().resolve() for p in args.paths] or [DEFAULT_ROOT]
    runs = []
    for path in paths:
        if not path.exists():
            print(f"MISSING {path}")
            continue
        runs.extend(find_runs(path))
    if not runs:
        print("NO-RUNS")
    for run in runs:
        cache = run / "cache"
        total, cached = disk_bytes(run), disk_bytes(cache) if cache.is_dir() else 0
        print(f"RUN {run} total={human(total)} cache={human(cached)} other={human(total - cached)} "
              f"live={len(live_records(run))}")
        if cache.is_dir() and not cache.is_symlink():
            for entry in sorted(cache.iterdir()):
                print(f"CACHE {entry.name} {human(disk_bytes(entry))}")
    return 0


def clean(args: argparse.Namespace) -> int:
    run = pathlib.Path(args.run).expanduser().resolve()
    cache = run / "cache"
    if not is_run(run):
        print(f"REFUSE {run}: not a run directory (no {', '.join(RUN_MARKERS)})")
        return 1
    if cache.is_symlink():
        print(f"REFUSE {cache}: symlink")
        return 1
    if not cache.is_dir():
        print(f"SUMMARY nothing to clean: {cache} does not exist")
        return 0
    live = live_records(run)
    targets = [cache / name for name in args.entry] if args.entry else [cache]
    refused = removed = 0
    freed = 0
    for target in targets:
        if args.entry and (target.parent != cache or target.name in ("", ".", "..")):
            print(f"REFUSE {target}: --entry must name a direct child of {cache}")
            refused += 1
            continue
        if target.is_symlink():
            print(f"REFUSE {target}: symlink")
            refused += 1
            continue
        if not target.exists():
            print(f"SKIP {target}: does not exist")
            continue
        blockers = live if target == cache else [(r, why) for r, why in live if references(r, target)]
        if blockers:
            for record, why in blockers:
                print(f"REFUSE {target}: live record {record.get('name')} ({why}); stop it with run-procs.py stop")
            refused += 1
            continue
        size = disk_bytes(target)
        if not args.apply:
            print(f"WOULD-REMOVE {target} {human(size)}")
            freed += size
            continue
        shutil.rmtree(target) if target.is_dir() else target.unlink()
        print(f"REMOVED {target} {human(size)}")
        removed += 1
        freed += size
    verb = "freed" if args.apply else "would free"
    print(f"SUMMARY {verb}={human(freed)} removed={removed} refused={refused}")
    return 1 if refused else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    sub = commands.add_parser("report")
    sub.add_argument("paths", nargs="*")
    sub = commands.add_parser("clean")
    sub.add_argument("run")
    sub.add_argument("--entry", action="append", default=[])
    sub.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return {"report": report, "clean": clean}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
