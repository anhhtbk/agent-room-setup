#!/usr/bin/env python3
"""Start processes in a run-owned process group and stop only that group.

Usage:
  run-procs.py run   <registry-dir> [--name N] [--cwd DIR] [--grace S] -- <command...>
  run-procs.py start <registry-dir> --log FILE [--name N] [--cwd DIR] -- <command...>
  run-procs.py stop  <registry-dir> [--name N] [--grace S]
  run-procs.py list  <registry-dir>

Call it as `python3 <absolute path>/run-procs.py` with an absolute registry
path; every subcommand prints the absolute registry it used.

run    Foreground: output passes through, exit code is the command's. When the
       command exits, or `run` gets SIGINT/SIGTERM/SIGHUP/SIGQUIT, every
       process still in its group is stopped (a database a test runner left
       behind). Cleanup itself ignores further signals.
start  Background (servers, watchers): output to --log; stop it later.
stop   Stops every registered group in the registry (or one --name): SIGTERM to
       the group, SIGKILL after --grace seconds (default 10). Ends with one
       SUMMARY line.
list   Shows each record, whether its holder is verified alive, and members.

Each command runs under a small holder process that leads a new session and
process group. The holder ignores SIGTERM and stays alive while the group may
still have members, so the group id cannot be reused by anyone else. The
holder writes its own identity (pid, start time, group id, per-launch nonce in
its argv) into the record before it starts the command, so a command never
runs unregistered: if `run`/`start` dies at any point, either nothing was
started or the record already holds the verified identity. `stop` signals a
group only after verifying that identity against the live process. If the
holder is gone or does not match, it signals nothing and prints REFUSE with
the pids it saw, for a human decision. It never matches processes by name.
A record whose holder never registered is reported `NOT-STARTED`; `stop`
cancels such a launch, and a late holder then exits without running anything.

Commands get MSBUILDDISABLENODEREUSE=1, DOTNET_CLI_USE_MSBUILD_SERVER=0 and
UseSharedCompilation=false, so MSBuild node reuse and the shared Roslyn compiler
server do not outlive the run inside its group (killing a server that another
session attached to would break that session). Other shared servers (gradle
daemon, bazel, ...) are not covered: set their own flags in the command.

Exit codes: run = the command's (128+N when it died of signal N; 128+N when
`run` itself got signal N); 125 when the command was never started; stop 1
when anything was refused; 2 usage error. `stop`/`list` on a registry that does
not exist print `NO-REGISTRY <path>` and exit 0: nothing was ever started there.

Limits: helper, not a sandbox. A process that leaves the group (setsid,
daemonizing `--fork`, launchd- or docker-managed services) is not tracked and
not stopped. Records are created only by run/start; existing processes cannot
be adopted. If `run` itself is SIGKILLed its holder and command keep running
and stay registered; `stop` cleans them. A holder SIGKILLed with members left
makes `stop` REFUSE (unverifiable group). Between the final identity check and
the kill signal the holder could die and its group id be reused (microseconds,
only possible once the group is otherwise empty). Identity is read with
`ps -ww`; if `ps` itself fails, state is "unknown", never "empty": nothing is
signalled and the holder keeps waiting. Unix only (macOS, Linux).
"""
import argparse
import datetime
import json
import os
import pathlib
import secrets
import signal
import subprocess
import sys
import time

HOLD = "_hold"
BUILD_SERVER_ENV = {"MSBUILDDISABLENODEREUSE": "1", "DOTNET_CLI_USE_MSBUILD_SERVER": "0", "UseSharedCompilation": "false"}
LAUNCH_WAIT = 5.0  # seconds `stop` waits for a launching holder to register
POLL = 0.5
HANDLED = tuple(getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT"))


class PsUnavailable(Exception):
    """`ps` failed or printed something unexpected: the process table is unknown."""


class RecordError(Exception):
    pass


class Interrupted(Exception):
    def __init__(self, number: int):
        super().__init__(number)
        self.number = number


def ps_lines(*args: str, gone_ok: bool = False) -> list[str]:
    """`ps -ww` in its own session (never in a group someone signals). rc 1 with no output means no such pid."""
    try:
        result = subprocess.run(["ps", "-ww", *args], capture_output=True, text=True, start_new_session=True,
                                env={**os.environ, "LC_ALL": "C"})
    except OSError as error:
        raise PsUnavailable(str(error)) from None
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 and not (gone_ok and result.returncode == 1 and not lines):
        raise PsUnavailable(f"ps exited {result.returncode}: {result.stderr.strip()}")
    return lines


def describe(pid: int) -> dict | None:
    """Live process facts, or None when it is gone (a zombie is gone)."""
    lines = ps_lines("-o", "pgid=", "-o", "stat=", "-o", "lstart=", "-o", "command=", "-p", str(pid), gone_ok=True)
    if not lines:
        return None
    try:
        pgid, state, rest = lines[0].split(None, 2)
        info = {"pgid": int(pgid), "lstart": rest[:24].strip(), "command": rest[24:].strip()}
    except ValueError:
        raise PsUnavailable(f"unparsable ps line: {lines[0]!r}") from None
    return None if "Z" in state else info


def group_members(pgid: int, holder: int | None = None) -> list[int]:
    """Live (non-zombie) processes in the group except `holder`."""
    members = []
    for line in ps_lines("-A", "-o", "pid=", "-o", "pgid=", "-o", "stat="):
        try:
            pid, group, state = line.split(None, 2)
            pid, group = int(pid), int(group)
        except ValueError:
            raise PsUnavailable(f"unparsable ps line: {line!r}") from None
        if group == pgid and "Z" not in state and pid != holder:
            members.append(pid)
    return sorted(members)


def settled(pgid: int, holder: int | None) -> bool:
    """True only when the group is known to be empty; an unknown table is not empty."""
    try:
        return not group_members(pgid, holder)
    except PsUnavailable:
        return False


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: pathlib.Path, data: dict) -> None:
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def create_exclusive(path: pathlib.Path, data: dict) -> None:
    """Atomically create `path` with complete content; FileExistsError if the name is taken."""
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def read_record(path: pathlib.Path) -> dict:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RecordError(f"unreadable record {path}: {error}") from None
    if not isinstance(record, dict) or "name" not in record:
        raise RecordError(f"not a run-procs record: {path}")
    return record


def update_record(path: pathlib.Path, **fields) -> dict:
    record = read_record(path)
    record.update(fields)
    write_json(path, record)
    return record


def own_identity(nonce: str) -> dict | None:
    for attempt in range(5):
        try:
            info = describe(os.getpid())
        except PsUnavailable:
            info = None
        if info and info["pgid"] == os.getpid() and f"--nonce {nonce}" in info["command"]:
            return info
        time.sleep(0.2)
    return None


def hold(args: argparse.Namespace) -> int:
    """Holder: register own identity, then lead the group, run the command, keep the group id pinned
    until no other process is left in it."""
    for number in HANDLED:
        signal.signal(number, lambda *_: None)  # caught, so the command execs with default dispositions
    record = pathlib.Path(args.record)

    def tell(text: str) -> None:
        try:
            os.write(args.notify_fd, text.encode())
        except OSError:
            pass  # the launcher is gone; the record is what counts

    info = own_identity(args.nonce)
    if info is None:
        print("run-procs: holder cannot verify its own identity; command not started", file=sys.stderr)
        update_record(record, state="not-started", reason="holder could not verify its own identity")
        return 1
    cancelled = pathlib.Path(f"{record}.cancel")
    if cancelled.exists():  # early out: nothing registered, nothing started
        update_record(record, state="not-started", reason="launch cancelled before the command started")
        return 0
    update_record(record, state="running", pid=os.getpid(), pgid=os.getpid(), lstart=info["lstart"], started_at=now())
    if cancelled.exists():  # registered first, checked second: a `stop` that saw "starting" is seen here
        update_record(record, state="not-started", reason="launch cancelled before the command started")
        return 0
    tell("started\n")
    try:
        code = subprocess.Popen(args.command, env={**os.environ, **BUILD_SERVER_ENV}).wait()
    except OSError as error:
        print(f"run-procs: cannot start {args.command[0]}: {error}", file=sys.stderr)
        code = 127
    pathlib.Path(f"{record}.exit").write_text(f"{code}\n", encoding="utf-8")
    if args.report_exit:
        tell(f"{code}\n")
    os.close(args.notify_fd)
    while True:
        try:
            if not group_members(os.getpgrp(), holder=os.getpid()):
                break
        except PsUnavailable:
            pass  # unknown is not empty: keep the group id pinned
        time.sleep(POLL)
    pathlib.Path(f"{record}.closed").write_text(now() + "\n", encoding="utf-8")
    return 0


def start_holder(argv: list[str], **kwargs) -> subprocess.Popen:
    return subprocess.Popen(argv, **kwargs)


def launch(args: argparse.Namespace, foreground: bool):
    """Validate, then create the `starting` record. Returns (record path, nonce, opened log or None)."""
    if args.cwd and not os.path.isdir(args.cwd):
        raise SystemExit(f"run-procs: --cwd is not a directory: {args.cwd}")
    log = None if foreground else open(args.log, "ab")
    registry = pathlib.Path(args.registry).resolve()
    registry.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = args.name or f"{pathlib.Path(args.command[0]).name}-{stamp}-{secrets.token_hex(2)}"
    record_path = registry / f"{name}.json"
    nonce = secrets.token_hex(16)
    try:
        create_exclusive(record_path, {  # names are never reused
            "name": name, "state": "starting", "created_at": now(), "launcher_pid": os.getpid(), "nonce": nonce,
            "command": args.command, "cwd": os.path.abspath(args.cwd or "."),
            "log": os.path.abspath(args.log) if log else None})
    except FileExistsError:
        raise SystemExit(f"run-procs: record name already used: {record_path}") from None
    return record_path, nonce, log


def spawn(args: argparse.Namespace, foreground: bool, record_path: pathlib.Path, nonce: str, log):
    read_fd, write_fd = os.pipe()
    argv = [sys.executable, os.path.abspath(__file__), HOLD, "--record", str(record_path), "--nonce", nonce,
            "--notify-fd", str(write_fd)]
    if foreground:
        argv.append("--report-exit")
    try:
        holder = start_holder(
            [*argv, "--", *args.command], cwd=args.cwd, start_new_session=True,
            stdin=None if foreground else subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT if log else None, pass_fds=(write_fd,))
    except OSError:
        os.close(read_fd)
        update_record(record_path, state="not-started", reason="holder could not be spawned")
        raise
    finally:
        os.close(write_fd)
        if log:
            log.close()
    return holder, read_fd


def verified(record: dict) -> bool:
    info = describe(record["pid"])
    return bool(
        info and info["pgid"] == record["pgid"] == record["pid"] and info["lstart"] == record["lstart"]
        and f"--nonce {record['nonce']}" in info["command"]
    )


def wait_until(predicate, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def signal_group(pgid: int, number: int) -> None:
    try:
        os.killpg(pgid, number)
    except ProcessLookupError:
        pass


def holder_process_exists(nonce: str) -> bool:
    """Only a wait hint, never a signalling target: is a process with this launch's nonce in its argv alive?"""
    return any(f"--nonce {nonce}" in line for line in ps_lines("-A", "-o", "command="))


def cancel_launch(record_path: pathlib.Path) -> dict:
    """A launch that never registered. Create the cancel marker first: a holder registers before it checks the
    marker, so any holder that is not yet registered will exit without starting the command. Then give a live
    holder a moment to settle the record."""
    with open(f"{record_path}.cancel", "a"):
        pass
    deadline = time.monotonic() + LAUNCH_WAIT
    record = read_record(record_path)
    while record.get("state") == "starting" and time.monotonic() < deadline:
        if not holder_process_exists(record.get("nonce", "")):
            record = read_record(record_path)
            break
        time.sleep(0.1)
        record = read_record(record_path)
    if record.get("state") == "starting":
        record = update_record(record_path, state="not-started", reason="launch cancelled before a holder registered")
    return record


def stop_one(record_path: pathlib.Path, grace: float) -> str:
    """Stop one registered group. Returns stopped, exited, not-started, skipped or refused."""
    try:
        record = read_record(record_path)
    except RecordError as error:
        print(f"REFUSE {error}")
        return "refused"
    name = record["name"]
    try:
        if record.get("state") == "starting":
            record = cancel_launch(record_path)
        if record.get("state") == "not-started":
            print(f"NOT-STARTED {name}: {record.get('reason', 'the command was never started')}; nothing is running")
            return "not-started"
        if record.get("state") != "running":
            print(f"SKIP {name}: state {record.get('state')}")
            return "skipped"
        return stop_running(record_path, record, grace)
    except PsUnavailable as error:
        print(f"REFUSE {name}: cannot read the process table ({error}); nothing was signalled")
        return "refused"
    except RecordError as error:
        print(f"REFUSE {error}")
        return "refused"


def stop_running(record_path: pathlib.Path, record: dict, grace: float) -> str:
    name, pgid, holder = record["name"], record["pgid"], record["pid"]
    if not verified(record):
        seen = group_members(pgid)
        if seen:
            print(f"REFUSE {name}: holder {holder} is gone or not ours; "
                  f"pids {seen} in group {pgid} are unverified and were not signalled")
            return "refused"
        closed = pathlib.Path(f"{record_path}.closed").exists()
        record.update(state="exited" if closed else "exited-holder-lost", stopped_at=now())
        write_json(record_path, record)
        print(f"EXITED {name}: nothing left in group {pgid}")
        return "exited"
    targets = group_members(pgid, holder)
    if targets:
        signal_group(pgid, signal.SIGTERM)
        wait_until(lambda: settled(pgid, holder), grace)
    remaining = group_members(pgid, holder)
    still_ours = verified(record)
    if remaining and not still_ours:
        print(f"REFUSE {name}: holder left while {remaining} remain in group {pgid}; not signalled further")
        return "refused"
    if still_ours:
        signal_group(pgid, signal.SIGKILL)  # the group, not the holder alone: a command racing to start dies too
    if not wait_until(lambda: settled(pgid, None), 5):
        print(f"REFUSE {name}: group {pgid} still has {group_members(pgid)} after SIGKILL")
        return "refused"
    record.update(state="stopped", stopped_at=now(), sigterm=targets, sigkill=remaining)
    write_json(record_path, record)
    print(f"STOPPED {name}: group {pgid} sigterm={targets} sigkill={remaining}")
    return "stopped"


def records(registry: str, name: str | None) -> tuple[pathlib.Path, list[pathlib.Path] | None]:
    """Absolute registry and its record files; None when the registry directory does not exist."""
    folder = pathlib.Path(registry).resolve()
    if not folder.is_dir():
        return folder, None
    if name:
        path = folder / f"{name}.json"
        if not path.is_file():
            print(f"REGISTRY {folder}")
            print(f"REFUSE no record {path}")
            raise SystemExit(1)
        return folder, [path]
    return folder, sorted(folder.glob("*.json"))


def interrupt(number: int, _frame) -> None:
    raise Interrupted(number)


def finish(record_path: pathlib.Path | None, holder, grace: float) -> bool:
    """Cleanup after a launch: ignore further signals, stop the group. True when nothing was refused."""
    for number in HANDLED:
        signal.signal(number, signal.SIG_IGN)
    if record_path is None:
        return True
    outcome = stop_one(record_path, grace)
    if holder is not None and outcome != "refused":
        try:
            holder.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    return outcome != "refused"


def read_started(pipe) -> bool:
    return pipe.readline().strip() == "started"


def run(args: argparse.Namespace) -> int:
    for number in HANDLED:
        signal.signal(number, interrupt)
    record_path = holder = None
    code, started = 1, False
    try:
        record_path, nonce, log = launch(args, foreground=True)
        holder, read_fd = spawn(args, True, record_path, nonce, log)
        with os.fdopen(read_fd, "r") as pipe:
            started = read_started(pipe)
            if started:
                line = pipe.readline().strip()
                code = int(line) if line else 1
    except Interrupted as caught:
        code = 128 + caught.number
    finally:
        clean = finish(record_path, holder, args.grace)
    if not started and code == 1:
        print(f"run-procs: NOT-STARTED {record_path}: the command was never started", file=sys.stderr)
        return 125
    if not clean:
        print(f"run-procs: cleanup of {record_path.stem} refused; see REFUSE above", file=sys.stderr)
    return 128 - code if code < 0 else code


def start(args: argparse.Namespace) -> int:
    for number in HANDLED:
        signal.signal(number, interrupt)
    record_path = holder = None
    started = False
    try:
        record_path, nonce, log = launch(args, foreground=False)
        holder, read_fd = spawn(args, False, record_path, nonce, log)
        with os.fdopen(read_fd, "r") as pipe:
            started = read_started(pipe)
    except Interrupted:
        pass
    finally:
        for number in HANDLED:
            signal.signal(number, signal.SIG_IGN)
        if not started:
            finish(record_path, holder, 10)
    if not started:
        print(f"run-procs: NOT-STARTED {record_path}: the command was never started", file=sys.stderr)
        return 125
    record = read_record(record_path)
    print(f"STARTED {record['name']} pid={record['pid']} log={record['log']} record={record_path}")
    return 0


def stop(args: argparse.Namespace) -> int:
    folder, paths = records(args.registry, args.name)
    if paths is None:
        print(f"NO-REGISTRY {folder}: directory does not exist, nothing was ever started there; nothing to stop")
        return 0
    print(f"REGISTRY {folder} records={len(paths)}")
    counts: dict[str, int] = {}
    for path in paths:
        outcome = stop_one(path, args.grace)
        counts[outcome] = counts.get(outcome, 0) + 1
    print("SUMMARY " + " ".join(f"{label}={counts.get(label, 0)}"
                                for label in ("stopped", "exited", "not-started", "skipped", "refused")))
    return 1 if counts.get("refused") else 0


def list_records(args: argparse.Namespace) -> int:
    folder, paths = records(args.registry, None)
    if paths is None:
        print(f"NO-REGISTRY {folder}: directory does not exist, nothing was ever started there")
        return 0
    print(f"REGISTRY {folder} records={len(paths)}")
    for path in paths:
        try:
            record = read_record(path)
        except RecordError as error:
            print(f"UNREADABLE {error}")
            continue
        exit_file = pathlib.Path(f"{path}.exit")
        code = exit_file.read_text().strip() if exit_file.exists() else "-"
        try:
            alive = record.get("state") == "running" and verified(record)
            members = group_members(record["pgid"], record["pid"]) if alive else []
            holder = "verified" if alive else "absent"
        except PsUnavailable:
            members, holder = [], "unknown"
        print(f"{record['name']} state={record.get('state')} holder={holder} "
              f"exit={code} members={members} command={' '.join(record.get('command', []))}")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == HOLD:
        parser = argparse.ArgumentParser(prog=f"run-procs.py {HOLD}")
        parser.add_argument("--record", required=True)
        parser.add_argument("--nonce", required=True)
        parser.add_argument("--notify-fd", type=int, required=True)
        parser.add_argument("--report-exit", action="store_true")
        parser.add_argument("command", nargs="+")
        return hold(parser.parse_args(sys.argv[2:]))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("run", "start"):
        sub = commands.add_parser(action)
        sub.add_argument("registry")
        sub.add_argument("--name")
        sub.add_argument("--cwd")
        if action == "run":
            sub.add_argument("--grace", type=float, default=10)
        else:
            sub.add_argument("--log", required=True)
        sub.add_argument("command", nargs="+")
    sub = commands.add_parser("stop")
    sub.add_argument("registry")
    sub.add_argument("--name")
    sub.add_argument("--grace", type=float, default=10)
    sub = commands.add_parser("list")
    sub.add_argument("registry")
    args = parser.parse_args()
    return {"run": run, "start": start, "stop": stop, "list": list_records}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
