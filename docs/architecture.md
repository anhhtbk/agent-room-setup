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
  claude-<role> / omp-<role> provider command
      |
      v
~/.local/bin/agent-room <claude|omp> <role> <Paseo args...>
      |
      +-- reads developer_instructions from overlays/<role>.config.toml
      +-- claude: merges a SessionStart hook into --settings,
      |           adds Agent,Workflow to --disallowedTools
      +-- omp:    --config ~/.config/codex-room/omp-room.config.yml,
      |           merges the role into --append-system-prompt
      `-- exec claude|omp with the operator's own home (~/.claude, ~/.omp)
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
- **Native subagents off.** Claude denies `Agent` and `Workflow`; omp sets
  `task.maxRecursionDepth: 0`, which removes its `task` tool. Delegation goes
  through Paseo roles, matching the Codex runtimes.
- **Probes pass through.** `--version`, `--help`, and subcommands such as
  `auth status` run unchanged; any invocation starting with another flag, or
  with no arguments, is a role session.

Codex-only overlay keys (`model`, `sandbox_mode`, `approval_policy`, ...) do not
apply to Claude/omp; model, thinking, and permission mode come from the Paseo
agent settings.

## Ownership

| Layer | Owner | Mutable state |
| --- | --- | --- |
| `~/.codex` | Operator/Codex | Auth, global config, skills, plugins, sessions |
| `~/.config/codex-room` | This repository | Role overlays, omp overlay, and the workspace protocol reference |
| `~/.claude`, `~/.omp` | Operator/Claude Code, omp | Auth, settings, skills, sessions (read by `agent-room` roles, never written by this repository) |
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
