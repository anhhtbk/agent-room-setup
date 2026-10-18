# Architecture

## Control flow

```text
~/.paseo/config.json
  custom provider command
      |
      v
~/.local/bin/codex-room <role>
      |
      +-- codex-room-sync <role>
      |     +-- reads ~/.codex/config.toml
      |     +-- reads ~/.config/codex-room/overlays/<role>.config.toml
      |     +-- reads codex debug models
      |     `-- writes ~/.codex-runtime/<role>/
      |
      `-- CODEX_HOME=~/.codex-runtime/<role> codex ...
```

Claude Code and oh-my-pi roles use the same overlays through a second launcher:

```text
~/.paseo/config.json
  claude-<role> / omp-<role> / pi-<role> provider command
      |
      v
~/.local/bin/agent-room <claude|omp|pi> <role> <Paseo args...>
      |
      +-- reads developer_instructions from overlays/<role>.config.toml
      +-- claude: merges a SessionStart hook into --settings,
      |           adds Agent,Workflow to --disallowedTools
      +-- omp:    --config ~/.config/codex-room/omp-room.config.yml,
      |           merges the role into --append-system-prompt
      +-- pi:     adds an additive --append-system-prompt for the role
      `-- exec claude|omp|pi with the operator's own home
```

No per-role home is generated for these runtimes. Relocating
`CLAUDE_CONFIG_DIR` re-keys the macOS Keychain login, and relocating the omp
agent directory moves its credential database, so each role would need its
own login. Role policy is therefore per process:

- **Role instructions.** Claude's Agent SDK host (Paseo) sends its own
  system-prompt append over the control channel, which replaces an argv
  `--append-system-prompt`. A `SessionStart` hook is used instead; it also
  re-injects the role after resume, clear, and compaction. omp keeps only the
  last `--append-system-prompt`, so the launcher folds Paseo's value into one
  merged flag.
  Pi appends are additive; the launcher adds its role flag before unchanged
  host arguments, leaving Pi to parse text/files and message delimiters.
  It does not pass omp's YAML overlay or relocate `PI_CODING_AGENT_DIR`.
  Explicit append flags disable Pi's implicit `APPEND_SYSTEM.md` discovery;
  operators can pass that file explicitly as another append.
- **Pi MCP compatibility.** A room-managed `pi-mcp-adapter.mjs` implements
  the host's per-session `--mcp-config` protocol using Pi >=1.3.0's
  native MCP API. It retains the builtin MCP extension and preserves
  operator-owned configuration. This is separate from Paseo's prompt/history
  extension, which does not deliver orchestration tools. Because Paseo now
  follows the latest stable release, the adapter also stops a Paseo-started
  Supervisor/Lead session that arrives without the `paseo` MCP server, and
  install/verify/doctor warn when a release fails the contract probe.
- **Native subagents off.** Claude denies `Agent` and `Workflow`; omp sets
  `task.maxRecursionDepth: 0`, which removes its `task` tool. Delegation goes
  through Paseo roles, matching the Codex runtimes.
  Pi has no built-in subagents. Custom Pi extensions remain operator-owned;
  the role contract is not a sandbox for arbitrary extension code.
- **Probes pass through.** `--version`, `--help`, and subcommands such as
  `auth status` run unchanged; any invocation starting with another flag, or
  with no arguments, is a role session.
  Pi also treats positional messages as sessions; only its known maintenance
  commands pass through. Literal arguments after `--` remain messages.

Codex-only overlay keys (`model`, `sandbox_mode`, `approval_policy`, ...) do not
apply to Claude/omp/Pi; model and thinking come from the Paseo
agent settings.
Pi does not expose an approval/sandbox mode equivalent to Codex.

## Ownership

| Layer | Owner | Mutable state |
| --- | --- | --- |
| `~/.codex` | Operator/Codex | Auth, global config, skills, plugins, sessions |
| `~/.config/codex-room` | This repository | Role overlays, omp overlay, Pi MCP compatibility extension, and the workspace protocol reference |
| `~/.claude`, `~/.omp`, `~/.pi` | Operator and their runtimes | Auth, settings, skills, sessions (never written by this repository's setup) |
| `~/.codex-runtime` | `codex-room-sync` | Generated configs plus role-local sessions and databases |
| `~/.paseo` | Paseo | Provider config, agents, projects, worktrees, logs and identity |
| Paseo stable release checkout | Git | Source code for CLI, daemon and Desktop |

## Runtime merge

For a role, the sync script:

1. Reads the operator's Codex user config as the base.
2. Replaces an allowlisted set of top-level scalar values from the role overlay.
3. Adds role-specific `developer_instructions`.
4. Generates a model catalog with native multi-agent metadata removed.
5. Forces `[agents].enabled = false` and all native multi-agent feature flags off.
6. Symlinks shared Codex resources and the common model instructions.

Supervisor, Lead, and Peer retain a canonical
`plugins -> ~/.codex/plugins` symlink. Existing additional runtime directories
and private workflow files are not generated, inspected, migrated, or removed.
The launcher has one public route: it accepts one of the three retained roles,
regenerates that role's runtime, and starts Codex with its isolated
`CODEX_HOME`.

The retained `WORKSPACE_PROTOCOL.md` is not linked into role runtimes. Each
workspace can provide its own `docs/WORKSPACE_PROTOCOL.md`.

CLI flags and trusted project `.codex/config.toml` files can still override generated user-level values according to normal Codex precedence.
