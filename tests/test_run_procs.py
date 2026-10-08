"""Behavior tests for run-procs.py through its CLI, on processes the test creates.

Every "foreign" process here is a /bin/sleep started by the test itself with
the same command line as the run's processes; tests never touch other processes.
"""
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

TOOL = pathlib.Path(__file__).resolve().parents[1] / "home" / ".config" / "codex-room" / "tools" / "run-procs.py"

# Runs the tool in-process and SIGKILLs the launcher at a critical point of the launch.
KILL_LAUNCHER = """
import importlib.util, os, signal, sys
spec = importlib.util.spec_from_file_location("run_procs", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
point, real = sys.argv[2], tool.start_holder
def start_holder(argv, **kwargs):
    if point == "before-spawn":
        os.kill(os.getpid(), signal.SIGKILL)
    holder = real(argv, **kwargs)
    if point == "after-spawn":
        os.kill(os.getpid(), signal.SIGKILL)
    return holder
tool.start_holder = start_holder
sys.argv = ["run-procs.py", *sys.argv[3:]]
sys.exit(tool.main())
"""

# A `ps` stand-in on PATH: logs the process group it runs in, can fail or stall on demand, and cuts lines to 60
# characters unless called with -ww (what a narrow terminal does to real ps output).
PS_SHIM = """#!{python}
import os, subprocess, sys, time
here = os.path.dirname(os.path.abspath(__file__))
def flag(name):
    path = os.path.join(here, name)
    return open(path).read().strip() if os.path.exists(path) else None
real = "{real_ps}"
with open(os.path.join(here, "pgids.log"), "a") as log:
    log.write(subprocess.run([real, "-o", "pgid=", "-p", str(os.getpid())], capture_output=True, text=True).stdout.strip() + "\\n")
if flag("slow"):
    time.sleep(float(flag("slow")))
if flag("fail") is not None:
    sys.exit(1)
result = subprocess.run([real, *sys.argv[1:]], capture_output=True, text=True)
lines = result.stdout.splitlines()
if "-ww" not in sys.argv:
    lines = [line[:60] for line in lines]
sys.stdout.write("".join(line + "\\n" for line in lines))
sys.exit(result.returncode)
"""


def alive(pid: int) -> bool:
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(result.stdout.strip()) and "Z" not in result.stdout


def wait_for(predicate, seconds: float = 10) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


class RunProcsTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="runprocs-")).resolve()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.registry = self.dir / "procs"
        self.foreign = subprocess.Popen(["/bin/sleep", "300"], start_new_session=True)
        self.addCleanup(self.foreign.wait)
        self.addCleanup(self.foreign.kill)
        self.addCleanup(self.kill_registered)
        self.pids: list[int] = []
        self.addCleanup(self.kill_pids)
        self.shims = self.dir / "shims"

    def kill_registered(self):
        for path in self.registry.glob("*.json"):
            try:
                record = json.loads(path.read_text())
                os.killpg(record["pgid"], signal.SIGKILL)
            except (OSError, ValueError, KeyError):
                pass

    def kill_pids(self):
        for pid in self.pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def shim_env(self) -> dict:
        if not self.shims.exists():
            self.shims.mkdir()
            shim = self.shims / "ps"
            shim.write_text(PS_SHIM.format(python=sys.executable, real_ps=shutil.which("ps")))
            shim.chmod(0o755)
        return {**os.environ, "PATH": f"{self.shims}{os.pathsep}{os.environ['PATH']}"}

    def tool(self, *args, timeout: float = 60, env=None, cwd=None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True,
                              timeout=timeout, env=env, cwd=cwd)

    def record(self, name: str) -> dict:
        return json.loads((self.registry / f"{name}.json").read_text())

    def start(self, name: str, script: str, env=None) -> dict:
        result = self.tool("start", self.registry, "--name", name, "--log", self.dir / f"{name}.log",
                           "--", "sh", "-c", script, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.record(name)

    def pid_from(self, path: pathlib.Path) -> int:
        self.assertTrue(wait_for(lambda: path.exists() and path.read_text().strip()), path)
        pid = int(path.read_text())
        self.pids.append(pid)
        return pid

    def runner(self, name: str, script: str, env=None) -> subprocess.Popen:
        process = subprocess.Popen([sys.executable, str(TOOL), "run", str(self.registry), "--name", name, "--",
                                    "sh", "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    # --- run / start / stop as in v1 -------------------------------------------------------------

    def test_run_returns_exit_code_reaps_leftover_and_spares_same_named_foreign(self):
        pidfile = self.dir / "orphan.pid"
        result = self.tool("run", self.registry, "--name", "gate", "--",
                           "sh", "-c", f"/bin/sleep 300 & echo $! > {pidfile}; echo gate-output; exit 3")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("gate-output", result.stdout)
        orphan = int(pidfile.read_text())
        self.assertTrue(wait_for(lambda: not alive(orphan)))
        self.assertTrue(alive(self.foreign.pid))
        self.assertEqual(self.record("gate")["state"], "stopped")

    def test_run_reports_signal_death_and_unstartable_command(self):
        result = self.tool("run", self.registry, "--name", "dies", "--", "sh", "-c", "kill -9 $$")
        self.assertEqual(result.returncode, 137)
        result = self.tool("run", self.registry, "--name", "missing", "--", "/nonexistent/command")
        self.assertEqual(result.returncode, 127)
        self.assertIn("cannot start", result.stderr)

    def test_stop_terminates_background_group_and_escalates(self):
        pidfile = self.dir / "stubborn.pid"
        record = self.start("server", f"trap '' TERM; /bin/sleep 300 & echo $! > {pidfile}; while :; do /bin/sleep 1; done")
        child = self.pid_from(pidfile)
        listing = self.tool("list", self.registry).stdout
        self.assertIn("server state=running holder=verified", listing)
        result = self.tool("stop", self.registry, "--grace", "1")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("STOPPED server", result.stdout)
        self.assertIn("SUMMARY stopped=1", result.stdout)
        self.assertTrue(wait_for(lambda: not alive(child) and not alive(record["pid"])))
        self.assertTrue(self.record("server")["sigkill"], "TERM-ignoring shell must be escalated to SIGKILL")
        self.assertTrue(alive(self.foreign.pid))

    def test_stop_refuses_record_pointing_at_foreign_process(self):
        record = self.start("server", "/bin/sleep 300")
        tampered = {**record, "pid": self.foreign.pid, "pgid": self.foreign.pid}
        (self.registry / "server.json").write_text(json.dumps(tampered))
        result = self.tool("stop", self.registry, "--grace", "1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("REFUSE server", result.stdout)
        self.assertTrue(alive(self.foreign.pid))
        (self.registry / "server.json").write_text(json.dumps(record))
        self.assertEqual(self.tool("stop", self.registry, "--grace", "1").returncode, 0)
        self.assertTrue(alive(self.foreign.pid))

    def test_stop_refuses_unverifiable_group_when_holder_is_gone(self):
        pidfile = self.dir / "member.pid"
        record = self.start("server", f"/bin/sleep 300 & echo $! > {pidfile}; wait")
        member = self.pid_from(pidfile)
        os.kill(record["pid"], signal.SIGKILL)
        self.assertTrue(wait_for(lambda: not alive(record["pid"])))
        result = self.tool("stop", self.registry, "--grace", "1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unverified", result.stdout)
        self.assertTrue(alive(member), "an unverified group must not be signalled")

    def test_background_command_that_finished_is_reported_exited(self):
        self.start("oneshot", "exit 0")
        self.assertTrue(wait_for(lambda: (self.registry / "oneshot.json.closed").exists()))
        result = self.tool("stop", self.registry)
        self.assertEqual(result.returncode, 0)
        self.assertIn("EXITED oneshot", result.stdout)
        self.assertEqual(self.record("oneshot")["state"], "exited")

    # --- B3: every hang-up style signal to `run` cleans its group ----------------------------------

    def test_run_interrupted_by_any_signal_still_cleans_its_group(self):
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
            with self.subTest(signal=number.name):
                pidfile = self.dir / f"child-{number.name}.pid"
                runner = self.runner(f"gate-{number.name}", f"/bin/sleep 300 & echo $! > {pidfile}; wait")
                child = self.pid_from(pidfile)
                runner.send_signal(number)
                self.assertEqual(runner.wait(timeout=30), 128 + number)
                self.assertTrue(wait_for(lambda: not alive(child)))
                self.assertTrue(alive(self.foreign.pid))
                self.assertEqual(self.record(f"gate-{number.name}")["state"], "stopped")

    def test_sigkilled_run_leaves_a_registered_group_that_stop_cleans(self):
        pidfile = self.dir / "child.pid"
        runner = self.runner("gate", f"/bin/sleep 300 & echo $! > {pidfile}; wait")
        child = self.pid_from(pidfile)
        runner.kill()
        runner.wait()
        self.assertTrue(alive(child), "SIGKILL of the launcher cannot stop the group; that is the documented limit")
        self.assertIn("gate state=running holder=verified", self.tool("list", self.registry).stdout)
        result = self.tool("stop", self.registry, "--grace", "1")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(wait_for(lambda: not alive(child)))
        self.assertTrue(alive(self.foreign.pid))

    # --- B1: the holder's own polling must survive `stop` and a failing ps -------------------------

    def test_holder_keeps_waiting_when_ps_fails_and_its_ps_is_outside_the_group(self):
        env = self.shim_env()
        pidfile = self.dir / "stubborn.pid"
        record = self.start("server", f"(trap '' TERM; exec /bin/sleep 300) & echo $! > {pidfile}",
                            env=env)
        member = self.pid_from(pidfile)
        self.assertTrue(wait_for(lambda: (self.registry / "server.json.exit").exists()),
                        "the command finished; the holder is now in its poll phase")
        (self.shims / "fail").write_text("")
        time.sleep(2.5)  # several polls with a failing ps: unknown must not be read as empty
        self.assertTrue(alive(record["pid"]), "holder left although the process table was unreadable")
        self.assertTrue(alive(member))
        self.assertFalse((self.registry / "server.json.closed").exists())
        (self.shims / "fail").unlink()
        result = self.tool("stop", self.registry, "--grace", "1", env=env)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"sigkill=[{member}]", result.stdout, "the TERM-ignoring member needs SIGKILL while the holder is verified")
        self.assertTrue(wait_for(lambda: not alive(member) and not alive(record["pid"])))
        groups = {line for line in (self.shims / "pgids.log").read_text().split()}
        self.assertNotIn(str(record["pgid"]), groups, "ps calls must not run inside the run's process group")

    def test_stop_reports_unknown_process_table_instead_of_signalling(self):
        env = self.shim_env()
        record = self.start("server", "/bin/sleep 300", env=env)
        (self.shims / "fail").write_text("")
        result = self.tool("stop", self.registry, "--grace", "1", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot read the process table", result.stdout)
        (self.shims / "fail").unlink()
        self.assertTrue(alive(record["pid"]))
        self.assertEqual(self.tool("stop", self.registry, "--grace", "1", env=env).returncode, 0)

    def test_identity_checks_do_not_depend_on_terminal_width(self):
        env = self.shim_env()
        record = self.start("server", "/bin/sleep 300", env=env)
        narrow = subprocess.run([str(self.shims / "ps"), "-o", "command=", "-p", str(record["pid"])],
                                capture_output=True, text=True).stdout.strip()
        self.assertLessEqual(len(narrow), 60, "the shim must truncate without -ww or this test proves nothing")
        self.assertIn("holder=verified", self.tool("list", self.registry, env=env).stdout)
        result = self.tool("stop", self.registry, "--grace", "1", env=env)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("STOPPED server", result.stdout)

    # --- B2: the registry is always named, a missing one is explicit -------------------------------

    def test_registry_is_always_named_and_a_missing_one_is_explicit(self):
        missing = self.dir / "not-there"
        for action in ("stop", "list"):
            result = self.tool(action, missing)
            self.assertEqual(result.returncode, 0)
            self.assertIn(f"NO-REGISTRY {missing}", result.stdout)
        relative = self.tool("stop", "relative-registry", cwd=self.dir)
        self.assertIn(f"NO-REGISTRY {self.dir / 'relative-registry'}", relative.stdout)
        self.registry.mkdir()
        empty = self.tool("stop", self.registry)
        self.assertIn(f"REGISTRY {self.registry} records=0", empty.stdout)
        self.assertIn("SUMMARY stopped=0 exited=0 not-started=0 skipped=0 refused=0", empty.stdout)
        self.assertIn(f"REGISTRY {self.registry} records=0", self.tool("list", self.registry).stdout)
        named = self.tool("stop", self.registry, "--name", "nope")
        self.assertEqual(named.returncode, 1)
        self.assertIn("REFUSE no record", named.stdout)

    def test_unreadable_record_is_refused_not_a_crash(self):
        self.registry.mkdir()
        (self.registry / "bad.json").write_text("{not json")
        stopped = self.tool("stop", self.registry)
        self.assertEqual(stopped.returncode, 1, stopped.stdout + stopped.stderr)
        self.assertIn("REFUSE unreadable record", stopped.stdout)
        self.assertIn("UNREADABLE", self.tool("list", self.registry).stdout)

    # --- B4: no shared build servers inside the group ----------------------------------------------

    def test_commands_get_env_that_disables_shared_build_servers(self):
        env = {**os.environ, "MSBUILDDISABLENODEREUSE": "0", "UseSharedCompilation": "true"}
        result = self.tool("run", self.registry, "--name", "env", "--", "sh", "-c",
                           "echo $MSBUILDDISABLENODEREUSE $DOTNET_CLI_USE_MSBUILD_SERVER $UseSharedCompilation", env=env)
        self.assertEqual(result.stdout.splitlines()[0], "1 0 false")

    # --- launch: a command never runs unregistered --------------------------------------------------

    def kill_launcher(self, point: str, name: str, script: str, env=None) -> subprocess.CompletedProcess:
        # no pipes: the surviving holder would keep them open and block the read
        return subprocess.run(
            [sys.executable, "-c", KILL_LAUNCHER, str(TOOL), point, "run", str(self.registry), "--name", name, "--",
             "sh", "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, timeout=60)

    def test_launcher_killed_before_the_holder_exists_leaves_nothing_to_run(self):
        ran = self.dir / "ran"
        result = self.kill_launcher("before-spawn", "gate", f"echo $$ > {ran}; /bin/sleep 300")
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertEqual(self.record("gate")["state"], "starting")
        stopped = self.tool("stop", self.registry)
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.assertIn("NOT-STARTED gate", stopped.stdout)
        self.assertIn("not-started=1", stopped.stdout)
        time.sleep(0.5)
        self.assertFalse(ran.exists(), "the command must never run")

    def test_launcher_killed_right_after_spawn_leaves_a_registered_group(self):
        pidfile = self.dir / "cmd.pid"
        result = self.kill_launcher("after-spawn", "gate", f"echo $$ > {pidfile}; /bin/sleep 300")
        self.assertEqual(result.returncode, -signal.SIGKILL)
        command = self.pid_from(pidfile)
        record = self.record("gate")
        self.assertEqual(record["state"], "running")
        self.assertEqual(record["pgid"], os.getpgid(command), "the record must hold the group the command runs in")
        self.assertIn("gate state=running holder=verified", self.tool("list", self.registry).stdout)
        stopped = self.tool("stop", self.registry, "--grace", "1")
        self.assertEqual(stopped.returncode, 0, stopped.stdout)
        self.assertTrue(wait_for(lambda: not alive(command)))

    def test_launcher_killed_while_the_holder_is_still_registering_never_runs_the_command(self):
        env = self.shim_env()
        (self.shims / "slow").write_text("2")  # the holder's first ps (its own identity) takes 2 s
        ran = self.dir / "ran"
        result = self.kill_launcher("after-spawn", "gate", f"echo $$ > {ran}; /bin/sleep 300", env=env)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertEqual(self.record("gate")["state"], "starting")
        stopped = self.tool("stop", self.registry)  # plain env: real ps
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.assertIn("NOT-STARTED gate", stopped.stdout)
        self.assertEqual(self.record("gate")["state"], "not-started")
        time.sleep(0.5)
        self.assertFalse(ran.exists(), "the late holder must see the cancel marker and exit without running anything")
        listing = subprocess.run(["ps", "-ww", "-A", "-o", "command="], capture_output=True, text=True).stdout
        self.assertNotIn(self.record("gate")["nonce"], listing, "the cancelled holder must be gone")

    def test_run_interrupted_while_the_holder_is_registering_never_runs_the_command(self):
        env = self.shim_env()
        (self.shims / "slow").write_text("2")
        ran = self.dir / "ran"
        runner = self.runner("gate", f"echo $$ > {ran}; /bin/sleep 300", env=env)
        self.assertTrue(wait_for(lambda: (self.registry / "gate.json").exists()))
        runner.send_signal(signal.SIGTERM)
        self.assertEqual(runner.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertEqual(self.record("gate")["state"], "not-started")
        time.sleep(0.5)
        self.assertFalse(ran.exists())

    def test_bad_launch_arguments_start_nothing_and_register_nothing(self):
        result = self.tool("run", self.registry, "--cwd", self.dir / "nope", "--", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.registry.glob("*")) if self.registry.exists() else [], [])
        self.start("dup", "/bin/sleep 300")
        again = self.tool("start", self.registry, "--name", "dup", "--log", self.dir / "dup2.log", "--", "true")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already used", again.stdout + again.stderr)
        self.assertEqual(self.tool("stop", self.registry, "--grace", "1").returncode, 0)


if __name__ == "__main__":
    unittest.main()
