# Provider profiles

The live template defines three derived providers per runtime: Supervisor,
Lead, and Peer.

- `codex-<role>` extends `codex`; its `command` launches `codex-room`, which
  selects an isolated runtime through `CODEX_HOME`.
- `claude-<role>` and `omp-<role>` extend `claude`/`omp`; their `command`
  launches `agent-room <runtime> <role>`, which applies the role to the
  operator's own Claude Code/omp installation without relocating its home.

`models` is a replacement catalog for each custom profile. `additionalModels`
would be additive; this setup does not currently use it. Claude and omp role
providers declare no `models`, so they inherit the runtime's discovered catalog.
Paseo ignores `params` for derived Claude providers.
