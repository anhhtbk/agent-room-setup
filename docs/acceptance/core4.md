# Minimum core acceptance record

This record is the release handoff for the composed minimum core. It covers
the public installation lifecycle and the evidence that remains for the one
consolidated Human review of CORE-2, CORE-3, CORE-4, and the Epic.

## Public contract

From a clean clone, an operator prepares the common dependencies and runs
(an authenticated Codex home is optional):

```bash
./install
./install --apply
paseo daemon start
./install --verify
```

The first command is read-only. Apply stages the latest stable Paseo checkout, the
managed HOME files, and, when Codex prerequisites are available, the Supervisor,
Lead, and Peer Codex runtimes as one transaction. Verification is read-only and includes the live provider
inventory, so it requires a reachable Paseo daemon. `scripts/verify` and the
other lower-level scripts are maintenance interfaces for an already installed
room.

The room defines three derived providers per runtime (`codex-*`, `claude-*`,
`omp-*`, `pi-*`). The policy enables Paseo tools for Supervisor and Lead and
disables automatic injection for Peer. Pi delivery is accepted within the
verification boundaries below. Human retains product, cost, external-effect, and irreversible-risk
decisions. Supervisor routes intent, Lead owns technical acceptance, and Peer
owns one bounded outcome at a time.

Repeated apply regenerates managed outputs while preserving operator
`~/.codex` bytes, existing role sessions and databases, and private legacy
runtime directories. Only recognized, unchanged obsolete artifacts are retired;
customized or redirecting artifacts are preserved with a warning. Transaction
backups are owner-only. The installer does not authenticate Codex, start the
daemon, manage operator credentials, or install Desktop GUI state.

## Room model set — technical ACCEPT (2026-10-19)

Base: `a36a34e`. Human decision: Paseo lists only Claude Fable 5.1, Opus 5.5,
Sonnet 5.5, GPT 6 Astra and GPT 6.1 Sol, within what each runtime can run, as a
static list (no availability check). Defaults chosen by Human after Lead
reported that omp (first catalog entry `anthropic/claude-3-5-sonnet-20240620`),
Pi (operator setting `openai-codex/gpt-5.6-sol`) and base Codex fell outside the
set: omp/`omp-*` default `anthropic/claude-opus-5-5` with runtime thinking `low`;
`pi`/`pi-*` default `openai-codex/gpt-6.1-sol` Medium; base `codex` disabled
because its runtime catalog has neither Astra nor Sol 6.1. Claude roles keep
Claude Code's default Opus 5.5 (medium); `codex-*` keep overlay defaults.

Evidence: an isolated Paseo v0.11.4 daemon (temporary home, port 6799, relay
off; the operator daemon and `~/.paseo/config.json` untouched) loaded the
rendered template and listed exactly — with thinking options and defaults —
`claude`/`claude-lead`/`claude-peer`: the three Claude models; `codex-*`: Astra
and Sol 6.1 (low…max); `omp-*` and temporarily enabled `omp`: the five prefixed
models (auto, low…max); `pi` and `pi-*`: the two `openai-codex/` GPT models
(minimal…max); base `codex` disabled. `paseo-models.jq` and `paseo-tools.jq`
passed on the template; model-alignment against overlays passed;
`./scripts/verify --source` `VERIFY_OK`; release, alignment and full suites below.

Limits: models were listed, not run; Codex's runtime catalog on this machine does
not list Astra/Sol 6.1, so their runnability on `codex-*` rests on the existing
overlay, not this check. With the operator's real `~/.pi/agent`, `pi-*` cannot
start: the third-party `pi-mcp-adapter` npm package there also registers
`--mcp-config` and `/mcp`, conflicting with Room's adapter and disabling
builtin MCP. The `pi-*` lists were therefore shown with an empty temporary Pi
agent directory. That conflict predates this change and is not fixed here.
Human decision (2026-10-19): Pi is not in use for now; keep `~/.pi` unchanged,
do not remove the package or change the adapter. Deferred until Human resumes
Pi; that decision (remove the package or adapt Room's adapter) returns then.
Base `omp` stays disabled by Paseo default; its list applies if enabled.

## Paseo latest-stable channel — technical ACCEPT (2026-10-19)

Base: `fb45d23fdfc7fffae1731056116dd1ad7899d69b`. Human decision: setup always
installs the newest published stable Paseo release instead of the v0.9.2 pin,
and two installs may yield different versions. Human chose the reaction to a
release that breaks the Pi contract: **install anyway with a warning**;
install/update/verify/doctor only warn, Pi Supervisor/Lead fail at startup with
the reason, and Pi Peer, Codex, Claude and omp are unaffected. Lead implemented
directly (no Peer dispatch). Commit is local only; push needs separate approval.

Kept protections: official source only, tag→commit resolved once and re-checked
before dependency work and after fetch, staging plus transaction rollback,
release recorded in `git config codex-room.paseoRelease` and shown by plan,
apply, verify and doctor. Public installer refuses `PASEO_RELEASE_TAG` /
`PASEO_VERIFIED_COMMIT` overrides.

Evidence (actual results):

- Official release list on 2026-10-19: latest stable `v0.11.4`
  (`dc5b02f7d7c120baea380d76def8b968020d8823`); `v0.12.0-beta.1..3` ignored.
  `paseo-release.py resolve` printed exactly that pair.
- v0.11.4 source vs v0.9.2: `paseo-tool-policy.ts` and `runtime-mcp-config.ts`
  identical; Pi argv construction unchanged; adapter predicate still precedes
  the new builtin-MCP path. Provider schema now accepts `options` (old `params`
  remains supported until 2027-03-30).
- Real isolated `scripts/install-paseo --preflight` (temporary HOME/npm cache,
  official source): resolved v0.11.4, `npm ci`, `build:server:clean`, CLI help,
  then `PI_CONTRACT_OK policy=exact-id delivery=paseo-mcp`; `PASEO_PREFLIGHT_OK`,
  exit 0, about 160 s.
- Real v0.11.4 `PiRpcAgentClient` + production `agent-room` + real Pi 1.3.0,
  loopback MCP fixture, no model: Lead and Supervisor started and the fixture
  saw `initialize`/`tools/list` with caller and bearer; Lead with no delivered
  `paseo` server exited 1 with "started this Room lead session without the paseo
  MCP server"; Peer without injection started. Standalone `agent-room pi lead`
  RPC `get_state` succeeded.
- `python3 -m unittest discover -s tests`: **134 tests OK** (177.5 s), offline
  with local Git/release fixtures: newer main/beta/draft ignored, highest
  version wins, listed-but-untagged and prerelease/draft-only metadata refused,
  coordinator-resolved tag moved before lookup refused, tag moved between
  lookup and fetch refused, annotated tags, fork migration and rollback,
  updater fast-forward and moved-tag refusal, recorded release, warning-only
  contract in verify, override refusal.
- `./scripts/verify --source`: `VERIFY_OK`; shell/zsh/Node/Python syntax and
  `git diff --check` passed.

Not exercised: a full `./install --apply` into a temporary HOME with the real
v0.11.4 build, Desktop build/sign/replace via `paseo-local-update`, a live
daemon with a model-driven Pi tool call, and Docker container acceptance. A
future release failing the contract was simulated only by withholding delivery,
not by a real incompatible release.

## Pi integration — technical ACCEPT (2026-10-18)

Base: `d097d75516993b9ae5d56e859c95c461b2850153`. Lead owns implementation.
Research Peer owned only `paseo/notes/pi-integration.md`; Lead **ACCEPTS** its
research snapshot `8b9e31009d723ebb80110e3ffe9d730b66f06abc41373ef9ca16d738e5393366`
and **ACCEPTED the REOPEN_REQUEST** on MCP delivery. That dependency is now
resolved by the room-owned adapter and the execution/resume evidence below.
Lead **ACCEPTS the Pi working-tree candidate** on this base; no commit or push.
All Peer briefs are closed and repository ownership is back with Lead.

Pi 1.3.0 role/host prompt and RPC `get_state` smoke passed for all three roles
in temporary HOME. That does not prove orchestration tools are delivered.
Pinned Paseo rejects Pi's builtin MCP discovery signature and expects the old
`--mcp-config` interface. Its prompt/history extension does not register tools.
Setting `paseoTools.enabled` is policy, not delivery evidence.

Decision: Lead selects a room-owned compatibility extension using Pi 1.3.0's
native MCP registration API to implement the pinned Paseo `--mcp-config`
interface. No Paseo pin upgrade, upstream patch, or replacement of operator
MCP configuration is selected. The independent architecture brief is closed;
its accepted route and constraints are implemented in the accepted candidate.

Lead **ACCEPTS the bounded implementation for integration** after inspecting
both files and the writer's actual Pi 1.3.0 discovery/failure evidence:

- `home/.local/bin/agent-room`:
  `716adc239ac8d9128af7d11141939fdad4ce280d32bd6c8437d348b7893248ed`
- `home/.config/codex-room/pi-mcp-adapter.mjs`:
  `9d39bfb276ca453bbfa2c0b480d0bb27aec812ac8d14192054b36d7d92e8617b`

The writer brief is closed and both files are now Lead-owned. The implementation
uses actual native registration and exits 1 on startup delivery/configuration
failures rather than throwing an error Pi can swallow. Bounded implementation
acceptance was followed by the separate tool-execution/resume proof below;
registration and discovery alone were not treated as sufficient. Lead now owns
all repository changes and the handed-off temporary proof artifacts. No assignment
authorized authentication, external model calls or live daemon changes.
Lead also **ACCEPTS the fresh read-only candidate review** of these exact hashes:
no evidence-backed blocker was found in the launcher/bridge or lifecycle callers.
This is source/checksum evidence only; that Peer did not repeat runtime smoke.
Its brief is closed, with no write ownership or outstanding action.

- Register diagnostic command `mcp:1`, not `mcp`: Pi replaces its builtin when
  an extension registers the exact `mcp` command. The Peer withdrew its initial
  recommendation after checking the builtin exclusion logic. A real Pi 1.3.0
  prototype returned both adapter `mcp:1` and `builtin:mcp` through RPC.
  This proves discovery compatibility only, not tool delivery.
- Register the CLI flag at extension load; consume its value at session start.
- Remove only the legacy `auth:false` and `oauth:false` sentinels; preserve
  valid auth configuration and the per-session URL, caller identity and headers.
  Removing `oauth:false` alone does not disable native OAuth.
- Use direct exposure for the injected Paseo server, not all operator servers.
- Disabled/replaced builtin MCP or a native configuration shadowing the injected
  Paseo server must fail visibly, not masquerade as successful delivery.
  Preserve operator files; account for native namespace normalization.
- Keep exact-provider policy enabled for Supervisor/Lead and disabled for Peer.
  This prevents automatic injection; it is not a security sandbox.

The delivery dependency is closed: exact pinned-Paseo discovery and generated
per-session configuration reach Pi native MCP; real tool calls and resumed
caller/token identity were exercised. Peer policy prevents automatic injection.
Disabled builtin, native collision and malformed-config cases exit 1. The
installed launcher and apply/reapply/verify/doctor work without Pi or Codex in
PATH; actually launching a missing runtime fails with an actionable diagnostic.
No product-scope reduction or deferred implementation is used for acceptance.

Completed Lead integration checks:

- `python3 -m unittest discover -s tests`: **135 tests passed** (163.580s),
  including unsupported-Pi session rejection and Pi private-state preservation.
- `./scripts/verify --source`: `VERIFY_OK`; shell syntax, Python compilation
  and `node --check` on the managed adapter passed.
- Disposable copy with local Git/npm build fixtures and PATH containing
  neither Pi nor Codex: `./install`, `./install --apply` twice,
  `scripts/verify`, `scripts/doctor` all exited 0. No `.pi`, `.codex` or
  `.codex-runtime` was created by setup. Twelve role definitions installed;
  Pi policies were Supervisor/Lead true, Peer false.
- Installed launcher with actual Pi 1.3.0: all three roles returned successful
  RPC `get_state`, zero messages, correct role plus host append and unchanged
  custom agent-dir/settings. No model was invoked.
- `scripts/export-current --apply` and `scripts/uninstall --apply` on the
  disposable copy exited 0; export retained the adapter bytes, uninstall
  removed the managed adapter and preserved a private Pi state marker.
- Doctor returned 0 with warnings for unsupported Pi 0.84.4 and a failing
  optional version probe. Neither becomes a common setup prerequisite.

Lead smoke logs are under temporary root `room-pi-final-414b6wwd`:
`final-setup-{0..4}.log`, `role-{supervisor,lead,peer}.{json,log}`,
`doctor-*.log`, `export.log`, `uninstall.log` and `pinned-real-handler.log`.

Lead **ACCEPTS the bounded protocol proof** at
`/tmp/pi-mcp-proof.HbNG2i/run-cXKvTM/evidence.json` for the hashes above:
the exact pinned `PiRpcAgentClient`/`PiCliRuntime` generated session config,
the production launcher and Pi 1.3.0 CLI discovered native tools, and Pi's
native SDK executed `tools/call` against a loopback counter fixture.
Supervisor changed its counter 0→3 and Lead 0→5 with the expected caller and
bearer header. Peer exact-ID policy produced one launch, no config flag and no
fixture requests. That initial snapshot did not prove resume because an empty
session had not persisted. It is superseded for resume by the final proof below,
not retroactively counted as a resume pass.

Final proof disposition: **ACCEPT**.

- Peer evidence `run-ZD5qYW/evidence.json` under
  `/tmp/pi-mcp-proof.HbNG2i/` proves fresh config/caller/token and native
  discovery after actual pinned `resumeSession`, four SDK tool calls, and Peer
  opt-out. A user entry was seeded through `SessionManager` storage API to
  create a persisted session without a model call.
- Peer evidence `real-server-mo550F/evidence.json` exercises the actual pinned
  `createAgentMcpServer → createPaseoToolCatalog → list_agents` handler.
- Lead inspected the harness and source build entries, then independently ran
  `/opt/homebrew/bin/node /tmp/pi-mcp-proof.HbNG2i/proof-real-server.mjs`:
  **exit 0**, four real handler calls. Evidence:
  `/private/tmp/pi-mcp-proof.HbNG2i/real-server-ywknrk/evidence.json`.
  Both Supervisor and Lead returned only workspace A's visible record before
  resume and only workspace B's record with the new caller/token after resume;
  archived and other-workspace records were filtered out.

Evidence boundaries: CLI performs real probe/config/discovery; tool execution
uses Pi 1.3.0 native SDK tools directly, not model selection. The MCP server and
handler are pinned source, but manager/storage/provider data are isolated RAM
fixtures and HTTP auth middleware is loopback harness code. No live daemon,
real authentication, paid model turn or full model-driven delegation was tested.
These are unexercised deployment/runtime boundaries, not missing bridge code.
An early direct smoke of the historical npm 0.84.4 bundle failed on missing
`jiti` before extension loading. The final launcher rejects that unsupported
version at its version gate; this is not claimed as repairing the old bundle.

Isolation audit caveat: the proof Peer's initial dependency download installed
under `/tmp` but did not override npm HOME/cache. Zero writes to the real npm
cache cannot be certified for that download. Do not erase this uncertainty or
modify the global cache to conceal it. All Pi runtime runs used temporary
HOME/agentDir and scrubbed environments; Lead's independent run also supplied
a temporary npm cache. No global runtime installation or authentication was
performed.

Usable downstream: apply the repository through the normal installer, supply
an operator-installed/authenticated Pi >=1.3.0, and select `pi-supervisor`,
`pi-lead` or `pi-peer` in Paseo. Supervisor/Lead receive the native MCP catalog;
Peer does not receive automatic Paseo injection. Standalone `agent-room pi lead`
adds the role but does not manufacture a Paseo endpoint or credentials.
The four-runtime outcome remains unchanged. Technical acceptance does not
authorize commits, pushes, deployment or installing into the operator's HOME.

## Optional Codex setup acceptance — 2026-10-15

Lead disposition: **ACCEPT** the bounded change making Codex optional for
setup, not removing Codex support. Base: `dd8f58d753b626273238ae71e17eff94a2ad1535`;
candidate is the current working-tree patch, identified by its SHA-256 in the
delivery. No Peer dispatch, push, deployment, daemon start, or real-HOME install.

Missing CLI (unless an offline catalog is supplied) or required shared
resources now skips Codex generation/runtime checks. Existing Codex runtime
bytes and permissions remain untouched on this route. All provider definitions
and launchers remain installed. Restoring prerequisites and reapplying resumes
generation; available invalid inputs still use the existing fail-closed path.

Evidence:

- Missing-Codex regression failed before the change at the required-command
  gate, then passed with an isolated PATH containing no `codex`.
- `python3 -m unittest discover -s tests -p test_setup.py -v -f`:
  62 tests passed, including no-Codex apply/reapply, runtime preservation,
  missing-resource recovery, Codex generation, rollback and launcher behavior.
- `python3 -m unittest discover -s tests -p test_model_alignment.py`:
  10 tests passed. `./scripts/verify --source`: `VERIFY_OK`.
- `bash -n scripts/verify scripts/doctor` and `python3 -m py_compile
  scripts/install-room tests/test_setup.py tests/test_model_alignment.py`: passed.
- The remaining `unittest discover -s tests -p <file>` runs passed:
  `test_container_interface.py` (5), `test_paseo_release.py` (11),
  `test_room_gc.py` (5), `test_run_procs.py` (19), and
  `test_worktree_guard.py` (22). All seven modules: **134 tests passed**.
- Disposable CLI smoke: actual `install`, `install --apply` twice,
  `scripts/verify`, and `scripts/doctor` all exited 0 without Codex or a Codex
  home. Used the existing local Paseo Git/npm fixtures with only the copied
  manifest pointed at that fixture; installer and verifier were not mocked.
  No `.codex` or `.codex-runtime` was created.

Limits and non-pass results: the initial full-suite run hit its 300-second
deadline and exposed an alignment fixture that needed the optional runtime's
prerequisites; the updated alignment suite passed. The remote real-Paseo
install was cancelled via SIGINT during preparation, not accepted as a build
pass. Standalone verification initially failed three lexical-path comparisons
with macOS `/var` versus `/private/var`; using the canonical temporary HOME
passed, without expanding this change into path normalization.
No live provider daemon or authenticated agent session was exercised.
Operators still install/authenticate their chosen runtime independently.

Smoke logs: temporary directory
`room-no-codex-co5xlcek` under the session's macOS temporary root; files
`apply.log`, `install.log`, `install-apply.log`,
`scripts-verify-canonical-home.log`, and `scripts-doctor-canonical-home.log`.

## Evidence matrix

| Boundary | Evidence | Status at handoff |
| --- | --- | --- |
| CORE-2 operating contract | [CORE-2](https://github.com/hoangnb24/codex-room-setup/issues/4) | Technically accepted; Human check deferred |
| CORE-3 public transaction | [CORE-3 handoff](https://github.com/hoangnb24/codex-room-setup/issues/5#issuecomment-5550376777) | Technically accepted; independent F1–F6 closeout passed |
| Role/provider source contract | `./scripts/verify --source` and unit tests | Passed in the writer workspace, clean clone, and container source check |
| Public installer composition | `make test` and `make test-container` | 49 tests and complete container acceptance passed |
| Live Paseo roles and tool inventory | `./install --verify` plus three smoke sessions | Pending the single Human review |

The final candidate is identified by the immutable branch/PR and issue proof
recorded by Lead. This file intentionally contains no self-referential commit
hash.

## Writer validation

The following checks were run in the candidate workspace with
`CODEX_ROOM_TOML_PYTHON=/opt/homebrew/bin/python3.12` set only in the shell:

```text
49 unit/interface tests: OK
python3 -m py_compile scripts/install-room: OK
all tracked shell entrypoints and container scripts: bash -n OK
./scripts/verify --source: VERIFY_OK
git diff --check: OK
```

The complete unit output is retained at
`/tmp/codex-room-core4-tests.log`; source verification output is at
`/tmp/codex-room-core4-source.log`. Lead's independent proof follows.

## Final clean-clone proof

On 2026-09-05, Lead tested implementation commit
`f9a56017e0622158b6791355af1dc4dc181ee7df` in a separate clean clone.
At the initial handoff, the only subsequent change was this evidence record. Independent CORE-4
review found no functional blocker; CORE-3's six transaction findings had
already passed their independent closeout.

```text
make test: 49 tests passed (114.647 seconds)
./scripts/verify --source: VERIFY_OK
Python compilation, shell syntax, git diff --check: passed
PUBLIC_PLAN_READ_ONLY_OK
PUBLIC_INSTALL_PASS fresh
PUBLIC_INSTALL_PASS repeated
PUBLIC_VERIFY_FIXTURE_OK live_inventory_is_fake
ROLE_INVENTORY ["codex-lead","codex-peer","codex-supervisor"]
MCP_RECIPIENTS ["codex-supervisor","codex-lead"]
CONTAINER_ACCEPTANCE_OK node=v22.16.0 python=3.11.2 paseo=8511089eaeb06cddd049b629562926822020de5c
```

The first `make test-container` attempt passed fresh installation but failed
with npm `ECONNRESET` during repeated-install preflight. An unchanged rerun
completed successfully. Both logs are retained; the failed attempt is not
counted as a full pass. Source verification also passed through a separate
read-only invocation inside the first container.

The composed test checks plan bytes/modes/links, fresh and repeated install,
operator and legacy/active JSONL/SQLite preservation, customized obsolete
files, final backup directory permissions, and installed/provider verification.
Regular managed/CLI backup permissions and intentional rollback failures are
covered by the transaction regressions. A supplementary read-only check during
the successful container's repeated-install phase found all 136,175 completed
regular backup files at mode `0600`; final directory modes are checked after
apply. This supplementary check is separate from the committed container test.

The coordination session retains `unit.log`, `source.log`, `container.log`,
`container-retry.log`, `container-source.log`, the backup-file permission result,
full generated instructions, and changed-path manifests. The final immutable
handoff and review status are recorded on
[CORE-4](https://github.com/hoangnb24/codex-room-setup/issues/6).

## Installation feedback: optional hooks

The operator's first installation attempt exposed an overly strict prerequisite:
`hooks.json` was required even when no hooks were configured. The installer and
runtime generator now skip an absent hooks file, share an existing one, and
reject an explicitly dangling hooks symlink. They do not create operator files.
Other required resources retain their previous checks.

Three focused regressions passed, covering public plan/apply/repeat and direct
generation without hooks, hooks added later, dangling hooks, and required-resource
or catalog failures. The read-only plan also passed against the reporting
operator's existing home without creating `hooks.json`. The full-suite result
and correction commit are recorded on PR #8. The container evidence above
belongs to the original implementation; it was not rerun for this correction.

## Installation feedback: native-agent v2 table

The operator deliberately enabled native agents in the personal Codex home;
the Room contract still requires all three role runtimes to disable them.
The generator previously added a v2 boolean alongside the operator's v2 table,
producing invalid TOML. It now preserves the table and sets its `enabled` field
to `false`, or emits boolean `false` for scalar configurations. Verification
recognizes both disabled forms and exposes parser errors instead of hiding them
behind the generic policy failure.

Focused tests parse all three generated runtimes through repeated public apply,
prove the operator config remains unchanged, and check verification of disabled,
enabled and malformed v2 settings. Generation from the reporting operator's
actual base in a disposable stage also produced three valid disabled configs
without changing the base. Correction hashes and full-suite results are tracked
on PR #8; the original container evidence was not rerun for this correction.

## Consolidated Human runbook

Before merge, select the candidate branch explicitly: README's default clone
still selects `main` until this PR is merged.

```bash
git clone --branch core-minimum https://github.com/hoangnb24/codex-room-setup.git
cd codex-room-setup
git rev-parse HEAD   # compare with the final commit recorded on the PR/CORE-4
```

Use this clean clone at the recorded candidate, a disposable operator home, and an
authenticated Codex/Paseo environment prepared by the operator. Follow only
the README for installation, then record commands and observations on
[CORE-4](https://github.com/hoangnb24/codex-room-setup/issues/6):

1. Run the default plan and confirm the home tree is unchanged. Apply twice,
   start Paseo, and run live verification.
2. Inspect the live provider inventory: exactly Supervisor, Lead, and Peer;
   confirm MCP is present only for Supervisor and Lead. Launch one real smoke
   session per role and confirm identity and instructions.
3. Read all generated role instructions. Observe Lead delegate one bounded
   writable task and explicitly accept or reject the returned candidate. Inspect
   the live Peer tool inventory and observe a fresh read-only Peer review.
4. Repeat the install and upgrade from a five-role fixture. Confirm active
   sessions, SQLite state, operator files, and customized obsolete files remain
   unchanged. Inspect owner-only replacement backups.
5. Trigger a controlled preflight or verification failure and confirm the
   previous managed installation remains byte-for-byte unchanged.
6. Post the observed commands and results on CORE-4, set Project `Human
   verification` to `Verified`, and close the child issue only after the Epic
   review is complete.

Live role identity, actual tool inventory, bounded write acceptance, and the
final Project field remain explicitly pending. The fake provider inventory
exercises the verification parser. A separate real daemon smoke exercises
startup and provider RPC, without proving Codex authentication, MCP calls, or
real sessions.

## Paseo build correction

The operator's successful apply exposed a missing runtime build: the CLI
launcher existed, but `packages/cli/dist/index.js` did not. Dependency
installation alone did not produce the server and CLI bundles. Both preflight
and publication now run the audited fork's `build:server:clean`, require the
CLI bundle and daemon runner, and execute CLI help before reporting readiness.
Installed verification also checks these outputs and CLI execution.

A disposable copy of the operator's audited checkout passed the clean build
and a real daemon/provider RPC smoke test on Node 24.9.0. The operator checkout
and Codex configuration were not modified by that test. Container acceptance
now includes the same real daemon smoke after repeated public installation,
using a temporary home and loopback port with relay and web UI disabled.
This smoke tests executable runtime startup; authenticated role sessions and
actual MCP tool inventory remain part of the Human review.

Validation for this correction: 54 tests passed (138.85 seconds), source
verification passed, and independent code review passed. Full container
acceptance passed with Node 22.16.0/Python 3.11.2, including fresh/repeated apply,
preservation checks, and `PASEO_DAEMON_SMOKE_OK real_cli_and_provider_rpc`.
The initial uncached container run was stopped during a slow Git download;
the passing run mounted the same audited Git objects read-only through
`GIT_ALTERNATE_OBJECT_DIRECTORIES`. Remote pin checks and all npm/build steps
still ran. Its log is `/tmp/paseo-build-container-cached.log`; macOS build and
smoke logs are under `/tmp/paseo-build-acceptance.NGT4UM/`.

## Boundaries and deferred work

This release does not add a collector, evaluator, benchmark CLI, scoring rules,
workflow state, leases, gates, or another compatibility layer. Evaluation is a
separate future Epic with its own schema, collector, scoring, and report
interface. Git history retains removed experimental design material.

The final container proof does not cover Paseo Desktop, GUI behavior, macOS
signing or TCC, application restart behavior, or power-loss durability. Those
observations belong to the operator's macOS runbook and future release work.

## 2026-09-18 Workspace policy alignment (source only)

Lead decision: ACCEPT the bounded source-policy change. Human approved
parallel writable Peers with verified, accepted inputs and separate ownership,
sequencing shared-file/interface changes. Lead/Peer overlays also now specify
session resumption, updating existing task descriptions and criteria after
decisions, and reproducible handoff evidence. The reference protocol,
operations guide, and policy checks are aligned; Human authority and Lead
acceptance remain unchanged.

Exact inspected SHA-256 candidates:

| Source | SHA-256 |
| --- | --- |
| `home/.config/codex-room/overlays/lead.config.toml` | `29d45fe1a27b6b492c099dd6447eba9522198efed08e09d37d3c4c99cb530390` |
| `home/.config/codex-room/overlays/peer.config.toml` | `f526e34ab6880321e77d8c5396051b2f6b98104e235701577dc11028ad432fb9` |
| `home/.config/codex-room/workflow/WORKSPACE_PROTOCOL.md` | `93d5f7a657c3c7b8332908e8bd466f5f22ef906d464b36c3ab16c7aecf38788c` |

A fresh read-only Peer (`35991217-848e-4659-bfd7-ca92f42c8b91`) verified
these fingerprints and found no source-policy contradictions. Lead inspected
the same candidates. Source verification returned `VERIFY_OK`; seven focused
policy/runtime-generation tests passed, including exact overlay-instruction
presence in generated configs. Python compilation, verifier shell syntax, and
`git diff --check` passed.

Full-suite reproduction on macOS uses the existing uv-managed Python 3.12:

```bash
env PATH="$HOME/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  CODEX_ROOM_TOML_PYTHON="$HOME/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12" make test
```

Result: 64 tests, 63 passed, one failed (`test_role_defaults_are_aligned`):
the existing Paseo Lead/Peer defaults select `gpt-6-astra` while overlays select
`gpt-5.6-sol`. This mismatch predates this change; model selection was not in
scope and remains unresolved. Earlier Python 3.9 runs failed with missing
`tomllib` and temporary-HOME side effects; one retry also referenced an absent
Homebrew Python. An interrupted run has no accepted result. Those attempts
are not passes; the completed Python 3.12 run is the evidence above.

The source-policy outcome is accepted, not the full installation/release.
No install, new-policy sync, commit, push, or daemon restart was performed.
Real concurrent-agent behavior remains untested. Next work is to reconcile
the model-default mismatch before publishing the current combined worktree;
the updated overlays are the downstream inputs for that installation.

### Targeted overlay sync

Human subsequently authorized syncing only this overlay change. Installed
Lead/Peer overlays were backed up under
`~/.config/codex-room/overlay-backup.dTV21R/`, updated to the accepted source,
and regenerated with `./scripts/sync-all lead peer` (`SYNC_COMPLETE`).
TOML parsing confirmed installed overlay bytes match source and both generated
runtime instruction blocks and role settings match the overlays. ACCEPT this
targeted sync; no full install, provider/model selection change, Supervisor
sync, or Paseo restart was performed. The installed workflow reference was
not updated. Existing sessions are not claimed to have reloaded instructions;
use fresh Lead/Peer sessions. Concurrent behavior remains untested and the
separate model-default mismatch remains unresolved.
