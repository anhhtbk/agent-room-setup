# Provider profiles

The live template defines three derived providers per runtime: Supervisor,
Lead, and Peer.

- `codex-<role>` extends `codex`; its `command` launches `codex-room`, which
  selects an isolated runtime through `CODEX_HOME`.
- `claude-<role>` and `omp-<role>` extend `claude`/`omp`; their `command`
  launches `agent-room <runtime> <role>`, which applies the role to the
  operator's own Claude Code/omp installation without relocating its home.

`models` is a replacement catalog for each provider. Every Room role and the
base `claude`, `omp`, and `pi` providers declare a static list limited to the
Room model set (see `docs/profiles-and-overlays.md`), so none inherits its
runtime's discovered catalog; base `codex` is disabled instead. `additionalModels`
would be additive; this setup does not use it. Paseo ignores `params` for derived
Claude providers.
