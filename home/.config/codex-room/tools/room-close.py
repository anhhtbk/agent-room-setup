#!/usr/bin/env python3
"""Remove what a Room run created once its integration branch is merged into the working branch.

Usage:
  room-close.py scan  --repo R [--repo R]...
  room-close.py close --slug S --repo R [--repo R]... [--into B]... [--root W]...
                      [--run RUN] [--drop-unmerged] [--apply]

A Room run with slug S creates, per repository R (IMPLEMENT_SPEC.md): branches
`S/integration` and `S/<ticket>-a<K>`, linked worktrees `W/<R name>-S-<suffix>`
for branch `S/<suffix>` (W defaults to `<parent of R>/.worktrees`), one adopted
Paseo workspace per worktree and the Paseo project Paseo registers for each
worktree path, and Lead's run directory RUN. The main checkout R, its Paseo
project and workspaces, and every branch outside `S/` belong to Human and are
never touched.

scan    Read-only. Per repository lists every slug that has an `S/integration`
        branch: whether it is merged into R's current branch, its branches and
        worktrees. One SCAN line per slug.
close   Dry run unless --apply. `--into` is the working branch per repository
        (one value for all, or one per --repo; default: the branch checked out
        in R). Preflight refuses every change when `S/integration` exists and
        is not an ancestor of the working branch, when the working branch is
        inside `S/`, or when the `paseo` CLI (PASEO_BIN, default `paseo`)
        fails. Then, per repository:
          worktree  removed (after archiving every active Paseo workspace and
                    deleting every Paseo project at or below its path) only
                    when it is a linked worktree of R on branch `S/<suffix>`,
                    named `<R name>-S-<suffix>` directly under W, unlocked, its
                    tip merged into the working branch, `git status` shows
                    nothing (tracked, staged or untracked; ignored build output
                    goes with it) and no merge/rebase/cherry-pick/revert/bisect
                    is in progress. Removal is `git worktree remove` without
                    --force, so git repeats its own clean check. Anything else
                    is KEEP with the reason.
          project   a Paseo project at `W/<R name>-S-<suffix>` of an existing
                    `S/<suffix>` branch whose path no longer exists (a ticket
                    worktree already removed by worktree-guard.py) is deleted;
                    Paseo keeps local files.
          branch    every `S/*` branch not checked out anywhere is deleted when
                    its tip is merged into the working branch; an unmerged one
                    (rejected attempt) only with --drop-unmerged. Each deletion
                    prints the SHA so `git branch <name> <sha>` restores it
                    until git garbage-collects the commits. W itself is
                    removed when it is left empty.
        With --run, RUN is deleted last, only when nothing was kept, refused or
        left partial, it is a Room run directory (cache, procs or baseline.json
        present, not a symlink, outside every R) and no process registered
        under RUN/procs is live (see room-gc.py).

Output: one line per item, verb first (WOULD-REMOVE, REMOVED, KEEP, REFUSE,
PARTIAL, NOTE), then one SUMMARY line.
Exit codes: 0 done (or dry run without KEEP/REFUSE); 1 something kept or
refused; 2 usage error; 3 a removal failed midway (PARTIAL).

Limits: Paseo state is read and changed only through the `paseo` CLI of the
local daemon. Workspaces under Paseo's own worktree root (~/.paseo/worktrees)
are never archived here: archiving them deletes the directory unchecked.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

PASEO_ROOT = os.path.realpath(os.path.expanduser("~/.paseo/worktrees"))
IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply")


class Refuse(Exception):
    pass


def load_room_gc():
    path = pathlib.Path(__file__).resolve().with_name("room-gc.py")
    spec = importlib.util.spec_from_file_location("room_gc", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise Refuse(f"git {' '.join(args)} in {repo}: {result.stderr.strip() or result.returncode}")
    return result


def real(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def is_ancestor(repo: str, commit: str, into: str) -> bool:
    return git(repo, "merge-base", "--is-ancestor", commit, into, check=False).returncode == 0


def branches(repo: str, prefix: str = "") -> dict[str, str]:
    pattern = f"refs/heads/{prefix}" if prefix else "refs/heads/"
    out = git(repo, "for-each-ref", "--format=%(refname:strip=2) %(objectname)", pattern).stdout
    return dict(line.split(" ", 1) for line in out.splitlines() if line)


def worktrees(repo: str) -> list[dict]:
    """Linked worktrees of `repo` (the main worktree is excluded)."""
    out = git(repo, "worktree", "list", "--porcelain").stdout
    items, current = [], {}
    for line in out.splitlines() + [""]:
        if not line:
            if current:
                items.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value if value else True
    return [{**item, "path": real(item["worktree"])} for item in items[1:]]


class Paseo:
    def __init__(self) -> None:
        self.bin = os.environ.get("PASEO_BIN", "paseo")

    def run(self, *args: str):
        try:
            result = subprocess.run([self.bin, *args, "--json"], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Refuse(f"paseo {' '.join(args)}: {error}")
        if result.returncode != 0:
            raise Refuse(f"paseo {' '.join(args)}: {result.stderr.strip() or result.stdout.strip() or result.returncode}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise Refuse(f"paseo {' '.join(args)}: unreadable JSON ({error})")

    def load(self) -> None:
        self.workspaces = self.run("workspace", "ls", "--background")
        self.projects = self.run("project", "ls")

    def workspaces_at(self, path: str) -> list[dict]:
        return [w for w in self.workspaces if under(real(w["cwd"]), path)]

    def projects_at(self, path: str) -> list[dict]:
        return [p for p in self.projects if under(real(p["path"]), path)]


class Closer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.apply = args.apply
        self.kept = self.removed = 0
        self.partial = False
        self.forgotten: set[str] = set()
        self.paseo = Paseo()

    def say(self, verb: str, text: str) -> None:
        if verb == "REMOVE":
            verb = "REMOVED" if self.apply else "WOULD-REMOVE"
            self.removed += 1
        elif verb in ("KEEP", "REFUSE"):
            self.kept += 1
        print(f"{verb} {text}")

    def plans(self) -> list[dict]:
        repos = [real(r) for r in self.args.repo]
        intos, roots = self.args.into, self.args.root
        for name, values in (("--into", intos), ("--root", roots)):
            if len(values) not in (0, 1, len(repos)):
                raise SystemExit(f"usage: {name} takes one value or one per --repo")
        plans = []
        for index, repo in enumerate(repos):
            top = git(repo, "rev-parse", "--show-toplevel").stdout.strip()
            if real(top) != repo:
                raise Refuse(f"{repo}: not the top level of a repository")
            into = intos[index if len(intos) > 1 else 0] if intos else git(repo, "branch", "--show-current").stdout.strip()
            if not into:
                raise Refuse(f"{repo}: detached HEAD; pass --into")
            if into.startswith(f"{self.args.slug}/"):
                raise Refuse(f"{repo}: working branch {into} is inside {self.args.slug}/")
            git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{into}")
            root = real(roots[index if len(roots) > 1 else 0]) if roots else real(os.path.join(os.path.dirname(repo), ".worktrees"))
            plans.append({"repo": repo, "into": into, "root": root})
        return plans

    def preflight(self, plans: list[dict]) -> None:
        slug = self.args.slug
        for plan in plans:
            tip = branches(plan["repo"], f"{slug}/").get(f"{slug}/integration")
            if tip is None:
                print(f"NOTE {plan['repo']}: no {slug}/integration branch; each {slug}/* branch is checked on its own")
            elif not is_ancestor(plan["repo"], tip, plan["into"]):
                raise Refuse(f"{plan['repo']}: {slug}/integration {tip[:12]} is not merged into {plan['into']}")
            else:
                print(f"NOTE {plan['repo']}: {slug}/integration {tip[:12]} is merged into {plan['into']}")
        self.paseo.load()

    def worktree_reason(self, plan: dict, item: dict) -> str | None:
        repo, slug, path = plan["repo"], self.args.slug, item["path"]
        branch = item.get("branch", "").removeprefix("refs/heads/")
        suffix = branch.removeprefix(f"{slug}/")
        if os.path.dirname(path) != plan["root"] or os.path.basename(path) != f"{os.path.basename(repo)}-{slug}-{suffix}":
            return f"not named {os.path.basename(repo)}-{slug}-{suffix} under {plan['root']}"
        if under(path, PASEO_ROOT):
            return "inside Paseo's own worktree root"
        if "locked" in item:
            return "locked"
        if "prunable" in item or not os.path.isdir(path):
            return "directory missing; inspect and run git worktree prune by hand"
        if not is_ancestor(repo, item["HEAD"], plan["into"]):
            return f"{branch} {item['HEAD'][:12]} is not merged into {plan['into']}"
        status = git(path, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none").stdout
        if status.strip():
            return f"not clean: {status.splitlines()[0].strip()}"
        for marker in IN_PROGRESS:
            if os.path.exists(git(path, "rev-parse", "--git-path", marker).stdout.strip()):
                return f"{marker} in progress"
        return None

    def forget(self, path: str) -> None:
        """Archive active workspaces and delete projects at or below `path` (files stay)."""
        for workspace in self.paseo.workspaces_at(path):
            if workspace["workspaceId"] in self.forgotten:
                continue
            self.forgotten.add(workspace["workspaceId"])
            self.say("REMOVE", f"workspace {workspace['workspaceId']} {workspace['cwd']}")
            if self.apply:
                self.paseo.run("workspace", "archive", workspace["workspaceId"])
        for project in self.paseo.projects_at(path):
            if project["projectId"] in self.forgotten:
                continue
            self.forgotten.add(project["projectId"])
            self.say("REMOVE", f"project {project['projectId']} {project['path']}")
            if self.apply:
                self.paseo.run("project", "delete", project["projectId"])

    def close_repo(self, plan: dict) -> None:
        repo, slug = plan["repo"], self.args.slug
        owned = branches(repo, f"{slug}/")
        names = {os.path.join(plan["root"], f"{os.path.basename(repo)}-{slug}-{b.removeprefix(slug + '/')}")
                 for b in [*owned, f"{slug}/integration"]}
        checked_out = set()
        for item in worktrees(repo):
            branch = item.get("branch", "").removeprefix("refs/heads/")
            if not branch.startswith(f"{slug}/"):
                if branch:
                    checked_out.add(branch)
                elif item["path"] in names:
                    self.say("KEEP", f"worktree {item['path']}: detached HEAD {item['HEAD'][:12]}")
                continue
            reason = self.worktree_reason(plan, item)
            if reason:
                checked_out.add(branch)
                self.say("KEEP", f"worktree {item['path']} {branch}: {reason}")
                continue
            self.forget(item["path"])
            self.say("REMOVE", f"worktree {item['path']} {branch} {item['HEAD'][:12]}")
            if self.apply:
                if not os.path.isdir(item["path"]):
                    self.partial = True
                    print(f"PARTIAL worktree {item['path']}: directory vanished while archiving its workspace")
                    continue
                result = git(repo, "worktree", "remove", item["path"], check=False)
                if result.returncode != 0:
                    self.partial = True
                    checked_out.add(branch)
                    print(f"PARTIAL worktree {item['path']}: Paseo entries removed, git refused: {result.stderr.strip()}")
        for project in self.paseo.projects:
            path = real(project["path"])
            if path in names and not os.path.exists(path):
                self.forget(path)
        for branch, tip in sorted(owned.items()):
            if branch in checked_out:
                self.say("KEEP", f"branch {branch} {tip[:12]}: checked out in a kept worktree")
                continue
            merged = is_ancestor(repo, tip, plan["into"])
            if not merged and not self.args.drop_unmerged:
                self.say("KEEP", f"branch {branch} {tip[:12]}: not merged into {plan['into']} (--drop-unmerged deletes it)")
                continue
            self.say("REMOVE", f"branch {branch} {tip} {'merged' if merged else 'unmerged'}; restore: git -C {repo} branch {branch} {tip}")
            if self.apply:
                result = git(repo, "update-ref", "-d", f"refs/heads/{branch}", tip, check=False)
                if result.returncode != 0:
                    self.partial = True
                    print(f"PARTIAL branch {branch}: {result.stderr.strip()}")
        root = plan["root"]
        if self.apply and os.path.isdir(root) and not os.path.islink(root) and not os.listdir(root):
            os.rmdir(root)
            print(f"REMOVED empty worktree directory {root}")

    def close_run(self, repos: list[str]) -> None:
        run = real(self.args.run)
        gc = load_room_gc()
        if os.path.islink(self.args.run) or not gc.is_run(pathlib.Path(run)):
            return self.say("REFUSE", f"run {run}: not a Room run directory")
        if any(under(run, repo) for repo in repos):
            return self.say("REFUSE", f"run {run}: inside a repository checkout")
        if self.kept or self.partial:
            return self.say("KEEP", f"run {run}: holds the baselines and evidence of what was kept")
        live = gc.live_records(pathlib.Path(run))
        if live:
            return self.say("KEEP", f"run {run}: live record {live[0][0].get('name')} ({live[0][1]}); stop it with run-procs.py stop")
        self.say("REMOVE", f"run {run} {gc.human(gc.disk_bytes(pathlib.Path(run)))}")
        if self.apply:
            shutil.rmtree(run)

    def close(self) -> int:
        plans = self.plans()
        self.preflight(plans)
        try:
            for plan in plans:
                self.close_repo(plan)
            if self.args.run:
                self.close_run([plan["repo"] for plan in plans])
        except Refuse as error:
            if not self.apply:
                raise
            self.partial = True
            print(f"PARTIAL {error}: the item on the line above did not complete; nothing after it ran")
        verb = "removed" if self.apply else "would-remove"
        print(f"SUMMARY {verb}={self.removed} kept={self.kept} partial={'yes' if self.partial else 'no'}")
        return 3 if self.partial else 1 if self.kept else 0


def scan(args: argparse.Namespace) -> int:
    for repo in map(real, args.repo):
        into = git(repo, "branch", "--show-current").stdout.strip() or "HEAD"
        heads = branches(repo)
        trees = worktrees(repo)
        slugs = sorted(name.removesuffix("/integration") for name in heads if name.endswith("/integration"))
        if not slugs:
            print(f"SCAN {repo}: no */integration branch")
        for slug in slugs:
            owned = [name for name in heads if name.startswith(f"{slug}/")]
            paths = [t["path"] for t in trees if t.get("branch", "").startswith(f"refs/heads/{slug}/")]
            merged = is_ancestor(repo, heads[f"{slug}/integration"], into)
            print(f"SCAN {repo} slug={slug} integration={'merged' if merged else 'unmerged'} into={into} "
                  f"branches={len(owned)} worktrees={len(paths)}")
            for path in paths:
                print(f"  WORKTREE {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    sub = commands.add_parser("scan")
    sub.add_argument("--repo", action="append", required=True)
    sub = commands.add_parser("close")
    sub.add_argument("--slug", required=True)
    sub.add_argument("--repo", action="append", required=True)
    sub.add_argument("--into", action="append", default=[])
    sub.add_argument("--root", action="append", default=[])
    sub.add_argument("--run")
    sub.add_argument("--drop-unmerged", action="store_true")
    sub.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.action == "close" and (not args.slug or "/" in args.slug or args.slug in (".", "..")):
        parser.error("--slug must be one path segment")
    try:
        return scan(args) if args.action == "scan" else Closer(args).close()
    except Refuse as error:
        print(f"REFUSE {error}")
        print("SUMMARY nothing changed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
