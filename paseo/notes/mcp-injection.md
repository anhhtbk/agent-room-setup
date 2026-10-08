# Paseo tool delivery

`daemon.mcp.enabled` and `daemon.mcp.injectIntoAgents` are true.
Each exact provider ID has an explicit `paseoTools.enabled` policy:

- `codex-supervisor`, `codex-lead`, `claude-supervisor`, `claude-lead`,
  `omp-supervisor`, `omp-lead`: true.
- `codex-peer`, `claude-peer`, `omp-peer`, and all other configured/built-in
  providers: false.

Peer receives neither the Paseo MCP server nor the native Paseo tool catalog.
`injectIntoProviders` was specific to the retired fork and must not be retained.
Upstream defaults to enabled for a missing policy; new providers must explicitly
opt out unless they are Supervisor or Lead. `extends` does not inherit the policy.
Restart/reload an agent session to apply a changed policy to that session.
