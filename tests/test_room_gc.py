"""Behavior tests for room-gc.py through its CLI, on run directories and processes the test creates."""
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "home" / ".config" / "codex-room" / "tools"
GC = TOOLS / "room-gc.py"
RUN_PROCS = TOOLS / "run-procs.py"


class RoomGcTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="roomgc-")).resolve()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.run_dir = self.dir / "spec" / ".room"
        self.cache = self.run_dir / "cache"
        for entry in ("cand-a", "cand-b"):
            (self.cache / entry / "build").mkdir(parents=True)
            (self.cache / entry / "build" / "out.bin").write_bytes(b"x" * 4096)
        (self.run_dir / "logs").mkdir()
        (self.run_dir / "logs" / "gate.log").write_text("evidence\n")
        (self.run_dir / "baseline.json").write_text("{}\n")
        self.addCleanup(self.kill_registered)

    def kill_registered(self):
        for path in (self.run_dir / "procs").rglob("*.json"):
            try:
                os.killpg(json.loads(path.read_text())["pgid"], signal.SIGKILL)
            except (OSError, ValueError, KeyError):
                pass

    def gc(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, GC, *map(str, args)], capture_output=True, text=True, timeout=60)

    def start(self, registry: str, *command: str) -> pathlib.Path:
        folder = self.run_dir / "procs" / registry
        result = subprocess.run([sys.executable, RUN_PROCS, "start", folder, "--log", self.dir / f"{registry}.log",
                                 "--", *command], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return folder

    def stop(self, folder: pathlib.Path) -> None:
        result = subprocess.run([sys.executable, RUN_PROCS, "stop", folder, "--grace", "1"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dry_run_keeps_everything(self):
        result = self.gc("clean", self.run_dir)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"WOULD-REMOVE {self.cache}", result.stdout)
        self.assertTrue((self.cache / "cand-a" / "build" / "out.bin").exists())

    def test_live_process_refuses_whole_cache_until_stopped(self):
        folder = self.start("01-a1", "/bin/sleep", "300")
        refused = self.gc("clean", self.run_dir, "--apply")
        self.assertEqual(refused.returncode, 1, refused.stdout)
        self.assertIn("REFUSE", refused.stdout)
        self.assertTrue(self.cache.exists())

        self.stop(folder)
        cleaned = self.gc("clean", self.run_dir, "--apply")
        self.assertEqual(cleaned.returncode, 0, cleaned.stdout)
        self.assertFalse(self.cache.exists())
        self.assertEqual((self.run_dir / "logs" / "gate.log").read_text(), "evidence\n")
        self.assertTrue((self.run_dir / "baseline.json").exists())

    def test_entry_is_refused_only_by_a_process_that_uses_it(self):
        self.start("01-a2", "/bin/sh", "-c", "sleep 300", "--instance", "cand-b")
        free = self.gc("clean", self.run_dir, "--entry", "cand-a", "--apply")
        self.assertEqual(free.returncode, 0, free.stdout)
        self.assertFalse((self.cache / "cand-a").exists())

        busy = self.gc("clean", self.run_dir, "--entry", "cand-b", "--apply")
        self.assertEqual(busy.returncode, 1, busy.stdout)
        self.assertTrue((self.cache / "cand-b" / "build" / "out.bin").exists())

    def test_symlinked_entry_and_escaping_names_are_refused(self):
        outside = self.dir / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep\n")
        (self.cache / "link").symlink_to(outside)
        for entry in ("link", "../logs"):
            result = self.gc("clean", self.run_dir, "--entry", entry, "--apply")
            self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue((outside / "keep.txt").exists())
        self.assertTrue((self.run_dir / "logs" / "gate.log").exists())

    def test_report_finds_run_directories_below_a_parent(self):
        result = self.gc("report", self.dir)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"RUN {self.run_dir} ", result.stdout)
        self.assertIn("CACHE cand-a ", result.stdout)


if __name__ == "__main__":
    unittest.main()
