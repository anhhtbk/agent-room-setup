# Profiles and overlays

The word “profile” appears at three different levels:

1. **Paseo custom provider:** `codex-<role>` extends the built-in Codex adapter; `claude-<role>` and `omp-<role>` extend the Claude Code and oh-my-pi adapters.
2. **Codex Room overlay:** a focused TOML fragment. Codex merges it into a generated `CODEX_HOME`; `agent-room` reads only its `developer_instructions` for Claude/omp.
3. **Native Codex profile:** selected through `codex --profile`; this room does not use that mechanism.

Changing a Paseo provider model affects the model picker and Paseo default. Changing an overlay affects the Codex process default after the next sync. Keep both aligned deliberately. Claude/omp role providers inherit their runtime's model catalog; an overlay's `developer_instructions` change reaches them on the next new session without a sync.

The selected defaults as of 2026-10-01 are Lead `gpt-6-astra` / `medium`,
Supervisor and Peer `gpt-6.1-sol` / `medium`. This is an explicit operator
choice, not an inferred model upgrade. Keep provider defaults, role overlays,
generated runtime defaults, and the README aligned. Existing sessions retain
their selected models; changing defaults does not migrate running sessions.
Non-default model choices are preserved.

Alignment verification accepted on 2026-10-01: `scripts/verify --source`
compares each provider's unique default model and reasoning effort with its
parsed role overlay. Installed verification additionally compares generated
runtime defaults. This intentionally checks consistency without hardcoding
model names; it does not prove model availability or active-session settings.
Python 3.11+ with `tomllib` is required (`CODEX_ROOM_TOML_PYTHON` can select it).
Acceptance evidence: `make test` under Python 3.12 passed all 64 existing tests;
the separate `test_model_alignment.py` run passed 10 additional tests, including
negative cases and source/installed verifier wiring. Source verification and
the alignment helper against the installed providers, overlays, and runtimes
passed. The default system Python 3.9 run failed an existing `tomllib` import;
the Python 3.12 rerun passed. Full installed-system verification and model
response quality are not claimed by this acceptance.

## Instruction revision — approved and synced (2026-10-01)

The source Lead/Supervisor overlays now emphasize outcome-driven scope,
continuation after resolved decisions, and faithful routing of ambiguous intent.
Lead keeps proposed implementation choices separate from binding requirements;
Supervisor checks usable progress as well as communication closure and verifies
alert evidence before alleging a missing response. These replace or refine
existing guidance, without adding a review gate, role, or tracker.

Review cases: an approved manual exception should unblock already-authorized
implementation, not authorize real deletion; a later release requirement should
not silently block an earlier bounded task; a product-vision request should not
become a layout directive; an incomplete alert should prompt source inspection,
not a claim that the Peer failed. Correctly closed local slices can still need a
Lead decision about the shortest useful integration path.

Human approved committing, pushing, and syncing this revision after review.
The Lead/Supervisor installed overlays were updated and `scripts/sync-all`
regenerated all three role runtimes. Running sessions were not restarted or
claimed to have reloaded their instructions. Peer instructions, model defaults, the shared protocol,
ownership, external-action authority and heartbeat lifecycle are unchanged by
this revision. Static validation does not prove improved agent behavior; that
requires observation on subsequent work using the revised instructions.

Source review accepted: a fresh read-only Peer checked the exact Lead
`fa15680d61b98` and Supervisor `5e98ff4005c7` SHA-256 candidates against the shared
contract and the cases above; Lead inspected the diff and accepted them for
Human review, not rollout. `make test` with Python 3.12 passed all 74 tests plus
compile/shell checks; `scripts/verify --source` returned `VERIFY_OK` and
`git diff --check` passed. These checks cover configuration/integration, not
agent behavior. No new phrase-matching tests or behavioral-success claim added.

The Peer overlay owns one bounded implementation, investigation, architecture,
or read-only candidate review outcome. Peer has no Paseo MCP injection and its
role instructions forbid coordinating other seats.

The sync allowlist is intentionally small. New top-level role-specific keys must be added to `OVERRIDE_KEYS` in `codex-room-sync` and covered by tests.

Retired role entrypoints are backed up and removed during install. Existing
runtime directories and private operator files remain untouched.
