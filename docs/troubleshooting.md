# Troubleshooting

## A role still uses an old model

Cause: the overlay changed but the generated runtime was not refreshed.

```bash
scripts/sync-all <role>
grep -E '^(model|model_reasoning_effort) =' "$HOME/.codex-runtime/<role>/config.toml"
```

## `codex-room-sync` cannot find a shared resource

The operator's `~/.codex` is incomplete for this setup. Check the exact missing path reported by the script. This repository will not create or overwrite it.

## Paseo does not show custom providers

1. Validate `~/.paseo/config.json` with `jq`.
2. Confirm Codex role commands point to `~/.local/bin/codex-room` and Claude/omp/Pi
   role commands point to `~/.local/bin/agent-room`.
3. Confirm `~/.local/bin` is on the daemon's PATH.
4. Restart Paseo when no agent is running.
5. Run `./install --verify`.

## A `claude-*`, `omp-*`, or `pi-*` role is unavailable or ignores its role

1. Run `paseo provider diagnostic claude-lead` (or `omp-lead`/`pi-lead`): Paseo probes
   `agent-room <runtime> <role> --version`, so the runtime must be on the
   daemon's PATH or set through `CLAUDE_BIN`/`OMP_BIN`/`PI_BIN`.
2. `agent-room` fails before exec when the role overlay has no
   `developer_instructions` or the omp-specific `omp-room.config.yml` is missing.
3. `agent-room` needs Python 3.11+ (`tomllib`). When the daemon PATH resolves
   `python3` to an older interpreter (macOS `/usr/bin/python3` is 3.9), it
   re-execs under the first `python3.14`…`python3.11` on that PATH and fails
   with `requires Python 3.11+` when none is found.
4. Claude receives the role from a `SessionStart` hook; setting
   `disableAllHooks` in operator Claude settings removes it.
5. Role changes apply to new sessions only.
6. Pi is pi.dev, not omp: check `agent-room pi lead --version`. Pi roles use
   `--mode rpc`; do not add omp's `--config` or `rpc-ui` flags. Pi custom
   extensions can rewrite prompts/tools; inspect those separately when
   debugging role behavior. Setup does not alter `~/.pi/agent` or credentials.
7. Pi orchestration requires >=1.3.0 and the managed
   `~/.config/codex-room/pi-mcp-adapter.mjs`. Do not disable/replace builtin
   MCP. A native `mcp.json` entry shadowing the injected Paseo server must
   be resolved by the operator; setup will not overwrite it.
8. An interactive `agent-room pi lead` alone has no Paseo endpoint/token.
   Use `pi-lead` or `pi-supervisor` through Paseo for automatic orchestration
   delivery. Provider policy or `get_state` success alone does not prove tools
   arrived.
8. `pi-supervisor`/`pi-lead` exits at startup with "started this Room ... session
   without the paseo MCP server": the installed Paseo release no longer delivers
   Paseo tools the way Room's adapter expects, or `paseoTools`/`daemon.mcp` is
   disabled. `scripts/doctor` shows the release and the contract result. Pi Peer
   and the other runtimes keep working; update the Room adapter for that release.
9. Every `pi-*` role fails with `Flag "--mcp-config" conflicts with
   .../pi-mcp-adapter.mjs`: a third-party `pi-mcp-adapter` package in the Pi
   agent directory registers the same flag and `/mcp`. Known limitation on the
   operator machine (2026-10-19), deferred while Pi is unused; see
   `paseo/notes/pi-integration.md`. Setup does not remove operator packages.

## Daemon PID and listener disagree

Compare the PID file with the actual listener:

```bash
cat "$HOME/.paseo/paseo.pid"
lsof -nP -iTCP:6767 -sTCP:LISTEN
```

A wrapper PID and child Node PID can differ. Diagnose before deleting PID or state files.
