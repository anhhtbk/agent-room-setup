"""Model-agnostic validation and real verifier wiring in disposable trees."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/lib/model-alignment.py"
ROLES = ("supervisor", "lead", "peer")


class ModelAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.overlays = self.root / "overlays"
        self.overlays.mkdir()
        self.runtime = self.root / "runtime"
        self.config_path = self.root / "paseo.json"
        self.config = {"agents": {"providers": {}}}
        for role in ROLES:
            model = f"arbitrary-{role}"
            self.config["agents"]["providers"][f"codex-{role}"] = {
                "models": [{"id": model, "isDefault": True,
                            "thinkingOptions": [{"id": "custom-effort", "isDefault": True}]}]
            }
            # Literal/quoted TOML keys, comments, and misleading instruction text
            # ensure this is a parser check, not a line/regex comparison.
            content = (f"'model' = '{model}' # comment\n"
                       "model_reasoning_effort = 'custom-effort'\n"
                       "developer_instructions = '''\nmodel = \"decoy\"\n'''\n")
            (self.overlays / f"{role}.config.toml").write_text(content)
            (self.runtime / role).mkdir(parents=True)
            (self.runtime / role / "config.toml").write_text(content)

    def models(self, role="peer"):
        return self.config["agents"]["providers"][f"codex-{role}"]["models"]

    def run_helper(self, runtime=False):
        self.config_path.write_text(json.dumps(self.config))
        args = [sys.executable, "-B", str(HELPER), str(self.config_path), str(self.overlays)]
        if runtime:
            args += ["--runtime-root", str(self.runtime)]
        return subprocess.run(args, capture_output=True, text=True)

    def assert_failure(self, result, *messages):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        for message in messages:
            self.assertIn(message, result.stderr)

    def test_aligned_arbitrary_models_and_effort_with_real_toml(self):
        for runtime in (False, True):
            with self.subTest(runtime=runtime):
                result = self.run_helper(runtime)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_provider_model_and_effort_mismatch_for_every_role(self):
        baseline = copy.deepcopy(self.config)
        for role in ROLES:
            for field in ("model", "model_reasoning_effort"):
                with self.subTest(role=role, field=field):
                    self.config = copy.deepcopy(baseline)
                    entry = self.models(role)[0]
                    if field == "model":
                        entry["id"] = "wrong-model"
                    else:
                        entry["thinkingOptions"][0]["id"] = "wrong-effort"
                    self.assert_failure(self.run_helper(), f"{role} model alignment", f"Paseo {field}=", f"overlay {field}=")

    def test_missing_and_duplicate_defaults(self):
        baseline = copy.deepcopy(self.config)
        for layer in ("model", "effort"):
            for count in (0, 2):
                with self.subTest(layer=layer, count=count):
                    self.config = copy.deepcopy(baseline)
                    entries = self.models() if layer == "model" else self.models()[0]["thinkingOptions"]
                    if count == 0:
                        del entries[0]["isDefault"]
                    else:
                        entries.append(copy.deepcopy(entries[0]))
                    self.assert_failure(self.run_helper(), "peer model alignment", f"expected exactly one default, found {count}")

    def test_nonempty_string_ids_and_boolean_default_flags(self):
        baseline = copy.deepcopy(self.config)
        for layer in ("model", "effort"):
            for key, values in (("id", (None, "", "  ", 42)), ("isDefault", ("true", 1, None))):
                for value in values:
                    with self.subTest(layer=layer, key=key, value=value):
                        self.config = copy.deepcopy(baseline)
                        entry = self.models()[0] if layer == "model" else self.models()[0]["thinkingOptions"][0]
                        entry[key] = value
                        self.assert_failure(self.run_helper(), "peer model alignment", "nonempty string ID" if key == "id" else "expected a boolean")

    def test_missing_and_malformed_provider_structure(self):
        baseline = copy.deepcopy(self.config)
        for value in (None, [], {}, {"models": None}, {"models": [None]}, {"models": []}):
            with self.subTest(value=value):
                self.config = copy.deepcopy(baseline)
                self.config["agents"]["providers"]["codex-peer"] = value
                self.assert_failure(self.run_helper(), "peer model alignment")
        self.config = {"agents": []}
        self.assert_failure(self.run_helper(), "cannot read Paseo providers")

    def test_overlay_and_runtime_require_top_level_valid_strings(self):
        for layer in ("overlay", "runtime"):
            path = (self.overlays / "peer.config.toml" if layer == "overlay"
                    else self.runtime / "peer/config.toml")
            original = path.read_text()
            for content in ("", "[nested]\nmodel = 'arbitrary-peer'\nmodel_reasoning_effort = 'custom-effort'\n",
                            "model = ''\nmodel_reasoning_effort = 'custom-effort'\n",
                            "model = 'arbitrary-peer'\nmodel_reasoning_effort = 1\n"):
                with self.subTest(layer=layer, content=content):
                    path.write_text(content)
                    self.assert_failure(self.run_helper(True), layer, "nonempty string ID")
            path.write_text(original)

    def test_invalid_toml_and_missing_files_fail_without_content_dump(self):
        for layer in ("overlay", "runtime"):
            path = (self.overlays / "peer.config.toml" if layer == "overlay"
                    else self.runtime / "peer/config.toml")
            original = path.read_text()
            path.write_text(original + "model = 'PRIVATE_SENTINEL'\n")
            result = self.run_helper(True)
            self.assert_failure(result, f"cannot read {layer} TOML", "TOMLDecodeError")
            self.assertNotIn("PRIVATE_SENTINEL", result.stderr)
            path.unlink()
            self.assert_failure(self.run_helper(True), f"cannot read {layer} TOML", "FileNotFoundError")
            path.write_text(original)

    def test_runtime_model_and_effort_mismatch_for_every_role(self):
        for role in ROLES:
            path = self.runtime / role / "config.toml"
            original = path.read_text()
            for before, after, field in ((f"arbitrary-{role}", "wrong-model", "model"),
                                          ("custom-effort", "wrong-effort", "model_reasoning_effort")):
                with self.subTest(role=role, field=field):
                    path.write_text(original.replace(before, after))
                    self.assert_failure(self.run_helper(True), f"{role} model alignment", f"runtime {field}=", f"overlay {field}=")
            path.write_text(original)

    def copy_verifier_tree(self):
        repo = self.root / "repo"
        for name in ("scripts", "home", "paseo"):
            shutil.copytree(ROOT / name, repo / name)
        env = {**os.environ, "HOME": str(self.root / "unused-home"),
               "CODEX_ROOM_TOML_PYTHON": sys.executable, "PYTHONDONTWRITEBYTECODE": "1"}
        return repo, env

    def test_source_verify_integration_passes_then_rejects_mismatch(self):
        repo, env = self.copy_verifier_tree()
        args = [str(repo / "scripts/verify"), "--source"]
        result = subprocess.run(args, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK    role model/effort defaults aligned (source)", result.stdout)
        config_path = repo / "home/.paseo/config.json.template"
        config = json.loads(config_path.read_text())
        default = next(model for model in config["agents"]["providers"]["codex-peer"]["models"] if model.get("isDefault"))
        default["id"] = "deliberately-wrong"
        config_path.write_text(json.dumps(config))
        result = subprocess.run(args, env=env, capture_output=True, text=True)
        self.assert_failure(result, "peer model alignment", "deliberately-wrong")
        self.assertIn("FAIL  role model/effort defaults aligned (source)", result.stdout)
        self.assertNotIn("VERIFY_OK", result.stdout)

    def test_installed_verify_wires_installed_paths_and_runtime_override(self):
        repo, env = self.copy_verifier_tree()
        home = repo / "home"
        env["HOME"] = str(home)
        env["CODEX_ROOM_RUNTIME_ROOT"] = str(self.runtime)
        env["PASEO_REPO_DIR"] = str(self.root / "absent-paseo-checkout")
        env["PASEO_CLI_LINK"] = str(self.root / "absent-paseo-cli")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        codex = bin_dir / "codex"
        codex.write_text("#!/bin/sh\nexit 0\n")
        codex.chmod(0o755)
        env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
        (home / ".paseo/config.json").write_text(json.dumps(self.config))
        for role in ROLES:
            shutil.copyfile(self.overlays / f"{role}.config.toml", home / f".config/codex-room/overlays/{role}.config.toml")
        args = [str(repo / "scripts/verify")]
        result = subprocess.run(args, env=env, capture_output=True, text=True)
        # This minimal fixture deliberately lacks a release checkout/catalogs;
        # those independent failures must not hide the alignment check result.
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OK    role model/effort defaults aligned (installed)", result.stdout)
        path = self.runtime / "lead/config.toml"
        path.write_text(path.read_text().replace("custom-effort", "stale-effort"))
        result = subprocess.run(args, env=env, capture_output=True, text=True)
        self.assert_failure(result, "lead model alignment", "runtime model_reasoning_effort='stale-effort'")
        self.assertIn("FAIL  role model/effort defaults aligned (installed)", result.stdout)


if __name__ == "__main__":
    unittest.main()
