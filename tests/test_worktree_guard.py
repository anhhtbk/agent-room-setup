"""Behavior tests for worktree-guard.py through its CLI, on throwaway repositories."""
import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

GUARD = pathlib.Path(__file__).resolve().parents[1] / "home" / ".config" / "codex-room" / "tools" / "worktree-guard.py"

# Runs the guard in-process with `scan` wrapped, to land a write between the hash pass and the final lstat pass.
LATE_WRITE = """
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location("guard", sys.argv[1])
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
real_scan, seen, late = guard.scan, [], sys.argv[2]
def scan(root, hashing, *args, **kwargs):
    if not hashing and not seen:
        seen.append(1)
        pathlib.Path(late).write_text("late edit\\n")
    return real_scan(root, hashing, *args, **kwargs)
guard.scan = scan
sys.argv = ["worktree-guard.py", *sys.argv[3:]]
sys.exit(guard.main())
"""


class Fixture:
    """Main repo with a submodule `sm`, a clean linked worktree holding an initialised submodule, an embedded
    clone in an ignored dir and ignored build output, plus a sibling worktree that belongs to someone else."""

    def __init__(self, base: pathlib.Path):
        self.base = base
        self.env = {
            **os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(base / "gitconfig"),
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        }
        (base / "gitconfig").write_text("[protocol \"file\"]\n\tallow = always\n[init]\n\tdefaultBranch = main\n")
        self.sub, self.repo = base / "sub", base / "repo"
        self.root = base / "local-merges" / "run-1"
        self.wt, self.other = self.root / "mod-mr-1", self.root / "mod-mr-2"
        self.manifest = base / ".state" / "worktree-baselines" / "run-1" / "mod-mr-1.json"
        self.digest = ""
        self.git(base, "init", "-q", str(self.sub))
        for number in (1, 2):
            self.write(self.sub / "s.txt", f"sub {number}\n")
            self.git(self.sub, "add", "s.txt")
            self.git(self.sub, "commit", "-qm", f"sub {number}")
        self.git(base, "init", "-q", str(self.repo))
        self.write(self.repo / "a.txt", "base\n")
        self.write(self.repo / "keep.txt", "keep\n")
        self.write(self.repo / ".gitignore", "bin/\nclones/\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "base")
        self.git(self.repo, "submodule", "add", "-q", str(self.sub), "sm")
        self.git(self.repo, "commit", "-qm", "sm")
        self.git(self.repo, "checkout", "-qb", "feature")
        self.write(self.repo / "a.txt", "feature\n")
        self.git(self.repo, "commit", "-qam", "feature")
        self.git(self.repo, "checkout", "-q", "main")
        self.write(self.repo / "a.txt", "target\n")
        self.git(self.repo, "commit", "-qam", "target")
        self.write(self.repo / "main-dirty.txt", "human work in main checkout\n")
        self.root.mkdir(parents=True)
        for path in (self.wt, self.other):
            self.git(self.repo, "worktree", "add", "-q", "--detach", str(path), "main")
        self.git(self.wt, "submodule", "update", "--init", "-q")
        self.git(self.wt, "clone", "-q", str(self.sub), "clones/c")
        self.write(self.wt / "bin" / "out.dll", "build output\n")
        self.write(self.other / "theirs.txt", "someone else's work\n")

    @staticmethod
    def write(path: pathlib.Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def git(self, cwd: pathlib.Path, *args: str) -> str:
        return subprocess.run(["git", "-C", str(cwd), *args], env=self.env, check=True,
                              capture_output=True, text=True).stdout

    def git_dir(self, repo: pathlib.Path) -> pathlib.Path:
        return pathlib.Path(self.git(repo, "rev-parse", "--absolute-git-dir").strip())

    def head(self, repo=None) -> str:
        return self.git(repo or self.wt, "rev-parse", "HEAD").strip()

    def start_merge(self) -> None:
        subprocess.run(["git", "-C", str(self.wt), "merge", "--no-ff", "--no-commit", "feature"],
                       env=self.env, capture_output=True)

    def guard(self, *args, env=None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(GUARD), *map(str, args)], env={**self.env, **(env or {})},
                              capture_output=True, text=True)

    def record(self, worktree=None, root=None, repo=None, manifest=None, head=None, merge_head=None,
               env=None) -> subprocess.CompletedProcess:
        worktree = worktree or self.wt
        args = ["record", manifest or self.manifest, "--repo", repo or self.repo, "--worktree", worktree,
                "--root", root or self.root, "--owner", "run-1", "--head", head or self.head(worktree)]
        if merge_head:
            args += ["--merge-head", merge_head]
        return self.guard(*args, env=env)

    def recorded(self, **kwargs) -> subprocess.CompletedProcess:
        result = self.record(**kwargs)
        assert result.returncode == 0, result.stdout + result.stderr
        self.digest = re.search(r"digest=([0-9a-f]{64})", result.stdout).group(1)
        return result

    def check(self, owner: str = "run-1") -> subprocess.CompletedProcess:
        return self.guard("check", self.manifest, "--owner", owner)

    def remove(self, owner: str = "run-1", digest=None, env=None) -> subprocess.CompletedProcess:
        return self.guard("remove", self.manifest, "--owner", owner, "--digest", digest or self.digest, env=env)

    def listed(self) -> str:
        return self.git(self.repo, "worktree", "list", "--porcelain")

    def token(self) -> pathlib.Path:
        return self.git_dir(self.wt) / "codex-room-owner"


class GuardCase(unittest.TestCase):
    def setUp(self):
        self.f = self.fresh()

    def fresh(self) -> Fixture:
        base = pathlib.Path(tempfile.mkdtemp(prefix="wtguard-")).resolve()
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        return Fixture(base)

    def assert_neighbours_untouched(self, f=None):
        f = f or self.f
        self.assertEqual((f.other / "theirs.txt").read_text(), "someone else's work\n")
        self.assertEqual((f.repo / "main-dirty.txt").read_text(), "human work in main checkout\n")
        self.assertEqual(f.git(f.repo, "branch", "--show-current").strip(), "main")
        self.assertIn(f"worktree {f.other}\n", f.listed())

    def assert_refused_and_kept(self, result, f=None):
        f = f or self.f
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("REFUSE", result.stdout)
        self.assertNotIn("PARTIAL", result.stdout)
        self.assertTrue(f.wt.is_dir())
        self.assertIn(f"worktree {f.wt}\n", f.listed())
        self.assert_neighbours_untouched(f)

    def assert_nothing_left_by_record(self, result, f=None):
        f = f or self.f
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("REFUSE", result.stdout)
        self.assertFalse(f.manifest.exists(), "refused record must leave no manifest")
        self.assertFalse(f.token().exists(), "refused record must leave no owner token")
        self.assertFalse(f.manifest.parent.exists(), "refused record must not create directories")


class RecordTest(GuardCase):
    def test_success_reports_digest_of_manifest_bytes_and_ignored_entries(self):
        f = self.f
        result = f.recorded()
        self.assertEqual(f.digest, hashlib.sha256(f.manifest.read_bytes()).hexdigest())
        self.assertEqual(sorted(line for line in result.stdout.splitlines() if line.startswith("IGNORED")),
                         ["IGNORED bin/", "IGNORED clones/"])
        self.assertTrue(f.token().is_file())
        ok = f.check()
        self.assertEqual(ok.stdout.strip(), f"OK identical to baseline digest={f.digest}")

    def test_refuses_dirty_or_unsafe_worktrees_and_leaves_nothing(self):
        def stage_edit(f):
            f.write(f.wt / "keep.txt", "staged\n")
            f.git(f.wt, "add", "keep.txt")

        def sm_staged(f):
            f.write(f.wt / "sm" / "new.txt", "x\n")
            f.git(f.wt / "sm", "add", "new.txt")

        def clone_staged(f):
            f.write(f.wt / "clones" / "c" / "new.txt", "x\n")
            f.git(f.wt / "clones" / "c", "add", "new.txt")

        def clone_operation(f):
            clone = f.wt / "clones" / "c"
            f.write(clone / ".git" / "CHERRY_PICK_HEAD", f.head(clone) + "\n")

        def assume_unchanged(f):
            f.git(f.wt, "update-index", "--assume-unchanged", "keep.txt")
            f.write(f.wt / "keep.txt", "hidden edit\n")

        def skip_worktree(f):
            f.git(f.wt, "update-index", "--skip-worktree", "keep.txt")
            f.write(f.wt / "keep.txt", "hidden edit\n")

        cases = {
            "unstaged": (lambda f: f.write(f.wt / "keep.txt", "edit\n"), {}),
            "staged": (stage_edit, {}),
            "deleted tracked": (lambda f: (f.wt / "keep.txt").unlink(), {}),
            "mode change": (lambda f: os.chmod(f.wt / "keep.txt", 0o755), {}),
            "untracked": (lambda f: f.write(f.wt / "notes.md", "n\n"), {}),
            "assume-unchanged hides an edit": (assume_unchanged, {}),
            "skip-worktree hides an edit": (skip_worktree, {}),
            "submodule untracked": (lambda f: f.write(f.wt / "sm" / "scratch.txt", "x\n"), {}),
            "submodule staged": (sm_staged, {}),
            "submodule modified": (lambda f: f.write(f.wt / "sm" / "s.txt", "edit\n"), {}),
            "submodule commit": (lambda f: (f.write(f.wt / "sm" / "s.txt", "w\n"),
                                            f.git(f.wt / "sm", "commit", "-qam", "w")), {}),
            "nested clone untracked": (lambda f: f.write(f.wt / "clones" / "c" / "scratch.txt", "x\n"), {}),
            "nested clone staged": (clone_staged, {}),
            "nested clone operation": (clone_operation, {}),
            "merge in progress without --merge-head": (lambda f: f.start_merge(), {}),
            "bisect state": (lambda f: f.write(f.git_dir(f.wt) / "BISECT_LOG", "git bisect start\n"), {}),
            "index.lock": (lambda f: f.write(f.git_dir(f.wt) / "index.lock", ""), {}),
            "nested .git is a symlink": (lambda f: (os.makedirs(f.wt / "clones" / "e"),
                                                    os.symlink("../c/.git", f.wt / "clones" / "e" / ".git")), None),
            "HEAD mismatch": (lambda f: None, lambda f: {"head": f.git(f.wt, "rev-parse", "HEAD~1").strip()}),
            "HEAD not a commit": (lambda f: None, lambda f: {"head": "deadbeef"}),
            "head given as a branch name": (lambda f: None, lambda f: {"head": "main"}),
            "locked": (lambda f: f.git(f.repo, "worktree", "lock", str(f.wt)), None),
            "main worktree": (lambda f: None, lambda f: {"worktree": f.repo, "root": f.base, "head": f.head(f.repo)}),
            "outside root": (lambda f: None, lambda f: {"root": f.base / "elsewhere"}),
            "root itself": (lambda f: None, lambda f: {"worktree": f.root, "root": f.root, "head": f.head()}),
            "other repository": (lambda f: None, lambda f: {"repo": f.sub}),
            "manifest inside the worktree": (lambda f: None, lambda f: {"manifest": f.wt / "baseline.json"}),
        }
        for label, (mutate, arguments) in cases.items():
            with self.subTest(label):
                f = self.fresh()
                mutate(f)
                kwargs = arguments(f) if arguments else {}
                result = f.record(**kwargs)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("REFUSE", result.stdout)
                self.assertFalse(kwargs.get("manifest", f.manifest).exists())
                self.assertFalse(f.token().exists(), "refused record must leave no owner token")
                self.assertFalse(f.manifest.parent.exists(), "refused record must not create directories")

    def test_failed_record_does_not_block_a_later_record(self):
        f = self.f
        self.assert_nothing_left_by_record(f.record(head=f.git(f.wt, "rev-parse", "HEAD~1").strip()))
        self.assertEqual(f.record().returncode, 0)

    def test_record_failing_after_capture_removes_its_token(self):
        f = self.f
        f.base.joinpath(".state").write_text("a file where the manifest directory must go\n")
        result = f.record()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse(f.token().exists())

    def test_refuses_to_replace_an_existing_baseline(self):
        f = self.f
        f.recorded()
        again = f.record()
        self.assertEqual(again.returncode, 1)
        self.assertIn("manifest already exists", again.stdout)
        self.assertEqual(f.digest, hashlib.sha256(f.manifest.read_bytes()).hexdigest())

    def test_write_landing_during_capture_refuses_record_and_leaves_nothing(self):
        f = self.f
        late = f.wt / "bin" / "late.txt"
        result = subprocess.run(
            [sys.executable, "-c", LATE_WRITE, str(GUARD), str(late), "record", str(f.manifest), "--repo", str(f.repo),
             "--worktree", str(f.wt), "--root", str(f.root), "--owner", "run-1", "--head", f.head()],
            env=f.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("changed while it was being captured", result.stdout)
        self.assertFalse(f.manifest.exists())
        self.assertFalse(f.token().exists())


class MergeHeadTest(GuardCase):
    def setUp(self):
        super().setUp()
        self.f.start_merge()
        self.feature = self.f.git(self.f.repo, "rev-parse", "feature").strip()

    def test_conflicted_merge_is_recorded_and_unchanged_merge_is_removed(self):
        f = self.f
        result = f.recorded(merge_head=self.feature)
        self.assertIn(f"merge_head={self.feature}", result.stdout)
        self.assertIn("<<<<<<<", (f.wt / "a.txt").read_text())
        self.assertEqual(f.check().returncode, 0)
        removed = f.remove()
        self.assertEqual(removed.returncode, 0, removed.stdout)
        self.assertFalse(f.wt.exists())
        self.assert_neighbours_untouched()

    def test_later_edits_to_the_merge_state_are_detected(self):
        mutations = {
            "hand-resolved working bytes": lambda f: f.write(f.wt / "a.txt", "resolved by hand\n"),
            "resolution staged": lambda f: (f.write(f.wt / "a.txt", "resolved\n"), f.git(f.wt, "add", "a.txt")),
            "merge aborted": lambda f: f.git(f.wt, "merge", "--abort"),
            "untracked file": lambda f: f.write(f.wt / "notes.md", "n\n"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label):
                f = self.fresh()
                f.start_merge()
                f.recorded(merge_head=f.git(f.repo, "rev-parse", "feature").strip())
                mutate(f)
                self.assertEqual(f.check().returncode, 1)
                self.assert_refused_and_kept(f.remove(), f)

    def test_refusals(self):
        f = self.f
        main = f.git(f.repo, "rev-parse", "main").strip()
        self.assert_nothing_left_by_record(f.record(merge_head=main))
        f.write(f.wt / "notes.md", "untracked\n")
        self.assert_nothing_left_by_record(f.record(merge_head=self.feature))
        (f.wt / "notes.md").unlink()
        f.write(f.git_dir(f.wt) / "CHERRY_PICK_HEAD", main + "\n")
        self.assert_nothing_left_by_record(f.record(merge_head=self.feature))
        (f.git_dir(f.wt) / "CHERRY_PICK_HEAD").unlink()
        f.git(f.wt, "merge", "--abort")
        self.assert_nothing_left_by_record(f.record(merge_head=self.feature))

    def test_refuses_tracked_changes_that_are_not_the_merge(self):
        def unstaged(f):
            (f.wt / "keep.txt").write_text("someone else\n")

        def staged(f):
            unstaged(f)
            f.git(f.wt, "add", "keep.txt")

        def staged_deletion(f):
            f.git(f.wt, "rm", "-q", "keep.txt")

        def staged_extra_file(f):
            f.write(f.wt / "extra.txt", "extra\n")
            f.git(f.wt, "add", "extra.txt")

        def hand_edit_in_conflict_bytes(f):
            text = (f.wt / "a.txt").read_text()
            self.assertIn("target\n", text)
            (f.wt / "a.txt").write_text(text.replace("target\n", "target, edited\n"))

        def conflict_resolved_and_staged(f):
            f.write(f.wt / "a.txt", "resolved\n")
            f.git(f.wt, "add", "a.txt")

        def conflict_stage_replaced(f):
            f.git(f.wt, "update-index", "--force-remove", "a.txt")
            f.write(f.wt / "a.txt", "feature\n")
            f.git(f.wt, "add", "a.txt")

        def conflict_file_deleted(f):
            (f.wt / "a.txt").unlink()

        def skip_worktree(f):
            f.git(f.wt, "update-index", "--skip-worktree", "keep.txt")
            unstaged(f)

        cases = {
            "unstaged edit of an unrelated tracked file": unstaged,
            "staged edit of an unrelated tracked file": staged,
            "staged deletion of an unrelated tracked file": staged_deletion,
            "staged extra file": staged_extra_file,
            "hand edit of the conflicted working bytes": hand_edit_in_conflict_bytes,
            "conflict resolved and staged": conflict_resolved_and_staged,
            "conflict stages replaced": conflict_stage_replaced,
            "conflicted working file deleted": conflict_file_deleted,
            "skip-worktree edit": skip_worktree,
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                f = self.fresh()
                f.start_merge()
                mutate(f)
                self.assert_nothing_left_by_record(f.record(merge_head=f.git(f.repo, "rev-parse", "feature").strip()), f)

    def test_clean_merge_is_recorded_and_hand_edits_of_merged_files_are_refused(self):
        def side_merge(f):
            f.git(f.repo, "branch", "side", "main~1")
            f.git(f.repo, "checkout", "-q", "side")
            f.write(f.repo / "side.txt", "side\n")
            f.write(f.repo / "keep.txt", "keep, side edit\n")
            f.git(f.repo, "add", ".")
            f.git(f.repo, "commit", "-qm", "side")
            f.git(f.repo, "checkout", "-q", "main")
            f.git(f.wt, "merge", "--no-ff", "--no-commit", "side")
            return f.git(f.repo, "rev-parse", "side").strip()

        f = self.fresh()
        side = side_merge(f)
        self.assertEqual(f.git(f.wt, "ls-files", "-u"), "")
        self.assertEqual(f.recorded(merge_head=side).returncode, 0)
        self.assertEqual(f.check().returncode, 0)
        self.assertEqual(f.remove().returncode, 0)
        for label, mutate in {
            "hand edit of a file the merge added": lambda f: (f.wt / "side.txt").write_text("edited\n"),
            "hand edit of a file the merge changed": lambda f: (f.wt / "keep.txt").write_text("edited\n"),
            "staged hand edit of a merged file": lambda f: (f.write(f.wt / "side.txt", "edited\n"),
                                                            f.git(f.wt, "add", "side.txt")),
            "merged file deleted": lambda f: (f.wt / "side.txt").unlink(),
        }.items():
            with self.subTest(label):
                f = self.fresh()
                side = side_merge(f)
                mutate(f)
                self.assert_nothing_left_by_record(f.record(merge_head=side), f)

    def test_merge_that_moves_a_submodule_pointer_is_recorded(self):
        f = self.fresh()
        f.git(f.repo, "checkout", "-q", "-b", "bump", "main")
        f.git(f.repo / "sm", "checkout", "-q", "HEAD~1")
        f.git(f.repo, "add", "sm")
        f.git(f.repo, "commit", "-qm", "bump")
        f.git(f.repo, "checkout", "-q", "main")
        f.git(f.repo / "sm", "checkout", "-q", "-")
        f.git(f.wt, "merge", "--no-ff", "--no-commit", "bump")
        self.assertIn("sm", f.git(f.wt, "diff", "--cached", "--name-only"))
        self.assertEqual(f.recorded(merge_head=f.git(f.repo, "rev-parse", "bump").strip()).returncode, 0)


class RemoveTest(GuardCase):
    def test_removes_only_own_unchanged_worktree_and_keeps_the_manifest_valid(self):
        f = self.f
        f.recorded()
        before = f.manifest.read_bytes()
        admin = f.git_dir(f.wt)
        result = f.remove()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"REMOVED {f.wt}", result.stdout)
        self.assertFalse(f.wt.exists())
        self.assertFalse(admin.exists())
        self.assertNotIn(f"worktree {f.wt}\n", f.listed())
        self.assertTrue(f.root.is_dir())
        self.assert_neighbours_untouched()
        self.assertEqual(f.manifest.read_bytes(), before)
        self.assertTrue(pathlib.Path(f"{f.manifest}.removed").is_file())
        again = f.remove()
        self.assertEqual(again.returncode, 1)
        self.assertIn("already marked removed", again.stdout)

    def test_refuses_wrong_digest_owner_or_manifest(self):
        f = self.f
        self.assert_refused_and_kept(f.remove(digest="0" * 64))  # never recorded
        f.recorded()
        self.assert_refused_and_kept(f.remove(digest="0" * 64))
        self.assert_refused_and_kept(f.remove(owner="run-2"))
        self.assert_refused_and_kept(f.remove(digest="not-a-digest"))
        self.assertEqual(f.remove().returncode, 0)

    def test_tampered_manifest_is_refused_even_with_a_recomputed_digest(self):
        f = self.f
        f.recorded()
        manifest = json.loads(f.manifest.read_text())
        manifest["worktree"] = str(f.other)
        f.manifest.write_text(json.dumps(manifest))
        self.assert_refused_and_kept(f.remove())  # old digest
        self.assert_refused_and_kept(f.remove(digest=hashlib.sha256(f.manifest.read_bytes()).hexdigest()))
        self.assertTrue((f.other / "theirs.txt").exists())

    def test_refuses_recreated_worktree_at_same_path(self):
        f = self.f
        f.recorded()
        f.git(f.repo, "worktree", "remove", "--force", str(f.wt))
        f.git(f.repo, "worktree", "add", "-q", "--detach", str(f.wt), "main")
        result = f.remove()
        self.assert_refused_and_kept(result)
        self.assertIn("owner token", result.stdout)

    def test_refuses_every_content_change_and_preserves_it(self):
        def stage_new_content(f):
            f.write(f.wt / "keep.txt", "staged edit\n")
            f.git(f.wt, "add", "keep.txt")
            f.write(f.wt / "keep.txt", "keep\n")  # working bytes back to baseline, index differs

        def sm_update_after_commit(f):
            f.write(f.wt / "sm" / "s.txt", "work\n")
            f.git(f.wt / "sm", "commit", "-qam", "work reachable only by reflog afterwards")
            f.git(f.wt, "submodule", "update", "-q")

        def sm_checkout_away_and_back(f):
            original = f.head(f.wt / "sm")
            f.git(f.wt / "sm", "checkout", "-q", "HEAD~1")
            f.git(f.wt / "sm", "checkout", "-q", original)

        def clone_reset(f):
            clone = f.wt / "clones" / "c"
            f.write(clone / "s.txt", "clone work\n")
            f.git(clone, "commit", "-qam", "clone work")
            f.git(clone, "reset", "-q", "--hard", "HEAD~1")

        def head_reflog(f):
            original = f.head()
            f.git(f.wt, "checkout", "-q", "--detach", "HEAD~1")
            f.git(f.wt, "checkout", "-q", "--detach", original)

        def sm_hook(f):
            f.write(f.git_dir(f.wt / "sm") / "hooks" / "post-commit", "#!/bin/sh\nexit 0\n")

        mutations = {
            "staged": (stage_new_content, None),
            "unstaged": (lambda f: f.write(f.wt / "keep.txt", "unstaged edit\n"), "keep.txt"),
            "deleted tracked file": (lambda f: (f.wt / "keep.txt").unlink(), None),
            "untracked file": (lambda f: f.write(f.wt / "notes.md", "new note\n"), "notes.md"),
            "new ignored file": (lambda f: f.write(f.wt / "bin" / "debug.log", "kept log\n"), "bin/debug.log"),
            "changed ignored file": (lambda f: f.write(f.wt / "bin" / "out.dll", "rebuilt\n"), "bin/out.dll"),
            "ignored symlink": (lambda f: os.symlink("keep.txt", f.wt / "bin" / "link"), None),
            "mode change": (lambda f: os.chmod(f.wt / "keep.txt", 0o755), None),
            "commit in worktree": (lambda f: (f.write(f.wt / "keep.txt", "c\n"),
                                              f.git(f.wt, "commit", "-qam", "user commit")), None),
            "HEAD reflog only": (head_reflog, None),
            "admin dir file": (lambda f: f.write(f.git_dir(f.wt) / "notes", "x\n"), None),
            "submodule commit": (lambda f: (f.write(f.wt / "sm" / "s.txt", "sub work\n"),
                                            f.git(f.wt / "sm", "commit", "-qam", "sub work")), None),
            "submodule staged": (lambda f: (f.write(f.wt / "sm" / "new.txt", "x\n"),
                                            f.git(f.wt / "sm", "add", "new.txt")), "sm/new.txt"),
            "submodule untracked": (lambda f: f.write(f.wt / "sm" / "scratch.txt", "x\n"), "sm/scratch.txt"),
            "submodule commit then `submodule update`": (sm_update_after_commit, None),
            "submodule checkout away and back": (sm_checkout_away_and_back, None),
            "submodule config": (lambda f: f.git(f.wt / "sm", "config", "x.y", "z"), None),
            "submodule hook": (sm_hook, None),
            "nested clone commit then reset --hard": (clone_reset, None),
            "nested clone config": (lambda f: f.git(f.wt / "clones" / "c", "config", "x.y", "z"), None),
            "nested clone hook": (lambda f: f.write(f.wt / "clones" / "c" / ".git" / "hooks" / "pre-push",
                                                    "#!/bin/sh\nexit 0\n"), None),
            "nested clone stash": (lambda f: (f.write(f.wt / "clones" / "c" / "s.txt", "w\n"),
                                              f.git(f.wt / "clones" / "c", "stash", "-q")), None),
            "nested repository added": (lambda f: f.git(f.wt, "init", "-q", "clones/d"), None),
        }
        for label, (mutate, kept_path) in mutations.items():
            with self.subTest(label):
                f = self.fresh()
                f.recorded()
                mutate(f)
                expected = (f.wt / kept_path).read_bytes() if kept_path else None
                checked = f.check()
                self.assertEqual(checked.returncode, 1, checked.stdout)
                self.assertIn("DIFF", checked.stdout)
                self.assert_refused_and_kept(f.remove(), f)
                if kept_path:
                    self.assertEqual((f.wt / kept_path).read_bytes(), expected)

    def test_check_names_the_nested_git_dir_file_that_changed(self):
        f = self.f
        f.recorded()
        f.git(f.wt / "sm", "config", "x.y", "z")
        self.assertRegex(f.check().stdout, r"DIFF admin changed: modules/sm/config")
        f.git(f.wt / "clones" / "c", "config", "x.y", "z")
        self.assertIn("DIFF file changed: clones/c/.git/config", f.check().stdout)

    def test_write_after_hash_pass_is_caught_by_the_final_stat_pass(self):
        f = self.f
        f.recorded()
        late = f.wt / "bin" / "late.txt"
        result = subprocess.run(
            [sys.executable, "-c", LATE_WRITE, str(GUARD), str(late), "remove", str(f.manifest), "--owner", "run-1",
             "--digest", f.digest], env=f.env, capture_output=True, text=True)
        self.assert_refused_and_kept(result)
        self.assertIn("changed while it was being verified", result.stdout)
        self.assertEqual(late.read_text(), "late edit\n")

    def test_undeletable_directory_is_refused_before_git_runs(self):
        f = self.f
        f.recorded()
        locked = f.wt / "bin"
        os.chmod(locked, 0o555)
        try:
            self.assertEqual(f.check().returncode, 1)
            result = f.remove()
            self.assert_refused_and_kept(result)
            self.assertIn("not deletable", result.stdout)
            self.assertIn("nothing removed", result.stdout)
            self.assertEqual((locked / "out.dll").read_text(), "build output\n")
        finally:
            os.chmod(locked, 0o755)
        self.assertEqual(f.remove().returncode, 0)

    @unittest.skipUnless(hasattr(os, "chflags"), "file flags are BSD/macOS")
    def test_immutable_file_is_refused_before_git_runs(self):
        f = self.f
        f.recorded()
        target = f.wt / "bin" / "out.dll"
        os.chflags(target, stat.UF_IMMUTABLE)
        try:
            result = f.remove()
            self.assert_refused_and_kept(result)
            self.assertIn("immutable", result.stdout)
        finally:
            os.chflags(target, 0)
        self.assertEqual(f.remove().returncode, 0)

    def test_git_failing_midway_is_reported_as_partial_not_refuse(self):
        f = self.f
        f.recorded()
        shims = f.base / "shims"
        shims.mkdir()
        real_git = shutil.which("git")
        shim = shims / "git"
        shim.write_text(f"""#!/bin/sh
case " $* " in
  *" worktree remove "*) rm -rf "{f.wt}/bin"; echo "error: simulated failure" >&2; exit 1;;
esac
exec {real_git} "$@"
""")
        shim.chmod(0o755)
        result = f.remove(env={"PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"})
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("PARTIAL", result.stdout)
        self.assertIn("simulated failure", result.stdout)
        self.assertIn("worktree directory: present", result.stdout)
        self.assertIn("admin dir: present", result.stdout)
        self.assertIn("registered in `git worktree list`: yes", result.stdout)
        self.assertNotIn("REFUSE", result.stdout)
        self.assertFalse(pathlib.Path(f"{f.manifest}.removed").exists())
        self.assertFalse((f.wt / "bin").exists(), "the shim removed it; the report must not claim otherwise")
        self.assert_neighbours_untouched()


if __name__ == "__main__":
    unittest.main()
