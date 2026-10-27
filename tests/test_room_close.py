"""Behavior tests for room-close.py through its CLI, on throwaway repositories and a fake `paseo` CLI."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

CLOSE = pathlib.Path(__file__).resolve().parents[1] / "home" / ".config" / "codex-room" / "tools" / "room-close.py"

# Minimal stand-in for the Paseo CLI calls room-close.py makes; state lives in $FAKE_PASEO_STATE.
FAKE_PASEO = """#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_PASEO_STATE"]
state = json.load(open(path))
args = [a for a in sys.argv[1:] if a not in ("--json", "--background")]
if args == ["workspace", "ls"]:
    print(json.dumps(state["workspaces"]))
elif args == ["project", "ls"]:
    print(json.dumps(state["projects"]))
elif args[:2] == ["workspace", "archive"]:
    state["workspaces"] = [w for w in state["workspaces"] if w["workspaceId"] != args[2]]
    print(json.dumps({"workspaceId": args[2], "status": "archived"}))
elif args[:2] == ["project", "delete"]:
    if not any(p["projectId"] == args[2] for p in state["projects"]):
        sys.exit("project not found")
    state["projects"] = [p for p in state["projects"] if p["projectId"] != args[2]]
    print(json.dumps({"projectId": args[2], "removedWorkspaceIds": []}))
else:
    sys.exit(f"unexpected: {args}")
json.dump(state, open(path, "w"))
"""


class RoomCloseTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="roomclose-")).resolve()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.repo = self.dir / "app"
        self.root = self.dir / ".worktrees"
        self.run_dir = self.dir / "spec" / ".room"
        (self.run_dir / "logs").mkdir(parents=True)
        (self.run_dir / "baseline.json").write_text("{}")
        self.git(self.dir, "init", "-q", "-b", "main", str(self.repo))
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "init")
        self.git(self.repo, "branch", "keep/human")
        self.git(self.repo, "branch", "demo/integration")
        self.integration = self.add_worktree("integration")
        self.state = self.dir / "paseo.json"
        fake = self.dir / "paseo"
        fake.write_text(FAKE_PASEO)
        fake.chmod(0o755)
        self.env = {**os.environ, "PASEO_BIN": str(fake), "FAKE_PASEO_STATE": str(self.state)}
        self.workspaces = [{"workspaceId": "wks_main", "cwd": str(self.repo)},
                           {"workspaceId": "wks_int", "cwd": str(self.integration)}]
        self.projects = [{"projectId": "prj_main", "path": str(self.repo)},
                         {"projectId": "prj_int", "path": str(self.integration)}]

    def git(self, cwd, *args) -> str:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                              env=env).stdout.strip()

    def add_worktree(self, suffix: str, start: str = "main") -> pathlib.Path:
        path = self.root / f"app-demo-{suffix}"
        if suffix == "integration":
            self.git(self.repo, "worktree", "add", "-q", str(path), "demo/integration")
        else:
            self.git(self.repo, "worktree", "add", "-q", "-b", f"demo/{suffix}", str(path), start)
            (path / f"{suffix}.txt").write_text(suffix)
            self.git(path, "add", ".")
            self.git(path, "commit", "-q", "-m", suffix)
        return path

    def merge_into_integration(self, suffix: str) -> None:
        self.git(self.integration, "merge", "-q", "--no-ff", "-m", f"merge {suffix}", f"demo/{suffix}")

    def close(self, *args) -> subprocess.CompletedProcess:
        self.state.write_text(json.dumps({"workspaces": self.workspaces, "projects": self.projects}))
        return subprocess.run([sys.executable, CLOSE, "close", "--slug", "demo", "--repo", self.repo,
                               "--run", self.run_dir, *map(str, args)],
                              capture_output=True, text=True, timeout=60, env=self.env)

    def paseo_state(self) -> dict:
        return json.loads(self.state.read_text())

    def branches(self) -> set[str]:
        return set(self.git(self.repo, "branch", "--format=%(refname:short)").split())

    def test_unmerged_integration_refuses_every_change(self):
        ticket = self.add_worktree("01-a1")
        self.merge_into_integration("01-a1")
        result = self.close("--apply")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("is not merged into main", result.stdout)
        self.assertTrue(self.integration.is_dir() and ticket.is_dir() and self.run_dir.is_dir())
        self.assertEqual(self.branches(), {"main", "keep/human", "demo/integration", "demo/01-a1"})
        self.assertEqual(len(self.paseo_state()["projects"]), 2)

    def test_merged_run_is_removed_and_human_state_kept(self):
        ticket = self.add_worktree("01-a1")
        self.merge_into_integration("01-a1")
        gone = self.add_worktree("02-a1")  # accepted, merged, and already removed by worktree-guard
        self.merge_into_integration("02-a1")
        self.git(self.repo, "worktree", "remove", str(gone))
        (self.repo / ".git" / "info" / "exclude").write_text("build/\n")
        (self.integration / "build").mkdir()  # ignored build output goes with the worktree
        (self.integration / "build" / "out.bin").write_text("x")
        self.git(self.repo, "merge", "-q", "--ff-only", "demo/integration")
        # Same prefix, another slug: not this run's.
        self.git(self.repo, "branch", "demo-x/integration")
        other = self.root / "app-demo-x-integration"
        self.git(self.repo, "worktree", "add", "-q", str(other), "demo-x/integration")
        self.workspaces.append({"workspaceId": "wks_t1", "cwd": str(ticket)})
        self.projects += [{"projectId": "prj_t1", "path": str(ticket)}, {"projectId": "prj_t2", "path": str(gone)},
                          {"projectId": "prj_other", "path": str(other)},
                          {"projectId": "prj_other_gone", "path": str(self.root / "app-demo-x-01-a1")}]

        dry = self.close()
        self.assertEqual(dry.returncode, 0, dry.stdout)
        self.assertTrue(ticket.is_dir() and self.run_dir.is_dir())
        self.assertEqual(len(self.paseo_state()["projects"]), 6)

        result = self.close("--apply")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.integration.exists() or ticket.exists() or self.run_dir.exists())
        self.assertTrue(other.is_dir() and self.repo.is_dir())
        self.assertEqual(self.branches(), {"main", "keep/human", "demo-x/integration"})
        state = self.paseo_state()
        self.assertEqual([w["workspaceId"] for w in state["workspaces"]], ["wks_main"])
        self.assertEqual(sorted(p["projectId"] for p in state["projects"]), ["prj_main", "prj_other", "prj_other_gone"])

    def test_dirty_or_unmerged_work_is_kept_with_its_run(self):
        dirty = self.add_worktree("01-a1")
        self.merge_into_integration("01-a1")
        rejected = self.add_worktree("02-a1")
        self.git(self.repo, "worktree", "remove", str(rejected))
        self.git(self.repo, "merge", "-q", "--ff-only", "demo/integration")
        (dirty / "scratch.txt").write_text("unsaved")
        self.workspaces.append({"workspaceId": "wks_t1", "cwd": str(dirty)})

        result = self.close("--apply")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("not clean", result.stdout)
        self.assertTrue((dirty / "scratch.txt").exists() and self.run_dir.is_dir())
        self.assertEqual(self.branches(), {"main", "keep/human", "demo/01-a1", "demo/02-a1"})
        self.assertIn("wks_t1", [w["workspaceId"] for w in self.paseo_state()["workspaces"]])

        (dirty / "scratch.txt").unlink()
        result = self.close("--apply", "--drop-unmerged")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("demo/02-a1", [line.split()[2] for line in result.stdout.splitlines() if "unmerged" in line])
        self.assertEqual(self.branches(), {"main", "keep/human"})
        self.assertFalse(dirty.exists() or self.run_dir.exists() or self.root.exists())


if __name__ == "__main__":
    unittest.main()
