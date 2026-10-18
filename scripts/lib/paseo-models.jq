# Paseo shows exactly the Room model set; a static `models` list replaces each
# runtime's discovered catalog. Base `codex` is disabled because its runtime
# catalog does not offer Astra or Sol 6.1; the codex-* roles list them directly.
{
  claude: ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5"],
  codex: ["gpt-6-astra", "gpt-6.1-sol"],
  omp: ["anthropic/claude-fable-5-1", "anthropic/claude-opus-5-5", "anthropic/claude-sonnet-5-5",
        "openai-codex/gpt-6-astra", "openai-codex/gpt-6.1-sol"],
  pi: ["openai-codex/gpt-6-astra", "openai-codex/gpt-6.1-sol"]
} as $allowed |
def one_default: (map(select(.isDefault == true)) | length) == 1;
.agents.providers as $providers |
($providers.codex.enabled == false) and
([$allowed | keys[] as $runtime | $runtime, ("supervisor", "lead", "peer" | "\($runtime)-\(.)")]
  | map(select(. != "codex")) as $listed |
  all($listed[]; . as $id | ($id | split("-")[0]) as $runtime | $providers[$id].models as $models |
    ($models | type) == "array" and ($models | length) > 0 and
    ($models | map(.id) | unique | length) == ($models | length) and
    all($models[]; .id as $m | $allowed[$runtime] | index($m) != null) and
    ($models | one_default) and
    all($models[]; (.thinkingOptions | type) == "array" and (.thinkingOptions | length) > 0
      and (.thinkingOptions | one_default))))
