# Paseo shows exactly the Room model set; a static `models` list replaces each
# runtime's discovered catalog. GPT models are disabled: every codex and pi
# provider (GPT-only) must stay disabled, and omp lists Claude models only.
{
  claude: ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5"],
  codex: ["gpt-6-astra", "gpt-6.1-sol"],
  omp: ["anthropic/claude-fable-5-1", "anthropic/claude-opus-5-5", "anthropic/claude-sonnet-5-5"],
  pi: ["openai-codex/gpt-6-astra", "openai-codex/gpt-6.1-sol"]
} as $allowed |
def one_default: (map(select(.isDefault == true)) | length) == 1;
.agents.providers as $providers |
([$allowed | keys[] as $runtime | $runtime, ("supervisor", "lead", "peer" | "\($runtime)-\(.)")]) as $ids |
all($ids[] | select(startswith("codex") or startswith("pi")); $providers[.].enabled == false) and
($ids | map(select(. != "codex")) as $listed |
  all($listed[]; . as $id | ($id | split("-")[0]) as $set | $providers[$id].models as $models |
    ($models | type) == "array" and ($models | length) > 0 and
    ($models | map(.id) | unique | length) == ($models | length) and
    all($models[]; .id as $m | $allowed[$set] | index($m) != null) and
    ($models | one_default) and
    all($models[]; (.thinkingOptions | type) == "array" and (.thinkingOptions | length) > 0
      and (.thinkingOptions | one_default))))
