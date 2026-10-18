"""Release selection and the one-time, transaction-owned fork migration."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_setup

ROOT = Path(__file__).resolve().parents[1]
OLD_FORK = "8511089eaeb06cddd049b629562926822020de5c"


class PaseoReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixtures = test_setup.SetupShapeTests()
        self.remote, self.first, self.release = self.fixtures.make_paseo_remote(self.root)
        self.npm = self.fixtures.fake_npm(self.root)
        self.target = self.root / "checkout"
        self.env = self.fixtures.paseo_env(self.root / "home", self.remote, self.target, self.npm)

    def git(self, repo, *args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    def run_helper(self, *args, helper=None, **env):
        return subprocess.run([str(helper or ROOT / "scripts/install-paseo"), *args],
                              env={**self.env, **env}, capture_output=True, text=True)

    def resolve(self, *releases):
        metadata = test_setup.write_releases(self.root / "resolve.json", *releases)
        return subprocess.run([str(ROOT / "home/.config/codex-room/tools/paseo-release.py"), "resolve"],
                              env={**self.env, "PASEO_RELEASES_API": str(metadata)}, capture_output=True, text=True)

    def test_latest_stable_wins_over_newer_main_prerelease_and_draft(self):
        work = self.root / "paseo-work"
        self.git(work, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "--allow-empty", "-qm", "daily development after release")
        development = self.git(work, "rev-parse", "HEAD")
        self.git(work, "push", str(self.remote), "HEAD:refs/heads/main")
        # The default metadata also lists v1.5.0-beta.1 (prerelease) and v1.6.0 (draft).
        self.git(self.remote, "tag", "v1.5.0-beta.1", development)
        self.git(self.remote, "tag", "v1.6.0", development)
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"release={test_setup.FIXTURE_RELEASE}", result.stdout)
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD"), self.release)
        self.assertEqual(self.git(self.target, "remote"), "origin")
        self.assertEqual(self.git(self.target, "rev-parse", f"{test_setup.FIXTURE_RELEASE}^{{commit}}"), self.release)
        self.assertEqual(self.git(self.target, "config", "codex-room.paseoRelease"), test_setup.FIXTURE_RELEASE)

    def test_highest_stable_version_wins_regardless_of_listing_order(self):
        self.git(self.remote, "tag", "v1.3.9", self.first)
        result = self.resolve(("v1.3.9", False, False), (test_setup.FIXTURE_RELEASE, False, False), ("v1.10.0-rc.1", False, True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), [test_setup.FIXTURE_RELEASE, self.release])

    def test_transaction_restores_clean_official_checkout_to_release_tag(self):
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.target)], check=True)
        (self.target / "post-release-change").write_text("newer official checkout\n")
        self.git(self.target, "add", "post-release-change")
        self.git(self.target, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "post-release")
        newer_commit = self.git(self.target, "rev-parse", "HEAD")

        preflight = self.run_helper("--preflight")
        self.assertEqual(preflight.returncode, 0, preflight.stderr)
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD"), newer_commit)

        direct = self.run_helper()
        self.assertNotEqual(direct.returncode, 0)
        self.assertIn("transaction-backed replacement", direct.stderr)
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD"), newer_commit)

        managed = self.run_helper(PASEO_COORDINATOR_MANAGED="1")
        self.assertEqual(managed.returncode, 0, managed.stderr)
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD"), self.release)
        self.assertEqual(self.git(self.target, "branch", "--show-current"), "main")
        self.assertEqual(self.git(self.target, "remote"), "origin")
        self.assertEqual(self.git(self.target, "remote", "get-url", "origin"), str(self.remote))
        self.assertFalse((self.target / "post-release-change").exists())

    def test_annotated_release_tag_uses_peeled_commit(self):
        tag = test_setup.FIXTURE_RELEASE
        self.git(self.remote, "tag", "-d", tag)
        self.git(self.remote, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "tag", "-a", tag, self.release, "-m", "Stable release")
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.target, "cat-file", "-t", tag), "tag")
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD"), self.release)
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.target, "cat-file", "-t", tag), "tag")

    def test_missing_prerelease_only_or_unstable_release_fails_before_install(self):
        cases = {
            "listed but untagged": (("v9.9.9", False, False),),
            "prerelease only": (("v1.5.0-beta.1", False, True),),
            "draft only": (("v1.6.0", True, False),),
        }
        for name, releases in cases.items():
            with self.subTest(name):
                metadata = test_setup.write_releases(self.root / f"{name}.json", *releases)
                result = self.run_helper(PASEO_RELEASES_API=str(metadata))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cannot resolve the latest stable", result.stderr)
                self.assertFalse(self.target.exists())
        for tag in ("v1.5.0-beta.1", "main"):
            with self.subTest(tag=tag):
                result = self.run_helper(PASEO_RELEASE_TAG=tag, PASEO_VERIFIED_COMMIT=self.release)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.target.exists())
        self.assertFalse((self.root / "npm.log").exists())

    def test_release_resolved_by_coordinator_then_moved_is_rejected(self):
        self.git(self.remote, "tag", "-f", test_setup.FIXTURE_RELEASE, self.first)
        result = self.run_helper(PASEO_RELEASE_TAG=test_setup.FIXTURE_RELEASE, PASEO_VERIFIED_COMMIT=self.release)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("moved since it was resolved", result.stderr)
        self.assertFalse(self.target.exists())
        self.assertFalse((self.root / "npm.log").exists())

    def make_fork(self, legacy=False):
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.target)], check=True)
        self.git(self.target, "checkout", "-B", "main", self.first)
        (self.target / "fork-feature").write_text("private fork implementation\n")
        self.git(self.target, "add", "fork-feature")
        self.git(self.target, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fork")
        fork_commit = self.git(self.target, "rev-parse", "HEAD")
        if legacy:
            self.git(self.target, "remote", "set-url", "origin", "git@github.com:getpaseo/paseo.git")
            self.git(self.target, "remote", "add", "hoangnb24", "git@github.com:hoangnb24/paseo.git")
        else:
            self.git(self.target, "remote", "set-url", "origin", "git@github.com:hoangnb24/paseo.git")
            self.git(self.target, "remote", "add", "upstream", "git@github.com:getpaseo/paseo.git")
        self.git(self.target, "config", "branch.main.remote", "origin")
        (self.target / ".codex").mkdir()
        (self.target / ".codex/operator-note").write_text("keep me\n")
        # Substitute only the audited historical SHA in a disposable copy.
        # Production code exposes no environment override for that baseline.
        copy = self.root / "setup"
        for relative in ("scripts/lib/common.sh", "scripts/install-paseo", "paseo/source.toml",
                         "home/.config/codex-room/tools/paseo-release.py",
                         "home/.config/codex-room/tools/paseo-pi-contract.mjs",
                         "home/.paseo/config.json.template"):
            dst = copy / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, dst)
            dst.write_text(dst.read_text().replace(OLD_FORK, fork_commit))
        return fork_commit, copy / "scripts/install-paseo"

    def test_fork_migration_requires_journal_preserves_notes_and_removes_fork_remote(self):
        fork, helper = self.make_fork()
        config_before = (self.target / ".git/config").read_bytes()
        result = self.run_helper("--preflight", helper=helper)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.target / ".git/config").read_bytes(), config_before)
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD"), fork)
        result = self.run_helper(helper=helper)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("transactional backup", result.stderr)
        result = self.run_helper(helper=helper, PASEO_COORDINATOR_MANAGED="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD"), self.release)
        self.assertEqual(self.git(self.target, "remote"), "origin")
        self.assertEqual(self.git(self.target, "remote", "get-url", "origin"), str(self.remote))
        self.assertEqual(self.git(self.target, "for-each-ref", "--format=%(refname)", "refs/remotes/origin"), "")
        self.assertFalse((self.target / "fork-feature").exists())
        self.assertEqual((self.target / ".codex/operator-note").read_text(), "keep me\n")
        result = self.run_helper(helper=helper)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_remote_layout_migrates_and_unknown_fork_commit_is_refused(self):
        fork, helper = self.make_fork(legacy=True)
        result = self.run_helper(helper=helper, PASEO_COORDINATOR_MANAGED="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.target, "remote"), "origin")
        self.git(self.target, "remote", "set-url", "origin", "git@github.com:hoangnb24/paseo.git")
        self.git(self.target, "remote", "add", "upstream", "git@github.com:getpaseo/paseo.git")
        result = self.run_helper(helper=helper, PASEO_COORDINATOR_MANAGED="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("recognized Room baseline", result.stderr)
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD"), self.release)

    def test_policy_verifier_rejects_implicit_tools_and_peer_enabled(self):
        config = json.loads((ROOT / "home/.paseo/config.json.template").read_text())
        def check(value):
            return subprocess.run(["jq", "-e", "-f", str(ROOT / "scripts/lib/paseo-tools.jq")],
                                  input=json.dumps(value), text=True, capture_output=True).returncode
        self.assertEqual(check(config), 0)
        config["agents"]["providers"]["codex-peer"]["paseoTools"]["enabled"] = True
        self.assertNotEqual(check(config), 0)
        config["agents"]["providers"]["codex-peer"]["paseoTools"]["enabled"] = False
        config["agents"]["providers"]["future-provider"] = {"extends": "codex", "label": "Future"}
        self.assertNotEqual(check(config), 0)
        config["agents"]["providers"]["future-provider"]["paseoTools"] = {"enabled": False}
        self.assertEqual(check(config), 0)

    def test_public_migration_rolls_back_fork_on_final_verification_failure(self):
        lifecycle = test_setup.PublicInstallTransactionTests()
        lifecycle.setUp()
        self.addCleanup(lifecycle.tearDown)
        fork, helper = self.make_fork()
        copy = helper.parents[1]
        for directory in ("scripts", "home", "paseo"):
            shutil.copytree(ROOT / directory, copy / directory, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "install", copy / "install")
        for relative in ("scripts/install-room", "scripts/install-paseo"):
            file = copy / relative
            file.write_text(file.read_text().replace(OLD_FORK, fork))
        before = lifecycle.tree_snapshot(self.target)
        # The release tests' fixture remote and metadata are the official source here.
        env = {**lifecycle.lifecycle_env(helper, lifecycle.make_fake_verifier()),
               "PASEO_SOURCE_URL": self.env["PASEO_SOURCE_URL"],
               "PASEO_RELEASES_API": self.env["PASEO_RELEASES_API"],
               "PASEO_NPM_BIN": self.env["PASEO_NPM_BIN"], "NPM_LOG": self.env["NPM_LOG"],
               "PASEO_REPO_DIR": str(self.target),
               "VERIFY_FAIL": "1"}
        result = subprocess.run([str(copy / "install"), "--apply"], env=env,
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PASEO_RELEASE_READY", result.stdout, result.stderr)
        self.assertEqual(lifecycle.tree_snapshot(self.target), before)
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD"), fork)
        self.assertFalse((lifecycle.home / ".paseo/config.json").exists())
        # The same transaction succeeds on retry and retains a full fork backup.
        result = subprocess.run([str(copy / "install"), "--apply"],
                                env={**env, "VERIFY_FAIL": "0"}, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD"), self.release)
        self.assertEqual(self.git(self.target, "remote"), "origin")
        self.assertTrue(list((lifecycle.home / ".codex-room-backups").rglob("fork-feature")))

    def test_tag_moving_between_lookup_and_fetch_is_rejected(self):
        # Resolution and the helper's re-check both see the release; the tag then
        # moves before the fetch, which must still refuse the changed object.
        wrapper = self.root / "bin/git"
        self.fixtures.executable(wrapper, f'''#!/bin/sh
set -eu
if [ "${{1:-}}" = ls-remote ]; then
  "$REAL_GIT" "$@"
  printf x >> "$LOOKUPS"
  if [ "$(wc -c < "$LOOKUPS")" -ge 2 ]; then
    "$REAL_GIT" -C "$TEST_REMOTE" update-ref refs/tags/{test_setup.FIXTURE_RELEASE} "$TEST_FIRST"
  fi
else
  exec "$REAL_GIT" "$@"
fi
''')
        result = self.run_helper(PATH=str(wrapper.parent) + os.pathsep + self.env["PATH"], LOOKUPS=str(self.root / "lookups"),
                                 REAL_GIT=shutil.which("git"), TEST_REMOTE=str(self.remote), TEST_FIRST=self.first)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match resolved commit", result.stderr)
        self.assertFalse(self.target.exists())
        self.assertFalse((self.root / "npm.log").exists())

    def test_desktop_updater_accepts_stable_tag_without_following_main(self):
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.target)], check=True)
        self.git(self.remote, "update-ref", "refs/heads/main", self.first)
        sentinel = self.fixtures.executable(self.root / "sentinel-npm", '''#!/bin/sh
printf '%s\\n' "$*" > "$NPM_LOG"
exit 17
''')
        result = subprocess.run([str(ROOT / "home/.local/bin/paseo-local-update")],
                                env={**self.env, "PASEO_NPM_BIN": str(sentinel),
                                     "CODEX_ROOM_TOOLS": str(ROOT / "home/.config/codex-room/tools")},
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("npm ci failed", result.stderr)
        self.assertEqual((self.root / "npm.log").read_text().strip(), "ci")
        self.assertEqual(self.git(self.target, "rev-parse", "HEAD"), self.release)
        self.assertEqual(self.git(self.target, "config", "codex-room.paseoRelease"), test_setup.FIXTURE_RELEASE)
