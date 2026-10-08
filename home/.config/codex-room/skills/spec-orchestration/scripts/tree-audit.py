#!/usr/bin/env python3
"""Detect destructive git operations on a working tree shared by Peers.

Usage:
  tree-audit.py snapshot <baseline.json> <repo>...   record branch, HEAD, reflog, stash, upstream, dirty files
  tree-audit.py check <baseline.json> [--quiet-point]

`check` reports VIOLATION lines and exits 1 when, since the snapshot:
  - the branch changed (checkout/switch);
  - HEAD no longer contains the snapshot HEAD (reset/rebase/amend);
  - HEAD's reflog gained any entry other than a plain `commit:`
    (checkout, reset, rebase, merge, pull, cherry-pick, amend, ...);
  - the stash list changed;
  - the upstream ref records a push;
  - a file that was already dirty at snapshot time changed (Human's work).
Paths dirty now but not at snapshot time print as UNCOMMITTED; with
--quiet-point (no Peer running) they are violations too. Paths inside the spec
folder are Lead's own files (tickets and `.room/`) and are ignored when the
baseline is stored at `<spec>/.room/baseline.json`.

This is detection after the fact, not prevention: work destroyed by
`reset --hard` or `clean` may be unrecoverable even though it is reported.
"""
import json
import pathlib
import subprocess
import sys


def git(repo: str, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed in {repo}: {result.stderr.strip()}")
    return result.stdout if result.returncode == 0 else ""


def reflog(repo: str, ref: str) -> list[str]:
    output = git(repo, "log", "-g", "--date=raw", "--format=%gd%x09%H%x09%gs", ref, "--", check=False)
    return [line for line in output.splitlines() if line]


def dirty_files(repo: str, ignore: pathlib.Path | None) -> dict[str, str]:
    """Map every dirty path outside `ignore` to its content hash (or <deleted>)."""
    entries = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
    paths = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        paths.append(path)
        if "R" in status or "C" in status:
            index += 1  # the rename/copy source follows
    result = {}
    for path in paths:
        file = pathlib.Path(repo) / path
        if ignore and file.resolve().is_relative_to(ignore):
            continue
        result[path] = git(repo, "hash-object", "--", path).strip() if file.is_file() else "<deleted>"
    return result


def upstream(repo: str) -> str | None:
    name = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False).strip()
    return f"refs/remotes/{name}" if name else None


def snapshot(repo: str, ignore: pathlib.Path | None) -> dict:
    root = git(repo, "rev-parse", "--show-toplevel").strip()
    remote = upstream(root)
    head_log = reflog(root, "HEAD")
    remote_log = reflog(root, remote) if remote else []
    return {
        "root": root,
        "branch": git(root, "branch", "--show-current").strip(),
        "head": git(root, "rev-parse", "HEAD").strip(),
        "reflog_top": head_log[0] if head_log else "",
        "stash": git(root, "stash", "list", "--format=%H").split(),
        "upstream": remote,
        "upstream_reflog_top": remote_log[0] if remote_log else "",
        "dirty": dirty_files(root, ignore),
    }


def entries_since(entries: list[str], top: str) -> list[str] | None:
    if not top:
        return entries
    return entries[: entries.index(top)] if top in entries else None


def check(before: dict, quiet_point: bool, ignore: pathlib.Path | None) -> tuple[list[str], list[str]]:
    root = before["root"]
    violations: list[str] = []
    uncommitted: list[str] = []
    branch = git(root, "branch", "--show-current").strip()
    if branch != before["branch"]:
        violations.append(f"branch changed from {before['branch'] or '(detached)'} to {branch or '(detached)'}")
    ancestor = subprocess.run(["git", "-C", root, "merge-base", "--is-ancestor", before["head"], "HEAD"])
    if ancestor.returncode != 0:
        violations.append(f"HEAD no longer contains {before['head'][:12]} (reset, rebase, or amend)")
    new_entries = entries_since(reflog(root, "HEAD"), before["reflog_top"])
    if new_entries is None:
        violations.append("HEAD reflog no longer contains the snapshot entry (history rewritten or expired)")
    else:
        for entry in reversed(new_entries):
            subject = entry.split("\t", 2)[2] if entry.count("\t") >= 2 else entry
            if not subject.startswith("commit:"):
                violations.append(f"non-commit HEAD operation: {subject}")
    stash = git(root, "stash", "list", "--format=%H").split()
    if stash != before["stash"]:
        violations.append(f"stash list changed ({len(before['stash'])} -> {len(stash)} entries)")
    if before["upstream"]:
        pushed = entries_since(reflog(root, before["upstream"]), before["upstream_reflog_top"]) or []
        if any("push" in entry.split("\t")[-1] for entry in pushed):
            violations.append(f"{before['upstream']} records a push")
    now = dirty_files(root, ignore)
    for path, content in before["dirty"].items():
        if now.get(path, "<clean>") != content:
            violations.append(f"pre-existing change was modified, committed, or discarded: {path}")
    for path in sorted(set(now) - set(before["dirty"])):
        (violations if quiet_point else uncommitted).append(f"uncommitted change: {path}")
    return violations, uncommitted


def spec_folder(baseline: str) -> pathlib.Path | None:
    """The spec folder when baseline.json lives in `<spec>/.room/`, else None."""
    parent = pathlib.Path(baseline).resolve().parent
    return parent.parent if parent.name == ".room" else None


def main() -> None:
    args = sys.argv[1:]
    if len(args) >= 3 and args[0] == "snapshot":
        ignore = spec_folder(args[1])
        baseline = {"repos": [snapshot(repo, ignore) for repo in args[2:]]}
        pathlib.Path(args[1]).write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
        for repo in baseline["repos"]:
            print(f"SNAPSHOT {repo['root']} {repo['branch']} {repo['head'][:12]} dirty={len(repo['dirty'])}")
        return
    if len(args) in (2, 3) and args[0] == "check" and args[2:] in ([], ["--quiet-point"]):
        baseline = json.loads(pathlib.Path(args[1]).read_text(encoding="utf-8"))
        failed = False
        for repo in baseline["repos"]:
            violations, uncommitted = check(repo, bool(args[2:]), spec_folder(args[1]))
            for line in violations:
                print(f"VIOLATION {repo['root']}: {line}")
            for line in uncommitted:
                print(f"UNCOMMITTED {repo['root']}: {line}")
            if not violations:
                print(f"OK {repo['root']}")
            failed = failed or bool(violations)
        sys.exit(1 if failed else 0)
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
