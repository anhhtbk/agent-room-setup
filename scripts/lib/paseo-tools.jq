# All known providers need an explicit policy: upstream defaults to enabled.
# Room roles exist for every runtime; only Supervisor and Lead get Paseo tools.
["codex", "claude", "omp"] as $runtimes |
.daemon.mcp.enabled == true and
.daemon.mcp.injectIntoAgents == true and
(.daemon.mcp | has("injectIntoProviders") | not) and
(.agents.providers as $providers |
  (["claude", "codex", "copilot", "opencode", "pi", "omp"]
    + [$runtimes[] as $runtime | ("supervisor", "lead", "peer") | "\($runtime)-\(.)"] |
    all(.[]; . as $id | $providers | has($id)))
) and
(.agents.providers | to_entries | all(.[];
  .value.paseoTools.enabled ==
    (.key as $id | [$runtimes[] | "\(.)-supervisor", "\(.)-lead"] | index($id) != null)
))
