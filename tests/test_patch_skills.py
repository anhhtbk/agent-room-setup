"""Behavior tests for scripts/patch-skills through its CLI, on a throwaway HOME."""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "patch-skills"
PATCHES = REPO / "skill-patches"


def upstream_text(skill: str) -> str:
    """Rebuild an upstream-shaped SKILL.md: every old hunk, separated by filler."""
    parts = ["---\nname: %s\n---\n\nIntro.\n" % skill]
    for old_file in sorted((PATCHES / skill).glob("*.old.txt")):
        parts.append(old_file.read_text())
        parts.append("\nFiller between hunks.\n")
    return "".join(parts)


class PatchSkillsTest(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp(prefix="patchskills-")).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.skills = sorted(p.name for p in PATCHES.iterdir() if p.is_dir())

    def run_cli(self, *args):
        env = {**os.environ, "HOME": str(self.home)}
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True)

    def install(self, skill, text, root=".agents/skills"):
        path = self.home / root / skill / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_dry_run_changes_nothing(self):
        paths = {s: self.install(s, upstream_text(s)) for s in self.skills}
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DRY_RUN", result.stdout)
        for skill, path in paths.items():
            self.assertEqual(path.read_text(), upstream_text(skill))

    def test_apply_patches_then_is_idempotent(self):
        paths = {s: self.install(s, upstream_text(s)) for s in self.skills}
        result = self.run_cli("--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for skill, path in paths.items():
            text = path.read_text()
            for old_file in (PATCHES / skill).glob("*.old.txt"):
                self.assertNotIn(old_file.read_text(), text)
        self.assertTrue(any((self.home / ".codex-room-backups").rglob("SKILL.md")))
        snapshot = {s: p.read_text() for s, p in paths.items()}
        again = self.run_cli("--apply")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertNotIn("PATCHED", again.stdout)
        self.assertEqual({s: p.read_text() for s, p in paths.items()}, snapshot)

    def test_symlinked_skill_is_patched_once(self):
        skill = self.skills[0]
        real = self.install(skill, upstream_text(skill))
        link = self.home / ".claude/skills" / skill
        link.parent.mkdir(parents=True)
        link.symlink_to(real.parent)
        result = self.run_cli("--apply")
        self.assertEqual(result.stdout.count(f"PATCHED    {skill} "), 1, result.stdout)

    def test_changed_upstream_is_stale_and_untouched(self):
        skill = self.skills[0]
        text = upstream_text(skill).replace((PATCHES / skill / "01.old.txt").read_text(), "rewritten upstream\n")
        path = self.install(skill, text)
        result = self.run_cli("--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("STALE", result.stdout)
        self.assertEqual(path.read_text(), text)

    def test_missing_skill_is_skipped(self):
        result = self.run_cli("--apply")
        self.assertEqual(result.returncode, 0)
        self.assertIn("SKIP", result.stdout)


if __name__ == "__main__":
    unittest.main()
