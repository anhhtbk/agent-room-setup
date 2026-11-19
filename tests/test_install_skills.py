import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-skills"


class InstallSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.lock = {}

    def tearDown(self):
        self.temporary.cleanup()

    def fake(self, name, stdout):
        path = self.bin / name
        path.write_text(f"#!/bin/sh\ncat <<'EOF'\n{stdout}\nEOF\n")
        path.chmod(0o755)
        return str(path)

    def install(self, name, source, claude_link=True):
        skill = self.home / ".agents" / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
        if claude_link:
            link = self.home / ".claude" / "skills" / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(skill)
        self.lock[name] = {"source": source}

    def run_script(self, *arguments, claude="[]", omp="{}"):
        lock = self.home / ".agents" / ".skill-lock.json"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"version": 3, "skills": self.lock}))
        env = {
            **os.environ,
            "HOME": str(self.home),
            "CLAUDE_BIN": self.fake("claude", claude),
            "OMP_BIN": self.fake("omp", omp),
        }
        return subprocess.run([str(SCRIPT), *arguments], env=env, text=True, capture_output=True)

    def install_complete_set(self):
        self.install("tdd", "mattpocock/skills")
        self.install("code-review", "mattpocock/skills")
        self.install("how", "cursor/plugins")
        self.install("grill-with-ui", "jasonku09/grill-with-ui")
        self.install("drawing-excalidraw-figures", "nv-minh/drawing-excalidraw-figures")

    def test_verify_passes_on_complete_shared_install(self):
        self.install_complete_set()
        result = self.run_script("--verify")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SKILLS_VERIFY_OK", result.stdout)

    def test_verify_names_missing_room_skill(self):
        self.install_complete_set()
        (self.home / ".agents/skills/tdd/SKILL.md").unlink()
        result = self.run_script("--verify")
        self.assertEqual(result.returncode, 1)
        self.assertIn("tdd", result.stdout)

    def test_verify_rejects_pstack_owning_a_mattpocock_name(self):
        self.install_complete_set()
        self.install("teach", "cursor/plugins")
        result = self.run_script("--verify")
        self.assertEqual(result.returncode, 1)
        self.assertIn("teach: installed from cursor/plugins", result.stdout)

    def test_verify_requires_claude_link(self):
        self.install_complete_set()
        self.install("why", "cursor/plugins", claude_link=False)
        result = self.run_script("--verify")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no Claude Code link", result.stdout)

    def test_plan_lists_retired_copies_and_keeps_foreign_skill(self):
        self.install("find-skills", "vercel-labs/skills")
        dev = self.home / "dev" / "grill-with-ui"
        dev.mkdir(parents=True)
        (self.home / ".agents/skills/grill-with-ui").symlink_to(dev)
        vendor = self.home / ".omp/vendor/cursor-plugins/harness/pstack/claude-code/skills/how"
        vendor.mkdir(parents=True)
        omp_skills = self.home / ".omp/agent/skills"
        omp_skills.mkdir(parents=True)
        (omp_skills / "how").symlink_to(vendor)
        (omp_skills / "mine").mkdir()
        result = self.run_script(
            "--dry-run",
            claude=json.dumps([{"id": "pstack@cursor-plugins"}, {"id": "sentry@claude-plugins-official"}]),
            omp='{"plugins": {"pstack@cursor-plugins": []}}',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RETIRE    skill         find-skills", result.stdout)
        self.assertIn("RETIRE    claude-plugin pstack@cursor-plugins", result.stdout)
        self.assertNotIn("sentry", result.stdout)
        self.assertIn("RETIRE    omp-plugin    pstack@cursor-plugins", result.stdout)
        self.assertIn("1 links in", result.stdout)
        self.assertIn("keep foreign grill-with-ui", result.stdout)
        self.assertTrue((omp_skills / "how").is_symlink(), "dry-run changed state")


if __name__ == "__main__":
    unittest.main()
