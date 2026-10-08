#!/usr/bin/env python3
"""Remove a disposable linked git worktree only when its content still equals a baseline its writer recorded.

Usage:
  worktree-guard.py record <manifest> --repo R --worktree P --root D --owner O --head SHA [--merge-head SHA]
  worktree-guard.py check  <manifest> --owner O
  worktree-guard.py remove <manifest> --owner O --digest D

Protocol (who calls what)
  The writer of the worktree runs `record` in the same session as its last
  write (merge, build, test), passing the commit it believes is checked out
  (--head) and, for a worktree that deliberately holds an unfinished merge,
  the merged commit (--merge-head). Nobody else records for a writer: the tool
  cannot know who made a worktree, only that its content equals what the writer
  attested. The writer also attests every `IGNORED <path>` line that `record`
  prints (build output, caches). The writer's disposition (or whoever later
  decides the cleanup) binds the printed manifest digest, and `remove`
  requires that digest, so a manifest swapped after the disposition is refused.

record   Refuses, leaving no manifest, no owner token and no directory behind:
         manifest exists; worktree not strictly inside --root; not the top
         level of a linked worktree; locked; belongs to another repository
         than --repo; HEAD != --head; untracked non-ignored files; assume-
         unchanged and skip-worktree index entries (they hide edits); a nested
         repository (submodule or clone, at any depth) with staged/unstaged/
         untracked-non-ignored changes or an operation in progress; the tree
         changing while it is being captured. Without --merge-head it also
         refuses any staged change, conflict entry, unstaged tracked change, and
         any operation in progress (merge, cherry-pick, revert, rebase,
         sequencer, bisect, index.lock). With --merge-head MERGE_HEAD must
         equal it, other operations still refuse, and the worktree must be the
         unmodified result of `git merge` of it into HEAD with the default
         strategy, as computed by `git merge-tree --write-tree` (in a
         throw-away object directory; the repository is not written):
         every path that is not a conflict must have its index entry equal to
         the merge result and its working bytes equal to the index (git
         status shows no unstaged change); the conflict stages 1/2/3 must
         equal the merge's; the working file of every conflict must equal the
         file the merge writes (blob through the path's checkout filters),
         ignoring the text after the <<<<<<< ||||||| >>>>>>> markers, which
         `git merge` takes from the branch name. A submodule whose pointer
         the merge moved may stay at its old checkout.
         Success prints `RECORDED ... digest=<sha256 of the manifest bytes>`
         and one `IGNORED <path>` per ignored entry (a fully ignored directory
         is one line). Capture and validation come first; the token and the
         manifest are written last, so a failed record leaves nothing.
check    `OK identical to baseline digest=<d>`, or DIFF/REFUSE lines. Changes
         nothing.
remove   Refuses, touching nothing, on digest mismatch, owner mismatch,
         identity mismatch, any content difference, an already removed
         manifest, or any directory git could not delete (unwritable
         directory, immutable flag). Otherwise `git worktree remove --force`
         on exactly that worktree (it also drops an in-progress merge); never
         prunes other worktrees, never deletes the parent. The manifest is
         never rewritten (its digest stays valid); success writes a sibling
         marker `<manifest>.removed`. If git fails midway the result is
         `PARTIAL ...` stating what is gone and what is left (exit 3), never
         REFUSE.

The baseline covers: repository common dir, worktree path, admin dir and owner
token; HEAD (symbolic and resolved); index entries with stage (staged and
conflict state) and flags; every file, symlink and directory under the
worktree incl. untracked, ignored and conflicted working bytes; every file of
the worktree admin dir (MERGE_*, rebase/cherry-pick/bisect state, per-worktree
refs, HEAD reflog, config.worktree, info/); and, for every nested repository,
every file of its git directory (embedded `.git/` or the admin `modules/**`
dir: objects, refs, reflogs, config, hooks) except its `index` stat cache,
whose entries are compared through `git ls-files`.

Exit codes: 0 OK/RECORDED/REMOVED, 1 refused or different, 2 usage error,
3 PARTIAL.

Limits (read before trusting):
- Helper, not a sandbox. `check`/`remove` re-hash the whole worktree, ignored
  outputs and nested git dirs included. Measured on one macOS machine: 1.3 s
  for 20k files / 1.2 GB (scales with size). That pass is not atomic. A
  closing lstat pass (0.1 s at that size) compares size, mtime, ctime, inode
  and mode of every entry with what the hash pass saw, so a write during the
  hash pass is refused. A write landing after an entry was re-scanned and
  before `git worktree remove` deletes it (order of 0.1 s plus the deletion
  time, both growing with size) is lost. The re-scan only adds refusals; it
  narrows the race from the hash pass to that window, it does not close it.
  Processes holding files open in the worktree are not detected: stop the
  run's processes first.
- The baseline proves "unchanged since record", not "nobody edited before
  record". Plain mode proves, by refusal, that no tracked, staged, untracked or
  nested change exists at record (ignored files and anything the writer
  attests are taken as given). --merge-head mode proves the same for every
  non-conflict path, and for the conflict stages and conflict working bytes
  relative to what the default `git merge` produces. Not proven there: the
  label text on conflict marker lines (ignored), the content of a submodule
  checkout whose pointer the merge moved (only the nested-repository checks
  and the baseline cover it), and anything the writer attests. Refused as a
  difference, though legitimate: a merge made with another strategy, -X
  option or -s ours, a merge driver or .gitattributes changed after the
  merge, a changed conflict-marker-size, and any non-default resolution of a
  conflict. Skip-worktree and assume-unchanged entries are refused in both
  modes, so sparse checkouts cannot be recorded.
- Commits reachable only from the common dir of the repository (branches,
  tags, stash) survive removal and are not part of the baseline; HEAD, the
  worktree reflog and nested repositories are.
- Deletability is pre-checked with access(2) and file flags; other causes of a
  failing `git worktree remove` (busy mount, ACL deny) still end as PARTIAL.
- A nested `.git` that is a symlink is refused. Unix only (macOS, Linux);
  file names that are not valid UTF-8 are untested.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import secrets
import stat
import subprocess
import sys
import tempfile

SCHEMA = 2
TOKEN_FILE = "codex-room-owner"
OPERATION_FILES = (
    "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD", "BISECT_LOG", "BISECT_START",
    "rebase-merge", "rebase-apply", "sequencer", "index.lock",
)
UNMERGED = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
SHA_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")
FLAG_MASK = sum(getattr(stat, name, 0) for name in (
    "UF_IMMUTABLE", "UF_APPEND", "UF_NOUNLINK", "SF_IMMUTABLE", "SF_APPEND", "SF_NOUNLINK"))
LINE_LIMIT = 60
GIT_ENV = {
    **{key: value for key, value in os.environ.items() if key not in {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX"}},
    "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C",
}


class Refuse(Exception):
    pass


def shown(text: str) -> str:
    """Printable form of a path: control characters and undecodable bytes escaped."""
    if text.isprintable():
        return text
    return text.encode("unicode_escape", errors="backslashreplace").decode("ascii")


def run_git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", cwd, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="surrogateescape", env=GIT_ENV)


def git(cwd: str, *args: str) -> str:
    result = run_git(cwd, *args)
    if result.returncode != 0:
        raise Refuse(f"git {' '.join(args)} failed in {shown(cwd)}: {result.stderr.strip()}")
    return result.stdout


def git_ok(cwd: str, *args: str) -> str | None:
    result = run_git(cwd, *args)
    return result.stdout if result.returncode == 0 else None


def real(path: str | os.PathLike) -> str:
    return os.path.realpath(os.path.abspath(path))


def under(path: str, root: str) -> bool:
    return path != root and pathlib.Path(path).is_relative_to(root)


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class Scan:
    """One walk: content per entry, cheap signature per entry, nested repository
    roots, and directories git could not delete."""

    def __init__(self) -> None:
        self.tree: dict[str, str] = {}
        self.sig: dict[str, tuple] = {}
        self.nested: list[str] = []
        self.blockers: list[str] = []


def scan(root: str, hashing: bool, inside_git: bool = False, skip_top: frozenset = frozenset()) -> Scan:
    """Walk root. `inside_git`: root is a git dir, whose top-level `index` (stat cache)
    is skipped; the same applies to every `.git/` directory met below the worktree."""
    result = Scan()
    stack = [("", inside_git)]
    while stack:
        relative, inside = stack.pop()
        directory = os.path.join(root, relative) if relative else root
        with os.scandir(directory) as entries:
            names = sorted(item.name for item in entries)
        if relative and not inside and ".git" in names:
            result.nested.append(relative)
        for name in names:
            if not relative and name in skip_top:
                continue
            if inside and name == "index" and "HEAD" in names:
                continue
            child = f"{relative}/{name}" if relative else name
            path = os.path.join(root, child)
            info = os.lstat(path)
            kind = stat.S_IFMT(info.st_mode)
            result.sig[child] = (info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
            if kind == stat.S_IFLNK:
                if name == ".git":
                    raise Refuse(f"{shown(child)} is a symlink; nested repository content cannot be compared")
                result.tree[child] = "link:" + os.readlink(path)
            elif kind == stat.S_IFDIR:
                result.tree[child] = "dir"
                stack.append((child, inside or name == ".git"))
                if hashing and not os.access(path, os.W_OK | os.X_OK):
                    result.blockers.append(f"directory not writable: {shown(child)}")
            elif kind == stat.S_IFREG:
                executable = "x" if info.st_mode & 0o111 else "-"
                result.tree[child] = f"file{executable}:{file_digest(path) if hashing else ''}"
            else:
                result.tree[child] = f"special:{kind:o}"
            if hashing and getattr(info, "st_flags", 0) & FLAG_MASK:
                result.blockers.append(f"immutable or append-only flag: {shown(child)}")
    return result


def git_dir_of(repo: str) -> str:
    return real(git(repo, "rev-parse", "--absolute-git-dir").strip())


def repo_state(repo: str, refs: bool = True) -> dict:
    """Readable git state of one repository or worktree; bytes of the git dir are compared separately."""
    head = git_ok(repo, "rev-parse", "--verify", "-q", "HEAD")
    state = {
        "head": head.strip() if head else None,
        "symbolic_head": (git_ok(repo, "symbolic-ref", "-q", "HEAD") or "").strip() or None,
        "index": git(repo, "ls-files", "--stage", "-z").split("\0")[:-1],
        "index_flags": git(repo, "ls-files", "-v", "-z").split("\0")[:-1],
    }
    if refs:
        state["refs"] = git(repo, "for-each-ref", "--format=%(objectname) %(refname)").splitlines()
    return state


def capture(worktree: str, admin: str) -> tuple[dict, tuple[Scan, Scan]]:
    tree = scan(worktree, hashing=True)
    admin_tree = scan(admin, hashing=True, inside_git=True, skip_top=frozenset({TOKEN_FILE}))
    content = {
        "tree": tree.tree,
        "admin_tree": admin_tree.tree,
        "git": repo_state(worktree, refs=False),
        "nested": {path: repo_state(os.path.join(worktree, path)) for path in tree.nested},
    }
    return content, (tree, admin_tree)


def identity(worktree: str) -> dict:
    if not os.path.isdir(worktree):
        raise Refuse(f"worktree path does not exist: {shown(worktree)}")
    top = git_ok(worktree, "rev-parse", "--show-toplevel")
    if top is None or real(top.strip()) != worktree:
        raise Refuse(f"not the top level of a git worktree: {shown(worktree)}")
    admin = git_dir_of(worktree)
    common = real(os.path.join(worktree, git(worktree, "rev-parse", "--git-common-dir").strip()))
    if admin == common:
        raise Refuse("path is a main worktree, not a linked worktree")
    if os.path.exists(os.path.join(admin, "locked")):
        raise Refuse("worktree is locked by someone (git worktree lock)")
    return {"admin": admin, "common": common}


def diff_maps(kind: str, before: dict, now_: dict) -> list[str]:
    lines = []
    for key in sorted(set(before) | set(now_)):
        if before.get(key) != now_.get(key):
            change = "added" if key not in before else "removed" if key not in now_ else "changed"
            lines.append(f"DIFF {kind} {change}: {shown(key)}")
    return lines


def diff_state(prefix: str, before: dict, now_: dict) -> list[str]:
    lines = []
    for field in ("head", "symbolic_head"):
        if before.get(field) != now_.get(field):
            lines.append(f"DIFF {prefix}{field}: {before.get(field)} -> {now_.get(field)}")
    for field in ("index", "index_flags", "refs"):
        if field in before and before[field] != now_.get(field):
            lines.append(f"DIFF {prefix}{field} changed (staged, conflict, flag, or ref content)")
    return lines


def emit(lines: list[str]) -> None:
    for line in lines[:LINE_LIMIT]:
        print(line)
    if len(lines) > LINE_LIMIT:
        print(f"... and {len(lines) - LINE_LIMIT} more difference lines")


def signature_changes(before: tuple[Scan, Scan], after: tuple[Scan, Scan]) -> list[str]:
    lines = []
    for label, one, two in (("worktree", before[0], after[0]), ("admin", before[1], after[1])):
        lines += [line.replace("DIFF ", "", 1) for line in diff_maps(label, one.sig, two.sig)]
    return lines


def load(path: str) -> tuple[dict, str]:
    """Manifest and sha256 of the very bytes it was parsed from."""
    if not os.path.isfile(path):
        raise Refuse(f"baseline manifest missing: {shown(path)}")
    raw = pathlib.Path(path).read_bytes()
    try:
        manifest = json.loads(raw)
        for key in ("schema", "owner", "root", "worktree", "common", "admin", "token", "content"):
            manifest[key]
        for key in ("tree", "admin_tree", "git", "nested"):
            manifest["content"][key]
    except (ValueError, KeyError, TypeError):
        raise Refuse(f"manifest is not a valid baseline: {shown(path)}") from None
    if manifest["schema"] != SCHEMA:
        raise Refuse(f"unsupported manifest schema {manifest['schema']}")
    return manifest, hashlib.sha256(raw).hexdigest()


def removed_marker(manifest_path: str) -> str:
    return f"{manifest_path}.removed"


def verify(manifest: dict, manifest_path: str, owner: str) -> tuple[list[str], tuple[Scan, Scan], dict]:
    """DIFF lines (empty: identical) and the scans they came from. Refusals raise."""
    if os.path.lexists(removed_marker(manifest_path)):
        raise Refuse(f"manifest already marked removed: {shown(removed_marker(manifest_path))}")
    if owner != manifest["owner"]:
        raise Refuse(f"owner {owner!r} does not match manifest owner {manifest['owner']!r}")
    worktree, root = manifest["worktree"], manifest["root"]
    if not under(worktree, root):
        raise Refuse(f"{shown(worktree)} is not strictly inside root {shown(root)}")
    ident = identity(worktree)
    if ident["common"] != manifest["common"]:
        raise Refuse(f"repository changed: {shown(ident['common'])} != {shown(manifest['common'])}")
    if ident["admin"] != manifest["admin"]:
        raise Refuse(f"worktree admin dir changed: {shown(ident['admin'])} != {shown(manifest['admin'])}")
    token_path = os.path.join(ident["admin"], TOKEN_FILE)
    token = pathlib.Path(token_path).read_text().strip() if os.path.isfile(token_path) else None
    if token != manifest["token"]:
        raise Refuse("owner token missing or different: worktree was recreated or is not this manifest's")
    now_, scans = capture(worktree, ident["admin"])
    base = manifest["content"]
    lines = diff_maps("file", base["tree"], now_["tree"])
    lines += diff_maps("admin", base["admin_tree"], now_["admin_tree"])
    lines += diff_state("", base["git"], now_["git"])
    for path in sorted(set(base["nested"]) | set(now_["nested"])):
        if path not in base["nested"] or path not in now_["nested"]:
            lines.append(f"DIFF nested repository added or removed: {shown(path)}")
        else:
            lines += diff_state(f"nested {shown(path)} ", base["nested"][path], now_["nested"][path])
    return lines, scans, ident


def operations_in(git_dir: str, allow: tuple[str, ...] = ()) -> list[str]:
    return [name for name in OPERATION_FILES if name not in allow and os.path.lexists(os.path.join(git_dir, name))]


def status_entries(repo: str) -> list[tuple[str, str]]:
    fields = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none").split("\0")
    entries, index = [], 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        code, path = field[:2], field[3:]
        if code[0] in "RC":
            index += 1  # original path of a rename/copy
        entries.append((code, path))
    return entries


def git_bytes(cwd: str, env: dict, *args: str) -> bytes:
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", cwd, *args], capture_output=True, env=env)
    if result.returncode != 0:
        raise Refuse(f"git {args[0]} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def split_z(raw: bytes) -> list[str]:
    return [item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item]


def tree_entries(cwd: str, env: dict, tree: str) -> dict[str, tuple[str, str]]:
    """path -> (mode, oid) of every non-tree entry of a tree."""
    entries = {}
    for item in split_z(git_bytes(cwd, env, "ls-tree", "-r", "-z", "--full-tree", tree)):
        meta, path = item.split("\t", 1)
        mode, _, oid = meta.split(" ")
        entries[path] = (mode, oid)
    return entries


def index_entries(cwd: str, env: dict) -> tuple[dict[str, tuple[str, str]], dict[str, set]]:
    """(stage 0 path -> (mode, oid), unmerged path -> {(stage, mode, oid)}) of the index."""
    merged: dict[str, tuple[str, str]] = {}
    unmerged: dict[str, set] = {}
    for item in split_z(git_bytes(cwd, env, "ls-files", "-s", "-z")):
        meta, path = item.split("\t", 1)
        mode, oid, stage = meta.split(" ")
        if stage == "0":
            merged[path] = (mode, oid)
        else:
            unmerged.setdefault(path, set()).add((stage, mode, oid))
    return merged, unmerged


MARKER_LABEL = re.compile(rb"^(<{7}|\|{7}|>{7})[ \t][^\r\n]*", re.MULTILINE)
LABELLED = re.compile(r"~[^/~]+$")


def expected_working_bytes(cwd: str, env: dict, path: str, mode: str, oid: str) -> bytes:
    """Bytes git leaves in the working tree for a conflicted path whose merge-tree result is (mode, oid)."""
    if mode == "120000":
        return git_bytes(cwd, env, "cat-file", "blob", oid)
    return git_bytes(cwd, env, "cat-file", "--filters", f"--path={path}", oid)


def canonical(path: str) -> str:
    return LABELLED.sub("~*", path)


def working_bytes(worktree: str, path: str) -> bytes | None:
    full = os.path.join(worktree, path)
    try:
        info = os.lstat(full)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return os.readlink(full.encode("utf-8", "surrogateescape"))
    if not stat.S_ISREG(info.st_mode):
        return b"\0not a regular file"
    with open(full.encode("utf-8", "surrogateescape"), "rb") as handle:
        return handle.read()


def merge_deviations(worktree: str, head: str, merge_head: str, status: list[tuple[str, str]]) -> list[str]:
    """What differs from `git merge` of merge_head into head, computed by `git merge-tree` (the default
    strategy of `git merge`) in a throw-away object directory that falls back to the real one."""
    common = os.path.join(real(os.path.join(worktree, git(worktree, "rev-parse", "--git-common-dir").strip())), "objects")
    with tempfile.TemporaryDirectory(prefix="worktree-guard-") as quarantine:
        env = {**GIT_ENV, "GIT_OBJECT_DIRECTORY": quarantine, "GIT_ALTERNATE_OBJECT_DIRECTORIES": common}
        run = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", worktree, "merge-tree", "--write-tree", "-z", "--no-messages",
             "--allow-unrelated-histories", head, merge_head], capture_output=True, env=env)
        if run.returncode not in (0, 1):
            raise Refuse(f"cannot compute the merge of {merge_head} into {head}: "
                         f"{run.stderr.decode('utf-8', 'replace').strip()}")
        tree, *infos = split_z(run.stdout)
        expected = tree_entries(worktree, env, tree)
        before = tree_entries(worktree, env, head)
        conflicts: dict[str, set] = {}  # keyed by canonical path; `git merge` and merge-tree name `file~<label>` differently
        named: dict[str, list[str]] = {}
        for info in infos:
            meta, path = info.split("\t", 1)
            mode, oid, stage = meta.split(" ")
            conflicts.setdefault(canonical(path), set()).add((stage, mode, oid))
            named.setdefault(canonical(path), []).append(path)
        merged, unmerged = index_entries(worktree, env)
        held: dict[str, set] = {}
        for path, stages in unmerged.items():
            held.setdefault(canonical(path), set()).update(stages)
        problems: dict[str, list[str]] = {}
        for path in sorted(set(merged) | set(expected)):
            if canonical(path) not in conflicts and merged.get(path) != expected.get(path):
                problems.setdefault("index differs from the merge result", []).append(path)
        for path in sorted(set(held) | set(conflicts)):
            if held.get(path, set()) != conflicts.get(path, set()):
                problems.setdefault("conflict stages differ from the merge result", []).append(path)
        for code, path in status:
            if code == "??" or code in UNMERGED or code[1] == " ":
                continue
            gitlink = merged.get(path, ("",))[0] == "160000" and expected.get(path) != before.get(path)
            if not gitlink:  # a submodule checkout is left where it was by `git merge`; its own repository is checked apart
                problems.setdefault("edited after the merge", []).append(path)
        for path in sorted(unmerged):
            targets = [expected.get(other) for other in named.get(canonical(path), [])]
            if any(target is not None and target[0] == "160000" for target in targets):
                continue
            found = working_bytes(worktree, path)
            normal = None if found is None else MARKER_LABEL.sub(rb"\1", found)
            wanted = [None if target is None else MARKER_LABEL.sub(rb"\1", expected_working_bytes(worktree, env, path, *target))
                      for target in targets]
            if normal not in wanted:
                problems.setdefault("conflicted working bytes differ from what the merge writes", []).append(path)
    return [f"{kind}: {listed(paths)}" for kind, paths in problems.items()]


def listed(paths: list[str]) -> str:
    return ", ".join(shown(path) for path in paths[:8]) + (f" (+{len(paths) - 8} more)" if len(paths) > 8 else "")


def normalize(rev: str, cwd: str, flag: str) -> str:
    rev = rev.lower()
    if not SHA_PATTERN.match(rev):
        raise Refuse(f"{flag} must be a hex commit id of 7-64 characters, got {rev!r}")
    full = git_ok(cwd, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}")
    if full is None:
        raise Refuse(f"{flag} {rev} is not a commit in this repository")
    return full.strip()


def check_clean(worktree: str, admin: str, head: str, merge_head: str | None) -> None:
    current = git_ok(worktree, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    if current is None or current.strip() != head:
        raise Refuse(f"HEAD is {current.strip() if current else 'unborn'}, not --head {head}")
    if merge_head:
        marker = os.path.join(admin, "MERGE_HEAD")
        lines = pathlib.Path(marker).read_text().split() if os.path.isfile(marker) else []
        if lines != [merge_head]:
            raise Refuse(f"MERGE_HEAD {lines or 'absent'} does not equal --merge-head {merge_head}")
    busy = operations_in(admin, allow=("MERGE_HEAD",) if merge_head else ())
    if busy:
        raise Refuse(f"operation in progress in the worktree: {', '.join(busy)}")
    status = entries = status_entries(worktree)
    if merge_head:
        entries = [entry for entry in entries if entry[0] == "??"]
        problems = [] if entries else merge_deviations(worktree, head, merge_head, status)
        if problems:
            raise Refuse(f"worktree is not the unmodified merge of {merge_head} into {head}: " + "; ".join(problems))
    if entries:
        kinds = {"untracked": [p for c, p in entries if c == "??"],
                 "conflict": [p for c, p in entries if c in UNMERGED],
                 "staged": [p for c, p in entries if c not in UNMERGED and c[0] not in " ?"],
                 "unstaged": [p for c, p in entries if c not in UNMERGED and c[0] in " ?" and c[1] != " " and c != "??"]}
        raise Refuse("worktree is not clean: " + "; ".join(f"{kind}: {listed(paths)}" for kind, paths in kinds.items() if paths))
    hidden = [line[2:] for line in git(worktree, "ls-files", "-v", "-z").split("\0") if line[:1].islower() or line[:1] == "S"]
    if hidden:
        raise Refuse(f"assume-unchanged or skip-worktree index entries hide edits from git: {listed(hidden)}")


def check_nested(worktree: str, nested: list[str]) -> None:
    for path in nested:
        repo = os.path.join(worktree, path)
        busy = operations_in(git_dir_of(repo))
        if busy:
            raise Refuse(f"nested repository {shown(path)} has an operation in progress: {', '.join(busy)}")
        entries = status_entries(repo)
        if entries:
            raise Refuse(f"nested repository {shown(path)} is not clean: {listed([p for _, p in entries])}")


def ignored_entries(worktree: str, nested: list[str]) -> list[str]:
    result: list[str] = []
    for prefix in ["", *nested]:
        repo = os.path.join(worktree, prefix) if prefix else worktree
        out = git(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z")
        for item in out.split("\0"):
            full = f"{prefix}/{item}" if prefix and item else item
            if item and not any(done.endswith("/") and full.startswith(done) for done in result):
                result.append(full)
    return sorted(result)


def write_manifest(path: str, data: dict) -> str:
    raw = (json.dumps(data, indent=1, sort_keys=True) + "\n").encode("utf-8")
    temporary = f"{path}.tmp-{os.getpid()}"
    try:
        with open(temporary, "xb") as handle:
            handle.write(raw)
        try:
            os.link(temporary, path)  # atomic and exclusive: never a partial or replaced manifest
        except FileExistsError:
            raise Refuse(f"manifest already exists, refusing to replace a baseline: {shown(path)}") from None
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)
    return hashlib.sha256(raw).hexdigest()


def record(args: argparse.Namespace) -> int:
    manifest_path = os.path.abspath(args.manifest)
    if not args.owner:
        raise Refuse("--owner must not be empty")
    if os.path.lexists(manifest_path) or os.path.lexists(removed_marker(manifest_path)):
        raise Refuse(f"manifest already exists, refusing to replace a baseline: {shown(manifest_path)}")
    worktree, root = real(args.worktree), real(args.root)
    if not under(worktree, root):
        raise Refuse(f"{shown(worktree)} is not strictly inside root {shown(root)}")
    ident = identity(worktree)
    repo_common = real(os.path.join(args.repo, git(args.repo, "rev-parse", "--git-common-dir").strip()))
    if repo_common != ident["common"]:
        raise Refuse(f"worktree belongs to {shown(ident['common'])}, not to --repo {shown(repo_common)}")
    admin = ident["admin"]
    manifest_home = real(os.path.dirname(manifest_path))
    if manifest_home == worktree or under(manifest_home, worktree) or manifest_home == admin or under(manifest_home, admin):
        raise Refuse("manifest must live outside the worktree and its admin dir")
    token_path = os.path.join(admin, TOKEN_FILE)
    if os.path.lexists(token_path):
        raise Refuse(f"worktree already has an owner token: {shown(token_path)}")
    head = normalize(args.head, worktree, "--head")
    merge_head = normalize(args.merge_head, worktree, "--merge-head") if args.merge_head else None
    check_clean(worktree, admin, head, merge_head)

    content, scans = capture(worktree, admin)
    check_nested(worktree, scans[0].nested)
    ignored = ignored_entries(worktree, scans[0].nested)
    again = (scan(worktree, hashing=False), scan(admin, hashing=False, inside_git=True, skip_top=frozenset({TOKEN_FILE})))
    changed = signature_changes(scans, again)
    if changed:
        raise Refuse(f"worktree changed while it was being captured: {listed(changed)}")

    token = secrets.token_hex(16)
    created: list[str] = []
    try:
        missing = []
        probe = os.path.dirname(manifest_path)
        while not os.path.isdir(probe):
            missing.append(probe)
            probe = os.path.dirname(probe)
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        created += reversed(missing)  # removed again, deepest first, if anything below fails
        with open(token_path, "x", encoding="utf-8") as handle:
            handle.write(token + "\n")
        created.append(token_path)
        digest = write_manifest(manifest_path, {
            "schema": SCHEMA, "owner": args.owner, "recorded_at": now(), "root": root, "worktree": worktree,
            "common": ident["common"], "admin": admin, "token": token, "head": head, "merge_head": merge_head,
            "content": content,
        })
    except BaseException:
        for path in reversed(created):
            try:
                os.unlink(path) if os.path.isfile(path) else os.rmdir(path)
            except OSError:
                pass
        raise
    for path in ignored:
        print(f"IGNORED {shown(path)}")
    print(f"RECORDED {shown(worktree)} head={head} merge_head={merge_head or '-'} entries={len(content['tree'])} "
          f"index={len(content['git']['index'])} nested={len(content['nested'])} ignored={len(ignored)} "
          f"manifest={shown(manifest_path)} digest={digest}")
    return 0


def check(args: argparse.Namespace) -> int:
    manifest_path = os.path.abspath(args.manifest)
    manifest, digest = load(manifest_path)
    lines, scans, ident = verify(manifest, manifest_path, args.owner)
    parents = deletability(manifest, ident, scans)
    if lines or parents:
        emit(lines + [f"DIFF cannot be removed: {line}" for line in parents])
        return 1
    print(f"OK identical to baseline digest={digest}")
    return 0


def deletability(manifest: dict, ident: dict, scans: tuple[Scan, Scan]) -> list[str]:
    problems = [*scans[0].blockers, *(f"admin dir: {line}" for line in scans[1].blockers)]
    for label, path in (("parent of the worktree", os.path.dirname(manifest["worktree"])),
                        ("parent of the admin dir", os.path.dirname(ident["admin"]))):
        if not os.access(path, os.W_OK | os.X_OK):
            problems.append(f"{label} not writable: {shown(path)}")
    return problems


def remove(args: argparse.Namespace) -> int:
    manifest_path = os.path.abspath(args.manifest)
    worktree = None
    try:
        manifest, digest = load(manifest_path)
        worktree = manifest["worktree"]
        if args.digest.strip().lower() != digest:
            raise Refuse(f"manifest digest {digest} does not equal --digest {args.digest}")
        lines, scans, ident = verify(manifest, manifest_path, args.owner)
        blocked = deletability(manifest, ident, scans)
        if lines or blocked:
            emit(lines + [f"REFUSE not deletable: {line}" for line in blocked])
            raise Refuse("content differs or cannot be deleted")
        again = (scan(worktree, hashing=False),
                 scan(ident["admin"], hashing=False, inside_git=True, skip_top=frozenset({TOKEN_FILE})))
        changed = signature_changes(scans, again)
        if changed:
            raise Refuse(f"worktree changed while it was being verified: {listed(changed)}")
    except (Refuse, OSError) as error:
        print(f"REFUSE {error}")
        print(f"REFUSE nothing removed: {shown(worktree) if worktree else shown(manifest_path)}")
        return 1
    result = run_git(manifest["common"], "worktree", "remove", "--force", worktree)
    registered = f"worktree {worktree}\n" in (git_ok(manifest["common"], "worktree", "list", "--porcelain") or "")
    if result.returncode != 0 or os.path.lexists(worktree) or registered or os.path.lexists(ident["admin"]):
        left = sum(len(dirs) + len(files) for _, dirs, files in os.walk(worktree)) if os.path.isdir(worktree) else 0
        print(f"PARTIAL {shown(worktree)}: git worktree remove exited {result.returncode}: "
              f"{(result.stderr.strip().splitlines() or ['no message'])[-1]}")
        print(f"PARTIAL worktree directory: {'present, ' + str(left) + ' entries left' if os.path.lexists(worktree) else 'gone'}")
        print(f"PARTIAL admin dir: {'present' if os.path.lexists(ident['admin']) else 'gone'}")
        print(f"PARTIAL registered in `git worktree list`: {'yes' if registered else 'no'}")
        return 3
    try:
        with open(removed_marker(manifest_path), "x", encoding="utf-8") as handle:
            json.dump({"removed_at": now(), "worktree": worktree, "digest": digest}, handle)
            handle.write("\n")
    except OSError as error:
        print(f"WARNING removal marker not written ({error}); do not reuse this manifest")
    print(f"REMOVED {shown(worktree)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    rec = commands.add_parser("record")
    rec.add_argument("manifest")
    for flag in ("--repo", "--worktree", "--root", "--owner", "--head"):
        rec.add_argument(flag, required=True)
    rec.add_argument("--merge-head")
    for name in ("check", "remove"):
        sub = commands.add_parser(name)
        sub.add_argument("manifest")
        sub.add_argument("--owner", required=True)
        if name == "remove":
            sub.add_argument("--digest", required=True)
    args = parser.parse_args()
    try:
        return {"record": record, "check": check, "remove": remove}[args.command](args)
    except (Refuse, OSError) as error:
        print(f"REFUSE {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
